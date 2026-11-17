"""Test a single Copy in each form that CLICK's dialog saves, and the forms that it refuses.

The CLICK v4 captures in ``tests/fixtures/v4_captures/copy_forms/`` show what CLICK saves.
They include these single Copies:

- Copy Binary of a value converted between a real and a 32-bit integer
- the same conversion with a pointer on either side
- a hex word copied into DF
- a number copied into TXT as text
- a real of 7 significant digits
- text that holds ``é``, a tab, ``€`` or a control character
- quoted text saved with its destination end, and pasted text saved without one

The same folder holds a Search of ``"é"`` and a Math with a real of 6 significant digits.
"""

from __future__ import annotations

import csv
import re
from dataclasses import replace
from pathlib import Path

import pytest

from laddercodec import Rung, decode, decode_program, encode, read_csv, write_csv
from laddercodec.binary_helpers import _build_blob
from laddercodec.csv import CSV_HEADER
from laddercodec.errors import CsvError
from laddercodec.instructions import from_tags_af, parse_af_blob
from laddercodec.instructions.copy import BlockCopy, Copy, Fill, Pack, Unpack
from laddercodec.instructions.math import Math
from laddercodec.instructions.raw import _decompose_blob, _fields_to_tag_dicts
from laddercodec.instructions.search import Search
from laddercodec.operands.errors import FieldError, Reason
from laddercodec.operands.unchecked import refusals, stored_blob

CAPTURES = Path(__file__).resolve().parents[1] / "fixtures" / "v4_captures" / "copy_forms"

_TO_TEXT = "convert=to_text(suppress_zero=1,termination_code=none)"
_TO_TEXT_ZEROS = "convert=to_text(suppress_zero=0,termination_code=none)"
_TO_REAL_TEXT = "convert=to_text(exponential=0,termination_code=none)"


def _tags(blob: bytes) -> dict[int, str]:
    """Return each tag that *blob* holds, mapped to its value."""
    return {tag: value for tag, _sentinel, value in _decompose_blob(blob)[4]}


def _clip_blob(clip: bytes) -> bytes:
    """Return the bytes of *clip* from the start of its Copy blob to the end of the buffer.

    *clip* is a clipboard capture that holds one Copy.
    """
    return clip[clip.index("Copy".encode("utf-16-le") + b"\x00\x00") :]


def _copies(rungs: list[Rung]) -> list[Copy]:
    return [t for rung in rungs for t in rung.instructions if isinstance(t, Copy)]


def _errors(build) -> list[FieldError]:
    with pytest.raises(FieldError) as raised:
        build()
    return list(raised.value.errors)


def _write_af(path: Path, af: str) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        writer.writerow(["R", "X001"] + ["-"] * 30 + [af])


def _read_af(tmp_path: Path, af: str) -> object:
    path = tmp_path / "rung.csv"
    _write_af(path, af)
    [found] = [t for t in read_csv(path)[0].instructions if t]
    return found


def _stored(tags: dict[int, str]) -> bytes:
    """Return a Copy blob that holds ``tags``, in the form that a program file or an older
    laddercodec stores."""
    return _build_blob("Copy", 0x2721, (*tags, 0x0000), [*tags.values(), ""])


def _both_paths(tags: dict[int, str]) -> Copy:
    """Return the Copy that the clipboard decoder builds from ``tags``.

    Assert that the program-file decoder builds the same Copy with the same refusals. If the
    Copy keeps its stored blob, assert that it writes that blob back."""
    blob = _stored(tags)
    from_clip = parse_af_blob(blob)
    from_scr = from_tags_af("Copy", 0x2721, tags)
    assert isinstance(from_clip, Copy)
    assert from_scr == from_clip
    assert [str(e) for e in refusals(from_scr)] == [str(e) for e in refusals(from_clip)]
    if stored_blob(from_clip) is not None:
        # An unchanged Copy writes the bytes that it was decoded from.
        assert from_clip.build_blob() == blob
    return from_clip


# ---------------------------------------------------------------------------
# CLICK's captures
# ---------------------------------------------------------------------------

