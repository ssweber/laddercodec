"""Read/write golden canonical CSV files for encode_rung() testing.

Reading delegates to ``laddercodec.csv``.  Write helpers are
test-only utilities that stay here.
"""

from __future__ import annotations

import csv
from pathlib import Path

from laddercodec import (
    Coil,
    CompareContact,
    Contact,
    Counter,
    RawInstruction,
    Rung,
    Timer,
    read_csv,
)
from laddercodec.csv import CSV_HEADER
from laddercodec.encode import AfToken, ConditionToken

GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "ladder_captures" / "golden"
TOTAL_COLUMNS = len(CSV_HEADER)  # 33

__all__ = [
    "GOLDEN_DIR",
    "Rung",
    "read_csv",
    "write_golden_csv",
    "write_multi_rung_golden_csv",
]


def _token_to_csv(token: ConditionToken | AfToken) -> str:
    """Serialize a token (string, Contact, Coil, CompareContact, Timer, or RawInstruction) to CSV."""
    if isinstance(token, (Contact, Coil, CompareContact, Counter, Timer, RawInstruction)):
        return token.to_csv()
    return token


def write_golden_csv(
    path: Path,
    condition_rows: list[list[ConditionToken]],
    af_tokens: list[AfToken],
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
            row = [marker] + [_token_to_csv(c) for c in conditions] + [_token_to_csv(af)]
            writer.writerow(row)


def write_multi_rung_golden_csv(
    path: Path,
    rungs: list[Rung] | list[tuple[int, list, list, str | None]],
) -> None:
    """Write a multi-rung golden CSV file.

    Accepts either ``Rung`` objects or ``(logical_rows, conditions, instructions, comment)`` tuples.
    """
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for item in rungs:
            if isinstance(item, tuple):
                _lr, conds, afs, comment = item
            else:
                conds, afs, comment = item.conditions, item.instructions, item.comment
            if comment is not None:
                for line in comment.split("\n"):
                    writer.writerow(["#", line])
            for i, (conditions, af) in enumerate(zip(conds, afs, strict=True)):
                marker = "R" if i == 0 else ""
                writer.writerow(
                    [marker] + [_token_to_csv(c) for c in conditions] + [_token_to_csv(af)]
                )
