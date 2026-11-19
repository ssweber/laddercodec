"""Tests that an instruction from a program file encodes to the blob of CLICK's clipboard.

A program file (``Scr*.tmp``) stores fewer tags than the clipboard. It leaves out each tag
that holds its default, and it stores a set flag with no value. The clipboard stores every
tag of the instruction in a fixed order, and writes a flag as ``-1``, ``1`` or ``0``.

The pairs are the programs in ``tests/fixtures/tumbler`` and ``tests/fixtures/scr_captures``,
and the one-rung saves in ``tests/fixtures/v4_captures/copy_forms``, ``copy_single`` and
``copy_txt``, each saved by CLICK and copied out through its clipboard. The v4 saves are the
pairs whose instructions keep a stored blob. The other files there have no clipboard copy
that CLICK wrote: ``time_drums.bin`` and the pair of ``pins.scr`` are synthetic,
``constants/`` holds only program files, and ``paste01`` and ``paste02`` have no ``.bin``.
"""

from __future__ import annotations

import gzip
import warnings
from pathlib import Path

import pytest

from laddercodec import decode, decode_program, encode
from laddercodec.decode import inspect_cells
from laddercodec.decode_program import (
    _FUNC_CODE_TAG,
    _af_form,
    _clipboard_part_rows,
    _parse_header,
    _scr_af,
    _scr_blob,
    _scr_box,
    _scr_raw,
    _ScrEntry,
    _set_flag,
    _walk_rung_records,
)
from laddercodec.instructions import RawInstruction, Search, from_tags_condition
from laddercodec.instructions.coil import Coil
from laddercodec.instructions.copy import Copy
from laddercodec.instructions.raw import _decompose_blob, find_blob_boundary
from laddercodec.model import Instruction
from laddercodec.operands.unchecked import stored_blob

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_TUMBLER = _FIXTURES / "tumbler"
_SCR_CAPTURES = _FIXTURES / "scr_captures"
_V4 = _FIXTURES / "v4_captures"

_PAIRS = [
    *(
        (scr, scr.with_name(f"{scr.stem}.clipboard.bin"))
        for scr in sorted(_TUMBLER.rglob("*.scr"), key=lambda p: p.name.lower())
    ),
    *(
        (_SCR_CAPTURES / f"{stem}.scr", _SCR_CAPTURES / f"{stem}.bin")
        for stem in (
            "coverage",
            "counter_scr",
            "or_topology",
            "shift_scr",
            "time_drum_b_column",
            "time_drum_insert_rows",
        )
    ),
    (_SCR_CAPTURES / "rungs_266.scr", _SCR_CAPTURES / "rungs_266.bin.gz"),
    *(
        (scr, scr.with_suffix(".bin"))
        for folder in ("copy_forms", "copy_single", "copy_txt")
        for scr in sorted((_V4 / folder).glob("*.scr"))
        if scr.with_suffix(".bin").exists()
    ),
]

#: The tags, by class, in which the encoder's own blob differs from CLICK's clipboard.
#: Decoding the clipboard copy and encoding it writes the same tags, so these are the
#: encoder's form, not the program file's. Remove an entry when the encoder writes CLICK's.
_ENCODER_FORM: dict[str, frozenset[str]] = {
    # The subroutine's index. The encoder writes 0.
    "Call": frozenset({"3219"}),
    # The text flag. The encoder writes 0 where CLICK v4 writes -1.
    "Copy": frozenset({"1201"}),
    # The capture shows nicknames: the formula names them, and the nickname flag is on.
    # CLICK v4 writes more reserved slots (688C) than the encoder.
    "Math": frozenset({"2224", "6228", "688C"}),
    # The clipboard writes an empty entry for each unused index of these arrays. The
    # encoder leaves those entries out.
    "RD": frozenset({"688F"}),
    "SD": frozenset({"6889", "688F"}),
}

