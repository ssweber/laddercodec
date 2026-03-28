"""Multi-rung buffer encoder.

Combines N pre-specified rungs into one multi-rung clipboard buffer.

Pipeline
--------

    1. Header    — load from single-rung template, patch row_word
    2. Grid      — build cell objects per row (data + preamble + terminal),
                   concatenate to form grid bytes
    3. Assemble  — header[:0x0A60] + grid_bytes
    4. Comments  — insert per-rung RTF payloads back-to-front
    5. Pad       — to next 0x1000 page boundary

Rung preamble
-------------

Each rung has a 0x40-byte preamble that precedes its data rows.
Rung 0's preamble starts at 0x0260, immediately after the program
header (0x0254–0x025F).  It is copied from the template, not in the
cell grid.  Rung N>0's preamble is cell 0 of its preamble row in
the grid.

Both share the same comment layout at fixed offsets from preamble base:

    +0x30   comment flag (0x01 = has comment data)
    +0x34   comment payload length (4 bytes LE)
    +0x38   comment payload body (RTF bytes)

For single-rung encoding, these correspond to the existing constants
PAYLOAD_LENGTH_OFFSET (0x0294 = 0x0260+0x34) and
PAYLOAD_BYTES_OFFSET  (0x0298 = 0x0260+0x38).

Grid layout (1-row rungs shown; multi-row rungs span multiple rows)
-------------------------------------------------------------------

    row 0        rung 0 data       (preamble at 0x0260, not in grid)
    row 1        rung 1 preamble
    row 2        rung 1 data
    row 3        rung 2 preamble   (if 3+ rungs)
    ...
    last row     terminal

Key cell field differences from single-rung
--------------------------------------------

    +0x05   global 1-based row (not local)
    +0x30   1 on preamble rows (load-bearing for comment detection)
    +0x38   0 only on last rung's col31; 1 everywhere else
    +0x39   load-bearing rung index (confirmed via bisect 2026-03-12):
              data rows       col 0..30: rung_idx
                              col31:     0 if last rung, else rung_idx+1
              preamble rows   all cols:  rung_idx+1
    +0x3D   0 on data row col31; 1 on preamble col31  (untested, kept)

Fields present in native captures but confirmed cosmetic (not written):
    +0x0B = 0x30   multi-rung marker on every cell
    +0x15 = 1      rung-start flag on col0 of rung rows
    PH+0x17 = 0x30 multi-rung type flag in program header

Terminal row bytes +0x01..+0x04 match native captures but are untested;
kept for fidelity. +0x05=0xFF is the sentinel Click uses to detect the row.
"""

from __future__ import annotations

from collections.abc import Sequence

from ._grid import _build_rung_grid, _compute_rung_metadata, _validate_rung
from .cell import (
    build_preamble_cell,
    build_row,
    build_terminal_cell,
)
from .empty_multirow import synthesize_empty_multirow
from .encode import (
    _PREFIX,
    _SUFFIX,
    COMMENT_MAX_BYTES,
    _build_rtf_body,
)
from .topology import (
    COLS_PER_ROW,
    GRID_FIRST_ROW_START,
    PREAMBLE_COMMENT_BODY,
    PREAMBLE_COMMENT_LENGTH,
    PROGRAM_HEADER_BASE,
    RUNG0_PREAMBLE_BASE,
)

_PAGE_SIZE = 0x1000

from .encode import AfToken, ConditionToken

