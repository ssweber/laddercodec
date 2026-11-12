"""Copy-family operand rules: CLICK v4.00 Help CL173 (Single Copy), CL185 (Fill), CL238
(pointers) and the OBJ-xxx dialog errors in ``SC_ErrorList.ini``.

Each rule is checked through ``read_csv`` (the CSV path) and, for single Copy, through
``Copy.from_csv_token`` too.  A refused blob decodes as raw.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from laddercodec import FieldError, read_csv
from laddercodec.csv import CSV_HEADER
from laddercodec.instructions import from_tags_af, parse_af_blob
from laddercodec.instructions.copy import Copy, Fill, Pack, Unpack


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
    # Help CL238: a pointer addresses C, DS, DD, DH, DF, XD, YD, TD, CTD or TXT
    (
        "copy(X[DS1],C1)",
        r"Copy.source: 'X\[DS1\]' is not allowed; a pointer in Copy.source addresses C, DS,",
    ),
    ("copy(SC[DS1],C1)", r"Copy.source: 'SC\[DS1\]' is not allowed"),
    ("copy(SD[DS1],DS1)", r"Copy.source: 'SD\[DS1\]' is not allowed"),
    ("copy(T[DS1],C1)", r"Copy.source: 'T\[DS1\]' is not allowed"),
    ("copy(C1,Y[DS1])", r"Copy.destination: 'Y\[DS1\]' is not allowed"),
    ("copy(DS1,XD[DS2])", r"Copy.destination: 'XD\[DS2\]' is not allowed"),
    ("copy(DD[DS1+2],DS1)", r"Copy.source pointer: 'DS1\+2' is not a CLICK address"),
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
    # Pack / Unpack: one slot (OBJ-033/035/019), counts (OBJ-027/041/040, 032/039/042)
    ("pack_bits(X016..X101,DD1)", "spans two X slots"),
    ("unpack_to_bits(DS1,Y101..Y201)", "spans two Y slots"),
    # 21-36 is the dual option slot, a slot of its own (Q-A1)
    ("pack_bits(X001..X036,DD1)", r"X001\.\.X036 spans two X slots"),
    ("pack_bits(X015..X022,DS1)", r"X015\.\.X022 spans two X slots"),
    ("pack_bits(X036..X101,DD1)", "spans two X slots"),
    ("unpack_to_bits(DD1,Y016..Y021)", r"Y016\.\.Y021 spans two Y slots"),
    ("pack_bits(X021..X037,DD1)", "Pack.source_end: 'X037' is outside"),
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
    # Single Copy constants (Q-M5): an integer is 32-bit (OBJ-005); hex above FFFFh goes to
    # the 32-bit integer registers only (OBJ-024)
    ("copy(5000000000,DD1)", "Copy.source: '5000000000' is outside -2147483648..2147483647"),
    ("copy(-2147483649,DD1)", "is outside -2147483648..2147483647"),
    ("copy(10000h,DH1)", "can't take '10000h'; a hex constant above FFFFh copies to DD, CTD"),
    ("copy(1FFFFh,DS1)", "a hex constant above FFFFh copies to DD, CTD"),
    ("copy(10000h,TXT1)", "a hex constant above FFFFh copies to DD, CTD"),
    # Block Copy banks (Q-M1): source and destination edits (OBJ-004), pairing rows
    ("blockcopy(DS1..DS3,YD1..YD3)", "BlockCopy.dest_start: 'YD1' is not allowed"),
    ("blockcopy(DS1..DS2,YD0..YD0u)", "BlockCopy.dest_start: 'YD0' is not allowed"),
    ("blockcopy(TD1..TD3,DS1..DS3)", "BlockCopy.source_start: 'TD1' is not allowed"),
    ("blockcopy(CTD1..CTD3,DS1..DS3)", "BlockCopy.source_start: 'CTD1' is not allowed"),
    ("blockcopy(YD1..YD3,DS1..DS3)", "BlockCopy.source_start: 'YD1' is not allowed"),
    ("blockcopy(XD0..XD0u,DS1..DS2)", "BlockCopy.source_start: 'XD0' is not allowed"),
    ("blockcopy(DS1..DS3,T1..T3)", "BlockCopy.dest_start: 'T1' is not allowed"),
    ("blockcopy(TXT1..TXT3,DF1..DF3)", "a block copy from TXT goes to DS, DD, DH, TXT"),
    ("blockcopy(TXT1..TXT3,TD1..TD3)", "a block copy from TXT goes to DS, DD, DH, TXT"),
    ("blockcopy(C1..C3,DS1..DS3)", "a block copy from C goes to Y, C"),
    ("blockcopy(DS1..DS3,TXT1..TXT3)", "a block copy from DS goes to DS, DD, DH, DF, TD, CTD, SD"),
    ("blockcopy(DS1..DS3,C1..C3)", "a block copy from DS goes to DS, DD, DH, DF, TD, CTD, SD"),
    # Block Copy ranges (Q-M3, OBJ-012/009) and the end CLICK computes (Q-M4)
    ("blockcopy(DS1..DS1,DS5..DS5)", r"DS1\.\.DS1 is one address"),
    ("blockcopy(DS4..DS1,DS5..DS8)", r"DS4\.\.DS1 runs backwards"),
    (
        "blockcopy(DS1..DS4,DD1..DD2)",
        r"'DD2' is not where the copy ends; DS1\.\.DS4 fills DD1\.\.DD4",
    ),
    ("blockcopy(DD1..DD4,DS1..DS9)", r"DD1\.\.DD4 fills DS1\.\.DS4"),
    ("blockcopy(C1..C4,Y001..Y016)", r"C1\.\.C4 fills Y001\.\.Y004"),
    # the Block source stays in one slot (Inst_Copy.dll module check); a Y
    # destination run that crosses a slot is not captured yet
    ("blockcopy(X001..X101,C1..C101)", "spans two X slots; the range stays in one 16-point"),
    ("blockcopy(C1..C16,Y010..Y025)", "into Y010 crosses a Y slot; crossing a slot is not"),
    ("blockcopy(X001..X008,Y010..Y021)", "crosses a Y slot"),
    ("blockcopy(C1..C16,Y010..Y101)", "crosses a Y slot"),
    # Pack pairs (Q-M2): X/Y/T/CT/SC pack into DH only; DS into DD/DF; DH into DD
    ("pack_bits(X001..X016,DS1)", "a pack from X goes to DH"),
    ("pack_bits(Y001..Y016,DD1)", "a pack from Y goes to DH"),
    ("pack_bits(T1..T16,DS1)", "a pack from T goes to DH"),
    ("pack_words(DH1..DH2,DF1)", "a pack from DH goes to DD"),
    ("pack_words(DS1..DS2,DH1)", "a pack from DS goes to DD, DF"),
    ("pack_text(TXT1..TXT4,SD1)", "Pack.destination: 'SD1' is not allowed"),
    ("pack_text(TXT1..TXT4,YD0u)", "Pack.destination: 'YD0u' is not allowed"),
    ("pack_bits(C1..C16,YD0u)", "Pack.destination: 'YD0u' is not allowed"),
    ("pack_words(DD1..DD2,DF1)", "Pack.source_start: 'DD1' is not allowed"),
    ("pack_words(XD0..XD1,DD1)", "Pack.source_start: 'XD0' is not allowed"),
    ("pack_bits(C1..C1,DS1)", r"C1\.\.C1 is one address"),
    ("pack_bits(C5..C1,DS1)", r"C5\.\.C1 runs backwards"),
    # Unpack pairs (Q-M2b): only DH unpacks to Y; DS to C only; nothing to DF
    ("unpack_to_bits(DS5,Y001..Y016)", "an unpack from DS goes to C"),
    ("unpack_to_bits(DD5,Y001..Y016)", "an unpack from DD goes to C, DS, DH"),
    ("unpack_to_words(DD1,DF1..DF2)", "Unpack.dest_start: 'DF1' is not allowed"),
    ("unpack_to_words(DD1,YD0..YD0u)", "Unpack.dest_start: 'YD0' is not allowed"),
    ("unpack_to_bits(TXT1,C1..C16)", "Unpack.source: 'TXT1' is not allowed"),
    ("unpack_to_bits(XD0u,C1..C16)", "Unpack.source: 'XD0u' is not allowed"),
    ("unpack_to_bits(DS1,C1..C1)", r"C1\.\.C1 is one address"),
    # Fill's OnOK runs the same range check on its destination (Inst_Copy.dll)
    ("fill(0,DS1..DS1)", r"DS1\.\.DS1 is one address"),
    ("fill(0,DS5..DS1)", r"DS5\.\.DS1 runs backwards"),
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
        "copy($0D,TXT1)",
        "copy(DD[DS1],DS1)",
        "copy(DS1,TXT[DS2])",
        "copy(C[DS1],Y001)",
        "copy(XD[DS1],DS1)",
        "copy(DS1,YD[DS2])",
        "copy(TXT1,DS1,convert=to_value)",
        "copy(DD1,DF1,convert=to_binary)",
        "fill(1,TXT1..TXT3)",
        "fill(XD1,DS1..DS3)",
        "fill(TXT1,TXT2..TXT5)",
        "fill($00,TXT1..TXT4)",
        "blockcopy(TXT1..TXT4,DS1..DS4,convert=to_ascii)",
        "blockcopy(TXT1..TXT4,DH1..DH4,convert=to_value)",
        "blockcopy(TXT1..TXT4,TXT11..TXT14)",
        "blockcopy(DS1..DS4,DD1..DD4)",  # the end counts elements (Q-M4)
        "blockcopy(DD1..DD4,DS1..DS4)",
        "blockcopy(DF1..DF3,CTD1..CTD3)",
        "blockcopy(C1..C16,Y001..Y016)",
        "blockcopy(X021..X036,C1..C16)",
        "blockcopy(C1..C7,Y010..Y016)",
        "blockcopy(X001..X008,Y101..Y108)",
        "pack_text(DS1..DS2,DD1)",  # a non-TXT source is not refused (needs a dialog check)
        "pack_bits(X001..X016,DH1)",
        "pack_bits(X021..X036,DH1)",
        "pack_bits(SC1..SC16,DH1)",
        "pack_bits(C1..C16,DF1)",
        "pack_words(DS1..DS2,DF1)",
        "pack_words(DH1..DH2,DD1)",
        "pack_text(TXT1..TXT4,CTD1)",
        "unpack_to_bits(DH1,Y021..Y036)",
        "unpack_to_bits(DF1,C1..C32)",
        "unpack_to_words(DF1,DH1..DH2)",
        "copy(X021,Y036)",
        "pack_bits(C1..C32,DD1)",
        "unpack_to_bits(DD1,C1..C32)",
        # Single Copy constants (Q-M5)
        "copy(40000,DS1)",
        "copy(3.5,DS1)",
        "copy(100h,DH1)",
        "copy(FFFFh,DS1)",
        "copy(10000h,DD1)",
        "copy(10000h,CTD1)",
        "copy(2147483647,DD1)",
        "copy(-2147483648,DD1)",
    ],
)
def test_accepted_through_read_csv(tmp_path: Path, token: str) -> None:
    parsed = _read_af(tmp_path, token)
    assert parse_af_blob(parsed.build_blob()) == parsed  # type: ignore[attr-defined]


# CLICK's shared constant check (operands.constants.classify; DLL: baseEx.dll,
# CheckInputData) on a single Copy source and a Fill value: OBJ-005.

_TEXT_129 = '"' + "A" * 129 + '"'
_TEXT_128 = '"' + "A" * 128 + '"'
_HEX_SIGN = "a hex constant has no sign and at most 8 digits"
_CHAR_CODE = r"a character code is \$ and two hex digits"
_TEXT_RULE = "a text constant is 1 to 128 characters in quotes, with no quote inside"
_INT32 = "is outside -2147483648..2147483647; an integer constant is 32-bit"

_COPY_SOURCE_REFUSED = [
    ("+1h", "DS9", _HEX_SIGN),
    ("-1h", "DS9", _HEX_SIGN),
    ("+1h", "DD1", _HEX_SIGN),
    ("-1h", "DF1", _HEX_SIGN),
    ("+1h", "DH1", _HEX_SIGN),
    ("-1h", "TXT2", _HEX_SIGN),
    ("100000000h", "DD1", _HEX_SIGN),
    ("0FFFFFFFFh", "DD1", _HEX_SIGN),
    ('""', "TXT2", _TEXT_RULE),
    ('"""', "TXT2", _TEXT_RULE),
    ('"a"b"', "TXT2", _TEXT_RULE),
    (_TEXT_129, "TXT2", _TEXT_RULE),
    ("$1", "TXT2", _CHAR_CODE),
    ("$D", "TXT2", _CHAR_CODE),
    ("$100", "TXT2", _CHAR_CODE),
    ("$4142", "TXT2", _CHAR_CODE),
]


