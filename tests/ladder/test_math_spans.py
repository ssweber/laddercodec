"""Test where in a Math formula each refusal is, as ``FieldError.span`` states it.

``span`` is a half-open ``(start, end)`` pair of offsets into the formula as it was passed,
so ``formula[start:end]`` is the refused text. A blank formula, a formula that is too long,
a ``(`` with no ``)`` and a key that only the other mode takes have no span. Neither has a
refusal of any other field or of any other instruction.
"""

from __future__ import annotations

import pickle
from typing import Any

import pytest

from laddercodec import CompareContact, Copy, FieldError, Math, Search, replace
from laddercodec.codes import Code
from laddercodec.instructions import parse_af_blob
from laddercodec.instructions.math_formula import parse
from laddercodec.operands.address import display_form_only
from laddercodec.operands.unchecked import refusals

#: A sum of 69 addresses, over the length limit.
_LONG = " + ".join(f"DS{n}" for n in range(1, 70))


def _refusals(build: Any) -> tuple[FieldError, ...]:
    with pytest.raises(FieldError) as caught:
        build()
    assert caught.value.errors[0] is caught.value
    return caught.value.errors


def _formula(expression: str, mode: str = "decimal") -> tuple[FieldError, ...]:
    result = "DH100" if mode == "hex" else "DS100"
    return _refusals(lambda: Math(expression, result, mode))  # type: ignore[arg-type]


def _at_fault(expression: str, error: FieldError) -> str | None:
    """Return the text that ``error.span`` names in ``expression``, or None."""
    if error.span is None:
        return None
    start, end = error.span
    assert 0 <= start < end <= len(expression)
    return expression[start:end]


