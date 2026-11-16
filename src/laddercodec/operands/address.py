"""CLICK addresses: the banks, the address check and the display form.

:func:`check_address` parses and checks an address, :func:`normalize_address` writes it
in the form CLICK shows, and ``OPERAND_RE`` is the shape the CSV token parser uses to
tell a contact from other condition tokens.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Collection, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, NamedTuple

from .errors import AddressError, FieldError, Reason

#: Shape of an address token, in any letter case; the CSV token parser uses it to tell a
#: contact from other condition tokens.  :func:`check_address` checks the bank and number.
OPERAND_RE = re.compile(r"^[A-Za-z]{1,3}[0-9]{1,5}$")


#: Number range of every CLICK address bank.  X and Y number by slot (see :data:`XY_SLOTS`).
#: XD and YD are ``XD0`` (slot 0), ``XD0u`` (slot 1) and ``XD1``-``XD8`` (expansion 1-8).
ADDRESS_BANKS: dict[str, tuple[int, int]] = {
    "X": (1, 816),
    "Y": (1, 816),
    "C": (1, 2000),
    "T": (1, 500),
    "CT": (1, 250),
    "SC": (1, 1000),
    "DS": (1, 4500),
    "DD": (1, 1000),
    "DH": (1, 500),
    "DF": (1, 500),
    "XD": (0, 8),
    "YD": (0, 8),
    "TD": (1, 500),
    "CTD": (1, 250),
    "SD": (1, 1000),
    "TXT": (1, 1000),
}

#: The ten 16-point X/Y slots: ``(first, last)`` point numbers.  1-16 is the CPU, 21-36 the
#: CPU's dual option slot (its word form is ``XD0u``/``YD0u``), 101-116 to 801-816 the
#: expansion modules 1-8.
XY_SLOTS: tuple[tuple[int, int], ...] = ((1, 16), (21, 36)) + tuple(
    (100 * m + 1, 100 * m + 16) for m in range(1, 9)
)

_MODULE_BANKS = frozenset({"X", "Y"})
_WORD_IO_BANKS = frozenset({"XD", "YD"})
_ADDRESS_RE = re.compile(r"([A-Z]{1,3})([0-9]{1,5})(u?)")


class Address(NamedTuple):
    """A parsed CLICK address: ``XD0u`` is ``Address("XD", 0, upper=True)``."""

    bank: str
    number: int
    upper: bool = False

    @property
    def display(self) -> str:
        """The address as CLICK shows and stores it: ``X001``, ``C1``, ``XD0u``.

        X and Y pad the number to 3 digits; every other bank writes it unpadded.
        """
        number = f"{self.number:03d}" if self.bank in _MODULE_BANKS else str(self.number)
        return f"{self.bank}{number}{'u' if self.upper else ''}"


#: Address text in any letter case, with or without leading zeros (``x1``, ``ds07``,
#: ``XD0U``), and a pointer ``BANK[address]``.
_LOOSE_ADDRESS_RE = re.compile(r"([A-Za-z]{1,3})([0-9]{1,5})([uU]?)")
_LOOSE_POINTER_RE = re.compile(r"([A-Za-z]{1,3})\[([^\[\]]*)\]")


#: Set while a decoder builds an instruction from a blob: text not in display form is
#: refused, so the blob stays raw rather than re-encode as different bytes.
_DISPLAY_FORM_ONLY: ContextVar[bool] = ContextVar("_DISPLAY_FORM_ONLY", default=False)


class NotDisplayForm(FieldError):
    """Text not in CLICK's display form, refused inside :func:`display_form_only`."""


@contextmanager
def display_form_only() -> Generator[None]:
    """Refuse, rather than normalize, text that is not in CLICK's display form.

    The ``from_tags`` dispatchers build instructions inside this block: a blob holding
    ``x1`` or ``C001`` raises :class:`NotDisplayForm` and stays unparsed.
    """
    token = _DISPLAY_FORM_ONLY.set(True)
    try:
        yield
    finally:
        _DISPLAY_FORM_ONLY.reset(token)


def to_display(value: str, display: str, field: str | None) -> str:
    """Return ``display``, the form CLICK writes for ``value``.

    Inside :func:`display_form_only` a ``value`` that differs from it raises
    :class:`NotDisplayForm` naming ``field``, the field ``value`` was read for.
    """
    if display != value and _DISPLAY_FORM_ONLY.get():
        raise NotDisplayForm(
            f"{value!r} is not CLICK's display form {display!r}", field=field, reason=Reason.FORM
        )
    return display


def normalize_fields(inst: object, *names: str) -> None:
    """Write each named text field of ``inst`` in display form with :func:`normalize_address`.

    Every value goes to :func:`normalize_address`, so a value that is not text raises
    ``TypeError``; a caller that lets a field be None or a ``ModbusAddress`` leaves it out.
    A refusal names ``Class.name``.
    """
    cls = type(inst).__name__
    for name in names:
        value = normalize_address(getattr(inst, name), f"{cls}.{name}")
        object.__setattr__(inst, name, value)  # a Modbus target is frozen


