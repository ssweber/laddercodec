"""classify() and parse_digits(): each constant kind's accepted and refused forms."""

from __future__ import annotations

import pytest

from laddercodec.operands.constants import (
    TEXT_MAX,
    Constant,
    Kind,
    classify,
    parse_digits,
    printable,
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
    ("0E0", Constant(F, 0.0)),
    ("3.5E+3", Constant(F, 3500.0)),
    ("-3.4028235E+38", Constant(F, -3.4028235e38)),
    # rounds to float32's largest finite value
    ("3.40282356E+38", Constant(F, 3.40282356e38)),
    ("-3.40282356E+38", Constant(F, -3.40282356e38)),
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
    ("0E0h", Constant(H, 0xE0)),
    ("1EH", Constant(H, 0x1E)),
    # Hex is tried before an address, so letters-only hex is a constant, not a bank name.
    ("DH", Constant(H, 0xD)),
    ("EH", Constant(H, 0xE)),
    ("ABCH", Constant(H, 0xABC)),
    ("10000h", Constant(H, 0x10000, wide=True)),
    ("FFFFFFFFh", Constant(H, 0xFFFFFFFF, wide=True)),
    ("0001FFFFh", Constant(H, 0x1FFFF, wide=True)),
    # Text: 1 to 128 characters between quotes, any character but the quote, as written.
    ('"A"', Constant(T, "A")),
    ('"ab"', Constant(T, "ab")),
    ('" "', Constant(T, " ")),
    ('"a,b"', Constant(T, "a,b")),
    ('"$41"', Constant(T, "$41")),
    ('"~"', Constant(T, "~")),
    ('"' + "A" * TEXT_MAX + '"', Constant(T, "A" * TEXT_MAX)),
    # The shared check takes non-ASCII and control characters; printable() is a field limit.
    ('"\u00e9"', Constant(T, "\u00e9")),
    ('"\t"', Constant(T, "\t")),
    ('"\x7f"', Constant(T, "\x7f")),
    ('"\u0663"', Constant(T, "\u0663")),
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
    # Floating point: no comma, no bare exponent, nothing that is not finite.
    "1,5",
    "1,000",
    "E5",
    "1E",
    "1E+",
    ".",
    "nan",
    "inf",
    "-inf",
    "1E999",
    "-1E999",
    # above float32 (arc.md Q-M17, dialog 2026-11-12); a value rounding to its largest passes
    "3.5E+38",
    "-3.5E+38",
    "3.4028236E+38",
    "1.5.2",
    # Separators and other spellings.
    "1_000",
    "1'000",
    "'A'",
    # Text: empty, unterminated, a quote inside, too long.
    '""',
    '"""',
    '"A',
    'A"',
    '"a"b"',
    '"A""B"',
    '"' + "A" * (TEXT_MAX + 1) + '"',
    '"é' + "A" * TEXT_MAX + '"',
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


#: More leading zeros than int() converts (it refuses text over 4300 digits).
ZEROS = "0" * 5000


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (ZEROS + "1", Constant(N, 1)),
        ("-" + ZEROS + "1", Constant(N, -1)),
        ("+" + ZEROS + "40000", Constant(N, 40000, wide=True)),
        (ZEROS, Constant(N, 0)),
        (ZEROS + "1h", Constant(H, 1)),
        (ZEROS + "1" + "0" * 10, None),
    ],
    ids=["zeros-1", "minus-zeros-1", "plus-zeros-40000", "zeros", "zeros-1h", "zeros-big"],
)
def test_leading_zeros(text: str, expected: Constant | None) -> None:
    assert classify(text) == expected


def test_parse_digits_leading_zeros() -> None:
    assert parse_digits(ZEROS + "5") == 5
    assert parse_digits(ZEROS) == 0


@pytest.mark.parametrize(
    ("text", "expected"),
    [("A", True), (" ~", True), ('"', True), ("", True)]
    + [("é", False), ("\t", False), ("\x7f", False), ("٣", False)],
)
def test_printable(text: str, expected: bool) -> None:
    assert printable(text) is expected
