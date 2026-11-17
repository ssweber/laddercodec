"""Ladder rung decoder — binary clipboard buffer to structured data.

Reads a Click clipboard binary and produces the same data structures
that feed ``encode_rung()`` / ``encode_rungs()``.

Public API
----------

    decode_rung(data)        -> Rung
    decode_rungs(data)       -> list[Rung]

Round-trip identity:

    decode_rung(encode_rung(lr, cr, af, cmt))
        .logical_rows  == lr
        .conditions    == cr
        .instructions  == af
        .comment       == cmt

Instruction cells
-----------------

Contacts and coils are composite: a horizontal wire (``(1,1,0)``) with
instruction data layered on top.  The instruction payload starts at
cell offset ``+0x25`` (UTF-16LE class name, type marker, operand, func
code).  Wire-only cells are exactly ``0x40`` bytes; instruction cells
are larger.

Known instruction types are decoded into domain objects (``Contact``,
``Coil``, ``Timer``, etc.) from ``instructions/``.  Unrecognised cells
fall back to ``UnknownCondition`` / ``UnknownInstruction`` with raw
bytes preserved.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, replace

from .csv.contract import CONDITION_COLUMNS as _COLUMN_NAMES
from .csv.contract import OUTPUT_COLUMN as _AF_NAME
from .encode import _PREFIX, _SUFFIX
from .errors import DecodeError
from .instructions import (
    AfInstruction,
    AfToken,
    ConditionToken,
    RawInstruction,
    UnknownCondition,
    UnknownInstruction,
    parse_af_blob,
    parse_condition_blob,
)
from .instructions.raw import find_blob_boundary
from .legacy import warn_legacy
from .model import PinnedInstruction
from .operands.unchecked import keep_cell_rows
from .refused import warn_refused
from .topology import (
    CELL_SIZE,
    CELL_TAIL_SIZE,
    COLS_PER_ROW,
    CONDITION_COLUMNS,
    GRID_FIRST_ROW_START,
    GRID_ROW_STRIDE,
    PREAMBLE_COMMENT_BODY,
    PREAMBLE_COMMENT_LENGTH,
    PROGRAM_HEADER_BASE,
    RUNG0_PREAMBLE_BASE,
)
from .undecoded import (
    BAD_BYTES,
    Undecoded,
    marker_rung,
    read_comment,
    reason,
    to_the_end,
    warn_comments,
    warn_undecoded,
)

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class _CellError(DecodeError):
    """A cell of a data row that cannot be decoded; ``column`` counts from 0 (31 is AF)."""

    def __init__(self, column: int, message: str) -> None:
        super().__init__(message)
        self.column = column


@dataclass
class Rung:
    """Structured rung data — used for both decode output and encode input.

    This is a semantic model: native row/segment flags and editing history
    are not retained. Re-encoding constructs canonical flags rather than
    promising byte-identical preservation of CLICK's bytes.

    Attributes
    ----------
    logical_rows:
        Number of rung rows (1..32).
    conditions:
        Row-major token grid. Each row has 31 condition-column entries.
        Wire-only cells are strings (``""`` blank, ``"-"`` horizontal,
        ``"|"`` vertical, ``"T"`` junction-down).  Contacts are
        ``Contact`` objects; unrecognised cells are
        ``UnknownCondition``.
    instructions:
        One per row.  ``"NOP"`` or ``""`` for wire-only cells.
        Coils are ``Coil`` objects; unrecognised cells are
        ``UnknownInstruction``.
    comment:
        Markdown text (for CSV export), or ``None``.
    comment_rtf:
        Raw RTF payload bytes, or ``None``.  Preserves byte-exact
        fidelity for re-encoding.
    """

    logical_rows: int
    conditions: list[list[ConditionToken]]
    instructions: list[AfToken]
    comment: str | None
    comment_rtf: bytes | None = None


# Backwards-compatible alias.
DecodedRung = Rung


@dataclass
class CellDump:
    """Raw byte dump of a single cell, for RE/debugging.

    Attributes
    ----------
    rung:  Rung index (0-based).
    row:   Visual row within the rung (0-based).
    col:   Column letter ("A".."AE" or "AF").
    offset:  Absolute byte offset in the buffer.
    size:  Cell size in bytes (0x40 for wire-only, larger for instructions).
    raw:   Raw cell bytes.
    flags: Flags ``(segment, right, down)`` read from ``+0x19/+0x1D/+0x21``.
    token: Decoded wire/instruction token, or ``None`` if not decoded.
    """

    rung: int
    row: int
    col: str
    offset: int
    size: int
    raw: bytes
    flags: tuple[int, int, int]
    token: ConditionToken | AfToken | None

    def hex(self, cols: int = 16) -> str:
        """Return a formatted hex dump with offset labels."""
        lines = []
        for i in range(0, len(self.raw), cols):
            chunk = self.raw[i : i + cols]
            hex_part = " ".join(f"{b:02x}" for b in chunk)
            ascii_part = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
            lines.append(f"  +{i:04x}: {hex_part:<{cols * 3}}  {ascii_part}")
        return "\n".join(lines)

    def __str__(self) -> str:
        hdr = (
            f"Cell rung={self.rung} row={self.row} col={self.col} "
            f"@ {self.offset:#x} ({self.size:#x} bytes)  "
            f"flags=({self.flags[0]},{self.flags[1]},{self.flags[2]})  "
            f"token={self.token!r}"
        )
        return f"{hdr}\n{self.hex()}"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAGIC = b"CLICK   "

# Reverse of encode._TOKEN_FLAGS: (segment, right, down) -> token
#
# The segment flag (+0x19) is load-bearing — getting it wrong causes
# contacts/wires to shift down to their own row.  It is ignored for
# token classification — tokens are classified by (right, down) only.
#
# Visual rendering note for pyrung walkers:
#   Click renders the DOWN wire at the LEFT EDGE of the cell, not the
#   center.  A "-" below a T appears as a corner (└ shape) because
#   the T's down-wire meets the "-" at the cell's left edge.  This
#   means a "-" that has no cell to its RIGHT should look UP one row
#   for a T — the branch connects there via the left-edge overlap.
#
_FLAGS_TO_TOKEN: dict[tuple[int, int, int], str] = {
    (0, 0, 0): "",
    (1, 0, 0): "",  # segment-only — no right wire, effectively blank
    (1, 1, 0): "-",
    (0, 1, 0): "-",  # right-only — same as horizontal (segment don't-care)
    (0, 0, 1): "|",
    (1, 0, 1): "|",  # segment + down — no right wire, effectively vertical
    (1, 1, 1): "T",
    (0, 1, 1): "T",  # right + down — same as T (segment don't-care)
}

# Payload offsets derived from rung 0 preamble.
_PAYLOAD_LENGTH_OFFSET = RUNG0_PREAMBLE_BASE + PREAMBLE_COMMENT_LENGTH  # 0x0294
_PAYLOAD_BYTES_OFFSET = RUNG0_PREAMBLE_BASE + PREAMBLE_COMMENT_BODY  # 0x0298

# Instruction data starts at this offset within a cell.
_INSTR_DATA_OFFSET = 0x25


@dataclass(frozen=True)
class _RtfStyle:
    """Inline style state for markdown-emitting RTF decode."""

    bold: bool = False
    italic: bool = False
    underline: bool = False


@dataclass
class _RtfGroupState:
    """Current RTF group state."""

    style: _RtfStyle
    skip_destination: bool = False
    unicode_skip: int = 1


_RTF_STYLE_MARKERS: tuple[tuple[str, str], ...] = (
    ("bold", "**"),
    ("italic", "*"),
    ("underline", "__"),
)

_RTF_ANSI_CPG_RE = re.compile(rb"\\ansicpg(\d+)")

# Max bytes to scan forward when searching for a cell boundary.
_CELL_SCAN_LIMIT = 0x200

# ---------------------------------------------------------------------------
# Private helpers — buffer validation & RTF
# ---------------------------------------------------------------------------


def _validate_buffer(data: bytes) -> None:
    """Check magic and minimum buffer size."""
    if len(data) < len(_MAGIC) or data[: len(_MAGIC)] != _MAGIC:
        raise DecodeError(f"Invalid magic: expected {_MAGIC!r}, got {data[: len(_MAGIC)]!r}")
    if len(data) < GRID_FIRST_ROW_START:
        raise DecodeError(
            f"Buffer too short: need at least {GRID_FIRST_ROW_START:#x} bytes, got {len(data):#x}"
        )


def _emit_rtf_style_transition(out: list[str], current: _RtfStyle, target: _RtfStyle) -> _RtfStyle:
    """Emit markdown markers needed to move from ``current`` to ``target``."""
    if current == target:
        return current

    for attr, marker in reversed(_RTF_STYLE_MARKERS):
        if getattr(current, attr) and not getattr(target, attr):
            out.append(marker)

    for attr, marker in _RTF_STYLE_MARKERS:
        if getattr(target, attr) and not getattr(current, attr):
            out.append(marker)

    return target


def _append_rtf_text(
    out: list[str], render_style: _RtfStyle, target_style: _RtfStyle, text: str
) -> _RtfStyle:
    """Append visible text, opening/closing markdown markers as needed."""
    if not text:
        return render_style

    render_style = _emit_rtf_style_transition(out, render_style, target_style)
    out.append(text)
    return render_style


def _parse_rtf_control(body: str, i: int) -> tuple[str | None, int | None, int]:
    """Parse one RTF control sequence starting at ``body[i] == '\\'``."""
    n = len(body)
    if i + 1 >= n:
        return None, None, n

    ch = body[i + 1]
    if ch in "\\{}'~_-*":
        return ch, None, i + 2

    if not ch.isalpha():
        return ch, None, i + 2

    j = i + 1
    while j < n and body[j].isalpha():
        j += 1
    word = body[i + 1 : j]

    sign = 1
    if j < n and body[j] in "+-":
        if body[j] == "-":
            sign = -1
        j += 1

    digits_start = j
    while j < n and body[j].isascii() and body[j].isdigit():
        j += 1
    arg = sign * int(body[digits_start:j]) if j > digits_start else None

    if j < n and body[j] == " ":
        j += 1

    return word, arg, j


def _assert_rtf_ansicpg_1252(payload: bytes, body_start: int) -> None:
    """Reject RTF payloads that declare a non-cp1252 ANSI code page."""
    match = _RTF_ANSI_CPG_RE.search(payload[:body_start])
    if match is None:
        raise DecodeError("Cannot locate RTF code page: missing \\ansicpg in prefix")

    codepage = match.group(1)
    if codepage != b"1252":
        value = codepage.decode("ascii", errors="replace")
        raise DecodeError(
            f"Unsupported RTF code page: expected \\ansicpg1252, got \\ansicpg{value}"
        )


def _decode_rtf_unicode_char(arg: int | None) -> str:
    """Decode one RTF ``\\u`` argument using the signed 16-bit rules."""
    if arg is None:
        return ""

    codepoint = arg if arg >= 0 else arg + 0x10000
    if not (0 <= codepoint <= 0x10FFFF):
        return ""

    try:
        return chr(codepoint)
    except ValueError:
        return ""


def _skip_rtf_fallback_chars(body: str, i: int, count: int) -> int:
    """Skip the ANSI fallback chars that follow an RTF ``\\u`` control."""
    remaining = max(count, 0)
    n = len(body)

    while remaining > 0 and i < n:
        if body[i] in "\r\n":
            i += 1
            continue

        if body[i] == "\\":
            control, _, next_i = _parse_rtf_control(body, i)
            if control == "'" and i + 4 <= n:
                i += 4
            else:
                i = next_i
            remaining -= 1
            continue

        i += 1
        remaining -= 1

    return i


def _decode_rtf(payload: bytes) -> str:
    """Convert an RTF comment payload to markdown text.

    Strips the RTF envelope (prefix/suffix), decodes the cp1252 body,
    then tokenizes the body so control words are treated as structure
    instead of leaking through as literal text.
    """
    # Strip envelope.
    if payload.startswith(_PREFIX):
        body_start = len(_PREFIX)
    else:
        # Fallback: find \fsNN<space> as the prefix boundary.
        idx = payload.find(b"\\fs")
        if idx == -1:
            raise DecodeError("Cannot locate RTF body: no \\fs marker in prefix")
        space = payload.find(b" ", idx)
        if space == -1:
            raise DecodeError("Cannot locate RTF body: no space after \\fs marker")
        body_start = space + 1

    _assert_rtf_ansicpg_1252(payload, body_start)

    if payload.endswith(_SUFFIX):
        body_end = len(payload) - len(_SUFFIX)
    else:
        # Fallback: find last \par } sequence.
        idx = payload.rfind(b"\\par }")
        if idx == -1:
            raise DecodeError("Cannot locate RTF body: no \\par } in suffix")
        body_end = idx

    body = payload[body_start:body_end].decode("cp1252")

    stack = [_RtfGroupState(style=_RtfStyle())]
    render_style = _RtfStyle()
    out: list[str] = []
    i = 0

    while i < len(body):
        group = stack[-1]
        ch = body[i]

        if ch == "{":
            stack.append(
                _RtfGroupState(
                    style=group.style,
                    skip_destination=group.skip_destination,
                    unicode_skip=group.unicode_skip,
                )
            )
            i += 1
            continue

        if ch == "}":
            if len(stack) > 1:
                stack.pop()
            i += 1
            continue

        if ch == "\\":
            control, arg, next_i = _parse_rtf_control(body, i)
            group = stack[-1]

            if control in {"\\", "{", "}"}:
                if not group.skip_destination:
                    render_style = _append_rtf_text(out, render_style, group.style, control)
            elif control == "'":
                if next_i <= len(body) and i + 4 <= len(body):
                    hex_digits = body[i + 2 : i + 4]
                    try:
                        text = bytes([int(hex_digits, 16)]).decode("cp1252")
                    except ValueError:
                        text = ""
                    if text and not group.skip_destination:
                        render_style = _append_rtf_text(out, render_style, group.style, text)
                    next_i = i + 4
            elif control == "~":
                if not group.skip_destination:
                    render_style = _append_rtf_text(out, render_style, group.style, " ")
            elif control == "_":
                if not group.skip_destination:
                    render_style = _append_rtf_text(out, render_style, group.style, "-")
            elif control == "-":
                if not group.skip_destination:
                    render_style = _append_rtf_text(out, render_style, group.style, "-")
            elif control == "*":
                group.skip_destination = True
            elif isinstance(control, str):
                if control == "b":
                    group.style = replace(group.style, bold=arg != 0 if arg is not None else True)
                elif control == "i":
                    group.style = replace(group.style, italic=arg != 0 if arg is not None else True)
                elif control == "ul":
                    group.style = replace(
                        group.style, underline=arg != 0 if arg is not None else True
                    )
                elif control == "ulnone":
                    group.style = replace(group.style, underline=False)
                elif control == "plain":
                    group.style = _RtfStyle()
                elif control == "uc":
                    if arg is not None:
                        group.unicode_skip = max(arg, 0)
                elif control == "u":
                    if arg is not None and not group.skip_destination:
                        text = _decode_rtf_unicode_char(arg)
                        render_style = _append_rtf_text(out, render_style, group.style, text)
                    next_i = _skip_rtf_fallback_chars(body, next_i, group.unicode_skip)
                elif control in {"par", "line"}:
                    if not group.skip_destination:
                        render_style = _append_rtf_text(out, render_style, group.style, "\n")
                elif control == "tab":
                    if not group.skip_destination:
                        render_style = _append_rtf_text(out, render_style, group.style, "\t")

            i = next_i
            continue

        if ch not in "\r\n" and not group.skip_destination:
            render_style = _append_rtf_text(out, render_style, group.style, ch)
        i += 1

    _emit_rtf_style_transition(out, render_style, _RtfStyle())
    return "".join(out)


def _read_rung0_comment(data: bytes) -> tuple[bytes | None, int]:
    """Extract rung 0's comment from the fixed preamble at 0x0260.

    Returns (raw_rtf_bytes | None, payload_len).
    """
    payload_len = struct.unpack_from("<I", data, _PAYLOAD_LENGTH_OFFSET)[0]
    if payload_len > 0:
        rtf = bytes(data[_PAYLOAD_BYTES_OFFSET : _PAYLOAD_BYTES_OFFSET + payload_len])
        return rtf, payload_len
    return None, 0


# ---------------------------------------------------------------------------
# Private helpers — cell boundary detection
# ---------------------------------------------------------------------------


def _is_cell_signature(data: bytes, pos: int, expected_col: int, expected_row_byte: int) -> bool:
    """Check whether ``pos`` is the start of a cell with the given col/row."""
    return (
        pos + CELL_SIZE <= len(data)
        and data[pos] == 0x00
        and data[pos + 0x01] == expected_col
        and data[pos + 0x05] == expected_row_byte
        and data[pos + 0x09] == 0x01
        and data[pos + 0x0A] == 0x01
    )


def _find_next_cell(data: bytes, search_from: int, expected_col: int, row_byte: int) -> int:
    """Scan forward to find the start of the next cell in the same row.

    Used when the current cell is an instruction cell (> 0x40 bytes).
    """
    limit = min(search_from + _CELL_SCAN_LIMIT, len(data) - CELL_SIZE)
    for pos in range(search_from, limit + 1):
        if _is_cell_signature(data, pos, expected_col, row_byte):
            return pos
    raise DecodeError(
        f"Cannot find cell boundary for col={expected_col}, "
        f"row_byte={row_byte:#x} scanning from {search_from:#x}"
    )


def _find_row_end(data: bytes, search_from: int, row_byte: int) -> int:
    """Find the end of the last cell (col 31) in a data row.

    Uses the current row's ``row_byte`` to look for the next row
    (``row_byte + 1`` at +0x05) or a terminal/padding boundary.
    """
    next_row_byte = (row_byte + 1) & 0xFF
    limit = min(search_from + _CELL_SCAN_LIMIT * 2, len(data) - CELL_SIZE)

    for pos in range(search_from, limit + 1):
        # Next grid row's cell 0: col=0, expected row_byte, structural 01-01.
        if _is_cell_signature(data, pos, 0, next_row_byte):
            return pos
        # Terminal row signature.
        if (
            data[pos + 0x01] == 0x01
            and data[pos + 0x02] == 0x01
            and data[pos + 0x03] == 0x30
            and data[pos + 0x05] == 0xFF
        ):
            return pos

    # Fallback: first 16-byte zero run (start of page padding).
    for pos in range(search_from, limit + 1):
        if data[pos : pos + 0x10] == b"\x00" * 0x10:
            return pos

    # Last resort: assume standard cell size.
    return search_from


# ---------------------------------------------------------------------------
# Private helpers — data row decoding
# ---------------------------------------------------------------------------

# Per-cell boundary info: (cell_start, cell_end, has_instruction).
_CellBound = tuple[int, int, bool]


def _walk_row_cells(data: bytes, cursor: int) -> list[_CellBound]:
    """Walk cells in a data row and return their byte boundaries.

    Returns one ``(cell_start, cell_end, has_instr)`` tuple per column
    (32 entries).  Handles both fixed-size wire cells (0x40 bytes) and
    variable-length instruction cells.
    """
    row_byte = data[cursor + 0x05]
    pos = cursor
    cells: list[_CellBound] = []

    for col in range(COLS_PER_ROW):
        has_instr = data[pos + _INSTR_DATA_OFFSET] != 0

        if has_instr:
            # Use blob structure to find minimum scan start — large blobs
            # (e.g. Math at ~8KB) can contain byte patterns that fool the
            # heuristic cell-signature scanner.  Skip past the 16-byte
            # tail too — tail bytes can match cell signatures when
            # row_byte is small (e.g. 0x01).
            scan_from = pos + CELL_SIZE
            try:
                instr_start = pos + _INSTR_DATA_OFFSET
                _, blob_end, _ = find_blob_boundary(data[instr_start:])
                blob_abs_end = instr_start + blob_end + CELL_TAIL_SIZE
                if blob_abs_end > scan_from:
                    scan_from = blob_abs_end
            except (ValueError, IndexError):
                pass
            if col < COLS_PER_ROW - 1:
                next_pos = _find_next_cell(data, scan_from, col + 1, row_byte)
            else:
                next_pos = _find_row_end(data, scan_from, row_byte)
        else:
            next_pos = pos + CELL_SIZE

        cells.append((pos, next_pos, has_instr))
        pos = next_pos

    return cells


#: Why a rung with a down wire in its output column decodes as an undecoded marker.
AF_DOWN_WIRE = (
    "the output column has a down wire, which isn't supported. CLICK's syntax check removes it."
)


def _decode_data_row(
    data: bytes, cursor: int, *, refuse_af_down: bool = False
) -> tuple[list[ConditionToken], AfToken]:
    """Decode one grid data row by walking cells sequentially.

    Pass ``refuse_af_down`` when the row's content is being kept, so a down wire in the AF
    column raises instead of being dropped.

    Returns ``(conditions, af_token)``.

    Raises
    ------
    _CellError
        For a cell whose bytes can't be read, naming its column.
    """
    cell_bounds = _walk_row_cells(data, cursor)
    conditions: list[ConditionToken] = []
    af_token: AfToken = ""

    for col, (pos, next_pos, has_instr) in enumerate(cell_bounds):
        try:
            if col < CONDITION_COLUMNS:
                conditions.append(_decode_condition_cell(data, pos, next_pos, has_instr))
                continue
            # AF column (col 31)
            if refuse_af_down and data[pos + 0x21] != 0:
                raise _CellError(col, AF_DOWN_WIRE)
            af_token = _decode_af_cell(data, pos, next_pos, has_instr)
        except _CellError:
            raise
        except BAD_BYTES as exc:
            raise _CellError(col, reason(exc)) from exc
    return conditions, af_token


def _decode_condition_cell(data: bytes, pos: int, next_pos: int, has_instr: bool) -> ConditionToken:
    """The token of one condition cell (columns A..AE)."""
    if has_instr:
        instr_raw = bytes(data[pos + _INSTR_DATA_OFFSET : next_pos])
        parsed = parse_condition_blob(instr_raw)
        if parsed is None:
            return UnknownCondition(raw=instr_raw)
        # Read wire_down flag from cell header (+0x21).
        if data[pos + 0x21] == 1:
            parsed.wire_down = True
        return parsed
    seg = data[pos + 0x19]  # segment flag (+0x19)
    wr = data[pos + 0x1D]
    wd = data[pos + 0x21]
    key = (seg, wr, wd)
    token = _FLAGS_TO_TOKEN.get(key)
    if token is None:
        raise DecodeError(f"unknown wire flags (segment, right, down) = {key}")
    return token


def _decode_af_cell(data: bytes, pos: int, next_pos: int, has_instr: bool) -> AfToken:
    """The token of the AF cell (column 31)."""
    if not has_instr:
        return "NOP" if data[pos + 0x1D] == 1 else ""
    instr_raw = bytes(data[pos + _INSTR_DATA_OFFSET : next_pos])
    parsed_af = parse_af_blob(instr_raw)
    if parsed_af is not None and _fits_stored_span(parsed_af, data[pos + 0x09]):
        keep_cell_rows(parsed_af, data[pos + 0x09], data[pos + 0x0A])
        return parsed_af
    # Try to extract a raw instruction blob.
    try:
        class_name, blob_end, part_count = find_blob_boundary(instr_raw)
        # Keep the cell's row span (+0x09) and sub-rows (+0x0A).
        return RawInstruction(
            class_name=class_name,
            blob=instr_raw[:blob_end],
            part_count=part_count,
            visual_rows=data[pos + 0x09] or None,
            sub_rows=data[pos + 0x0A] or None,
        )
    except (ValueError, IndexError):
        return UnknownInstruction(raw=instr_raw)


# ---------------------------------------------------------------------------
# Private helpers — grid walking
# ---------------------------------------------------------------------------

# Row classification tags.
_DATA = "DATA"
_PREAMBLE = "PREAMBLE"
#: A row the walk can't read: it and every row after it are lost.
_LOST = "LOST"

# (tag, cursor, comment_rtf for PREAMBLE | error text for LOST | None)
_RowInfo = tuple[str, int, bytes | str | None]


def _is_terminal(data: bytes, pos: int) -> bool:
    """The terminal row's signature.  The full check avoids a data row with row_byte 0xFF."""
    return data[pos + 0x05] == 0xFF and data[pos + 0x01] == 0x01 and data[pos + 0x03] == 0x30


