"""Tests for real_display(), copy_real_display() and constant_text().

real_display() and copy_real_display() write a typed real in CLICK's form. constant_text()
writes a Python value as a CLICK constant."""

from __future__ import annotations

import math
import re
import struct

import pytest

from laddercodec import Copy, FieldError, Math, constant_text
from laddercodec.operands.constants import (
    FLOAT32_MAX,
    classify,
    copy_real_display,
    fits_float32,
    real_display,
)


def _copy_source(typed: str, destination: str, kept: str | None = None) -> str:
    """Return the source that a single Copy of ``typed`` stores.

    Pass ``kept`` when ``typed`` has more than 7 significant digits. The helper then asserts
    that the Copy refuses ``typed`` and names ``kept``, and it builds the Copy from ``kept``
    instead."""
    if kept is not None:
        with pytest.raises(
            FieldError, match=f"CLICK keeps 7 significant digits: write {re.escape(kept)}$"
        ):
            Copy(typed, destination)
        typed = kept
    return Copy(typed, destination).source


def _math_refuses(typed: str, kept: str) -> None:
    """Assert that a Math refuses ``typed`` and names ``kept``, and that a Math of ``kept`` builds.

    ``typed`` is a real of more than 6 significant digits."""
    with pytest.raises(
        FieldError, match=f"CLICK keeps 6 significant digits in Math: write {re.escape(kept)}$"
    ):
        Math(typed, "DF1")
    assert Math(kept, "DF1").expression.replace(" ", "") == kept


#: The value that a Copy's refusal names for each real of more than 7 significant digits.
#: It is the float32 value printed with 7 significant digits. CLICK saves 3.4028235E+38 as
#: 3.402823E+38.
_COPY_KEPT = {
    "3.4028235E+38": "3.402823E+38",
    "-3.4028235E+38": "-3.402823E+38",
    "+3.4028235E+38": "3.402823E+38",
    "3.40282355E+38": "3.402823E+38",
    "-3.40282355E+38": "-3.402823E+38",
    "3.40282347E+38": "3.402823E+38",
    "-3.40282347E+38": "-3.402823E+38",
    "1.17549435E-38": "1.175494E-38",
    "-1.17549435E-38": "-1.175494E-38",
    "1.1754942E-38": "1.175494E-38",
    "-1.1754942E-38": "-1.175494E-38",
    "9.9999999E+37": "1E+38",
    "-9.9999999E+37": "-1E+38",
    "1.0000001E+10": "1E+10",
    "-1.0000001E+10": "-1E+10",
    "1.2345678E+10": "1.234568E+10",
    "1234567.89": "1234568.0",
}


@pytest.mark.parametrize(
    ("typed", "printed"),
    [
        # CLICK gave these answers.
        ("1.50", "1.5"),
        ("1e3", "1000.0"),
        (".5", "0.5"),
        ("1E5", "100000.0"),
        ("1.5E+10", "1.5E+10"),
        ("+2.5", "+2.5"),
        # No CLICK answer is captured for these, so they are laddercodec's. They are printed
        # with 7 significant digits. A typed + is kept, as CLICK keeps it on +2.5.
        ("+2.50", "+2.5"),
        ("-1.50", "-1.5"),
        ("1.", "1.0"),
        ("0.0001", "0.0001"),
        # laddercodec's answers: it drops the digits beyond the float32 value, and the value
        # stays the same.
        ("0.30000001", "0.3"),
        ("9999999.4", "9999999.0"),
        # Kept as typed, because 7 significant digits print another float32 value.
        ("1234567.89", "1234567.89"),
        ("0.123456789", "0.123456789"),
        # Kept as typed, because 7 significant digits print these in exponent form. CLICK's
        # form for them in a Math is not known. For a Copy, copy_real_display gives it.
        ("1e7", "1e7"),
        ("1.0E-10", "1.0E-10"),
        ("0.00009", "0.00009"),
        ("3.4028235E+38", "3.4028235E+38"),
    ],
)
def test_real_display(typed: str, printed: str) -> None:
    assert real_display(typed) == printed
    # The typed and the printed text give the same float32 value.
    assert struct.pack("<f", float(printed)) == struct.pack("<f", float(typed))


@pytest.mark.parametrize(
    ("typed", "printed"),
    [
        # CLICK gave these answers for a single Copy source.
        ("+1.5", "1.5"),
        ("-1.5", "-1.5"),
        ("1.50", "1.5"),
        ("01.5", "1.5"),
        (".5", "0.5"),
        ("-.5", "-0.5"),
        ("1.", "1.0"),
        ("1E5", "100000.0"),
        ("1.5E+3", "1500.0"),
        ("1.5e-3", "0.0015"),
        ("-1.5E-3", "-0.0015"),
        ("3.4028235E+38", "3.402823E+38"),
        ("1E-45", "1E-45"),
        ("1E-50", "1E-50"),
        # No CLICK answer is captured for these. laddercodec prints them as real_display
        # does, but drops a typed +.
        ("+2.50", "2.5"),
        ("-3.4028235E+38", "-3.402823E+38"),
        ("+3.4028235E+38", "3.402823E+38"),
        # The value is rounded to float32 first, so it prints as the largest float32, not as
        # a value above it.
        ("3.40282355E+38", "3.402823E+38"),
        ("-3.40282355E+38", "-3.402823E+38"),
        ("1.17549435E-38", "1.175494E-38"),
        ("1.2345678E+10", "1.234568E+10"),
        ("1234567.89", "1234567.89"),
        ("1e7", "1e7"),
        ("+1e7", "1e7"),
        ("1.0E-10", "1.0E-10"),
    ],
)
def test_copy_real_display(typed: str, printed: str) -> None:
    assert copy_real_display(typed) == printed
    assert fits_float32(float(printed))
    if typed in _COPY_KEPT:
        # CLICK keeps 7 significant digits. A Copy refuses more and names the value with 7.
        assert _copy_source(typed, "DF1", _COPY_KEPT[typed]) == _COPY_KEPT[typed]
    else:
        assert Copy(typed, "DF1").source == printed


