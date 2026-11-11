"""Search operand rules: the table is DS, DD, DH, DF, TD, CTD or TXT, the result a DS, and
the search value a constant or a data register, never a bit (Help CL174).
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
        "search(CTD1..CTD10 < SD1,result=DS1,found=Y001)",
        # the found flag's banks wait on a dialog check: any bank, XD0u included
        "search(DS1..DS10 == 1,result=DS20,found=XD0u)",
        "search(DS1..DS10 == 1,result=DS20,found=YD0u)",
        # whether Search takes a pointer waits on a dialog check
        "search(DS1..DS10 == DS[DS100],result=DS20,found=C1)",
        # bank pairs, order and mixed-bank tables wait on a dialog check
        "search(DS10..DS1 == 1,result=DS20,found=C1)",
        "search(DS1..DD5 == 1,result=DS20,found=C1)",
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


def test_refused_blob_is_left_unparsed() -> None:
    tags = {0x6065: "DS1", 0x6066: "C1", 0x6067: "C10", 0x6079: "DS20", 0x607A: "C1"}
    assert from_tags_af("Search", 0x2722, tags) is None
