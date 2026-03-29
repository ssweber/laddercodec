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
from dataclasses import dataclass, field
from typing import Literal, cast

from .decode import Rung, _decode_rtf
from .instructions import INSTRUCTION_MODULES, RawInstruction
from .instructions.call import Call
from .instructions.coil import Coil
from .instructions.comparison import CompareContact
from .instructions.contact import Contact
from .instructions.copy import BlockCopy, Copy, Fill, Pack, Unpack
from .instructions.counter import Counter
from .instructions.drum import Drum
from .instructions.end import End
from .instructions.forloop import ForLoop, Next
from .instructions.math import Math, _reconstruct_expression
from .instructions.return_ import Return
from .instructions.search import Search
from .instructions.send_receive import (
    _COM_PORT_MODE_INV,
    ModbusAddress,
    ModbusRtuTarget,
    ModbusTcpTarget,
    Receive,
    Send,
)
from .instructions.shift import Shift
from .instructions.timer import TIMER_UNITS, Timer
from .model import InstructionType, Program

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCR_MAGIC = b"SC-SCR  "
_ROW_TOPOLOGY_PREFIX = b"\x03\x00\x00"
_ROW_TOPOLOGY_FLAG_ENTRY_COUNTS = frozenset({31, 32})
_ROW_TOPOLOGY_PRELUDE_LEN_RANGE = range(8, 17)
_CONDITION_COLUMNS = 31  # A..AE = cols 0..30; AF = col 31
_RAW_STANDARD_SENTINEL = b"\xff\xff\xff\xff"
_MAX_SECTION_INSTRUCTIONS = 512


@dataclass(frozen=True)
class _ScrTagParseSpec:
    """Legacy SCR tag parsing rules — retained for test imports only.

    Wire-type dispatch now uses ``_tag_wire_type``.  Only ``stop_tags``
    (semantic overrides that halt parsing) remain in use at runtime via
    ``_SCR_STOP_TAGS``.
    """

    byte_value_tags: frozenset[int] = field(default_factory=frozenset)
    u16_value_tags: frozenset[int] = field(default_factory=frozenset)
    flag_tags: frozenset[int] = field(default_factory=frozenset)
    variant_u16_tags: frozenset[int] = field(default_factory=frozenset)
    variant_string_tags: frozenset[int] = field(default_factory=frozenset)
    stop_tags: frozenset[int] = field(default_factory=frozenset)


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
    """Structural row-topology record that precedes a rung's instruction section."""

    start: int
    row_word: int
    prelude: bytes
    leading_rows_right_wires: list[set[int]]
    row0_flag_count: int
    row0_flags: dict[int, int]
    flags_start: int
    continuation_start: int


def _tag_wire_type(tag: int) -> str:
    """Infer the wire type of a SCR tag from its high byte.

    Returns one of: "flag", "byte", "u16", "string", "variant_u16",
    "variant_string", or "unknown".
    """
    hi = (tag >> 8) & 0xFF
    if hi in (0x11, 0x12):
        return "flag"
    if hi in (0x20, 0x21, 0x22):
        return "byte"
    if hi == 0x32:
        return "u16"
    if hi == 0x3A:
        return "variant_u16"
    if hi in (0x60, 0x61, 0x62):
        return "string"
    if hi == 0x68:
        return "variant_string"
    return "unknown"


_SCR_TAG_PARSE_SPECS: dict[str, _ScrTagParseSpec] = {
    "Call": _ScrTagParseSpec(u16_value_tags=frozenset({0x3219})),
    "Copy": _ScrTagParseSpec(
        byte_value_tags=frozenset({0x2206, 0x2223, 0x2227}),
        u16_value_tags=frozenset({0x3216}),
        flag_tags=frozenset({0x11F8, 0x1201, 0x1221}),
    ),
    "Math": _ScrTagParseSpec(
        byte_value_tags=frozenset({0x2224}),
        flag_tags=frozenset({0x11F8, 0x11FE}),
        stop_tags=frozenset({0x6888, 0x688C}),
    ),
    "Tmr": _ScrTagParseSpec(
        byte_value_tags=frozenset({0x21F9, 0x21FA, 0x21FB}),
        variant_u16_tags=frozenset({0x3A05}),
    ),
    "Drum": _ScrTagParseSpec(
        byte_value_tags=frozenset({0x2200, 0x21F9}),
        u16_value_tags=frozenset({0x3203, 0x3204}),
        flag_tags=frozenset({0x1201, 0x1202}),
        variant_u16_tags=frozenset({0x3A05, 0x3A26}),
        variant_string_tags=frozenset({0x6872, 0x6873}),
    ),
    "Email": _ScrTagParseSpec(
        byte_value_tags=frozenset({0x20CA, 0x2206, 0x2237, 0x2238, 0x2239}),
        u16_value_tags=frozenset({0x3218}),
    ),
    "Home": _ScrTagParseSpec(
        byte_value_tags=frozenset({0x222D, 0x222E, 0x222F, 0x2230, 0x2232, 0x2233}),
        u16_value_tags=frozenset({0x3218}),
        flag_tags=frozenset({0x11F5}),
    ),
    "RD": _ScrTagParseSpec(
        byte_value_tags=frozenset(
            {
                0x220C,
                0x220D,
                0x2211,
                0x2212,
                0x2213,
                0x2214,
                0x2215,
                0x221C,
                0x221D,
                0x2225,
                0x223A,
            }
        ),
        u16_value_tags=frozenset({0x320E, 0x320F, 0x3210, 0x3216, 0x3218, 0x322C}),
        flag_tags=frozenset({0x1209, 0x120A, 0x120B, 0x121A, 0x121B, 0x121E, 0x121F, 0x1220}),
    ),
    "Position": _ScrTagParseSpec(
        byte_value_tags=frozenset({0x2206, 0x222D, 0x222F, 0x2231}),
        u16_value_tags=frozenset({0x3218}),
        flag_tags=frozenset({0x11F5}),
    ),
    "SD": _ScrTagParseSpec(
        byte_value_tags=frozenset({0x220C, 0x220D, 0x2211, 0x2214, 0x2215, 0x221C, 0x2225, 0x223A}),
        u16_value_tags=frozenset({0x320E, 0x320F, 0x3210, 0x3216, 0x3218, 0x322C}),
        flag_tags=frozenset({0x1209, 0x120A, 0x120B, 0x121A, 0x1220, 0x1221}),
    ),
    "Velocity": _ScrTagParseSpec(
        byte_value_tags=frozenset({0x222D, 0x222F, 0x2231}),
        u16_value_tags=frozenset({0x3218}),
        flag_tags=frozenset({0x11F5}),
    ),
}

# Runtime dispatch only needs stop_tags — wire type is inferred by _tag_wire_type.
_SCR_STOP_TAGS: dict[str, frozenset[int]] = {
    name: spec.stop_tags for name, spec in _SCR_TAG_PARSE_SPECS.items() if spec.stop_tags
}


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