@pytest.mark.parametrize(("source", "destination", "message"), _COPY_SOURCE_REFUSED)
def test_copy_source_refuses_what_the_constant_check_refuses(
    source: str, destination: str, message: str
) -> None:
    with pytest.raises(FieldError, match=rf"^Copy.source: .* {message}"):
        Copy(source, destination)


@pytest.mark.parametrize(
    "token",
    ['copy("",TXT2)', "copy($1,TXT2)", "copy(+1h,DD1)", f"copy({_TEXT_129},TXT2)"],
)
def test_copy_source_constant_refused_through_read_csv(tmp_path: Path, token: str) -> None:
    with pytest.raises(FieldError, match="^Copy.source: "):
        _read_af(tmp_path, token)


@pytest.mark.parametrize(
    ("source", "destination"),
    [
        ("FFFFFFFFh", "DD1"),
        ("0FFFFh", "DS9"),
        ("10000h", "CTD1"),
        (_TEXT_128, "TXT2"),
        ('"A"', "TXT2"),
        ('"$41"', "TXT2"),
        ('"é"', "TXT2"),  # non-ASCII text into TXT has no ruling yet: accepted
        ("$00", "TXT2"),
        ("$FF", "TXT2"),
        ("$0d", "TXT2"),
        ("5", "TXT2"),  # a number into TXT has no ruling yet: accepted
        ("2147483647", "DD1"),
        ("-2147483648", "DD1"),
    ],
)
def test_copy_source_constant_edges_accepted(source: str, destination: str) -> None:
    copy = Copy(source, destination)
    assert parse_af_blob(copy.build_blob()) == copy


