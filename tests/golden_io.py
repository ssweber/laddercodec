"""Read/write golden canonical CSV files for encode_rung() testing.

Reading delegates to ``laddercodec.csv.reader``.  Write helpers are
test-only utilities that stay here.
"""

from __future__ import annotations

import csv
from pathlib import Path

from laddercodec.csv.contract import CSV_HEADER
from laddercodec.csv.reader import (
    MultiRungItem,
    is_multi_rung_csv,
    read_golden_csv,
)
from laddercodec.csv.reader import (
    read_multi_rung_csv as read_multi_rung_golden_csv,
)
from laddercodec.encode import AfToken, ConditionToken
from laddercodec.instructions import Coil, CompareContact, Contact, RawInstruction, Timer

GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "ladder_captures" / "golden"
TOTAL_COLUMNS = len(CSV_HEADER)  # 33

# Re-export for existing test imports
__all__ = [
    "GOLDEN_DIR",
    "MultiRungItem",
    "is_multi_rung_csv",
    "read_golden_csv",
    "read_multi_rung_golden_csv",
    "write_golden_csv",
    "write_multi_rung_golden_csv",
]


def _token_to_csv(token: ConditionToken | AfToken) -> str:
    """Serialize a token (string, Contact, Coil, CompareContact, Timer, or RawInstruction) to CSV."""
    if isinstance(token, (Contact, Coil, CompareContact, Timer, RawInstruction)):
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
                writer.writerow(
                    [marker] + [_token_to_csv(c) for c in conditions] + [_token_to_csv(af)]
                )
