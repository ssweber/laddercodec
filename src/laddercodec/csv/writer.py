"""CSV writer — Rung objects to CSV v1 format.

Converts ``Rung`` objects (from ``decode()``) into canonical CSV files
that round-trip through ``read_csv()`` and back to ``encode()``.

Public API
----------

    write_csv(path, rungs)              — list[Rung] → CSV file
    decoded_rung_to_rows(rung)          — Rung → list of CSV row lists

Layout
------

When laddercodec can lay out a rung, the writer writes it as CLICK's syntax
check draws it (``docs/internals/layout.md``), and the file reads back to
exactly that drawing.  If CLICK would split the rung, the writer writes the
rungs that CLICK splits it into.  A rung that has no layout keeps its cells
where they are.  That happens when it holds only wires and unwired NOPs, when
the layout cannot draw it, or when ``laddercodec.check()`` reports a finding
other than an unwired box input or a contact that feeds only a NOP.

Pin row reconstruction
----------------------

In the binary format, flags in the blob say which pins are in use, such as
the flag for a retained timer.  The blob's part bytes hold the row of each
pin (``pin_rows``).  In the CSV format, each pin in use is a pin row, such
as ``.reset()``, on that row.  The OR-leg rows between pins stay in place.

Tall instruction padding
------------------------

A tall AF instruction spans several rows.  Rows below its token that hold
only blank cells and vertical wires (``|``) are padding.  The writer leaves
out the padding rows at the end of the instruction.  When ``read_csv()``
reads the file, it pads the instruction back to its height and puts the
vertical wires back.
"""

from __future__ import annotations

import csv as csv_mod
import warnings
from collections.abc import Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import get_args

from .._layout import LayoutError, canonical, circuit
from ..decode import Rung
from ..errors import WriterError
from ..instructions import (
    AfInstruction,
    ConditionInstruction,
    RawInstruction,
    UnknownCondition,
    UnknownInstruction,
)
from ..model import PinnedInstruction
from ..operands.unchecked import refusals, unchecked
from ..undecoded import Stop, Undecoded, UndecodedRungWarning, marker_rung
from .contract import CONDITION_COLUMNS, CSV_HEADER
from .converter import _is_blank_row, convert_rung, pinned_gap_height
from .parser import _parse_single_rung_rows

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
    # Wire tokens and plain strings ("", "-", "|", "T", "+", "+|", "-!", "-|", "NOP") are
    # already CSV text.
    return str(token)


# ---------------------------------------------------------------------------
# Rung → CSV rows
# ---------------------------------------------------------------------------


def _is_padding_row(conditions: Sequence[object]) -> bool:
    """Return True if every cell of the row is blank or a vertical wire (``|``).

    Such a row is padding below a tall instruction.  The read rebuilds each
    ``|`` from the wire in the row above, so the writer can leave the row out.
    """
    return all(c in ("", "|") for c in conditions)


def _append_data_row(
    rows: list[list[str]],
    data_row_count: int,
    conditions: Sequence[object],
    af: object,
) -> int:
    """Append one CSV data row to *rows* and return *data_row_count* plus one."""
    marker = "R" if data_row_count == 0 else ""
    rows.append([marker] + [_token_to_csv(c) for c in conditions] + [_token_to_csv(af)])
    return data_row_count + 1


def _followed_by_floating_row(af_tokens: Sequence[object], span_end: int) -> bool:
    """Return True if the row just below a tall instruction's rows has a blank AF cell, or
    holds a box with lead slots.

    If so, the writer must keep the instruction's padding rows.  Otherwise the
    read would take the blank-AF row as one of the instruction's rows, and that
    row and the rows below it would move up.  An AF instruction or the end of
    the rung after the span holds the rows in place, and the padding rows can
    be left out.  The exception is a box with lead slots, the slots above its
    main input.  Its lead rows are written as blank-AF rows above its token,
    so this returns True for it too.
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
    """Append a continuation row of a tall instruction, with a blank AF cell.

    Leave out a padding row, one with only blank cells and ``|`` wires,
    because the read pads the instruction back to its height.  With
    *keep_positional*, write the padding row anyway, so that the rows after
    it keep their place on read.  Return the new data row count.
    """
    if not keep_positional and _is_padding_row(conditions):
        return data_row_count
    return _append_data_row(rows, data_row_count, conditions, "")


def _require_blank_af(af: object, *, message: str) -> None:
    """Raise ``WriterError(message)`` if *af*, a continuation row's AF cell, is not blank."""
    if af != "":
        raise WriterError(message)


