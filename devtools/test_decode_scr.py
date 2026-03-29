"""Compare decode_program() output against decode() for or_topology."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from laddercodec import Rung, decode
from laddercodec.decode_program import decode_program


def token_to_str(tok) -> str:
    """Convert a condition or AF token to a string for comparison."""
    if isinstance(tok, str):
        return tok
    if hasattr(tok, "to_csv"):
        return tok.to_csv()
    return repr(tok)


def rung_to_lines(r: Rung) -> list[str]:
    """Convert a Rung to comparable text lines."""
    lines = []
    for row_idx in range(r.logical_rows):
        conds = [token_to_str(t) for t in r.conditions[row_idx]]
        af = token_to_str(r.instructions[row_idx])
        lines.append(",".join(conds) + "|" + af)
    return lines


def main() -> None:
    scr_path = (
        sys.argv[1]
        if len(sys.argv) > 1
        else r"C:\Users\Sam\AppData\Local\Temp\CLICK (008B0E8C)\Scr1.tmp"
    )
    clip_path = (
        sys.argv[2]
        if len(sys.argv) > 2
        else r"C:\Users\Sam\Documents\GitHub\clicknick\or_topology.bin"
    )

    scr_data = Path(scr_path).read_bytes()
    clip_data = Path(clip_path).read_bytes()

    clip_result = decode(clip_data)
    clip_rungs = cast(list[Rung], clip_result) if isinstance(clip_result, list) else [clip_result]

    program = decode_program(scr_data)
    scr_rungs = program.rungs

    print(f"CLIP rungs: {len(clip_rungs)}")
    print(f"SCR  rungs: {len(scr_rungs)} (program: {program.name!r}, idx={program.prog_idx})")

    all_match = True
    if len(clip_rungs) != len(scr_rungs):
        all_match = False
        print(f"Rung count mismatch: clip={len(clip_rungs)} scr={len(scr_rungs)}")

    for i in range(min(len(clip_rungs), len(scr_rungs))):
        cr = clip_rungs[i]
        sr = scr_rungs[i]

        # Compare via token output
        clip_csv = rung_to_lines(cr)
        scr_csv = rung_to_lines(sr)

        match = clip_csv == scr_csv
        if not match:
            all_match = False

        status = "OK" if match else "MISMATCH"
        print(f"\nRung {i}: {status} (rows: clip={cr.logical_rows} scr={sr.logical_rows})")

        if not match:
            # Show diffs
            for j, (cl, sl) in enumerate(zip(clip_csv, scr_csv, strict=False)):
                if cl != sl:
                    print(f"  Line {j}:")
                    print(f"    CLIP: {cl}")
                    print(f"    SCR:  {sl}")
            if len(clip_csv) != len(scr_csv):
                print(f"  Line count: clip={len(clip_csv)} scr={len(scr_csv)}")

    print(f"\n{'=' * 40}")
    print(f"Overall: {'ALL MATCH' if all_match else 'MISMATCHES FOUND'}")


if __name__ == "__main__":
    main()
