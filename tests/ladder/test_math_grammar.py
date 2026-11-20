"""Test the Math formula reader against CLICK's Math grammar, with one test per rule.

The rules are the steps of the check that CLICK's Math dialog runs, as "Math formula grammar"
in ``docs/internals/instruction-blobs.md`` lists them. The expected results come from what the
dialog accepted and refused, and from captures of what CLICK saved.

``math_unary_plus_pi.bin`` is ``fixtures/v4_captures/math_unary_plus_pi.bin``. It holds two
formulas typed in CLICK v4. After them it holds one rung for each formula that the dialog
refused, with a comment that names the formula.
"""

from __future__ import annotations

import gzip
import importlib
import re
import struct
from pathlib import Path

import pytest

from laddercodec import AddressError, FieldError, RefusedFieldWarning, decode, decode_program
from laddercodec.binary_helpers import (
    _parse_tagged_fields_verbose,
    _tagged_field,
    _utf16le_null,
    tag_flag,
)
from laddercodec.instructions import parse_af_blob
from laddercodec.instructions.math import Math, _reconstruct_expression
from laddercodec.instructions.math_formula import parse
from laddercodec.instructions.raw import RawInstruction
from laddercodec.operands.unchecked import refusals
from tests.kept_refusals import kept
from tests.test_v4_captures import REFUSED_XY_RANGES, xy_range_message

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _refused(expression: str, mode: str, message: str) -> None:
    with pytest.raises(FieldError, match=message):
        Math(expression, "DH9" if mode == "hex" else "DF9", mode)  # type: ignore[arg-type]


def _views(expression: str, mode: str) -> tuple[str, str, str, str]:
    formula = parse(expression, mode)
    return formula.display, formula.template, formula.internal(template=True), formula.internal()


# ---------------------------------------------------------------------------
# Formula predictions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("constant", ["1Eh", "0Eh", "2E5Ah"])
def test_hex_constant_with_digits_then_e_is_refused(constant: str) -> None:
    _refused(f"DH1 + {constant}", "hex", f"{constant} is refused; CLICK reads the digits before E")


@pytest.mark.parametrize(
    ("typed", "display", "value"),
    [
        ("1E3h", "1E3h", 0x1E3),
        ("1e3H", "1E3h", 0x1E3),
        ("01E3h", "1E3h", 0x1E3),
        ("2E5h", "2E5h", 0x2E5),
    ],
)
def test_hex_constant_click_stores_with_digits_e_digits_is_read(
    typed: str, display: str, value: int
) -> None:
    # A hex Math stores a constant typed 1e3 (no h) as 1E3h, UH483. CLICK's tokenizer rule
    # would split 1E3h into the real number 1E3 and a lone h. laddercodec reads a word split
    # before a lone h as hex, so these constants read as hex.
    assert _views(f"DH1 + {typed}", "hex") == (
        f"DH1 + {display}",
        f"@ + {display}",
        f"@#+#UH{value}",
        f"DH1#+#UH{value}",
    )
    _refused(f"DS1 + {typed}", "decimal", f"{display} is a hex constant; a decimal Math")


def test_sign_after_an_operator_is_refused_and_accepted_in_parentheses() -> None:
    _refused("DS1 * -5", "decimal", "'-' after '\\*': a sign right after an operator")
    assert _views("DS1 * ( -5 )", "decimal") == (
        "DS1 * ( -5 )",
        "@ * ( -5 )",
        "@#*#(#H-5#)",
        "DS1#*#(#H-5#)",
    )


def test_hex_sign_after_an_operator_is_refused() -> None:
    _refused("DH1 + -Ah", "hex", "'-' after '\\+': a sign right after an operator")


def test_shift_takes_an_address_first() -> None:
    _refused("LSH ( 1h , 2h )", "hex", "LSH takes LSH \\( a , b \\): a is an address")
    assert parse("LSH ( DH1 , DH2 )", "hex").internal() == "DH1#LSH#DH2#"


def test_trig_body_holds_a_colon_only_in_a_sum() -> None:
    _refused("SIN ( MAX ( DF1 : DF3 ) )", "decimal", "SIN \\( ... \\) holds a ',' or ':'")
    assert parse("SIN ( SUM ( DF1 : DF3 ) )", "decimal").internal() == "SIN#(#SUM#(#DF1#:#DF3#)#)"


def test_hex_bare_digits_stay_refused() -> None:
    # In a hex Math, CLICK rewrites DH1 + 7 as DH1 + 7h, and 7H7 as 77h. laddercodec refuses
    # both instead of changing what the CSV says. For 7 and 1e3 the message names the h form.
    _refused("DH1 + 7", "hex", "7 has no h; a hex Math takes hex constants, .* write 7h")
    _refused("DH1 + 1e3", "hex", "1e3 has no h; .* reads it as 1E3h: write 1E3h")
    _refused("DH1 + 7H7", "hex", "'7H7' is not an address")