RungInput = tuple[int, Sequence[Sequence[ConditionToken]], Sequence[AfToken]]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def encode_rungs(
    rungs: Sequence[RungInput],
    comments: Sequence[str | None] | None = None,
) -> bytes:
    """Combine N rungs into one multi-rung clipboard buffer.

    Parameters
    ----------
    rungs:
        Sequence of ``(logical_rows, condition_rows, af_tokens)`` tuples,
        one per rung — the same arguments as ``encode_rung()``.
        Minimum 2 rungs required.
    comments:
        Optional sequence of per-rung comments, one per rung.  Each entry
        is either a comment string or ``None`` / ``""`` for no comment.
        If the sequence itself is ``None``, no rungs get comments.

        Comment text supports inline styles (markdown syntax):
            ``**text**``  → bold
            ``__text__``  → underline
            ``*text*``    → italic (asterisk)
            ``_text_``    → italic (underscore)
        Line breaks: ``\\n`` becomes an RTF paragraph break (``\\par``).

    Returns
    -------
    bytes
        Encoded multi-rung binary payload ready for clipboard paste.
    """
    N = len(rungs)
    if N < 2:
        raise ValueError(f"encode_rungs requires at least 2 rungs, got {N}")

    # Normalise comments to a list aligned with rungs.
    if comments is None:
        comments_list: list[str | None] = [None] * N
    else:
        if len(comments) != N:
            raise ValueError(f"comments length ({len(comments)}) must match rungs length ({N})")
        comments_list = list(comments)

    # --- Validate ---
    for r_idx, (logical_rows, condition_rows, af_tokens) in enumerate(rungs):
        _validate_rung(logical_rows, condition_rows, af_tokens, label=f"Rung {r_idx}")

    # Validate comment lengths up front.
    for r_idx, cmt in enumerate(comments_list):
        if cmt is not None and cmt != "":
            encoded = _build_rtf_body(cmt).encode("cp1252")
            if len(encoded) > COMMENT_MAX_BYTES:
                raise ValueError(
                    f"Rung {r_idx}: comment body exceeds {COMMENT_MAX_BYTES} bytes "
                    f"after RTF encoding (got {len(encoded)})"
                )

    # --- Step 1: Header — load template, patch row_word ---

    total_rung_rows = sum(lr for lr, _, _ in rungs)
    total_grid_rows = total_rung_rows + N  # data rows + (N-1 preamble rows + 1 terminal)
    row_word = total_grid_rows * 0x20

    template = synthesize_empty_multirow(1)
    out = bytearray(template[:GRID_FIRST_ROW_START])
    out[PROGRAM_HEADER_BASE + 0x00] = row_word & 0xFF
    out[PROGRAM_HEADER_BASE + 0x01] = (row_word >> 8) & 0xFF

    # --- Step 2: Grid — build cell objects, concatenate ---

    grid = bytearray()
    preamble_bases: list[int] = [RUNG0_PREAMBLE_BASE]
    global_row = 0

    for r_idx, (logical_rows, condition_rows, af_tokens) in enumerate(rungs):
        is_last = r_idx == N - 1

        meta = _compute_rung_metadata(logical_rows, condition_rows, af_tokens, single_rung=False)
        grid += _build_rung_grid(
            logical_rows,
            condition_rows,
            af_tokens,
            meta,
            global_row_start=global_row,
            rung_idx=r_idx,
            is_last_rung=is_last,
            single_rung=False,
        )

        global_row += logical_rows

        # Preamble row for the next rung (if not last).
        if not is_last:
            preamble_bases.append(GRID_FIRST_ROW_START + len(grid))
            cells = [build_preamble_cell(col, global_row, r_idx) for col in range(COLS_PER_ROW)]
            grid += build_row(cells)
            global_row += 1

    # Terminal row.
    cells = [build_terminal_cell() for _ in range(COLS_PER_ROW)]
    grid += build_row(cells)

    # --- Step 3: Assemble header + grid ---

    out += grid

    # --- Step 4: Comments — insert back-to-front ---

    any_comment = any(c is not None and c != "" for c in comments_list)
    if any_comment:
        # Process in reverse order so earlier inserts don't shift later
        # rung addresses.
        for r_idx in range(N - 1, -1, -1):
            cmt = comments_list[r_idx]
            if cmt is None or cmt == "":
                continue

            payload = _PREFIX + _build_rtf_body(cmt).encode("cp1252") + _SUFFIX
            preamble = preamble_bases[r_idx]
            insert_offset = preamble + PREAMBLE_COMMENT_BODY
            length_offset = preamble + PREAMBLE_COMMENT_LENGTH

            # Slice-insert pushes everything at insert_offset+ forward.
            out[insert_offset:insert_offset] = payload
            out[length_offset : length_offset + 4] = len(payload).to_bytes(4, "little")

    # --- Step 5: Pad to page boundary ---

    remainder = len(out) % _PAGE_SIZE
    if remainder:
        out += b"\x00" * (_PAGE_SIZE - remainder)

    return bytes(out)