#: The name of each capture, and the CSV token of the Copy that decode() reads from it.
CAPTURED = [
    ("case01", "copy(CTD1,DF1,convert=to_binary)"),
    ("case02", "copy(DF1,CTD1,convert=to_binary)"),
    ("case03", "copy(1.5,DD1,convert=to_binary)"),
    ("case04", "copy(1.5,CTD1,convert=to_binary)"),
    ("case05", "copy(32768,DF1,convert=to_binary)"),
    ("case06", "copy(65536,DF1,convert=to_binary)"),
    ("case07", "copy(CTD1,DF1)"),
    ("case08", "copy(1.5,DD1)"),
    ("case09", "copy(DF[DS1],DD1)"),
    ("case10", "copy(DD[DS1],DF1)"),
    ("case11", "copy(CTD[DS1],DF1)"),
    ("case12", "copy(FFFFh,DF1)"),
    ("case13", "copy(0FFFFh,DF1)"),
    ("case14", f"copy(123,TXT1,{_TO_TEXT_ZEROS})"),
    ("case15", f"copy(123,TXT1,{_TO_TEXT})"),
    ("case16", f"copy(5,TXT1,{_TO_TEXT})"),
    ("case17", "copy(3.402823E+38,DF1)"),
    ("case18", f"copy(3.402823E+38,TXT1,{_TO_REAL_TEXT})"),
    ("case19", 'copy("é",TXT1)'),
    ("case20", 'copy("\t",TXT1)'),
    ("case21", 'copy("HALLO",TXT1)'),
    ("case22", 'copy("AB",TXT999)'),
    ("case23", "copy(TXT1,DF1)"),
    ("case24", "copy(DF[DS1],CTD1,convert=to_binary)"),
    ("case25", "copy(CTD1,DF[DS1],convert=to_binary)"),
    ("case26", "copy(DF1,CTD[DS1])"),
    ("case27", 'copy("€",TXT1)'),
    ("case28", 'copy("\x01",TXT1)'),
]

#: The captures whose source is a text constant. CLICK v4 sets the text flag 0x1201 on every
#: save, and laddercodec sets it for a text constant, so laddercodec writes these blobs byte
#: for byte as CLICK does.
_TEXT = ("case19", "case20", "case21", "case22", "case27", "case28")

#: The captures that CLICK saved as conversion type 7 or 8 for a pair other than a DD address
#: and a DF address. The decoder keeps CLICK's blob for each of them.
_OTHER_TYPE_7 = (*(f"case{n:02d}" for n in range(1, 12)), "case24", "case25", "case26")


@pytest.mark.parametrize(("case", "csv_text"), CAPTURED)
def test_a_click_capture_decodes_as_its_copy(case: str, csv_text: str) -> None:
    clip = (CAPTURES / f"{case}.bin").read_bytes()
    [from_clip] = _copies(decode(clip))
    [from_scr] = _copies(decode_program((CAPTURES / f"{case}.scr").read_bytes()).rungs)
    for found in (from_clip, from_scr):
        assert found.to_csv() == csv_text
        assert not refusals(found)
    assert from_clip == from_scr
    if stored_blob(from_clip) is not None:
        # An unchanged Copy writes the blob that CLICK saved.
        assert _clip_blob(clip).startswith(from_clip.build_blob())
    if case in _OTHER_TYPE_7:
        assert stored_blob(from_clip) is not None


@pytest.mark.parametrize(("case", "csv_text"), CAPTURED)
def test_the_copy_a_capture_reads_as_writes_clicks_tags(
    tmp_path: Path, case: str, csv_text: str
) -> None:
    """A Copy read from the capture's CSV token writes the same tags as CLICK's clipboard.

    The one difference is the text flag 0x1201. Where the source is not a text constant,
    CLICK sets the flag and laddercodec does not."""
    click = _tags(_clip_blob((CAPTURES / f"{case}.bin").read_bytes()))
    built = _read_af(tmp_path, csv_text)
    assert isinstance(built, Copy)
    assert built.to_csv() == csv_text
    assert Copy.from_csv_token(csv_text) == built
    ours = _tags(built.build_blob())
    if case not in _TEXT:
        assert (click.pop(0x1201), ours.pop(0x1201)) == ("-1", "0")
    assert ours == click
    assert parse_af_blob(built.build_blob()) == built


@pytest.mark.parametrize("case", _TEXT)
def test_a_text_copy_encodes_as_clicks_clip(tmp_path: Path, case: str) -> None:
    """A Copy of a text constant writes CLICK's blob byte for byte, including the destination
    end, the last TXT that the text fills.

    The cases include ``é``, a tab, ``€`` and a control character. The decoded Copy keeps no
    stored blob and writes the same bytes."""
    clip = (CAPTURES / f"{case}.bin").read_bytes()
    csv_text = dict(CAPTURED)[case]
    built = _read_af(tmp_path, csv_text)
    assert _clip_blob(clip).startswith(built.build_blob())
    [decoded] = _copies(decode(clip))
    assert stored_blob(decoded) is None
    assert decoded.build_blob() == built.build_blob()


