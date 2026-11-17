"""CLICK saves some addresses as typed; decode reads them in display form.

CLICK's answers (``tests/fixtures/editor_grids/*.answers.json``) show which fields: a single
Copy's, a Block Copy's and a Pack's destination, each address of a Math formula, and a hex
Math's result keep the text typed (``DS001``, ``ds1``, ``YD0U``, ``DS[ds1]``).  A Copy or
Block Copy source, an Unpack source, a decimal Math result and an Out address are saved in
display form.  Each answered save decodes as the instruction, with its CSV in display form;
unchanged, it writes the saved bytes back, and changed, it is built in display form.  A typed
form the rules refuse once it is in display form decodes holding the refusal, and a form no
save shows stays raw.  A box ``decode_program`` reads keeps the blob composed from the program
file, a set flag held as an empty field, and reads back from the clipboard as itself.
"""

from __future__ import annotations

import json
import sys
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from laddercodec import (
    RawInstruction,
    RefusedFieldWarning,
    Rung,
    decode,
    decode_program,
    encode,
    read_csv,
)
from laddercodec.csv import CSV_HEADER
from laddercodec.decode_program import _scr_box
from laddercodec.encode import encode_rung
from laddercodec.instructions import parse_af_blob
from laddercodec.instructions.copy import BlockCopy, Copy, Fill, Pack, Unpack
from laddercodec.instructions.forloop import ForLoop
from laddercodec.instructions.math import Math
from laddercodec.instructions.raw import _compose_blob, _decompose_blob, _fields_to_tag_dicts
from laddercodec.model import AfInstruction, display_form_only
from laddercodec.operands.address import read_as_typed
from laddercodec.operands.unchecked import refusals, stored_blob
from tests.kept_refusals import kept

FIXTURES = Path(__file__).parent / "fixtures"
GRIDS = FIXTURES / "editor_grids"

#: Every save CLICK's answers hold with an address typed: (grid, case, instruction, CSV).
ANSWERED: list[tuple[str, str, AfInstruction, str]] = [
    ("copy_single", "single DS2 -> DS001", Copy("DS2", "DS1"), "copy(DS2,DS1)"),
    ("copy_single", "single DS2 -> DS01", Copy("DS2", "DS1"), "copy(DS2,DS1)"),
    ("copy_single", "single DS2 -> ds1", Copy("DS2", "DS1"), "copy(DS2,DS1)"),
    ("copy_single", "single DS2 -> DS[DS001]", Copy("DS2", "DS[DS1]"), "copy(DS2,DS[DS1])"),
    ("copy_single", "single DS2 -> DS[ds1]", Copy("DS2", "DS[DS1]"), "copy(DS2,DS[DS1])"),
    ("copy_single", "single DS2 -> YD00", Copy("DS2", "YD0"), "copy(DS2,YD0)"),
    ("copy_single", "single DS2 -> YD0U", Copy("DS2", "YD0u"), "copy(DS2,YD0u)"),
    (
        "copy_block",
        "block DS1..DS2 -> DS001",
        BlockCopy("DS1", "DS2", "DS1", "DS2"),
        "blockcopy(DS1..DS2,DS1..DS2)",
    ),
    (
        "copy_block",
        "block DS1..DS2 -> ds1",
        BlockCopy("DS1", "DS2", "DS1", "DS2"),
        "blockcopy(DS1..DS2,DS1..DS2)",
    ),
    (
        "copy_pack",
        "pack C1..C16 -> DS001",
        Pack("C1", "C16", "DS1", "bits"),
        "pack_bits(C1..C16,DS1)",
    ),
    (
        "copy_pack",
        "pack C1..C16 -> ds1",
        Pack("C1", "C16", "DS1", "bits"),
        "pack_bits(C1..C16,DS1)",
    ),
    *[
        (
            "math_decimal",
            f"dec DS1 = {typed} + 1",
            Math("DS1 + 1", "DS1"),
            "math(DS1 + 1,DS1,mode=decimal)",
        )
        for typed in ("DS001", "DS01", "ds1")
    ],
    *[
        (
            "math_hex",
            f"hex DH1 = {typed}{tail}",
            Math(f"{display}{tail}", "DH1", "hex"),
            f"math({display}{tail},DH1,mode=hex)",
        )
        for typed, display in (("XD00", "XD0"), ("XD0U", "XD0u"), ("YD00", "YD0"), ("YD0U", "YD0u"))
        for tail in ("", " + 1h")
    ],
    (
        "math_hex",
        "hex DH1 = xd0U + 1h",
        Math("XD0u + 1h", "DH1", "hex"),
        "math(XD0u + 1h,DH1,mode=hex)",
    ),
    (
        "math_hex",
        "hex YD00 = DH2 + DH3",
        Math("DH2 + DH3", "YD0", "hex"),
        "math(DH2 + DH3,YD0,mode=hex)",
    ),
    (
        "math_hex",
        "hex YD0U = DH2 + DH3",
        Math("DH2 + DH3", "YD0u", "hex"),
        "math(DH2 + DH3,YD0u,mode=hex)",
    ),
]


