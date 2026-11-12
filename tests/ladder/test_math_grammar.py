"""The Math formula reader against CLICK's Math grammar, one test per rule.

Sources: the Math dialog's check read from Inst_Math.dll ([code]; the steps of
``docs/internals/instruction-blobs.md``, "Math formula grammar"), the dialog answers in
``scratchpad/validation/arc.md`` and the native captures.  ``math_unary_plus_pi.bin`` is
``fixtures/v4_captures/math_unary_plus_pi.bin``: two formulas typed in CLICK v4, then one
rung per formula the dialog refused, its comment naming the formula.
"""

from __future__ import annotations

import gzip
import importlib
import struct
from pathlib import Path

import pytest

from laddercodec import AddressError, FieldError, decode, decode_program
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
from tests.test_v4_captures import REFUSED_XY_RANGES

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _refused(expression: str, mode: str, message: str) -> None:
    with pytest.raises(FieldError, match=message):
        Math(expression, "DH9" if mode == "hex" else "DF9", mode)  # type: ignore[arg-type]


def _views(expression: str, mode: str) -> tuple[str, str, str, str]:
    formula = parse(expression, mode)
    return formula.display, formula.template, formula.internal(template=True), formula.internal()


# ---------------------------------------------------------------------------
# The predictions the dialog confirmed (arc.md, "every prediction held", 2026-11-12)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("constant", ["1Eh", "0Eh", "2E5h"])
def test_hex_constant_with_digits_then_e_is_refused(constant: str) -> None:
    _refused(f"DH1 + {constant}", "hex", f"{constant} is refused; CLICK reads the digits before E")


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
    # CLICK rewrites hex DH1 + 7 as 7h; laddercodec keeps the CSV's intent and refuses it
    # (user ruling 2026-11-12), as it refuses 7H7, which CLICK rewrites as 77h.
    _refused("DH1 + 7", "hex", "7 is a decimal constant; a hex Math")
    _refused("DH1 + 7H7", "hex", "'7H7' is not an address")


# ---------------------------------------------------------------------------
# Tokenizer (§1.1 step 1) [code]
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "display"),
    [
        ("DS1+DS2*DS3", "DS1 + DS2 * DS3"),  # splits on + - * / ^
        ("SUM(DS1:DS3)", "SUM ( DS1 : DS3 )"),  # and on ( ) , :
        ("DS1\t+   DS2", "DS1 + DS2"),  # a run of spaces or tabs is one gap
        ("DF1*1.5E+10", "DF1 * 1.5E+10"),  # a real number keeps its exponent sign
        ("DF1+.5", "DF1 + .5"),
        ("DF1+1.", "DF1 + 1."),
    ],
)
def test_tokenizer_splits_as_clicks(typed: str, display: str) -> None:
    assert parse(typed, "decimal").display == display


@pytest.mark.parametrize("word", ["1.5x", "1.2.3", "2E5DS", "1EMOD"])
def test_word_the_number_rule_cuts_is_refused(word: str) -> None:
    # The longest real number a digit run starts is one token; a word going on past it
    # would be two tokens side by side.
    _refused(f"DF1 + {word}", "decimal", "is not an address, a function name or a constant")


@pytest.mark.parametrize("char", ["=", "#", "@", ";", "!", "&", "<", "\n", "\xa0", "\u2003"])
def test_character_outside_a_formula_is_refused(char: str) -> None:
    # Only a space or a tab separates tokens [code]; other white space is refused (BOB ruling).
    _refused(f"DS1 +{char}DS2", "decimal", "is no part of a Math formula")


def test_pointer_is_refused() -> None:
    # CLICK takes a pointer in Math; its pass was not read, and laddercodec refuses it.
    _refused("DS[DS1] + 1", "decimal", "'\\[' is part of a pointer")


# ---------------------------------------------------------------------------
# Classification and constants (§1.1 steps 2, 6, 7) [code]
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expression", ["DS1 + FOO", "DS1 + NAN", "DS1 + 0x1A", "DS1 + .", "DS1 . DS2"]
)
def test_word_is_refused(expression: str) -> None:
    # FOO: dialog answer (arc.md).  NAN and the strtod hex real 0x1A: CLICK's converter
    # takes them [inf]; laddercodec refuses them (BOB ruling).  A lone '.':
    # math_unary_plus_pi.bin refuses DS1 + .
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
    # v4_captures/sweep_math.bin: 32767 is H, 40000 and 100000 are W.
    assert parse(f"( {constant} )", "decimal").internal() == f"(#{internal}#)"


