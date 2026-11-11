"""Shared domain types for ladder instructions.

Defines ``InstructionType`` enum, the field errors, the CLICK address check
(:func:`check_address`), its display form (:func:`normalize_address`) and the
``OPERAND_RE`` shape pattern.  These are the foundation types imported by every
``instructions/`` module — no reverse dependency.

Instruction dataclasses (Contact, Coil, …) and their func-code
tables live in :mod:`laddercodec.instructions`.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from enum import IntEnum
from typing import TYPE_CHECKING, Any, NamedTuple, cast

if TYPE_CHECKING:
    from .decode import Rung

# ---------------------------------------------------------------------------
# Instruction base classes — used for isinstance dispatch
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


def _name_typed_text(cls: type) -> None:
    """Wrap ``cls.__post_init__`` so a field error names the text as typed.

    ``__post_init__`` writes each address in display form before checking it; a refusal
    quotes that form, and this adds the text the caller gave: ``'x0' (X000) is outside``.
    """
    post_init = cls.__dict__.get("__post_init__")
    if post_init is None:
        return

    @functools.wraps(post_init)
    def wrapper(self: object) -> None:
        if _DISPLAY_FORM_ONLY.get():
            post_init(self)
            return
        before = _text_fields(self)
        try:
            post_init(self)
        except FieldError as exc:
            exc.args = (_typed_text(str(exc), before, _text_fields(self)),)
            raise

    setattr(cls, "__post_init__", wrapper)


class ConditionInstruction:
    """Base class for condition-side instructions (Contact, CompareContact)."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _name_typed_text(cls)

    def to_csv(self) -> str:
        raise NotImplementedError

    def build_blob(self) -> bytes:
        raise NotImplementedError

    def cell_params(self) -> dict:
        raise NotImplementedError


class AfInstruction:
    """Base class for AF-side instructions (Coil, Timer, Counter, Copy, Fill, RawInstruction)."""

    # Keep this a plain class attribute. As a dataclass field in a subclass it would
    # take part in equality and change how decoded instructions compare.
    #: ``(instruction, token, detail)`` findings a decoder recorded for a legacy encoding;
    #: see :mod:`laddercodec.legacy`.
    _legacy_findings: Collection[tuple[str, str, str]] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _name_typed_text(cls)

    def to_csv(self) -> str:
        raise NotImplementedError

    def build_blob(self) -> bytes:
        raise NotImplementedError

    def cell_params(self) -> dict:
        raise NotImplementedError


class PinnedInstruction(AfInstruction):
    """An AF box with inputs ("slots") on several rows.

    Slots run top to bottom: ``lead_rows`` slots above the main input
    (count_down's unused Up), the main input (the CSV row holding the
    instruction token), then one slot per name in ``pin_names()``.
    ``pin_rows`` holds the row of every slot after the first; it is the
    blob's part bytes, and the box ends at its last row.

    OR legs under a slot push every later slot down; legs under the last
    slot sit below the box.  An unused pin keeps a row of its own.  When
    ``lead_rows`` is nonzero, the decoded main row's AF cell holds a NOP.
    """

    pin_rows: tuple[int, ...]

    @property
    def lead_rows(self) -> int:
        """Slots above the main input."""
        return 0

    def pin_names(self) -> tuple[str, ...]:
        """CSV pin tokens below the main input, in box order (e.g. ``.reset``)."""
        raise NotImplementedError

    def pin_labels(self) -> tuple[str | None, ...]:
        """CSV text of each pin row, ``None`` for an unused pin."""
        raise NotImplementedError

    def with_pins(
        self, pins: dict[str, tuple[str, ...]], pin_rows: tuple[int, ...]
    ) -> PinnedInstruction:
        """Copy with the flags the used pins (name -> args) imply, at ``pin_rows``."""
        raise NotImplementedError

    def with_pin_rows(self, pin_rows: tuple[int, ...]) -> PinnedInstruction:
        """Copy at ``pin_rows`` (subclasses are dataclasses)."""
        return replace(cast(Any, self), pin_rows=pin_rows)


