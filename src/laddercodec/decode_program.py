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
from .decode import Rung, _decode_rtf, _drop_tall_span_nops
from .instructions import (
    INSTRUCTION_MODULES,
    RawInstruction,
    from_tags_af,
    from_tags_condition,
)
from .instructions.comparison import CompareContact
from .instructions.contact import Contact
from .model import Program
from .topology import CONDITION_COLUMNS as _CONDITION_COLUMNS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCR_MAGIC = b"SC-SCR  "
_ROW_TOPOLOGY_PREFIX = b"\x03\x00\x00"
_ROW_TOPOLOGY_END_MARKER = b"\x20\x00"
_MAX_SECTION_INSTRUCTIONS = 512


_ScrVariantU16Tags = dict[int, dict[int, int]]
_ScrVariantStringTags = dict[int, dict[int, str]]
_ScrSectionInstruction = tuple[
    int,
    int,
    str,
    int,
    dict[int, str],
    int,
    dict[int, int],
    _ScrVariantU16Tags,
    _ScrVariantStringTags,
]


@dataclass(frozen=True)
class _ScrRowTopologyBlock:
    """Structural row-topology record that precedes a rung's instruction section.

    Uniform framing (verified against all native captures)::

        [row_word u16] [03 00 00]
          (row_word - 1) row blocks, one per grid row, each:
            [flag u8] [count u8] [00]  +  count x ([seg u8] [col u8])
        [20 00]
        32-column wire-down table

    ``flag``/``seg`` are the clipboard +0x19 segment flags (flag = the row's
    AF cell, seg = that condition cell).  Entries are placement-ordered — the
    column sequence is not guaranteed ascending — so columns are kept as sets.
    A count-0 row block is an empty grid row.
    """

    start: int
    row_word: int
    rows_right_cols: tuple[frozenset[int], ...]  # index 0 = grid row 0
    rows_row0_like: tuple[bool, ...]  # per row: carries the grid-row-0 signature
    wiredown: dict[int, tuple[int, ...]]
    end: int  # first byte after the wire-down table


# ---------------------------------------------------------------------------
# SCR header parsing
# ---------------------------------------------------------------------------


def _read_utf16le(data: bytes, offset: int, byte_count: int) -> str:
    """Read a length-prefixed UTF-16LE string."""
    raw = data[offset : offset + byte_count]
    if len(raw) % 2 == 1:
        raw = raw + b"\x00"
    return raw.decode("utf-16-le").rstrip("\x00")


def _skip_condition_column_family_table(data: bytes, cursor: int) -> int:
    """Skip the fixed-width per-condition-column family table.

    SCR stores ``cols_per_row`` first, then one UTF-16LE family code for each
    condition column (A..AE). The AF/output column is not included, so a Click
    program with 32 visible columns still serializes 31 family entries here.
    """
    if cursor + 2 > len(data):
        return cursor

    cols_per_row = struct.unpack_from("<H", data, cursor)[0]
    cursor += 2

    if 1 <= cols_per_row <= _CONDITION_COLUMNS + 1:
        family_table_bytes = (cols_per_row - 1) * 2
        if cursor + family_table_bytes <= len(data):
            return cursor + family_table_bytes

    # Fallback for malformed headers: consume a contiguous UTF-16LE ASCII table
    # without assuming any specific family code such as "A".
    while cursor + 1 < len(data) and data[cursor + 1] == 0 and 0x20 <= data[cursor] <= 0x7E:
        cursor += 2

    return cursor


def _skip_initial_rtf_prelude(data: bytes, cursor: int) -> int:
    """Skip the variable marker/length prelude that precedes the first RTF block.

    The 7-byte prelude layout:
      +0x00  (2B) — marker (observed: varies per file)
      +0x02  (1B) — unidentified (always 0x0D in observations)
      +0x03  (4B) — unknown uint32
      +0x07  (4B) — RTF body length (uint32 LE)
    We skip past the first 7 bytes so data_start points at the RTF length field.
    """
    if cursor + 11 > len(data) or data[cursor + 2] != 0x0D:
        return cursor

    rtf_len = struct.unpack_from("<I", data, cursor + 7)[0]
    rtf_start = cursor + 11
    if 0 < rtf_len <= len(data) - rtf_start and data[rtf_start : rtf_start + 6] == b"{\\rtf1":
        return cursor + 7

    return cursor