def _case(grid: str, label: str) -> dict[str, Any]:
    answers = json.loads((GRIDS / f"{grid}.answers.json").read_text(encoding="utf-8"))
    [found] = [c for c in answers["cases"] if c["case"] == label]
    return found


def _saved_rung(tmp_path: Path, case: dict[str, Any]) -> Rung:
    """The rung CLICK saved for a case, as its ``stored`` rows record it."""
    path = tmp_path / "stored.csv"
    path.write_text("\n".join([",".join(CSV_HEADER), *case["stored"]]) + "\n", "utf-8")
    [rung] = read_csv(path)
    return rung


def _raw_box(rung: Rung) -> RawInstruction:
    [raw] = [t for t in rung.instructions if isinstance(t, RawInstruction)]
    return raw


def _program_box(raw: RawInstruction) -> AfInstruction:
    """The box ``decode_program`` reads from the program file entry ``raw`` was written from.

    The raw box holds the blob composed from the entry's tags, a flag that is set as an
    empty value; read from those tags, it is read as ``decode_program`` reads the entry.
    """
    class_name, type_code, parts, _extra, fields = _decompose_blob(raw.blob)
    assert parts == 1
    tags = {tag: value for tag, _sentinel, value in fields}
    rows = bytes([raw.visual_rows or 0, raw.sub_rows or 0])
    return _scr_box(class_name, type_code, tags, b"\x01", {}, {}, rows)


@pytest.mark.parametrize(("grid", "label", "inst", "csv_text"), ANSWERED)
def test_each_answered_save_reads_in_display_form(
    tmp_path: Path, grid: str, label: str, inst: AfInstruction, csv_text: str
) -> None:
    case = _case(grid, label)
    assert case["outcome"] == "accepted"
    rung = _saved_rung(tmp_path, case)
    raw = _raw_box(rung)
    box = _program_box(raw)
    assert box == inst
    assert box.to_csv() == csv_text
    assert not refusals(box)
    # Unchanged, it writes the bytes CLICK saved, and the cell rows.
    assert box.build_blob() == raw.blob
    instructions = [box if t is raw else t for t in rung.instructions]
    data = encode(replace(rung, instructions=instructions))
    assert data == encode(rung)
    # Read back from the clipboard, it is the same instruction: a hex Math stays hex.
    decoded = decode(data)
    assert isinstance(decoded, Rung)
    [back] = [t for t in decoded.instructions if isinstance(t, type(inst))]
    assert back == inst and not refusals(back)
    assert encode(decoded) == data
    # Changed, it is built in display form.
    box.oneshot = True
    assert box.build_blob() == replace(inst, oneshot=True).build_blob()


def test_the_answered_saves_are_every_typed_save(tmp_path: Path) -> None:
    """Of the Copy and Math saves the answers hold as ``raw(...)``, those that read as the
    instruction now are the answered typed addresses."""
    read: set[tuple[str, str]] = set()
    for grid in ("copy_single", "copy_block", "copy_pack", "math_decimal", "math_hex"):
        answers = json.loads((GRIDS / f"{grid}.answers.json").read_text(encoding="utf-8"))
        for case in answers["cases"]:
            if not any("raw(" in row for row in case.get("stored") or []):
                continue
            raw = _raw_box(_saved_rung(tmp_path, case))
            if not isinstance(_program_box(raw), RawInstruction):
                read.add((grid, case["case"]))
    assert read == {(grid, label) for grid, label, _inst, _csv in ANSWERED}


def _retagged(blob: bytes, edits: dict[int, tuple[str, str]]) -> bytes:
    """``blob`` with ``old`` written as ``new`` in each edited tag's value."""
    class_name, type_code, parts, extra, fields = _decompose_blob(blob)
    edited = []
    for tag, sentinel, value in fields:
        if tag in edits:
            old, new = edits[tag]
            assert old in value
            value = value.replace(old, new)
        edited.append((tag, sentinel, value))
    return _compose_blob(class_name, type_code, parts, extra, edited)


