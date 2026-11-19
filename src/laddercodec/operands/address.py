"""CLICK addresses: the banks, the address check and the display form.

:func:`check_address` parses and checks an address, :func:`normalize_address` writes it
in the form CLICK shows, and ``OPERAND_RE`` is the shape the CSV token parser uses to
tell a contact from other condition tokens.

:func:`parse_address`, :func:`split_pointer`, :func:`is_pointer`, :func:`bank_prefix` and
:func:`address_shape` read address text and never raise. :func:`xy_points` and
:func:`xy_room` count X/Y points by slot.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Collection, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, NamedTuple

from ..codes import Code
from .banks import WORD_IO_BANKS, XY_BANKS
from .errors import AddressError, FieldError, Reason
from .message import LABEL, Op, make_refusal, parts_of, says, set_parts

#: The pattern of an address token, in any letter case.  The CSV token parser uses it to tell
#: a contact from other condition tokens.  :func:`check_address` checks the bank and number.
OPERAND_RE = re.compile(r"^[A-Za-z]{1,3}[0-9]{1,5}$")


#: The number range of every CLICK address bank.  In the X and Y ranges, only the numbers
#: inside a slot of :data:`XY_SLOTS` are addresses.  XD and YD are ``XD0`` (slot 0),
#: ``XD0u`` (slot 1) and ``XD1``-``XD8`` (expansion modules 1-8).
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

#: The ten 16-point X/Y slots, each as its ``(first, last)`` point numbers.  Points 1-16 are
#: on the CPU.  Points 21-36 are on the CPU's dual option slot, whose word form is
#: ``XD0u``/``YD0u``.  Points 101-116 to 801-816 are on expansion modules 1-8.
XY_SLOTS: tuple[tuple[int, int], ...] = ((1, 16), (21, 36)) + tuple(
    (100 * m + 1, 100 * m + 16) for m in range(1, 9)
)

_ADDRESS_RE = re.compile(r"([A-Z]{1,3})([0-9]{1,5})(u?)")


class Address(NamedTuple):
    """A parsed CLICK address: ``XD0u`` is ``Address("XD", 0, upper=True)``."""

    bank: str
    number: int
    upper: bool = False

    @property
    def display(self) -> str:
        """The address as CLICK shows and stores it: ``X001``, ``C1``, ``XD0u``.

        X and Y pad the number to 3 digits.  Every other bank writes it with no padding.
        """
        number = f"{self.number:03d}" if self.bank in XY_BANKS else str(self.number)
        return f"{self.bank}{number}{'u' if self.upper else ''}"


#: Address text in any letter case, with or without leading zeros (``x1``, ``ds07``,
#: ``XD0U``).  The second pattern matches a pointer, ``BANK[address]``.
_LOOSE_ADDRESS_RE = re.compile(r"([A-Za-z]{1,3})([0-9]{1,5})([uU]?)")
_LOOSE_POINTER_RE = re.compile(r"([A-Za-z]{1,3})\[([^\[\]]*)\]")


#: True while a decoder builds an instruction from a blob.  Text that is not in display form
#: is then refused, and the blob stays raw.  Otherwise the instruction would encode back to
#: different bytes.
_DISPLAY_FORM_ONLY: ContextVar[bool] = ContextVar("_DISPLAY_FORM_ONLY", default=False)


class NotDisplayForm(FieldError):
    """Raised inside :func:`display_form_only` for text that is not in CLICK's display form."""


@contextmanager
def display_form_only() -> Generator[None]:
    """Refuse, rather than normalize, text that is not in CLICK's display form.

    The ``from_tags`` dispatchers build instructions inside this block.  A blob that holds
    ``x1`` or ``C001`` then raises :class:`NotDisplayForm`, and the blob stays unparsed.
    """
    token = _DISPLAY_FORM_ONLY.set(True)
    try:
        yield
    finally:
        _DISPLAY_FORM_ONLY.reset(token)


def to_display(value: str, display: str, field: str | None) -> str:
    """Return ``display``, the form CLICK writes for ``value``.

    Inside :func:`display_form_only`, raise :class:`NotDisplayForm` if ``value`` differs
    from ``display``.  Its message starts with ``field``, the field that ``value`` was read
    for, as the message of every refusal does.
    """
    if display != value and _DISPLAY_FORM_ONLY.get():
        # The display form is CLICK's, not the caller's, so it is plain text.
        raise make_refusal(
            NotDisplayForm,
            field or None,
            says(
                "{value} is not CLICK's display form {display!r}", value=Op(value), display=display
            ),
            field=field,
            reason=Reason.FORM,
            code=Code.NOT_CLICK_FORM,
        )
    return display


