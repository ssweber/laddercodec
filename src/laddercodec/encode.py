"""Ladder rung encoder — unified pipeline.

Definitions
-----------

Rung:
    One logical unit of ladder logic. A rung has 1..32 rows, each with
    31 condition columns (A..AE) and 1 output column (AF). The rung may
    also carry a single plain-text comment.

Row:
    A horizontal slice of the rung grid. Row 0 is the topmost visible
    row. The grid starts at absolute offset 0x0A60 with a stride of
    0x800 per row (32 columns x 64 bytes per cell).

Cell:
    A 64-byte (0x40) block within the grid. Addressed by (row, column).
    Contains wire flags, structural control bytes, and (for instruction-
    bearing rungs) stream-placement metadata.

Wire topology:
    The arrangement of horizontal wires ("-"), vertical pass-throughs
    ("|"), and junction-down points ("T") across the condition grid.
    Encoded via three per-cell flag bytes: +0x19 (segment), +0x1D
    (right), +0x21 (down). Conditions also set these flags (like "-").

Condition:
    An instruction placed on a condition column (A..AE).  Includes
    ``Contact`` (NO/NC/edge) and ``CompareContact`` (GT/GE/LT/LE/EQ/NE).
    Condition cells are variable-length: a 0x25-byte header (wire flags,
    column, row, instruction index) followed by an instruction blob
    (class name, type marker, operand, func_code).  Passed as
    ``Contact`` or ``CompareContact`` objects in the condition_rows grid.

NOP:
    The simplest AF-column instruction. At most one per rung. Encoded
    via a minimal byte model: col31 +0x1D = 1 (all rows), plus col0
    +0x15 = 1 for non-first rows. Does not require an instruction stream
    entry.

Comment:
    Plain-text annotation on a rung. Stored as an RTF envelope (fixed
    prefix + cp1252 body + fixed suffix) in the payload region at
    0x0298. The 4-byte payload length sits at 0x0294. The cell grid
    (always at 0x0A60 in a no-payload buffer) is pushed forward by
    payload_len bytes after insertion. Max 1400 bytes.

Page:
    A 0x1000 (4096) byte allocation unit. Buffer size is:
    pad_to_page(0x0A60 + logical_rows * 0x800 + payload_len).

Program header:
    A single 0x40-byte structure at 0x0254. Contains the row-count
    word (+0x00/+0x01 = (rows+1)*0x20) and other GUI state. Not a
    32-entry table — the range 0x0294–0x0A5F is the payload region.


Supported checklist
-------------------

Verified in Click (encode → paste → copy back → decode round-trip):

    [x] Empty rung, 1..32 rows
    [x] Wire topology, 1..32 rows (-, |, T in any valid position)
    [x] NOP on any row (with col0 +0x15 enable for non-first rows)
    [x] Plain comment, 1-row (empty, wire, NOP, max 1400 bytes)
    [x] Plain comment, 2-row (empty, NOP, wire incl. col-A, max 1324)
    [x] Plain comment, 3-row (empty, NOP, wire, mixed, max 1400)
    [x] Plain comment, 4..32 rows (wire combos, scaling)
    [x] Multi-line comment (\\n → \\par; verified 2026-03-12)
    [x] Styled comments (bold/italic/underline via markdown → RTF groups; verified 2026-03-12)
    [x] Contacts (NO, NC, edge, immediate — via Contact objects in condition_rows)
    [x] Coils (out, latch, reset, immediate, range — via Coil objects in af_tokens)
    [x] Comparison contacts (GT, GE, LT, LE, EQ, NE — via CompareContact objects)
    [x] Timers (on_delay, off_delay, retentive — via Timer objects in af_tokens)
    [ ] Full AF instruction set (counters, math, etc.)


Pipeline steps
--------------

    1. Header   — load from synthesize_empty_multirow (includes row_word)
    2. Grid     — build 32 cell objects per row (wire flags + NOP baked
                  in), concatenate to form the grid bytes
    3. Assemble — header[:0x0A60] + grid_bytes
    4. Comment  — assemble RTF, insert at 0x0298, push grid forward
    5. Pad      — to next 0x1000 page boundary

Cell objects are bytes blobs built by ``ClickCell.to_bytes()``.
Wire cells are 0x40 bytes.  Instruction cells (contacts, coils, timers)
are larger, and the concatenation model handles variable-length cells
naturally — no fixed-offset assumptions in the grid.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .cell import (
    ClickCell,
    build_coil_blob,
    build_compare_blob,
    build_contact_blob,
    build_row,
    build_timer_blob,
)
from .empty_multirow import synthesize_empty_multirow
from .instructions import Coil, CompareContact, Contact, RawInstruction, Timer
from .topology import (
    COLS_PER_ROW,
    GRID_FIRST_ROW_START,
    PREAMBLE_COMMENT_BODY,
    PREAMBLE_COMMENT_LENGTH,
    RUNG0_PREAMBLE_BASE,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Rung 0 comment offsets — derived from preamble layout.
PAYLOAD_LENGTH_OFFSET = RUNG0_PREAMBLE_BASE + PREAMBLE_COMMENT_LENGTH  # 0x0294
PAYLOAD_BYTES_OFFSET = RUNG0_PREAMBLE_BASE + PREAMBLE_COMMENT_BODY  # 0x0298
COMMENT_MAX_BYTES = 1400

CONDITION_COLUMNS = COLS_PER_ROW - 1  # A..AE (31 columns)
AF_COLUMN = COLS_PER_ROW - 1  # Column AF (index 31)

MIN_ROWS = 1
MAX_ROWS = 32

# Token → (segment, horizontal_right, vertical_down)
_TOKEN_FLAGS: dict[str, tuple[int, int, int]] = {
    "": (0, 0, 0),
    "-": (1, 1, 0),
    "|": (0, 0, 1),
    "T": (1, 1, 1),
}

SUPPORTED_CONDITION_TOKENS = frozenset(_TOKEN_FLAGS)

#: A condition-column token: wire string, Contact, or CompareContact object.
ConditionToken = str | Contact | CompareContact

#: An AF-column token: ``""`` / ``"NOP"`` string, Coil, Timer, or RawInstruction.
AfToken = str | Coil | Timer | RawInstruction

# RTF comment envelope — from native capture.
# Prefix (105 bytes) + cp1252 body + suffix (11 bytes).
_PREFIX = (
    b"{\\rtf1\\ansi\\ansicpg1252\\deff0\\deflang1033"
    b"{\\fonttbl{\\f0\\fnil\\fcharset0 Arial;}}\r\n"
    b"\\viewkind4\\uc1\\pard\\fs20 "
)
_SUFFIX = b"\r\n\\par }\r\n\x00"

_PAGE_SIZE = 0x1000

# Markdown inline-style patterns — double markers matched before single.
# Underscore delimiters require non-word chars (or string edge) on the outside
# so that identifiers like count_up_down are not misinterpreted as markup.
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_RE_UNDERLINE = re.compile(r"(?<!\w)__(.+?)__(?!\w)", re.DOTALL)
_RE_ITALIC_STAR = re.compile(r"\*(.+?)\*", re.DOTALL)
_RE_ITALIC_UNDER = re.compile(r"(?<!\w)_(.+?)_(?!\w)", re.DOTALL)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_rtf_body(text: str) -> str:
    """Convert comment text to an RTF body string.

    Handles:
    - Line endings: ``\\r\\n`` and bare ``\\r`` → ``\\n``; ``\\n`` → ``\\par ``
    - Inline styles (double markers before single to avoid partial matches):
        ``**text**`` → ``{\\b text}``  (bold)
        ``__text__`` → ``{\\ul text}`` (underline)
        ``*text*``   → ``{\\i text}``  (italic, asterisk)
        ``_text_``   → ``{\\i text}``  (italic, underscore)

    Plain-text ``{``, ``}`` and ``\\`` are not escaped — avoid them in
    comment text or the resulting RTF will be malformed.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _RE_BOLD.sub(r"{\\b \1}", text)
    text = _RE_UNDERLINE.sub(r"{\\ul \1}", text)
    text = _RE_ITALIC_STAR.sub(r"{\\i \1}", text)
    text = _RE_ITALIC_UNDER.sub(r"{\\i \1}", text)
    text = text.replace("\n", "\\par ")
    return text


