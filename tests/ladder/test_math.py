from __future__ import annotations

import struct

import pytest

from laddercodec.binary_helpers import _tagged_field, _utf16le_null
from laddercodec.instructions import parse_af_blob
from laddercodec.instructions.math import (
    Math,
    _make_internal,
    _range_interiors,
    _reconstruct_expression,
)


def _build_math_blob_with_nickname_and_display_literal() -> bytes:
    out = bytearray()
    out += _utf16le_null("Math")
    out += struct.pack("<I", 0x271A)
    out += b"\x01\x00"
    out += struct.pack("<I", 9)
    out += _tagged_field(0x6065, "DS124")
    out += _tagged_field(0x11FE, "0")
    out += _tagged_field(0x11F8, "0")
    out += _tagged_field(0x61FF, "@ + 200")
    out += _tagged_field(0x6228, "<z_AckAndClearAllAlm_loop> + 200")
    out += _tagged_field(0x6229, "@#+#H200")
    out += _tagged_field(0x61FD, "DS123#+#H200")
    out += _tagged_field(0x3218, "8451")
    out += _tagged_field(0x2224, "1")
    return bytes(out)


def test_reconstruct_expression_preserves_display_literals_and_concrete_operands() -> None:
    assert _reconstruct_expression("@ + 200", "DS123#+#H200") == "DS123 + 200"


def test_internal_form_normalizes_literals() -> None:
    """Decimal integers get ``H``; hex constants become ``UH`` + decimal value.

    ``Ah`` → ``UH10`` is from a CLICK v4 copy-back (clicknick math-error-ok.bin);
    ``( -5 )`` → ``(#H-5#)`` and ``( -2.5 )`` → ``(#F-2.5#)`` from ones typed
    in v4 (math_neg.bin).
    """
    assert _make_internal("DS1 + 200") == "DS1#+#H200"
    assert _make_internal("DS401 + ( -5 )") == "DS401#+#(#H-5#)"
    assert _make_internal("DF401 * ( -2.5 )") == "DF401#*#(#F-2.5#)"
    assert _make_internal("DF401 * ( -1.5E+10 )") == "DF401#*#(#F-1.5E+10#)"
    assert _make_internal("DF1 * 3.14") == "DF1#*#F3.14"
    assert _make_internal("DF1 * .5 + 1E5") == "DF1#*#F.5#+#F1E5"
    assert _make_internal("- DS401") == "-#DS401"
    assert _make_internal("DH221 + Ah") == "DH221#+#UH10"
    assert _make_internal("DH1 AND AB59h") == "DH1#AND#UH43865"


@pytest.mark.parametrize(
    ("display", "internal"),
    [
        # typed in CLICK v4: math_r1.bin, math_typed.bin, the math__v4 RAND rungs
        ("LSH ( DH5 , 1h )", "DH5#LSH#UH1#"),
        ("RAND ( 1 , 100 )", "H1#RAND#H100#"),
        ("RAND ( DD111 , DD112 )", "DD111#RAND#DD112#"),
        ("RAND ( 1 , 10 ) + DS1", "H1#RAND#H10#+#DS1"),
        ("SUM ( DS1 : DS3 ) + 5", "SUM#(#DS1#:#DS3#)#+#H5"),
        ("MAX ( DS1 : DS3 ) + SUM ( DS5 : DS8 )", "MAX#(#DS1#:#DS3#)#+#SUM#(#DS5#:#DS8#)"),
        # the other comma functions and positions: same rule, not typed yet
        ("RRO ( DH1 , DH2 )", "DH1#RRO#DH2#"),
        ("DH2 + LSH ( DH1 , 1h )", "DH2#+#DH1#LSH#UH1#"),
        ("( LSH ( DH1 , 1h ) ) + DH2", "(#DH1#LSH#UH1#)#+#DH2"),
        ("ABS ( RAND ( 1 , 10 ) )", "ABS#(#H1#RAND#H10#)"),
        # the editor refuses a compound argument; the call form passes Check Program
        ("LSH ( DH1 + 1h , 2h )", "LSH#(#DH1#+#UH1#,#UH2#)"),
        ("LSH ( ( DH1 AND FFh ) , 1h )", "LSH#(#(#DH1#AND#UH255#)#,#UH1#)"),
        ("LSH ( RSH ( DH1 , 1h ) , 2h )", "LSH#(#RSH#(#DH1#,#UH1#)#,#UH2#)"),
        # range functions take no commas; a comma list is left as written
        ("MAX ( DS1 , DS2 )", "MAX#(#DS1#,#DS2#)"),
    ],
)
def test_comma_calls_are_stored_infix(display: str, internal: str) -> None:
    assert _make_internal(display) == internal


