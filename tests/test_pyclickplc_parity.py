"""Tests that laddercodec's copy of CLICK's bank facts agrees with pyclickplc.

laddercodec has no runtime dependencies, so it keeps its own copy of the bank facts in
:mod:`laddercodec.operands.address` and :mod:`laddercodec.operands.banks`. Some
instructions keep sets of banks that follow from a bank's data type or register width.
pyclickplc is in the dev group. These tests fail when laddercodec and pyclickplc disagree on:

- the banks, in CLICK's type order, and each bank's number range;
- the X/Y slots, the X/Y points that a count can cover, the XD/YD word addresses and
  their order in a Math formula;
- which banks hold bits, which hold registers, how wide each register is, and which
  registers hold a 32-bit integer;
- the bank sets in Copy, Send and Receive that follow from a bank's data type or
  register width;
- the last DS address that a Send's Slave ID accepts;
- the bank ranges that a refusal message lists;
- the register bank that pairs with each of T and CT;
- which text names an address, and the display form of that address.

The two libraries read address text for different jobs. ``DIFFERENCES`` and
``PARSE_DIFFERENCES`` list each kind of text that they read differently by design, with
the reason.
"""

from __future__ import annotations

import importlib.metadata
import re
from collections.abc import Callable, Iterator
from typing import NamedTuple

import pytest
from packaging.version import Version

# pyclickplc has no __version__, so the skip reads the version from the package metadata.
# The imports below are plain, so a broken install fails the tests rather than skipping them.
try:
    _PYCLICKPLC_VERSION = importlib.metadata.version("pyclickplc")
except importlib.metadata.PackageNotFoundError:
    pytest.skip("the parity tests need pyclickplc", allow_module_level=True)
if Version(_PYCLICKPLC_VERSION) < Version("0.9.1"):
    pytest.skip("the parity tests need pyclickplc 0.9.1 or later", allow_module_level=True)

from pyclickplc import BANKS, DataType, plc_to_modbus
from pyclickplc import normalize_address as pc_normalize
from pyclickplc import parse_address as pc_parse
from pyclickplc.addresses import (
    format_address_display,
    is_xd_yd_hidden_slot,
    is_xd_yd_upper_byte,
    iter_address_slots,
    parse_addr_key,
    xd_yd_display_to_mdb,
    xd_yd_mdb_to_display,
)
from pyclickplc.banks import BIT_ONLY_TYPES

from laddercodec import Counter, FieldError, ModbusRtuTarget, Timer
from laddercodec.instructions import copy, math_formula, send_receive
from laddercodec.operands import address as address_module
from laddercodec.operands.address import (
    ADDRESS_BANKS,
    XY_SLOTS,
    Address,
    normalize_address,
    parse_address,
    xy_points,
    xy_room,
)
from laddercodec.operands.banks import (
    BIT_BANKS,
    REGISTER_BANKS,
    WORD_IO_BANKS,
    XY_BANKS,
    Bank,
    bits_per_register,
)

# ---------------------------------------------------------------------------
# Banks and ranges
# ---------------------------------------------------------------------------


def test_banks_are_in_click_type_order() -> None:
    assert list(ADDRESS_BANKS) == list(BANKS)
    for name, flag in Bank.__members__.items():
        type_number = flag.bit_length() - 1
        assert parse_addr_key(type_number << 24) == (name, 0)


@pytest.mark.parametrize("bank", list(BANKS))
def test_bank_range(bank: str) -> None:
    config = BANKS[bank]
    if bank in WORD_IO_BANKS:
        expected = (xd_yd_mdb_to_display(config.min_addr), xd_yd_mdb_to_display(config.max_addr))
    else:
        expected = (config.min_addr, config.max_addr)
    assert ADDRESS_BANKS[bank] == expected
    assert ADDRESS_BANKS[bank][1] == config.display_max_addr


