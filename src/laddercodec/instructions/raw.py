"""Raw — opaque instruction passthrough for unrecognised class names.

Preserves the full instruction blob (from cell offset +0x25 to before
the tail) as hex.  The encoder reconstructs header and tail from grid
context; the blob is pasted verbatim.

CSV token format (decoded fields)::

    raw(ClassName,0xTTTT,N,tag=val,tag=val,...,tag[250]=,...)

Where:
- ``0xTTTT`` is the type marker (hex).
- ``N`` is the part count (1 for single-row, 2+ for multi-row).
- ``tag=val`` is a standard-sentinel (FFFFFFFF) tagged field.
- ``tag[N]=`` is an array run: N entries with sequential index sentinels,
  all empty.
- ``tag:SSSSSSSS=val`` is a variant-sentinel tagged field (explicit
  sentinel hex).

Legacy hex format is still accepted on read::

    raw(ClassName,hex_blob)
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..binary_helpers import (
    _parse_tagged_fields_verbose,
    _tag_wire_type,
    _tagged_field,
    _utf16le_null,
    _variant_tagged_field,
)
from ..model import AfInstruction, FieldError
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

# ---------------------------------------------------------------------------
# Blob boundary detection
# ---------------------------------------------------------------------------

_STANDARD_SENTINEL = b"\xff\xff\xff\xff"


def _read_utf16le_boundary(raw: bytes, offset: int) -> tuple[str, int]:
    """Read a null-terminated UTF-16LE string, return (string, pos_after_null).

    Raises ``ValueError`` if the string is unterminated within *raw*.
    """
    i = offset
    while i + 1 < len(raw):
        if raw[i] == 0 and raw[i + 1] == 0:
            return raw[offset:i].decode("utf-16-le"), i + 2
        i += 2
    raise ValueError(f"Unterminated UTF-16LE string at offset {offset:#x}")


def find_blob_boundary(raw: bytes) -> tuple[str, int, int]:
    """Find the end of the instruction blob in *raw* bytes.

    *raw* is everything from cell offset +0x25 to the next cell boundary
    (i.e. blob + 16-byte tail).

    Returns ``(class_name, blob_end_offset, part_count)``.  The clean
    blob is ``raw[:blob_end_offset]``.

    Raises ``ValueError`` on malformed data.
    """
    pos = 0

    # 1. Class name (UTF-16LE null-terminated).
    class_name, pos = _read_utf16le_boundary(raw, pos)

    # 2. Type marker (uint32 LE).
    if pos + 4 > len(raw):
        raise ValueError("Truncated: no type marker")
    pos += 4

    # 3. Part count (uint16 LE).
    if pos + 2 > len(raw):
        raise ValueError("Truncated: no part count")
    part_count = struct.unpack_from("<H", raw, pos)[0]
    pos += 2

    # 4. Extra part bytes: (part_count - 1) sequential bytes.
    extra = max(0, part_count - 1)
    if pos + extra > len(raw):
        raise ValueError("Truncated: missing part extra bytes")
    pos += extra

    # 5. Field count (uint32 LE).
    if pos + 4 > len(raw):
        raise ValueError("Truncated: no field count")
    field_count = struct.unpack_from("<I", raw, pos)[0]
    pos += 4

    # 6. Tagged fields: [2B tag][4B sentinel/marker][UTF-16LE null value].
    for f_idx in range(field_count):
        if pos + 6 > len(raw):
            raise ValueError(f"Truncated at field {f_idx}/{field_count}")
        pos += 2  # tag
        pos += 4  # sentinel or sub-marker
        _, pos = _read_utf16le_boundary(raw, pos)

    return class_name, pos, part_count


# ---------------------------------------------------------------------------
# Blob decompose / compose
# ---------------------------------------------------------------------------


def _decompose_blob(
    blob: bytes,
) -> tuple[str, int, int, bytes, list[tuple[int, bytes, str]]]:
    """Parse a raw blob into structural components.

    Returns ``(class_name, type_marker, part_count, extra_bytes, fields)``
    where *fields* is a list of ``(tag, sentinel_4bytes, value)`` tuples.
    """
    pos = 0
    class_name, pos = _read_utf16le_boundary(blob, pos)
    type_marker = struct.unpack_from("<I", blob, pos)[0]
    pos += 4
    part_count = struct.unpack_from("<H", blob, pos)[0]
    pos += 2
    extra_n = max(0, part_count - 1)
    extra_bytes = blob[pos : pos + extra_n]
    pos += extra_n
    field_count = struct.unpack_from("<I", blob, pos)[0]
    pos += 4
    fields, _ = _parse_tagged_fields_verbose(blob, pos, field_count)
    return class_name, type_marker, part_count, extra_bytes, fields


def _fields_to_tag_dicts(
    fields: list[tuple[int, bytes, str]],
) -> tuple[
    dict[int, str],
    dict[int, dict[int, int]],
    dict[int, dict[int, str]],
]:
    """Convert verbose tagged-field list to SCR-style tag dicts.

    Normalises clipboard conventions to match the SCR representation:

    * **Flag tags** (``0x11xx``/``0x12xx``): clipboard value ``"-1"``
      or ``"1"`` → present in *tags*; ``"0"`` → absent.
    * **Value tags** (byte, u16, string): their string value in *tags*;
      read them through ``binary_helpers.tag_value`` / ``tag_int``.
    * **Variant-sentinel fields**: ``0x3Axx`` → *variant_u16_tags*,
      ``0x68xx`` → *variant_string_tags*.

    Returns ``(tags, variant_u16_tags, variant_string_tags)``.
    """
    tags: dict[int, str] = {}
    variant_u16_tags: dict[int, dict[int, int]] = {}
    variant_string_tags: dict[int, dict[int, str]] = {}

    for tag, sentinel, value in fields:
        if sentinel == _STANDARD_SENTINEL:
            if _tag_wire_type(tag) == "flag":
                if value in ("-1", "1"):
                    tags[tag] = ""
                # "0" / "" → absent (disabled)
            else:
                tags[tag] = value
        else:
            # Variant sentinel — the 4 bytes encode the array index.
            idx = struct.unpack_from("<I", sentinel)[0]
            wire = _tag_wire_type(tag)
            if wire == "variant_u16":
                try:
                    int_val = int(value or "0")
                except ValueError:
                    int_val = 0
                variant_u16_tags.setdefault(tag, {})[idx] = int_val
            elif wire == "variant_string":
                variant_string_tags.setdefault(tag, {})[idx] = value
            else:
                # Unknown variant — store as string tag (harmless).
                tags[tag] = value

    return tags, variant_u16_tags, variant_string_tags


def _compose_blob(
    class_name: str,
    type_marker: int,
    part_count: int,
    extra_bytes: bytes,
    fields: list[tuple[int, bytes, str]],
) -> bytes:
    """Reconstruct blob bytes from structural components."""
    out = bytearray()
    out += _utf16le_null(class_name)
    out += struct.pack("<I", type_marker)
    out += struct.pack("<H", part_count)
    out += extra_bytes
    out += struct.pack("<I", len(fields))
    for tag, sentinel, value in fields:
        if sentinel == _STANDARD_SENTINEL:
            out += _tagged_field(tag, value)
        else:
            out += _variant_tagged_field(tag, sentinel, value)
    return bytes(out)


# ---------------------------------------------------------------------------
# Field spec serialization (blob ↔ CSV field specs)
# ---------------------------------------------------------------------------


def _compress_fields(fields: list[tuple[int, bytes, str]]) -> list[str]:
    """Convert tagged fields to compact field-spec strings.

    Standard sentinel fields: ``tag=val``.
    Array runs (same tag, sequential index sentinels, all empty): ``tag[N]=``.
    Single variant sentinel fields: ``tag:SSSSSSSS=val``.
    """
    specs: list[str] = []
    i = 0
    while i < len(fields):
        tag, sentinel, value = fields[i]

        if sentinel == _STANDARD_SENTINEL:
            specs.append(f"{tag:04x}={value}")
            i += 1
            continue

        # Check for compressible array run: same tag, sequential index
        # sentinels starting at 0, all empty values.
        idx_val = struct.unpack_from("<I", sentinel)[0]
        if idx_val == 0 and value == "":
            run_len = 1
            while i + run_len < len(fields):
                t, s, v = fields[i + run_len]
                if t != tag or v != "" or s != struct.pack("<I", run_len):
                    break
                run_len += 1
            if run_len > 1:
                specs.append(f"{tag:04x}[{run_len}]=")
                i += run_len
                continue

        # Single variant field — emit with explicit sentinel.
        specs.append(f"{tag:04x}:{sentinel.hex()}={value}")
        i += 1

    return specs


# Regex for parsing a single field spec.
_FIELD_SPEC_RE = re.compile(
    r"([0-9a-fA-F]{4})"  # tag (4 hex digits)
    r"(?:\[([0-9]+)\])?"  # optional [N] array count
    r"(?::([0-9a-fA-F]{8}))?"  # optional :sentinel (8 hex digits)
    r"=(.*)",  # =value (rest of string)
)


def _parse_field_specs(specs: list[str]) -> list[tuple[int, bytes, str]]:
    """Parse field-spec strings back to ``(tag, sentinel, value)`` tuples."""
    fields: list[tuple[int, bytes, str]] = []
    for spec in specs:
        m = _FIELD_SPEC_RE.fullmatch(spec)
        if not m:
            raise ValueError(f"Invalid field spec: {spec!r}")
        tag = int(m.group(1), 16)
        array_count = int(m.group(2)) if m.group(2) else None
        sentinel_hex = m.group(3)
        value = m.group(4)

        if array_count is not None:
            # Array run: N entries with sequential index sentinels.
            for idx in range(array_count):
                fields.append((tag, struct.pack("<I", idx), value))
        elif sentinel_hex is not None:
            # Explicit variant sentinel.
            fields.append((tag, bytes.fromhex(sentinel_hex), value))
        else:
            # Standard sentinel.
            fields.append((tag, _STANDARD_SENTINEL, value))

    return fields


def _split_raw_args(text: str) -> list[str]:
    """Split comma-separated raw token arguments, respecting double quotes."""
    parts: list[str] = []
    current: list[str] = []
    in_quote = False
    for ch in text:
        if ch == '"':
            current.append(ch)
            in_quote = not in_quote
        elif ch == "," and not in_quote:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    parts.append("".join(current).strip())
    return parts


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class RawInstruction(AfInstruction):
    """Opaque AF instruction — blob preserved for byte-exact round-trip.

    Attributes
    ----------
    class_name:
        Binary class name (e.g. ``"Copy"``, ``"Cnt"``).  Extracted from
        the blob for CSV readability; also present inside *blob*.
    blob:
        Full instruction blob bytes (from cell offset +0x25 to the end
        of tagged fields, excluding tail).
    part_count:
        Number of parts (1 = single-row, >1 = multi-row).  Derived from
        the blob during construction.
    visual_rows, sub_rows:
        The box's cell header row bytes: ``visual_rows`` is the row span
        (+0x09), ``sub_rows`` the sub-rows (+0x0A).  The decoders keep the
        native cell's bytes.  ``None`` takes the height from the class: the
        typed family's height when its blob alone gives it (Copy family,
        Search, Send, Receive, Out variants), otherwise ``part_count`` rows.
        A ``sub_rows`` of ``None`` with a ``visual_rows`` given is that row
        span.  The CSV token does not hold them, so they take no part in
        equality.
    """

    class_name: str
    blob: bytes
    part_count: int = 1
    visual_rows: int | None = field(default=None, compare=False)
    sub_rows: int | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        # A decoded blob gives any class name and a 16-bit part count; check only the types.
        if not isinstance(self.class_name, str):
            raise FieldError(f"RawInstruction.class_name: {self.class_name!r} is not text")
        if not isinstance(self.blob, bytes):
            raise FieldError(f"RawInstruction.blob: {type(self.blob).__name__} is not bytes")
        if type(self.part_count) is not int or not 0 <= self.part_count <= 0xFFFF:
            raise FieldError(
                f"RawInstruction.part_count: {self.part_count!r} is not a whole number "
                "from 0 to 65535"
            )
        for name in ("visual_rows", "sub_rows"):
            rows = getattr(self, name)
            if rows is not None and (type(rows) is not int or not 1 <= rows <= 0xFF):
                raise FieldError(
                    f"RawInstruction.{name}: {rows!r} is not a whole number from 1 to 255"
                )

    def cell_params(self) -> dict:
        """Return ClickCell kwargs intrinsic to this instruction."""
        if self.visual_rows is None:
            params = self._class_cell_params()
            span = int(params.get("visual_rows", 1))
            sub = int(params.get("sub_rows", span)) if self.sub_rows is None else self.sub_rows
        else:
            span = self.visual_rows
            sub = span if self.sub_rows is None else self.sub_rows
        if span == sub == 1:
            return {}
        return {"visual_rows": span} if sub == span else {"visual_rows": span, "sub_rows": sub}

    def _class_cell_params(self) -> dict:
        """Height of a box of this class with no native cell header.

        The first family whose ``cell_params_from_tags`` knows the blob gives it; any
        other box (the pinned families among them) spans ``part_count`` rows.
        """
        from . import AF_FAMILY_SPECS  # the registry imports this module

        try:
            class_name, type_marker, _pc, _eb, fields = _decompose_blob(self.blob)
        except (ValueError, IndexError, struct.error):
            return {"visual_rows": self.part_count} if self.part_count > 1 else {}
        tags, _u16, _str = _fields_to_tag_dicts(fields)
        for spec in AF_FAMILY_SPECS:
            hook = spec.cell_params_from_tags
            if hook is not None and (params := hook(class_name, type_marker, tags)) is not None:
                return params
        return {"visual_rows": self.part_count} if self.part_count > 1 else {}

    def build_blob(self) -> bytes:
        """Return the raw blob bytes (no-op — already stored)."""
        return self.blob

    def to_csv(self) -> str:
        """Serialize to decoded-fields ``raw(ClassName,0xTTTT,N,...)`` token.

        Falls back to legacy hex format if decomposition fails.
        """
        try:
            cn, tm, pc, _eb, flds = _decompose_blob(self.blob)
            specs = _compress_fields(flds)
            parts = [cn, f"0x{tm:04x}", str(pc), *specs]
            return f"raw({','.join(parts)})"
        except (ValueError, IndexError, struct.error):
            return f"raw({self.class_name},{self.blob.hex()})"

    @classmethod
    def from_csv_token(cls, token: str) -> RawInstruction:
        """Parse a raw CSV token (decoded-fields or legacy hex).

        Decoded-fields format::

            raw(ClassName,0xTTTT,N,field_specs...)

        Legacy hex format::

            raw(ClassName,hex_blob)
        """
        token = token.strip()
        if not token.startswith("raw(") or not token.endswith(")"):
            raise ValueError(f"Not a raw token: {token!r}")
        inner = token[4:-1]

        # Split on first comma to get class name.
        first_comma = inner.index(",")
        class_name = inner[:first_comma].strip()
        rest = inner[first_comma + 1 :].strip()

        # Detect format: decoded-fields (starts with 0x) vs legacy hex.
        if rest.startswith("0x"):
            return cls._from_fields_token(class_name, rest)

        # Legacy hex format.
        blob = bytes.fromhex(rest)
        try:
            _, _, part_count = find_blob_boundary(blob)
        except (ValueError, IndexError):
            part_count = 1
        return cls(class_name=class_name, blob=blob, part_count=part_count)

    @classmethod
    def _from_fields_token(cls, class_name: str, rest: str) -> RawInstruction:
        """Parse decoded-fields format after the class name."""
        parts = _split_raw_args(rest)
        if (
            len(parts) < 2
            or not re.fullmatch(r"(?:0[xX])?[0-9A-Fa-f]+", parts[0])
            or not re.fullmatch(r"[0-9]+", parts[1])
        ):
            raise ValueError(
                f"raw({class_name},...): type marker is 0xTTTT and part count is digits"
            )
        type_marker = int(parts[0], 16)
        part_count = int(parts[1])
        field_specs = parts[2:]

        fields = _parse_field_specs(field_specs)

        # Reconstruct extra bytes: Click numbers parts 1..part_count-1 (Tmr 01,
        # Cnt/SR 01 02, Drum 01 02 03 in every native capture).
        extra_bytes = bytes(range(1, max(1, part_count)))

        blob = _compose_blob(class_name, type_marker, part_count, extra_bytes, fields)
        return cls(class_name=class_name, blob=blob, part_count=part_count)


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> RawInstruction | None:
    """Raw from_tags always returns None.

    All previously-handled families (Email, Home, Velocity, Position)
    now have their own modules.  Genuinely unrecognised class names
    fall through to the caller's ``RawInstruction`` fallback.
    """
    return None


def parse_af_call(call: AfCall) -> RawInstruction:
    """Parse an AF AST call into a RawInstruction."""
    return RawInstruction.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="raw",
    instruction_types=(RawInstruction,),
    binary_class_names=(),
    from_tags=from_tags,
    csv_names=("raw",),
    parse_csv_call=parse_af_call,
)