def _from_program(blob: bytes, rows: int) -> AfInstruction:
    """The box ``decode_program`` reads from a program file entry of ``blob``'s fields.

    A program file holds a set flag as an empty value and leaves an unset one out.
    """
    class_name, type_code, parts, _extra, fields = _decompose_blob(blob)
    assert parts == 1
    tags, variant_u16, variant_string = _fields_to_tag_dicts(fields)
    return _scr_box(
        class_name, type_code, tags, b"\x01", variant_u16, variant_string, bytes([rows, 0])
    )


#: Boxes ``decode_program`` reads holding the blob composed from the program file, each with
#: a flag set: (instruction, tag edits that make the stored text differ, the flags set).
FLAGGED: list[tuple[str, AfInstruction, dict[int, tuple[str, str]], tuple[int, ...]]] = [
    ("copy oneshot, typed", Copy("DS2", "DS1", oneshot=True), {0x6076: ("DS1", "ds1")}, (0x11F8,)),
    (
        "copy oneshot, edge space",
        Copy("DS2", "DS1", oneshot=True),
        {0x6076: ("DS1", "DS1 ")},
        (0x11F8,),
    ),
    (
        "copy termination code",
        Copy("DS20", "TXT7", format="text", termination_code="$13"),
        {0x6076: ("TXT7", "TXT7 ")},
        (0x1201, 0x1221),
    ),
    (
        "math oneshot",
        Math("DS1 + 1", "DS4", oneshot=True),
        {0x6228: ("DS1", "ds1"), 0x61FD: ("DS1", "ds1")},
        (0x11F8,),
    ),
    (
        "hex math oneshot",
        Math("DH2 + DH3", "YD0u", "hex", oneshot=True),
        {0x6065: ("YD0u", "YD0U")},
        (0x11FE, 0x11F8),
    ),
]


@pytest.mark.parametrize(
    ("inst", "edits", "flags"),
    [pytest.param(*case[1:], id=case[0]) for case in FLAGGED],
)
def test_a_program_box_reads_back_from_the_clipboard(
    inst: AfInstruction, edits: dict[int, tuple[str, str]], flags: tuple[int, ...]
) -> None:
    """The blob composed from a program file writes a set flag as an empty value; the
    clipboard decoder reads it as set, so the box reads back as itself."""
    blob = inst.build_blob()
    fields = {tag: value for tag, _sentinel, value in _decompose_blob(blob)[4]}
    assert all(fields[flag] == "-1" for flag in flags)
    box = _from_program(_retagged(blob, edits), int(inst.cell_params().get("visual_rows", 1)))
    assert box == inst and not refusals(box)
    composed = {tag: value for tag, _sentinel, value in _decompose_blob(box.build_blob())[4]}
    assert all(composed[flag] == "" for flag in flags)
    data = _one_box_of(box)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RefusedFieldWarning)
        decoded = decode(data)
    assert isinstance(decoded, Rung)
    [back] = [t for t in decoded.instructions if isinstance(t, AfInstruction)]
    assert back == inst and not refusals(back)
    assert encode(decoded) == data


def test_a_program_box_holding_a_refusal_reads_back_from_the_clipboard() -> None:
    """A box of another family that holds a refusal keeps its set flag through the clipboard."""
    blob = _retagged(ForLoop(limit="3", oneshot=True).build_blob(), {0x6065: ("3", "Y001")})
    box = _from_program(blob, 1)
    assert isinstance(box, ForLoop) and box.oneshot
    kept(box, "ForLoop.limit")
    data = _one_box_of(box)
    with pytest.warns(RefusedFieldWarning):
        decoded = decode(data)
    assert isinstance(decoded, Rung)
    [back] = [t for t in decoded.instructions if isinstance(t, AfInstruction)]
    assert isinstance(back, ForLoop) and back.oneshot and back.limit == "Y001"
    kept(back, "ForLoop.limit")
    assert encode(decoded) == data


def _one_box_of(box: AfInstruction) -> bytes:
    """A one-rung clipboard holding ``box``."""
    return encode_rung(1, [["-"] * 31], [box])


def _one_box(blob: bytes) -> bytes:
    """A one-rung clipboard holding a raw box of ``blob``."""
    raw = RawInstruction(_decompose_blob(blob)[0], blob)
    return encode_rung(1, [["-"] * 31], [raw])


