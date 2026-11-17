"""A single Copy's conversion type 7 and a number copied into TXT, as CLICK saves them.

CLICK saves conversion type 7 (tag 0x2227) for a value converted between a real and a 32-bit
integer: DF to DD or CTD and back (a DF, DD or CTD pointer source too), a real constant into DD
or CTD, and an integer outside int16 into DF.  It saves a number constant whose text fills more than one TXT with the TXT that text
ends in (tag 0x6077), counted on the constant as typed, and the conversion type of its kind.
The saves are CLICK's answers in ``tests/fixtures/editor_grids/copy_single.answers.json`` and
the CLICK v4 captures in ``tests/fixtures/v4_captures/copy_single/``.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from laddercodec import decode, decode_program
from laddercodec.binary_helpers import _build_blob
from laddercodec.csv import CSV_HEADER, read_csv
from laddercodec.instructions import from_tags_af, parse_af_blob
from laddercodec.instructions.copy import Copy, from_tags
from laddercodec.instructions.raw import RawInstruction, _decompose_blob, _fields_to_tag_dicts
from laddercodec.operands.errors import FieldError, Reason
from laddercodec.operands.unchecked import refusals, stored_blob

ANSWERS = (
    Path(__file__).resolve().parents[1] / "fixtures" / "editor_grids" / "copy_single.answers.json"
)


def _saved_blob(tmp_path: Path, case: str) -> bytes:
    """The blob CLICK saved for one ``copy_single`` case, as its answers record it."""
    answers = json.loads(ANSWERS.read_text(encoding="utf-8"))
    [found] = [c for c in answers["cases"] if c["case"] == case]
    path = tmp_path / "stored.csv"
    path.write_text("\n".join([",".join(CSV_HEADER), *found["stored"]]) + "\n", "utf-8")
    [rung] = read_csv(path)
    [raw] = [t for t in rung.instructions if isinstance(t, RawInstruction)]
    return raw.blob


def _tags(blob: bytes) -> dict[int, str]:
    """Every tag a blob holds, by tag."""
    return {tag: value for tag, _sentinel, value in _decompose_blob(blob)[4]}


#: Each answered save: the case, the CSV decode writes, and the conversion type and end the
#: encoder writes for that CSV (CLICK's, but where the rule has no answer to rest on).
SAVES = [
    ("single 1.5 -> DD1", "copy(1.5,DD1)", "7", ""),
    ("single 1.5 -> DD[DS1]", "copy(1.5,DD[DS1])", "7", ""),
    ("single 1.5 -> CTD1", "copy(1.5,CTD1)", "7", ""),
    ("single 1.5 -> CTD[DS1]", "copy(1.5,CTD[DS1])", "7", ""),
    ("single CTD1 -> DF1", "copy(CTD1,DF1)", "7", ""),
    ("single DF1 -> CTD1", "copy(DF1,CTD1)", "7", ""),
    ("single 2147483647 -> DF1", "copy(2147483647,DF1)", "7", ""),
    (
        "single -5 -> TXT1",
        "copy(-5,TXT1,convert=to_text(suppress_zero=1,termination_code=none))",
        "1",
        "TXT2",
    ),
    (
        "single FFh -> TXT1",
        "copy(FFh,TXT1,convert=to_text(suppress_zero=1,termination_code=none))",
        "1",
        "TXT3",
    ),
    (
        "single 2147483647 -> TXT1",
        "copy(2147483647,TXT1,convert=to_text(suppress_zero=1,termination_code=none))",
        "1",
        "TXT10",
    ),
    (
        "single 1.5 -> TXT1",
        "copy(1.5,TXT1,convert=to_text(exponential=0,termination_code=none))",
        "3",
        "TXT3",
    ),
    # Quoted text with an E is stored as its real value.
    (
        'single "HELLO" -> TXT1',
        "copy(0.0,TXT1,convert=to_text(exponential=0,termination_code=none))",
        "3",
        "TXT3",
    ),
]


@pytest.mark.parametrize(("case", "csv", "conv", "end"), SAVES)
def test_a_save_decodes_as_the_copy_and_writes_its_bytes(
    tmp_path: Path, case: str, csv: str, conv: str, end: str
) -> None:
    blob = _saved_blob(tmp_path, case)
    parsed = parse_af_blob(blob)
    assert isinstance(parsed, Copy)
    assert parsed.to_csv() == csv
    assert not refusals(parsed)
    # Unchanged, it writes the blob CLICK saved.
    assert parsed.build_blob() == blob
    # The tags read alone, as a program file holds them, build the same Copy.
    class_name, type_code, _parts, _extra, fields = _decompose_blob(blob)
    assert from_tags_af(class_name, type_code, *_fields_to_tag_dicts(fields)) == parsed
    # Built from its CSV, it writes the encoder's conversion type and end, and reads back.
    built = Copy.from_csv_token(csv)
    assert built == parsed
    written = built.build_blob()
    assert (_tags(written)[0x2227], _tags(written)[0x6077]) == (conv, end)
    assert parse_af_blob(written) == built
    assert replace(parsed).build_blob() == written


@pytest.mark.parametrize(
    ("source", "destination"),
    [
        ("DD1", "DF1"),  # the DD <-> DF Copy Value, written before
        ("DF1", "DD1"),
        ("CTD1", "DF1"),
        ("DF1", "CTD1"),
        ("CTD250", "DF500"),
        ("1.5", "DD1"),
        ("-1.5", "CTD250"),
        ("1.0", "DD[DS1]"),
        ("100000.0", "CTD[DS1]"),
        ("32768", "DF1"),  # an integer outside int16 into DF
        ("-32769", "DF1"),
        ("65535", "DF1"),
        ("65536", "DF1"),
        ("2147483647", "DF1"),
        ("2147483647", "DF[DS1]"),
        ("DF[DS1]", "DD1"),  # a pointer source, as CLICK saves it
        ("DD[DS1]", "DF1"),
        ("CTD[DS1]", "DF1"),
        ("DF[DS1]", "CTD1"),
        ("DF1", "CTD[DS1]"),  # a pointer destination, as CLICK saves it
        ("DD1", "DF[DS1]"),
    ],
)
def test_a_value_converted_between_a_real_and_a_32_bit_integer_writes_type_7(
    source: str, destination: str
) -> None:
    copy = Copy(source, destination)
    assert _tags(copy.build_blob())[0x2227] == "7"
    assert parse_af_blob(copy.build_blob()) == copy


@pytest.mark.parametrize(
    ("source", "destination"),
    [
        ("1.5", "DS1"),
        ("1.5", "DF1"),
        ("1.5", "TD1"),
        ("1.5", "DF[DS1]"),
        ("5", "DF1"),
        ("-5", "DF1"),
        ("32767", "DF1"),
        ("-32768", "DF1"),
        ("32767", "DF[DS1]"),
        ("FFh", "DF1"),
        ("FFFFh", "DF1"),
        ("2147483647", "DD1"),
        ("DS1", "DF1"),
        ("TD1", "DF1"),
        ("DF1", "TD1"),
    ],
)
def test_other_copies_write_type_0(source: str, destination: str) -> None:
    assert _tags(Copy(source, destination).build_blob())[0x2227] == "0"


@pytest.mark.parametrize(
    ("source", "destination", "decodes"),
    [
        ("2147483647", "DF1", True),
        ("32768", "DF1", True),  # outside int16
        ("-32769", "DF1", True),
        ("32767", "DF1", False),
        ("-5", "DF1", False),
        ("5", "DF[DS1]", False),
        ("2147483647", "DF[DS1]", True),
        ("-32768", "DF[DS1]", False),
        ("FFh", "DF1", False),
        ("DS1", "DF1", False),
        ("DD[DS1]", "DF1", True),
        ("DF[DS1]", "DD1", True),
        ("CTD[DS1]", "DF1", True),
        ("DF1", "CTD[DS1]", True),
        ("DF1", "DF1", False),
        ("1.5", "DS1", False),
        ("1.5", "DF1", False),
    ],
)
def test_type_7_decodes_only_where_click_saves_it(
    source: str, destination: str, decodes: bool
) -> None:
    """Type 7 for any other pair is no blob CLICK saves: it stays raw()."""
    parsed = from_tags("Copy", 0x2721, {0x6074: source, 0x6076: destination, 0x2227: "7"})
    assert (parsed is not None) is decodes
    if parsed is not None:
        assert parsed == Copy(source, destination)


@pytest.mark.parametrize(
    ("source", "destination", "end"),
    [
        ("-5", "TXT1", "TXT2"),
        ("+5", "TXT1", "TXT2"),  # the end counts the + and the h
        ("1h", "TXT1", "TXT2"),
        ("10h", "TXT1", "TXT3"),
        ("FFh", "TXT1", "TXT3"),
        ("0FFh", "TXT1", "TXT4"),
        ("FFFFh", "TXT1", "TXT5"),
        ("0FFh", "TXT10", "TXT13"),
        ("-2147483648", "TXT1", "TXT11"),
        ("-5", "TXT999", "TXT1000"),
        ("5", "TXT1", ""),  # one character
        ("-5", "TXT[DS1]", ""),  # a pointer
        ("DS1", "TXT1", ""),
        ("DD[DS1]", "TXT1", ""),  # CLICK's: an integer pointer, type 1 and no end
        ("DS[DS1]", "TXT1", ""),
    ],
)
def test_a_number_into_txt_writes_the_end_its_text_fills(
    source: str, destination: str, end: str
) -> None:
    copy = Copy(source, destination, convert="to_text", suppress_zero=True)
    written = copy.build_blob()
    assert _tags(written)[0x6077] == end
    assert _tags(written)[0x2227] == "1"
    assert parse_af_blob(written) == copy


@pytest.mark.parametrize(
    ("source", "destination", "end"),
    [
        ("1.5", "TXT1", "TXT3"),  # CLICK's
        ("-1.5", "TXT1", "TXT4"),
        ("100000.0", "TXT10", "TXT17"),
        ("1.5", "TXT[DS1]", ""),  # a pointer
        ("DF1", "TXT1", ""),
        ("DF[DS1]", "TXT1", ""),  # CLICK's
    ],
)
@pytest.mark.parametrize(("exponential", "conv"), [(False, "3"), (True, "4")])
def test_a_real_into_txt_writes_its_numbering_and_end(
    source: str, destination: str, end: str, exponential: bool, conv: str
) -> None:
    """A real constant or a DF source, a pointer too, takes real (3) or exponential (4)
    numbering, with 0x2206 set for exponential."""
    copy = Copy(source, destination, convert="to_text", exponential=exponential)
    written = _tags(copy.build_blob())
    assert (written[0x2227], written[0x2206], written[0x6077]) == (conv, str(int(exponential)), end)
    assert parse_af_blob(copy.build_blob()) == copy
    assert copy.to_csv() == (
        f"copy({source},{destination},"
        f"convert=to_text(exponential={int(exponential)},termination_code=none))"
    )


def test_a_number_with_zeros_kept_writes_its_end() -> None:
    """The end counts the constant as typed, whichever option the text takes."""
    copy = Copy("-5", "TXT1", convert="to_text", suppress_zero=False)
    assert (_tags(copy.build_blob())[0x2227], _tags(copy.build_blob())[0x6077]) == ("2", "TXT2")
    assert parse_af_blob(copy.build_blob()) == copy


@pytest.mark.parametrize(
    ("source", "destination", "end"),
    [
        ("-5", "TXT1000", "TXT1001"),  # CLICK's answer
        ("FFh", "TXT999", "TXT1001"),
        ("+5", "TXT1000", "TXT1001"),
        ("1.5", "TXT999", "TXT1001"),
    ],
)
def test_a_number_whose_text_passes_txt1000_is_refused(
    source: str, destination: str, end: str
) -> None:
    """CLICK shows the end past TXT1000 and refuses it as outside the range (OBJ-003)."""
    with pytest.raises(FieldError) as raised:
        Copy(source, destination, convert="to_text")
    [error] = raised.value.errors
    assert (error.field, error.reason, error.click_id) == (
        "Copy.dest",
        Reason.RANGE,
        "OBJ-003",
    )
    assert end in str(error)


@pytest.mark.parametrize("destination", ["DF1", "DF[DS1]"])
def test_a_hex_constant_above_ffffh_into_df_is_refused(destination: str) -> None:
    """CLICK refuses 10000h into DF1 as a combination it does not allow (OBJ-024)."""
    with pytest.raises(FieldError) as raised:
        Copy("10000h", destination)
    [error] = raised.value.errors
    assert (error.field, error.click_id) == ("Copy.dest", "OBJ-024")


@pytest.mark.parametrize(
    ("source", "end", "conv", "decodes"),
    [
        ("-5", "TXT2", "1", True),  # CLICK's
        ("1.5", "TXT3", "3", True),  # CLICK's
        ("1.5", "TXT3", "4", True),  # CLICK's
        ("-5", "", "1", True),  # an integer with no end, as laddercodec 0.4.0 wrote it
        ("1.5", "", "1", True),  # a real, as laddercodec 0.4.0 wrote it
        ("-5", "TXT2", "4", False),  # exponential numbering for an integer
        ("-5", "TXT3", "1", False),  # an end the text does not fill
        ("-5", "TXT2", "3", False),  # an integer's end with a real's type
        ("1.5", "TXT3", "1", False),  # a real's end with an integer's type
        ("-5", "TXT2", "2", True),  # zeros kept
        ("-5", "TXT2", "0", False),
        ("5", "TXT1", "1", False),  # one character has no end
    ],
)
def test_a_number_end_decodes_only_as_click_saves_it(
    source: str, end: str, conv: str, decodes: bool
) -> None:
    tags = {0x6074: source, 0x6076: "TXT1", 0x2227: conv}
    if end:
        tags[0x6077] = end
    parsed = from_tags_af("Copy", 0x2721, tags)
    assert (parsed is not None) is decodes
    if parsed is None:
        return
    if source == "1.5":
        expected = Copy(source, "TXT1", convert="to_text", exponential=conv == "4")
    else:
        expected = Copy(source, "TXT1", convert="to_text", suppress_zero=conv != "2")
    assert parsed == expected
    assert not refusals(parsed)


@pytest.mark.parametrize(
    ("source", "conv", "decodes"),
    [
        ("DF[DS1]", "3", True),  # CLICK's
        ("DF[DS1]", "4", True),  # CLICK's
        ("DD[DS1]", "1", True),  # CLICK's
        ("DS[DS1]", "1", True),  # CLICK's
        ("DD[DS1]", "4", False),  # exponential numbering for an integer pointer
    ],
)
def test_a_pointer_into_txt_decodes_by_its_bank(source: str, conv: str, decodes: bool) -> None:
    parsed = from_tags("Copy", 0x2721, {0x6074: source, 0x6076: "TXT1", 0x2227: conv})
    assert (parsed is not None) is decodes
    if parsed is not None:
        assert not refusals(parsed)
        assert parsed.to_csv().startswith(f"copy({source},TXT1,convert=to_text(")


def _with_tags(blob: bytes, changes: dict[int, str]) -> bytes:
    """*blob* with the tags in *changes* holding their new values."""
    class_name, type_code, _parts, _extra, fields = _decompose_blob(blob)
    tags = tuple(tag for tag, _sentinel, _value in fields)
    values = [changes.get(tag, value) for tag, _sentinel, value in fields]
    return _build_blob(class_name, type_code, tags, values)


@pytest.mark.parametrize(
    ("copy", "changes"),
    [
        # A real or DF source saved with type 1, as laddercodec 0.4.0 wrote it: the
        # encoder writes real numbering (type 3) and the end.
        (Copy("1.5", "TXT1", convert="to_text"), {0x2227: "1", 0x6077: ""}),
        (Copy("1.5", "TXT[DS1]", convert="to_text"), {0x2227: "1"}),
        (Copy("DF[DS1]", "TXT1", convert="to_text"), {0x2227: "1"}),
        # An integer's text with no end: the encoder writes the end it fills.
        (Copy("-5", "TXT1", convert="to_text", suppress_zero=True), {0x6077: ""}),
        # An integer outside int16 into DF as type 0: the encoder writes type 7.
        (Copy("2147483647", "DF1"), {0x2227: "0"}),
    ],
)
def test_a_save_the_encoder_writes_otherwise_keeps_its_blob(
    copy: Copy, changes: dict[int, str]
) -> None:
    """A decoded Copy whose conversion type or end differs from what its fields write
    writes the stored blob while unchanged, and the encoder's blob once changed."""
    stored = _with_tags(copy.build_blob(), changes)
    assert stored != copy.build_blob()
    parsed = parse_af_blob(stored)
    assert parsed == copy
    assert parsed.build_blob() == stored
    assert replace(parsed).build_blob() == copy.build_blob()