def read_as_typed(value: str) -> str:
    """Return the display form of address text that CLICK saved as typed.

    Return other text unchanged.  CLICK saves some fields as they were typed, not in
    display form.  The decoders name those fields.  Such a field keeps its letter case
    (``ds1``, ``xd0U``), its leading zeros (``DS001``, ``YD00``) and a pointer's index
    (``DS[ds1]``).  This function reads them as ``DS1``, ``XD0u``, ``YD0`` and ``DS[DS1]``.

    Text that is shorter than its display form, such as ``Y1`` for ``Y001``, comes back
    unchanged.  No recorded save holds such text, so :func:`display_form_only` still
    refuses it.  Unlike :func:`normalize_address`, this function never refuses.
    """
    token = _DISPLAY_FORM_ONLY.set(False)
    try:
        display = normalize_address(value)
    finally:
        _DISPLAY_FORM_ONLY.reset(token)
    return value if len(display) > len(value) else display


def read_typed_address(value: str, *, trim: bool = False) -> str:
    """Return the address that CLICK saved as typed in ``value``, in display form.

    Return ``value`` unchanged if it does not read as an address, such as a constant.  With
    ``trim``, spaces at the start and end are removed first, for a field that CLICK saves
    with them (``" DS1"``).  :func:`read_as_typed` reads the rest.
    """
    display = read_as_typed(value.strip(" ") if trim else value)
    return display if parse_address(display) is not None else value


def normalize_fields(inst: object, *names: str) -> None:
    """Write each named text field of ``inst`` in display form with :func:`normalize_address`.

    Every value goes to :func:`normalize_address`, so a value that is not text raises
    ``TypeError``.  If a field may be None or a ``ModbusAddress``, the caller does not
    pass its name.  A refusal names the field as ``Class.name``.
    """
    cls = type(inst).__name__
    for name in names:
        value = normalize_address(getattr(inst, name), f"{cls}.{name}")
        object.__setattr__(inst, name, value)  # Works on a frozen Modbus target too.


def normalize_items(inst: object, *names: str) -> None:
    """Write each item of each named list field of ``inst`` in display form.

    The field becomes the tuple of its items, each through :func:`normalize_address`, so a
    value that can't be iterated, or an item that is not text, raises ``TypeError``.  A
    refusal names ``Class.name[i]``.
    """
    cls = type(inst).__name__
    for name in names:
        items = getattr(inst, name)
        value = tuple(normalize_address(v, f"{cls}.{name}[{i}]") for i, v in enumerate(items))
        object.__setattr__(inst, name, value)


def normalize_address(value: str, field: str | None = None) -> str:
    """Return an address in CLICK's display form, and return other text unchanged.

    CLICK normalizes an address as you type it.  The bank becomes uppercase.  X and Y pad
    the number to 3 digits, and every other bank drops leading zeros.  For example, ``x1``
    becomes ``X001``, ``C001`` becomes ``C1`` and ``xd0U`` becomes ``XD0u``.  Both parts
    of a pointer are normalized: ``ds[ds01]`` becomes ``DS[DS1]``.

    Text that is not an address in one of :data:`ADDRESS_BANKS`, such as a constant, a
    blank or an unknown bank, comes back as given.  This function does not check the
    number's range or whether the field takes the bank.  :func:`check_address` does that.
    Inside :func:`display_form_only`, an address that is not in display form raises
    :class:`FieldError` naming ``field``.
    """
    pointer = _loose_pointer(value)
    if pointer is not None:
        bank, index = pointer
        return to_display(value, f"{bank}[{normalize_address(index, field)}]", field)
    display = _loose_display(value)
    return value if display is None else to_display(value, display, field)


#: How many texts each address cache below holds. A program names a few thousand addresses.
_CACHE_SIZE = 8192


@functools.lru_cache(maxsize=_CACHE_SIZE)
def _loose_pointer(value: str) -> tuple[str, str] | None:
    """Return the bank in uppercase and the index as typed of a pointer in any letter case.

    Return None if ``value`` is not a pointer into a bank of :data:`ADDRESS_BANKS`.
    """
    match = _LOOSE_POINTER_RE.fullmatch(value)
    if match is None or match.group(1).upper() not in ADDRESS_BANKS:
        return None
    return match.group(1).upper(), match.group(2)


@functools.lru_cache(maxsize=_CACHE_SIZE)
def _loose_display(value: str) -> str | None:
    """Return the display form of an address typed in any letter case, or None.

    None means that ``value`` is not an address in a bank of :data:`ADDRESS_BANKS`.
    """
    match = _LOOSE_ADDRESS_RE.fullmatch(value)
    if match is None or match.group(1).upper() not in ADDRESS_BANKS:
        return None
    return Address(match.group(1).upper(), int(match.group(2)), match.group(3) != "").display


