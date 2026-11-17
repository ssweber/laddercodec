"""Copy family — single copy, block copy, fill, pack, and unpack (type marker 0x2721).

Binary class name: ``"Copy"``.

All five variants share the same binary class, discriminated by field[6]:

- ``0`` → single copy (``Copy``)
- ``1`` → block copy (``BlockCopy``)
- ``2`` → fill (``Fill``)
- ``3`` → pack (``Pack``)
- ``4`` → unpack (``Unpack``)

The fixture ``tests/fixtures/coverage/golden/copy__to_text_term.csv`` holds a copy to text
with the termination checkbox ticked. For that copy, CLICK's dialog greys out the termination
value. The blob still stores the flag and the character code as usual.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ..binary_helpers import tag_flag, tag_int, tag_value
from ..codes import Code
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
    check_csv_flag,
    check_kept_text,
    check_operand,
    check_writable_sd,
    constant_shape,
)
from ..operands.constants import (
    REAL_DIGITS,
    TEXT_MAX,
    Constant,
    Kind,
    classify,
    copy_real_display,
    real_beyond_kept_digits,
    significant_digits,
)
from ..operands.unchecked import read_in_another_form
from .family import AfInstructionFamilySpec, fixed_cell_params

if TYPE_CHECKING:
    from ..csv.ast import AfCall

#: Cell keyword arguments of every Copy-family box. The box is two rows tall, and the cell
#: header stores 2 at +0x09 and at +0x0A.
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

_VALID_CONVERTS = frozenset({None, "to_value", "to_text", "to_binary", "to_ascii"})

#: field[8] conversion_type → (convert, suppress_zero, exponential).
#: The conversion type also stores the options of a copy to text. An integer source is
#: type 1 with suppress zero or type 2 without it. A DF address, a DF pointer or a real
#: constant is type 3 with real numbering or type 4 with exponential numbering. Such a
#: source has no suppress zero option, and the decoder sets suppress_zero to None for it.
#: Type 7 converts a value between a real and a 32-bit integer (:func:`_converts_value`).
#: The CSV writes a type 7 copy as a plain copy.
_CONVTYPE_TO_OPTS: dict[str, tuple[str | None, bool, bool]] = {
    "0": (None, False, False),
    "1": ("to_text", True, False),  # integer source, suppress zeros
    "2": ("to_text", False, False),  # integer source, don't suppress zeros
    "3": ("to_text", True, False),  # DF source or real constant, real numbering
    "4": ("to_text", True, True),  # DF source or real constant, exponential numbering
    "5": ("to_value", False, False),
    "6": ("to_ascii", False, False),
    "7": (None, False, False),  # a real <-> a 32-bit integer
    "8": ("to_binary", False, False),
}

_DF_RE = re.compile(r"DF[0-9]+")
_DD_RE = re.compile(r"DD[0-9]+")


def _is_df(operand: str) -> bool:
    return _DF_RE.fullmatch(operand.strip()) is not None


def _real_text_source(source: str) -> bool:
    """Return whether CLICK's dialog offers real and exponential numbering, and no suppress
    zero, when ``source`` is copied to text. It does for a DF address or pointer and for a
    real constant."""
    return (
        _operand_bank(source, pointer=True) == "DF"
        or constant_shape(source, _CONSTANTS) is Kind.FLOAT
    )


def _is_dd_df_pair(source: str, destination: str) -> bool:
    """Return whether ``source`` and ``destination`` are a DD address and a DF address, in
    either order.

    For a single copy between these two, CLICK's dialog offers Copy Value or Copy Binary.
    """
    src, dst = source.strip(), destination.strip()
    return (_DD_RE.fullmatch(src) is not None and _is_df(dst)) or (
        _is_df(src) and _DD_RE.fullmatch(dst) is not None
    )


def _operand_bank(operand: str, *, pointer: bool = False) -> str | None:
    """Return the bank of ``operand`` read as an address, or None if it is not an address.

    With ``pointer``, also return the bank of a pointer such as ``DD[DS1]``."""
    try:
        return check_operand(operand, "Copy.source", pointer=pointer).bank
    except FieldError:
        return None


def _converts_value(source: str, destination: str) -> bool:
    """Return whether a single Copy of ``source`` into ``destination`` converts a value
    between a real and a 32-bit integer. CLICK saves such a copy as conversion type 7.

    This is true in two cases:

    - A copy from DF into DD or CTD, or from DD or CTD into DF. Either side may be an
      address or a pointer (``DD[DS1]`` into DF1, DF1 into ``CTD[DS1]``).
    - A real constant copied into DD or CTD, as an address or a pointer (``1.5`` into
      ``DD[DS1]``).
    """
    src, dst = _operand_bank(source, pointer=True), _operand_bank(destination, pointer=True)
    if (src == "DF" and dst in _INT32_BANKS) or (src in _INT32_BANKS and dst == "DF"):
        return True
    return constant_shape(source, _CONSTANTS) is Kind.FLOAT and dst in _INT32_BANKS


def _wide_into_df(source: str, destination: str) -> bool:
    """Return whether ``source`` is a decimal integer outside the int16 range and
    ``destination`` is a DF address or pointer. CLICK saves such a copy as conversion type 7.

    CLICK saves ``32768``, ``-32769``, ``65535`` and ``65536`` into DF1 as type 7. It saves
    ``2147483647`` into DF1 and into ``DF[DS1]`` as type 7. It saves ``32767`` and
    ``-32768`` as type 0.
    """
    const = classify(source)
    return (
        const is not None
        and const.kind is Kind.INTEGER
        and const.wide
        and _operand_bank(destination, pointer=True) == "DF"
    )


def _saves_type_7(source: str, destination: str) -> bool:
    """Return whether CLICK saves a plain single Copy of ``source`` into ``destination`` as
    conversion type 7, which is Copy Value. For the same pair, CLICK saves Copy Binary as
    type 8."""
    return (
        _is_dd_df_pair(source, destination)
        or _converts_value(source, destination)
        or _wide_into_df(source, destination)
    )


def _other_type_7(source: str, destination: str) -> bool:
    """Return whether CLICK saves type 7 for the pair and the pair is not a DD address and a
    DF address.

    The decoder marks a Copy of type 7 or 8 for such a pair so that, while it is unchanged,
    it encodes as the blob it was decoded from."""
    return _saves_type_7(source, destination) and not _is_dd_df_pair(source, destination)


#: Non-text convert → field[8] conversion_type.
_CONVERT_TO_CONVTYPE: dict[str | None, str] = {
    None: "0",
    "to_value": "5",
    "to_ascii": "6",
    "to_binary": "8",
}

#: Non-text convert → field[4] value.
_CONVERT_TO_FIELD4: dict[str | None, str] = {
    None: "0",
    "to_value": "0",
    "to_ascii": "1",
    "to_binary": "2",
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
    0x2223,  # [6]  copy_type_idx (0=single, 1=block, 2=fill, 3=pack, 4=unpack)
    0x3218,  # [7]  func_code
    0x2227,  # [8]  conversion_type (0=none, 1-4=text variants, 5=value, 6=ascii, 8=binary)
    0x1221,  # [9]  termination_flag (-1 = termination enabled)
    0x3216,  # [10] termination_char (decimal ASCII code, e.g. 19 = $13)
    0x1201,  # [11] text_flag (-1 = text constant source or termination enabled)
    0x0000,  # [12] terminator
)


def _is_text_constant(operand: str) -> bool:
    """Return True for a quoted text constant (``"Q"``) or an ASCII-code constant (``$00``).

    ``operand`` is a source that has already been checked, so a value in it that starts
    with ``$`` is a ``$hh`` code.
    """
    return operand.strip().startswith(('"', "$"))


def _ascii_code(code: int) -> str:
    """Return a character code as CLICK writes it: ``$`` and two hex digits (``$0D``)."""
    if not 0 <= code <= 0xFF:
        raise FieldError(
            f"Copy.termination_code: ASCII code {code} is outside 0 to 0xFF",
            field="Copy.termination_code",
            reason=Reason.RANGE,
            code=Code.INVALID_CHAR_CODE,
        )
    return f"${code:02X}"


_HEX_DIGITS = frozenset("0123456789ABCDEFabcdef")


def _is_one_digit_code(source: str) -> bool:
    """Return whether ``source`` is ``$`` and one hex digit (``$1``)."""
    return len(source) == 2 and source[0] == "$" and source[1] in _HEX_DIGITS


def _source_display(source: str, kind: Kind) -> str:
    """Return ``source`` in the form CLICK shows it, for a constant that a single Copy
    accepts as its source.

    - A decimal integer keeps its sign, including a typed ``+``, and loses its leading
      zeros. ``005`` becomes ``5``, and ``+5`` and ``+0`` stay as they are. Zero loses a
      ``-``, so ``-0`` becomes ``0``.
    - A hex constant has its digits in uppercase and keeps its leading zeros, followed by
      a lowercase ``h``. ``0ffh`` becomes ``0FFh``.
    - A real of at most 7 significant digits is printed back without a typed ``+``.
      ``1.50`` becomes ``1.5``, ``+1.5`` becomes ``1.5`` and ``1E5`` becomes
      ``100000.0``. See :func:`~laddercodec.operands.constants.copy_real_display`. The
      caller refuses a real with more digits before it calls this function.
    - Text and a character code are returned unchanged.
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


