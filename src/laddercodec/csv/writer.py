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

Tall AF instructions have trailing padding rows for visual height.  Padding
rows — those containing only blank cells and vertical pass-through wires
(``|``) — are stripped before writing.  The forward path's auto-padding and
wire-continuation hydration restores them.
"""

from __future__ import annotations

import csv as csv_mod
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from ..decode import Rung
from ..instructions import (
    AfInstruction,
    AfToken,
    ConditionInstruction,
    ConditionToken,
    Counter,
    Drum,
    RawInstruction,
    Shift,
    Timer,
    UnknownCondition,
    UnknownInstruction,
    get_af_family_for_token,
)
from .contract import CONDITION_COLUMNS, CSV_HEADER
from .converter import convert_rung
from .parser import _parse_single_rung_rows


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


def _is_padding_row(conditions: Sequence[object]) -> bool:
    """Return True when a row is pure tall-instruction padding.

    Padding rows contain only blank cells and vertical pass-through
    wires (``|``).  The ``|`` tokens are reconstructable from ``T``
    tokens in the row above, so they can be stripped on write and
    restored on read.
    """
    return all(c in ("", "|") for c in conditions)


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
    if _is_padding_row(conditions):
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
        data_row_count = _append_data_row(
            rows, data_row_count, condition_rows[start + 1], ".reset()"
        )
    else:
        data_row_count = _emit_blank_continuation(rows, data_row_count, condition_rows[start + 1])
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
            data_row_count = _append_data_row(
                rows, data_row_count, condition_rows[start + 1], ".down()"
            )
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
    if all(c == "" for c in counter_conditions):
        data_row_count = _append_data_row(rows, data_row_count, bridge_conditions, counter)
    else:
        data_row_count = _append_data_row(rows, data_row_count, counter_conditions, "")
        data_row_count = _append_data_row(rows, data_row_count, bridge_conditions, counter)

    if counter.reset_enabled:
        data_row_count = _append_data_row(
            rows, data_row_count, condition_rows[start + 2], ".reset()"
        )
    else:
        data_row_count = _emit_blank_continuation(rows, data_row_count, condition_rows[start + 2])
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
        # Drum continuation rows are positional.  Omitting an empty jump row
        # lets a later blank-AF row slide into the jump/jog slot on reparse.
        data_row_count = _append_data_row(
            rows, data_row_count, condition_rows[start + 2], ""
        )
    if drum.jog_enabled:
        data_row_count = _append_data_row(rows, data_row_count, condition_rows[start + 3], ".jog()")
    else:
        data_row_count = _append_data_row(
            rows, data_row_count, condition_rows[start + 3], ""
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


def _display_token(token: object) -> str:
    """Return a compact user-facing representation for mismatch errors."""
    try:
        return repr(_token_to_csv(token))
    except WriterError:
        return repr(token)


def _af_tokens_match(expected: object, actual: object) -> bool:
    """Return True when AF tokens are semantically equivalent for CSV replay."""
    if expected == actual:
        return True

    if not isinstance(expected, AfInstruction) or not isinstance(actual, AfInstruction):
        return False

    if not isinstance(expected, RawInstruction) and not isinstance(actual, RawInstruction):
        return False

    return (
        expected.build_blob() == actual.build_blob()
        and expected.cell_params() == actual.cell_params()
    )


def _rebuild_rung_from_rows(rows: Sequence[Sequence[str]]) -> Rung:
    """Round-trip emitted CSV rows back into a decoded-style ``Rung``."""
    try:
        rung_ast = _parse_single_rung_rows(rows)
        logical_rows, conditions, instructions, comment = convert_rung(rung_ast)
    except (TypeError, ValueError) as exc:
        raise WriterError(
            f"CSV round-trip validation failed: emitted rows do not reparse: {exc}"
        ) from exc

    return Rung(
        logical_rows=logical_rows,
        conditions=cast(list[list[ConditionToken]], conditions),
        instructions=cast(list[AfToken], instructions),
        comment=comment,
        comment_rtf=None,
    )


def _validate_roundtrip(rung: Rung, rows: Sequence[Sequence[str]]) -> None:
    """Fail loudly when emitted CSV rows lose information from the decoded rung."""
    rebuilt = _rebuild_rung_from_rows(rows)

    if rebuilt.logical_rows != rung.logical_rows:
        # Trailing blank rows (no conditions, no AF) can be lost when
        # a tall instruction's stripped continuation absorbs them on
        # read-back.  This is cosmetic — warn instead of failing.
        extra = rung.logical_rows - rebuilt.logical_rows
        if extra > 0 and all(
            _is_padding_row(rung.conditions[r]) and rung.instructions[r] == ""
            for r in range(rebuilt.logical_rows, rung.logical_rows)
        ):
            import warnings

            warnings.warn(
                f"CSV round-trip lost {extra} trailing blank row(s) "
                f"(logical_rows {rung.logical_rows} → {rebuilt.logical_rows})",
                stacklevel=2,
            )
        else:
            raise WriterError(
                "CSV round-trip validation failed: "
                f"logical row count mismatch: expected {rung.logical_rows}, got {rebuilt.logical_rows}"
            )

    if rebuilt.comment != rung.comment:
        raise WriterError(
            "CSV round-trip validation failed: "
            f"comment mismatch: expected {rung.comment!r}, got {rebuilt.comment!r}"
        )

    for row_idx, (expected_row, actual_row) in enumerate(
        zip(rung.conditions[: rebuilt.logical_rows], rebuilt.conditions, strict=True),
        start=1,
    ):
        for col_idx, (expected, actual) in enumerate(zip(expected_row, actual_row, strict=True)):
            if expected != actual:
                raise WriterError(
                    "CSV round-trip validation failed: "
                    f"condition mismatch at row {row_idx} col {CONDITION_COLUMNS[col_idx]}: "
                    f"expected {_display_token(expected)}, got {_display_token(actual)}"
                )

    for row_idx, (expected, actual) in enumerate(
        zip(rung.instructions[: rebuilt.logical_rows], rebuilt.instructions, strict=True),
        start=1,
    ):
        if not _af_tokens_match(expected, actual):
            raise WriterError(
                "CSV round-trip validation failed: "
                f"AF mismatch at row {row_idx}: "
                f"expected {_display_token(expected)}, got {_display_token(actual)}"
            )


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

    _validate_roundtrip(rung, rows)
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
