"""Test every refusal of a Math and of its formula, with its field, reason and CLICK id.

Building a Math raises one ``FieldError`` whose ``errors`` hold the refusals of all its
fields. The formula adds one refusal on ``Math.expression`` for each problem it finds: each
word it refuses, such as an unknown name or an address outside its bank, each constant's
value, each operator or function from the other mode's keypad, each address in a bank that
the mode does not accept, and each bad range. The reader stops at the first error in the
characters, a bracket, the parentheses or the order of the tokens.
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
#: A sum of 69 addresses. CLICK's internal template of it is 273 characters, over the limit
#: of 270.
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
    """A Math with three refused fields raises three refusals.

    The fields are a result in a bank that Math does not write, a refused formula and a
    oneshot that is not a flag.
    """
    errors = _refusals(lambda: Math("DS1 + DS0", "C1", oneshot=2))
    assert _shape(errors) == [
        ("Math.dest", "bank", "OBJ-004"),
        (_EXPR, "address", None),
        ("Math.oneshot", "flag", None),
    ]
    assert isinstance(errors[0], AddressError)
    assert all(isinstance(e.obj, Math) for e in errors)


def test_math_mode_refused_skips_what_depends_on_it() -> None:
    """A refused mode skips the checks of the result's bank and of the formula.

    Both checks depend on the mode. The other fields are still checked.
    """
    errors = _refusals(lambda: Math("DS0", "C1", mode="bogus", oneshot=2))  # type: ignore[arg-type]
    assert _shape(errors) == [("Math.mode", "choice", None), ("Math.oneshot", "flag", None)]
    assert str(errors[0]) == "Math.mode: 'bogus' is not 'decimal' or 'hex'"


def test_math_nickname_is_not_read_as_a_formula() -> None:
    (error,) = _refusals(lambda: Math("<Tank> + DS0", "DS1"))
    assert (error.field, error.reason, error.click_id) == (_EXPR, Reason.ADDRESS, None)
    assert "holds a <nickname>" in str(error)


def test_hex_result_in_sd_is_outside_the_range() -> None:
    """For a hex Math result, CLICK reports an SD register or a YD past YD8 with OBJ-003.

    It reports any other bank that a hex result does not accept with OBJ-004.
    """
    cases = (
        ("SD29", "bank", "OBJ-003"),
        ("SD31", "bank", "OBJ-003"),
        ("SD1000", "bank", "OBJ-003"),
        ("YD9", "address", "OBJ-003"),
        ("DS1", "bank", "OBJ-004"),
        # SD0 and SD1001 are outside the SD range, so they are not SD registers. They are
        # refused as a bank that the result does not accept.
        ("SD0", "bank", "OBJ-004"),
        ("SD1001", "bank", "OBJ-004"),
    )
    for result, reason, click_id in cases:
        (error,) = _refusals(lambda result=result: Math("DH1", result, "hex"))
        assert (error.field, error.reason, error.click_id) == ("Math.dest", reason, click_id)
    assert str(_refusals(lambda: Math("DH1", "SD29", "hex"))[0]) == (
        "Math.dest: 'SD29' is outside the range of a hex Math result (OBJ-003); it takes DH and YD"
    )
    assert str(_refusals(lambda: Math("DH1", "SD0", "hex"))[0]) == (
        "Math.dest: 'SD0' is not allowed; Math.dest takes DH, YD (OBJ-004)"
    )
    assert str(_refusals(lambda: Math("DH1", "YD9", "hex"))[0]) == (
        "Math.dest: 'YD9' is outside the range of a hex Math result (OBJ-003); "
        "it takes DH1-DH500, YD0, YD0u, YD1-YD8"
    )
    for result in ("YD0", "YD0u", "YD8"):
        Math("DH1", result, "hex")
    # A decimal result accepts SD. A bank that it does not accept is still refused with
    # OBJ-004.
    Math("DS1", "SD29")
    (error,) = _refusals(lambda: Math("DS1", "DH1"))
    assert error.click_id == "OBJ-004"


def test_math_result_and_formula_both_reported() -> None:
    errors = _refusals(lambda: Math("DS1 + FOO", "DH1"))
    assert _shape(errors) == [("Math.dest", "bank", "OBJ-004"), (_EXPR, "kind", "OBJ-1001")]


# ---------------------------------------------------------------------------
# The formula: every refusal it finds
# ---------------------------------------------------------------------------


def test_formula_gives_every_refusal() -> None:
    """A formula with eight problems raises eight refusals, in this order.

    They are two refused words (DS0 and FFh), a constant's value (007), the hex operator AND,
    a range that runs high to low, two bits (C5 and C1), and a median over more than 1024
    bytes.
    """
    errors = _formula("DS0 + FFh * 007 + MAX ( C5 : C1 ) AND MDN ( DS1 : DS900 )")
    assert _shape(errors) == [
        (_EXPR, "address", None),
        (_EXPR, "kind", "OBJ-1001"),
        (_EXPR, "form", "OBJ-1009"),
        (_EXPR, "conflict", "OBJ-1006"),
        (_EXPR, "form", "OBJ-1014"),
        (_EXPR, "bank", "OBJ-1002"),
        (_EXPR, "bank", "OBJ-1002"),
        (_EXPR, "range", "OBJ-1013"),
    ]
    assert [str(e).split(": ", 1)[1].split(" ", 1)[0] for e in errors] == [
        "'DS0'",
        "FFh",
        "007",
        "AND",
        "C5",
        "C5",
        "C1",
        "MDN",
    ]
    assert errors[3].fields == (_EXPR, _MODE)


def test_formula_first_refusal_is_the_one_read_first() -> None:
    """The first refusal is the error that the formula raises when that problem is its only one.

    The reader runs its steps in order, so the earliest problem gives the first refusal.
    """
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
    """Unbalanced parentheses end the reading.

    The refusals of words, which the reader finds first, are kept (DS0). The constant's
    value (007) and the bank of C1 are not checked.
    """
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
        "Math.expression: 'DS2' after '007': two values need an operator between them "
        "(OBJ-1001). Put an operator between them, such as DS1 + DS2."
    )


def test_formula_word_of_no_kind_skips_the_order_and_operands() -> None:
    """FOO is not an address, a constant or a function name.

    After such a word the reader does not check the order of the tokens or the bank of C1.
    It still checks the constant's value (007) and the keys of the other mode (AND).
    """
    errors = _formula("FOO + 007 C1 AND 2")
    assert _shape(errors) == [
        (_EXPR, "kind", "OBJ-1001"),
        (_EXPR, "form", "OBJ-1009"),
        (_EXPR, "conflict", "OBJ-1006"),
    ]


def test_formula_refused_word_reads_on_as_what_it_looks_like() -> None:
    """After the reader refuses a word, it reads on as if the word were what it looks like.

    A refused constant (FFh in a decimal Math) joins the sign before it and fills a RAND
    argument. A refused address (DS0) can still be one end of a SUM range. In a hex Math, the
    refused decimal constants 5 and 1 are still read as constants. Each case gives no other
    refusal.
    """
    assert _shape(_formula("RAND ( - FFh , 5 )")) == [(_EXPR, "kind", "OBJ-1001")]
    assert _shape(_formula("SUM ( DS0 : DS5 )")) == [(_EXPR, "address", None)]
    assert _shape(_formula("DH1 + 5 + LSH ( DH2 , 1 )", "hex")) == [
        (_EXPR, "kind", None),
        (_EXPR, "kind", None),
    ]


def test_formula_rand_refuses_each_bound_then_its_banks() -> None:
    """RAND's refusals of a real bound and of equal bounds come before a bound's bank.

    Each problem is one refusal. A bound that was refused when it was read (DS0) is not
    checked again, for equal bounds or for its bank.
    """
    assert _shape(_formula("RAND ( DF1 , DF1 )")) == [
        (_EXPR, "form", "OBJ-1001"),
        (_EXPR, "bank", "OBJ-1002"),
        (_EXPR, "bank", "OBJ-1002"),
    ]
    assert _shape(_formula("RAND ( 1.5 , 1.5 )")) == [
        (_EXPR, "kind", "OBJ-1001"),
        (_EXPR, "kind", "OBJ-1001"),
        (_EXPR, "form", "OBJ-1001"),
    ]
    assert _shape(_formula("RAND ( TD1 , 1.5 ) + RAND ( DS0 , DS0 )")) == [
        (_EXPR, "address", None),
        (_EXPR, "address", None),
        (_EXPR, "kind", "OBJ-1001"),
        (_EXPR, "bank", "OBJ-1002"),
    ]


def test_formula_refused_address_is_not_checked_again() -> None:
    """DS0 is refused once, not again as the end of a range running high to low."""
    assert _shape(_formula("SUM ( DS5 : DS0 )")) == [(_EXPR, "address", None)]


_DECIMAL_ONLY = (
    "a decimal Math takes only DS, DD, DF, TD, CTD and SD registers and decimal constants, "
    "and X, Y, C, T and SC bits only as the range of SUM ( a : b ) (OBJ-1002)"
)
_HEX_ONLY = "a hex Math takes only DH, XD and YD registers and hex constants (OBJ-1002)"


def test_formula_decimal_sum_over_a_refused_bank_is_refused_once() -> None:
    """One refusal for each SUM over a bank a decimal formula does not take, CT included."""
    errors = _formula(
        "SUM ( CT1 : CT5 ) + SUM ( CT7 : CT9 ) + SUM ( DH1 : DH3 ) + SUM ( XD0 : XD1 ) "
        "+ SUM ( YD0 : YD1 ) + SUM ( TXT1 : TXT2 )"
    )
    assert [str(e) for e in errors] == [
        f"Math.expression: SUM ( {low} : {high} ) is refused for {low}; {_DECIMAL_ONLY}"
        for low, high in (
            ("CT1", "CT5"),
            ("CT7", "CT9"),
            ("DH1", "DH3"),
            ("XD0", "XD1"),
            ("YD0", "YD1"),
            ("TXT1", "TXT2"),
        )
    ]
    assert {(e.reason, e.click_id) for e in errors} == {(Reason.BANK, "OBJ-1002")}


def test_formula_sum_refusal_names_the_refused_end() -> None:
    """A SUM over two banks is first refused for spanning them (OBJ-1015), as CLICK refuses it.

    The bank refusal that follows names the SUM and the end whose bank is refused (TXT2).
    """
    errors = _formula("SUM ( X001 : TXT2 )")
    assert [str(e) for e in errors] == [
        "Math.expression: X001 : TXT2 spans two banks; a range stays in one (OBJ-1015)",
        f"Math.expression: SUM ( X001 : TXT2 ) is refused for TXT2; {_DECIMAL_ONLY}",
    ]


@pytest.mark.parametrize(
    ("expression", "mode", "first"),
    [
        # CLICK reports the range's order or its two banks before a bank that the mode refuses.
        ("SUM ( DH2 : DH1 )", "decimal", "OBJ-1014"),
        ("SUM ( TXT2 : TXT1 )", "decimal", "OBJ-1014"),
        ("SUM ( DS2 : DS1 )", "hex", "OBJ-1014"),
        ("SUM ( X002 : X001 )", "hex", "OBJ-1014"),
        ("SUM ( CT1 : C2 )", "decimal", "OBJ-1015"),
        ("SUM ( DH1 : TXT2 )", "decimal", "OBJ-1015"),
        ("SUM ( YD0 : X002 )", "decimal", "OBJ-1015"),
    ],
)
def test_formula_range_shape_comes_before_its_bank(expression: str, mode: str, first: str) -> None:
    """A range is first refused for its order or for spanning two banks.

    Then the SUM is refused once for a bank that the mode does not accept, even when both
    of its ends are in such a bank.
    """
    errors = _formula(expression, mode)
    assert errors[0].click_id == first
    assert errors[0].reason == Reason.FORM
    assert [e.click_id for e in errors[1:]] == ["OBJ-1002"]


def test_formula_range_shapes_come_before_every_bank() -> None:
    """The refusals of every range's order and banks come first, then each address's bank,
    then a median's size.

    Here that is OBJ-1014 for the SUM, OBJ-1002 for DH1 and for the SUM, and OBJ-1013 for
    the median.
    """
    errors = _formula("DH1 + SUM ( DH5 : DH2 ) + MDN ( DS1 : DS900 )")
    assert [e.click_id for e in errors] == ["OBJ-1014", "OBJ-1002", "OBJ-1002", "OBJ-1013"]


@pytest.mark.parametrize("address", ["DH1", "XD0", "XD0u", "YD1", "TXT1", "C1", "X001", "CT1"])
def test_formula_decimal_refuses_each_bank_it_does_not_take(address: str) -> None:
    errors = _formula(f"DS1 + {address}")
    assert [str(e) for e in errors] == [f"Math.expression: {address} is refused; {_DECIMAL_ONLY}"]
    assert _shape(errors) == [(_EXPR, "bank", "OBJ-1002")]


def test_formula_decimal_takes_its_registers_and_bits_in_a_sum() -> None:
    Math(
        "DS1 + DD1 + DF1 + TD1 + CTD1 + SD1 + SUM ( X001 : X002 ) + SUM ( Y001 : Y002 ) "
        "+ SUM ( C1 : C2 ) + SUM ( T1 : T2 ) + SUM ( SC1 : SC2 ) + SUM ( SD1 : SD2 )",
        "DF100",
    )


def test_formula_hex_sum_over_a_refused_bank_is_refused_once() -> None:
    """One refusal for each SUM over a bank a hex formula does not take, CT and DS included."""
    errors = _formula(
        "SUM ( X001 : X036 ) + SUM ( CT1 : CT3 ) + SUM ( C1 : C2 ) + SUM ( DS1 : DS3 )", "hex"
    )
    assert [str(e) for e in errors] == [
        f"Math.expression: SUM ( X001 : X036 ) is refused for X001; {_HEX_ONLY}",
        f"Math.expression: SUM ( CT1 : CT3 ) is refused for CT1; {_HEX_ONLY}",
        f"Math.expression: SUM ( C1 : C2 ) is refused for C1; {_HEX_ONLY}",
        f"Math.expression: SUM ( DS1 : DS3 ) is refused for DS1; {_HEX_ONLY}",
    ]
    assert {(e.reason, e.click_id) for e in errors} == {(Reason.BANK, "OBJ-1002")}


def test_formula_hex_address_outside_sum_is_refused_each() -> None:
    """Each address a hex formula does not take, a bit or a register, is one refusal."""
    errors = _formula("DH1 + C1 + MAX ( X001 : X002 ) + MIN ( DD1 : DD3 ) + XD0 + YD1", "hex")
    assert [str(e) for e in errors] == [
        f"Math.expression: C1 is refused; {_HEX_ONLY}",
        f"Math.expression: X001 is refused; {_HEX_ONLY}",
        f"Math.expression: X002 is refused; {_HEX_ONLY}",
        f"Math.expression: DD1 is refused; {_HEX_ONLY}",
        f"Math.expression: DD3 is refused; {_HEX_ONLY}",
    ]


@pytest.mark.parametrize("bank", ["DS", "DD", "DF", "TD", "CTD", "SD", "TXT"])
def test_formula_hex_refuses_each_register_but_dh_xd_yd(bank: str) -> None:
    errors = _formula(f"DH1 + {bank}1", "hex")
    assert [str(e) for e in errors] == [f"Math.expression: {bank}1 is refused; {_HEX_ONLY}"]
    assert _shape(errors) == [(_EXPR, "bank", "OBJ-1002")]


def test_formula_hex_takes_dh_xd_and_yd() -> None:
    Math("SUM ( DH1 : DH3 ) + XD0u + MAX ( YD0 : YD2 ) + 1h", "DH100", "hex")


def test_formula_bit_range_outside_sum_has_no_option_slot_refusal() -> None:
    errors = _formula("MAX ( X001 : X036 )")
    assert [str(e) for e in errors] == [
        f"Math.expression: X001 is refused; {_DECIMAL_ONLY}",
        f"Math.expression: X036 is refused; {_DECIMAL_ONLY}",
    ]


def test_formula_length_is_checked_only_without_a_refused_constant() -> None:
    (error,) = _formula(_LONG)
    assert (error.reason, error.click_id) == (Reason.RANGE, "OBJ-1008")
    # A refused constant has no internal form, so the length is not counted.
    assert _shape(_formula(_LONG.replace("DS69", "FFh"))) == [(_EXPR, "kind", "OBJ-1001")]
    # The length is still counted after a refused address or bit. A refused address is still
    # an @ in the template, and a bit refused for its bank changes no token's internal form.
    for refused, shape in [("DS0", ("address", None)), ("C1", ("bank", "OBJ-1002"))]:
        assert _shape(_formula(_LONG.replace("DS69", refused))) == [
            (_EXPR, *shape),
            (_EXPR, "range", "OBJ-1008"),
        ]
    # It is also counted after a function name that is not in display form. The template
    # counts that name as its own text.
    with display_form_only():
        errors = _formula(_LONG.replace("DS69", "sum ( DS70 : DS71 )"))
    assert _shape(errors) == [(_EXPR, "form", None), (_EXPR, "range", "OBJ-1008")]


# ---------------------------------------------------------------------------
# A reason for every refusal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "mode", "reason", "click_id"),
    [
        # An error in the characters, a bracket or an empty formula ends the reading.
        ('DS1 + "A"', "decimal", "kind", None),
        ("DS1 + ~", "decimal", "form", None),
        ("DS[DS1]", "decimal", "pointer", None),
        ("", "decimal", "missing", None),
        # Refused words. Each is a word that is not a name, an address or a constant, an
        # address outside its bank's range, or a constant of the wrong mode or range.
        ("DS1 + ٣", "decimal", "form", None),
        ("DH1 + 1Eh", "hex", "form", None),
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
        ("3.4028235E+38", "decimal", "range", "OBJ-1009"),
        ("DS1 + 3.4028235E+38", "decimal", "range", "OBJ-1009"),
        ("-3.4028235E+38", "decimal", "range", "OBJ-1009"),
        ("123456789012", "decimal", "range", "OBJ-1009"),
        ("000000000005", "decimal", "form", "OBJ-1009"),
        # CLICK accepts 6000000000, so 06000000000 is refused for its leading zero.
        ("06000000000", "decimal", "form", "OBJ-1009"),
        ("-03000000000", "decimal", "range", "OBJ-1009"),
        ("0" * 4301 + "1", "decimal", "form", "OBJ-1009"),
        ("-" + "0" * 5000 + "1", "decimal", "form", "OBJ-1009"),
        ("0" * 5000 + "12345678901", "decimal", "range", "OBJ-1009"),
        ("3000000000", "decimal", "range", "OBJ-1009"),
        ("007", "decimal", "form", "OBJ-1009"),
        # An operator or function from the other mode's keypad.
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
        # Banks and ranges.
        ("C1 + DS1", "decimal", "bank", "OBJ-1002"),
        ("SUM ( CT1 : CT5 )", "decimal", "bank", "OBJ-1002"),
        ("DS1 + DH1", "decimal", "bank", "OBJ-1002"),
        ("SUM ( DS1 : DD5 )", "decimal", "form", "OBJ-1015"),
        ("SUM ( DS5 : DS1 )", "decimal", "form", "OBJ-1014"),
        ("MDN ( DS1 : DS900 )", "decimal", "range", "OBJ-1013"),
        ("SUM ( X001 : X036 )", "decimal", "range", None),
        # A RAND bound in a refused bank, a real bound, and equal bounds.
        ("RAND ( DF1 , 10 )", "decimal", "bank", "OBJ-1002"),
        ("RAND ( XD0 , Ah )", "hex", "bank", "OBJ-1002"),
        ("RAND ( 1.5 , 10 )", "decimal", "kind", "OBJ-1001"),
        ("RAND ( 1 , 1 )", "decimal", "form", "OBJ-1001"),
        ("RAND ( DH1 , DH1 )", "hex", "form", "OBJ-1001"),
        # The length.
        (_LONG, "decimal", "range", "OBJ-1008"),
    ],
)
def test_formula_reason(expression: str, mode: str, reason: str, click_id: str | None) -> None:
    (error,) = _formula(expression, mode)
    assert (error.field, error.reason, error.click_id) == (_EXPR, reason, click_id)
    assert isinstance(error.reason, Reason)
    # CLICK's id ends the rule sentence. A suggestion may follow it.
    _, marker, after = str(error).partition(f" ({click_id})")
    ends_rule = bool(marker) and (after == "" or after.startswith(". "))
    assert ends_rule == (click_id is not None)
    expected = (_EXPR, _MODE) if reason == "conflict" else (_EXPR,)
    assert error.fields == expected


#: Constants of more than 4300 digits. Python's int() refuses to read a number that long.
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
    """A Math blob whose formula holds such a constant decodes as that Math.

    The Math keeps its refusals, and one of them is OBJ-1009.
    """
    blob = Math("DS1 + 12345", "DS1").build_blob()
    assert parse_af_blob(blob) == Math("DS1 + 12345", "DS1")
    text = expression.removeprefix("DS1 + ")
    stored = blob.replace("12345".encode("utf-16-le"), text.encode("utf-16-le"))
    parsed = parse_af_blob(stored)
    assert isinstance(parsed, Math) and parsed.expression == f"DS1 + {text}"
    found = refusals(parsed)
    assert found and all(e.field == _EXPR for e in found)
    assert any(e.click_id == "OBJ-1009" for e in found)


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        # CLICK accepts 6000000000, so the message names the leading zero, not the range.
        ("06000000000", "06000000000 is refused; an integer constant has no leading zeros"),
        (
            "3000000000",
            "3000000000 is outside -2147483648..2147483647; an integer constant is 32-bit",
        ),
    ],
)
def test_integer_constant_message_says_what_is_refused(expression: str, message: str) -> None:
    (error,) = _formula(expression)
    assert str(error) == f"{_EXPR}: {message} (OBJ-1009)"


@pytest.mark.parametrize("expression", ["sin ( DS1 )", "ds1 + 1", "DH1 + ffh"])
def test_formula_display_form_refusal(expression: str) -> None:
    mode = "hex" if "ffh" in expression else "decimal"
    with display_form_only():
        (error,) = _formula(expression, mode)
    assert (error.field, error.reason) == (_EXPR, Reason.FORM)
    # The field leads the message, as in every refusal.
    assert str(error).startswith(f"{_EXPR}: ")
    assert "is not CLICK's display form" in str(error)


def test_formula_display_form_refusals_read_on() -> None:
    """A function name or an address that is not in CLICK's display form is refused.

    The reader still reads it as that function or address and goes on, so it also refuses
    the bank of C1.
    """
    with display_form_only():
        errors = _formula("sin ( ds1 ) + C1")
    assert _shape(errors) == [
        (_EXPR, "form", None),
        (_EXPR, "form", None),
        (_EXPR, "bank", "OBJ-1002"),
    ]
