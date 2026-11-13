"""Program file decoder — Scr*.tmp binary to structured Rung data.

Reads Click Programming Software's internal temp files and produces
the same ``Rung`` objects as the clipboard decoder.

Public API
----------

    decode_program(data)  -> Program

The SCR format is compact (~17x smaller than clipboard) and represents
the full program as stored on disk.  Instruction tag IDs and operand
values are identical to clipboard format — only the framing differs.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import cast

from .binary_helpers import _STANDARD_SENTINEL, _tag_wire_type
from .decode import Rung, _decode_rtf, _drop_tall_span_nops, _fits_stored_span
from .instructions import (
    RawInstruction,
    _with_pin_rows,
    from_tags_af,
    from_tags_condition,
)
from .instructions.comparison import CompareContact
from .instructions.contact import Contact
from .legacy import warn_legacy
from .model import AfInstruction, Program
from .topology import CONDITION_COLUMNS as _CONDITION_COLUMNS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCR_MAGIC = b"SC-SCR  "
_MAX_SECTION_INSTRUCTIONS = 512


_ScrVariantU16Tags = dict[int, dict[int, int]]
_ScrVariantStringTags = dict[int, dict[int, str]]
_ScrSectionInstruction = tuple[
    int,
    int,
    str,
    int,
    dict[int, str],
    bytes,  # part rows, 1-based, main row first
    _ScrVariantU16Tags,
    _ScrVariantStringTags,
    bytes,  # cell rows: the entry's row span and sub-rows (clipboard +0x09, +0x0A)
]


@dataclass(frozen=True)
class _ScrRow:
    """Stored row flags and placement-ordered (segment, column) wire entries."""

    flags: int
    entries: tuple[tuple[int, int], ...]

    @property
    def right_cols(self) -> frozenset[int]:
        return frozenset(col for _segment, col in self.entries)


@dataclass(frozen=True)
class _ScrRowTopologyBlock:
    """Counted rows, including the special first row, followed by down lists.

    Row flags bit 0 maps to column A's clipboard +0x15 field; entry bit 0
    maps to +0x19. Entry presence supplies +0x1D. The first stored row is the
    comment/preamble row, not a fixed three-byte prefix.
    """

    start: int
    stored_rows: tuple[_ScrRow, ...]
    column_count: int
    wiredown: dict[int, tuple[int, ...]]  # ordinary grid row indices, zero-based
    end: int

    @property
    def row_word(self) -> int:
        return len(self.stored_rows)

    @property
    def rows_right_cols(self) -> tuple[frozenset[int], ...]:
        return tuple(row.right_cols for row in self.stored_rows[1:])


@dataclass(frozen=True)
class _ScrHeader:
    name: str
    prog_idx: int
    column_widths: tuple[int, ...]
    # Bits: nicknames, address comments, rung comments, freeze coil area.
    display_flags: int
    rung_count: int
    rungs_start: int  # the u16 index of rung zero


# ---------------------------------------------------------------------------
# SCR header parsing
# ---------------------------------------------------------------------------


def _read_utf16le(data: bytes, offset: int, byte_count: int) -> str:
    """Read a length-prefixed UTF-16LE string."""
    raw = data[offset : offset + byte_count]
    if len(raw) % 2 == 1:
        raw = raw + b"\x00"
    return raw.decode("utf-16-le").rstrip("\x00")


def _parse_header(data: bytes) -> _ScrHeader:
    """Read counted numeric widths, display flags, and the u16 rung count."""
    if len(data) < 0x43 or data[:8] != _SCR_MAGIC:
        raise ValueError(f"Not an SC-SCR file (magic: {data[:8]!r})")

    prog_idx = struct.unpack_from("<H", data, 0x40)[0]
    name_len = data[0x42]
    cursor = 0x43 + name_len
    if cursor + 2 > len(data):
        raise ValueError("truncated SCR name or column count")
    name = _read_utf16le(data, 0x43, name_len)
    column_count = struct.unpack_from("<H", data, cursor)[0]
    cursor += 2
    if not 1 <= column_count <= _CONDITION_COLUMNS + 1:
        raise ValueError(f"unsupported SCR column count: {column_count}")
    widths_end = cursor + 2 * column_count
    if widths_end + 3 > len(data):
        raise ValueError("truncated SCR column widths or display header")
    widths = struct.unpack_from(f"<{column_count}H", data, cursor)
    return _ScrHeader(
        name=name,
        prog_idx=prog_idx,
        column_widths=widths,
        display_flags=data[widths_end],
        rung_count=struct.unpack_from("<H", data, widths_end + 1)[0],
        rungs_start=widths_end + 3,
    )


# ---------------------------------------------------------------------------
# Instruction blob parsing
# ---------------------------------------------------------------------------


def _parse_blob(data: bytes, pos: int, data_len: int = 0) -> tuple[str, int, int, bytes] | None:
    """Parse SCR instruction blob at pos.

    Returns (class_name, type_code, end_offset, part_rows) or None.  ``part_rows``
    holds one 1-based row per part, main row first (``01 02 03 04`` for a drum;
    OR legs under a pin push the later parts down, e.g. ``01 02 04 05``).
    """
    if not data_len:
        data_len = len(data)
    if pos >= data_len - 20:
        return None
    sl = data[pos]
    if not (3 <= sl <= 60 and pos + 1 + sl + 2 <= data_len):
        return None
    try:
        text = _read_utf16le(data, pos + 1, sl)
        type_off = pos + 1 + sl
        marker = struct.unpack_from("<H", data, type_off)[0]
        if not (text and text[0].isupper() and text.isascii() and all(c.isalnum() for c in text)):
            return None
        if not (0x2700 <= marker <= 0x2800):
            return None

        # Fields after the type code:
        #   after_type+0  (2B) — zero in every capture (the box's row span and
        #                        sub-rows are in the entry header)
        #   after_type+2  (2B) — opaque, small values (0, 1, 2, ...)
        #   after_type+4  (2B) — zero in every capture
        #   after_type+6  (1B) — part count (0x01 single part, 0x02+ pinned)
        # Followed by one row byte per part, then end_offset.
        after_type = type_off + 2
        if after_type + 12 > data_len:
            return None
        part_count = data[after_type + 6]
        if not (1 <= part_count <= 8):
            return None
        eo_pos = after_type + 7 + part_count
        if eo_pos + 4 > data_len:
            return None
        # end_offset is the explicit blob boundary pointer — the same boundary
        # that clipboard's find_blob_boundary() derives by scanning tag fields.
        end_offset = struct.unpack_from("<I", data, eo_pos)[0]
        if not (pos < end_offset < data_len):
            return None
        return text, marker, end_offset, data[after_type + 7 : eo_pos]
    except (UnicodeDecodeError, ValueError, struct.error):
        return None


# ---------------------------------------------------------------------------
# SCR blob → parsed instruction
# ---------------------------------------------------------------------------


def _parse_scr_tags(
    data: bytes,
    blob_start: int,
    end_offset: int,
    part_count: int,
) -> tuple[str, int, dict[int, str], _ScrVariantU16Tags, _ScrVariantStringTags]:
    """Parse SCR blob into scalar tags plus compact variant-tag collections.

    Wire type is inferred from each tag's high byte via ``_tag_wire_type``.
    """
    pos = blob_start
    sl = data[pos]
    pos += 1
    class_name = _read_utf16le(data, pos, sl)
    pos += sl
    type_code = struct.unpack_from("<H", data, pos)[0]
    pos += 2
    pos += (
        6 + 1 + part_count + 4
    )  # skip the six zero bytes, part count, part-row bytes and end_offset

    tags: dict[int, str] = {}
    variant_u16_tags: _ScrVariantU16Tags = {}
    variant_string_tags: _ScrVariantStringTags = {}
    while pos < end_offset:
        if pos + 2 > len(data):
            break
        tag = struct.unpack_from("<H", data, pos)[0]
        pos += 2

        if tag == 0x0000:
            tags[tag] = ""
            break

        wire = _tag_wire_type(tag)

        if wire == "variant_u16":
            entries_u16: dict[int, int] = {}
            while pos + 2 <= len(data):
                sub_idx = struct.unpack_from("<H", data, pos)[0]
                pos += 2
                if sub_idx == 0xFFFF:
                    break
                if pos + 2 > len(data):
                    break
                entries_u16[sub_idx] = struct.unpack_from("<H", data, pos)[0]
                pos += 2
            variant_u16_tags[tag] = entries_u16
            continue

        if wire == "variant_string":
            entries_str: dict[int, str] = {}
            while pos + 2 <= len(data):
                sub_idx = struct.unpack_from("<H", data, pos)[0]
                pos += 2
                if sub_idx == 0xFFFF:
                    break
                if pos + 1 > len(data):
                    break
                str_len = data[pos]
                pos += 1
                if pos + str_len > len(data):
                    break
                value_raw = data[pos : pos + str_len]
                if len(value_raw) % 2 == 1:
                    value_raw = value_raw + b"\x00"
                entries_str[sub_idx] = value_raw.decode("utf-16-le", errors="replace").rstrip(
                    "\x00"
                )
                pos += str_len
            variant_string_tags[tag] = entries_str
            continue

        if wire == "flag":
            tags[tag] = ""
            continue

        if wire == "u16":
            if pos + 2 > len(data):
                break
            value = struct.unpack_from("<H", data, pos)[0]
            tags[tag] = str(value)
            pos += 2
            continue

        if wire == "byte":
            if pos + 1 > len(data):
                break
            value = data[pos]
            tags[tag] = str(value)
            pos += 1
            continue

        # Default: length-prefixed UTF-16LE string (wire == "string" or "unknown")
        if pos + 1 > len(data):
            break
        str_len = data[pos]
        pos += 1
        if pos + str_len > len(data):
            break
        value_raw = data[pos : pos + str_len]
        if len(value_raw) % 2 == 1:
            value_raw = value_raw + b"\x00"
        str_value = value_raw.decode("utf-16-le", errors="replace").rstrip("\x00")
        tags[tag] = str_value
        pos += str_len
    return class_name, type_code, tags, variant_u16_tags, variant_string_tags


def _clipboard_part_rows(part_rows: bytes) -> bytes:
    """SCR part rows as the clipboard blob's extra bytes (rows below the main part).

    SCR rows are the parts' 1-based rung rows: a count_down whose main part
    sits on rung row 1 stores ``02 03 04``.
    """
    return bytes(row - part_rows[0] for row in part_rows[1:])


def _scr_af(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    part_rows: bytes,
    variant_u16_tags: _ScrVariantU16Tags,
    variant_string_tags: _ScrVariantStringTags,
) -> AfInstruction | None:
    """Build an AF instruction from SCR tags, with each pin on its stored row."""
    parsed_af = from_tags_af(
        class_name,
        type_code,
        tags,
        variant_u16_tags,
        variant_string_tags,
    )
    return _with_pin_rows(parsed_af, _clipboard_part_rows(part_rows))


def _infer_af_visual_rows(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    part_rows: bytes,
    variant_u16_tags: _ScrVariantU16Tags,
    variant_string_tags: _ScrVariantStringTags,
    cell_rows: bytes,
) -> int:
    """Rows the AF box of an SCR entry spans: those of the box ``_scr_box`` builds."""
    box = _scr_box(
        class_name, type_code, tags, part_rows, variant_u16_tags, variant_string_tags, cell_rows
    )
    return max(1, int(box.cell_params().get("visual_rows", 1)))


def _scr_box(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    part_rows: bytes,
    variant_u16_tags: _ScrVariantU16Tags,
    variant_string_tags: _ScrVariantStringTags,
    cell_rows: bytes,
) -> AfInstruction:
    """The AF box of an SCR entry: typed when its class height is the stored row span.

    Otherwise, as in the clipboard decoder, it stays raw with the entry's row bytes
    (the clipboard cell's +0x09 and +0x0A).
    """
    parsed_af = _scr_af(
        class_name,
        type_code,
        tags,
        part_rows,
        variant_u16_tags,
        variant_string_tags,
    )
    if parsed_af is not None and _fits_stored_span(parsed_af, cell_rows[0]):
        return parsed_af
    return _scr_raw(class_name, type_code, tags, part_rows, cell_rows)


def _scr_raw(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    part_rows: bytes,
    cell_rows: bytes,
) -> RawInstruction:
    """A minimal RawInstruction from SCR tag data.

    The entry's row bytes are the clipboard cell's +0x09 and +0x0A.
    """
    from .instructions.raw import _compose_blob

    blob = _compose_blob(
        class_name,
        type_code,
        len(part_rows),
        _clipboard_part_rows(part_rows),
        [(t, _STANDARD_SENTINEL, v) for t, v in tags.items()],
    )
    return RawInstruction(
        class_name=class_name,
        blob=blob,
        part_count=len(part_rows),
        visual_rows=cell_rows[0] or None,
        sub_rows=cell_rows[1] or None,
    )


# ---------------------------------------------------------------------------
# Row topology parsing
# ---------------------------------------------------------------------------


def _parse_row_block(data: bytes, pos: int, data_len: int) -> tuple[_ScrRow, int] | None:
    """Read flags u8, count u16, and count (segment u8, column u8) pairs."""
    if pos < 0 or pos + 3 > data_len:
        return None
    flags = data[pos]
    count = struct.unpack_from("<H", data, pos + 1)[0]
    if flags & ~3 or count > _CONDITION_COLUMNS + 1:
        return None
    end = pos + 3 + count * 2
    if end > data_len:
        return None
    entries: list[tuple[int, int]] = []
    seen: set[int] = set()
    for off in range(pos + 3, end, 2):
        segment, col = data[off : off + 2]
        if segment not in (0, 1) or col > _CONDITION_COLUMNS or col in seen:
            return None
        entries.append((segment, col))
        seen.add(col)
    return _ScrRow(flags, tuple(entries)), end


def _parse_wiredown_table(
    data: bytes,
    pos: int,
    data_len: int,
    column_count: int = 32,
    stored_row_count: int | None = None,
) -> tuple[dict[int, tuple[int, ...]], int] | None:
    """Read a u16 count and that many stored-row index bytes per column.

    Stored row zero is special. Down lists refer to ordinary rows starting
    at one; convert them to zero-based grid coordinates.
    """
    result: dict[int, tuple[int, ...]] = {}
    for col in range(column_count):
        if pos + 2 > data_len:
            return None
        count = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        if pos + count > data_len:
            return None
        indices = data[pos : pos + count]
        if any(r == 0 or (stored_row_count is not None and r >= stored_row_count) for r in indices):
            return None
        if indices:
            result[col] = tuple(sorted({r - 1 for r in indices}))
        pos += count
    return result, pos


def _parse_row_topology_block(
    data: bytes,
    pos: int,
    data_len: int = 0,
) -> _ScrRowTopologyBlock | None:
    """Read every counted row, then the counted column down lists."""
    if not data_len:
        data_len = len(data)
    if pos < 0 or pos + 2 > data_len:
        return None
    stored_row_count = struct.unpack_from("<H", data, pos)[0]
    if not 2 <= stored_row_count <= 33:
        return None
    cursor = pos + 2
    rows: list[_ScrRow] = []
    for _ in range(stored_row_count):
        parsed = _parse_row_block(data, cursor, data_len)
        if parsed is None:
            return None
        row, cursor = parsed
        rows.append(row)
    if cursor + 2 > data_len:
        return None
    column_count = struct.unpack_from("<H", data, cursor)[0]
    if not 1 <= column_count <= _CONDITION_COLUMNS + 1:
        return None
    if any(col >= column_count for row in rows for _seg, col in row.entries):
        return None
    parsed_wd = _parse_wiredown_table(
        data,
        cursor + 2,
        data_len,
        column_count,
        stored_row_count,
    )
    if parsed_wd is None:
        return None
    wiredown, end = parsed_wd
    return _ScrRowTopologyBlock(pos, tuple(rows), column_count, wiredown, end)


# ---------------------------------------------------------------------------
# Linear rung-record walk
# ---------------------------------------------------------------------------
# Every rung, including zero: u16 index, u32 RTF length, RTF body, topology,
# u16 instruction count, then (if nonempty) u32 section marker and entries.
# Main programs (prog_idx == 1) have a two-byte file tail.


@dataclass(frozen=True)
class _ScrRungRecord:
    """One complete rung record from the linear walk."""

    comment: str | None
    comment_rtf: bytes | None
    topology: _ScrRowTopologyBlock
    instructions: list[_ScrSectionInstruction]


def _parse_section_entries(
    data: bytes, pos: int, count: int, data_len: int
) -> tuple[list[_ScrSectionInstruction], int] | None:
    """Parse ``count`` instruction entries; returns (instructions, end_pos).

    Each entry is a fixed 8-byte header followed by a blob whose explicit
    ``end_offset`` plus the 1-byte trailer length at that offset determine the
    next entry position.  Header bytes 2 and 3 are the box's row span and
    sub-rows, the bytes a clipboard cell holds at +0x09 and +0x0A.
    """
    results: list[_ScrSectionInstruction] = []
    cursor = pos
    for _ in range(count):
        if cursor + 9 > data_len:
            return None
        blob = _parse_blob(data, cursor + 8, data_len)
        if blob is None:
            return None
        row_1based = data[cursor]
        col_idx = data[cursor + 1]
        _cls, _marker, end_off, part_rows = blob
        cn, tc, tags, v_u16, v_str = _parse_scr_tags(data, cursor + 8, end_off, len(part_rows))
        cell_rows = bytes(data[cursor + 2 : cursor + 4])
        results.append((row_1based - 1, col_idx, cn, tc, tags, part_rows, v_u16, v_str, cell_rows))

        trailer_len = data[end_off]
        if trailer_len > 8:
            return None
        cursor = end_off + 2 + trailer_len
        if cursor > data_len:
            return None
    return results, cursor


def _walk_rung_records(data: bytes, header: _ScrHeader) -> list[_ScrRungRecord]:
    """Walk the declared records; reject malformed framing without resync."""
    pos = header.rungs_start
    limit = len(data) - (2 if header.prog_idx == 1 else 0)
    records: list[_ScrRungRecord] = []
    for index in range(header.rung_count):
        if pos + 6 > limit:
            raise ValueError(f"truncated rung prefix at 0x{pos:X} (rung {index})")
        got = struct.unpack_from("<H", data, pos)[0]
        if got != index:
            raise ValueError(f"rung index mismatch at 0x{pos:X}: expected {index}, got {got}")
        pos += 2

        rtf_len = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        comment: str | None = None
        rtf_bytes: bytes | None = None
        if rtf_len:
            if pos + rtf_len > limit or data[pos : pos + 6] != b"{\\rtf1":
                raise ValueError(f"invalid rung comment at 0x{pos:X} (rung {index})")
            rtf_bytes = bytes(data[pos : pos + rtf_len])
            try:
                comment = _decode_rtf(rtf_bytes)
            except Exception:
                comment = None
            pos += rtf_len

        block = _parse_row_topology_block(data, pos, limit)
        if block is None:
            raise ValueError(f"unparseable rung topology at 0x{pos:X} (rung {index})")
        if block.column_count != len(header.column_widths):
            raise ValueError(f"column count mismatch at 0x{pos:X} (rung {index})")
        pos = block.end

        if pos + 2 > limit:
            raise ValueError(f"truncated section count at 0x{pos:X} (rung {index})")
        count = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        instructions: list[_ScrSectionInstruction] = []
        if count:
            if count > _MAX_SECTION_INSTRUCTIONS or pos + 4 > limit:
                raise ValueError(f"invalid section header at 0x{pos - 2:X} (rung {index})")
            pos += 4  # section_marker: opaque per-file constant
            parsed = _parse_section_entries(data, pos, count, limit)
            if parsed is None:
                raise ValueError(f"unparseable section entries at 0x{pos:X} (rung {index})")
            instructions, pos = parsed

        records.append(_ScrRungRecord(comment, rtf_bytes, block, instructions))

    if pos != limit:
        raise ValueError(f"rung walk ended at 0x{pos:X}, expected 0x{limit:X}")
    return records


def _is_trailing_placeholder(record: _ScrRungRecord) -> bool:
    """Trailing content-less rung: no instructions and no comment.

    Click programs keep 1..4 ordinary empty rungs in the editor below the
    last programmed rung (some carry a fully-wired row).  They are real rung
    records, but content-less — only instructions or a comment make a
    trailing record worth emitting.
    """
    return not record.instructions and record.comment_rtf is None


def _build_topology_backed_rung(
    topology_block: _ScrRowTopologyBlock,
    logical_rows: int,
    section_instructions: list[_ScrSectionInstruction],
    comment: str | None,
    comment_rtf: bytes | None,
) -> Rung:
    """Map ordinary stored rows directly to grid rows.

    Preserve wires above later rail-connected rows. Segment patterns depend
    on editing history and cannot establish that an earlier row is debris.
    The semantic Rung model does not retain raw row/segment flags.
    """
    rows = topology_block.rows_right_cols
    wiredown = topology_block.wiredown

    row0 = rows[0] if rows else frozenset()
    return _build_rung(
        logical_rows=logical_rows,
        section_instructions=section_instructions,
        row0_flags=dict.fromkeys(row0, 1),
        extra_rows_right_wires=[set(r) for r in rows[1:]],
        wiredown=wiredown,
        comment=comment,
        comment_rtf=comment_rtf,
    )


# ---------------------------------------------------------------------------
# Rung construction
# ---------------------------------------------------------------------------


def _build_rung(
    logical_rows: int,
    section_instructions: list[_ScrSectionInstruction],
    row0_flags: dict[int, int],
    extra_rows_right_wires: list[set[int]],
    wiredown: dict[int, tuple[int, ...]],
    comment: str | None,
    comment_rtf: bytes | None,
) -> Rung:
    """Build a Rung from parsed SCR components."""
    from .instructions import AfToken, ConditionToken, UnknownCondition

    # Initialize grids
    conditions: list[list[ConditionToken]] = [
        cast(list[ConditionToken], [""] * _CONDITION_COLUMNS) for _ in range(logical_rows)
    ]
    instructions: list[AfToken] = cast(list[AfToken], [""] * logical_rows)

    # 1. Place instructions from instruction section
    instr_positions: set[tuple[int, int]] = set()
    for (
        row,
        col,
        class_name,
        type_code,
        tags,
        part_rows,
        variant_u16_tags,
        variant_string_tags,
        cell_rows,
    ) in section_instructions:
        if row < 0 or row >= logical_rows:
            continue
        if col < _CONDITION_COLUMNS:
            parsed = from_tags_condition(
                class_name,
                type_code,
                tags,
                variant_u16_tags,
                variant_string_tags,
            )
            if parsed is not None:
                conditions[row][col] = parsed
            else:
                conditions[row][col] = UnknownCondition(raw=class_name.encode())
            instr_positions.add((row, col))
        elif col == _CONDITION_COLUMNS:
            instructions[row] = _scr_box(
                class_name,
                type_code,
                tags,
                part_rows,
                variant_u16_tags,
                variant_string_tags,
                cell_rows,
            )

    # A stored row whose block carries an AF right-wire but no real AF
    # instruction is a NOP (this includes count_down / drum bridge rows).
    if _CONDITION_COLUMNS in row0_flags and instructions[0] == "":
        instructions[0] = "NOP"
    for row_idx, right_wires in enumerate(extra_rows_right_wires, start=1):
        if row_idx >= logical_rows:
            break
        if _CONDITION_COLUMNS in right_wires and instructions[row_idx] == "":
            instructions[row_idx] = "NOP"

    # 2. Apply horizontal wire flags from flag blocks
    # Row 0: use row0_flags
    for col_idx in row0_flags:
        if col_idx >= _CONDITION_COLUMNS:
            continue  # skip AF column
        if (0, col_idx) not in instr_positions:
            conditions[0][col_idx] = "-"

    # Extra rows: SCR stores the explicit set of right-wired columns.
    for extra_row_idx, right_columns in enumerate(extra_rows_right_wires):
        row = extra_row_idx + 1
        if row >= logical_rows:
            break
        for col_idx in right_columns:
            if col_idx >= _CONDITION_COLUMNS:
                continue
            if (row, col_idx) not in instr_positions:
                conditions[row][col_idx] = "-"

    # 3. Apply wire_down (vertical wires going down)
    for col, row_indices in wiredown.items():
        if col >= _CONDITION_COLUMNS:
            continue
        for row in row_indices:
            if not (0 <= row < logical_rows):
                continue
            cell = conditions[row][col]
            if isinstance(cell, str):
                if cell == "-":
                    conditions[row][col] = "T"  # horizontal + down
                elif cell == "":
                    conditions[row][col] = "|"  # vertical only
                # "T" or "|" already set — keep as is
            elif isinstance(cell, (Contact, CompareContact)):
                cell.wire_down = True

    # Drop stray NOPs that land inside a tall instruction's row span (e.g. a
    # NOP left stranded on a drum pin row) — same rule as the clipboard decoder.
    _drop_tall_span_nops(instructions)

    return Rung(
        logical_rows=logical_rows,
        conditions=conditions,
        instructions=instructions,
        comment=comment,
        comment_rtf=comment_rtf,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def decode_program(data: bytes) -> Program:
    """Decode an SC-SCR temp file into a Program.

    Parameters
    ----------
    data:
        Raw bytes of a ``Scr*.tmp`` file (starts with ``SC-SCR  `` magic).

    Returns
    -------
    Program
        Program with name, prog_idx, and rungs parsed from the file.

    Raises
    ------
    ValueError
        If the file cannot be parsed, or a rung has a down wire in the output column.
    """
    header = _parse_header(data)
    records = _walk_rung_records(data, header)

    # Drop trailing content-less rungs — the ordinary empty rungs Click keeps
    # below the last programmed rung (a rung-scoped clipboard copy excludes
    # them too).
    while records and _is_trailing_placeholder(records[-1]):
        records.pop()

    rungs: list[Rung] = []
    for record in records:
        inferred_rows = 1
        for (
            row,
            col,
            class_name,
            type_code,
            tags,
            part_rows,
            variant_u16_tags,
            variant_string_tags,
            cell_rows,
        ) in record.instructions:
            inferred_rows = max(inferred_rows, row + 1)
            if col == _CONDITION_COLUMNS:
                visual_rows = _infer_af_visual_rows(
                    class_name,
                    type_code,
                    tags,
                    part_rows,
                    variant_u16_tags,
                    variant_string_tags,
                    cell_rows,
                )
                inferred_rows = max(inferred_rows, row + visual_rows)

        logical_rows = max(1, record.topology.row_word - 1, inferred_rows)
        af_down = [
            r for r in record.topology.wiredown.get(_CONDITION_COLUMNS, ()) if 0 <= r < logical_rows
        ]
        if af_down:
            raise ValueError(
                f"Rung {len(rungs)}, row {af_down[0]} (zero-based): the output column has a "
                "down wire, which isn't supported. CLICK's syntax check removes it."
            )
        rungs.append(
            _build_topology_backed_rung(
                topology_block=record.topology,
                logical_rows=logical_rows,
                section_instructions=record.instructions,
                comment=record.comment,
                comment_rtf=record.comment_rtf,
            )
        )

    warn_legacy(rungs, program=header.name)
    return Program(name=header.name, prog_idx=header.prog_idx, rungs=rungs)