def test_xy_slots() -> None:
    assert BANKS["X"].valid_ranges == XY_SLOTS
    assert BANKS["Y"].valid_ranges == XY_SLOTS
    assert XY_BANKS == {name for name, config in BANKS.items() if config.valid_ranges}
    x_points = sum(1 for bank, _ in iter_address_slots() if bank == "X")
    assert xy_points(BANKS["X"].min_addr, BANKS["X"].max_addr) == x_points


def test_xy_room() -> None:
    """A count from a CPU or option slot point can cover the rest of both slots. A count
    from an expansion slot point can cover the rest of that slot."""
    slots = BANKS["X"].valid_ranges
    assert slots is not None
    (cpu_first, cpu_last), (option_first, option_last), *expansion = slots
    option_points = option_last - option_first + 1
    for number in range(cpu_first, cpu_last + 1):
        assert xy_room(number) == cpu_last - number + 1 + option_points, number
    for first, last in [(option_first, option_last), *expansion]:
        for number in range(first, last + 1):
            assert xy_room(number) == last - number + 1, number


@pytest.mark.parametrize("bank", sorted(WORD_IO_BANKS))
def test_word_io_addresses(bank: str) -> None:
    """XD and YD have the same addresses in both libraries, and each maps to its MDB slot."""
    config = BANKS[bank]
    shown = {
        mdb: (xd_yd_mdb_to_display(mdb), is_xd_yd_upper_byte(bank, mdb))
        for mdb in range(config.min_addr, config.max_addr + 1)
        if not is_xd_yd_hidden_slot(bank, mdb)
    }
    lo, hi = ADDRESS_BANKS[bank]
    parsed = [parse_address(f"{bank}{n}{u}") for n in range(lo - 1, hi + 2) for u in ("", "u")]
    ours = {
        xd_yd_display_to_mdb(a.number, a.upper): (a.number, a.upper)
        for a in parsed
        if a is not None
    }
    assert ours == shown


def test_xy_word_order() -> None:
    """A Math formula orders the XD and YD numbers as CLICK lists the addresses."""
    for bank in sorted(WORD_IO_BANKS):
        listed = tuple(
            format_address_display(name, mdb).removeprefix(bank)
            for name, mdb in iter_address_slots()
            if name == bank
        )
        assert math_formula._XY_WORD_ORDER == listed


def _range_text(bank: str) -> str:
    """Return the range text of ``bank`` built from pyclickplc's slots."""
    config = BANKS[bank]
    if config.valid_ranges is not None:
        slots = [
            f"{format_address_display(bank, first)}-{format_address_display(bank, last)}"
            for first, last in config.valid_ranges
        ]
        return f"{slots[0]}, {slots[1]}, {slots[2]} ... {slots[-1]}"
    if bank in WORD_IO_BANKS:
        names = [
            format_address_display(name, mdb) for name, mdb in iter_address_slots() if name == bank
        ]
        return f"{names[0]}, {names[1]}, {names[2]}-{names[-1]}"
    return f"{bank}{config.min_addr}-{bank}{config.max_addr}"


@pytest.mark.parametrize("bank", list(BANKS))
def test_bank_range_text(bank: str) -> None:
    """A refusal message lists the same range of each bank as pyclickplc."""
    assert address_module._bank_range_text(bank) == _range_text(bank)


def _laddercodec_addresses() -> Iterator[str]:
    """Yield the display form of every address that laddercodec's ranges and slots allow."""
    for bank, (lo, hi) in ADDRESS_BANKS.items():
        for number in range(lo, hi + 1):
            for upper in (False, True):
                address = parse_address(Address(bank, number, upper).display)
                if address is not None:
                    yield address.display


def test_every_address() -> None:
    """Both libraries list the same addresses, in the same display form."""
    theirs = [format_address_display(bank, mdb) for bank, mdb in iter_address_slots()]
    ours = list(_laddercodec_addresses())
    assert len(ours) == len(set(ours))
    assert set(ours) == set(theirs)