@pytest.mark.parametrize(
    ("expression", "fix", "fixed"),
    [
        ("DH1 + 7", "7h", "DH1 + 7h"),
        ("DH1 + 005", "5h", "DH1 + 5h"),
        ("FF", "FFh", "FFh"),
        ("abc", "ABCh", "ABCh"),
        ("( -5 )", "-5h", "( -5h )"),
        ("-5", "-5h", "-5h"),
        ("RAND ( 5 , Ah )", "5h", "RAND ( 5h , Ah )"),
        ("LSH ( DH1 , 1 )", "1h", "LSH ( DH1 , 1h )"),
    ],
)
def test_hex_no_h_message_names_a_fix_that_is_taken(expression: str, fix: str, fixed: str) -> None:
    with pytest.raises(FieldError) as caught:
        parse(expression, "hex")
    (error,) = caught.value.errors
    assert error.click_id is None
    assert str(error).endswith(f": write {fix}")
    parse(fixed, "hex")


@pytest.mark.parametrize(
    ("expression", "with_h"),
    [
        ("RAND ( -5 , Ah )", "RAND ( -5h , Ah )"),
        ("RAND ( Ah , -5 )", "RAND ( Ah , -5h )"),
        ("LSH ( DH1 , -1 )", "LSH ( DH1 , -1h )"),
    ],
)
def test_hex_no_h_message_names_no_fix_where_the_h_form_is_refused(
    expression: str, with_h: str
) -> None:
    # RAND and the shifts refuse a signed argument even with its h (OBJ-1001), so the
    # message names no fix.
    with pytest.raises(FieldError) as caught:
        parse(expression, "hex")
    first = str(caught.value.errors[0])
    assert "has no h; a hex Math takes hex constants such as 7h" in first
    assert "write" not in first
    with pytest.raises(FieldError, match="OBJ-1001"):
        parse(with_h, "hex")


@pytest.mark.parametrize("word", ["00005", "000FF", "0FFFE"])
def test_hex_five_typed_digits_name_no_h_form(word: str) -> None:
    # CLICK counts the digits as typed and refuses five (OBJ-1009), so the message names no
    # h form.
    with pytest.raises(FieldError) as caught:
        parse(f"DH1 + {word}", "hex")
    assert "has no h" not in str(caught.value)


# ---------------------------------------------------------------------------
# Tokenizer (§1.1 step 1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "display"),
    [
        ("DS1+DS2*DS3", "DS1 + DS2 * DS3"),  # splits on + - * / ^
        ("SUM(DS1:DS3)", "SUM ( DS1 : DS3 )"),  # and on ( ) , :
        ("DS1\t+   DS2", "DS1 + DS2"),  # a run of spaces or tabs is one gap
        ("DF1*1.5E+10", "DF1 * 1.5E+10"),  # a real number keeps its exponent sign
        ("DF1+.5", "DF1 + 0.5"),  # a real is written as CLICK prints its value
        ("DF1+1.", "DF1 + 1.0"),
    ],
)
def test_tokenizer_splits_as_clicks(typed: str, display: str) -> None:
    assert parse(typed, "decimal").display == display


@pytest.mark.parametrize("word", ["1.5x", "1.2.3", "2E5DS", "1EMOD"])
def test_word_the_number_rule_cuts_is_refused(word: str) -> None:
    # CLICK's tokenizer ends a number token at the end of the longest real number that a run
    # of digits starts. A word that goes on past that point would be two tokens side by side.
    _refused(f"DF1 + {word}", "decimal", "is not an address, a function name or a constant")


@pytest.mark.parametrize("char", ["=", "#", "@", ";", "!", "&", "<", "\n", "\xa0", "\u2003"])
def test_character_outside_a_formula_is_refused(char: str) -> None:
    # Only a space or a tab separates tokens. Other white space is refused.
    _refused(f"DS1 +{char}DS2", "decimal", "is no part of a Math formula")


def test_pointer_is_refused() -> None:
    # CLICK accepts a pointer in Math. Nobody has read the step of CLICK's check that
    # handles a pointer, and laddercodec refuses one.
    _refused("DS[DS1] + 1", "decimal", "'\\[' is part of a pointer")


# ---------------------------------------------------------------------------
# Classification and constants (§1.1 steps 2, 6, 7)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expression", ["DS1 + FOO", "DS1 + NAN", "DS1 + 0x1A", "DS1 + .", "DS1 . DS2"]
)
def test_word_is_refused(expression: str) -> None:
    # CLICK's dialog refuses FOO. CLICK's number converter (strtod) accepts NAN and the hex
    # real 0x1A, but laddercodec refuses them. For a lone '.', a rung in
    # math_unary_plus_pi.bin records that CLICK refused DS1 + .
    _refused(expression, "decimal", "is not an address, a function name or a constant")


