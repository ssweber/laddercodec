"""The checks that instruction fields share.  Each field makes one call, with its own parameters.

- :func:`~laddercodec.operands.address.check_address`: an address in the field's banks.
- :func:`check_constant`: a constant of the kinds and limits a :class:`Constants` names.
- :func:`check_operand`: an address, a pointer or a constant, in one field;
  :func:`constant_shape` names the kind of constant a text is spelled as, limits aside;
  :func:`bank_of` returns the bank of an address or pointer that the check accepts.
- :func:`check_quoted_text`: a quoted text constant, as a Search value takes it;
  :func:`check_kept_text`: text a single Copy source or a Search value holds.
- :func:`check_out_target`: an address a coil writes.
- :func:`check_writable_sd`: an SD register a Copy or a decimal Math writes.
- :func:`check_flag`: a True/False field.
- :class:`Refusals`: runs one instruction's checks and raises every refusal as one error.

:data:`BIT_BANKS` and :data:`REGISTER_BANKS` are the bank sets more than one family uses.
They are defined in :mod:`laddercodec.operands.banks`, and this module imports them.

Every refusal is a :class:`~laddercodec.operands.errors.FieldError`, or an
:class:`~laddercodec.operands.errors.AddressError` for an address or a pointer.  Its
``field`` is the ``field`` the caller gave, as ``Class.attr``, and its ``reason`` is a
:class:`~laddercodec.operands.errors.Reason`.  The message names ``label``, or the field
when no label is given.  The constant checks build on
:func:`~laddercodec.operands.constants.classify`.

Not public API.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import TracebackType
from typing import Any, NamedTuple, TypedDict, TypeVar

from ..codes import Code
from .address import ADDRESS_BANKS, Address, check_address, normalize_fields, split_pointer
from .banks import BIT_BANKS, REGISTER_BANKS
from .constants import (
    CHAR_CODE_RULE,
    INT32_MAX,
    INT32_MIN,
    KEPT_TEXT_RULE,
    TEXT_MAX,
    Constant,
    Kind,
    classify,
    kept_text,
    printable,
)
from .errors import AddressError, FieldError, Reason
from .message import Op, Parts, Rule, make_refusal, operand, says, set_parts, shown

__all__ = [
    "ALL_KINDS",
    "BIT_BANKS",
    "OUT_BANKS",
    "POINTER_BANKS",
    "SOURCE_POINTER_BANKS",
    "REGISTER_BANKS",
    "WRITABLE_SC",
    "WRITABLE_SD",
    "Constants",
    "Operand",
    "Refusals",
    "bank_of",
    "check_address",
    "check_constant",
    "check_csv_flag",
    "check_flag",
    "check_operand",
    "check_out_target",
    "check_kept_text",
    "check_quoted_text",
    "check_writable_sd",
    "constant_shape",
    "choice_operand",
    "is_choice",
]

#: Every constant kind.
ALL_KINDS: frozenset[Kind] = frozenset(Kind)

#: The highest 32-bit hex constant.
_HEX32_HIGH = 0xFFFFFFFF


@dataclass(frozen=True)
class Constants:
    """The constants one field takes: the parameters of :func:`check_constant`.

    The defaults are :func:`~laddercodec.operands.constants.classify`'s own limits, with
    text in printable ASCII and with no quote inside it.
    """

    #: The kinds the field takes.
    kinds: frozenset[Kind]
    #: The signs a decimal integer or a real may start with: ``"+-"``, ``"-"`` (a
    #: counter preset) or ``""`` (digits only: a timer preset).
    signs: str = "+-"
    #: The lowest and highest decimal integer.
    low: int = INT32_MIN
    high: int = INT32_MAX
    #: The highest hex value: ``0xFFFF`` where a field takes 16-bit hex only.
    hex_high: int = _HEX32_HIGH
    #: Whether a sign before hex digits (``+1h``) reads as a hex constant.  Such text is
    #: refused either way.  This flag decides whether :func:`check_operand` refuses it as a
    #: constant (:class:`FieldError`) or as an address (:class:`AddressError`).
    hex_sign: bool = False
    #: CLICK's id for a real constant outside the float32 range, where the field's dialog
    #: gives one.
    real_id: str | None = None
    #: The most characters between the quotes of a text constant.
    text_max: int = TEXT_MAX
    #: Whether a text constant holds printable ASCII only (space to ``~``).
    printable: bool = True
    #: Whether a text constant may hold a quote between its outer quotes.  Each quote is
    #: one character of the text, so ``"A""B"`` is the four characters ``A""B``.
    quote: bool = False
    #: Whether ``$`` and one hex digit (``$1``) is a character code, kept as typed.
    one_digit_char: bool = False
    #: The most characters the typed constant may have, or ``None``.
    max_length: int | None = None
    #: CLICK's id for a decimal or hex constant outside the field's limits, where the
    #: field's dialog gives one.
    range_id: str | None = "OBJ-005"


class _ResultIds(TypedDict):
    """The keyword arguments of :func:`check_address` that carry a field's error ids."""

    bank_ids: dict[str, str]
    range_ids: dict[str, str]
    outside_range_of: str