def _parse_blob(data: bytes, pos: int) -> tuple[str, int, int, int, int] | None:
    """Parse SCR instruction blob at pos.

    Returns (class_name, type_code, end_offset, next_pos, visual_sub_rows) or None.
    """
    if pos >= len(data) - 20:
        return None
    sl = data[pos]
    if not (3 <= sl <= 60 and pos + 1 + sl + 2 <= len(data)):
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
        if after_type + 12 > len(data):
            return None
        visual_sub_rows = data[after_type + 6]
        if not (1 <= visual_sub_rows <= 8):
            return None
        eo_pos = after_type + 7 + visual_sub_rows
        if eo_pos + 4 > len(data):
            return None
        # end_offset is the explicit blob boundary pointer — the same boundary
        # that clipboard's find_blob_boundary() derives by scanning tag fields.
        end_offset = struct.unpack_from("<I", data, eo_pos)[0]
        if not (pos < end_offset < len(data)):
            return None
        next_pos = end_offset + 2
        return text, marker, end_offset, next_pos, visual_sub_rows
    except (UnicodeDecodeError, ValueError, struct.error):
        return None


# ---------------------------------------------------------------------------
# SCR blob → parsed instruction
# ---------------------------------------------------------------------------

# Type marker → InstructionType
_TYPE_CODE_TO_ITYPE: dict[int, InstructionType] = {
    0x2711: InstructionType.CONTACT_NO,
    0x2712: InstructionType.CONTACT_NC,
    0x2713: InstructionType.CONTACT_EDGE,
    0x2714: InstructionType.COMPARE,
    0x2715: InstructionType.COIL_OUT,
    0x2716: InstructionType.COIL_LATCH,
    0x2717: InstructionType.COIL_RESET,
    0x2718: InstructionType.TIMER,
}

# Compare type index → operator
_COMPARE_IDX_TO_OP: dict[str, Literal["==", "!=", ">", "<", ">=", "<="]] = {
    "0": "==",
    "1": "!=",
    "2": ">",
    "3": "<",
    "4": ">=",
    "5": "<=",
}


