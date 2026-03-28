"""Generate golden .bin fixtures from golden .csv files.

Reads each .csv in the golden directory, encodes it, and writes
the result as a .bin file with the same basename.

Single-rung CSVs (one R marker) use encode_rung().
Multi-rung CSVs (multiple R markers, named mr-*) use encode_multi_rung().

Usage: uv run python devtools/generate_golden.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from golden_io import GOLDEN_DIR, is_multi_rung_csv, read_golden_csv, read_multi_rung_golden_csv

from laddercodec import encode_multi_rung
from laddercodec.encode import encode_rung


def main() -> None:
    csv_files = sorted(GOLDEN_DIR.glob("*.csv"))
    if not csv_files:
        print(f"No CSV files found in {GOLDEN_DIR}")
        print("Run: uv run python devtools/create_golden_csvs.py")
        sys.exit(1)

    print(f"Generating .bin fixtures from {len(csv_files)} CSV files:")
    for csv_path in csv_files:
        if is_multi_rung_csv(csv_path):
            rung_items = read_multi_rung_golden_csv(csv_path)
            result = encode_multi_rung(
                [(lr, cr, af) for lr, cr, af, _ in rung_items],
                comments=[cmt for _, _, _, cmt in rung_items],
            )
        else:
            logical_rows, condition_rows, af_tokens, comment = read_golden_csv(csv_path)
            result = encode_rung(logical_rows, condition_rows, af_tokens, comment=comment)
        bin_path = csv_path.with_suffix(".bin")
        bin_path.write_bytes(result)
        print(f"  {csv_path.name} -> {bin_path.name} ({len(result):,} bytes)")

    print(f"\nDone. {len(csv_files)} fixtures generated.")


if __name__ == "__main__":
    main()