#: Clipboard blobs with an address typed as CLICK saves it: (instruction, tag edits).
TYPED_BLOBS: list[tuple[AfInstruction, dict[int, tuple[str, str]]]] = [
    (Copy("DS2", "DS1"), {0x6076: ("DS1", "DS001")}),
    (Copy("DS2", "DS1"), {0x6076: ("DS1", "ds1")}),
    (Copy("DS2", "DS[DS1]"), {0x6076: ("DS[DS1]", "DS[ds1]")}),
    (Copy("DS2", "YD0"), {0x6076: ("YD0", "YD00")}),
    (Copy("DS2", "YD0u"), {0x6076: ("YD0u", "YD0U")}),
    (BlockCopy("DS1", "DS2", "DS11", "DS12"), {0x6076: ("DS11", "ds11")}),
    (Pack("C1", "C16", "DS1", "bits"), {0x6076: ("DS1", "DS001")}),
    (Math("DS1 + 1", "DS4"), {0x6228: ("DS1", "ds1"), 0x61FD: ("DS1", "ds1")}),
    (Math("XD0 + 1h", "DH1", "hex"), {0x6228: ("XD0", "XD00"), 0x61FD: ("XD0", "XD00")}),
    (Math("DH2 + DH3", "YD0u", "hex"), {0x6065: ("YD0u", "YD0U")}),
]


@pytest.mark.parametrize(("inst", "edits"), TYPED_BLOBS)
def test_a_typed_clipboard_blob_reads_in_display_form(
    inst: AfInstruction, edits: dict[int, tuple[str, str]]
) -> None:
    blob = _retagged(inst.build_blob(), edits)
    parsed = parse_af_blob(blob)
    assert parsed == inst and parsed is not None
    assert parsed.to_csv() == inst.to_csv()
    assert not refusals(parsed)
    assert parsed.build_blob() == blob != inst.build_blob()
    data = _one_box(blob)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RefusedFieldWarning)
        decoded = decode(data)
    assert isinstance(decoded, Rung)
    [box] = decoded.instructions
    assert box == inst
    assert encode(decoded) == data
    parsed.oneshot = True
    assert stored_blob(parsed) is None
    assert parsed.build_blob() == replace(inst, oneshot=True).build_blob()


@pytest.mark.parametrize(
    ("inst", "edits", "field", "display"),
    [
        (Copy("DS2", "DS1"), {0x6076: ("DS1", "DS04501")}, "Copy.destination", "DS4501"),
        (Math("DH2 + DH3", "YD0", "hex"), {0x6065: ("YD0", "YD09")}, "Math.result", "YD9"),
        (
            Math("DS1 + 1", "DS4"),
            {0x6228: ("DS1", "DS04501"), 0x61FD: ("DS1", "DS04501")},
            "Math.expression",
            "DS4501 + 1",
        ),
    ],
)
def test_a_typed_form_refused_in_display_form_keeps_the_refusal(
    inst: AfInstruction, edits: dict[int, tuple[str, str]], field: str, display: str
) -> None:
    data = _one_box(_retagged(inst.build_blob(), edits))
    with pytest.warns(RefusedFieldWarning):
        decoded = decode(data)
    assert isinstance(decoded, Rung)
    [box] = decoded.instructions
    kept(box, field)
    assert display in box.to_csv()
    assert encode(decoded) == data


@pytest.mark.parametrize(
    ("inst", "edits"),
    [
        # A source is saved in display form.
        (Copy("DS2", "DS1"), {0x6074: ("DS2", "ds2")}),
        (BlockCopy("DS1", "DS2", "DS11", "DS12"), {0x6074: ("DS1", "DS001")}),
        (Unpack("DS1", "C1", "C16", "bits"), {0x6074: ("DS1", "ds1")}),
        # CLICK works out a Block Copy's destination end.
        (BlockCopy("DS1", "DS2", "DS11", "DS12"), {0x6077: ("DS12", "ds12")}),
        # No save shows a typed Unpack or Fill destination, or an X or Y number made short.
        (Unpack("DS1", "C1", "C16", "bits"), {0x6076: ("C1", "c1")}),
        (Fill("5", "DS1", "DS2"), {0x6076: ("DS1", "ds1")}),
        (Copy("C1", "Y001"), {0x6076: ("Y001", "Y1")}),
        # A decimal Math's result is saved in display form.
        (Math("DS1 + 1", "DS4"), {0x6065: ("DS4", "ds4")}),
    ],
)
def test_a_form_no_save_shows_stays_raw(
    inst: AfInstruction, edits: dict[int, tuple[str, str]]
) -> None:
    assert parse_af_blob(inst.build_blob()) == inst
    assert parse_af_blob(_retagged(inst.build_blob(), edits)) is None


def _as_list(decoded: Rung | list[Rung]) -> list[Rung]:
    return decoded if isinstance(decoded, list) else [decoded]