_FILL_VALUE_REFUSED = [
    ("2147483648", "DS52", "DS55", _INT32),
    ("-2147483649", "DS52", "DS55", _INT32),
    ("3000000000", "DS52", "DS55", _INT32),
    ("6000000000", "DS52", "DS55", _INT32),
    ("+1h", "DS52", "DS55", _HEX_SIGN),
    ("-1h", "DS52", "DS55", _HEX_SIGN),
    ("100000000h", "DS52", "DS55", _HEX_SIGN),
    ("0FFFFFFFFh", "DS52", "DS55", _HEX_SIGN),
    ("2147483648", "TXT2", "TXT5", _INT32),
    ("+1h", "TXT2", "TXT5", _HEX_SIGN),
    ("100000000h", "TXT2", "TXT5", _HEX_SIGN),
    ('""', "TXT2", "TXT5", _TEXT_RULE),
    ('"""', "TXT2", "TXT5", _TEXT_RULE),
    ('"a"b"', "TXT2", "TXT5", _TEXT_RULE),
    (_TEXT_129, "TXT2", "TXT5", _TEXT_RULE),
    ("$1", "TXT2", "TXT5", _CHAR_CODE),
    ("$D", "TXT2", "TXT5", _CHAR_CODE),
    ("$100", "TXT2", "TXT5", _CHAR_CODE),
    ("$4142", "TXT2", "TXT5", _CHAR_CODE),
]