def test_hex_constant_round_trips_through_csv_form() -> None:
    blob = Math(expression="DH221 + Ah", result="DH222", mode="hex").build_blob()
    parsed = parse_af_blob(blob)
    assert isinstance(parsed, Math)
    assert parsed.to_csv() == "math(DH221 + Ah,DH222,mode=hex)"


def test_reconstruct_expression_handles_repeated_operands() -> None:
    assert _reconstruct_expression("@ + @", "DS1#+#DS1") == "DS1 + DS1"


def test_parse_blob_prefers_canonical_math_expression_over_internal_literal_form() -> None:
    parsed = parse_af_blob(_build_math_blob_with_nickname_and_display_literal())

    assert parsed is not None
    assert parsed.expression == "DS123 + 200"
    assert parsed.result == "DS124"
    assert parsed.mode == "decimal"
    assert parsed.to_csv() == "math(DS123 + 200,DS124,mode=decimal)"


@pytest.mark.parametrize(
    ("typed", "spaced"),
    [
        ("DS1+DS2", "DS1 + DS2"),
        ("ABS(DS1)*2", "ABS ( DS1 ) * 2"),
        ("(DS1+DS2)/2", "( DS1 + DS2 ) / 2"),
        ("DS1-5", "DS1 - 5"),
        ("DS1 - 5", "DS1 - 5"),
        ("-5+DS1", "-5 + DS1"),
        ("DS1*(-5)", "DS1 * ( -5 )"),
        ("DS1*-2.5", "DS1 * -2.5"),
        ("-DS1", "- DS1"),
        ("DF1*1.0E-10", "DF1 * 1.0E-10"),
        ("DF1*-1.5e+10", "DF1 * -1.5e+10"),
        ("DF1+.5", "DF1 + .5"),
        ("DH1+1Eh-1h", "DH1 + 1Eh - 1h"),
        ("DS1 MOD 2", "DS1 MOD 2"),
        ("DS1 MOD -2", "DS1 MOD -2"),
        ("SUM(DS1:DS9)", "SUM ( DS1 : DS9 )"),
        ("RAND(1,100)", "RAND ( 1 , 100 )"),
        ("<a-b> + 1", "<a-b> + 1"),
    ],
)
def test_expression_is_spaced_like_clicks_editor(typed: str, spaced: str) -> None:
    assert Math(typed, "DS9").expression == spaced


def test_nickname_display_wraps_each_operand_once() -> None:
    blob = Math("DS10 + DS1 + DS1", "DS9").build_blob(show_nicknames=True)
    assert "<?DS10> + <?DS1> + <?DS1>".encode("utf-16-le") in blob


def test_template_leaves_hex_constants_alone() -> None:
    blob = Math("C1 + AC1h", "DH9", mode="hex").build_blob()
    assert "@ + AC1h".encode("utf-16-le") in blob


def test_literal_after_unspaced_operator_gets_its_internal_prefix() -> None:
    assert _make_internal(Math("ABS(DS1)*2", "DS9").expression) == "ABS#(#DS1#)#*#H2"


@pytest.mark.parametrize(
    ("expression", "interiors"),
    [
        ("MAX ( XD0 : XD3 )", ["XD0u", "XD1", "XD2"]),
        ("MAX ( XD0u : XD2 )", ["XD1"]),
        ("MAX ( XD0 : XD0u )", []),
        ("MAX ( YD0 : YD1 )", ["YD0u"]),
        ("SUM ( DS1 : DS3 )", ["DS2"]),
    ],
)
def test_range_interiors(expression: str, interiors: list[str]) -> None:
    assert _range_interiors(expression) == interiors


def test_xd_operands_decode_with_their_display_constants() -> None:
    blob = Math("XD0u AND 1h", "DH1", mode="hex").build_blob()
    parsed = parse_af_blob(blob)
    assert isinstance(parsed, Math)
    assert parsed.expression == "XD0u AND 1h"
    assert "@ AND 1h".encode("utf-16-le") in blob


def test_500_interiors_keeps_the_short_form_and_501_takes_v4_capacity() -> None:
    field_count = lambda expr: struct.unpack_from(  # noqa: E731
        "<I", Math(expr, "DD1").build_blob(), 16
    )[0]
    assert field_count("SUM ( DS1 : DS502 )") == 1010
    assert field_count("SUM ( DS1 : DS503 )") == 5510
