"""Shared field checks: one call per instruction field, with that field's parameters.

- :func:`~laddercodec.operands.address.check_address`: an address in the field's banks.
- :func:`check_constant`: a constant of the kinds and limits a :class:`Constants` names.
- :func:`check_operand`: an address, a pointer or a constant, in one field;
  :func:`constant_shape` names the kind of constant a text is spelled as, limits aside.
- :func:`check_quoted_text`: a quoted text constant, as Compare and Search take it.
- :func:`check_out_target`: an address a coil writes.
- :func:`check_flag`: a True/False field.

:data:`BIT_BANKS` and :data:`REGISTER_BANKS` are the bank sets more than one family uses.

Every refusal is a :class:`~laddercodec.operands.errors.FieldError` (an
:class:`~laddercodec.operands.errors.AddressError` for an address or a pointer) whose
``field`` is the ``name`` the caller gave.  The constant checks build on
:func:`~laddercodec.operands.constants.classify`.

Not public API.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import NamedTuple

from .address import ADDRESS_BANKS, Address, check_address
from .constants import (
    CHAR_CODE_RULE,
    INT32_MAX,
    INT32_MIN,
    TEXT_MAX,
    Constant,
    Kind,
    classify,
    printable,
)
from .errors import AddressError, FieldError

__all__ = [
    "ALL_KINDS",
    "BIT_BANKS",
    "OUT_BANKS",
    "POINTER_BANKS",
    "REGISTER_BANKS",
    "WRITABLE_SC",
    "Constants",
    "Operand",
    "check_address",
    "check_constant",
    "check_flag",
    "check_operand",
    "check_out_target",
    "check_quoted_text",
    "constant_shape",
]

#: Every constant kind.
ALL_KINDS: frozenset[Kind] = frozenset(Kind)

#: The bit banks.
BIT_BANKS = frozenset({"X", "Y", "C", "T", "CT", "SC"})
#: The register banks.
REGISTER_BANKS = frozenset({"DS", "DD", "DH", "DF", "XD", "YD", "TD", "CTD", "SD", "TXT"})

#: The highest 32-bit hex constant.
_HEX32_HIGH = 0xFFFFFFFF


@dataclass(frozen=True)
class Constants:
    """The constants one field takes: the parameters of :func:`check_constant`.

    The defaults are :func:`~laddercodec.operands.constants.classify`'s own limits, with
    text in printable ASCII.
    """

    #: The kinds the field takes.
    kinds: frozenset[Kind]
    #: The signs a decimal integer or a real may start with: ``"+-"``, ``"-"`` (a
    #: counter preset) or ``""`` (digits only: a timer set point).
    signs: str = "+-"
    #: The lowest and highest decimal integer.
    low: int = INT32_MIN
    high: int = INT32_MAX
    #: The highest hex value: ``0xFFFF`` where a field takes 16-bit hex only.
    hex_high: int = _HEX32_HIGH
    #: Whether a sign before hex digits (``+1h``) reads as a hex constant.  Such text is
    #: refused either way: this decides whether :func:`check_operand` refuses it as a
    #: constant (:class:`FieldError`) or as an address (:class:`AddressError`).
    hex_sign: bool = False
    #: Whether a real is within float32.  ``False`` takes any real spelling.
    float32: bool = True
    #: The most characters between the quotes of a text constant.
    text_max: int = TEXT_MAX
    #: Whether a text constant holds printable ASCII only (space to ``~``).
    printable: bool = True
    #: The most characters the typed constant may have, or ``None``.
    max_length: int | None = None


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


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Shapes, on uppercase text, with any sign; constant_shape() narrows them to a field's signs.
_HEX_SHAPE = re.compile(r"([+-]?)[0-9A-F]+H")
_INTEGER_SHAPE = re.compile(r"([+-]?)[0-9]+")
_FLOAT_SHAPE = re.compile(r"([+-]?)(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:E[+-]?[0-9]+)?")


def constant_shape(value: str, constants: Constants) -> Kind | None:
    """The kind of constant ``value`` is spelled as, limits aside; ``None`` for other text.

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


