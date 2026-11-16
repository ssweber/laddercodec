"""Every refusal of a Math, and of its formula, with its field, reason and CLICK id.

A Math collects its own fields' refusals.  Its formula gives one refusal for each word,
constant value, key of the other mode, bit and range it refuses, all on ``Math.expression``,
and stops at an error in the characters, a bracket, the parentheses or the order.
"""

from __future__ import annotations

from typing import Any

import pytest

from laddercodec import AddressError, FieldError, Math, Reason
from laddercodec.instructions import parse_af_blob
from laddercodec.instructions.math_formula import parse
from laddercodec.operands.address import display_form_only
from laddercodec.operands.unchecked import refusals

_EXPR, _MODE = "Math.expression", "Math.mode"
#: A sum of 69 addresses: 276 characters in CLICK's internal template.
_LONG = " + ".join(f"DS{n}" for n in range(1, 70))


def _refusals(build: Any) -> tuple[FieldError, ...]:
    with pytest.raises(FieldError) as caught:
        build()
    assert caught.value.errors[0] is caught.value
    return caught.value.errors


def _shape(errors: tuple[FieldError, ...]) -> list[tuple[str | None, str | None, str | None]]:
    return [(e.field, e.reason, e.click_id) for e in errors]


def _formula(expression: str, mode: str = "decimal") -> tuple[FieldError, ...]:
    result = "DH100" if mode == "hex" else "DS100"
    return _refusals(lambda: Math(expression, result, mode))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Math's own fields
# ---------------------------------------------------------------------------


def test_math_gives_every_refusal() -> None:
    """A result in a bank Math does not write, a refused formula and a bad flag: three."""
    errors = _refusals(lambda: Math("DS1 + DS0", "C1", oneshot=2))
    assert _shape(errors) == [
        ("Math.result", "bank", "OBJ-004"),
        (_EXPR, "address", None),
        ("Math.oneshot", "flag", None),
    ]
    assert isinstance(errors[0], AddressError)
    assert all(isinstance(e.obj, Math) for e in errors)


def test_math_mode_refused_skips_what_depends_on_it() -> None:
    """The result's banks and the formula's reading depend on the mode: neither is checked."""
    errors = _refusals(lambda: Math("DS0", "C1", mode="bogus", oneshot=2))  # type: ignore[arg-type]
    assert _shape(errors) == [("Math.mode", "choice", None), ("Math.oneshot", "flag", None)]
    assert str(errors[0]) == "Math.mode: 'bogus' is not 'decimal' or 'hex'"


def test_math_nickname_is_not_read_as_a_formula() -> None:
    (error,) = _refusals(lambda: Math("<Tank> + DS0", "DS1"))
    assert (error.field, error.reason, error.click_id) == (_EXPR, Reason.ADDRESS, None)
    assert "holds a <nickname>" in str(error)


def test_hex_result_in_sd_is_outside_the_range() -> None:
    """CLICK answers an SD, or a YD past YD8, as a hex result with OBJ-003; another bank is OBJ-004."""
    cases = (
        ("SD29", "bank", "OBJ-003"),
        ("SD31", "bank", "OBJ-003"),
        ("SD1000", "bank", "OBJ-003"),
        ("YD9", "address", "OBJ-003"),
        ("DS1", "bank", "OBJ-004"),
    )
    for result, reason, click_id in cases:
        (error,) = _refusals(lambda result=result: Math("DH1", result, "hex"))
        assert (error.field, error.reason, error.click_id) == ("Math.result", reason, click_id)
    assert str(_refusals(lambda: Math("DH1", "SD29", "hex"))[0]) == (
        "Math.result: 'SD29' is outside the range of a hex Math result (OBJ-003); "
        "it takes DH and YD"
    )
    assert str(_refusals(lambda: Math("DH1", "YD9", "hex"))[0]) == (
        "Math.result: 'YD9' is outside the range of a hex Math result (OBJ-003); "
        "it takes DH1-DH500, YD0, YD0u, YD1-YD8"
    )
    for result in ("YD0", "YD0u", "YD8"):
        Math("DH1", result, "hex")
    # The decimal result takes SD, and a bank it does not take keeps OBJ-004.
    Math("DS1", "SD29")
    (error,) = _refusals(lambda: Math("DS1", "DH1"))
    assert error.click_id == "OBJ-004"


