"""Read/write golden canonical CSV files for encode_rung() testing.

Golden CSV format: 33-column canonical layout matching contract.CSV_HEADER.

    marker,A,B,C,...,AE,AF

Row types:
    #,comment text,,,,...,,     Comment (text in column A, rest blank)
    R,-,-,,,,...,,NOP           First rung row (marker = R)
    ,-,-,,,,...,,               Continuation rung row (marker = blank)
"""

from __future__ import annotations

import csv
from pathlib import Path

from laddercodec.csv.contract import CSV_HEADER

GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "ladder_captures" / "golden"
TOTAL_COLUMNS = len(CSV_HEADER)  # 33


def read_golden_csv(
    path: Path,
) -> tuple[int, list[list[str]], list[str], str | None]:
    """Read a golden CSV and return (logical_rows, condition_rows, af_tokens, comment).

    Returns the exact arguments needed for ``encode_rung()``.
    """
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        if tuple(header) != CSV_HEADER:
            raise ValueError(f"Bad header in {path.name}: expected {CSV_HEADER}")

        comment: str | None = None
        condition_rows: list[list[str]] = []
        af_tokens: list[str] = []

        for row in reader:
            marker = row[0]
            if marker == "#":
                # Comment row: just #,text (no column count requirement)
                comment = row[1] if len(row) > 1 else ""
                continue
            if len(row) != TOTAL_COLUMNS:
                raise ValueError(
                    f"Row has {len(row)} columns, expected {TOTAL_COLUMNS} in {path.name}"
                )
            if marker in ("R", ""):
                conditions = row[1:32]  # columns A..AE (indices 1-31)
                af = row[32]  # column AF (index 32)
                condition_rows.append(conditions)
                af_tokens.append(af)
            else:
                raise ValueError(f"Unknown marker {marker!r} in {path.name}")

    logical_rows = len(condition_rows)
    if logical_rows == 0:
        raise ValueError(f"No rung rows found in {path.name}")
    return logical_rows, condition_rows, af_tokens, comment


def write_golden_csv(
    path: Path,
    condition_rows: list[list[str]],
    af_tokens: list[str],
    comment: str | None = None,
) -> None:
    """Write a golden CSV file from encode_rung() arguments."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)

        if comment is not None:
            writer.writerow(["#", comment])

        for i, (conditions, af) in enumerate(zip(condition_rows, af_tokens, strict=True)):
            marker = "R" if i == 0 else ""
            row = [marker] + list(conditions) + [af]
            writer.writerow(row)