#: The tags, by class, in which a blob built from the program file's tags still differs
#: from CLICK's: the arrays that it takes from the encoder's form.
_COMPOSED_FORM: dict[str, frozenset[str]] = {
    "Math": frozenset({"688C"}),
    "RD": _ENCODER_FORM["RD"],
    "SD": _ENCODER_FORM["SD"],
}


def _read(path: Path) -> bytes:
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


def _pair_id(pair: tuple[Path, Path]) -> str:
    return f"{pair[0].parent.name}/{pair[0].stem}"


def _blob(raw_cell: bytes) -> bytes:
    """Return the instruction blob of one clipboard cell."""
    raw = raw_cell[0x25:]
    return raw[: find_blob_boundary(raw)[1]]


def _fields(blob: bytes) -> dict[tuple[int, bytes], str]:
    return {(tag, sentinel): value for tag, sentinel, value in _decompose_blob(blob)[4]}


def _differing_tags(ours: bytes, click: bytes) -> set[str]:
    """Return the tags (hex, without array index) in which two blobs differ."""
    assert _decompose_blob(ours)[:4] == _decompose_blob(click)[:4]
    fields_ours, fields_click = _fields(ours), _fields(click)
    keys = fields_ours.keys() | fields_click.keys()
    return {
        f"{tag:04X}" for tag, s in keys if fields_ours.get((tag, s)) != fields_click.get((tag, s))
    }


def _allowed(allowlist: dict[str, frozenset[str]]) -> set[tuple[str, str]]:
    return {(class_name, tag) for class_name, tags in allowlist.items() for tag in tags}


def _instruction_cells(rungs) -> list[tuple[int, int, str]]:
    cells = []
    for index, rung in enumerate(rungs):
        for row in range(rung.logical_rows):
            for col, cell in enumerate(rung.conditions[row]):
                if not isinstance(cell, str):
                    cells.append((index, row, _column(col)))
            if isinstance(rung.instructions[row], Instruction):
                cells.append((index, row, "AF"))
    return cells


def _column(col: int) -> str:
    return chr(ord("A") + col) if col < 26 else "A" + chr(ord("A") + col - 26)


def _cell_blobs(pair: tuple[Path, Path]):
    """Yield (where, ours, CLICK's, round trip's) blob for each instruction cell of a pair.

    Ours is ``encode(decode_program(scr))``; the round trip's is ``encode(decode(clip))``."""
    scr, clip = pair
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        rungs = decode_program(scr.read_bytes()).rungs
        click = _read(clip)
        round_trip = encode(decode(click))
    cells = _instruction_cells(rungs)
    assert cells
    for mine, theirs, again in zip(
        inspect_cells(encode(rungs), cells),
        inspect_cells(click, cells),
        inspect_cells(round_trip, cells),
        strict=True,
    ):
        where = f"{_pair_id(pair)} rung {mine.rung} row {mine.row} {mine.col}"
        yield where, _blob(mine.raw), _blob(theirs.raw), _blob(again.raw)


@pytest.mark.parametrize("pair", _PAIRS, ids=_pair_id)
def test_each_cell_from_a_program_file_encodes_to_the_clipboard_blob(
    pair: tuple[Path, Path],
) -> None:
    """``encode(decode_program(scr))`` writes CLICK's clipboard blob in every instruction cell.

    A cell may differ only in the tags of ``_ENCODER_FORM``, and only where the clipboard
    copy, decoded and encoded, writes the same blob."""
    for where, ours, click, again in _cell_blobs(pair):
        if ours == click:
            continue
        class_name = _decompose_blob(click)[0]
        assert _differing_tags(ours, click) <= _ENCODER_FORM.get(class_name, set()), where
        assert again == ours, where


