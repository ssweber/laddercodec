"""Copy-family operand rules: CLICK v4.00 Help CL173 (Single Copy), CL185 (Fill), CL238
(pointers) and the OBJ-xxx dialog errors in ``SC_ErrorList.ini``.

Each rule is checked through ``read_csv`` (the CSV path) and, for single Copy, through
``Copy.from_csv_token`` too.  A refused blob decodes as raw.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from laddercodec import FieldError, read_csv
from laddercodec.csv import CSV_HEADER
from laddercodec.instructions import from_tags_af, parse_af_blob
from laddercodec.instructions.copy import Copy, Pack, Unpack


def _read_af(tmp_path: Path, af: str) -> object:
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", "C1"] + ["-"] * 30 + [af])
    return read_csv(path)[0].instructions[0]


_REFUSED = [
    # Help CL173: a bit copies to Y or C, a register to a register
    ("copy(X001,DS1)", "can't take 'X001'; a bit copies to Y, C"),
    ("copy(DS1,C1)", "can't take 'DS1'; a numeric register copies to"),
    # a constant never goes into Y or C; a string constant goes to TXT only
    ("copy(5,C1)", "can't take '5'; a number constant copies to"),
    ('copy("A",DS1)', "can't take '\"A\"'; a text constant copies to TXT"),
    ("copy($41,DD1)", r"can't take '\$41'; a text constant copies to TXT"),
    # XD is not a destination
    ("copy(DS1,XD1)", "Copy.destination: 'XD1' is not allowed"),
    # every address goes through check_address
    ("copy(DS4501,DS1)", "outside DS1-DS4500"),
    ("copy(DS1,Q5)", "no CLICK bank 'Q'"),
    ("copy(DS1,DS)", "not a CLICK address"),
    # Help CL238: the pointer is a DS
    ("copy(DS[DD1],DS2)", "Copy.source pointer: 'DD1' is not allowed"),
    ("copy(DS1,QQ[DS1])", r"Copy.destination: 'QQ\[DS1\]' is not allowed"),
    # converters
    ("copy(DS1,TXT1,convert=to_value)", "to_value copies TXT to a number"),
    ("copy(TXT1,TXT2,convert=to_ascii)", "to_ascii copies TXT to a number"),
    ("copy(TXT1,DS1,convert=to_text(suppress_zero=1))", "to_text copies a number to TXT"),
    ("copy(DS1,DD1,convert=to_binary)", "to_binary copies a number to TXT"),
    # Block Copy: no pointers, one bank per range, converts only from TXT
    ("blockcopy(DS[DS1]..DS5,DS10..DS14)", "is a pointer; only a single Copy"),
    ("blockcopy(DS1..DD4,DS10..DS13)", "BlockCopy.source_end: 'DD4' is not in the bank"),
    ("blockcopy(DS1..DS4,DS10..DS4501)", "outside DS1-DS4500"),
    ("blockcopy(TXT1..TXT4,TXT10..TXT1001)", "outside TXT1-TXT1000"),
    ("blockcopy(DS1..DS4,DS10..DS13,convert=to_value)", "to_value needs a TXT source"),
    # Help CL185: Fill takes no bits; TXT and text fill TXT only; nothing fills Y or C
    ("fill(X001,DS1..DS5)", "Fill.value: 'X001' is not allowed"),
    ("fill(TXT1,DS1..DS4)", "can't take 'TXT1'; a TXT register copies to TXT"),
    ("fill(DS1,TXT1..TXT4)", "can't take 'DS1'; a numeric register copies to"),
    ('fill("A",DS1..DS4)', "can't take '\"A\"'; a text constant copies to TXT"),
    ("fill(5,C1..C4)", "Fill.dest_start: 'C1' is not allowed"),
    ("fill(0,DS1..DD5)", "Fill.dest_end: 'DD5' is not in the bank"),
    ("fill(DS[DS1],DS2..DS5)", "is a pointer; only a single Copy"),
    # Pack / Unpack: one module (OBJ-033/035/019), counts (OBJ-027/041/040, 032/039/042)
    ("pack_bits(X016..X101,DD1)", "spans two X modules"),
    ("unpack_to_bits(DS1,Y101..Y201)", "spans two Y modules"),
    ("pack_bits(C1..C17,DS1)", "is 17 bits; a pack into 'DS1' takes at most 16"),
    ("pack_bits(C1..C17,DH1)", "at most 16"),
    ("pack_bits(C1..C33,DD1)", "is 33 bits; a pack into 'DD1' takes at most 32"),
    ("pack_bits(C1..C33,DF1)", "at most 32"),
    ("pack_words(DS1..DS3,DD1)", "is 3 words; a pack into 'DD1' takes at most 2"),
    ("unpack_to_bits(DS1,C1..C17)", "is 17 bits; an unpack from 'DS1' takes at most 16"),
    ("unpack_to_bits(DD1,C1..C33)", "at most 32"),
    ("unpack_to_words(DD1,DS1..DS3)", "is 3 words; an unpack from 'DD1' takes at most 2"),
    ("pack_bits(C1..C2,DS[DS1])", "is a pointer; only a single Copy"),
    ("pack_bits(C1..DS2,DS1)", "Pack.source_end: 'DS2' is not in the bank"),
    # bits / words is the bank kind: the blob has no flag for it
    ("pack_bits(DS1..DS2,DD1)", "'DS1' is a register; bits needs a bit bank"),
    ("pack_words(C1..C2,DS1)", "'C1' is a bit; words needs a register bank"),
    ("unpack_to_bits(DD1,DS1..DS2)", "'DS1' is a register; bits needs a bit bank"),
    ("unpack_to_words(DS1,C1..C16)", "'C1' is a bit; words needs a register bank"),
]


@pytest.mark.parametrize(("token", "message"), _REFUSED)
def test_refused_through_read_csv(tmp_path: Path, token: str, message: str) -> None:
    with pytest.raises(FieldError, match=message):
        _read_af(tmp_path, token)


@pytest.mark.parametrize(("token", "message"), [r for r in _REFUSED if r[0].startswith("copy(")])
def test_copy_from_csv_token_refuses_the_same(token: str, message: str) -> None:
    with pytest.raises(FieldError, match=message):
        Copy.from_csv_token(token)


@pytest.mark.parametrize(
    "token",
    [
        "copy(C1,Y001)",
        "copy(SC1,C1)",
        "copy(XD0u,DS1)",
        "copy(DS1,YD0u)",
        "copy(TXT1,DS1)",
        "copy(DS1,TXT1)",
        "copy(5,TXT1)",
        "copy(1Fh,DH1)",
        "copy(1FH,DH1)",
        "copy(-1.5E+3,DF1)",
        "copy(.5,DF1)",
        "copy($D,TXT1)",
        "copy(DD[DS1],DS1)",
        "copy(DS1,TXT[DS2])",
        "copy(TXT1,DS1,convert=to_value)",
        "copy(DD1,DF1,convert=to_binary)",
        "fill(1,TXT1..TXT3)",
        "fill(XD1,DS1..DS3)",
        "fill(TXT1,TXT2..TXT5)",
        "fill($00,TXT1..TXT4)",
        "blockcopy(TXT1..TXT4,DS1..DS4,convert=to_ascii)",
        "pack_bits(X001..X016,DS1)",
        "pack_bits(C1..C32,DD1)",
        "pack_words(XD0..XD1,DD1)",  # how CLICK counts XD0u is unchecked: no count
        "unpack_to_bits(DD1,C1..C32)",
    ],
)
def test_accepted_through_read_csv(tmp_path: Path, token: str) -> None:
    parsed = _read_af(tmp_path, token)
    assert parse_af_blob(parsed.build_blob()) == parsed  # type: ignore[attr-defined]


def test_copy_csv_paths_agree(tmp_path: Path) -> None:
    token = "copy(DS20,TXT7,oneshot=1,convert=to_text(suppress_zero=1,termination_code=$0D))"
    copy = Copy.from_csv_token(token)
    assert copy == _read_af(tmp_path, token)
    assert copy.to_csv() == token


def test_termination_code_needs_a_number_register_copied_to_text() -> None:
    """CLICK v4's dialog greys the box for TXT -> TXT and constant -> TXT copies."""
    Copy("DS1", "TXT1", format="text", termination_code="$0D")
    Copy("DS1", "TXT1", format="binary", termination_code="$0D")
    for source, destination, fmt in [
        ("DS1", "TXT1", "none"),
        ("TXT1", "TXT2", "none"),
        ("5", "TXT1", "text"),
        ("DD1", "DF1", "binary"),
    ]:
        with pytest.raises(FieldError, match=r"Copy.termination_code: '\$0D'"):
            Copy(source, destination, format=fmt, termination_code="$0D")


