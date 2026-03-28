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
    Encoded via three per-cell flag bytes: +0x19 (left), +0x1D (right),
    +0x21 (down). Conditions also set these flags (like "-").

Condition:
    A contact or comparison instruction placed on a condition column.
    NOT supported in this version. Conditions set wire flags (like "-")
    and additionally write an instruction stream entry with a type
    marker, function code, and operand.

Instruction stream:
    Serialized instruction data in the payload region (0x0298+). For
    instruction rungs, the payload is inserted at 0x0298 and the grid
    is pushed forward by payload_len bytes. NOT used in this version.

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
    [ ] Contacts (NO, NC, edge, comparison, immediate variants)
    [ ] Coils / AF instructions (out, latch, reset)
    [ ] Instruction stream placement


Pipeline steps
--------------

    1. Header   — load from synthesize_empty_multirow (includes row_word)
    2. Grid     — build 32 cell objects per row (wire flags + NOP baked
                  in), concatenate to form the grid bytes
    3. Assemble — header[:0x0A60] + grid_bytes
    4. Comment  — assemble RTF, insert at 0x0298, push grid forward
    5. Pad      — to next 0x1000 page boundary

Cell objects are bytes blobs built by ``cell.build_data_cell()``.
Wire cells are 0x40 bytes.  Future instruction cells (contacts, coils)
will be larger, and the concatenation model handles variable-length
cells naturally — no fixed-offset assumptions in the grid.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .cell import build_data_cell, build_row
from .empty_multirow import synthesize_empty_multirow
from .topology import (
    COLS_PER_ROW,
    GRID_FIRST_ROW_START,
    GRID_ROW_STRIDE,
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

# Token → (horizontal_left, horizontal_right, vertical_down)
_TOKEN_FLAGS: dict[str, tuple[int, int, int]] = {
    "": (0, 0, 0),
    "-": (1, 1, 0),
    "|": (0, 0, 1),
    "T": (1, 1, 1),
}

SUPPORTED_CONDITION_TOKENS = frozenset(_TOKEN_FLAGS)

# FUTURE: Contact and comparison tokens will extend this map. Each contact
# type (NO, NC, edge) requires wire flags plus an instruction stream entry
# with type marker (0x2711 NO, 0x2712 NC, 0x2713 edge), function code, and
# UTF-16LE operand string.  AF instructions beyond NOP (out/latch/reset
# coils) will also need type markers and UTF-16LE operands.

# RTF comment envelope — hardcoded from native capture (2026-03-09).
# Prefix (105 bytes) + cp1252 body + suffix (11 bytes).
#
# Trimming options (not yet tested against Click — needs re-verification):
#
#   Conservative (79 bytes): drop \deflang1033, \r\n, \viewkind4, \uc1
#       b"{\\rtf1\\ansi\\ansicpg1252\\deff0"
#       b"{\\fonttbl{\\f0\\fnil\\fcharset0 Arial;}}"
#       b"\\pard\\fs20 "
#
#   Aggressive (35 bytes): drop all except encoding + paragraph + font size
#       b"{\\rtf1\\ansi\\ansicpg1252\\pard\\fs20 "
#
#   Suffix (7 bytes): drop cosmetic \r\n on each side — b"\\par }\\x00"
_PREFIX = (
    b"{\\rtf1\\ansi\\ansicpg1252\\deff0\\deflang1033"
    b"{\\fonttbl{\\f0\\fnil\\fcharset0 Arial;}}\r\n"
    b"\\viewkind4\\uc1\\pard\\fs20 "
)
_SUFFIX = b"\r\n\\par }\r\n\x00"

_PAGE_SIZE = 0x1000

# Markdown inline-style patterns — double markers matched before single.
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_RE_UNDERLINE = re.compile(r"__(.+?)__", re.DOTALL)
_RE_ITALIC_STAR = re.compile(r"\*(.+?)\*", re.DOTALL)
_RE_ITALIC_UNDER = re.compile(r"_(.+?)_", re.DOTALL)


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


def _normalize_af(token: str) -> str:
    """Normalize an AF token to 'NOP' or ''.

    FUTURE: Will expand to handle coil instructions once instruction
    stream encoding is implemented.
    """
    stripped = token.strip().upper()
    if stripped == "NOP":
        return "NOP"
    if stripped == "":
        return ""
    raise ValueError(f"Unsupported AF token: {token!r}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def encode_rung(
    logical_rows: int,
    condition_rows: Sequence[Sequence[str]],
    af_tokens: Sequence[str],
    comment: str | None = None,
) -> bytes:
    """Encode a ladder rung to binary payload.

    Parameters
    ----------
    logical_rows:
        Number of rung rows (1..32).
    condition_rows:
        Row-major token grid. Each row has 31 condition-column tokens.
        Supported: ``""`` blank, ``"-"`` horizontal wire,
        ``"|"`` vertical pass-through, ``"T"`` junction-down.
    af_tokens:
        One per row. ``"NOP"`` encodes the NOP instruction on the AF
        column; ``""`` leaves it blank.
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
    for row_idx in range(logical_rows):
        cond_row = condition_rows[row_idx]
        has_nop = _normalize_af(af_tokens[row_idx]) == "NOP"
        cells: list[bytes] = []

        for col_idx in range(COLS_PER_ROW):
            if col_idx < CONDITION_COLUMNS:
                left, right, down = _TOKEN_FLAGS[cond_row[col_idx]]
                cells.append(
                    build_data_cell(
                        col_idx,
                        row_idx,
                        local_row=row_idx,
                        logical_rows=logical_rows,
                        rung_idx=0,
                        is_last_rung=True,
                        single_rung=True,
                        wire_left=left,
                        wire_right=right,
                        wire_down=down,
                        nop_enable=1 if (has_nop and row_idx > 0 and col_idx == 0) else 0,
                    )
                )
            else:  # AF column (col 31)
                cells.append(
                    build_data_cell(
                        col_idx,
                        row_idx,
                        local_row=row_idx,
                        logical_rows=logical_rows,
                        rung_idx=0,
                        is_last_rung=True,
                        single_rung=True,
                        af_nop=1 if has_nop else 0,
                    )
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
