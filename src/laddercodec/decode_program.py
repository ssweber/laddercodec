"""Decode a CLICK program file (``Scr*.tmp``) into ``Rung`` objects.

Reads Click Programming Software's internal temp files and produces
the same ``Rung`` objects as the clipboard decoder.

Public API
----------

    decode_program(data)  -> Program

An SCR file holds the whole program as CLICK stores it on disk. It is
about 17 times smaller than the clipboard form. It uses the same
instruction tag IDs and operand values as the clipboard. Only the
framing differs.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .binary_helpers import _STANDARD_SENTINEL, _tag_wire_type
from .decode import AF_DOWN_WIRE, Rung, _drop_tall_span_nops, _fits_stored_span
from .errors import DecodeError
from .instructions import (
    RawInstruction,
    _with_pin_rows,
    from_tags_af,
    from_tags_condition,
)
from .instructions.undecoded import Stop
from .legacy import warn_legacy
from .model import AfInstruction, Program
from .operands.unchecked import keep_cell_rows, keep_stored_blob, needs_stored_blob
from .refused import warn_refused
from .topology import CONDITION_COLUMNS as _CONDITION_COLUMNS
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
# Constants
# ---------------------------------------------------------------------------

_SCR_MAGIC = b"SC-SCR  "
_MAX_SECTION_INSTRUCTIONS = 512
#: The main program's index. Its file ends with two extra bytes, and an undecoded marker
#: in it acts as ``end()``.
_MAIN_PROG_IDX = 1


_ScrVariantU16Tags = dict[int, dict[int, int]]
_ScrVariantStringTags = dict[int, dict[int, str]]
_ScrSectionInstruction = tuple[
    int,
    int,
    str,
    int,
    dict[int, str],
    bytes,  # part rows: each part's 1-based rung row, top part first
    _ScrVariantU16Tags,
    _ScrVariantStringTags,
    bytes,  # cell rows: the entry's row span and sub-rows (clipboard +0x09, +0x0A)
]


@dataclass(frozen=True)
class _ScrRow:
    """One stored row: its flags and its (segment, column) wire entries, in stored order."""

    flags: int
    entries: tuple[tuple[int, int], ...]

    @property
    def right_cols(self) -> frozenset[int]:
        return frozenset(col for _segment, col in self.entries)


@dataclass(frozen=True)
class _ScrRowTopologyBlock:
    """A rung's stored rows, then the down list of each column.

    The first stored row is the comment (preamble) row. It is a full row
    block, not a fixed three-byte prefix. Bit 0 of a row's flags is the
    clipboard's +0x15 field in column A. An entry's segment bit is +0x19,
    and a column with an entry has +0x1D set.
    """

    start: int
    stored_rows: tuple[_ScrRow, ...]
    column_count: int
    wiredown: dict[int, tuple[int, ...]]  # zero-based grid rows; the comment row is not one
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
    rungs_start: int  # offset of rung zero's record, which starts with its u16 index


# ---------------------------------------------------------------------------
# SCR header parsing
# ---------------------------------------------------------------------------


def _read_utf16le(data: bytes, offset: int, byte_count: int) -> str:
    """Return *byte_count* bytes at *offset* decoded as UTF-16LE, without trailing NULs."""
    raw = data[offset : offset + byte_count]
    if len(raw) % 2 == 1:
        raw = raw + b"\x00"
    return raw.decode("utf-16-le").rstrip("\x00")


def _parse_header(data: bytes) -> _ScrHeader:
    """Return the file header: program index, name, column widths, display flags, rung count."""
    if len(data) < 0x43 or data[:8] != _SCR_MAGIC:
        raise DecodeError(f"Not an SC-SCR file (magic: {data[:8]!r})")

    prog_idx = struct.unpack_from("<H", data, 0x40)[0]
    name_len = data[0x42]
    cursor = 0x43 + name_len
    if cursor + 2 > len(data):
        raise DecodeError("truncated SCR name or column count")
    try:
        name = _read_utf16le(data, 0x43, name_len)
    except UnicodeDecodeError as exc:
        raise DecodeError(f"SCR name is not UTF-16LE text: {exc}") from exc
    column_count = struct.unpack_from("<H", data, cursor)[0]
    cursor += 2
    if not 1 <= column_count <= _CONDITION_COLUMNS + 1:
        raise DecodeError(f"unsupported SCR column count: {column_count}")
    widths_end = cursor + 2 * column_count
    if widths_end + 3 > len(data):
        raise DecodeError("truncated SCR column widths or display header")
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
    """Parse the SCR instruction blob at *pos*.

    Returns (class_name, type_code, end_offset, part_rows), or None if the bytes
    are not a blob. ``part_rows`` holds one 1-based rung row per part, top part
    first. A drum on the first row stores ``01 02 03 04``. An OR leg under a pin
    pushes the later parts down, as in ``01 02 04 05``.
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
        # end_offset points at the end of the blob. For the clipboard,
        # find_blob_boundary() finds the same end by scanning the tag fields.
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
    """Parse the SCR blob at *blob_start* into its class name, type code and tags.

    Plain tags come back in one dict. Variant tags come back in two more dicts, one
    for u16 values and one for strings. ``_tag_wire_type`` reads the value type of
    each tag from its high byte.
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
    )  # skip the six bytes after the type code, part count, part-row bytes and end_offset

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
    """Return SCR part rows as the clipboard blob's extra bytes.

    The SCR file stores each part's rung row, counting from 1. The clipboard
    stores the row of each part after the first, counted from the first part. For
    example, if the stored part rows are ``02 03 04``, this returns ``01 02``.
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
    """Return the number of rows spanned by the AF box that ``_scr_box`` builds for an entry."""
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
    """Return the AF box of an SCR entry.

    The box is the typed instruction if the height of that instruction matches the row
    span that the entry stores, or if the entry stores none. Otherwise the box is a
    ``RawInstruction`` that keeps the entry's row bytes, which are the clipboard cell's
    +0x09 and +0x0A. The clipboard decoder does the same.
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
        if needs_stored_blob(parsed_af):
            # The instruction holds refusals, or it read a stored address in another form:
            # without a space at its start or end, or in display form where CLICK saved it
            # as typed. While its fields are unchanged, it writes the blob that a raw box
            # of this entry would write.
            keep_stored_blob(parsed_af, _scr_blob(class_name, type_code, tags, part_rows))
            keep_cell_rows(parsed_af, cell_rows[0], cell_rows[1])
        return parsed_af
    return _scr_raw(class_name, type_code, tags, part_rows, cell_rows)


def _scr_blob(class_name: str, type_code: int, tags: dict[int, str], part_rows: bytes) -> bytes:
    """Return the clipboard blob that a raw box writes, built from an SCR entry's tags."""
    from .instructions.raw import _compose_blob

    return _compose_blob(
        class_name,
        type_code,
        len(part_rows),
        _clipboard_part_rows(part_rows),
        [(t, _STANDARD_SENTINEL, v) for t, v in tags.items()],
    )