@pytest.mark.parametrize(
    ("constant", "internal"),
    [
        ("32767", "H32767"),
        ("-32768", "H-32768"),
        ("40000", "W40000"),
        ("6000000000", "W6000000000"),
    ],
)
def test_decimal_integer_is_h_or_w_by_int16(constant: str, internal: str) -> None:
    # An integer inside the int16 range gets H, and one outside it gets W.
    assert parse(f"( {constant} )", "decimal").internal() == f"(#{internal}#)"


@pytest.mark.parametrize("constant", ["007", "00", "3000000000", "000000000001", "9" * 5000])
def test_decimal_integer_must_print_back_at_its_length(constant: str) -> None:
    # CLICK reads the integer with _wtoi64, keeps the low 32 bits and prints them with %d.
    # It refuses the integer unless the print has the typed length. %d prints at most 11
    # characters.
    _refused(f"DS1 + {constant}", "decimal", f"{constant[:20]}")


def test_real_is_f_and_fits_float32() -> None:
    assert parse("DF1 * 1.5e5", "decimal").internal() == "DF1#*#F150000.0"
    _refused("DF1 * 1E39", "decimal", "1E39 is outside the float32 range")


@pytest.mark.parametrize(
    "constant",
    [
        # CLICK refuses this one, though float32 rounds it to its largest value.
        "3.4028235E+38",
        # Nobody has tried these in CLICK. laddercodec refuses them because, as typed, they
        # are above float32's largest value in size.
        "3.40282347E+38",
        "-3.4028235E+38",
    ],
)
def test_real_above_the_largest_float32_is_refused(constant: str) -> None:
    _refused(
        f"DF1 * ( {constant} )",
        "decimal",
        re.escape(
            f"{constant} is outside the float32 range; a real constant in Math is at most "
            "3.402823E+38 in size (OBJ-1009)"
        ),
    )


@pytest.mark.parametrize("constant", ["3.40282E+38", "-3.40282E+38", "1E-50"])
def test_real_up_to_the_largest_float32_is_taken(constant: str) -> None:
    # The largest real of 6 significant digits, its negative, and a small real.
    assert parse(f"DF1 * ( {constant} )", "decimal").internal() == f"DF1#*#(#F{constant}#)"


@pytest.mark.parametrize(
    ("constant", "saved"),
    [
        # CLICK saves 0.33333334 typed in a formula as 0.333333, and 0.000012345678 as
        # 1.234568E-05.
        ("0.33333334", "0.333333"),
        ("0.000012345678", "1.234568E-05"),
        ("0.123456789", "0.123457"),
        ("-0.33333334", "-0.333333"),
        ("1.0000005", "1.000001"),
        ("3.402823466E+38", "3.402823E+38"),
        ("3.4028234663852886E+38", "3.402823E+38"),
        ("1.23456789E-20", "1.234568E-20"),
    ],
)
def test_real_that_click_saves_as_another_value_is_refused(constant: str, saved: str) -> None:
    _refused(
        f"DF1 * ( {constant} )",
        "decimal",
        re.escape(
            f"{constant} has more digits than CLICK keeps in Math; CLICK saves it as {saved}: "
            f"write {saved}"
        ),
    )


@pytest.mark.parametrize(
    ("constant", "saved", "write"),
    [
        # Typed without an E, a real keeps 6 digits after the point. CLICK saves 0.00012345
        # as 0.000123, and 12345678.9 as 1.234568E+07. Typed with an E, 0.00012345 keeps its
        # value, so the refusal names that form.
        ("0.00012345", "0.000123", "1.2345E-04"),
        ("0.0001234567", "0.000123", "1.234567E-04"),
        ("12345678.9", "1.234568E+07", "1.234568E+07"),
        ("16777216.0", "1.677722E+07", "1.677722E+07"),
        ("123456789.0", "1.234568E+08", "1.234568E+08"),
        # Typed with an E, a real keeps 7 significant digits. CLICK saves 1.2345678E+15 as
        # 1.234568E+15. 1.23456789E-04 is saved as 0.0001234568, which a real typed without
        # an E can't hold, so the refusal names the exponent form.
        ("1.2345678E+15", "1.234568E+15", "1.234568E+15"),
        ("1.2345678E+37", "1.234568E+37", "1.234568E+37"),
        ("3.4028234E+38", "3.402823E+38", "3.402823E+38"),
        ("1.23456789E-04", "0.0001234568", "1.234568E-04"),
    ],
)
def test_real_saved_as_another_value_depends_on_how_it_is_typed(
    constant: str, saved: str, write: str
) -> None:
    _refused(
        f"DF1 * ( {constant} )",
        "decimal",
        re.escape(
            f"{constant} has more digits than CLICK keeps in Math; CLICK saves it as {saved}: "
            f"write {write}"
        ),
    )
    Math(f"DF1 * ( {write} )", "DF9")