# ---------------------------------------------------------------------------
# Quoted text saved without its destination end (a paste)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "texts"),
    [("paste01", ['"HALLO"']), ("paste02", ['"HELLO"', '"HALLO"'])],
)
def test_pasted_text_saved_without_its_end_decodes_as_the_copy(case: str, texts: list) -> None:
    """When CLICK pastes a Copy of text, it saves the text and no destination end.

    The Copy decodes with no refusal. While it is unchanged, it writes the blob that it was
    decoded from."""
    found = _copies(decode_program((CAPTURES / f"{case}.scr").read_bytes()).rungs)
    assert found == [Copy(text, "TXT1") for text in texts]
    for copy in found:
        assert not refusals(copy)
        blob = stored_blob(copy)
        assert blob is not None
        assert 0x6077 not in {k for k, v in _tags(blob).items() if v}
        # A copy made by replace() has no stored blob. It writes the end that its text
        # fills, as CLICK's clipboard does.
        assert _tags(replace(copy).build_blob())[0x6077] == "TXT5"


@pytest.mark.parametrize(
    ("source", "destination", "end"),
    [
        ('"TT"', "TXT1", "TXT2"),
        ('"AB"', "TXT999", "TXT1000"),  # the last TXT
        ('"é\t"', "TXT10", "TXT11"),
        ('"A"', "TXT1", ""),  # one character has no end
        ('"AB"', "TXT[DS1]", ""),  # a pointer destination has no end either
    ],
)
def test_text_without_its_end_decodes_on_both_paths(
    source: str, destination: str, end: str
) -> None:
    found = _both_paths({0x6074: source, 0x6076: destination})
    assert found == Copy(source, destination)
    assert not refusals(found)
    # The encoder writes the end. A save that lacks an end the encoder would write keeps its
    # blob.
    assert _tags(Copy(source, destination).build_blob())[0x6077] == end
    assert (stored_blob(found) is not None) is bool(end)


def test_text_without_its_end_past_txt1000_keeps_obj_003() -> None:
    found = _both_paths({0x6074: '"ABC"', 0x6076: "TXT999"})
    [error] = refusals(found)
    assert (error.field, error.click_id) == ("Copy.dest", "OBJ-003")
    with pytest.raises(FieldError, match="OBJ-003"):
        replace(found)


# ---------------------------------------------------------------------------
# A number into TXT needs a converter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "destination", "option"),
    [
        ("5", "TXT1", "suppress_zero=1"),
        ("123", "TXT1", "suppress_zero=1"),
        ("-5", "TXT999", "suppress_zero=1"),
        ("FFh", "TXT1", "suppress_zero=1"),
        ("1.5", "TXT1", "exponential=0"),
        ("DS1", "TXT1", "suppress_zero=1"),
        ("XD0", "TXT1", "suppress_zero=1"),
        ("DF1", "TXT1", "exponential=0"),
        ("DD[DS1]", "TXT1", "suppress_zero=1"),
        ("DF[DS1]", "TXT1", "exponential=0"),
        ("DS1", "TXT[DS1]", "suppress_zero=1"),
        ("5", "TXT[DS1]", "suppress_zero=1"),
    ],
)
def test_a_number_into_txt_needs_a_converter(
    tmp_path: Path, source: str, destination: str, option: str
) -> None:
    """A plain copy of a number into TXT is refused, because CLICK's dialog never saves one.

    The dialog saves the number as text (Copy Value) or as binary (Copy Binary). The message
    names CLICK's default text option. That is Suppress zero for an integer source, and real
    numbering for a DF source or a real constant. A Copy with that converter round-trips
    through its blob."""
    [error] = _errors(lambda: Copy(source, destination))
    assert error.fields == ("Copy.convert", "Copy.source", "Copy.dest")
    assert (error.reason, error.click_id) == (Reason.CONFLICT, None)
    assert f"convert=to_text({option},termination_code=none), CLICK's default" in str(error)
    assert "convert=to_binary" in str(error)
    with pytest.raises(FieldError, match="needs a converter"):
        _read_af(tmp_path, f"copy({source},{destination})")
    with pytest.raises(FieldError, match="needs a converter"):
        Copy.from_csv_token(f"copy({source},{destination})")
    name, value = option.split("=")
    copy = Copy(source, destination, convert="to_text", **{name: value == "1"})
    assert parse_af_blob(copy.build_blob()) == copy


@pytest.mark.parametrize(
    ("source", "destination"),
    [('"AB"', "TXT1"), ("$41", "TXT1"), ("TXT1", "TXT2"), ("TXT[DS1]", "TXT2")],
)
def test_text_into_txt_takes_no_converter(source: str, destination: str) -> None:
    copy = Copy(source, destination)
    assert _tags(copy.build_blob())[0x2227] == "0"


