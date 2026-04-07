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


def _append_data_row(
    rows: list[list[str]],
    data_row_count: int,
    conditions: Sequence[object],
    af: object,
) -> int:
    """Append one CSV data row and return the new emitted-data-row count."""
    marker = "R" if data_row_count == 0 else ""
    rows.append([marker] + [_token_to_csv(c) for c in conditions] + [_token_to_csv(af)])
    return data_row_count + 1


def _emit_blank_continuation(
    rows: list[list[str]],
    data_row_count: int,
    conditions: Sequence[object],
) -> int:
    """Emit a blank-AF continuation row only when it carries geometry."""
    if _conditions_are_blank(conditions):
        return data_row_count
    return _append_data_row(rows, data_row_count, conditions, "")


def _require_blank_af(af: object, *, message: str) -> None:
    """Ensure a consumed continuation row does not hide another AF token."""
    if af != "":
        raise WriterError(message)


def _emit_timer_block(
    rows: list[list[str]],
    data_row_count: int,
    condition_rows: Sequence[Sequence[object]],
    af_tokens: Sequence[object],
    start: int,
    timer: Timer,
) -> tuple[int, int]:
    """Emit one timer block and return ``(new_count, consumed_rows)``."""
    needed = start + 2
    if len(condition_rows) < needed or len(af_tokens) < needed:
        raise WriterError(f"timer requires {needed} decoded rows; got {len(condition_rows)}")

    _require_blank_af(
        af_tokens[start + 1],
        message="timer continuation row must be blank AF",
    )

    data_row_count = _append_data_row(rows, data_row_count, condition_rows[start], timer)
    if timer.retained:
        data_row_count = _append_data_row(rows, data_row_count, condition_rows[start + 1], ".reset()")
    else:
        data_row_count = _emit_blank_continuation(
            rows, data_row_count, condition_rows[start + 1]
        )
    return data_row_count, 2


def _emit_counter_block(
    rows: list[list[str]],
    data_row_count: int,
    condition_rows: Sequence[Sequence[object]],
    af_tokens: Sequence[object],
    start: int,
    counter: Counter,
) -> tuple[int, int]:
    """Emit one counter block and return ``(new_count, consumed_rows)``."""
    needed = start + 3
    if len(condition_rows) < needed or len(af_tokens) < needed:
        raise WriterError(
            f"{counter.counter_type} requires {needed} decoded rows; got {len(condition_rows)}"
        )

    if counter.counter_type == "count_up":
        _require_blank_af(
            af_tokens[start + 1],
            message="count_up continuation row must be blank AF",
        )
        _require_blank_af(
            af_tokens[start + 2],
            message="count_up reset row must be blank AF",
        )
        data_row_count = _append_data_row(rows, data_row_count, condition_rows[start], counter)
        if counter.down_enabled:
            data_row_count = _append_data_row(rows, data_row_count, condition_rows[start + 1], ".down()")
        else:
            data_row_count = _emit_blank_continuation(
                rows, data_row_count, condition_rows[start + 1]
            )
        if counter.reset_enabled:
            data_row_count = _append_data_row(
                rows, data_row_count, condition_rows[start + 2], ".reset()"
            )
        else:
            data_row_count = _emit_blank_continuation(
                rows, data_row_count, condition_rows[start + 2]
            )
        return data_row_count, 3

    if af_tokens[start + 1] != "NOP":
        raise WriterError("count_down requires a NOP bridge row after the counter")
    _require_blank_af(
        af_tokens[start + 2],
        message="count_down reset row must be blank AF",
    )

    counter_conditions = condition_rows[start]
    bridge_conditions = condition_rows[start + 1]
    if _conditions_are_blank(counter_conditions):
        data_row_count = _append_data_row(rows, data_row_count, bridge_conditions, counter)
    else:
        data_row_count = _append_data_row(rows, data_row_count, counter_conditions, "")
        data_row_count = _append_data_row(rows, data_row_count, bridge_conditions, counter)

    if counter.reset_enabled:
        data_row_count = _append_data_row(
            rows, data_row_count, condition_rows[start + 2], ".reset()"
        )
    else:
        data_row_count = _emit_blank_continuation(
            rows, data_row_count, condition_rows[start + 2]
        )
    return data_row_count, 3


def _emit_shift_block(
    rows: list[list[str]],
    data_row_count: int,
    condition_rows: Sequence[Sequence[object]],
    af_tokens: Sequence[object],
    start: int,
    shift: Shift,
) -> tuple[int, int]:
    """Emit one shift block and return ``(new_count, consumed_rows)``."""
    needed = start + 3
    if len(condition_rows) < needed or len(af_tokens) < needed:
        raise WriterError(f"shift requires {needed} decoded rows; got {len(condition_rows)}")

    _require_blank_af(
        af_tokens[start + 1],
        message="shift .clock() row must be blank AF",
    )
    _require_blank_af(
        af_tokens[start + 2],
        message="shift .reset() row must be blank AF",
    )

    data_row_count = _append_data_row(rows, data_row_count, condition_rows[start], shift)
    data_row_count = _append_data_row(rows, data_row_count, condition_rows[start + 1], ".clock()")
    data_row_count = _append_data_row(rows, data_row_count, condition_rows[start + 2], ".reset()")
    return data_row_count, 3


