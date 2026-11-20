"""Read and write the parts of an instruction blob, the binary record of one instruction.

The encoding helpers write UTF-16LE strings and tagged fields for the code that builds a
blob.  The decoding helpers read them back for the code that parses a blob.
``_tag_wire_type`` names a tag's wire type from its high byte.  ``tag_value``, ``tag_int``
and ``tag_flag`` read a tag that a program file may leave out.
"""

from __future__ import annotations

import struct

from .codes import Code
from .operands.errors import FieldError, Reason

# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------


def _utf16le_null(s: str) -> bytes:
    """Encode *s* as UTF-16LE with a null terminator."""
    return s.encode("utf-16-le") + b"\x00\x00"


def _tagged_field(tag: int, value: str) -> bytes:
    """Build ``[2B tag LE][FFFFFFFF sentinel][UTF-16LE null-terminated value]``."""
    return struct.pack("<H", tag) + b"\xff\xff\xff\xff" + _utf16le_null(value)


def _variant_tagged_field(tag: int, sub_marker: bytes, value: str) -> bytes:
    """Build ``[2B tag LE][4B sub-marker][UTF-16LE null-terminated value]``."""
    return struct.pack("<H", tag) + sub_marker + _utf16le_null(value)


def _build_blob(
    class_name: str,
    type_marker: int,
    tags: tuple[int, ...],
    fields: list[str],
) -> bytes:
    """Build an instruction blob of one part.

    The blob holds the class name, the type marker, a part count of 1, the field count and
    the tagged fields.
    """
    out = bytearray()
    out += _utf16le_null(class_name)
    out += struct.pack("<I", type_marker)
    out += b"\x01\x00"
    out += struct.pack("<I", len(fields))
    for tag, value in zip(tags, fields, strict=True):
        out += _tagged_field(tag, value)
    return bytes(out)


# ---------------------------------------------------------------------------
# Decoding helpers
# ---------------------------------------------------------------------------


def _read_utf16le(raw: bytes, offset: int) -> tuple[str, int]:
    """Read a null-terminated UTF-16LE string from *raw* at *offset*.

    Returns ``(string, offset_after_null_terminator)``.
    """
    i = offset
    while i < len(raw) - 1:
        if raw[i] == 0 and raw[i + 1] == 0:
            return raw[offset:i].decode("utf-16-le"), i + 2
        i += 2
    # Unterminated — return what we have.
    return raw[offset:].decode("utf-16-le", errors="replace"), len(raw)


def _parse_tagged_fields(raw: bytes, offset: int, count: int) -> list[str]:
    """Parse *count* tagged fields: ``[2B tag][FFFFFFFF][UTF-16LE value]``.

    Returns a list of decoded string values (tags are discarded).
    """
    fields: list[str] = []
    pos = offset
    for _ in range(count):
        if pos + 6 > len(raw):
            break
        pos += 2  # skip tag
        if raw[pos : pos + 4] != b"\xff\xff\xff\xff":
            break
        pos += 4  # skip sentinel
        value, pos = _read_utf16le(raw, pos)
        fields.append(value)
    return fields


def _parse_tagged_fields_verbose(
    raw: bytes, offset: int, count: int
) -> tuple[list[tuple[int, bytes, str]], int]:
    """Parse *count* tagged fields, returning full detail for each.

    Each field: ``[2B tag LE][4B sentinel/sub-marker][UTF-16LE value]``.

    Returns ``(fields, end_offset)`` where *fields* is a list of
    ``(tag, sentinel_bytes, value)`` tuples.  Unlike
    :func:`_parse_tagged_fields`, this does NOT require the sentinel
    to be ``FFFFFFFF`` — it accepts any 4-byte marker (used by timers
    and other multi-part instructions).
    """
    fields: list[tuple[int, bytes, str]] = []
    pos = offset
    for _ in range(count):
        if pos + 6 > len(raw):
            break
        tag = struct.unpack_from("<H", raw, pos)[0]
        pos += 2
        sentinel = raw[pos : pos + 4]
        pos += 4
        value, pos = _read_utf16le(raw, pos)
        fields.append((tag, sentinel, value))
    return fields, pos


# ---------------------------------------------------------------------------
# Wire-type classification
# ---------------------------------------------------------------------------

_STANDARD_SENTINEL = b"\xff\xff\xff\xff"