#: ``HEX_MATH_RESULT`` holds the ids and wording that CLICK gives for a hex Math result it
#: refuses.  CLICK calls an SD in SD1-SD1000, or a YD past YD8, outside the range (OBJ-003).
#: It gives OBJ-004 for an SD outside SD1-SD1000, such as SD0 or SD1001, and for any other
#: bank the result does not take.  Pass ``HEX_MATH_RESULT`` as keyword arguments to
#: :func:`check_address`.
HEX_MATH_RESULT: _ResultIds = {
    "bank_ids": {"SD": "OBJ-003"},
    "range_ids": {"YD": "OBJ-003"},
    "outside_range_of": "a hex Math result",
}


class Operand(NamedTuple):
    """A checked operand: an address, a pointer or a constant."""

    #: The bank of an address, or the bank a pointer addresses; ``None`` for a constant.
    bank: str | None = None
    #: The address; ``None`` for a pointer or a constant.
    address: Address | None = None
    #: A pointer's index register (``DS1`` in ``DD[DS1]``); ``None`` otherwise.
    index: Address | None = None
    #: The constant; ``None`` for an address or a pointer.
    constant: Constant | None = None


class _At(NamedTuple):
    """The field a check refuses for, and the label its messages name."""

    field: str
    label: str

    def error(
        self,
        value: str,
        said: Rule,
        reason: Reason,
        click_id: str | None = None,
        cls: type[FieldError] = FieldError,
        *,
        code: Code,
        also: str | None = None,
        then: str = "",
    ) -> FieldError:
        """Build the error ``label: 'value' short; detail``, with CLICK's id at the end.

        ``said`` is the rule that follows the value, from :func:`~.message.says`.  ``also``
        names the other field of a refused pair.  ``then`` is the sentence that says what
        to do."""
        return make_refusal(
            cls,
            self.label,
            Rule((Op(value), " ", *said.short), said.detail),
            field=self.field if also is None else (self.field, also),
            reason=reason,
            code=code,
            click_id=click_id,
            then=then,
        )


def _at(field: str, label: str | None) -> _At:
    return _At(field, label or field)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Shapes, on uppercase text, with any sign; constant_shape() narrows them to a field's signs.
_HEX_SHAPE = re.compile(r"([+-]?)[0-9A-F]+H")
_INTEGER_SHAPE = re.compile(r"([+-]?)[0-9]+")
_FLOAT_SHAPE = re.compile(r"([+-]?)(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:E[+-]?[0-9]+)?")


def constant_shape(value: str, constants: Constants) -> Kind | None:
    """Return the kind of constant that ``value`` is spelled as, ignoring limits, or ``None``
    for other text.

    The kinds are tried in :func:`classify`'s order.  A sign the field does not take
    makes a number no constant, and so does a sign before hex digits unless
    :attr:`Constants.hex_sign` is set.
    """
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return Kind.TEXT
    if value.startswith("$"):
        return Kind.CHAR
    if not value.isascii():
        return None
    upper = value.upper()
    m = _HEX_SHAPE.fullmatch(upper)
    if m is not None:
        return Kind.HEX if not m.group(1) or constants.hex_sign else None
    for kind, pattern in ((Kind.INTEGER, _INTEGER_SHAPE), (Kind.FLOAT, _FLOAT_SHAPE)):
        m = pattern.fullmatch(upper)
        if m is not None:
            return kind if m.group(1) in constants.signs else None
    return None


def _kinds_text(kinds: Collection[Kind]) -> str:
    names = {
        Kind.INTEGER: "a decimal integer",
        Kind.FLOAT: "a real",
        Kind.HEX: "a hex value",
        Kind.TEXT: "quoted text",
        Kind.CHAR: "a $hh character code",
    }
    return ", ".join(names[k] for k in Kind if k in kinds) or "no constant"


def _kind_refusal(value: str, at: _At, kind: Kind, constants: Constants) -> FieldError:
    """Return the refusal of a constant of a kind that the field does not take."""
    return at.error(
        value,
        says(
            "is {kind}",
            "{label} takes {kinds}",
            kind=_kinds_text([kind]),
            kinds=_kinds_text(constants.kinds),
        ),  # fmt: skip
        Reason.KIND,
        code=Code.CONSTANT_KIND_NOT_ALLOWED,
    )


def _hex_above(value: str, at: _At, constants: Constants) -> FieldError:
    """Return the refusal of a hex constant above the field's highest value."""
    high = f"{constants.hex_high:X}h"
    return at.error(
        value,
        says("is above {high}", "a hex constant here is 0h to {high}", high=high),
        Reason.RANGE,
        constants.range_id,
        code=Code.CONSTANT_OUT_OF_RANGE,
    )


