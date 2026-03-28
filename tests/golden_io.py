"""Read/write golden canonical CSV files for encode_rung() testing.

Golden CSV format: 33-column canonical layout matching contract.CSV_HEADER.

    marker,A,B,C,...,AE,AF

Row types:
    #,comment text,,,,...,,     Comment line (multiple # rows join with \\n)
    R,-,-,,,,...,,NOP           First rung row (marker = R)
    ,-,-,,,,...,,               Continuation rung row (marker = blank)

Multi-line comments use one ``#`` row per line::

    #,First line
    #,Second line

Styled text uses markdown syntax in the comment text::

    #,**bold** and _italic_ and __underline__

Multi-rung CSVs use multiple ``R`` markers — each ``R`` starts a new rung.
Comments before an ``R`` belong to that rung::

    #,Comment for rung 0
    R,...
    R,...    <- rung 1 starts here
"""

from __future__ import annotations

import csv
from pathlib import Path

from laddercodec.csv.contract import CSV_HEADER

GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "ladder_captures" / "golden"
TOTAL_COLUMNS = len(CSV_HEADER)  # 33

# Type alias: (logical_rows, condition_rows, af_tokens, comment)
MultiRungItem = tuple[int, list[list[str]], list[str], str | None]


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

        comment_lines: list[str] = []
        condition_rows: list[list[str]] = []
        af_tokens: list[str] = []

        for row in reader:
            marker = row[0]
            if marker == "#":
                # One # row per comment line; multiple rows join with \n.
                comment_lines.append(row[1] if len(row) > 1 else "")
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
    comment = "\n".join(comment_lines) if comment_lines else None
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
            for line in comment.split("\n"):
                writer.writerow(["#", line])

        for i, (conditions, af) in enumerate(zip(condition_rows, af_tokens, strict=True)):
            marker = "R" if i == 0 else ""
            row = [marker] + list(conditions) + [af]
            writer.writerow(row)


# ---------------------------------------------------------------------------
# Multi-rung golden CSV helpers
# ---------------------------------------------------------------------------


def is_multi_rung_csv(path: Path) -> bool:
    """Return True if the CSV contains more than one rung (multiple R markers)."""
    count = 0
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if row and row[0] == "R":
                count += 1
                if count > 1:
                    return True
    return False


def read_multi_rung_golden_csv(path: Path) -> list[MultiRungItem]:
    """Read a multi-rung golden CSV. Each R marker starts a new rung.

    Returns list of (logical_rows, condition_rows, af_tokens, comment).
    Comments (# rows) before each R belong to that rung.
    """
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        if tuple(header) != CSV_HEADER:
            raise ValueError(f"Bad header in {path.name}: expected {CSV_HEADER}")

        rungs: list[MultiRungItem] = []
        pending_comment_lines: list[str] = []
        rung_comment_lines: list[str] = []
        current_conditions: list[list[str]] = []
        current_af: list[str] = []
        in_rung = False

        for row in reader:
            marker = row[0]
            if marker == "#":
                pending_comment_lines.append(row[1] if len(row) > 1 else "")
                continue
            if len(row) != TOTAL_COLUMNS:
                raise ValueError(
                    f"Row has {len(row)} columns, expected {TOTAL_COLUMNS} in {path.name}"
                )
            if marker == "R":
                if in_rung:
                    comment = "\n".join(rung_comment_lines) if rung_comment_lines else None
                    rungs.append((len(current_conditions), current_conditions, current_af, comment))
                rung_comment_lines = pending_comment_lines
                pending_comment_lines = []
                current_conditions = [row[1:32]]
                current_af = [row[32]]
                in_rung = True
            elif marker == "" and in_rung:
                current_conditions.append(row[1:32])
                current_af.append(row[32])
            else:
                raise ValueError(f"Unknown marker {marker!r} in {path.name}")

        if in_rung:
            comment = "\n".join(rung_comment_lines) if rung_comment_lines else None
            rungs.append((len(current_conditions), current_conditions, current_af, comment))

    if len(rungs) < 2:
        raise ValueError(
            f"Multi-rung CSV must have at least 2 rungs, got {len(rungs)} in {path.name}"
        )
    return rungs


def write_multi_rung_golden_csv(path: Path, rungs: list[MultiRungItem]) -> None:
    """Write a multi-rung golden CSV file."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for _logical_rows, condition_rows, af_tokens, comment in rungs:
            if comment is not None:
                for line in comment.split("\n"):
                    writer.writerow(["#", line])
            for i, (conditions, af) in enumerate(zip(condition_rows, af_tokens, strict=True)):
                marker = "R" if i == 0 else ""
                writer.writerow([marker] + list(conditions) + [af])