# ---------------------------------------------------------------------------
# Bit banks, register banks and register widths
# ---------------------------------------------------------------------------


def test_bit_and_register_banks() -> None:
    assert BIT_BANKS == BIT_ONLY_TYPES
    assert REGISTER_BANKS == set(BANKS) - BIT_ONLY_TYPES
    assert WORD_IO_BANKS == {name for name in BANKS if is_xd_yd_upper_byte(name, 1)}


@pytest.mark.parametrize("bank", list(BANKS))
def test_bits_per_register(bank: str) -> None:
    """A register is as wide as the Modbus registers that hold it. Bits and TXT have no width."""
    config = BANKS[bank]
    if bank in BIT_ONLY_TYPES or config.data_type == DataType.TXT:
        expected = None
    else:
        _, words = plc_to_modbus(bank, config.min_addr)
        expected = 16 * words
    assert bits_per_register(bank) == expected


def _of_type(*types: DataType) -> frozenset[str]:
    """Return the banks whose data type is one of ``types``."""
    return frozenset(name for name, config in BANKS.items() if config.data_type in types)


def test_32_bit_integer_banks() -> None:
    assert copy._INT32_BANKS == _of_type(DataType.INT2)


def test_two_register_banks() -> None:
    """Send and Receive treat the banks of two Modbus registers as wide."""
    registers = set(BANKS) - BIT_ONLY_TYPES - _of_type(DataType.TXT)
    wide = {name for name in registers if plc_to_modbus(name, BANKS[name].min_addr)[1] == 2}
    assert send_receive._WIDE_BANKS == wide
    assert send_receive._FC16_ONLY == wide


def test_send_hex_fffd_banks() -> None:
    """A hex remote start stops at FFFDh for a local bank of 32-bit integers, reals or text."""
    assert send_receive._SEND_HEX_FFFD == _of_type(DataType.INT2, DataType.FLOAT, DataType.TXT)


def test_same_type_banks() -> None:
    """Send and Receive group each register bank with the banks of its data type."""
    assert set(send_receive._SAME_TYPE) == set(BANKS) - BIT_ONLY_TYPES
    for bank, group in send_receive._SAME_TYPE.items():
        assert group == _of_type(BANKS[bank].data_type), bank


def test_receive_remote_banks() -> None:
    """A Receive pairs each local bank only with remote banks of its data type."""
    for local, remotes in send_receive._RECEIVE_REMOTE_FOR_DEST.items():
        assert remotes == _of_type(BANKS[local].data_type), local


def test_send_slave_id_ds_range() -> None:
    """A Send's Slave ID accepts every DS address and no number past the last one."""
    config = BANKS["DS"]
    for number in (config.min_addr, config.max_addr):
        ModbusRtuTarget(name="r", com_port="cpu2", device_id=f"DS{number}")
    for number in (config.min_addr - 1, config.max_addr + 1):
        with pytest.raises(FieldError):
            ModbusRtuTarget(name="r", com_port="cpu2", device_id=f"DS{number}")


# ---------------------------------------------------------------------------
# T/TD and CT/CTD pairs
# ---------------------------------------------------------------------------


def _timer(done: str, accumulator: str) -> Timer:
    return Timer("on_delay", done, accumulator, "1", "Tms")


def _counter(done: str, accumulator: str) -> Counter:
    return Counter("count_up", done, accumulator, "1")


#: The instruction whose done bit is in each bit bank of an interleaved pair.
_PAIRED_INSTRUCTIONS: dict[str, Callable[[str, str], object]] = {"T": _timer, "CT": _counter}


def test_paired_banks_are_the_interleaved_banks() -> None:
    interleaved = {name for name, config in BANKS.items() if config.interleaved_with}
    bits = interleaved & BIT_ONLY_TYPES
    assert set(_PAIRED_INSTRUCTIONS) == bits