@pytest.mark.parametrize(
    ("constant", "write"),
    [
        ("1.2345e-04", "1.2345E-04"),
        ("1.23456789e2", "123.456789"),
        ("1.2345678e15", "1.234568E+15"),
    ],
)
def test_real_typed_with_a_lowercase_e_is_taken_when_both_forms_keep_it(
    constant: str, write: str
) -> None:
    """CLICK's form for a real typed with a lowercase e is not known, so a Math refuses one
    that either form would change."""
    _refused(
        f"DF1 * ( {constant} )",
        "decimal",
        re.escape(f"{constant} may have more digits than CLICK keeps in Math. Write {write}."),
    )
    Math(f"DF1 * ( {write} )", "DF9")
    Math("DF1 * ( 1.5e-3 )", "DF9")


@pytest.mark.parametrize(
    "constant",
    [
        # CLICK saves 1234567.0 as 1234567, 3.0E+38 as 3E+38 and 1.2345E-04 as 0.00012345:
        # the same values.
        "1234567.0",
        "3.0E+38",
        "1.2345E-04",
        "1E+07",
        "3.402821E+38",
        "-3.402823E+38",
        "1.50000000",
        "123456.0",
        "1.234567",
        "1234567.89",
        "0.000123",
        "1.5E+10",
        "1.234567E+10",
        "3.402823E+38",
        "1E-45",
    ],
)
def test_real_that_click_keeps_is_taken(constant: str) -> None:
    Math(f"DF1 * ( {constant} )", "DF9")


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        # CLICK stores a real as it prints the value, in the display and internal forms.
        ("1.50", "1.5"),
        ("1e3", "1000.0"),
        (".5", "0.5"),
        ("1.5E+10", "1.5E+10"),
        # A typed sign stays with the real. CLICK stores DS1 + ( +2.5 ) with F+2.5.
        ("( +2.50 )", "( +2.5 )"),
        # CLICK saves 3.0E+38 as 3E+38 and 0.000012345678 as 1.234568E-05: exponent form
        # with trailing zeros cut. A real typed with a lowercase e is written the same way:
        # both rules that may apply to it give that text.
        ("( -1.5e10 )", "( -1.5E+10 )"),
        ("1.0E-10", "1E-10"),
        ("0.000015", "1.5E-05"),
        ("20000000.0", "2E+07"),
        ("( -0.000015 )", "( -1.5E-05 )"),
        # CLICK keeps 6 digits after the point of a real typed without an E, though it has
        # more than 7 significant digits.
        ("1234.000001", "1234.000001"),
        ("4194304.1", "4194304.1"),
        ("8388608.4", "8388608.4"),
    ],
)
def test_real_is_written_as_click_prints_it(typed: str, stored: str) -> None:
    formula = parse(f"DS2 + {typed}", "decimal")
    assert formula.display == f"DS2 + {stored}"
    constant = stored.strip("( )")
    assert formula.internal() == "DS2#+#" + stored.replace(constant, f"F{constant}").replace(
        " ", "#"
    )


def test_hex_constant_is_written_as_click_shows_it() -> None:
    # CLICK prints the value with %Xh.
    assert _views("DH1 + 0fH", "hex") == ("DH1 + Fh", "@ + Fh", "@#+#UH15", "DH1#+#UH15")
    _refused("DH1 + 0FFFEh", "hex", "0FFFEh is outside 0h..FFFFh")  # at most 4 digits as typed


def test_each_mode_takes_its_own_constants() -> None:
    _refused("DS1 + 1Fh", "decimal", "1Fh is a hex constant")
    _refused("DH1 + 1.5", "hex", "1.5 is a decimal constant")


# ---------------------------------------------------------------------------
# Parentheses (step 3), signs (step 5), mode keys (step 8)
# ---------------------------------------------------------------------------


def test_parentheses_balance_and_nest_eight_deep() -> None:
    _refused("( DS1", "decimal", "has a '\\(' with no '\\)'")
    _refused("DS1 )", "decimal", "has a '\\)' with no '\\('")
    _refused("( " * 9 + "DS1" + " )" * 9, "decimal", "nests parentheses 9 deep")


@pytest.mark.parametrize(
    ("typed", "internal"),
    [
        ("- 5 + DS1", "H-5#+#DS1"),  # at the start
        ("DS1 + ( - 5 )", "DS1#+#(#H-5#)"),  # after (
        ("RAND ( 1 , - 5 )", "H1#RAND#H-5#"),  # after ,
        ("- DS1", "-#DS1"),  # a sign on an address stays a token
        ("+5 + DS1", "H+5#+#DS1"),  # '+' joins as '-' does, keeping the typed text
        ("RAND ( 1 , +5 )", "H1#RAND#H+5#"),
        ("DF1 * ( +2.5 )", "DF1#*#(#F+2.5#)"),  # a real is F and the typed text
        ("( +0 )", "(#H+0#)"),
        ("+ DS1", "+#DS1"),
    ],
)
def test_decimal_sign_joins_its_constant(typed: str, internal: str) -> None:
    assert parse(typed, "decimal").internal() == internal