def _unread(value: str, at: _At, constants: Constants) -> FieldError:
    """Return the refusal of text in which :func:`classify` reads no constant, worded by the
    field's own kinds and limits."""
    kinds = constants.kinds
    if len(value) >= 2 and value[0] == value[-1] == '"':
        if Kind.TEXT not in kinds:
            return _kind_refusal(value, at, Kind.TEXT, constants)
        # classify() refuses only an empty text and a text longer than TEXT_MAX.
        refusal = _quote_refusal(value, at, constants)
        if refusal is not None:
            return refusal
        return at.error(
            value,
            _text_rule(constants),
            Reason.RANGE,
            code=Code.CONSTANT_OUT_OF_RANGE,
        )
    upper = value.upper() if value.isascii() else ""
    m = _HEX_SHAPE.fullmatch(upper)
    if m is not None:
        if Kind.HEX not in kinds:
            return _kind_refusal(value, at, Kind.HEX, constants)
        if m.group(1):
            return at.error(
                value,
                says("is refused", "a hex constant has no sign"),
                Reason.FORM,
                code=Code.INVALID_CONSTANT,
            )
        if int(upper[:-1], 16) > constants.hex_high:
            return _hex_above(value, at, constants)
        # Only the digit count is left to refuse a value above FFFFh.  0FFFFFFFFh has nine
        # digits, so it is no 32-bit constant.
        return at.error(
            value,
            says("is refused", "a hex constant above FFFFh has at most 8 digits"),
            Reason.RANGE,
            code=Code.CONSTANT_OUT_OF_RANGE,
        )
    if _INTEGER_SHAPE.fullmatch(upper):
        # check_constant words its own refusal of an integer for a field that takes integers.
        # Only a field that does not take them gets here.
        return _kind_refusal(value, at, Kind.INTEGER, constants)
    if _FLOAT_SHAPE.fullmatch(upper):
        if Kind.FLOAT not in kinds:
            return _kind_refusal(value, at, Kind.FLOAT, constants)
        return at.error(
            value,
            says(
                "is refused",
                "a real constant is a finite number within float32 (up to about 3.4028235E+38)",
            ),
            Reason.RANGE,
            constants.real_id,
            code=Code.CONSTANT_OUT_OF_RANGE,
        )
    if kinds == ALL_KINDS:
        said = says("is refused", "it is not a constant")
    elif kinds == {Kind.HEX}:
        said = says("is refused", "{label} takes a hex value: hex digits then h")
    else:
        said = says("is refused", "{label} takes {kinds}", kinds=_kinds_text(kinds))
    return at.error(value, said, Reason.KIND, code=Code.NOT_A_CONSTANT)


def _text_rule(constants: Constants) -> Rule:
    """Return the rule of the field's text constants, as a refusal of ``is refused`` says it."""
    if constants.text_max == 1:
        rule = "a text constant is one character in quotes"
    else:
        rule = f"a text constant is 1 to {constants.text_max} characters in quotes"
    if constants.quote:
        return says("is refused", "{rule}", rule=rule)
    return says(
        "is refused", "{rule}, with no quote inside (write the quote character as $22)", rule=rule
    )


def _quote_refusal(value: str, at: _At, constants: Constants) -> FieldError | None:
    """Return the refusal of ``value``, a quoted text, if it holds a quote between its outer
    quotes and the field takes none.  Otherwise return None.

    A quote among other characters gets its own message, because no form writes it: ``$22``
    is a lone quote.  A field of one character refuses every quote with its text rule."""
    inner = value[1:-1]
    if constants.quote or '"' not in inner:
        return None
    if inner != '"' and constants.text_max > 1:
        said = says(
            "holds a quote with other characters, which a text constant can't hold",
            'write the text without it, such as "AB"',
        )
    else:
        said = _text_rule(constants)
    return at.error(value, said, Reason.FORM, code=Code.INVALID_TEXT_CONSTANT)


#: The rule that a refused ``$`` value breaks in a field that takes ``$`` and one hex digit.
_ONE_DIGIT_CHAR_RULE = "a character code is $ and one or two hex digits, $0 to $FF, such as $41"


def _is_one_digit_code(value: str) -> bool:
    """Return whether ``value`` is ``$`` and one hex digit (``$1``)."""
    return len(value) == 2 and value[0] == "$" and value[1] in "0123456789ABCDEFabcdef"


def check_constant(
    value: str,
    field: str,
    constants: Constants,
    *,
    label: str | None = None,
    char_id: str | None = None,
) -> Constant:
    """Return the constant that ``value`` spells, if ``constants`` takes it.  Otherwise raise
    :class:`FieldError` naming ``field``.  ``char_id`` is CLICK's id for a ``$`` text that is
    no character code, where the field's dialog gives one.

    :func:`~laddercodec.operands.constants.classify` reads the text, and then ``constants``
    applies the field's kinds and limits.
    """
    at = _at(field, label)
    if value == "":
        raise _blank(at)
    if value.startswith("$"):
        const = classify(value)
        if const is None and constants.one_digit_char and _is_one_digit_code(value):
            const = Constant(Kind.CHAR, int(value[1], 16))
        if const is None or const.kind is not Kind.CHAR:
            if Kind.CHAR in constants.kinds:
                rule = _ONE_DIGIT_CHAR_RULE if constants.one_digit_char else CHAR_CODE_RULE
                raise at.error(
                    value,
                    says("is refused", "{rule}", rule=rule),
                    Reason.FORM,
                    char_id,
                    code=Code.INVALID_CHAR_CODE,
                )
            said = says("is refused", "{label} takes {kinds}", kinds=_kinds_text(constants.kinds))
            raise at.error(value, said, Reason.KIND, code=Code.NOT_A_CONSTANT)
    else:
        const = classify(value)
        if const is None:
            if Kind.INTEGER in constants.kinds and _INTEGER_SHAPE.fullmatch(value.upper()):
                # The text is an integer beyond int32.  The field's own sign rule and limits
                # word the refusal.
                _check_sign(value, at, constants)
                raise _outside(value, at, constants)
            raise _unread(value, at, constants)
    if const.kind not in constants.kinds:
        raise _kind_refusal(value, at, const.kind, constants)
    _check_limits(value, at, constants, const)
    return const


