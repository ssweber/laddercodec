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

from ..decode import Rung
from ..instructions import (
    AfInstruction,
    ConditionInstruction,
    Counter,
    Drum,
    Shift,
    Timer,
    UnknownCondition,
    UnknownInstruction,
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

    # --- Find pinned AF instruction (counter/timer/shift/drum) at any row ---
    pinned_row: int | None = None
    pinned_af: AfInstruction | None = None
    pinned_family: str | None = None
    for idx, af in enumerate(af_tokens):
        if isinstance(af, AfInstruction):
            fam = get_af_family_for_token(af)
            if fam is not None and fam.family_name in ("counter", "timer", "shift", "drum"):
                pinned_row = idx
                pinned_af = af
                pinned_family = fam.family_name
                break

    is_retained_timer = (
        pinned_family == "timer" and isinstance(pinned_af, Timer) and pinned_af.retained
    )
    is_tall = any(
        isinstance(af, AfInstruction) and af.cell_params().get("visual_rows", 1) > 1
        for af in af_tokens
    )

    # Helper: emit regular data rows for indices [0, up_to).
    def _emit_prefix(up_to: int) -> None:
        for i in range(up_to):
            marker = "R" if i == 0 else ""
            rows.append(
                [marker]
                + [_token_to_csv(c) for c in condition_rows[i]]
                + [_token_to_csv(af_tokens[i])]
            )

    if pinned_family == "counter":
        assert pinned_row is not None
        counter = cast(Counter, pinned_af)
        needed = pinned_row + 3
        if len(condition_rows) < needed or len(af_tokens) < needed:
            raise WriterError(
                f"{counter.counter_type} requires {needed} decoded rows; got {len(condition_rows)}"
            )
        _emit_prefix(pinned_row)
        first_marker = "R" if pinned_row == 0 else ""

        if counter.counter_type == "count_up":
            rows.append(
                [first_marker]
                + [_token_to_csv(c) for c in condition_rows[pinned_row]]
                + [counter.to_csv()]
            )
            if counter.down_enabled:
                rows.append(
                    [""] + [_token_to_csv(c) for c in condition_rows[pinned_row + 1]] + [".down()"]
                )
            if counter.reset_enabled:
                rows.append(
                    [""] + [_token_to_csv(c) for c in condition_rows[pinned_row + 2]] + [".reset()"]
                )
            return rows

        # count_down: NOP bridge row follows the counter.
        bridge_row = pinned_row + 1
        if af_tokens[bridge_row] != "NOP":
            raise WriterError("count_down requires a NOP bridge row after the counter")
        counter_conditions = condition_rows[pinned_row]
        bridge_conditions = condition_rows[bridge_row]
        if _conditions_are_blank(counter_conditions):
            rows.append(
                [first_marker] + [_token_to_csv(c) for c in bridge_conditions] + [counter.to_csv()]
            )
        else:
            rows.append([first_marker] + [_token_to_csv(c) for c in counter_conditions] + [""])
            rows.append([""] + [_token_to_csv(c) for c in bridge_conditions] + [counter.to_csv()])
        if counter.reset_enabled:
            rows.append(
                [""] + [_token_to_csv(c) for c in condition_rows[bridge_row + 1]] + [".reset()"]
            )
        return rows

    if pinned_family == "shift":
        assert pinned_row is not None
        shift = cast(Shift, pinned_af)
        needed = pinned_row + 3
        if len(condition_rows) < needed or len(af_tokens) < needed:
            raise WriterError(f"shift requires {needed} decoded rows; got {len(condition_rows)}")
        _emit_prefix(pinned_row)
        marker = "R" if pinned_row == 0 else ""
        rows.append(
            [marker] + [_token_to_csv(c) for c in condition_rows[pinned_row]] + [shift.to_csv()]
        )
        rows.append(
            [""] + [_token_to_csv(c) for c in condition_rows[pinned_row + 1]] + [".clock()"]
        )
        rows.append(
            [""] + [_token_to_csv(c) for c in condition_rows[pinned_row + 2]] + [".reset()"]
        )
        return rows

    if pinned_family == "drum":
        assert pinned_row is not None
        drum = cast(Drum, pinned_af)
        needed = pinned_row + 4
        if len(condition_rows) < needed or len(af_tokens) < needed:
            raise WriterError(f"Drum requires {needed} decoded rows; got {len(condition_rows)}")
        _emit_prefix(pinned_row)
        marker = "R" if pinned_row == 0 else ""
        rows.append(
            [marker] + [_token_to_csv(c) for c in condition_rows[pinned_row]] + [drum.to_csv()]
        )
        rows.append(
            [""] + [_token_to_csv(c) for c in condition_rows[pinned_row + 1]] + [".reset()"]
        )
        if drum.jump_enabled:
            rows.append(
                [""]
                + [_token_to_csv(c) for c in condition_rows[pinned_row + 2]]
                + [f".jump({drum.jump_target})"]
            )
        if drum.jog_enabled:
            rows.append(
                [""] + [_token_to_csv(c) for c in condition_rows[pinned_row + 3]] + [".jog()"]
            )
        return rows

    if is_retained_timer:
        # Retained timer: keep all rows — the row after the timer is a .reset() pin.
        pass
    elif is_tall:
        # Tall instruction (timer/copy/search): strip trailing blank padding rows.
        while len(condition_rows) > 1 and _is_blank_row(condition_rows[-1], af_tokens[-1]):
            condition_rows = condition_rows[:-1]
            af_tokens = af_tokens[:-1]

    # --- Data rows ---
    for i, (conditions, af) in enumerate(zip(condition_rows, af_tokens, strict=True)):
        marker = "R" if i == 0 else ""

        # Pin row: retained timer's row after the timer gets .reset() as AF.
        if is_retained_timer and pinned_row is not None and i == pinned_row + 1:
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