def _pad_to_page(data: bytearray) -> bytes:
    remainder = len(data) % _PAGE_SIZE
    if remainder:
        data += b"\x00" * (_PAGE_SIZE - remainder)
    return bytes(data)


def _normalize_af(token: AfToken) -> str:
    """Normalize an AF token to ``'NOP'``, ``''``, ``'COIL'``, ``'TIMER'``, or ``'RAW'``."""
    if isinstance(token, Coil):
        return "COIL"
    if isinstance(token, Timer):
        return "TIMER"
    if isinstance(token, RawInstruction):
        return "RAW"
    stripped = token.strip().upper()
    if stripped == "NOP":
        return "NOP"
    if stripped == "":
        return ""
    raise ValueError(f"Unsupported AF token: {token!r}")


def _build_af_summary(
    total_instr_count: int,
    af_count: int,
    af_entries: list[tuple[int, int, bool]],
) -> bytes:
    """Build the AF instruction summary block for the last AF cell.

    Appended between the blob and tail on the last AF instruction cell
    when the rung has 2+ AF instructions.  Confirmed via native capture
    (instr-3row-branch).

    Parameters
    ----------
    total_instr_count:
        Total number of instructions (conditions + AFs) in the rung.
    af_count:
        Number of AF instruction cells in the rung.
    af_entries:
        One tuple per AF instruction, ordered by row:
        ``(instr_index, instrs_on_row, row_has_contact)``.
        ``instrs_on_row`` = count of all instructions on this AF's row.
        ``row_has_contact`` = True if a Contact/CompareContact is on this row.

    Structure (40 bytes for 3 AFs)::

        12 zero bytes
        uint32 LE total_instr_count
        af_count × 8-byte entries (diagonal pattern):
            entry[af_idx] = left_value
            entry[af_idx + af_count] = right_value (1 if row has contact)
        where left_value:
            non-last AF: total_instr_count - instr_index
            last AF: instrs_on_row
    """
    block = bytearray(12)  # zero header
    block += total_instr_count.to_bytes(4, "little")

    for af_idx, (instr_index, instrs_on_row, row_has_contact) in enumerate(af_entries):
        entry = bytearray(8)
        is_last_af = af_idx == af_count - 1
        left = instrs_on_row if is_last_af else total_instr_count - instr_index
        entry[af_idx] = left & 0xFF
        if row_has_contact:
            entry[af_idx + af_count] = 1
        block += entry

    return bytes(block)