def _parse_header(data: bytes) -> tuple[str, int, int]:
    """Parse SC-SCR file header.

    Returns (program_name, prog_idx, data_start).
    """
    if len(data) < 0x50 or data[:8] != _SCR_MAGIC:
        raise ValueError(f"Not an SC-SCR file (magic: {data[:8]!r})")

    prog_idx = struct.unpack_from("<H", data, 0x40)[0]
    name_len = data[0x42]
    name = _read_utf16le(data, 0x43, name_len)
    cursor = 0x43 + name_len

    cursor = _skip_condition_column_family_table(data, cursor)
    cursor = _skip_initial_rtf_prelude(data, cursor)

    return name, prog_idx, cursor


# ---------------------------------------------------------------------------
# Instruction blob parsing
# ---------------------------------------------------------------------------


def _parse_blob(data: bytes, pos: int, data_len: int = 0) -> tuple[str, int, int, int] | None:
    """Parse SCR instruction blob at pos.

    Returns (class_name, type_code, end_offset, visual_sub_rows) or None.
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

        # Embedded cell-header fields (matches clipboard cell offsets +0x09..+0x10):
        #   after_type+0  (1B) — row_span (unused here)
        #   after_type+1  (1B) — ??? (always 0x00 in observations)
        #   after_type+2  (2B) — structural bytes
        #   after_type+4  (2B) — instruction_index (unused here)
        #   after_type+6  (1B) — visual_sub_rows (0x01 single-row, 0x02+ multi-row)
        # Followed by visual_sub_rows sequential counting bytes, then end_offset.
        after_type = type_off + 2
        if after_type + 12 > data_len:
            return None
        visual_sub_rows = data[after_type + 6]
        if not (1 <= visual_sub_rows <= 8):
            return None
        eo_pos = after_type + 7 + visual_sub_rows
        if eo_pos + 4 > data_len:
            return None
        # end_offset is the explicit blob boundary pointer — the same boundary
        # that clipboard's find_blob_boundary() derives by scanning tag fields.
        end_offset = struct.unpack_from("<I", data, eo_pos)[0]
        if not (pos < end_offset < data_len):
            return None
        return text, marker, end_offset, visual_sub_rows
    except (UnicodeDecodeError, ValueError, struct.error):
        return None


# ---------------------------------------------------------------------------
# SCR blob → parsed instruction
# ---------------------------------------------------------------------------


def _parse_scr_tags(
    data: bytes,
    blob_start: int,
    end_offset: int,
    visual_sub_rows: int,
) -> tuple[str, int, dict[int, str], dict[int, int], _ScrVariantU16Tags, _ScrVariantStringTags]:
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
        6 + 1 + visual_sub_rows + 4
    )  # skip cell-header + visual_sub_rows counting bytes + end_offset

    tags: dict[int, str] = {}
    tag_byte_lens: dict[int, int] = {}
    variant_u16_tags: _ScrVariantU16Tags = {}
    variant_string_tags: _ScrVariantStringTags = {}
    while pos < end_offset:
        if pos + 2 > len(data):
            break
        tag = struct.unpack_from("<H", data, pos)[0]
        pos += 2

        if tag == 0x0000:
            tags[tag] = ""
            tag_byte_lens[tag] = 0
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
            tag_byte_lens[tag] = 0
            continue

        if wire == "u16":
            if pos + 2 > len(data):
                break
            value = struct.unpack_from("<H", data, pos)[0]
            tags[tag] = str(value)
            tag_byte_lens[tag] = 2
            pos += 2
            continue

        if wire == "byte":
            if pos + 1 > len(data):
                break
            value = data[pos]
            tags[tag] = str(value)
            # Preserve the old contract: short-value tags expose their raw byte
            # through ``tag_byte_lens`` for downstream decoders.
            tag_byte_lens[tag] = value
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
        tag_byte_lens[tag] = str_len
        pos += str_len
    return class_name, type_code, tags, tag_byte_lens, variant_u16_tags, variant_string_tags


def _infer_af_visual_rows(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    visual_sub_rows: int,
    tag_byte_lens: dict[int, int],
    variant_u16_tags: _ScrVariantU16Tags,
    variant_string_tags: _ScrVariantStringTags,
) -> int:
    """Infer visual row count using parsed instruction metadata when possible."""
    parsed_af = from_tags_af(
        class_name,
        type_code,
        tags,
        tag_byte_lens,
        variant_u16_tags,
        variant_string_tags,
    )
    if parsed_af is not None:
        return max(1, int(parsed_af.cell_params().get("visual_rows", 1)))

    family_spec = INSTRUCTION_MODULES.get(class_name)
    min_rows = int(getattr(family_spec, "min_csv_rows", 1))
    return max(1, min_rows, visual_sub_rows)


# ---------------------------------------------------------------------------
# Row topology parsing
# ---------------------------------------------------------------------------


def _parse_row_block(data: bytes, pos: int, data_len: int) -> tuple[set[int], bool, int] | None:
    """Parse one uniform row block: ``[flag][count][00]`` + count x ``[seg][col]``.

    Returns ``(right_wired_cols, row0_like, next_pos)`` or ``None`` on any
    structural mismatch.  Entries are placement-ordered — columns are
    collected as a set.

    ``row0_like`` is the grid-row-0 signature: the row reaches the power rail
    (col 0 present) and every condition cell carries segment flag 1 (grid row
    0 is exempt from the per-row segment boundary, so only a true row 0 looks
    like this — continuation rows connected to the rail get seg=0 left of the
    boundary).
    """
    if pos + 3 > data_len:
        return None
    flag = data[pos]
    count = data[pos + 1]
    if flag not in (0, 1) or data[pos + 2] != 0 or count > _CONDITION_COLUMNS + 1:
        return None
    entries_end = pos + 3 + count * 2
    if entries_end > data_len:
        return None

    cols: set[int] = set()
    all_condition_segs_set = True
    for off in range(pos + 3, entries_end, 2):
        seg = data[off]
        col = data[off + 1]
        if seg not in (0, 1) or col > _CONDITION_COLUMNS or col in cols:
            return None
        if col < _CONDITION_COLUMNS and seg == 0:
            all_condition_segs_set = False
        cols.add(col)
    row0_like = 0 in cols and all_condition_segs_set
    return cols, row0_like, entries_end


def _parse_wiredown_table(
    data: bytes, pos: int, data_len: int
) -> tuple[dict[int, tuple[int, ...]], int] | None:
    """Parse the 32-column wire-down table that follows the ``20 00`` marker.

    Exactly one entry per column 0..31: ``00 00`` (no down wires) or
    ``[count][00][count x 1-based row index]``.  Returns
    ``({col: row_indices}, end)`` or ``None`` on structural mismatch.
    """
    result: dict[int, tuple[int, ...]] = {}
    for col in range(_CONDITION_COLUMNS + 1):
        if pos + 2 > data_len:
            return None
        count = data[pos]
        if data[pos + 1] != 0:
            return None
        pos += 2
        if count:
            if pos + count > data_len:
                return None
            rows = tuple(sorted({b - 1 for b in data[pos : pos + count] if b > 0}))
            if rows:
                result[col] = rows
            pos += count
    return result, pos


def _parse_row_topology_block(
    data: bytes, pos: int, data_len: int = 0
) -> _ScrRowTopologyBlock | None:
    """Parse a full row-topology block (header, row blocks, marker, wiredown)."""
    if not data_len:
        data_len = len(data)
    if pos < 0 or pos + 7 > data_len:
        return None

    row_word = struct.unpack_from("<H", data, pos)[0]
    if not 2 <= row_word <= 33:
        return None

    if data[pos + 2 : pos + 5] != _ROW_TOPOLOGY_PREFIX:
        return None

    cursor = pos + 5
    rows: list[frozenset[int]] = []
    row0_like: list[bool] = []
    for _ in range(row_word - 1):
        parsed = _parse_row_block(data, cursor, data_len)
        if parsed is None:
            return None
        cols, is_row0_like, cursor = parsed
        rows.append(frozenset(cols))
        row0_like.append(is_row0_like)

    if data[cursor : cursor + 2] != _ROW_TOPOLOGY_END_MARKER:
        return None

    parsed_wd = _parse_wiredown_table(data, cursor + 2, data_len)
    if parsed_wd is None:
        return None
    wiredown, end = parsed_wd

    return _ScrRowTopologyBlock(
        start=pos,
        row_word=row_word,
        rows_right_cols=tuple(rows),
        rows_row0_like=tuple(row0_like),
        wiredown=wiredown,
        end=end,
    )


# ---------------------------------------------------------------------------
# Linear rung-record walk
# ---------------------------------------------------------------------------
#
# Per-rung grammar (single forward cursor, no scanning):
#
#   RUNG = [u16 rung_index (1-based ordinal; rung 0 has the file prelude
#           [u16 file_marker][0d][u32 total_rung_records] instead)]
#          [u32 rtf_len][rtf body]
#          TOPOLOGY                        (see _parse_row_topology_block)
#          [u16 instr_count]               (0 = empty rung, else section follows)
#          [u32 section_marker] + entries  (only when instr_count > 0)
#
# Entry advance is trailer-aware: the byte at each blob's end_offset is a
# trailer length (0 or 1), so the next entry starts at
# ``end_offset + 2 + data[end_offset]``.
# Files whose prog_idx == 1 (the main program) end with a 2-byte tail after
# the last rung record; subroutines end exactly at the last record.


@dataclass(frozen=True)
class _ScrRungRecord:
    """One rung record from the linear walk."""

    comment: str | None
    comment_rtf: bytes | None
    topology: _ScrRowTopologyBlock | None  # None only for skipped trailing debris
    instructions: list[_ScrSectionInstruction]


def _locate_rung0_rtf_field(data: bytes, data_start: int) -> tuple[int, int | None]:
    """Locate rung 0's ``[u32 rtf_len]`` field and the total rung-record count.

    ``_parse_header`` leaves ``data_start`` either at the 7-byte rung-0 file
    prelude ``[u16 file_marker][0d][u32 total_rung_records]`` (when rung 0 has
    no comment) or just past it (comment present).  Returns
    ``(rtf_len_pos, total_rung_records | None)``.
    """
    if data_start + 7 <= len(data) and data[data_start + 2] == 0x0D:
        return data_start + 7, struct.unpack_from("<I", data, data_start + 3)[0]
    if data_start >= 7 and data[data_start - 5] == 0x0D:
        return data_start, struct.unpack_from("<I", data, data_start - 4)[0]
    return data_start, None


def _parse_section_entries(
    data: bytes, pos: int, count: int, data_len: int
) -> tuple[list[_ScrSectionInstruction], int] | None:
    """Parse ``count`` instruction entries; returns (instructions, end_pos).

    Each entry is a fixed 8-byte header followed by a blob whose explicit
    ``end_offset`` plus the 1-byte trailer length at that offset determine the
    next entry position.
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
        _cls, _marker, end_off, vsub = blob
        cn, tc, tags, tbl, v_u16, v_str = _parse_scr_tags(data, cursor + 8, end_off, vsub)
        results.append((row_1based - 1, col_idx, cn, tc, tags, vsub, tbl, v_u16, v_str))

        trailer_len = data[end_off]
        if trailer_len > 8:
            return None
        cursor = end_off + 2 + trailer_len
    return results, cursor


