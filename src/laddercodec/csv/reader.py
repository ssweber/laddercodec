"""CSV reader — parse golden/contract CSV files into encode_rung() arguments.

Public API for reading Click Ladder CSV files into structured data ready
for ``encode_rung()`` / ``encode_multi_rung()``.
"""

from __future__ import annotations

import csv as csv_mod
from pathlib import Path

from ..encode import SUPPORTED_CONDITION_TOKENS, AfToken, ConditionToken
from ..instructions import Coil, CompareContact, Contact, RawInstruction, Timer
from .contract import CSV_HEADER

TOTAL_COLUMNS = len(CSV_HEADER)  # 33

# Type alias: (logical_rows, condition_rows, af_tokens, comment)
MultiRungItem = tuple[int, list[list[ConditionToken]], list[AfToken], str | None]


def _parse_condition(token: str) -> ConditionToken:
    """Convert a CSV condition token to a wire string, Contact, or CompareContact."""
    if token in SUPPORTED_CONDITION_TOKENS:
        return token

    # Strip wire-down prefix for dispatch decision.
    # T:X001 → dispatch as Contact; T:DS1==1 → dispatch as CompareContact.
    check = token.strip()
    if len(check) > 2 and check[1] == ":" and check[0] in ("T", "|"):
        check = check[2:]

    for op in ("==", "!=", ">=", "<=", ">", "<"):
        if op in check:
            return CompareContact.from_csv_token(token)
    return Contact.from_csv_token(token)


def _parse_af(token: str) -> AfToken:
    """Convert a CSV AF token to a string, Coil, Timer, or RawInstruction."""
    if token.strip().upper() in ("", "NOP"):
        return token
    if token.strip().startswith("raw("):
        return RawInstruction.from_csv_token(token)
    if token.strip().startswith(("on_delay(", "off_delay(")):
        return Timer.from_csv_token(token)
    return Coil.from_csv_token(token)


def read_golden_csv(
    path: Path,
) -> tuple[int, list[list[ConditionToken]], list[AfToken], str | None]:
    """Read a golden CSV and return (logical_rows, condition_rows, af_tokens, comment).

    Returns the exact arguments needed for ``encode_rung()``.
    Instruction tokens (e.g. ``X001``, ``out(Y001)``) are parsed into
    ``Contact`` / ``Coil`` objects; wire tokens remain as strings.
    """
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv_mod.reader(f)
        header = next(reader)
        if tuple(header) != CSV_HEADER:
            raise ValueError(f"Bad header in {path.name}: expected {CSV_HEADER}")

        comment_lines: list[str] = []
        condition_rows: list[list[ConditionToken]] = []
        af_tokens: list[AfToken] = []

        for row in reader:
            marker = row[0]
            if marker == "#":
                comment_lines.append(row[1] if len(row) > 1 else "")
                continue
            if len(row) != TOTAL_COLUMNS:
                raise ValueError(
                    f"Row has {len(row)} columns, expected {TOTAL_COLUMNS} in {path.name}"
                )
            if marker in ("R", ""):
                conditions = [_parse_condition(t) for t in row[1:32]]
                af_raw = row[32].strip()
                # Pin rows: .reset() makes the parent timer retentive.
                if af_raw.startswith(".reset("):
                    for i in range(len(af_tokens) - 1, -1, -1):
                        if isinstance(af_tokens[i], Timer):
                            t = af_tokens[i]
                            af_tokens[i] = Timer(
                                timer_type=t.timer_type,
                                done_bit=t.done_bit,
                                current=t.current,
                                setpoint=t.setpoint,
                                unit=t.unit,
                                retained=True,
                            )
                            break
                    af: AfToken = ""
                else:
                    af = _parse_af(af_raw)
                condition_rows.append(conditions)
                af_tokens.append(af)
            else:
                raise ValueError(f"Unknown marker {marker!r} in {path.name}")

    logical_rows = len(condition_rows)
    if logical_rows == 0:
        raise ValueError(f"No rung rows found in {path.name}")
    comment = "\n".join(comment_lines) if comment_lines else None
    return logical_rows, condition_rows, af_tokens, comment


def is_multi_rung_csv(path: Path) -> bool:
    """Return True if the CSV contains more than one rung (multiple R markers)."""
    count = 0
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv_mod.reader(f)
        next(reader)  # skip header
        for row in reader:
            if row and row[0] == "R":
                count += 1
                if count > 1:
                    return True
    return False


def read_multi_rung_csv(path: Path) -> list[MultiRungItem]:
    """Read a multi-rung golden CSV. Each R marker starts a new rung.

    Returns list of (logical_rows, condition_rows, af_tokens, comment).
    Comments (# rows) before each R belong to that rung.
    """
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv_mod.reader(f)
        header = next(reader)
        if tuple(header) != CSV_HEADER:
            raise ValueError(f"Bad header in {path.name}: expected {CSV_HEADER}")

        rungs: list[MultiRungItem] = []
        pending_comment_lines: list[str] = []
        rung_comment_lines: list[str] = []
        current_conditions: list[list[ConditionToken]] = []
        current_af: list[AfToken] = []
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
                current_conditions = [[_parse_condition(t) for t in row[1:32]]]
                current_af = [_parse_af(row[32])]
                in_rung = True
            elif marker == "" and in_rung:
                current_conditions.append([_parse_condition(t) for t in row[1:32]])
                current_af.append(_parse_af(row[32]))
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
