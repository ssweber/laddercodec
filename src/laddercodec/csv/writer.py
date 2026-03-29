"""CSV writer — Rung objects to CSV v1 format.

Converts ``Rung`` objects (from ``decode()``) into canonical CSV files
that round-trip through ``read_csv()`` and back to ``encode()``.

Public API
----------

    write_csv(path, rungs)              — list[Rung] → CSV file
    decoded_rung_to_rows(rung)          — Rung → list of CSV row lists

Pin row reconstruction
----------------------

The binary format stores timer retention as a flag in the timer blob.
The CSV format represents it as a ``.reset()`` pin row.  When a retained
timer is decoded, the writer emits a ``.reset()`` row using the conditions
from the timer's second grid row (which carried the reset-enable branch).

Tall instruction padding
------------------------

Non-retained timers have a trailing blank row for visual height.  This row
is stripped before writing — the forward path's auto-padding restores it.
"""

from __future__ import annotations

import csv as csv_mod
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from ..decode import (
    Rung,
    UnknownCondition,
    UnknownInstruction,
)
from ..instructions import (
    AfInstruction,
    ConditionInstruction,
    Counter,
    Drum,
    Shift,
    Timer,
    get_af_family_for_token,
)
from .contract import CSV_HEADER


class WriterError(ValueError):
    """Raised when a decoded rung cannot be serialized to CSV."""


# ---------------------------------------------------------------------------
# Token serialization
# ---------------------------------------------------------------------------


def _token_to_csv(token: object) -> str:
    """Serialize a condition or AF token to its CSV string."""
    if isinstance(token, (ConditionInstruction, AfInstruction)):
        return token.to_csv()
    if isinstance(token, UnknownCondition):
        raise WriterError(f"Cannot serialize unknown condition to CSV (raw {len(token.raw)} bytes)")
    if isinstance(token, UnknownInstruction):
        raise WriterError(
            f"Cannot serialize unknown instruction to CSV (raw {len(token.raw)} bytes)"
        )
    # Wire tokens and plain strings ("", "-", "|", "T", "+", "+|", "-!", "-|", "NOP")
    return str(token)


# ---------------------------------------------------------------------------
# Rung → CSV rows
# ---------------------------------------------------------------------------


def _is_blank_row(conditions: Sequence[object], af: object) -> bool:
    """Return True if all conditions are blank/empty and AF is blank."""
    if af != "":
        return False
    return all(c == "" for c in conditions)


def _conditions_are_blank(conditions: Sequence[object]) -> bool:
    """Return True when a row has no condition-side content at all."""
    return all(c == "" for c in conditions)


