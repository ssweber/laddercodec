"""Combine the data rows of randomly chosen coverage golden CSVs into one rung.

Pick N CSV files at random from tests/fixtures/coverage/golden and put all
their data rows, in order, into one rung. Write that rung to
devtools/combined.csv, encode it, and write the result to
devtools/combined.bin. The first data row gets the ``R`` marker. Every
other row gets an empty marker, so it continues the same rung. The script
drops comment rows.

Usage::

    uv run devtools/combine_coverage.py          # 4 random fixtures
    uv run devtools/combine_coverage.py -n 3     # 3 random fixtures
    uv run devtools/combine_coverage.py -n 6     # 6 random fixtures
"""

import argparse
import csv
import random
import sys
from io import StringIO
from pathlib import Path

from laddercodec import encode, read_csv
from laddercodec.csv.contract import CSV_HEADER

COVERAGE_DIR = Path("tests/fixtures/coverage/golden")
OUT_CSV = Path("devtools/combined.csv")
OUT_BIN = Path("devtools/combined.bin")


def collect_data_rows(csv_path: Path) -> list[list[str]]:
    """Return the data rows of a coverage CSV. Skip the header, empty rows and comment rows."""
    rows = []
    with csv_path.open(newline="") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if not row or row[0].strip() == "#":
                continue
            rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Combine coverage CSVs")
    parser.add_argument("-n", type=int, default=4, help="number of fixtures (default: 4)")
    parser.add_argument("--seed", type=int, default=None, help="random seed")
    args = parser.parse_args()

    csvs = sorted(COVERAGE_DIR.glob("*.csv"))
    if not csvs:
        print("No coverage CSVs found", file=sys.stderr)
        sys.exit(1)

    rng = random.Random(args.seed)
    picked = rng.sample(csvs, min(args.n, len(csvs)))

    print(f"Combining {len(picked)} fixtures:")
    all_rows: list[list[str]] = []
    for p in picked:
        print(f"  {p.stem}")
        all_rows.extend(collect_data_rows(p))

    if not all_rows:
        print("No data rows found", file=sys.stderr)
        sys.exit(1)

    all_rows[0][0] = "R"
    for row in all_rows[1:]:
        row[0] = ""

    # Write combined CSV
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADER)
    writer.writerows(all_rows)
    OUT_CSV.write_text(buf.getvalue())
    print(f"\nWrote {OUT_CSV} ({len(all_rows)} data rows)")

    # Encode to .bin
    rung = read_csv(OUT_CSV)
    data = encode(rung)
    OUT_BIN.write_bytes(data)
    print(f"Wrote {OUT_BIN} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