def test_plus_sign_joins_its_constant() -> None:
    # In math_unary_plus_pi.bin, CLICK stored a typed DS1 + ( +5 ) as these four strings.
    assert _views("DS1 + ( +5 )", "decimal") == (
        "DS1 + ( +5 )",
        "@ + ( +5 )",
        "@#+#(#H+5#)",
        "DS1#+#(#H+5#)",
    )
    assert _views("DS1 + ( + 5 )", "decimal")[0] == "DS1 + ( +5 )"


def test_plus_sign_keeps_the_length_rule() -> None:
    # CLICK prints '+' and then the value with %d, so +007 prints back as +7 and is refused.
    _refused("( +007 )", "decimal", "\\+007 is refused; CLICK reads it back as \\+7")


def test_hex_sign_stays_a_token() -> None:
    # CLICK stores ( -Ah ) typed in a hex Math as (#-#UH10#).
    assert parse("DH1 + ( -Ah )", "hex").internal() == "DH1#+#(#-#UH10#)"


def test_hex_plus_sign_stays_a_token() -> None:
    # In a hex Math no sign joins its constant (step 5 of CLICK's check). math_hex_signed.bin
    # shows this for '-'.
    assert _views("DH1 + ( +Ah )", "hex") == (
        "DH1 + ( + Ah )",
        "@ + ( + Ah )",
        "@#+#(#+#UH10#)",
        "DH1#+#(#+#UH10#)",
    )


def test_keys_of_the_other_keypad_are_refused() -> None:
    _refused("SIN ( DH1 )", "hex", "SIN is decimal only")
    _refused("DS1 XOR DS2", "decimal", "XOR is hex only")


# ---------------------------------------------------------------------------
# The follow-set table (step 9, §2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        # '(' may not be followed by ',', ':', ')' or an operator other than a sign
        ("( * DS1 )", "'\\*' after '\\(': it needs a value before it"),
        ("( )", "the parentheses hold nothing"),
        ("( : DS3 )", "':' after '\\('"),
        # ')' may not be followed by '(' or a value
        ("( DS1 ) ( DS2 )", "'\\(' after '\\)'"),
        ("( DS1 ) DS2", "'DS2' after '\\)'"),
        ("( DS1 ) SIN ( DS2 )", "'SIN' after '\\)'"),
        ("RAND ( 1 , 10 ) DS1", "'DS1' after '\\)'"),  # refused in math_unary_plus_pi.bin
        # an operator may not be followed by ')', an operator, ',' or ':'
        ("( DS1 + )", "'\\)' after '\\+'"),
        ("DS1 + * DS2", "'\\*' after '\\+'"),
        ("DS1 - -5", "'-' after '-'"),
        # a constant or an address may not be followed by '(' or a value
        ("DS1 DS2", "'DS2' after 'DS1'"),
        ("5 ( DS1 )", "'\\(' after '5'"),
        ("2 PI", "'PI' after '2'"),
        ("DS1 SQRT ( DS2 )", "'SQRT' after 'DS1'"),
        ("DS1 RAND ( 1 , 2 )", "'RAND' after 'DS1'"),
        # PI may not be followed by a value, ',' or ':'
        ("PI DS1", "'DS1' after 'PI'"),
        ("RAND ( PI , 10 )", "RAND takes RAND"),
        # ',' and ':' may not be followed by ')' or an operator
        ("( DS1 , )", "'\\)' after ','"),
        ("( DS1 : * DS2 )", "'\\*' after ':'"),
        # a trig function takes '(' next
        ("SIN DF1", "SIN takes its argument in parentheses"),
    ],
)
def test_follow_set(expression: str, message: str) -> None:
    _refused(expression, "decimal", message)


def test_shift_may_not_follow_a_comma() -> None:
    _refused("( DH1 , LSH ( DH2 , 1h ) )", "hex", "LSH may not stand right after")


def test_shift_may_not_follow_a_value() -> None:
    # A rung in math_unary_plus_pi.bin records that CLICK refused DS1 LSH 1h.
    _refused("DS1 LSH 1h", "hex", "'LSH' after 'DS1'")


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("* DS1", "starts with '\\*'"),
        ("MOD DS1", "starts with 'MOD'"),
        ("/ DS1", "starts with '/'"),
        ("DS1 +", "ends with '\\+'"),
        ("-", "ends with '-'"),
    ],
)
def test_first_and_last_token(expression: str, message: str) -> None:
    _refused(expression, "decimal", message)


def test_formula_may_start_with_a_sign_or_end_with_pi() -> None:
    assert parse("- DS1 * PI", "decimal").display == "- DS1 * PI"


