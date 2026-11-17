"""Tests the operand rules of the Copy family and the OBJ-xxx errors of CLICK's dialogs.

The family is single Copy, Block Copy, Fill, Pack and Unpack, and the rules include pointers.
The tests check the rules through the constructors, through ``read_csv`` and, for a single
Copy, through ``Copy.from_csv_token``. A blob that breaks a rule decodes to the instruction
with the refusal kept on it, or in some cases stays raw.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from laddercodec import AddressError, FieldError, Reason, read_csv
from laddercodec.csv import CSV_HEADER
from laddercodec.instructions import from_tags_af, parse_af_blob
from laddercodec.instructions.comparison import CompareContact
from laddercodec.instructions.copy import BlockCopy, Copy, Fill, Pack, Unpack
from laddercodec.instructions.raw import _decompose_blob
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


#: The message pattern for an integer outside int32.
INT_RULE = r"is outside -2147483648 to 2147483647 \(OBJ-005\)"

_REFUSED = [
    # a bit copies to Y or C, a register to a register
    ("copy(X001,DS1)", "can't take 'X001'; a bit copies to Y, C"),
    ("copy(DS1,C1)", "can't take 'DS1'; a numeric register copies to"),
    # no constant goes into Y or C. A text constant goes into TXT only.
    ("copy(5,C1)", "can't take '5'; a number constant copies to"),
    ('copy("A",DS1)', "can't take '\"A\"'; a text constant copies to TXT"),
    ("copy($41,DD1)", r"can't take '\$41'; a text constant copies to TXT"),
    # XD is not a destination
    ("copy(DS1,XD1)", "Copy.dest: 'XD1' is not allowed"),
    # every address goes through check_address
    ("copy(DS4501,DS1)", "outside DS1-DS4500"),
    ("copy(DS1,Q5)", "no CLICK bank 'Q'"),
    ("copy(DS1,DS)", "not a CLICK address"),
    # the pointer index is a DS register
    (
        "copy(DS[DD1],DS2)",
        "Copy.source pointer: 'DD1' is not allowed",
    ),
    ("copy(DS1,QQ[DS1])", r"Copy.dest: 'QQ\[DS1\]' is not allowed"),
    # a pointer addresses C, DS, DD, DH, DF, XD, YD, TD, CTD or TXT
    (
        "copy(X[DS1],C1)",
        r"Copy.source: 'X\[DS1\]' is not allowed; a pointer in Copy.source addresses C, DS,",
    ),
    ("copy(SC[DS1],C1)", r"Copy.source: 'SC\[DS1\]' is not allowed"),
    ("copy(SD[DS1],DS1)", r"Copy.source: 'SD\[DS1\]' is not allowed"),
    ("copy(T[DS1],C1)", r"Copy.source: 'T\[DS1\]' is not allowed"),
    ("copy(C1,Y[DS1])", r"Copy.dest: 'Y\[DS1\]' is not allowed"),
    ("copy(DS1,XD[DS2])", r"Copy.dest: 'XD\[DS2\]' is not allowed"),
    (
        "copy(DD[DS1+2],DS1)",
        r"Copy.source pointer: 'DS1\+2' is not a CLICK address",
    ),
    # converters
    ("copy(DS1,TXT1,convert=to_value)", "to_value copies TXT to a number"),
    ("copy(TXT1,TXT2,convert=to_ascii)", "to_ascii copies TXT to a number"),
    ("copy(TXT1,DS1,convert=to_text(suppress_zero=1))", "to_text copies a number to TXT"),
    ("copy(DS1,DD1,convert=to_binary)", "to_binary copies a number to TXT"),
    # Block Copy takes no pointers, keeps each range in one bank and converts only from TXT
    ("blockcopy(DS[DS1]..DS5,DS10..DS14)", "is a pointer; only a single Copy"),
    ("blockcopy(DS1..DD4,DS10..DS13)", "BlockCopy.source_end: 'DD4' is not in the bank"),
    ("blockcopy(DS1..DS4,DS10..DS4501)", "outside DS1-DS4500"),
    ("blockcopy(TXT1..TXT4,TXT10..TXT1001)", "outside TXT1-TXT1000"),
    ("blockcopy(DS1..DS4,DS10..DS13,convert=to_value)", "to_value needs a TXT source"),
    # Fill takes no bits. A TXT register or a text constant fills TXT only. Nothing fills Y or C.
    ("fill(X001,DS1..DS5)", "Fill.value: 'X001' is not allowed"),
    ("fill(TXT1,DS1..DS4)", "can't take 'TXT1'; a TXT register copies to TXT"),
    ("fill(DS1,TXT1..TXT4)", "can't take 'DS1'; a numeric register copies to"),
    ('fill("A",DS1..DS4)', "can't take '\"A\"'; a text constant copies to TXT"),
    ("fill(5,C1..C4)", "Fill.dest_start: 'C1' is not allowed"),
    ("fill(0,DS1..DD5)", "Fill.dest_end: 'DD5' is not in the bank"),
    ("fill(DS[DS1],DS2..DS5)", "is a pointer; only a single Copy"),
    # Pack and Unpack keep a range in one slot (OBJ-033/035/1009) and limit its size
    # (OBJ-027/041/040, 032/039/042)
    ("pack_bits(X016..X101,DD1)", "spans two X slots"),
    ("unpack_to_bits(DH1,Y101..Y201)", "spans two Y slots"),
    # 21-36 is the dual option slot, a slot of its own
    ("pack_bits(X001..X036,DD1)", r"X001\.\.X036 spans two X slots"),
    ("pack_bits(X015..X022,DS1)", r"X015\.\.X022 spans two X slots"),
    ("pack_bits(X036..X101,DD1)", "spans two X slots"),
    ("unpack_to_bits(DH1,Y016..Y021)", r"Y016\.\.Y021 spans two Y slots"),
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
    # the bank sets the kind, bits or words. The blob has no flag for it.
    ("pack_bits(DS1..DS2,DD1)", "'DS1' is a register; bits needs a bit bank"),
    ("pack_words(C1..C2,DS1)", "'C1' is a bit; words needs a register bank"),
    # a TXT source packs only as pack_text, and pack_text needs one
    ("pack_text(DS1..DS2,DD1)", "'DS1' is not a TXT register; pack_text takes a TXT source"),
    ("pack_text(C1..C2,DS1)", "'C1' is not a TXT register; pack_text takes a TXT source"),
    ("pack_words(TXT1..TXT2,DS1)", "'TXT1' is a TXT register; pack_words has no TXT source"),
    ("pack_bits(TXT1..TXT2,DS1)", "'TXT1' is a TXT register; pack_bits has no TXT source"),
    ("unpack_to_bits(DD1,DS1..DS2)", "'DS1' is a register; bits needs a bit bank"),
    ("unpack_to_words(DS1,C1..C16)", "'C1' is a bit; words needs a register bank"),
    # Single Copy constants. An integer is 32-bit (OBJ-005). A hex constant above FFFFh goes
    # into the 32-bit integer registers only (OBJ-024).
    ("copy(5000000000,DD1)", "Copy.source: '5000000000' " + INT_RULE),
    ("copy(-2147483649,DD1)", INT_RULE),
    ("copy(10000h,DH1)", "can't take '10000h'; a hex constant above FFFFh copies to DD, CTD"),
    ("copy(1FFFFh,DS1)", "a hex constant above FFFFh copies to DD, CTD"),
    ("copy(10000h,TXT1)", "a hex constant above FFFFh copies to DD, CTD"),
    # Block Copy banks. Some banks are refused as a source or a destination (OBJ-004), and
    # each source bank copies only to certain destination banks.
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
    # Block Copy ranges (OBJ-012/009). The destination end must be the one that CLICK
    # computes from the source range.
    ("blockcopy(DS1..DS1,DS5..DS5)", r"DS1\.\.DS1 is one address"),
    ("blockcopy(DS4..DS1,DS5..DS8)", r"DS4\.\.DS1 runs backwards"),
    (
        "blockcopy(DS1..DS4,DD1..DD2)",
        r"'DD2' is not where the copy ends; DS1\.\.DS4 fills DD1\.\.DD4",
    ),
    ("blockcopy(DD1..DD4,DS1..DS9)", r"DD1\.\.DD4 fills DS1\.\.DS4"),
    ("blockcopy(C1..C4,Y001..Y016)", r"C1\.\.C4 fills Y001\.\.Y004"),
    # A Block Copy source stays in one slot. laddercodec refuses a Y destination that
    # crosses a slot, because no capture shows how CLICK saves one.
    ("blockcopy(X001..X101,C1..C101)", "spans two X slots; the range stays in one 16-point"),
    ("blockcopy(C1..C16,Y010..Y025)", "into Y010 crosses a Y slot; crossing a slot is not"),
    ("blockcopy(X001..X008,Y010..Y021)", "crosses a Y slot"),
    ("blockcopy(C1..C16,Y010..Y101)", "crosses a Y slot"),
    # Pack pairs. X, Y, T, CT and SC pack into DH only. DS packs into DD or DF, and DH into DD.
    ("pack_bits(X001..X016,DS1)", "a pack from X goes to DH"),
    ("pack_bits(Y001..Y016,DD1)", "a pack from Y goes to DH"),
    ("pack_bits(T1..T16,DS1)", "a pack from T goes to DH"),
    ("pack_words(DH1..DH2,DF1)", "a pack from DH goes to DD"),
    ("pack_words(DS1..DS2,DH1)", "a pack from DS goes to DD, DF"),
    ("pack_text(TXT1..TXT4,SD1)", "Pack.dest: 'SD1' is not allowed"),
    ("pack_text(TXT1..TXT4,YD0u)", "Pack.dest: 'YD0u' is not allowed"),
    ("pack_bits(C1..C16,YD0u)", "Pack.dest: 'YD0u' is not allowed"),
    ("pack_words(DD1..DD2,DF1)", "Pack.source_start: 'DD1' is not allowed"),
    ("pack_words(XD0..XD1,DD1)", "Pack.source_start: 'XD0' is not allowed"),
    ("pack_bits(C1..C1,DS1)", r"C1\.\.C1 is one address"),
    ("pack_bits(C5..C1,DS1)", r"C5\.\.C1 runs backwards"),
    # Unpack pairs. Only DH unpacks to Y. DS unpacks to C only. Nothing unpacks to DF.
    ("unpack_to_bits(DS5,Y001..Y016)", "an unpack from DS goes to C"),
    ("unpack_to_bits(DD5,Y001..Y016)", "an unpack from DD goes to C, DS, DH"),
    ("unpack_to_words(DD1,DF1..DF2)", "Unpack.dest_start: 'DF1' is not allowed"),
    ("unpack_to_words(DD1,YD0..YD0u)", "Unpack.dest_start: 'YD0' is not allowed"),
    ("unpack_to_bits(TXT1,C1..C16)", "Unpack.source: 'TXT1' is not allowed"),
    ("unpack_to_bits(XD0u,C1..C16)", "Unpack.source: 'XD0u' is not allowed"),
    ("unpack_to_bits(DS1,C1..C1)", r"C1\.\.C1 is one address"),
    # Fill runs the same range check on its destination
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
        "copy(TXT1,DS1,convert=to_value)",
        "copy(TXT1,DF1)",
        "copy(DS1,TXT1,convert=to_text(suppress_zero=1,termination_code=none))",
        "copy(5,TXT1,convert=to_text(suppress_zero=1,termination_code=none))",
        "copy(1Fh,DH1)",
        "copy(1FH,DH1)",
        "copy(-1.5E+3,DF1)",
        "copy(.5,DF1)",
        "copy($0D,TXT1)",
        "copy(DD[DS1],DS1)",
        "copy(DS1,TXT[DS2],convert=to_text(suppress_zero=1,termination_code=none))",
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
        "blockcopy(DS1..DS4,DD1..DD4)",  # the destination end counts elements
        "blockcopy(DD1..DD4,DS1..DS4)",
        "blockcopy(DF1..DF3,CTD1..CTD3)",
        "blockcopy(C1..C16,Y001..Y016)",
        "blockcopy(X021..X036,C1..C16)",
        "blockcopy(C1..C7,Y010..Y016)",
        "blockcopy(X001..X008,Y101..Y108)",
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
        # Single Copy constants
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


# The tests below run CLICK's shared constant check (operands.constants.classify) on a single
# Copy source and a Fill value. CLICK's id for these refusals is OBJ-005.

_TEXT_129 = '"' + "A" * 129 + '"'
_TEXT_128 = '"' + "A" * 128 + '"'
_HEX_SIGN = "a hex constant has no sign$"
_COPY_HEX_SIGN = r"a hex constant has no sign \(OBJ-005\)$"
_HEX_ABOVE = r"is above FFFFFFFFh; a hex constant here is 0h to FFFFFFFFh \(OBJ-005\)"
_HEX_PADDED = r"a hex constant above FFFFh has at most 8 digits \(OBJ-005\)$"
_FILL_HEX_PADDED = "a hex constant above FFFFh has at most 8 digits$"
_TEXT_RULE = "a text constant is 1 to 128 characters in quotes, with no quote inside"
_TEXT_ONE = "a text constant is one character in quotes, with no quote inside"
_INT32 = INT_RULE
_FINITE = "a real constant is a finite number"

_COPY_SOURCE_REFUSED = [
    ("+1h", "DS9", _COPY_HEX_SIGN),
    ("-1h", "DS9", _COPY_HEX_SIGN),
    ("+1h", "DD1", _COPY_HEX_SIGN),
    ("-1h", "DF1", _COPY_HEX_SIGN),
    ("+1h", "DH1", _COPY_HEX_SIGN),
    ("-1h", "TXT2", _COPY_HEX_SIGN),
    ("100000000h", "DD1", _HEX_ABOVE),
    ("0FFFFFFFFh", "DD1", _HEX_PADDED),
    ('""', "TXT2", _TEXT_RULE),
    ('"""', "TXT2", _TEXT_RULE),
    ('"a"b"', "TXT2", _TEXT_RULE),
    (_TEXT_129, "TXT2", _TEXT_RULE),
    ("1E999", "DF1", _FINITE),
    ("-1E999", "DF1", _FINITE),
]


