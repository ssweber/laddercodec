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

Known instruction types are decoded into ``Contact`` (condition columns)
or ``Coil`` (AF column) domain objects from ``model.py``.  Unrecognised
cells fall back to ``UnknownCondition`` / ``UnknownInstruction`` with
raw bytes preserved.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

from .csv.contract import CONDITION_COLUMNS as _COLUMN_NAMES
from .csv.contract import OUTPUT_COLUMN as _AF_NAME
from .encode import _PREFIX, _SUFFIX, CONDITION_COLUMNS
from .instructions import (
    BlockCopy,
    Coil,
    CompareContact,
    Contact,
    Copy,
    Counter,
    End,
    Fill,
    ForLoop,
    Next,
    Pack,
    RawInstruction,
    Return,
    Shift,
    Timer,
    Unpack,
    parse_af_blob,
    parse_condition_blob,
)
from .instructions.raw import find_blob_boundary
from .topology import (
    CELL_SIZE,
    CELL_TAIL_SIZE,
    COLS_PER_ROW,
    GRID_FIRST_ROW_START,
    GRID_ROW_STRIDE,
    PREAMBLE_COMMENT_BODY,
    PREAMBLE_COMMENT_LENGTH,
    PROGRAM_HEADER_BASE,
    RUNG0_PREAMBLE_BASE,
)

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class DecodeError(ValueError):
    """Raised when a clipboard binary cannot be decoded."""


@dataclass
class UnknownCondition:
    """Instruction cell on a condition column (A..AE).

    The wire flags (always ``(1,1,0)`` for contacts) are implicit.
    ``raw`` carries the instruction-specific bytes from cell offset
    ``+0x25`` to the cell boundary.
    """

    raw: bytes


@dataclass
class UnknownInstruction:
    """Instruction cell on the AF column.

    ``raw`` carries the instruction-specific bytes from cell offset
    ``+0x25`` to the cell boundary.
    """

    raw: bytes


#: A condition-column cell: wire token, parsed Contact/CompareContact, or unknown blob.
ConditionToken = str | Contact | CompareContact | UnknownCondition

#: An AF-column cell: ``""`` / ``"NOP"`` string, parsed AF instruction model,
#: raw opaque blob, or unknown blob.
AfToken = (
    str
    | Coil
    | Timer
    | Counter
    | Copy
    | BlockCopy
    | Fill
    | Pack
    | Unpack
    | ForLoop
    | Next
    | Shift
    | End
    | Return
    | RawInstruction
    | UnknownInstruction
)


@dataclass
class Rung:
    """Structured rung data — used for both decode output and encode input.

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

# RTF body -> markdown patterns.
# Group-style (our encoder output): {\b text}
_RE_GROUP_BOLD = re.compile(r"\{\\b\s(.+?)\}", re.DOTALL)
_RE_GROUP_ITALIC = re.compile(r"\{\\i\s(.+?)\}", re.DOTALL)
_RE_GROUP_UNDERLINE = re.compile(r"\{\\ul\s(.+?)\}", re.DOTALL)
# Toggle-style (Click native): \b text\b0 / \ul text\ulnone
_RE_TOGGLE_BOLD = re.compile(r"\\b\s(.+?)\\b0", re.DOTALL)
_RE_TOGGLE_ITALIC = re.compile(r"\\i\s(.+?)\\i0", re.DOTALL)
_RE_TOGGLE_UNDERLINE = re.compile(r"\\ul\s(.+?)\\ulnone", re.DOTALL)

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


def _decode_rtf(payload: bytes) -> str:
    """Convert an RTF comment payload to markdown text.

    Strips the RTF envelope (prefix/suffix), decodes the cp1252 body,
    and converts RTF inline styles back to markdown.
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

    if payload.endswith(_SUFFIX):
        body_end = len(payload) - len(_SUFFIX)
    else:
        # Fallback: find last \par } sequence.
        idx = payload.rfind(b"\\par }")
        if idx == -1:
            raise DecodeError("Cannot locate RTF body: no \\par } in suffix")
        body_end = idx

    body = payload[body_start:body_end].decode("cp1252")

    # Strip RTF source line endings (CR/LF before \par are insignificant).
    body = body.replace("\r\n\\par ", "\\par ")
    body = body.replace("\r\\par ", "\\par ")

    # RTF markup -> markdown.  Group-style first (more specific), then toggle.
    body = _RE_GROUP_BOLD.sub(r"**\1**", body)
    body = _RE_GROUP_ITALIC.sub(r"*\1*", body)
    body = _RE_GROUP_UNDERLINE.sub(r"__\1__", body)
    body = _RE_TOGGLE_BOLD.sub(r"**\1**", body)
    body = _RE_TOGGLE_ITALIC.sub(r"*\1*", body)
    body = _RE_TOGGLE_UNDERLINE.sub(r"__\1__", body)

    # Line breaks.
    body = body.replace("\\par ", "\n")

    # Unescape RTF special characters.
    body = body.replace("\\{", "{")
    body = body.replace("\\}", "}")
    body = body.replace("\\\\", "\\")

    # Strip any remaining stray CR.
    body = body.replace("\r", "")

    return body


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


