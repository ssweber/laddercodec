"""Tests for the rules on Search's operands.

The table is DS, DD, DH, DF, TD, CTD or TXT. The result is a DS. The search value is a
constant or a data register, never a bit. The rules for the Result Flag, pointers, the
table range, text operators and hex values apply only to Search.
"""

from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

import pytest

from laddercodec import FieldError, decode, encode, read_csv, write_csv
from laddercodec.binary_helpers import _build_blob
from laddercodec.csv import CSV_HEADER
from laddercodec.decode_program import _scr_box
from laddercodec.instructions import from_tags_af, parse_af_blob
from laddercodec.instructions.search import Search
from laddercodec.operands.unchecked import refusals
from tests.kept_refusals import kept


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
        ("C1..C10 == 1", "result=DS1,found=C20", "Search.table_start: 'C1..C10' is not allowed"),
        ("DS1..SD10 == 1", "result=DS1,found=C20", "Search.table_end: 'SD10' is not allowed"),
        ("XD1..XD3 == 1", "result=DS1,found=C20", "Search.table_start: 'XD1..XD3' is not allowed"),
        ("DS1..DS10 == 1", "result=DD1,found=C20", "Search.result: 'DD1' is not allowed"),
        ("DS1..DS10 == 1", "result=C1,found=C20", "Search.result: 'C1' is not allowed"),
        ("DS1..DS10 == X001", "result=DS20,found=C20", "Search.value: 'X001' is not allowed"),
        ("DS1..DS10 == C5", "result=DS20,found=C20", "Search.value: 'C5' is not allowed"),
        ("DS1..DS10 == DS4501", "result=DS20,found=C20", "outside DS1-DS4500"),
        ("DS1..DS10 == 1", "result=DS20,found=C2001", "Search.found: 'C2001' is outside"),
        ("DS1..DS10 == foo", "result=DS20,found=C20", "Search.value: 'foo' is not a CLICK"),
        # the Result Flag is a C bit (OBJ-004)
        ("DS1..DS10 == 1", "result=DS20,found=Y001", "Search.found: 'Y001' is not allowed"),
        ("DS1..DS10 == 1", "result=DS20,found=XD0u", "Search.found: 'XD0u' is not allowed"),
        ("DS1..DS10 == 1", "result=DS20,found=YD0u", "Search.found: 'YD0u' is not allowed"),
        # Search refuses a pointer
        ("DS1..DS10 == DS[DS100]", "result=DS20,found=C1", "Search.value: 'DS\\[DS100\\]' is a"),
        ("DS1..DS10 == 1", "result=DS[DS1],found=C1", "Search.result: 'DS\\[DS1\\]' is a"),
        ("DS[DS1]..DS10 == 1", "result=DS20,found=C1", "Search.table_start: 'DS\\[DS1\\]' is a"),
        # the table is in one bank, and its start comes before its end (OBJ-009, OBJ-008,
        # OBJ-012)
        ("DS10..DS1 == 1", "result=DS20,found=C1", "DS10\\.\\.DS1 runs backwards"),
        ("DS1..DD5 == 1", "result=DS20,found=C1", "'DD5' is not in the bank of 'DS1'"),
        ("DS1..DS1 == 1", "result=DS20,found=C1", "DS1\\.\\.DS1 is one address"),
        # CLICK offers no order operator for a text value, either a text constant or a TXT
        # register
        ('TXT1..TXT10 > "A"', "result=DS20,found=C1", "'>' is not offered for text"),
        ('TXT1..TXT10 <= "A"', "result=DS20,found=C1", "'<=' is not offered for text"),
        ("TXT1..TXT10 >= $41", "result=DS20,found=C1", "'>=' is not offered for text"),
        ("TXT1..TXT10 < TXT20", "result=DS20,found=C1", "'<' is not offered for text"),
        ("DS1..DS10 > TXT20", "result=DS20,found=C1", "'>' is not offered for text"),
        # a hex value above FFFFh is 32-bit and is refused (OBJ-005). CLICK's shared input
        # check decides by the value, not by the number of digits.
        ("DH1..DH10 == 10000h", "result=DS20,found=C1", "10000h is above FFFFh"),
        ("DH1..DH10 == 001FFFFh", "result=DS20,found=C1", "001FFFFh is above FFFFh"),
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
        "search(DH1..DH10 >= XD0u,result=DS1,found=C1)",
        "search(TD1..TD10 >= DF1,result=DS1,found=C1)",
        "search(CTD1..CTD10 < SD1,result=DS1,found=C1)",
        'search(TXT1..TXT10 != "A",result=DS1,found=C1)',
        "search(TXT1..TXT10 == TXT20,result=DS1,found=C1)",
        "search(DH1..DH10 == FFFFh,result=DS1,found=C1)",
        "search(DH1..DH10 == 0FFFFh,result=DS1,found=C1)",
        "search(DH1..DH10 == 00001h,result=DS1,found=C1)",
        # an int32 constant against a DS table
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
    with pytest.raises(FieldError, match="Search.op"):
        Search("DS1", "DS10", "5", "DS20", "C1", comparison)