def _compute_seg_boundaries(
    condition_rows: Sequence[Sequence[ConditionToken]],
) -> list[int]:
    """Compute per-row segment boundaries for instruction-bearing rungs.

    Row 0 is exempt (boundary=0 → all non-blank cells get seg=1).
    Row R>0: boundary = max of:
        - T col+2 / | col+1 from row R-1 only (does not propagate further),
        - Contact/Compare col+2 from rows 0..R-1.

    Cells at col < boundary get seg=0; cells at col >= boundary get seg=1.

    Note: Click's native seg flags depend on editor creation order — if a
    user "inserts row above", the original row stays exempt instead of row 0.
    Our encoder always treats row 0 as exempt, which matches rungs built
    top-down (the way our encoder creates them).  Verified 2026-03-19.
    """
    n = len(condition_rows)
    boundaries = [0] * n
    for r in range(1, n):
        # T/| only from the immediately preceding row.
        # T uses col+2, | uses col+1.
        tj_max = 0
        for c_idx, tok in enumerate(condition_rows[r - 1]):
            if isinstance(tok, str) and tok == "T":
                tj_max = max(tj_max, c_idx + 2)
            elif isinstance(tok, str) and tok == "|":
                tj_max = max(tj_max, c_idx + 1)
        # Contacts from all prior rows.
        ct_max = 0
        for prev_r in range(r):
            for c_idx, tok in enumerate(condition_rows[prev_r]):
                if isinstance(tok, (Contact, CompareContact)):
                    ct_max = max(ct_max, c_idx + 2)
        boundaries[r] = max(tj_max, ct_max)
    return boundaries


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def encode_rung(
    logical_rows: int,
    condition_rows: Sequence[Sequence[ConditionToken]],
    af_tokens: Sequence[AfToken],
    comment: str | None = None,
) -> bytes:
    """Encode a ladder rung to binary payload.

    Parameters
    ----------
    logical_rows:
        Number of rung rows (1..32).
    condition_rows:
        Row-major token grid. Each row has 31 condition-column entries.
        Supported: ``""`` blank, ``"-"`` horizontal wire,
        ``"|"`` vertical pass-through, ``"T"`` junction-down,
        or a ``Contact`` object.
    af_tokens:
        One per row. ``"NOP"`` encodes the NOP instruction on the AF
        column; ``""`` leaves it blank; a ``Coil`` object encodes the
        coil instruction.
    comment:
        Optional comment text (max 1400 bytes after RTF encoding). Stored
        as an RTF envelope inserted at 0x0298; the cell grid is pushed
        forward by payload_len bytes automatically.

        Inline styles (markdown syntax):
            ``**text**``  → bold
            ``__text__``  → underline
            ``*text*``    → italic (asterisk)
            ``_text_``    → italic (underscore)
        Line breaks: ``\\n`` becomes an RTF paragraph break (``\\par``).
        ``\\r\\n`` and bare ``\\r`` are normalized to ``\\n`` first.

    Returns
    -------
    bytes
        Encoded binary payload ready for the target environment.
    """

    # --- Validate dimensions ---

    if not (MIN_ROWS <= logical_rows <= MAX_ROWS):
        raise ValueError(f"logical_rows must be {MIN_ROWS}..{MAX_ROWS}, got {logical_rows}")
    if len(condition_rows) != logical_rows:
        raise ValueError(f"Expected {logical_rows} condition rows, got {len(condition_rows)}")
    if len(af_tokens) != logical_rows:
        raise ValueError(f"Expected {logical_rows} AF tokens, got {len(af_tokens)}")
    for row_idx, row in enumerate(condition_rows):
        if len(row) != CONDITION_COLUMNS:
            raise ValueError(f"Row {row_idx}: expected {CONDITION_COLUMNS} columns, got {len(row)}")
        for col_idx, token in enumerate(row):
            if isinstance(token, (Contact, CompareContact)):
                continue  # Instruction objects are always valid
            if token not in SUPPORTED_CONDITION_TOKENS:
                raise ValueError(f"Unsupported token {token!r} at row={row_idx}, col={col_idx}")
            if col_idx == 0 and token in ("|", "T"):
                raise ValueError(
                    f"Vertical-down tokens are not allowed in column A "
                    f"(row={row_idx}, token={token!r})"
                )
            if row_idx == logical_rows - 1 and token in ("|", "T"):
                raise ValueError(
                    f"Vertical-down tokens are not allowed on the last row "
                    f"(row={row_idx}, col={col_idx}, token={token!r})"
                )

    nop_count = sum(1 for af in af_tokens if _normalize_af(af) == "NOP")
    if nop_count > 1:
        raise ValueError(f"Only one NOP per rung is allowed (got {nop_count})")

    # --- Step 1: Header — load from template with correct row_word ---

    template = synthesize_empty_multirow(logical_rows)
    out = bytearray(template[:GRID_FIRST_ROW_START])

    # --- Step 2: Grid — build cell objects, concatenate ---

    grid = bytearray()
    # NOP col-0 enable (+0x15) is only needed in NOP-only rungs.
    # When the rung has instruction cells, the flag must stay 0.
    rung_has_instructions = any(
        isinstance(t, (Contact, CompareContact)) for row in condition_rows for t in row
    ) or any(isinstance(af, (Coil, Timer, RawInstruction)) for af in af_tokens)

    total_instr_count = sum(
        1 for row in condition_rows for t in row if isinstance(t, (Contact, CompareContact))
    ) + sum(1 for af in af_tokens if isinstance(af, (Coil, Timer, RawInstruction)))

    # Pre-compute instruction indices: conditions first (all rows),
    # then AF instructions (all rows).  Native Click numbers all
    # condition-side instructions before any AF-side instructions.
    cond_instr_indices: dict[tuple[int, int], int] = {}
    af_instr_indices: dict[int, int] = {}
    idx = 0
    for row_idx in range(logical_rows):
        for col_idx, tok in enumerate(condition_rows[row_idx]):
            if isinstance(tok, (Contact, CompareContact)):
                cond_instr_indices[(row_idx, col_idx)] = idx
                idx += 1
    for row_idx in range(logical_rows):
        af = af_tokens[row_idx]
        if isinstance(af, (Coil, Timer, RawInstruction)):
            af_instr_indices[row_idx] = idx
            idx += 1

    # AF summary block — needed on the last AF instruction cell when 2+ AFs.
    af_summary_block = b""
    af_rows = sorted(af_instr_indices.keys())
    if len(af_rows) >= 2:
        af_entries: list[tuple[int, int, bool]] = []
        for r in af_rows:
            cond_count = sum(
                1 for t in condition_rows[r] if isinstance(t, (Contact, CompareContact))
            )
            instrs_on_row = cond_count + 1  # +1 for the AF instruction itself
            row_has_contact = cond_count > 0
            af_entries.append((af_instr_indices[r], instrs_on_row, row_has_contact))
        af_summary_block = _build_af_summary(total_instr_count, len(af_rows), af_entries)

    # Per-row segment boundaries for instruction-bearing rungs.
    seg_boundaries = _compute_seg_boundaries(condition_rows) if rung_has_instructions else None
    for row_idx in range(logical_rows):
        cond_row = condition_rows[row_idx]
        af = af_tokens[row_idx]
        af_kind = _normalize_af(af)
        has_nop = af_kind == "NOP"
        cells: list[bytes] = []
        seg_bound = seg_boundaries[row_idx] if seg_boundaries else 0

        for col_idx in range(COLS_PER_ROW):
            if col_idx < CONDITION_COLUMNS:
                token = cond_row[col_idx]
                # Segment flag: on row 0, always 1 for non-blank.
                # On row 1+, 0 below boundary, 1 at/above boundary.
                seg = 1 if col_idx >= seg_bound else (0 if row_idx > 0 and seg_bound > 0 else 1)
                if isinstance(token, Contact):
                    blob = build_contact_blob(token)
                    cells.append(
                        ClickCell(
                            col=col_idx,
                            global_row=row_idx,
                            rung_idx=0,
                            local_row=row_idx,
                            logical_rows=logical_rows,
                            is_last_rung=True,
                            single_rung=True,
                            is_contact=True,
                            rung_has_instructions=rung_has_instructions,
                            segment=seg,
                            wire_right=1,
                            wire_down=1 if token.wire_down else 0,
                            instr_index=cond_instr_indices[(row_idx, col_idx)],
                            blob=blob,
                        ).to_bytes()
                    )
                elif isinstance(token, CompareContact):
                    blob = build_compare_blob(token)
                    cells.append(
                        ClickCell(
                            col=col_idx,
                            global_row=row_idx,
                            rung_idx=0,
                            local_row=row_idx,
                            logical_rows=logical_rows,
                            is_last_rung=True,
                            single_rung=True,
                            is_contact=True,
                            rung_has_instructions=rung_has_instructions,
                            segment=seg,
                            wire_right=1,
                            wire_down=1 if token.wire_down else 0,
                            instr_index=cond_instr_indices[(row_idx, col_idx)],
                            blob=blob,
                        ).to_bytes()
                    )
                else:
                    seg, right, down = _TOKEN_FLAGS[token]
                    # Apply segment boundary on row 1+.
                    if seg and row_idx > 0 and seg_bound > 0 and col_idx < seg_bound:
                        seg = 0
                    cells.append(
                        ClickCell(
                            col=col_idx,
                            global_row=row_idx,
                            rung_idx=0,
                            local_row=row_idx,
                            logical_rows=logical_rows,
                            is_last_rung=True,
                            single_rung=True,
                            rung_has_instructions=rung_has_instructions,
                            segment=seg,
                            wire_right=right,
                            wire_down=down,
                            nop_enable=1
                            if (
                                has_nop
                                and row_idx > 0
                                and col_idx == 0
                                and not rung_has_instructions
                            )
                            else 0,
                        ).to_bytes()
                    )
            else:  # AF column (col 31)
                is_last_af = af_rows and row_idx == af_rows[-1]
                summary = af_summary_block if is_last_af else b""
                if af_kind == "COIL":
                    assert isinstance(af, Coil)
                    blob = build_coil_blob(af)
                    cells.append(
                        ClickCell(
                            col=col_idx,
                            global_row=row_idx,
                            rung_idx=0,
                            local_row=row_idx,
                            logical_rows=logical_rows,
                            is_last_rung=True,
                            single_rung=True,
                            is_contact=False,
                            rung_has_instructions=rung_has_instructions,
                            segment=1 if row_idx == 0 else 0,
                            wire_right=1,
                            instr_index=af_instr_indices[row_idx],
                            blob=blob,
                            af_summary=summary,
                        ).to_bytes()
                    )
                elif af_kind == "TIMER":
                    assert isinstance(af, Timer)
                    blob = build_timer_blob(af)
                    cells.append(
                        ClickCell(
                            col=col_idx,
                            global_row=row_idx,
                            rung_idx=0,
                            local_row=row_idx,
                            logical_rows=logical_rows,
                            is_last_rung=True,
                            single_rung=True,
                            is_contact=False,
                            rung_has_instructions=rung_has_instructions,
                            segment=0,
                            wire_right=1,
                            instr_index=af_instr_indices[row_idx],
                            blob=blob,
                            row_span=logical_rows,
                            visual_rows=3 if af.retained else 2,
                            af_summary=summary,
                        ).to_bytes()
                    )
                elif af_kind == "RAW":
                    assert isinstance(af, RawInstruction)
                    is_multi_row = af.part_count > 1
                    cells.append(
                        ClickCell(
                            col=col_idx,
                            global_row=row_idx,
                            rung_idx=0,
                            local_row=row_idx,
                            logical_rows=logical_rows,
                            is_last_rung=True,
                            single_rung=True,
                            is_contact=False,
                            rung_has_instructions=rung_has_instructions,
                            segment=0 if is_multi_row else (1 if row_idx == 0 else 0),
                            wire_right=1,
                            instr_index=af_instr_indices[row_idx],
                            blob=af.blob,
                            row_span=logical_rows if is_multi_row else 1,
                            visual_rows=af.part_count if is_multi_row else 1,
                            af_summary=summary,
                        ).to_bytes()
                    )
                else:
                    cells.append(
                        ClickCell(
                            col=col_idx,
                            global_row=row_idx,
                            rung_idx=0,
                            local_row=row_idx,
                            logical_rows=logical_rows,
                            is_last_rung=True,
                            single_rung=True,
                            rung_has_instructions=rung_has_instructions,
                            segment=1 if has_nop else 0,
                            af_nop=1 if has_nop else 0,
                            instr_count=total_instr_count,
                        ).to_bytes()
                    )

        grid += build_row(cells)

    # --- Step 3: Assemble header + grid ---

    out += grid

    # --- Step 4: Comment payload — insert at 0x0298, grid pushes forward ---

    has_comment = comment is not None and comment != ""
    if has_comment:
        assert comment is not None
        encoded = _build_rtf_body(comment).encode("cp1252")
        if len(encoded) > COMMENT_MAX_BYTES:
            raise ValueError(
                f"Comment body exceeds {COMMENT_MAX_BYTES} bytes after RTF encoding "
                f"(got {len(encoded)})"
            )
        payload = _PREFIX + encoded + _SUFFIX

        # Slice-insert pushes everything at 0x0298+ forward by len(payload).
        # The cell grid (at 0x0A60 before insert) lands at 0x0A60+len(payload).
        out[PAYLOAD_BYTES_OFFSET:PAYLOAD_BYTES_OFFSET] = payload
        out[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET] = len(payload).to_bytes(4, "little")

    # --- Step 5: Pad to page boundary ---

    return _pad_to_page(out)
