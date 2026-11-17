"""real_display() and constant_text(): a real and a Python value written in CLICK's form."""

from __future__ import annotations

import math
import struct

import pytest

from laddercodec import Copy, Math, constant_text
from laddercodec.operands.constants import classify, real_display


@pytest.mark.parametrize(
    ("typed", "printed"),
    [
        # CLICK's answers.
        ("1.50", "1.5"),
        ("1e3", "1000.0"),
        (".5", "0.5"),
        ("1E5", "100000.0"),
        ("1.5E+10", "1.5E+10"),
        ("+2.5", "+2.5"),
        # laddercodec's, until CLICK answers: printed with 7 significant digits, a typed +
        # kept as CLICK keeps it on +2.5.
        ("+2.50", "+2.5"),
        ("-1.50", "-1.5"),
        ("1.", "1.0"),
        ("0.0001", "0.0001"),
        # laddercodec's: digits beyond the float32 value are dropped, the same value.
        ("0.30000001", "0.3"),
        ("9999999.4", "9999999.0"),
        # Kept as typed: 7 digits print another float32 value.
        ("1234567.89", "1234567.89"),
        ("0.123456789", "0.123456789"),
        # Kept as typed: 7 digits print it in exponent form, whose CLICK form is not known.
        ("1e7", "1e7"),
        ("1.0E-10", "1.0E-10"),
        ("0.00009", "0.00009"),
        ("3.4028235E+38", "3.4028235E+38"),
    ],
)
def test_real_display(typed: str, printed: str) -> None:
    assert real_display(typed) == printed
    # The same float32 value either way.
    assert struct.pack("<f", float(printed)) == struct.pack("<f", float(typed))


@pytest.mark.parametrize(
    ("value", "hex_", "text"),
    [
        (5, False, "5"),
        (-7, False, "-7"),
        (70000, False, "70000"),
        (255, True, "FFh"),
        (0, True, "0h"),
        (0x10000, True, "10000h"),
        (1000.0, False, "1000.0"),
        (0.5, False, "0.5"),
        (1.5, False, "1.5"),
        (-0.0, False, "-0.0"),
        (1e5, False, "100000.0"),
        (1.5e10, False, "1.5E+10"),
        # The float32 value nearest, in the fewest digits that read back as it.
        (0.1, False, "0.1"),
        (1 / 3, False, "0.33333334"),
        (16777217.0, False, "16777216.0"),
        (1e20, False, "1E+20"),
        ("AB", False, '"AB"'),
        ("$41", False, '"$41"'),
        ("\r", False, "$0D"),
        ("\x7f", False, "$7F"),
    ],
)
def test_constant_text(value: int | float | str, hex_: bool, text: str) -> None:
    assert constant_text(value, hex=hex_) == text
    assert classify(text) is not None


_FLOAT32_MAX = struct.unpack("<f", bytes.fromhex("ffff7f7f"))[0]


@pytest.mark.parametrize("sign", [1, -1])
def test_constant_text_at_the_float32_edge(sign: int) -> None:
    # The fewest digits that read back as the largest float32 and stay within it.
    text = constant_text(sign * _FLOAT32_MAX)
    assert text == ("-" if sign < 0 else "") + "3.402823466E+38"
    assert struct.unpack("<f", struct.pack("<f", float(text)))[0] == sign * _FLOAT32_MAX
    assert constant_text(sign * 3.4025e38) == ("-" if sign < 0 else "") + "3.4025E+38"


@pytest.mark.parametrize(
    "value",
    [0, 5, -7, 70000, -(2**31), 2**31 - 1, 0.5, 1000.0, 1e5, 1.5e10, 1 / 3, 1e-10, "AB", chr(13)],
)
def test_constant_text_is_what_construction_stores(value: int | float | str) -> None:
    text = constant_text(value)
    destination = "TXT1" if isinstance(value, str) else "DD1" if isinstance(value, int) else "DF1"
    assert Copy(text, destination).source == text
    if not isinstance(value, str):
        assert Math(text, "DF1").expression.replace(" ", "") == text


@pytest.mark.parametrize("value", [0, 255, 0x1E3, 0xFFFF, 0x10000, 0xFFFFFFFF])
def test_constant_text_hex_is_what_construction_stores(value: int) -> None:
    text = constant_text(value, hex=True)
    assert Copy(text, "DD1").source == text
    if value <= 0xFFFF:
        assert Math(text, "DH1", mode="hex").expression == text


def test_constant_text_builds_clicks_instruction() -> None:
    assert Copy(constant_text(1000.0), "DF1") == Copy("1e3", "DF1")
    assert Math(f"DH2 + {constant_text(0x1E3, hex=True)}", "DH1", mode="hex").expression == (
        "DH2 + 1E3h"
    )
    assert Copy(constant_text("\r"), "TXT1").source == "$0D"


@pytest.mark.parametrize(
    ("value", "hex_", "error"),
    [
        (True, False, TypeError),
        (None, False, TypeError),
        (1.5, True, TypeError),
        (-1, True, ValueError),
        (2**32, True, ValueError),
        (2**31, False, ValueError),
        (-(2**31) - 1, False, ValueError),
        (2**40, False, ValueError),
        (math.inf, False, ValueError),
        (math.nan, False, ValueError),
        (1e39, False, ValueError),
        ("", False, ValueError),
        ('say "hi"', False, ValueError),
        ("A" * 129, False, ValueError),
        ("٣", False, ValueError),
    ],
)
def test_constant_text_refuses_what_no_constant_spells(
    value: object, hex_: bool, error: type[Exception]
) -> None:
    with pytest.raises(error):
        constant_text(value, hex=hex_)  # type: ignore[arg-type]
