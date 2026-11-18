"""Test that a stored instruction that breaks a rule of CLICK's dialog decodes as itself.

Each case edits one coverage golden so that one instruction holds a value that its checks
refuse. The cases cover each instruction family that has checks. The tests show that:

- ``read_csv`` raises the refusal by default.
- ``read_csv(..., unchecked=True)`` and the decoders build the instruction as stored. The
  instruction keeps the refusals, and the reader warns with a ``RefusedFieldWarning``.
- ``write_csv`` writes the instruction as it holds it.
- An instruction that was decoded and not changed encodes as the bytes it was decoded from.
  For an output box from a program file, that is the blob that the decoder composes from the
  file's tags, the same blob that the box holds when it decodes raw.
- ``encode()`` raises the error that building the instruction raises, in three cases:

  - a field changed and is still refused;
  - the instruction was read from CSV;
  - the instruction is a condition from a program file.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import pickle
import struct
import sys
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import laddercodec
import laddercodec._grid
import laddercodec.operands.unchecked as unchecked_mod
from laddercodec import (
    FieldError,
    RawInstruction,
    RefusedFieldWarning,
    Rung,
    decode,
    decode_program,
    encode,
    read_csv,
    write_csv,
)
from laddercodec.csv import CSV_HEADER, CsvLocation
from laddercodec.csv.writer import WriterError
from laddercodec.instructions import from_tags_af, parse_af_blob
from laddercodec.instructions.call import Call
from laddercodec.instructions.coil import Coil
from laddercodec.instructions.comparison import CompareContact
from laddercodec.instructions.contact import Contact
from laddercodec.instructions.copy import BlockCopy, Copy, Fill, Pack, Unpack
from laddercodec.instructions.counter import Counter
from laddercodec.instructions.drum import Drum
from laddercodec.instructions.forloop import ForLoop
from laddercodec.instructions.math import Math
from laddercodec.instructions.out_variant import OutVariant
from laddercodec.instructions.raw import _decompose_blob, _fields_to_tag_dicts
from laddercodec.instructions.search import Search
from laddercodec.instructions.send_receive import Receive, Send
from laddercodec.instructions.shift import Shift
from laddercodec.instructions.timer import Timer
from laddercodec.model import AfInstruction, Reason
from laddercodec.operands.unchecked import rebuilt, refusals, stored_blob
from tests.kept_refusals import kept

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "coverage" / "golden"

#: (golden, text replaced, replacement, class, fields refused).
CASES = [
    ("cond__no", ",C2,", ",DS2,", Contact, ["Contact.operand"]),
    ("cond__eq", "DS1==5", "Y001==5", CompareContact, ["CompareContact.left"]),
    ("out__tag", "out(C23)", "out(X001)", Coil, ["Coil.operand"]),
    ("out__v4", "-,toggle(C1101)", "-,toggle(X001)", OutVariant, ["OutVariant.operand"]),
    ("off_delay__tof", "off_delay(T3,", "off_delay(Y001,", Timer, ["Timer.done"]),
    ("count_down", "count_down(CT3,", "count_down(Y001,", Counter, ["Counter.done"]),
    ("shift__basic", "shift(C99..", "shift(Y001..", Shift, ["Shift.start_bit"]),
    (
        "event_drum__basic",
        "current_step=DS182",
        "current_step=Y001",
        Drum,
        ["Drum.current_step"],
    ),
    ("forloop__basic", "for(3)", "for(Y001)", ForLoop, ["ForLoop.count"]),
    ("call__basic", "coverage_sub", "x" * 25, Call, ["Call.subroutine"]),
    ("copy__tag", "copy(DS7,", "copy(Y001,", Copy, ["Copy.dest"]),
    (
        "blockcopy__block",
        "blockcopy(DS28..",
        "blockcopy(Y001..",
        BlockCopy,
        ["BlockCopy.source_end", "BlockCopy.dest_start"],
    ),
    ("fill__literal", "fill(0,", "fill(Y001,", Fill, ["Fill.value"]),
    (
        "pack_bits",
        "pack_bits(C108..",
        "pack_bits(Y001..",
        Pack,
        ["Pack.source_end", "Pack.dest"],
    ),
    ("pack_text", "(TXT1..TXT4,DS170)", "(TXT1..TXT8,DH1)", Pack, ["Pack.source_end"]),
    ("unpack_to_bits", "(DS172,", "(Y001,", Unpack, ["Unpack.source"]),
    ("search__continuous", "search(DS144..", "search(Y001..", Search, ["Search.table_start"]),
    ("math__decimal", "DS66,DS67", "DS66,C67", Math, ["Math.dest"]),
    ("send__tcp_click_coil", "success=C2", "success=C1", Send, ["Send.success"]),
    ("send__tcp_click_coil", "device_id=1", "device_id=256", Send, ["ModbusTcpTarget.device_id"]),
    ("receive__rtu_click_block", "dest=DS1..DS5", "dest=TD1..TD5", Receive, ["Receive.dest"]),
    (
        "receive__rtu_click_block",
        "device_id=5",
        "device_id=248",
        Receive,
        ["ModbusRtuTarget.device_id"],
    ),
]

_IDS = [f"{case[3].__name__}-{case[4][0]}" for case in CASES]

#: Building a Send's or Receive's blob checks its own fields again, so ``_stored_bytes``
#: cannot encode these edits from CSV. These cases edit the golden's .bin file instead. Each
#: value is (tag, stored text, replacement), and both texts are the same length.
_BYTE_EDITS = {
    (Send, "Send.success"): (0x607B, "C2", "C1"),
    (Receive, "Receive.dest"): (0x607E, "DS1", "TD1"),
}


def _edited(tmp_path: Path, golden: str, old: str, new: str) -> Path:
    text = (GOLDEN / f"{golden}.csv").read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path = tmp_path / f"{golden}.csv"
    path.write_text(text.replace(old, new), encoding="utf-8")
    return path


def _tokens(rung: Rung) -> list[object]:
    return [*(t for row in rung.conditions for t in row), *rung.instructions]


def _held(rungs: list[Rung]) -> tuple[int, object]:
    """Return the rung index and the one instruction in ``rungs`` that keeps refusals.

    Assert that exactly one instruction keeps refusals.
    """
    found = [(i, t) for i, rung in enumerate(rungs) for t in _tokens(rung) if refusals(t)]
    assert len(found) == 1, found
    return found[0]


def _read_unchecked(path: Path) -> tuple[list[Rung], list[RefusedFieldWarning]]:
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        rungs = read_csv(path, unchecked=True)
    return rungs, [w.message for w in record if isinstance(w.message, RefusedFieldWarning)]


@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_read_csv_refuses_it_by_default(tmp_path, golden, old, new, cls, fields) -> None:
    with pytest.raises(FieldError, match=f"^{fields[0]}"):
        read_csv(_edited(tmp_path, golden, old, new))


@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_read_csv_unchecked_reads_it_as_written(tmp_path, golden, old, new, cls, fields) -> None:
    rungs, warned = _read_unchecked(_edited(tmp_path, golden, old, new))
    index, held = _held(rungs)
    assert isinstance(held, cls)
    kept(held, *fields)
    [warning] = warned
    assert warning.instruction is held
    assert warning.errors == refusals(held) and warning.error is refusals(held)[0]
    assert (warning.rung, warning.program) == (index, None)


@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_read_csv_unchecked_locates_each_refusal_as_raised(
    tmp_path, golden, old, new, cls, fields
) -> None:
    """Each refusal that the unchecked read keeps has the CSV location that the default read
    raises it with."""
    path = _edited(tmp_path, golden, old, new)
    with pytest.raises(FieldError) as raised:
        read_csv(path)
    rungs, [warning] = _read_unchecked(path)
    _, held = _held(rungs)

    def where(errors: tuple[FieldError, ...]) -> list[tuple[object, ...]]:
        return [(e.fields, e.reason, CsvLocation.of(e)) for e in errors]

    assert where(refusals(held)) == where(raised.value.errors)
    for refusal in refusals(held):
        location = CsvLocation.of(refusal)
        assert location is not None
        assert location.file == path
        assert None not in (location.line, location.rung_line, location.row, location.column)
    assert str(warning).endswith(f" (at {CsvLocation.of(warning.error)})")


@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_encode_refuses_it(tmp_path, golden, old, new, cls, fields) -> None:
    rungs, _ = _read_unchecked(_edited(tmp_path, golden, old, new))
    _, held = _held(rungs)
    with pytest.raises(FieldError) as caught:
        encode(rungs)
    assert str(caught.value) == str(refusals(held)[0])


def _stored_bytes(tmp_path, monkeypatch, golden, old, new, cls, fields) -> bytes:
    """Return the clipboard bytes of the edited golden, as an older laddercodec, or a paste
    that CLICK kept, would have stored them.

    The cases in ``_BYTE_EDITS`` edit the golden's .bin file. The other cases encode the
    edited CSV with the checks turned off.
    """
    edit = _BYTE_EDITS.get((cls, fields[0]))
    if edit is not None:
        tag, was, now = edit
        head = struct.pack("<H", tag) + b"\xff" * 4
        data = (GOLDEN / f"{golden}.bin").read_bytes()
        stored = head + was.encode("utf-16-le") + b"\x00\x00"
        assert data.count(stored) == 1
        return data.replace(stored, head + now.encode("utf-16-le") + b"\x00\x00")
    rungs, _ = _read_unchecked(_edited(tmp_path, golden, old, new))
    with monkeypatch.context() as patch:
        patch.setattr(laddercodec._grid, "_check_instruction", lambda *_args: None)
        patch.setattr(unchecked_mod, "refusals", lambda _inst: ())
        return encode(rungs)


def _decoded(data: bytes) -> tuple[list[Rung], list[RefusedFieldWarning]]:
    with pytest.warns(RefusedFieldWarning) as record:
        decoded = decode(data)
    rungs = decoded
    return rungs, [w.message for w in record if isinstance(w.message, RefusedFieldWarning)]


@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_stored_bytes_decode_as_the_instruction(
    tmp_path, monkeypatch, golden, old, new, cls, fields
) -> None:
    data = _stored_bytes(tmp_path, monkeypatch, golden, old, new, cls, fields)
    rungs, _ = _read_unchecked(_edited(tmp_path, golden, old, new))
    index, held = _held(rungs)
    decoded, [warning] = _decoded(data)
    found = _held(decoded)
    assert found[0] == index
    if (cls, fields[0]) in _BYTE_EDITS:
        # A CSV does not hold a Modbus function code, and the bytes do. Compare without it.
        assert rebuilt(found[1], function_code=None) == held
    else:
        assert found[1] == held
    kept(_held(decoded)[1], *fields)
    assert (warning.rung, warning.program) == (index, None)


@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_decoded_and_unchanged_it_writes_the_stored_bytes(
    tmp_path, monkeypatch, golden, old, new, cls, fields
) -> None:
    data = _stored_bytes(tmp_path, monkeypatch, golden, old, new, cls, fields)
    rungs, _ = _decoded(data)
    assert encode(rungs) == data
    _, held = _held(rungs)
    assert held.build_blob() in data


def _fixes(held: object, valid: object) -> dict[str, Any]:
    """Return each field of *held* that differs from *valid*, with the value in *valid*."""
    return {
        f.name: getattr(valid, f.name)
        for f in dataclasses.fields(cast("Any", valid))
        if getattr(held, f.name) != getattr(valid, f.name)
    }


def _swap(rungs: list[Rung], old: object, new: object) -> None:
    """Put *new* in place of the instruction *old* in *rungs*."""
    for rung in rungs:
        for row in rung.conditions:
            row[:] = [new if t is old else t for t in row]
        rung.instructions[:] = [new if t is old else t for t in rung.instructions]


@pytest.mark.parametrize("source", ["clipboard", "csv"])
@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_a_field_fixed_by_replace_is_accepted(
    tmp_path, monkeypatch, source, golden, old, new, cls, fields
) -> None:
    """``replace`` checks the instruction again when a field changes.

    Once the refused field is fixed, the copy holds no refusal, and the rungs encode as the
    golden that they were edited from.
    """
    if source == "clipboard":
        rungs, _ = _decoded(_stored_bytes(tmp_path, monkeypatch, golden, old, new, cls, fields))
    else:
        rungs, _ = _read_unchecked(_edited(tmp_path, golden, old, new))
    index, held = _held(rungs)
    golden_bytes = (GOLDEN / f"{golden}.bin").read_bytes()
    [valid] = [t for t in _tokens(decode(golden_bytes)[index]) if type(t) is cls]
    fixed = laddercodec.replace(held, **_fixes(held, valid))
    assert not refusals(fixed)
    assert stored_blob(fixed) is None
    _swap(rungs, held, fixed)
    assert encode(rungs) == golden_bytes


@pytest.mark.parametrize("source", ["clipboard", "csv"])
@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_a_field_fixed_in_lowercase_encodes_as_construction_writes_it(
    tmp_path, monkeypatch, source, golden, old, new, cls, fields
) -> None:
    """A field fixed with an address typed in lowercase encodes the address in display form.

    That is how construction writes it, so the rungs encode as the golden.
    """
    if source == "clipboard":
        rungs, _ = _decoded(_stored_bytes(tmp_path, monkeypatch, golden, old, new, cls, fields))
    else:
        rungs, _ = _read_unchecked(_edited(tmp_path, golden, old, new))
    index, held = _held(rungs)
    golden_bytes = (GOLDEN / f"{golden}.bin").read_bytes()
    [valid] = [t for t in _tokens(decode(golden_bytes)[index]) if type(t) is cls]
    typed = {
        f.name: getattr(valid, f.name).lower()
        for f in dataclasses.fields(cast("Any", valid))
        if getattr(held, f.name) != getattr(valid, f.name)
        and isinstance(getattr(valid, f.name), str)
        and getattr(valid, f.name).lower() != getattr(valid, f.name)
    }
    if not typed:
        pytest.skip("the fix holds no letters")
    fixed = laddercodec.replace(held, **(_fixes(held, valid) | typed))
    assert not refusals(fixed)
    _swap(rungs, held, fixed)
    assert encode(rungs) == golden_bytes


@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_a_copy_of_it_refuses(tmp_path, monkeypatch, golden, old, new, cls, fields) -> None:
    """A copy made with ``replace`` raises the first refusal of the instruction.

    The copy runs its checks. If the copy keeps a Modbus target that holds the refusal, its
    own checks pass, but it has no stored blob, so ``build_blob()`` raises the refusal.
    """
    data = _stored_bytes(tmp_path, monkeypatch, golden, old, new, cls, fields)
    rungs, _ = _decoded(data)
    _, held = _held(rungs)
    with pytest.raises(FieldError) as caught:
        replace(held).build_blob()
    assert str(caught.value) == str(refusals(held)[0])


@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_write_csv_writes_it_as_held(tmp_path, golden, old, new, cls, fields) -> None:
    rungs, _ = _read_unchecked(_edited(tmp_path, golden, old, new))
    _, held = _held(rungs)
    written = tmp_path / "written.csv"
    write_csv(written, rungs)
    again, warned = _read_unchecked(written)
    assert _held(again)[1] == held
    assert len(warned) == 1
    with pytest.raises(FieldError, match=f"^{fields[0]}"):
        read_csv(written)


def test_warning_names_the_rung_and_every_refusal(tmp_path) -> None:
    path = _edited(tmp_path, "blockcopy__block", "blockcopy(DS28..", "blockcopy(Y001..")
    _, [warning] = _read_unchecked(path)
    assert str(warning) == (
        "rung 0: BlockCopy holds a value CLICK's dialog refuses, and decodes as it is "
        f"stored: {warning.error} (and 1 more) "
        f"(at {path}, line 3, rung at line 3, row 0 from 0, column AF)"
    )
    assert len(warning.errors) == 2


def test_warning_survives_pickle_and_copy(tmp_path) -> None:
    path = _edited(tmp_path, "copy__tag", "copy(DS7,", "copy(Y001,")
    _, [warning] = _read_unchecked(path)
    for clone in (pickle.loads(pickle.dumps(warning)), copy.copy(warning)):
        assert isinstance(clone, RefusedFieldWarning)
        assert str(clone) == str(warning)
        assert clone.instruction == warning.instruction
        assert [str(e) for e in clone.errors] == [str(e) for e in warning.errors]
        assert (clone.rung, clone.program) == (warning.rung, warning.program)


@pytest.mark.parametrize("unchecked", [False, True])
def test_a_refusal_no_stored_instruction_holds_still_raises(tmp_path, unchecked) -> None:
    """A timer unit that is not one of CLICK's unit names raises, even with ``unchecked``.

    Such a unit matches no stored value, so no decoded instruction can keep its refusal.
    """
    path = _edited(tmp_path, "off_delay__tof", "unit=Tms", "unit=Tx")
    with pytest.raises(FieldError) as raised:
        read_csv(path, unchecked=unchecked)
    error = raised.value
    assert error.field == "Timer.unit"
    assert error.reason is Reason.CHOICE
    assert error.location is not None
    assert "'Tx' is not one of" in str(error)


#: Each Math that CLICK saved with a formula that its dialog refuses, as (capture, rung index).
REAL_MATH = [
    ("math_ranges_x25_x101.bin", 0),
    ("math_ranges_x_t.bin", 2),
    ("math_ranges_xy_slots.bin", 1),
    ("math_ranges_xy_slots.bin", 2),
    ("math_ranges_xy_slots.bin", 3),
    ("math_ranges_xy_slots.bin", 4),
    ("math_ranges_xy_slots2.bin", 2),
    ("retyped/math_wide.bin", 5),
    ("retyped/math_wide.bin", 10),
]


@pytest.mark.parametrize(("file", "index"), REAL_MATH, ids=[f"{f}:{i}" for f, i in REAL_MATH])
def test_clicks_own_refused_math_writes_its_bytes(monkeypatch, file, index) -> None:
    """Each Math encodes as it did when it decoded as ``raw(...)``, with CLICK's blob and cell
    rows. ``replace`` raises the refusal for a copy that changes a field."""
    data = (FIXTURES / "v4_captures" / file).read_bytes()
    rungs, _ = _decoded(data)
    rung = rungs[index]
    [math] = [t for t in rung.instructions if refusals(t)]
    assert isinstance(math, Math)
    blob = math.build_blob()
    assert blob in data
    decode_mod = sys.modules["laddercodec.decode"]
    parse = decode_mod.parse_af_blob
    monkeypatch.setattr(
        decode_mod, "parse_af_blob", lambda raw: None if refusals(p := parse(raw)) else p
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        decoded_raw = decode(data)
    monkeypatch.undo()
    as_raw = decoded_raw[index]
    assert any(isinstance(t, RawInstruction) for t in as_raw.instructions)
    out = encode(rung)
    assert out == encode(as_raw)
    again, _ = _decoded(out)
    assert encode(again) == out
    with pytest.raises(FieldError) as caught:
        laddercodec.replace(math, oneshot=not math.oneshot)
    assert caught.value.code == refusals(math)[0].code


#: Edits made to both a program file and the clipboard capture of the same program. Each is
#: (file name without extension, stored text, replacement), and both texts are the same
#: length. The instruction that holds each replacement refuses it.
PROGRAM_EDITS = [
    ("shift_scr", "C2", "C0"),
    ("counter_scr", "CTD1", "CTD2"),
    ("coverage", "C4", "C0"),
    ("coverage", "3000", "abcd"),
]


def _instructions(rungs: list[Rung]) -> list[object]:
    return [t for rung in rungs for t in _tokens(rung) if refusals(t)]


@pytest.mark.parametrize(("name", "old", "new"), PROGRAM_EDITS)
def test_program_and_clipboard_decoders_agree(monkeypatch, name, old, new) -> None:
    """The clipboard decoder and the program decoder read the same instructions and refusals.

    An instruction from the clipboard keeps the blob that CLICK stored. A box from a program
    file keeps the blob that the decoder composes from the entry's tags, the same blob that
    the box holds when it stays raw. A condition from a program file keeps no blob, so its
    ``build_blob()`` raises its first refusal.
    """
    scr_dir = FIXTURES / "scr_captures"
    clipboard = (scr_dir / f"{name}.bin").read_bytes()
    program = (scr_dir / f"{name}.scr").read_bytes()

    def clip(text: str) -> bytes:
        return text.encode("utf-16-le") + b"\x00\x00"

    def scr(text: str) -> bytes:
        # A program file stores a string as a length byte, the text and one NUL byte.
        return bytes([len(text) * 2 + 1]) + text.encode("utf-16-le") + b"\x00"

    assert clipboard.count(clip(old)) == program.count(scr(old)) >= 1
    clipboard = clipboard.replace(clip(old), clip(new))
    from_clipboard, _ = _decoded(clipboard)
    with pytest.warns(RefusedFieldWarning):
        from_program = decode_program(program.replace(scr(old), scr(new))).rungs
    held, held_scr = _instructions(from_clipboard), _instructions(from_program)
    assert held and held == held_scr
    # Decode the program file again, and leave each box that holds a refusal raw.
    program_mod = sys.modules["laddercodec.decode_program"]
    scr_af = program_mod._scr_af
    monkeypatch.setattr(
        program_mod, "_scr_af", lambda *args: None if refusals(af := scr_af(*args)) else af
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        as_raw = decode_program(program.replace(scr(old), scr(new))).rungs
    raw_boxes = [t for rung in as_raw for t in rung.instructions if isinstance(t, RawInstruction)]
    for inst, inst_scr in zip(held, held_scr, strict=True):
        assert [e.field for e in refusals(inst)] == [e.field for e in refusals(inst_scr)]
        blob = stored_blob(inst)
        assert blob is not None and blob in clipboard
        if isinstance(inst_scr, AfInstruction):
            raw = raw_boxes.pop(0)
            assert stored_blob(inst_scr) == raw.blob
            assert inst_scr.build_blob() == raw.blob
            continue
        assert stored_blob(inst_scr) is None
        with pytest.raises(FieldError) as caught:
            inst_scr.build_blob()
        assert str(caught.value) == str(refusals(inst_scr)[0])
    assert not raw_boxes


def _saved_blob(tmp_path: Path, case: str) -> bytes:
    """Return the blob that CLICK saved for one case of the ``risky`` editor grid.

    Read it from the stored rows that ``risky.answers.json`` records for the case.
    """
    answers = json.loads(
        (FIXTURES / "editor_grids" / "risky.answers.json").read_text(encoding="utf-8")
    )
    [found] = [c for c in answers["cases"] if c["case"] == case]
    path = tmp_path / "stored.csv"
    path.write_text("\n".join([",".join(CSV_HEADER), *found["stored"]]) + "\n", "utf-8")
    [rung] = read_csv(path)
    [raw] = [t for t in rung.instructions if isinstance(t, RawInstruction)]
    return raw.blob


@pytest.mark.parametrize(
    ("case", "cls"),
    [
        ("single DS2 -> DS1 ", Copy),
        ("single DS2 ->  DS1", Copy),
        ("pack C1..C16 ->  DS1", Pack),
    ],
)
def test_an_edge_spaced_destination_writes_the_stored_bytes(tmp_path, case, cls) -> None:
    """A destination saved with a space at its start or end reads as the address alone.

    The instruction writes back the blob that CLICK saved. A copy made with ``replace``
    writes a different blob.
    """
    blob = _saved_blob(tmp_path, case)
    parsed = parse_af_blob(blob)
    assert isinstance(parsed, cls)
    assert parsed.dest == "DS1"
    assert not refusals(parsed)
    assert parsed.build_blob() == blob
    assert replace(parsed).build_blob() != blob
    # The tags read alone build the same instruction.
    class_name, type_code, _parts, _extra, fields = _decompose_blob(blob)
    assert from_tags_af(class_name, type_code, *_fields_to_tag_dicts(fields)) == parsed


#: Edits to the coverage program and its clipboard capture that put a space at the start or
#: end of a destination. Each is (stored text, replacement, class), and both texts are the
#: same length.
EDGE_EDITS = [("DS10", " DS1", Copy), ("DS10", "DS1 ", Copy), ("DS167", " DS16", Pack)]


@pytest.mark.parametrize(("old", "new", "cls"), EDGE_EDITS)
def test_both_decoders_write_an_edge_spaced_destination_as_stored(
    monkeypatch, old, new, cls
) -> None:
    """Each decoder reads the address without the space.

    The unchanged instruction writes back what the box wrote when it decoded raw. From the
    clipboard, that is the bytes that CLICK stored. From the program file, it is the blob
    that the decoder composes from the entry's tags, with the space kept.
    """
    scr_dir = FIXTURES / "scr_captures"
    clipboard = (scr_dir / "coverage.bin").read_bytes()
    program = (scr_dir / "coverage.scr").read_bytes()
    clip_old, clip_new = (t.encode("utf-16-le") + b"\x00\x00" for t in (old, new))
    scr_old, scr_new = (
        bytes([len(t) * 2 + 1]) + t.encode("utf-16-le") + b"\x00" for t in (old, new)
    )
    assert clipboard.count(clip_old) == program.count(scr_old) == 1
    clipboard = clipboard.replace(clip_old, clip_new)
    program = program.replace(scr_old, scr_new)

    def edge_spaced(rungs: list[Rung]) -> tuple[int, Any]:
        [found] = [
            (i, t)
            for i, rung in enumerate(rungs)
            for t in rung.instructions
            if type(t) is cls and t.dest == new.strip()
        ]
        return found

    from_clipboard = decode(clipboard)
    index, inst = edge_spaced(from_clipboard)
    assert not refusals(inst)
    blob = inst.build_blob()
    assert clip_new in blob and blob in clipboard
    # Decode the clipboard again, and leave that instruction raw.
    decode_mod = sys.modules["laddercodec.decode"]
    parse_af = decode_mod.parse_af_blob
    monkeypatch.setattr(
        decode_mod, "parse_af_blob", lambda raw: None if (af := parse_af(raw)) == inst else af
    )
    as_raw_clipboard = decode(clipboard)
    monkeypatch.undo()
    [raw_clip] = [t for t in as_raw_clipboard[index].instructions if isinstance(t, RawInstruction)]
    assert raw_clip.blob == blob
    assert encode(from_clipboard) == encode(as_raw_clipboard)

    from_program = decode_program(program).rungs
    scr_index, inst_scr = edge_spaced(from_program)
    assert inst_scr == inst and not refusals(inst_scr)
    # Decode the program file again, and leave that box raw.
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
    assert clip_new in raw.blob
    assert encode(from_program[scr_index]) == encode(as_raw[scr_index])


def test_a_block_copy_destination_keeps_its_edge_space() -> None:
    """CLICK refuses a space at the start or end of a Block Copy destination.

    So a stored blob with one does not decode as a BlockCopy, and ``from_tags_af`` returns
    None for it.
    """
    block = BlockCopy(source_start="DS1", source_end="DS2", dest_start="DS11", dest_end="DS12")
    class_name, type_code, _parts, _extra, fields = _decompose_blob(block.build_blob())
    tags, variant_u16, variant_string = _fields_to_tag_dicts(fields)
    assert from_tags_af(class_name, type_code, tags, variant_u16, variant_string) == block
    for spaced in (" DS11", "DS11 "):
        edited = tags | {0x6076: spaced}
        assert from_tags_af(class_name, type_code, edited, variant_u16, variant_string) is None


def _copy_rung(copy_af: Copy) -> Rung:
    return Rung(
        logical_rows=1,
        conditions=[["-"] * 31],
        instructions=[copy_af],
        comment_rtf=None,
        comment=None,
    )


def _force(inst: object, **values: object) -> None:
    """Write *values* to the fields of the frozen *inst* without running its checks."""
    for name, value in values.items():
        object.__setattr__(inst, name, value)


def test_write_csv_refuses_a_value_forced_after_construction(tmp_path) -> None:
    """If code forces a refused value onto a built instruction, ``write_csv`` raises.

    The rows that it would write do not read back as the rung.
    """
    copy_af = Copy("DS1", "DS2")
    _force(copy_af, dest="Y001")
    with pytest.raises(WriterError, match="Y001"):
        write_csv(tmp_path / "out.csv", [_copy_rung(copy_af)])


def test_write_csv_refuses_it_beside_a_held_refusal(tmp_path) -> None:
    """``write_csv`` also raises for a token forced to a refused value in a rung that holds
    a refusal.

    The writer reads such a rung back unchecked, and the token read back holds a refusal
    that the token written did not hold.
    """
    rungs, _ = _read_unchecked(_edited(tmp_path, "cond__no", ",C2,", ",DS2,"))
    _, contact = _held(rungs)
    copy_af = Copy("DS1", "DS2")
    rung = _copy_rung(copy_af)
    rung.conditions[0][0] = contact
    write_csv(tmp_path / "held.csv", [rung])
    _force(copy_af, dest="Y002")
    with pytest.raises(WriterError, match="Y002"):
        write_csv(tmp_path / "out.csv", [rung])
