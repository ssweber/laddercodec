"""Search operand rules: the table is DS, DD, DH, DF, TD, CTD or TXT, the result a DS, and
the search value a constant or a data register, never a bit (Help CL174).  The Result Flag,
pointer, table range, text operator and hex value rules are Inst_Search.dll's (Q-M6, Q-M10).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from laddercodec import FieldError, read_csv
from laddercodec.csv import CSV_HEADER
from laddercodec.instructions import from_tags_af, parse_af_blob
from laddercodec.instructions.search import Search


def _read_af(tmp_path: Path, af: str) -> object:
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", "C1"] + ["-"] * 30 + [af])
    return read_csv(path)[0].instructions[0]


@pytest.mark.parametrize(
    ("expr", "kw", "message"),
    [
        ("C1..C10 == 1", "result=DS1,found=C20", "Search.table_start: 'C1' is not allowed"),
        ("DS1..SD10 == 1", "result=DS1,found=C20", "Search.table_end: 'SD10' is not allowed"),
        ("XD1..XD3 == 1", "result=DS1,found=C20", "Search.table_start: 'XD1' is not allowed"),
        ("DS1..DS10 == 1", "result=DD1,found=C20", "Search.result: 'DD1' is not allowed"),
        ("DS1..DS10 == 1", "result=C1,found=C20", "Search.result: 'C1' is not allowed"),
        ("DS1..DS10 == X001", "result=DS20,found=C20", "Search.source: 'X001' is not allowed"),
        ("DS1..DS10 == C5", "result=DS20,found=C20", "Search.source: 'C5' is not allowed"),
        ("DS1..DS10 == DS4501", "result=DS20,found=C20", "outside DS1-DS4500"),
        ("DS1..DS10 == 1", "result=DS20,found=C2001", "Search.found: 'C2001' is outside"),
        ("DS1..DS10 == foo", "result=DS20,found=C20", "Search.source: 'foo' is not a CLICK"),
        # the Result Flag is a C bit (Q-M10, OBJ-004)
        ("DS1..DS10 == 1", "result=DS20,found=Y001", "Search.found: 'Y001' is not allowed"),
        ("DS1..DS10 == 1", "result=DS20,found=XD0u", "Search.found: 'XD0u' is not allowed"),
        ("DS1..DS10 == 1", "result=DS20,found=YD0u", "Search.found: 'YD0u' is not allowed"),
        # no pointers (Q-M6)
        ("DS1..DS10 == DS[DS100]", "result=DS20,found=C1", "Search.source: 'DS\\[DS100\\]' is a"),
        ("DS1..DS10 == 1", "result=DS[DS1],found=C1", "Search.result: 'DS\\[DS1\\]' is a"),
        ("DS[DS1]..DS10 == 1", "result=DS20,found=C1", "Search.table_start: 'DS\\[DS1\\]' is a"),
        # the table is one bank, start before end (Q-M10: OBJ-009, OBJ-008, OBJ-012)
        ("DS10..DS1 == 1", "result=DS20,found=C1", "DS10\\.\\.DS1 runs backwards"),
        ("DS1..DD5 == 1", "result=DS20,found=C1", "'DD5' is not in the bank of 'DS1'"),
        ("DS1..DS1 == 1", "result=DS20,found=C1", "DS1\\.\\.DS1 is one address"),
        # a text value hides the order operators, a text constant or a TXT register alike
        # (Q-M10; Inst_Search.dll)
        ('TXT1..TXT10 > "A"', "result=DS20,found=C1", "'>' is not offered for text"),
        ('TXT1..TXT10 <= "A"', "result=DS20,found=C1", "'<=' is not offered for text"),
        ("TXT1..TXT10 >= $41", "result=DS20,found=C1", "'>=' is not offered for text"),
        ("TXT1..TXT10 < TXT20", "result=DS20,found=C1", "'<' is not offered for text"),
        ("DS1..DS10 > TXT20", "result=DS20,found=C1", "'>' is not offered for text"),
        # a hex value above FFFFh is 32-bit (OBJ-005; baseEx.dll decides by value)
        ("DH1..DH10 == 10000h", "result=DS20,found=C1", "'10000h' is above FFFFh"),
        ("DH1..DH10 == 001FFFFh", "result=DS20,found=C1", "'001FFFFh' is above FFFFh"),
    ],
)
def test_refused(tmp_path: Path, expr: str, kw: str, message: str) -> None:
    with pytest.raises(FieldError, match=message):
        _read_af(tmp_path, f"search({expr},{kw})")


@pytest.mark.parametrize(
    "token",
    [
        'search(TXT1..TXT10 == "ADC",result=DS1,found=C1)',
        "search(TXT1..TXT10 == $41,result=DS1,found=C1)",
        "search(DH1..DH10 == 1Fh,result=DS1,found=C1)",
        "search(DF1..DF10 > -1.5,result=DS1,found=C1)",
        "search(TD1..TD10 >= XD0u,result=DS1,found=C1)",
        "search(CTD1..CTD10 < SD1,result=DS1,found=C1)",
        'search(TXT1..TXT10 != "A",result=DS1,found=C1)',
        "search(TXT1..TXT10 == TXT20,result=DS1,found=C1)",
        "search(DH1..DH10 == FFFFh,result=DS1,found=C1)",
        "search(DH1..DH10 == 0FFFFh,result=DS1,found=C1)",
        "search(DH1..DH10 == 00001h,result=DS1,found=C1)",
        # an int32 constant against a DS table (Q-M10, user dialog check 2026-11-11)
        "search(DS1..DS10 > 40000,result=DS20,found=C1)",
    ],
)
def test_accepted(tmp_path: Path, token: str) -> None:
    parsed = _read_af(tmp_path, token)
    assert isinstance(parsed, Search)
    assert parse_af_blob(parsed.build_blob()) == parsed
    assert parsed.to_csv() == token


def test_direct_construction_is_checked() -> None:
    with pytest.raises(FieldError, match="Search.result"):
        Search("DS72", "DS81", "DS71", "DD82", "C81", "==")


@pytest.mark.parametrize("comparison", ["=<", "=", "<>", ""])
def test_unknown_comparison_is_refused(comparison: str) -> None:
    with pytest.raises(FieldError, match="Search.comparison"):
        Search("DS1", "DS10", "5", "DS20", "C1", comparison)


# CLICK's shared constant check (operands.constants.classify; DLL: baseEx.dll,
# CheckInputData) on the search value: OBJ-005 (arc.md Q-M10 ruling).

_INT32 = "is outside -2147483648..2147483647; an integer constant is 32-bit"
_HEX_SIGN = "a hex constant has no sign and at most 8 digits"
_FINITE = "a real constant is a finite number"


@pytest.mark.parametrize(
    ("table", "source", "message"),
    [
        ("DS", "2147483648", _INT32),
        ("DS", "-2147483649", _INT32),
        ("DS", "3000000000", _INT32),
        ("DS", "6000000000", _INT32),
        ("DH", "+1h", _HEX_SIGN),
        ("DH", "-1h", _HEX_SIGN),
        ("DF", "1E999", _FINITE),
        ("DS", "-1E999", _FINITE),
    ],
)
def test_source_refuses_what_the_constant_check_refuses(
    tmp_path: Path, table: str, source: str, message: str
) -> None:
    with pytest.raises(FieldError, match=rf"^Search.source: .* {message}"):
        Search(f"{table}1", f"{table}10", source, "DS20", "C1", "==")
    token = f"search({table}1..{table}10 == {source},result=DS20,found=C1)"
    with pytest.raises(FieldError, match="^Search.source: "):
        _read_af(tmp_path, token)


@pytest.mark.parametrize(
    ("table", "source"),
    [
        ("DS", "2147483647"),
        ("DS", "-2147483648"),
        ("DF", "-1.5E+3"),
        ("DH", "0h"),
        ("DH", "FFFFh"),
        ("TXT", "$00"),
        ("TXT", "$FF"),
        ("TXT", '"$41"'),
        ("TXT", '"' + "A" * 128 + '"'),
    ],
)
def test_source_constant_edges_accepted(table: str, source: str) -> None:
    search = Search(f"{table}1", f"{table}10", source, "DS20", "C1", "==")
    assert parse_af_blob(search.build_blob()) == search


# arc.md Q-B7: $ and one hex digit, and a $ code above FF, are refused only in Compare until
# a capture shows the form CLICK stores (CLICK's shared check accepts both). A Search value
# keeps them as written.
@pytest.mark.parametrize("table", ["TXT", "DS"])
@pytest.mark.parametrize("source", ["$1", "$D", "$d", "$100", "$4142"])
def test_source_dollar_forms_kept_as_written(table: str, source: str) -> None:
    search = Search(f"{table}1", f"{table}10", source, "DS20", "C1", "==")
    assert search.source == source
    assert parse_af_blob(search.build_blob()) == search


@pytest.mark.parametrize(
    "fields",
    [
        {0x6066: "C1", 0x6067: "C10"},  # a bit table
        {0x607A: "Y001"},  # the Result Flag is a C bit
        {0x6066: "DS10", 0x6067: "DS1"},  # backwards
        {0x6065: '"A"', 0x6066: "TXT1", 0x6067: "TXT10", 0x21F7: "2"},  # > on text
        {0x6065: "TXT20", 0x21F7: "2"},  # > on a TXT register
        {0x6065: "10000h", 0x6066: "DH1", 0x6067: "DH10"},  # a 32-bit hex value
        {0x6065: "3000000000"},  # outside int32
        {0x6065: "+1h", 0x6066: "DH1", 0x6067: "DH10"},  # a signed hex value
    ],
)
def test_refused_blob_is_left_unparsed(fields: dict[int, str]) -> None:
    tags = {0x6065: "DS1", 0x6066: "DS1", 0x6067: "DS10", 0x6079: "DS20", 0x607A: "C1"}
    assert from_tags_af("Search", 0x2722, tags) is not None
    assert from_tags_af("Search", 0x2722, tags | fields) is None


@pytest.mark.parametrize(
    ("table", "value"),
    [
        ("DS", "5"),
        ("DD", "-70000"),
        ("DF", "1.5"),
        ("TD", "0"),
        ("CTD", "7"),
        ("DH", "FFFFh"),
        ("TXT", '"A"'),
        ("TXT", "$41"),
    ],
)
def test_search_value_kind_fits_table(table: str, value: str) -> None:
    Search(f"{table}1", f"{table}10", value, "DS20", "C20", "==")


@pytest.mark.parametrize(
    ("table", "value"),
    [
        ("DS", "FFFFh"),
        ("DS", '"A"'),
        ("DS", "$41"),
        ("DH", "5"),
        ("DH", "1.5"),
        ("DH", '"A"'),
        ("TXT", "5"),
        ("TXT", "0Fh"),
        ("TXT", "1.5"),
    ],
)
def test_search_value_kind_must_fit_table(table: str, value: str) -> None:
    with pytest.raises(FieldError, match="^Search.source: "):
        Search(f"{table}1", f"{table}10", value, "DS20", "C20", "==")
