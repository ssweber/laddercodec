"""Bit flags for CLICK's address banks, in the order of CLICK's bank type numbers.

Bit ``n`` stands for CLICK's bank type ``n``. X is bit 0 and TXT is bit 15. A CLICK
dialog stores the banks that a field accepts as a mask of these bits. For example,
``0x3f`` is X, Y, C, T, CT and SC. :data:`~laddercodec.operands.address.ADDRESS_BANKS`
lists its keys in the same order.

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
    """Return the names of the banks whose bits are set in ``value``.

    For example, ``banks(0x3f)`` returns X, Y, C, T, CT and SC. Raise ``ValueError`` if
    ``value`` sets a bit above TXT.
    """
    if value & ~int(ALL):
        raise ValueError(f"bank mask {value:#x} sets a bit above TXT")
    return frozenset(name for name, bank in Bank.__members__.items() if value & bank)


def mask(*names: str) -> Bank:
    """Return the flags of the banks named in ``names``: ``mask("DS", "DD")`` is ``0xc0``."""
    result = Bank(0)
    for name in names:
        result |= Bank[name]
    return result