@pytest.mark.parametrize(("source", "destination", "message"), _COPY_SOURCE_REFUSED)
def test_copy_source_refuses_what_the_constant_check_refuses(
    source: str, destination: str, message: str
) -> None:
    with pytest.raises(FieldError, match=rf"^Copy.source: .* {message}"):
        Copy(source, destination)


@pytest.mark.parametrize(
    "token",
    ['copy("",TXT2)', "copy(0FFFFFFFFh,DD1)", "copy(+1h,DD1)", f"copy({_TEXT_129},TXT2)"],
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
        ('" "', "TXT2"),  # printable ASCII runs from space to ~
        ('"~"', "TXT2"),
        ("$00", "TXT2"),
        ("$FF", "TXT2"),
        ("$0d", "TXT2"),
        ("2147483647", "DD1"),
        ("-2147483648", "DD1"),
    ],
)
def test_copy_source_constant_edges_accepted(source: str, destination: str) -> None:
    copy = Copy(source, destination)
    assert parse_af_blob(copy.build_blob()) == copy


# A $ code is one of the codes in CLICK's Embed ASCII Code table, $00 to $FF. Every field
# takes it as $ and two hex digits. _DOLLAR_FORMS lists $ texts in other forms.
_DOLLAR_FORMS = ["$", "$1", "$D", "$d", "$100", "$4142", "$G1", "$٣٣"]
#: A single Copy's source takes $ and one hex digit, which CLICK stores with two ($1 is $01).
_ONE_DIGIT_CODES = ["$1", "$D", "$d"]
_COPY_DOLLAR_FORMS = [form for form in _DOLLAR_FORMS if form not in _ONE_DIGIT_CODES]
_DOLLAR_RULE = r"a character code is \$ and two hex digits, \$00 to \$FF"
_DOLLAR_FIELDS = [
    ("Copy.source", lambda code: Copy(code, "TXT2")),
    ("Fill.value", lambda code: Fill(code, "TXT2", "TXT5")),
    ("Search.value", lambda code: Search("TXT1", "TXT10", code, "DS20", "C1", "==")),
    ("CompareContact.right", lambda code: CompareContact("==", "TXT1", code)),
    ("CompareContact.left", lambda code: CompareContact("==", code, "TXT1")),
    (
        "Copy.termination_code",
        lambda code: Copy("DS20", "TXT7", convert="to_text", termination_code=code),
    ),
]


