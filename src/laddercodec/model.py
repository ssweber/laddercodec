"""Shared domain types for ladder instructions.

Defines the ``InstructionType`` enum, the instruction base classes and the program
containers.  It re-exports the field errors (:mod:`laddercodec.operands.errors`), the
CLICK address check (:func:`check_address`), its display form
(:func:`normalize_address`) and the ``OPERAND_RE`` shape pattern
(:mod:`laddercodec.operands.address`).  These are the foundation types imported by
every ``instructions/`` module — no reverse dependency.

Instruction dataclasses (Contact, Coil, …) and their func-code
tables live in :mod:`laddercodec.instructions`.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field, replace
from enum import IntEnum
from functools import wraps
from typing import TYPE_CHECKING, Any, cast

from .operands.address import ADDRESS_BANKS as ADDRESS_BANKS
from .operands.address import OPERAND_RE as OPERAND_RE
from .operands.address import XY_SLOTS as XY_SLOTS
from .operands.address import Address as Address
from .operands.address import _name_typed_text
from .operands.address import check_address as check_address
from .operands.address import display_form_only as display_form_only
from .operands.address import normalize_address as normalize_address
from .operands.address import to_display as to_display
from .operands.address import xy_slot as xy_slot
from .operands.errors import AddressError as AddressError
from .operands.errors import FieldError as FieldError

if TYPE_CHECKING:
    from .decode import Rung

# ---------------------------------------------------------------------------
# Instruction base classes — used for isinstance dispatch
# ---------------------------------------------------------------------------


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

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        own = cls.__dict__.get("__post_init__")
        if own is None:
            return

        @wraps(own)
        def checked(self: PinnedInstruction) -> None:
            own(self)
            self._check_pin_rows()

        cls.__post_init__ = checked  # type: ignore[attr-defined]

    def _check_pin_rows(self) -> None:
        """Raise :class:`FieldError` unless ``pin_rows`` is one ascending row per pin.

        A box has ``lead_rows`` slots above its main input and one slot per pin name
        below it; the blob stores each as one byte, so a row is 1 to 255.
        """
        name = f"{type(self).__name__}.pin_rows"
        rows = self.pin_rows
        want = self.lead_rows + len(self.pin_names())
        if not isinstance(rows, tuple) or len(rows) != want:
            raise FieldError(f"{name}: {rows!r} must be a tuple of {want} rows, one per input")
        if not all(type(row) is int and 1 <= row <= 255 for row in rows):
            raise FieldError(f"{name}: {rows!r} holds a row outside the whole numbers 1 to 255")
        if any(later <= earlier for earlier, later in zip(rows, rows[1:], strict=False)):
            raise FieldError(f"{name}: {rows!r} must ascend; each input sits below the last")

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
