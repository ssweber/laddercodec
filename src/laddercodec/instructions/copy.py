"""Copy family — single copy, block copy, fill, pack, and unpack (type marker 0x2721).

Binary class name: ``"Copy"``.

All five variants share the same binary class, discriminated by field[6]:

- ``0`` → single copy (``Copy``)
- ``1`` → block copy (``BlockCopy``)
- ``2`` → fill (``Fill``)
- ``3`` → pack (``Pack``)
- ``4`` → unpack (``Unpack``)

Quirk: the ``to_text_term`` variant (termination checkbox enabled) was
captured with the termination value greyed-out in the Click UI, yet the
binary stores the flag and character code normally.  Round-trip is
byte-exact against the native capture, but the UI behaviour is not fully
understood — the termination encoding may need revisiting.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

from ..binary_helpers import tag_flag, tag_int, tag_value
from ..model import (
    ADDRESS_BANKS,
    Address,
    AddressError,
    AfInstruction,
    FieldError,
    check_address,
)
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

#: copy_type_idx → func_code string.
COPY_FUNC_CODES: dict[str, str] = {
    "0": "8960",  # single
    "1": "8962",  # block
    "2": "8976",  # fill
    "3": "8978",  # pack
    "4": "8980",  # unpack
}

#: Reverse lookup.
_FUNC_TO_COPY_TYPE: dict[str, str] = {v: k for k, v in COPY_FUNC_CODES.items()}

# ---------------------------------------------------------------------------
# Conversion type mapping (field[8], verified from Click captures)
# ---------------------------------------------------------------------------

_VALID_FORMATS = frozenset({"none", "value", "text", "binary", "ascii"})

#: field[8] conversion_type → (format, suppress_zero, exponential).
#: Text sub-options are encoded in the conversion_type value itself: an integer
#: source has suppress zero (1) or not (2); a DF source has real (3) or
#: exponential (4) numbering, with suppress_zero stored as 1.  7 is a DD <-> DF
#: Copy Value, a plain copy in CSV (InstCtl_Copy.dll, v4_captures/sweep_copy.bin).
_CONVTYPE_TO_OPTS: dict[str, tuple[str, str, str]] = {
    "0": ("none", "0", "0"),
    "1": ("text", "1", "0"),  # integer source, suppress zeros
    "2": ("text", "0", "0"),  # integer source, don't suppress zeros
    "3": ("text", "1", "0"),  # DF source, real numbering
    "4": ("text", "1", "1"),  # DF source, exponential numbering
    "5": ("value", "0", "0"),
    "6": ("ascii", "0", "0"),
    "7": ("none", "0", "0"),  # DD <-> DF
    "8": ("binary", "0", "0"),
}

_DF_RE = re.compile(r"DF\d+")
_DD_RE = re.compile(r"DD\d+")


def _is_df(operand: str) -> bool:
    return _DF_RE.fullmatch(operand.strip()) is not None


def _is_dd_df_pair(source: str, destination: str) -> bool:
    """A single copy between DD and DF, either way: CLICK's Copy Value / Copy Binary choice."""
    src, dst = source.strip(), destination.strip()
    return (_DD_RE.fullmatch(src) is not None and _is_df(dst)) or (
        _is_df(src) and _DD_RE.fullmatch(dst) is not None
    )


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
    0x1201,  # [11] text_flag (-1 = text constant source or termination enabled)
    0x0000,  # [12] terminator
)

#: An ASCII-code constant, e.g. ``$00`` (CLICK's spelling of one character by code).
_ASCII_CODE_CONSTANT_RE = re.compile(r"\$[0-9A-Fa-f]{2}")


def _is_text_constant(operand: str) -> bool:
    """True for a quoted text constant (``"Q"``) or an ASCII-code constant (``$00``)."""
    operand = operand.strip()
    return operand.startswith('"') or _ASCII_CODE_CONSTANT_RE.fullmatch(operand) is not None


def _ascii_code(code: int) -> str:
    """Spell a character code the way CLICK and pyrung do: ``$`` + two hex digits (``$0D``)."""
    if not 0 <= code <= 0xFF:
        raise FieldError(f"ASCII code out of range 0..0xFF: {code}")
    return f"${code:02X}"