_F32_EDGES = [
    "3.4028235E+38",
    "3.40282355E+38",
    "3.40282347E+38",
    "3.402823E+38",
    "1.17549435E-38",
    "1.1754942E-38",
    "1.4E-45",
    "1E-45",
    "1E-50",
    "9.9999999E+37",
    "1.0000001E+10",
    "9.999999E-05",
]


@pytest.mark.parametrize("typed", [*_F32_EDGES, *(f"-{t}" for t in _F32_EDGES)])
def test_copy_real_is_stored_once(typed: str) -> None:
    # A Copy built from a stored source stores the same source again. The source fits float32.
    stored = _copy_source(typed, "DF1", _COPY_KEPT.get(typed))
    assert Copy(stored, "DF1").source == stored
    assert fits_float32(float(stored))


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
        # constant_text writes the nearest float32 value, in the fewest digits that read
        # back as that value.
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


@pytest.mark.parametrize("sign", [1, -1])
def test_constant_text_at_the_float32_edge(sign: int) -> None:
    # constant_text writes the largest float32 in the fewest digits that read back as it
    # and do not go above it.
    text = constant_text(sign * FLOAT32_MAX)
    assert text == ("-" if sign < 0 else "") + "3.402823466E+38"
    assert struct.unpack("<f", struct.pack("<f", float(text)))[0] == sign * FLOAT32_MAX
    minus = "-" if sign < 0 else ""
    # A Math refuses it and names the value with 6 significant digits. A Copy refuses it and
    # names the value with 7.
    _math_refuses(text, f"{minus}3.40282E+38")
    assert _copy_source(text, "DF1", f"{minus}3.402823E+38") == f"{minus}3.402823E+38"
    assert constant_text(sign * 3.4025e38) == ("-" if sign < 0 else "") + "3.4025E+38"


@pytest.mark.parametrize(
    "value",
    [
        *(0, 5, -7, 70000, -(2**31), 2**31 - 1, 0.5, 1000.0, 1e5, 1.5e10, 1 / 3, 1e-10),
        *(16777217.0, "AB", chr(13)),
    ],
)
def test_constant_text_is_what_construction_stores(value: int | float | str) -> None:
    text = constant_text(value)
    destination = "TXT1" if isinstance(value, str) else "DD1" if isinstance(value, int) else "DF1"
    if text in _BEYOND:
        # The text has more significant digits than CLICK keeps, so a Copy and a Math refuse it.
        copy_kept, math_kept = _BEYOND[text]
        assert _copy_source(text, destination, copy_kept) == copy_kept
        _math_refuses(text, math_kept)
        return
    assert Copy(text, destination).source == text
    if not isinstance(value, str):
        assert Math(text, "DF1").expression.replace(" ", "") == text


#: For each constant_text result with more digits than CLICK keeps, the value that a Copy's
#: refusal names (7 significant digits) and the value that a Math's refusal names (6).
_BEYOND = {
    "0.33333334": ("0.3333333", "0.333333"),
    "16777216.0": ("1.677722E+07", "1.67772E+07"),
}


#: Reals in exponent form that need more than 7 digits. A Copy and a Math refuse them.
#: Each entry is (value, constant_text result, the value that a Copy's refusal names, the
#: value that a Math's refusal names).
_LONG_EXPONENT = [
    (FLOAT32_MAX, "3.402823466E+38", "3.402823E+38", "3.40282E+38"),
    (1.2345678e10, "1.2345678E+10", "1.234568E+10", "1.23457E+10"),
    (1.17549435e-38, "1.1754944E-38", "1.175494E-38", "1.17549E-38"),
]


@pytest.mark.parametrize(("value", "text", "stored", "in_math"), _LONG_EXPONENT)
def test_constant_text_long_exponent_real(
    value: float, text: str, stored: str, in_math: str
) -> None:
    # A Math refuses the value and names it with 6 significant digits. A Copy refuses it and
    # names it with 7.
    assert constant_text(value) == text
    nearest = struct.unpack("<f", struct.pack("<f", value))[0]
    assert struct.unpack("<f", struct.pack("<f", float(text)))[0] == nearest
    _math_refuses(text, in_math)
    assert _copy_source(text, "DF1", stored) == stored


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