@pytest.mark.parametrize("constant", ["007", "00", "3000000000", "000000000001", "9" * 5000])
def test_decimal_integer_must_print_back_at_its_length(constant: str) -> None:
    # _wtoi64, low 32 bits, %d (Q-M9 verifier answer); %d prints at most 11 characters.
    _refused(f"DS1 + {constant}", "decimal", f"{constant[:20]}")


def test_real_is_f_and_fits_float32() -> None:
    assert parse("DF1 * 1.5e5", "decimal").internal() == "DF1#*#F1.5e5"  # case kept as typed
    _refused("DF1 * 1E39", "decimal", "1E39 is outside the float32 range")


def test_hex_constant_is_written_as_click_shows_it() -> None:
    # %Xh of the value (arc.md dialog answers; v4_captures/math_hex_upper_h.bin).
    assert _views("DH1 + 0fH", "hex") == ("DH1 + Fh", "@ + Fh", "@#+#UH15", "DH1#+#UH15")
    _refused("DH1 + 0FFFEh", "hex", "0FFFEh is outside 0h..FFFFh")  # four digits as typed


def test_each_mode_takes_its_own_constants() -> None:
    _refused("DS1 + 1Fh", "decimal", "1Fh is a hex constant")  # Q-M13
    _refused("DH1 + 1.5", "hex", "1.5 is a decimal constant")  # Q-M13b


# ---------------------------------------------------------------------------
# Parentheses (step 3), signs (step 5), mode keys (step 8) [code]
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
        ("DF1 * ( +2.5 )", "DF1#*#(#F+2.5#)"),  # a real is F and the typed text [code]
        ("( +0 )", "(#H+0#)"),
        ("+ DS1", "+#DS1"),
    ],
)
def test_decimal_sign_joins_its_constant(typed: str, internal: str) -> None:
    assert parse(typed, "decimal").internal() == internal


def test_plus_sign_joins_its_constant() -> None:
    # math_unary_plus_pi.bin: typed DS1 + ( +5 ), stored as these four strings.
    assert _views("DS1 + ( +5 )", "decimal") == (
        "DS1 + ( +5 )",
        "@ + ( +5 )",
        "@#+#(#H+5#)",
        "DS1#+#(#H+5#)",
    )
    assert _views("DS1 + ( + 5 )", "decimal")[0] == "DS1 + ( +5 )"


def test_plus_sign_keeps_the_length_rule() -> None:
    # The check string is '+' and %d of the value [code], so +007 prints back as +7.
    _refused("( +007 )", "decimal", "\\+007 is refused; CLICK reads it back as \\+7")


def test_hex_sign_stays_a_token() -> None:
    # v4_captures/math_hex_signed.bin: typed ( -Ah ), stored (#-#UH10#).
    assert parse("DH1 + ( -Ah )", "hex").internal() == "DH1#+#(#-#UH10#)"


def test_hex_plus_sign_stays_a_token() -> None:
    # No sign joins in a hex Math [code, step 5], as math_hex_signed.bin shows for '-'.
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
# The follow-set table (step 9, §2) [code]
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        # '(' may not be followed by an operator other than a sign, ',', ':' or ')'
        ("( * DS1 )", "'\\*' after '\\(': it needs a value before it"),
        ("( )", "the parentheses hold nothing"),
        ("( : DS3 )", "':' after '\\('"),
        # ')' may not be followed by '(' or a value
        ("( DS1 ) ( DS2 )", "'\\(' after '\\)'"),
        ("( DS1 ) DS2", "'DS2' after '\\)'"),
        ("( DS1 ) SIN ( DS2 )", "'SIN' after '\\)'"),
        ("RAND ( 1 , 10 ) DS1", "'DS1' after '\\)'"),  # math_unary_plus_pi.bin
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
    # math_unary_plus_pi.bin refuses DS1 LSH 1h.
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
# Call forms (§2) [code], and the shape laddercodec adds
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
    # The editor refuses a compound argument; laddercodec used to write it in call form
    # (BOB ruling: refuse it).
    _refused(expression, "decimal", "RAND takes RAND \\( a , b \\)")