@pytest.mark.parametrize(("source", "destination"), [("DS1", "TXT1"), ("5", "TXT1")])
def test_a_stored_plain_number_copy_into_txt_keeps_its_refusal(
    source: str, destination: str
) -> None:
    """A plain copy of a number into TXT, as laddercodec 0.4.0 wrote it, decodes as a Copy
    that holds the refusal.

    While the Copy is unchanged, it writes the bytes that it was decoded from. A copy made by
    replace() raises the refusal."""
    found = _both_paths({0x6074: source, 0x6076: destination})
    assert found.convert is None
    [error] = refusals(found)
    assert error.fields == ("Copy.convert", "Copy.source", "Copy.dest")
    with pytest.raises(FieldError, match="needs a converter"):
        replace(found)


def test_a_block_copy_of_numbers_into_txt_stays_refused() -> None:
    """CLICK's dialog refuses a range of number registers into TXT (OBJ-024)."""
    [error] = _errors(lambda: BlockCopy("DS1", "DS2", "TXT1", "TXT2"))
    assert error.click_id == "OBJ-024"


@pytest.mark.parametrize(
    ("source", "suppress_zero", "conv", "field4", "end"),
    [
        ("123", False, "2", "1", "TXT3"),  # a CLICK capture
        ("123", True, "1", "0", "TXT3"),  # a CLICK capture
        ("5", True, "1", "0", ""),  # a CLICK capture: one character has no end
        ("5", False, "2", "1", ""),
    ],
)
def test_an_integer_into_txt_writes_its_suppress_zero(
    source: str, suppress_zero: bool, conv: str, field4: str, end: str
) -> None:
    copy = Copy(source, "TXT1", convert="to_text", suppress_zero=suppress_zero)
    written = _tags(copy.build_blob())
    assert (written[0x2227], written[0x2206], written[0x6077]) == (conv, field4, end)


# ---------------------------------------------------------------------------
# Copy Binary of a value converted between a real and a 32-bit integer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "destination"),
    [
        ("CTD1", "DF1"),
        ("DF1", "CTD1"),
        ("1.5", "DD1"),
        ("1.5", "CTD1"),
        ("32768", "DF1"),
        ("65536", "DF1"),
        ("-32769", "DF1"),
        ("DD1", "DF1"),  # Copy Binary between DD and DF
        ("DF1", "DD1"),
    ],
)
def test_copy_binary_writes_type_8(source: str, destination: str) -> None:
    copy = Copy(source, destination, convert="to_binary")
    written = _tags(copy.build_blob())
    assert (written[0x2227], written[0x2206]) == ("8", "1")
    assert parse_af_blob(copy.build_blob()) == copy


@pytest.mark.parametrize(
    ("source", "destination"),
    [
        ("DF[DS1]", "CTD1"),  # a CLICK capture
        ("CTD1", "DF[DS1]"),  # a CLICK capture
        ("DF[DS1]", "DD1"),
        ("DD[DS1]", "DF1"),
        ("CTD[DS1]", "DF1"),
        ("DF1", "CTD[DS1]"),
        ("DD1", "DF[DS1]"),
        ("1.5", "DD[DS1]"),
        ("65536", "DF[DS1]"),
    ],
)
def test_copy_binary_with_a_pointer_writes_type_8(source: str, destination: str) -> None:
    """Copy Binary writes type 8 when either side is a pointer, as for addresses.

    The conversion type follows the pair of banks, whether each side is an address or a
    pointer. Both decoders read the blob back as the same Copy with no refusal."""
    copy = Copy(source, destination, convert="to_binary")
    written = _tags(copy.build_blob())
    assert (written[0x2227], written[0x2206]) == ("8", "1")
    assert parse_af_blob(copy.build_blob()) == copy
    found = _both_paths({0x6074: source, 0x6076: destination, 0x2206: "1", 0x2227: "8"})
    assert found == copy
    assert not refusals(found)


@pytest.mark.parametrize(
    ("source", "destination"),
    [("DF1", "CTD[DS1]"), ("CTD1", "DF[DS1]"), ("DD1", "DF[DS1]"), ("DF1", "DD[DS1]")],
)
def test_a_plain_copy_into_a_pointer_writes_type_7(source: str, destination: str) -> None:
    # CLICK saves DF1 into CTD[DS1] as type 7, as it does DF1 into CTD1.
    assert _tags(Copy(source, destination).build_blob())[0x2227] == "7"


@pytest.mark.parametrize(("source", "destination"), [("DS1", "DF1"), ("5", "DF1"), ("DD1", "DS1")])
def test_copy_binary_for_another_pair_is_refused(source: str, destination: str) -> None:
    [error] = _errors(lambda: Copy(source, destination, convert="to_binary"))
    assert error.reason is Reason.CONFLICT
    assert "to_binary copies a number to TXT, or a value between a real and" in str(error)
    # A decoded save of such a Copy Binary keeps the refusal. CLICK never saves type 7 for
    # these pairs, so from_tags_af() does not read a type 7 save as a Copy.
    tags = {0x6074: source, 0x6076: destination, 0x2206: "1", 0x2227: "8"}
    assert [e.fields for e in refusals(_both_paths(tags))] == [error.fields]
    assert from_tags_af("Copy", 0x2721, {**tags, 0x2227: "7"}) is None