# ---------------------------------------------------------------------------
# Operands and banks (CLICK v4.00 Help CL173 Single Copy, CL185 Fill, CL238 Pointers)
# ---------------------------------------------------------------------------

#: Bit banks: the "Bits" rows of the Help copy tables.
BIT_BANKS = frozenset({"X", "Y", "C", "T", "CT", "SC"})
#: Registers a copy reads: the "Registers" rows.
REGISTER_BANKS = frozenset({"DS", "DD", "DH", "DF", "XD", "YD", "TD", "CTD", "SD", "TXT"})
#: Registers that hold a number.
NUMERIC_BANKS = REGISTER_BANKS - {"TXT"}
#: Registers a copy writes: every register but XD.
_REGISTER_DEST_BANKS = REGISTER_BANKS - {"XD"}
_NUMERIC_DEST_BANKS = _REGISTER_DEST_BANKS - {"TXT"}
_COPY_DEST_BANKS = _REGISTER_DEST_BANKS | {"Y", "C"}

_POINTER_RE = re.compile(r"([A-Z]{1,3})\[(.*)\]")
#: A number constant (Help CL196): integer or real (``42``, ``-1.5``, ``1.0E+04``), or hex
#: digits then ``h`` (``1Eh``).  The sign, exponent and letter case are not narrowed.
_NUMBER_CONSTANT_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|[+-]?[0-9A-Fa-f]+[hH]")
#: A text constant by character code: ``$`` then hex digits (``$0D``); how many CLICK takes
#: is not narrowed here.
_ASCII_CODE_OPERAND_RE = re.compile(r"\$[0-9A-Fa-f]+")


class Operand(NamedTuple):
    """A checked operand.

    ``kind`` is ``"bit"``, ``"word"`` (a numeric register), ``"txt"`` (a TXT register),
    ``"number"`` or ``"text"`` (constants).  ``bank`` is ``None`` for a constant; for a
    pointer ``DD[DS1]`` it is the pointed-to bank (``DD``).
    """

    kind: str
    bank: str | None = None
    pointer: bool = False


#: How each operand kind reads in a message.
_KIND_TEXT = {
    "bit": "a bit",
    "word": "a numeric register",
    "txt": "a TXT register",
    "number": "a number constant",
    "text": "a text constant",
}


def _bank_prefix(operand: str) -> str:
    """The bank letters an address starts with (``CTD`` for ``CTD5``), checked or not."""
    m = re.match(r"[A-Z]*", operand)
    return m.group(0) if m else ""


def _bank_list(banks: Collection[str]) -> str:
    return ", ".join(b for b in ADDRESS_BANKS if b in banks)


def _register_kind(bank: str) -> str:
    if bank in BIT_BANKS:
        return "bit"
    return "txt" if bank == "TXT" else "word"


def check_operand(
    value: str,
    name: str,
    banks: Collection[str] | None = None,
    *,
    constant: bool = False,
    pointer: bool = False,
) -> Operand:
    """Check one operand; raise :class:`AddressError` naming field ``name`` if CLICK refuses it.

    An address goes through :func:`check_address`, narrowed to ``banks`` (``None``: any bank).
    With ``constant``, a number constant (``42``, ``-1.5``, ``1Eh``) or a text constant
    (``"AB"``, ``$0D``) passes too.  With ``pointer``, ``BANK[DSn]`` passes: ``BANK`` must be
    in ``banks`` and the pointer a DS address (Help CL238).
    """
    if constant:
        if (len(value) >= 2 and value[0] == value[-1] == '"') or (
            _ASCII_CODE_OPERAND_RE.fullmatch(value)
        ):
            return Operand("text")
        if _NUMBER_CONSTANT_RE.fullmatch(value):
            return Operand("number")
    m = _POINTER_RE.fullmatch(value)
    if m is not None:
        if not pointer:
            raise AddressError(f"{name}: {value!r} is a pointer; only a single Copy takes one")
        bank = m.group(1)
        allowed = ADDRESS_BANKS if banks is None else banks
        if bank not in allowed:
            raise AddressError(
                f"{name}: {value!r} is not allowed; {name} takes {_bank_list(allowed)}"
            )
        check_address(m.group(2), f"{name} pointer", {"DS"})
        return Operand(_register_kind(bank), bank, pointer=True)
    address = check_address(value, name, banks)
    return Operand(_register_kind(address.bank), address.bank)