def _blank(at: _At, cls: type[FieldError] = FieldError) -> FieldError:
    """Return the refusal of a blank field, with the reason ``missing`` and no CLICK id."""
    return make_refusal(
        cls,
        at.label,
        says("is blank", "it needs a value"),
        field=at.field,
        reason=Reason.MISSING,
        code=Code.BLANK_FIELD,
    )


def _outside(value: str, at: _At, constants: Constants) -> FieldError:
    """Return the refusal of a decimal integer outside the field's limits."""
    # Without a '-' the lowest value a field can take is 0.
    low = constants.low if "-" in constants.signs else max(constants.low, 0)
    return at.error(
        value,
        says("is outside {low} to {high}", low=low, high=constants.high),
        Reason.RANGE,
        constants.range_id,
        code=Code.CONSTANT_OUT_OF_RANGE,
    )


def _check_sign(value: str, at: _At, constants: Constants) -> None:
    """Refuse a leading sign the field does not take."""
    if value[:1] in "+-" and value[0] not in constants.signs:
        # A field that takes one sign names the other in the message, as in "no plus sign".
        # A field that takes no sign says "no sign".
        refused = {"+": "plus ", "-": "minus "}[value[0]] if constants.signs else ""
        # A minus sign where the field's lowest value is 0 or more is out of range.
        code = Code.CONSTANT_OUT_OF_RANGE if value[0] == "-" else Code.INVALID_CONSTANT
        raise at.error(
            value,
            says("is refused", "a constant here takes no {refused}sign", refused=refused),
            Reason.FORM,
            "OBJ-005",
            code=code,
        )


def _check_limits(value: str, at: _At, constants: Constants, const: Constant) -> None:
    """Refuse a constant outside the field's limits."""
    kind = const.kind
    if kind in (Kind.INTEGER, Kind.FLOAT):
        _check_sign(value, at, constants)
    low = constants.low if "-" in constants.signs else max(constants.low, 0)
    if kind is Kind.INTEGER and not low <= int(const.value) <= constants.high:
        raise _outside(value, at, constants)
    if kind is Kind.HEX and int(const.value) > constants.hex_high:
        raise _hex_above(value, at, constants)
    if kind is Kind.TEXT:
        refusal = _quote_refusal(value, at, constants)
        if refusal is not None:
            raise refusal
        text = str(const.value)
        if len(text) > constants.text_max:
            if constants.text_max == 1:
                raise at.error(
                    value,
                    says("is {count} characters", "{label} takes one character", count=len(text)),
                    Reason.RANGE,
                    code=Code.CONSTANT_OUT_OF_RANGE,
                )
            raise at.error(
                value,
                says(
                    "is {count} characters",
                    "{label} takes at most {most}",
                    count=len(text),
                    most=constants.text_max,
                ),  # fmt: skip
                Reason.RANGE,
                code=Code.CONSTANT_OUT_OF_RANGE,
            )
        if constants.printable and not printable(text):
            raise at.error(
                value,
                says(
                    "is refused",
                    "text holds printable ASCII only (space to ~); write another character as "
                    "its $hh code",
                ),
                Reason.FORM,
                code=Code.INVALID_TEXT_CONSTANT,
            )
    if constants.max_length is not None and len(value) > constants.max_length:
        raise at.error(
            value,
            says(
                "is {count} characters",
                "a constant here is at most {most}",
                count=len(value),
                most=constants.max_length,
            ),  # fmt: skip
            Reason.RANGE,
            "OBJ-005",
            code=Code.CONSTANT_OUT_OF_RANGE,
        )


#: The characters a quoted text constant may hold: printable ASCII, space to ``~``.
_TEXT_CHARS = range(0x20, 0x7F)


def check_kept_text(value: str, text: str, field: str, *, label: str | None = None) -> None:
    """Refuse the constant ``value`` when CLICK does not keep a character of its text
    ``text`` (:func:`~laddercodec.operands.constants.kept_text`).  A single Copy source and
    a Search text value take only the characters that CLICK keeps."""
    if not kept_text(text):
        raise _at(field, label).error(
            value,
            says("is refused", "{rule}", rule=KEPT_TEXT_RULE),
            Reason.FORM,
            code=Code.INVALID_TEXT_CONSTANT,
        )


def check_quoted_text(
    value: str, field: str, *, label: str | None = None, kept: bool = False
) -> None:
    """Refuse a quoted text constant that the field refuses.

    The text between the quotes must be 1 to :data:`TEXT_MAX` printable ASCII characters,
    with no quote inside.  For a quote alone between the quotes, the message says to write
    ``$22``.  With ``kept``, for a Search value, the text may hold any character that CLICK
    keeps (:func:`check_kept_text`), not only printable ASCII.  With ``kept``, the message for
    a quote among other characters says to leave the quote out, because ``$22`` matches only
    a lone quote character.  On the PLC, the text is compared against consecutive TXT
    registers, starting from the one the instruction names.
    """
    at = _at(field, label)
    if value == "":
        raise _blank(at)
    inner = value[1:-1]
    long = not 1 <= len(inner) <= TEXT_MAX
    if long or (not kept and any(ord(c) not in _TEXT_CHARS for c in inner)):
        chars = "characters" if kept else "printable ASCII characters"
        raise at.error(
            value,
            says(
                "is refused",
                "a text constant is 1 to {most} {chars} in quotes (use $hh for a character by "
                "code)",
                most=TEXT_MAX,
                chars=chars,
            ),
            Reason.RANGE if long else Reason.FORM,
            code=Code.CONSTANT_OUT_OF_RANGE if long else Code.INVALID_TEXT_CONSTANT,
        )
    if kept:
        check_kept_text(value, inner, field, label=label)
    if '"' in inner:
        if kept and inner != '"':
            said = says(
                "holds a quote, which a Search text value can't hold",
                'write the text without it, such as "AB"',
            )
        else:
            said = says("holds a quote", "write the quote character as $22")
        raise at.error(value, said, Reason.FORM, code=Code.INVALID_TEXT_CONSTANT)


