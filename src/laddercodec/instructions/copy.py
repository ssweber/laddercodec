"""Copy family — single copy, block copy, fill, pack, and unpack (type marker 0x2721).

Binary class name: ``"Copy"``.

All five variants share the same binary class, discriminated by field[6]:

- ``0`` → single copy (``Copy``)
- ``1`` → block copy (``BlockCopy``)
- ``2`` → fill (``Fill``)
- ``3`` → pack (``Pack``)
- ``4`` → unpack (``Unpack``)

Quirk: in the ``to_text_term`` variant (termination checkbox enabled) the Click UI
greys out the termination value, yet the binary stores the flag and character code
normally.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ..binary_helpers import tag_flag, tag_int, tag_value
from ..errors import CsvError, WriterError
from ..model import (
    ADDRESS_BANKS,
    Address,
    AddressError,
    AfInstruction,
    FieldError,
    Reason,
    check_address,
    xy_slot,
)
from ..operands.address import read_as_typed
from ..operands.checks import (
    ALL_KINDS,
    BIT_BANKS,
    REGISTER_BANKS,
    WRITABLE_SD,
    Constants,
    Operand,
    Refusals,
    check_constant,
    check_operand,
    check_writable_sd,
    constant_shape,
)
from ..operands.constants import TEXT_MAX, Constant, Kind, classify, copy_real_display
from ..operands.unchecked import read_in_another_form
from .family import AfInstructionFamilySpec, fixed_cell_params

if TYPE_CHECKING:
    from ..csv.ast import AfCall

#: Cell kwargs of every Copy-family box: two rows (cell header +0x09 = +0x0A = 2).
_CELL_PARAMS: dict = {"visual_rows": 2}

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
# Conversion type mapping (field[8])
# ---------------------------------------------------------------------------

_VALID_FORMATS = frozenset({"none", "value", "text", "binary", "ascii"})

#: field[8] conversion_type → (format, suppress_zero, exponential).
#: Text sub-options are encoded in the conversion_type value itself: an integer
#: source has suppress zero (1) or not (2); a DF source (a pointer too) or a real
#: constant has real (3) or exponential (4) numbering and no suppress zero, which decode
#: holds as None.  7 converts a value between a real and a 32-bit integer
#: (:func:`_converts_value`), a plain copy in CSV.
_CONVTYPE_TO_OPTS: dict[str, tuple[str, str, str]] = {
    "0": ("none", "0", "0"),
    "1": ("text", "1", "0"),  # integer source, suppress zeros
    "2": ("text", "0", "0"),  # integer source, don't suppress zeros
    "3": ("text", "1", "0"),  # DF source or real constant, real numbering
    "4": ("text", "1", "1"),  # DF source or real constant, exponential numbering
    "5": ("value", "0", "0"),
    "6": ("ascii", "0", "0"),
    "7": ("none", "0", "0"),  # a real <-> a 32-bit integer
    "8": ("binary", "0", "0"),
}

_DF_RE = re.compile(r"DF[0-9]+")
_DD_RE = re.compile(r"DD[0-9]+")


def _is_df(operand: str) -> bool:
    return _DF_RE.fullmatch(operand.strip()) is not None


def _real_text_source(source: str) -> bool:
    """Whether CLICK's dialog offers real and exponential numbering for ``source`` copied
    to text, and no suppress zero: a DF address or pointer, or a real constant."""
    return (
        _operand_bank(source, pointer=True) == "DF"
        or constant_shape(source, _CONSTANTS) is Kind.FLOAT
    )


def _is_dd_df_pair(source: str, destination: str) -> bool:
    """A single copy between DD and DF, either way: CLICK's Copy Value / Copy Binary choice."""
    src, dst = source.strip(), destination.strip()
    return (_DD_RE.fullmatch(src) is not None and _is_df(dst)) or (
        _is_df(src) and _DD_RE.fullmatch(dst) is not None
    )


def _operand_bank(operand: str, *, pointer: bool = False) -> str | None:
    """The bank of ``operand`` read as an address (with ``pointer``, a pointer's bank too);
    None for a constant or text that is neither."""
    try:
        return check_operand(operand, "Copy.source", pointer=pointer).bank
    except FieldError:
        return None


def _converts_value(source: str, destination: str) -> bool:
    """Whether a single Copy of ``source`` into ``destination`` converts a value between a
    real and a 32-bit integer, which CLICK saves as conversion type 7.

    That is a copy between DF and DD or CTD, either way, and a real constant into DD or CTD,
    an address or a pointer (``1.5`` into ``DD[DS1]``).  A pointer of DF, DD or CTD beside a
    register is not type 7 here.
    """
    src, dst = _operand_bank(source), _operand_bank(destination)
    if (src == "DF" and dst in _INT32_BANKS) or (src in _INT32_BANKS and dst == "DF"):
        return True
    return (
        constant_shape(source, _CONSTANTS) is Kind.FLOAT
        and _operand_bank(destination, pointer=True) in _INT32_BANKS
    )