def normalize_items(inst: object, *names: str) -> None:
    """Write each item of each named list field of ``inst`` in display form.

    The field becomes the list of its items, each through :func:`normalize_address`, so a
    value that can't be iterated, or an item that is not text, raises ``TypeError``.  A
    refusal names ``Class.name[i]``.
    """
    cls = type(inst).__name__
    for name in names:
        items = getattr(inst, name)
        value = [normalize_address(v, f"{cls}.{name}[{i}]") for i, v in enumerate(items)]
        object.__setattr__(inst, name, value)


def normalize_address(value: str, field: str | None = None) -> str:
    """Return an address in CLICK's display form; return other text unchanged.

    CLICK normalizes an address as it is typed: the bank is uppercase, X and Y pad the
    number to 3 digits and every other bank drops leading zeros, so ``x1`` becomes
    ``X001``, ``C001`` becomes ``C1`` and ``xd0U`` becomes ``XD0u``.  A pointer
    normalizes both parts (``ds[ds01]`` becomes ``DS[DS1]``).  Text that is not an
    address in one of :data:`ADDRESS_BANKS` (a constant, a blank, an unknown bank) comes
    back as given; range and allowed banks are :func:`check_address`'s job.  Inside
    :func:`display_form_only` an address not in display form raises :class:`FieldError`
    naming ``field``.
    """
    pointer = _LOOSE_POINTER_RE.fullmatch(value)
    if pointer is not None:
        bank = pointer.group(1).upper()
        if bank in ADDRESS_BANKS:
            index = normalize_address(pointer.group(2), field)
            return to_display(value, f"{bank}[{index}]", field)
        return value
    match = _LOOSE_ADDRESS_RE.fullmatch(value)
    if match is None:
        return value
    bank = match.group(1).upper()
    if bank not in ADDRESS_BANKS:
        return value
    address = Address(bank, int(match.group(2)), match.group(3) != "")
    return to_display(value, address.display, field)


def _bank_range_text(bank: str) -> str:
    if bank in _MODULE_BANKS:
        return (
            f"{bank}001-{bank}016, {bank}021-{bank}036, {bank}101-{bank}116 ... {bank}801-{bank}816"
        )
    if bank in _WORD_IO_BANKS:
        return f"{bank}0, {bank}0u, {bank}1-{bank}8"
    lo, hi = ADDRESS_BANKS[bank]
    return f"{bank}{lo}-{bank}{hi}"


def _in_range(bank: str, digits: str, upper: bool) -> bool:
    if upper:
        return bank in _WORD_IO_BANKS and digits == "0"
    number = int(digits)
    lo, hi = ADDRESS_BANKS[bank]
    if not lo <= number <= hi:
        return False
    if bank in _MODULE_BANKS:
        return xy_slot(number) is not None
    return True


def xy_slot(number: int) -> int | None:
    """Return the index in :data:`XY_SLOTS` of the slot holding X/Y point ``number``, or None."""
    for index, (first, last) in enumerate(XY_SLOTS):
        if first <= number <= last:
            return index
    return None