#: Hex constants that a single Copy reads as a real, in uppercase, each mapped to the real
#: that CLICK stores for it. It is not known whether CLICK reads any other hex constant
#: with an E (0EH, 01EH, E0H) as a real.
_REAL_HEX_WORDS = {"EH": "0.0", "1EH": "1.0"}


def _real_hex_refusal(source: str) -> str | None:
    """Return the reason a single Copy refuses ``source`` if it is a hex constant that CLICK
    reads as a real. Return None for any other ``source``."""
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
#: Registers that a copy can write to. That is every register except XD.
_REGISTER_DEST_BANKS = REGISTER_BANKS - {"XD"}
_NUMERIC_DEST_BANKS = _REGISTER_DEST_BANKS - {"TXT"}
_COPY_DEST_BANKS = _REGISTER_DEST_BANKS | {"Y", "C"}
#: A Copy source or a Fill value accepts a constant of any kind. Hex digits with a sign
#: before them (``+1h``) are read as a hex constant, and the field then refuses that
#: constant.
_CONSTANTS = Constants(ALL_KINDS, hex_sign=True)
#: The same constants, but a text may hold any character. A single Copy checks the
#: characters of its source after it checks the source against the destination
#: (:func:`_check_source_text`).
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
    """Return the bank letters that ``operand`` starts with (``CTD`` for ``CTD5``).

    The address does not have to be valid."""
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
    """Check ``value`` with ``check_operand`` for a field that does not accept a pointer, and
    return the checked operand.

    Every Copy-family field except the source and destination of a single Copy uses this
    check. A pointer raises ``AddressError`` with a message that says only a single Copy
    takes one.
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
            code=Code.POINTER_OUTSIDE_COPY,
        )
    return check_operand(value, name, banks, constants, bank_id=bank_id)


def _refusal(
    cls: str,
    attrs: tuple[str, ...],
    rule: str,
    reason: Reason,
    click_id: str | None = None,
    error: type[FieldError] = AddressError,
    *,
    code: Code,
) -> FieldError:
    """Return an ``error`` that refuses the field ``cls.attrs[0]``.

    The message is ``Class.attr: rule``, with CLICK's id in parentheses at the end when there
    is one. When the rule is about several fields, ``attrs`` lists them all, and the error's
    ``fields`` holds them all."""
    fields = tuple(f"{cls}.{attr}" for attr in attrs)
    tail = f" ({click_id})" if click_id else ""
    return error(
        f"{fields[0]}: {rule}{tail}", field=fields, reason=reason, click_id=click_id, code=code
    )


def _source_kind(value: str, name: str, banks: Collection[str], *, pointer: bool = False) -> str:
    """Return the kind of a Copy source or a Fill value: ``bit``, ``word``, ``txt``,
    ``number`` or ``text``.

    This function checks an address or a pointer. It leaves the limits of a constant to the
    caller. A Fill checks the value against its range first, and a single Copy checks the
    value of a constant after the destination. A ``$hh`` code is the exception, and this
    function checks it at once.
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
    """Return the position of ``address`` in its bank. ``XD0``, ``XD0u``, ``XD1`` ... are at
    positions 0, 1, 2 ..."""
    if address.bank in ("XD", "YD"):
        return 1 if address.upper else address.number + (address.number > 0)
    return address.number


def _span(first: Address, last: Address) -> int | None:
    """Return the number of addresses from ``first`` to ``last`` in one bank, or ``None`` for
    XD and YD.

    How CLICK counts across ``XD0u`` has not been checked, so an XD or YD range gets no
    count.
    """
    if first.bank in ("XD", "YD"):
        return None
    return last.number - first.number + 1