def decoded_rung_to_rows(rung: Rung) -> list[list[str]]:
    """Convert a ``Rung`` to a list of CSV row lists.

    Each returned row is a list of 33 strings: [marker, A..AE, AF].
    Comment rows have marker ``"#"`` and text in column A.
    Data rows have marker ``"R"`` (first) or ``""`` (continuation).

    Retained timers produce a ``.reset()`` pin row from the second
    grid row.  Non-retained timers strip trailing blank padding.
    """
    rows: list[list[str]] = []

    # --- Comment rows ---
    if rung.comment is not None:
        for line in rung.comment.split("\n"):
            rows.append(["#", line])

    # Build working copies for potential stripping.
    condition_rows = list(rung.conditions)
    af_tokens = list(rung.instructions)

    # Counters need custom CSV shaping. Native count_down decodes as AF row 0
    # plus a NOP bridge row; when row 0 is truly empty we collapse that spacer
    # row in CSV, but preserve any real row-above content.
    counter_row = next((idx for idx, af in enumerate(af_tokens) if isinstance(af, Counter)), None)
    if counter_row is not None:
        counter = cast(Counter, af_tokens[counter_row])
        if len(condition_rows) < 3 or len(af_tokens) < 3:
            raise WriterError(
                f"{counter.counter_type} requires 3 decoded rows; got {len(condition_rows)}"
            )

        if counter.counter_type == "count_up":
            if counter_row != 0:
                raise WriterError("count_up must appear on decoded row 0")

            top_conditions = condition_rows[0]
            rows.append(["R"] + [_token_to_csv(c) for c in top_conditions] + [counter.to_csv()])

            if counter.down_enabled:
                down_conditions = condition_rows[1]
                rows.append([""] + [_token_to_csv(c) for c in down_conditions] + [".down()"])

            if counter.reset_enabled:
                reset_conditions = condition_rows[2]
                rows.append([""] + [_token_to_csv(c) for c in reset_conditions] + [".reset()"])

            return rows

        if counter_row == 0:
            if af_tokens[1] != "NOP":
                raise WriterError("count_down requires a NOP bridge row in the decoded rung")
        elif counter_row != 1:
            raise WriterError("count_down must appear on decoded row 0 or row 1")

        top_conditions = condition_rows[0]
        bridge_conditions = condition_rows[1]
        if _conditions_are_blank(top_conditions):
            rows.append(["R"] + [_token_to_csv(c) for c in bridge_conditions] + [counter.to_csv()])
        else:
            rows.append(["R"] + [_token_to_csv(c) for c in top_conditions] + [""])
            rows.append([""] + [_token_to_csv(c) for c in bridge_conditions] + [counter.to_csv()])

        if counter.reset_enabled:
            reset_conditions = condition_rows[2]
            rows.append([""] + [_token_to_csv(c) for c in reset_conditions] + [".reset()"])

        return rows

    # --- Determine timer retention / tall padding ---
    af0 = rung.instructions[0] if rung.instructions else None
    af0_family = get_af_family_for_token(af0) if isinstance(af0, AfInstruction) else None
    family_name = af0_family.family_name if af0_family is not None else None
    is_retained_timer = family_name == "timer" and isinstance(af0, Timer) and af0.retained
    is_tall = isinstance(af0, AfInstruction) and af0.cell_params().get("visual_rows", 1) > 1

    if family_name == "shift":
        shift = cast(Shift, af0)
        if len(condition_rows) != 3 or len(af_tokens) != 3:
            raise WriterError(f"shift requires 3 decoded rows; got {len(condition_rows)}")

        rows.append(["R"] + [_token_to_csv(c) for c in condition_rows[0]] + [shift.to_csv()])
        rows.append([""] + [_token_to_csv(c) for c in condition_rows[1]] + [".clock()"])
        rows.append([""] + [_token_to_csv(c) for c in condition_rows[2]] + [".reset()"])
        return rows

    if family_name == "drum":
        drum = cast(Drum, af0)
        if len(condition_rows) < 4 or len(af_tokens) < 4:
            raise WriterError(f"Drum requires 4 decoded rows; got {len(condition_rows)}")

        # Row 0: main + drum instruction
        rows.append(["R"] + [_token_to_csv(c) for c in condition_rows[0]] + [drum.to_csv()])
        # Row 1: .reset() — always present
        rows.append([""] + [_token_to_csv(c) for c in condition_rows[1]] + [".reset()"])
        # Row 2: .jump(target) if enabled
        if drum.jump_enabled:
            rows.append(
                [""]
                + [_token_to_csv(c) for c in condition_rows[2]]
                + [f".jump({drum.jump_target})"]
            )
        # Row 3: .jog() if enabled
        if drum.jog_enabled:
            rows.append([""] + [_token_to_csv(c) for c in condition_rows[3]] + [".jog()"])
        return rows

    if is_retained_timer:
        # Retained timer: the second row becomes a .reset() pin row.
        # Keep all rows — the second row carries reset-enable conditions.
        pass
    elif is_tall:
        # Tall instruction (timer/copy): strip trailing blank padding rows.
        while len(condition_rows) > 1 and _is_blank_row(condition_rows[-1], af_tokens[-1]):
            condition_rows = condition_rows[:-1]
            af_tokens = af_tokens[:-1]

    # --- Data rows ---
    for i, (conditions, af) in enumerate(zip(condition_rows, af_tokens, strict=True)):
        marker = "R" if i == 0 else ""

        # Pin row: retained timer's second row gets .reset() as AF.
        if is_retained_timer and i == 1:
            af_str = ".reset()"
        else:
            af_str = _token_to_csv(af)

        cond_strs = [_token_to_csv(c) for c in conditions]
        rows.append([marker] + cond_strs + [af_str])

    return rows


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


def write_csv(
    path: Path | str,
    rungs: list[Rung],
) -> None:
    """Write decoded rungs to a canonical CSV file.

    Parameters
    ----------
    path:
        Output file path.
    rungs:
        One or more decoded rungs (from ``decode_rung()`` or
        ``decode_rungs()``).

    Raises
    ------
    WriterError
        If any rung contains unknown instructions that cannot be serialized.
    """
    path = Path(path)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv_mod.writer(f)
        writer.writerow(CSV_HEADER)
        for rung in rungs:
            for row in decoded_rung_to_rows(rung):
                writer.writerow(row)