def _clip_text(text: str) -> bytes:
    return text.encode("utf-16-le") + b"\x00\x00"


def _scr_text(text: str) -> bytes:
    return bytes([len(text) * 2 + 1]) + text.encode("utf-16-le") + b"\x00"


#: Same-length edits of the coverage program and its clipboard capture that type an address
#: as CLICK saves it: ((stored, typed) texts, class, field, the field's value read).
COVERAGE_EDITS = [
    ((("DS10", "ds10"),), Copy, "destination", "DS10"),
    ((("DS32", "ds32"),), BlockCopy, "dest_start", "DS32"),
    ((("DS167", "ds167"),), Pack, "destination", "DS167"),
    (
        (("DS65 + DS66", "ds65 + DS66"), ("DS65#+#DS66", "ds65#+#DS66")),
        Math,
        "expression",
        "DS65 + DS66",
    ),
    ((("DH3", "dh3"),), Math, "result", "DH3"),
]


@pytest.mark.parametrize(("texts", "cls", "field", "display"), COVERAGE_EDITS)
def test_both_decoders_read_a_typed_address(
    monkeypatch: pytest.MonkeyPatch,
    texts: tuple[tuple[str, str], ...],
    cls: type,
    field: str,
    display: str,
) -> None:
    """Each decoder reads the address in display form and, unchanged, writes back what it
    wrote when the box decoded raw: the clipboard the bytes CLICK stored, the program file
    the blob composed from its tags, the text as typed."""
    scr_dir = FIXTURES / "scr_captures"
    clipboard = (scr_dir / "coverage.bin").read_bytes()
    program = (scr_dir / "coverage.scr").read_bytes()
    for old, new in texts:
        assert clipboard.count(_clip_text(old)) == program.count(_scr_text(old)) == 1
        clipboard = clipboard.replace(_clip_text(old), _clip_text(new))
        program = program.replace(_scr_text(old), _scr_text(new))

    def typed(rungs: list[Rung]) -> tuple[int, Any]:
        [found] = [
            (i, t)
            for i, rung in enumerate(rungs)
            for t in rung.instructions
            if type(t) is cls and getattr(t, field) == display
        ]
        return found

    with warnings.catch_warnings():
        warnings.simplefilter("error", RefusedFieldWarning)
        from_clipboard = _as_list(decode(clipboard))
        from_program = decode_program(program).rungs
    index, inst = typed(from_clipboard)
    assert not refusals(inst)
    blob = inst.build_blob()
    assert all(_clip_text(new) in blob for _old, new in texts)
    assert blob in clipboard
    # The clipboard's cells when that one stayed raw.
    decode_mod = sys.modules["laddercodec.decode"]
    parse_af = decode_mod.parse_af_blob
    monkeypatch.setattr(
        decode_mod, "parse_af_blob", lambda raw: None if (af := parse_af(raw)) == inst else af
    )
    as_raw_clipboard = _as_list(decode(clipboard))
    monkeypatch.undo()
    assert encode(from_clipboard) == encode(as_raw_clipboard)

    scr_index, inst_scr = typed(from_program)
    assert inst_scr == inst and not refusals(inst_scr)
    # The program file's boxes when that one stayed raw.
    program_mod = sys.modules["laddercodec.decode_program"]
    scr_af = program_mod._scr_af
    monkeypatch.setattr(
        program_mod,
        "_scr_af",
        lambda *args: None if (af := scr_af(*args)) == inst_scr else af,
    )
    as_raw = decode_program(program).rungs
    [raw] = [t for t in as_raw[scr_index].instructions if isinstance(t, RawInstruction)]
    assert inst_scr.build_blob() == raw.blob
    assert encode(from_program[scr_index]) == encode(as_raw[scr_index])


@pytest.mark.parametrize(
    ("typed", "display"),
    [
        ("ds1", "DS1"),
        ("DS001", "DS1"),
        ("DS01", "DS1"),
        ("XD00", "XD0"),
        ("XD0U", "XD0u"),
        ("xd0U", "XD0u"),
        ("YD00", "YD0"),
        ("DS[ds1]", "DS[DS1]"),
        ("DS[DS001]", "DS[DS1]"),
    ],
)
def test_read_as_typed(typed: str, display: str) -> None:
    with display_form_only():
        assert read_as_typed(typed) == display


@pytest.mark.parametrize("text", ["DS1", "Y1", "x1", "X01", "5", "1.5", "FFh", "", " DS1", "H1"])
def test_read_as_typed_leaves_other_text(text: str) -> None:
    with display_form_only():
        assert read_as_typed(text) == text