def _emit_pin_gap(
    rows: list[list[str]],
    data_row_count: int,
    gap: Sequence[Sequence[object]],
    unused_pins: int,
) -> int:
    """Append the rows between two slots of a pinned block, before a used pin.

    Leave out as many padding rows at the end of *gap* as the converter adds
    back for the unused pins in between (``pinned_gap_height``).  The used pin
    then lands on its own row on read.  Return the new data row count.
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
    """Append the rows of a pinned block after its last used pin.

    Leave out the padding rows at the end, because the read pads the box back
    to its height.  With *keep_positional*, keep them, because a blank-AF row
    follows the box.
    Return the new data row count.
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
    """Append the rows of a box whose slots sit at ``af.pin_rows``.

    Return ``(new_count, consumed_rows)``.

    Write the lead slots, the slots above the main input, as blank-AF rows
    before the instruction token.  Write the token on the main input's row.
    In the decoded rung, that row has a NOP in its AF cell.  Leave out the
    blank lead rows at the top of the box.  Keep them if the row above the box
    has a blank AF cell, because the read would take that row as a lead row.
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
    """Append the rows of a tall AF instruction that is not pinned.

    Return ``(new_count, consumed_rows)``.  Leave out only the padding rows at
    the end of its span.  Keep a padding row that has a non-padding row below
    it in the span, so that the lower row keeps its place on read.  A raw Drum
    has such a row when an unused pin row sits above a used one.
    """
    visual_rows = int(af.cell_params().get("visual_rows", 1))
    needed = start + visual_rows
    if len(condition_rows) < needed or len(af_tokens) < needed:
        raise WriterError(
            f"{type(af).__name__} requires {needed} decoded rows; got {len(condition_rows)}"
        )

    keep = _followed_by_floating_row(af_tokens, needed)
    last_content = max(
        (
            offset
            for offset in range(1, visual_rows)
            if not _is_padding_row(condition_rows[start + offset])
        ),
        default=0,
    )
    data_row_count = _append_data_row(rows, data_row_count, condition_rows[start], af)
    for offset in range(1, visual_rows):
        _require_blank_af(
            af_tokens[start + offset],
            message=f"{type(af).__name__} continuation row must be blank AF",
        )
        data_row_count = _emit_blank_continuation(
            rows, data_row_count, condition_rows[start + offset], keep or offset < last_content
        )
    return data_row_count, visual_rows


def _display_token(token: object) -> str:
    """Return a compact user-facing representation for mismatch errors."""
    try:
        return repr(_token_to_csv(token))
    except WriterError:
        return repr(token)


def _af_tokens_match(expected: object, actual: object) -> bool:
    """Return True if two AF tokens are equal, or if either is a ``RawInstruction``
    and both build the same blob and cell parameters."""
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


def _same_refusals(expected: object, actual: object) -> bool:
    """Return True if the token read back holds refusals of the same fields as the one written."""
    return [e.field for e in refusals(expected)] == [e.field for e in refusals(actual)]


def _rebuild_rung_from_rows(rows: Sequence[Sequence[str]], *, held: bool = False) -> Rung:
    """Read the CSV rows written for one rung back into a ``Rung``, as ``read_csv`` reads them.

    Pass *held* when the rung holds a refusal.  The rows are then read as
    ``read_csv(..., unchecked=True)`` reads them, so that an instruction that holds
    refusals reads back to one that holds the same refusals.
    """
    try:
        with unchecked() if held else nullcontext():
            rebuilt = convert_rung(_parse_single_rung_rows(rows))
    except (TypeError, ValueError) as exc:
        raise WriterError(
            f"CSV round-trip validation failed: emitted rows do not reparse: {exc}"
        ) from exc
    if len(rebuilt) != 1:
        raise WriterError(
            f"CSV round-trip validation failed: the rows read back as {len(rebuilt)} rungs"
        )
    return rebuilt[0]


def _validate_roundtrip(rung: Rung, rows: Sequence[Sequence[str]], *, exact: bool = False) -> None:
    """Raise ``WriterError`` if the CSV rows written for *rung* lose any of it on read.

    Pass ``exact`` for a rung in CLICK's layout.  Its rows must then read back to the rung
    itself.  Without ``exact``, if the read drops blank rows at the end of the rung, this
    only warns.
    """
    tokens = [*(t for row in rung.conditions for t in row), *rung.instructions]
    rebuilt = _rebuild_rung_from_rows(rows, held=any(refusals(t) for t in tokens))

    if rebuilt.logical_rows != rung.logical_rows:
        # Blank rows at the end of the rung, with no conditions and no AF, can be
        # lost on read.  A tall instruction whose padding rows were left out takes
        # them as its own rows.  The loss is cosmetic, so warn instead of failing.
        extra = rung.logical_rows - rebuilt.logical_rows
        if (
            not exact
            and extra > 0
            and all(
                _is_padding_row(rung.conditions[r]) and rung.instructions[r] == ""
                for r in range(rebuilt.logical_rows, rung.logical_rows)
            )
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
            if expected != actual or not _same_refusals(expected, actual):
                raise WriterError(
                    "CSV round-trip validation failed: "
                    f"condition mismatch at row {row_idx} col {CONDITION_COLUMNS[col_idx]}: "
                    f"expected {_display_token(expected)}, got {_display_token(actual)}"
                )

    for row_idx, (expected, actual) in enumerate(
        zip(rung.instructions[: rebuilt.logical_rows], rebuilt.instructions, strict=True),
        start=1,
    ):
        if not _af_tokens_match(expected, actual) or not _same_refusals(expected, actual):
            if (
                isinstance(expected, PinnedInstruction)
                and isinstance(actual, PinnedInstruction)
                and expected.pin_rows != actual.pin_rows
            ):
                raise WriterError(
                    "CSV round-trip validation failed: "
                    f"{_display_token(expected)} at row {row_idx} has its pins on rows "
                    f"{expected.pin_rows}, which read back as {actual.pin_rows}"
                )
            raise WriterError(
                "CSV round-trip validation failed: "
                f"AF mismatch at row {row_idx}: "
                f"expected {_display_token(expected)}, got {_display_token(actual)}"
            )


def decoded_rung_to_rows(rung: Rung) -> list[list[str]]:
    """Convert a ``Rung`` to a list of CSV row lists.

    Each data row is a list of 33 strings: [marker, A..AE, AF].  The first
    data row of a rung has the marker ``"R"``, and the rest have ``""``.  A
    comment row is ``["#", text]``, with the text in column A.

    When laddercodec can lay out the rung, it is written as CLICK's syntax
    check draws it.  If CLICK would split the rung, the rows hold one rung per
    part, each starting with an ``R`` row, and the comment goes on the first.
    A rung that has no layout keeps its cells where they are.  That happens
    when it holds only wires and unwired NOPs, when the layout cannot draw it,
    or when ``laddercodec.check()`` reports a finding other than an unwired
    box input or a contact that feeds only a NOP.

    The writer writes a pin row for each pin of a box that is in use, such as
    a retained timer's ``.reset()``.  The pin row goes on the row that the box's
    ``pin_rows`` gives for that pin, counted from the box's top row.  With the
    default ``pin_rows=(1,)``, a retained timer's ``.reset()`` row is the row
    below the timer.  A rung can hold several tall or pinned instructions, and
    each one reads back with all of its rows.
    """
    rows: list[list[str]] = []
    for part, exact in _drawn(rung):
        part_rows = _rung_rows(part)
        _validate_roundtrip(part, part_rows, exact=exact)
        rows.extend(part_rows)
    return rows


def _drawn(rung: Rung) -> list[tuple[Rung, bool]]:
    """Return the rungs to write for *rung*, each with whether it is in CLICK's layout."""
    parts = canonical(rung)
    if parts is None:
        return [(rung, False)]
    if parts != [rung]:
        try:
            same = circuit(parts) == circuit([rung])
        except LayoutError as exc:
            raise WriterError(f"CSV layout changed the rung's circuit: {exc}") from exc
        if not same:
            raise WriterError("CSV layout changed the rung's circuit")
    return [(part, True) for part in parts]


