"""Shared domain types for ladder instructions.

Defines ``InstructionType`` enum, operand validation, and the
``OPERAND_RE`` pattern.  These are the foundation types imported
by every ``instructions/`` module — no reverse dependency.

Instruction dataclasses (Contact, Coil, …) and their func-code
tables live in :mod:`laddercodec.instructions`.
"""

from __future__ import annotations

import re
from enum import IntEnum


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


OPERAND_RE = re.compile(r"^[A-Z]{1,3}\d{1,5}$")


def _validate_operand(operand: str) -> str:
    operand = operand.strip()
    if not OPERAND_RE.fullmatch(operand):
        raise ValueError(f"Invalid operand: {operand!r}")
    return operand