# ---------------------------------------------------------------------------
# Hex words into DF
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["FFFFh", "0FFFFh", "FFh", "0h"])
def test_a_hex_word_into_df_is_kept_as_typed(source: str) -> None:
    copy = Copy(source, "DF1")
    written = _tags(copy.build_blob())
    assert (written[0x6074], written[0x2227]) == (source, "0")


# ---------------------------------------------------------------------------
# A real constant keeps 7 significant digits
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "destination", "options", "kept"),
    [
        ("3.4028235E+38", "DF1", {}, "3.402823E+38"),  # a CLICK capture
        ("3.4028235E+38", "TXT1", {"convert": "to_text"}, "3.402823E+38"),  # a CLICK capture
        ("-3.4028235E+38", "DF1", {}, "-3.402823E+38"),
        ("1.2345678", "DF1", {}, "1.234568"),
        ("1.23456789", "DD1", {}, "1.234568"),
        ("0.00012345678", "DF1", {}, "0.0001234568"),
        ("12345678.0", "DF1", {}, "1.234568E+07"),
        ("1234567.89", "DF1", {}, "1234568.0"),
        ("1.2345678E+20", "DF1", {}, "1.234568E+20"),
    ],
)
def test_a_real_beyond_seven_significant_digits_is_refused(
    tmp_path: Path, typed: str, destination: str, options: dict, kept: str
) -> None:
    """A real with more than 7 significant digits is refused, by Copy() and by read_csv().

    CLICK keeps 7 significant digits, and it shortens a longer real when it saves. A CSV
    states the value that its author meant, so laddercodec refuses the longer real instead of
    shortening it. The message gives the value in 7 digits."""
    [error] = _errors(lambda: Copy(typed, destination, **options))
    assert (error.field, error.reason, error.click_id) == ("Copy.source", Reason.FORM, None)
    assert str(error).endswith(f"CLICK keeps 7 significant digits: write {kept}")
    with pytest.raises(FieldError, match=re.escape(f"write {kept}")):
        _read_af(tmp_path, Copy(kept, destination, **options).to_csv().replace(kept, typed))
    assert Copy(kept, destination, **options).source == kept


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("1.234567", "1.234567"),
        ("1.2345670", "1.234567"),  # a trailing zero is not a significant digit
        ("0.0001234567", "0.0001234567"),  # nor is a leading zero
        ("1234567.0", "1234567.0"),
        ("1.234567E+20", "1.234567E+20"),
        ("100000000.0", "100000000.0"),
        ("3.402823E+38", "3.402823E+38"),
    ],
)
def test_a_real_of_seven_significant_digits_is_kept(typed: str, stored: str) -> None:
    assert Copy(typed, "DF1").source == stored


def test_an_integer_has_no_digit_limit() -> None:
    assert Copy("2147483647", "DD1").source == "2147483647"
    assert Copy("-2147483648", "DF1").source == "-2147483648"


def test_the_txt_end_of_a_real_counts_clicks_form() -> None:
    copy = Copy("3.402823E+38", "TXT1", convert="to_text")
    assert _tags(copy.build_blob())[0x6077] == "TXT12"


def test_a_stored_real_beyond_seven_digits_keeps_its_refusal() -> None:
    found = _both_paths({0x6074: "3.4028235E+38", 0x6076: "DF1"})
    assert found.source == "3.4028235E+38"
    [error] = refusals(found)
    assert error.field == "Copy.source"
    with pytest.raises(FieldError, match="write 3.402823E"):
        replace(found)


# ---------------------------------------------------------------------------
# Text holding any character CLICK keeps
# ---------------------------------------------------------------------------

#: Text that CLICK keeps as typed, and characters that could break a CSV line: line breaks,
#: other separators and a byte-order mark. The captures show that CLICK keeps é, a tab, €
#: and U+0001.
_KEPT_TEXT = [
    *('"é"', '"\t"', '"€"', '"\x01"', '"A\tBé"', '"\xa0"', '"\xff"', '"ABC\t"'),
    *('"A\nB"', '"\r"', '"A\r\nB"', '"\x0b\x0c"', '"\x1c\x1e\x1f"', '"\x7f\x85"'),
    *('"\u2028\u2029"', '"\ufeff"', '"\uffff"', '"A,B)=C"'),
]