@functools.lru_cache(maxsize=_CACHE_SIZE)
def _address_parts(value: str) -> tuple[str, str, bool] | None:
    """Return the bank, the digits and the ``u`` of an address in CLICK's uppercase form.

    Return None for other text. The bank need not be one of :data:`ADDRESS_BANKS`, and the
    number need not be in its range.
    """
    match = _ADDRESS_RE.fullmatch(value)
    if match is None:
        return None
    return match.group(1), match.group(2), match.group(3) == "u"


def _bank_range_text(bank: str) -> str:
    if bank in XY_BANKS:
        return (
            f"{bank}001-{bank}016, {bank}021-{bank}036, {bank}101-{bank}116 ... {bank}801-{bank}816"
        )
    if bank in WORD_IO_BANKS:
        return f"{bank}0, {bank}0u, {bank}1-{bank}8"
    lo, hi = ADDRESS_BANKS[bank]
    return f"{bank}{lo}-{bank}{hi}"


def _in_range(bank: str, digits: str, upper: bool) -> bool:
    if upper:
        return bank in WORD_IO_BANKS and digits == "0"
    number = int(digits)
    lo, hi = ADDRESS_BANKS[bank]
    if not lo <= number <= hi:
        return False
    if bank in XY_BANKS:
        return xy_slot(number) is not None
    return True


def xy_slot(number: int) -> int | None:
    """Return the index in :data:`XY_SLOTS` of the slot holding X/Y point ``number``, or None."""
    for index, (first, last) in enumerate(XY_SLOTS):
        if first <= number <= last:
            return index
    return None


def xy_points(first: int, last: int) -> int:
    """Return how many X/Y points of :data:`XY_SLOTS` lie in ``first..last``."""
    return sum(max(0, min(last, hi) - max(first, lo) + 1) for lo, hi in XY_SLOTS)


def xy_room(number: int) -> int:
    """Return how many X/Y points a count from point ``number`` can cover in its slot run.

    A slot run is the set of slots that one count may cross. The CPU slot and its dual
    option slot form one run, so a count from X001 can cover 32 points. A count from an
    expansion slot must stay in that slot, so a count from X101 can cover 16.
    """
    if number <= 16:
        return 33 - number
    if number <= 36:
        return 37 - number
    return 17 - number % 100


# ---------------------------------------------------------------------------
# Reading address text without a refusal
# ---------------------------------------------------------------------------

#: A pointer, ``BANK[index]``, with a bank of one to three uppercase letters.
_POINTER_RE = re.compile(r"([A-Z]{1,3})\[(.*)\]")
#: Uppercase letters followed by digits, such as ``DS001`` or ``ZZ1``.
_SHAPE_RE = re.compile(r"([A-Z]+)([0-9]+)")
_LETTERS_RE = re.compile(r"[A-Z]*")


def parse_address(text: str) -> Address | None:
    """Return the address that ``text`` spells, or None if it is not a CLICK address.

    The function reads ``text`` as :func:`check_address` does. The bank is uppercase and
    one of :data:`ADDRESS_BANKS`, and the number is inside the bank's range. ``XD0u`` and
    ``YD0u`` are addresses here. :func:`check_address` refuses them when it is given no
    banks.
    """
    parts = _address_parts(text)
    if parts is None:
        return None
    bank, digits, upper = parts
    if bank not in ADDRESS_BANKS or not _in_range(bank, digits, upper):
        return None
    return Address(bank, int(digits), upper)


def split_pointer(text: str) -> tuple[str, str] | None:
    """Return the bank and the index of the pointer ``BANK[index]``, or None for other text.

    The bank is one to three uppercase letters, and the letters need not name a bank. The
    index is any text between the brackets that holds no line break. For example,
    ``split_pointer("DS[ds1]")`` returns ``("DS", "ds1")``.
    """
    match = _POINTER_RE.fullmatch(text)
    return None if match is None else (match.group(1), match.group(2))


def is_pointer(text: str) -> bool:
    """Return whether ``text`` is a pointer: a bank of :data:`ADDRESS_BANKS`, then a DS
    address in brackets, such as ``DD[DS1]``.

    The bank may be one that no pointer can address, such as X in ``X[DS1]``.
    """
    parts = split_pointer(text)
    if parts is None or parts[0] not in ADDRESS_BANKS:
        return False
    index = parse_address(parts[1])
    return index is not None and index.bank == "DS"


