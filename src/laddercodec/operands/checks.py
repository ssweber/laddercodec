"""Shared field checks: one call per instruction field, with that field's parameters.

- :func:`~laddercodec.operands.address.check_address`: an address in the field's banks.
- :func:`check_constant`: a constant of the kinds and limits a :class:`Constants` names.
- :func:`check_operand`: an address, a pointer or a constant, in one field;
  :func:`constant_shape` names the kind of constant a text is spelled as, limits aside.
- :func:`check_quoted_text`: a quoted text constant, as Compare and Search take it.
- :func:`check_out_target`: an address a coil writes.
- :func:`check_flag`: a True/False field.
- :class:`Refusals`: runs one instruction's checks and raises every refusal as one error.

:data:`BIT_BANKS` and :data:`REGISTER_BANKS` are the bank sets more than one family uses.

Every refusal is a :class:`~laddercodec.operands.errors.FieldError` (an
:class:`~laddercodec.operands.errors.AddressError` for an address or a pointer) whose
``field`` is the ``field`` the caller gave, as ``Class.attr``, and whose ``reason`` is a
:class:`~laddercodec.operands.errors.Reason`.  The message names ``label``, or the field
when no label is given.  The constant checks build on
:func:`~laddercodec.operands.constants.classify`.

Not public API.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection
from dataclasses import dataclass
from types import TracebackType
from typing import Any, NamedTuple, TypeVar

from .address import ADDRESS_BANKS, Address, check_address, normalize_fields
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
from .errors import AddressError, FieldError, Reason

__all__ = [
    "ALL_KINDS",
    "BIT_BANKS",
    "OUT_BANKS",
    "POINTER_BANKS",
    "REGISTER_BANKS",
    "WRITABLE_SC",
    "Constants",
    "Operand",
    "Refusals",
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


class _At(NamedTuple):
    """The field a check refuses for, and the label its messages name."""

    field: str
    label: str

    def error(
        self,
        value: str,
        rule: str,
        reason: Reason,
        click_id: str | None = None,
        cls: type[FieldError] = FieldError,
        *,
        also: str | None = None,
    ) -> FieldError:
        """``label: 'value' rule``, with CLICK's id at the end; ``also`` is the other field
        of a refused pair."""
        tail = f" ({click_id})" if click_id else ""
        return cls(
            f"{self.label}: {value!r} {rule}{tail}",
            field=self.field if also is None else (self.field, also),
            reason=reason,
            click_id=click_id,
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


def _kind_refusal(value: str, at: _At, kind: Kind, constants: Constants) -> FieldError:
    """The refusal of a constant of a kind the field does not take."""
    return at.error(
        value,
        f"is {_kinds_text([kind])}; {at.label} takes {_kinds_text(constants.kinds)}",
        Reason.KIND,
    )


def _hex_above(value: str, at: _At, constants: Constants) -> FieldError:
    """The refusal of a hex constant above the field's highest."""
    high = f"{constants.hex_high:X}h"
    return at.error(
        value, f"is above {high}; a hex constant here is 0h to {high}", Reason.RANGE, "OBJ-005"
    )


def _unread(value: str, at: _At, constants: Constants) -> FieldError:
    """The refusal of text :func:`classify` reads no constant in, worded by the field's own
    kinds and limits."""
    kinds = constants.kinds
    if len(value) >= 2 and value[0] == value[-1] == '"':
        if Kind.TEXT not in kinds:
            return _kind_refusal(value, at, Kind.TEXT, constants)
        if constants.text_max == 1:
            rule = "a text constant is one character in quotes"
        else:
            rule = f"a text constant is 1 to {constants.text_max} characters in quotes"
        # classify() refuses a quote inside, an empty text and a longer one.
        reason = Reason.FORM if '"' in value[1:-1] else Reason.RANGE
        return at.error(
            value,
            f"is refused; {rule}, with no quote inside (write the quote character as $22)",
            reason,
        )
    upper = value.upper() if value.isascii() else ""
    m = _HEX_SHAPE.fullmatch(upper)
    if m is not None:
        if Kind.HEX not in kinds:
            return _kind_refusal(value, at, Kind.HEX, constants)
        if m.group(1):
            return at.error(value, "is refused; a hex constant has no sign", Reason.FORM)
        if int(upper[:-1], 16) > constants.hex_high:
            return _hex_above(value, at, constants)
        # Past FFFFh only the digit count refuses: 0FFFFFFFFh is no 32-bit constant.
        return at.error(
            value, "is refused; a hex constant above FFFFh has at most 8 digits", Reason.RANGE
        )
    if _INTEGER_SHAPE.fullmatch(upper):
        # check_constant words an integer for a field that takes integers, so only a field
        # that does not take them gets here.
        return _kind_refusal(value, at, Kind.INTEGER, constants)
    if _FLOAT_SHAPE.fullmatch(upper):
        if Kind.FLOAT not in kinds:
            return _kind_refusal(value, at, Kind.FLOAT, constants)
        return at.error(
            value,
            "is refused; a real constant is a finite number within float32 "
            "(up to about 3.4028235E+38)",
            Reason.RANGE,
        )
    if kinds == ALL_KINDS:
        rule = "it is not a constant"
    elif kinds == {Kind.HEX}:
        rule = f"{at.label} takes a hex value: hex digits then h"
    else:
        rule = f"{at.label} takes {_kinds_text(kinds)}"
    return at.error(value, f"is refused; {rule}", Reason.KIND)


