"""classify() and parse_digits(): each constant kind's accepted and refused forms."""

from __future__ import annotations

import pytest

from laddercodec.operands.constants import (
    TEXT_MAX,
    Constant,
    Kind,
    classify,
    parse_digits,
)

N, F, H, T, C = Kind.INTEGER, Kind.FLOAT, Kind.HEX, Kind.TEXT, Kind.CHAR

ACCEPTED: list[tuple[str, Constant]] = [
    # Decimal integers: int16, then int32 (wide).
    ("0", Constant(N, 0)),
    ("42", Constant(N, 42)),
    ("-0", Constant(N, 0)),
    ("+1", Constant(N, 1)),
    ("-1", Constant(N, -1)),
    ("007", Constant(N, 7)),
    ("32767", Constant(N, 32767)),
    ("-32768", Constant(N, -32768)),
    ("32768", Constant(N, 32768, wide=True)),
    ("-32769", Constant(N, -32769, wide=True)),
    ("2147483647", Constant(N, 2147483647, wide=True)),
    ("-2147483648", Constant(N, -2147483648, wide=True)),
    ("+2147483647", Constant(N, 2147483647, wide=True)),
    ("0000000000002147483647", Constant(N, 2147483647, wide=True)),
    # Floating point: a '.' or an exponent, either case.
    ("1.5", Constant(F, 1.5)),
    ("-1.5", Constant(F, -1.5)),
    (".5", Constant(F, 0.5)),
    ("1.", Constant(F, 1.0)),
    ("1E5", Constant(F, 1e5)),
    ("1e5", Constant(F, 1e5)),
    ("-1.5e-3", Constant(F, -1.5e-3)),
    ("3.4028235E+38", Constant(F, 3.4028235e38)),
    # Hex: 16-bit by value, 32-bit up to eight digits; either case of letter and h.
    ("0h", Constant(H, 0)),
    ("0H", Constant(H, 0)),
    ("0000h", Constant(H, 0)),
    ("FFFFh", Constant(H, 0xFFFF)),
    ("ffffh", Constant(H, 0xFFFF)),
    ("FFFFH", Constant(H, 0xFFFF)),
    ("0FFFFh", Constant(H, 0xFFFF)),
    ("000000000FFFFh", Constant(H, 0xFFFF)),
    ("1E5h", Constant(H, 0x1E5)),
    ("10000h", Constant(H, 0x10000, wide=True)),
    ("FFFFFFFFh", Constant(H, 0xFFFFFFFF, wide=True)),
    ("0001FFFFh", Constant(H, 0x1FFFF, wide=True)),
    # Text: 1 to 128 printable ASCII characters between quotes, kept as written.
    ('"A"', Constant(T, "A")),
    ('"ab"', Constant(T, "ab")),
    ('" "', Constant(T, " ")),
    ('"a,b"', Constant(T, "a,b")),
    ('"$41"', Constant(T, "$41")),
    ('"~"', Constant(T, "~")),
    ('"' + "A" * TEXT_MAX + '"', Constant(T, "A" * TEXT_MAX)),
    # Character codes: $ and two hex digits.
    ("$00", Constant(C, 0)),
    ("$41", Constant(C, 0x41)),
    ("$0d", Constant(C, 0x0D)),
    ("$FF", Constant(C, 0xFF)),
    ("$ff", Constant(C, 0xFF)),
]

REFUSED: list[str] = [
    # Empty and whitespace: nothing is trimmed.
    "",
    " ",
    " 5",
    "5 ",
    "1 0",
    '"A" ',
    # Addresses are no constants.
    "DS1",
    "ds1",
    "X001",
    "TXT1",
    "XD0u",
    "DS[DS1]",
    # Integers outside int32, and signs that don't lead.
    "2147483648",
    "-2147483649",
    "3000000000",
    "99999999999999999999999999999",
    "1-2",
    "--5",
    "+-5",
    "+",
    "-",
    # Hex: no sign, no 0x, at least one digit, at most eight digits above FFFFh.
    "+1h",
    "-1h",
    "0x10",
    "0X10",
    "h",
    "H",
    "FFFF",
    "100000000h",
    "0FFFFFFFFh",
    "1Gh",
    "FF h",
    # Floating point: no comma, no bare exponent, no nan or inf.
    "1,5",
    "1,000",
    "E5",
    "1E",
    "1E+",
    ".",
    "nan",
    "inf",
    "-inf",
    "1.5.2",
    # Separators and other spellings.
    "1_000",
    "1'000",
    "'A'",
    # Text: empty, unterminated, a quote inside, too long, not printable ASCII.
    '""',
    '"""',
    '"A',
    'A"',
    '"a"b"',
    '"A""B"',
    '"' + "A" * (TEXT_MAX + 1) + '"',
    '"é"',
    '"\t"',
    '"\x7f"',
    "A",
    "abc",
    # Character codes other than two hex digits.
    "$",
    "$1",
    "$D",
    "$100",
    "$4142",
    "$GG",
    "$-1",
    # Unicode digits are no digits (arc.md ruling 2026-11-11).
    "٣",
    "1٣",
    "٣h",
    "$٣٣",
    "１",
    "1.٣",
]


@pytest.mark.parametrize(("text", "expected"), ACCEPTED, ids=[t for t, _ in ACCEPTED])
def test_accepted(text: str, expected: Constant) -> None:
    got = classify(text)
    assert got == expected
    assert got is not None
    assert type(got.value) is type(expected.value)


@pytest.mark.parametrize("text", REFUSED, ids=[repr(t) for t in REFUSED])
def test_refused(text: str) -> None:
    assert classify(text) is None


@pytest.mark.parametrize(
    ("text", "wide"),
    [("32767", False), ("32768", True), ("-32768", False), ("-32769", True)]
    + [("FFFFh", False), ("10000h", True), ("1.5", False), ('"A"', False), ("$41", False)],
)
def test_wide(text: str, wide: bool) -> None:
    got = classify(text)
    assert got is not None and got.wide is wide


def test_kinds_are_strings() -> None:
    assert [str(k) for k in Kind] == ["integer", "float", "hex", "text", "char"]


DIGITS: list[tuple[str, int | None]] = [
    ("0", 0),
    ("7", 7),
    ("007", 7),
    ("32767", 32767),
    ("2147483648", 2147483648),
    ("0" * 30 + "5", 5),
    ("9" * 20, int("9" * 20)),
    ("9" * 21, None),
    ("1" * 5000, None),
    ("", None),
    (" ", None),
    (" 5", None),
    ("5 ", None),
    ("1 0", None),
    ("+1", None),
    ("-1", None),
    ("1.5", None),
    ("1E5", None),
    ("FFh", None),
    ("1_000", None),
    ("DS1", None),
    ("٣", None),
    ("1٣", None),
    ("１", None),
]


@pytest.mark.parametrize(("text", "expected"), DIGITS, ids=[repr(t[:12]) for t, _ in DIGITS])
def test_parse_digits(text: str, expected: int | None) -> None:
    assert parse_digits(text) == expected
