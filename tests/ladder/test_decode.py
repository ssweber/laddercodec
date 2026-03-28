"""Golden round-trip tests and validation tests for decode_rung().

For each single-rung golden .bin fixture, decodes the binary and compares
the result against the CSV-derived data (the same data that produced the
.bin via encode_rung()).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec import encode_multi_rung, encode_rung
from laddercodec.decode import DecodeError, _decode_rtf, decode_rung
from laddercodec.encode import _PREFIX, _SUFFIX
from tests.golden_io import GOLDEN_DIR, read_golden_csv

# -- Golden CSV/BIN decode round-trip tests --

_GOLDEN_CSVS = sorted(p for p in GOLDEN_DIR.glob("*.csv") if not p.stem.startswith("mr-"))


@pytest.mark.parametrize("csv_path", _GOLDEN_CSVS, ids=[p.stem for p in _GOLDEN_CSVS])
def test_golden_decode(csv_path: Path) -> None:
    logical_rows, condition_rows, af_tokens, comment = read_golden_csv(csv_path)
    bin_path = csv_path.with_suffix(".bin")
    assert bin_path.exists(), f"Missing golden .bin: {bin_path.name}"
    data = bin_path.read_bytes()

    result = decode_rung(data)

    assert result.logical_rows == logical_rows
    assert result.condition_rows == condition_rows
    assert result.af_tokens == af_tokens
    assert result.comment == comment


# -- Encode -> decode round-trip tests --


def test_encode_decode_roundtrip_empty() -> None:
    conds = [[""] * 31]
    afs = [""]
    data = encode_rung(1, conds, afs)
    result = decode_rung(data)
    assert result.logical_rows == 1
    assert result.condition_rows == conds
    assert result.af_tokens == afs
    assert result.comment is None


def test_encode_decode_roundtrip_wire_nop_comment() -> None:
    conds = [["-"] * 31, [""] * 31]
    afs = ["NOP", ""]
    comment = "Hello **world**"
    data = encode_rung(2, conds, afs, comment=comment)
    result = decode_rung(data)
    assert result.logical_rows == 2
    assert result.condition_rows == conds
    assert result.af_tokens == afs
    assert result.comment == comment


def test_encode_decode_roundtrip_multiline_comment() -> None:
    conds = [[""] * 31]
    afs = [""]
    comment = "Line 1\nLine 2\nLine 3"
    data = encode_rung(1, conds, afs, comment=comment)
    result = decode_rung(data)
    assert result.comment == comment


def test_encode_decode_roundtrip_styled_comment() -> None:
    conds = [[""] * 31]
    afs = [""]
    comment = "**bold** and *italic* and __underline__"
    data = encode_rung(1, conds, afs, comment=comment)
    result = decode_rung(data)
    assert result.comment == comment


# -- Validation / error tests --


def test_decode_rejects_bad_magic() -> None:
    bad = b"NOTCLICK" + b"\x00" * 0x0A60
    with pytest.raises(DecodeError, match="magic"):
        decode_rung(bad)


def test_decode_rejects_short_buffer() -> None:
    with pytest.raises(DecodeError, match="too short"):
        decode_rung(b"CLICK   " + b"\x00" * 100)


def test_decode_rung_rejects_multi_rung() -> None:
    multi_bin = encode_multi_rung(
        [(1, [[""] * 31], [""]), (1, [[""] * 31], [""])],
    )
    with pytest.raises(DecodeError, match="multiple rungs"):
        decode_rung(multi_bin)


# -- RTF decode unit tests --


def test_rtf_decode_plain() -> None:
    payload = _PREFIX + b"Hello" + _SUFFIX
    assert _decode_rtf(payload) == "Hello"


def test_rtf_decode_group_bold() -> None:
    payload = _PREFIX + rb"{\b Hello}" + _SUFFIX
    assert _decode_rtf(payload) == "**Hello**"


def test_rtf_decode_group_italic() -> None:
    payload = _PREFIX + rb"{\i Hello}" + _SUFFIX
    assert _decode_rtf(payload) == "*Hello*"


def test_rtf_decode_group_underline() -> None:
    payload = _PREFIX + rb"{\ul Hello}" + _SUFFIX
    assert _decode_rtf(payload) == "__Hello__"


def test_rtf_decode_multiline() -> None:
    payload = _PREFIX + rb"Line 1\par Line 2" + _SUFFIX
    assert _decode_rtf(payload) == "Line 1\nLine 2"


def test_rtf_decode_mixed_styles() -> None:
    body = rb"{\b Bold} and {\i italic} and {\ul underline}"
    payload = _PREFIX + body + _SUFFIX
    assert _decode_rtf(payload) == "**Bold** and *italic* and __underline__"


def test_rtf_decode_toggle_bold() -> None:
    payload = _PREFIX + rb"\b Hello\b0" + _SUFFIX
    assert _decode_rtf(payload) == "**Hello**"


def test_rtf_decode_toggle_italic() -> None:
    payload = _PREFIX + rb"\i Hello\i0" + _SUFFIX
    assert _decode_rtf(payload) == "*Hello*"


def test_rtf_decode_toggle_underline() -> None:
    payload = _PREFIX + rb"\ul Hello\ulnone" + _SUFFIX
    assert _decode_rtf(payload) == "__Hello__"


# -- DecodedRung preserves raw RTF --


def test_decoded_rung_has_comment_rtf() -> None:
    data = encode_rung(1, [[""] * 31], [""], comment="Test")
    result = decode_rung(data)
    assert result.comment_rtf is not None
    assert result.comment_rtf.startswith(_PREFIX)
    assert result.comment == "Test"


def test_decoded_rung_no_comment_rtf_when_empty() -> None:
    data = encode_rung(1, [[""] * 31], [""])
    result = decode_rung(data)
    assert result.comment_rtf is None
    assert result.comment is None
