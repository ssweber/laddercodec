"""Functions that check a rung and build its cell grid, for both encoders.

``encode.py`` encodes one rung and ``encode_multi.py`` encodes several.  Each one writes
its own headers, comments and page padding, and calls these functions for the grid.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from .cell import ClickCell, build_row
from .csv.contract import CONDITION_COLUMNS as _COLUMN_NAMES
from .encode import (
    _TOKEN_FLAGS,
    MAX_ROWS,
    MIN_ROWS,
    SUPPORTED_CONDITION_TOKENS,
    AfToken,
    ConditionToken,
    _af_segment,
    _compute_seg_boundaries,
    _normalize_af,
)
from .errors import EncodeError
from .instructions import (
    AfInstruction,
    ConditionInstruction,
    Tee,
    Undecoded,
    UnknownCondition,
    UnknownInstruction,
)
from .operands.unchecked import refusals, stored_blob, stored_cell_rows
from .topology import COLS_PER_ROW, CONDITION_COLUMNS

# ---------------------------------------------------------------------------
# 5a: Shared validation
# ---------------------------------------------------------------------------


def _check_instruction(token: ConditionInstruction | AfInstruction) -> None:
    """Refuse a value in *token* that CLICK's dialog refuses.

    A decoded instruction that holds the blob it was read from is not checked.
    ``encode()`` writes those bytes, as it does for a ``RawInstruction``.

    Any other instruction is checked.  An instruction built from stored data can hold the
    refusals that its construction would raise (see ``laddercodec.operands.unchecked``).
    The function raises the first of them.  This way ``encode()`` writes only values that
    construction accepts.
    """
    if stored_blob(token) is not None:
        return
    found = refusals(token)
    if found:
        raise found[0].with_traceback(None)


def _cell_contact(token: ConditionToken) -> str | ConditionInstruction:
    """Return the contact inside a ``Tee``, or *token* itself if it is not a ``Tee``.

    ``_validate_rung`` refuses an ``UnknownCondition``, inside a ``Tee`` or not, before
    the grid is built.
    """
    if not isinstance(token, Tee):
        return token
    return cast("ConditionInstruction", token.contact)


def _check_tee(tee: Tee, row_idx: int, col_idx: int, logical_rows: int, prefix: str) -> None:
    """Raise :class:`EncodeError` if *tee* is in column A or on the rung's last row.

    A ``Tee`` has a wire down, so the same rules hold for it as for ``"T"`` and ``"|"``.
    """
    contact = tee.contact
    text = (
        tee.to_csv()
        if isinstance(contact, ConditionInstruction)
        else f"Tee({type(contact).__name__})"
    )
    where = f"{prefix}Row {row_idx}, column {_COLUMN_NAMES[col_idx]}: {text} has a wire down"
    if col_idx == 0:
        raise EncodeError(
            f"{where}, and column A can't hold one. Put the contact in column A without a Tee."
        )
    if row_idx == logical_rows - 1:
        raise EncodeError(
            f"{where} on the rung's last row, where the wire has no row to reach. Write the "
            "contact without a Tee, or add a row below it."
        )


def _validate_rung(
    logical_rows: int,
    condition_rows: Sequence[Sequence[ConditionToken]],
    af_tokens: Sequence[AfToken],
    label: str = "",
) -> None:
    """Validate rung dimensions, tokens, and NOP count.

    Parameters
    ----------
    label:
        Prefix for error messages, such as ``"Rung 1"``.  A message then starts
        with ``"Rung 1: "``.
    """
    prefix = f"{label}: " if label else ""

    if not (MIN_ROWS <= logical_rows <= MAX_ROWS):
        fix = (
            "Split it into rungs of 32 rows or fewer."
            if logical_rows > MAX_ROWS
            else "Pass conditions as one list of 31 tokens per row, such as [['-'] * 31]."
        )
        raise EncodeError(
            f"{prefix}A rung has {MIN_ROWS} to {MAX_ROWS} rows. This one has {logical_rows}. {fix}"
        )
    rows = f"{logical_rows} row{'' if logical_rows == 1 else 's'}"
    if len(condition_rows) != logical_rows:
        raise EncodeError(
            f"{prefix}The rung has {rows}, and conditions has {len(condition_rows)}. "
            "Pass one list of 31 tokens per row."
        )
    if len(af_tokens) != logical_rows:
        tokens = f"{len(af_tokens)} token{'' if len(af_tokens) == 1 else 's'}"
        raise EncodeError(
            f"{prefix}The rung has {rows}, and instructions has {tokens}. Pass one AF "
            "token per row, with '' for a row that has no instruction."
        )

    for row_idx, row in enumerate(condition_rows):
        if len(row) != CONDITION_COLUMNS:
            raise EncodeError(
                f"{prefix}Row {row_idx}: expected {CONDITION_COLUMNS} columns, got {len(row)}"
            )
        for col_idx, token in enumerate(row):
            if isinstance(token, Tee):
                _check_tee(token, row_idx, col_idx, logical_rows, prefix)
                token = token.contact
            if isinstance(token, UnknownCondition):
                raise EncodeError(
                    f"{prefix}Unknown condition at row={row_idx}, col={col_idx}: "
                    "laddercodec can't write an instruction it couldn't read. Replace the "
                    "cell, or remove it."
                )
            if isinstance(token, ConditionInstruction):
                _check_instruction(token)
                continue
            if token not in SUPPORTED_CONDITION_TOKENS:
                raise EncodeError(
                    f"{prefix}Unsupported token {token!r} at row={row_idx}, col={col_idx}. "
                    "Use a contact, or one of '', '-', '|' or 'T'."
                )
            if col_idx == 0 and token in ("|", "T"):
                raise EncodeError(
                    f"{prefix}Vertical-down tokens are not allowed in column A "
                    f"(row={row_idx}, token={token!r})"
                )
            if row_idx == logical_rows - 1 and token in ("|", "T"):
                raise EncodeError(
                    f"{prefix}Vertical-down tokens are not allowed on the last row "
                    f"(row={row_idx}, col={col_idx}, token={token!r})"
                )

    for row_idx, af in enumerate(af_tokens):
        if isinstance(af, UnknownInstruction):
            raise EncodeError(
                f"{prefix}Unknown instruction at row={row_idx}, AF: "
                "laddercodec can't write an instruction it couldn't read. Replace the "
                "instruction, or remove it."
            )
        if isinstance(af, Undecoded):
            raise EncodeError(f"{prefix}Row {row_idx}, AF: {af.refusal()}")
        if isinstance(af, AfInstruction):
            _check_instruction(af)

    nop_count = sum(1 for af in af_tokens if _normalize_af(af) == "NOP")
    if nop_count > 1:
        raise EncodeError(f"{prefix}Only one NOP per rung is allowed (got {nop_count})")


# ---------------------------------------------------------------------------
# 5b: Shared metadata computation
# ---------------------------------------------------------------------------


@dataclass
class RungMetadata:
    """Facts about one rung that are computed once, before its cell grid is built."""

    rung_has_instructions: bool
    total_instr_count: int
    cond_instr_indices: dict[tuple[int, int], int]
    af_instr_indices: dict[int, int]
    seg_boundaries: list[int] | None


def _compute_rung_metadata(
    logical_rows: int,
    condition_rows: Sequence[Sequence[ConditionToken]],
    af_tokens: Sequence[AfToken],
) -> RungMetadata:
    """Compute instruction indices and segment boundaries."""
    rung_has_instructions = any(
        isinstance(_cell_contact(t), ConditionInstruction) for row in condition_rows for t in row
    ) or any(isinstance(af, AfInstruction) for af in af_tokens)

    total_instr_count = sum(
        1
        for row in condition_rows
        for t in row
        if isinstance(_cell_contact(t), ConditionInstruction)
    ) + sum(1 for af in af_tokens if isinstance(af, AfInstruction))

    # Number the condition instructions first, row by row, then the AF instructions.
    cond_instr_indices: dict[tuple[int, int], int] = {}
    af_instr_indices: dict[int, int] = {}
    idx = 0
    for row_idx in range(logical_rows):
        for col_idx, tok in enumerate(condition_rows[row_idx]):
            if isinstance(_cell_contact(tok), ConditionInstruction):
                cond_instr_indices[(row_idx, col_idx)] = idx
                idx += 1
    for row_idx in range(logical_rows):
        af = af_tokens[row_idx]
        if isinstance(af, AfInstruction):
            af_instr_indices[row_idx] = idx
            idx += 1

    seg_boundaries = _compute_seg_boundaries(condition_rows) if rung_has_instructions else None

    return RungMetadata(
        rung_has_instructions=rung_has_instructions,
        total_instr_count=total_instr_count,
        cond_instr_indices=cond_instr_indices,
        af_instr_indices=af_instr_indices,
        seg_boundaries=seg_boundaries,
    )


# ---------------------------------------------------------------------------
# 5c: Shared grid-building loop
# ---------------------------------------------------------------------------


def _build_rung_grid(
    logical_rows: int,
    condition_rows: Sequence[Sequence[ConditionToken]],
    af_tokens: Sequence[AfToken],
    meta: RungMetadata,
    global_row_start: int,
    rung_idx: int,
    is_last_rung: bool,
    single_rung: bool,
    *,
    show_nicknames: bool = False,
) -> bytearray:
    """Build the cell grid bytes for one rung.

    Returns the concatenated grid rows as a bytearray.
    """
    grid = bytearray()

    for local_row in range(logical_rows):
        g = global_row_start + local_row
        cond_row = condition_rows[local_row]
        af = af_tokens[local_row]
        af_kind = _normalize_af(af)
        has_nop = af_kind == "NOP"
        cells: list[bytes] = []
        seg_bound = meta.seg_boundaries[local_row] if meta.seg_boundaries else 0

        for col_idx in range(COLS_PER_ROW):
            if col_idx < CONDITION_COLUMNS:
                token = cond_row[col_idx]
                # A Tee writes the cell of the contact inside it, with the down flag set.
                tee_down = isinstance(token, Tee)
                token = _cell_contact(token)
                # An instruction's segment flag is 1 on row 0.  On a later row it is 0 left
                # of the row's segment boundary, and 1 at or right of the boundary.
                seg = 1 if col_idx >= seg_bound else (0 if local_row > 0 and seg_bound > 0 else 1)
                if isinstance(token, ConditionInstruction):
                    blob = token.build_blob()
                    params = token.cell_params()
                    cells.append(
                        ClickCell(
                            col=col_idx,
                            global_row=g,
                            rung_idx=rung_idx,
                            local_row=local_row,
                            logical_rows=logical_rows,
                            is_last_rung=is_last_rung,
                            single_rung=single_rung,
                            is_contact=params["is_contact"],
                            rung_has_instructions=meta.rung_has_instructions,
                            segment=seg,
                            wire_right=1,
                            wire_down=1 if tee_down else 0,
                            instr_index=meta.cond_instr_indices[(local_row, col_idx)],
                            blob=blob,
                        ).to_bytes()
                    )
                else:
                    seg, right, down = _TOKEN_FLAGS[token]
                    # On a later row, clear the segment flag left of the segment boundary.
                    if seg and local_row > 0 and seg_bound > 0 and col_idx < seg_bound:
                        seg = 0
                    cells.append(
                        ClickCell(
                            col=col_idx,
                            global_row=g,
                            rung_idx=rung_idx,
                            local_row=local_row,
                            logical_rows=logical_rows,
                            is_last_rung=is_last_rung,
                            single_rung=single_rung,
                            rung_has_instructions=meta.rung_has_instructions,
                            segment=seg,
                            wire_right=right,
                            wire_down=down,
                            row_start_flag=1
                            if (
                                has_nop
                                and local_row > 0
                                and col_idx == 0
                                and not meta.rung_has_instructions
                            )
                            else 0,
                        ).to_bytes()
                    )
            else:  # AF column (col 31)
                if isinstance(af, AfInstruction):
                    from .instructions.math import Math

                    blob = (
                        af.build_blob(show_nicknames=show_nicknames)
                        if isinstance(af, Math)
                        else af.build_blob()
                    )
                    # A decoded instruction that writes its stored blob also writes the cell
                    # row counts that were stored with it.
                    params = {**af.cell_params(), **stored_cell_rows(af)}
                    is_multi_row = params.get("visual_rows", 1) > 1
                    cells.append(
                        ClickCell(
                            col=col_idx,
                            global_row=g,
                            rung_idx=rung_idx,
                            local_row=local_row,
                            logical_rows=logical_rows,
                            is_last_rung=is_last_rung,
                            single_rung=single_rung,
                            is_contact=False,
                            rung_has_instructions=meta.rung_has_instructions,
                            segment=_af_segment(local_row, is_multi_row, single_rung),
                            wire_right=int(params.get("wire_right", 1)),
                            instr_index=meta.af_instr_indices[local_row],
                            blob=blob,
                            row_span=params.get("visual_rows", 1),
                            visual_rows=params.get("sub_rows", params.get("visual_rows", 1)),
                        ).to_bytes()
                    )
                else:
                    cells.append(
                        ClickCell(
                            col=col_idx,
                            global_row=g,
                            rung_idx=rung_idx,
                            local_row=local_row,
                            logical_rows=logical_rows,
                            is_last_rung=is_last_rung,
                            single_rung=single_rung,
                            rung_has_instructions=meta.rung_has_instructions,
                            segment=1 if has_nop else 0,
                            af_nop=1 if has_nop else 0,
                            instr_count=meta.total_instr_count,
                        ).to_bytes()
                    )

        grid += build_row(cells)

    return grid