def test_every_encoder_form_entry_is_needed() -> None:
    """Each tag in ``_ENCODER_FORM`` still differs from CLICK in some cell of the pairs."""
    seen: set[tuple[str, str]] = set()
    for pair in _PAIRS:
        for _where, ours, click, _again in _cell_blobs(pair):
            if ours != click:
                class_name = _decompose_blob(click)[0]
                seen |= {(class_name, tag) for tag in _differing_tags(ours, click)}
    assert seen == _allowed(_ENCODER_FORM)


def test_the_pairs_hold_a_kept_blob() -> None:
    """The pairs hold an instruction that keeps a stored blob, from the program file."""
    kept = 0
    for scr, _clip in _PAIRS:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            rungs = decode_program(scr.read_bytes()).rungs
        kept += sum(
            stored_blob(t) is not None
            for rung in rungs
            for t in [*rung.instructions, *(c for row in rung.conditions for c in row)]
            if not isinstance(t, str)
        )
    assert kept > 0


def _entries():
    """Yield (where, column, entry, clipboard blob) for every entry of the pairs."""
    for scr, clip in _PAIRS:
        data = scr.read_bytes()
        records = _walk_rung_records(data, _parse_header(data))
        click = _read(clip)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            rungs = decode_program(data).rungs
        cells = _instruction_cells(rungs)
        dumps = {(d.rung, d.row, d.col): d for d in inspect_cells(click, cells)}
        for index, record in enumerate(records[: len(rungs)]):
            for row, col, *fields in record.instructions:
                dump = dumps.get((index, row, _column(col) if col < 31 else "AF"))
                if dump is not None:
                    where = f"{_pair_id((scr, clip))} rung {index} row {row} col {col}"
                    yield where, col, _ScrEntry(*fields[:6]), _blob(dump.raw)


def _form(col: int, entry: _ScrEntry):
    arrays = (entry.variant_u16_tags, entry.variant_string_tags)
    if col == 31:
        return _scr_af(
            entry.class_name, entry.type_code, entry.tags, entry.part_rows, *arrays
        ) or _af_form(entry)
    return from_tags_condition(entry.class_name, entry.type_code, entry.tags, *arrays)


def test_a_composed_blob_is_the_clipboard_blob() -> None:
    """Every entry of the pairs, built with its typed instruction as the form, writes the
    blob of CLICK's clipboard.

    This applies the composition to every entry that has a typed form, not only to those
    that keep a stored blob. The blob differs only in the tags of ``_COMPOSED_FORM``."""
    seen: set[tuple[str, str]] = set()
    count = 0
    for where, col, entry, click in _entries():
        form = _form(col, entry)
        assert form is not None, where
        composed = _scr_blob(entry, form)
        count += 1
        if composed == click:
            continue
        differ = _differing_tags(composed, click)
        assert differ <= _COMPOSED_FORM.get(entry.class_name, set()), f"{where} {differ}"
        seen |= {(entry.class_name, tag) for tag in differ}
    assert count > 1500
    # A tag that no entry needs any more must be removed.
    assert seen == _allowed(_COMPOSED_FORM)


def test_each_class_writes_a_set_flag_as_the_clipboard_does() -> None:
    """In every clipboard blob of the pairs, a set flag is ``_set_flag`` of its class."""
    seen: set[tuple[str, str]] = set()
    for _where, _col, _entry, click in _entries():
        class_name, _type, _parts, _extra, fields = _decompose_blob(click)
        for tag, _sentinel, value in fields:
            if tag >> 8 in (0x11, 0x12) and value != "0":
                assert value == _set_flag(class_name), (class_name, hex(tag))
                seen.add((class_name, value))
    assert {value for _class, value in seen} == {"-1", "1"}