# ---------------------------------------------------------------------------
# Operands
# ---------------------------------------------------------------------------

#: The banks a pointer ``BANK[DSn]`` can address.
POINTER_BANKS = frozenset({"C", "DS", "DD", "DH", "DF", "XD", "YD", "TD", "CTD", "TXT"})

#: The banks a pointer can address where a Copy reads it as its source.  CLICK takes an SD
#: pointer there, and refuses one as a destination.
SOURCE_POINTER_BANKS = POINTER_BANKS | {"SD"}


def _example_address(bank: str, banks: Collection[str] | None) -> str:
    """Return an address that a field of ``banks`` takes, for a message that refuses a
    pointer into ``bank``.

    The address is the first of ``bank``, such as DS1 for ``DS[DS1]``, if the field takes
    that bank.  Otherwise it is the first address of the field's first bank.
    """
    if bank not in ADDRESS_BANKS or (banks is not None and bank not in banks):
        bank = next((b for b in ADDRESS_BANKS if banks is None or b in banks), "DS")
    return Address(bank, 1, False).display


#: Every constant that CLICK's shared input check reads, with any sign.
_ANY_CONSTANT = Constants(ALL_KINDS, signs="+-", hex_sign=True)


def _other_constant(value: str, constants: Constants) -> Kind | None:
    """Return the kind of constant that ``value`` is spelled as, if a field of whole
    numbers ``constants`` does not take it, such as ``3.5``, ``-5`` or ``FFh``.  Return
    None for other text, and for any value in a field that is not one of whole numbers.

    A field of whole numbers takes decimal integers only, with no minus sign.  The name of
    a bank, such as ``DH``, is not a constant here.
    """
    if constants.kinds != {Kind.INTEGER} or "-" in constants.signs:
        return None
    if value.upper() in ADDRESS_BANKS:
        return None
    kind = constant_shape(value, _ANY_CONSTANT)
    if kind is not Kind.HEX and value[:1].isalpha():
        return None
    return kind


def _not_a_count(
    value: str, kind: Kind, at: _At, constants: Constants, banks: Collection[str] | None
) -> FieldError:
    """Return the refusal of ``value``, a constant of ``kind`` that a field of whole numbers
    does not take (see :func:`_other_constant`).

    It is the refusal of text that is no CLICK address: an :class:`AddressError` with the
    code ``not-an-address``.  Its rule names the kind, and its next sentence names the
    field's whole numbers and banks.
    """
    if kind is Kind.HEX:
        said = says("is a hex value")
    elif kind is Kind.TEXT:
        said = says("is quoted text")
    elif kind is Kind.CHAR:
        said = says("is text")
    elif kind is Kind.INTEGER:
        # An unsigned integer is a constant the field takes, so this one has a sign.
        said = says("has a plus sign" if value[0] == "+" else "has a minus sign")
    elif _is_fraction(value):
        said = says("is not a whole number")
    else:
        said = says("is a real")
    listed = [b for b in ADDRESS_BANKS if banks is None or b in banks]
    if banks is None or not listed:
        where, example = "an address", "DS1"
    elif len(listed) == 1:
        where, example = f"a {listed[0]} address", Address(listed[0], 1, False).display
    else:
        where = f"an address in {', '.join(listed[:-1])} or {listed[-1]}"
        example = Address(listed[0], 1, False).display
    low = max(constants.low, 0)
    then = f"Write a whole number from {low} to {constants.high}, or {where}, such as {example}."
    return at.error(
        value, said, Reason.ADDRESS, cls=AddressError, code=Code.NOT_AN_ADDRESS, then=then
    )


def _is_fraction(value: str) -> bool:
    """Return whether ``value``, a real such as ``3.5`` or ``1e3``, has a fractional part."""
    try:
        number = Decimal(value)
    except InvalidOperation:
        return False
    return number.is_finite() and number != number.to_integral_value()