@pytest.mark.parametrize(("value", "start", "end", "message"), _FILL_VALUE_REFUSED)
def test_fill_value_refuses_what_the_constant_check_refuses(
    value: str, start: str, end: str, message: str
) -> None:
    with pytest.raises(FieldError, match=rf"^Fill.value: .* {message}"):
        Fill(value, start, end)


@pytest.mark.parametrize(
    "token", ['fill("",TXT2..TXT5)', "fill(3000000000,DS52..DS55)", "fill(-1h,DS52..DS55)"]
)
def test_fill_value_constant_refused_through_read_csv(tmp_path: Path, token: str) -> None:
    with pytest.raises(FieldError, match="^Fill.value: "):
        _read_af(tmp_path, token)


@pytest.mark.parametrize(
    ("value", "start", "end"),
    [
        ("2147483647", "DS52", "DS55"),
        ("-2147483648", "DS52", "DS55"),
        ("FFFFh", "DS52", "DS55"),
        # a 32-bit hex Fill and a number into TXT have no ruling yet: accepted
        ("10000h", "DS52", "DS55"),
        ("FFFFFFFFh", "DS52", "DS55"),
        ("5", "TXT2", "TXT5"),
        (_TEXT_128, "TXT2", "TXT5"),
        ('"é"', "TXT2", "TXT5"),
        ("$00", "TXT2", "TXT5"),
        ("$7E", "TXT2", "TXT5"),
    ],
)
def test_fill_value_constant_edges_accepted(value: str, start: str, end: str) -> None:
    fill = Fill(value, start, end)
    assert parse_af_blob(fill.build_blob()) == fill