def test_math_result_and_formula_both_reported() -> None:
    errors = _refusals(lambda: Math("DS1 + FOO", "DH1"))
    assert _shape(errors) == [("Math.result", "bank", "OBJ-004"), (_EXPR, "kind", "OBJ-1001")]


# ---------------------------------------------------------------------------
# The formula: every refusal it finds
# ---------------------------------------------------------------------------


def test_formula_gives_every_refusal() -> None:
    """Two words, a constant's value, a key of the other mode, two bits, a range, a median."""
    errors = _formula("DS0 + FFh * 007 + MAX ( C5 : C1 ) AND MDN ( DS1 : DS900 )")
    assert _shape(errors) == [
        (_EXPR, "address", None),
        (_EXPR, "kind", "OBJ-1001"),
        (_EXPR, "form", "OBJ-1009"),
        (_EXPR, "conflict", "OBJ-1006"),
        (_EXPR, "bank", "OBJ-1002"),
        (_EXPR, "bank", "OBJ-1002"),
        (_EXPR, "form", "OBJ-1014"),
        (_EXPR, "range", "OBJ-1013"),
    ]
    assert [str(e).split(": ", 1)[1].split(" ", 1)[0] for e in errors] == [
        "'DS0'",
        "FFh",
        "007",
        "AND",
        "C5",
        "C1",
        "C5",
        "MDN",
    ]
    assert errors[3].fields == (_EXPR, _MODE)


def test_formula_first_refusal_is_the_one_read_first() -> None:
    """Steps run in their order, so the first refusal is the one a stop at it would give."""
    (alone,) = _formula("DS0 + DS2")
    errors = _formula("DS0 + FFh + DS2 + C1")
    assert str(errors[0]) == str(alone)
    assert type(errors[0]) is type(alone)


def test_formula_parse_gives_every_refusal() -> None:
    with pytest.raises(FieldError) as caught:
        parse("DS0 + DS5000", "decimal")
    assert [str(e) for e in caught.value.errors] == [
        "Math.expression: 'DS0' is outside DS1-DS4500",
        "Math.expression: 'DS5000' is outside DS1-DS4500",
    ]


def test_formula_stops_at_the_parentheses() -> None:
    """The words before are kept; a constant's value and what follows are not read."""
    errors = _formula("DS0 + ( 007 + C1")
    assert _shape(errors) == [(_EXPR, "address", None), (_EXPR, "form", "OBJ-1005")]


def test_formula_stops_at_the_order() -> None:
    errors = _formula("DS0 + 007 DS2 + C1")
    assert _shape(errors) == [
        (_EXPR, "address", None),
        (_EXPR, "form", "OBJ-1009"),
        (_EXPR, "form", "OBJ-1001"),
    ]
    assert str(errors[2]) == (
        "Math.expression: 'DS2' after '007': two values need an operator between them (OBJ-1001)"
    )


def test_formula_word_of_no_kind_skips_the_order_and_operands() -> None:
    """FOO is no address, constant or name: neither the order nor the bits are checked."""
    errors = _formula("FOO + 007 C1 AND 2")
    assert _shape(errors) == [
        (_EXPR, "kind", "OBJ-1001"),
        (_EXPR, "form", "OBJ-1009"),
        (_EXPR, "conflict", "OBJ-1006"),
    ]


def test_formula_refused_word_reads_on_as_what_it_looks_like() -> None:
    """A refused constant joins its sign and fills RAND's argument; a refused address is an
    address to a range function."""
    assert _shape(_formula("RAND ( - FFh , 5 )")) == [(_EXPR, "kind", "OBJ-1001")]
    assert _shape(_formula("SUM ( DS0 : DS5 )")) == [(_EXPR, "address", None)]
    assert _shape(_formula("DH1 + 5 + LSH ( DH2 , 1 )", "hex")) == [
        (_EXPR, "kind", None),
        (_EXPR, "kind", None),
    ]


