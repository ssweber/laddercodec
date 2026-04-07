"""Shared binary serialization primitives for instruction blobs.

Encoding helpers (UTF-16LE strings, tagged fields) used by instruction
blob builders, and decoding helpers (read/parse) used by blob parsers.
Wire-type classification for tag dispatch.
"""

from __future__ import annotations

import struct

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
    """Build a standard instruction blob: class name + type marker + part=1 + tagged fields."""
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
