"""The decoder that reads a CLICK clipboard binary into ``Rung`` objects.

Each ``Rung`` holds the values that ``encode_rung()`` and ``encode_rungs()`` take as
input.

Public API
----------

    decode(data)             -> list[Rung]
    decode_rung(data)        -> Rung
    decode_rungs(data)       -> list[Rung]
    inspect_cells(data, cells) -> list[CellDump]

``decode_rung`` returns the values that ``encode_rung`` was given, as tuples:

    decode_rung(encode_rung(lr, cr, af, cmt))
        .logical_rows  == lr
        .conditions    == tuple(map(tuple, cr))
        .instructions  == tuple(af)
        .comment       == cmt

Instruction cells
-----------------

A cell that holds a contact or a coil is a horizontal wire cell, with the flags
``(1,1,0)``, that also holds the instruction's data.  A contact cell may also set its down
flag (+0x21) for a wire down.  The decoder returns that cell as a ``Tee`` around the
contact.  The instruction data starts at offset ``+0x25`` in the cell.  It holds the
class name in UTF-16LE, a type marker, the operand and the function code.  A cell with only wires is exactly ``0x40`` bytes long.
A cell with an instruction is longer.

For each instruction type it knows, the decoder builds an object from ``instructions/``,
such as a ``Contact``, ``Coil`` or ``Timer``.  A condition cell that it does not
recognise becomes an ``UnknownCondition``.  An AF cell that it does not recognise becomes
a ``RawInstruction`` when the decoder can find the instruction's blob, and an
``UnknownInstruction`` otherwise.  Each of these keeps the instruction's raw bytes.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from ._comment import PLAIN, Run, Style, write_runs
from .csv.contract import CONDITION_COLUMNS as _COLUMN_NAMES
from .csv.contract import OUTPUT_COLUMN as _AF_NAME
from .encode import _PREFIX, _SUFFIX
from .errors import DecodeError, EncodeError
from .instructions import (
    Condition,
    ConditionToken,
    Instruction,
    InstructionToken,
    RawInstruction,
    Tee,
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
    """Raised when a cell of a data row cannot be decoded.

    ``column`` is the cell's column, counted from 0, so the AF column is 31.
    """

    def __init__(self, column: int, message: str) -> None:
        super().__init__(message)
        self.column = column


@dataclass(frozen=True, init=False)
class Rung:
    """One rung of ladder logic.  The decoders return it, and ``encode()`` accepts it.

    A ``Rung`` holds what the rung means, not how CLICK stored it.  It does not
    keep CLICK's row and segment flags or any trace of how the rung was edited.
    ``encode()`` writes the flags in a standard form, so its bytes can differ
    from the bytes that CLICK wrote.

    A ``Rung`` is frozen.  You may pass lists for ``conditions`` and ``instructions``.
    The rung stores them as tuples, so a rung built from lists equals the same rung built
    from tuples, and it can be hashed.  To change a rung, build a new one or call
    ``laddercodec.replace(rung, instructions=...)``.  A text where a row of
    ``conditions`` or the ``instructions`` list belongs raises
    :class:`~laddercodec.EncodeError`.

    Attributes
    ----------
    conditions:
        One tuple of tokens per row.  Each row has 31 entries, one per
        condition column.  A cell with only wires is a string (``""`` blank,
        ``"-"`` horizontal, ``"|"`` vertical, ``"T"`` junction-down).  A
        contact is an object such as ``Contact``.  A cell that the decoder
        does not recognise is an ``UnknownCondition``.  A cell that holds a
        contact and a wire down from its left edge is a ``Tee`` around the
        contact, such as ``Tee(Contact("X001"))``.  A ``Tee`` is to a
        contact what ``"T"`` is to ``"-"``.
    instructions:
        One AF token per row.  A row with no instruction holds ``"NOP"``
        or ``""``.  An instruction is an object such as ``Coil``.  A cell
        that the decoder does not recognise is a ``RawInstruction`` or an
        ``UnknownInstruction``.
    comment:
        The rung comment as Markdown text, or ``None``.  The CSV form
        uses this text.
    comment_rtf:
        The comment's RTF bytes as the binary stored them, or ``None``.
        ``encode()`` does not read them.  It writes the comment from
        ``comment``.  Two rungs that differ only in ``comment_rtf`` are equal.
    """

    conditions: tuple[tuple[ConditionToken, ...], ...]
    instructions: tuple[InstructionToken, ...]
    comment: str | None
    comment_rtf: bytes | None = field(default=None, compare=False)

    def __init__(
        self,
        conditions: Sequence[Sequence[ConditionToken]],
        instructions: Sequence[InstructionToken],
        comment: str | None,
        comment_rtf: bytes | None = None,
    ) -> None:
        # Read each argument once, so that a generator is checked and stored whole.
        rows = [conditions] if isinstance(conditions, str) else list(conditions)
        # A text where a row belongs is most often one flat row of tokens, which tuple()
        # would split into rows of one cell each.
        for row in rows:
            if isinstance(row, str):
                raise EncodeError(
                    f"conditions holds the text {row!r} where a row belongs. Pass conditions "
                    "as one list of 31 tokens per row, such as [['-'] * 31]."
                )
        if isinstance(instructions, str):
            raise EncodeError(
                f"instructions holds the text {instructions!r} where a list belongs. Pass "
                "one AF token per row, such as ['NOP']."
            )
        # The fields hold tuples whatever sequences the caller passes, so a rung built
        # from lists equals the same rung built from tuples, and hashes the same.
        object.__setattr__(self, "conditions", tuple(tuple(row) for row in rows))
        object.__setattr__(self, "instructions", tuple(instructions))
        object.__setattr__(self, "comment", comment)
        object.__setattr__(self, "comment_rtf", comment_rtf)

    @property
    def logical_rows(self) -> int:
        """The number of rows in the rung, ``len(conditions)``.  ``encode()`` takes 1 to 32."""
        return len(self.conditions)


@dataclass
class CellDump:
    """The raw bytes of one cell and what they decode to, for reverse engineering and debugging.

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
    token: ConditionToken | InstructionToken | None

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
# The segment flag (+0x19) matters to CLICK.  If an encoder writes it
# wrong, CLICK shows the contacts and wires shifted down to a row of
# their own.  The decoder ignores it and picks the token from the
# right and down flags only.
#
# How CLICK draws these wires, for code that follows them through the grid:
#   Click draws the DOWN wire at the LEFT EDGE of the cell, not at its
#   center.  A "-" below a T looks like a corner (└ shape), because the
#   T's down wire meets the "-" at the cell's left edge.  When a "-"
#   has no cell to its RIGHT, look UP one row for a T.  The branch
#   connects there, where the two wires meet at the left edge.
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