def _rung_rows(rung: Rung) -> list[list[str]]:
    """Return the CSV rows for *rung*, its comment rows first."""
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

    return rows


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


def write_csv(
    path: Path | str,
    rungs: list[Rung],
    *,
    index: bool = False,
    stop: Stop = "end",
) -> None:
    """Write decoded rungs to a canonical CSV file.

    When laddercodec can lay out a rung, it is written as CLICK's syntax check
    draws it.  If CLICK would split a rung, the file holds the rungs it splits
    into, so the file can hold more rungs than *rungs*.  A rung that has no
    layout is written with its cells where they are (see
    :func:`decoded_rung_to_rows`).

    No CSV token can hold the bytes of an unknown condition or instruction.
    A rung that holds one is written as an undecoded marker rung, with an
    ``UndecodedRungWarning``.

    Parameters
    ----------
    path:
        Output file path.
    rungs:
        One or more decoded rungs, such as the list ``decode()`` returns.
    index:
        When ``True``, each rung's ``R`` marker gets the rung's number, counted
        from 1 across the whole file: ``R1``, ``R2``, ``R3`` and so on.  The
        default, ``False``, writes a plain ``R``.  ``read_csv()`` ignores the
        digits, so an indexed file reads back the same.
    stop:
        Whether the marker that stands in for a rung with an unknown token acts as
        ``end()`` or as ``return()``.  Pass ``"end"`` in the main program and
        ``"return"`` in a subroutine.

    Raises
    ------
    WriterError
        If *stop* is neither ``"end"`` nor ``"return"`` (nothing is written), or if a
        rung can't be written, such as one whose shape the CSV can't hold.
    """
    if stop not in get_args(Stop):
        raise WriterError(f"write_csv: stop={stop!r} must be 'end' or 'return'")
    path = Path(path)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv_mod.writer(f)
        writer.writerow(CSV_HEADER)
        rung_number = 0  # Counts the rungs written. A rung CLICK would split counts as several.
        for rung_index, rung in enumerate(rungs):
            unknown = _unknown_cell(rung)
            if unknown is None:
                rows = decoded_rung_to_rows(rung)
            else:
                row, column, error = unknown
                marker = Undecoded(error, rung_index, row, column, stop)
                warnings.warn(UndecodedRungWarning(marker), stacklevel=2)
                rows = decoded_rung_to_rows(marker_rung(marker, rung.comment))
            for row in rows:
                if row and row[0] == "R":
                    rung_number += 1
                    if index:
                        row = [f"R{rung_number}", *row[1:]]
                writer.writerow(row)


def _unknown_cell(rung: Rung) -> tuple[int, int, str] | None:
    """Return ``(row, column, error)`` for the first unknown condition or instruction in *rung*.

    ``row`` and ``column`` count from 0.  Return None if *rung* holds no unknown token.
    """
    for row, (conditions, af) in enumerate(zip(rung.conditions, rung.instructions, strict=False)):
        cells = [*enumerate(conditions), (len(CONDITION_COLUMNS), af)]
        for column, token in cells:
            if isinstance(token, (UnknownCondition, UnknownInstruction)):
                kind = "condition" if isinstance(token, UnknownCondition) else "instruction"
                return (
                    row,
                    column,
                    f"no CSV token holds this unknown {kind} ({len(token.raw)} bytes)",
                )
    return None