@pytest.mark.parametrize(
    ("expression", "mode", "code", "text"),
    [
        # A character that ends the reading: a text constant, a character of no token, and a
        # pointer's bracket.
        ('DS1 + "A"', "decimal", Code.MATH_CONSTANT_KIND, '"'),
        ("DS1 + $41", "decimal", Code.MATH_CONSTANT_KIND, "$"),
        ("DS1 + ~", "decimal", Code.MATH_INVALID_TOKEN, "~"),
        ("DS[DS1]", "decimal", Code.POINTER_OUTSIDE_COPY, "["),
        # Refused words.
        ("DS1 + ٣", "decimal", Code.MATH_INVALID_TOKEN, "٣"),
        ("DH1 + 1Eh", "hex", Code.MATH_INVALID_TOKEN, "1Eh"),
        ("DS1 + 1.5x", "decimal", Code.MATH_INVALID_TOKEN, "1.5x"),
        ("DS1 + FOO", "decimal", Code.MATH_INVALID_TOKEN, "FOO"),
        ("DS1 + DS0", "decimal", Code.ADDRESS_OUT_OF_RANGE, "DS0"),
        ("DS1 + FFh", "decimal", Code.MATH_CONSTANT_KIND, "FFh"),
        # A sign that the message does not name is not part of the span.
        ("DS1 * ( - FFh )", "decimal", Code.MATH_CONSTANT_KIND, "FFh"),
        ("DH1 + 12345h", "hex", Code.MATH_CONSTANT_OUT_OF_RANGE, "12345h"),
        ("DH1 + 5", "hex", Code.MATH_CONSTANT_KIND, "5"),
        ("DH1 + 1.5", "hex", Code.MATH_CONSTANT_KIND, "1.5"),
        # A sign that the hex refusal names is part of the span, with the space after it.
        ("-5 + DH1", "hex", Code.MATH_CONSTANT_KIND, "-5"),
        ("DH1 * ( - 5 )", "hex", Code.MATH_CONSTANT_KIND, "- 5"),
        ("DH1 * ( - 1.5 )", "hex", Code.MATH_CONSTANT_KIND, "- 1.5"),
        # The parentheses.
        ("( " * 9 + "DS1" + " )" * 9, "decimal", Code.MATH_NESTING_DEPTH, "("),
        ("DS1 )", "decimal", Code.MATH_UNBALANCED_PARENS, ")"),
        # A decimal constant's value. A sign that joins the constant is part of the span.
        ("DS1 + 1E39", "decimal", Code.MATH_CONSTANT_OUT_OF_RANGE, "1E39"),
        ("DS1 + 3000000000", "decimal", Code.MATH_CONSTANT_OUT_OF_RANGE, "3000000000"),
        ("DS1 + 007", "decimal", Code.MATH_CONSTANT_OUT_OF_RANGE, "007"),
        ("DS1 * ( - 007 )", "decimal", Code.MATH_CONSTANT_OUT_OF_RANGE, "- 007"),
        ("DS1 + 1.23456789", "decimal", Code.MATH_CONSTANT_OUT_OF_RANGE, "1.23456789"),
        # The order: two tokens that may not stand together span both. A refusal of one
        # token spans that token.
        ("DS1 DS2", "decimal", Code.MATH_SYNTAX_ERROR, "DS1 DS2"),
        ("DS1 + * DS2", "decimal", Code.MATH_SYNTAX_ERROR, "+ *"),
        ("DS1 + ( )", "decimal", Code.MATH_SYNTAX_ERROR, "( )"),
        ("DS1 , DS2", "decimal", Code.MATH_SYNTAX_ERROR, ","),
        ("DS1 : DS2", "decimal", Code.MATH_SYNTAX_ERROR, ":"),
        ("* DS1", "decimal", Code.MATH_SYNTAX_ERROR, "*"),
        ("DS1 +", "decimal", Code.MATH_SYNTAX_ERROR, "+"),
        # A call of the wrong form spans the call.
        (
            "DS1 + RAND ( DS1 + DS2 , 5 )",
            "decimal",
            Code.MATH_ARG_EXPRESSION,
            "RAND ( DS1 + DS2 , 5 )",
        ),
        ("SUM ( DS1 + DS2 ) * 2", "decimal", Code.MATH_ARG_EXPRESSION, "SUM ( DS1 + DS2 )"),
        ("DS1 + RAND", "decimal", Code.MATH_ARG_EXPRESSION, "RAND"),
        (
            "SIN ( MAX ( DF1 : DF3 ) , 2 ) + 1",
            "decimal",
            Code.MATH_SYNTAX_ERROR,
            "SIN ( MAX ( DF1 : DF3 ) , 2 )",
        ),
        # RAND bounds.
        ("RAND ( DF1 , 10 )", "decimal", Code.RANDOM_BOUND_TYPE, "DF1"),
        ("RAND ( 1 , 1.5 )", "decimal", Code.RANDOM_BOUND_TYPE, "1.5"),
        ("DS1 + RAND ( 1 , 1 )", "decimal", Code.RANDOM_EQUAL_BOUNDS, "RAND ( 1 , 1 )"),
        # Banks. SUM's refusal spans its range.
        ("DS1 + C1", "decimal", Code.MATH_OPERAND_BANK, "C1"),
        ("SUM ( CT1 : CT5 )", "decimal", Code.SUM_BANK_UNAVAILABLE, "CT1 : CT5"),
        ("SUM ( DH1 : DH5 )", "decimal", Code.SUM_BANK_UNAVAILABLE, "DH1 : DH5"),
        # Ranges span a : b.
        ("SUM ( DS1 : DD5 )", "decimal", Code.MATH_RANGE_MIXED_BANKS, "DS1 : DD5"),
        ("SUM ( DS5 : DS1 )", "decimal", Code.MATH_RANGE_NOT_ASCENDING, "DS5 : DS1"),
        ("MDN ( DS1 : DS900 )", "decimal", Code.MEDIAN_RANGE_TOO_LARGE, "DS1 : DS900"),
        ("SUM ( X001 : X036 )", "decimal", Code.SUM_OPTION_SLOT, "X001 : X036"),
        ("SUM ( Y021 : Y036 )", "decimal", Code.SUM_OPTION_SLOT, "Y021 : Y036"),
    ],
)
def test_span_names_the_text_at_fault(expression: str, mode: str, code: str, text: str) -> None:
    (error,) = _formula(expression, mode)
    assert error.code == code
    assert _at_fault(expression, error) == text


@pytest.mark.parametrize(
    ("expression", "mode", "code"),
    [
        ("", "decimal", Code.BLANK_FIELD),
        ("  \t ", "decimal", Code.BLANK_FIELD),
        (_LONG, "decimal", Code.MATH_FORMULA_TOO_LONG),
        ("( DS1 + 2", "decimal", Code.MATH_UNBALANCED_PARENS),
        ("DS1 AND DS2", "decimal", Code.MATH_FUNCTION_MODE),
        ("SIN ( DH1 )", "hex", Code.MATH_FUNCTION_MODE),
    ],
)
def test_no_span_where_no_one_stretch_is_at_fault(expression: str, mode: str, code: str) -> None:
    (error,) = _formula(expression, mode)
    assert error.code == code
    assert error.span is None


def test_no_span_for_a_formula_that_is_not_a_string() -> None:
    (error,) = _refusals(lambda: Math(5, "DS1"))  # type: ignore[arg-type]
    assert (error.field, error.code) == ("Math.expression", Code.MATH_INVALID_TOKEN)
    assert error.span is None


def test_two_identical_refusals_have_their_own_spans() -> None:
    """``DS0 + DS0`` raises two refusals with the same message. Their spans differ."""
    expression = "DS0 + DS0"
    first, second = _formula(expression)
    assert str(first) == str(second)
    assert (first.span, second.span) == ((0, 3), (6, 9))


