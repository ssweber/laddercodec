"""Validate SCR captures: decode clipboard binary, write CSV, diff against reference."""

from __future__ import annotations

import sys
from pathlib import Path

from laddercodec import decode, write_csv


def main() -> None:
    bin_path = Path(sys.argv[1])
    csv_path = Path(sys.argv[2])

    data = bin_path.read_bytes()
    result = decode(data)

    if isinstance(result, list):
        rungs = result
    else:
        rungs = [result]

    print(f"Decoded {len(rungs)} rungs from {bin_path.name}")
    for i, r in enumerate(rungs):
        cmt = r.comment[:40] if r.comment else "(none)"
        print(f"  Rung {i}: {r.logical_rows} rows, comment={cmt!r}")

    # Write decoded CSV
    out_path = bin_path.with_suffix(".decoded.csv")
    write_csv(str(out_path), rungs)
    print(f"\nWrote decoded CSV to {out_path}")

    # Compare with reference
    ref_lines = csv_path.read_text().splitlines()
    dec_lines = out_path.read_text().splitlines()

    print(f"\nReference: {len(ref_lines)} lines")
    print(f"Decoded:   {len(dec_lines)} lines")

    diffs = 0
    max_lines = max(len(ref_lines), len(dec_lines))
    for i in range(max_lines):
        ref = ref_lines[i] if i < len(ref_lines) else "<missing>"
        dec = dec_lines[i] if i < len(dec_lines) else "<missing>"
        if ref != dec:
            if diffs < 20:
                print(f"\n  Line {i + 1} differs:")
                print(f"    REF: {ref[:120]}")
                print(f"    DEC: {dec[:120]}")
            diffs += 1

    if diffs == 0:
        print("\nPERFECT MATCH!")
    else:
        print(f"\n{diffs} lines differ")


if __name__ == "__main__":
    main()