def _decode_data_row(data: bytes, cursor: int) -> tuple[list[ConditionToken], AfToken, int]:
    """Decode one grid data row by walking cells sequentially.

    Handles both fixed-size wire cells (0x40 bytes) and variable-length
    instruction cells.  Instruction cells are detected by a non-zero
    byte at cell offset ``+0x25``.

    Returns ``(conditions, af_token, actual_row_size)``.
    """
    row_byte = data[cursor + 0x05]
    pos = cursor
    conditions: list[ConditionToken] = []
    af_token: AfToken = ""

    for col in range(COLS_PER_ROW):
        has_instr = data[pos + _INSTR_DATA_OFFSET] != 0

        # Determine cell boundary.
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

        if col < CONDITION_COLUMNS:
            if has_instr:
                instr_raw = bytes(data[pos + _INSTR_DATA_OFFSET : next_pos])
                parsed = parse_condition_blob(instr_raw)
                if parsed is not None:
                    # Read wire_down flag from cell header (+0x21).
                    if data[pos + 0x21] == 1:
                        parsed.wire_down = True
                    conditions.append(parsed)
                else:
                    conditions.append(UnknownCondition(raw=instr_raw))
            else:
                seg = data[pos + 0x19]  # segment flag (+0x19)
                wr = data[pos + 0x1D]
                wd = data[pos + 0x21]
                key = (seg, wr, wd)
                token = _FLAGS_TO_TOKEN.get(key)
                if token is None:
                    raise DecodeError(
                        f"Unknown wire flags {key} at row cursor={cursor:#x}, col={col}"
                    )
                conditions.append(token)
        else:  # AF column (col 31)
            if has_instr:
                instr_raw = bytes(data[pos + _INSTR_DATA_OFFSET : next_pos])
                parsed_af = parse_af_blob(instr_raw)
                if parsed_af is not None:
                    af_token = parsed_af
                else:
                    # Try to extract a raw instruction blob.
                    try:
                        class_name, blob_end, part_count = find_blob_boundary(instr_raw)
                        af_token = RawInstruction(
                            class_name=class_name,
                            blob=instr_raw[:blob_end],
                            part_count=part_count,
                        )
                    except (ValueError, IndexError):
                        af_token = UnknownInstruction(raw=instr_raw)
            else:
                af_token = "NOP" if data[pos + 0x1D] == 1 else ""

        pos = next_pos

    return conditions, af_token, pos - cursor


# ---------------------------------------------------------------------------
# Private helpers — grid walking
# ---------------------------------------------------------------------------

# Row classification tags.
_DATA = "DATA"
_PREAMBLE = "PREAMBLE"

# (tag, cursor, comment_rtf | None)
_RowInfo = tuple[str, int, bytes | None]


