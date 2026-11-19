"""Raw: an AF instruction that laddercodec keeps as bytes.

The decoders return one for a class name that no family recognises.  They also return one
for a box that its family cannot read, and for a box whose cell stores a row span other
than the span the decoded box would have.

``RawInstruction`` keeps the whole instruction blob, from cell offset +0x25 up to
the tail.  The encoder builds the cell header and the tail from the position of
the box in the grid, and writes the blob unchanged.

CSV token format (decoded fields)::

    raw(ClassName,0xTTTT,N,rows=R,sub=S,pins=P,tag=val,tag=val,...,tag[250]=,...)

Where:
- ``0xTTTT`` is the type marker (hex).
- ``N`` is the part count (1 for single-row, 2+ for multi-row).
- ``rows=R`` and ``sub=S`` are the cell's row span and sub-rows.  ``pins=P``
  appears only for a box of 2 or more parts.  See :meth:`RawInstruction.from_csv_token`.
- ``tag=val`` is a tagged field with the standard sentinel (FFFFFFFF).
- ``tag[N]=`` is an array run: N entries with sequential index sentinels,
  all empty.
- ``tag:SSSSSSSS=val`` is a tagged field with a variant sentinel, given in hex.

When the decoded-fields form cannot hold a blob, the token holds the blob as hex.
The reader accepts this form too::

    raw(ClassName,hex_blob,rows=R,sub=S)
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
from ..codes import Code
from ..model import FieldError, Instruction, Reason
from ..operands.checks import Refusals
from ..operands.message import Rule, make_refusal, says
from .family import AfInstructionFamilySpec, cell_rows_spec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

# ---------------------------------------------------------------------------
# Blob boundary detection
# ---------------------------------------------------------------------------

_STANDARD_SENTINEL = b"\xff\xff\xff\xff"


def _read_utf16le_boundary(raw: bytes, offset: int) -> tuple[str, int]:
    """Read a null-terminated UTF-16LE string that starts at *offset* in *raw*.

    Return ``(string, pos_after_null)``.  Raise ``ValueError`` if the string has no
    terminator within *raw*.
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
    """Convert a verbose tagged-field list to the tag dicts that the program-file decoder builds.

    A program file (``Scr*.tmp``) writes some values differently from the clipboard.
    This function converts the clipboard's values to the program file's:

    * **Flag tags** (``0x11xx``/``0x12xx``): clipboard value ``"-1"``
      or ``"1"`` → present in *tags*; ``"0"`` → absent.  An empty value is
      present too.  CLICK writes ``"-1"``, ``"1"`` or ``"0"``, but a blob
      composed from the tags of a program file writes a set flag as an empty
      value, as the program file does.
    * **Value tags** (byte, u16, string) keep their string value in *tags*.
      Read them with ``binary_helpers.tag_value`` or ``tag_int``.
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
                if value in ("-1", "1", ""):
                    tags[tag] = ""
                # A "0" flag is off, and is left out of tags.
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


def _token_error(
    said: Rule,
    *,
    field: str | None = None,
    reason: Reason = Reason.FORM,
    code: Code = Code.INVALID_TOKEN,
) -> FieldError:
    """Return the error for a raw token that does not follow the token syntax.

    Unless the caller says otherwise, the ``FieldError`` names no field, and its reason is
    ``Reason.FORM``.  The message has no label.
    """
    return make_refusal(FieldError, None, said, field=field, reason=reason, code=code)


def _fromhex(text: str) -> bytes:
    try:
        return bytes.fromhex(text)
    except ValueError:
        raise _token_error(says("{text!r} is not hex bytes", text=text)) from None


def _parse_field_specs(specs: list[str]) -> list[tuple[int, bytes, str]]:
    """Parse field-spec strings back to ``(tag, sentinel, value)`` tuples."""
    fields: list[tuple[int, bytes, str]] = []
    for spec in specs:
        m = _FIELD_SPEC_RE.fullmatch(spec)
        if not m:
            raise _token_error(says("Invalid field spec: {spec!r}", spec=spec))
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
            fields.append((tag, _fromhex(sentinel_hex), value))
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


@dataclass(frozen=True)
class RawInstruction(Instruction):
    """An AF instruction kept as its blob, so that it is written back byte for byte.

    Attributes
    ----------
    class_name:
        The class name in the blob, such as ``"Copy"`` or ``"Cnt"``.  The
        CSV token shows it so that a person can read it.  It is also inside
        *blob*.
    blob:
        Full instruction blob bytes (from cell offset +0x25 to the end
        of tagged fields, excluding tail).
    part_count:
        The number of parts: 1 for a single-row box, more for a multi-row
        box.  The clipboard decoder reads it from the blob.  So does the CSV
        reader for the hex form of the token, which uses 1 if the blob does
        not parse.  The program file decoder counts the part rows of the
        entry, and the CSV reader takes it from the decoded-fields form of
        the token.  Each of those two builds the blob with that count.
    rows, sub:
        The row bytes of the box's cell header.  ``rows`` is the row span
        (+0x09), and ``sub`` is the sub-rows (+0x0A).  The decoders keep the
        bytes of the cell that CLICK wrote.  They leave a box raw when its
        stored row span is not the height of the typed instruction.  If
        ``rows`` is None, the box takes its height from its class name and
        its blob.  If the blob alone gives the height of the typed family,
        the box takes that height: the Copy family, Search, Send, Receive,
        Out variants, and 3 rows for Email, Home, Position and Velocity.
        Otherwise the box ends one row below the row of its last
        part, as the extra part bytes of the blob give it.  A 1-part box is 1
        row.  Boxes made in CLICK's editor may store other sub-rows: Math
        ``01 03``, some Search ``02 03``, Tmr ``02 03``, Drum ``04 05``, SR
        ``03 02``.  For those classes CLICK keeps the height that laddercodec
        writes.  If ``rows`` is set and ``sub`` is None, the sub-rows equal
        the row span.  The CSV token holds the two bytes that the box encodes
        (``rows=``, ``sub=``).  For a box of 2 or more parts, it also holds
        the extra part bytes (``pins=``).  Two boxes are equal when they
        encode the same bytes, even if one has ``None`` and the other states
        the height that ``None`` gives.
    """

    class_name: str
    blob: bytes
    part_count: int = 1
    rows: int | None = None
    sub: int | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RawInstruction):
            return NotImplemented
        return (self.class_name, self.blob, self.part_count, self._cell_rows()) == (
            other.class_name,
            other.blob,
            other.part_count,
            other._cell_rows(),
        )

    def __hash__(self) -> int:
        # Hash what __eq__ compares, so that two equal boxes hash equal even if only one
        # of them states its height.
        return hash((self.class_name, self.blob, self.part_count, self._cell_rows()))

    def _cell_rows(self) -> tuple[int, int]:
        """Return the row span (+0x09) and sub-rows (+0x0A) that this box encodes."""
        params = self.cell_params()
        span = int(params.get("visual_rows", 1))
        return span, int(params.get("sub_rows", span))

    def __post_init__(self) -> None:
        # A decoded blob can hold any class name and any 16-bit part count.  The checks here
        # refuse a value of the wrong type, a part count outside 0 to 65535, and a row span or
        # sub-rows outside 1 to 255.
        with Refusals(self) as check:
            if not isinstance(self.class_name, str):
                check.refuse(
                    "class_name",
                    says("{class_name!r} is not text", class_name=self.class_name),
                    Reason.FORM,
                    code=Code.INVALID_RAW,
                )
            if not isinstance(self.blob, bytes):
                check.refuse(
                    "blob",
                    says("{kind} is not bytes", kind=type(self.blob).__name__),
                    Reason.FORM,
                    code=Code.INVALID_RAW,
                )
            part_count = self.part_count
            if type(part_count) is not int:
                check.refuse(
                    "part_count",
                    says(
                        "{part_count!r} is not a whole number from 0 to 65535",
                        part_count=part_count,
                    ),
                    Reason.FORM,
                    code=Code.INVALID_RAW,
                )
            elif not 0 <= part_count <= 0xFFFF:
                check.refuse(
                    "part_count",
                    says(
                        "{part_count!r} is not a whole number from 0 to 65535",
                        part_count=part_count,
                    ),
                    Reason.RANGE,
                    code=Code.INVALID_RAW,
                )
            for name in ("rows", "sub"):
                rows = getattr(self, name)
                if rows is None:
                    continue
                rule = says("{rows!r} is not a whole number from 1 to 255", rows=rows)
                if type(rows) is not int:
                    check.refuse(name, rule, Reason.FORM, code=Code.INVALID_RAW)
                elif not 1 <= rows <= 0xFF:
                    check.refuse(name, rule, Reason.RANGE, code=Code.INVALID_RAW)

    def cell_params(self) -> dict:
        """Return ClickCell kwargs intrinsic to this instruction."""
        if self.rows is None:
            params = self._class_cell_params()
            span = int(params.get("visual_rows", 1))
            sub = int(params.get("sub_rows", span)) if self.sub is None else self.sub
        else:
            span = self.rows
            sub = span if self.sub is None else self.sub
        if span == sub == 1:
            return {}
        return {"visual_rows": span} if sub == span else {"visual_rows": span, "sub_rows": sub}

    def _class_cell_params(self) -> dict:
        """Return the cell kwargs for the height of this box's class, used when ``rows`` is None.

        The first family whose ``cell_params_from_tags`` hook recognises the blob gives
        the height.  Any other box, the boxes of the pinned families among them, ends one
        row below the row of its last part.  If its part bytes are not valid pin rows, or
        the blob does not parse, the box spans ``part_count`` rows.
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
        """Return the row of each later part, counted from the main row.

        These rows are the part bytes of the blob.  Return an empty tuple for a 1-part box,
        when the blob does not parse, and when the part bytes are not one ascending row
        from 1 to 31 for each later part.
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
        """Return the decoded-fields token ``raw(ClassName,0xTTTT,N,rows=R,sub=S,...)``.

        ``rows`` and ``sub`` are the cell bytes that the box encodes (+0x09, +0x0A).  A
        box of 2 or more parts adds ``pins=``, its extra part bytes.

        The method returns the hex form, with ``rows`` and ``sub``, in these cases:

        - The blob does not parse into fields.
        - The part bytes are not ascending rows from 1 to 31, or the row span is not one
          more than the last of them.
        - The decoded-fields token does not read back as this box, because it can't hold
          one of the field values.
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
            # The fields form can't state these part bytes or this height.  The hex keeps them.
            return f"raw({self.class_name},{self.blob.hex()},{rows})"
        parts = [cn, f"0x{tm:04x}", str(pc), rows, *([pins] if pins else []), *specs]
        token = f"raw({','.join(parts)})"
        if not self._reads_back(token):
            # The fields form can't hold one of the field values.  The hex keeps it.
            return f"raw({self.class_name},{self.blob.hex()},{rows})"
        return token

    def _reads_back(self, token: str) -> bool:
        """Return True if *token* reads back as this box, with the same bytes and height."""
        from ..csv.ast import AfCall
        from ..csv.token_parser import parse_af_token  # the csv package imports this module

        try:
            # Read the token as the CSV reader does: parse it, then build the box from the
            # token that the parser returns.
            node = parse_af_token(token)
            return isinstance(node, AfCall) and self.from_csv_token(node.to_token()) == self
        except ValueError:
            return False

    @classmethod
    def from_csv_token(cls, token: str) -> RawInstruction:
        """Parse a raw CSV token in the decoded-fields form or the hex form.

        Decoded-fields format::

            raw(ClassName,0xTTTT,N,rows=R,sub=S,pins=P,field_specs...)

        Hex format::

            raw(ClassName,hex_blob,rows=R,sub=S)

        ``rows`` (row span) and ``sub`` (sub-rows) come right after the part count, or
        right after the hex.  Each is optional, and an absent one is None.  If both are
        absent, the box takes its height from its class name and its blob.  If only
        ``sub`` is absent, the sub-rows equal ``rows``.  ``pins`` is the extra part bytes
        joined by ``/``.  It is allowed only in the decoded-fields form, for a box of 2 or
        more parts.  Without it, the part bytes are ``01 02 ...``.  If ``rows`` is given,
        it must be one more than the last pin.
        """
        token = token.strip()
        if not token.startswith("raw(") or not token.endswith(")"):
            raise _token_error(says("Not a raw token: {token!r}", token=token))
        inner = token[4:-1]

        # Split on first comma to get class name.
        if "," not in inner:
            raise _token_error(says("raw({inner}): a raw token is raw(ClassName,...)", inner=inner))
        first_comma = inner.index(",")
        class_name = inner[:first_comma].strip()
        rest = inner[first_comma + 1 :].strip()

        # After the class name, the decoded-fields form starts with 0x.  Anything else is hex.
        if rest.startswith("0x"):
            return cls._from_fields_token(class_name, rest)

        # The hex form.
        hex_blob, *rest_parts = (part.strip() for part in rest.split(","))
        rows, sub, pins, extra = _take_box_rows(class_name, rest_parts, raw_token=True)
        if pins is not None:
            raise _token_error(
                says(
                    "raw({class_name},hex,...): pins={pins} can't follow the hex",
                    "the blob holds the part bytes",
                    class_name=class_name,
                    pins=pins,
                )
            )
        if extra:
            raise _token_error(
                says(
                    "raw({class_name},hex,...): only rows= and sub= may follow the hex, "
                    "not {extra!r}",
                    class_name=class_name,
                    extra=extra[0],
                )
            )
        blob = _fromhex(hex_blob)
        try:
            _, _, part_count = find_blob_boundary(blob)
        except (ValueError, IndexError):
            part_count = 1
        return cls(class_name, blob, part_count, rows, sub)

    @classmethod
    def _from_fields_token(cls, class_name: str, rest: str) -> RawInstruction:
        """Parse decoded-fields format after the class name."""
        parts = _split_raw_args(rest)
        if (
            len(parts) < 2
            or not re.fullmatch(r"(?:0[xX])?[0-9A-Fa-f]+", parts[0])
            or not re.fullmatch(r"[0-9]+", parts[1])
        ):
            raise _token_error(
                says(
                    "raw({class_name},...): type marker is 0xTTTT and part count is digits",
                    class_name=class_name,
                )
            )
        type_marker = int(parts[0], 16)
        part_count = int(parts[1])
        if part_count > 0xFFFF:
            raise _token_error(
                says(
                    "raw({class_name},...): part count {part_count} is not a whole number "
                    "from 0 to 65535",
                    class_name=class_name,
                    part_count=part_count,
                ),
                reason=Reason.RANGE,
            )
        rows, sub, pins, field_specs = _take_box_rows(class_name, parts[2:], raw_token=True)
        extra_bytes = _pin_rows(class_name, part_count, pins)
        if extra_bytes and rows is not None and rows != extra_bytes[-1] + 1:
            stated = "pins=" + pins if pins is not None else "no pins= (rows 1, 2, ...)"
            raise _token_error(
                says(
                    "raw({class_name},...): rows={rows} does not fit {stated}",
                    "the box ends one row below its last pin (rows={last})",
                    class_name=class_name,
                    rows=rows,
                    stated=stated,
                    last=extra_bytes[-1] + 1,
                ),
                field="RawInstruction.rows",
                code=Code.INVALID_RAW,  # the token's rows= and pins= disagree
            )

        fields = _parse_field_specs(field_specs)
        blob = _compose_blob(class_name, type_marker, part_count, extra_bytes, fields)
        return cls(class_name, blob, part_count, rows, sub)