def _walk_grid(data: bytes, grid_start: int, total_grid_rows: int) -> tuple[list[_RowInfo], bool]:
    """Walk grid rows and classify each as DATA or PREAMBLE.

    Returns (row_infos, is_multi_rung).
    Stops early if a TERMINAL row (``+0x05 == 0xFF``) is encountered.

    For data rows, walks all 32 cells to determine the actual row size
    (which may exceed ``GRID_ROW_STRIDE`` if instruction cells are present).

    A row before the last one the program header counts that is cut off, holds no cell 0,
    or whose cells can't be walked is LOST, and the walk stops: where the next row starts
    is known only from this row's end.  So is a row taken for a preamble that may not be
    one: a preamble row's cell 0 must carry the cell signature, numbered one past the row
    before it, and its cell 1 must have the preamble flag (+0x30) too.
    """
    cursor = grid_start
    row_infos: list[_RowInfo] = []
    is_multi = False
    row_byte: int | None = None  # the row byte (+0x05) of the row before

    for index in range(total_grid_rows):
        last = index == total_grid_rows - 1
        if cursor + CELL_SIZE > len(data):
            if not last:
                row_infos.append((_LOST, cursor, f"the buffer ends before grid row {index}"))
            break

        if _is_terminal(data, cursor):
            # Terminal sentinel — end of grid.
            is_multi = True
            break

        if data[cursor + 0x30] == 0x01:
            # Preamble row — multi-rung boundary.
            expected = data[cursor + 0x05] if row_byte is None else (row_byte + 1) & 0xFF
            if not _is_cell_signature(data, cursor, 0, expected):
                if not last:
                    error = f"grid row {index} is a preamble row with no cell 0 at {cursor:#x}"
                    row_infos.append((_LOST, cursor, error))
                break
            cmt_len = int.from_bytes(data[cursor + 0x34 : cursor + 0x38], "little")
            # Every cell of a preamble row has +0x30 set; a data row's cell 1 has it clear.
            cell1 = cursor + CELL_SIZE + cmt_len
            if cell1 + CELL_SIZE > len(data) or data[cell1 + 0x30] != 0x01:
                if not last:
                    error = f"grid row {index} has the preamble flag on cell 0 only, at {cursor:#x}"
                    row_infos.append((_LOST, cursor, error))
                break
            is_multi = True
            row_byte = expected
            if cmt_len > 0:
                cmt_rtf = bytes(data[cursor + 0x38 : cursor + 0x38 + cmt_len])
            else:
                cmt_rtf = None
            row_infos.append((_PREAMBLE, cursor, cmt_rtf))
            cursor += GRID_ROW_STRIDE + cmt_len
            continue

        # Data row — but only decode if cell 0 has valid structural bytes.  The trailing
        # "extra" row in single-rung buffers (and CLICK's own buffers with non-zero padding)
        # may lack them.
        if not (data[cursor + 0x09] == 0x01 and data[cursor + 0x0A] == 0x01):
            if not last:
                error = f"grid row {index} has no cell 0 at {cursor:#x}"
                row_infos.append((_LOST, cursor, error))
            break
        try:
            row_end = _walk_row_cells(data, cursor)[-1][1]
        except BAD_BYTES as exc:
            row_infos.append((_LOST, cursor, reason(exc)))
            break
        row_infos.append((_DATA, cursor, None))
        row_byte = data[cursor + 0x05]
        cursor = row_end

    return row_infos, is_multi


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def decode(data: bytes) -> list[Rung]:
    """Decode a clipboard binary into its rungs, one or several.

    Parameters
    ----------
    data:
        Raw clipboard bytes (page-aligned, starts with ``CLICK   `` magic).

    Returns
    -------
    list[Rung]
        One ``Rung`` per rung of the buffer, in order: a list of one for a single-rung
        buffer.  A rung that can't be decoded comes back as an undecoded marker rung
        (:func:`laddercodec.undecoded.marker_rung`), with an ``UndecodedRungWarning``.
        When the cells can't be walked, the marker stands for that rung and every rung
        after it; when that happens in rung 0, before any preamble row, the decoder can't
        tell one rung from several and returns the marker rung alone in the list.

    Raises
    ------
    DecodeError
        If the buffer is invalid: its magic or size.
    """
    _validate_buffer(data)
    row_word = struct.unpack_from("<I", data, PROGRAM_HEADER_BASE)[0]
    total_grid_rows = row_word // 0x20
    rung0_rtf, payload_len = _read_rung0_comment(data)
    grid_start = GRID_FIRST_ROW_START + payload_len
    row_infos, is_multi = _walk_grid(data, grid_start, total_grid_rows)
    failed: list[tuple[int, str]] = []
    if is_multi:
        rungs = _decode_multi(data, row_infos, rung0_rtf, failed)
        warn_legacy(rungs)
        warn_refused(rungs)
        warn_comments(failed)
        warn_undecoded(rungs)
        return rungs
    rung = _decode_single(data, row_infos, total_grid_rows, rung0_rtf, failed)
    warn_legacy([rung])
    warn_refused([rung])
    warn_comments(failed)
    warn_undecoded([rung])
    return [rung]