def test_span_counts_spaces_tabs_and_lowercase_as_typed() -> None:
    """The offsets index into the text as passed, before it is trimmed or put in upper case."""
    expression = "  ds0 +\tds0 + Ds1"
    errors = _formula(expression)
    assert [_at_fault(expression, e) for e in errors] == ["ds0", "ds0"]
    assert [e.span for e in errors] == [(2, 5), (8, 11)]


def test_display_form_refusals_span_the_word() -> None:
    expression = "sin ( ds1 ) + ffh"
    with display_form_only():
        errors = _formula(expression, "hex")
    texts = [_at_fault(expression, e) for e in errors if e.code == Code.NOT_CLICK_FORM]
    assert texts == ["sin", "ds1", "ffh"]


def test_each_refusal_has_its_own_span() -> None:
    """The error raised is the first refusal, with that refusal's span."""
    expression = "FOO + DS0 + 007 + C1 + SUM ( DS5 : DS1 )"
    errors = _formula(expression)
    assert [_at_fault(expression, e) for e in errors] == [
        "FOO",
        "DS0",
        "007",
    ]
    expression = "DS0 + 007 + C1 + SUM ( DS5 : DS1 )"
    errors = _formula(expression)
    assert [_at_fault(expression, e) for e in errors] == [
        "DS0",
        "007",
        "DS5 : DS1",
        "C1",
    ]


def test_mode_refusals_have_no_span_among_spanned_ones() -> None:
    expression = "DS0 AND 007"
    errors = _formula(expression)
    assert [(e.code, e.span) for e in errors] == [
        (Code.ADDRESS_OUT_OF_RANGE, (0, 3)),
        (Code.MATH_CONSTANT_OUT_OF_RANGE, (8, 11)),
        (Code.MATH_FUNCTION_MODE, None),
    ]


def test_parse_sets_the_span() -> None:
    with pytest.raises(FieldError) as caught:
        parse(" DS1 + DS0", "decimal")
    assert caught.value.span == (7, 10)


def test_span_survives_pickle() -> None:
    (error,) = _formula("DS1 + DS0")
    assert pickle.loads(pickle.dumps(error)).span == (6, 9)


def test_state_with_no_span_reads_none() -> None:
    """An error whose state has no ``span``, as one pickled before FieldError had one,
    reads None."""
    (error,) = _formula("DS1 + DS0")
    del error.__dict__["span"]
    assert error.span is None
    restored = pickle.loads(pickle.dumps(error))
    assert "span" not in pickle.dumps(error).decode("latin-1")
    assert restored.span is None
    assert FieldError.__new__(FieldError).span is None


@pytest.mark.parametrize(
    ("expression", "text"),
    [
        ("<Tank> + DS0", "<Tank>"),
        ("  DS1 + <Tank Level>", "<Tank Level>"),
        ("DS1 + <A> + <B>", "<A>"),
    ],
)
def test_nickname_refusal_spans_the_nickname(expression: str, text: str) -> None:
    (error,) = _refusals(lambda: Math(expression, "DS1"))
    assert error.code == Code.MATH_NICKNAME
    assert _at_fault(expression, error) == text


@pytest.mark.parametrize(
    "build",
    [
        lambda: Math("DS1 + 2", "C1"),
        lambda: Copy(source="DS1", dest="C1"),
        lambda: CompareContact("==", "DS1", "DH1"),
        lambda: Search("DS0", "DS10", "5", "DS20", "C1", "=="),
    ],
    ids=["math-dest", "copy", "compare", "search"],
)
def test_other_fields_have_no_span(build: Any) -> None:
    errors = _refusals(build)
    assert all(e.span is None for e in errors)


def test_decoded_math_spans_its_expression_not_the_stored_text() -> None:
    """A decoded Math keeps each refusal's span. The span indexes into the Math's
    ``expression``, which reads the typed address ``ds001`` as ``DS1``. CLICK's stored
    display text keeps ``ds001``, so the same offsets name other text there.
    """
    blob = Math("DS1 + 12345", "DD1").build_blob()
    stored = blob.replace("DS1".encode("utf-16-le"), "ds001".encode("utf-16-le"))
    stored = stored.replace("12345".encode("utf-16-le"), "007".encode("utf-16-le"))
    assert "ds001 + 007".encode("utf-16-le") in stored
    parsed = parse_af_blob(stored)
    assert isinstance(parsed, Math) and parsed.expression == "DS1 + 007"
    (error,) = refusals(parsed)
    assert error.code == Code.MATH_CONSTANT_OUT_OF_RANGE
    assert error.span == (6, 9)
    assert parsed.expression[6:9] == "007"
    assert "ds001 + 007"[6:9] != "007"
    # A copy that changes no field keeps the refusal and its span.
    (copied,) = refusals(replace(parsed))
    assert copied is not error and copied.span == (6, 9)