def _take_cell_rows(class_name: str, parts: list[str]) -> tuple[int | None, int | None, list[str]]:
    """Read the leading ``rows=`` and ``sub=`` of a raw token's *parts*.

    Returns ``(rows, sub, remaining parts)``.  An absent field is None.
    A ``pins=`` among the parts raises FieldError (see :func:`_take_box_rows`).
    """
    rows, sub, pins, rest = _take_box_rows(class_name, parts, raw_token=False)
    if pins is not None:
        raise _token_error(
            says(
                "raw({class_name},...): pins= is only for a box of 2 or more parts",
                class_name=class_name,
            )
        )
    return rows, sub, rest


def _take_box_rows(
    class_name: str, parts: list[str], *, raw_token: bool
) -> tuple[int | None, int | None, str | None, list[str]]:
    """Read the leading ``rows=``, ``sub=`` and ``pins=`` of a raw token's *parts*.

    Returns ``(rows, sub, pins text, remaining parts)``.  An absent field is None.
    ``rows`` is at most the number of rows in a rung.  The sub-rows byte can be larger
    than the row span, up to 255.  A Drum that CLICK made stores ``04 05``.

    When *raw_token* is true, the token is a ``raw(...)`` token, and a refused ``rows=``
    or ``sub=`` names the ``RawInstruction`` field.  The token of a typed class has no
    such field, so then the refusal names no field.
    """
    from ..encode import MAX_ROWS

    values: dict[str, int | None] = {"rows": None, "sub": None}
    limits = {"rows": MAX_ROWS, "sub": 0xFF}
    i = 0
    for key in values:
        if i < len(parts) and parts[i].startswith(f"{key}="):
            text = parts[i][len(key) + 1 :]
            digits = text.isascii() and text.isdigit()
            if not (digits and 1 <= int(text) <= limits[key]):
                raise _token_error(
                    says(
                        "raw({class_name},...): {key}={text!r} is not a whole number "
                        "from 1 to {high}",
                        class_name=class_name,
                        key=key,
                        text=text,
                        high=limits[key],
                    ),
                    field=(
                        ("RawInstruction.rows" if key == "rows" else "RawInstruction.sub")
                        if raw_token
                        else None
                    ),
                    # In a raw token, a number out of range has reason RANGE.  Text that is
                    # not a number, or any refusal in a typed class's token, has reason FORM.
                    reason=Reason.RANGE if raw_token and digits else Reason.FORM,
                    code=Code.INVALID_RAW if raw_token else Code.INVALID_TOKEN,
                )
            values[key] = int(text)
            i += 1
    pins = None
    if i < len(parts) and parts[i].startswith("pins="):
        pins = parts[i][len("pins=") :]
        i += 1
    for part in parts[i:]:
        if part.startswith(("rows=", "sub=", "pins=")):
            raise _token_error(
                says(
                    "raw({class_name},...): {part!r} goes right after the part count, "
                    "rows= then sub= then pins=, once each",
                    class_name=class_name,
                    part=part,
                )
            )
    return values["rows"], values["sub"], pins, parts[i:]