CAPTURES = Path(__file__).resolve().parents[1] / "fixtures" / "v4_captures" / "copy_single"

#: Each CLICK v4 capture of a single Copy CLICK accepted: the case and the CSV decode writes.
_TO_TEXT = "convert=to_text(suppress_zero=1,termination_code=none)"
_REAL = "convert=to_text(exponential=0,termination_code=none)"
_EXPONENTIAL = "convert=to_text(exponential=1,termination_code=none)"
CAPTURED = [
    ("case01", "copy(CTD1,DF1)"),
    ("case02", "copy(DF1,CTD1)"),
    ("case03", "copy(1.5,DD1)"),
    ("case04", "copy(1.5,CTD1)"),
    ("case05", "copy(1.5,CTD[DS1])"),
    ("case06", f"copy(-5,TXT1,{_TO_TEXT})"),
    ("case07", f"copy(1h,TXT1,{_TO_TEXT})"),
    ("case08", f"copy(10h,TXT1,{_TO_TEXT})"),
    ("case09", f"copy(0FFh,TXT1,{_TO_TEXT})"),
    ("case10", f"copy(FFFFh,TXT1,{_TO_TEXT})"),
    ("case11", f"copy(+5,TXT1,{_TO_TEXT})"),
    ("case12", "copy(32767,DF1)"),
    ("case13", "copy(32768,DF1)"),
    ("case14", "copy(-32768,DF1)"),
    ("case15", "copy(-32769,DF1)"),
    ("case16", "copy(65535,DF1)"),
    ("case17", "copy(65536,DF1)"),
    ("case19", "copy(2147483647,DF[DS1])"),
    ("case21", f"copy(1.5,TXT1,{_REAL})"),
    ("case22", f"copy(1.5,TXT1,{_EXPONENTIAL})"),
    ("case23", f"copy(DF[DS1],TXT1,{_REAL})"),
    ("case24", f"copy(DF[DS1],TXT1,{_EXPONENTIAL})"),
    ("case25", f"copy(DF[DS1],TXT1,{_REAL})"),  # Suppress zero asked for; not offered
    ("case26", f"copy(DD[DS1],TXT1,{_TO_TEXT})"),
    ("case27", f"copy(DS[DS1],TXT1,{_TO_TEXT})"),
]

