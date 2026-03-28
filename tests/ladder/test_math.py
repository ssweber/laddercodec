from __future__ import annotations

import struct

from laddercodec.binary_helpers import _tagged_field, _utf16le_null
from laddercodec.instructions.math import _reconstruct_expression, parse_blob


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


def test_reconstruct_expression_handles_repeated_operands() -> None:
    assert _reconstruct_expression("@ + @", "DS1#+#DS1") == "DS1 + DS1"


def test_parse_blob_prefers_canonical_math_expression_over_internal_literal_form() -> None:
    parsed = parse_blob(_build_math_blob_with_nickname_and_display_literal())

    assert parsed is not None
    assert parsed.expression == "DS123 + 200"
    assert parsed.result == "DS124"
    assert parsed.mode == "decimal"
    assert parsed.to_csv() == "math(DS123 + 200,DS124,mode=decimal)"
