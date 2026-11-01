"""CSV writer — Rung objects to CSV v1 format.

Converts ``Rung`` objects (from ``decode()``) into canonical CSV files
that round-trip through ``read_csv()`` and back to ``encode()``.

Public API
----------

    write_csv(path, rungs)              — list[Rung] → CSV file
    decoded_rung_to_rows(rung)          — Rung → list of CSV row lists

Pin row reconstruction
----------------------

The binary format stores pin use as flags in the blob (e.g. timer
retention) and each pin's row as the blob's part bytes (``pin_rows``).
The CSV format represents each used pin as a pin row (``.reset()``, ...)
at that row, with the OR-leg rows between pins kept in place.

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
    RawInstruction,
    UnknownCondition,
    UnknownInstruction,
)
from ..model import PinnedInstruction
from .contract import CONDITION_COLUMNS, CSV_HEADER
from .converter import _is_blank_row, convert_rung, pinned_gap_height
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


def _followed_by_floating_row(af_tokens: Sequence[object], span_end: int) -> bool:
    """True when a blank-AF row sits just below a tall instruction's span.

    Such a row would be absorbed into the instruction's continuation slots on
    reparse, so the instruction's trailing padding must stay positional rather
    than dehydrated — otherwise the following content floats up.  A real AF
    instruction (or the end of the rung) anchors the position, so dehydration
    is safe there — except a box with lead slots, whose lead rows are written
    as blank-AF rows above its token.
    """
    if span_end >= len(af_tokens):
        return False
    following = af_tokens[span_end]
    return following == "" or (isinstance(following, PinnedInstruction) and following.lead_rows > 0)


def _emit_blank_continuation(
    rows: list[list[str]],
    data_row_count: int,
    conditions: Sequence[object],
    keep_positional: bool = False,
) -> int:
    """Emit a blank-AF continuation row.

    Trailing padding (blank cells and ``|`` pass-through wires) is dehydrated —
    the reparser rebuilds it from the instruction's visual height.  But when a
    blank-AF row follows the instruction's span (``keep_positional``), the row
    is emitted so following content keeps its position on reparse.
    """
    if not keep_positional and _is_padding_row(conditions):
        return data_row_count
    return _append_data_row(rows, data_row_count, conditions, "")


def _require_blank_af(af: object, *, message: str) -> None:
    """Ensure a consumed continuation row does not hide another AF token."""
    if af != "":
        raise WriterError(message)


def _emit_pin_gap(
    rows: list[list[str]],
    data_row_count: int,
    gap: Sequence[Sequence[object]],
    unused_pins: int,
) -> int:
    """Emit the rows between two slots of a pinned block, before a used pin.

    Drops as much trailing padding as the converter re-pads for the unused
    pins in between (``pinned_gap_height``), so the pin lands on its row.
    """
    keep = len(gap)
    for drop in range(min(unused_pins, len(gap)), 0, -1):
        if all(_is_padding_row(row) for row in gap[-drop:]) and (
            pinned_gap_height(gap[:-drop], unused_pins) == len(gap)
        ):
            keep = len(gap) - drop
            break
    for row in gap[:keep]:
        data_row_count = _append_data_row(rows, data_row_count, row, "")
    return data_row_count


def _emit_box_tail(
    rows: list[list[str]],
    data_row_count: int,
    tail: Sequence[Sequence[object]],
    keep_positional: bool,
) -> int:
    """Emit a pinned block's rows after its last used pin (its unused pins' rows).

    Trailing padding dehydrates, since the reparse pads the box back to its
    height, unless a floating row follows (``keep_positional``).
    """
    last = len(tail) - 1
    if not keep_positional:
        last = max((i for i, row in enumerate(tail) if not _is_padding_row(row)), default=-1)
    for row in tail[: last + 1]:
        data_row_count = _append_data_row(rows, data_row_count, row, "")
    return data_row_count


def _emit_pinned_block(
    rows: list[list[str]],
    data_row_count: int,
    condition_rows: Sequence[Sequence[object]],
    af_tokens: Sequence[object],
    start: int,
    af: PinnedInstruction,
) -> tuple[int, int]:
    """Emit a box whose slots sit at ``af.pin_rows``; return ``(new_count, consumed_rows)``.

    Lead slots (above the main input) are emitted as blank-AF rows before the
    instruction token; the token goes on the main input's row, which decodes
    with a NOP in its AF cell.  Empty lead rows are left out, unless the row
    above is a blank-AF row the reparse would take as the lead row instead.
    """
    name = af.to_csv().split("(", 1)[0]
    height = af.pin_rows[-1] + 1
    lead = af.lead_rows
    needed = start + height
    if len(condition_rows) < needed or len(af_tokens) < needed:
        raise WriterError(f"{name} requires {needed} decoded rows; got {len(condition_rows)}")
    for offset in range(1, height):
        if offset == lead:
            if af_tokens[start + offset] != "NOP":
                raise WriterError(f"{name} requires a NOP bridge row on its main input")
            continue
        _require_blank_af(af_tokens[start + offset], message=f"{name} pin rows must be blank AF")

    main = af.pin_rows[lead - 1] if lead else 0
    if main != lead:
        raise WriterError(f"{name} lead slots must sit directly above its main input")
    first_lead = next(
        (i for i in range(lead) if not _is_blank_row(condition_rows[start + i])), lead
    )
    if start > 0 and af_tokens[start - 1] == "":
        first_lead = 0
    for offset in range(first_lead, lead):
        data_row_count = _append_data_row(rows, data_row_count, condition_rows[start + offset], "")
    data_row_count = _append_data_row(rows, data_row_count, condition_rows[start + main], af)
    prev, unused = main, 0
    for pin_row, label in zip(af.pin_rows[lead:], af.pin_labels(), strict=True):
        if label is None:
            unused += 1
            continue
        gap = condition_rows[start + prev + 1 : start + pin_row]
        data_row_count = _emit_pin_gap(rows, data_row_count, gap, unused)
        data_row_count = _append_data_row(
            rows, data_row_count, condition_rows[start + pin_row], label
        )
        prev, unused = pin_row, 0
    tail = condition_rows[start + prev + 1 : needed]
    keep = _followed_by_floating_row(af_tokens, needed)
    data_row_count = _emit_box_tail(rows, data_row_count, tail, keep)
    return data_row_count, height


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

    keep = _followed_by_floating_row(af_tokens, start + visual_rows)
    data_row_count = _append_data_row(rows, data_row_count, condition_rows[start], af)
    for offset in range(1, visual_rows):
        _require_blank_af(
            af_tokens[start + offset],
            message=f"{type(af).__name__} continuation row must be blank AF",
        )
        data_row_count = _emit_blank_continuation(
            rows, data_row_count, condition_rows[start + offset], keep
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
            if (
                isinstance(expected, PinnedInstruction)
                and isinstance(actual, PinnedInstruction)
                and expected.pin_rows != actual.pin_rows
            ):
                raise WriterError(
                    "CSV round-trip validation failed: "
                    f"{_display_token(expected)} at row {row_idx} has its pins on rows "
                    f"{expected.pin_rows}, which CSV cannot express (it reads back as "
                    f"{actual.pin_rows}); an OR leg likely sits on an unused pin's row"
                )
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
            if isinstance(af, PinnedInstruction):
                data_row_count, consumed = _emit_pinned_block(
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
    *,
    index: bool = False,
) -> None:
    """Write decoded rungs to a canonical CSV file.

    Parameters
    ----------
    path:
        Output file path.
    rungs:
        One or more decoded rungs (from ``decode_rung()`` or
        ``decode_rungs()``).
    index:
        When ``True``, the per-rung ``R`` marker is replaced with a 1-based
        sequential index (``R1``, ``R2``, ``R3``, ...) counting across the
        whole file.  The default (``False``) emits a plain ``R``.  Indexed
        files still round-trip through ``read_csv()`` — the digits are
        decorative and ignored on read.

    Raises
    ------
    WriterError
        If any rung contains unknown instructions that cannot be serialized.
    """
    path = Path(path)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv_mod.writer(f)
        writer.writerow(CSV_HEADER)
        for rung_number, rung in enumerate(rungs, start=1):  # start=1 → first rung is R1
            for row in decoded_rung_to_rows(rung):
                if index and row and row[0] == "R":
                    row = [f"R{rung_number}", *row[1:]]
                writer.writerow(row)