# The search value goes through CLICK's shared constant check, which
# operands.constants.classify implements (OBJ-005).

_INT32 = r"is outside -2147483648 to 2147483647 \(OBJ-005\)"
_HEX_SIGN = "a hex constant has no sign$"
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
    with pytest.raises(FieldError, match=rf"^Search.value: .* {message}"):
        Search(f"{table}1", f"{table}10", source, "DS20", "C1", "==")
    token = f"search({table}1..{table}10 == {source},result=DS20,found=C1)"
    with pytest.raises(FieldError, match="^Search.value: "):
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


# A Search value accepts a $ code as $ and one or two hex digits. `$`, `$100` and `$4142`
# are refused.
@pytest.mark.parametrize("table", ["TXT", "DS"])
@pytest.mark.parametrize("source", ["$", "$100", "$4142", "$G1"])
def test_source_other_dollar_forms_refused(table: str, source: str) -> None:
    with pytest.raises(FieldError, match=r"^Search.value: .* \$ and one or two hex digits"):
        Search(f"{table}1", f"{table}10", source, "DS20", "C1", "==")


@pytest.mark.parametrize("source", ["$1", "$D", "$d"])
def test_source_one_digit_code_kept_as_typed(tmp_path: Path, source: str) -> None:
    search = Search("TXT1", "TXT10", source, "DS20", "C1", "==")
    assert search.value == source
    token = f"search(TXT1..TXT10 == {source},result=DS20,found=C1)"
    assert search.to_csv() == token
    assert _read_af(tmp_path, token) == search
    assert parse_af_blob(search.build_blob()) == search
    # A character code searches TXT only.
    with pytest.raises(FieldError, match="^Search.value: .* is a char value, which searches TXT"):
        Search("DS1", "DS10", source, "DS20", "C1", "==")


@pytest.mark.parametrize(
    ("fields", "refused"),
    [
        ({0x6066: "C1", 0x6067: "C10"}, ["table_start"]),  # a bit table, one refusal
        ({0x607A: "Y001"}, ["found"]),  # the Result Flag is a C bit
        ({0x6066: "DS10", 0x6067: "DS1"}, ["table_end"]),  # backwards
        (
            {0x6065: '"A"', 0x6066: "TXT1", 0x6067: "TXT10", 0x21F7: "2"},  # > on text
            ["op"],
        ),
        ({0x6065: "TXT20", 0x6066: "TXT1", 0x6067: "TXT10", 0x21F7: "2"}, ["op"]),  # > on TXT
        ({0x6065: "TXT20"}, ["value"]),  # a TXT value against a DS table
        ({0x6065: "10000h", 0x6066: "DH1", 0x6067: "DH10"}, ["value"]),  # a 32-bit hex value
        ({0x6065: "3000000000"}, ["value"]),  # outside int32
        ({0x6065: "+1h", 0x6066: "DH1", 0x6067: "DH10"}, ["value"]),  # a signed hex value
    ],
)
def test_refused_blob_keeps_its_refusal(fields: dict[int, str], refused: list[str]) -> None:
    tags = {0x6065: "DS1", 0x6066: "DS1", 0x6067: "DS10", 0x6079: "DS20", 0x607A: "C1"}
    assert kept(from_tags_af("Search", 0x2722, tags)) is not None
    search = from_tags_af("Search", 0x2722, tags | fields)
    assert isinstance(search, Search)
    kept(search, *(f"Search.{name}" for name in refused))


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
        # $ and three hex digits is no character code, and $ and one is a code for TXT only
        ("DS", "$4"),
        ("DS", "$123"),
        ("DH", "$4"),
        ("DH", "$123"),
        ("TXT", "$123"),
    ],
)
def test_search_value_kind_must_fit_table(table: str, value: str) -> None:
    with pytest.raises(FieldError, match="^Search.value: "):
        Search(f"{table}1", f"{table}10", value, "DS20", "C20", "==")


# An address value is in the compare group of the table: hex (DH, XD, YD), numeric (DS, DD,
# DF, TD, CTD, SD) or text (TXT).
@pytest.mark.parametrize(
    ("table", "value"),
    [
        ("DS", "DS20"),
        ("DS", "DD20"),
        ("DS", "DF20"),
        ("DS", "TD20"),
        ("DS", "CTD20"),
        ("DS", "SD20"),
        ("DF", "DS20"),
        ("DH", "DH20"),
        ("DH", "XD0"),
        ("DH", "YD0u"),
        ("TXT", "TXT20"),
    ],
)
def test_search_value_address_in_the_table_group(table: str, value: str) -> None:
    Search(f"{table}1", f"{table}10", value, "DS30", "C1", "==")


@pytest.mark.parametrize(
    ("table", "value", "group"),
    [
        ("DS", "TXT20", "text"),
        ("DS", "XD0u", "hex"),
        ("DS", "DH20", "hex"),
        ("DD", "YD0", "hex"),
        ("DH", "DS20", "numeric"),
        ("DH", "TXT20", "text"),
        ("TXT", "DS20", "numeric"),
        ("TXT", "XD0", "hex"),
    ],
)
def test_search_value_address_outside_the_table_group_refused(
    table: str, value: str, group: str
) -> None:
    with pytest.raises(FieldError, match=rf"^Search.value: .* is a {group} address") as info:
        Search(f"{table}1", f"{table}10", value, "DS30", "C1", "==")
    assert info.value.click_id == "OBJ-004"