@pytest.mark.parametrize(
    ("field", "build", "code"),
    [
        (field, build, code)
        for code in ["$", "$1", "$G1"]
        for field, build in _DOLLAR_FIELDS
        if not (field == "Copy.source" and code in _ONE_DIGIT_CODES)
    ],
)
def test_every_field_refuses_other_dollar_forms_alike(field: str, build, code: str) -> None:
    """Every field refuses these $ forms with a plain FieldError and the same wording.

    One check, operands.checks.check_constant, raises the error for every field."""
    with pytest.raises(FieldError) as caught:
        build(code)
    assert type(caught.value) is FieldError
    # For a termination code, the message adds CLICK's id. The rest of the wording is the same.
    click_id = " (OBJ-036)" if field == "Copy.termination_code" else ""
    assert str(caught.value) == (
        f"{field}: {code!r} is refused; a character code is $ and two hex digits, $00 to $FF, "
        f"such as $41{click_id}"
    )


@pytest.mark.parametrize("source", _COPY_DOLLAR_FORMS)
def test_copy_source_other_dollar_forms_refused(tmp_path: Path, source: str) -> None:
    with pytest.raises(FieldError, match=rf"^Copy.source: .* {_DOLLAR_RULE}"):
        Copy(source, "TXT2")
    with pytest.raises(FieldError, match=rf"^Copy.source: .* {_DOLLAR_RULE}"):
        _read_af(tmp_path, f"copy({source},TXT2)")


