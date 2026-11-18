"""Test the helpers that read address text and bank names without raising.

They live in ``laddercodec.operands.address``, ``laddercodec.operands.banks`` and
``laddercodec.operands.checks``.
"""

from __future__ import annotations

import pytest

from laddercodec.operands.address import (
    ADDRESS_BANKS,
    Address,
    address_shape,
    bank_prefix,
    is_pointer,
    parse_address,
    split_pointer,
    xy_points,
    xy_room,
)
from laddercodec.operands.banks import (
    BIT_BANKS,
    REGISTER_BANKS,
    WORD_IO_BANKS,
    XY_BANKS,
    bits_per_register,
)
from laddercodec.operands.checks import bank_of


def test_bank_sets() -> None:
    assert frozenset({"X", "Y", "C", "T", "CT", "SC"}) == BIT_BANKS
    assert BIT_BANKS | REGISTER_BANKS == set(ADDRESS_BANKS)
    assert not BIT_BANKS & REGISTER_BANKS
    assert frozenset({"X", "Y"}) == XY_BANKS
    assert frozenset({"XD", "YD"}) == WORD_IO_BANKS


@pytest.mark.parametrize(
    ("bank", "bits"),
    [
        ("DS", 16), ("DH", 16), ("TD", 16), ("SD", 16), ("XD", 16), ("YD", 16),
        ("DD", 32), ("DF", 32), ("CTD", 32),
        ("TXT", None), ("X", None), ("C", None), ("", None), ("ds", None), ("ZZ", None),
    ],
)  # fmt: skip
def test_bits_per_register(bank: str, bits: int | None) -> None:
    assert bits_per_register(bank) == bits


@pytest.mark.parametrize(
    ("text", "address"),
    [
        ("DS1", Address("DS", 1)),
        ("DS000001", None),  # more than five digits after the bank
        ("DS001", Address("DS", 1)),
        ("X001", Address("X", 1)),
        ("X1", Address("X", 1)),
        ("X017", None),  # between the CPU slot and the option slot
        ("XD0u", Address("XD", 0, upper=True)),
        ("YD0u", Address("YD", 0, upper=True)),
        ("XD1u", None),
        ("DS1u", None),
        ("XD0U", None),
        ("DS4500", Address("DS", 4500)),
        ("DS4501", None),
        ("DS0", None),
        ("ds1", None),
        ("ZZ1", None),
        ("DS[DS1]", None),
        ("", None),
        (" DS1", None),
    ],
)
def test_parse_address(text: str, address: Address | None) -> None:
    assert parse_address(text) == address


@pytest.mark.parametrize(
    ("text", "parts"),
    [
        ("DS[DS1]", ("DS", "DS1")),
        ("ZZ[x]", ("ZZ", "x")),
        ("DS[]", ("DS", "")),
        ("DS[DS1]]", ("DS", "DS1]")),
        ("DS[DS[1]]", ("DS", "DS[1]")),
        ("DS[\n]", None),  # the index holds no line break
        ("ds[DS1]", None),
        ("DSXX[DS1]", None),
        ("[DS1]", None),
        ("DS[DS1", None),
        ("DS1", None),
    ],
)
def test_split_pointer(text: str, parts: tuple[str, str] | None) -> None:
    assert split_pointer(text) == parts


@pytest.mark.parametrize(
    ("text", "pointer"),
    [
        ("DD[DS1]", True),
        ("X[DS1]", True),  # a bank that no pointer addresses is still read as a pointer
        ("DD[DS4501]", False),
        ("DD[DD1]", False),
        ("DD[ds1]", False),
        ("ZZ[DS1]", False),
        ("DD[DS1]]", False),
        ("DD1", False),
    ],
)
def test_is_pointer(text: str, pointer: bool) -> None:
    assert is_pointer(text) is pointer


@pytest.mark.parametrize(
    ("text", "prefix"),
    [("CTD5", "CTD"), ("X[DS1]", "X"), ("ZZZZ9", "ZZZZ"), ("ds1", ""), ("1", ""), ("", "")],
)
def test_bank_prefix(text: str, prefix: str) -> None:
    assert bank_prefix(text) == prefix


@pytest.mark.parametrize(
    ("text", "shape"),
    [
        ("DS001", ("DS", "001")),
        ("ZZ1", ("ZZ", "1")),
        ("DF123456", ("DF", "123456")),
        ("XD0u", None),
        ("ds1", None),
        ("DS", None),
        ("1", None),
        ("DS1\n", None),
        ("DS١", None),  # an Arabic-Indic digit is no ASCII digit
    ],
)
def test_address_shape(text: str, shape: tuple[str, str] | None) -> None:
    assert address_shape(text) == shape


@pytest.mark.parametrize(
    ("first", "last", "points"),
    [(1, 16, 16), (1, 21, 17), (1, 36, 32), (17, 20, 0), (1, 816, 160), (110, 210, 17)],
)
def test_xy_points(first: int, last: int, points: int) -> None:
    assert xy_points(first, last) == points


@pytest.mark.parametrize(
    ("number", "room"),
    [(1, 32), (16, 17), (21, 16), (36, 1), (101, 16), (116, 1), (801, 16), (816, 1)],
)
def test_xy_room(number: int, room: int) -> None:
    assert xy_room(number) == room


@pytest.mark.parametrize(
    ("text", "pointer", "bank"),
    [
        ("DS1", False, "DS"),
        ("X001", False, "X"),
        ("X017", False, None),
        ("XD0u", False, None),  # check_operand refuses XD0u when it is given no banks
        ("DD[DS1]", False, None),
        ("DD[DS1]", True, "DD"),
        ("X[DS1]", True, None),  # no pointer addresses X
        ("DD[DD1]", True, None),
        ("5", True, None),
        ("", True, None),
    ],
)
def test_bank_of(text: str, pointer: bool, bank: str | None) -> None:
    assert bank_of(text, "Copy.dest", pointer=pointer) == bank