# ---------------------------------------------------------------------------
# A quote inside a Search text value
# ---------------------------------------------------------------------------

#: Search values with a quote between the outer quotes. The Search matches each character
#: between the outer quotes as typed, and each quote is one character.
_QUOTED = ['"A"B"', '"A""B"', '""""', '"""', '"A",B"', '"Hi", Bob"', '"A","B"', '"["']

#: A rung to hold one Search: CLICK's save of a single Copy into TXT1.
_RUNG = Path(__file__).resolve().parents[1] / "fixtures" / "v4_captures" / "copy_forms"


def _quoted(value: str) -> Search:
    return Search("TXT1", "TXT10", value, "DS30", "C1", "==")


@pytest.mark.parametrize("value", _QUOTED)
def test_a_quote_inside_a_search_value_is_kept_as_typed(tmp_path: Path, value: str) -> None:
    search = _quoted(value)
    assert search.value == value
    assert not refusals(search)
    token = f"search(TXT1..TXT10 == {value},result=DS30,found=C1)"
    assert search.to_csv() == token
    assert _read_af(tmp_path, token) == search
    assert parse_af_blob(search.build_blob()) == search


@pytest.mark.parametrize("value", _QUOTED)
def test_a_search_value_with_a_quote_round_trips(tmp_path: Path, value: str) -> None:
    """write_csv writes the Search, read_csv reads it back, and decode() reads what encode()
    writes."""
    [rung] = decode((_RUNG / "case21.bin").read_bytes())
    rung = replace(rung, instructions=[_quoted(value), ""])
    path = tmp_path / "written.csv"
    write_csv(path, [rung])
    assert [t for t in read_csv(path)[0].instructions if t] == [_quoted(value)]
    [back] = decode(encode(rung))
    assert [t for t in back.instructions if t] == [_quoted(value)]


#: CLICK's save of ``search(TXT1..TXT10 == "A"B",result=DS30,found=C101)``, as the clipboard
#: holds it.
_SAVED = {
    0x6065: '"A"B"',
    0x6066: "TXT1",
    0x6067: "TXT10",
    0x6079: "DS30",
    0x607A: "C101",
    0x1277: "0",
    0x3218: "8964",
    0x11F8: "0",
    0x21F7: "0",
}


def test_clicks_save_of_a_search_value_with_a_quote_decodes_as_the_search() -> None:
    blob = _build_blob("Search", 0x2722, (*_SAVED, 0x0000), [*_SAVED.values(), ""])
    found = parse_af_blob(blob)
    assert found == Search("TXT1", "TXT10", '"A"B"', "DS30", "C101", "==")
    assert not refusals(found)
    assert found.build_blob() == blob
    # The program file stores no flag that is off.
    stored = {k: v for k, v in _SAVED.items() if k not in (0x1277, 0x11F8)}
    assert _scr_box("Search", 0x2722, stored, b"\x01", {}, {}, b"\x02\x02") == found


@pytest.mark.parametrize("value", ['"A",B"', '"A"B"'])
def test_a_decoded_search_value_with_a_quote_writes(tmp_path: Path, value: str) -> None:
    """decode() reads the save as the Search, and write_csv writes it."""
    stored = {k: v for k, v in _SAVED.items() if k not in (0x1277, 0x11F8)} | {0x6065: value}
    [rung] = decode((_RUNG / "case21.bin").read_bytes())
    box = _scr_box("Search", 0x2722, stored, b"\x01", {}, {}, b"\x02\x02")
    assert box == Search("TXT1", "TXT10", value, "DS30", "C101", "==")
    path = tmp_path / "written.csv"
    write_csv(path, [replace(rung, instructions=[box, ""])])
    assert [t for t in read_csv(path)[0].instructions if t] == [box]


def test_22_searches_for_a_lone_quote() -> None:
    search = _quoted("$22")
    assert search.to_csv() == "search(TXT1..TXT10 == $22,result=DS30,found=C1)"
    assert parse_af_blob(search.build_blob()) == search


@pytest.mark.parametrize(
    ("value", "says"),
    [
        ('"' + "x" * 128 + '""', "a text constant is 1 to 128 characters in quotes"),
        ('"A"\x00"', "no NUL"),
    ],
)
def test_a_search_value_with_a_quote_keeps_the_text_rules(value: str, says: str) -> None:
    """A Search value with a quote inside it is still 1 to 128 characters that CLICK keeps."""
    with pytest.raises(FieldError, match="^Search.value: ") as info:
        _quoted(value)
    assert says in str(info.value)


def test_an_empty_search_text_names_the_blank_character_code() -> None:
    with pytest.raises(FieldError) as info:
        _quoted('""')
    assert str(info.value) == (
        'Search.value: "" is refused; a text constant is 1 to 128 characters in quotes. '
        "Write $00 for the blank character."
    )