def _round_trip(tmp_path: Path, inst: object, token: str) -> object:
    """Write ``inst`` with write_csv, check that the file holds ``token``, and return what
    read_csv reads back.

    Also check that ``inst`` survives encode() and decode()."""
    path = tmp_path / "written.csv"
    [rung] = decode((CAPTURES / "case21.bin").read_bytes())
    write_csv(path, [replace(rung, instructions=[inst, ""])])
    assert token.replace('"', '""') in path.read_bytes().decode("utf-8")
    [back] = [t for t in read_csv(path)[0].instructions if t]
    [back_rung] = decode(encode(replace(rung, instructions=[inst, ""])))
    [decoded] = [t for t in back_rung.instructions if t]
    assert decoded == inst
    return back


@pytest.mark.parametrize("text", _KEPT_TEXT)
def test_copy_text_of_any_character_click_keeps_round_trips(tmp_path: Path, text: str) -> None:
    """A Copy keeps each character of its text as typed, as CLICK does, in one TXT per
    character.

    The blob holds the text in UTF-16LE. write_csv writes it inside the quotes, and read_csv
    reads it back unchanged."""
    copy = Copy(text, "TXT1")
    assert copy.source == text
    assert text.encode("utf-16-le") in copy.build_blob()
    assert _tags(copy.build_blob())[0x6077] == ("" if len(text) == 3 else f"TXT{len(text) - 2}")
    assert _round_trip(tmp_path, copy, copy.to_csv()) == copy


@pytest.mark.parametrize("text", _KEPT_TEXT)
def test_search_text_takes_what_copy_takes(tmp_path: Path, text: str) -> None:
    search = Search("TXT1", "TXT10", text, "DS1", "C1", "==")
    assert _round_trip(tmp_path, search, search.to_csv()) == search


@pytest.mark.parametrize(
    "token",
    [
        "copy(DS1,\nDS2)",
        "copy(\nDS1,DS2)",
        "copy(DS1,DS2\n)",
        "copy(DS1,\rDS2)",
        "copy(DS1,DS2,\noneshot=1)",
        'copy("A",\nTXT1)',
        "blockcopy(DS1..DS2,\nDS10..DS11)",
        "fill(1,\nDS1..DS3)",
        "pack_text(TXT1..TXT4,\nDS1)",
        "unpack_to_bits(DS1,\nC1..C16)",
        "math(DS1 + 1,DS2,\nmode=decimal)",
        "math(DS1 +\n1,DS2,mode=decimal)",
        'search(TXT1..\nTXT10 == "A",result=DS1,found=C1)',
        'search(TXT1..TXT10 == "A",\nresult=DS1,found=C1)',
        "out(\nC1)",
    ],
)
def test_a_line_break_outside_quotes_is_refused(tmp_path: Path, token: str) -> None:
    """read_csv accepts a line break only inside quoted text. Anywhere else it raises
    CsvError."""
    with pytest.raises(CsvError):
        _read_af(tmp_path, token)


@pytest.mark.parametrize(
    ("token", "want"),
    [
        ('copy("A\nB",TXT1)', Copy('"A\nB"', "TXT1")),
        ('copy("A\r\nB",TXT[DS1])', Copy('"A\r\nB"', "TXT[DS1]")),
        (
            'search(TXT1..TXT10 == "A\nB",result=DS1,found=C1)',
            Search("TXT1", "TXT10", '"A\nB"', "DS1", "C1", "=="),
        ),
    ],
)
def test_a_line_break_inside_quotes_is_read(tmp_path: Path, token: str, want: object) -> None:
    assert _read_af(tmp_path, token) == want


@pytest.mark.parametrize(
    "text",
    ['"\x00"', '"A\x00"', '"\U0001f600"', '"\ud800"'],
)
def test_text_click_cannot_keep_is_refused(text: str) -> None:
    """Copy and Search refuse text that holds NUL, a surrogate or a character above U+FFFF.

    NUL ends a stored string, and the character code ``$00`` writes it. A surrogate or a
    character above U+FFFF is not one 16-bit character."""
    for build, field in (
        (lambda: Copy(text, "TXT1"), "Copy.source"),
        (lambda: Search("TXT1", "TXT10", text, "DS1", "C1", "=="), "Search.value"),
    ):
        [error] = _errors(build)
        assert (error.field, error.reason) == (field, Reason.FORM)
        assert "text holds characters U+0001 to U+FFFF, no NUL and no surrogate" in str(error)


def test_clicks_search_of_latin_1_text_decodes() -> None:
    clip = (CAPTURES / "search01.bin").read_bytes()
    want = Search("TXT1", "TXT10", '"é"', "DS1", "C1", "==")
    found = [
        *(t for rung in decode(clip) for t in rung.instructions if t),
        *(
            t
            for t in decode_program((CAPTURES / "search01.scr").read_bytes()).rungs[0].instructions
            if t
        ),
    ]
    assert found == [want, want]
    assert not any(refusals(t) for t in found)
    # A Search built from its fields writes CLICK's blob.
    blob = want.build_blob()
    assert clip[clip.index("Search".encode("utf-16-le") + b"\x00\x00") :][: len(blob)] == blob


