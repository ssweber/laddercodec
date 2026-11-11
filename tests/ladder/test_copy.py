"""Tests for laddercodec.instructions.copy: termination codes and conversion types.

CLICK and pyrung's exporter spell a termination code as ``$`` + two hex digits
(``$0D``, ``$00``), so a decoded Copy must write the same text.  Conversion
types (tag 0x2227) follow CLICK's dialog: they depend on the source and
destination types (InstCtl_Copy.dll, v4_captures/sweep_copy.bin).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from laddercodec import FieldError, Rung, decode, encode, read_csv
from laddercodec.csv import CSV_HEADER
from laddercodec.instructions import parse_af_blob
from laddercodec.instructions.copy import Copy, from_tags
from laddercodec.instructions.raw import _decompose_blob


def _conv_and_option(copy: Copy) -> tuple[str, str]:
    """(0x2227 conversion type, 0x2206 option) as written."""
    fields = {tag: value for tag, _s, value in _decompose_blob(copy.build_blob())[4]}
    return fields[0x2227], fields[0x2206]


@pytest.mark.parametrize(
    ("token", "conv", "option", "csv"),
    [
        (
            "copy(DS1,TXT1,convert=to_text(suppress_zero=1,termination_code=none))",
            "1",
            "0",
            "copy(DS1,TXT1,convert=to_text(suppress_zero=1,termination_code=none))",
        ),
        (
            "copy(DD1,TXT1,convert=to_text(suppress_zero=0,exponential=0,termination_code=none))",
            "2",
            "1",
            "copy(DD1,TXT1,convert=to_text(suppress_zero=0,termination_code=none))",
        ),
        (
            "copy(DF1,TXT1,convert=to_text(exponential=0,termination_code=none))",
            "3",
            "0",
            "copy(DF1,TXT1,convert=to_text(exponential=0,termination_code=none))",
        ),
        (  # suppress_zero means nothing for DF: accepted, not written
            "copy(DF1,TXT1,convert=to_text(suppress_zero=0,exponential=1,termination_code=none))",
            "4",
            "1",
            "copy(DF1,TXT1,convert=to_text(exponential=1,termination_code=none))",
        ),
        ("copy(DD1,DF1)", "7", "0", "copy(DD1,DF1)"),
        ("copy(DF1,DD1)", "7", "0", "copy(DF1,DD1)"),
        ("copy(DD1,DF1,convert=to_binary)", "8", "1", "copy(DD1,DF1,convert=to_binary)"),
        ("copy(DS1,TXT1,convert=to_binary)", "8", "2", "copy(DS1,TXT1,convert=to_binary)"),
        ("copy(DS1,DF1)", "0", "0", "copy(DS1,DF1)"),  # not a DD <-> DF pair
    ],
)
def test_conversion_type_follows_source_and_destination(
    token: str, conv: str, option: str, csv: str
) -> None:
    copy = Copy.from_csv_token(token)
    assert _conv_and_option(copy) == (conv, option)
    parsed = parse_af_blob(copy.build_blob())
    assert parsed == copy
    assert isinstance(parsed, Copy)
    assert parsed.to_csv() == csv


def test_exponential_on_integer_source_rejected() -> None:
    # CLICK offers exponential numbering for a DF source only.
    with pytest.raises(ValueError, match="needs a DF source"):
        Copy.from_csv_token("copy(DS1,TXT1,convert=to_text(exponential=1))")


@pytest.mark.parametrize(("conv", "source", "destination"), [(7, "DS1", "DF1"), (4, "DS1", "TXT1")])
def test_conversion_type_for_another_source_is_not_decoded(
    conv: int, source: str, destination: str
) -> None:
    """A type CLICK only writes for another source kind is left to raw()."""
    tags = {0x6074: source, 0x6076: destination, 0x2227: str(conv)}
    assert from_tags("Copy", 0x2721, tags) is None


_TOKEN = "copy(DS20,TXT7,convert=to_text(suppress_zero=1,termination_code={code}))"

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


@pytest.mark.parametrize(
    ("code", "token"),
    [
        ("$0D", "copy(DS1,TXT1,convert=to_binary(termination_code=$0D))"),
        ("0", "copy(DS1,TXT1,convert=to_binary)"),
    ],
)
def test_binary_termination_code_round_trips(tmp_path: Path, code: str, token: str) -> None:
    """Copy -> CSV -> read_csv -> encode -> decode keeps a to_binary termination code."""
    copy = Copy("DS1", "TXT1", format="binary", termination_code=code)
    assert copy.to_csv() == token
    assert Copy.from_csv_token(token) == copy

    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", "C1"] + ["-"] * 30 + [copy.to_csv()])
    rung = read_csv(path)[0]
    assert rung.instructions[0] == copy

    decoded = decode(encode(rung))
    assert isinstance(decoded, Rung)
    assert decoded.instructions[0] == copy
    assert decoded.instructions[0].to_csv() == token


def test_binary_termination_code_none_reads_as_no_code() -> None:
    parsed = Copy.from_csv_token("copy(DS1,TXT1,convert=to_binary(termination_code=none))")
    assert parsed == Copy("DS1", "TXT1", format="binary")


def test_to_binary_rejects_other_keywords() -> None:
    with pytest.raises(FieldError, match="suppress_zero"):
        Copy.from_csv_token("copy(DS1,TXT1,convert=to_binary(suppress_zero=1))")