# ---------------------------------------------------------------------------
# Call forms (§2), and the shape laddercodec adds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expression",
    [
        "RAND ( DS1 + 1 , 2 )",  # one token per argument
        "RAND ( ABS ( DD616 ) , 20 )",
        "RAND ( 1 , 2 , 3 )",
        "RAND ( 1 )",
    ],
)
def test_rand_takes_one_token_per_argument(expression: str) -> None:
    # CLICK's editor refuses an argument of more than one token, and so does laddercodec.
    _refused(expression, "decimal", "RAND takes RAND \\( a , b \\)")


@pytest.mark.parametrize(
    "expression",
    ["LSH ( DH1 + 1h , 2h )", "LSH ( ( DH1 AND FFh ) , 1h )", "LSH ( RSH ( DH1 , 1h ) , 2h )"],
)
def test_shift_takes_one_token_per_argument(expression: str) -> None:
    _refused(expression, "hex", "LSH takes LSH \\( a , b \\)")


@pytest.mark.parametrize("expression", ["SUM DS1", "ABS DS1", "MAX DS1", "RAND .5"])
def test_every_function_takes_parentheses(expression: str) -> None:
    # CLICK's check requires '(' after a trig function. A rung in math_unary_plus_pi.bin
    # records that CLICK refused SUM DS1. laddercodec treats the other functions as SUM.
    _refused(expression, "decimal", "takes its argument in parentheses")


def test_pi_may_take_parentheses() -> None:
    # CLICK's check lets '(' follow PI. In math_unary_plus_pi.bin, CLICK stored a typed
    # PI ( 2 ) in call form.
    assert _views("PI ( 2 )", "decimal") == ("PI ( 2 )", "PI ( 2 )", "PI#(#H2#)", "PI#(#H2#)")
    _refused("PI DS1", "decimal", "'DS1' after 'PI'")


@pytest.mark.parametrize(
    "expression",
    [
        "SUM ( DS1 + DS2 )",  # refused in math_unary_plus_pi.bin
        "MAX ( DS1 , DS2 )",  # refused in math_unary_plus_pi.bin
        "SUM ( DS1 )",
        "SUM ( DS1 : DS3 : DS5 )",
        "SUM ( 1 : 5 )",
        "MDN ( ( DS1 : DS3 ) )",
    ],
)
def test_range_function_takes_two_addresses(expression: str) -> None:
    # SUM, MAX, MIN, MDN and AVG take the form F ( addr : addr ). The refused rungs in
    # math_unary_plus_pi.bin agree with this rule.
    name = expression.split()[0]
    _refused(expression, "decimal", f"{name} takes {name} \\( a : b \\)")


def test_hex_range_function_takes_two_addresses() -> None:
    _refused("SUM ( 1h : 5h )", "hex", "SUM takes SUM \\( a : b \\)")


@pytest.mark.parametrize(
    "expression", ["DS1 , DS2", "DS1 + 1 , 5", "( DS1 , DS2 )", "ABS ( DS1 , DS2 )"]
)
def test_comma_outside_a_two_argument_call_is_refused(expression: str) -> None:
    # A rung in math_unary_plus_pi.bin records that CLICK's dialog refused DS1 , DS2 with
    # OBJ-037 "Please use a period (.) as a decimal point."
    _refused(expression, "decimal", "use a period \\(.\\) as the decimal point")


@pytest.mark.parametrize("expression", ["DS1 : DS5", "ABS ( DS1 : DS3 )", "( DS1 : DS3 )"])
def test_colon_outside_a_range_function_is_refused(expression: str) -> None:
    # A ':' stands only in SUM, MAX, MIN, MDN or AVG ( a : b ).
    _refused(expression, "decimal", "':' stands outside SUM, MAX, MIN, MDN or AVG")


@pytest.mark.parametrize("address", ["DS0", "DS4501", "XD1u", "X017", "DS100000000"])
def test_address_passes_the_full_check(address: str) -> None:
    # CLICK refused DS1 + DS0 in math_unary_plus_pi.bin, so it checks each address against
    # its bank's range, not only its shape.
    with pytest.raises(AddressError, match=f"'{address}'"):
        Math(f"DS1 + {address}", "DS9")


@pytest.mark.parametrize("expression", ["SIN ( RAND ( 1 , 2 ) )", "SQRT ( SUM ( DS1 : DS3 ) , 1 )"])
def test_trig_body_counts_commas_against_sums(expression: str) -> None:
    _refused(expression, "decimal", "holds a ',' or ':' that is not a SUM range")


# ---------------------------------------------------------------------------
# Printers (§3) [code; every native fixture]
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "mode", "internal"),
    [
        ("RAND ( 1 , 100 )", "decimal", "H1#RAND#H100#"),  # the trailing '#'
        ("RAND ( 1 , 10 ) + DS1", "decimal", "H1#RAND#H10#+#DS1"),
        ("LSH ( DH1 , 1h ) AND RSH ( DH2 , 2h )", "hex", "DH1#LSH#UH1#AND#DH2#RSH#UH2#"),
        ("ABS ( RAND ( 1 , 10 ) )", "decimal", "ABS#(#H1#RAND#H10#)"),
    ],
)
def test_comma_function_is_stored_infix(expression: str, mode: str, internal: str) -> None:
    assert parse(expression, mode).internal() == internal