def test_fill_text_stays_printable_ascii() -> None:
    with pytest.raises(FieldError, match="printable ASCII only"):
        Fill('"é"', "TXT1", "TXT3")


# ---------------------------------------------------------------------------
# A Math real keeps 6 significant digits
# ---------------------------------------------------------------------------


def test_clicks_math_of_a_long_real_saves_6_digits() -> None:
    """CLICK saves 0.33333334 typed into a Math as 0.333333."""
    want = Math("0.333333", "DF1")
    found = [
        *(
            t
            for rung in decode((CAPTURES / "math01.bin").read_bytes())
            for t in rung.instructions
            if t
        ),
        *(
            t
            for t in decode_program((CAPTURES / "math01.scr").read_bytes()).rungs[0].instructions
            if t
        ),
    ]
    assert found == [want, want]
    assert not any(refusals(t) for t in found)
    with pytest.raises(
        FieldError, match=r"CLICK keeps 6 significant digits in Math: write 0\.333333$"
    ):
        Math("0.33333334", "DF1")


def test_math_of_the_float32_edge_is_out_of_range() -> None:
    # CLICK refuses this Math with OBJ-1009.
    [error] = _errors(lambda: Math("3.4028235E+38", "DF1"))
    assert (error.click_id, error.reason) == ("OBJ-1009", Reason.RANGE)


# ---------------------------------------------------------------------------
# TXT into DF
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["to_value", "to_ascii"])
@pytest.mark.parametrize(("source", "destination"), [("TXT1", "DF1"), ("TXT[DS1]", "DF[DS1]")])
def test_txt_into_df_takes_no_converter(
    tmp_path: Path, fmt: str, source: str, destination: str
) -> None:
    """CLICK's dialog offers neither Copy Character Value nor Copy ASCII Code Value for TXT
    into DF, and saves a plain copy."""
    [error] = _errors(lambda: Copy(source, destination, convert=fmt))
    assert error.fields == ("Copy.convert", "Copy.source", "Copy.dest")
    assert error.reason is Reason.CONFLICT
    assert "CLICK copies TXT into DF with no converter" in str(error)
    with pytest.raises(FieldError, match="no converter"):
        _read_af(tmp_path, f"copy({source},{destination},convert={fmt})")
    assert _tags(Copy(source, destination).build_blob())[0x2227] == "0"
    # A decoded save with one of these converters keeps the refusal. While it is unchanged,
    # it writes the bytes that it was decoded from.
    conv = "5" if fmt == "to_value" else "6"
    tags = {0x6074: source, 0x6076: destination, 0x2227: conv}
    if fmt == "to_ascii":
        tags[0x2206] = "1"
    found = _both_paths(tags)
    assert found.convert == fmt
    assert [e.fields for e in refusals(found)] == [error.fields]


# ---------------------------------------------------------------------------
# CSV keywords and flags of the Copy family
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    [
        "fill(1,DS1..DS3,one_shot=1)",
        "fill(1,DS1..DS3,convert=to_text)",
        "pack_bits(C1..C16,DS1,allow_whitespace=1)",
        "pack_words(DS1..DS2,DD1,oneshoot=1)",
        "pack_text(TXT1..TXT4,DS1,allow_whitspace=1)",
        "unpack_to_bits(DS1,C1..C16,convert=to_value)",
        "unpack_to_words(DD1,DS1..DS2,termination_code=$0D)",
    ],
)
def test_a_keyword_the_call_does_not_take_is_refused(tmp_path: Path, token: str) -> None:
    """read_csv raises for a keyword that the call does not take, such as a misspelt one,
    instead of dropping it and its value."""
    with pytest.raises(CsvError, match="does not support keyword argument"):
        _read_af(tmp_path, token)


@pytest.mark.parametrize(
    ("token", "field"),
    [
        ("copy(DS1,DS2,oneshot=yes)", "Copy.oneshot"),
        ("blockcopy(DS1..DS2,DS11..DS12,oneshot=true)", "BlockCopy.oneshot"),
        ("fill(1,DS1..DS3,oneshot=2)", "Fill.oneshot"),
        ("pack_bits(C1..C16,DS1,oneshot=on)", "Pack.oneshot"),
        ("pack_text(TXT1..TXT4,DS1,allow_whitespace=yes)", "Pack.allow_whitespace"),
        ("unpack_to_words(DD1,DS1..DS2,oneshot=-1)", "Unpack.oneshot"),
    ],
)
def test_a_flag_other_than_0_or_1_is_refused(tmp_path: Path, token: str, field: str) -> None:
    """A flag is 1 or 0. read_csv refuses any other value, such as ``oneshot=yes``, instead
    of reading it as off."""
    with pytest.raises(
        FieldError, match=rf"{re.escape(field)}: '.*' is not 1 or 0 \(at "
    ) as raised:
        _read_af(tmp_path, token)
    assert raised.value.reason is Reason.FLAG