def decode_rung(data: bytes) -> Rung:
    """Decode a single-rung clipboard binary.

    Parameters
    ----------
    data:
        Raw clipboard bytes (page-aligned, starts with ``CLICK   `` magic).

    Returns
    -------
    Rung
        Decoded rung data matching ``encode_rung()`` input contract.

    Raises
    ------
    DecodeError
        If the buffer is invalid or contains multiple rungs.  A rung that can't be decoded
        comes back as an undecoded marker rung, as from :func:`decode`.
    """
    _validate_buffer(data)

    row_word = struct.unpack_from("<I", data, PROGRAM_HEADER_BASE)[0]
    total_grid_rows = row_word // 0x20

    rung0_rtf, payload_len = _read_rung0_comment(data)
    grid_start = GRID_FIRST_ROW_START + payload_len

    row_infos, is_multi = _walk_grid(data, grid_start, total_grid_rows)

    if is_multi:
        raise DecodeError("Buffer contains multiple rungs; use decode_rungs()")

    failed: list[tuple[int, str]] = []
    rung = _decode_single(data, row_infos, total_grid_rows, rung0_rtf, failed)
    warn_legacy([rung])
    warn_refused([rung])
    warn_comments(failed)
    warn_undecoded([rung])
    return rung


def decode_rungs(data: bytes) -> list[Rung]:
    """Decode a multi-rung clipboard binary.

    Parameters
    ----------
    data:
        Raw clipboard bytes (page-aligned, starts with ``CLICK   `` magic).

    Returns
    -------
    list[Rung]
        One entry per rung, in order.

    Raises
    ------
    DecodeError
        If the buffer is invalid or contains only a single rung.  A rung that can't be
        decoded comes back as an undecoded marker rung, as from :func:`decode`; when the
        walk stops in rung 0, which can't tell one rung from several, the list holds that
        rung's marker only.
    """
    _validate_buffer(data)

    row_word = struct.unpack_from("<I", data, PROGRAM_HEADER_BASE)[0]
    total_grid_rows = row_word // 0x20

    rung0_rtf, payload_len = _read_rung0_comment(data)
    grid_start = GRID_FIRST_ROW_START + payload_len

    row_infos, is_multi = _walk_grid(data, grid_start, total_grid_rows)

    # A walk that stops before any preamble row can't tell one rung from several.
    if not is_multi and not (row_infos and row_infos[-1][0] == _LOST):
        raise DecodeError("Buffer contains a single rung; use decode_rung()")

    failed: list[tuple[int, str]] = []
    rungs = _decode_multi(data, row_infos, rung0_rtf, failed)
    warn_legacy(rungs)
    warn_refused(rungs)
    warn_comments(failed)
    warn_undecoded(rungs)
    return rungs