@pytest.mark.parametrize(
    "expression",
    ["LSH ( DH1 + 1h , 2h )", "LSH ( ( DH1 AND FFh ) , 1h )", "LSH ( RSH ( DH1 , 1h ) , 2h )"],
)
def test_shift_takes_one_token_per_argument(expression: str) -> None:
    _refused(expression, "hex", "LSH takes LSH \\( a , b \\)")


@pytest.mark.parametrize("expression", ["SUM DS1", "ABS DS1", "MAX DS1", "RAND .5"])
def test_every_function_takes_parentheses(expression: str) -> None:
    # [code] for the trig functions; math_unary_plus_pi.bin refuses SUM DS1, and the other
    # functions follow it (BOB ruling).
    _refused(expression, "decimal", "takes its argument in parentheses")


def test_pi_may_take_parentheses() -> None:
    # The checker lets '(' follow PI [code]; math_unary_plus_pi.bin stores typed PI ( 2 )
    # in call form.
    assert _views("PI ( 2 )", "decimal") == ("PI ( 2 )", "PI ( 2 )", "PI#(#H2#)", "PI#(#H2#)")
    _refused("PI DS1", "decimal", "'DS1' after 'PI'")


@pytest.mark.parametrize(
    "expression",
    [
        "SUM ( DS1 + DS2 )",  # math_unary_plus_pi.bin
        "MAX ( DS1 , DS2 )",  # math_unary_plus_pi.bin
        "SUM ( DS1 )",
        "SUM ( DS1 : DS3 : DS5 )",
        "SUM ( 1 : 5 )",
        "MDN ( ( DS1 : DS3 ) )",
    ],
)
def test_range_function_takes_two_addresses(expression: str) -> None:
    # SUM, MAX, MIN, MDN and AVG take F ( addr : addr ); math_unary_plus_pi.bin confirms it.
    name = expression.split()[0]
    _refused(expression, "decimal", f"{name} takes {name} \\( a : b \\)")


def test_hex_range_function_takes_two_addresses() -> None:
    _refused("SUM ( 1h : 5h )", "hex", "SUM takes SUM \\( a : b \\)")


@pytest.mark.parametrize(
    "expression", ["DS1 , DS2", "DS1 + 1 , 5", "( DS1 , DS2 )", "ABS ( DS1 , DS2 )"]
)
def test_comma_outside_a_two_argument_call_is_refused(expression: str) -> None:
    # OBJ-037 "Please use a period (.) as a decimal point.", the dialog's answer to
    # DS1 , DS2 (user's dialog check, math_unary_plus_pi.bin).
    _refused(expression, "decimal", "use a period \\(.\\) as the decimal point")


@pytest.mark.parametrize("expression", ["DS1 : DS5", "ABS ( DS1 : DS3 )", "( DS1 : DS3 )"])
def test_colon_outside_a_range_function_is_refused(expression: str) -> None:
    # BOB ruling: a ':' stands only in SUM, MAX, MIN, MDN or AVG ( a : b ).
    _refused(expression, "decimal", "':' stands outside SUM, MAX, MIN, MDN or AVG")


@pytest.mark.parametrize("address", ["DS0", "DS4501", "XD1u", "X017", "DS100000000"])
def test_address_passes_the_full_check(address: str) -> None:
    # math_unary_plus_pi.bin refuses DS1 + DS0: the bank's range is checked, not only the
    # address's shape.
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
        ("RAND ( 1 , 100 )", "decimal", "H1#RAND#H100#"),  # tumbler: the trailing '#'
        ("RAND ( 1 , 10 ) + DS1", "decimal", "H1#RAND#H10#+#DS1"),
        ("LSH ( DH1 , 1h ) AND RSH ( DH2 , 2h )", "hex", "DH1#LSH#UH1#AND#DH2#RSH#UH2#"),
        ("ABS ( RAND ( 1 , 10 ) )", "decimal", "ABS#(#H1#RAND#H10#)"),
    ],
)
def test_comma_function_is_stored_infix(expression: str, mode: str, internal: str) -> None:
    assert parse(expression, mode).internal() == internal


def test_template_writes_at_for_each_address() -> None:
    # retyped/math_xd.bin: XD and YD addresses are @ in the template too.
    assert _views("XD0u AND YD1", "hex") == ("XD0u AND YD1", "@ AND @", "@#AND#@", "XD0u#AND#YD1")


# ---------------------------------------------------------------------------
# Every Math in the fixtures
# ---------------------------------------------------------------------------