@pytest.mark.parametrize(
    "instruction",
    [
        Pack("X001", "X016", "DS1", pack_type="bits"),
        Pack("Y101", "Y108", "DH1", pack_type="bits"),
        Pack("T1", "T16", "DS1", pack_type="bits"),
        Pack("CT1", "CT4", "DS1", pack_type="bits"),
        Pack("SC1", "SC16", "DS1", pack_type="bits"),
        Pack("CTD1", "CTD2", "DD1", pack_type="words"),
        Unpack("DS1", "Y001", "Y016", unpack_type="bits"),
        Unpack("DD1", "CTD1", "CTD2", unpack_type="words"),
    ],
)
def test_pack_kind_decodes_from_the_bank(instruction: Pack | Unpack) -> None:
    """Bits or words comes from the bank, not the first letter (CT, CTD, X, Y, T, SC)."""
    assert parse_af_blob(instruction.build_blob()) == instruction


@pytest.mark.parametrize(
    "tags",
    [
        {0x6074: "X001", 0x6076: "DS1"},  # a bit into a register
        {0x6074: "DS1", 0x6076: "TXT1", 0x2227: "1", 0x1221: "-1", 0x3216: "-1"},  # bad char
        {0x6074: "DS1", 0x6075: "DS4", 0x6076: "DS[DS9]", 0x6077: "DS13", 0x2223: "1"},
        {0x6074: "C1", 0x6075: "C17", 0x6076: "DS1", 0x2223: "3"},  # 17 bits into DS
    ],
)
def test_refused_blob_is_left_unparsed(tags: dict[int, str]) -> None:
    assert from_tags_af("Copy", 0x2721, tags) is None