def _decode_single(
    data: bytes,
    row_infos: list[_RowInfo],
    total_grid_rows: int,
    rung0_rtf: bytes | None,
    failed: list[tuple[int, str]],
) -> Rung:
    """Decode a single-rung buffer from pre-walked grid info."""
    # Single-rung: total_grid_rows = logical_rows + 1 (format quirk).
    logical_rows = total_grid_rows - 1
    data_rows = [ri for ri in row_infos if ri[0] != _PREAMBLE][:logical_rows]

    if len(data_rows) < logical_rows and all(ri[0] == _DATA for ri in data_rows):
        error = f"expected {logical_rows} data rows, found {len(data_rows)}"
        data_rows.append((_LOST, -1, error))
    return _build_rung(data, data_rows, rung0_rtf, 0, failed)


def _decode_multi(
    data: bytes,
    row_infos: list[_RowInfo],
    rung0_rtf: bytes | None,
    failed: list[tuple[int, str]],
) -> list[Rung]:
    """Decode a multi-rung buffer from pre-walked grid info."""
    # Group DATA rows into rungs, split by PREAMBLE boundaries.
    # Rung 0: DATA rows before first PREAMBLE (comment from fixed preamble).
    # Rung N>0: DATA rows after PREAMBLE[N] (comment from that preamble).
    rungs: list[Rung] = []
    current_data: list[_RowInfo] = []  # the current rung's data rows
    current_rtf: bytes | None = rung0_rtf  # rung 0 uses fixed preamble

    for info in row_infos:
        tag, _, extra = info
        if tag == _PREAMBLE:
            # Flush the current rung.  One with no data rows is a marker to the end.
            rungs.append(_build_rung(data, current_data, current_rtf, len(rungs), failed))
            if not current_data:
                return rungs
            current_data = []
            current_rtf = extra if isinstance(extra, bytes) else None
        else:
            current_data.append(info)

    # Flush the last rung (data rows after the final preamble).
    rungs.append(_build_rung(data, current_data, current_rtf, len(rungs), failed))
    return rungs