def _range_end(
    value: str, field: str, banks: Collection[str] | None, bank_id: str | None
) -> Address:
    """Check one end of a range and return its address. A pointer is refused."""
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
    """Refuse an end that does not fit its start.

    The end must be in the bank of the start. With ``ordered`` it must come after the
    start, and with ``one_module`` it must be in the same X or Y slot. The refusal names
    both fields, the end's field first."""
    pair = (end_field, start_field)
    if first.bank != last.bank:
        raise _refusal(
            cls,
            pair,
            f"{end!r} is not in the bank of {start!r}; both ends of a range are in one bank",
            Reason.CONFLICT,
            "OBJ-008" if ids else None,
            code=Code.RANGE_MIXED_BANKS,
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
            code=Code.RANGE_NOT_ASCENDING,
        )
    if one_module and first.bank in ("X", "Y") and xy_slot(first.number) != xy_slot(last.number):
        raise _refusal(
            cls,
            pair,
            f"{start}..{end} spans two {first.bank} slots; "
            f"the range stays in one 16-point {first.bank} slot",
            Reason.CONFLICT,
            module_id,
            code=Code.RANGE_CROSSES_SLOT,
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

    Both ends must be addresses in one bank (OBJ-008), and neither may be a pointer. With
    ``ordered``, the end must come after the start. An end before the start is OBJ-009,
    and an end at the start is OBJ-012. The Search instruction uses the same range check.

    With ``one_module``, an X or Y range must stay inside one 16-point slot of
    :data:`~laddercodec.model.XY_SLOTS`. ``module_id`` is CLICK's id for that refusal. The
    dual option slot, 21-36, counts as a slot of its own. The Pack source, the Block Copy
    source and the Unpack destination use this check.

    ``bank_id`` is CLICK's id for an end in a bank that the field does not accept. When the
    ends do not fit each other, the refusal names both fields, the end's field first. With
    ``ids=False`` the refusals leave out OBJ-008, OBJ-009 and OBJ-012. Use it for a dialog
    whose ids are not known.
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
    """Do the checks of :func:`check_range` through ``check`` and keep every refusal. Check
    each end on its own, and then the two ends together.

    Return both ends, with None for an end that was refused. The ends are returned even
    when the check of the two together refused them. That refusal names the end's field
    first.
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
    *,
    code: Code,
) -> None:
    """Refuse ``dest_bank`` if a source of kind ``kind`` cannot be copied into it. The
    refusal names the destination field first and the source field second."""
    allowed = pairs[kind]
    if dest_bank not in allowed:
        raise _refusal(
            cls,
            (dest_field, source_field),
            f"{destination!r} can't take {source!r}; "
            f"{_KIND_TEXT[kind]} copies to {_bank_list(allowed)}",
            Reason.CONFLICT,
            click_id,
            code=code,
        )


def _check_kind(
    cls: str, field_name: str, value: str, bank: str, kind: str, kind_field: str
) -> None:
    """Refuse ``bank`` if it does not suit ``kind``. A pack or unpack of ``bits`` needs a bit
    range, and one of ``words`` needs a register range.

    The blob stores no flag for bits or words. The decoder works out the kind from this
    bank. The refusal names the start of the range first and ``kind_field`` second.
    """
    if (kind == "bits") != (bank in BIT_BANKS):
        what = "a register" if kind == "bits" else "a bit"
        need = f"a bit bank ({_bank_list(BIT_BANKS)})" if kind == "bits" else "a register bank"
        raise _refusal(
            cls,
            (field_name, kind_field),
            f"{value!r} is {what}; {kind} needs {need}",
            Reason.CONFLICT,
            code=Code.PACK_KIND_MISMATCH,
        )


#: Most bits one register packs into or unpacks from.
_BITS_PER_REGISTER = {"DS": 16, "DH": 16, "DD": 32, "DF": 32}
#: Most bits any one pack moves.
_MAX_BITS = max(_BITS_PER_REGISTER.values())
#: Most words one pack or unpack moves.
_MAX_WORDS = 2
#: Most TXT characters that a pack of text can put into one DH. DH is the only destination
#: with a known limit.
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
    """Return the most bits, words or characters that one register of ``bank`` packs or
    unpacks, or None if there is no limit."""
    if kind == "bits":
        return _BITS_PER_REGISTER.get(bank or "")
    if kind == "text":
        return _DH_TEXT_CHARS if bank == "DH" else None
    return _MAX_WORDS


def _pack_kind(bank: str) -> str:
    """Return the kind of pack that a source in ``bank`` makes: ``text`` for TXT, ``bits``
    for a bit bank and ``words`` for any other bank."""
    if bank == "TXT":
        return "text"
    return "bits" if bank in BIT_BANKS else "words"


def _pack_limit(kind: str, source_bank: str, dest_bank: str, paired: bool) -> int | None:
    """Return the largest count that a Pack source of ``kind`` may have, or None for no
    limit. A Pack checks this count before it checks the pairing of source and destination.

    If the source can pack into the destination (``paired``), the limit is what the
    destination holds. If it cannot, a source of bits is limited to 32, the most that any
    destination holds, and a DH source is limited to two words. Any other source, such as
    DS, then has no limit.
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
    """Refuse a Pack source or an Unpack destination whose ``count`` is more than ``limit``.
    The refusal names the end of the range, then its start, then the field of the single
    register.

    ``single`` is the single register, and the message names it. If ``single`` is None,
    the message states the limit for every pack of ``kind``. A Pack passes None when its
    source cannot pack into its destination.
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
            code=Code.PACK_TOO_MANY,
        )


#: Source kind -> destination banks of a single Copy.
_COPY_PAIRS: dict[str, frozenset[str]] = {
    "bit": frozenset({"Y", "C"}),
    "word": _REGISTER_DEST_BANKS,
    "txt": _REGISTER_DEST_BANKS,
    "number": _REGISTER_DEST_BANKS,
    "text": frozenset({"TXT"}),
}

#: Source kind -> destination banks of a Fill. For a constant, the banks are the same as in
#: ``_COPY_PAIRS``. A numeric register fills only numeric registers, and a TXT register fills
#: only TXT.
_FILL_PAIRS: dict[str, frozenset[str]] = {
    "word": _NUMERIC_DEST_BANKS,
    "txt": frozenset({"TXT"}),
    "number": _REGISTER_DEST_BANKS,
    "text": frozenset({"TXT"}),
}


def _copy_dest_bank(kind: str | None, source: str, destination: str) -> tuple[str | None, Code]:
    """Return CLICK's id and the code for a single Copy destination in a bank that a Copy
    does not write.

    A ``$hh`` character code copies to TXT only. CLICK refuses it in any other bank as an
    address that the instruction cannot use (OBJ-004), for example ``$41`` into X001 or
    XD0. CLICK gives the same id when it refuses a ``$hh`` code paired with a register.

    The only bit banks that a Copy writes are Y and C. In X, T, CT and SC, an address
    outside the range of its bank is OBJ-004 from any source (DS2 into X017, T501, CT251 or
    SC1001). For an address inside the range, CLICK refuses a bit source as an address that
    the instruction cannot use (OBJ-004), for example X001 into X001, or C1 into SC50 or
    SC303. It refuses any other source as a pairing of kinds (OBJ-024), for example DS2 or
    5 into X001. OBJ-024 is also the id of every other pairing that a single Copy refuses.
    XD is the one register bank that a Copy does not write. For a source other than a ``$hh``
    code, CLICK's id depends on the source (OBJ-004 for most, OBJ-024 for a bit, a text or
    10000h), and this function returns no id.

    If the source is refused, this function returns no id. That happens for an address
    that ``_source_kind`` refuses (``kind`` is None). It also happens for a constant that
    the source's own check refuses later, because it is out of range or holds characters
    that CLICK does not keep. That refusal comes after the destination's.

    The code is ``bank-not-allowed``, except for two pairings. A constant into a bit,
    including a ``$hh`` code, is ``constant-into-bit``. A register into a bit is
    ``copy-bank-incompatible``.
    """
    if kind is None:
        return None, Code.BANK_NOT_ALLOWED
    if kind in ("number", "text"):
        try:
            _check_source_text(source, "Copy.source")
        except FieldError:
            return None, Code.BANK_NOT_ALLOWED
    in_bit_bank = _bank_prefix(destination) in BIT_BANKS
    if source.startswith("$"):
        return "OBJ-004", Code.CONSTANT_INTO_BIT if in_bit_bank else Code.BANK_NOT_ALLOWED
    if not in_bit_bank:
        return None, Code.BANK_NOT_ALLOWED
    if kind == "bit" or not _in_its_bank(destination):
        return "OBJ-004", Code.BANK_NOT_ALLOWED
    if kind in ("number", "text"):
        return "OBJ-024", Code.CONSTANT_INTO_BIT
    return "OBJ-024", Code.COPY_BANK_INCOMPATIBLE


def _check_copy_destination(destination: str, field: str, source: str, kind: str | None) -> Operand:
    """Check a single Copy destination and return it. It must be an address or a pointer in
    a bank that a Copy writes.

    A ``$hh`` code copies to TXT only. CLICK refuses it into a pointer of any other bank
    (``X[DS1]``, ``XD[DS1]``, ``SD[DS1]``) as an address that the instruction cannot use
    (OBJ-004). It refuses it into an address of another bank in the same way.
    """
    bank_id, bank_code = _copy_dest_bank(kind, source, destination)
    try:
        return check_operand(
            destination, field, _COPY_DEST_BANKS, pointer=True,
            bank_id=bank_id, bank_code=bank_code,
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
            f"{exc} (OBJ-004)",
            field=exc.fields,
            reason=exc.reason,
            click_id="OBJ-004",
            code=exc.code,
        ) from None


def _is_pointer(value: str, field: str) -> bool:
    """Return whether ``value`` is a pointer ``BANK[DSn]``, a bank name with a DS address in
    brackets."""
    bank, bracket, index = value.partition("[")
    if not bracket or bank not in ADDRESS_BANKS or not index.endswith("]"):
        return False
    try:
        return check_address(index[:-1], field).bank == "DS"
    except AddressError:
        return False


def _in_its_bank(address: str) -> bool:
    """Return whether ``address`` is a valid CLICK address, with its number inside the range
    of its bank."""
    try:
        check_address(address, "Copy.dest")
    except AddressError:
        return False
    return True


def _check_source_value(source: str, field: str) -> Constant:
    """Check the value of a single Copy's constant source and return it. This check does not
    look at the characters of a text.

    CLICK refuses these as values, with OBJ-005, the id it gives a hex constant above
    FFFFFFFFh:

    - an empty text;
    - a text of more than 128 characters;
    - a signed hex constant (``-FFh``);
    - a hex constant of more than 8 digits (``0FFFFFFFFh``).

    Whether CLICK refuses a text with a quote inside it, and with which id, is not known.
    This function refuses it with no id.
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
            f"{exc} (OBJ-005)",
            field=exc.fields,
            reason=exc.reason,
            click_id="OBJ-005",
            code=exc.code,
        ) from None


def _check_source_text(source: str, field: str) -> Constant:
    """Check a single Copy's constant source, including the characters of a text, and
    return it. A text may hold only characters that CLICK keeps
    (:func:`~laddercodec.operands.checks.check_kept_text`)."""
    const = check_constant(source, field, _ANY_TEXT)
    if const.kind is Kind.TEXT:
        check_kept_text(source, str(const.value), field)
    return const


#: The 32-bit integer registers.
_INT32_BANKS = frozenset({"DD", "CTD"})
#: The banks that a single Copy can copy a hex constant above FFFFh into: the 32-bit
#: integer registers. CLICK refuses any other bank with OBJ-024.
_HEX32_DEST_BANKS = _INT32_BANKS


def _check_hex32(source: str, dest_field: str, destination: str, dest_bank: str) -> None:
    """Refuse a hex constant above FFFFh if ``dest_bank`` is not a 32-bit integer
    register."""
    shape = constant_shape(source, _CONSTANTS)
    if shape is Kind.HEX and int(source[:-1], 16) > 0xFFFF and dest_bank not in _HEX32_DEST_BANKS:
        raise _refusal(
            "Copy",
            (dest_field, "source"),
            f"{destination!r} can't take {source!r}; a hex constant above "
            f"FFFFh copies to {_bank_list(_HEX32_DEST_BANKS)}",
            Reason.CONFLICT,
            "OBJ-024",
            code=Code.COPY_BANK_INCOMPATIBLE,
        )


#: The last TXT register.
_TXT_LAST = ADDRESS_BANKS["TXT"][1]


def _text_fill_end(source: str, destination: str) -> Address | None:
    """Return the last TXT register that a single Copy of quoted text fills. The blob
    stores it as the destination end (tag 0x6077).

    CLICK stores the end for two or more characters: ``"TT"`` into TXT1 stores TXT2. It
    leaves the end empty for one character (``"Q"`` into TXT2) and for a ``$hh`` code.
    Return ``None`` for those. Also return ``None`` for a pointer destination, because
    CLICK stores no end for a pointer, whatever the length (``copy("AB",TXT[DS1])``).
    """
    if not (len(source) >= 4 and source[0] == source[-1] == '"'):
        return None
    # The destination is a TXT address or pointer, because text copies only to TXT.
    first = check_operand(destination, "Copy.dest", pointer=True)
    if first.address is None:
        return None
    return Address("TXT", first.address.number + len(source) - 3)


#: The constant kinds a single Copy writes into TXT as their text.
_NUMBER_KINDS = frozenset({Kind.INTEGER, Kind.HEX, Kind.FLOAT})


