"""Inspect SC-SCR temp file format and compare to clipboard binary.

Annotates the byte stream with known structure markers.
"""

from __future__ import annotations

import struct
import sys


def hexdump(data: bytes, base: int = 0, cols: int = 16) -> str:
    lines = []
    for i in range(0, len(data), cols):
        chunk = data[i : i + cols]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
        lines.append(f"  {base + i:04x}: {hex_part:<{cols * 3}}  {ascii_part}")
    return "\n".join(lines)


def read_utf16le(data: bytes, offset: int, byte_count: int) -> str:
    raw = data[offset : offset + byte_count]
    if len(raw) % 2 == 1:
        raw = raw + b"\x00"
    return raw.decode("utf-16-le").rstrip("\x00")


def annotated_dump(path: str) -> None:
    """Dump the SCR file with byte-level annotations."""
    with open(path, "rb") as f:
        data = f.read()

    print(f"File: {path}")
    print(f"Size: {len(data)} ({len(data):#x})")
    print()

    # --- File header ---
    print(f"[0x0000] Magic: {data[:8]!r}")
    print(f"[0x0008] u16le: {struct.unpack_from('<H', data, 8)[0]:#x}")
    print(f"[0x000A] u16le: {struct.unpack_from('<H', data, 0xA)[0]:#x} (version?)")
    print(f"[0x000C] zeros: {data[0xC:0x40].hex()}")
    print()

    # --- Program info ---
    prog_idx = struct.unpack_from("<H", data, 0x40)[0]
    name_len = data[0x42]
    name = read_utf16le(data, 0x43, name_len)
    cursor = 0x43 + name_len
    print(f"[0x0040] Program index: {prog_idx}")
    print(f"[0x0042] Name len: {name_len} ({name_len:#x})")
    print(f"[0x0043] Name: {name!r}")
    print(f"         next byte at {cursor:#x}")
    print()

    # --- Dump rest in 16-byte lines with annotations ---
    print("=" * 72)
    print("ANNOTATED DUMP from cursor")
    print("=" * 72)

    # Rather than trying to parse, let's just dump and annotate known patterns
    pos = cursor
    while pos < len(data):
        remaining = len(data) - pos

        # RTF body detection
        if remaining >= 6 and data[pos : pos + 6] == b"{\\rtf1":
            # Backtrack to find length
            if pos >= 4:
                rtf_len = struct.unpack_from("<I", data, pos - 4)[0]
            else:
                rtf_len = 0
            # Find the actual end
            end_marker = data.find(b"\\par }", pos)
            if end_marker >= 0:
                actual_end = end_marker + len(b"\\par }\r\n")
                # Extract comment text
                body = data[pos:actual_end].decode("cp1252", errors="replace")
                fs_idx = body.find("\\fs20 ")
                par_idx = body.find("\r\n\\par ")
                if par_idx == -1:
                    par_idx = body.find("\\par }")
                text = body[fs_idx + 6 : par_idx] if fs_idx >= 0 and par_idx >= 0 else "?"
                print(
                    f"\n[{pos:#06x}] *** RTF COMMENT (declared_len={rtf_len}, actual={actual_end - pos}) ***"
                )
                print(f"         Text: {text!r}")
                pos = actual_end
                # Skip trailing null(s)
                while pos < len(data) and data[pos] == 0x00:
                    pos += 1
                continue

        # Length-prefixed UTF-16LE class name followed by InstructionType
        if remaining >= 10:
            str_len = data[pos]
            if 5 <= str_len <= 60 and pos + 1 + str_len + 2 <= len(data):
                try:
                    text = read_utf16le(data, pos + 1, str_len)
                    type_offset = pos + 1 + str_len
                    marker = struct.unpack_from("<H", data, type_offset)[0]
                    if (
                        text
                        and text[0].isupper()
                        and text.isascii()
                        and all(c.isalnum() for c in text)
                        and 0x2700 <= marker <= 0x2800
                    ):
                        # Found instruction blob!
                        # Determine blob extent: scan forward for next class name or rung marker
                        blob_start = pos
                        scan = type_offset + 2
                        blob_end = None
                        while scan < len(data) - 10:
                            # Check for next class name
                            sl = data[scan]
                            if 5 <= sl <= 60 and scan + 1 + sl + 2 <= len(data):
                                try:
                                    t2 = read_utf16le(data, scan + 1, sl)
                                    m2 = struct.unpack_from("<H", data, scan + 1 + sl)[0]
                                    if (
                                        t2
                                        and t2[0].isupper()
                                        and t2.isascii()
                                        and all(c.isalnum() for c in t2)
                                        and 0x2700 <= m2 <= 0x2800
                                    ):
                                        blob_end = scan
                                        break
                                except (UnicodeDecodeError, ValueError):
                                    pass
                            # Check for RTF
                            if data[scan : scan + 6] == b"{\\rtf1":
                                # Back up past the RTF length field
                                blob_end = scan - 4 if scan >= 4 else scan
                                break
                            # Check for row header marker: XX 00 03 00 00 01 20 00
                            if (
                                scan + 8 <= len(data)
                                and data[scan + 2 : scan + 8] == b"\x03\x00\x00\x01\x20\x00"
                            ):
                                blob_end = scan
                                break
                            scan += 1

                        if blob_end is None:
                            blob_end = min(pos + 80, len(data))

                        blob_bytes = data[blob_start:blob_end]
                        print(f"\n[{pos:#06x}] *** INSTRUCTION: {text} (type={marker:#06x}) ***")
                        print(f"         Blob size: {len(blob_bytes)} bytes")
                        print(hexdump(blob_bytes, pos))

                        # Parse tagged fields after type marker
                        after_type = type_offset + 2
                        if after_type + 10 <= len(data):
                            print(
                                f"  After type ({after_type:#06x}): {data[after_type : after_type + 16].hex(' ')}"
                            )

                        pos = blob_end
                        continue
                except (UnicodeDecodeError, ValueError):
                    pass

        # Row header detection: XX 00 03 00 00 01 20 00
        if remaining >= 8 and data[pos + 2 : pos + 8] == b"\x03\x00\x00\x01\x20\x00":
            row_word = struct.unpack_from("<H", data, pos)[0]
            print(f"\n[{pos:#06x}] *** ROW HEADER (row_word={row_word:#x}) ***")
            print(f"  {hexdump(data[pos : pos + 8], pos)}")
            pos += 8

            # Column flag entries: 32 x (flag, col_idx)
            if pos + 64 <= len(data):
                col_flags = []
                for i in range(32):
                    flag = data[pos + i * 2]
                    col_idx = data[pos + i * 2 + 1]
                    col_flags.append((flag, col_idx))
                non_wire = [(f, c) for f, c in col_flags if f != 0x01]
                print(
                    f"  Column flags (32 entries): all=0x01 except: {non_wire if non_wire else 'none (all wired)'}"
                )
                pos += 64

            # Trailing COLS_PER_ROW marker
            if pos + 2 <= len(data):
                trail = struct.unpack_from("<H", data, pos)[0]
                print(f"  Trailing u16le: {trail:#x}")
                pos += 2
            continue

        # Column type block: many 'A' (0x41 0x00) entries
        if remaining >= 4 and data[pos] == 0x41 and data[pos + 1] == 0x00:
            count = 0
            while (
                pos + count * 2 + 1 < len(data)
                and data[pos + count * 2] == 0x41
                and data[pos + count * 2 + 1] == 0x00
            ):
                count += 1
            if count >= 10:
                print(f"\n[{pos:#06x}] Column type block: {count} x 'A' (UTF-16LE)")
                pos += count * 2
                continue

        # Zero block
        if remaining >= 16 and data[pos : pos + 16] == b"\x00" * 16:
            zero_start = pos
            while pos < len(data) and data[pos] == 0x00:
                pos += 1
            print(f"\n[{zero_start:#06x}] ZERO BLOCK ({pos - zero_start} bytes)")
            continue

        # Default: dump raw u16le
        if remaining >= 2:
            val = struct.unpack_from("<H", data, pos)[0]
            print(f"  [{pos:#06x}] u16le={val:#06x} ({val})  raw={data[pos : pos + 2].hex(' ')}")
            pos += 2
        else:
            print(f"  [{pos:#06x}] byte={data[pos]:#04x}")
            pos += 1


if __name__ == "__main__":
    path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else r"C:\Users\Sam\AppData\Local\Temp\CLICK (009C0C64)\Scr2.tmp"
    )
    annotated_dump(path)