# Where rung 0's comment length and comment bytes sit in the rung 0 preamble.
_PAYLOAD_LENGTH_OFFSET = RUNG0_PREAMBLE_BASE + PREAMBLE_COMMENT_LENGTH  # 0x0294
_PAYLOAD_BYTES_OFFSET = RUNG0_PREAMBLE_BASE + PREAMBLE_COMMENT_BODY  # 0x0298

# Instruction data starts at this offset within a cell.
_INSTR_DATA_OFFSET = 0x25


@dataclass
class _RtfGroupState:
    """The state of one RTF group.

    It holds the group's style, whether the group's text is skipped, and how many fallback
    characters follow a ``\\u`` control.
    """

    style: Style
    skip_destination: bool = False
    unicode_skip: int = 1


_RTF_ANSI_CPG_RE = re.compile(rb"\\ansicpg(\d+)")

# Max bytes to scan forward when searching for a cell boundary.
_CELL_SCAN_LIMIT = 0x200

# ---------------------------------------------------------------------------
# Private helpers — buffer validation & RTF
# ---------------------------------------------------------------------------


def _validate_buffer(data: bytes) -> None:
    """Raise :class:`DecodeError` if *data* lacks the magic or ends before the grid starts."""
    if len(data) < len(_MAGIC) or data[: len(_MAGIC)] != _MAGIC:
        raise DecodeError(f"Invalid magic: expected {_MAGIC!r}, got {data[: len(_MAGIC)]!r}")
    if len(data) < GRID_FIRST_ROW_START:
        raise DecodeError(
            f"Buffer too short: need at least {GRID_FIRST_ROW_START:#x} bytes, got {len(data):#x}"
        )


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
    """Raise :class:`DecodeError` unless the RTF prefix declares ANSI code page 1252."""
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
    """Return the character for an RTF ``\\u`` argument, or ``""`` when there is none.

    RTF writes the argument as a signed 16-bit number, so a negative value stands for the
    value plus 0x10000.
    """
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

    It removes the RTF prefix and suffix around the comment text and decodes the
    rest as cp1252.  Then it reads the control words in the body, so that they set
    the style or add a line break or a character, and their names do not appear in
    the text. :func:`write_runs` writes the styled text as Markdown. It puts a backslash
    before a literal ``*``, ``_`` or ``\\`` where the Markdown reader would otherwise read
    the character as a marker or an escape.
    """
    # Find the body between the RTF prefix and suffix.
    if payload.startswith(_PREFIX):
        body_start = len(_PREFIX)
    else:
        # The prefix is not the one encode() writes.  The body starts after the space
        # that follows \fsNN.
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
        # The suffix is not the one encode() writes.  The body ends at the last \par }.
        idx = payload.rfind(b"\\par }")
        if idx == -1:
            raise DecodeError("Cannot locate RTF body: no \\par } in suffix")
        body_end = idx

    body = payload[body_start:body_end].decode("cp1252")

    stack = [_RtfGroupState(style=PLAIN)]
    runs: list[Run] = []
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
                    runs.append((group.style, control))
            elif control == "'":
                if next_i <= len(body) and i + 4 <= len(body):
                    hex_digits = body[i + 2 : i + 4]
                    try:
                        text = bytes([int(hex_digits, 16)]).decode("cp1252")
                    except ValueError:
                        text = ""
                    if text and not group.skip_destination:
                        runs.append((group.style, text))
                    next_i = i + 4
            elif control == "~":
                if not group.skip_destination:
                    runs.append((group.style, " "))
            elif control == "_":
                if not group.skip_destination:
                    runs.append((group.style, "-"))
            elif control == "-":
                if not group.skip_destination:
                    runs.append((group.style, "-"))
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
                    group.style = PLAIN
                elif control == "uc":
                    if arg is not None:
                        group.unicode_skip = max(arg, 0)
                elif control == "u":
                    if arg is not None and not group.skip_destination:
                        text = _decode_rtf_unicode_char(arg)
                        runs.append((group.style, text))
                    next_i = _skip_rtf_fallback_chars(body, next_i, group.unicode_skip)
                elif control in {"par", "line"}:
                    if not group.skip_destination:
                        runs.append((group.style, "\n"))
                elif control == "tab":
                    if not group.skip_destination:
                        runs.append((group.style, "\t"))

            i = next_i
            continue

        if ch not in "\r\n" and not group.skip_destination:
            runs.append((group.style, ch))
        i += 1

    return write_runs(runs)


def _read_rung0_comment(data: bytes) -> tuple[bytes | None, int]:
    """Return rung 0's comment RTF bytes from the fixed preamble at 0x0260, and their length.

    Return ``(None, 0)`` when rung 0 has no comment.
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

    The caller uses it after an instruction cell, which is longer than 0x40 bytes.
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

    It looks for the first cell of the next row, which has ``row_byte + 1`` at +0x05, or
    for the terminal row.  If it finds neither, it looks for the zero bytes where page
    padding starts.
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

    # Last resort: the cell ends where the search started.
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
            # Start the scan after the end of the instruction's blob.  A large
            # blob, such as a Math box at about 8 KB, can hold bytes that look
            # like a cell signature.  Skip the 16-byte cell tail too, because its
            # bytes can look like a cell signature when row_byte is small, such as 0x01.
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
) -> tuple[list[ConditionToken], InstructionToken]:
    """Decode one grid data row by walking cells sequentially.

    Pass ``refuse_af_down=True`` when the row becomes part of a decoded rung.  A down wire
    in the AF column then raises :class:`_CellError`.  Otherwise the decoder ignores it.

    Returns ``(conditions, af_token)``.

    Raises
    ------
    _CellError
        For a cell whose bytes can't be read, naming its column.
    """
    cell_bounds = _walk_row_cells(data, cursor)
    conditions: list[ConditionToken] = []
    af_token: InstructionToken = ""

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
    """Return the token of one condition cell (columns A..AE)."""
    if has_instr:
        instr_raw = bytes(data[pos + _INSTR_DATA_OFFSET : next_pos])
        parsed = parse_condition_blob(instr_raw)
        cell: Condition | UnknownCondition = (
            UnknownCondition(raw=instr_raw) if parsed is None else parsed
        )
        # The down flag (+0x21) of an instruction cell is a wire down from the cell.
        return Tee(cell) if data[pos + 0x21] == 1 else cell
    seg = data[pos + 0x19]  # segment flag (+0x19)
    wr = data[pos + 0x1D]
    wd = data[pos + 0x21]
    key = (seg, wr, wd)
    token = _FLAGS_TO_TOKEN.get(key)
    if token is None:
        raise DecodeError(f"unknown wire flags (segment, right, down) = {key}")
    return token