def _number_fill_end(source: str, destination: str) -> Address | None:
    """Return the last TXT register that a single Copy fills when it copies a number constant
    into a TXT address as text. CLICK saves this register as the destination end (tag
    0x6077).

    The text is the constant as stored, including an ``h`` and a ``+``, and each character
    fills one TXT register. Copied into TXT1, ``-5``, ``1h`` and ``+5`` end in TXT2, ``10h``
    and ``1.5`` in TXT3, ``0FFh`` in TXT4, ``FFFFh`` in TXT5 and ``2147483647`` in TXT10.
    The function also returns an end past TXT1000, which CLICK refuses: ``-5`` into TXT1000
    ends in TXT1001, and CLICK gives OBJ-003.

    Return ``None`` for a constant of one character (``5`` into TXT1, which CLICK saves with
    no end) and for a pointer (``1.5`` into ``TXT[DS1]``, also saved with no end). Also
    return ``None`` for any other source or destination.
    """
    if len(source) < 2 or constant_shape(source, _CONSTANTS) not in _NUMBER_KINDS:
        return None
    try:
        first = check_operand(destination, "Copy.dest").address
    except FieldError:
        return None
    if first is None or first.bank != "TXT":
        return None
    return Address("TXT", first.number + len(source) - 1)


def _number_text_types(source: str) -> frozenset[int]:
    """Return the conversion types that CLICK saves with the end of a number constant copied
    into TXT: 3 or 4 (real or exponential numbering) for a real, and 1 or 2 (zeros
    suppressed or not) for an integer or hex constant."""
    if constant_shape(source, _CONSTANTS) is Kind.FLOAT:
        return frozenset({3, 4})
    return frozenset({1, 2})


# ---------------------------------------------------------------------------
# Block, Pack and Unpack pairs (pairing table)
# ---------------------------------------------------------------------------

#: A table of pairing rows. Each row holds source banks and the destination banks they copy
#: to. The first row that holds the source bank applies, and a destination outside that row
#: is refused.
_Rows = tuple[tuple[frozenset[str], frozenset[str]], ...]

_NUMERIC_BITS = frozenset({"X", "Y", "T", "CT", "SC"})

#: Block Copy rows. CLICK's source and destination fields refuse every bank that is not in
#: these rows (OBJ-004). XD, YD, TD and CTD cannot be a source, and X, T, CT, SC, XD and YD
#: cannot be a destination.
_BLOCK_ROWS: _Rows = (
    (BIT_BANKS, frozenset({"Y", "C"})),
    (frozenset({"DS", "DD", "DH", "DF", "SD"}), frozenset({"DS", "DD", "DH", "DF", "TD", "CTD", "SD"})),
    (frozenset({"TXT"}), frozenset({"DS", "DD", "DH", "TXT"})),
)  # fmt: skip
#: Pack rows. X, Y, T, CT and SC bits pack into DH only. C bits pack into any 16-bit or
#: 32-bit word.
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


#: CLICK's id for a destination bank that the source's row leaves out. For an Unpack, the
#: destination field gives OBJ-004 for every bank that the source greys out, except Y
#: (:data:`_UNPACK_Y_ID`). Block Copy and Pack give OBJ-024, the id for a pairing of kinds.
_ROW_IDS = {"BlockCopy": "OBJ-024", "Pack": "OBJ-024", "Unpack": "OBJ-004"}
#: CLICK's id for an Unpack into Y from a source other than DH. CLICK refuses it as a
#: pairing of kinds.
_UNPACK_Y_ID = "OBJ-024"


def _source_row(rows: _Rows, source_bank: str) -> frozenset[str]:
    """Return the destination banks of the first row that holds ``source_bank``."""
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
    """Refuse ``dest_bank`` if the pairing row of ``source_bank`` leaves it out. The refusal
    names the destination field first and the source field second."""
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
            code=Code.COPY_BANK_INCOMPATIBLE,
        )


#: The last SD register a Copy writes.
_LAST_WRITABLE_SD = max(WRITABLE_SD)


