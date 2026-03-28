"""Dump SCR tagged fields for each instruction in or_topology."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from devtools.walk_scr import find_valid_sections, parse_header
from laddercodec.decode_program import _parse_blob


def main() -> None:
    path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else r"C:\Users\Sam\AppData\Local\Temp\CLICK (008B0E8C)\Scr1.tmp"
    )
    data = Path(path).read_bytes()
    name, prog_idx, data_start = parse_header(data)
    sections = find_valid_sections(data, start=data_start)

    for si, (sec_off, count, _sec_end) in enumerate(sections):
        print(f"\nRung {si}:")
        cursor = sec_off + 6
        for ii in range(count):
            blob8 = _parse_blob(data, cursor + 8)
            blob9 = _parse_blob(data, cursor + 9)
            if blob8:
                row = data[cursor]
                col = data[cursor + 1]
                blob_start = cursor + 8
                cls, typ, end_off, next_pos, m1 = blob8
            elif blob9:
                row = data[cursor + 1]
                col = data[cursor + 2]
                blob_start = cursor + 9
                cls, typ, end_off, next_pos, m1 = blob9
            else:
                break

            # Parse tagged fields
            pos = blob_start
            sl = data[pos]
            pos += 1 + sl + 2  # skip class name + type
            pos += 6 + 1 + m1 + 4  # skip zeros + m1 + counting + end_offset

            tags = []
            while pos < end_off:
                if pos + 3 > len(data):
                    break
                tag = struct.unpack_from("<H", data, pos)[0]
                pos += 2
                str_len = data[pos]
                pos += 1
                val_raw = data[pos : pos + str_len]
                if len(val_raw) % 2 == 1:
                    val_raw += b"\x00"
                val = val_raw.decode("utf-16-le", errors="replace").rstrip("\x00")
                tags.append((tag, val))
                pos += str_len

            col_name = (
                chr(ord("A") + col)
                if col < 26
                else (f"A{chr(ord('A') + col - 26)}" if col < 31 else "AF")
            )
            tag_str = ", ".join(f"{t:#06x}={v!r}" for t, v in tags)
            print(f"  [{ii}] r{row} {col_name}: {cls} type={typ:#06x} m1={m1} tags=[{tag_str}]")
            cursor = next_pos


if __name__ == "__main__":
    main()
