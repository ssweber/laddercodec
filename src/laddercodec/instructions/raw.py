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
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..binary_helpers import (
    _parse_tagged_fields_verbose,
    _tag_wire_type,
    _tagged_field,
    _utf16le_null,
    _variant_tagged_field,
)
from ..model import AfInstruction, FieldError
from .family import AfInstructionFamilySpec, cell_rows_spec

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
        native cell's bytes, and leave a typed box raw when its stored row
        span is not its class's.  ``None`` takes the height from the class:
        the typed family's height when its blob alone gives it (Copy family,
        Search, Send, Receive, Out variants, and 3 rows for Email, Home,
        Position and Velocity), otherwise one row below its last part's
        row (the blob's extra part bytes; 1 row for a 1-part box).  Boxes the
        editor creates may store other sub-rows (Math ``01 03``, some
        Search ``02 03``, Tmr ``02 03``, Drum ``04 05``, SR ``03 02``); for
        those classes CLICK keeps the height laddercodec writes.  With
        ``visual_rows`` set and ``sub_rows`` None, the sub-rows equal the row
        span.  The CSV token holds the two bytes the box encodes
        (``rows=``, ``sub=``) and, for a box of 2 or more parts, the extra
        part bytes (``pins=``).  Two boxes are equal when they encode the
        same bytes: a box with ``None`` equals one that states its class's
        height.
    """

    class_name: str
    blob: bytes
    part_count: int = 1
    visual_rows: int | None = None
    sub_rows: int | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RawInstruction):
            return NotImplemented
        return (self.class_name, self.blob, self.part_count, self._cell_rows()) == (
            other.class_name,
            other.blob,
            other.part_count,
            other._cell_rows(),
        )

    def _cell_rows(self) -> tuple[int, int]:
        """The row span (+0x09) and sub-rows (+0x0A) this box encodes."""
        params = self.cell_params()
        span = int(params.get("visual_rows", 1))
        return span, int(params.get("sub_rows", span))

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
        other box (the pinned families among them) ends one row below its last
        part's row, or spans ``part_count`` rows when its part bytes are no pin rows.
        """
        from . import AF_FAMILY_SPECS  # the registry imports this module

        try:
            class_name, type_marker, pc, eb, fields = _decompose_blob(self.blob)
        except (ValueError, IndexError, struct.error):
            return {"visual_rows": self.part_count} if self.part_count > 1 else {}
        tags, _u16, _str = _fields_to_tag_dicts(fields)
        for spec in AF_FAMILY_SPECS:
            hook = spec.cell_params_from_tags
            if hook is not None and (params := hook(class_name, type_marker, tags)) is not None:
                return params
        if eb and _pins_spec(eb, pc):
            return {"visual_rows": eb[-1] + 1}
        return {"visual_rows": self.part_count} if self.part_count > 1 else {}

    def part_rows(self) -> tuple[int, ...]:
        """Each later part's row below the main row: the blob's part bytes.

        Empty for a 1-part box, and when the part bytes are not one ascending row from 1
        to 31 per later part.
        """
        try:
            _cn, _tm, pc, eb, _fields = _decompose_blob(self.blob)
        except (ValueError, IndexError, struct.error):
            return ()
        return tuple(eb) if eb and _pins_spec(eb, pc) else ()

    def build_blob(self) -> bytes:
        """Return the raw blob bytes (no-op — already stored)."""
        return self.blob

    def to_csv(self) -> str:
        """Serialize to decoded-fields ``raw(ClassName,0xTTTT,N,rows=R,sub=S,...)`` token.

        ``rows`` and ``sub`` are the cell bytes the box encodes (+0x09, +0x0A); a box of
        2 or more parts adds ``pins=``, its extra part bytes.  Falls back to the legacy
        hex format, with ``rows`` and ``sub``, if decomposition fails, or if the part
        bytes are no ascending rows 1 to 31 or the span is not the last one + 1, or if
        the fields text does not read back as this box (a field value the token can't carry).
        """
        params = self.cell_params()
        rows = cell_rows_spec(params)
        try:
            cn, tm, pc, eb, flds = _decompose_blob(self.blob)
            specs = _compress_fields(flds)
        except (ValueError, IndexError, struct.error):
            return f"raw({self.class_name},{self.blob.hex()},{rows})"
        pins = _pins_spec(eb, pc)
        if pins is None or (eb and params.get("visual_rows", 1) != eb[-1] + 1):
            # Part bytes or a height the fields form refuses: the hex keeps them.
            return f"raw({self.class_name},{self.blob.hex()},{rows})"
        parts = [cn, f"0x{tm:04x}", str(pc), rows, *([pins] if pins else []), *specs]
        token = f"raw({','.join(parts)})"
        if not self._reads_back(token):
            # A field value the token can't carry: the hex keeps it.
            return f"raw({self.class_name},{self.blob.hex()},{rows})"
        return token

    def _reads_back(self, token: str) -> bool:
        """Whether *token* reads back as this box, bytes and height."""
        from ..csv.ast import AfCall
        from ..csv.token_parser import parse_af_token  # the csv package imports this module

        try:
            # The CSV reader's path: the token parser first, then the token it hands on.
            node = parse_af_token(token)
            return isinstance(node, AfCall) and self.from_csv_token(node.to_token()) == self
        except ValueError:
            return False

    @classmethod
    def from_csv_token(cls, token: str) -> RawInstruction:
        """Parse a raw CSV token (decoded-fields or legacy hex).

        Decoded-fields format::

            raw(ClassName,0xTTTT,N,rows=R,sub=S,pins=P,field_specs...)

        Legacy hex format::

            raw(ClassName,hex_blob,rows=R,sub=S)

        ``rows`` (row span) and ``sub`` (sub-rows) come right after the part count, or
        after the hex.  Each is optional: an absent one is ``visual_rows`` or
        ``sub_rows`` None, which takes the class's height.  ``pins`` (fields format
        only, 2 or more parts) is the extra part bytes joined by ``/``; without it they
        are ``01 02 ...``.  A stated ``rows`` must be the last pin + 1.
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
        hex_blob, *rest_parts = (part.strip() for part in rest.split(","))
        visual_rows, sub_rows, pins, extra = _take_box_rows(class_name, rest_parts)
        if pins is not None:
            raise FieldError(
                f"raw({class_name},hex,...): pins={pins} can't follow the hex; the blob "
                "holds the part bytes"
            )
        if extra:
            raise FieldError(
                f"raw({class_name},hex,...): only rows= and sub= may follow the hex, "
                f"not {extra[0]!r}"
            )
        blob = bytes.fromhex(hex_blob)
        try:
            _, _, part_count = find_blob_boundary(blob)
        except (ValueError, IndexError):
            part_count = 1
        return cls(class_name, blob, part_count, visual_rows, sub_rows)

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
        visual_rows, sub_rows, pins, field_specs = _take_box_rows(class_name, parts[2:])
        extra_bytes = _pin_rows(class_name, part_count, pins)
        if extra_bytes and visual_rows is not None and visual_rows != extra_bytes[-1] + 1:
            stated = "pins=" + pins if pins is not None else "no pins= (rows 1, 2, ...)"
            raise FieldError(
                f"raw({class_name},...): rows={visual_rows} does not fit {stated}; the box "
                f"ends one row below its last pin (rows={extra_bytes[-1] + 1})"
            )

        fields = _parse_field_specs(field_specs)
        blob = _compose_blob(class_name, type_marker, part_count, extra_bytes, fields)
        return cls(class_name, blob, part_count, visual_rows, sub_rows)


def _take_cell_rows(class_name: str, parts: list[str]) -> tuple[int | None, int | None, list[str]]:
    """Read the leading ``rows=`` and ``sub=`` of a raw token's *parts*.

    Returns ``(visual_rows, sub_rows, remaining parts)``; an absent field is None.
    A ``pins=`` among the parts raises FieldError (see :func:`_take_box_rows`).
    """
    rows, sub, pins, rest = _take_box_rows(class_name, parts)
    if pins is not None:
        raise FieldError(f"raw({class_name},...): pins= is only for a box of 2 or more parts")
    return rows, sub, rest


def _take_box_rows(
    class_name: str, parts: list[str]
) -> tuple[int | None, int | None, str | None, list[str]]:
    """Read the leading ``rows=``, ``sub=`` and ``pins=`` of a raw token's *parts*.

    Returns ``(visual_rows, sub_rows, pins text, remaining parts)``; an absent
    field is None.  A box spans at most a rung's rows; its sub-rows byte may
    exceed its span (a native Drum stores ``04 05``).
    """
    from ..encode import MAX_ROWS

    values: dict[str, int | None] = {"rows": None, "sub": None}
    limits = {"rows": MAX_ROWS, "sub": 0xFF}
    i = 0
    for key in values:
        if i < len(parts) and parts[i].startswith(f"{key}="):
            text = parts[i][len(key) + 1 :]
            if not (text.isascii() and text.isdigit() and 1 <= int(text) <= limits[key]):
                raise FieldError(
                    f"raw({class_name},...): {key}={text!r} is not a whole number "
                    f"from 1 to {limits[key]}"
                )
            values[key] = int(text)
            i += 1
    pins = None
    if i < len(parts) and parts[i].startswith("pins="):
        pins = parts[i][len("pins=") :]
        i += 1
    for part in parts[i:]:
        if part.startswith(("rows=", "sub=", "pins=")):
            raise FieldError(
                f"raw({class_name},...): {part!r} goes right after the part count, "
                "rows= then sub= then pins=, once each"
            )
    return values["rows"], values["sub"], pins, parts[i:]


def _pin_rows(class_name: str, part_count: int, text: str | None) -> bytes:
    """The extra part bytes of a box of *part_count* parts, from a token's ``pins=``.

    Each later part's row below the main row, ascending, 1 to 31 (a box ends inside
    a rung).  Without ``pins=`` the parts sit on rows 1, 2, ...
    """
    want = max(0, part_count - 1)
    if text is None:
        return bytes(range(1, want + 1))
    if want == 0:
        raise FieldError(
            f"raw({class_name},...): pins={text} is only for a box of 2 or more parts, "
            f"not {part_count}"
        )
    values = text.split("/")
    if len(values) != want:
        raise FieldError(
            f"raw({class_name},...): pins={text} must hold {want} rows, one per part "
            f"after the first, joined by /"
        )
    if not all(v.isascii() and v.isdigit() and 1 <= int(v) <= 31 for v in values):
        raise FieldError(
            f"raw({class_name},...): pins={text} holds a row that is not a whole number "
            "from 1 to 31"
        )
    rows = [int(v) for v in values]
    if any(later <= earlier for earlier, later in zip(rows, rows[1:], strict=False)):
        raise FieldError(f"raw({class_name},...): pins={text} must ascend")
    return bytes(rows)


def _pins_spec(extra_bytes: bytes, part_count: int) -> str | None:
    """The ``pins=`` field for *extra_bytes*, or None when a token can't state them."""
    if part_count < 2:
        return None if extra_bytes else ""
    rows = list(extra_bytes)
    if (
        len(rows) != part_count - 1
        or not all(1 <= row <= 31 for row in rows)
        or any(later <= earlier for earlier, later in zip(rows, rows[1:], strict=False))
    ):
        return None
    return "pins=" + "/".join(str(row) for row in rows)


def _take_fixed_cell_rows(class_name: str, parts: list[str], params: dict[str, int]) -> list[str]:
    """Read the ``rows=``/``sub=`` of a fixed-height class's token *parts*.

    A stated height other than the class's (*params*) raises FieldError, since
    the typed object always writes its class's height. Returns the parts after them.
    """
    rows, sub, rest = _take_cell_rows(class_name, parts)
    span = params["visual_rows"]
    want = (span, params.get("sub_rows", span))
    got_rows = span if rows is None else rows
    got_sub = sub if sub is not None else (want[1] if rows is None else rows)
    got = (got_rows, got_sub)
    if got != want:
        raise FieldError(
            f"raw({class_name},...): rows={got[0]},sub={got[1]} is not the {class_name} "
            f"box's height (rows={want[0]},sub={want[1]})"
        )
    return rest


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