def test_formula_refused_address_is_not_checked_again() -> None:
    """DS0 is refused once, not again as the end of a range running high to low."""
    assert _shape(_formula("SUM ( DS5 : DS0 )")) == [(_EXPR, "address", None)]


def test_formula_sum_over_ct_is_refused_once() -> None:
    errors = _formula("SUM ( CT1 : CT5 ) + SUM ( CT7 : CT9 )")
    assert [str(e) for e in errors] == [
        "Math.expression: SUM over CT1 is refused; SUM takes no CT range",
        "Math.expression: SUM over CT7 is refused; SUM takes no CT range",
    ]


def test_formula_bit_range_outside_sum_has_no_member_refusal() -> None:
    errors = _formula("MAX ( X001 : X036 )")
    assert [str(e) for e in errors] == [
        "Math.expression: X001 is a bit; a bit stands only in SUM over a bit range (OBJ-1002)",
        "Math.expression: X036 is a bit; a bit stands only in SUM over a bit range (OBJ-1002)",
    ]


def test_formula_length_is_checked_only_without_a_refused_constant() -> None:
    (error,) = _formula(_LONG)
    assert (error.reason, error.click_id) == (Reason.RANGE, "OBJ-1008")
    # A refused constant has no internal form: the length is not counted.
    assert _shape(_formula(_LONG.replace("DS69", "FFh"))) == [(_EXPR, "kind", "OBJ-1001")]
    # A refused address is still an @ in the template, and a refused bit keeps every
    # token's form: the length is still counted.
    for refused, shape in [("DS0", ("address", None)), ("C1", ("bank", "OBJ-1002"))]:
        assert _shape(_formula(_LONG.replace("DS69", refused))) == [
            (_EXPR, *shape),
            (_EXPR, "range", "OBJ-1008"),
        ]
    # So is a name not in display form, read as its own text.
    with display_form_only():
        errors = _formula(_LONG.replace("DS69", "sum ( DS70 : DS71 )"))
    assert _shape(errors) == [(_EXPR, "form", None), (_EXPR, "range", "OBJ-1008")]


# ---------------------------------------------------------------------------
# A reason for every refusal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "mode", "reason", "click_id"),
    [
        # The characters, a bracket and the empty formula: the reading ends.
        ('DS1 + "A"', "decimal", "kind", None),
        ("DS1 + ~", "decimal", "form", None),
        ("DS[DS1]", "decimal", "pointer", None),
        ("", "decimal", "missing", None),
        # Words.
        ("DS1 + ٣", "decimal", "form", None),
        ("DS1 + 1Eh", "hex", "form", None),
        ("DS1 + 1.5x", "decimal", "kind", "OBJ-1001"),
        ("DS1 + FOO", "decimal", "kind", "OBJ-1001"),
        ("DS1 + DS0", "decimal", "address", None),
        ("DS1 + FFh", "decimal", "kind", "OBJ-1001"),
        ("DH1 + 12345h", "hex", "range", "OBJ-1009"),
        ("DH1 + 5", "hex", "kind", None),
        # Parentheses.
        ("( " * 9 + "DS1" + " )" * 9, "decimal", "range", "OBJ-1010"),
        ("DS1 )", "decimal", "form", "OBJ-1004"),
        ("( DS1", "decimal", "form", "OBJ-1005"),
        # A decimal constant's value.
        ("1E39", "decimal", "range", "OBJ-1009"),
        ("123456789012", "decimal", "range", "OBJ-1009"),
        ("000000000005", "decimal", "form", "OBJ-1009"),
        # Leading zeros are the form refused: 6000000000 alone is taken.
        ("06000000000", "decimal", "form", "OBJ-1009"),
        ("-03000000000", "decimal", "range", "OBJ-1009"),
        ("0" * 4301 + "1", "decimal", "form", "OBJ-1009"),
        ("-" + "0" * 5000 + "1", "decimal", "form", "OBJ-1009"),
        ("0" * 5000 + "12345678901", "decimal", "range", "OBJ-1009"),
        ("3000000000", "decimal", "range", "OBJ-1009"),
        ("007", "decimal", "form", "OBJ-1009"),
        # A key of the other mode.
        ("DS1 AND DS2", "decimal", "conflict", "OBJ-1006"),
        ("SIN ( DH1 )", "hex", "conflict", "OBJ-1006"),
        # The order.
        ("DS1 DS2", "decimal", "form", "OBJ-1001"),
        ("DS1 , DS2", "decimal", "form", "OBJ-037"),
        ("DS1 : DS2", "decimal", "form", None),
        ("RAND ( DS1 + DS2 , 5 )", "decimal", "form", "OBJ-1001"),
        ("SUM ( DS1 + DS2 )", "decimal", "form", None),
        ("SIN ( MAX ( DF1 : DF3 ) )", "decimal", "form", "OBJ-1001"),
        ("* DS1", "decimal", "form", "OBJ-1001"),
        ("DS1 +", "decimal", "form", "OBJ-1001"),
        # Bits and ranges.
        ("C1 + DS1", "decimal", "bank", "OBJ-1002"),
        ("SUM ( CT1 : CT5 )", "decimal", "bank", None),
        ("SUM ( DS1 : DD5 )", "decimal", "form", "OBJ-1015"),
        ("SUM ( DS5 : DS1 )", "decimal", "form", "OBJ-1014"),
        ("MDN ( DS1 : DS900 )", "decimal", "range", "OBJ-1013"),
        ("SUM ( X001 : X036 )", "decimal", "range", None),
        # The length.
        (_LONG, "decimal", "range", "OBJ-1008"),
    ],
)
def test_formula_reason(expression: str, mode: str, reason: str, click_id: str | None) -> None:
    (error,) = _formula(expression, mode)
    assert (error.field, error.reason, error.click_id) == (_EXPR, reason, click_id)
    assert isinstance(error.reason, Reason)
    assert str(error).endswith(f" ({click_id})") == (click_id is not None)
    expected = (_EXPR, _MODE) if reason == "conflict" else (_EXPR,)
    assert error.fields == expected