def bank_prefix(text: str) -> str:
    """Return the uppercase ASCII letters at the start of ``text``.

    ``bank_prefix("CTD5")`` returns ``"CTD"``, and ``bank_prefix("X[DS1]")`` returns ``"X"``.
    The letters need not name a bank, and the rest of ``text`` is not read. If ``text``
    starts with any other character, the function returns an empty string.
    """
    match = _LETTERS_RE.match(text)
    return match.group(0) if match else ""


def address_shape(text: str) -> tuple[str, str] | None:
    """Return the letters and the digits of ``text`` if it is uppercase ASCII letters
    followed by ASCII digits. Return None for any other text.

    ``address_shape("DS001")`` returns ``("DS", "001")``. The letters need not name a bank,
    and the number may be any length.
    """
    match = _SHAPE_RE.fullmatch(text)
    return None if match is None else (match.group(1), match.group(2))


def check_address(
    value: str,
    field: str,
    banks: Collection[str] | None = None,
    *,
    label: str | None = None,
    bank_id: str | None = None,
    bank_code: Code = Code.BANK_NOT_ALLOWED,
    bank_ids: Mapping[str, str] | None = None,
    range_ids: Mapping[str, str] | None = None,
    outside_range_of: str | None = None,
) -> Address:
    """Parse a CLICK address, or raise :class:`AddressError` naming ``field``.

    The bank must be one of :data:`ADDRESS_BANKS`, and in ``banks`` when that is given.
    The number must be inside the bank's range.  X and Y number by 16-point slot
    (:data:`XY_SLOTS`): ``X001``-``X016`` on the CPU, ``X021``-``X036`` on its dual option
    slot, and ``X101``-``X116`` to ``X801``-``X816`` on expansion modules 1-8.  Leading
    zeros are allowed, so ``X001`` and ``X1`` are the same point.  The bank must be
    uppercase.  An instruction passes each field through :func:`normalize_address` first
    and keeps the display form.  ``XD0u`` and ``YD0u`` are accepted, spelled exactly so,
    only when ``banks`` names XD or YD.

    The message names ``label``, or the field when no label is given.  ``bank_id`` is the
    error id that CLICK's dialog gives for a bank the field does not take, such as
    ``"OBJ-004"``, where it is known.  It becomes the refusal's ``click_id``.
    ``bank_code`` is the refusal's code.  It is ``bank-not-allowed`` unless the caller
    passes another.

    ``bank_ids`` gives a different id for particular banks, such as ``{"SD": "OBJ-003"}``.
    It applies only to an address inside its bank's range, so SD0 gets ``bank_id``.
    ``range_ids`` gives an id, by bank, for a number outside its bank's range.  A refusal
    with one of those ids says that the address is outside the range of
    ``outside_range_of``, the field's noun, or of the label or field when that is not
    given.  It also says what the field takes.
    """
    name = label or field
    if value == "":
        raise make_refusal(
            AddressError,
            name,
            says("is blank", "it needs an address"),
            field=field,
            reason=Reason.MISSING,
            code=Code.BLANK_FIELD,
        )
    parts = _address_parts(value)
    if parts is None:
        raise make_refusal(
            AddressError,
            name,
            says("{value} is not a CLICK address", value=Op(value)),
            field=field,
            reason=Reason.ADDRESS,
            code=Code.NOT_AN_ADDRESS,
        )
    bank, digits, upper = parts
    if bank not in ADDRESS_BANKS:
        raise make_refusal(
            AddressError,
            name,
            says(
                "{value} has no CLICK bank {bank!r}",
                "banks are {banks}",
                value=Op(value),
                bank=bank,
                banks=", ".join(ADDRESS_BANKS),
            ),  # fmt: skip
            field=field,
            reason=Reason.ADDRESS,
            code=Code.NOT_AN_ADDRESS,
        )
    if banks is not None and bank not in banks:
        allowed = [b for b in ADDRESS_BANKS if b in banks]
        specific = (bank_ids or {}).get(bank)
        if specific is not None and _in_range(bank, digits, upper):
            names = (
                ", ".join(allowed[:-1]) + " and " + allowed[-1] if len(allowed) > 1 else allowed[0]
            )
            raise make_refusal(
                AddressError,
                name,
                says(
                    "{value} is outside the range of {of}",
                    "it takes {banks}",
                    value=Op(value),
                    of=outside_range_of or LABEL,
                    banks=names,
                ),  # fmt: skip
                field=field,
                reason=Reason.BANK,
                code=bank_code,
                click_id=specific,
                id_after_short=True,
            )
        raise make_refusal(
            AddressError,
            name,
            says(
                "{value} is not allowed",
                "{label} takes {banks}",
                value=Op(value),
                banks=", ".join(allowed),
            ),  # fmt: skip
            field=field,
            reason=Reason.BANK,
            code=bank_code,
            click_id=bank_id,
        )
    if not _in_range(bank, digits, upper):
        # The number is outside its bank's range, so there is no such address.
        in_range = (range_ids or {}).get(bank)
        if in_range is not None:
            takes = ", ".join(_bank_range_text(b) for b in ADDRESS_BANKS if b in (banks or {bank}))
            raise make_refusal(
                AddressError,
                name,
                says(
                    "{value} is outside the range of {of}",
                    "it takes {banks}",
                    value=Op(value),
                    of=outside_range_of or LABEL,
                    banks=takes,
                ),  # fmt: skip
                field=field,
                reason=Reason.ADDRESS,
                code=Code.ADDRESS_OUT_OF_RANGE,
                click_id=in_range,
                id_after_short=True,
            )
        raise make_refusal(
            AddressError,
            name,
            says("{value} is outside {range}", value=Op(value), range=_bank_range_text(bank)),
            field=field,
            reason=Reason.ADDRESS,
            code=Code.ADDRESS_OUT_OF_RANGE,
        )
    if upper and banks is None:
        raise make_refusal(
            AddressError,
            name,
            says(
                "{value} is not allowed",
                "{label} does not take {bank}0u",
                value=Op(value),
                bank=bank,
            ),
            field=field,
            reason=Reason.FORM,
            code=Code.UPPER_BYTE_NOT_ALLOWED,
        )
    return Address(bank, int(digits), upper)