def _decode_af_cell(data: bytes, pos: int, next_pos: int, has_instr: bool) -> InstructionToken:
    """Return the token of the AF cell (column 31)."""
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
            rows=data[pos + 0x09] or None,
            sub=data[pos + 0x0A] or None,
        )
    except (ValueError, IndexError):
        return UnknownInstruction(raw=instr_raw)


# ---------------------------------------------------------------------------
# Private helpers — grid walking
# ---------------------------------------------------------------------------

# Row classification tags.
_DATA = "DATA"
_PREAMBLE = "PREAMBLE"
#: The tag for a row that the walk can't read.  The walk stops there, so it reads no later row.
_LOST = "LOST"

# (tag, cursor, comment_rtf for PREAMBLE | error text for LOST | None)
_RowInfo = tuple[str, int, bytes | str | None]


def _is_terminal(data: bytes, pos: int) -> bool:
    """Return whether the row at *pos* is the terminal row.

    It checks +0x01 and +0x03 as well as +0x05, so a data row whose row byte is 0xFF
    does not match.
    """
    return data[pos + 0x05] == 0xFF and data[pos + 0x01] == 0x01 and data[pos + 0x03] == 0x30


def _walk_grid(data: bytes, grid_start: int, total_grid_rows: int) -> tuple[list[_RowInfo], bool]:
    """Walk grid rows and tag each one as DATA, PREAMBLE or LOST.

    Returns (row_infos, is_multi_rung).  *is_multi_rung* is True when the walk finds a
    preamble row or the TERMINAL row (``+0x05 == 0xFF``).  The walk stops at the
    TERMINAL row.

    For data rows, walks all 32 cells to determine the actual row size
    (which may exceed ``GRID_ROW_STRIDE`` if instruction cells are present).

    The walk tags a row LOST and stops when the row is cut off, has no cell 0, or has
    cells that can't be walked.  It must stop, because only the end of this row shows
    where the next row starts.  A row that has the preamble flag but fails the preamble
    checks is LOST too.  A preamble row's cell 0 must have the cell signature, with a row
    byte one more than the row before it.  Its cell 1 must have the preamble flag (+0x30)
    as well.

    The program header counts the grid rows.  If the last of them is cut off, has no
    cell 0 or fails the preamble checks, the walk stops there and does not tag it LOST.
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
            # A preamble row starts each rung after the first.
            expected = data[cursor + 0x05] if row_byte is None else (row_byte + 1) & 0xFF
            if not _is_cell_signature(data, cursor, 0, expected):
                if not last:
                    error = f"grid row {index} is a preamble row with no cell 0 at {cursor:#x}"
                    row_infos.append((_LOST, cursor, error))
                break
            cmt_len = int.from_bytes(data[cursor + 0x34 : cursor + 0x38], "little")
            # Every cell of a preamble row has +0x30 set.  A data row's cell 1 has it clear.
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

        # A data row.  Read it only if cell 0 has the structural bytes 01 01 at +0x09 and
        # +0x0A.  The extra row at the end of a single-rung buffer may lack them.  So may
        # the extra row at the end of a buffer from CLICK whose padding is not zero.
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
        One ``Rung`` per rung of the buffer, in order.  A single-rung buffer gives a
        list of one.  A rung that can't be decoded comes back as an undecoded marker
        rung (:func:`laddercodec.undecoded.marker_rung`), with an
        ``UndecodedRungWarning``.  If the decoder can't walk the grid past a row, the
        marker stands for that rung and every rung after it.  If that happens in rung 0,
        before any preamble row, the decoder can't tell one rung from several.  It then
        returns a list that holds only the marker rung.

    Raises
    ------
    DecodeError
        If the buffer does not start with the ``CLICK   `` magic or is too short.
    """
    _validate_buffer(data)
    row_word = struct.unpack_from("<I", data, PROGRAM_HEADER_BASE)[0]
    total_grid_rows = row_word // 0x20
    rung0_rtf, payload_len = _read_rung0_comment(data)
    grid_start = GRID_FIRST_ROW_START + payload_len
    row_infos, is_multi = _walk_grid(data, grid_start, total_grid_rows)
    failed: list[tuple[int, str]] = []
    if is_multi:
        rungs = _decode_multi(data, row_infos, total_grid_rows, rung0_rtf, failed)
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
        The decoded rung.  Its fields hold the values that ``encode_rung()`` takes.

    Raises
    ------
    DecodeError
        If the buffer is invalid or contains multiple rungs.  A rung that can't be decoded
        does not raise.  It comes back as an undecoded marker rung, as from :func:`decode`.
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
        decoded does not raise.  It comes back as an undecoded marker rung, as from
        :func:`decode`.  If the walk stops in rung 0, before any preamble row, the
        decoder can't tell one rung from several.  The list then holds only that rung's
        marker.
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
    rungs = _decode_multi(data, row_infos, total_grid_rows, rung0_rtf, failed)
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
    [(_, data_rows)] = _rung_rows(row_infos, False, total_grid_rows)
    return _build_rung(data, data_rows, rung0_rtf, 0, failed)


