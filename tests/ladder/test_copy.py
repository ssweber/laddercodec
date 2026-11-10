"""Tests for laddercodec.instructions.copy: Copy-to-text termination codes.

CLICK and pyrung's exporter spell a termination code as ``$`` + two hex digits
(``$0D``, ``$00``), so a decoded Copy must write the same text.
"""

from __future__ import annotations

import pytest

from laddercodec.instructions import parse_af_blob
from laddercodec.instructions.copy import Copy, from_tags

_TOKEN = "copy(DS20,TXT7,convert=to_text(suppress_zero=1,exponential=0,termination_code={code}))"

#: Below 0x10 is where a one-digit spelling used to slip out.
_CODES = ["$00", "$0D", "$0A", "$13", "$7F"]


@pytest.mark.parametrize("code", _CODES)
def test_termination_code_round_trips(code: str) -> None:
    """CSV token → blob → decode → CSV gives back the same two-digit code."""
    token = _TOKEN.format(code=code)
    copy = Copy.from_csv_token(token)
    parsed = parse_af_blob(copy.build_blob())
    assert isinstance(parsed, Copy)
    assert parsed.termination_code == code
    assert parsed == copy
    assert parsed.to_csv() == token


@pytest.mark.parametrize(("code", "term_char"), [("$00", None), ("$0D", "13")])
def test_termination_code_from_scr_tags(code: str, term_char: str | None) -> None:
    """SCR omits 0x3216 at 0, so a $00 terminator has only its 0x1221 flag."""
    tags = {0x6074: "DS20", 0x6076: "TXT7", 0x2227: "1", 0x1221: ""}
    if term_char is not None:
        tags[0x3216] = term_char
    parsed = from_tags("Copy", 0x2721, tags)
    assert isinstance(parsed, Copy)
    assert parsed.termination_code == code


@pytest.mark.parametrize("end_tag", [0x6075, 0x6077])
def test_single_copy_with_end_address_is_not_decoded(end_tag: int) -> None:
    """Copy type 0 (absent 0x2223) with an end address is left to raw(), not truncated."""
    tags = {0x6074: "DS1", 0x6076: "DS10", end_tag: "DS20"}
    assert from_tags("Copy", 0x2721, tags) is None


@pytest.mark.parametrize(("given", "stored"), [("$D", "$0D"), ("$0", "$00"), ("$0d", "$0D")])
def test_one_digit_or_lowercase_code_is_stored_canonical(given: str, stored: str) -> None:
    copy = Copy(source="DS20", destination="TXT7", format="text", termination_code=given)
    assert copy.termination_code == stored
    assert f"termination_code={stored})" in copy.to_csv()


@pytest.mark.parametrize("bad", ["$", "$ZZ", "$100"])
def test_invalid_termination_code_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        Copy(source="DS20", destination="TXT7", format="text", termination_code=bad)