@pytest.mark.parametrize("value", _DOLLAR_FORMS)
def test_fill_value_other_dollar_forms_refused(tmp_path: Path, value: str) -> None:
    with pytest.raises(FieldError, match=rf"^Fill.value: .* {_DOLLAR_RULE}"):
        Fill(value, "TXT2", "TXT5")
    with pytest.raises(FieldError, match=rf"^Fill.value: .* {_DOLLAR_RULE}"):
        _read_af(tmp_path, f"fill({value},TXT2..TXT5)")


@pytest.mark.parametrize("value", _DOLLAR_FORMS)
@pytest.mark.parametrize(
    "tags", [{0x6076: "TXT2"}, {0x6076: "TXT2", 0x6077: "TXT5", 0x2223: "2"}], ids=["copy", "fill"]
)
def test_other_dollar_form_blob_keeps_its_refusal(tags: dict[int, str], value: str) -> None:
    assert kept(from_tags_af("Copy", 0x2721, tags | {0x6074: "$41"})) is not None
    field = "Fill.value" if 0x6077 in tags else "Copy.source"
    if field == "Copy.source" and value in _ONE_DIGIT_CODES:
        # A Copy source accepts a one-digit code and stores it in CLICK's two-digit form.
        decoded = from_tags_af("Copy", 0x2721, tags | {0x6074: value})
        assert isinstance(decoded, Copy)
        assert decoded.source == f"$0{value[1]}"
        assert refusals(decoded) == ()
        return
    kept(from_tags_af("Copy", 0x2721, tags | {0x6074: value}), field)


@pytest.mark.parametrize(("typed", "stored"), [("$1", "$01"), ("$D", "$0D"), ("$d", "$0d")])
def test_copy_source_one_digit_code_is_written_with_two(
    tmp_path: Path, typed: str, stored: str
) -> None:
    # CLICK's Copy takes $1 into TXT and stores $01.  Fill, Search and Compare still refuse it.
    copy = Copy(typed, "TXT2")
    assert copy.source == stored
    assert copy.to_csv() == f"copy({stored},TXT2)"
    assert _read_af(tmp_path, f"copy({typed},TXT2)") == copy
    assert parse_af_blob(copy.build_blob()) == copy


