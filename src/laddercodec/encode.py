"""Encode ladder rungs as the binary that CLICK puts on the clipboard.

Definitions
-----------

Rung:
    One logical unit of ladder logic. A rung has 1..32 rows, each with
    31 condition columns (A..AE) and 1 output column (AF). A rung may
    also have one comment.

Row:
    A horizontal slice of the rung grid. Row 0 is the topmost visible
    row. The grid starts at absolute offset 0x0A60 with a stride of
    0x800 per row (32 columns x 64 bytes per cell).

Cell:
    The bytes for one (row, column) position in the grid. A wire cell
    is 64 (0x40) bytes, and an instruction cell is longer. A cell holds
    wire flags and bytes that describe the grid's structure. An
    instruction cell also holds its index among the rung's instructions,
    at +0x0D. The encoder numbers the condition instructions row by row,
    then the AF instructions. When the AF cell on the last row of the
    last rung is a 0x40-byte cell, blank or a NOP, the encoder writes the
    number of that rung's instructions at its +0x3C. A NOP is not
    counted. CLICK often writes another value there.

Wire topology:
    The arrangement of horizontal wires ("-"), vertical pass-throughs
    ("|"), and junction-down points ("T") across the condition grid.
    Each cell stores it in three flag bytes: +0x19 (segment), +0x1D
    (right) and +0x21 (down). A condition cell sets these flags as a
    "-" cell does.

Condition:
    An instruction in a condition column (A..AE): a ``Contact``
    (NO/NC/edge) or a ``CompareContact`` (GT/GE/LT/LE/EQ/NE). A
    condition cell has a variable length. It is a 0x25-byte header
    (wire flags, column, row, instruction index) followed by the
    instruction blob (class name, type marker, operand, func_code). The
    caller passes each condition as an object in the condition_rows grid.

NOP:
    The simplest AF-column instruction. A rung holds at most one. The
    encoder writes it as flags: +0x1D = 1 in column 31 of the NOP's row,
    and +0x15 = 1 in column 0 of that row if it is not the first row and
    the rung holds no other instruction.
    A NOP gets no instruction index and is not counted.

Comment:
    Text attached to a rung. The encoder stores it as RTF: a fixed
    prefix, the ASCII body and a fixed suffix. The RTF goes in the
    payload region at 0x0298, and its 4-byte length goes at 0x0294.
    With no comment the cell grid starts at 0x0A60. A comment moves the
    grid forward by the length of the RTF. The body is at most 1400
    bytes.

Page:
    A 0x1000 (4096) byte allocation unit. Buffer size is:
    pad_to_page(0x0A60 + logical_rows * 0x800 + payload_len).

Program header:
    A single 0x40-byte structure at 0x0254. It holds the row-count
    word (+0x00/+0x01 = (rows+1)*0x20) and other GUI state. There is
    only one. The range 0x0294–0x0A5F after it is the payload region,
    not a table of 32 headers.


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
    [x] Multi-line comment (\\n → \\par)
    [x] Styled comments (bold/italic/underline via markdown → RTF groups)
    [x] Contacts (NO, NC, edge, immediate — via Contact objects in condition_rows)
    [x] Coils (out, latch, reset, immediate, range — via Coil objects in af_tokens)
    [x] Comparison contacts (GT, GE, LT, LE, EQ, NE — via CompareContact objects)
    [x] Timers (on_delay, off_delay, retentive — via Timer objects in af_tokens)
    [x] These AF instructions: counters, the Copy family, Search, Math,
        Shift, drums, For/Next, Call, Return, End, Send/Receive and the
        Out variants (tests/fixtures/coverage/golden/)
    [x] Email, Home, Position and Velocity, as raw(...) only


Pipeline steps
--------------

    1. Header   — load from synthesize_empty_multirow (includes row_word)
    2. Grid     — build the 32 cells of each row, with their wire flags
                  and any NOP, and join them into the grid bytes
    3. Assemble — header[:0x0A60] + grid_bytes
    4. Comment  — assemble RTF, insert at 0x0298, push grid forward
    5. Pad      — to next 0x1000 page boundary

Each cell is the bytes that ``ClickCell.to_bytes()`` returns. A wire
cell is 0x40 bytes. An instruction cell, such as a contact, coil or
timer, is longer. The encoder joins the cells end to end, so it does
not assume that any cell sits at a fixed offset in the grid.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from ._comment import rtf_body as _build_rtf_body
from .empty_multirow import synthesize_empty_multirow
from .errors import EncodeError
from .instructions import Condition, ConditionToken, Instruction, InstructionToken, Tee
from .topology import (
    GRID_FIRST_ROW_START,
    PREAMBLE_COMMENT_BODY,
    PREAMBLE_COMMENT_LENGTH,
    RUNG0_PREAMBLE_BASE,
)

if TYPE_CHECKING:
    from .decode import Rung

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Offsets of the comment's length and body, from the layout of rung 0's preamble.
PAYLOAD_LENGTH_OFFSET = RUNG0_PREAMBLE_BASE + PREAMBLE_COMMENT_LENGTH  # 0x0294
PAYLOAD_BYTES_OFFSET = RUNG0_PREAMBLE_BASE + PREAMBLE_COMMENT_BODY  # 0x0298
COMMENT_MAX_BYTES = 1400

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

# RTF comment envelope.
# Prefix (105 bytes) + ASCII body + suffix (11 bytes).
_PREFIX = (
    b"{\\rtf1\\ansi\\ansicpg1252\\deff0\\deflang1033"
    b"{\\fonttbl{\\f0\\fnil\\fcharset0 Arial;}}\r\n"
    b"\\viewkind4\\uc1\\pard\\fs20 "
)
_SUFFIX = b"\r\n\\par }\r\n\x00"

_PAGE_SIZE = 0x1000


def _comment_bytes(comment: str) -> bytes:
    """Return the RTF body that ``encode()`` writes for the Markdown *comment*, without
    checking its length.

    ``check()`` and ``encode()`` both measure a comment with this function, so they agree on
    its size.
    """
    return _build_rtf_body(comment).encode("ascii")


def _comment_body(comment: str, rung: int | None = None) -> bytes:
    """Return the RTF body that ``encode()`` writes for the Markdown *comment*.

    Raise :class:`EncodeError` if the body is longer than :data:`COMMENT_MAX_BYTES`. The
    message names rung *rung* if it is given.
    """
    body = _comment_bytes(comment)
    if len(body) > COMMENT_MAX_BYTES:
        which = "The comment" if rung is None else f"The comment of rung {rung}"
        cut = len(body) - COMMENT_MAX_BYTES
        raise EncodeError(
            f"{which} is too long: CLICK would store {len(body)} bytes, and the limit is "
            f"{COMMENT_MAX_BYTES}. A character outside ASCII takes more than one byte: "
            f"é takes 4 (\\'e9), and a character that code page 1252 lacks takes 6 or "
            f"more. Shorten the comment by at least {cut} byte{'' if cut == 1 else 's'}."
        )
    return body


def _pad_to_page(data: bytearray) -> bytes:
    remainder = len(data) % _PAGE_SIZE
    if remainder:
        data += b"\x00" * (_PAGE_SIZE - remainder)
    return bytes(data)


def _normalize_af(token: InstructionToken) -> str:
    """Normalize an AF token to ``'NOP'``, ``''``, or ``'INSTR'``."""
    if isinstance(token, Instruction):
        return "INSTR"
    stripped = token.strip().upper() if isinstance(token, str) else None
    if stripped == "NOP":
        return "NOP"
    if stripped == "":
        return ""
    raise EncodeError(f"Unsupported AF token: {token!r}. Use an instruction, 'NOP' or ''.")


def _compute_seg_boundaries(
    condition_rows: Sequence[Sequence[ConditionToken]],
) -> list[int]:
    """Return the segment boundary of each row, for a rung that holds instructions.

    A cell in a column below its row's boundary gets seg=0. A cell at or past
    the boundary keeps the flag of its token, which is 1 for ``-``, ``T`` and a
    condition instruction. Row 0 has boundary 0. For a later row R, the
    boundary is the largest of:

        - col+2 for a ``T`` and col+1 for a ``|``, in row R-1 only;
        - col+2 for a Contact or CompareContact, or a ``Tee`` around one, in any of rows
          0..R-1.

    In CLICK the seg flags depend on the order in which the user made the rows.
    If a user "inserts row above", the original top row keeps boundary 0 and
    the new row 0 does not. This encoder always gives row 0 boundary 0, which
    matches a rung built from the top down.
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
                if isinstance(tok, (Condition, Tee)):
                    ct_max = max(ct_max, c_idx + 2)
        boundaries[r] = max(tj_max, ct_max)
    return boundaries