def test_a_flag_that_the_form_leaves_clear_is_written_as_its_class_writes_it() -> None:
    """A stored flag that no field reads is written set: ``-1`` in a Copy, ``1`` in an SD.

    CLICK's clipboard writes a Copy's 1201 as ``-1``. No capture shows an SD's 1220 set, so
    ``1`` there is laddercodec's choice: the value of the SD's other set flags."""
    found = {}
    for _where, col, entry, _click in _entries():
        if col == 31 and entry.class_name in ("Copy", "SD") and entry.class_name not in found:
            found[entry.class_name] = entry
    for class_name, tag, value in (("Copy", 0x1201, "-1"), ("SD", 0x1220, "1")):
        entry = found[class_name]
        assert tag not in entry.tags
        form = _form(31, entry)
        flagged = _ScrEntry(
            entry.class_name,
            entry.type_code,
            {**entry.tags, tag: ""},
            entry.part_rows,
            entry.variant_u16_tags,
            entry.variant_string_tags,
        )
        assert _fields(_scr_blob(entry, form))[(tag, b"\xff\xff\xff\xff")] == "0"
        assert _fields(_scr_blob(flagged, form))[(tag, b"\xff\xff\xff\xff")] == value


def test_a_stored_func_code_is_kept() -> None:
    """A program file stores the func code when it is not the class's default. A raw Out
    keeps the stored one, though its form writes another."""
    form = Coil("C1", kind="latch")
    class_name, type_code, _parts, _extra, fields = _decompose_blob(form.build_blob())
    assert dict((tag, value) for tag, _s, value in fields)[0x3218] == "8195"
    entry = _ScrEntry(class_name, type_code, {0x6066: "C1", 0x3218: "8199"}, b"\x01", {}, {})
    raw = _scr_raw(entry, b"\x01\x01", form)
    assert {tag: value for tag, _s, value in _decompose_blob(raw.blob)[4]}[0x3218] == "8199"


def test_pin_rows_that_the_checks_refuse_keep_the_form() -> None:
    """A Timer whose reset sits on its own row (part rows 01 01) has pin rows that the checks
    refuse, so it stays raw. Its blob is still the clipboard form, with the entry's part
    rows."""
    data = (_SCR_CAPTURES / "coverage.scr").read_bytes()
    [entry] = [
        _ScrEntry(*fields[:6])
        for record in _walk_rung_records(data, _parse_header(data))
        for _row, col, *fields in record.instructions
        if col == 31 and fields[0] == "Tmr" and len(fields[3]) == 2
    ][:1]
    refused = _ScrEntry(
        entry.class_name,
        entry.type_code,
        entry.tags,
        b"\x01\x01",
        entry.variant_u16_tags,
        entry.variant_string_tags,
    )
    arrays = (refused.variant_u16_tags, refused.variant_string_tags)
    assert (
        _scr_af(refused.class_name, refused.type_code, refused.tags, b"\x01\x01", *arrays) is None
    )
    form = _af_form(refused)
    assert form is not None
    blob = _scr_blob(refused, form)
    assert _decompose_blob(blob)[3] == _clipboard_part_rows(b"\x01\x01")
    assert _decompose_blob(blob)[4] == _decompose_blob(_scr_blob(entry, _form(31, entry)))[4]


# ---------------------------------------------------------------------------
# By value: a Copy and a Search of "A"B", as CLICK saves them and as it copies them
# ---------------------------------------------------------------------------

#: CLICK's clipboard blob of ``Copy('"A"B"', TXT1)``: 13 tags, with 1201 = -1.
_COPY_CLIP = bytes.fromhex(
    "43006f007000790000002127000001000d0000007460ffffffff22004100220042002200000075"
    "60ffffffff00007660ffffffff540058005400310000007760ffffffff5400580054003300000006"
    "22ffffffff30000000f811ffffffff300000002322ffffffff300000001832ffffffff3800390036"
    "00300000002722ffffffff300000002112ffffffff300000001632ffffffff300000000112ffffff"
    "ff2d00310000000000ffffffff0000"
)