def _wide_into_df(source: str, destination: str) -> bool:
    """Whether ``source`` is a decimal integer outside int16 copied into a DF address or
    pointer, which CLICK saves as conversion type 7.

    CLICK saves ``32768``, ``-32769``, ``65535`` and ``65536`` into DF1, and ``2147483647``
    into DF1 and ``DF[DS1]``, as type 7; ``32767`` and ``-32768`` as type 0.
    """
    const = classify(source)
    return (
        const is not None
        and const.kind is Kind.INTEGER
        and const.wide
        and _operand_bank(destination, pointer=True) == "DF"
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
    0x6077,  # [3]  destination_end (block copy; a single copy of text: its last TXT)
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


def _is_text_constant(operand: str) -> bool:
    """True for a quoted text constant (``"Q"``) or an ASCII-code constant (``$00``).

    ``operand`` is a checked source: a ``$`` value in one is ``$hh``.
    """
    return operand.strip().startswith(('"', "$"))


def _ascii_code(code: int) -> str:
    """Spell a character code the way CLICK and pyrung do: ``$`` + two hex digits (``$0D``)."""
    if not 0 <= code <= 0xFF:
        raise FieldError(
            f"Copy.termination_code: ASCII code {code} is outside 0 to 0xFF",
            field="Copy.termination_code",
            reason=Reason.RANGE,
        )
    return f"${code:02X}"


_HEX_DIGITS = frozenset("0123456789ABCDEFabcdef")


def _is_one_digit_code(source: str) -> bool:
    """Whether ``source`` is ``$`` and one hex digit (``$1``)."""
    return len(source) == 2 and source[0] == "$" and source[1] in _HEX_DIGITS


def _source_display(source: str, kind: Kind) -> str:
    """CLICK's form of a single Copy's constant source, one it takes.

    A decimal integer keeps its sign, typed ``+`` too, and loses its leading zeros
    (``005`` is ``5``, ``+5`` and ``+0`` stay); zero loses a ``-`` (``-0`` is ``0``).  A hex
    constant has its digits uppercased, leading zeros kept, then a lowercase ``h`` (``0ffh``
    is ``0FFh``).  A real is printed back without a typed ``+`` (``1.50`` is ``1.5``,
    ``+1.5`` is ``1.5``, ``1E5`` is ``100000.0``, ``3.4028235E+38`` is ``3.402823E+38``;
    see :func:`~laddercodec.operands.constants.copy_real_display`).  Text and a character
    code come back as given.
    """
    if kind is Kind.INTEGER:
        sign = source[:1] if source[:1] in ("+", "-") else ""
        digits = source[len(sign) :].lstrip("0") or "0"
        if sign == "-" and digits == "0":
            sign = ""
        return sign + digits
    if kind is Kind.HEX:
        return f"{source[:-1].upper()}h"
    if kind is Kind.FLOAT:
        return copy_real_display(source)
    return source


#: Hex words a single Copy reads as a real, uppercased, with the real CLICK stores for each.
#: Whether CLICK reads any other hex word with an E (0EH, 01EH, E0H) as a real is not known.
_REAL_HEX_WORDS = {"EH": "0.0", "1EH": "1.0"}


def _real_hex_refusal(source: str) -> str | None:
    """Why a single Copy refuses ``source``, a hex word CLICK reads as a real, or None."""
    real = _REAL_HEX_WORDS.get(source.upper())
    if real is None:
        return None
    digits = source[:-1].upper()
    return (
        f"{source!r} is refused; CLICK's Copy reads it as the real {real}, not as hex "
        f"{digits}: write {real} for the real, or {int(digits, 16)} for the value of hex {digits}"
    )


# ---------------------------------------------------------------------------
# Operands and banks (Single Copy, Fill and pointers)
# ---------------------------------------------------------------------------

#: Registers that hold a number.
NUMERIC_BANKS = REGISTER_BANKS - {"TXT"}
#: Registers a copy writes: every register but XD.
_REGISTER_DEST_BANKS = REGISTER_BANKS - {"XD"}
_NUMERIC_DEST_BANKS = _REGISTER_DEST_BANKS - {"TXT"}
_COPY_DEST_BANKS = _REGISTER_DEST_BANKS | {"Y", "C"}
#: A Copy source or Fill value takes a constant of any kind; a signed hex text reads as a hex
#: constant, which the field then refuses.
_CONSTANTS = Constants(ALL_KINDS, hex_sign=True)
#: The same, with text of any characters: a single Copy checks its source's characters after
#: the pairing with the destination.
_ANY_TEXT = replace(_CONSTANTS, printable=False)
#: A termination code is a ``$hh`` character code.
_TERMINATION = Constants(frozenset({Kind.CHAR}))

#: How each source kind reads in a message.
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


def check_box_operand(
    value: str,
    name: str,
    banks: Collection[str] | None,
    constants: Constants | None = None,
    *,
    bank_id: str | None = None,
) -> Operand:
    """The shared ``check_operand`` for a field that takes no pointer: every Copy-family field
    but a single Copy's source and destination.

    A pointer is refused in the Copy family's words, "only a single Copy takes one".
    """
    bank, _, rest = value.partition("[")
    if (
        rest.endswith("]")
        and bank.isascii()
        and bank.isalpha()
        and bank.isupper()
        and len(bank) <= 3
    ):
        raise AddressError(
            f"{name}: {value!r} is a pointer; only a single Copy takes one",
            field=name,
            reason=Reason.POINTER,
        )
    return check_operand(value, name, banks, constants, bank_id=bank_id)


def _refusal(
    cls: str,
    attrs: tuple[str, ...],
    rule: str,
    reason: Reason,
    click_id: str | None = None,
    error: type[FieldError] = AddressError,
) -> FieldError:
    """A refusal of ``cls.attrs[0]`` (a pair or more, when the rule is about several
    fields): ``Class.attr: rule``, with CLICK's id at the end."""
    fields = tuple(f"{cls}.{attr}" for attr in attrs)
    tail = f" ({click_id})" if click_id else ""
    return error(f"{fields[0]}: {rule}{tail}", field=fields, reason=reason, click_id=click_id)


def _source_kind(value: str, name: str, banks: Collection[str], *, pointer: bool = False) -> str:
    """The kind of a Copy source or Fill value: ``bit``, ``word``, ``txt``, ``number`` or
    ``text``.

    An address or pointer is checked here.  A constant's limits wait for the caller: a Fill
    pairs the value with its range first, and a single Copy checks the constant's value
    after the destination (a ``$hh`` code is read at once).
    """
    shape = constant_shape(value, _CONSTANTS)
    if shape is Kind.CHAR:
        check_constant(value, name, _CONSTANTS)
    if shape is not None:
        return "text" if shape in (Kind.TEXT, Kind.CHAR) else "number"
    bank = (
        check_operand(value, name, banks, pointer=True)
        if pointer
        else check_box_operand(value, name, banks)
    ).bank
    assert bank is not None
    return _register_kind(bank)


def _position(address: Address) -> int:
    """Order of an address in its bank: ``XD0``, ``XD0u``, ``XD1`` ... count 0, 1, 2 ..."""
    if address.bank in ("XD", "YD"):
        return 1 if address.upper else address.number + (address.number > 0)
    return address.number


def _span(first: Address, last: Address) -> int | None:
    """Addresses from ``first`` to ``last`` in one bank; ``None`` for XD/YD.

    How CLICK counts across ``XD0u`` is not checked, so XD/YD ranges get no count.
    """
    if first.bank in ("XD", "YD"):
        return None
    return last.number - first.number + 1


def _range_end(
    value: str, field: str, banks: Collection[str] | None, bank_id: str | None
) -> Address:
    """One end of a range: an address, never a pointer."""
    address = check_box_operand(value, field, banks, bank_id=bank_id).address
    assert address is not None
    return address


def _check_relation(
    cls: str,
    start_field: str,
    start: str,
    end_field: str,
    end: str,
    first: Address,
    last: Address,
    *,
    one_module: bool,
    ordered: bool,
    module_id: str | None,
    ids: bool,
) -> None:
    """Refuse an end that does not fit its start: another bank, not after it, or in another
    X or Y slot.  A refusal of the pair, the end's field first."""
    pair = (end_field, start_field)
    if first.bank != last.bank:
        raise _refusal(
            cls,
            pair,
            f"{end!r} is not in the bank of {start!r}; both ends of a range are in one bank",
            Reason.CONFLICT,
            "OBJ-008" if ids else None,
        )
    if ordered and _position(last) <= _position(first):
        same = _position(last) == _position(first)
        raise _refusal(
            cls,
            pair,
            f"{start}..{end} {'is one address' if same else 'runs backwards'}; "
            "a range ends after its start",
            Reason.CONFLICT,
            ("OBJ-012" if same else "OBJ-009") if ids else None,
        )
    if one_module and first.bank in ("X", "Y") and xy_slot(first.number) != xy_slot(last.number):
        raise _refusal(
            cls,
            pair,
            f"{start}..{end} spans two {first.bank} slots; "
            f"the range stays in one 16-point {first.bank} slot",
            Reason.CONFLICT,
            module_id,
        )


def check_range(
    cls: str,
    start_field: str,
    start: str,
    end_field: str,
    end: str,
    banks: Collection[str] | None = None,
    *,
    one_module: bool = False,
    ordered: bool = True,
    bank_id: str | None = None,
    module_id: str | None = None,
    ids: bool = True,
) -> tuple[Address, Address]:
    """Check a ``start..end`` range and return its two ends.

    Both ends are addresses in one bank (OBJ-008), never pointers.  With ``ordered``, the end
    comes after the start: an end before it is OBJ-009 and the same address OBJ-012
    (Search repeats this range check).
    With ``one_module``, an X or Y range stays inside one 16-point slot of
    :data:`~laddercodec.model.XY_SLOTS` (``module_id`` is CLICK's id for the refusal); the
    dual option slot, 21-36, is a slot of its own.  The module check applies to the
    Pack source, the Block Copy source and the Unpack destination.  ``bank_id`` is CLICK's id
    for an end in a bank the field does not take.  A refusal of how the ends fit is a refusal
    of the pair, the end's field first.  ``ids=False`` leaves out OBJ-008, OBJ-009 and
    OBJ-012, for a dialog whose ids are not known.
    """
    first = _range_end(start, f"{cls}.{start_field}", banks, bank_id)
    last = _range_end(end, f"{cls}.{end_field}", banks, bank_id)
    _check_relation(
        cls, start_field, start, end_field, end, first, last,
        one_module=one_module, ordered=ordered, module_id=module_id, ids=ids,
    )  # fmt: skip
    return first, last


def _check_range(
    check: Refusals,
    start_attr: str,
    start: str,
    end_attr: str,
    end: str,
    banks: Collection[str] | None = None,
    *,
    one_module: bool = False,
    ordered: bool = True,
    bank_id: str | None = None,
    module_id: str | None = None,
    ids: bool = True,
) -> tuple[Address | None, Address | None]:
    """:func:`check_range` keeping every refusal: each end on its own, then the pair.

    The ends come back, None for a refused one, even when the relation between them was
    refused (the end's field leads that refusal).
    """
    cls = check.field(start_attr).partition(".")[0]
    first = check(start_attr, _range_end, banks, bank_id)
    last = check(end_attr, _range_end, banks, bank_id)
    if first is not None and last is not None:
        check.run(
            _check_relation, cls, start_attr, start, end_attr, end, first, last,
            one_module=one_module, ordered=ordered, module_id=module_id, ids=ids,
        )  # fmt: skip
    return first, last


def _check_pair(
    cls: str,
    source_field: str,
    source: str,
    kind: str,
    dest_field: str,
    destination: str,
    dest_bank: str,
    pairs: dict[str, frozenset[str]],
    click_id: str | None = None,
) -> None:
    """Refuse a destination bank the source kind can't copy into: a refusal of the
    destination with the source."""
    allowed = pairs[kind]
    if dest_bank not in allowed:
        raise _refusal(
            cls,
            (dest_field, source_field),
            f"{destination!r} can't take {source!r}; "
            f"{_KIND_TEXT[kind]} copies to {_bank_list(allowed)}",
            Reason.CONFLICT,
            click_id,
        )


def _check_kind(
    cls: str, field_name: str, value: str, bank: str, kind: str, kind_field: str
) -> None:
    """Pack/unpack ``bits`` takes a bit range and ``words`` a register range.

    The blob stores no bits/words flag; the decoder reads it from this bank.  A refusal of
    the range's start with ``kind_field``.
    """
    if (kind == "bits") != (bank in BIT_BANKS):
        what = "a register" if kind == "bits" else "a bit"
        need = f"a bit bank ({_bank_list(BIT_BANKS)})" if kind == "bits" else "a register bank"
        raise _refusal(
            cls,
            (field_name, kind_field),
            f"{value!r} is {what}; {kind} needs {need}",
            Reason.CONFLICT,
        )


#: Most bits one register packs into or unpacks from.
_BITS_PER_REGISTER = {"DS": 16, "DH": 16, "DD": 32, "DF": 32}
#: Most bits any one pack moves.
_MAX_BITS = max(_BITS_PER_REGISTER.values())
#: Most words one pack or unpack moves.
_MAX_WORDS = 2
#: Most TXT characters a pack of text reads into a DH.  Only DH has a limit yet.
_DH_TEXT_CHARS = 4
#: How a count of each kind reads in a message.
_UNITS = {"bits": "bits", "words": "words", "text": "characters"}
#: CLICK's id for a count over the limit: (kind, limit) -> (Pack's id, Unpack's id).
_COUNT_IDS: dict[tuple[str, int], tuple[str, str | None]] = {
    ("bits", 16): ("OBJ-027", "OBJ-032"),
    ("bits", _MAX_BITS): ("OBJ-041", "OBJ-039"),
    ("words", _MAX_WORDS): ("OBJ-040", "OBJ-042"),
    ("text", _DH_TEXT_CHARS): ("OBJ-003", None),
}


def _count_limit(kind: str, bank: str | None) -> int | None:
    """Most bits, words or characters one register of ``bank`` packs or unpacks; None for
    no limit."""
    if kind == "bits":
        return _BITS_PER_REGISTER.get(bank or "")
    if kind == "text":
        return _DH_TEXT_CHARS if bank == "DH" else None
    return _MAX_WORDS


def _pack_kind(bank: str) -> str:
    """The pack a source bank makes: ``bits``, ``words``, or ``text`` from TXT."""
    if bank == "TXT":
        return "text"
    return "bits" if bank in BIT_BANKS else "words"


def _pack_limit(kind: str, source_bank: str, dest_bank: str, paired: bool) -> int | None:
    """Most a Pack source of ``kind`` holds, checked before the pairing.

    Where the source packs into the destination (``paired``), the destination's room. Where
    it doesn't, bits are held to 32, the most any destination takes, and a DH source to two
    words; a DS source is not counted then.
    """
    if paired:
        return _count_limit(kind, dest_bank)
    if kind == "bits":
        return _MAX_BITS
    return _MAX_WORDS if source_bank == "DH" else None


def _check_count(
    cls: str,
    start_field: str,
    end_field: str,
    other_field: str,
    span_text: str,
    count: int | None,
    kind: str,
    limit: int | None,
    single: str | None,
) -> None:
    """Refuse a pack source or unpack destination longer than ``limit``: a refusal of the
    range's end with its start and the single register's field.

    ``single`` names the register in the message; None states the limit of every pack of
    ``kind`` (for a Pack whose source does not pack into its destination).
    """
    if limit is not None and count is not None and count > limit:
        unit = _UNITS[kind]
        if single is None:
            rule = f"a pack of {unit} takes at most {limit}"
        else:
            verb = "a pack into" if cls == "Pack" else "an unpack from"
            rule = f"{verb} {single!r} takes at most {limit}"
        pack_id, unpack_id = _COUNT_IDS[(kind, limit)]
        raise _refusal(
            cls,
            (end_field, start_field, other_field),
            f"{span_text} is {count} {unit}; {rule}",
            Reason.RANGE,
            pack_id if cls == "Pack" else unpack_id,
            FieldError,
        )


#: Source kind -> destination banks of a single Copy.
_COPY_PAIRS: dict[str, frozenset[str]] = {
    "bit": frozenset({"Y", "C"}),
    "word": _REGISTER_DEST_BANKS,
    "txt": _REGISTER_DEST_BANKS,
    "number": _REGISTER_DEST_BANKS,
    "text": frozenset({"TXT"}),
}

#: Source kind -> destination banks of a Fill, which agree with a single Copy for registers.
_FILL_PAIRS: dict[str, frozenset[str]] = {
    "word": _NUMERIC_DEST_BANKS,
    "txt": frozenset({"TXT"}),
    "number": _REGISTER_DEST_BANKS,
    "text": frozenset({"TXT"}),
}


def _copy_dest_bank_id(kind: str | None, source: str, destination: str) -> str | None:
    """CLICK's id for a single Copy destination in a bank a Copy does not write.

    A ``$hh`` character code copies to TXT only, and CLICK refuses it anywhere else as an
    address the instruction can't use (OBJ-004: ``$41`` into X001 or XD0), as its pairing
    with a register is.  In a bit bank a Copy does not write (X, T, CT and SC: it writes no
    bit bank but Y and C), an address outside its bank is OBJ-004 from any source (DS2 into
    X017, T501, CT251 or SC1001).  Inside it, CLICK refuses a bit as an address the
    instruction can't use (OBJ-004: X001 into X001, C1 into SC50 and SC303), and anything
    else as a pairing of kinds (OBJ-024: DS2 and 5 into X001), the id of every other pairing
    a single Copy refuses.  XD, the one register bank a Copy does not write, has no id from
    another source.

    A source that is refused has no id here: an address ``_source_kind`` refuses (``kind``
    None), and a constant the source's own check refuses later (out of range, or text it
    can't hold); that refusal stays after the destination's.
    """
    if kind is None:
        return None
    if kind in ("number", "text"):
        try:
            check_constant(source, "Copy.source", _CONSTANTS)
        except FieldError:
            return None
    if source.startswith("$"):
        return "OBJ-004"
    if _bank_prefix(destination) not in BIT_BANKS:
        return None
    if kind == "bit" or not _in_its_bank(destination):
        return "OBJ-004"
    return "OBJ-024"


def _check_copy_destination(destination: str, field: str, source: str, kind: str | None) -> Operand:
    """A single Copy destination: an address or pointer of a bank a Copy writes.

    A ``$hh`` code copies to TXT only: CLICK refuses it into a pointer of any other bank
    (``X[DS1]``, ``XD[DS1]``, ``SD[DS1]``) as an address the instruction can't use (OBJ-004),
    as into an address.
    """
    try:
        return check_operand(
            destination, field, _COPY_DEST_BANKS, pointer=True,
            bank_id=_copy_dest_bank_id(kind, source, destination),
        )  # fmt: skip
    except AddressError as exc:
        if (
            exc.click_id is not None
            or exc.reason is not Reason.POINTER
            or kind is None
            or not source.startswith("$")
            or not _is_pointer(destination, field)
        ):
            raise
        raise AddressError(
            f"{exc} (OBJ-004)", field=exc.fields, reason=exc.reason, click_id="OBJ-004"
        ) from None


def _is_pointer(value: str, field: str) -> bool:
    """Whether ``value`` is ``BANK[DSn]``: a bank's name and a DS address in brackets."""
    bank, bracket, index = value.partition("[")
    if not bracket or bank not in ADDRESS_BANKS or not index.endswith("]"):
        return False
    try:
        return check_address(index[:-1], field).bank == "DS"
    except AddressError:
        return False


def _in_its_bank(address: str) -> bool:
    """Whether ``address`` is a CLICK address: its number inside its bank's range."""
    try:
        check_address(address, "Copy.destination")
    except AddressError:
        return False
    return True


def _check_source_value(source: str, field: str) -> Constant:
    """A single Copy source constant's own value, its characters aside.

    CLICK refuses as values, with OBJ-005 as for a hex constant above FFFFFFFFh: an empty
    text, a text of more than 128 characters, a signed hex constant (``-FFh``) and one of
    more than 8 digits (``0FFFFFFFFh``).  A quote inside the text has no answer and no id.
    """
    try:
        return check_constant(source, field, _ANY_TEXT)
    except FieldError as exc:
        shape = constant_shape(source, _ANY_TEXT)
        if exc.click_id is not None or not (
            shape is Kind.HEX or (shape is Kind.TEXT and '"' not in source[1:-1])
        ):
            raise
        raise FieldError(
            f"{exc} (OBJ-005)", field=exc.fields, reason=exc.reason, click_id="OBJ-005"
        ) from None


#: The 32-bit integer registers.
_INT32_BANKS = frozenset({"DD", "CTD"})
#: Where a single Copy puts a hex constant above FFFFh: the 32-bit integer registers
#: (OBJ-024).
_HEX32_DEST_BANKS = _INT32_BANKS


def _check_hex32(source: str, dest_field: str, destination: str, dest_bank: str) -> None:
    """Refuse a hex constant above FFFFh that ``dest_bank`` can't take."""
    shape = constant_shape(source, _CONSTANTS)
    if shape is Kind.HEX and int(source[:-1], 16) > 0xFFFF and dest_bank not in _HEX32_DEST_BANKS:
        raise _refusal(
            "Copy",
            (dest_field, "source"),
            f"{destination!r} can't take {source!r}; a hex constant above "
            f"FFFFh copies to {_bank_list(_HEX32_DEST_BANKS)}",
            Reason.CONFLICT,
            "OBJ-024",
        )


#: The last TXT register.
_TXT_LAST = ADDRESS_BANKS["TXT"][1]


def _text_fill_end(source: str, destination: str) -> Address | None:
    """The last TXT a single Copy of quoted text fills; the blob stores it as the
    destination end (tag 0x6077).

    CLICK stores it for two or more characters (``"TT"`` into TXT1 stores TXT2) and
    leaves the end empty for one character (``"Q"`` into TXT2) and for a ``$hh`` code.
    ``None`` for those, and for a pointer destination, where CLICK stores no end whatever
    the length (``copy("AB",TXT[DS1])``).
    """
    if not (len(source) >= 4 and source[0] == source[-1] == '"'):
        return None
    # A TXT: text copies only there.
    first = check_operand(destination, "Copy.destination", pointer=True)
    if first.address is None:
        return None
    return Address("TXT", first.address.number + len(source) - 3)


#: The constant kinds a single Copy writes into TXT as their text.
_NUMBER_KINDS = frozenset({Kind.INTEGER, Kind.HEX, Kind.FLOAT})


def _number_fill_end(source: str, destination: str) -> Address | None:
    """The last TXT a single Copy of a number constant into a TXT address fills with the
    constant's text, which CLICK saves as the destination end (tag 0x6077).

    The text is the constant as stored, ``h`` and a ``+`` included, one TXT a character:
    ``-5``, ``1h`` and ``+5`` into TXT1 end in TXT2, ``10h`` and ``1.5`` in TXT3, ``0FFh`` in
    TXT4, ``FFFFh`` in TXT5, ``2147483647`` in TXT10.  An end past TXT1000 is returned too:
    CLICK refuses it (``-5`` into TXT1000 ends in TXT1001, OBJ-003).  ``None`` for one
    character (``5`` into TXT1, saved with no end), for a pointer (``1.5`` into ``TXT[DS1]``,
    saved with no end), and for any other source or destination.
    """
    if len(source) < 2 or constant_shape(source, _CONSTANTS) not in _NUMBER_KINDS:
        return None
    try:
        first = check_operand(destination, "Copy.destination").address
    except FieldError:
        return None
    if first is None or first.bank != "TXT":
        return None
    return Address("TXT", first.number + len(source) - 1)


def _number_text_types(source: str) -> frozenset[int]:
    """The conversion types a number constant's end is saved with: 3 or 4 (real or
    exponential numbering) for a real, 1 or 2 (zeros suppressed or not) for an integer or
    hex constant."""
    if constant_shape(source, _CONSTANTS) is Kind.FLOAT:
        return frozenset({3, 4})
    return frozenset({1, 2})


# ---------------------------------------------------------------------------
# Block, Pack and Unpack pairs (pairing table)
# ---------------------------------------------------------------------------

#: One pairing row: source banks and the destination banks they copy to.  The first row
#: holding the source bank applies; a destination outside it is refused.
_Rows = tuple[tuple[frozenset[str], frozenset[str]], ...]

_NUMERIC_BITS = frozenset({"X", "Y", "T", "CT", "SC"})

#: Block Copy rows.  Its source and destination edits refuse every other bank
#: (OBJ-004): XD, YD, TD and CTD are no source, and X, T, CT, SC, XD and YD no destination.
_BLOCK_ROWS: _Rows = (
    (BIT_BANKS, frozenset({"Y", "C"})),
    (frozenset({"DS", "DD", "DH", "DF", "SD"}), frozenset({"DS", "DD", "DH", "DF", "TD", "CTD", "SD"})),
    (frozenset({"TXT"}), frozenset({"DS", "DD", "DH", "TXT"})),
)  # fmt: skip
#: Pack rows: X/Y/T/CT/SC bits pack into DH only; C into any 16- or 32-bit word.
_PACK_ROWS: _Rows = (
    (_NUMERIC_BITS, frozenset({"DH"})),
    (frozenset({"C"}), frozenset({"DS", "DD", "DH", "DF"})),
    (frozenset({"DS"}), frozenset({"DD", "DF"})),
    (frozenset({"DH"}), frozenset({"DD"})),
    (frozenset({"TXT"}), frozenset({"DS", "DD", "DH", "DF", "TD", "CTD"})),
)
#: Unpack rows: only DH unpacks to Y.
_UNPACK_ROWS: _Rows = (
    (frozenset({"DS"}), frozenset({"C"})),
    (frozenset({"DD", "DF"}), frozenset({"C", "DS", "DH"})),
    (frozenset({"DH"}), frozenset({"Y", "C"})),
)


def _sources(rows: _Rows) -> frozenset[str]:
    return frozenset().union(*(src for src, _ in rows))


def _destinations(rows: _Rows) -> frozenset[str]:
    return frozenset().union(*(dst for _, dst in rows))


#: CLICK's id for a destination bank the source's row leaves out: an Unpack's destination
#: field gives OBJ-004 for every bank its source greys out but Y (:data:`_UNPACK_Y_ID`);
#: Block Copy and Pack give OBJ-024 for a pairing.
_ROW_IDS = {"BlockCopy": "OBJ-024", "Pack": "OBJ-024", "Unpack": "OBJ-004"}
#: CLICK's id for an Unpack into Y from a source other than DH: a pairing of kinds.
_UNPACK_Y_ID = "OBJ-024"


def _source_row(rows: _Rows, source_bank: str) -> frozenset[str]:
    """The destination banks of the first row holding ``source_bank``."""
    return next(dst for src, dst in rows if source_bank in src)


def _check_row(
    cls: str,
    rows: _Rows,
    source: str,
    source_field: str,
    source_bank: str,
    dest_field: str,
    destination: str,
    dest_bank: str,
) -> None:
    """Refuse a destination bank the source bank's pairing row leaves out: a refusal of the
    destination with the source."""
    allowed = _source_row(rows, source_bank)
    if dest_bank not in allowed:
        what = {"BlockCopy": "a block copy", "Pack": "a pack", "Unpack": "an unpack"}[cls]
        raise _refusal(
            cls,
            (dest_field, source_field),
            f"{destination!r} can't take {source!r}; "
            f"{what} from {source_bank} goes to {_bank_list(allowed)}",
            Reason.CONFLICT,
            _UNPACK_Y_ID if cls == "Unpack" and dest_bank == "Y" else _ROW_IDS[cls],
        )


#: The last SD register a Copy writes.
_LAST_WRITABLE_SD = max(WRITABLE_SD)


def _check_sd_range(dest: Address, end: int, source: tuple[str, str]) -> None:
    """Refuse a Block Copy into SD whose range, after its writable start, holds an SD that
    is not writable: a refusal of the destination with the source, whose length sets the end.

    CLICK's id: OBJ-018 when every unwritable SD in the range lies below SD215, OBJ-004 when
    every one lies past it, no id when it has both.
    """
    unwritable = [n for n in range(dest.number, end + 1) if n not in WRITABLE_SD]
    if not unwritable:
        return
    if all(n > _LAST_WRITABLE_SD for n in unwritable):
        click_id: str | None = "OBJ-004"
    elif all(n < _LAST_WRITABLE_SD for n in unwritable):
        click_id = "OBJ-018"
    else:
        click_id = None
    first = Address("SD", unwritable[0]).display
    raise _refusal(
        "BlockCopy",
        ("dest_start", "source_start", "source_end"),
        f"{source[0]}..{source[1]} into {dest.display} fills "
        f"{dest.display}..{Address('SD', end).display}, and {first} is not a writable SD "
        f"register; the writable SD are {', '.join(f'SD{n}' for n in sorted(WRITABLE_SD))}",
        Reason.NOT_WRITABLE,
        click_id,
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

    Examples: ``to_value``, ``to_text(exponential=1)``.
    """
    m = _CONVERT_CALL_RE.fullmatch(raw.strip())
    if not m:
        raise CsvError(f"Cannot parse convert value: {raw!r}")

    fmt = m.group(1)  # "text", "value", "binary", "ascii"
    inner = (m.group(2) or "").strip()

    if fmt not in ("text", "binary"):
        if inner:
            raise CsvError(f"to_{fmt} takes no arguments: {raw!r}")
        return fmt, {}

    # to_text and to_binary: parse kwargs
    text_opts: dict[str, str] = {}
    if inner:
        for part in inner.split(","):
            part = part.strip()
            if "=" not in part:
                raise CsvError(f"to_{fmt} options must be keyword arguments: {raw!r}")
            k, v = part.split("=", 1)
            k = k.strip()
            if fmt == "binary" and k != "termination_code":
                raise FieldError(
                    f"to_binary: {k!r} is not an option; it takes only termination_code",
                    field="Copy.format",
                    reason=Reason.CHOICE,
                )
            text_opts[k] = v.strip()

    return fmt, text_opts


def _parse_range(arg: str) -> tuple[str, str]:
    """Split ``"A..B"`` into ``("A", "B")``."""
    if ".." not in arg:
        raise CsvError(f"Expected range with '..': {arg!r}")
    parts = [p.strip() for p in arg.split("..")]
    if len(parts) != 2 or not all(parts):
        raise CsvError(f"Cannot parse range: {arg!r}")
    return parts[0], parts[1]


# ---------------------------------------------------------------------------
# Termination code (single Copy and Block Copy)
# ---------------------------------------------------------------------------


def _read_termination(check: Refusals, inst: Copy | BlockCopy) -> None:
    """Spell ``inst.termination_code`` one way, whichever way it came in (``$0d`` from CSV,
    13 from a blob): ``$`` and two uppercase hex digits, or ``"0"`` for no code.

    ``"none"`` is the CSV spelling of no code, which ``to_csv`` writes; a blank is refused.
    """
    if inst.termination_code == "":
        check.refuse(
            "termination_code", "is blank; it needs a code, or 'none' for no code", Reason.MISSING
        )
    elif inst.termination_code == "none":
        inst.termination_code = "0"
    elif inst.termination_code.startswith("$"):
        code = check("termination_code", check_constant, _TERMINATION, char_id="OBJ-036")
        if code is not None:
            spelled = check.run(_ascii_code, int(code.value))
            if spelled is not None:
                inst.termination_code = spelled


def _check_termination_form(check: Refusals, inst: Copy | BlockCopy) -> None:
    """Refuse a termination code that is no character code: the blob stores only those."""
    if not inst.termination_code.startswith("$") and inst.termination_code != "0":
        check.refuse(
            "termination_code",
            f"{inst.termination_code!r} is not allowed; it is a "
            "character code ($0D), or '0' or 'none' for no code",
            Reason.FORM,
            "OBJ-036",
        )


def _termination_tags(termination_code: str) -> tuple[str, str]:
    """Tags 0x1221 (termination flag) and 0x3216 (the code in decimal) for a code."""
    if termination_code != "0" and termination_code.startswith("$"):
        return "-1", str(int(termination_code[1:], 16))
    return "0", "0"


def _read_termination_tags(tags: dict[int, str]) -> str | None:
    """The termination code a blob stores: ``"0"`` for none, or ``$hh``; None for a code
    that is no decimal number.

    0x1221 alone marks termination; 0x1201 is also set for a text constant source, so it
    does not imply a code.  CLICK leaves 0x3216 out for the code ``$00``.
    """
    term_char = tag_value(tags, 0x3216)
    if not (tag_flag(tags, 0x1221) and term_char):
        return "0"
    if not (term_char.isascii() and term_char.isdigit()):
        return None
    return _ascii_code(int(term_char))


def _termination_csv(termination_code: str) -> list[str]:
    """The ``termination_code=`` kwarg of a Copy with no converter or a Block Copy: none
    for no code."""
    return [] if termination_code == "0" else [f"termination_code={termination_code}"]


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
        ``"binary"``, or ``"ascii"``.  A TXT register copied into a numeric register other
        than DF takes ``"value"`` or ``"ascii"``, and refuses ``"none"``.
    oneshot:
        Execute once on OFF→ON transition.
    suppress_zero:
        Text option for an integer, hex or register source — ``"0"`` (don't suppress) or
        ``"1"`` (suppress); ``None`` reads as ``"0"``.  A DF source or a real constant
        has no such option: it holds ``None``, and refuses a value.  A TXT source refuses
        ``"1"``.
    exponential:
        Text option for a DF source or a real constant — ``"0"`` (real) or ``"1"``
        (exponential).  Any other source has no such option and refuses ``"1"``.
    termination_code:
        For a number register copied to text (``"text"`` or ``"binary"``) or a TXT register
        copied to TXT (``"none"``) — ``"0"`` or ``"none"`` (no code; stored as ``"0"``), or
        ``"$HH"`` hex ASCII code, always two digits (``"$0D"`` for 0x0D; ``"$D"`` is
        refused).  A lowercase code is stored in uppercase (``"$0d"`` as ``"$0D"``).
    """

    source: str
    destination: str
    format: str = "none"
    oneshot: bool = False
    suppress_zero: str | None = None
    exponential: str = "0"
    termination_code: str = "0"

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            # A constant comes back from normalize_address as written.
            check.normalize("source", "destination")
            if _is_one_digit_code(self.source):
                # A single Copy takes $ and one hex digit as a character code; CLICK stores
                # it with two ($1 is $01).
                self.source = f"$0{self.source[1]}"
            elif (why := _real_hex_refusal(self.source)) is not None:
                check.refuse("source", why, Reason.FORM)
            if self.format not in _VALID_FORMATS:
                check.refuse(
                    "format",
                    f"{self.format!r} is not allowed; it is none, value, text, binary or ascii",
                    Reason.CHOICE,
                )
            _read_termination(check, self)
            # No suppress_zero is "0", but for a real source copied to text, which has none.
            if self.suppress_zero is None and not (
                self.format == "text" and _real_text_source(self.source)
            ):
                self.suppress_zero = "0"
            for option in ("suppress_zero", "exponential"):
                value = getattr(self, option)
                if value not in ("0", "1") and not (option == "suppress_zero" and value is None):
                    check.refuse(
                        option,
                        f"{getattr(self, option)!r} is not allowed; it is '0' or '1'",
                        Reason.CHOICE,
                    )
            # CLICK's order: the source's address, the destination's, the source constant's
            # own value, the pairing of the two, then an SD the Copy does not write.
            kind = check("source", _source_kind, BIT_BANKS | REGISTER_BANKS, pointer=True)
            dst = check("destination", _check_copy_destination, self.source, kind)
            const = None
            if kind in ("number", "text"):
                # Before the pairing: "" and 100000000h into DS1 are refused values (OBJ-005).
                # Text outside printable ASCII is refused at the end ("é" into DS1 is OBJ-024).
                const = check("source", _check_source_value)
            if kind is not None and dst is not None:
                assert dst.bank is not None
                # A $hh code into any bank but TXT is OBJ-004; any other pairing, OBJ-024.
                check.run(
                    _check_pair, "Copy", "source", self.source, kind,
                    "destination", self.destination, dst.bank, _COPY_PAIRS,
                    "OBJ-004" if self.source.startswith("$") else "OBJ-024",
                )  # fmt: skip
                if kind == "number":
                    check.run(_check_hex32, self.source, "destination", self.destination, dst.bank)
            if dst is not None and dst.address is not None:
                # A Copy writes only the writable SD registers (OBJ-004), after the pairing:
                # a bit, quoted text or 10000h into SD1 is OBJ-024.
                check.run(
                    check_writable_sd, dst.address, check.field("destination"), click_id="OBJ-004"
                )
            if kind is not None and dst is not None:
                assert dst.bank is not None
                self._check_format(check, kind, dst.bank)
                if self.termination_code != "0" and not (
                    (self.format in ("text", "binary") and kind == "word" and dst.bank == "TXT")
                    or (self.format == "none" and kind == "txt" and dst.bank == "TXT")
                ):
                    # CLICK's dialog offers Termination Code for a number register copied to
                    # text and for a TXT register copied to TXT; it greys the box for a
                    # constant copied to TXT.
                    check.refuse(
                        ("termination_code", "format", "source", "destination"),
                        f"{self.termination_code!r} needs a numeric register copied to TXT "
                        "with to_text or to_binary, or a TXT register copied to TXT, not "
                        f"{self.source!r} -> {self.destination!r} with format {self.format!r}",
                        Reason.CONFLICT,
                    )
            if kind == "txt" and self.suppress_zero == "1":
                # CLICK's dialog greys Suppress zero for a TXT source, into a number or TXT.
                check.refuse(
                    ("suppress_zero", "source"),
                    f"suppress_zero=1 is not an option for {self.source!r}; suppress zero is "
                    "for a number copied to text",
                    Reason.CONFLICT,
                )
            if self.format == "text":
                # CLICK's dialog offers suppress zero for an integer, hex or register
                # source, and real or exponential numbering for a DF source or a real
                # constant, never both.
                if _real_text_source(self.source):
                    if self.suppress_zero is not None and not check.refused("suppress_zero"):
                        check.refuse(
                            ("suppress_zero", "source"),
                            f"to_text(suppress_zero=...) is not an option for {self.source!r}; "
                            "a DF source or a real constant only has exponential",
                            Reason.CONFLICT,
                        )
                elif self.exponential == "1":
                    check.refuse(
                        ("exponential", "source"),
                        "to_text(exponential=1) needs a DF source or a real constant, not "
                        f"{self.source!r}; an integer source only has suppress_zero",
                        Reason.CONFLICT,
                    )
            _check_termination_form(check, self)
            if const is not None:
                const = check("source", check_constant, _CONSTANTS)
            if const is not None:
                # Written as CLICK stores it.
                self.source = _source_display(self.source, const.kind)
            if not check.refused("source", "destination"):
                # CLICK's dialog shows the end a text fills (TXT1001) and refuses one past
                # TXT1000 as out of range.
                end = _text_fill_end(self.source, self.destination)
                if end is not None and end.number > _TXT_LAST:
                    check.add(
                        _refusal(
                            "Copy",
                            ("destination",),
                            f"{self.destination!r} can't take {self.source!r}; its "
                            f"{len(self.source) - 2} characters fill "
                            f"{self.destination}..{end.display}, past TXT{_TXT_LAST}",
                            Reason.RANGE,
                            "OBJ-003",
                        )
                    )
                end = _number_fill_end(self.source, self.destination)
                if self.format == "text" and end is not None and end.number > _TXT_LAST:
                    check.add(
                        _refusal(
                            "Copy",
                            ("destination",),
                            f"{self.destination!r} can't take {self.source!r} as text; it "
                            f"fills {self.destination}..{end.display}, past TXT{_TXT_LAST}",
                            Reason.RANGE,
                            "OBJ-003",
                        )
                    )
            check.flag("oneshot")

    def _destination_end(self) -> str:
        """Tag 0x6077: the last TXT a text of two or more characters fills, else empty.

        A number constant copied to text fills TXT with its own text, as CLICK saves it:
        the end counts the constant as stored, ``h`` and a ``+`` included (``-5`` into TXT1
        ends in TXT2, ``0FFh`` in TXT4, ``1.5`` in TXT3).
        """
        end = _text_fill_end(self.source, self.destination)
        if end is None and self.format == "text":
            end = _number_fill_end(self.source, self.destination)
        return "" if end is None else end.display

    def _conversion(self) -> tuple[str, str]:
        """Tags 0x2227 (conversion type) and 0x2206 (format option) as the encoder writes
        them for these fields."""
        # field[4] is the dialog's radio index; CLICK v4 ignores it on load.
        if self.format == "text":
            if _real_text_source(self.source):
                exp = int(self.exponential)
                return str(3 + exp), str(exp)
            sz = 1 if self.suppress_zero == "1" else 0
            return str(2 - sz), str(1 - sz)
        if _is_dd_df_pair(self.source, self.destination) and self.format in ("none", "binary"):
            return ("7", "0") if self.format == "none" else ("8", "1")
        if self.format == "none" and (
            _converts_value(self.source, self.destination)
            or _wide_into_df(self.source, self.destination)
        ):
            return "7", "0"
        return _FORMAT_TO_CONVTYPE[self.format], _FORMAT_TO_FIELD4[self.format]

    def _check_format(self, check: Refusals, kind: str, dest_bank: str) -> None:
        """Refuse a converter the source and destination kinds don't offer."""
        fmt = self.format
        if fmt == "binary" and _is_dd_df_pair(self.source, self.destination):
            return  # DD <-> DF Copy Binary
        if fmt == "none" and kind == "txt" and _asks_txt_choice(dest_bank):
            # CLICK's dialog asks for Copy Character Value or Copy ASCII Code Value, and
            # saves one of them; a plain copy is not one it saves.
            check.refuse(
                ("format", "source", "destination"),
                f"{self.source!r} -> {self.destination!r} needs convert=to_value (the "
                "character's value) or convert=to_ascii (its ASCII code)",
                Reason.CONFLICT,
            )
            return
        if fmt in ("text", "binary"):
            ok, need = kind in ("word", "number") and dest_bank == "TXT", "a number to TXT"
        elif fmt in ("value", "ascii"):
            ok, need = kind == "txt" and dest_bank in _NUMERIC_DEST_BANKS, "TXT to a number"
        else:
            return
        if not ok:
            check.refuse(
                ("format", "source", "destination"),
                f"to_{fmt} copies {need}, not {self.source!r} -> {self.destination!r}",
                Reason.CONFLICT,
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
            copy(TXT1,TXT21,termination_code=$0D)
        """
        token = token.strip()
        m = re.fullmatch(r"copy\((.+)\)", token)
        if not m:
            raise CsvError(f"Cannot parse copy: {token!r}")

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
            raise CsvError(
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
            # Only the option the source has.
            option = (
                f"exponential={self.exponential}"
                if _real_text_source(self.source)
                else f"suppress_zero={self.suppress_zero}"
            )
            text_kw = [
                option,
                f"termination_code={'none' if self.termination_code == '0' else self.termination_code}",
            ]
            kw.append(f"convert=to_text({','.join(text_kw)})")
        elif self.format == "binary" and self.termination_code != "0":
            kw.append(f"convert=to_binary(termination_code={self.termination_code})")
        elif self.format in ("value", "binary", "ascii"):
            kw.append(f"convert=to_{self.format}")
        elif self.format == "none":
            # A TXT register copied to TXT: the code stands alone, with no converter.
            kw.extend(_termination_csv(self.termination_code))
        else:
            raise WriterError(f"Unknown format: {self.format!r}")

        if kw:
            return f"copy({','.join(parts)},{','.join(kw)})"
        return f"copy({','.join(parts)})"

    def cell_params(self) -> dict:
        """Return ClickCell kwargs intrinsic to this instruction."""
        return dict(_CELL_PARAMS)

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this copy cell."""
        from ..binary_helpers import _build_blob

        return _build_blob("Copy", 0x2721, _COPY_TAGS, self._tag_values())

    def _tag_values(self) -> list[str]:
        """The value of each tag in :data:`_COPY_TAGS`, as the encoder writes them."""
        # conversion_type (field[8]) and format_option (field[4]).
        conv_type, field4 = self._conversion()

        # Termination encoding: $hex → decimal for field[10], flag for [9].
        term_flag, term_char = _termination_tags(self.termination_code)
        # field[11]: CLICK v4's dialog writes -1 on every save and ignores it on
        # load; earlier versions set it only for a termination code.  We write -1 for
        # those and for a text constant source.
        text_flag = "-1" if term_flag == "-1" or _is_text_constant(self.source) else "0"

        return [
            self.source,  # [0]
            "",  # [1] source_end (single = empty)
            self.destination,  # [2]
            self._destination_end(),  # [3] destination_end (text: its last TXT)
            field4,  # [4] format_option
            "-1" if self.oneshot else "0",  # [5]
            "0",  # [6] copy_type_idx (single)
            self.func_code,  # [7]
            conv_type,  # [8] conversion_type
            term_flag,  # [9] termination_flag
            term_char,  # [10] termination_char (decimal)
            text_flag,  # [11] text_flag
            "",  # [12] terminator
        ]


# ---------------------------------------------------------------------------
# BlockCopy
# ---------------------------------------------------------------------------


def _asks_txt_choice(dest_bank: str) -> bool:
    """Whether a single Copy of a TXT register into ``dest_bank`` writes the character's
    value (to_value) or its ASCII code (to_ascii), one of which CLICK's dialog saves.

    That is every numeric register but DF: CLICK saves a TXT register into DF as a plain
    copy.
    """
    return dest_bank in _NUMERIC_DEST_BANKS and dest_bank != "DF"


#: Formats a block copy takes.
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
        ``"none"``, ``"value"`` (the characters' values) or ``"ascii"`` (their ASCII codes),
        for a TXT source into a numeric register.
    oneshot:
        Execute once on OFF→ON transition.
    termination_code:
        For a TXT range copied to TXT — ``"0"`` or ``"none"`` (no code; stored as ``"0"``),
        or ``"$HH"`` hex ASCII code, as a single Copy's.
    """

    source_start: str
    source_end: str
    dest_start: str
    dest_end: str
    format: str = "none"
    oneshot: bool = False
    termination_code: str = "0"

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            check.normalize("source_start", "source_end", "dest_start", "dest_end")
            if self.format not in _BLOCKCOPY_FORMATS:
                check.refuse(
                    "format", f"{self.format!r} is not allowed; it is none, value or ascii",
                    Reason.CHOICE,
                )  # fmt: skip
            _read_termination(check, self)
            cls = "BlockCopy"
            src, src_last = _check_range(
                check, "source_start", self.source_start, "source_end", self.source_end,
                _sources(_BLOCK_ROWS), one_module=True, bank_id="OBJ-004",
            )  # fmt: skip
            # CLICK fills in the destination end itself, so a one-address destination stays
            # unordered here and is refused below as an end that doesn't match.
            dest, dest_last = _check_range(
                check, "dest_start", self.dest_start, "dest_end", self.dest_end,
                _destinations(_BLOCK_ROWS), ordered=False, bank_id="OBJ-004",
            )  # fmt: skip
            if dest is not None:
                check.run(check_writable_sd, dest, check.field("dest_start"))
            if src is not None and dest is not None:
                check.run(
                    _check_row, cls, _BLOCK_ROWS, f"{self.source_start}..{self.source_end}",
                    "source_start", src.bank, "dest_start", self.dest_start, dest.bank,
                )  # fmt: skip
            if (
                src is not None and src_last is not None
                and dest is not None and dest_last is not None
                and not check.refused("source_end", "dest_end")
            ):  # fmt: skip
                # The destination end is the start plus the source's
                # element count (GetNextAddress), whatever the two banks.
                end = dest.number + src_last.number - src.number
                spans = ("source_start", "source_end")
                if dest.bank == "Y" and xy_slot(end) != xy_slot(dest.number):
                    # GetNextAddress steps a Y run on into the next slot; what CLICK then
                    # stores for the destination is not captured.
                    check.add(
                        _refusal(
                            cls,
                            ("dest_start", *spans),
                            f"{self.source_start}..{self.source_end} into "
                            f"{self.dest_start} crosses a Y slot; crossing a slot is not "
                            "supported yet: it needs a capture",
                            Reason.CONFLICT,
                        )
                    )
                if dest.bank == "SD" and not check.refused("dest_start"):
                    check.run(_check_sd_range, dest, end, (self.source_start, self.source_end))
                if dest_last.number != end:
                    spelled = Address(dest.bank, end).display
                    check.add(
                        _refusal(
                            cls,
                            ("dest_end", "dest_start", *spans),
                            f"{self.dest_end!r} is not where the copy ends; "
                            f"{self.source_start}..{self.source_end} fills "
                            f"{self.dest_start}..{spelled}",
                            Reason.CONFLICT,
                        )
                    )
            source = f"{self.source_start}..{self.source_end}"
            if self.format != "none" and src is not None and src.bank != "TXT":
                check.refuse(
                    ("format", "source_start", "source_end"),
                    f"to_{self.format} needs a TXT source, not {source}",
                    Reason.CONFLICT,
                )
            txt_to_txt = (
                src is not None and src.bank == "TXT" and dest is not None and dest.bank == "TXT"
            )
            if self.format != "none" and txt_to_txt:
                # CLICK's dialog offers TXT into TXT only Termination Code.
                check.refuse(
                    ("format", "dest_start"),
                    f"to_{self.format} copies TXT to a number, not {source} -> "
                    f"{self.dest_start}..{self.dest_end}",
                    Reason.CONFLICT,
                )
            if (
                self.format == "none"
                and src is not None and src.bank == "TXT"
                and dest is not None and dest.bank in _NUMERIC_DEST_BANKS
                and not check.refused("dest_start")
            ):  # fmt: skip
                # CLICK's dialog asks for Copy Character Value or Copy ASCII Code Value, as
                # for a single Copy, and saves one of them.
                check.refuse(
                    ("format", "source_start", "dest_start"),
                    f"{source} -> {self.dest_start}..{self.dest_end} needs convert=to_value "
                    "(the characters' values) or convert=to_ascii (their ASCII codes)",
                    Reason.CONFLICT,
                )
            if (
                self.termination_code != "0"
                and src is not None
                and dest is not None
                and not (txt_to_txt and self.format == "none")
            ):
                # CLICK's dialog offers Termination Code for a TXT range copied to TXT only.
                check.refuse(
                    ("termination_code", "source_start", "dest_start"),
                    f"{self.termination_code!r} needs a TXT range copied to TXT with no "
                    f"converter, not {source} -> {self.dest_start}..{self.dest_end} with "
                    f"format {self.format!r}",
                    Reason.CONFLICT,
                )
            _check_termination_form(check, self)
            check.flag("oneshot")

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
        kw.extend(_termination_csv(self.termination_code))
        if kw:
            return f"blockcopy({','.join(parts)},{','.join(kw)})"
        return f"blockcopy({','.join(parts)})"

    def cell_params(self) -> dict:
        """Return ClickCell kwargs intrinsic to this instruction."""
        return dict(_CELL_PARAMS)

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this block copy cell."""
        from ..binary_helpers import _build_blob

        conv_type = _FORMAT_TO_CONVTYPE.get(self.format, "0")
        term_flag, term_char = _termination_tags(self.termination_code)

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
                term_flag,  # [9] termination_flag
                term_char,  # [10] termination_char (decimal)
                term_flag,  # [11] text_flag: set with a termination code, as a single Copy's
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
        with Refusals(self) as check:
            check.normalize("value", "dest_start", "dest_end")
            kind = check("value", _source_kind, REGISTER_BANKS)
            # Fill runs the range check on the destination.
            dest, _ = _check_range(
                check, "dest_start", self.dest_start, "dest_end", self.dest_end,
                _REGISTER_DEST_BANKS, ids=False,
            )  # fmt: skip
            if kind is not None and dest is not None:
                check.run(
                    _check_pair, "Fill", "value", self.value, kind,
                    "dest_start", self.dest_start, dest.bank, _FILL_PAIRS,
                )  # fmt: skip
                if kind in ("number", "text"):
                    # A Fill into TXT takes one character of text.
                    text_max = 1 if dest.bank == "TXT" else TEXT_MAX
                    check("value", check_constant, replace(_CONSTANTS, text_max=text_max))
            check.flag("oneshot")

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
        return dict(_CELL_PARAMS)

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
        with Refusals(self) as check:
            check.normalize("source_start", "source_end", "destination")
            if self.pack_type not in _PACK_TYPES:
                check.refuse(
                    "pack_type",
                    f"{self.pack_type!r} is not allowed; it is bits, words or text",
                    Reason.CHOICE,
                )
            first, last = _check_range(
                check, "source_start", self.source_start, "source_end", self.source_end,
                _sources(_PACK_ROWS), one_module=True, module_id="OBJ-033",
            )  # fmt: skip
            # A bank no source packs into is one the field can't use (OBJ-004: X001, SD29 and
            # SD31 after C1..C16); a bank another source packs into is a pairing (OBJ-024).
            dest = check(
                "destination", check_box_operand, _destinations(_PACK_ROWS), bank_id="OBJ-004"
            )
            if first is not None and dest is not None:
                assert dest.bank is not None
                source = f"{self.source_start}..{self.source_end}"
                # The source's length comes before the pairing (_pack_limit).
                if last is not None and _pack_kind(first.bank) == self.pack_type:
                    paired = dest.bank in _source_row(_PACK_ROWS, first.bank)
                    check.run(
                        _check_count, "Pack", "source_start", "source_end", "destination",
                        source, _span(first, last), self.pack_type,
                        _pack_limit(self.pack_type, first.bank, dest.bank, paired),
                        self.destination if paired else None,
                    )  # fmt: skip
                check.run(
                    _check_row, "Pack", _PACK_ROWS, source, "source_start", first.bank,
                    "destination", self.destination, dest.bank,
                )  # fmt: skip
            if first is not None and not check.refused("pack_type"):
                if (first.bank == "TXT") != (self.pack_type == "text"):
                    check.add(
                        _refusal(
                            "Pack",
                            ("source_start", "pack_type"),
                            f"{self.source_start!r} is "
                            f"{'a TXT register' if first.bank == 'TXT' else 'not a TXT register'}; "
                            f"pack_{self.pack_type} "
                            f"{'takes a TXT source' if self.pack_type == 'text' else 'has no TXT source'}, "
                            f"{'pack_text' if first.bank == 'TXT' else 'pack_words or pack_bits'} does",
                            Reason.CONFLICT,
                        )
                    )
                if self.pack_type != "text":
                    check.run(
                        _check_kind, "Pack", "source_start", self.source_start, first.bank,
                        self.pack_type, "pack_type",
                    )  # fmt: skip
            check.flag("allow_whitespace", "oneshot")

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
        return dict(_CELL_PARAMS)

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
        with Refusals(self) as check:
            check.normalize("source", "dest_start", "dest_end")
            if self.unpack_type not in _UNPACK_TYPES:
                check.refuse(
                    "unpack_type",
                    f"{self.unpack_type!r} is not allowed; it is bits or words",
                    Reason.CHOICE,
                )
            # A bank no row holds is one the field can't use (OBJ-004): answered for an X
            # source, and for X, SC and SD destinations, as for a bank the source's row
            # leaves out (_ROW_IDS).
            src = check("source", check_box_operand, _sources(_UNPACK_ROWS), bank_id="OBJ-004")
            # The destination's start is paired with the source before the range's end is
            # read, so a pairing refusal comes ahead of the end's (OBJ-008, OBJ-009, OBJ-012,
            # the Y slot), and the end's fit with a refused start is not checked.
            banks = _destinations(_UNPACK_ROWS)
            first = check("dest_start", _range_end, banks, "OBJ-004")
            if src is not None and first is not None:
                assert src.bank is not None
                check.run(
                    _check_row, "Unpack", _UNPACK_ROWS, self.source, "source", src.bank,
                    "dest_start", self.dest_start, first.bank,
                )  # fmt: skip
            last = check("dest_end", _range_end, banks, "OBJ-004")
            if first is not None and last is not None:
                check.run(
                    _check_relation, "Unpack", "dest_start", self.dest_start, "dest_end",
                    self.dest_end, first, last, one_module=True, ordered=True,
                    module_id="OBJ-1009", ids=True,
                )  # fmt: skip
            if first is not None and not check.refused("unpack_type"):
                check.run(
                    _check_kind, "Unpack", "dest_start", self.dest_start, first.bank,
                    self.unpack_type, "unpack_type",
                )  # fmt: skip
                if last is not None and src is not None:
                    check.run(
                        _check_count, "Unpack", "dest_start", "dest_end", "source",
                        f"{self.dest_start}..{self.dest_end}", _span(first, last),
                        self.unpack_type, _count_limit(self.unpack_type, src.bank), self.source,
                    )  # fmt: skip
            check.flag("oneshot")

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
        return dict(_CELL_PARAMS)

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
    built = _from_tags(class_name, type_code, tags)
    if built is not None and _read_destination(tags) != tag_value(tags, 0x6076):
        # Decoded, it writes the bytes CLICK stored: the space, the text as typed.
        read_in_another_form(built)
    return built


def _edge_trimmed(tags: dict[int, str]) -> bool:
    """Whether the blob is a single Copy or a Pack, whose destination is read trimmed.

    CLICK saves a single Copy's and a Pack's destination with a space typed at its edge
    kept (" DS1", "DS1 "), and every other field trimmed: the address is read without it.
    """
    return tag_int(tags, 0x2223) in (0, 3)


def _read_destination(tags: dict[int, str]) -> str:
    """The destination (start) as it is read: trimmed (:func:`_edge_trimmed`), and for a
    single Copy, a Block Copy or a Pack, in display form.

    CLICK saves those destinations as typed (``DS001``, ``ds1``, ``YD0U``, ``DS[ds1]``)
    and every other address in display form.
    """
    destination = tag_value(tags, 0x6076)
    if _edge_trimmed(tags):
        destination = destination.strip(" ")
    if tag_int(tags, 0x2223) in (0, 1, 3):
        destination = read_as_typed(destination)
    return destination


def _from_tags(
    class_name: str, type_code: int, tags: dict[int, str]
) -> Copy | BlockCopy | Fill | Pack | Unpack | None:
    if class_name != "Copy" or type_code != _COPY_TYPE_CODE:
        return None

    source = tag_value(tags, 0x6074)
    source_end = tag_value(tags, 0x6075)
    destination = _read_destination(tags)
    destination_end = tag_value(tags, 0x6077)
    oneshot = tag_flag(tags, 0x11F8)
    copy_type = tag_int(tags, 0x2223)
    conv_type = tag_int(tags, 0x2227)

    if copy_type == 0:
        if not source or not destination:
            return None
        # A single copy has no source end, and a destination end only for text (checked
        # below); a blob that carries others isn't a shape CLICK writes, so leave it to
        # raw() rather than drop them.
        if source_end:
            return None
        opts = _CONVTYPE_TO_OPTS.get(str(conv_type))
        if opts is None:
            return None
        # Types that only exist for one source kind; anything else isn't a blob
        # CLICK writes, so leave it to raw() rather than re-encode it differently.
        if conv_type == 7 and not (
            _is_dd_df_pair(source, destination)
            or _converts_value(source, destination)
            or _wide_into_df(source, destination)
        ):
            return None
        if conv_type == 4 and not _real_text_source(source):
            return None
        fmt, suppress_zero, exponential = opts
        if fmt == "text" and _real_text_source(source):
            # No such option for a real source.
            suppress_zero = None

        termination_code = _read_termination_tags(tags)
        if termination_code is None:
            return None

        copy = Copy(
            source=source,
            destination=destination,
            format=fmt,
            oneshot=oneshot,
            suppress_zero=suppress_zero,
            exponential=exponential,
            termination_code=termination_code,
        )
        # The destination end follows from the text; an end that disagrees with it is
        # not a blob CLICK writes.  A number into a TXT address has either the end its text
        # fills, with the conversion type of its kind, or no end.
        number_end = _number_fill_end(copy.source, copy.destination)
        if number_end is not None and destination_end:
            if destination_end != number_end.display or conv_type not in _number_text_types(
                copy.source
            ):
                return None
        elif destination_end != copy._destination_end() and number_end is None:
            return None
        written = dict(zip(_COPY_TAGS, copy._tag_values(), strict=True))
        if (
            (conv_type, destination_end) != (int(written[0x2227]), written[0x6077])
            or (conv_type == 7 and not _is_dd_df_pair(source, destination))
            or (number_end is not None and destination_end)
        ):
            # The encoder writes another conversion type or end for these fields, or the
            # save is a type 7 other than DD to or from DF, or a number's end: unchanged,
            # the Copy writes the blob it was decoded from.
            read_in_another_form(copy)
        return copy

    if copy_type == 1:
        if not all([source, source_end, destination, destination_end]):
            return None
        fmt = {0: "none", 5: "value", 6: "ascii"}.get(conv_type)
        termination_code = _read_termination_tags(tags)
        if fmt is None or termination_code is None:
            return None
        return BlockCopy(
            source_start=source,
            source_end=source_end,
            dest_start=destination,
            dest_end=destination_end,
            format=fmt,
            oneshot=oneshot,
            termination_code=termination_code,
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


#: The keywords ``copy(...)`` and ``blockcopy(...)`` take besides their operands.
_COPY_KWARGS = frozenset({"convert", "oneshot", "termination_code"})


def _refuse_unknown_kwargs(name: str, kwargs: Mapping[str, str]) -> None:
    """Refuse a keyword ``copy`` or ``blockcopy`` does not take, so a misspelt one
    (``terminaton_code=``) is not dropped."""
    unknown = set(kwargs) - _COPY_KWARGS
    if unknown:
        raise CsvError(f"{name} does not support keyword argument(s): {sorted(unknown)}")


def _copy_from_csv(args: Sequence[str], kwargs: Mapping[str, str]) -> Copy:
    """Build a Copy from ``copy(source, dest, ...)`` arguments (both CSV paths)."""
    _refuse_unknown_kwargs("copy", kwargs)
    source, destination = args
    convert_raw = kwargs.get("convert", "")
    if convert_raw:
        fmt, text_opts = _parse_convert_kwarg(convert_raw)
    else:
        fmt, text_opts = "none", {}
    termination_code = text_opts.get("termination_code", "0")
    if kwargs.get("termination_code", "none") not in ("none", "0"):
        # A TXT register copied to TXT: the code stands alone, with no converter.  "none"
        # and "0" are no code, which any copy takes.
        if convert_raw:
            raise FieldError(
                f"Copy.termination_code: {kwargs['termination_code']!r} stands alone only "
                f"for TXT copied to TXT, with no converter, not beside {convert_raw}; a "
                "number copied to TXT takes it inside the converter "
                "(to_text(...,termination_code=$0D))",
                field=("Copy.termination_code", "Copy.format"),
                reason=Reason.CONFLICT,
            )
        termination_code = kwargs["termination_code"]
    if termination_code == "none":
        termination_code = "0"
    return Copy(
        source=source,
        destination=destination,
        format=fmt,
        oneshot=kwargs.get("oneshot") == "1",
        suppress_zero=text_opts.get("suppress_zero"),
        exponential=text_opts.get("exponential", "0"),
        termination_code=termination_code,
    )


def parse_af_call(call: AfCall) -> Copy | BlockCopy | Fill | Pack | Unpack:
    """Parse an AF AST call into a Copy-family instruction."""
    if call.name == "copy":
        if len(call.args) != 2:
            raise CsvError(f"copy expects 2 positional args (source, dest), got {len(call.args)}")
        return _copy_from_csv(call.args, call.kwargs)

    if call.name == "blockcopy":
        if len(call.args) != 2:
            raise CsvError(
                f"blockcopy expects 2 positional args (src_range, dest_range), got {len(call.args)}"
            )
        _refuse_unknown_kwargs("blockcopy", call.kwargs)
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
            termination_code=call.kwargs.get("termination_code", "0"),
        )

    if call.name == "fill":
        if len(call.args) != 2:
            raise CsvError(
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
            raise CsvError(
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
            raise CsvError(
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

    raise CsvError(f"Unsupported copy-family instruction: {call.name!r}")


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
    cell_params_from_tags=fixed_cell_params(_CELL_PARAMS, ("Copy", _COPY_TYPE_CODE)),
)
