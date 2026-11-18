"""Test decoding of single-rung clipboard binaries, and the errors that decode_rung() raises.

For each golden CSV whose name does not start with mr-, the test decodes the .bin file that
was generated from it. It compares each rung with what read_csv() returns for the CSV.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec import decode, read_csv
from laddercodec.decode import DecodeError, _decode_rtf, decode_rung
from laddercodec.encode import _PREFIX, _SUFFIX, encode_rung
from laddercodec.encode_multi import encode_rungs
from tests.golden_io import GOLDEN_DIR

# -- Golden CSV/BIN decode round-trip tests --

_GOLDEN_CSVS = sorted(p for p in GOLDEN_DIR.glob("*.csv") if not p.stem.startswith("mr-"))


@pytest.mark.parametrize("csv_path", _GOLDEN_CSVS, ids=[p.stem for p in _GOLDEN_CSVS])
def test_golden_decode(csv_path: Path) -> None:
    expected = read_csv(csv_path)  # more than one rung where CLICK splits the CSV rung
    bin_path = csv_path.with_suffix(".bin")
    assert bin_path.exists(), f"Missing golden .bin: {bin_path.name}"
    data = bin_path.read_bytes()

    got = decode(data)
    results = got

    assert len(results) == len(expected)
    for result, want in zip(results, expected, strict=True):
        assert result.logical_rows == want.logical_rows
        assert result.conditions == want.conditions
        assert result.instructions == want.instructions
        assert result.comment == want.comment


# -- Encode -> decode round-trip tests --


def test_encode_decode_roundtrip_empty() -> None:
    conds = [[""] * 31]
    afs = [""]
    data = encode_rung(1, conds, afs)
    [result] = decode(data)
    assert result.logical_rows == 1
    assert result.conditions == tuple(map(tuple, conds))
    assert result.instructions == tuple(afs)
    assert result.comment is None


def test_encode_decode_roundtrip_wire_nop_comment() -> None:
    conds = [["-"] * 31, [""] * 31]
    afs = ["NOP", ""]
    comment = "Hello **world**"
    data = encode_rung(2, conds, afs, comment=comment)
    [result] = decode(data)
    assert result.logical_rows == 2
    assert result.conditions == tuple(map(tuple, conds))
    assert result.instructions == tuple(afs)
    assert result.comment == comment


def test_encode_decode_roundtrip_multiline_comment() -> None:
    conds = [[""] * 31]
    afs = [""]
    comment = "Line 1\nLine 2\nLine 3"
    data = encode_rung(1, conds, afs, comment=comment)
    [result] = decode(data)
    assert result.comment == comment


def test_encode_decode_roundtrip_styled_comment() -> None:
    conds = [[""] * 31]
    afs = [""]
    comment = "**bold** and *italic* and __underline__"
    data = encode_rung(1, conds, afs, comment=comment)
    [result] = decode(data)
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
    multi_bin = encode_rungs(
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


def test_rtf_decode_tab_control() -> None:
    payload = _PREFIX + rb"Col1\tab Col2" + _SUFFIX
    assert _decode_rtf(payload) == "Col1\tCol2"


def test_rtf_decode_rejects_non_1252_ansicpg() -> None:
    payload = _PREFIX.replace(b"\\ansicpg1252", b"\\ansicpg1251", 1) + b"Hello" + _SUFFIX
    with pytest.raises(DecodeError, match="ansicpg1252"):
        _decode_rtf(payload)


def test_rtf_decode_unicode_escape_skips_ascii_fallback() -> None:
    payload = _PREFIX + rb"\u8217?" + _SUFFIX
    assert _decode_rtf(payload) == "\u2019"


def test_rtf_decode_unicode_escape_skips_hex_fallback() -> None:
    payload = _PREFIX + rb"\u8217\'92" + _SUFFIX
    assert _decode_rtf(payload) == "\u2019"


def test_rtf_decode_unicode_escape_signed_16bit_arg() -> None:
    payload = _PREFIX + rb"\u-24679?" + _SUFFIX
    assert _decode_rtf(payload) == "\u9f99"


# -- A decoded Rung keeps the raw RTF --


def test_decoded_rung_has_comment_rtf() -> None:
    data = encode_rung(1, [[""] * 31], [""], comment="Test")
    [result] = decode(data)
    assert result.comment_rtf is not None
    assert result.comment_rtf.startswith(_PREFIX)
    assert result.comment == "Test"


def test_decoded_rung_no_comment_rtf_when_empty() -> None:
    data = encode_rung(1, [[""] * 31], [""])
    [result] = decode(data)
    assert result.comment_rtf is None
    assert result.comment is None


# -- RTF special character / indentation round-trips --


def test_encode_decode_roundtrip_special_chars() -> None:
    """A comment with a backslash and braces survives encode and decode."""
    conds = [[""] * 31]
    afs = [""]
    comment = "if (x > 0) { return x \\ y; }"
    data = encode_rung(1, conds, afs, comment=comment)
    [result] = decode(data)
    assert result.comment == comment


def test_encode_decode_roundtrip_indented_comment() -> None:
    """Spaces at the start of each line of a comment survive encode and decode."""
    conds = [[""] * 31]
    afs = [""]
    comment = "  indented line\n    double indented"
    data = encode_rung(1, conds, afs, comment=comment)
    [result] = decode(data)
    assert result.comment == comment


def test_encode_decode_roundtrip_special_chars_multiline() -> None:
    """A comment with braces, several lines and indented lines survives encode and decode."""
    conds = [[""] * 31]
    afs = [""]
    comment = "func() {\n  x = 1;\n  y = 2;\n}"
    data = encode_rung(1, conds, afs, comment=comment)
    [result] = decode(data)
    assert result.comment == comment


# -- RTF decode edge cases (unit-level) --


def test_rtf_decode_crlf_before_par() -> None:
    """The decoder drops a CR LF before \\par. In RTF it is whitespace in the source, not text."""
    payload = _PREFIX + b"Line 1\r\n\\par Line 2" + _SUFFIX
    assert _decode_rtf(payload) == "Line 1\nLine 2"


def test_rtf_decode_cr_before_par() -> None:
    """The decoder also drops a CR with no LF after it before \\par."""
    payload = _PREFIX + b"Line 1\r\\par Line 2" + _SUFFIX
    assert _decode_rtf(payload) == "Line 1\nLine 2"


def test_rtf_decode_unescapes_braces() -> None:
    payload = _PREFIX + rb"open \{ close \}" + _SUFFIX
    assert _decode_rtf(payload) == "open { close }"


def test_rtf_decode_unescapes_backslash() -> None:
    payload = _PREFIX + rb"path\\to\\file" + _SUFFIX
    assert _decode_rtf(payload) == "path\\to\\file"


def test_rtf_decode_strips_stray_cr() -> None:
    payload = _PREFIX + b"hello\rworld" + _SUFFIX
    assert _decode_rtf(payload) == "helloworld"


def test_rtf_decode_strips_cf_color() -> None:
    payload = _PREFIX + rb"\cf1 red text\cf0  normal" + _SUFFIX
    assert _decode_rtf(payload) == "red text normal"


def test_rtf_decode_strips_cf_with_bold() -> None:
    payload = _PREFIX + rb"\cf2 {\b bold red}\cf0  plain" + _SUFFIX
    assert _decode_rtf(payload) == "**bold red** plain"


def test_rtf_decode_strips_highlight() -> None:
    payload = _PREFIX + rb"\highlight1 highlighted\highlight0  normal" + _SUFFIX
    assert _decode_rtf(payload) == "highlighted normal"


def test_rtf_decode_strips_cb() -> None:
    payload = _PREFIX + rb"\cb1 background\cb0  normal" + _SUFFIX
    assert _decode_rtf(payload) == "background normal"


def test_rtf_decode_ignores_stray_style_reset_after_group() -> None:
    payload = _PREFIX + rb"{\b bold}\b0  plain" + _SUFFIX
    assert _decode_rtf(payload) == "**bold** plain"


# -- Stray-NOP dropping inside tall-instruction spans --


def _make_time_drum():
    from laddercodec import Drum

    return Drum(
        kind="time_drum",
        outputs=["C2"],
        presets=["1"],
        pattern=[[0]],
        current_step="DS1",
        completion_flag="C1",
        accumulator="TD1",
        unit="Td",
    )


def test_drop_tall_span_nops_clears_nop_inside_drum() -> None:
    """A NOP on a row that a drum box covers below its first row is dropped.

    Such a NOP is left over from editing, for example when the user inserts a row above it.
    """
    from laddercodec.decode import _drop_tall_span_nops

    instrs = [_make_time_drum(), "NOP", "", ""]
    _drop_tall_span_nops(instrs)
    assert instrs[1] == ""


def test_drop_tall_span_nops_keeps_count_down_bridge() -> None:
    """A NOP on the main input row of a count_down box is kept, because it is part of the box."""
    from laddercodec import Counter
    from laddercodec.decode import _drop_tall_span_nops

    counter = Counter(
        kind="count_down",
        done="CT1",
        accumulator="CTD1",
        preset="10",
    )
    instrs = [counter, "NOP", ""]
    _drop_tall_span_nops(instrs)
    assert instrs[1] == "NOP"


def test_drop_tall_span_nops_keeps_standalone_nop() -> None:
    """A NOP on a row that no box of several rows covers is kept."""
    from laddercodec.decode import _drop_tall_span_nops

    instrs = ["", "NOP", ""]
    _drop_tall_span_nops(instrs)
    assert instrs[1] == "NOP"


def test_drum_with_parallel_branch_roundtrips() -> None:
    """A drum whose parallel input branch runs below the drum box keeps every row in place
    through CSV rows.

    The branch runs down from ``T`` through ``|`` cells to ``X002`` in the bottom row.
    ``X002`` does not move up into the row of the drum's jog input."""
    from laddercodec.csv.writer import _rebuild_rung_from_rows, decoded_rung_to_rows
    from laddercodec.instructions import Drum

    bin_path = GOLDEN_DIR.parent / "drum_weird_branch.bin"
    result = decode(bin_path.read_bytes())
    rung = result[0]

    assert rung.logical_rows == 7
    assert isinstance(rung.instructions[0], Drum)
    assert rung.conditions[6][1].to_csv() == "X002"  # bottom row, below the drum body

    rows = decoded_rung_to_rows(rung)
    rebuilt = _rebuild_rung_from_rows(rows)
    assert rebuilt.logical_rows == 7
    assert rebuilt.conditions == rung.conditions
