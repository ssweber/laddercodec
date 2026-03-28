"""Generate golden .bin fixtures from golden .csv files.

Reads each .csv in the golden directory, runs encode_rung(), and writes
the result as a .bin file with the same basename.

Usage: uv run python devtools/generate_golden.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from golden_io import GOLDEN_DIR, read_golden_csv

from laddercodec.encode import encode_rung


def main() -> None:
    csv_files = sorted(GOLDEN_DIR.glob("*.csv"))
    if not csv_files:
        print(f"No CSV files found in {GOLDEN_DIR}")
        print("Run: uv run python devtools/create_golden_csvs.py")
        sys.exit(1)

    print(f"Generating .bin fixtures from {len(csv_files)} CSV files:")
    for csv_path in csv_files:
        logical_rows, condition_rows, af_tokens, comment = read_golden_csv(csv_path)
        result = encode_rung(logical_rows, condition_rows, af_tokens, comment=comment)
        bin_path = csv_path.with_suffix(".bin")
        bin_path.write_bytes(result)
        print(f"  {csv_path.name} -> {bin_path.name} ({len(result):,} bytes)")

    print(f"\nDone. {len(csv_files)} fixtures generated.")


if __name__ == "__main__":
    main()