def _fits_stored_span(af: AfInstruction, span: int) -> bool:
    """True when *af*'s class height is the row span its cell stores (+0x09; 0 stores none).

    A box stored at another span stays raw with its stored bytes: CLICK keeps a 1-row
    Email, Home, Position or Velocity pasted from an earlier laddercodec at 1 row until
    its dialog is saved.
    """
    return span == 0 or int(af.cell_params().get("visual_rows", 1)) == span


def _drop_tall_span_nops(instructions: list[AfToken]) -> None:
    """Clear stray NOPs that fall inside a tall instruction's row span.

    An AF instruction owns ``visual_rows`` grid rows.  A NOP on one of its
    continuation rows is editing cruft — e.g. a NOP left stranded when the
    user inserts a row above it — not a real op, so drop it.  The main-input
    row of a box with lead slots is exempt: count_down's NOP bridge row is a
    genuine part of the instruction.
    """
    for i, af in enumerate(instructions):
        if not isinstance(af, AfInstruction):
            continue
        bridge = i + af.lead_rows if isinstance(af, PinnedInstruction) and af.lead_rows else -1
        span = int(af.cell_params().get("visual_rows", 1))
        for j in range(i + 1, min(i + span, len(instructions))):
            if j != bridge and instructions[j] == "NOP":
                instructions[j] = ""


