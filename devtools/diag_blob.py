"""Diagnostic: show what follows every instruction section to find the rung boundary pattern."""

from __future__ import annotations

import struct
from pathlib import Path


def read_utf16le(data: bytes, offset: int, byte_count: int) -> str:
    raw = data[offset : offset + byte_count]
    if len(raw) % 2 == 1:
        raw = raw + b"\x00"
    return raw.decode("utf-16-le").rstrip("\x00")


def parse_blob(data: bytes, pos: int) -> tuple[str, int, int] | None:
    """Returns (class_name, end_offset, next_pos) or None."""
    if pos >= len(data) - 20:
        return None
    sl = data[pos]
    if not (3 <= sl <= 60 and pos + 1 + sl + 2 <= len(data)):
        return None
    try:
        text = read_utf16le(data, pos + 1, sl)
        type_off = pos + 1 + sl
        marker = struct.unpack_from("<H", data, type_off)[0]
        if not (text and text[0].isupper() and text.isascii() and all(c.isalnum() for c in text)):
            return None
        if not (0x2700 <= marker <= 0x2800):
            return None
        after_type = type_off + 2
        if after_type + 12 > len(data):
            return None
        m1 = data[after_type + 6]
        if not (1 <= m1 <= 8):
            return None
        eo_pos = after_type + 7 + m1
        if eo_pos + 4 > len(data):
            return None
        end_offset = struct.unpack_from("<I", data, eo_pos)[0]
        if not (pos < end_offset < len(data)):
            return None
        return text, end_offset, end_offset + 2
    except (UnicodeDecodeError, ValueError, struct.error):
        return None


def main() -> None:
    scr = Path(r"C:\Users\Sam\AppData\Local\Temp\CLICK (008B0E8C)\Scr1.tmp").read_bytes()

    # Find all valid sections
    sections = []
    i = 0x100
    while i < len(scr) - 5:
        count = struct.unpack_from("<H", scr, i)[0]
        if 1 <= count <= 20 and scr[i + 2 : i + 6] == b"\x90\x00\x00\x00":
            cursor = i + 6
            ok = True
            for _ in range(count):
                blob = parse_blob(scr, cursor + 8)
                if not blob:
                    blob = parse_blob(scr, cursor + 9)
                if not blob:
                    ok = False
                    break
                cursor = blob[2]
            if ok:
                sections.append((i, count, cursor))
                i = cursor
                continue
        i += 1

    print(f"Found {len(sections)} sections\n")

    # For each section, show the bytes at end_offset and the 16 bytes after sec_end
    for idx, (sec_off, count, sec_end) in enumerate(sections[:20]):
        # Get last blob's end_offset
        cursor = sec_off + 6
        last_eo = 0
        for _ in range(count):
            blob = parse_blob(scr, cursor + 8)
            if not blob:
                blob = parse_blob(scr, cursor + 9)
            if blob:
                last_eo = blob[1]
                cursor = blob[2]

        print(
            f"Section {idx}: {sec_off:#06x} count={count} sec_end={sec_end:#06x} last_eo={last_eo:#06x}"
        )
        print(f"  Bytes at last_eo:  {scr[last_eo : last_eo + 2].hex(' ')}")
        print(f"  After sec_end ({sec_end:#06x}): {scr[sec_end : sec_end + 16].hex(' ')}")

        # Look for RTF signature
        for delta in range(0, 30):
            if scr[sec_end + delta : sec_end + delta + 2] == b"{\\":
                rtf_off = sec_end + delta
                prefix = scr[sec_end:rtf_off].hex(" ")
                print(f"  RTF at {rtf_off:#06x} (delta={delta}), prefix: {prefix}")
                break

        # Look for row header
        for delta in range(0, 200):
            pos = sec_end + delta
            if pos + 8 <= len(scr) and scr[pos + 2 : pos + 8] == b"\x03\x00\x00\x01\x20\x00":
                rh_prefix = scr[sec_end:pos].hex(" ")
                row_word = struct.unpack_from("<H", scr, pos)[0]
                print(
                    f"  Row header at {pos:#06x} (delta={delta}) rows={row_word - 1}, prefix: {rh_prefix[:80]}"
                )
                break

        print()


if __name__ == "__main__":
    main()