def _unread(value: str) -> str:
    """Why :func:`classify` reads no constant in ``value``."""
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return (
            f"a text constant is 1 to {TEXT_MAX} characters in quotes, with no quote inside "
            "(write the quote character as $22)"
        )
    upper = value.upper() if value.isascii() else ""
    if _HEX_SHAPE.fullmatch(upper):
        return "a hex constant has no sign and at most 8 digits"
    if _INTEGER_SHAPE.fullmatch(upper):
        return f"an integer constant is {INT32_MIN} to {INT32_MAX}"
    if _FLOAT_SHAPE.fullmatch(upper):
        return "a real constant is a finite number within float32 (up to about 3.4028235E+38)"
    return "it is not a constant"


def check_constant(value: str, name: str, constants: Constants) -> Constant:
    """Return the constant ``value`` spells; raise :class:`FieldError` naming field ``name``
    unless it is one ``constants`` takes.

    :func:`~laddercodec.operands.constants.classify` reads the text; ``constants`` then
    applies the field's kinds and limits.  A real beyond float32 is read only when
    :attr:`Constants.float32` is off.
    """
    if value.startswith("$"):
        const = classify(value)
        if const is None or const.kind is not Kind.CHAR:
            raise FieldError(f"{name}: {value!r} is refused; {CHAR_CODE_RULE}", field=name)
    else:
        const = classify(value)
        if (
            const is None
            and not constants.float32
            and constant_shape(value, constants) is Kind.FLOAT
        ):
            const = Constant(Kind.FLOAT, float(value))
        if const is None:
            raise FieldError(f"{name}: {value!r} is refused; {_unread(value)}", field=name)
    if const.kind not in constants.kinds:
        raise FieldError(
            f"{name}: {value!r} is {_kinds_text([const.kind])}; {name} takes "
            f"{_kinds_text(constants.kinds)}",
            field=name,
        )
    _check_limits(value, name, constants, const)
    return const


def _check_limits(value: str, name: str, constants: Constants, const: Constant) -> None:
    """Refuse a constant outside the field's limits."""
    kind = const.kind
    if kind in (Kind.INTEGER, Kind.FLOAT) and value[:1] in "+-" and value[0] not in constants.signs:
        signs = " or ".join(constants.signs) if constants.signs else "no sign"
        raise FieldError(
            f"{name}: {value!r} is refused; a constant here takes {signs} (OBJ-005)", field=name
        )
    # Without a '-' the lowest value a field can take is 0.
    low = constants.low if "-" in constants.signs else max(constants.low, 0)
    if kind is Kind.INTEGER and not low <= int(const.value) <= constants.high:
        raise FieldError(
            f"{name}: {value!r} is outside {low} to {constants.high} (OBJ-005)",
            field=name,
        )
    if kind is Kind.HEX and int(const.value) > constants.hex_high:
        raise FieldError(
            f"{name}: {value!r} is above {constants.hex_high:X}h; a hex constant here is 0h to "
            f"{constants.hex_high:X}h (OBJ-005)",
            field=name,
        )
    if kind is Kind.TEXT:
        text = str(const.value)
        if len(text) > constants.text_max:
            if constants.text_max == 1:
                raise FieldError(
                    f"{name}: {value!r} is {len(text)} characters; {name} takes one "
                    "character (OBJ-023)",
                    field=name,
                )
            raise FieldError(
                f"{name}: {value!r} is {len(text)} characters; {name} takes at most "
                f"{constants.text_max}",
                field=name,
            )
        if constants.printable and not printable(text):
            raise FieldError(
                f"{name}: {value!r} is refused; text holds printable ASCII only (space to ~); "
                "write another character as its $hh code",
                field=name,
            )
    if constants.max_length is not None and len(value) > constants.max_length:
        raise FieldError(
            f"{name}: {value!r} is {len(value)} characters; a constant here is at most "
            f"{constants.max_length} (OBJ-005)",
            field=name,
        )


#: The characters a quoted text constant may hold: printable ASCII, space to ``~``.
_TEXT_CHARS = range(0x20, 0x7F)