#: Saves whose tags are the ones the encoder writes, but 0x1201: a plain copy (type 0) and
#: a pointer's text.  They keep no stored blob, so they write 0x1201 as laddercodec does.
_ENCODERS = ("case12", "case14", "case23", "case24", "case25", "case26", "case27")


def _clip_blob(clip: bytes) -> bytes:
    """The Copy blob in a one-Copy clipboard capture, to the end of the buffer."""
    return clip[clip.index("Copy".encode("utf-16-le") + b"\x00\x00") :]


def _one_copy(rungs: object) -> Copy:
    rung = rungs[0]
    [copy] = [t for t in rung.instructions if isinstance(t, Copy)]
    return copy


@pytest.mark.parametrize(("case", "csv"), CAPTURED)
def test_a_click_capture_decodes_as_the_copy_and_writes_its_bytes(case: str, csv: str) -> None:
    clip = (CAPTURES / f"{case}.bin").read_bytes()
    from_clip = _one_copy(decode(clip))
    from_scr = _one_copy(decode_program((CAPTURES / f"{case}.scr").read_bytes()).rungs)
    for copy in (from_clip, from_scr):
        assert copy.to_csv() == csv
        assert not refusals(copy)
    assert from_clip == from_scr
    if case in _ENCODERS:
        # It writes the encoder's blob, which differs from CLICK's only in the text flag:
        # CLICK v4 sets 0x1201 on every save and ignores it on load.
        assert stored_blob(from_clip) is None
        assert stored_blob(from_scr) is None
        click = _tags(_clip_blob(clip))
        ours = _tags(from_clip.build_blob())
        assert (click.pop(0x1201), ours.pop(0x1201)) == ("-1", "0")
        assert ours == click
        return
    # Unchanged, each writes the blob it was decoded from: the clipboard's, and the one
    # composed from the program file's tags.
    assert _clip_blob(clip).startswith(from_clip.build_blob())
    assert stored_blob(from_scr) is not None
    assert from_scr.build_blob() == stored_blob(from_scr)


@pytest.mark.parametrize(("case", "csv"), CAPTURED)
def test_the_copy_a_capture_reads_as_writes_clicks_tags(case: str, csv: str) -> None:
    """Built from its CSV, the Copy writes every tag CLICK's clipboard holds, but the text
    flag: CLICK v4 sets 0x1201 on every save and ignores it on load."""
    click = _tags(_clip_blob((CAPTURES / f"{case}.bin").read_bytes()))
    ours = _tags(Copy.from_csv_token(csv).build_blob())
    assert (click.pop(0x1201), ours.pop(0x1201)) == ("-1", "0")
    assert ours == click