def test_template_writes_at_for_each_address() -> None:
    # retyped/math_xd.bin shows that CLICK writes XD and YD addresses as @ in the template,
    # like other addresses.
    assert _views("XD0u AND YD1", "hex") == ("XD0u AND YD1", "@ AND @", "@#AND#@", "XD0u#AND#YD1")


# ---------------------------------------------------------------------------
# Every Math in the fixtures
# ---------------------------------------------------------------------------

_NEEDLE = "Math".encode("utf-16-le") + b"\x00\x00"
_SLOT_TAGS = (0x6888, 0x688C)

#: Formulas that an older version of the encoder wrote into retyped/math_wide.bin. Its XD
#: and YD rungs put the address itself in the template, where CLICK writes @, as CLICK's own
#: retyped/math_xd.bin shows. Its sum of 69 addresses is over the 270-character limit.
_OLD_TEMPLATES = {"XD0 AND 1h", "XD0u AND 1h", "YD1 AND 1h", "MAX ( XD0 : XD3 )"}


def _clipboard_files() -> list[tuple[str, bytes]]:
    files = [(p.relative_to(FIXTURES).as_posix(), p.read_bytes()) for p in FIXTURES.rglob("*.bin")]
    files += [
        (p.relative_to(FIXTURES).as_posix(), gzip.decompress(p.read_bytes()))
        for p in FIXTURES.rglob("*.bin.gz")
    ]
    return sorted(files)


def _fixture_blobs() -> list[tuple[str, bool, str, dict[int, str]]]:
    """Return (file, native, mode, header tags) for each Math blob in the clipboard fixtures.

    *native* is True when CLICK's editor wrote the blob.
    """
    found = []
    for name, buf in _clipboard_files():
        i = -1
        while (i := buf.find(_NEEDLE, i + 1)) != -1:
            start = i + 10
            count = struct.unpack_from("<I", buf, start + 6)[0]
            fields, _ = _parse_tagged_fields_verbose(buf, start + 10, count)
            tags = {tag: value for tag, _, value in fields if tag not in _SLOT_TAGS}
            # Cell header bytes +0x09/+0x0A are 01 03 on a Math CLICK's editor wrote.
            native = buf[i - 0x25 + 0x09 : i - 0x25 + 0x0B] == b"\x01\x03"
            mode = "hex" if tags[0x11FE] == "-1" else "decimal"
            found.append((name, native, mode, tags))
    return found


_DECODE_PROGRAM = importlib.import_module("laddercodec.decode_program")


def _scr_blobs() -> list[tuple[str, bool, str, dict[int, str]]]:
    """Return (file, native, mode, tags) for each Math that the SCR decoder reads in the
    fixtures.

    ``decode_program`` returns the decoded ``Math``, not the strings that the SCR file
    stores, and no public function returns the tags of an SCR instruction. This function
    therefore wraps the private ``_scr_af``, which the SCR decoder calls with the tags of
    each AF cell.
    """
    found: list[tuple[str, bool, str, dict[int, str]]] = []
    read = _DECODE_PROGRAM._scr_af
    name = ""

    def record(class_name, type_code, tags, *rest):  # noqa: ANN001, ANN202
        if class_name == "Math":
            # A flag tag is set when present in SCR.
            mode = "hex" if tag_flag(tags, 0x11FE) else "decimal"
            found.append((name, True, mode, dict(tags)))
        return read(class_name, type_code, tags, *rest)

    _DECODE_PROGRAM._scr_af = record
    try:
        for path in sorted(FIXTURES.rglob("*.scr")):
            name = path.relative_to(FIXTURES).as_posix()
            decode_program(path.read_bytes())
    finally:
        _DECODE_PROGRAM._scr_af = read
    return found


_BLOBS = _fixture_blobs()
_SCR_BLOBS = _scr_blobs()


def test_fixtures_hold_native_math() -> None:
    assert len(_BLOBS) > 150
    assert sum(native for _, native, _, _ in _BLOBS) > 70
    assert len(_SCR_BLOBS) > 100


