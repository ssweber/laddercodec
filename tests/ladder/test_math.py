from __future__ import annotations

import struct

from laddercodec.binary_helpers import _tagged_field, _utf16le_null
from laddercodec.instructions import parse_af_blob
from laddercodec.instructions.math import Math, _make_internal, _reconstruct_expression


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
    assert _make_internal("LSH ( DH1 , 1h )") == "LSH#(#DH1#,#UH1#)"
    assert _make_internal("DH1 AND AB59h") == "DH1#AND#UH43865"


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