def check_operand(
    value: str,
    field: str,
    banks: Collection[str] | None = None,
    constants: Constants | None = None,
    *,
    pointer: bool = False,
    pointer_banks: Collection[str] = POINTER_BANKS,
    letter_first: bool = False,
    label: str | None = None,
    bank_id: str | None = None,
    bank_code: Code = Code.BANK_NOT_ALLOWED,
) -> Operand:
    """Check one operand and return it as an :class:`Operand`.  Raise :class:`FieldError`
    naming ``field`` if it is refused.

    An address goes through :func:`check_address`, narrowed to ``banks``, where ``None``
    allows any bank.  With ``pointer``, a pointer ``BANK[DSn]`` passes when ``BANK`` is in
    ``banks`` and in ``pointer_banks`` and the index is a DS address.  With
    ``constants``, a constant goes through :func:`check_constant`.  Every refusal of a
    pointer, including a refusal of its index, has the reason ``pointer``.  ``bank_id`` and
    ``bank_code`` are CLICK's id and the code for an address in a bank the field does not
    take, as for :func:`check_address`.

    These rules decide which of the two checks reads the text:

    - by default, text spelled as a constant of a kind ``constants`` takes is a constant,
      and any other text is an address (refused with :class:`AddressError`);
    - with ``letter_first``, text that starts with a letter is an address, and any other
      text is a constant (refused with :class:`FieldError`).

    By default, a field that takes only decimal integers refuses another constant, such as
    ``3.5``, ``-5`` or ``FFh``, as an address.  Its message names the constant's kind and
    the field's range and banks.
    """
    at = _at(field, label)
    if value == "":
        raise _blank(at, FieldError if constants is not None and letter_first else AddressError)
    if constants is not None:
        if letter_first:
            is_constant = not value[:1].isalpha()
        else:
            is_constant = constant_shape(value, constants) in constants.kinds
        if is_constant:
            return Operand(constant=check_constant(value, field, constants, label=label))
        kind = None if letter_first else _other_constant(value, constants)
        if kind is not None:
            raise _not_a_count(value, kind, at, constants, banks)
    parts = split_pointer(value)
    if parts is not None:
        if not pointer:
            raise at.error(
                value,
                says(
                    "is a pointer", "{label} can't be a pointer, and only a single Copy takes one"
                ),
                Reason.POINTER,
                cls=AddressError,
                code=Code.POINTER_OUTSIDE_COPY,
                then=f"Write an address, such as {_example_address(parts[0], banks)}.",
            )
        bank, index_text = parts
        allowed = set(pointer_banks).intersection(ADDRESS_BANKS if banks is None else banks)
        if bank not in allowed:
            listed = ", ".join(b for b in ADDRESS_BANKS if b in allowed)
            raise at.error(
                value,
                says("is not allowed", "a pointer in {label} addresses {banks}", banks=listed),
                Reason.POINTER,
                cls=AddressError,
                code=Code.POINTER_BANK_NOT_ALLOWED,
            )
        try:
            index = check_address(index_text, field, {"DS"}, label=f"{at.label} pointer")
        except AddressError as exc:
            # Whatever refused the index, the pointer's index is no DS address.
            exc.reason = Reason.POINTER
            exc.code = Code.POINTER_NOT_DS
            raise
        return Operand(bank=bank, index=index)
    address = check_address(value, field, banks, label=label, bank_id=bank_id, bank_code=bank_code)
    return Operand(bank=address.bank, address=address)


def bank_of(
    value: str,
    field: str,
    *,
    pointer: bool = False,
    pointer_banks: Collection[str] = POINTER_BANKS,
) -> str | None:
    """Return the bank of ``value`` if :func:`check_operand` accepts it as an address in any
    bank. Return None for any other text.

    ``field`` names the field that ``value`` is read for, as for :func:`check_operand`. With
    ``pointer``, also return the bank of a pointer that :func:`check_operand` accepts, such
    as DD for ``DD[DS1]``. A pointer that it refuses, such as ``X[DS1]``, returns None.
    ``pointer_banks`` are the banks that a pointer may address, as for :func:`check_operand`.

    Without ``pointer``, a pointer returns None and builds no refusal.  The refusal of a
    pointer outside a single Copy would contradict itself for a Copy field.
    """
    if not pointer and split_pointer(value) is not None:
        return None
    try:
        return check_operand(value, field, pointer=pointer, pointer_banks=pointer_banks).bank
    except AddressError:
        return None


# ---------------------------------------------------------------------------
# Coil targets and flags
# ---------------------------------------------------------------------------

#: The banks a coil writes: Out, Set, Reset and the Out variants.
OUT_BANKS = frozenset({"Y", "C", "SC"})

#: The SC bits a coil writes: the read-write system bits.  No other SC is accepted.
WRITABLE_SC = frozenset(
    {50, 51, 53, 55, 60, 61, 65, 66, 67, 75, 76, 120, 121, 162, 165, 168, 171}
    | {303, 304, 305, 306, 323, 324, 325, 326}
)

#: The SD registers a single Copy, a Block Copy and a decimal Math write: the read-write
#: system registers.  No other SD is accepted in those fields.
WRITABLE_SD = frozenset(
    {29, 31, 32, 34, 35, 36, 40, 41, 42, 50, 51, 60, 61, 106, 107, 108, 112, 113, 114}
    | set(range(140, 148))
    | {214, 215}
)


def check_writable_sd(
    address: Address, field: str, *, label: str | None = None, click_id: str | None = None
) -> None:
    """Refuse an SD register outside :data:`WRITABLE_SD`, in a field that writes it.

    ``click_id`` is the id CLICK's dialog gives for the refusal, where it is known.  An
    address of another bank passes.
    """
    if address.bank != "SD" or address.number in WRITABLE_SD:
        return
    raise _at(field, label).error(
        address.display,
        says("is not a writable SD register", "the writable SD are {sds}", sds=_sd_list()),
        Reason.NOT_WRITABLE,
        click_id,
        cls=AddressError,
        code=Code.NOT_WRITABLE,
    )


def _sd_list() -> str:
    return ", ".join(f"SD{n}" for n in sorted(WRITABLE_SD))