class InstructionType(IntEnum):
    """Instruction type IDs (low byte; high byte is always 0x27)."""

    CONTACT_NO = 0x11  # 0x2711
    CONTACT_NC = 0x12  # 0x2712
    CONTACT_EDGE = 0x13  # 0x2713 (rise/fall edge contacts)
    COMPARE = 0x14  # 0x2714 (comparison contacts: EQ/NE/GT/LT/GE/LE)
    COIL_OUT = 0x15  # 0x2715
    COIL_LATCH = 0x16  # 0x2716
    COIL_RESET = 0x17  # 0x2717
    TIMER = 0x18  # 0x2718 (on_delay / off_delay timers)
    COUNTER = 0x19  # 0x2719 (count_up / count_down counters)
    MATH = 0x1A  # 0x271A (math expression)
    DRUM = 0x1B  # 0x271B (event drum / time drum)
    SHIFT = 0x20  # 0x2720 (shift register)
    COPY = 0x21  # 0x2721 (single/block/fill/pack/unpack copy)
    SEARCH = 0x22  # 0x2722 (search table)
    CALL = 0x23  # 0x2723 (subroutine call)
    FOR_LOOP = 0x25  # 0x2725 (for loop)
    NEXT = 0x26  # 0x2726 (for loop terminator)
    RECEIVE = 0x28  # 0x2728 (modbus receive / read)
    SEND = 0x29  # 0x2729 (modbus send / write)


#: Shape of an address token, in any letter case; the CSV token parser uses it to tell a
#: contact from other condition tokens.  :func:`check_address` checks the bank and number.
OPERAND_RE = re.compile(r"^[A-Za-z]{1,3}\d{1,5}$")


# Mapping from SCR type-code marker to InstructionType.
TYPE_CODE_TO_ITYPE: dict[int, InstructionType] = {
    0x2711: InstructionType.CONTACT_NO,
    0x2712: InstructionType.CONTACT_NC,
    0x2713: InstructionType.CONTACT_EDGE,
    0x2714: InstructionType.COMPARE,
    0x2715: InstructionType.COIL_OUT,
    0x2716: InstructionType.COIL_LATCH,
    0x2717: InstructionType.COIL_RESET,
    0x2718: InstructionType.TIMER,
}


# ---------------------------------------------------------------------------
# Field errors and CLICK addresses
# ---------------------------------------------------------------------------


class FieldError(ValueError):
    """An instruction field holds a value CLICK's dialog refuses.

    The decoders' ``from_tags`` dispatchers catch it and leave the blob unparsed.
    """


class AddressError(FieldError):
    """A field holds an address outside CLICK's banks, ranges or allowed banks."""


#: Number range of every CLICK address bank (CLICK v4.00 Help topic CL195, "Memory
#: Addresses").  X and Y number by slot (see :data:`XY_SLOTS`).  XD and YD are
#: ``XD0`` (slot 0), ``XD0u`` (slot 1) and ``XD1``-``XD8`` (expansion 1-8).
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


@contextmanager
def display_form_only() -> Iterator[None]:
    """Refuse, rather than normalize, text that is not in CLICK's display form.

    The ``from_tags`` dispatchers build instructions inside this block: a blob holding
    ``x1`` or ``C001`` raises :class:`FieldError` and stays unparsed.
    """
    token = _DISPLAY_FORM_ONLY.set(True)
    try:
        yield
    finally:
        _DISPLAY_FORM_ONLY.reset(token)


def to_display(value: str, display: str) -> str:
    """Return ``display``, the form CLICK writes for ``value``.

    Inside :func:`display_form_only` a ``value`` that differs from it raises
    :class:`FieldError`.
    """
    if display != value and _DISPLAY_FORM_ONLY.get():
        raise FieldError(f"{value!r} is not CLICK's display form {display!r}")
    return display


def normalize_address(value: str) -> str:
    """Return an address in CLICK's display form; return other text unchanged.

    CLICK normalizes an address as it is typed: the bank is uppercase, X and Y pad the
    number to 3 digits and every other bank drops leading zeros, so ``x1`` becomes
    ``X001``, ``C001`` becomes ``C1`` and ``xd0U`` becomes ``XD0u``.  A pointer
    normalizes both parts (``ds[ds01]`` becomes ``DS[DS1]``).  Text that is not an
    address in one of :data:`ADDRESS_BANKS` (a constant, a blank, an unknown bank) comes
    back as given; range and allowed banks are :func:`check_address`'s job.  Inside
    :func:`display_form_only` an address not in display form raises :class:`FieldError`.
    """
    pointer = _LOOSE_POINTER_RE.fullmatch(value)
    if pointer is not None:
        bank = pointer.group(1).upper()
        if bank in ADDRESS_BANKS:
            return to_display(value, f"{bank}[{normalize_address(pointer.group(2))}]")
        return value
    match = _LOOSE_ADDRESS_RE.fullmatch(value)
    if match is None:
        return value
    bank = match.group(1).upper()
    if bank not in ADDRESS_BANKS:
        return value
    return to_display(value, Address(bank, int(match.group(2)), match.group(3) != "").display)


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