@pytest.mark.parametrize("fmt", ["text", "binary"])
@pytest.mark.parametrize("code", ["abc", "1", "DS1", "1.5", "FFFFh", '""', "none", "00", ""])
def test_termination_code_is_a_character_code(fmt: str, code: str) -> None:
    """The blob stores a termination code only as a character code (OBJ-036)."""
    with pytest.raises(FieldError, match=r"^Copy.termination_code: .* is not allowed; it is a"):
        Copy("DS20", "TXT7", format=fmt, termination_code=code)


@pytest.mark.parametrize("fmt", ["text", "binary"])
@pytest.mark.parametrize(("code", "stored"), [("0", "0"), ("$00", "$00"), ("$FF", "$FF")])
def test_termination_code_edges_accepted(fmt: str, code: str, stored: str) -> None:
    copy = Copy("DS20", "TXT7", format=fmt, termination_code=code)
    assert copy.termination_code == stored
    assert parse_af_blob(copy.build_blob()) == copy


@pytest.mark.parametrize(
    "tags",
    [
        {0x6074: "+1h", 0x6076: "DS9"},
        {0x6074: "100000000h", 0x6076: "DD1"},
        {0x6074: '""', 0x6076: "TXT2"},
        {0x6074: "$4142", 0x6076: "TXT2"},
        {0x6074: "3000000000", 0x6076: "DS52", 0x6077: "DS55", 0x2223: "2"},
        {0x6074: "$1", 0x6076: "TXT2", 0x6077: "TXT5", 0x2223: "2"},
    ],
)
def test_refused_constant_blob_is_left_unparsed(tags: dict[int, str]) -> None:
    assert from_tags_af("Copy", 0x2721, tags) is None


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


@pytest.mark.parametrize("option", ["suppress_zero", "exponential"])
@pytest.mark.parametrize("value", ["2", "5", "-1", ""])
def test_text_options_are_zero_or_one(option: str, value: str) -> None:
    with pytest.raises(FieldError, match=f"Copy.{option}: '{value}' is not allowed"):
        Copy("DF1", "TXT1", format="text", **{option: value})


@pytest.mark.parametrize(("source", "option"), [("DS1", "suppress_zero"), ("DF1", "exponential")])
def test_text_options_keep_their_bytes(source: str, option: str) -> None:
    for value in ("0", "1"):
        copy = Copy(source, "TXT1", format="text", **{option: value})
        assert parse_af_blob(copy.build_blob()) == copy


