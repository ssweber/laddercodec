"""Copy family — single copy, block copy, and fill (type marker 0x2721).

Binary class name: ``"Copy"``.

All three variants share the same binary class, discriminated by field[6]:

- ``0`` → single copy (``Copy``)
- ``1`` → block copy (``BlockCopy``)
- ``2`` → fill (``Fill``)

Pack and unpack share the same binary class but are not yet implemented —
they fall back to ``RawInstruction``.

Quirk: the ``to_text_term`` variant (termination checkbox enabled) was
captured with the termination value greyed-out in the Click UI, yet the
binary stores the flag and character code normally.  Round-trip is
byte-exact against the native capture, but the UI behaviour is not fully
understood — the termination encoding may need revisiting.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

from ..model import AfInstruction

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

#: copy_type_idx → func_code string.
COPY_FUNC_CODES: dict[str, str] = {
    "0": "8960",  # single
    "1": "8962",  # block
    "2": "8976",  # fill
    "3": "8978",  # pack
}

#: Reverse lookup.
_FUNC_TO_COPY_TYPE: dict[str, str] = {v: k for k, v in COPY_FUNC_CODES.items()}

# ---------------------------------------------------------------------------
# Conversion type mapping (field[8], verified from Click captures)
# ---------------------------------------------------------------------------

_VALID_FORMATS = frozenset({"none", "value", "text", "binary", "ascii"})

#: field[8] conversion_type → (format, suppress_zero, exponential).
#: Text sub-options are encoded in the conversion_type value itself.
_CONVTYPE_TO_OPTS: dict[str, tuple[str, str, str]] = {
    "0": ("none", "0", "0"),
    "1": ("text", "1", "0"),  # default text: real + suppress zeros
    "2": ("text", "0", "0"),  # real, no suppress zeros
    "4": ("text", "1", "1"),  # exponential + suppress zeros
    "5": ("value", "0", "0"),
    "6": ("ascii", "0", "0"),
    "8": ("binary", "0", "0"),
}

#: Non-text format → field[8] conversion_type.
_FORMAT_TO_CONVTYPE: dict[str, str] = {
    "none": "0",
    "value": "5",
    "ascii": "6",
    "binary": "8",
}

#: Non-text format → field[4] value.
_FORMAT_TO_FIELD4: dict[str, str] = {
    "none": "0",
    "value": "0",
    "ascii": "1",
    "binary": "2",
}

# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

_COPY_TAGS = (
    0x6074,  # [0]  source
    0x6075,  # [1]  source_end (block copy; empty for single)
    0x6076,  # [2]  destination
    0x6077,  # [3]  destination_end (block copy; empty for single)
    0x2206,  # [4]  format_option (0=default, 1=text-modified/ascii, 2=binary)
    0x11F8,  # [5]  oneshot (-1 = enabled)
    0x2223,  # [6]  copy_type_idx (0=single, 1=block, 2=fill, 3=pack)
    0x3218,  # [7]  func_code
    0x2227,  # [8]  conversion_type (0=none, 1-4=text variants, 5=value, 6=ascii, 8=binary)
    0x1221,  # [9]  termination_flag (-1 = termination enabled)
    0x3216,  # [10] termination_char (decimal ASCII code, e.g. 19 = $13)
    0x1201,  # [11] termination_flag2 (-1 = termination enabled)
    0x0000,  # [12] terminator
)

# ---------------------------------------------------------------------------
# Paren-aware helpers
# ---------------------------------------------------------------------------

_CONVERT_CALL_RE = re.compile(r"^to_(text|value|binary|ascii)(?:\((.*)\))?$", re.DOTALL)


def _split_paren_aware(s: str) -> list[str]:
    """Split *s* on commas at parenthesis depth 0 only."""
    parts: list[str] = []
    depth = start = 0
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(s[start:i].strip())
            start = i + 1
    parts.append(s[start:].strip())
    return parts


def _parse_convert_kwarg(raw: str) -> tuple[str, dict[str, str]]:
    """Parse a ``convert=`` kwarg value, returning *(format, text_opts)*.

    Examples: ``to_value``, ``to_text(suppress_zero=0,exponential=1)``.
    """
    m = _CONVERT_CALL_RE.fullmatch(raw.strip())
    if not m:
        raise ValueError(f"Cannot parse convert value: {raw!r}")

    fmt = m.group(1)  # "text", "value", "binary", "ascii"
    inner = (m.group(2) or "").strip()

    if fmt != "text":
        if inner:
            raise ValueError(f"to_{fmt} takes no arguments: {raw!r}")
        return fmt, {}

    # to_text: parse kwargs
    text_opts: dict[str, str] = {}
    if inner:
        for part in inner.split(","):
            part = part.strip()
            if "=" not in part:
                raise ValueError(f"to_text options must be keyword arguments: {raw!r}")
            k, v = part.split("=", 1)
            text_opts[k.strip()] = v.strip()

    return "text", text_opts


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Copy(AfInstruction):
    """A single copy instruction.

    Attributes
    ----------
    source:
        Source operand or literal (e.g. ``"DS7"``, ``"42"``, ``"3.14"``).
    destination:
        Destination operand (e.g. ``"DS8"``).
    format:
        Copy modifier — ``"none"``, ``"value"``, ``"text"``,
        ``"binary"``, or ``"ascii"``.
    oneshot:
        Execute once on OFF→ON transition.
    suppress_zero:
        Text option — ``"0"`` (don't suppress) or ``"1"`` (suppress).
    exponential:
        Text option — ``"0"`` (real) or ``"1"`` (exponential).
    termination_code:
        Text option — ``"0"`` (none) or ``"$HH"`` hex ASCII code
        (e.g. ``"$13"`` for 0x13).
    """

    source: str
    destination: str
    format: str = "none"
    oneshot: bool = False
    suppress_zero: str = "0"
    exponential: str = "0"
    termination_code: str = "0"

    def __post_init__(self) -> None:
        if self.format not in _VALID_FORMATS:
            raise ValueError(f"Invalid copy format: {self.format!r}")

    @classmethod
    def from_csv_token(cls, token: str) -> Copy:
        """Parse ``copy(source, dest)`` with optional ``convert=to_*`` modifier.

        Examples::

            copy(DS7,DS8)
            copy(42,DS9)
            copy(DS26,DS27,oneshot=1)
            copy(TXT1,DS10,convert=to_value)
            copy(DS12,TXT2,convert=to_text(suppress_zero=1,exponential=0,termination_code=none))
        """
        token = token.strip()
        m = re.fullmatch(r"copy\((.+)\)", token)
        if not m:
            raise ValueError(f"Cannot parse copy: {token!r}")

        # Paren-aware split of copy() arguments
        segments = _split_paren_aware(m.group(1))

        args: list[str] = []
        kwargs: dict[str, str] = {}
        for seg in segments:
            eq_pos = seg.find("=")
            if eq_pos >= 0 and "(" not in seg[:eq_pos]:
                k, v = seg.split("=", 1)
                kwargs[k.strip()] = v.strip()
            else:
                args.append(seg)

        if len(args) != 2:
            raise ValueError(
                f"copy expects 2 positional args (source, dest), got {len(args)}: {token!r}"
            )

        source, destination = args

        # Parse convert= kwarg
        convert_raw = kwargs.get("convert", "")
        if convert_raw:
            fmt, text_opts = _parse_convert_kwarg(convert_raw)
        else:
            fmt, text_opts = "none", {}

        oneshot = kwargs.get("oneshot") == "1"

        suppress_zero = text_opts.get("suppress_zero", "0")
        exponential = text_opts.get("exponential", "0")
        termination_code = text_opts.get("termination_code", "0")
        if termination_code == "none":
            termination_code = "0"

        return cls(
            source=source,
            destination=destination,
            format=fmt,
            oneshot=oneshot,
            suppress_zero=suppress_zero,
            exponential=exponential,
            termination_code=termination_code,
        )

    @property
    def func_code(self) -> str:
        base = int(COPY_FUNC_CODES["0"])  # single copy base: 8960
        return str(base + (1 if self.oneshot else 0))

    def to_csv(self) -> str:
        parts = [self.source, self.destination]
        kw: list[str] = []
        if self.oneshot:
            kw.append("oneshot=1")

        if self.format == "text":
            text_kw = [
                f"suppress_zero={self.suppress_zero}",
                f"exponential={self.exponential}",
                f"termination_code={'none' if self.termination_code == '0' else self.termination_code}",
            ]
            kw.append(f"convert=to_text({','.join(text_kw)})")
        elif self.format in ("value", "binary", "ascii"):
            kw.append(f"convert=to_{self.format}")
        elif self.format != "none":
            raise ValueError(f"Unknown format: {self.format!r}")

        if kw:
            return f"copy({','.join(parts)},{','.join(kw)})"
        return f"copy({','.join(parts)})"

    def cell_params(self) -> dict:
        """Return ClickCell kwargs intrinsic to this instruction."""
        return {"visual_rows": 2}

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this copy cell."""
        from ..binary_helpers import _tagged_field, _utf16le_null

        # Compute conversion_type (field[8]) and format_option (field[4]).
        if self.format == "text":
            sz = int(self.suppress_zero)
            exp = int(self.exponential)
            conv_type = str(1 + (1 - sz) + 3 * exp)
            # field[4]: "0" for default text options, "1" if modified
            field4 = "0" if (sz == 1 and exp == 0) else "1"
        else:
            conv_type = _FORMAT_TO_CONVTYPE[self.format]
            field4 = _FORMAT_TO_FIELD4[self.format]

        # Termination encoding: $hex → decimal for field[10], flags for [9]/[11].
        if self.termination_code != "0" and self.termination_code.startswith("$"):
            term_char = str(int(self.termination_code[1:], 16))
            term_flag = "-1"
        else:
            term_char = "0"
            term_flag = "0"

        type_marker = 0x2721
        field_count = 13
        fields = [
            self.source,  # [0]
            "",  # [1] source_end (single = empty)
            self.destination,  # [2]
            "",  # [3] destination_end (single = empty)
            field4,  # [4] format_option
            "-1" if self.oneshot else "0",  # [5]
            "0",  # [6] copy_type_idx (single)
            self.func_code,  # [7]
            conv_type,  # [8] conversion_type
            term_flag,  # [9] termination_flag
            term_char,  # [10] termination_char (decimal)
            term_flag,  # [11] termination_flag2
            "",  # [12] terminator
        ]

        out = bytearray()
        out += _utf16le_null("Copy")
        out += struct.pack("<I", type_marker)
        out += b"\x01\x00"  # part count
        out += struct.pack("<I", field_count)
        for tag, value in zip(_COPY_TAGS, fields, strict=True):
            out += _tagged_field(tag, value)
        return bytes(out)


# ---------------------------------------------------------------------------
# BlockCopy
# ---------------------------------------------------------------------------

#: Formats verified for block copy captures.
_BLOCKCOPY_FORMATS = frozenset({"none", "value", "ascii"})


@dataclass
class BlockCopy(AfInstruction):
    """A block copy instruction (copy_type_idx=1).

    Copies a contiguous range of source registers to a destination range.

    Attributes
    ----------
    source_start, source_end:
        Source range (e.g. ``"DS28"`` .. ``"DS31"``).
    dest_start, dest_end:
        Destination range.
    format:
        ``"none"`` or ``"value"`` (convert to numeric value).
    oneshot:
        Execute once on OFF→ON transition.
    """

    source_start: str
    source_end: str
    dest_start: str
    dest_end: str
    format: str = "none"
    oneshot: bool = False

    def __post_init__(self) -> None:
        if self.format not in _BLOCKCOPY_FORMATS:
            raise ValueError(f"Invalid blockcopy format: {self.format!r}")

    @property
    def func_code(self) -> str:
        base = int(COPY_FUNC_CODES["1"])  # block copy base: 8962
        return str(base + (1 if self.oneshot else 0))

    def to_csv(self) -> str:
        src = f"{self.source_start}..{self.source_end}"
        dst = f"{self.dest_start}..{self.dest_end}"
        parts = [src, dst]
        kw: list[str] = []
        if self.oneshot:
            kw.append("oneshot=1")
        if self.format != "none":
            kw.append(f"convert=to_{self.format}")
        if kw:
            return f"blockcopy({','.join(parts)},{','.join(kw)})"
        return f"blockcopy({','.join(parts)})"

    def cell_params(self) -> dict:
        """Return ClickCell kwargs intrinsic to this instruction."""
        return {"visual_rows": 2}

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this block copy cell."""
        from ..binary_helpers import _tagged_field, _utf16le_null

        conv_type = _FORMAT_TO_CONVTYPE.get(self.format, "0")

        type_marker = 0x2721
        field_count = 13
        fields = [
            self.source_start,  # [0]
            self.source_end,  # [1]
            self.dest_start,  # [2]
            self.dest_end,  # [3]
            "0",  # [4] format_option
            "-1" if self.oneshot else "0",  # [5]
            "1",  # [6] copy_type_idx (block)
            self.func_code,  # [7]
            conv_type,  # [8] conversion_type
            "0",  # [9] termination_flag
            "0",  # [10] termination_char
            "0",  # [11] termination_flag2
            "",  # [12] terminator
        ]

        out = bytearray()
        out += _utf16le_null("Copy")
        out += struct.pack("<I", type_marker)
        out += b"\x01\x00"  # part count
        out += struct.pack("<I", field_count)
        for tag, value in zip(_COPY_TAGS, fields, strict=True):
            out += _tagged_field(tag, value)
        return bytes(out)


# ---------------------------------------------------------------------------
# Fill
# ---------------------------------------------------------------------------


@dataclass
class Fill(AfInstruction):
    """A fill instruction (copy_type_idx=2).

    Fills a contiguous range of destination registers with a single value.

    Attributes
    ----------
    value:
        Source value — literal (``"0"``) or tag (``"DS56"``).
    dest_start, dest_end:
        Destination range.
    oneshot:
        Execute once on OFF→ON transition.
    """

    value: str
    dest_start: str
    dest_end: str
    oneshot: bool = False

    @property
    def func_code(self) -> str:
        base = int(COPY_FUNC_CODES["2"])  # fill base: 8976
        return str(base + (1 if self.oneshot else 0))

    def to_csv(self) -> str:
        parts = [self.value, f"{self.dest_start}..{self.dest_end}"]
        kw: list[str] = []
        if self.oneshot:
            kw.append("oneshot=1")
        if kw:
            return f"fill({','.join(parts)},{','.join(kw)})"
        return f"fill({','.join(parts)})"

    def cell_params(self) -> dict:
        """Return ClickCell kwargs intrinsic to this instruction."""
        return {"visual_rows": 2}

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this fill cell."""
        from ..binary_helpers import _tagged_field, _utf16le_null

        type_marker = 0x2721
        field_count = 13
        fields = [
            self.value,  # [0]
            "",  # [1] source_end (fill = empty)
            self.dest_start,  # [2]
            self.dest_end,  # [3]
            "0",  # [4] format_option
            "-1" if self.oneshot else "0",  # [5]
            "2",  # [6] copy_type_idx (fill)
            self.func_code,  # [7]
            "0",  # [8] conversion_type
            "0",  # [9] termination_flag
            "0",  # [10] termination_char
            "0",  # [11] termination_flag2
            "",  # [12] terminator
        ]

        out = bytearray()
        out += _utf16le_null("Copy")
        out += struct.pack("<I", type_marker)
        out += b"\x01\x00"  # part count
        out += struct.pack("<I", field_count)
        for tag, value in zip(_COPY_TAGS, fields, strict=True):
            out += _tagged_field(tag, value)
        return bytes(out)


# Module-level wrapper for backward compatibility.
def build_blob(copy: Copy) -> bytes:
    """Build the instruction data blob for a copy cell."""
    return copy.build_blob()


# ---------------------------------------------------------------------------
# Blob parser
# ---------------------------------------------------------------------------


def parse_blob(raw: bytes) -> Copy | BlockCopy | Fill | None:
    """Try to parse a Copy-family instruction from an instruction blob.

    Handles single copy (0), block copy (1), and fill (2).
    Pack (3) and other variants return None → RawInstruction fallback.
    """
    from ..binary_helpers import _parse_tagged_fields, _read_utf16le

    class_name, pos = _read_utf16le(raw, 0)
    if class_name != "Copy":
        return None
    if pos + 10 > len(raw):
        return None

    pos += 4  # skip type marker
    pos += 2  # skip part count (01 00)
    field_count = int.from_bytes(raw[pos : pos + 4], "little")
    pos += 4

    fields = _parse_tagged_fields(raw, pos, field_count)
    if len(fields) < 12:
        return None

    copy_type_idx = fields[6]

    if copy_type_idx == "0":
        # --- Single copy ---
        conv_type = fields[8]
        opts = _CONVTYPE_TO_OPTS.get(conv_type)
        if opts is None:
            return None
        fmt, suppress_zero, exponential = opts

        if fields[9] == "-1":
            term_decimal = int(fields[10])
            termination_code = f"${term_decimal:X}"
        else:
            termination_code = "0"

        return Copy(
            source=fields[0],
            destination=fields[2],
            format=fmt,
            oneshot=fields[5] == "-1",
            suppress_zero=suppress_zero,
            exponential=exponential,
            termination_code=termination_code,
        )

    if copy_type_idx == "1":
        # --- Block copy ---
        conv_type = fields[8]
        opts = _CONVTYPE_TO_OPTS.get(conv_type)
        if opts is None:
            return None
        fmt = opts[0]  # only the format name; no text sub-options
        if fmt not in _BLOCKCOPY_FORMATS:
            return None

        return BlockCopy(
            source_start=fields[0],
            source_end=fields[1],
            dest_start=fields[2],
            dest_end=fields[3],
            format=fmt,
            oneshot=fields[5] == "-1",
        )

    if copy_type_idx == "2":
        # --- Fill ---
        return Fill(
            value=fields[0],
            dest_start=fields[2],
            dest_end=fields[3],
            oneshot=fields[5] == "-1",
        )

    return None
