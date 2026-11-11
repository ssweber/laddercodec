"""CLICK address banks as bit flags, in CLICK's type order.

Bit ``n`` is CLICK's bank type ``n``: X is bit 0, TXT bit 15.  A dialog's bank mask
names the banks a field takes in this order: ``0x3f`` is X, Y, C, T, CT and SC.  The
order is also the key order of :data:`~laddercodec.operands.address.ADDRESS_BANKS`.

Not public API.
"""

from __future__ import annotations

from enum import IntFlag


class Bank(IntFlag):
    """One bit per CLICK bank, bit 0 = X."""

    X = 1 << 0
    Y = 1 << 1
    C = 1 << 2
    T = 1 << 3
    CT = 1 << 4
    SC = 1 << 5
    DS = 1 << 6
    DD = 1 << 7
    DH = 1 << 8
    DF = 1 << 9
    XD = 1 << 10
    YD = 1 << 11
    TD = 1 << 12
    CTD = 1 << 13
    SD = 1 << 14
    TXT = 1 << 15


#: Every bank.
ALL = Bank(0xFFFF)
#: The bit banks: X, Y, C, T, CT, SC.
BITS = Bank.X | Bank.Y | Bank.C | Bank.T | Bank.CT | Bank.SC
#: The register banks: every bank but the bit banks.
REGISTERS = ALL & ~BITS


def banks(value: int) -> frozenset[str]:
    """The names of the banks set in ``value``: ``banks(0x3f)`` is X, Y, C, T, CT and SC."""
    if value & ~int(ALL):
        raise ValueError(f"bank mask {value:#x} sets a bit above TXT")
    return frozenset(name for name, bank in Bank.__members__.items() if value & bank)


def mask(*names: str) -> Bank:
    """The flags of the banks ``names``: ``mask("DS", "DD")`` is ``0xc0``."""
    result = Bank(0)
    for name in names:
        result |= Bank[name]
    return result