def check_address(value: str, name: str, banks: Collection[str] | None = None) -> Address:
    """Parse a CLICK address; raise :class:`AddressError` naming field ``name`` if refused.

    The bank must be one of :data:`ADDRESS_BANKS` (and in ``banks`` when given), and the
    number inside the bank's range.  X and Y number by 16-point slot (:data:`XY_SLOTS`):
    ``X001``-``X016`` on the CPU, ``X021``-``X036`` on its dual option slot, and
    ``X101``-``X116`` to ``X801``-``X816`` on expansion modules 1-8.  Leading zeros are
    allowed (``X001`` and ``X1`` are the same point); the bank must be uppercase.  An
    instruction passes each field through :func:`normalize_address` first and keeps the
    display form.
    ``XD0u`` and ``YD0u`` are accepted, spelled exactly so, only when ``banks`` names XD or
    YD.
    """
    match = _ADDRESS_RE.fullmatch(value)
    if match is None:
        raise AddressError(f"{name}: {value!r} is not a CLICK address")
    bank, digits, upper = match.group(1), match.group(2), match.group(3) == "u"
    if bank not in ADDRESS_BANKS:
        raise AddressError(
            f"{name}: {value!r} has no CLICK bank {bank!r}; banks are {', '.join(ADDRESS_BANKS)}"
        )
    if banks is not None and bank not in banks:
        allowed = ", ".join(b for b in ADDRESS_BANKS if b in banks)
        raise AddressError(f"{name}: {value!r} is not allowed; {name} takes {allowed}")
    if not _in_range(bank, digits, upper):
        raise AddressError(f"{name}: {value!r} is outside {_bank_range_text(bank)}")
    if upper and banks is None:
        raise AddressError(f"{name}: {value!r} is not allowed; {name} does not take {bank}0u")
    return Address(bank, int(digits), upper)


# ---------------------------------------------------------------------------
# Program / Project containers
# ---------------------------------------------------------------------------


#: Longest subroutine or interrupt name: CLICK.exe's Add Subroutine edit takes 24
#: characters (EM_LIMITTEXT 0x18; Q-F2).
PROGRAM_NAME_MAX = 24

#: Characters a program name may not hold (CLICK.exe, GUI-040 "Invalid Program Name").
_PROGRAM_NAME_FORBIDDEN = '\\/:*?"<>|'

#: Windows device names a program name may not use before its last dot (CLICK.exe
#: device table, GUI-040), compared case-insensitively.
_DEVICE_NAMES = frozenset(
    {"AUX", "CON", "NUL", "PRN", "CLOCK$"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)


def check_program_name(name: str, field_name: str) -> None:
    """Raise :class:`FieldError` naming ``field_name`` if CLICK refuses ``name`` for a subroutine.

    Follows CLICK's Add New Subroutine dialog (Q-F2), which trims the name first and
    then checks it: not blank (user dialog check 2026-11-11), at most
    :data:`PROGRAM_NAME_MAX` characters, none of ``\\ / : * ? " < > |``, and the part
    before the last dot is not a Windows device name (GUI-040).  ``Main``, ``.``,
    inner spaces, ``-`` and a leading digit are accepted.
    """
    text = name.strip()
    if not text:
        raise FieldError(f"{field_name}: {name!r} is blank; a subroutine needs a name")
    if len(text) > PROGRAM_NAME_MAX:
        raise FieldError(
            f"{field_name}: {name!r} is {len(text)} characters; a subroutine name is at "
            f"most {PROGRAM_NAME_MAX}"
        )
    bad = sorted({ch for ch in text if ch in _PROGRAM_NAME_FORBIDDEN})
    if bad:
        raise FieldError(
            f"{field_name}: {name!r} holds {' '.join(bad)}; a subroutine name may not hold "
            f"any of {' '.join(_PROGRAM_NAME_FORBIDDEN)} (GUI-040)"
        )
    base = text.rsplit(".", 1)[0] if "." in text else text
    if base.upper() in _DEVICE_NAMES:
        raise FieldError(
            f"{field_name}: {name!r} uses the Windows device name {base!r}; CLICK refuses "
            "it as a subroutine name (GUI-040)"
        )


@dataclass
class Program:
    """A single PLC program (main or subroutine) with its rungs."""

    name: str
    prog_idx: int
    rungs: list[Rung] = field(default_factory=list)


@dataclass
class Project:
    """A complete PLC project: main program plus subroutines."""

    main: Program
    subroutines: list[Program] = field(default_factory=list)
