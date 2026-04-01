"""Shared grid-building functions for single-rung and multi-rung encoders.

Extracted from ``encode.py`` and ``encode_multi.py`` to eliminate
duplication.  Both encoders delegate to these functions after
orchestrating headers, comments, and page padding.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .cell import ClickCell, build_row

# Imports from encode.py — constants and helpers that stay there.
from .encode import (
    _TOKEN_FLAGS,
    MAX_ROWS,
    MIN_ROWS,
    SUPPORTED_CONDITION_TOKENS,
    AfToken,
    ConditionToken,
    _af_segment,
    _build_af_summary,
    _compute_seg_boundaries,
    _normalize_af,
)
from .instructions import AfInstruction, ConditionInstruction
from .topology import COLS_PER_ROW, CONDITION_COLUMNS

# ---------------------------------------------------------------------------
# 5a: Shared validation
# ---------------------------------------------------------------------------


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
        Prefix for error messages (e.g. ``"Rung 1, "``).
    """
    prefix = f"{label}: " if label else ""

    if not (MIN_ROWS <= logical_rows <= MAX_ROWS):
        raise ValueError(f"{prefix}logical_rows must be {MIN_ROWS}..{MAX_ROWS}, got {logical_rows}")
    if len(condition_rows) != logical_rows:
        raise ValueError(
            f"{prefix}Expected {logical_rows} condition rows, got {len(condition_rows)}"
        )
    if len(af_tokens) != logical_rows:
        raise ValueError(f"{prefix}Expected {logical_rows} AF tokens, got {len(af_tokens)}")

    for row_idx, row in enumerate(condition_rows):
        if len(row) != CONDITION_COLUMNS:
            raise ValueError(
                f"{prefix}Row {row_idx}: expected {CONDITION_COLUMNS} columns, got {len(row)}"
            )
        for col_idx, token in enumerate(row):
            if isinstance(token, ConditionInstruction):
                continue
            if token not in SUPPORTED_CONDITION_TOKENS:
                raise ValueError(
                    f"{prefix}Unsupported token {token!r} at row={row_idx}, col={col_idx}"
                )
            if col_idx == 0 and token in ("|", "T"):
                raise ValueError(
                    f"{prefix}Vertical-down tokens are not allowed in column A "
                    f"(row={row_idx}, token={token!r})"
                )
            if row_idx == logical_rows - 1 and token in ("|", "T"):
                raise ValueError(
                    f"{prefix}Vertical-down tokens are not allowed on the last row "
                    f"(row={row_idx}, col={col_idx}, token={token!r})"
                )

    nop_count = sum(1 for af in af_tokens if _normalize_af(af) == "NOP")
    if nop_count > 1:
        raise ValueError(f"{prefix}Only one NOP per rung is allowed (got {nop_count})")


# ---------------------------------------------------------------------------
# 5b: Shared metadata computation
# ---------------------------------------------------------------------------


@dataclass
class RungMetadata:
    """Pre-computed metadata for a single rung's grid building."""

    rung_has_instructions: bool
    total_instr_count: int
    cond_instr_indices: dict[tuple[int, int], int]
    af_instr_indices: dict[int, int]
    af_summary_block: bytes
    seg_boundaries: list[int] | None


def _compute_rung_metadata(
    logical_rows: int,
    condition_rows: Sequence[Sequence[ConditionToken]],
    af_tokens: Sequence[AfToken],
    *,
    single_rung: bool = True,
) -> RungMetadata:
    """Compute instruction indices, summary block, and segment boundaries.

    The AF summary block is only computed for single-rung buffers.
    """
    rung_has_instructions = any(
        isinstance(t, ConditionInstruction) for row in condition_rows for t in row
    ) or any(isinstance(af, AfInstruction) for af in af_tokens)

    total_instr_count = sum(
        1 for row in condition_rows for t in row if isinstance(t, ConditionInstruction)
    ) + sum(1 for af in af_tokens if isinstance(af, AfInstruction))

    # Pre-compute instruction indices: conditions first, then AFs.
    cond_instr_indices: dict[tuple[int, int], int] = {}
    af_instr_indices: dict[int, int] = {}
    idx = 0
    for row_idx in range(logical_rows):
        for col_idx, tok in enumerate(condition_rows[row_idx]):
            if isinstance(tok, ConditionInstruction):
                cond_instr_indices[(row_idx, col_idx)] = idx
                idx += 1
    for row_idx in range(logical_rows):
        af = af_tokens[row_idx]
        if isinstance(af, AfInstruction):
            af_instr_indices[row_idx] = idx
            idx += 1

    # AF summary block — needed on the last AF instruction cell when 2+ AFs
    # (single-rung only; multi-rung does not use af_summary).
    af_summary_block = b""
    af_rows = sorted(af_instr_indices.keys())
    if single_rung and len(af_rows) >= 2:
        af_entries: list[tuple[int, int, bool]] = []
        for r in af_rows:
            cond_count = sum(1 for t in condition_rows[r] if isinstance(t, ConditionInstruction))
            instrs_on_row = cond_count + 1  # +1 for the AF instruction itself
            row_has_contact = cond_count > 0
            af_entries.append((af_instr_indices[r], instrs_on_row, row_has_contact))
        af_summary_block = _build_af_summary(total_instr_count, len(af_rows), af_entries)

    seg_boundaries = _compute_seg_boundaries(condition_rows) if rung_has_instructions else None

    return RungMetadata(
        rung_has_instructions=rung_has_instructions,
        total_instr_count=total_instr_count,
        cond_instr_indices=cond_instr_indices,
        af_instr_indices=af_instr_indices,
        af_summary_block=af_summary_block,
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
    af_rows = sorted(meta.af_instr_indices.keys())

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
                # Segment flag: on row 0, always 1 for non-blank.
                # On row 1+, 0 below boundary, 1 at/above boundary.
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
                            wire_down=params["wire_down"],
                            instr_index=meta.cond_instr_indices[(local_row, col_idx)],
                            blob=blob,
                        ).to_bytes()
                    )
                else:
                    seg, right, down = _TOKEN_FLAGS[token]
                    # Apply segment boundary on row 1+.
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
                            nop_enable=1
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
                is_last_af = af_rows and local_row == af_rows[-1]
                summary = meta.af_summary_block if is_last_af else b""
                if isinstance(af, AfInstruction):
                    from .instructions.math import Math

                    blob = (
                        af.build_blob(show_nicknames=show_nicknames)
                        if isinstance(af, Math)
                        else af.build_blob()
                    )
                    params = af.cell_params()
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
                            visual_rows=params.get("visual_rows", 1),
                            af_summary=summary,
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