def _parse_scr_tags(
    data: bytes,
    blob_start: int,
    end_offset: int,
    visual_sub_rows: int,
    stop_tags: frozenset[int] = frozenset(),
) -> tuple[str, int, dict[int, str], dict[int, int], _ScrVariantU16Tags, _ScrVariantStringTags]:
    """Parse SCR blob into scalar tags plus compact variant-tag collections.

    Wire type is inferred from each tag's high byte via ``_tag_wire_type``.
    ``stop_tags`` is a semantic override that halts parsing (used by Math).
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

        if tag in stop_tags:
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


def _scr_to_condition(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    tag_byte_lens: dict[int, int] | None = None,
    variant_u16_tags: _ScrVariantU16Tags | None = None,
    variant_string_tags: _ScrVariantStringTags | None = None,
) -> Contact | CompareContact | None:
    """Construct a condition instruction from SCR tag data."""
    itype = _TYPE_CODE_TO_ITYPE.get(type_code)

    if class_name == "ContactNO" and itype in (
        InstructionType.CONTACT_NO,
        InstructionType.CONTACT_NC,
    ):
        operand = tags.get(0x6065, "")
        if not operand:
            return None
        immediate = 0x11F5 in tags
        return Contact(type=itype, operand=operand, immediate=immediate)

    if class_name == "Edge" and itype == InstructionType.CONTACT_EDGE:
        operand = tags.get(0x6065, "")
        if not operand:
            return None
        edge_kind = "fall" if 0x21F6 in tags else "rise"
        return Contact(
            type=InstructionType.CONTACT_EDGE,
            operand=operand,
            edge_kind=edge_kind,
        )

    if class_name == "Compare" and itype == InstructionType.COMPARE:
        left = tags.get(0x6066, "")
        right = tags.get(0x6067, "")
        # SCR encodes compare type as byte length of tag 0x21F7 (absent=0)
        lens = tag_byte_lens or {}
        type_idx = str(lens.get(0x21F7, 0))
        op = _COMPARE_IDX_TO_OP.get(type_idx)
        if not left or not right or op is None:
            return None
        return CompareContact(op=op, left=left, right=right)

    return None


def _scr_to_af(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    tag_byte_lens: dict[int, int] | None = None,
    variant_u16_tags: _ScrVariantU16Tags | None = None,
    variant_string_tags: _ScrVariantStringTags | None = None,
) -> (
    Coil
    | Timer
    | Counter
    | Copy
    | BlockCopy
    | Fill
    | Pack
    | Unpack
    | Math
    | Search
    | Shift
    | Drum
    | Receive
    | Send
    | Call
    | ForLoop
    | Next
    | End
    | Return
    | None
):
    """Construct an AF instruction from SCR tag data."""
    itype = _TYPE_CODE_TO_ITYPE.get(type_code)
    lens = tag_byte_lens or {}
    variant_u16 = variant_u16_tags or {}
    variant_strings = variant_string_tags or {}

    if class_name in ("Out", "Latch", "Reset") and itype in (
        InstructionType.COIL_OUT,
        InstructionType.COIL_LATCH,
        InstructionType.COIL_RESET,
    ):
        operand = tags.get(0x6066, "")
        if not operand:
            return None
        range_end_val = tags.get(0x6067, "")
        return Coil(
            type=itype,
            operand=operand,
            range_end=range_end_val or None,
            immediate=0x11F5 in tags,
            oneshot=0x11F8 in tags,
        )

    if class_name == "Tmr" and itype == InstructionType.TIMER:
        done_bit = tags.get(0x6068, "")
        setpoint = tags.get(0x606A, "")
        current = tags.get(0x6069, "")
        unit_idx = tags.get(0x21F9, "0")  # default: Tms
        unit = TIMER_UNITS.get(unit_idx)
        if not done_bit or not current or not setpoint or unit is None:
            return None
        timer_type = "off_delay" if 0x21FA in tags else "on_delay"
        return Timer(
            timer_type=timer_type,
            done_bit=done_bit,
            current=current,
            setpoint=setpoint,
            unit=unit,
            retained=0x21FB in tags,
        )

    if class_name == "Cnt" and type_code == 0x2719:
        done_bit = tags.get(0x606B, "")
        preset = tags.get(0x606A, "")
        current = tags.get(0x606C, "")
        mode = lens.get(0x21FC, 0)
        variant = cast(
            tuple[Literal["count_up", "count_down"], bool, bool] | None,
            {
                0: ("count_up", False, True),
                1: ("count_down", False, True),
                2: ("count_up", True, True),
            }.get(mode),
        )
        if not all([done_bit, preset, current]) or variant is None:
            return None
        counter_type, down_enabled, reset_enabled = variant
        return Counter(
            counter_type=counter_type,
            done_bit=done_bit,
            current=current,
            preset=preset,
            down_enabled=down_enabled,
            reset_enabled=reset_enabled,
        )

    if class_name == "Copy" and type_code == 0x2721:
        source = tags.get(0x6074, "")
        source_end = tags.get(0x6075, "")
        destination = tags.get(0x6076, "")
        destination_end = tags.get(0x6077, "")
        oneshot = 0x11F8 in tags
        copy_type = int(tags.get(0x2223, "0") or "0")
        conv_type = int(tags.get(0x2227, "0") or "0")

        if 0x2223 not in tags:
            if source_end and destination_end:
                copy_type = 1
            elif destination_end:
                copy_type = 2
            else:
                copy_type = 0

        if copy_type == 0:
            if not source or not destination:
                return None
            fmt = "none"
            suppress_zero = "0"
            exponential = "0"
            if conv_type == 0:
                pass
            elif conv_type == 1:
                fmt = "text"
                suppress_zero = "1"
            elif conv_type == 2:
                fmt = "text"
                suppress_zero = "0"
            elif conv_type == 4:
                fmt = "text"
                suppress_zero = "1"
                exponential = "1"
            elif conv_type == 5:
                fmt = "value"
            elif conv_type == 6:
                fmt = "ascii"
            elif conv_type == 8:
                fmt = "binary"
            else:
                return None

            termination_code = "0"
            term_char = tags.get(0x3216, "")
            if (0x1221 in tags or 0x1201 in tags) and term_char:
                termination_code = f"${int(term_char):X}"

            return Copy(
                source=source,
                destination=destination,
                format=fmt,
                oneshot=oneshot,
                suppress_zero=suppress_zero,
                exponential=exponential,
                termination_code=termination_code,
            )

        if copy_type == 1:
            if not all([source, source_end, destination, destination_end]):
                return None
            fmt = {0: "none", 5: "value", 6: "ascii"}.get(conv_type)
            if fmt is None:
                return None
            return BlockCopy(
                source_start=source,
                source_end=source_end,
                dest_start=destination,
                dest_end=destination_end,
                format=fmt,
                oneshot=oneshot,
            )

        if copy_type == 2:
            if not all([source, destination, destination_end]):
                return None
            return Fill(
                value=source,
                dest_start=destination,
                dest_end=destination_end,
                oneshot=oneshot,
            )

        if copy_type == 3:
            if not all([source, source_end, destination]):
                return None
            if conv_type == 9:
                pack_type = "text"
                allow_whitespace = False
            elif conv_type == 10:
                pack_type = "text"
                allow_whitespace = True
            elif conv_type == 0:
                pack_type = "bits" if source.startswith("C") else "words"
                allow_whitespace = False
            else:
                return None
            return Pack(
                source_start=source,
                source_end=source_end,
                destination=destination,
                pack_type=pack_type,
                allow_whitespace=allow_whitespace,
                oneshot=oneshot,
            )

        if copy_type == 4:
            if not all([source, destination, destination_end]):
                return None
            unpack_type = "bits" if destination.startswith("C") else "words"
            return Unpack(
                source=source,
                dest_start=destination,
                dest_end=destination_end,
                unpack_type=unpack_type,
                oneshot=oneshot,
            )

    if class_name == "SR" and type_code == 0x2720:
        start_bit = tags.get(0x6066, "")
        end_bit = tags.get(0x6067, "")
        if not start_bit or not end_bit:
            return None
        return Shift(start_bit=start_bit, end_bit=end_bit)

    if class_name == "Search" and type_code == 0x2722:
        source = tags.get(0x6065, "")
        table_start = tags.get(0x6066, "")
        table_end = tags.get(0x6067, "")
        result = tags.get(0x6079, "")
        found = tags.get(0x607A, "")
        cmp_idx = str(lens.get(0x21F7, 0))
        comparison = _COMPARE_IDX_TO_OP.get(cmp_idx)
        if source.startswith('"') and source.endswith('"'):
            source = source[1:-1]
        if not all([source, table_start, table_end, result, found]) or comparison is None:
            return None
        return Search(
            table_start=table_start,
            table_end=table_end,
            source=source,
            result=result,
            found=found,
            comparison=comparison,
            continuous=0x1277 in tags,
            oneshot=0x11F8 in tags,
        )

    if class_name == "Math" and type_code == 0x271A:
        result = tags.get(0x6065, "")
        expression = _reconstruct_expression(
            tags.get(0x61FF, ""),
            tags.get(0x61FD, ""),
        ) or tags.get(0x6228, "")
        if not result or not expression:
            return None
        return Math(
            expression=expression,
            result=result,
            mode="hex" if 0x11FE in tags else "decimal",
            oneshot=0x11F8 in tags,
        )

    if class_name == "Drum" and type_code == 0x271B:
        num_steps = int(tags.get(0x3203, "0") or "0")
        num_outputs = int(tags.get(0x3204, "0") or "0")
        current_step = tags.get(0x606E, "")
        completion_flag = tags.get(0x6070, "")
        if num_steps <= 0 or num_outputs <= 0 or not current_step or not completion_flag:
            return None

        outputs_by_idx = variant_strings.get(0x6873, {})
        events_by_idx = variant_strings.get(0x6872, {})
        bitmasks_by_idx = variant_u16.get(0x3A26, {})

        outputs = [outputs_by_idx.get(i, "") for i in range(num_outputs)]
        events_or_presets = [events_by_idx.get(i, "") for i in range(num_steps)]
        if any(not value for value in outputs) or any(not value for value in events_or_presets):
            return None

        pattern = [
            [
                (bitmasks_by_idx.get(step_idx, 0) >> output_idx) & 1
                for output_idx in range(num_outputs)
            ]
            for step_idx in range(num_steps)
        ]

        if tags.get(0x2200, "0") == "1":
            return Drum(
                drum_kind="event",
                outputs=outputs,
                events_or_presets=events_or_presets,
                pattern=pattern,
                current_step=current_step,
                completion_flag=completion_flag,
                jog_enabled=0x1201 in tags,
                jump_enabled=0x1202 in tags,
                jump_target=tags.get(0x6071, ""),
            )

        unit = TIMER_UNITS.get(tags.get(0x21F9, "0"), "Tms")
        accumulator = tags.get(0x606F, "")
        if not accumulator:
            return None
        return Drum(
            drum_kind="time",
            outputs=outputs,
            events_or_presets=events_or_presets,
            pattern=pattern,
            current_step=current_step,
            completion_flag=completion_flag,
            accumulator=accumulator,
            unit=unit,
        )

    if class_name == "RD" and type_code == 0x2728:
        protocol_mode = tags.get(0x220C, "0")
        device_id = int(tags.get(0x320E, tags.get(0x60B2, "1")) or "1")
        if protocol_mode == "2":
            target: ModbusRtuTarget | ModbusTcpTarget = ModbusTcpTarget(
                name="tcp",
                ip=tags.get(0x622B, ""),
                port=int(tags.get(0x322C, "502") or "502"),
                device_id=device_id,
            )
        else:
            target = ModbusRtuTarget(
                name="rtu",
                com_port=_COM_PORT_MODE_INV.get(protocol_mode, "cpu2"),
                device_id=device_id,
            )

        remote_start_raw = tags.get(0x6085, "")
        dest = tags.get(0x607E, "")
        if not remote_start_raw or not dest:
            return None

        address_type = tags.get(0x320F, "0")
        fc_subtype = tags.get(0x2211, "0")
        remote_start: str | ModbusAddress
        if address_type == "2":
            remote_start = remote_start_raw
        elif address_type == "1":
            register_type = {"0": "coil", "1": "discrete_input", "2": "holding", "3": "input"}.get(
                fc_subtype, "holding"
            )
            remote_start = ModbusAddress(address=remote_start_raw, register_type=register_type)
        else:
            remote_start = ModbusAddress(address=remote_start_raw)

        return Receive(
            target=target,
            remote_start=remote_start,
            dest=dest,
            quantity=int(tags.get(0x3210, "1") or "1"),
            receiving=tags.get(0x607C, ""),
            success=tags.get(0x607B, ""),
            error=tags.get(0x607D, ""),
            exception_response=tags.get(0x6083, ""),
            word_swap=tags.get(0x221C, "1") == "0",
        )

    if class_name == "SD" and type_code == 0x2729:
        protocol_mode = tags.get(0x220C, "0")
        device_id = int(tags.get(0x320E, tags.get(0x60B2, "1")) or "1")
        if protocol_mode == "2":
            target = ModbusTcpTarget(
                name="tcp",
                ip=tags.get(0x622B, ""),
                port=int(tags.get(0x322C, "502") or "502"),
                device_id=device_id,
            )
        else:
            target = ModbusRtuTarget(
                name="rtu",
                com_port=_COM_PORT_MODE_INV.get(protocol_mode, "cpu2"),
                device_id=device_id,
            )

        remote_start_raw = tags.get(0x6085, "")
        source = tags.get(0x607E, "")
        if not remote_start_raw or not source:
            return None

        address_type = tags.get(0x320F, "0")
        fc_subtype = tags.get(0x2211, "0")
        remote_start: str | ModbusAddress
        if address_type == "2":
            remote_start = remote_start_raw
        elif address_type == "1":
            register_type = {"0": "coil", "1": "holding", "2": "coil", "3": "holding"}.get(
                fc_subtype, "holding"
            )
            remote_start = ModbusAddress(address=remote_start_raw, register_type=register_type)
        else:
            remote_start = ModbusAddress(address=remote_start_raw)

        return Send(
            target=target,
            remote_start=remote_start,
            source=source,
            quantity=int(tags.get(0x3210, "1") or "1"),
            sending=tags.get(0x607C, "") if 0x120A in tags else "",
            success=tags.get(0x607B, "") if 0x1209 in tags else "",
            error=tags.get(0x607D, "") if 0x120B in tags else "",
            exception_response=tags.get(0x6083, "") if 0x121A in tags else "",
            word_swap=tags.get(0x221C, "1") == "0",
        )

    if class_name == "Call" and type_code == 0x2723:
        subroutine = tags.get(0x6208, "")
        if not subroutine:
            return None
        return Call(subroutine=subroutine)

    if class_name == "For" and type_code == 0x2725:
        limit = tags.get(0x6065, "")
        if not limit:
            return None
        return ForLoop(limit=limit, oneshot=0x11F8 in tags)

    if class_name == "Next" and type_code == 0x2726:
        return Next()

    if class_name == "End" and type_code == 0x2727:
        return End()

    if class_name == "Return" and type_code == 0x2724:
        return Return()

    return None


def _raw_field(tag: int, value: str) -> tuple[int, bytes, str]:
    """Build a standard-sentinel raw field tuple."""
    return tag, _RAW_STANDARD_SENTINEL, value


def _raw_empty_array_fields(tag: int, count: int) -> list[tuple[int, bytes, str]]:
    """Build compact array-style raw fields with sequential variant sentinels."""
    return [(tag, struct.pack("<I", idx), "") for idx in range(count)]


def _scr_to_raw_af(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    visual_sub_rows: int,
) -> RawInstruction | None:
    """Rehydrate sparse SCR AF blobs into clipboard-style RawInstruction blobs."""
    from .instructions.raw import _compose_blob

    fields: list[tuple[int, bytes, str]] | None = None

    if class_name == "Email" and type_code == 0x2737:
        fields = [
            _raw_field(0x60A5, tags.get(0x60A5, "")),
            _raw_field(0x60A6, tags.get(0x60A6, "")),
            _raw_field(0x60A7, tags.get(0x60A7, "")),
            _raw_field(0x2237, tags.get(0x2237) or "0"),
            _raw_field(0x6235, tags.get(0x6235, "")),
            _raw_field(0x6236, tags.get(0x6236, "")),
            _raw_field(0x60AE, tags.get(0x60AE, "")),
            _raw_field(0x60AF, tags.get(0x60AF, "")),
            _raw_field(0x2206, tags.get(0x2206) or "0"),
            _raw_field(0x2238, tags.get(0x2238) or "0"),
            _raw_field(0x6217, tags.get(0x6217, "")),
            _raw_field(0x622A, tags.get(0x622A, "")),
            _raw_field(0x6081, tags.get(0x6081, "")),
            _raw_field(0x6082, tags.get(0x6082, "")),
            _raw_field(0x607C, tags.get(0x607C, "")),
            _raw_field(0x607B, tags.get(0x607B, "")),
            _raw_field(0x607D, tags.get(0x607D, "")),
            _raw_field(0x6083, tags.get(0x6083, "")),
            _raw_field(0x2239, tags.get(0x2239) or "0"),
        ]
        fields.extend(_raw_empty_array_fields(0x68B1, 250))
        fields.extend(_raw_empty_array_fields(0x68B0, 250))
        fields.extend(
            [
                _raw_field(0x20CA, tags.get(0x20CA) or "2"),
                _raw_field(0x3218, tags.get(0x3218) or "9748"),
                _raw_field(0x0000, ""),
            ]
        )

    elif class_name == "Home" and type_code == 0x2734:
        try:
            home_variant = int(tags.get(0x222E, "0") or "0")
        except ValueError:
            home_variant = 0
        fields = [
            _raw_field(0x222D, tags.get(0x222D) or "0"),
            _raw_field(0x222E, tags.get(0x222E) or "0"),
            _raw_field(0x6096, tags.get(0x6096, "")),
            _raw_field(0x6097, tags.get(0x6097, "")),
            _raw_field(0x609E, tags.get(0x609E, "")),
            _raw_field(0x609F, tags.get(0x609F, "")),
            _raw_field(0x60A0, tags.get(0x60A0, "")),
            _raw_field(0x609C, tags.get(0x609C, "")),
            _raw_field(0x609D, tags.get(0x609D, "")),
            _raw_field(0x222F, tags.get(0x222F) or "0"),
            _raw_field(0x11F5, tags.get(0x11F5) or "0"),
            _raw_field(0x2230, tags.get(0x2230) or "0"),
            _raw_field(0x60A1, tags.get(0x60A1, "")),
            _raw_field(0x60A3, tags.get(0x60A3, "")),
            _raw_field(0x60A4, tags.get(0x60A4, "")),
            _raw_field(0x607B, tags.get(0x607B, "")),
            _raw_field(0x607D, tags.get(0x607D, "")),
            _raw_field(0x6083, tags.get(0x6083, "")),
            _raw_field(0x2232, tags.get(0x2232) or "0"),
            _raw_field(0x2233, tags.get(0x2233) or "0"),
            _raw_field(0x3218, tags.get(0x3218) or str(9738 + home_variant)),
            _raw_field(0x0000, ""),
        ]

    elif class_name == "Velocity" and type_code == 0x2735:
        fields = [
            _raw_field(0x222D, tags.get(0x222D) or "0"),
            _raw_field(0x609B, tags.get(0x609B, "")),
            _raw_field(0x609C, tags.get(0x609C, "")),
            _raw_field(0x609D, tags.get(0x609D, "")),
            _raw_field(0x222F, tags.get(0x222F) or "2"),
            _raw_field(0x11F5, tags.get(0x11F5) or "0"),
            _raw_field(0x2231, tags.get(0x2231) or "0"),
            _raw_field(0x60A2, tags.get(0x60A2, "")),
            _raw_field(0x60A3, tags.get(0x60A3, "")),
            _raw_field(0x60A4, tags.get(0x60A4, "")),
            _raw_field(0x607B, tags.get(0x607B, "")),
            _raw_field(0x607D, tags.get(0x607D, "")),
            _raw_field(0x6083, tags.get(0x6083, "")),
            _raw_field(0x3218, tags.get(0x3218) or "9744"),
            _raw_field(0x0000, ""),
        ]

    elif class_name == "Position" and type_code == 0x2736:
        fields = [
            _raw_field(0x222D, tags.get(0x222D) or "0"),
            _raw_field(0x6098, tags.get(0x6098, "")),
            _raw_field(0x6099, tags.get(0x6099, "")),
            _raw_field(0x609A, tags.get(0x609A, "")),
            _raw_field(0x2206, tags.get(0x2206) or "0"),
            _raw_field(0x609B, tags.get(0x609B, "")),
            _raw_field(0x609C, tags.get(0x609C, "")),
            _raw_field(0x609D, tags.get(0x609D, "")),
            _raw_field(0x222F, tags.get(0x222F) or "2"),
            _raw_field(0x11F5, tags.get(0x11F5) or "0"),
            _raw_field(0x2231, tags.get(0x2231) or "0"),
            _raw_field(0x60A2, tags.get(0x60A2, "")),
            _raw_field(0x60A3, tags.get(0x60A3, "")),
            _raw_field(0x60A4, tags.get(0x60A4, "")),
            _raw_field(0x607B, tags.get(0x607B, "")),
            _raw_field(0x607D, tags.get(0x607D, "")),
            _raw_field(0x6083, tags.get(0x6083, "")),
            _raw_field(0x3218, tags.get(0x3218) or "9745"),
            _raw_field(0x0000, ""),
        ]

    if fields is None:
        return None

    blob = _compose_blob(
        class_name,
        type_code,
        visual_sub_rows,
        bytes(range(max(0, visual_sub_rows - 1))),
        fields,
    )
    return RawInstruction(class_name=class_name, blob=blob, part_count=visual_sub_rows)


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
    parsed_af = _scr_to_af(
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
# Instruction section scanning
# ---------------------------------------------------------------------------


def _find_sections(data: bytes, start: int) -> list[tuple[int, int, int]]:
    """Find all valid instruction sections.

    Returns sorted list of (offset, instr_count, end_pos).
    """
    sections: list[tuple[int, int, int]] = []
    i = start
    while i < len(data) - 5:
        count = struct.unpack_from("<H", data, i)[0]
        section_marker = struct.unpack_from("<I", data, i + 2)[0]
        if 1 <= count <= _MAX_SECTION_INSTRUCTIONS and 0 < section_marker < len(data):
            cursor = i + 6
            ok = True
            for _ in range(count):
                if cursor + 9 > len(data):
                    ok = False
                    break
                blob = _parse_blob(data, cursor + 8)
                if not blob:
                    blob = _parse_blob(data, cursor + 9)
                if not blob:
                    ok = False
                    break
                cursor = blob[3]
            if ok:
                sections.append((i, count, cursor))
                i = cursor
                continue
        i += 1
    return sections


def _parse_section_instructions(
    data: bytes,
    sec_off: int,
    count: int,
) -> list[_ScrSectionInstruction]:
    """Parse all instruction blobs in a section.

    Returns parsed SCR instruction tuples with scalar and variant tag data.
    """
    results: list[_ScrSectionInstruction] = []
    cursor = sec_off + 6

    for _ in range(count):
        blob8 = _parse_blob(data, cursor + 8)
        blob9 = _parse_blob(data, cursor + 9)

        if blob8:
            row_1based = data[cursor]
            col_idx = data[cursor + 1]
            cls_name, typ, end_off, next_pos, vsub = blob8
            stop = _SCR_STOP_TAGS.get(cls_name, frozenset())
            cn, tc, tags, tbl, v_u16, v_str = _parse_scr_tags(data, cursor + 8, end_off, vsub, stop)
            results.append((row_1based - 1, col_idx, cn, tc, tags, vsub, tbl, v_u16, v_str))
            cursor = next_pos
        elif blob9:
            row_1based = data[cursor + 1]
            col_idx = data[cursor + 2]
            cls_name, typ, end_off, next_pos, vsub = blob9
            stop = _SCR_STOP_TAGS.get(cls_name, frozenset())
            cn, tc, tags, tbl, v_u16, v_str = _parse_scr_tags(data, cursor + 9, end_off, vsub, stop)
            results.append((row_1based - 1, col_idx, cn, tc, tags, vsub, tbl, v_u16, v_str))
            cursor = next_pos
        else:
            break

    return results


# ---------------------------------------------------------------------------
# Row topology, RTF comment, flag block parsing
# ---------------------------------------------------------------------------


def _parse_row_topology_block(data: bytes, pos: int) -> _ScrRowTopologyBlock | None:
    """Parse a row-topology block anchored by the ordered row-0 flag table."""
    if pos < 0 or pos + min(_ROW_TOPOLOGY_PRELUDE_LEN_RANGE) > len(data):
        return None

    row_word = struct.unpack_from("<H", data, pos)[0]
    if not 2 <= row_word <= 33:
        return None

    if data[pos + 2 : pos + 5] != _ROW_TOPOLOGY_PREFIX:
        return None

    best_block: _ScrRowTopologyBlock | None = None
    best_score: tuple[int, int] | None = None

    # The three bytes immediately before the row-0 table are:
    #   [af_segment] [entry_count] [00]
    # and the bytes between the fixed 5-byte block header and that 3-byte
    # trailer may contain zero or more sparse leading-row blocks.
    flags_scan_limit = min(len(data), pos + 0x40)
    marker_scan_limit = min(len(data), pos + 0x800)
    for flags_start in range(pos + 8, flags_scan_limit):
        af_segment = data[flags_start - 3]
        flag_entry_count = data[flags_start - 2]
        if data[flags_start - 1] != 0:
            continue
        if af_segment not in (0, 1) or not (1 <= flag_entry_count <= 32):
            continue

        if flags_start + flag_entry_count * 2 > len(data):
            continue

        row0_flags: dict[int, int] = {}
        ordered_cols: list[int] = []
        ok = True
        for c in range(flag_entry_count):
            off = flags_start + c * 2
            seg_flag = data[off]
            col_idx = data[off + 1]
            if seg_flag not in (0, 1) or col_idx > _CONDITION_COLUMNS or col_idx in row0_flags:
                ok = False
                break
            row0_flags[col_idx] = seg_flag
            ordered_cols.append(col_idx)

        if not ok:
            continue

        sorted_cols = sorted(ordered_cols)
        for shift in range(flag_entry_count):
            if ordered_cols == sorted_cols[shift:] + sorted_cols[:shift]:
                break
        else:
            continue

        leading_rows_right_wires: list[set[int]] = []
        aux_start = pos + 5
        aux_end = flags_start - 3
        aux_pos = aux_start
        while aux_pos < aux_end:
            parsed = _parse_extra_row_right_wire_block(data, aux_pos, aux_end)
            if parsed is None:
                break
            right_columns, block_len = parsed
            if right_columns:
                leading_rows_right_wires.append(right_columns)
            aux_pos += block_len

        continuation_start = flags_start + flag_entry_count * 2
        marker_probe = continuation_start
        for _ in range(max(0, row_word - 2)):
            parsed = _parse_extra_row_right_wire_block(data, marker_probe, marker_scan_limit)
            if parsed is None:
                break
            _right_columns, block_len = parsed
            marker_probe += block_len

        if (
            marker_probe + 2 > marker_scan_limit
            or data[marker_probe : marker_probe + 2] != b"\x20\x00"
        ):
            continue

        block = _ScrRowTopologyBlock(
            start=pos,
            row_word=row_word,
            prelude=bytes(data[pos:flags_start]),
            leading_rows_right_wires=leading_rows_right_wires,
            row0_flag_count=flag_entry_count,
            row0_flags=row0_flags,
            flags_start=flags_start,
            continuation_start=continuation_start,
        )
        score = (flag_entry_count, -flags_start)
        if best_score is None or score > best_score:
            best_block = block
            best_score = score

    return best_block


def _find_row_topology_block(
    data: bytes, pos: int, max_lookback: int = 4096
) -> _ScrRowTopologyBlock | None:
    """Find the nearest row-topology block before ``pos``."""
    start = max(0, pos - max_lookback)
    for i in range(pos - min(_ROW_TOPOLOGY_PRELUDE_LEN_RANGE), start - 1, -1):
        block = _parse_row_topology_block(data, i)
        if block is not None:
            return block
    return None


def _find_row_topology_blocks_between(
    data: bytes,
    start: int,
    end: int,
) -> list[_ScrRowTopologyBlock]:
    """Find row-topology blocks whose starts fall within ``[start, end)``."""
    blocks: list[_ScrRowTopologyBlock] = []
    pos = max(0, start)
    last_start = -1
    while pos < end:
        block = _parse_row_topology_block(data, pos)
        if block is not None and block.start < end:
            if block.start != last_start:
                blocks.append(block)
                last_start = block.start
            pos = block.flags_start
            continue
        pos += 1
    return blocks


def _find_row_header(data: bytes, pos: int, max_lookback: int = 4096) -> int | None:
    """Compatibility wrapper for callers that still expect a raw offset."""
    block = _find_row_topology_block(data, pos, max_lookback=max_lookback)
    return None if block is None else block.start


def _is_row_header_at(data: bytes, pos: int) -> bool:
    """Return True when *pos* points to a structurally valid row-topology block."""
    return _parse_row_topology_block(data, pos) is not None


def _find_row_headers_between(data: bytes, start: int, end: int) -> list[int]:
    """Compatibility wrapper returning raw row-topology offsets."""
    return [block.start for block in _find_row_topology_blocks_between(data, start, end)]


def _find_rtf_comment(data: bytes, start: int, end: int) -> tuple[bytes | None, str | None]:
    """Find RTF comment between start and end.

    Returns (rtf_bytes, markdown_text) or (None, None).
    """
    for i in range(end - 2, start - 1, -1):
        if data[i : i + 6] == b"{\\rtf1":
            if i >= 4:
                rtf_len = struct.unpack_from("<I", data, i - 4)[0]
                if rtf_len > 0 and i + rtf_len <= len(data):
                    rtf_bytes = bytes(data[i : i + rtf_len])
                    try:
                        comment = _decode_rtf(rtf_bytes)
                    except Exception:
                        comment = None
                    return rtf_bytes, comment
    return None, None


def _parse_row0_flags(data: bytes, rh: int) -> tuple[dict[int, int], int, int]:
    """Parse the variable-length row 0 flag block.

    Returns ``({col_idx: flag}, header_len, block_len)``.
    """
    block = _parse_row_topology_block(data, rh)
    if block is None:
        raise ValueError(f"Invalid row header at offset {rh}")
    return dict(block.row0_flags), len(block.prelude), block.row0_flag_count * 2


def _parse_extra_row_right_wire_block(
    data: bytes,
    start: int,
    end: int,
) -> tuple[set[int], int] | None:
    """Parse one continuation-row topology block.

    SCR stores rows 1..N-1 as variable-length blocks:

    ``00 [count] 00 00 [col next_seg]... [final_col]``

    where ``count`` is the number of cells on that row that have a right wire
    (condition cells plus AF, when present). The stored column order is a
    native serialized order, not always ascending. For each non-final entry,
    ``next_seg`` matches the clipboard segment flag (+0x19) of the next
    serialized right-wire cell. We still only need the explicit column set for
    token reconstruction, but the extra byte explains why the row blocks cannot
    be treated as a plain sorted column list.
    """
    if start + 3 > end or data[start] not in (0x00, 0x01):
        return None

    right_count = data[start + 1]
    block_len = right_count * 2 + 3
    if start + block_len > end:
        return None

    if right_count == 0:
        return set(), block_len

    body = data[start + 2 : start + block_len]
    if len(body) < 3 or body[:2] != b"\x00\x00":
        return None

    pairs = body[2:-1]
    if len(pairs) != (right_count - 1) * 2:
        return None

    right_columns: set[int] = set()
    for i in range(0, len(pairs), 2):
        col_idx = pairs[i]
        next_seg = pairs[i + 1]
        if col_idx > _CONDITION_COLUMNS or next_seg not in (0, 1):
            return None
        right_columns.add(col_idx)

    final_col = body[-1]
    if final_col > _CONDITION_COLUMNS:
        return None
    right_columns.add(final_col)

    return right_columns, block_len


def _parse_extra_row_right_wires(
    data: bytes, start: int, end: int, num_extra_rows: int
) -> tuple[list[set[int]], int | None]:
    """Parse continuation-row topology blocks before the 0x0020 marker.

    Returns ``(rows_right_wires, marker_pos)`` where each row entry is the set
    of columns whose cells carry a right wire on that continuation row.
    """
    rows_right_wires: list[set[int]] = []
    pos = start

    for _ in range(num_extra_rows):
        parsed = _parse_extra_row_right_wire_block(data, pos, end)
        if parsed is None:
            break
        right_columns, block_len = parsed
        rows_right_wires.append(right_columns)
        pos += block_len

    marker_pos = pos if pos + 2 <= end and data[pos : pos + 2] == b"\x20\x00" else None
    if marker_pos is None:
        marker_pos = _find_0x0020_marker(data, pos, end)

    return rows_right_wires, marker_pos


# ---------------------------------------------------------------------------
# Wire-down parsing
# ---------------------------------------------------------------------------


def _find_0x0020_marker(data: bytes, start: int, end: int) -> int | None:
    """Find the 0x0020 marker between start and end."""
    for i in range(start, end - 1):
        if data[i] == 0x20 and data[i + 1] == 0x00:
            return i
    return None


def _parse_wiredown(
    data: bytes, marker_pos: int | None, rung_end: int
) -> dict[int, tuple[int, ...]]:
    """Parse wire_down data from after the 0x0020 marker.

    Returns ``{col_idx: row_indices}`` for columns with vertical wire going down.

    Format: per-column entries starting from col 0:
      no wire_down: ``00 00``
      wire_down: ``[count] [00] [count bytes of 1-based row indices]``
    """
    if marker_pos is None:
        return {}

    pos = marker_pos + 2
    end = rung_end
    col = 0
    result: dict[int, tuple[int, ...]] = {}

    while pos < end:
        count = data[pos]
        if count == 0:
            # No wire_down: 2-byte entry (00 00)
            if pos + 1 < end and data[pos + 1] == 0:
                pos += 2
                col += 1
                continue
            break  # End of data
        entry_len = count + 2
        if pos + entry_len > end:
            break
        rows = tuple(
            sorted({row_idx - 1 for row_idx in data[pos + 2 : pos + entry_len] if row_idx > 0})
        )
        if rows:
            result[col] = rows
        pos += entry_len
        col += 1

    return result


def _build_topology_backed_rung(
    data: bytes,
    topology_block: _ScrRowTopologyBlock,
    rung_end: int,
    logical_rows: int,
    section_instructions: list[_ScrSectionInstruction],
    comment: str | None,
    comment_rtf: bytes | None,
) -> Rung:
    """Parse structural row data for a topology-backed rung and build the Rung object."""
    parsed_count_down = False
    for (
        _row,
        col,
        class_name,
        type_code,
        tags,
        _visual_sub_rows,
        tag_byte_lens,
        variant_u16_tags,
        variant_string_tags,
    ) in section_instructions:
        if col != _CONDITION_COLUMNS:
            continue
        parsed_af = _scr_to_af(
            class_name,
            type_code,
            tags,
            tag_byte_lens,
            variant_u16_tags,
            variant_string_tags,
        )
        if isinstance(parsed_af, Counter) and parsed_af.counter_type == "count_down":
            parsed_count_down = True
            break

    if parsed_count_down:
        leading_rows = list(topology_block.leading_rows_right_wires)
        extra_rows_right_wires, marker_pos = _parse_extra_row_right_wires(
            data,
            topology_block.continuation_start,
            rung_end,
            max(0, logical_rows - (len(leading_rows) + 1)),
        )
        wiredown = _parse_wiredown(data, marker_pos, rung_end)
        bridge_right_wires = set(topology_block.row0_flags)
        if leading_rows and bridge_right_wires:
            first_bridge_col = min(
                (col for col in bridge_right_wires if col < _CONDITION_COLUMNS),
                default=None,
            )
            if first_bridge_col is not None and first_bridge_col not in wiredown:
                wiredown = dict(wiredown)
                wiredown[first_bridge_col] = tuple(range(len(leading_rows)))
            elif first_bridge_col is not None and len(wiredown[first_bridge_col]) < len(
                leading_rows
            ):
                wiredown = dict(wiredown)
                wiredown[first_bridge_col] = tuple(
                    sorted(set(wiredown[first_bridge_col]) | set(range(len(leading_rows))))
                )

        if leading_rows:
            row0_flags = {col: 1 for col in leading_rows[0]}
            build_extra_rows = list(leading_rows[1:])
        else:
            row0_flags = {}
            build_extra_rows = []

        build_extra_rows.append(bridge_right_wires)
        build_extra_rows.extend(extra_rows_right_wires)

        return _build_rung(
            logical_rows=logical_rows,
            section_instructions=section_instructions,
            row0_flags=row0_flags,
            extra_rows_right_wires=build_extra_rows,
            wiredown=wiredown,
            comment=comment,
            comment_rtf=comment_rtf,
        )

    extra_rows_right_wires, marker_pos = _parse_extra_row_right_wires(
        data,
        topology_block.continuation_start,
        rung_end,
        logical_rows - 1,
    )
    wiredown = _parse_wiredown(data, marker_pos, rung_end)
    row0_flags = dict(topology_block.row0_flags)

    # Native SCR can omit continuation-row topology for modifier rows even when
    # the AF blob says that visual sub-row still accepts logic.
    stored_topology_rows = 1 + len(extra_rows_right_wires)
    compact_count_down = False
    if len(topology_block.prelude) > 8 and stored_topology_rows < logical_rows:
        for (
            _row,
            col,
            class_name,
            type_code,
            tags,
            _visual_sub_rows,
            tag_byte_lens,
            variant_u16_tags,
            variant_string_tags,
        ) in section_instructions:
            if col != _CONDITION_COLUMNS:
                continue
            parsed_af = _scr_to_af(
                class_name,
                type_code,
                tags,
                tag_byte_lens,
                variant_u16_tags,
                variant_string_tags,
            )
            if isinstance(parsed_af, Counter) and parsed_af.counter_type == "count_down":
                compact_count_down = True
                break

    if compact_count_down:
        shifted_rows = [set(row0_flags)]
        shifted_rows.extend(extra_rows_right_wires)
        extra_rows_right_wires = shifted_rows[: logical_rows - 1]
        row0_flags = {}

    return _build_rung(
        logical_rows=logical_rows,
        section_instructions=section_instructions,
        row0_flags=row0_flags,
        extra_rows_right_wires=extra_rows_right_wires,
        wiredown=wiredown,
        comment=comment,
        comment_rtf=comment_rtf,
    )


# ---------------------------------------------------------------------------
# Modifier-row inference
# ---------------------------------------------------------------------------


def _implied_modifier_row_offsets(af: object) -> set[int]:
    """Return AF-relative row offsets whose logic path may be omitted in SCR.

    Click can store ``count=0`` or omit continuation-row topology blocks for
    some AF modifier rows even when the visible rung still carries logic across
    that row. The AF blob does still tell us which visual sub-rows are actual
    logic inputs, so we restrict implied dash fill to those known pin rows.
    """
    if isinstance(af, Shift):
        return {1, 2}

    if isinstance(af, Timer):
        return {1} if af.retained else set()

    if isinstance(af, Counter):
        if af.counter_type == "count_down":
            return {1, 2} if af.reset_enabled else {1}

        rows: set[int] = set()
        if af.down_enabled:
            rows.add(1)
        if af.reset_enabled:
            rows.add(2)
        return rows

    if isinstance(af, Drum):
        rows = {1}
        if af.drum_kind == "event":
            if af.jump_enabled:
                rows.add(2)
            if af.jog_enabled:
                rows.add(3)
        return rows

    return set()


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
    from .decode import AfToken, ConditionToken, UnknownCondition

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
            parsed = _scr_to_condition(
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
            parsed_af = _scr_to_af(
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
                rehydrated_raw = _scr_to_raw_af(class_name, type_code, tags, visual_sub_rows)
                if rehydrated_raw is not None:
                    instructions[row] = rehydrated_raw
                    continue

                # Build a minimal RawInstruction from SCR tag data
                from .instructions.raw import _compose_blob

                blob = _compose_blob(
                    class_name,
                    type_code,
                    visual_sub_rows,
                    bytes(range(max(0, visual_sub_rows - 1))),
                    [(t, _RAW_STANDARD_SENTINEL, v) for t, v in tags.items()],
                )
                instructions[row] = RawInstruction(
                    class_name=class_name,
                    blob=blob,
                    part_count=visual_sub_rows,
                )

    if _CONDITION_COLUMNS in row0_flags and instructions[0] == "":
        instructions[0] = "NOP"
    for row_idx, right_wires in enumerate(extra_rows_right_wires, start=1):
        if row_idx >= logical_rows:
            break
        if _CONDITION_COLUMNS in right_wires and instructions[row_idx] == "":
            instructions[row_idx] = "NOP"

    # Native count_down uses a NOP bridge row between the AF row and reset row.
    for row, af in enumerate(instructions[:-1]):
        if (
            isinstance(af, Counter)
            and af.counter_type == "count_down"
            and instructions[row + 1] == ""
        ):
            instructions[row + 1] = "NOP"

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

    implied_modifier_rows: set[int] = set()
    for af_row, af in enumerate(instructions):
        if isinstance(af, str):
            continue
        for row_offset in _implied_modifier_row_offsets(af):
            row = af_row + row_offset
            if 0 < row < logical_rows:
                implied_modifier_rows.add(row)

    # 4. Targeted fallback for modifier rows whose topology Click omits from
    #    SCR even though the AF blob says that visual sub-row accepts logic.
    for row in sorted(implied_modifier_rows):
        explicit_right_wires = row - 1 < len(extra_rows_right_wires) and bool(
            extra_rows_right_wires[row - 1]
        )
        if explicit_right_wires:
            continue

        rightmost = -1
        for col in range(_CONDITION_COLUMNS):
            if conditions[row][col] != "":
                rightmost = col
        if rightmost < 0:
            continue

        for col in range(rightmost + 1, _CONDITION_COLUMNS):
            if conditions[row][col] != "":
                continue
            if row > 0 and conditions[row - 1][col] == "|":
                continue
            conditions[row][col] = "-"

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
    sections = _find_sections(data, start=data_start)

    if not sections:
        return Program(name=name, prog_idx=prog_idx, rungs=[])

    rungs: list[Rung] = []
    prev_sec_end = data_start

    for sec_off, count, sec_end in sections:
        section_instrs = _parse_section_instructions(data, sec_off, count)
        inferred_rows = 1
        has_condition_cells = False
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
        ) in section_instrs:
            inferred_rows = max(inferred_rows, row + 1)
            if col < _CONDITION_COLUMNS:
                has_condition_cells = True
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

        # Find nearest row-topology block before this section.
        topology_block = _find_row_topology_block(data, sec_off)
        headerless = topology_block is None or (
            topology_block.start < prev_sec_end and inferred_rows == 1 and not has_condition_cells
        )
        if headerless:
            # Headerless rung (e.g. next() after for()) — single row, all wired
            rtf_bytes, comment = _find_rtf_comment(data, prev_sec_end, sec_off)
            rung = _build_rung(
                logical_rows=inferred_rows,
                section_instructions=section_instrs,
                row0_flags={c: 1 for c in range(32)},  # all wired
                extra_rows_right_wires=[],
                wiredown={},
                comment=comment,
                comment_rtf=rtf_bytes,
            )
            rungs.append(rung)
            prev_sec_end = sec_end
            continue

        assert topology_block is not None
        comment_start = prev_sec_end
        empty_topology_blocks = _find_row_topology_blocks_between(
            data, prev_sec_end, topology_block.start
        )
        for idx, empty_block in enumerate(empty_topology_blocks):
            empty_end = (
                empty_topology_blocks[idx + 1].start
                if idx + 1 < len(empty_topology_blocks)
                else topology_block.start
            )
            empty_rtf_bytes, empty_comment = _find_rtf_comment(
                data, comment_start, empty_block.start
            )
            rungs.append(
                _build_topology_backed_rung(
                    data=data,
                    topology_block=empty_block,
                    rung_end=empty_end,
                    logical_rows=max(1, empty_block.row_word - 1),
                    section_instructions=[],
                    comment=empty_comment,
                    comment_rtf=empty_rtf_bytes,
                )
            )
            comment_start = empty_block.start

        # Normal rung with a row-topology block.
        logical_rows = max(1, topology_block.row_word - 1, inferred_rows)

        # Find RTF comment
        rtf_bytes, comment = _find_rtf_comment(data, comment_start, topology_block.start)

        rung = _build_topology_backed_rung(
            data=data,
            topology_block=topology_block,
            rung_end=sec_off,
            logical_rows=logical_rows,
            section_instructions=section_instrs,
            comment=comment,
            comment_rtf=rtf_bytes,
        )
        rungs.append(rung)
        prev_sec_end = sec_end

    return Program(name=name, prog_idx=prog_idx, rungs=rungs)