def _span(first: Address, last: Address) -> int | None:
    """Addresses from ``first`` to ``last`` in one bank; ``None`` for XD/YD.

    How CLICK counts across ``XD0u`` is not checked, so XD/YD ranges get no count.
    """
    if first.bank in ("XD", "YD"):
        return None
    return last.number - first.number + 1


def _check_range(
    cls: str,
    start_field: str,
    start: str,
    end_field: str,
    end: str,
    banks: Collection[str] | None = None,
    *,
    one_module: bool = False,
) -> tuple[Address, Address]:
    """Check a ``start..end`` range and return its two ends.

    Both ends are addresses in one bank (OBJ-008), never pointers.  With ``one_module``, an X
    or Y range stays inside one 16-point module (OBJ-033, OBJ-035, OBJ-019).
    """
    ends = []
    for field_name, value in ((start_field, start), (end_field, end)):
        name = f"{cls}.{field_name}"
        if _POINTER_RE.fullmatch(value):
            raise AddressError(f"{name}: {value!r} is a pointer; only a single Copy takes one")
        ends.append(check_address(value, name, banks))
    first, last = ends
    if first.bank != last.bank:
        raise AddressError(
            f"{cls}.{end_field}: {end!r} is not in the bank of {start!r}; "
            "both ends of a range are in one bank"
        )
    if one_module and first.bank in ("X", "Y") and first.number // 100 != last.number // 100:
        raise AddressError(
            f"{cls}.{end_field}: {start}..{end} spans two {first.bank} modules; "
            "the range stays inside one 16-point module"
        )
    return first, last


def _check_pair(
    cls: str,
    source: str,
    src: Operand,
    dest_field: str,
    destination: str,
    dest_bank: str,
    pairs: dict[str, frozenset[str]],
) -> None:
    """Refuse a destination bank the source kind can't copy into (OBJ-024)."""
    allowed = pairs[src.kind]
    if dest_bank not in allowed:
        raise AddressError(
            f"{cls}.{dest_field}: {destination!r} can't take {source!r}; "
            f"{_KIND_TEXT[src.kind]} copies to {_bank_list(allowed)}"
        )


def _check_kind(cls: str, field_name: str, value: str, bank: str, kind: str) -> None:
    """Pack/unpack ``bits`` takes a bit range and ``words`` a register range.

    The blob stores no bits/words flag; the decoder reads it from this bank.
    """
    if (kind == "bits") != (bank in BIT_BANKS):
        what = "a register" if kind == "bits" else "a bit"
        need = f"a bit bank ({_bank_list(BIT_BANKS)})" if kind == "bits" else "a register bank"
        raise AddressError(f"{cls}.{field_name}: {value!r} is {what}; {kind} needs {need}")


#: Most bits one register packs into or unpacks from (OBJ-027/041, OBJ-032/039).
_BITS_PER_REGISTER = {"DS": 16, "DH": 16, "DD": 32, "DF": 32}
#: Most words one pack or unpack moves (OBJ-040, OBJ-042).
_MAX_WORDS = 2


def _check_count(
    cls: str,
    end_field: str,
    span_text: str,
    count: int | None,
    kind: str,
    bank: str | None,
    single: str,
) -> None:
    """Refuse a pack source or unpack destination longer than the single register holds."""
    limit = _BITS_PER_REGISTER.get(bank or "") if kind == "bits" else _MAX_WORDS
    if limit is not None and count is not None and count > limit:
        unit = "bits" if kind == "bits" else "words"
        verb = "a pack into" if cls == "Pack" else "an unpack from"
        raise FieldError(
            f"{cls}.{end_field}: {span_text} is {count} {unit}; "
            f"{verb} {single!r} takes at most {limit}"
        )