def _pin_rows(class_name: str, part_count: int, text: str | None) -> bytes:
    """Return the extra part bytes of a box of *part_count* parts, from a token's ``pins=``.

    Each byte is the row of a later part, counted from the main row.  The rows ascend
    and run from 1 to 31, because a box ends inside a rung.  Without ``pins=``, the
    parts sit on rows 1, 2, and so on.
    """
    want = max(0, part_count - 1)
    if text is None:
        if want > 0xFF:  # a part byte is one byte
            raise _token_error(
                says(
                    "raw({class_name},...): {part_count} parts need pins=, each row 1 to 31",
                    class_name=class_name,
                    part_count=part_count,
                ),
                reason=Reason.RANGE,
            )
        return bytes(range(1, want + 1))
    if want == 0:
        raise _token_error(
            says(
                "raw({class_name},...): pins={text} is only for a box of 2 or more parts, "
                "not {part_count}",
                class_name=class_name,
                text=text,
                part_count=part_count,
            )
        )
    values = text.split("/")
    if len(values) != want:
        raise _token_error(
            says(
                "raw({class_name},...): pins={text} must hold {want} rows, one per part "
                "after the first, joined by /",
                class_name=class_name,
                text=text,
                want=want,
            )
        )
    if not all(v.isascii() and v.isdigit() and 1 <= int(v) <= 31 for v in values):
        raise _token_error(
            says(
                "raw({class_name},...): pins={text} holds a row that is not a whole number "
                "from 1 to 31",
                class_name=class_name,
                text=text,
            )
        )
    rows = [int(v) for v in values]
    if any(later <= earlier for earlier, later in zip(rows, rows[1:], strict=False)):
        raise _token_error(
            says("raw({class_name},...): pins={text} must ascend", class_name=class_name, text=text)
        )
    return bytes(rows)


def _pins_spec(extra_bytes: bytes, part_count: int) -> str | None:
    """Return the ``pins=`` field for *extra_bytes*, or None when a token can't state them.

    Return an empty string for a box of fewer than 2 parts with no extra bytes.
    """
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
        raise _token_error(
            says(
                "raw({class_name},...): rows={rows},sub={sub} is not the {class_name} "
                "box's height (rows={want_rows},sub={want_sub})",
                class_name=class_name,
                rows=got[0],
                sub=got[1],
                want_rows=want[0],
                want_sub=want[1],
            )
        )
    return rest


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> RawInstruction | None:
    """Return None for every blob.

    The raw family recognises no class name.  For a class name that no family
    recognises, the caller builds a ``RawInstruction`` itself.
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