def _emit_drum_block(
    rows: list[list[str]],
    data_row_count: int,
    condition_rows: Sequence[Sequence[object]],
    af_tokens: Sequence[object],
    start: int,
    drum: Drum,
) -> tuple[int, int]:
    """Emit one drum block and return ``(new_count, consumed_rows)``."""
    needed = start + 4
    if len(condition_rows) < needed or len(af_tokens) < needed:
        raise WriterError(f"Drum requires {needed} decoded rows; got {len(condition_rows)}")

    _require_blank_af(
        af_tokens[start + 1],
        message="drum .reset() row must be blank AF",
    )
    _require_blank_af(
        af_tokens[start + 2],
        message="drum .jump() row must be blank AF",
    )
    _require_blank_af(
        af_tokens[start + 3],
        message="drum .jog() row must be blank AF",
    )

    data_row_count = _append_data_row(rows, data_row_count, condition_rows[start], drum)
    data_row_count = _append_data_row(rows, data_row_count, condition_rows[start + 1], ".reset()")
    if drum.jump_enabled:
        data_row_count = _append_data_row(
            rows,
            data_row_count,
            condition_rows[start + 2],
            f".jump({drum.jump_target})",
        )
    else:
        data_row_count = _emit_blank_continuation(
            rows, data_row_count, condition_rows[start + 2]
        )
    if drum.jog_enabled:
        data_row_count = _append_data_row(rows, data_row_count, condition_rows[start + 3], ".jog()")
    else:
        data_row_count = _emit_blank_continuation(
            rows, data_row_count, condition_rows[start + 3]
        )
    return data_row_count, 4


def _emit_generic_tall_block(
    rows: list[list[str]],
    data_row_count: int,
    condition_rows: Sequence[Sequence[object]],
    af_tokens: Sequence[object],
    start: int,
    af: AfInstruction,
) -> tuple[int, int]:
    """Emit a non-pinned tall AF block, preserving only nonblank continuation rows."""
    visual_rows = int(af.cell_params().get("visual_rows", 1))
    needed = start + visual_rows
    if len(condition_rows) < needed or len(af_tokens) < needed:
        raise WriterError(
            f"{type(af).__name__} requires {needed} decoded rows; got {len(condition_rows)}"
        )

    data_row_count = _append_data_row(rows, data_row_count, condition_rows[start], af)
    for offset in range(1, visual_rows):
        _require_blank_af(
            af_tokens[start + offset],
            message=f"{type(af).__name__} continuation row must be blank AF",
        )
        data_row_count = _emit_blank_continuation(
            rows, data_row_count, condition_rows[start + offset]
        )
    return data_row_count, visual_rows


def decoded_rung_to_rows(rung: Rung) -> list[list[str]]:
    """Convert a ``Rung`` to a list of CSV row lists.

    Each returned row is a list of 33 strings: [marker, A..AE, AF].
    Comment rows have marker ``"#"`` and text in column A.
    Data rows have marker ``"R"`` (first) or ``""`` (continuation).

    Retained timers produce a ``.reset()`` pin row from the second
    grid row.  Multi-row AF families are streamed in order so multiple
    pinned/tall blocks survive CSV round-trip without truncation.
    """
    rows: list[list[str]] = []

    # --- Comment rows ---
    if rung.comment is not None:
        for line in rung.comment.split("\n"):
            rows.append(["#", line])

    condition_rows = list(rung.conditions)
    af_tokens = list(rung.instructions)
    data_row_count = 0
    row_idx = 0

    while row_idx < len(condition_rows):
        af = af_tokens[row_idx]
        consumed = 1

        if isinstance(af, AfInstruction):
            family = get_af_family_for_token(af)
            family_name = family.family_name if family is not None else None

            if family_name == "timer" and isinstance(af, Timer):
                data_row_count, consumed = _emit_timer_block(
                    rows, data_row_count, condition_rows, af_tokens, row_idx, af
                )
                row_idx += consumed
                continue

            if family_name == "counter" and isinstance(af, Counter):
                data_row_count, consumed = _emit_counter_block(
                    rows, data_row_count, condition_rows, af_tokens, row_idx, af
                )
                row_idx += consumed
                continue

            if family_name == "shift" and isinstance(af, Shift):
                data_row_count, consumed = _emit_shift_block(
                    rows, data_row_count, condition_rows, af_tokens, row_idx, af
                )
                row_idx += consumed
                continue

            if family_name == "drum" and isinstance(af, Drum):
                data_row_count, consumed = _emit_drum_block(
                    rows, data_row_count, condition_rows, af_tokens, row_idx, af
                )
                row_idx += consumed
                continue

            visual_rows = int(af.cell_params().get("visual_rows", 1))
            if visual_rows > 1:
                data_row_count, consumed = _emit_generic_tall_block(
                    rows, data_row_count, condition_rows, af_tokens, row_idx, af
                )
                row_idx += consumed
                continue

        data_row_count = _append_data_row(rows, data_row_count, condition_rows[row_idx], af)
        row_idx += consumed

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
