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

from .empty_multirow import synthesize_empty_multirow
from .instructions import AfInstruction, ConditionInstruction
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

#: A condition-column token: wire string or ConditionInstruction.
ConditionToken = str | ConditionInstruction

#: An AF-column token: ``""`` / ``"NOP"`` string or AfInstruction.
AfToken = str | AfInstruction

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

    RTF special characters (``\\``, ``{``, ``}``) in the plain text are
    escaped before markdown conversion so they pass through safely.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Escape RTF special characters (order matters: backslash first).
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "\\{")
    text = text.replace("}", "\\}")
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
    """Normalize an AF token to ``'NOP'``, ``''``, or ``'INSTR'``."""
    if isinstance(token, AfInstruction):
        return "INSTR"
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
                if isinstance(tok, ConditionInstruction):
                    ct_max = max(ct_max, c_idx + 2)
        boundaries[r] = max(tj_max, ct_max)
    return boundaries


def _af_segment(row_idx: int, is_multi_row: bool, single_rung: bool) -> int:
    """Compute the segment flag for an AF instruction cell.

    - Multi-row AF (Timer, multi-part Raw): always 0.
    - Multi-rung (all AF types): always 0.
    - Single-rung, single-row AF (Coil, single-part Raw): 1 on row 0, else 0.
    """
    if is_multi_row or not single_rung:
        return 0
    return 1 if row_idx == 0 else 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def encode_rung(
    logical_rows: int,
    condition_rows: Sequence[Sequence[ConditionToken]],
    af_tokens: Sequence[AfToken],
    comment: str | None = None,
    *,
    show_nicknames: bool = False,
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

    from ._grid import _build_rung_grid, _compute_rung_metadata, _validate_rung

    # --- Validate ---

    _validate_rung(logical_rows, condition_rows, af_tokens)

    # --- Step 1: Header — load from template with correct row_word ---

    template = synthesize_empty_multirow(logical_rows)
    out = bytearray(template[:GRID_FIRST_ROW_START])

    # --- Step 2: Grid — validate, compute metadata, build cells ---

    meta = _compute_rung_metadata(logical_rows, condition_rows, af_tokens)
    grid = _build_rung_grid(
        logical_rows,
        condition_rows,
        af_tokens,
        meta,
        global_row_start=0,
        rung_idx=0,
        is_last_rung=True,
        single_rung=True,
        show_nicknames=show_nicknames,
    )

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


def encode(rungs, *, show_nicknames: bool = False):
    """Encode one or more rungs to clipboard binary.

    Parameters
    ----------
    rungs:
        A single ``Rung`` object (single-rung encode) or a sequence of
        ``Rung`` objects (multi-rung encode).
    show_nicknames:
        When ``True``, sets the nickname display flag on math instructions
        so Click shows project-level tag names instead of raw addresses.
        The nicknames must already be loaded in the Click project before
        pasting.

    Returns
    -------
    bytes
        Encoded binary payload.
    """
    from .decode import Rung  # lazy import to avoid circular

    if isinstance(rungs, Rung):
        return encode_rung(
            rungs.logical_rows,
            rungs.conditions,
            rungs.instructions,
            rungs.comment,
            show_nicknames=show_nicknames,
        )
    from .encode_multi import encode_rungs

    return encode_rungs(
        [(r.logical_rows, r.conditions, r.instructions) for r in rungs],
        comments=[r.comment for r in rungs],
        show_nicknames=show_nicknames,
    )