def _build_rung(
    data: bytes,
    rows: list[_RowInfo],
    rtf: bytes | None,
    rung: int,
    failed: list[tuple[int, str]],
) -> Rung:
    """Build rung number *rung* from its walked data rows.

    A rung that can't be decoded (a row the walk could not read, a cell that does not
    decode, or no data rows at all) is an undecoded marker rung.  A LOST row ends the walk,
    so its marker stands for this rung and every rung after it, as does a rung with no data
    rows: the walk took a row for a preamble that was not one, or lost count of the rows.
    A comment that does not decode is noted in the comment and added to *failed*
    (:func:`laddercodec.undecoded.read_comment`).
    """
    comment = read_comment(rtf, rung, failed)
    if not rows:
        return marker_rung(Undecoded(to_the_end("the rung has no data rows", rung), rung), comment)

    conditions: list[list[ConditionToken]] = []
    instructions: list[AfToken] = []
    for row, (tag, cursor, error) in enumerate(rows):
        if tag != _DATA:
            return marker_rung(Undecoded(to_the_end(str(error), rung), rung, row), comment)
        try:
            conds, af = _decode_data_row(data, cursor, refuse_af_down=True)
        except _CellError as exc:
            return marker_rung(Undecoded(reason(exc), rung, row, exc.column), comment)
        except BAD_BYTES as exc:
            return marker_rung(Undecoded(reason(exc), rung, row), comment)
        conditions.append(conds)
        instructions.append(af)
    _drop_tall_span_nops(instructions)

    return Rung(
        logical_rows=len(rows),
        conditions=conditions,
        instructions=instructions,
        comment=comment,
        comment_rtf=rtf,
    )