def check_quoted_text(value: str, name: str) -> None:
    """Refuse a quoted text constant Compare and Search refuse.

    The text between the quotes is 1 to :data:`TEXT_MAX` printable ASCII characters,
    with no quote inside: a quote would end the text in the CSV token, so it is written
    ``$22``.  On hardware the text is compared against consecutive TXT registers from the
    named one.
    """
    inner = value[1:-1]
    if not 1 <= len(inner) <= TEXT_MAX or any(ord(c) not in _TEXT_CHARS for c in inner):
        raise FieldError(
            f"{name}: {value!r} is refused; a text constant is 1 to {TEXT_MAX} "
            "printable ASCII characters in quotes (use $hh for a character by code)",
            field=name,
        )
    if '"' in inner:
        raise FieldError(
            f"{name}: {value!r} holds a quote; write the quote character as $22", field=name
        )


# ---------------------------------------------------------------------------
# Operands
# ---------------------------------------------------------------------------

#: The banks a pointer ``BANK[DSn]`` can address.
POINTER_BANKS = frozenset({"C", "DS", "DD", "DH", "DF", "XD", "YD", "TD", "CTD", "TXT"})

_POINTER_RE = re.compile(r"([A-Z]{1,3})\[(.*)\]")


def check_operand(
    value: str,
    name: str,
    banks: Collection[str] | None = None,
    constants: Constants | None = None,
    *,
    pointer: bool = False,
    letter_first: bool = False,
) -> Operand:
    """Check one operand; raise :class:`FieldError` naming field ``name`` if it is refused.

    An address goes through :func:`check_address`, narrowed to ``banks`` (``None``: any
    bank).  With ``pointer``, ``BANK[DSn]`` passes: ``BANK`` is in ``banks`` and in
    :data:`POINTER_BANKS`, and the index is a DS address.  With ``constants``, a constant
    goes through :func:`check_constant`.

    Which of the two checks reads the text:

    - by default, text spelled as a constant of a kind ``constants`` takes is a constant,
      and any other text is an address (refused with :class:`AddressError`);
    - with ``letter_first``, text that starts with a letter is an address, and any other
      text is a constant (refused with :class:`FieldError`).
    """
    if constants is not None:
        if letter_first:
            is_constant = not value[:1].isalpha()
        else:
            is_constant = constant_shape(value, constants) in constants.kinds
        if is_constant:
            return Operand(constant=check_constant(value, name, constants))
    m = _POINTER_RE.fullmatch(value)
    if m is not None:
        if not pointer:
            raise AddressError(f"{name}: {value!r} is a pointer; {name} takes none", field=name)
        bank = m.group(1)
        allowed = POINTER_BANKS.intersection(ADDRESS_BANKS if banks is None else banks)
        if bank not in allowed:
            listed = ", ".join(b for b in ADDRESS_BANKS if b in allowed)
            raise AddressError(
                f"{name}: {value!r} is not allowed; a pointer in {name} addresses {listed}",
                field=name,
            )
        try:
            index = check_address(m.group(2), name, {"DS"})
        except AddressError:
            raise AddressError(
                f"{name}: {value!r} is refused; a pointer's index is a DS address", field=name
            ) from None
        return Operand(bank=bank, index=index)
    address = check_address(value, name, banks)
    return Operand(bank=address.bank, address=address)


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


def check_out_target(
    value: str, name: str, *, immediate: bool = False, banks: Collection[str] = OUT_BANKS
) -> Address:
    """Check an address a coil writes; return it.

    The bank is one of ``banks`` (Y, C and SC for Out, Set, Reset and the Out variants),
    an immediate target is Y, and an SC bit is one of :data:`WRITABLE_SC`.
    """
    address = check_address(value, name, banks)
    # Immediate first: an immediate SC target is refused whatever its number.
    if immediate and address.bank != "Y":
        raise FieldError(
            f"{name}: {value!r} is not allowed; an immediate coil takes Y only", field=name
        )
    if address.bank == "SC" and address.number not in WRITABLE_SC:
        writable = ", ".join(f"SC{n}" for n in sorted(WRITABLE_SC))
        raise AddressError(
            f"{name}: {value!r} is not a writable SC bit; a coil writes {writable}", field=name
        )
    return address


def check_flag(value: object, name: str) -> bool:
    """Return ``value`` as a bool; raise :class:`FieldError` naming field ``name`` unless
    it is True, False, 1 or 0."""
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise FieldError(f"{name}: {value!r} is not True, False, 1 or 0", field=name)