def check_address(
    value: str,
    field: str,
    banks: Collection[str] | None = None,
    *,
    label: str | None = None,
    bank_id: str | None = None,
    bank_ids: Mapping[str, str] | None = None,
    range_ids: Mapping[str, str] | None = None,
    outside_range_of: str | None = None,
) -> Address:
    """Parse a CLICK address; raise :class:`AddressError` naming ``field`` if refused.

    The bank must be one of :data:`ADDRESS_BANKS` (and in ``banks`` when given), and the
    number inside the bank's range.  X and Y number by 16-point slot (:data:`XY_SLOTS`):
    ``X001``-``X016`` on the CPU, ``X021``-``X036`` on its dual option slot, and
    ``X101``-``X116`` to ``X801``-``X816`` on expansion modules 1-8.  Leading zeros are
    allowed (``X001`` and ``X1`` are the same point); the bank must be uppercase.  An
    instruction passes each field through :func:`normalize_address` first and keeps the
    display form.
    ``XD0u`` and ``YD0u`` are accepted, spelled exactly so, only when ``banks`` names XD or
    YD.  The message names ``label``, or the field when no label is given.  ``bank_id`` is
    the error id CLICK's dialog gives for a bank the field does not take (``"OBJ-004"``),
    where it is known; it becomes the refusal's ``click_id``.  ``bank_ids`` gives another id
    for particular banks (``{"SD": "OBJ-003"}``), and ``range_ids`` one for a number outside
    its bank's range, by bank.  A refusal with one of those ids says it is outside the range
    of ``outside_range_of`` (the field's noun, else its name), and what the field takes.
    """
    name = label or field
    if value == "":
        raise AddressError(
            f"{name}: is blank; it needs an address", field=field, reason=Reason.MISSING
        )
    match = _ADDRESS_RE.fullmatch(value)
    if match is None:
        raise AddressError(
            f"{name}: {value!r} is not a CLICK address", field=field, reason=Reason.ADDRESS
        )
    bank, digits, upper = match.group(1), match.group(2), match.group(3) == "u"
    if bank not in ADDRESS_BANKS:
        raise AddressError(
            f"{name}: {value!r} has no CLICK bank {bank!r}; banks are {', '.join(ADDRESS_BANKS)}",
            field=field,
            reason=Reason.ADDRESS,
        )
    if banks is not None and bank not in banks:
        allowed = [b for b in ADDRESS_BANKS if b in banks]
        specific = (bank_ids or {}).get(bank)
        if specific is not None:
            names = (
                ", ".join(allowed[:-1]) + " and " + allowed[-1] if len(allowed) > 1 else allowed[0]
            )
            raise AddressError(
                f"{name}: {value!r} is outside the range of {outside_range_of or name} "
                f"({specific}); it takes {names}",
                field=field,
                reason=Reason.BANK,
                click_id=specific,
            )
        tail = f" ({bank_id})" if bank_id else ""
        raise AddressError(
            f"{name}: {value!r} is not allowed; {name} takes {', '.join(allowed)}{tail}",
            field=field,
            reason=Reason.BANK,
            click_id=bank_id,
        )
    if not _in_range(bank, digits, upper):
        # No such address: the number is outside its bank.
        in_range = (range_ids or {}).get(bank)
        if in_range is not None:
            takes = ", ".join(_bank_range_text(b) for b in ADDRESS_BANKS if b in (banks or {bank}))
            raise AddressError(
                f"{name}: {value!r} is outside the range of {outside_range_of or name} "
                f"({in_range}); it takes {takes}",
                field=field,
                reason=Reason.ADDRESS,
                click_id=in_range,
            )
        raise AddressError(
            f"{name}: {value!r} is outside {_bank_range_text(bank)}",
            field=field,
            reason=Reason.ADDRESS,
        )
    if upper and banks is None:
        raise AddressError(
            f"{name}: {value!r} is not allowed; {name} does not take {bank}0u",
            field=field,
            reason=Reason.FORM,
        )
    return Address(bank, int(digits), upper)


# ---------------------------------------------------------------------------
# Typed text in refusals
# ---------------------------------------------------------------------------


def _text_fields(inst: object) -> dict[str, Any]:
    """The instance's text fields and lists of text, by name."""
    return {
        name: list(value) if isinstance(value, (list, tuple)) else value
        for name, value in vars(inst).items()
        if isinstance(value, str)
        or (isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value))
    }


def _typed_text(message: str, before: dict[str, Any], after: dict[str, Any]) -> str:
    """Name the typed text beside each display form ``message`` quotes: ``'x0' (X000)``.

    A display form two fields reached from different text (``C1`` and ``C001``) is left
    as it is, since the message does not say which field it quotes.
    """
    typed: dict[str, set[str]] = {}
    for name, old in before.items():
        new = after.get(name)
        olds, news = (old, new) if isinstance(old, list) else ([old], [new])
        if not isinstance(news, list) or len(olds) != len(news):
            continue
        for o, n in zip(olds, news, strict=True):
            if isinstance(n, str) and normalize_address(o) == n:
                typed.setdefault(n, set()).add(o)
    for display, texts in typed.items():
        if len(texts) == 1 and (text := next(iter(texts))) != display:
            message = message.replace(repr(display), f"{text!r} ({display})")
    return message


def _name_typed_text(cls: Any) -> None:
    """Wrap ``cls.__post_init__`` so a field error names the text as typed.

    ``__post_init__`` writes each address in display form before checking it; a refusal
    quotes that form, and this adds the text the caller gave: ``'x0' (X000) is outside``.
    Each refusal's ``obj`` is the instance being built.
    """
    post_init = cls.__dict__.get("__post_init__")
    if post_init is None:
        return

    @functools.wraps(post_init)
    def wrapper(self: object) -> None:
        before = None if _DISPLAY_FORM_ONLY.get() else _text_fields(self)
        try:
            post_init(self)
        except FieldError as exc:
            _refused(self, exc, before)
            raise

    cls.__post_init__ = wrapper


def _refused(inst: object, exc: FieldError, before: dict[str, Any] | None) -> None:
    """Complete each refusal of ``inst`` in ``exc.errors``: its ``obj`` is ``inst``, and
    given ``before`` (the text fields as typed) its message names the typed text.  A refusal
    of an instruction built inside ``inst``'s checks was completed by its own wrapper."""
    after = None if before is None else _text_fields(inst)
    for error in exc.errors:
        if error.obj is not None and error.obj is not inst:
            continue
        error.obj = inst
        if before is not None and after is not None:
            error.args = (_typed_text(str(error), before, after),)