#: CLICK's clipboard blob of ``Search TXT1..TXT10 == "A"B"`` with result DS30 and found
#: bit C101: 10 tags.
_SEARCH_CLIP = bytes.fromhex(
    "53006500610072006300680000002227000001000a0000006560ffffffff2200410022004200220000"
    "006660ffffffff540058005400310000006760ffffffff5400580054003100300000007960ffffffff"
    "440053003300300000007a60ffffffff430031003000310000007712ffffffff300000001832ffffff"
    "ff38003900360034000000f811ffffffff30000000f721ffffffff300000000000ffffffff0000"
)


def _box(class_name: str, type_code: int, tags: dict[int, str], cell_rows: bytes):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return _scr_box(class_name, type_code, tags, b"\x01", {}, {}, cell_rows)


def test_a_saved_copy_of_quoted_text_writes_clicks_clipboard_blob() -> None:
    """The program file stores 5 tags of the Copy, with 1201 as a flag with no value. The
    Copy writes the 13 tags of CLICK's clipboard, with 1201 as -1."""
    tags = {0x6074: '"A"B"', 0x6076: "TXT1", 0x6077: "TXT3", 0x1201: "", 0x0000: ""}
    box = _box("Copy", 0x2721, tags, b"\x02\x02")
    blob = box.blob if isinstance(box, RawInstruction) else box.build_blob()
    assert blob == _COPY_CLIP


def test_a_saved_search_of_quoted_text_writes_clicks_clipboard_blob() -> None:
    """The program file stores 6 tags of the Search. The Search writes the 10 tags of
    CLICK's clipboard."""
    tags = {
        0x6065: '"A"B"',
        0x6066: "TXT1",
        0x6067: "TXT10",
        0x6079: "DS30",
        0x607A: "C101",
        0x0000: "",
    }
    box = _box("Search", 0x2722, tags, b"\x02\x03")
    assert isinstance(box, (RawInstruction, Search))
    blob = box.blob if isinstance(box, RawInstruction) else box.build_blob()
    assert blob == _SEARCH_CLIP


def test_a_kept_blob_writes_a_stored_flag_as_the_clipboard_does() -> None:
    """A Copy that CLICK saved with a destination as typed keeps a blob. Its oneshot flag,
    which the program file stores with no value, is written -1."""
    tags = {0x6074: "DS1", 0x6076: "ds2", 0x11F8: "", 0x0000: ""}
    box = _box("Copy", 0x2721, tags, bytes([2, 0]))
    blob = stored_blob(box)
    assert blob is not None
    fields = {tag: value for tag, _sentinel, value in _decompose_blob(blob)[4]}
    assert fields[0x6076] == "ds2"
    assert fields[0x11F8] == "-1"
    # A Copy's func code holds the one-shot too, and it agrees with the flag.
    assert fields[0x3218] == "8961"
    assert "" not in {fields[tag] for tag in fields if tag >> 8 in (0x11, 0x12)}


_STANDARD = b"\xff\xff\xff\xff"


def test_a_one_shot_copy_writes_the_func_code_of_a_one_shot() -> None:
    """A program file stores a one-shot Copy with 11F8 and no func code. CLICK's clipboard
    writes 11F8 as -1 and the func code of a one-shot, such as 8961 where a plain Copy of
    DS into DS has 8960. Each raw box writes CLICK's blob, a single Copy that keeps its
    blob writes CLICK's pair, and the same entry without 11F8 writes another func code."""
    one_shots = [
        (entry, click)
        for _where, col, entry, click in _entries()
        if col == 31 and entry.class_name == "Copy" and 0x11F8 in entry.tags
    ]
    assert one_shots
    codes = {"plain": Copy("DS26", "DS27"), "one-shot": Copy("DS26", "DS27", oneshot=True)}
    assert {k: _fields(v.build_blob())[(0x3218, _STANDARD)] for k, v in codes.items()} == {
        "plain": "8960",
        "one-shot": "8961",
    }
    seen = set()
    for entry, click in one_shots:
        assert _FUNC_CODE_TAG not in entry.tags
        clip = _fields(click)
        pair = (clip[(0x3218, _STANDARD)], clip[(0x11F8, _STANDARD)])
        assert pair[1] == "-1"
        seen.add(pair[0])
        raw = _scr_raw(entry, bytes([2, 0]), _af_form(entry))
        assert raw.blob == click
        if 0x2223 not in entry.tags:
            # A single Copy whose destination CLICK saved as typed keeps its blob.
            typed = {**entry.tags, 0x6076: entry.tags[0x6076].lower()}
            blob = stored_blob(_box("Copy", entry.type_code, typed, bytes([2, 0])))
            assert blob is not None
            kept = _fields(blob)
            assert (kept[(0x3218, _STANDARD)], kept[(0x11F8, _STANDARD)]) == pair
        tags = {tag: value for tag, value in entry.tags.items() if tag != 0x11F8}
        plain = _fields(_box("Copy", entry.type_code, tags, bytes([2, 0])).build_blob())
        assert plain[(0x3218, _STANDARD)] != pair[0]
    assert "8961" in seen