# ---------------------------------------------------------------------------
# Cell inspection
# ---------------------------------------------------------------------------

# Column letter → 0-based grid column index.
_COL_TO_INDEX: dict[str, int] = {name: i for i, name in enumerate(_COLUMN_NAMES)}
_COL_TO_INDEX[_AF_NAME] = CONDITION_COLUMNS  # 31


def inspect_cells(
    data: bytes,
    cells: list[tuple[int, int, str]],
) -> list[CellDump]:
    """Dump raw bytes for specific cells in a clipboard binary.

    Parameters
    ----------
    data:
        Raw clipboard bytes.
    cells:
        List of ``(rung_index, visual_row, column_letter)`` tuples.
        Column is ``"A"``..``"AE"`` for conditions or ``"AF"`` for output.

    Returns
    -------
    list[CellDump]
        One entry per requested cell, in the same order as *cells*.

    Example::

        dumps = inspect_cells(raw, [(0, 1, "A"), (0, 1, "B")])
        for d in dumps:
            print(d)
    """
    _validate_buffer(data)

    row_word = struct.unpack_from("<I", data, PROGRAM_HEADER_BASE)[0]
    total_grid_rows = row_word // 0x20

    rung0_rtf, payload_len = _read_rung0_comment(data)
    grid_start = GRID_FIRST_ROW_START + payload_len

    row_infos, _ = _walk_grid(data, grid_start, total_grid_rows)

    # Group data-row cursors by rung.
    rung_rows: list[list[int]] = []  # rung_rows[rung_idx] = [cursor, ...]
    current: list[int] = []
    for tag, cursor, _ in row_infos:
        if tag == _DATA:
            current.append(cursor)
        elif tag == _PREAMBLE:
            if current:
                rung_rows.append(current)
            current = []
    if current:
        rung_rows.append(current)

    results: list[CellDump] = []
    for rung_idx, vis_row, col_letter in cells:
        col_upper = col_letter.upper()
        col_idx = _COL_TO_INDEX.get(col_upper)
        if col_idx is None:
            raise DecodeError(f"Unknown column {col_letter!r}")
        if rung_idx < 0 or rung_idx >= len(rung_rows):
            raise DecodeError(f"Rung {rung_idx} out of range (have {len(rung_rows)} rungs)")
        row_cursors = rung_rows[rung_idx]
        if vis_row < 0 or vis_row >= len(row_cursors):
            raise DecodeError(
                f"Row {vis_row} out of range in rung {rung_idx} (have {len(row_cursors)} rows)"
            )

        row_cursor = row_cursors[vis_row]
        cell_bounds = _walk_row_cells(data, row_cursor)
        conditions, af_token = _decode_data_row(data, row_cursor)

        pos, next_pos, _has_instr = cell_bounds[col_idx]
        cell_raw = bytes(data[pos:next_pos])
        seg = data[pos + 0x19]
        wr = data[pos + 0x1D]
        wd = data[pos + 0x21]

        token: ConditionToken | AfToken | None
        if col_idx < CONDITION_COLUMNS:
            token = conditions[col_idx]
        else:
            token = af_token

        results.append(
            CellDump(
                rung=rung_idx,
                row=vis_row,
                col=col_upper,
                offset=pos,
                size=next_pos - pos,
                raw=cell_raw,
                flags=(seg, wr, wd),
                token=token,
            )
        )

    return results