def _walk_grid(data: bytes, grid_start: int, total_grid_rows: int) -> tuple[list[_RowInfo], bool]:
    """Walk grid rows and classify each as DATA or PREAMBLE.

    Returns (row_infos, is_multi_rung).
    Stops early if a TERMINAL row (``+0x05 == 0xFF``) is encountered.

    For data rows, walks all 32 cells to determine the actual row size
    (which may exceed ``GRID_ROW_STRIDE`` if instruction cells are present).
    """
    cursor = grid_start
    row_infos: list[_RowInfo] = []
    is_multi = False

    for _ in range(total_grid_rows):
        if cursor + CELL_SIZE > len(data):
            break

        marker_05 = data[cursor + 0x05]
        marker_30 = data[cursor + 0x30]

        if marker_05 == 0xFF and data[cursor + 0x01] == 0x01 and data[cursor + 0x03] == 0x30:
            # Terminal sentinel — end of grid.  Full signature check
            # avoids false positives when a data row has row_byte 0xFF.
            is_multi = True
            break

        if marker_30 == 0x01:
            # Preamble row — multi-rung boundary.
            is_multi = True
            cmt_len = int.from_bytes(data[cursor + 0x34 : cursor + 0x38], "little")
            if cmt_len > 0:
                cmt_rtf = bytes(data[cursor + 0x38 : cursor + 0x38 + cmt_len])
            else:
                cmt_rtf = None
            row_infos.append((_PREAMBLE, cursor, cmt_rtf))
            cursor += GRID_ROW_STRIDE + cmt_len
        else:
            # Data row — but only decode if cell 0 has valid structural
            # bytes.  The trailing "extra" row in single-rung buffers
            # (and native captures with non-zero padding) may lack them.
            cell0_valid = (
                cursor + CELL_SIZE <= len(data)
                and data[cursor + 0x09] == 0x01
                and data[cursor + 0x0A] == 0x01
            )
            if cell0_valid:
                row_infos.append((_DATA, cursor, None))
                _, _, row_size = _decode_data_row(data, cursor)
                cursor += row_size
            else:
                # Not a valid data row — stop walking.
                break

    return row_infos, is_multi


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def decode(data: bytes) -> Rung | list[Rung]:
    """Decode a clipboard binary. Returns Rung for single-rung, list[Rung] for multi-rung.

    Parameters
    ----------
    data:
        Raw clipboard bytes (page-aligned, starts with ``CLICK   `` magic).

    Returns
    -------
    Rung | list[Rung]
        A single ``Rung`` for single-rung buffers, or a list of ``Rung``
        objects for multi-rung buffers.

    Raises
    ------
    DecodeError
        If the buffer is invalid.
    """
    _validate_buffer(data)
    row_word = struct.unpack_from("<H", data, PROGRAM_HEADER_BASE)[0]
    total_grid_rows = row_word // 0x20
    rung0_rtf, payload_len = _read_rung0_comment(data)
    grid_start = GRID_FIRST_ROW_START + payload_len
    row_infos, is_multi = _walk_grid(data, grid_start, total_grid_rows)
    if is_multi:
        return _decode_multi(data, row_infos, rung0_rtf)
    return _decode_single(data, row_infos, total_grid_rows, rung0_rtf)


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
        If the buffer is invalid or contains multiple rungs.
    """
    _validate_buffer(data)

    row_word = struct.unpack_from("<H", data, PROGRAM_HEADER_BASE)[0]
    total_grid_rows = row_word // 0x20

    rung0_rtf, payload_len = _read_rung0_comment(data)
    grid_start = GRID_FIRST_ROW_START + payload_len

    row_infos, is_multi = _walk_grid(data, grid_start, total_grid_rows)

    if is_multi:
        raise DecodeError("Buffer contains multiple rungs; use decode_rungs()")

    return _decode_single(data, row_infos, total_grid_rows, rung0_rtf)


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
        If the buffer is invalid or contains only a single rung.
    """
    _validate_buffer(data)

    row_word = struct.unpack_from("<H", data, PROGRAM_HEADER_BASE)[0]
    total_grid_rows = row_word // 0x20

    rung0_rtf, payload_len = _read_rung0_comment(data)
    grid_start = GRID_FIRST_ROW_START + payload_len

    row_infos, is_multi = _walk_grid(data, grid_start, total_grid_rows)

    if not is_multi:
        raise DecodeError("Buffer contains a single rung; use decode_rung()")

    return _decode_multi(data, row_infos, rung0_rtf)


def _decode_single(
    data: bytes,
    row_infos: list[_RowInfo],
    total_grid_rows: int,
    rung0_rtf: bytes | None,
) -> Rung:
    """Decode a single-rung buffer from pre-walked grid info."""
    # Single-rung: total_grid_rows = logical_rows + 1 (format quirk).
    logical_rows = total_grid_rows - 1
    data_rows = [ri for ri in row_infos if ri[0] == _DATA][:logical_rows]

    if len(data_rows) < logical_rows:
        raise DecodeError(f"Expected {logical_rows} data rows, found {len(data_rows)}")

    conditions: list[list[ConditionToken]] = []
    instructions: list[AfToken] = []
    for _, cursor, _ in data_rows:
        conds, af, _ = _decode_data_row(data, cursor)
        conditions.append(conds)
        instructions.append(af)

    comment: str | None = None
    if rung0_rtf is not None:
        comment = _decode_rtf(rung0_rtf)

    return Rung(
        logical_rows=logical_rows,
        conditions=conditions,
        instructions=instructions,
        comment=comment,
        comment_rtf=rung0_rtf,
    )