def _check_sd_range(dest: Address, end: int, source: tuple[str, str]) -> None:
    """Refuse a Block Copy into SD whose range holds an SD register that is not writable.

    The start ``dest`` is writable, and ``end`` is the last register that the source's
    length fills. The refusal names the destination start, then the source start and end.

    CLICK gives OBJ-018 when every unwritable SD in the range is below SD215, and OBJ-004
    when every one is above it. It gives no id when the range holds both.
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
        code=Code.NOT_WRITABLE,
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
    """Parse a ``convert=`` kwarg value, returning *(convert, text_opts)*.

    Examples: ``to_value``, ``to_text(exponential=1)``.
    """
    m = _CONVERT_CALL_RE.fullmatch(raw.strip())
    if not m:
        raise CsvError(
            f"Could not read convert={raw}. Write to_value, to_ascii, to_text(...) or "
            "to_binary(...), such as convert=to_value."
        )

    fmt = m.group(1)  # "text", "value", "binary", "ascii"
    inner = (m.group(2) or "").strip()

    if fmt not in ("text", "binary"):
        if inner:
            raise CsvError(f"to_{fmt} takes no arguments: {raw!r}")
        return f"to_{fmt}", {}

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
                    field="Copy.convert",
                    reason=Reason.CHOICE,
                    code=Code.INVALID_CHOICE,
                )
            text_opts[k] = v.strip()

    return f"to_{fmt}", text_opts


def _parse_range(arg: str) -> tuple[str, str]:
    """Split ``"A..B"`` into ``("A", "B")``."""
    if ".." not in arg:
        raise CsvError(f"Expected range with '..': {arg!r}")
    parts = [p.strip() for p in arg.split("..")]
    if len(parts) != 2 or not all(parts):
        raise CsvError(
            f"Could not read the range {arg!r}. Write two addresses joined by '..', such as "
            "DS1..DS10."
        )
    return parts[0], parts[1]


# ---------------------------------------------------------------------------
# Termination code (single Copy and Block Copy)
# ---------------------------------------------------------------------------


def _read_termination(check: Refusals, inst: Copy | BlockCopy) -> None:
    """Rewrite ``inst.termination_code`` in one form: ``$`` and two uppercase hex digits, or
    ``"0"`` for no code. A code may arrive in another form, such as ``$0d`` from CSV.

    ``"none"`` is the CSV form of no code, and ``to_csv`` writes it. A blank code is
    refused.
    """
    if inst.termination_code == "":
        check.refuse(
            "termination_code",
            "is blank; it needs a code, or 'none' for no code",
            Reason.MISSING,
            code=Code.BLANK_FIELD,
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
    """Refuse a termination code that is neither a character code nor ``"0"``. The blob can
    store only a character code."""
    if not inst.termination_code.startswith("$") and inst.termination_code != "0":
        check.refuse(
            "termination_code",
            f"{inst.termination_code!r} is not allowed; it is a "
            "character code ($0D), or '0' or 'none' for no code",
            Reason.FORM,
            "OBJ-036",
            code=Code.INVALID_CHAR_CODE,
        )


def _termination_tags(termination_code: str) -> tuple[str, str]:
    """Return the values of tags 0x1221 (the termination flag) and 0x3216 (the code in
    decimal) for ``termination_code``."""
    if termination_code != "0" and termination_code.startswith("$"):
        return "-1", str(int(termination_code[1:], 16))
    return "0", "0"


def _read_termination_tags(tags: dict[int, str]) -> str | None:
    """Return the termination code that a blob stores: ``"0"`` for none, or ``$hh``. Return
    None if the stored code is not a decimal number.

    Only tag 0x1221 shows that termination is on. Tag 0x1201 is also set for a text
    constant source, so it does not mean that there is a code. CLICK leaves 0x3216 out for
    the code ``$00``.
    """
    term_char = tag_value(tags, 0x3216)
    if not (tag_flag(tags, 0x1221) and term_char):
        return "0"
    if not (term_char.isascii() and term_char.isdigit()):
        return None
    return _ascii_code(int(term_char))


def _termination_csv(termination_code: str) -> list[str]:
    """Return the ``termination_code=`` keyword of a Copy with no converter or of a Block
    Copy, as a list. Return an empty list for no code."""
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
    dest:
        Destination operand (e.g. ``"DS8"``).
    convert:
        The converter, by its CSV name: ``None`` (a plain copy), ``"to_value"``,
        ``"to_text"``, ``"to_binary"`` or ``"to_ascii"``. A TXT register copied into a
        numeric register other than DF needs ``"to_value"`` or ``"to_ascii"``, and ``None``
        is refused for it.
    oneshot:
        Execute once on OFF→ON transition.
    suppress_zero:
        The suppress zero option of a copy to text, for an integer, hex or register
        source. ``True`` suppresses zeros and ``False`` does not. ``None`` is read as
        ``False``. A DF source or a real constant copied with ``"to_text"`` has no such
        option. For it the attribute holds ``None``, and any other value is refused. A TXT
        source refuses ``True``.
    exponential:
        The numbering option of a copy to text, for a DF source or a real constant:
        ``False`` for real numbering and ``True`` for exponential. Any other source has no
        such option and refuses ``True``.
    termination_code:
        The termination code. Only a number register copied to text (with ``"to_text"`` or
        ``"to_binary"``) and a TXT register copied to TXT (with ``None``) accept one. The
        value is ``"0"`` or ``"none"`` for no code, stored as ``"0"``. Otherwise it is a hex
        ASCII code ``"$HH"`` with exactly two digits: ``"$0D"`` is 0x0D, and ``"$D"`` is
        refused. A lowercase code is stored in uppercase (``"$0d"`` as ``"$0D"``).
    """

    source: str
    dest: str
    convert: str | None = None
    oneshot: bool = False
    suppress_zero: bool | None = None
    exponential: bool = False
    termination_code: str = "0"

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            # normalize_address returns a constant as it was written.
            check.normalize("source", "dest")
            if _is_one_digit_code(self.source):
                # A single Copy accepts $ and one hex digit as a character code. CLICK
                # stores it with two digits, so $1 becomes $01.
                self.source = f"$0{self.source[1]}"
            elif (why := _real_hex_refusal(self.source)) is not None:
                check.refuse("source", why, Reason.FORM, code=Code.COPY_HEX_READS_AS_REAL)
            if self.convert not in _VALID_CONVERTS:
                check.refuse(
                    "convert",
                    f"{self.convert!r} is not allowed; it is None, 'to_value', 'to_text', "
                    "'to_binary' or 'to_ascii'",
                    Reason.CHOICE,
                    code=Code.INVALID_CHOICE,
                )
            _read_termination(check, self)
            # A suppress_zero of None means False, except for a real source copied to text,
            # which has no suppress zero option.
            if self.suppress_zero is None and not (
                self.convert == "to_text" and _real_text_source(self.source)
            ):
                self.suppress_zero = False
            if self.suppress_zero is None:
                check.flag("exponential")
            else:
                check.flag("suppress_zero", "exponential")
            # Check in CLICK's order: the source address, the destination address, the value
            # of a source constant, the pairing of source and destination, and then an SD
            # register that a Copy does not write.
            kind = check("source", _source_kind, BIT_BANKS | REGISTER_BANKS, pointer=True)
            dst = check("dest", _check_copy_destination, self.source, kind)
            const = None
            if kind in ("number", "text"):
                # Check the value before the pairing. CLICK refuses "" and 100000000h into
                # DS1 as values (OBJ-005). The characters of a text are checked at the end.
                # CLICK refuses "é" into DS1 with OBJ-024.
                const = check("source", _check_source_value)
            if kind is not None and dst is not None:
                assert dst.bank is not None
                # CLICK refuses a $hh code into any bank except TXT with OBJ-004, and any
                # other pairing with OBJ-024.
                pair_id = "OBJ-004" if self.source.startswith("$") else "OBJ-024"
                into_bit = kind in ("number", "text") and dst.bank in BIT_BANKS
                pair_code = Code.CONSTANT_INTO_BIT if into_bit else Code.COPY_BANK_INCOMPATIBLE
                check.run(
                    _check_pair, "Copy", "source", self.source, kind,
                    "dest", self.dest, dst.bank, _COPY_PAIRS, pair_id, code=pair_code,
                )  # fmt: skip
                if kind == "number":
                    check.run(_check_hex32, self.source, "dest", self.dest, dst.bank)
            if dst is not None and dst.address is not None:
                # A Copy writes only the writable SD registers (OBJ-004). This check comes
                # after the pairing: CLICK gives OBJ-024, not OBJ-004, for a bit, quoted
                # text or 10000h into SD1.
                check.run(check_writable_sd, dst.address, check.field("dest"), click_id="OBJ-004")
            if kind is not None and dst is not None:
                assert dst.bank is not None
                self._check_format(check, kind, dst.bank)
                if self.termination_code != "0" and not (
                    (
                        self.convert in ("to_text", "to_binary")
                        and kind == "word"
                        and dst.bank == "TXT"
                    )
                    or (self.convert is None and kind == "txt" and dst.bank == "TXT")
                ):
                    # CLICK's dialog offers Termination Code for a number register copied to
                    # text and for a TXT register copied to TXT. It greys out the box for a
                    # constant copied to TXT.
                    check.refuse(
                        ("termination_code", "convert", "source", "dest"),
                        f"{self.termination_code!r} needs a numeric register copied to TXT "
                        "with to_text or to_binary, or a TXT register copied to TXT, not "
                        f"{self.source!r} -> {self.dest!r} with convert {self.convert!r}",
                        Reason.CONFLICT,
                        code=Code.OPTION_NOT_OFFERED,
                    )
            if kind == "txt" and self.suppress_zero is True:
                # CLICK's dialog greys out Suppress zero for a TXT source, whether the
                # destination is a number register or TXT.
                check.refuse(
                    ("suppress_zero", "source"),
                    f"suppress_zero=1 is not an option for {self.source!r}; suppress zero is "
                    "for a number copied to text",
                    Reason.CONFLICT,
                    code=Code.OPTION_NOT_OFFERED,
                )
            if self.convert == "to_text":
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
                            code=Code.OPTION_NOT_OFFERED,
                        )
                elif self.exponential is True:
                    check.refuse(
                        ("exponential", "source"),
                        "to_text(exponential=1) needs a DF source or a real constant, not "
                        f"{self.source!r}; an integer source only has suppress_zero",
                        Reason.CONFLICT,
                        code=Code.OPTION_NOT_OFFERED,
                    )
            _check_termination_form(check, self)
            if const is not None:
                const = check("source", _check_source_text)
            kept = None
            if const is not None and const.kind is Kind.FLOAT:
                kept = real_beyond_kept_digits(self.source)
            if kept is not None:
                # CLICK keeps 7 significant digits of a real. It cuts a real with more
                # digits when it saves it.
                check.refuse(
                    "source",
                    f"{self.source!r} has {significant_digits(self.source)} significant "
                    f"digits; CLICK keeps {REAL_DIGITS} significant digits: write {kept}",
                    Reason.FORM,
                    code=Code.INVALID_CONSTANT,
                )
            elif const is not None:
                # Write the source in the form that CLICK stores.
                self.source = _source_display(self.source, const.kind)
            if not check.refused("source", "dest"):
                # CLICK's dialog shows the last TXT that a text fills, such as TXT1001. It
                # refuses an end past TXT1000 as out of range.
                end = _text_fill_end(self.source, self.dest)
                if end is not None and end.number > _TXT_LAST:
                    check.add(
                        _refusal(
                            "Copy",
                            ("dest",),
                            f"{self.dest!r} can't take {self.source!r}; its "
                            f"{len(self.source) - 2} characters fill "
                            f"{self.dest}..{end.display}, past TXT{_TXT_LAST}",
                            Reason.RANGE,
                            "OBJ-003",
                            code=Code.TEXT_PAST_BANK,
                        )
                    )
                end = _number_fill_end(self.source, self.dest)
                if self.convert == "to_text" and end is not None and end.number > _TXT_LAST:
                    check.add(
                        _refusal(
                            "Copy",
                            ("dest",),
                            f"{self.dest!r} can't take {self.source!r} as text; it "
                            f"fills {self.dest}..{end.display}, past TXT{_TXT_LAST}",
                            Reason.RANGE,
                            "OBJ-003",
                            code=Code.TEXT_PAST_BANK,
                        )
                    )
            check.flag("oneshot")

    def _destination_end(self) -> str:
        """Return the value of tag 0x6077: the last TXT that a text of two or more characters
        fills, or an empty string.

        A number constant copied with ``"to_text"`` fills TXT registers with its own text,
        as CLICK saves it. The end counts the characters of the constant as stored,
        including an ``h`` and a ``+``. ``-5`` into TXT1 ends in TXT2, ``0FFh`` in TXT4 and
        ``1.5`` in TXT3.
        """
        end = _text_fill_end(self.source, self.dest)
        if end is None and self.convert == "to_text":
            end = _number_fill_end(self.source, self.dest)
        return "" if end is None else end.display

    def _conversion(self) -> tuple[str, str]:
        """Return the values that the encoder writes for tags 0x2227 (conversion type) and
        0x2206 (format option), given the fields of this Copy."""
        # field[4] is the index of the radio button chosen in the dialog. CLICK v4 ignores
        # it when it loads the blob.
        if self.convert == "to_text":
            if _real_text_source(self.source):
                exp = int(self.exponential)
                return str(3 + exp), str(exp)
            sz = 1 if self.suppress_zero is True else 0
            return str(2 - sz), str(1 - sz)
        if self.convert in (None, "to_binary") and _saves_type_7(self.source, self.dest):
            # Copy Value (7) or Copy Binary (8, with 0x2206 set).
            return ("7", "0") if self.convert is None else ("8", "1")
        return _CONVERT_TO_CONVTYPE[self.convert], _CONVERT_TO_FIELD4[self.convert]

    def _check_format(self, check: Refusals, kind: str, dest_bank: str) -> None:
        """Refuse a converter the source and destination kinds don't offer."""
        convert = self.convert
        if convert == "to_binary" and _saves_type_7(self.source, self.dest):
            return  # Copy Binary is allowed for a copy between a real and a 32-bit integer.
        if convert is None and kind in ("word", "number") and dest_bank == "TXT":
            # CLICK's dialog saves a number copied to TXT either as its text (Copy Value,
            # with Suppress zero by default) or as binary. It never saves a plain copy here.
            option = "exponential=0" if _real_text_source(self.source) else "suppress_zero=1"
            check.refuse(
                ("convert", "source", "dest"),
                f"{self.source!r} -> {self.dest!r} needs a converter: "
                f"convert=to_text({option},termination_code=none), CLICK's default, or "
                "convert=to_binary",
                Reason.CONFLICT,
                code=Code.COPY_TXT_NEEDS_CONVERT,
            )
            return
        if convert in ("to_value", "to_ascii") and kind == "txt" and dest_bank == "DF":
            # CLICK's dialog offers no converter for TXT into DF, and saves a plain copy.
            check.refuse(
                ("convert", "source", "dest"),
                f"{convert} is not an option for {self.source!r} -> {self.dest!r}; "
                "CLICK copies TXT into DF with no converter",
                Reason.CONFLICT,
                code=Code.COPY_CONVERTER_BANK,
            )
            return
        if convert is None and kind == "txt" and _asks_txt_choice(dest_bank):
            # CLICK's dialog asks for Copy Character Value or Copy ASCII Code Value, and
            # saves one of them. It never saves a plain copy here.
            check.refuse(
                ("convert", "source", "dest"),
                f"{self.source!r} -> {self.dest!r} needs convert=to_value (the "
                "character's value) or convert=to_ascii (its ASCII code)",
                Reason.CONFLICT,
                code=Code.COPY_TXT_NEEDS_CONVERT,
            )
            return
        if convert == "to_text":
            ok, need = kind in ("word", "number") and dest_bank == "TXT", "a number to TXT"
        elif convert == "to_binary":
            ok = kind in ("word", "number") and dest_bank == "TXT"
            need = "a number to TXT, or a value between a real and a 32-bit integer (DF1 -> DD1)"
        elif convert in ("to_value", "to_ascii"):
            ok, need = kind == "txt" and dest_bank in _NUMERIC_DEST_BANKS, "TXT to a number"
        else:
            return
        if not ok:
            check.refuse(
                ("convert", "source", "dest"),
                f"{convert} copies {need}, not {self.source!r} -> {self.dest!r}",
                Reason.CONFLICT,
                code=Code.COPY_CONVERTER_BANK,
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
            raise CsvError(
                f"Could not read {token!r} as a copy. Write it as copy(source,dest), such as "
                "copy(DS1,DS2)."
            )

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
        parts = [self.source, self.dest]
        kw: list[str] = []
        if self.oneshot:
            kw.append("oneshot=1")

        if self.convert == "to_text":
            # Write only the option that this source offers.
            option = (
                f"exponential={1 if self.exponential else 0}"
                if _real_text_source(self.source)
                else f"suppress_zero={1 if self.suppress_zero else 0}"
            )
            text_kw = [
                option,
                f"termination_code={'none' if self.termination_code == '0' else self.termination_code}",
            ]
            kw.append(f"convert=to_text({','.join(text_kw)})")
        elif self.convert == "to_binary" and self.termination_code != "0":
            kw.append(f"convert=to_binary(termination_code={self.termination_code})")
        elif self.convert in ("to_value", "to_binary", "to_ascii"):
            kw.append(f"convert={self.convert}")
        elif self.convert is None:
            # Only a TXT register copied to TXT has a code here. The code is written as its
            # own keyword, with no converter.
            kw.extend(_termination_csv(self.termination_code))
        else:
            raise WriterError(f"Unknown convert: {self.convert!r}")

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
        """Return the value of each tag in :data:`_COPY_TAGS`, as the encoder writes it."""
        # conversion_type (field[8]) and format_option (field[4]).
        conv_type, field4 = self._conversion()

        # Termination encoding: $hex → decimal for field[10], flag for [9].
        term_flag, term_char = _termination_tags(self.termination_code)
        # field[11]: CLICK v4's dialog writes -1 on every save and ignores the field when
        # it loads the blob. Earlier versions set it only for a termination code. The
        # encoder writes -1 for a termination code and for a text constant source.
        text_flag = "-1" if term_flag == "-1" or _is_text_constant(self.source) else "0"

        return [
            self.source,  # [0]
            "",  # [1] source_end (single = empty)
            self.dest,  # [2]
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
    """Return whether CLICK's dialog asks what a single Copy of a TXT register into
    ``dest_bank`` writes: the character's value (``to_value``) or its ASCII code
    (``to_ascii``). The dialog saves one of the two.

    It asks for every numeric register except DF. CLICK saves a TXT register copied into
    DF as a plain copy.
    """
    return dest_bank in _NUMERIC_DEST_BANKS and dest_bank != "DF"


#: Converters a block copy takes.
_BLOCKCOPY_CONVERTS = frozenset({None, "to_value", "to_ascii"})


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
    convert:
        ``None``, ``"to_value"`` (the characters' values) or ``"to_ascii"`` (their ASCII
        codes), for a TXT source into a numeric register.
    oneshot:
        Execute once on OFF→ON transition.
    termination_code:
        The termination code. Only a TXT range copied to TXT accepts one. The value is
        ``"0"`` or ``"none"`` for no code, stored as ``"0"``, or a hex ASCII code
        ``"$HH"``, the same as for a single Copy.
    """

    source_start: str
    source_end: str
    dest_start: str
    dest_end: str
    convert: str | None = None
    oneshot: bool = False
    termination_code: str = "0"

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            check.normalize("source_start", "source_end", "dest_start", "dest_end")
            if self.convert not in _BLOCKCOPY_CONVERTS:
                check.refuse(
                    "convert",
                    f"{self.convert!r} is not allowed; it is None, 'to_value' or 'to_ascii'",
                    Reason.CHOICE,
                    code=Code.INVALID_CHOICE,
                )
            _read_termination(check, self)
            cls = "BlockCopy"
            src, src_last = _check_range(
                check, "source_start", self.source_start, "source_end", self.source_end,
                _sources(_BLOCK_ROWS), one_module=True, bank_id="OBJ-004",
            )  # fmt: skip
            # CLICK fills in the destination end itself, so the order of the ends is not
            # checked here. A destination whose end is its start is refused below, as an
            # end that does not match the source.
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
                # The destination range holds as many addresses as the source range,
                # whatever the two banks are. CLICK computes the end the same way.
                end = dest.number + src_last.number - src.number
                spans = ("source_start", "source_end")
                if dest.bank == "Y" and xy_slot(end) != xy_slot(dest.number):
                    # When CLICK computes the end, a Y range runs on into the next slot. No
                    # recorded CLICK save shows what CLICK then stores for the destination.
                    check.add(
                        _refusal(
                            cls,
                            ("dest_start", *spans),
                            f"{self.source_start}..{self.source_end} into "
                            f"{self.dest_start} runs past the end of its Y slot. laddercodec "
                            "can't write a destination that crosses a Y slot. Start the "
                            "destination where the whole range fits in one slot.",
                            Reason.CONFLICT,
                            code=Code.RANGE_CROSSES_SLOT,
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
                            code=Code.BLOCK_COPY_END_MISMATCH,
                        )
                    )
            source = f"{self.source_start}..{self.source_end}"
            if self.convert is not None and src is not None and src.bank != "TXT":
                check.refuse(
                    ("convert", "source_start", "source_end"),
                    f"{self.convert} needs a TXT source, not {source}",
                    Reason.CONFLICT,
                    code=Code.COPY_CONVERTER_BANK,
                )
            txt_to_txt = (
                src is not None and src.bank == "TXT" and dest is not None and dest.bank == "TXT"
            )
            if self.convert is not None and txt_to_txt:
                # For TXT into TXT, CLICK's dialog offers only Termination Code, and no
                # converter.
                check.refuse(
                    ("convert", "dest_start"),
                    f"{self.convert} copies TXT to a number, not {source} -> "
                    f"{self.dest_start}..{self.dest_end}",
                    Reason.CONFLICT,
                    code=Code.COPY_CONVERTER_BANK,
                )
            if (
                self.convert is None
                and src is not None and src.bank == "TXT"
                and dest is not None and dest.bank in _NUMERIC_DEST_BANKS
                and not check.refused("dest_start")
            ):  # fmt: skip
                # CLICK's dialog asks for Copy Character Value or Copy ASCII Code Value, as
                # for a single Copy, and saves one of them.
                check.refuse(
                    ("convert", "source_start", "dest_start"),
                    f"{source} -> {self.dest_start}..{self.dest_end} needs convert=to_value "
                    "(the characters' values) or convert=to_ascii (their ASCII codes)",
                    Reason.CONFLICT,
                    code=Code.COPY_TXT_NEEDS_CONVERT,
                )
            if (
                self.termination_code != "0"
                and src is not None
                and dest is not None
                and not (txt_to_txt and self.convert is None)
            ):
                # CLICK's dialog offers Termination Code for a TXT range copied to TXT only.
                check.refuse(
                    ("termination_code", "source_start", "dest_start"),
                    f"{self.termination_code!r} needs a TXT range copied to TXT with no "
                    f"converter, not {source} -> {self.dest_start}..{self.dest_end} with "
                    f"convert {self.convert!r}",
                    Reason.CONFLICT,
                    code=Code.OPTION_NOT_OFFERED,
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
        if self.convert is not None:
            kw.append(f"convert={self.convert}")
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

        conv_type = _CONVERT_TO_CONVTYPE.get(self.convert, "0")
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
        The value to fill with: a constant (``"0"``) or an address (``"DS56"``).
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
            dest, _ = _check_range(
                check, "dest_start", self.dest_start, "dest_end", self.dest_end,
                _REGISTER_DEST_BANKS, ids=False,
            )  # fmt: skip
            if kind is not None and dest is not None:
                check.run(
                    _check_pair, "Fill", "value", self.value, kind,
                    "dest_start", self.dest_start, dest.bank, _FILL_PAIRS,
                    code=Code.COPY_BANK_INCOMPATIBLE,
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
                "0",  # [11] text_flag (no recorded CLICK save shows a Fill with a text constant)
                "",  # [12] terminator
            ],
        )


# ---------------------------------------------------------------------------
# Pack
# ---------------------------------------------------------------------------

#: The kinds of Pack, as the CSV names them.
_PACK_KINDS = frozenset({"pack_bits", "pack_words", "pack_text"})

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
    dest:
        Destination operand (e.g. ``"DS167"``).
    kind:
        ``"pack_bits"``, ``"pack_words"`` or ``"pack_text"``.
    allow_whitespace:
        Text option — allow whitespace in text packing.
    oneshot:
        Execute once on OFF→ON transition.
    """

    source_start: str
    source_end: str
    dest: str
    kind: str = "pack_bits"
    allow_whitespace: bool = False
    oneshot: bool = False

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            check.normalize("source_start", "source_end", "dest")
            # The checks and messages use the short name of the kind: bits, words or text.
            short = str(self.kind).removeprefix("pack_")
            if self.kind not in _PACK_KINDS:
                check.refuse(
                    "kind",
                    f"{self.kind!r} is not allowed; it is 'pack_bits', 'pack_words' or 'pack_text'",
                    Reason.CHOICE,
                    code=Code.INVALID_CHOICE,
                )
            first, last = _check_range(
                check, "source_start", self.source_start, "source_end", self.source_end,
                _sources(_PACK_ROWS), one_module=True, module_id="OBJ-033",
            )  # fmt: skip
            # CLICK refuses a bank that no source packs into as a bank the field cannot use
            # (OBJ-004), for example X001, SD29 or SD31 after C1..C16. It refuses a bank that
            # some other source packs into as a pairing of kinds (OBJ-024).
            dest = check("dest", check_box_operand, _destinations(_PACK_ROWS), bank_id="OBJ-004")
            if first is not None and dest is not None:
                assert dest.bank is not None
                source = f"{self.source_start}..{self.source_end}"
                # Check the length of the source before the pairing (see _pack_limit).
                if (
                    last is not None
                    and not check.refused("kind")
                    and _pack_kind(first.bank) == short
                ):
                    paired = dest.bank in _source_row(_PACK_ROWS, first.bank)
                    check.run(
                        _check_count, "Pack", "source_start", "source_end", "dest",
                        source, _span(first, last), short,
                        _pack_limit(short, first.bank, dest.bank, paired),
                        self.dest if paired else None,
                    )  # fmt: skip
                check.run(
                    _check_row, "Pack", _PACK_ROWS, source, "source_start", first.bank,
                    "dest", self.dest, dest.bank,
                )  # fmt: skip
            if first is not None and not check.refused("kind"):
                if (first.bank == "TXT") != (self.kind == "pack_text"):
                    check.add(
                        _refusal(
                            "Pack",
                            ("source_start", "kind"),
                            f"{self.source_start!r} is "
                            f"{'a TXT register' if first.bank == 'TXT' else 'not a TXT register'}; "
                            f"{self.kind} "
                            f"{'takes a TXT source' if self.kind == 'pack_text' else 'has no TXT source'}, "
                            f"{'pack_text' if first.bank == 'TXT' else 'pack_words or pack_bits'} does",
                            Reason.CONFLICT,
                            code=Code.PACK_KIND_MISMATCH,
                        )
                    )
                if self.kind != "pack_text":
                    check.run(
                        _check_kind, "Pack", "source_start", self.source_start, first.bank,
                        short, "kind",
                    )  # fmt: skip
            check.flag("allow_whitespace", "oneshot")
            if (
                self.kind in ("pack_bits", "pack_words")
                and not check.refused("allow_whitespace")
                and self.allow_whitespace
            ):
                # Allow whitespace is a Pack Text option; pack_bits and pack_words have none.
                check.refuse(
                    ("allow_whitespace", "kind"),
                    f"allow_whitespace is a pack_text option; {self.kind} has none",
                    Reason.CONFLICT,
                    code=Code.OPTION_NOT_OFFERED,
                )

    @property
    def func_code(self) -> str:
        base = int(COPY_FUNC_CODES["3"])  # pack base: 8978
        return str(base + (1 if self.oneshot else 0))

    def to_csv(self) -> str:
        src = f"{self.source_start}..{self.source_end}"
        parts = [src, self.dest]
        kw: list[str] = []
        if self.oneshot:
            kw.append("oneshot=1")
        if self.allow_whitespace:
            kw.append("allow_whitespace=1")
        if kw:
            return f"{self.kind}({','.join(parts)},{','.join(kw)})"
        return f"{self.kind}({','.join(parts)})"

    def cell_params(self) -> dict:
        return dict(_CELL_PARAMS)

    def build_blob(self) -> bytes:
        from ..binary_helpers import _build_blob

        if self.kind == "pack_text":
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
                self.dest,  # [2]
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

#: The kinds of Unpack, as the CSV names them.
_UNPACK_KINDS = frozenset({"unpack_to_bits", "unpack_to_words"})


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
    kind:
        ``"unpack_to_bits"`` or ``"unpack_to_words"``.
    oneshot:
        Execute once on OFF→ON transition.
    """

    source: str
    dest_start: str
    dest_end: str
    kind: str = "unpack_to_bits"
    oneshot: bool = False

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            check.normalize("source", "dest_start", "dest_end")
            # The checks and messages use the short name of the kind: bits or words.
            short = str(self.kind).removeprefix("unpack_to_")
            if self.kind not in _UNPACK_KINDS:
                check.refuse(
                    "kind",
                    f"{self.kind!r} is not allowed; it is 'unpack_to_bits' or 'unpack_to_words'",
                    Reason.CHOICE,
                    code=Code.INVALID_CHOICE,
                )
            # CLICK refuses a bank that no row holds as a bank the field cannot use
            # (OBJ-004). CLICK gives this answer for an X source and for X, SC and SD
            # destinations. It is the same id that an Unpack gives for a bank that the
            # source's row leaves out (_ROW_IDS).
            src = check("source", check_box_operand, _sources(_UNPACK_ROWS), bank_id="OBJ-004")
            # Check the destination start against the source before reading the end of the
            # range. A pairing refusal then comes before any refusal of the end (OBJ-008,
            # OBJ-009, OBJ-012 or the Y slot). If the start is refused, the end is not
            # checked against it.
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
            if first is not None and not check.refused("kind"):
                check.run(
                    _check_kind, "Unpack", "dest_start", self.dest_start, first.bank,
                    short, "kind",
                )  # fmt: skip
                if last is not None and src is not None:
                    check.run(
                        _check_count, "Unpack", "dest_start", "dest_end", "source",
                        f"{self.dest_start}..{self.dest_end}", _span(first, last),
                        short, _count_limit(short, src.bank), self.source,
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
            return f"{self.kind}({','.join(parts)},{','.join(kw)})"
        return f"{self.kind}({','.join(parts)})"

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
        # The destination was read in a different form from the stored text: without a
        # space at its edge, or in display form. Mark the instruction so that, while it is
        # unchanged, it encodes as the bytes CLICK stored, with the space and the text as
        # typed.
        read_in_another_form(built)
    return built


def _edge_trimmed(tags: dict[int, str]) -> bool:
    """Return whether the blob is a single Copy or a Pack. The decoder strips spaces from
    the ends of the destination of these two.

    CLICK saves the destination of a single Copy or a Pack with any space typed at its
    start or end (" DS1", "DS1 "). It trims every other field. The decoder reads the
    address without the space.
    """
    return tag_int(tags, 0x2223) in (0, 3)


def _read_destination(tags: dict[int, str]) -> str:
    """Return the destination, or the start of the destination range, as the decoder reads
    it. For a single Copy or a Pack, spaces at its ends are removed (:func:`_edge_trimmed`).
    For a single Copy, a Block Copy or a Pack, it is put in display form.

    CLICK saves those three destinations as they were typed (``DS001``, ``ds1``, ``YD0U``,
    ``DS[ds1]``). It saves every other address in display form.
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
        # A single copy has no source end. It has a destination end only for text, which
        # is checked below. CLICK writes no single copy with any other end. Return None so
        # that the blob stays raw() and its ends are not dropped.
        if source_end:
            return None
        opts = _CONVTYPE_TO_OPTS.get(str(conv_type))
        if opts is None:
            return None
        # Type 7 exists only for certain pairs, and types 3 and 4 only for a real source.
        # CLICK does not write them for anything else. Return None so that the blob stays
        # raw(), because a Copy built from it would encode different bytes.
        if conv_type == 7 and not _saves_type_7(source, destination):
            return None
        if conv_type in (3, 4) and not _real_text_source(source):
            return None
        if conv_type != 0 and constant_shape(source, _ANY_TEXT) in (Kind.TEXT, Kind.CHAR):
            # A copy of text or of a character code has no conversion type.
            return None
        convert, suppress_zero, exponential = opts
        if convert == "to_text" and _real_text_source(source):
            # A real source has no suppress zero option.
            suppress_zero = None

        termination_code = _read_termination_tags(tags)
        if termination_code is None:
            return None

        copy = Copy(
            source=source,
            dest=destination,
            convert=convert,
            oneshot=oneshot,
            suppress_zero=suppress_zero,
            exponential=exponential,
            termination_code=termination_code,
        )
        # The text decides the destination end. CLICK does not write a blob whose end
        # disagrees with its text, so return None for one. A number copied into a TXT
        # address has either no end, or the end that its text fills together with the
        # conversion type for its kind of number. Quoted text has either no end or the end
        # that it fills. It can have no end because CLICK's paste drops the end, even from
        # CLICK's own clipboard.
        number_end = _number_fill_end(copy.source, copy.dest)
        if number_end is not None and destination_end:
            if destination_end != number_end.display or conv_type not in _number_text_types(
                copy.source
            ):
                return None
        elif destination_end and destination_end != copy._destination_end():
            return None
        written = dict(zip(_COPY_TAGS, copy._tag_values(), strict=True))
        if (
            (conv_type, destination_end) != (int(written[0x2227]), written[0x6077])
            or (conv_type in (7, 8) and _other_type_7(source, destination))
            or (number_end is not None and destination_end)
        ):
            # Mark the Copy so that, while it is unchanged, it encodes as the blob it was
            # decoded from. This is needed in three cases:
            # - the encoder writes another conversion type or end for these fields;
            # - the save is type 7 or 8, and the pair is not a DD address and a DF address;
            # - the save stores the end of a number copied into TXT.
            read_in_another_form(copy)
        return copy

    if copy_type == 1:
        if not all([source, source_end, destination, destination_end]):
            return None
        if conv_type not in (0, 5, 6):
            return None
        convert = {0: None, 5: "to_value", 6: "to_ascii"}[conv_type]
        termination_code = _read_termination_tags(tags)
        if termination_code is None:
            return None
        return BlockCopy(
            source_start=source,
            source_end=source_end,
            dest_start=destination,
            dest_end=destination_end,
            convert=convert,
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
            kind = "pack_text"
            allow_whitespace = False
        elif conv_type == 10:
            kind = "pack_text"
            allow_whitespace = True
        elif conv_type == 0:
            kind = "pack_bits" if _bank_prefix(source) in BIT_BANKS else "pack_words"
            allow_whitespace = False
        else:
            return None
        return Pack(
            source_start=source,
            source_end=source_end,
            dest=destination,
            kind=kind,
            allow_whitespace=allow_whitespace,
            oneshot=oneshot,
        )

    if copy_type == 4:
        if not all([source, destination, destination_end]):
            return None
        kind = "unpack_to_bits" if _bank_prefix(destination) in BIT_BANKS else "unpack_to_words"
        return Unpack(
            source=source,
            dest_start=destination,
            dest_end=destination_end,
            kind=kind,
            oneshot=oneshot,
        )

    return None


# ---------------------------------------------------------------------------
# CSV parser
# ---------------------------------------------------------------------------


#: The keywords that each Copy-family CSV call accepts besides its operands.
_CSV_KWARGS: dict[str, frozenset[str]] = {
    "copy": frozenset({"convert", "oneshot", "termination_code"}),
    "blockcopy": frozenset({"convert", "oneshot", "termination_code"}),
    "fill": frozenset({"oneshot"}),
    "pack_bits": frozenset({"oneshot"}),
    "pack_words": frozenset({"oneshot"}),
    "pack_text": frozenset({"oneshot", "allow_whitespace"}),
    "unpack_to_bits": frozenset({"oneshot"}),
    "unpack_to_words": frozenset({"oneshot"}),
}


def _refuse_unknown_kwargs(name: str, kwargs: Mapping[str, str]) -> None:
    """Raise ``CsvError`` for a keyword that the CSV call ``name`` does not accept. A
    misspelt keyword (``terminaton_code=``) is then reported, not silently ignored."""
    unknown = set(kwargs) - _CSV_KWARGS[name]
    if unknown:
        raise CsvError(f"{name} does not support keyword argument(s): {sorted(unknown)}")


def _copy_from_csv(args: Sequence[str], kwargs: Mapping[str, str]) -> Copy:
    """Build a Copy from the arguments of ``copy(source, dest, ...)``.

    :meth:`Copy.from_csv_token` and :func:`parse_af_call` both call it."""
    _refuse_unknown_kwargs("copy", kwargs)
    source, dest = args
    convert_raw = kwargs.get("convert", "")
    if convert_raw:
        convert, text_opts = _parse_convert_kwarg(convert_raw)
    else:
        convert, text_opts = None, {}
    termination_code = text_opts.get("termination_code", "0")
    if kwargs.get("termination_code", "none") not in ("none", "0"):
        # A termination code given as its own keyword is for a TXT register copied to
        # TXT, with no converter. "none" and "0" both mean no code, and every copy
        # accepts them.
        if convert_raw:
            raise FieldError(
                f"Copy.termination_code: {kwargs['termination_code']!r} stands alone only "
                f"for TXT copied to TXT, with no converter, not beside {convert_raw}; a "
                "number copied to TXT takes it inside the converter "
                "(to_text(...,termination_code=$0D))",
                field=("Copy.termination_code", "Copy.convert"),
                reason=Reason.CONFLICT,
                code=Code.OPTION_NOT_OFFERED,
            )
        termination_code = kwargs["termination_code"]
    if termination_code == "none":
        termination_code = "0"
    return Copy(
        source=source,
        dest=dest,
        convert=convert,
        oneshot=check_csv_flag(kwargs, "oneshot", "Copy.oneshot"),
        suppress_zero=(
            check_csv_flag(text_opts, "suppress_zero", "Copy.suppress_zero")
            if "suppress_zero" in text_opts
            else None
        ),
        exponential=check_csv_flag(text_opts, "exponential", "Copy.exponential"),
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
        convert = _parse_convert_kwarg(convert_raw)[0] if convert_raw else None
        return BlockCopy(
            source_start=src_start,
            source_end=src_end,
            dest_start=dest_start,
            dest_end=dest_end,
            convert=convert,
            oneshot=check_csv_flag(call.kwargs, "oneshot", "BlockCopy.oneshot"),
            termination_code=call.kwargs.get("termination_code", "0"),
        )

    if call.name == "fill":
        if len(call.args) != 2:
            raise CsvError(
                f"fill expects 2 positional args (value, dest_range), got {len(call.args)}"
            )
        _refuse_unknown_kwargs(call.name, call.kwargs)
        dest_start, dest_end = _parse_range(call.args[1])
        return Fill(
            value=call.args[0],
            dest_start=dest_start,
            dest_end=dest_end,
            oneshot=check_csv_flag(call.kwargs, "oneshot", "Fill.oneshot"),
        )

    if call.name in ("pack_bits", "pack_words", "pack_text"):
        if len(call.args) != 2:
            raise CsvError(
                f"{call.name} expects 2 positional args (src_range, dest), got {len(call.args)}"
            )
        _refuse_unknown_kwargs(call.name, call.kwargs)
        src_start, src_end = _parse_range(call.args[0])
        return Pack(
            source_start=src_start,
            source_end=src_end,
            dest=call.args[1],
            kind=call.name,
            allow_whitespace=check_csv_flag(
                call.kwargs, "allow_whitespace", "Pack.allow_whitespace"
            ),
            oneshot=check_csv_flag(call.kwargs, "oneshot", "Pack.oneshot"),
        )

    if call.name in ("unpack_to_bits", "unpack_to_words"):
        if len(call.args) != 2:
            raise CsvError(
                f"{call.name} expects 2 positional args (source, dest_range), got {len(call.args)}"
            )
        _refuse_unknown_kwargs(call.name, call.kwargs)
        dest_start, dest_end = _parse_range(call.args[1])
        return Unpack(
            source=call.args[0],
            dest_start=dest_start,
            dest_end=dest_end,
            kind=call.name,
            oneshot=check_csv_flag(call.kwargs, "oneshot", "Unpack.oneshot"),
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