#: Help CL173: source kind -> destination banks of a single Copy.
_COPY_PAIRS: dict[str, frozenset[str]] = {
    "bit": frozenset({"Y", "C"}),
    "word": _REGISTER_DEST_BANKS,
    "txt": _REGISTER_DEST_BANKS,
    "number": _REGISTER_DEST_BANKS,
    "text": frozenset({"TXT"}),
}

#: Help CL185: source kind -> destination banks of a Fill.
_FILL_PAIRS: dict[str, frozenset[str]] = {
    "word": _NUMERIC_DEST_BANKS,
    "txt": frozenset({"TXT"}),
    "number": _REGISTER_DEST_BANKS,
    "text": frozenset({"TXT"}),
}


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

    Examples: ``to_value``, ``to_text(exponential=1)``.
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


def _parse_range(arg: str) -> tuple[str, str]:
    """Split ``"A..B"`` into ``("A", "B")``."""
    if ".." not in arg:
        raise ValueError(f"Expected range with '..': {arg!r}")
    parts = [p.strip() for p in arg.split("..")]
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"Cannot parse range: {arg!r}")
    return parts[0], parts[1]


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
        Text option for an integer source — ``"0"`` (don't suppress) or
        ``"1"`` (suppress).  A DF source has no such option; it reads ``"1"``.
    exponential:
        Text option for a DF source — ``"0"`` (real) or ``"1"`` (exponential).
        An integer source has no such option and rejects ``"1"``.
    termination_code:
        Text option — ``"0"`` (none) or ``"$HH"`` hex ASCII code, always
        two digits (``"$0D"`` for 0x0D; ``"$D"`` is accepted and stored as ``"$0D"``).
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
            raise FieldError(f"Invalid copy format: {self.format!r}")
        # One spelling per code, whichever way it came in ($D from CSV, 13 from a blob).
        if self.termination_code.startswith("$"):
            try:
                code = int(self.termination_code[1:], 16)
            except ValueError:
                raise FieldError(f"Invalid termination code: {self.termination_code!r}") from None
            self.termination_code = _ascii_code(code)
        src = check_operand(
            self.source, "Copy.source", BIT_BANKS | REGISTER_BANKS, constant=True, pointer=True
        )
        dst = check_operand(self.destination, "Copy.destination", _COPY_DEST_BANKS, pointer=True)
        assert dst.bank is not None
        _check_pair(
            "Copy", self.source, src, "destination", self.destination, dst.bank, _COPY_PAIRS
        )
        self._check_format(src, dst.bank)
        if self.termination_code != "0" and not (
            self.format in ("text", "binary") and src.kind == "word" and dst.bank == "TXT"
        ):
            # CLICK v4's dialog: termination is for a single copy from a number register to
            # text; the box is greyed for TXT -> TXT and constant -> TXT.
            raise FieldError(
                f"Copy.termination_code: {self.termination_code!r} needs a numeric register "
                f"copied to TXT with to_text or to_binary, not {self.source!r} -> "
                f"{self.destination!r} with format {self.format!r}"
            )
        if self.format == "text":
            # CLICK's dialog offers suppress zero for an integer source and
            # real/exponential for a DF source, never both.
            if _is_df(self.source):
                self.suppress_zero = "1"  # what CLICK stores; not a setting
            elif self.exponential == "1":
                raise FieldError(
                    f"to_text(exponential=1) needs a DF source, not {self.source!r}; "
                    "an integer source only has suppress_zero"
                )

    def _check_format(self, src: Operand, dest_bank: str) -> None:
        """Refuse a converter the source and destination kinds don't offer."""
        fmt = self.format
        if fmt == "binary" and _is_dd_df_pair(self.source, self.destination):
            return  # DD <-> DF Copy Binary (v4_captures/sweep_copy.bin)
        if fmt in ("text", "binary"):
            ok, need = src.kind in ("word", "number") and dest_bank == "TXT", "a number to TXT"
        elif fmt in ("value", "ascii"):
            ok, need = src.kind == "txt" and dest_bank in _NUMERIC_DEST_BANKS, "TXT to a number"
        else:
            return
        if not ok:
            raise FieldError(
                f"Copy.format: to_{fmt} copies {need}, not {self.source!r} -> {self.destination!r}"
            )

    @classmethod
    def from_csv_token(cls, token: str) -> Copy:
        """Parse ``copy(source, dest)`` with optional ``convert=to_*`` modifier.

        Examples::

            copy(DS7,DS8)
            copy(42,DS9)
            copy(DS26,DS27,oneshot=1)
            copy(TXT1,DS10,convert=to_value)
            copy(DS12,TXT2,convert=to_text(suppress_zero=1,termination_code=none))
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
        return _copy_from_csv(args, kwargs)

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
            # Only the option the source has (pyrung's exporter writes the same).
            option = (
                f"exponential={self.exponential}"
                if _is_df(self.source)
                else f"suppress_zero={self.suppress_zero}"
            )
            text_kw = [
                option,
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
        from ..binary_helpers import _build_blob

        # Compute conversion_type (field[8]) and format_option (field[4]).
        # field[4] is the dialog's radio index; CLICK v4 ignores it on load.
        if self.format == "text":
            if _is_df(self.source):
                exp = int(self.exponential)
                conv_type, field4 = str(3 + exp), str(exp)
            else:
                sz = int(self.suppress_zero)
                conv_type, field4 = str(2 - sz), str(1 - sz)
        elif _is_dd_df_pair(self.source, self.destination) and self.format in ("none", "binary"):
            conv_type, field4 = ("7", "0") if self.format == "none" else ("8", "1")
        else:
            conv_type = _FORMAT_TO_CONVTYPE[self.format]
            field4 = _FORMAT_TO_FIELD4[self.format]

        # Termination encoding: $hex → decimal for field[10], flag for [9].
        if self.termination_code != "0" and self.termination_code.startswith("$"):
            term_char = str(int(self.termination_code[1:], 16))
            term_flag = "-1"
        else:
            term_char = "0"
            term_flag = "0"
        # field[11]: CLICK v4's dialog writes -1 on every save and ignores it on
        # load (InstCtl_Copy.dll); pre-v4 captures set it only for a termination
        # code.  We write -1 for those and for a text constant source, the cases
        # native captures we match byte for byte show.
        text_flag = "-1" if term_flag == "-1" or _is_text_constant(self.source) else "0"

        return _build_blob(
            "Copy",
            0x2721,
            _COPY_TAGS,
            [
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
                text_flag,  # [11] text_flag
                "",  # [12] terminator
            ],
        )


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
            raise FieldError(f"Invalid blockcopy format: {self.format!r}")
        # Bank pairs wait on a dialog check; only the addresses and ranges are checked.
        cls = "BlockCopy"
        src, _ = _check_range(cls, "source_start", self.source_start, "source_end", self.source_end)
        dest, _ = _check_range(cls, "dest_start", self.dest_start, "dest_end", self.dest_end)
        if self.format != "none" and src.bank != "TXT":
            raise FieldError(
                f"{cls}.format: to_{self.format} needs a TXT source, not "
                f"{self.source_start}..{self.source_end}"
            )

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
        from ..binary_helpers import _build_blob

        conv_type = _FORMAT_TO_CONVTYPE.get(self.format, "0")

        return _build_blob(
            "Copy",
            0x2721,
            _COPY_TAGS,
            [
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
                "0",  # [11] text_flag
                "",  # [12] terminator
            ],
        )


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

    def __post_init__(self) -> None:
        src = check_operand(self.value, "Fill.value", REGISTER_BANKS, constant=True)
        dest, _ = _check_range(
            "Fill", "dest_start", self.dest_start, "dest_end", self.dest_end, _REGISTER_DEST_BANKS
        )
        _check_pair("Fill", self.value, src, "dest_start", self.dest_start, dest.bank, _FILL_PAIRS)

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
        from ..binary_helpers import _build_blob

        return _build_blob(
            "Copy",
            0x2721,
            _COPY_TAGS,
            [
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
                "0",  # [11] text_flag (no capture of a Fill with a text constant yet)
                "",  # [12] terminator
            ],
        )


# ---------------------------------------------------------------------------
# Pack
# ---------------------------------------------------------------------------

#: Pack sub-type names and their CSV token names.
_PACK_TYPES = frozenset({"bits", "words", "text"})

#: field[8] conversion_type values for pack_text.
_PACK_TEXT_CONVTYPE = {"default": "9", "allow_whitespace": "10"}


@dataclass
class Pack(AfInstruction):
    """A pack instruction (copy_type_idx=3).

    Packs a range of source registers into a single destination.

    Attributes
    ----------
    source_start, source_end:
        Source range (e.g. ``"C108"`` .. ``"C123"``).
    destination:
        Destination operand (e.g. ``"DS167"``).
    pack_type:
        ``"bits"``, ``"words"``, or ``"text"``.
    allow_whitespace:
        Text option — allow whitespace in text packing.
    oneshot:
        Execute once on OFF→ON transition.
    """

    source_start: str
    source_end: str
    destination: str
    pack_type: str = "bits"
    allow_whitespace: bool = False
    oneshot: bool = False

    def __post_init__(self) -> None:
        if self.pack_type not in _PACK_TYPES:
            raise FieldError(f"Invalid pack type: {self.pack_type!r}")
        # Bank pairs wait on a dialog check; only the addresses, ranges and counts are checked.
        first, last = _check_range(
            "Pack", "source_start", self.source_start, "source_end", self.source_end,
            one_module=True,
        )  # fmt: skip
        dest = check_operand(self.destination, "Pack.destination")
        if self.pack_type == "text":
            return
        _check_kind("Pack", "source_start", self.source_start, first.bank, self.pack_type)
        _check_count(
            "Pack", "source_end", f"{self.source_start}..{self.source_end}", _span(first, last),
            self.pack_type, dest.bank, self.destination,
        )  # fmt: skip

    @property
    def func_code(self) -> str:
        base = int(COPY_FUNC_CODES["3"])  # pack base: 8978
        return str(base + (1 if self.oneshot else 0))

    def to_csv(self) -> str:
        src = f"{self.source_start}..{self.source_end}"
        parts = [src, self.destination]
        kw: list[str] = []
        if self.oneshot:
            kw.append("oneshot=1")
        if self.allow_whitespace:
            kw.append("allow_whitespace=1")
        if kw:
            return f"pack_{self.pack_type}({','.join(parts)},{','.join(kw)})"
        return f"pack_{self.pack_type}({','.join(parts)})"

    def cell_params(self) -> dict:
        return {"visual_rows": 2}

    def build_blob(self) -> bytes:
        from ..binary_helpers import _build_blob

        if self.pack_type == "text":
            if self.allow_whitespace:
                conv_type = _PACK_TEXT_CONVTYPE["allow_whitespace"]
                field4 = "1"
            else:
                conv_type = _PACK_TEXT_CONVTYPE["default"]
                field4 = "0"
        else:
            conv_type = "0"
            field4 = "0"

        return _build_blob(
            "Copy",
            0x2721,
            _COPY_TAGS,
            [
                self.source_start,  # [0]
                self.source_end,  # [1]
                self.destination,  # [2]
                "",  # [3] destination_end (pack = empty)
                field4,  # [4] format_option
                "-1" if self.oneshot else "0",  # [5]
                "3",  # [6] copy_type_idx (pack)
                self.func_code,  # [7]
                conv_type,  # [8] conversion_type
                "0",  # [9] termination_flag
                "0",  # [10] termination_char
                "0",  # [11] text_flag
                "",  # [12] terminator
            ],
        )


# ---------------------------------------------------------------------------
# Unpack
# ---------------------------------------------------------------------------

#: Unpack sub-type names.
_UNPACK_TYPES = frozenset({"bits", "words"})


@dataclass
class Unpack(AfInstruction):
    """An unpack instruction (copy_type_idx=4).

    Unpacks a single source into a range of destination registers.

    Attributes
    ----------
    source:
        Source operand (e.g. ``"DS172"``).
    dest_start, dest_end:
        Destination range (e.g. ``"C128"`` .. ``"C143"``).
    unpack_type:
        ``"bits"`` or ``"words"``.
    oneshot:
        Execute once on OFF→ON transition.
    """

    source: str
    dest_start: str
    dest_end: str
    unpack_type: str = "bits"
    oneshot: bool = False

    def __post_init__(self) -> None:
        if self.unpack_type not in _UNPACK_TYPES:
            raise FieldError(f"Invalid unpack type: {self.unpack_type!r}")
        # Bank pairs wait on a dialog check; only the addresses, ranges and counts are checked.
        src = check_operand(self.source, "Unpack.source")
        first, last = _check_range(
            "Unpack", "dest_start", self.dest_start, "dest_end", self.dest_end, one_module=True
        )
        _check_kind("Unpack", "dest_start", self.dest_start, first.bank, self.unpack_type)
        _check_count(
            "Unpack", "dest_end", f"{self.dest_start}..{self.dest_end}", _span(first, last),
            self.unpack_type, src.bank, self.source,
        )  # fmt: skip

    @property
    def func_code(self) -> str:
        base = int(COPY_FUNC_CODES["4"])  # unpack base: 8980
        return str(base + (1 if self.oneshot else 0))

    def to_csv(self) -> str:
        dst = f"{self.dest_start}..{self.dest_end}"
        parts = [self.source, dst]
        kw: list[str] = []
        if self.oneshot:
            kw.append("oneshot=1")
        if kw:
            return f"unpack_to_{self.unpack_type}({','.join(parts)},{','.join(kw)})"
        return f"unpack_to_{self.unpack_type}({','.join(parts)})"

    def cell_params(self) -> dict:
        return {"visual_rows": 2}

    def build_blob(self) -> bytes:
        from ..binary_helpers import _build_blob

        return _build_blob(
            "Copy",
            0x2721,
            _COPY_TAGS,
            [
                self.source,  # [0]
                "",  # [1] source_end (unpack = empty)
                self.dest_start,  # [2]
                self.dest_end,  # [3]
                "0",  # [4] format_option
                "-1" if self.oneshot else "0",  # [5]
                "4",  # [6] copy_type_idx (unpack)
                self.func_code,  # [7]
                "0",  # [8] conversion_type
                "0",  # [9] termination_flag
                "0",  # [10] termination_char
                "0",  # [11] text_flag
                "",  # [12] terminator
            ],
        )


# ---------------------------------------------------------------------------
# Shared from_tags factory
# ---------------------------------------------------------------------------

_COPY_TYPE_CODE = 0x2721


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Copy | BlockCopy | Fill | Pack | Unpack | None:
    """Construct a Copy-family instruction from tag data (shared by both decoders)."""
    if class_name != "Copy" or type_code != _COPY_TYPE_CODE:
        return None

    source = tag_value(tags, 0x6074)
    source_end = tag_value(tags, 0x6075)
    destination = tag_value(tags, 0x6076)
    destination_end = tag_value(tags, 0x6077)
    oneshot = tag_flag(tags, 0x11F8)
    copy_type = tag_int(tags, 0x2223)
    conv_type = tag_int(tags, 0x2227)

    if copy_type == 0:
        if not source or not destination:
            return None
        # A single copy has no end addresses; one that carries them isn't a shape
        # CLICK writes, so leave it to raw() rather than drop them.
        if source_end or destination_end:
            return None
        opts = _CONVTYPE_TO_OPTS.get(str(conv_type))
        if opts is None:
            return None
        # Types that only exist for one source kind; anything else isn't a blob
        # CLICK writes, so leave it to raw() rather than re-encode it differently.
        if conv_type == 7 and not _is_dd_df_pair(source, destination):
            return None
        if conv_type == 4 and not _is_df(source):
            return None
        fmt, suppress_zero, exponential = opts

        termination_code = "0"
        term_char = tag_value(tags, 0x3216)
        # 0x1221 alone marks termination; 0x1201 is also set for a text
        # constant source, so it must not imply a termination code.
        if tag_flag(tags, 0x1221) and term_char:
            if not term_char.isdigit():
                return None
            termination_code = _ascii_code(int(term_char))

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
            pack_type = "bits" if _bank_prefix(source) in BIT_BANKS else "words"
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
        unpack_type = "bits" if _bank_prefix(destination) in BIT_BANKS else "words"
        return Unpack(
            source=source,
            dest_start=destination,
            dest_end=destination_end,
            unpack_type=unpack_type,
            oneshot=oneshot,
        )

    return None


# ---------------------------------------------------------------------------
# CSV parser
# ---------------------------------------------------------------------------


def _copy_from_csv(args: Sequence[str], kwargs: Mapping[str, str]) -> Copy:
    """Build a Copy from ``copy(source, dest, ...)`` arguments (both CSV paths)."""
    source, destination = args
    convert_raw = kwargs.get("convert", "")
    if convert_raw:
        fmt, text_opts = _parse_convert_kwarg(convert_raw)
    else:
        fmt, text_opts = "none", {}
    termination_code = text_opts.get("termination_code", "0")
    if termination_code == "none":
        termination_code = "0"
    return Copy(
        source=source,
        destination=destination,
        format=fmt,
        oneshot=kwargs.get("oneshot") == "1",
        suppress_zero=text_opts.get("suppress_zero", "0"),
        exponential=text_opts.get("exponential", "0"),
        termination_code=termination_code,
    )


def parse_af_call(call: AfCall) -> Copy | BlockCopy | Fill | Pack | Unpack:
    """Parse an AF AST call into a Copy-family instruction."""
    if call.name == "copy":
        if len(call.args) != 2:
            raise ValueError(f"copy expects 2 positional args (source, dest), got {len(call.args)}")
        return _copy_from_csv(call.args, call.kwargs)

    if call.name == "blockcopy":
        if len(call.args) != 2:
            raise ValueError(
                f"blockcopy expects 2 positional args (src_range, dest_range), got {len(call.args)}"
            )
        src_start, src_end = _parse_range(call.args[0])
        dest_start, dest_end = _parse_range(call.args[1])
        convert_raw = call.kwargs.get("convert", "")
        if convert_raw:
            fmt, _ = _parse_convert_kwarg(convert_raw)
        else:
            fmt = "none"
        return BlockCopy(
            source_start=src_start,
            source_end=src_end,
            dest_start=dest_start,
            dest_end=dest_end,
            format=fmt,
            oneshot=call.kwargs.get("oneshot") == "1",
        )

    if call.name == "fill":
        if len(call.args) != 2:
            raise ValueError(
                f"fill expects 2 positional args (value, dest_range), got {len(call.args)}"
            )
        dest_start, dest_end = _parse_range(call.args[1])
        return Fill(
            value=call.args[0],
            dest_start=dest_start,
            dest_end=dest_end,
            oneshot=call.kwargs.get("oneshot") == "1",
        )

    if call.name in ("pack_bits", "pack_words", "pack_text"):
        if len(call.args) != 2:
            raise ValueError(
                f"{call.name} expects 2 positional args (src_range, dest), got {len(call.args)}"
            )
        src_start, src_end = _parse_range(call.args[0])
        return Pack(
            source_start=src_start,
            source_end=src_end,
            destination=call.args[1],
            pack_type=call.name.removeprefix("pack_"),
            allow_whitespace=call.kwargs.get("allow_whitespace") == "1",
            oneshot=call.kwargs.get("oneshot") == "1",
        )

    if call.name in ("unpack_to_bits", "unpack_to_words"):
        if len(call.args) != 2:
            raise ValueError(
                f"{call.name} expects 2 positional args (source, dest_range), got {len(call.args)}"
            )
        dest_start, dest_end = _parse_range(call.args[1])
        return Unpack(
            source=call.args[0],
            dest_start=dest_start,
            dest_end=dest_end,
            unpack_type=call.name.removeprefix("unpack_to_"),
            oneshot=call.kwargs.get("oneshot") == "1",
        )

    raise ValueError(f"Unsupported copy-family instruction: {call.name!r}")


SPEC = AfInstructionFamilySpec(
    family_name="copy",
    instruction_types=(Copy, BlockCopy, Fill, Pack, Unpack),
    binary_class_names=("Copy",),
    from_tags=from_tags,
    csv_names=(
        "copy",
        "blockcopy",
        "fill",
        "pack_bits",
        "pack_words",
        "pack_text",
        "unpack_to_bits",
        "unpack_to_words",
    ),
    parse_csv_call=parse_af_call,
    min_csv_rows=2,
)