# ---------------------------------------------------------------------------
# Typed text in refusals
# ---------------------------------------------------------------------------


def _text_fields(inst: object) -> dict[str, Any]:
    """Return the instance's fields that hold text or a list of text, by name."""
    return {
        name: list(value) if isinstance(value, (list, tuple)) else value
        for name, value in vars(inst).items()
        if isinstance(value, str)
        or (isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value))
    }


def _typed_forms(before: dict[str, Any], after: dict[str, Any]) -> dict[str, str]:
    """Return the text that the caller typed for each display form, keyed by display form.

    ``before`` and ``after`` are the text fields before and after the instruction wrote them
    in display form.  If two fields reached the same display form from different text, such
    as ``C1`` and ``C001``, leave that form out, because a message does not say which field
    it quotes.
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
    return {display: next(iter(texts)) for display, texts in typed.items() if len(texts) == 1}


def _typed_text(message: str, single: dict[str, str]) -> str:
    """Return ``message`` with the typed text beside each display form that it quotes.

    ``single`` is what :func:`_typed_forms` returns.  For example, ``'X000'`` becomes
    ``'x0' (X000)``.  A quoted range of two display forms gets the typed text of both ends:
    ``'X001..X002'`` becomes ``'x1..x2' (X001..X002)``.  A refusal that keeps the parts of
    its message gets its typed text from
    :meth:`~laddercodec.operands.message.Parts.typed` instead.
    """
    for first, first_text in single.items():
        for last, last_text in single.items():
            shown = f"{first}..{last}"
            if (first_text, last_text) != (first, last) and repr(shown) in message:
                message = message.replace(
                    repr(shown), f"{f'{first_text}..{last_text}'!r} ({shown})"
                )
    for display, text in single.items():
        if text != display:
            message = message.replace(repr(display), f"{text!r} ({display})")
    return message


def _name_typed_text(cls: Any) -> None:
    """Wrap ``cls.__post_init__`` so a field error names the text as typed.

    ``__post_init__`` writes each address in display form before it checks it, so a
    refusal quotes the display form.  The wrapper adds the text that the caller gave, as
    in ``'x0' (X000) is outside``.  It also sets each refusal's ``obj`` to the instance
    being built.
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
    """Set ``obj`` to ``inst`` on each refusal in ``exc.errors``, and name the typed text.

    With ``before``, the text fields as typed, add the typed text to each message.  Skip a
    refusal whose ``obj`` is another instance.  It comes from an instruction built inside
    the checks of ``inst``, and that instruction's own wrapper has completed it."""
    single = None if before is None else _typed_forms(before, _text_fields(inst))
    for error in exc.errors:
        if error.obj is not None and error.obj is not inst:
            continue
        error.obj = inst
        if single is None:
            continue
        parts = parts_of(error)
        if parts is None:
            error.args = (_typed_text(str(error), single),)
            continue
        set_parts(error, parts.typed(single))