def _decode_multi(
    data: bytes,
    row_infos: list[_RowInfo],
    total_grid_rows: int,
    rung0_rtf: bytes | None,
    failed: list[tuple[int, str]],
) -> list[Rung]:
    """Decode a multi-rung buffer from pre-walked grid info."""
    rungs: list[Rung] = []
    for index, (rtf, data_rows) in enumerate(_rung_rows(row_infos, True, total_grid_rows)):
        # Rung 0's comment is in the fixed preamble at 0x0260.
        comment = rung0_rtf if index == 0 else rtf
        rungs.append(_build_rung(data, data_rows, comment, index, failed))
    return rungs


def _rung_rows(
    row_infos: list[_RowInfo], is_multi: bool, total_grid_rows: int
) -> list[tuple[bytes | None, list[_RowInfo]]]:
    """Group the walked rows into rungs, and return each rung's comment and data rows.

    The comment is the RTF that the rung's preamble row holds, or None. Rung 0 has no
    preamble row, so its comment here is always None. If the walk stopped in a rung, that
    rung's rows end with its LOST row. A rung with no data rows is the last in the list,
    and no row after it is grouped.

    A single-rung buffer (*is_multi* False) counts one grid row more than the rung has. If
    the walk found fewer data rows than that, the rows end with a LOST row. A multi-rung
    buffer does not use *total_grid_rows*.
    """
    if not is_multi:
        logical_rows = total_grid_rows - 1
        data_rows = [info for info in row_infos if info[0] != _PREAMBLE][:logical_rows]
        if len(data_rows) < logical_rows and all(info[0] == _DATA for info in data_rows):
            error = f"expected {logical_rows} data rows, found {len(data_rows)}"
            data_rows.append((_LOST, -1, error))
        return [(None, data_rows)]

    rungs: list[tuple[bytes | None, list[_RowInfo]]] = [(None, [])]
    for tag, cursor, extra in row_infos:
        if tag != _PREAMBLE:
            rungs[-1][1].append((tag, cursor, extra))
        elif not rungs[-1][1]:
            break
        else:
            rungs.append((extra if isinstance(extra, bytes) else None, []))
    return rungs


