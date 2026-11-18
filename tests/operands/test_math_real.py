"""Tests for MathReal: each form of a real in a decimal Math formula."""

from __future__ import annotations

import pytest

from laddercodec import FieldError
from laddercodec.instructions import parse_af_blob
from laddercodec.instructions.math import Math
from laddercodec.instructions.math_formula import parse
from laddercodec.operands.math_real import MathReal, held_for
from laddercodec.operands.unchecked import refusals


@pytest.mark.parametrize(
    ("typed", "stored", "held"),
    [
        ("1.50", "1.5", "1.5"),
        ("+2.50", "+2.5", "+2.5"),
        ("1e3", "1000.0", "1000.0"),
        ("1E5", "100000.0", "100000.0"),
        # An integral real is written with .0, and keeps its sign.
        ("+1e3", "+1000.0", "+1000.0"),
        ("-0.0", "-0.0", "-0.0"),
        ("0.0", "0.0", "0.0"),
        ("-1234567.0", "-1234567.0", "-1234567.0"),
        ("9999999.0", "9999999.0", "9999999.0"),
        ("0.000015", "1.5E-05", "1.5E-05"),
        ("20000000.0", "2E+07", "2E+07"),
        ("1234.000001", "1234.000001", "1234.000001"),
        # CLICK saves 1.2345E-04 as 0.00012345, and cuts 0.00012345 to 0.000123 when it is
        # typed so. The Math holds the E form.
        ("1.2345E-04", "0.00012345", "1.2345E-04"),
        ("+1.2345E-04", "+0.00012345", "+1.2345E-04"),
        ("1.5E-3", "0.0015", "0.0015"),
    ],
)
def test_forms_of_a_kept_real(typed: str, stored: str, held: str) -> None:
    real = MathReal(typed)
    assert real.kept and real.in_range
    assert real.stored == stored
    assert real.internal == f"F{stored}"
    assert real.held == held
    assert held_for(stored) == held


@pytest.mark.parametrize(
    ("typed", "saved", "instead"),
    [
        ("0.33333334", "0.333333", "0.333333"),
        ("0.00012345", "0.000123", "1.2345E-04"),
        ("1.2345678E+15", "1.234568E+15", "1.234568E+15"),
        ("1.2345e-04", None, "1.2345E-04"),
    ],
)
def test_forms_of_a_real_click_saves_as_another_value(
    typed: str, saved: str | None, instead: str
) -> None:
    real = MathReal(typed)
    assert not real.kept
    assert real.saved == saved
    assert real.instead == instead
    assert MathReal(instead).kept


def test_real_above_the_float32_range_names_the_largest_real() -> None:
    with pytest.raises(FieldError, match=r"is at most 3\.402823E\+38 in size \(OBJ-1009\)"):
        parse("DF1 + 3.4028235E+38", "decimal")


def test_tokens_of_one_stored_real_are_equal() -> None:
    assert parse("DF1 + 1.50", "decimal") == parse("DF1 + 1.5", "decimal")


def _sample() -> list[str]:
    texts = []
    for value in (1.5, 0.00012345, 0.000015, 1234.000001, 1e5, 12345.6789, 3.0e38, 1e-45, 0.0):
        for digits in range(8):
            for text in (f"{value:.{digits}f}", f"{value:.{digits}E}", f"{value:.{digits}e}"):
                texts += [text, f"-{text}", f"+{text}"]
    reals = {t for t in texts if "." in t or "e" in t.lower()}
    return sorted(t for t in reals if MathReal(t).in_range and MathReal(t).kept)


@pytest.mark.parametrize("typed", _sample())
def test_held_text_stores_the_same_real(typed: str) -> None:
    """Typed again, the text that a Math holds stores the same text, and a decode of that
    stored text holds it again."""
    real = MathReal(typed)
    again = MathReal(real.held)
    assert again.kept
    assert again.stored == real.stored
    assert float(real.stored) == real.value
    assert held_for(real.stored) == real.held


@pytest.mark.parametrize("typed", _sample())
def test_parse_writes_the_forms_of_math_real(typed: str) -> None:
    real = MathReal(typed)
    token = parse(f"DF1 * ( {typed} )", "decimal").tokens[-2]
    assert (token.text, token.internal, token.written) == (real.stored, real.internal, real.held)


@pytest.mark.parametrize("typed", _sample())
def test_math_with_a_real_decodes_as_itself(typed: str) -> None:
    math = Math(f"DF1 * ( {typed} )", "DF9")
    decoded = parse_af_blob(math.build_blob())
    assert decoded == math
    assert refusals(decoded) == ()