def check_out_target(
    value: str,
    field: str,
    *,
    immediate: bool = False,
    banks: Collection[str] = OUT_BANKS,
    label: str | None = None,
    bank_id: str | None = None,
    not_writable_id: str | None = None,
) -> Address:
    """Check an address a coil writes; return it.

    The bank must be one of ``banks`` (Y, C and SC for Out, Set, Reset and the Out
    variants), an immediate target must be Y, and an SC bit must be one of
    :data:`WRITABLE_SC`.  When the instruction is immediate and the target is not Y, the
    refusal is a conflict between ``field`` and the instruction's ``immediate`` field.
    ``bank_id`` and ``not_writable_id`` are the ids CLICK's dialog gives for a bank the field
    does not take and for an SC bit it can't write, where they are known.
    """
    at = _at(field, label)
    address = check_address(value, field, banks, label=label, bank_id=bank_id)
    # Immediate first: an immediate SC target is refused whatever its number.
    if immediate and address.bank != "Y":
        raise at.error(
            value,
            says("is not allowed", "an immediate coil takes Y only"),
            Reason.CONFLICT,
            code=Code.IMMEDIATE_COIL_NOT_Y,
            also=f"{field.rsplit('.', 1)[0]}.immediate",
        )
    if address.bank == "SC" and address.number not in WRITABLE_SC:
        writable = ", ".join(f"SC{n}" for n in sorted(WRITABLE_SC))
        raise at.error(
            value,
            says("is not a writable SC bit", "a coil writes {sc}", sc=writable),
            Reason.NOT_WRITABLE,
            not_writable_id,
            cls=AddressError,
            code=Code.NOT_WRITABLE,
        )
    return address


def is_choice(value: object, choices: Collection[Any]) -> bool:
    """Return whether ``value`` is one of ``choices``.

    A value that can't be hashed, such as a list, is not one of them.  ``value in choices``
    raises ``TypeError`` for it when ``choices`` is a set or a dict.
    """
    try:
        return value in choices
    except TypeError:
        return False


def choice_operand(value: object) -> Op | str:
    """Return ``value`` as the refusal of a choice field names it.

    Text and a value that can be hashed are named as :func:`operand` names them, so a
    value that is not text has its whole repr.  A value that can't be hashed, such as a
    list, is named by :func:`shown`, which shortens a long repr.
    """
    try:
        hash(value)
    except Exception:  # noqa: BLE001 - a caller's __hash__ can raise anything
        return shown(value)
    return operand(value)


def check_flag(value: object, field: str) -> bool:
    """Return ``value`` as a bool; raise :class:`FieldError` naming ``field`` unless it is
    True, False, 1 or 0."""
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise make_refusal(
        FieldError,
        field,
        says("{value} is not True, False, 1 or 0", value=operand(value)),
        field=field,
        reason=Reason.FLAG,
        code=Code.NOT_A_FLAG,
    )


def check_csv_flag(kwargs: Mapping[str, str], name: str, field: str) -> bool:
    """Read the CSV flag keyword ``name`` (``oneshot=1``) from ``kwargs`` as a bool.

    The keyword is ``1`` or ``0``, and the flag is off when the keyword is absent.  A blank
    keyword (``oneshot=``) is refused as missing, and any other text is refused as not a
    flag.  Each refusal names ``field``.  Every CSV parser reads its 0/1 keywords with this
    function."""
    value = kwargs.get(name, "0")
    if value in ("0", "1"):
        return value == "1"
    if not value.strip():
        raise make_refusal(
            FieldError,
            field,
            says("is blank", "it needs a value, 1 or 0"),
            field=field,
            reason=Reason.MISSING,
            code=Code.BLANK_FIELD,
        )
    raise make_refusal(
        FieldError,
        field,
        says("{value} is not 1 or 0", value=Op(value)),
        field=field,
        reason=Reason.FLAG,
        code=Code.NOT_A_FLAG,
    )


# ---------------------------------------------------------------------------
# Every refusal of one instruction
# ---------------------------------------------------------------------------

_T = TypeVar("_T")