@pytest.mark.parametrize("bit_bank", sorted(_PAIRED_INSTRUCTIONS))
def test_paired_banks(bit_bank: str) -> None:
    """A Timer or Counter accepts the done bit with its interleaved register, and no other."""
    build = _PAIRED_INSTRUCTIONS[bit_bank]
    word_bank = BANKS[bit_bank].interleaved_with
    assert word_bank is not None
    config = BANKS[bit_bank]
    for number in (config.min_addr, config.max_addr):
        build(f"{bit_bank}{number}", f"{word_bank}{number}")
    for other in sorted(REGISTER_BANKS - {word_bank}):
        lo, _ = ADDRESS_BANKS[other]
        with pytest.raises(FieldError):
            build(f"{bit_bank}1", Address(other, max(lo, 1)).display)


# ---------------------------------------------------------------------------
# Address text
# ---------------------------------------------------------------------------

#: Address-like text, with any space around it kept in the first and last groups.
_TEXT_RE = re.compile(r"(\s*)([A-Za-z]+)([0-9]+)([uU]?)(\s*)")


def _rewrite(text: str, fix: Callable[[str, str, str], tuple[str, str, str]]) -> str:
    """Return ``text`` with its bank, digits and suffix passed through ``fix``.

    Text that is not address-like comes back unchanged."""
    match = _TEXT_RE.fullmatch(text)
    if match is None:
        return text
    before, letters, digits, suffix, after = match.groups()
    return before + "".join(fix(letters, digits, suffix)) + after


def _parts(text: str) -> tuple[str, str, str] | None:
    match = _TEXT_RE.fullmatch(text)
    return None if match is None else (match.group(2), match.group(3), match.group(4))


def _has_edge_space(text: str) -> bool:
    return text != text.strip()


def _has_long_number(text: str) -> bool:
    parts = _parts(text)
    return parts is not None and len(parts[1]) > 5


def _drop_long_zeros(text: str) -> str:
    def fix(letters: str, digits: str, suffix: str) -> tuple[str, str, str]:
        if len(digits) > 5 and digits[:-5].strip("0") == "":
            digits = digits[-5:]
        return letters, digits, suffix

    return _rewrite(text, fix)


def _not_display_case(text: str) -> bool:
    parts = _parts(text)
    return parts is not None and (not parts[0].isupper() or parts[2] == "U")


def _display_case(text: str) -> str:
    return _rewrite(text, lambda letters, digits, suffix: (letters.upper(), digits, suffix.lower()))


def _padded_upper_byte(text: str) -> bool:
    parts = _parts(text)
    return parts is not None and parts[2] != "" and len(parts[1]) > 1


def _drop_upper_byte_zeros(text: str) -> str:
    return _rewrite(
        text, lambda letters, digits, suffix: (letters, digits.lstrip("0") or "0", suffix)
    )


class Difference(NamedTuple):
    """A kind of text that laddercodec refuses and pyclickplc reads as an address."""

    #: Return whether a text is of this kind.
    matches: Callable[[str], bool]
    #: Return the text without this difference. laddercodec reads the result as pyclickplc
    #: reads the original.
    remove: Callable[[str], str]
    reason: str


#: The kinds of text that an instruction field refuses and pyclickplc's
#: ``normalize_address`` reads as an address. ``_read`` reads text as an instruction field
#: does: ``normalize_address`` first, and then the address check that ``parse_address``
#: also makes.
DIFFERENCES: dict[str, Difference] = {
    "edge space": Difference(
        _has_edge_space,
        str.strip,
        "An instruction field in laddercodec refuses an address with a space at either end. "
        "pyclickplc strips the spaces first.",
    ),
    "long number": Difference(
        _has_long_number,
        _drop_long_zeros,
        "An instruction field in laddercodec refuses an address number of more than five "
        "digits. pyclickplc reads a number of any length.",
    ),
}