def check_constant(
    value: str, field: str, constants: Constants, *, label: str | None = None
) -> Constant:
    """Return the constant ``value`` spells; raise :class:`FieldError` naming ``field``
    unless it is one ``constants`` takes.

    :func:`~laddercodec.operands.constants.classify` reads the text; ``constants`` then
    applies the field's kinds and limits.  A real beyond float32 is read only when
    :attr:`Constants.float32` is off.
    """
    at = _at(field, label)
    if value.startswith("$"):
        const = classify(value)
        if const is None or const.kind is not Kind.CHAR:
            if Kind.CHAR in constants.kinds:
                raise at.error(value, f"is refused; {CHAR_CODE_RULE}", Reason.FORM)
            rule = f"{at.label} takes {_kinds_text(constants.kinds)}"
            raise at.error(value, f"is refused; {rule}", Reason.KIND)
    else:
        const = classify(value)
        if (
            const is None
            and not constants.float32
            and constant_shape(value, constants) is Kind.FLOAT
        ):
            const = Constant(Kind.FLOAT, float(value))
        if const is None:
            if Kind.INTEGER in constants.kinds and _INTEGER_SHAPE.fullmatch(value.upper()):
                # An integer beyond int32: the field's own sign and limits word the refusal.
                _check_sign(value, at, constants)
                raise _outside(value, at, constants)
            raise _unread(value, at, constants)
    if const.kind not in constants.kinds:
        raise _kind_refusal(value, at, const.kind, constants)
    _check_limits(value, at, constants, const)
    return const


def _outside(value: str, at: _At, constants: Constants) -> FieldError:
    """The refusal of a decimal integer outside the field's limits."""
    # Without a '-' the lowest value a field can take is 0.
    low = constants.low if "-" in constants.signs else max(constants.low, 0)
    return at.error(value, f"is outside {low} to {constants.high}", Reason.RANGE, "OBJ-005")