class Refusals:
    """Run one instruction's checks and raise every refusal as one :class:`FieldError`.

    An instruction's ``__post_init__`` runs its checks inside the ``with`` block.  When the
    block ends, the first refusal is raised, and its :attr:`~FieldError.errors` holds them
    all::

        with Refusals(self) as check:
            check.flag("retained")
            check.normalize("done", "accumulator")
            done = check("done", check_address, banks={"T"})
            accumulator = check("accumulator", check_address, banks={"TD"})
            if done is not None and accumulator is not None and done.number != accumulator.number:
                check.refuse(
                    ("accumulator", "done"), "...", Reason.CONFLICT, code=Code.TIMER_PAIR_MISMATCH
                )

    You name a field by its attribute, such as ``"outputs[2]"`` for an item, and the error
    names it as ``Class.attr``.  Once a field is refused, a later check or refusal that
    names it is skipped, so nothing that depends on a refused value is checked.  A refusal
    of a pair refuses only its leading field, and its partner is still checked.  A refusal
    of a list field counts for each of its items, and a refusal of an item counts for the
    list.

    A :class:`FieldError` raised straight out of the block ends the block.  Each of its
    :attr:`~FieldError.errors` joins the refusals by the same rules.  An instruction built
    inside the block brings all of its own refusals this way.  Any other exception also
    ends the block.  If refusals were already kept, the first of them is raised from that
    exception.  A later check that crashes therefore does not hide the refusals before it.
    """

    def __init__(self, inst: object) -> None:
        self._inst = inst
        self._cls = type(inst).__name__
        self._errors: list[FieldError] = []

    def __enter__(self) -> Refusals:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if exc is not None and not isinstance(exc, Exception):
            return False  # let KeyboardInterrupt and SystemExit through unchanged
        if isinstance(exc, FieldError):
            self.add(exc)
        if not self._errors:
            return False
        first = self._errors[0]
        first.errors = tuple(self._errors)
        if first is exc:
            return False
        if exc is not None and not isinstance(exc, FieldError):
            raise first from exc
        raise first

    def field(self, attr: str) -> str:
        """Return the field name of attribute ``attr``, as ``Class.attr``."""
        return f"{self._cls}.{attr}"

    def refused(self, *attrs: str) -> bool:
        """Whether any of ``attrs`` was refused, or an item of it, or the list it is in."""
        return self._names_refused(tuple(self.field(attr) for attr in attrs))

    def _names_refused(self, fields: tuple[str, ...], kept: int | None = None) -> bool:
        """Return whether one of ``fields``, its list or an item of it leads a kept refusal.

        Only the leading field of a refusal counts.  A refusal of a pair refuses its first
        field, and its partner is still checked on its own.  Given ``kept``, only the first
        ``kept`` refusals count."""

        def overlap(a: str, b: str) -> bool:
            return a == b or a.startswith(f"{b}[") or b.startswith(f"{a}[")

        return any(
            e.field is not None and overlap(f, e.field) for e in self._errors[:kept] for f in fields
        )

    def add(self, error: FieldError) -> None:
        """Keep each of ``error``'s :attr:`~FieldError.errors`, unless it names a field that
        was refused before ``error`` arrived.  The refusals from one check therefore stay
        together, such as every refusal of a Math formula, which all name
        ``Math.expression``."""
        before = len(self._errors)
        for each in error.errors:
            if not self._names_refused(each.fields, before):
                self._mark_blank(each)
                self._errors.append(each)

    def _mark_blank(self, error: FieldError) -> None:
        """Give a refusal of a blank field of this instruction the reason ``missing`` and the
        code ``blank-field``.

        A field's own check, such as for a choice or a number, words a blank as a bad value.
        Whatever check refused it, the caller sees a blank as :attr:`Reason.MISSING`.  Only
        refusals reach this method, never an accepted blank.  The refusal keeps its CLICK
        id.
        """
        field = error.field
        prefix = f"{self._cls}."
        if error.reason is Reason.MISSING or field is None or not field.startswith(prefix):
            return
        name, _, index = field[len(prefix) :].partition("[")
        try:
            value = getattr(self._inst, name)
            if index:
                value = value[int(index[:-1])]
        except (AttributeError, IndexError, ValueError):
            return
        if isinstance(value, str) and value == "":
            error.reason = Reason.MISSING
            error.code = Code.BLANK_FIELD
            # The message says what is wrong with the value.  A blank is wrong the same way
            # wherever it is refused, so every blank gets this one message.  CLICK's id, if
            # any, stays on the error, and the message does not show it.
            set_parts(error, Parts(field, ("is blank",), ("it needs a value",)))

    def run(self, check: Callable[..., _T], *args: Any, **kwargs: Any) -> _T | None:
        """Return ``check(*args, **kwargs)``.  If it raises :class:`FieldError`, keep the
        refusal and return None."""
        try:
            return check(*args, **kwargs)
        except FieldError as exc:
            self.add(exc)
            return None

    def __call__(self, attr: str, check: Callable[..., _T], *args: Any, **kwargs: Any) -> _T | None:
        """Run ``check(value, field, *args, **kwargs)`` on attribute ``attr`` and return the
        result.

        Return None when the check refuses the value, or when ``attr`` was refused before.
        """
        if self.refused(attr):
            return None
        name, _, index = attr.partition("[")
        value = getattr(self._inst, name)
        if index:
            value = value[int(index[:-1])]
        return self.run(check, value, self.field(attr), *args, **kwargs)

    def refuse(
        self,
        attrs: str | tuple[str, ...],
        rule: Rule,
        reason: Reason,
        click_id: str | None = None,
        *,
        code: Code,
        then: str | None = None,
    ) -> None:
        """Refuse ``attrs``, one field or a pair, with the message ``Class.attr: rule``.

        In a pair, the first field leads, and the message names it.  CLICK's id follows the
        rule in parentheses.  ``then`` is a sentence that tells the user what to do.  It
        follows the id.

        Pass ``rule`` as a :class:`~laddercodec.operands.message.Rule` from
        :func:`~laddercodec.operands.message.says`, and the error keeps the parts of its
        message.
        """
        fields = tuple(map(self.field, (attrs,) if isinstance(attrs, str) else attrs))
        self.add(
            make_refusal(
                FieldError,
                fields[0],
                rule,
                field=fields,
                reason=reason,
                code=code,
                click_id=click_id,
                then=then or "",
            )  # fmt: skip
        )

    def flag(self, *attrs: str) -> None:
        """Check each True/False field and store it as a bool."""
        for attr in attrs:
            value = self(attr, check_flag)
            if value is not None:
                object.__setattr__(self._inst, attr, value)

    def normalize(self, *attrs: str, values: Collection[str] = ()) -> None:
        """Write each field in display form (see
        :func:`~laddercodec.operands.address.normalize_fields`).

        ``values`` names the fields that hold a constant as well as an address."""
        for attr in attrs:
            self.run(normalize_fields, self._inst, attr, values=values)