@pytest.mark.parametrize(
    "instruction",
    [
        Pack("X001", "X016", "DH1", pack_type="bits"),
        Pack("Y101", "Y108", "DH1", pack_type="bits"),
        Pack("X021", "X036", "DH1", pack_type="bits"),
        Unpack("DH1", "Y021", "Y036", unpack_type="bits"),
        Pack("T1", "T16", "DH1", pack_type="bits"),
        Pack("CT1", "CT4", "DH1", pack_type="bits"),
        Pack("SC1", "SC16", "DH1", pack_type="bits"),
        Pack("DH1", "DH2", "DD1", pack_type="words"),
        Unpack("DH1", "Y001", "Y016", unpack_type="bits"),
        Unpack("DD1", "DH1", "DH2", unpack_type="words"),
    ],
)
def test_pack_kind_decodes_from_the_bank(instruction: Pack | Unpack) -> None:
    """Bits or words comes from the bank, not the first letter (CT, X, Y, T, SC, DH)."""
    assert parse_af_blob(instruction.build_blob()) == instruction


@pytest.mark.parametrize(
    "tags",
    [
        {0x6074: "X001", 0x6076: "DS1"},  # a bit into a register
        {0x6074: "DS1", 0x6076: "TXT1", 0x2227: "1", 0x1221: "-1", 0x3216: "-1"},  # bad char
        {0x6074: "DS1", 0x6075: "DS4", 0x6076: "DS[DS9]", 0x6077: "DS13", 0x2223: "1"},
        {0x6074: "C1", 0x6075: "C17", 0x6076: "DS1", 0x2223: "3"},  # 17 bits into DS
        {0x6074: "X016", 0x6075: "X021", 0x6076: "DD1", 0x2223: "3"},  # two X slots
        {0x6074: "X001", 0x6075: "X036", 0x6076: "DD1", 0x2223: "3"},  # two X slots
        {0x6074: "X001", 0x6075: "X016", 0x6076: "DS1", 0x2223: "3"},  # X packs into DH only
        {0x6074: "DS5", 0x6076: "Y001", 0x6077: "Y016", 0x2223: "4"},  # DS unpacks to C only
        {0x6074: "DS1", 0x6075: "DS3", 0x6076: "YD1", 0x6077: "YD3", 0x2223: "1"},  # YD dest
        {0x6074: "DS1", 0x6075: "DS4", 0x6076: "DD1", 0x6077: "DD2", 0x2223: "1"},  # end
        {0x6074: "DS1", 0x6075: "DS1", 0x6076: "DS5", 0x6077: "DS5", 0x2223: "1"},  # one
        {0x6074: "0", 0x6076: "DS5", 0x6077: "DS1", 0x2223: "2"},  # fill runs backwards
        {0x6074: "C1", 0x6075: "C16", 0x6076: "Y010", 0x6077: "Y025", 0x2223: "1"},  # Y slot
        {0x6074: "10000h", 0x6076: "DH1"},  # hex above FFFFh into DH
        {0x6074: "5000000000", 0x6076: "DD1"},  # outside int32
    ],
)
def test_refused_blob_is_left_unparsed(tags: dict[int, str]) -> None:
    assert from_tags_af("Copy", 0x2721, tags) is None


@pytest.mark.parametrize(("first", "last"), [("X001", "X036"), ("X015", "X022"), ("X016", "X021")])
def test_pack_unpack_constructors_keep_to_one_slot(first: str, last: str) -> None:
    """The dual option slot, 21-36, is a 16-point slot of its own (Q-A1)."""
    message = f"Pack.source_end: {first}..{last} spans two X slots"
    with pytest.raises(FieldError, match=re.escape(message)):
        Pack(first, last, "DD1", pack_type="bits")
    y_first, y_last = "Y" + first[1:], "Y" + last[1:]
    message = f"Unpack.dest_end: {y_first}..{y_last} spans two Y slots"
    with pytest.raises(FieldError, match=re.escape(message)):
        Unpack("DD1", y_first, y_last, unpack_type="bits")