def _resync_trailing_rung(data: bytes, pos: int, next_index: int, limit: int) -> int | None:
    """Bounded resync past trailing editor debris.

    Native captures can contain one malformed topology-like block among the
    trailing placeholder rungs (observed once: a ``03 20 00`` marker instead
    of ``03 00 00``).  Search forward for the next rung prefix
    ``[u16 next_index][u32 rtf_len=0]`` followed by a valid topology block.
    """
    needle = struct.pack("<H", next_index) + b"\x00\x00\x00\x00"
    search = pos
    while True:
        found = data.find(needle, search, limit)
        if found < 0:
            return None
        if _parse_row_topology_block(data, found + 6, len(data)) is not None:
            return found
        search = found + 1


def _walk_rung_records(data: bytes, prog_idx: int, data_start: int) -> list[_ScrRungRecord]:
    """Walk all rung records with a single forward cursor."""
    data_len = len(data)
    pos, total_rungs = _locate_rung0_rtf_field(data, data_start)
    limit = data_len - (2 if prog_idx == 1 else 0)

    records: list[_ScrRungRecord] = []
    index = 0
    while pos < limit:
        if index > 0:
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

        block = _parse_row_topology_block(data, pos, data_len)
        if block is None:
            resync = _resync_trailing_rung(data, pos, index + 1, limit)
            if resync is None:
                raise ValueError(f"unparseable rung topology at 0x{pos:X} (rung {index})")
            records.append(_ScrRungRecord(comment, rtf_bytes, None, []))
            pos = resync
            index += 1
            continue
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
            parsed = _parse_section_entries(data, pos, count, data_len)
            if parsed is None:
                raise ValueError(f"unparseable section entries at 0x{pos:X} (rung {index})")
            instructions, pos = parsed

        records.append(_ScrRungRecord(comment, rtf_bytes, block, instructions))
        index += 1

    if pos != limit:
        raise ValueError(f"rung walk ended at 0x{pos:X}, expected 0x{limit:X}")
    if total_rungs is not None and len(records) != total_rungs:
        raise ValueError(
            f"rung record count mismatch: walked {len(records)}, header says {total_rungs}"
        )
    return records