def _tag_wire_type(tag: int) -> str:
    """Infer the wire type of a tag from its high byte.

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


# ---------------------------------------------------------------------------
# Tag defaults: reading a tag that may be absent
# ---------------------------------------------------------------------------
#
# Click's program files (Scr*.tmp) store a tag only when its value differs from
# the default.  The clipboard stores every tag.  A tag missing from a decoded tag
# dict therefore reads as its default.  Every ``from_tags`` reads value tags
# through ``tag_value`` or ``tag_int``, and flag tags through ``tag_flag``.
#
# A tag's default is the zero of its wire type: ``""`` for a string tag, ``"0"``
# for a byte or u16 tag, and unset for a flag.  The tables below list the tags
# whose default is something else.  A program file leaves each of them out when
# it holds that value.
#
# The func code (0x3218) is the exception.  A program file leaves it out whenever
# the class and the other fields determine it, so each instruction family works it
# out itself.

#: Tags whose default is not zero, whatever the class.
_TAG_DEFAULTS: dict[int, str] = {
    0x20CA: "2",
    0x221C: "1",  # Send/Receive word swap off
    0x3203: "1",  # Drum step count
    0x3204: "1",  # Drum output count
    0x3210: "1",  # Send/Receive quantity
    0x322C: "502",  # Modbus TCP port
}

#: Class-specific non-zero defaults, ``(class_name, tag) -> value``.
_CLASS_TAG_DEFAULTS: dict[tuple[str, int], str] = {
    ("RD", 0x320E): "1",  # Receive device ID
    ("RD", 0x60B2): "1",
    ("RD", 0x608D): "SD50",
    ("RD", 0x608E): "SD60",
    ("Position", 0x222F): "2",
    ("Velocity", 0x222F): "2",
}


def tag_default(tag: int, class_name: str = "") -> str:
    """Return the value a tag has when Click leaves it out."""
    value = _CLASS_TAG_DEFAULTS.get((class_name, tag))
    if value is not None:
        return value
    value = _TAG_DEFAULTS.get(tag)
    if value is not None:
        return value
    return "0" if _tag_wire_type(tag) in ("byte", "u16") else ""


#: Flags that are set by default, ``(class_name, tag)``. A program file stores one of
#: them only when it is clear. No ``from_tags`` reads these flags, so ``tag_flag``
#: does not use this table.
_CLASS_FLAG_DEFAULTS: frozenset[tuple[str, int]] = frozenset(
    ("RD", tag) for tag in (0x1209, 0x120A, 0x120B, 0x121A, 0x121B, 0x121E, 0x121F)
)


def flag_set(tags: dict[int, str], tag: int, class_name: str = "") -> bool:
    """Return whether a flag is set in the tags that a program file stores.

    The program file stores a flag only when it differs from its default. The default is
    clear, except for the flags in ``_CLASS_FLAG_DEFAULTS``.
    """
    return (tag in tags) != ((class_name, tag) in _CLASS_FLAG_DEFAULTS)


#: The classes whose clipboard blob writes a set flag as ``-1``. Every other class writes
#: it as ``1``. A clear flag is ``0`` in every class.
_MINUS_ONE_FLAG_CLASSES = frozenset({"Copy", "Drum", "Math", "Search"})


def _set_flag(class_name: str) -> str:
    """Return the value that the clipboard writes for a set flag of *class_name*."""
    return "-1" if class_name in _MINUS_ONE_FLAG_CLASSES else "1"


def tag_value(tags: dict[int, str], tag: int, class_name: str = "") -> str:
    """Read a value tag, or its default when it is absent or is a blank byte or u16 tag."""
    value = tags.get(tag)
    if value is None or (not value and _tag_wire_type(tag) in ("byte", "u16")):
        return tag_default(tag, class_name)
    return value


class NotANumber(FieldError):
    """Raised when a numeric tag holds text that is not a number.  The blob stays unparsed."""


def tag_int(tags: dict[int, str], tag: int, class_name: str = "") -> int:
    """Read a numeric tag as an int.  An absent or blank tag reads as its default.

    Raises :class:`NotANumber` when the tag holds text that is not a number.  The decoders
    then keep the blob raw.
    """
    value = tag_value(tags, tag, class_name)
    if not value:
        return int(tag_default(tag, class_name) or "0")
    try:
        return int(value)
    except ValueError:
        raise NotANumber(
            f"tag 0x{tag:04X}: {value!r} is no number", reason=Reason.KIND, code=Code.NOT_CLICK_FORM
        ) from None


def tag_flag(tags: dict[int, str], tag: int) -> bool:
    """Read a flag tag (0x11xx/0x12xx): set when present, unset when absent."""
    return tag in tags
