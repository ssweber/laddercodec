"""Split coverage main.csv into individual rung CSVs for clicknick-rung guided.

Usage:
    uv run devtools/split_coverage_csv.py

Reads:  tests/fixtures/coverage/main.csv
Writes: tests/fixtures/coverage/golden/<rung_id>.csv

Each rung comment (e.g. ``cond__no``, ``out__tag``) becomes the filename.
The --folder mode saves .bin alongside each CSV, producing cond__no.bin etc.
which test_coverage.py picks up automatically.
"""

import csv
from pathlib import Path

SRC = Path("tests/fixtures/coverage/main.csv")
DST = Path("tests/fixtures/coverage/golden")


def main():
    with open(SRC, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        all_rows = list(reader)

    # Split into rungs: each rung starts with comment row(s) then an R row.
    rungs: list[tuple[str, list[list[str]]]] = []
    pending_comments: list[list[str]] = []
    current_rows: list[list[str]] = []
    current_id: str = ""

    for row in all_rows:
        marker = row[0] if row else ""
        if marker == "#":
            if current_rows:
                rungs.append((current_id, pending_comments + current_rows))
                pending_comments = []
                current_rows = []
            pending_comments.append(row)
            # Extract rung ID from comment text.
            current_id = row[1].strip() if len(row) > 1 else ""
        elif marker == "R":
            if current_rows:
                rungs.append((current_id, pending_comments + current_rows))
                pending_comments = []
            current_rows = [row]
        else:
            current_rows.append(row)

    if current_rows:
        rungs.append((current_id, pending_comments + current_rows))

    DST.mkdir(parents=True, exist_ok=True)

    for rung_id, rows in rungs:
        out_path = DST / f"{rung_id}.csv"
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)
        print(f"  {out_path.name}  ({len([r for r in rows if r[0] != '#'])} data rows)  {rung_id}")

    print(f"\nWrote {len(rungs)} CSVs to {DST}/")
    print(f"\nNext: clicknick-rung guided {DST}")


if __name__ == "__main__":
    main()