def _check_sign(value: str, at: _At, constants: Constants) -> None:
    """Refuse a leading sign the field does not take."""
    if value[:1] in "+-" and value[0] not in constants.signs:
        # Name the sign the field refuses: "no plus sign" where a minus sign stands.
        refused = {"+": "plus ", "-": "minus "}[value[0]] if constants.signs else ""
        raise at.error(
            value, f"is refused; a constant here takes no {refused}sign", Reason.FORM, "OBJ-005"
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
        text = str(const.value)
        if len(text) > constants.text_max:
            if constants.text_max == 1:
                raise at.error(
                    value,
                    f"is {len(text)} characters; {at.label} takes one character",
                    Reason.RANGE,
                    "OBJ-023",
                )
            raise at.error(
                value,
                f"is {len(text)} characters; {at.label} takes at most {constants.text_max}",
                Reason.RANGE,
            )
        if constants.printable and not printable(text):
            raise at.error(
                value,
                "is refused; text holds printable ASCII only (space to ~); write another "
                "character as its $hh code",
                Reason.FORM,
            )
    if constants.max_length is not None and len(value) > constants.max_length:
        raise at.error(
            value,
            f"is {len(value)} characters; a constant here is at most {constants.max_length}",
            Reason.RANGE,
            "OBJ-005",
        )


#: The characters a quoted text constant may hold: printable ASCII, space to ``~``.
_TEXT_CHARS = range(0x20, 0x7F)


def check_quoted_text(value: str, field: str, *, label: str | None = None) -> None:
    """Refuse a quoted text constant Compare and Search refuse.

    The text between the quotes is 1 to :data:`TEXT_MAX` printable ASCII characters,
    with no quote inside: a quote would end the text in the CSV token, so it is written
    ``$22``.  On hardware the text is compared against consecutive TXT registers from the
    named one.
    """
    at = _at(field, label)
    inner = value[1:-1]
    long = not 1 <= len(inner) <= TEXT_MAX
    if long or any(ord(c) not in _TEXT_CHARS for c in inner):
        raise at.error(
            value,
            f"is refused; a text constant is 1 to {TEXT_MAX} printable ASCII characters in "
            "quotes (use $hh for a character by code)",
            Reason.RANGE if long else Reason.FORM,
        )
    if '"' in inner:
        raise at.error(value, "holds a quote; write the quote character as $22", Reason.FORM)


# ---------------------------------------------------------------------------
# Operands
# ---------------------------------------------------------------------------

#: The banks a pointer ``BANK[DSn]`` can address.
POINTER_BANKS = frozenset({"C", "DS", "DD", "DH", "DF", "XD", "YD", "TD", "CTD", "TXT"})

_POINTER_RE = re.compile(r"([A-Z]{1,3})\[(.*)\]")


def check_operand(
    value: str,
    field: str,
    banks: Collection[str] | None = None,
    constants: Constants | None = None,
    *,
    pointer: bool = False,
    letter_first: bool = False,
    label: str | None = None,
    bank_id: str | None = None,
) -> Operand:
    """Check one operand; raise :class:`FieldError` naming ``field`` if it is refused.

    An address goes through :func:`check_address`, narrowed to ``banks`` (``None``: any
    bank).  With ``pointer``, ``BANK[DSn]`` passes: ``BANK`` is in ``banks`` and in
    :data:`POINTER_BANKS`, and the index is a DS address.  With ``constants``, a constant
    goes through :func:`check_constant`.  Every refusal of a pointer, its index's included,
    has the reason ``pointer``.  ``bank_id`` is CLICK's id for an address in a bank the
    field does not take, as for :func:`check_address`.

    Which of the two checks reads the text:

    - by default, text spelled as a constant of a kind ``constants`` takes is a constant,
      and any other text is an address (refused with :class:`AddressError`);
    - with ``letter_first``, text that starts with a letter is an address, and any other
      text is a constant (refused with :class:`FieldError`).
    """
    at = _at(field, label)
    if constants is not None:
        if letter_first:
            is_constant = not value[:1].isalpha()
        else:
            is_constant = constant_shape(value, constants) in constants.kinds
        if is_constant:
            return Operand(constant=check_constant(value, field, constants, label=label))
    m = _POINTER_RE.fullmatch(value)
    if m is not None:
        if not pointer:
            raise at.error(
                value, f"is a pointer; {at.label} takes none", Reason.POINTER, cls=AddressError
            )
        bank = m.group(1)
        allowed = POINTER_BANKS.intersection(ADDRESS_BANKS if banks is None else banks)
        if bank not in allowed:
            listed = ", ".join(b for b in ADDRESS_BANKS if b in allowed)
            raise at.error(
                value,
                f"is not allowed; a pointer in {at.label} addresses {listed}",
                Reason.POINTER,
                cls=AddressError,
            )
        try:
            index = check_address(m.group(2), field, {"DS"}, label=f"{at.label} pointer")
        except AddressError as exc:
            exc.reason = Reason.POINTER
            raise
        return Operand(bank=bank, index=index)
    address = check_address(value, field, banks, label=label, bank_id=bank_id)
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

    The bank is one of ``banks`` (Y, C and SC for Out, Set, Reset and the Out variants),
    an immediate target is Y, and an SC bit is one of :data:`WRITABLE_SC`.  A target the
    immediate box refuses is a conflict of ``field`` with the instruction's ``immediate``.
    ``bank_id`` and ``not_writable_id`` are the ids CLICK's dialog gives for a bank the field
    does not take and for an SC bit it can't write, where they are known.
    """
    at = _at(field, label)
    address = check_address(value, field, banks, label=label, bank_id=bank_id)
    # Immediate first: an immediate SC target is refused whatever its number.
    if immediate and address.bank != "Y":
        raise at.error(
            value,
            "is not allowed; an immediate coil takes Y only",
            Reason.CONFLICT,
            also=f"{field.rsplit('.', 1)[0]}.immediate",
        )
    if address.bank == "SC" and address.number not in WRITABLE_SC:
        writable = ", ".join(f"SC{n}" for n in sorted(WRITABLE_SC))
        raise at.error(
            value,
            f"is not a writable SC bit; a coil writes {writable}",
            Reason.NOT_WRITABLE,
            not_writable_id,
            cls=AddressError,
        )
    return address


def check_flag(value: object, field: str) -> bool:
    """Return ``value`` as a bool; raise :class:`FieldError` naming ``field`` unless it is
    True, False, 1 or 0."""
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise FieldError(
        f"{field}: {value!r} is not True, False, 1 or 0", field=field, reason=Reason.FLAG
    )


# ---------------------------------------------------------------------------
# Every refusal of one instruction
# ---------------------------------------------------------------------------

_T = TypeVar("_T")


class Refusals:
    """Run one instruction's checks and raise every refusal as one :class:`FieldError`.

    ``__post_init__`` runs its checks inside the block; on leaving it, the first refusal
    is raised with :attr:`~FieldError.errors` holding them all::

        with Refusals(self) as check:
            check.flag("retained")
            check.normalize("done_bit", "current")
            done = check("done_bit", check_address, banks={"T"})
            current = check("current", check_address, banks={"TD"})
            if done is not None and current is not None and done.number != current.number:
                check.refuse(("current", "done_bit"), "...", Reason.CONFLICT)

    A field is named by its attribute (``"outputs[2]"`` for an item); the error names
    ``Class.attr``.  Once a field is refused, a later check or refusal that names it is
    skipped: what depends on a refused value is not checked.  A refusal of a pair refuses
    its leading field only, so its partner is still checked.  A refusal of a list field
    counts for each of its items, and a refusal of an item for the list.  A
    :class:`FieldError` raised straight out of the block ends it and joins the refusals the
    same way, each of its :attr:`~FieldError.errors` (an instruction built inside the block
    brings all of its own).  Any other exception ends the block too; with refusals already
    kept, the first is raised from it, so a value that crashes a later check (None where
    text belongs) does not hide them.
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
            return False  # KeyboardInterrupt, SystemExit: not ours to replace
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
        """The field name of attribute ``attr``: ``Class.attr``."""
        return f"{self._cls}.{attr}"

    def refused(self, *attrs: str) -> bool:
        """Whether any of ``attrs`` was refused, or an item of it, or the list it is in."""
        return self._names_refused(tuple(self.field(attr) for attr in attrs))

    def _names_refused(self, fields: tuple[str, ...]) -> bool:
        """Whether one of ``fields`` leads a kept refusal (its list or an item of it too).

        Only the leading field counts: a refusal of a pair refuses its first field, and its
        partner is still checked on its own."""

        def overlap(a: str, b: str) -> bool:
            return a == b or a.startswith(f"{b}[") or b.startswith(f"{a}[")

        return any(
            e.field is not None and overlap(f, e.field) for e in self._errors for f in fields
        )

    def add(self, error: FieldError) -> None:
        """Keep each of ``error``'s :attr:`~FieldError.errors`, unless it names a field
        already refused."""
        for each in error.errors:
            if not self._names_refused(each.fields):
                self._errors.append(each)

    def run(self, check: Callable[..., _T], *args: Any, **kwargs: Any) -> _T | None:
        """``check(*args, **kwargs)``; None when it raises :class:`FieldError`, kept."""
        try:
            return check(*args, **kwargs)
        except FieldError as exc:
            self.add(exc)
            return None

    def __call__(self, attr: str, check: Callable[..., _T], *args: Any, **kwargs: Any) -> _T | None:
        """``check(value, field, *args, **kwargs)`` on attribute ``attr``.

        None when the check refuses the value or ``attr`` was refused before.
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
        rule: str,
        reason: Reason,
        click_id: str | None = None,
    ) -> None:
        """Refuse ``attrs``, one field or a pair, the first leading: ``Class.attr: rule``."""
        fields = tuple(map(self.field, (attrs,) if isinstance(attrs, str) else attrs))
        tail = f" ({click_id})" if click_id else ""
        self.add(
            FieldError(f"{fields[0]}: {rule}{tail}", field=fields, reason=reason, click_id=click_id)
        )

    def flag(self, *attrs: str) -> None:
        """Check each True/False field and store it as a bool."""
        for attr in attrs:
            value = self(attr, check_flag)
            if value is not None:
                setattr(self._inst, attr, value)

    def normalize(self, *attrs: str) -> None:
        """Write each field in display form (see
        :func:`~laddercodec.operands.address.normalize_fields`)."""
        for attr in attrs:
            self.run(normalize_fields, self._inst, attr)