_NEEDLE = "Math".encode("utf-16-le") + b"\x00\x00"
_SLOT_TAGS = (0x6888, 0x688C)

#: Blobs the encoder wrote before its current rules, in retyped/math_wide.bin: its XD/YD
#: rungs keep the address in the template, where CLICK writes @ (native retyped/math_xd.bin),
#: and its 69-address sum is over the 270-character cap.
_OLD_TEMPLATES = {"XD0 AND 1h", "XD0u AND 1h", "YD1 AND 1h", "MAX ( XD0 : XD3 )"}


def _clipboard_files() -> list[tuple[str, bytes]]:
    files = [(p.relative_to(FIXTURES).as_posix(), p.read_bytes()) for p in FIXTURES.rglob("*.bin")]
    files += [
        (p.relative_to(FIXTURES).as_posix(), gzip.decompress(p.read_bytes()))
        for p in FIXTURES.rglob("*.bin.gz")
    ]
    return sorted(files)


def _fixture_blobs() -> list[tuple[str, bool, str, dict[int, str]]]:
    """(file, native, mode, header tags) of each Math blob in the clipboard fixtures."""
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
    """(file, native, mode, tags) of each Math the SCR decoder reads in the fixtures.

    ``decode_program`` returns the decoded ``Math``, not the strings the SCR file stores,
    and no public function returns an SCR instruction's tags.  So this wraps the private
    ``_scr_af``, which the SCR decoder calls with each AF cell's tags.
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
    """Each formula, read from its stored form, prints back the four strings stored."""
    expression = _reconstruct_expression(tags[0x61FF], tags[0x61FD])
    if not native and path.endswith("math_wide.bin"):
        if len(tags[0x6229]) > 270:
            with pytest.raises(FieldError, match="CLICK allows 270"):
                parse(expression, mode)
            return
        if expression in _OLD_TEMPLATES:
            formula = parse(expression, mode)
            assert tags[0x61FF] == formula.display != formula.template
            assert formula.internal() == tags[0x61FD]
            return
    # The X/Y ranges of v4_captures/math_ranges_*.bin that laddercodec refuses; the
    # encoder also wrote SUM ( X001 : X036 ) into retyped/math_wide.bin.
    if expression in REFUSED_XY_RANGES:
        with pytest.raises(FieldError, match="wrong member list"):
            parse(expression, mode)
        return
    formula = parse(expression, mode)
    assert formula.template == tags[0x61FF]
    assert formula.internal(template=True) == tags[0x6229]
    assert formula.internal() == tags[0x61FD]
    display = tags[0x6228]
    if tags.get(0x2224) == "1":
        # Nickname view: each address shows its project nickname, which the blob names only
        # in the display; compare the rest of the display.
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
    # math_unary_plus_pi.bin's DS1 + ( +5 ), its template rewritten to DS1 + +5, a sign
    # right after an operator.
    buf = (FIXTURES / "v4_captures" / "math_unary_plus_pi.bin").read_bytes()
    stored, refused = "@ + ( +5 )".encode("utf-16-le"), "@ + +5    ".encode("utf-16-le")
    rungs = decode(buf.replace(stored, refused))
    assert isinstance(rungs, list)
    (raw,) = _raw_maths(rungs)
    assert refused in raw.build_blob()
    assert isinstance(rungs[1].instructions[0], Math)


def test_refused_stored_formula_decodes_as_raw_from_scr() -> None:
    # sm_IsCmdValid.scr's DH51 AND DH52, its template rewritten to DH51 DH52 AND.
    data = (FIXTURES / "tumbler" / "subroutines" / "sm_IsCmdValid.scr").read_bytes()
    stored = "@ AND @".encode("utf-16-le")
    assert stored in data
    program = decode_program(data.replace(stored, "@ @ AND".encode("utf-16-le")))
    assert _raw_maths(program.rungs)


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


def test_stored_constant_of_5000_digits_decodes_as_raw() -> None:
    digits = "9" * 5000
    assert parse_af_blob(_blob(f"@ + {digits}", f"DS1#+#H{digits}")) is None
    # A long constant only in the internal formula reads no further than the template.
    parsed = parse_af_blob(_blob("@ + 5", f"DS1#+#H{digits}"))
    assert isinstance(parsed, Math)
    assert parsed.expression == "DS1 + 5"