_FILL_VALUE_REFUSED = [
    ("2147483648", "DS52", "DS55", _INT32),
    ("-2147483649", "DS52", "DS55", _INT32),
    ("3000000000", "DS52", "DS55", _INT32),
    ("6000000000", "DS52", "DS55", _INT32),
    ("+1h", "DS52", "DS55", _HEX_SIGN),
    ("-1h", "DS52", "DS55", _HEX_SIGN),
    ("100000000h", "DS52", "DS55", _HEX_ABOVE),
    ("0FFFFFFFFh", "DS52", "DS55", _FILL_HEX_PADDED),
    ("2147483648", "TXT2", "TXT5", _INT32),
    ("+1h", "TXT2", "TXT5", _HEX_SIGN),
    ("100000000h", "TXT2", "TXT5", _HEX_ABOVE),
    ('""', "TXT2", "TXT5", _TEXT_ONE),
    ('"""', "TXT2", "TXT5", _TEXT_ONE),
    ('"a"b"', "TXT2", "TXT5", _TEXT_ONE),
    (_TEXT_129, "TXT2", "TXT5", _TEXT_ONE),
    ("1E999", "DF1", "DF4", _FINITE),
    ("3.5E+38", "DF1", "DF4", _FINITE),
    ("-3.5E+38", "DF1", "DF4", _FINITE),
    # a Fill into TXT takes one character
    ('"AB"', "TXT2", "TXT5", "takes one character"),
    (_TEXT_128, "TXT2", "TXT5", "takes one character"),
    ("-1E999", "DS52", "DS55", _FINITE),
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
        # a 32-bit hex Fill and a number into TXT are accepted
        ("10000h", "DS52", "DS55"),
        ("FFFFFFFFh", "DS52", "DS55"),
        ("5", "TXT2", "TXT5"),
        ('"~"', "TXT2", "TXT5"),
        ("$00", "TXT2", "TXT5"),
        ("$7E", "TXT2", "TXT5"),
    ],
)
def test_fill_value_constant_edges_accepted(value: str, start: str, end: str) -> None:
    fill = Fill(value, start, end)
    assert parse_af_blob(fill.build_blob()) == fill


@pytest.mark.parametrize("fmt", ["to_text", "to_binary"])
@pytest.mark.parametrize("code", ["abc", "1", "DS1", "1.5", "FFFFh", '""', "None", "00"])
def test_termination_code_is_a_character_code(fmt: str, code: str) -> None:
    """Copy refuses a termination code that is not a character code (OBJ-036).

    The blob stores a termination code only as a character code."""
    with pytest.raises(FieldError, match=r"^Copy.termination_code: .* is not allowed; it is a"):
        Copy("DS20", "TXT7", convert=fmt, termination_code=code)


@pytest.mark.parametrize("fmt", ["to_text", "to_binary"])
def test_blank_termination_code_is_missing(fmt: str) -> None:
    with pytest.raises(FieldError, match=r"^Copy.termination_code: is blank") as raised:
        Copy("DS20", "TXT7", convert=fmt, termination_code="")
    assert (raised.value.reason, raised.value.click_id) == ("missing", None)


@pytest.mark.parametrize("fmt", ["to_text", "to_binary"])
@pytest.mark.parametrize(
    ("code", "stored"), [("0", "0"), ("none", "0"), ("$00", "$00"), ("$FF", "$FF")]
)
def test_termination_code_edges_accepted(fmt: str, code: str, stored: str) -> None:
    copy = Copy("DS20", "TXT7", convert=fmt, termination_code=code)
    assert copy.termination_code == stored
    assert parse_af_blob(copy.build_blob()) == copy


@pytest.mark.parametrize(
    ("tags", "field"),
    [
        ({0x6074: "+1h", 0x6076: "DS9"}, "Copy.source"),
        ({0x6074: "100000000h", 0x6076: "DD1"}, "Copy.source"),
        ({0x6074: '""', 0x6076: "TXT2"}, "Copy.source"),
        ({0x6074: "3000000000", 0x6076: "DS52", 0x6077: "DS55", 0x2223: "2"}, "Fill.value"),
        ({0x6074: '""', 0x6076: "TXT2", 0x6077: "TXT5", 0x2223: "2"}, "Fill.value"),
    ],
)
def test_refused_constant_blob_keeps_its_refusal(tags: dict[int, str], field: str) -> None:
    kept(from_tags_af("Copy", 0x2721, tags), field)


def test_quote_character_blob_is_left_unparsed() -> None:
    # The CSV token copy(""",TXT2) does not read back, so the blob stays raw.
    assert from_tags_af("Copy", 0x2721, {0x6074: '"""', 0x6076: "TXT2"}) is None


# A single Copy of text into TXT stores the last TXT register that the text fills as the
# destination end (0x6077). "TT" into TXT1 stores TXT2. One character and a $hh code store
# no end. test_v4_captures.py checks the blobs against CLICK's captures.


def _destination_end(copy: Copy) -> str:
    fields = {tag: value for tag, _, value in _decompose_blob(copy.build_blob())[4]}
    return fields[0x6077]


@pytest.mark.parametrize(
    ("source", "destination", "end"),
    [
        ('"TT"', "TXT1", "TXT2"),
        ('"ABC"', "txt10", "TXT12"),
        ('"$41"', "TXT2", "TXT4"),  # three characters of text
        ('"AB"', "TXT999", "TXT1000"),
        (_TEXT_128, "TXT873", "TXT1000"),
        ('"Q"', "TXT1000", ""),
        ("$41", "TXT1000", ""),
        ('"Q"', "TXT[DS1]", ""),  # a pointer stores no end, whatever the length
        ('"AB"', "TXT[DS1]", ""),  # as captured in v4_captures/text_pointer.bin
        ('"$41"', "TXT[DS1]", ""),
        (_TEXT_128, "TXT[DS1]", ""),
        ("$41", "TXT[DS1]", ""),
        # laddercodec accepts text with an E. CLICK's Copy dialog has a bug with an E in text.
        ('"HELLO"', "TXT1", "TXT5"),
    ],
)
def test_text_copy_stores_its_last_txt(source: str, destination: str, end: str) -> None:
    copy = Copy(source, destination)
    assert _destination_end(copy) == end
    assert copy.to_csv() == f"copy({source},{copy.dest})"
    assert parse_af_blob(copy.build_blob()) == copy