def _is_trailing_placeholder(record: _ScrRungRecord) -> bool:
    """Trailing content-less rung: no instructions and no comment.

    Click programs keep 1..4 ordinary empty rungs in the editor below the
    last programmed rung (some carry a fully-wired row).  They are real rung
    records, but content-less — only instructions or a comment make a
    trailing record worth emitting.
    """
    return not record.instructions and record.comment is None


def _build_topology_backed_rung(
    topology_block: _ScrRowTopologyBlock,
    logical_rows: int,
    section_instructions: list[_ScrSectionInstruction],
    comment: str | None,
    comment_rtf: bytes | None,
) -> Rung:
    """Build the Rung object for a rung with a parsed row-topology block.

    Row block *i* maps directly to grid row *i* — no reshuffling.  count_down
    counters and drums need no special handling: their AF-row block simply
    carries flag=0 and the bridge/pin row is a normal stored row.

    One exception: SCR can retain orphaned wire rows *above* the true grid
    row 0 (editor debris under a tall instruction box, observed in native
    drum captures).  The true row 0 is identified by its grid-row-0 segment
    signature (see ``_parse_row_block``); non-empty stored rows preceding it
    are dropped, and wire-down row indices shift accordingly.  Click's own
    clipboard copy of such rungs omits these rows.
    """
    rows = topology_block.rows_right_cols
    wiredown = topology_block.wiredown

    junk_rows = 0
    for idx, is_row0_like in enumerate(topology_block.rows_row0_like):
        if is_row0_like:
            junk_rows = idx
            break
    if junk_rows and all(rows[i] for i in range(junk_rows)):
        rows = rows[junk_rows:]
        wiredown = {
            col: shifted
            for col, row_indices in wiredown.items()
            if (shifted := tuple(r - junk_rows for r in row_indices if r >= junk_rows))
        }

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
        visual_sub_rows,
        tag_byte_lens,
        variant_u16_tags,
        variant_string_tags,
    ) in section_instructions:
        if row < 0 or row >= logical_rows:
            continue
        if col < _CONDITION_COLUMNS:
            parsed = from_tags_condition(
                class_name,
                type_code,
                tags,
                tag_byte_lens,
                variant_u16_tags,
                variant_string_tags,
            )
            if parsed is not None:
                conditions[row][col] = parsed
            else:
                conditions[row][col] = UnknownCondition(raw=class_name.encode())
            instr_positions.add((row, col))
        elif col == _CONDITION_COLUMNS:
            parsed_af = from_tags_af(
                class_name,
                type_code,
                tags,
                tag_byte_lens,
                variant_u16_tags,
                variant_string_tags,
            )
            if parsed_af is not None:
                instructions[row] = parsed_af
            else:
                # Build a minimal RawInstruction from SCR tag data
                from .instructions.raw import _compose_blob

                blob = _compose_blob(
                    class_name,
                    type_code,
                    visual_sub_rows,
                    bytes(range(max(0, visual_sub_rows - 1))),
                    [(t, _STANDARD_SENTINEL, v) for t, v in tags.items()],
                )
                instructions[row] = RawInstruction(
                    class_name=class_name,
                    blob=blob,
                    part_count=visual_sub_rows,
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
        If the file cannot be parsed.
    """
    name, prog_idx, data_start = _parse_header(data)
    records = _walk_rung_records(data, prog_idx, data_start)

    # Drop trailing content-less rungs — the ordinary empty rungs Click keeps
    # below the last programmed rung (a rung-scoped clipboard copy excludes
    # them too).
    while records and _is_trailing_placeholder(records[-1]):
        records.pop()

    rungs: list[Rung] = []
    for record in records:
        if record.topology is None:
            continue  # skipped trailing debris that wasn't last

        inferred_rows = 1
        for (
            row,
            col,
            class_name,
            type_code,
            tags,
            _visual_sub_rows,
            tag_byte_lens,
            variant_u16_tags,
            variant_string_tags,
        ) in record.instructions:
            inferred_rows = max(inferred_rows, row + 1)
            if col == _CONDITION_COLUMNS:
                visual_rows = _infer_af_visual_rows(
                    class_name,
                    type_code,
                    tags,
                    _visual_sub_rows,
                    tag_byte_lens,
                    variant_u16_tags,
                    variant_string_tags,
                )
                inferred_rows = max(inferred_rows, row + visual_rows)

        rungs.append(
            _build_topology_backed_rung(
                topology_block=record.topology,
                logical_rows=max(1, record.topology.row_word - 1, inferred_rows),
                section_instructions=record.instructions,
                comment=record.comment,
                comment_rtf=record.comment_rtf,
            )
        )

    return Program(name=name, prog_idx=prog_idx, rungs=rungs)
