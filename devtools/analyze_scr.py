"""Analyze SC-SCR temp file format by extracting rung boundaries and instruction blobs.

Uses the known CSV as ground truth to validate structural findings.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path


def read_utf16le(data: bytes, offset: int, byte_count: int) -> str:
    raw = data[offset : offset + byte_count]
    if len(raw) % 2 == 1:
        raw = raw + b"\x00"
    return raw.decode("utf-16-le").rstrip("\x00")


def find_row_headers(data: bytes, start: int = 0) -> list[int]:
    """Find all row header markers: XX 00 03 00 00 01 20 00."""
    results = []
    for i in range(start, len(data) - 7):
        if (
            data[i + 1] == 0x00
            and data[i + 2] == 0x03
            and data[i + 3] == 0x00
            and data[i + 4] == 0x00
            and data[i + 5] == 0x01
            and data[i + 6] == 0x20
            and data[i + 7] == 0x00
        ):
            results.append(i)
    return results


def find_instruction_sections(data: bytes, start: int = 0) -> list[tuple[int, int]]:
    """Find instruction section headers: [u16 count] [90 00] [00 00]."""
    results = []
    for i in range(start, len(data) - 5):
        count = struct.unpack_from("<H", data, i)[0]
        if (
            1 <= count <= 10
            and data[i + 2] == 0x90
            and data[i + 3] == 0x00
            and data[i + 4] == 0x00
            and data[i + 5] == 0x00
        ):
            results.append((i, count))
    return results


def find_instruction_blobs(data: bytes, start: int, end: int) -> list[dict]:
    """Find instruction blobs between start and end offsets."""
    blobs = []
    pos = start
    while pos < end - 10:
        str_len = data[pos]
        if 5 <= str_len <= 60 and pos + 1 + str_len + 2 <= end:
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
                    blobs.append(
                        {
                            "offset": pos,
                            "class_name": text,
                            "type": marker,
                            "type_offset": type_offset,
                        }
                    )
                    # Skip past the type marker to avoid re-finding
                    pos = type_offset + 2
                    continue
            except (UnicodeDecodeError, ValueError):
                pass
        pos += 1
    return blobs


def main() -> None:
    scr_path = Path(sys.argv[1])
    data = scr_path.read_bytes()

    print(f"File: {scr_path.name} ({len(data)} bytes)")

    # Parse header
    magic = data[:8]
    prog_idx = struct.unpack_from("<H", data, 0x40)[0]
    name_len = data[0x42]
    name = read_utf16le(data, 0x43, name_len)
    cursor = 0x43 + name_len

    print(f"Magic: {magic!r}")
    print(f"Program: {name!r} (index={prog_idx})")
    print(f"Header ends at: {cursor:#x}")

    # Bytes between header and first column-type block
    print(f"\nPost-header bytes: {data[cursor : cursor + 6].hex(' ')}")
    cols_per_row = struct.unpack_from("<H", data, cursor)[0]
    print(f"  Cols per row: {cols_per_row}")

    # Find row headers
    row_headers = find_row_headers(data, cursor)
    print(f"\nFound {len(row_headers)} row headers")

    # Find instruction sections
    instr_sections = find_instruction_sections(data, cursor)
    print(f"Found {len(instr_sections)} instruction sections")

    # Build rung map: each rung is a row header + instruction section
    # Row headers contain column flags; instruction sections have the blobs
    print(f"\n{'=' * 72}")
    print("RUNG MAP")
    print(f"{'=' * 72}")

    # Group row headers and instruction sections into rungs
    # Strategy: each rung has 1+ row headers (for multi-row rungs) followed by
    # an instruction section for each row.

    # Let's look at the relationship between row headers and instruction sections
    # For each row header, find the next instruction section
    for i, rh_off in enumerate(row_headers[:10]):  # First 10
        row_word = struct.unpack_from("<H", data, rh_off)[0]
        # Read column flags
        flags_start = rh_off + 8  # after the 8-byte header
        non_wire = []
        for c in range(32):
            flag = data[flags_start + c * 2]
            col_idx = data[flags_start + c * 2 + 1]
            if flag != 0x01:
                non_wire.append((col_idx, flag))

        # Find what's between this row header end and the next one
        rh_end = flags_start + 64 + 2  # 32 flags + trailing u16
        next_rh = row_headers[i + 1] if i + 1 < len(row_headers) else len(data)

        # Find instruction blobs in this span
        blobs = find_instruction_blobs(data, rh_end, next_rh)
        blob_names = [b["class_name"] for b in blobs]

        # Check for RTF between row header end and next row header
        rtf_offset = None
        span = data[rh_end:next_rh]
        rtf_idx = span.find(b"{\\rtf1")
        if rtf_idx >= 0:
            rtf_offset = rh_end + rtf_idx

        print(f"\n  Row header #{i} @ {rh_off:#06x}: row_word={row_word:#x}")
        print(f"    Non-wire cols: {non_wire if non_wire else 'all wired'}")
        print(f"    Instructions: {blob_names}")
        if rtf_offset:
            # Extract comment text
            body = data[rtf_offset : rtf_offset + 300].decode("cp1252", errors="replace")
            fs_idx = body.find("\\fs20 ")
            par_idx = body.find("\r\n\\par ")
            if par_idx == -1:
                par_idx = body.find("\\par }")
            text = body[fs_idx + 6 : par_idx] if fs_idx >= 0 and par_idx >= 0 else "?"
            print(f"    RTF comment: {text[:50]!r}")

    # Now show the column flag pattern for multi-row rungs
    print(f"\n{'=' * 72}")
    print("MULTI-ROW RUNG ANALYSIS")
    print(f"{'=' * 72}")

    # Find rows where col A has flag != 01 (potential multi-row pin rows)
    for i, rh_off in enumerate(row_headers):
        flags_start = rh_off + 8
        col_a_flag = data[flags_start]
        if col_a_flag != 0x01:
            row_word = struct.unpack_from("<H", data, rh_off)[0]
            flags = [(data[flags_start + c * 2], data[flags_start + c * 2 + 1]) for c in range(32)]
            non_zero_flags = [(c, f) for f, c in flags if f != 0x00]
            wire_flags = [(c, f) for f, c in flags if f == 0x01]
            print(f"\n  Row #{i} @ {rh_off:#06x}: row_word={row_word:#x}")
            print(f"    Col A flag: {col_a_flag:#x}")
            print(f"    Non-zero: {non_zero_flags[:10]}...")
            print(f"    Wire(01): {len(wire_flags)} cols")

    # Instruction section analysis
    print(f"\n{'=' * 72}")
    print("INSTRUCTION SECTION DETAILS")
    print(f"{'=' * 72}")

    for i, (off, count) in enumerate(instr_sections[:15]):
        print(f"\n  Section #{i} @ {off:#06x}: count={count}")
        # Dump the per-instruction headers
        pos = off + 6  # skip count(2) + marker(2) + 00 00(2)
        for j in range(count):
            if pos + 8 > len(data):
                break
            header = data[pos : pos + 8]
            flag = header[0]
            col_idx = header[1]
            col_name = (
                chr(ord("A") + col_idx)
                if col_idx < 26
                else f"A{chr(ord('A') + col_idx - 26)}"
                if col_idx < 31
                else "AF"
            )
            print(
                f"    Instr {j}: flag={flag:#x} col={col_name}({col_idx}) header={header.hex(' ')}"
            )
            # Find the next blob
            blob = find_instruction_blobs(data, pos + 8, pos + 200)
            if blob:
                b = blob[0]
                print(f"      -> {b['class_name']} (type={b['type']:#x}) @ {b['offset']:#x}")
                pos = b["type_offset"] + 2
                # Skip past blob data to next instruction header
                # Look for the next instruction header pattern or row header
                # The blob ends before the next flag+col pair
                while pos < len(data) - 2:
                    # Check if this could be an instruction header (flag=01, col=valid)
                    if data[pos] == 0x01 and 0 <= data[pos + 1] <= 31:
                        # Could be next instruction header - verify with 01 01 pattern
                        if pos + 4 <= len(data) and data[pos + 2] == 0x01 and data[pos + 3] == 0x01:
                            break
                    # Check for rung boundary (u16 rung_idx)
                    if pos + 6 <= len(data):
                        maybe_rtf_len = struct.unpack_from("<I", data, pos + 2)[0]
                        if maybe_rtf_len == 0 or (maybe_rtf_len > 50 and maybe_rtf_len < 2000):
                            # Could be rung boundary
                            pass
                    pos += 1
            else:
                pos += 8  # skip this header, no blob found


if __name__ == "__main__":
    main()