@pytest.mark.parametrize(
    ("source", "destination", "message"),
    [
        ('"AB"', "TXT1000", r"2 characters fill TXT1000..TXT1001, past TXT1000"),
        (_TEXT_128, "TXT874", r"128 characters fill TXT874..TXT1001, past TXT1000"),
    ],
)
def test_text_copy_past_txt1000_refused(
    tmp_path: Path, source: str, destination: str, message: str
) -> None:
    with pytest.raises(AddressError, match=rf"^Copy.dest: .* {message}"):
        Copy(source, destination)
    with pytest.raises(AddressError, match=rf"^Copy.dest: .* {message}"):
        _read_af(tmp_path, f"copy({source},{destination})")


def test_pointer_copy_with_an_end_stays_raw() -> None:
    """CLICK writes no value in 0x6077 for a copy through a pointer.

    A blob with a value in 0x6077 stays raw()."""
    tags = {0x6074: '"AB"', 0x6076: "TXT[DS1]", 0x6077: "TXT2", 0x2223: "0", 0x2227: "0"}
    assert from_tags_af("Copy", 0x2721, tags) is None
    assert from_tags_af("Copy", 0x2721, tags | {0x6077: ""}) is not None


@pytest.mark.parametrize("source", ['"AB"', '"$41"', _TEXT_128])
def test_text_copy_into_a_pointer_stores_no_end(tmp_path: Path, source: str) -> None:
    """CLICK accepts two or more characters through a pointer and writes an empty 0x6077."""
    copy = Copy(source, "TXT[DS1]")
    assert _destination_end(copy) == ""
    assert _read_af(tmp_path, f"copy({source},TXT[DS1])") == copy
    assert parse_af_blob(copy.build_blob()) == copy


# Text in a Fill holds printable ASCII only, as in Compare. To fill with another character,
# write its $hh code. A single Copy's text accepts any 16-bit character that CLICK keeps, as
# Search's text does.
_NOT_PRINTABLE = ['"é"', '"é1"', '"\U0001f600"', '"A\tB"', '"\x7f"']
_PRINTABLE_RULE = r"text holds printable ASCII only \(space to ~\); write another character"
_COPY_TEXT_RULE = r"text holds characters U\+0001 to U\+FFFF, no NUL and no surrogate"
#: Texts that a single Copy refuses. NUL is refused because it ends a stored string. A
#: surrogate and a character above U+FFFF are refused because neither is a 16-bit character.
_NOT_COPY_TEXT = ['"\U0001f600"', '"\x00"', '"A\x00B"', '"\ud800"']


@pytest.mark.parametrize("text", _NOT_PRINTABLE)
def test_fill_text_is_printable_ascii(text: str) -> None:
    if len(text) == 3:  # a Fill value takes one character
        with pytest.raises(FieldError, match=rf"^Fill.value: .* {_PRINTABLE_RULE}"):
            Fill(text, "TXT2", "TXT5")


@pytest.mark.parametrize("text", _NOT_COPY_TEXT)
def test_copy_text_refuses_other_characters(tmp_path: Path, text: str) -> None:
    with pytest.raises(FieldError, match=rf"^Copy.source: .* {_COPY_TEXT_RULE}"):
        Copy(text, "TXT2")
    if text != '"\ud800"':  # a lone surrogate has no UTF-8 for the CSV file
        with pytest.raises(FieldError, match=rf"^Copy.source: .* {_COPY_TEXT_RULE}"):
            _read_af(tmp_path, f"copy({text},TXT2)")
    if len(text) == 3:  # with one character, the blob needs no end
        assert kept(from_tags_af("Copy", 0x2721, {0x6074: '"A"', 0x6076: "TXT2"})) is not None
        stored = kept(from_tags_af("Copy", 0x2721, {0x6074: text, 0x6076: "TXT2"}), "Copy.source")
        assert stored.source == text


@pytest.mark.parametrize(
    ("source", "destination", "end"),
    [
        ('"TT"', "TXT1", "TXT1"),
        ('"TT"', "TXT1", "TXT3"),
        ('"Q"', "TXT2", "TXT2"),  # one character stores no end
        ("$41", "TXT2", "TXT2"),
        ('"AB"', "TXT[DS1]", "TXT2"),
        ("DS1", "TXT1", "TXT2"),
    ],
)
def test_text_copy_blob_with_another_end_is_left_unparsed(
    source: str, destination: str, end: str
) -> None:
    tags = {0x6074: source, 0x6076: destination, 0x6077: end}
    assert from_tags_af("Copy", 0x2721, tags) is None


def test_copy_csv_paths_agree(tmp_path: Path) -> None:
    token = "copy(DS20,TXT7,oneshot=1,convert=to_text(suppress_zero=1,termination_code=$0D))"
    copy = Copy.from_csv_token(token)
    assert copy == _read_af(tmp_path, token)
    assert copy.to_csv() == token


