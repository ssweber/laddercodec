"""Shared domain types for ladder instructions.

Defines ``InstructionType`` enum, operand validation, and the
``OPERAND_RE`` pattern.  These are the foundation types imported
by every ``instructions/`` module — no reverse dependency.

Instruction dataclasses (Contact, Coil, …) and their func-code
tables live in :mod:`laddercodec.instructions`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import IntEnum
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from .decode import Rung

# ---------------------------------------------------------------------------
# Instruction base classes — used for isinstance dispatch
# ---------------------------------------------------------------------------


class ConditionInstruction:
    """Base class for condition-side instructions (Contact, CompareContact)."""

    def to_csv(self) -> str:
        raise NotImplementedError

    def build_blob(self) -> bytes:
        raise NotImplementedError

    def cell_params(self) -> dict:
        raise NotImplementedError


class AfInstruction:
    """Base class for AF-side instructions (Coil, Timer, Counter, Copy, Fill, RawInstruction)."""

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


OPERAND_RE = re.compile(r"^[A-Z]{1,3}\d{1,5}$")


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


def _validate_operand(operand: str) -> str:
    operand = operand.strip()
    if not OPERAND_RE.fullmatch(operand):
        raise ValueError(f"Invalid operand: {operand!r}")
    return operand


# ---------------------------------------------------------------------------
# Program / Project containers
# ---------------------------------------------------------------------------


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