# ---------------------------------------------------------------------------
# An entry with no form: the stored tags, with each stored flag written 0 or set
# ---------------------------------------------------------------------------

#: The tags of an SD that CLICK saved with the sending address ``C100<tab>``. No family
#: reads that address, so the entry has no form. CLICK's clipboard copy of it writes the
#: four stored flags as 1.
_SD_NO_FORM = {
    0x120A: "",
    0x607C: "C100\t",
    0x1209: "",
    0x607B: "C101",
    0x120B: "",
    0x607D: "C102",
    0x121A: "",
    0x6083: "DS100",
    0x320E: "1",
    0x60B2: "1",
    0x2211: "1",
    0x6085: "400001",
    0x607E: "DS1",
    0x0000: "",
}


def test_an_entry_with_no_form_writes_a_stored_flag_as_its_class_sets_it() -> None:
    """The SD keeps its stored tags and writes each stored flag as CLICK's clipboard does."""
    box = _box("SD", 0x2729, _SD_NO_FORM, bytes([3, 3]))
    assert isinstance(box, RawInstruction)
    fields = _fields(box.blob)
    assert [tag for tag, _sentinel in fields] == list(_SD_NO_FORM)
    assert {f"{tag:04X}": fields[(tag, _STANDARD)] for tag in (0x120A, 0x1209, 0x120B, 0x121A)} == {
        "120A": "1",
        "1209": "1",
        "120B": "1",
        "121A": "1",
    }


def test_a_class_that_laddercodec_does_not_read_writes_a_stored_flag_as_set() -> None:
    """A stored flag of an unknown class is written 1, and of a Copy-like class -1. An RD
    flag that is set by default reads as clear when stored, and is written 0.

    No capture shows an RD's 1220 set, so ``1`` there is laddercodec's choice: the value of
    the RD's other set flags."""
    tags = {0x6065: "DS1", 0x1201: "", 0x2211: "1", 0x0000: ""}
    unknown = _box("NotAClass", 0x27FF, tags, b"\x01\x01")
    assert isinstance(unknown, RawInstruction)
    assert _fields(unknown.blob) == {
        (0x6065, _STANDARD): "DS1",
        (0x1201, _STANDARD): "1",
        (0x2211, _STANDARD): "1",
        (0x0000, _STANDARD): "",
    }
    copy = _scr_raw(_ScrEntry("Copy", 0x27FF, tags, b"\x01", {}, {}), b"\x01\x01")
    assert _fields(copy.blob)[(0x1201, _STANDARD)] == "-1"
    rd_tags = {0x1209: "", 0x1220: "", 0x0000: ""}
    rd = _scr_raw(_ScrEntry("RD", 0x27FF, rd_tags, b"\x01", {}, {}), b"\x01\x01")
    assert _fields(rd.blob)[(0x1209, _STANDARD)] == "0"
    assert _fields(rd.blob)[(0x1220, _STANDARD)] == "1"