def test_termination_code_needs_a_number_register_copied_to_text() -> None:
    """CLICK v4's dialog offers Termination Code for a number register copied to text and for
    a TXT register copied to TXT. It greys the option out for a constant copied to TXT."""
    Copy("DS1", "TXT1", convert="to_text", termination_code="$0D")
    Copy("DS1", "TXT1", convert="to_binary", termination_code="$0D")
    Copy("TXT1", "TXT2", termination_code="$0D")
    for source, destination, fmt in [
        ("DS1", "DD1", None),
        ("TXT1", "DF1", None),
        ("TXT1", "DS1", "to_value"),
        ("5", "TXT1", "to_text"),
        ("DD1", "DF1", "to_binary"),
    ]:
        with pytest.raises(FieldError, match=r"Copy.termination_code: '\$0D'"):
            Copy(source, destination, convert=fmt, termination_code="$0D")


@pytest.mark.parametrize("option", ["suppress_zero", "exponential"])
@pytest.mark.parametrize("value", [2, 5, -1, "1", "0"])
def test_text_options_are_flags(option: str, value: object) -> None:
    with pytest.raises(FieldError, match=f"Copy.{option}: {value!r} is not True, False, 1 or 0"):
        Copy("DF1", "TXT1", convert="to_text", **{option: value})


@pytest.mark.parametrize("option", ["suppress_zero", "exponential"])
def test_a_blank_text_option_is_missing(option: str) -> None:
    with pytest.raises(FieldError, match=f"^Copy.{option}: is blank") as raised:
        Copy("DF1", "TXT1", convert="to_text", **{option: ""})
    assert raised.value.reason is Reason.MISSING


@pytest.mark.parametrize(("source", "option"), [("DS1", "suppress_zero"), ("DF1", "exponential")])
def test_text_options_keep_their_bytes(source: str, option: str) -> None:
    for value in (False, True):
        copy = Copy(source, "TXT1", convert="to_text", **{option: value})
        assert parse_af_blob(copy.build_blob()) == copy


@pytest.mark.parametrize(
    "instruction",
    [
        Pack("X001", "X016", "DH1", kind="pack_bits"),
        Pack("Y101", "Y108", "DH1", kind="pack_bits"),
        Pack("X021", "X036", "DH1", kind="pack_bits"),
        Unpack("DH1", "Y021", "Y036", kind="unpack_to_bits"),
        Pack("T1", "T16", "DH1", kind="pack_bits"),
        Pack("CT1", "CT4", "DH1", kind="pack_bits"),
        Pack("SC1", "SC16", "DH1", kind="pack_bits"),
        Pack("DH1", "DH2", "DD1", kind="pack_words"),
        Unpack("DH1", "Y001", "Y016", kind="unpack_to_bits"),
        Unpack("DD1", "DH1", "DH2", kind="unpack_to_words"),
    ],
)
def test_pack_kind_decodes_from_the_bank(instruction: Pack | Unpack) -> None:
    """Decoding takes the kind, bits or words, from the bank and not from its first letter.

    The cases cover the CT, X, Y, T, SC and DH banks."""
    assert parse_af_blob(instruction.build_blob()) == instruction


@pytest.mark.parametrize(
    ("tags", "family", "fields"),
    [
        ({0x6074: "X001", 0x6076: "DS1"}, Copy, ["dest"]),  # a bit into a register
        (
            {0x6074: "DS1", 0x6075: "DS4", 0x6076: "DS[DS9]", 0x6077: "DS13", 0x2223: "1"},
            BlockCopy,
            ["dest_start"],
        ),
        ({0x6074: "C1", 0x6075: "C17", 0x6076: "DS1", 0x2223: "3"}, Pack, ["source_end"]),
        (
            {0x6074: "X016", 0x6075: "X021", 0x6076: "DD1", 0x2223: "3"},  # two X slots
            Pack,
            ["source_end", "dest"],
        ),
        (
            {0x6074: "X001", 0x6075: "X036", 0x6076: "DD1", 0x2223: "3"},  # two X slots
            Pack,
            ["source_end", "dest"],
        ),
        (
            {0x6074: "X001", 0x6075: "X016", 0x6076: "DS1", 0x2223: "3"},  # X packs into DH only
            Pack,
            ["dest"],
        ),
        (
            {0x6074: "DS5", 0x6076: "Y001", 0x6077: "Y016", 0x2223: "4"},  # DS unpacks to C only
            Unpack,
            ["dest_start"],
        ),
        (
            {0x6074: "DS1", 0x6075: "DS3", 0x6076: "YD1", 0x6077: "YD3", 0x2223: "1"},  # YD dest
            BlockCopy,
            ["dest_start", "dest_end"],
        ),
        (
            # the destination end is not where the copy ends
            {0x6074: "DS1", 0x6075: "DS4", 0x6076: "DD1", 0x6077: "DD2", 0x2223: "1"},
            BlockCopy,
            ["dest_end"],
        ),
        (
            # a source range of one address
            {0x6074: "DS1", 0x6075: "DS1", 0x6076: "DS5", 0x6077: "DS5", 0x2223: "1"},
            BlockCopy,
            ["source_end"],
        ),
        (
            {0x6074: "0", 0x6076: "DS5", 0x6077: "DS1", 0x2223: "2"},  # fill runs backwards
            Fill,
            ["dest_end"],
        ),
        (
            # the Y destination crosses a slot
            {0x6074: "C1", 0x6075: "C16", 0x6076: "Y010", 0x6077: "Y025", 0x2223: "1"},
            BlockCopy,
            ["dest_start"],
        ),
        ({0x6074: "10000h", 0x6076: "DH1"}, Copy, ["dest"]),  # hex above FFFFh into DH
        (
            # pack_text (conversion type 9) from a source that is not TXT
            {0x6074: "DS1", 0x6075: "DS2", 0x6076: "DD1", 0x2223: "3", 0x2227: "9"},
            Pack,
            ["source_start"],
        ),
        (
            # pack_words from a TXT source
            {0x6074: "TXT1", 0x6075: "TXT2", 0x6076: "DS1", 0x2223: "3", 0x2227: "0"},
            Pack,
            ["source_start"],
        ),
        (
            {0x6074: '"AB"', 0x6076: "TXT2", 0x6077: "TXT5", 0x2223: "2"},  # Fill: one character
            Fill,
            ["value"],
        ),
        ({0x6074: "5000000000", 0x6076: "DD1"}, Copy, ["source"]),  # outside int32
    ],
)
def test_refused_blob_keeps_its_refusal(
    tags: dict[int, str], family: type, fields: list[str]
) -> None:
    built = kept(
        from_tags_af("Copy", 0x2721, tags), *(f"{family.__name__}.{name}" for name in fields)
    )
    assert type(built) is family