@pytest.mark.parametrize(
    ("path", "native", "mode", "tags"),
    _BLOBS + _SCR_BLOBS,
    ids=[b[0] for b in _BLOBS + _SCR_BLOBS],
)
def test_reader_prints_every_stored_math(
    path: str, native: bool, mode: str, tags: dict[int, str]
) -> None:
    """Each stored formula, parsed, prints back the four strings that its blob stores."""
    expression = _reconstruct_expression(tags[0x61FF], tags[0x61FD])
    if not native and path.endswith("math_wide.bin"):
        if len(tags[0x6229]) > 270:
            with pytest.raises(FieldError) as caught:
                parse(expression, mode)
            assert str(caught.value).endswith("CLICK allows 270 (OBJ-1008). Shorten the formula.")
            return
        if expression in _OLD_TEMPLATES:
            formula = parse(expression, mode)
            assert tags[0x61FF] == formula.display != formula.template
            assert formula.internal() == tags[0x61FD]
            return
    # laddercodec refuses some X and Y ranges in v4_captures/math_ranges_*.bin. An older
    # encoder also wrote one of them, SUM ( X001 : X036 ), into retyped/math_wide.bin.
    if expression in REFUSED_XY_RANGES:
        with pytest.raises(FieldError, match=re.escape(xy_range_message(expression))):
            parse(expression, mode)
        return
    formula = parse(expression, mode)
    assert formula.template == tags[0x61FF]
    assert formula.internal(template=True) == tags[0x6229]
    assert formula.internal() == tags[0x61FD]
    display = tags[0x6228]
    if tags.get(0x2224) == "1":
        # With nicknames shown, the display names each address by its project nickname in
        # <...>, and no other field holds the nickname. Replace each one with @ and compare
        # the result with the template.
        parts = display.split("<")
        display = parts[0] + "".join("@" + p.split(">", 1)[1] for p in parts[1:])
        assert display == formula.template
    else:
        assert display == formula.display


@pytest.mark.parametrize("path", sorted(FIXTURES.rglob("*.scr")), ids=lambda p: p.stem)
def test_every_scr_math_decodes(path: Path) -> None:
    data = path.read_bytes()
    if "Math".encode("utf-16-le") not in data:
        pytest.skip("no Math")
    for rung in decode_program(data).rungs:
        for instruction in rung.instructions:
            assert not (
                isinstance(instruction, RawInstruction) and instruction.class_name == "Math"
            )


def _raw_maths(rungs: list) -> list[RawInstruction]:  # noqa: ANN001
    return [
        i
        for rung in rungs
        for i in rung.instructions
        if isinstance(i, RawInstruction) and i.class_name == "Math"
    ]


def test_refused_stored_formula_decodes_as_raw() -> None:
    # Take DS1 + ( +5 ) from math_unary_plus_pi.bin and rewrite its template as DS1 + +5,
    # which puts a sign right after an operator.
    buf = (FIXTURES / "v4_captures" / "math_unary_plus_pi.bin").read_bytes()
    stored, refused = "@ + ( +5 )".encode("utf-16-le"), "@ + +5    ".encode("utf-16-le")
    rungs = decode(buf.replace(stored, refused))
    assert isinstance(rungs, list)
    (raw,) = _raw_maths(rungs)
    assert refused in raw.build_blob()
    assert isinstance(rungs[1].instructions[0], Math)


def test_refused_stored_formula_keeps_its_refusal_from_scr() -> None:
    # Take DH51 AND DH52 from sm_IsCmdValid.scr and rewrite its template as DH51 DH52 AND.
    data = (FIXTURES / "tumbler" / "subroutines" / "sm_IsCmdValid.scr").read_bytes()
    stored = "@ AND @".encode("utf-16-le")
    assert stored in data
    with pytest.warns(RefusedFieldWarning):
        program = decode_program(data.replace(stored, "@ @ AND".encode("utf-16-le")))
    assert not _raw_maths(program.rungs)
    refused = [
        i
        for rung in program.rungs
        for i in rung.instructions
        if isinstance(i, Math) and refusals(i)
    ]
    assert [kept(math, "Math.expression").expression for math in refused] == ["DH51 DH52 AND"]


def _blob(template: str, internal: str) -> bytes:
    out = bytearray(_utf16le_null("Math"))
    out += struct.pack("<I", 0x271A) + b"\x01\x00" + struct.pack("<I", 9)
    for tag, value in [
        (0x6065, "DS9"),
        (0x11FE, "0"),
        (0x11F8, "0"),
        (0x61FF, template),
        (0x6228, template.replace("@", "DS1")),
        (0x6229, template.replace(" ", "#")),
        (0x61FD, internal),
        (0x3218, "8451"),
        (0x2224, "0"),
    ]:
        out += _tagged_field(tag, value)
    return bytes(out)


def test_stored_constant_of_5000_digits_keeps_its_refusal() -> None:
    digits = "9" * 5000
    parsed = kept(parse_af_blob(_blob(f"@ + {digits}", f"DS1#+#H{digits}")), "Math.expression")
    assert parsed.expression == f"DS1 + {digits}"
    # The reader takes constants from the template, so a long constant that only the
    # internal formula holds is not read.
    parsed = parse_af_blob(_blob("@ + 5", f"DS1#+#H{digits}"))
    assert isinstance(parsed, Math)
    assert parsed.expression == "DS1 + 5"
