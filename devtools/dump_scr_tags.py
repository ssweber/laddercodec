"""Print the tagged fields of each instruction in each rung of a CLICK .scr file."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from devtools.walk_scr import find_valid_sections, parse_header
from laddercodec.decode_program import _parse_blob, _parse_scr_tags


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
            blob = _parse_blob(data, cursor + 8)
            if not blob:
                break
            row = data[cursor]
            col = data[cursor + 1]
            blob_start = cursor + 8
            cls, typ, end_off, part_rows = blob
            m1 = len(part_rows)
            next_pos = end_off + 2 + data[end_off]  # the byte at end_off is a trailer length

            _cls, _typ, tags, v_u16, v_str = _parse_scr_tags(data, blob_start, end_off, m1)

            col_name = (
                chr(ord("A") + col)
                if col < 26
                else (f"A{chr(ord('A') + col - 26)}" if col < 31 else "AF")
            )
            tag_str = ", ".join(f"{t:#06x}={v!r}" for t, v in tags.items())
            u16_str = ", ".join(f"{t:#06x}={v!r}" for t, v in v_u16.items())
            str_str = ", ".join(f"{t:#06x}={v!r}" for t, v in v_str.items())
            print(
                f"  [{ii}] r{row} {col_name}: {cls} type={typ:#06x} m1={m1} tags=[{tag_str}]"
                f" variant_u16=[{u16_str}] variant_string=[{str_str}]"
            )
            cursor = next_pos


if __name__ == "__main__":
    main()