def _fits_stored_span(af: Instruction, span: int) -> bool:
    """Return True when the row span that the cell stores at +0x09 is the height of *af*.

    A box with pins, such as a Counter or a Drum, ends one row below its last pin row.
    Also return True when the cell stores no span (0).  The caller keeps a box stored at
    another span as a ``RawInstruction`` with its stored bytes.  For example, an earlier
    laddercodec wrote Email, Home, Position and Velocity boxes 1 row tall.  When such a box
    is pasted, CLICK keeps it at 1 row until its dialog is saved.
    """
    return span == 0 or int(af.cell_params().get("visual_rows", 1)) == span


def _drop_tall_span_nops(instructions: list[InstructionToken]) -> None:
    """Clear each NOP that sits on a row covered by a tall AF instruction.

    An AF instruction covers ``visual_rows`` grid rows.  A NOP on one of the
    rows below its first row is left over from editing.  For example, a NOP
    stays behind when the user inserts a row above it.  It is not a real
    instruction, so this function replaces it with ``""``.  A box with inputs
    above its main input, such as count_down with its unused Up input, has a
    NOP on its main-input row.  That NOP is part of the box, so it stays.
    """
    for i, af in enumerate(instructions):
        if not isinstance(af, Instruction):
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

    Return an undecoded marker rung when the rung can't be decoded.  That happens when a
    row is LOST, a cell does not decode, or the rung has no data rows.  A LOST row ended the
    walk, so its marker stands for this rung and every rung after it.  The marker for a rung
    with no data rows stands for every later rung too.  Such a rung means that the walk took
    a row for a preamble row when it was not one, or lost count of the rows.  If the comment
    does not decode, :func:`laddercodec.undecoded.read_comment` puts a note in the comment
    and adds the error to *failed*.
    """
    comment = read_comment(rtf, rung, failed)
    if not rows:
        return marker_rung(Undecoded(to_the_end("the rung has no data rows", rung), rung), comment)

    conditions: list[list[ConditionToken]] = []
    instructions: list[InstructionToken] = []
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

        token: ConditionToken | InstructionToken | None
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