#: Constants of more than 4300 digits, which Python will not read as one number.
_LONG_DIGITS = [
    "DS1 + " + "0" * 4301 + "1",
    "DS1 + -" + "0" * 5000 + "1",
    "foo + " + "0" * 5000 + "1",
]


@pytest.mark.parametrize("expression", _LONG_DIGITS)
def test_formula_long_digit_run_is_refused(expression: str) -> None:
    errors = _refusals(lambda: Math(expression, "DS1"))
    assert all(e.field == _EXPR and isinstance(e.reason, Reason) for e in errors)
    assert any(e.click_id == "OBJ-1009" and e.reason == Reason.FORM for e in errors)


@pytest.mark.parametrize("expression", _LONG_DIGITS)
def test_formula_long_digit_run_keeps_its_refusal(expression: str) -> None:
    """A stored formula with such a constant decodes as that Math, keeping the refusals."""
    blob = Math("DS1 + 12345", "DS1").build_blob()
    assert parse_af_blob(blob) == Math("DS1 + 12345", "DS1")
    text = expression.removeprefix("DS1 + ")
    stored = blob.replace("12345".encode("utf-16-le"), text.encode("utf-16-le"))
    parsed = parse_af_blob(stored)
    assert isinstance(parsed, Math) and parsed.expression == f"DS1 + {text}"
    found = refusals(parsed)
    assert found and all(e.field == _EXPR for e in found)
    assert any(e.click_id == "OBJ-1009" for e in found)


@pytest.mark.parametrize("expression", ["sin ( DS1 )", "ds1 + 1", "DH1 + ffh"])
def test_formula_display_form_refusal(expression: str) -> None:
    mode = "hex" if "ffh" in expression else "decimal"
    with display_form_only():
        (error,) = _formula(expression, mode)
    assert (error.field, error.reason) == (_EXPR, Reason.FORM)


def test_formula_display_form_refusals_read_on() -> None:
    """A name or an address not in display form is refused, and read on as what it is."""
    with display_form_only():
        errors = _formula("sin ( ds1 ) + C1")
    assert _shape(errors) == [
        (_EXPR, "form", None),
        (_EXPR, "form", None),
        (_EXPR, "bank", "OBJ-1002"),
    ]