def test_blob_with_an_unknown_option_is_left_unparsed() -> None:
    # The termination code in 0x3216 is not a decimal character code.
    tags = {0x6074: "DS1", 0x6076: "TXT1", 0x2227: "1", 0x1221: "-1", 0x3216: "-1"}
    assert from_tags_af("Copy", 0x2721, tags) is None


@pytest.mark.parametrize(("first", "last"), [("X001", "X036"), ("X015", "X022"), ("X016", "X021")])
def test_pack_unpack_constructors_keep_to_one_slot(first: str, last: str) -> None:
    """Pack and Unpack refuse a range that spans two slots.

    The dual option slot, 21-36, is a 16-point slot of its own."""
    message = f"Pack.source_end: {first}..{last} spans two X slots"
    with pytest.raises(FieldError, match=re.escape(message)):
        Pack(first, last, "DD1", kind="pack_bits")
    y_first, y_last = "Y" + first[1:], "Y" + last[1:]
    message = f"Unpack.dest_end: {y_first}..{y_last} spans two Y slots"
    with pytest.raises(FieldError, match=re.escape(message)):
        Unpack("DH1", y_first, y_last, kind="unpack_to_bits")


# ---------------------------------------------------------------------------
# FieldError.field names the field that was refused
# ---------------------------------------------------------------------------


def _ascii_code_out_of_range() -> object:
    from laddercodec.instructions.copy import _ascii_code

    return _ascii_code(300)


@pytest.mark.parametrize(
    ("build", "field"),
    [
        (lambda: Copy("DS1", "DS2", convert="bogus"), "Copy.convert"),
        (
            lambda: Copy.from_csv_token("copy(DS1,TXT2,convert=to_binary(suppress_zero=1))"),
            "Copy.convert",
        ),
        (lambda: Copy("DS1", "TXT2", convert="to_text", exponential=True), "Copy.exponential"),
        (_ascii_code_out_of_range, "Copy.termination_code"),
        (lambda: BlockCopy("DS1", "DS2", "DS3", "DS4", convert="bogus"), "BlockCopy.convert"),
        (lambda: Pack("C1", "C16", "DS1", kind="bogus"), "Pack.kind"),
        (lambda: Unpack("DS1", "C1", "C16", kind="bogus"), "Unpack.kind"),
    ],
)
def test_field_names_the_refused_field(build, field: str) -> None:
    with pytest.raises(FieldError) as info:
        build()
    assert info.value.field == field


@pytest.mark.parametrize(
    ("build", "field"),
    [
        (lambda: Copy("DS[DS0]", "DS1"), "Copy.source"),
        (lambda: Copy("DS[DD1]", "DS1"), "Copy.source"),
        (lambda: Copy("DS1", "DS[DS4501]"), "Copy.dest"),
        (lambda: Copy("DS1", "DS[X1]"), "Copy.dest"),
    ],
)
def test_pointer_index_refusal_is_a_pointer_refusal(build, field: str) -> None:
    """A refused pointer index names the operand's field and has reason ``pointer``.

    The message starts with the field name and the word pointer."""
    with pytest.raises(AddressError) as info:
        build()
    assert info.value.field == field
    assert info.value.reason == "pointer"
    assert str(info.value).startswith(f"{field} pointer: ")


@pytest.mark.parametrize("source", ["99999999999", "-2147483649"])
@pytest.mark.parametrize(
    ("destination", "convert", "termination"),
    [("DS1", "to_value", "0"), ("TXT2", "to_text", "$0D"), ("DS1", None, "$0D")],
)
def test_integer_out_of_range_is_reported_before_convert_and_termination(
    source: str, destination: str, convert: str | None, termination: str
) -> None:
    with pytest.raises(FieldError) as info:
        Copy(source, destination, convert=convert, termination_code=termination)
    assert info.value.field == "Copy.source"