def _scr_raw(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    part_rows: bytes,
    cell_rows: bytes,
) -> RawInstruction:
    """Return a ``RawInstruction`` built from the tags of an SCR entry.

    Its rows and sub-rows come from the entry's row bytes, which are the clipboard
    cell's +0x09 and +0x0A.
    """
    return RawInstruction(
        class_name=class_name,
        blob=_scr_blob(class_name, type_code, tags, part_rows),
        part_count=len(part_rows),
        rows=cell_rows[0] or None,
        sub=cell_rows[1] or None,
    )


# ---------------------------------------------------------------------------
# Row topology parsing
# ---------------------------------------------------------------------------


def _parse_row_block(data: bytes, pos: int, data_len: int) -> tuple[_ScrRow, int] | None:
    """Return one stored row and the offset after it, or None if the bytes are not a row.

    A row is a u8 of flags, a u16 count, and that many (segment u8, column u8) pairs.
    """
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
    """Return the down list of each column and the offset after the table, or None.

    For each column the table holds a u16 count and that many stored-row indices,
    one byte each. Stored row 0 is the comment row, so a down list cannot name it,
    and grid row 0 is stored row 1. The returned lists hold zero-based grid rows.
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
    """Return the rows and down lists of one rung, or None if the bytes are not valid.

    The block is a u16 row count, that many rows, a u16 column count, and the down
    list of each column.
    """
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
    """One rung's record from an SCR file: its comment RTF, rows and instructions."""

    comment_rtf: bytes | None
    topology: _ScrRowTopologyBlock
    instructions: list[_ScrSectionInstruction]