#: The kinds of text that laddercodec's ``parse_address`` refuses and pyclickplc reads.
#: ``parse_address`` reads text in display form. An instruction field writes its text in
#: that form with ``normalize_address`` first.
PARSE_DIFFERENCES: dict[str, Difference] = {
    **DIFFERENCES,
    "case": Difference(
        _not_display_case,
        _display_case,
        "parse_address reads only an uppercase bank and a lowercase u.",
    ),
    "padded upper byte": Difference(
        _padded_upper_byte,
        _drop_upper_byte_zeros,
        "parse_address reads an upper byte only as XD0u or YD0u, with no extra zeros.",
    ),
}


def _numbers(bank: str) -> set[int]:
    """Return the numbers to spell for ``bank``: each end of its range and of each slot, and
    the number on each side of an end, and 0 and 1."""
    config = BANKS[bank]
    ends = {config.min_addr, config.display_max_addr}
    for first, last in config.valid_ranges or ():
        ends |= {first, last}
    return {n for end in ends for n in (end - 1, end, end + 1) if n >= 0} | {0, 1}


def _corpus() -> list[str]:
    texts: set[str] = set()
    for bank in BANKS:
        for number in _numbers(bank):
            for name in (bank, bank.lower(), bank.title()):
                for digits in (f"{number}", f"{number:03d}", f"{number:05d}", f"{number:06d}"):
                    for suffix in ("", "u", "U"):
                        texts.add(f"{name}{digits}{suffix}")
    texts |= {"", " ", "X", "1", "u", "ZZ1", "XX1", "DSS1", "X1.0", "X-1", "X+1", "X 1"}
    texts |= {"X\u0663", "\uff38\uff11", "DS[DS1]", "XD0uu", "XDu", "XD00u", "xD0U", "Xd0u"}
    texts |= {" X1", "X1 ", "\tDS1", "DS1\n", " xd0u "}
    return sorted(texts)


CORPUS = _corpus()


def _read(text: str) -> str | None:
    """Return the display form that an instruction field writes for ``text``, or None."""
    address = parse_address(normalize_address(text))
    return None if address is None else address.display


def _parse(text: str) -> str | None:
    address = parse_address(text)
    return None if address is None else address.display


def _check_text(read: Callable[[str], str | None], allowed: dict[str, Difference]) -> None:
    """Assert that ``read`` and pyclickplc read each text in the corpus alike, except where
    ``allowed`` explains the difference.

    A difference is explained when laddercodec refuses the text and pyclickplc reads it.
    Each matching kind removes its difference from the text. laddercodec then reads the
    result as pyclickplc reads the original.
    Each kind must be the only kind that explains at least one text. Otherwise the entry is
    stale, or another entry hides it.
    """
    unexplained: list[tuple[str, str | None, str | None]] = []
    seen: set[str] = set()
    for text in CORPUS:
        ours, theirs = read(text), pc_normalize(text)
        if ours == theirs:
            continue
        kinds = [name for name, kind in allowed.items() if kind.matches(text)]
        fixed = text
        for name in kinds:
            fixed = allowed[name].remove(fixed)
        if ours is None and theirs is not None and kinds and read(fixed) == theirs:
            if len(kinds) == 1:
                seen.add(kinds[0])
        else:
            unexplained.append((text, ours, theirs))
    assert unexplained == []
    assert seen == set(allowed), (
        "An entry explains no differing text on its own. Remove the entry, or add to the "
        "corpus a text that only it explains."
    )


def test_read_address_text() -> None:
    """An instruction field and pyclickplc agree on which text is an address, and its form."""
    _check_text(_read, DIFFERENCES)


def test_parse_address_text() -> None:
    _check_text(_parse, PARSE_DIFFERENCES)


def test_parsed_number() -> None:
    """Both libraries read the same bank and number from each address in the corpus."""
    for text in CORPUS:
        address = parse_address(text)
        if address is None:
            continue
        number = address.number
        if address.bank in WORD_IO_BANKS:
            number = xd_yd_display_to_mdb(number, address.upper)
        assert pc_parse(text) == (address.bank, number), text