def _af_segment(row_idx: int, is_multi_row: bool, single_rung: bool) -> int:
    """Return the segment flag that the encoder writes for an AF instruction cell.

    CLICK itself copies a bit that it stores for each entry. These rules do not
    describe how CLICK writes the flag, and they do not reproduce a flag that a
    rung's editing history produced.

    - A multi-row AF instruction (Timer, multi-part Raw) gets 0.
    - Every AF instruction gets 0 when several rungs are encoded together.
    - A single-row AF instruction (Coil, single-part Raw) in a single rung gets 1
      on row 0 and 0 on any other row.
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
    af_tokens: Sequence[InstructionToken],
    comment: str | None = None,
    *,
    show_nicknames: bool = False,
) -> bytes:
    """Encode one ladder rung as CLICK clipboard binary.

    Parameters
    ----------
    logical_rows:
        Number of rung rows (1..32).
    condition_rows:
        The token grid, one list per row. Each row has 31 condition-column
        entries. Each entry is ``""`` blank, ``"-"`` horizontal wire,
        ``"|"`` vertical pass-through, ``"T"`` junction-down,
        a ``Condition`` such as a ``Contact``, or a ``Tee`` around one.
    af_tokens:
        One per row. ``"NOP"`` encodes the NOP instruction on the AF
        column, and ``""`` leaves it blank. An ``Instruction``, such as a
        ``Coil``, encodes that instruction.
    comment:
        Optional comment text, at most 1400 bytes after RTF encoding. The
        encoder inserts it as RTF at 0x0298 and moves the cell grid forward
        by the length of the RTF.

        Inline styles (markdown syntax):
            ``**text**``  → bold
            ``__text__``  → underline
            ``*text*``    → italic (asterisk)
            ``_text_``    → italic (underscore)
        A backslash before ``*``, ``_`` or ``\\`` makes that character text.
        Line breaks: ``\\n`` becomes an RTF paragraph break (``\\par``).
        ``\\r\\n`` and a lone ``\\r`` are normalized to ``\\n`` first.

    Returns
    -------
    bytes
        The encoded rung, padded to a whole number of 0x1000-byte pages.
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
        payload = _PREFIX + _comment_body(comment) + _SUFFIX

        # Slice-insert pushes everything at 0x0298+ forward by len(payload).
        # The cell grid (at 0x0A60 before insert) lands at 0x0A60+len(payload).
        out[PAYLOAD_BYTES_OFFSET:PAYLOAD_BYTES_OFFSET] = payload
        out[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET] = len(payload).to_bytes(4, "little")

    # --- Step 5: Pad to page boundary ---

    return _pad_to_page(out)


def encode(rungs: Rung | Iterable[Rung], *, show_nicknames: bool = False) -> bytes:
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

    Raises
    ------
    EncodeError
        If a rung can't be written: a grid of the wrong size, a wire token where CLICK
        can't draw one, more than one ``NOP``, an undecoded marker, or a comment too long.
    FieldError
        If an instruction holds a value CLICK's dialog refuses.
    """
    from .decode import Rung  # lazy import to avoid circular

    rung_list = [rungs] if isinstance(rungs, Rung) else list(rungs)
    if len(rung_list) == 1:
        r = rung_list[0]
        return encode_rung(
            r.logical_rows,
            r.conditions,
            r.instructions,
            r.comment,
            show_nicknames=show_nicknames,
        )
    from .encode_multi import encode_rungs

    return encode_rungs(
        [(r.logical_rows, r.conditions, r.instructions) for r in rung_list],
        comments=[r.comment for r in rung_list],
        show_nicknames=show_nicknames,
    )