def _parse_section_entries(
    data: bytes, pos: int, count: int, data_len: int
) -> tuple[list[_ScrSectionInstruction], int] | None:
    """Parse ``count`` instruction entries. Returns (instructions, end_pos), or None.

    Each entry is a fixed 8-byte header followed by a blob. At the blob's
    ``end_offset`` is a 1-byte trailer length, and the next entry starts
    ``2 + trailer length`` bytes after ``end_offset``. Header bytes 2 and 3 are
    the box's row span and sub-rows, which a clipboard cell holds at +0x09 and
    +0x0A.
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
    """Return every record that the header declares. Raise ``DecodeError`` on bad framing."""
    records, error = _walk_until_framing_error(data, header)
    if error is not None:
        raise DecodeError(f"{error} (rung {len(records)})")
    return records


class _UnconfirmedEnd(DecodeError):
    """Raised for a framing error after which the last record read may be wrong.

    Only the next record's prefix, which holds its index, confirms where a record ends.
    For the last record, the end of the file confirms it. When that check fails, the
    record before may have ended in the wrong place. For example, a section count one
    too low ends the record early, and it would decode as the wrong rung.
    """


def _walk_until_framing_error(
    data: bytes, header: _ScrHeader
) -> tuple[list[_ScrRungRecord], str | None]:
    """Return the records before the first malformed one, and the framing error or None.

    The function does not search for a later rung to resume at, so it loses every record
    from the framing error on. It also drops the record before a prefix that is cut off
    or holds the wrong index, and the last record when the file does not end after it.
    The end of such a record is not confirmed (:class:`_UnconfirmedEnd`).
    """
    records: list[_ScrRungRecord] = []
    try:
        _read_rung_records(data, header, records)
    except _UnconfirmedEnd as exc:
        if records:
            records.pop()
        return records, reason(exc)
    except BAD_BYTES as exc:
        return records, reason(exc)
    return records, None


def _read_rung_records(data: bytes, header: _ScrHeader, records: list[_ScrRungRecord]) -> None:
    """Append each record that the header declares to *records*.

    Raise ``DecodeError`` when the framing of a record is malformed.
    """
    pos = header.rungs_start
    limit = len(data) - (2 if header.prog_idx == _MAIN_PROG_IDX else 0)
    for index in range(header.rung_count):
        if pos + 6 > limit:
            raise _UnconfirmedEnd(f"truncated rung prefix at 0x{pos:X}")
        got = struct.unpack_from("<H", data, pos)[0]
        if got != index:
            raise _UnconfirmedEnd(f"rung index mismatch at 0x{pos:X}: expected {index}, got {got}")
        pos += 2

        rtf_len = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        rtf_bytes: bytes | None = None
        if rtf_len:
            if pos + rtf_len > limit or data[pos : pos + 6] != b"{\\rtf1":
                raise DecodeError(f"invalid rung comment at 0x{pos:X}")
            rtf_bytes = bytes(data[pos : pos + rtf_len])
            pos += rtf_len

        block = _parse_row_topology_block(data, pos, limit)
        if block is None:
            raise DecodeError(f"unparseable rung topology at 0x{pos:X}")
        if block.column_count != len(header.column_widths):
            raise DecodeError(f"column count mismatch at 0x{pos:X}")
        pos = block.end

        if pos + 2 > limit:
            raise DecodeError(f"truncated section count at 0x{pos:X}")
        count = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        instructions: list[_ScrSectionInstruction] = []
        if count:
            if count > _MAX_SECTION_INSTRUCTIONS or pos + 4 > limit:
                raise DecodeError(f"invalid section header at 0x{pos - 2:X}")
            pos += 4  # section_marker: the same in every rung of a file, meaning unknown
            parsed = _parse_section_entries(data, pos, count, limit)
            if parsed is None:
                raise DecodeError(f"unparseable section entries at 0x{pos:X}")
            instructions, pos = parsed

        records.append(_ScrRungRecord(rtf_bytes, block, instructions))

    if pos != limit:
        raise _UnconfirmedEnd(f"rung walk ended at 0x{pos:X}, expected 0x{limit:X}")


def _is_trailing_placeholder(record: _ScrRungRecord) -> bool:
    """Return True if *record* has no instructions and no comment.

    Click programs keep 1..4 empty rungs in the editor below the last
    programmed rung, and some of them hold a row wired all the way across.
    They are real rung records. The decoder drops such records from the end
    of a program, because only instructions or a comment make one worth
    returning.
    """
    return not record.instructions and record.comment_rtf is None


def _build_topology_backed_rung(
    topology_block: _ScrRowTopologyBlock,
    logical_rows: int,
    section_instructions: list[_ScrSectionInstruction],
    comment: str | None,
    comment_rtf: bytes | None,
) -> Rung:
    """Build the rung, with each stored row after the comment row as one grid row.

    Keep the wires in every stored row, even in a row above a later row that
    connects to the rail. Such a row may be left over from editing, but the
    segment flags depend on how the rung was edited, so they cannot show it.
    The Rung model does not keep the stored row and segment flags.
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
    from .instructions import AfToken, ConditionToken, Tee, UnknownCondition

    # Initialize grids
    conditions: list[list[ConditionToken]] = [
        [""] * _CONDITION_COLUMNS for _ in range(logical_rows)
    ]
    instructions: list[AfToken] = [""] * logical_rows

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

    # A stored row with a right wire in the AF column but no AF instruction holds
    # a NOP. The bridge rows of count_down and drum boxes are such rows.
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

    # 3. Apply the down wires. A down wire in an instruction cell wraps it in a Tee.
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
            elif not isinstance(cell, Tee):
                conditions[row][col] = Tee(cell)

    # Drop stray NOPs inside a tall instruction's rows, such as a NOP left behind
    # on a drum pin row. The clipboard decoder does the same.
    _drop_tall_span_nops(instructions)

    return Rung(
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
        Program with name, prog_idx, and rungs parsed from the file. If a rung can't
        be decoded, an undecoded marker rung takes its place, and the decoder warns
        with ``UndecodedRungWarning``.

        A framing error is a truncated record, or rows or an instruction section that
        the decoder can't read. The rungs before the error decode, and one marker takes
        the place of that rung and every rung after it. If the error is in a record's
        prefix, or the file does not end after the last record, the record before may
        have ended in the wrong place. The marker then starts at that record.

        A marker acts as ``end()`` in the main program and as ``return()`` in a
        subroutine.

    Raises
    ------
    DecodeError
        If the file header cannot be parsed.
    """
    header = _parse_header(data)
    records, framing_error = _walk_until_framing_error(data, header)
    stop: Stop = "end" if header.prog_idx == _MAIN_PROG_IDX else "return"

    # Drop the empty rungs that Click keeps below the last programmed rung. A
    # clipboard copy of the rungs leaves them out too. After a framing error they
    # are dropped before the marker is added, so the marker takes the place of the
    # first of them. That is safe because an empty rung does nothing when it runs.
    while records and _is_trailing_placeholder(records[-1]):
        records.pop()

    failed: list[tuple[int, str]] = []
    rungs = [_record_rung(record, index, stop, failed) for index, record in enumerate(records)]
    if framing_error is not None:
        index = len(rungs)
        rungs.append(marker_rung(Undecoded(to_the_end(framing_error, index), index, stop=stop)))

    warn_legacy(rungs, program=header.name)
    warn_refused(rungs, program=header.name)
    warn_comments(failed, program=header.name)
    warn_undecoded(rungs, program=header.name)
    return Program(name=header.name, prog_idx=header.prog_idx, rungs=rungs)


def _record_rung(
    record: _ScrRungRecord, index: int, stop: Stop, failed: list[tuple[int, str]]
) -> Rung:
    """Return rung *index* of the program, built from *record*, or an undecoded marker rung.

    If the comment does not decode, the rung's comment says so, and ``(index, error)``
    is added to *failed*.
    """
    comment = read_comment(record.comment_rtf, index, failed)

    def marker(error: str, row: int | None = None, column: int | None = None) -> Rung:
        return marker_rung(Undecoded(error, index, row, column, stop), comment)

    seen: set[tuple[int, int]] = set()
    for row, col, *_ in record.instructions:
        if row < 0:
            return marker("an instruction is stored on the comment row", column=_column(col))
        if col > _CONDITION_COLUMNS:
            return marker(f"an instruction is stored in column {col}, past AF", row)
        if (row, col) in seen:
            return marker("two instructions are stored in one cell", row, col)
        seen.add((row, col))

    try:
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
            return marker(AF_DOWN_WIRE, af_down[0], _CONDITION_COLUMNS)
        return _build_topology_backed_rung(
            topology_block=record.topology,
            logical_rows=logical_rows,
            section_instructions=record.instructions,
            comment=comment,
            comment_rtf=record.comment_rtf,
        )
    except BAD_BYTES as exc:
        return marker(reason(exc))


def _column(col: int) -> int | None:
    """Return *col* as an :class:`Undecoded` column, or None if it is past AF."""
    return col if col <= _CONDITION_COLUMNS else None