@pytest.mark.parametrize(
    ("token", "field"),
    [
        ("copy(DS1,DS2,oneshot=)", "Copy.oneshot"),
        ("blockcopy(DS1..DS2,DS11..DS12,oneshot= )", "BlockCopy.oneshot"),
        ("pack_text(TXT1..TXT4,DS1,allow_whitespace=)", "Pack.allow_whitespace"),
    ],
)
def test_a_blank_flag_is_missing(tmp_path: Path, token: str, field: str) -> None:
    with pytest.raises(FieldError, match=f"{re.escape(field)}: is blank; it needs a value, 1 or 0"):
        _read_af(tmp_path, token)
    with pytest.raises(FieldError) as raised:
        _read_af(tmp_path, token)
    assert (raised.value.field, raised.value.reason) == (field, Reason.MISSING)


@pytest.mark.parametrize(
    ("kind", "source"), [("pack_bits", ("C1", "C16")), ("pack_words", ("DS1", "DS2"))]
)
def test_allow_whitespace_is_a_pack_text_option(kind: str, source: tuple) -> None:
    """Pack refuses allow_whitespace for pack_bits and pack_words.

    read_csv refuses the keyword on those calls, and write_csv does not write it for them."""
    [error] = _errors(lambda: Pack(*source, "DD1", kind, allow_whitespace=True))
    assert error.fields == ("Pack.allow_whitespace", "Pack.kind")
    assert error.reason is Reason.CONFLICT
    assert Pack(*source, "DD1", kind).to_csv() == f"{kind}({source[0]}..{source[1]},DD1)"


@pytest.mark.parametrize(
    ("token", "kind", "flags"),
    [
        ("copy(DS1,DS2)", Copy, {"oneshot": False}),
        ("copy(DS1,DS2,oneshot=0)", Copy, {"oneshot": False}),
        ("copy(DS1,DS2,oneshot=1)", Copy, {"oneshot": True}),
        ("fill(1,DS1..DS3,oneshot=1)", Fill, {"oneshot": True}),
        (
            "pack_text(TXT1..TXT4,DS1,allow_whitespace=1,oneshot=0)",
            Pack,
            {"allow_whitespace": True, "oneshot": False},
        ),
        ("unpack_to_bits(DS1,C1..C16,oneshot=1)", Unpack, {"oneshot": True}),
    ],
)
def test_a_flag_reads_as_1_or_0(tmp_path: Path, token: str, kind: type, flags: dict) -> None:
    found = _read_af(tmp_path, token)
    assert isinstance(found, kind)
    assert {name: getattr(found, name) for name in flags} == flags


# The tags of each captured Copy, read alone as a program file stores them, build the same
# Copy as the clipboard decoder.
def test_the_program_file_tags_build_the_clipboard_copy() -> None:
    for case, _csv in CAPTURED:
        blob = _clip_blob((CAPTURES / f"{case}.bin").read_bytes())
        class_name, type_code, _parts, _extra, fields = _decompose_blob(blob)
        [from_clip] = _copies(decode((CAPTURES / f"{case}.bin").read_bytes()))
        assert from_tags_af(class_name, type_code, *_fields_to_tag_dicts(fields)) == from_clip


@pytest.mark.parametrize(
    ("source", "destination", "conv"),
    [
        ('"AB"', "TXT1", "1"),
        ('"AB"', "TXT1", "3"),
        ('"A"', "TXT1", "2"),
        ("$41", "TXT1", "1"),
        ('"AB"', "TXT1", "8"),
        ("DS1", "TXT1", "3"),
        ("5", "TXT1", "3"),
        ("DD[DS1]", "TXT1", "3"),
    ],
)
def test_a_conversion_type_click_never_saves_reads_as_raw(
    source: str, destination: str, conv: str
) -> None:
    """A save with a conversion type that CLICK never writes for its source is not read as
    a Copy.

    CLICK copies text and a character code with no conversion type. It uses real numbering
    (type 3) only for a DF source or a real constant. Both decoders return None for such a
    save, instead of reading it as some other Copy."""
    tags = {0x6074: source, 0x6076: destination, 0x2227: conv}
    assert from_tags_af("Copy", 0x2721, tags) is None
    assert parse_af_blob(_stored(tags)) is None