def _decode_multi(
    data: bytes,
    row_infos: list[_RowInfo],
    rung0_rtf: bytes | None,
) -> list[Rung]:
    """Decode a multi-rung buffer from pre-walked grid info."""
    # Group DATA rows into rungs, split by PREAMBLE boundaries.
    # Rung 0: DATA rows before first PREAMBLE (comment from fixed preamble).
    # Rung N>0: DATA rows after PREAMBLE[N] (comment from that preamble).
    rungs: list[Rung] = []
    current_data: list[int] = []  # cursors for current rung's data rows
    current_rtf: bytes | None = rung0_rtf  # rung 0 uses fixed preamble

    for tag, cursor, cmt_rtf in row_infos:
        if tag == _DATA:
            current_data.append(cursor)
        elif tag == _PREAMBLE:
            # Flush the current rung.
            rungs.append(_build_rung(data, current_data, current_rtf))
            current_data = []
            current_rtf = cmt_rtf

    # Flush the last rung (data rows after the final preamble).
    if current_data:
        rungs.append(_build_rung(data, current_data, current_rtf))

    return rungs


def _build_rung(data: bytes, data_cursors: list[int], rtf: bytes | None) -> Rung:
    """Build a Rung from a list of data-row cursors."""
    conditions: list[list[ConditionToken]] = []
    instructions: list[AfToken] = []
    for cursor in data_cursors:
        conds, af, _ = _decode_data_row(data, cursor)
        conditions.append(conds)
        instructions.append(af)

    comment: str | None = None
    if rtf is not None:
        comment = _decode_rtf(rtf)

    return Rung(
        logical_rows=len(data_cursors),
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

    row_word = struct.unpack_from("<H", data, PROGRAM_HEADER_BASE)[0]
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

        # Walk cells in the target row up to the requested column.
        row_cursor = row_cursors[vis_row]
        row_byte = data[row_cursor + 0x05]
        pos = row_cursor
        for c in range(col_idx + 1):
            has_instr = data[pos + _INSTR_DATA_OFFSET] != 0
            if has_instr:
                scan_from = pos + CELL_SIZE
                try:
                    instr_start = pos + _INSTR_DATA_OFFSET
                    _, blob_end, _ = find_blob_boundary(data[instr_start:])
                    blob_abs_end = instr_start + blob_end + CELL_TAIL_SIZE
                    if blob_abs_end > scan_from:
                        scan_from = blob_abs_end
                except (ValueError, IndexError):
                    pass
                if c < COLS_PER_ROW - 1:
                    next_pos = _find_next_cell(data, scan_from, c + 1, row_byte)
                else:
                    next_pos = _find_row_end(data, scan_from, row_byte)
            else:
                next_pos = pos + CELL_SIZE

            if c == col_idx:
                cell_raw = bytes(data[pos:next_pos])
                seg = data[pos + 0x19]  # segment flag (+0x19)
                wr = data[pos + 0x1D]
                wd = data[pos + 0x21]

                # Resolve the decoded token for context.
                token: ConditionToken | AfToken | None = None
                if col_idx < CONDITION_COLUMNS:
                    if has_instr:
                        instr_raw = bytes(data[pos + _INSTR_DATA_OFFSET : next_pos])
                        parsed = parse_condition_blob(instr_raw)
                        token = parsed if parsed is not None else UnknownCondition(raw=instr_raw)
                    else:
                        token = _FLAGS_TO_TOKEN.get((seg, wr, wd))
                else:
                    if has_instr:
                        instr_raw = bytes(data[pos + _INSTR_DATA_OFFSET : next_pos])
                        parsed_af = parse_af_blob(instr_raw)
                        if parsed_af is not None:
                            token = parsed_af
                        else:
                            try:
                                cn, be, pc = find_blob_boundary(instr_raw)
                                token = RawInstruction(
                                    class_name=cn,
                                    blob=instr_raw[:be],
                                    part_count=pc,
                                )
                            except (ValueError, IndexError):
                                token = UnknownInstruction(raw=instr_raw)
                    else:
                        token = "NOP" if data[pos + 0x1D] == 1 else ""

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
                break

            pos = next_pos

    return results
