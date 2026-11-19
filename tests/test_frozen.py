"""Test that instructions are frozen values, and that ``laddercodec.replace`` changes one.

An instruction can't be changed in place. ``replace`` returns a copy:

- If every value that the caller passes is equal to the field's current value, the copy
  keeps the blob that the original was decoded from, and it holds the same refusals. Each
  copy holds error objects of its own.
- If a value differs, the copy is built as if new, and a refused value raises the
  ``FieldError`` that building it raises.
"""

from __future__ import annotations

import csv
import dataclasses
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest

from laddercodec import (
    AddressError,
    Coil,
    Contact,
    Copy,
    FieldError,
    RawInstruction,
    RefusedFieldWarning,
    Rung,
    Tee,
    Timer,
    decode,
    encode,
    read_csv,
    replace,
    write_csv,
)
from laddercodec.csv import CSV_HEADER
from laddercodec.instructions import (
    ModbusAddress,
    ModbusRtuTarget,
    ModbusTcpTarget,
    UnknownCondition,
    UnknownInstruction,
)
from laddercodec.model import Condition, Instruction
from laddercodec.operands.unchecked import rebuilt, refusals, stored_blob, unchecked
from laddercodec.refused import warn_refused

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_DIRS = (FIXTURES / "ladder_captures" / "golden", FIXTURES / "coverage" / "golden")
GOLDEN_BINS = sorted(path for folder in GOLDEN_DIRS for path in folder.glob("*.bin"))


def _subclasses(cls: type) -> Iterator[type]:
    for sub in cls.__subclasses__():
        yield sub
        yield from _subclasses(sub)


#: Every instruction class that laddercodec defines, and the value types that an
#: instruction holds. Classes that other test modules define are left out.
CLASSES = sorted(
    {
        cls
        for cls in (
            *_subclasses(Instruction),
            *_subclasses(Condition),
            UnknownCondition,
            UnknownInstruction,
            Tee,
            ModbusAddress,
            ModbusRtuTarget,
            ModbusTcpTarget,
        )
        if dataclasses.is_dataclass(cls) and cls.__module__.startswith("laddercodec.")
    },
    key=lambda cls: cls.__name__,
)


def _instructions(value: object) -> Iterator[object]:
    """Yield each instruction in the rungs *value*, and each dataclass that one holds."""
    if isinstance(value, Rung):
        for row in value.conditions:
            for token in row:
                yield from _instructions(token)
        for token in value.instructions:
            yield from _instructions(token)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        yield value
        for field in dataclasses.fields(value):
            yield from _instructions(getattr(value, field.name))


def _decoded(path: Path) -> list[object]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        rungs = decode(path.read_bytes())
    return [inst for rung in rungs for inst in _instructions(rung)]


def _utf16z(text: str) -> bytes:
    return text.encode("utf-16-le") + b"\x00\x00"


def _rung(conditions: list[object], af: object) -> Rung:
    return Rung(
        conditions=[[*conditions, *["-"] * (31 - len(conditions))]],
        instructions=[af],
        comment_rtf=None,
        comment=None,
    )


def _stored(rung: Rung, *swaps: tuple[str, str]) -> bytes:
    """Return the bytes of *rung* with each stored text in *swaps* replaced by another of
    the same length, as if CLICK had stored that text."""
    data = encode(rung)
    for old, new in swaps:
        assert len(old) == len(new) and data.count(_utf16z(old)) == 1
        data = data.replace(_utf16z(old), _utf16z(new))
    return data


def _same_refusals(inst: object) -> list[tuple[object, ...]]:
    """Return the field, code, message and CSV location of each refusal of *inst*."""
    return [(e.field, e.code, str(e), getattr(e, "location", None)) for e in refusals(inst)]


def _decode_refused(data: bytes) -> tuple[Rung, list[RefusedFieldWarning]]:
    with pytest.warns(RefusedFieldWarning) as record:
        [rung] = decode(data)
    return rung, [w.message for w in record if isinstance(w.message, RefusedFieldWarning)]


# ---------------------------------------------------------------------------
# Frozen and hashable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", CLASSES, ids=lambda cls: cls.__name__)
def test_every_instruction_class_is_frozen(cls: type) -> None:
    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen  # type: ignore[attr-defined]


@pytest.mark.parametrize("path", GOLDEN_BINS, ids=lambda path: path.stem)
def test_assigning_to_a_field_raises(path: Path) -> None:
    for inst in _decoded(path):
        names = [field.name for field in dataclasses.fields(inst)] or ["anything"]
        for name in names:
            with pytest.raises(dataclasses.FrozenInstanceError):
                setattr(inst, name, getattr(inst, name, None))


@pytest.mark.parametrize("path", GOLDEN_BINS, ids=lambda path: path.stem)
def test_every_golden_instruction_hashes_as_its_equal_does(path: Path) -> None:
    first, again = _decoded(path), _decoded(path)
    assert len(first) == len(again)
    for inst, same in zip(first, again, strict=True):
        assert inst is not same and inst == same
        assert hash(inst) == hash(same)
    # The CSV golden reads as equal instructions, except where it holds a raw(...) token
    # for an instruction that decodes as its class.
    read = [inst for rung in read_csv(path.with_suffix(".csv")) for inst in _instructions(rung)]
    assert len(read) == len(first)
    equal = [(inst, same) for inst, same in zip(read, first, strict=True) if inst == same]
    for inst, same in equal:
        assert hash(inst) == hash(same)


def test_instructions_work_as_set_members_and_dict_keys() -> None:
    timer = Timer(kind="on_delay", done="T1", accumulator="TD1", preset="100", unit="Tms")
    same = Timer(kind="on_delay", done="T1", accumulator="TD1", preset="100", unit="Tms")
    assert {timer, same, Coil("Y001")} == {same, Coil("Y001")}
    assert {timer: 1}[same] == 1


@pytest.mark.parametrize("cls", [UnknownCondition, UnknownInstruction])
def test_an_unknown_cell_built_from_a_bytearray_holds_bytes(cls: type) -> None:
    unknown = cls(raw=bytearray(b"\x01\x02"))
    assert type(unknown.raw) is bytes
    assert unknown == cls(raw=b"\x01\x02")
    assert hash(unknown) == hash(cls(raw=b"\x01\x02"))


def test_a_raw_box_hashes_as_the_equal_box_that_states_its_height() -> None:
    blob = Copy("DS1", "DS2").build_blob()
    implied = RawInstruction("Copy", blob)
    rows = implied.cell_params().get("visual_rows", 1)
    stated = RawInstruction("Copy", blob, rows=rows, sub=rows)
    assert implied == stated
    assert hash(implied) == hash(stated)
    assert RawInstruction("Copy", blob, rows=rows + 1) != implied


# ---------------------------------------------------------------------------
# replace() on a built instruction
# ---------------------------------------------------------------------------


def test_replace_checks_the_changed_values() -> None:
    timer = Timer(kind="on_delay", done="T1", accumulator="TD1", preset="100", unit="Tms")
    slower = replace(timer, preset="500")
    assert slower == Timer(kind="on_delay", done="T1", accumulator="TD1", preset="500", unit="Tms")
    assert timer.preset == "100"
    with pytest.raises(FieldError) as built:
        Timer(kind="on_delay", done="T1", accumulator="TD1", preset="40000", unit="Tms")
    with pytest.raises(FieldError) as replaced:
        replace(timer, preset="40000")
    assert type(replaced.value) is type(built.value)
    assert str(replaced.value) == str(built.value)
    assert (replaced.value.field, replaced.value.code, replaced.value.click_id) == (
        built.value.field,
        built.value.code,
        built.value.click_id,
    )


def test_replace_writes_a_changed_address_in_display_form() -> None:
    assert replace(Coil("Y001"), operand="y2") == Coil("Y002")


def test_replace_with_no_changes_returns_an_equal_copy() -> None:
    coil = Coil("Y001")
    copy = replace(coil)
    assert copy == coil and copy is not coil
    assert replace(coil, operand="Y001", oneshot=False) == coil


@pytest.mark.parametrize("value", [Coil("Y001"), Contact("X001"), Copy("DS1", "DS2")])
def test_replace_refuses_an_unknown_field_name(value: object) -> None:
    with pytest.raises(TypeError):
        replace(value, no_such_field=1)


def test_replace_refuses_a_value_that_is_not_an_instruction() -> None:
    with pytest.raises(TypeError):
        replace("Y001", operand="Y002")  # type: ignore[type-var]
    with pytest.raises(TypeError):
        replace(Coil, operand="Y002")  # type: ignore[type-var]


# ---------------------------------------------------------------------------
# replace() on a decoded instruction
# ---------------------------------------------------------------------------


def _edge_spaced() -> tuple[bytes, Rung, Copy]:
    """Return the bytes of a rung whose Copy CLICK saved with a space before its
    destination, the decoded rung, and its Copy. The Copy holds no refusal."""
    data = _stored(_rung([], Copy("DS2", "DS10")), ("DS10", " DS1"))
    [rung] = decode(data)
    [copy] = rung.instructions
    assert isinstance(copy, Copy) and copy.dest == "DS1"
    assert not refusals(copy)
    assert stored_blob(copy) is not None
    return data, rung, copy


def test_replace_unchanged_keeps_the_blob_of_a_decoded_instruction() -> None:
    data, rung, copy = _edge_spaced()
    for same in (replace(copy), replace(copy, dest="DS1", oneshot=copy.oneshot)):
        assert same == copy and same is not copy
        assert stored_blob(same) == stored_blob(copy)
        assert same.build_blob() == copy.build_blob()
        assert encode(replace(rung, instructions=[same])) == data


def test_replace_changed_drops_the_blob_of_a_decoded_instruction() -> None:
    _, rung, copy = _edge_spaced()
    changed = replace(copy, oneshot=True)
    assert stored_blob(changed) is None
    assert changed.build_blob() == Copy("DS2", "DS1", oneshot=True).build_blob()
    assert copy.oneshot is False


def test_replace_unchanged_keeps_the_refusals_of_a_decoded_instruction() -> None:
    data = _stored(_rung([Contact("X101")], Coil("Y801")), ("Y801", "Y901"), ("X101", "X117"))
    rung, warned = _decode_refused(data)
    contact, coil = rung.conditions[0][0], rung.instructions[0]
    assert [(w.instruction, w.error.field) for w in warned] == [
        (contact, "Contact.operand"),
        (coil, "Coil.operand"),
    ]
    rung = replace(
        rung,
        conditions=[(replace(contact), *rung.conditions[0][1:])],
        instructions=[replace(coil)],
    )
    for old, new in ((contact, rung.conditions[0][0]), (coil, rung.instructions[0])):
        assert new == old and new is not old
        assert _same_refusals(new) == _same_refusals(old)
        assert all(error.obj is new for error in refusals(new))
        assert all(error.obj is old for error in refusals(old))
        assert stored_blob(new) == stored_blob(old) is not None
    assert encode(rung) == data
    with pytest.warns(RefusedFieldWarning) as again:
        warn_refused([rung])
    assert [(w.message.instruction, w.message.error.field) for w in again] == [
        (rung.conditions[0][0], "Contact.operand"),
        (rung.instructions[0], "Coil.operand"),
    ]


def test_replace_that_fixes_every_refusal_gives_a_clean_instruction() -> None:
    data = _stored(_rung([], Coil("Y801")), ("Y801", "Y901"))
    rung, _ = _decode_refused(data)
    [coil] = rung.instructions
    fixed = replace(coil, operand="Y001")
    assert fixed == Coil("Y001")
    assert not refusals(fixed) and stored_blob(fixed) is None
    assert encode(replace(rung, instructions=[fixed])) == encode(_rung([], Coil("Y001")))


def test_replace_that_leaves_a_refusal_raises_it() -> None:
    data = _stored(_rung([], Coil("Y801")), ("Y801", "Y901"))
    rung, _ = _decode_refused(data)
    [coil] = rung.instructions
    [held] = refusals(coil)
    with pytest.raises(AddressError) as caught:
        replace(coil, oneshot=True)
    assert (caught.value.field, caught.value.code) == (held.field, held.code)
    with pytest.raises(AddressError) as built:
        Coil("Y901", oneshot=True)
    assert str(caught.value) == str(built.value)


def _decoded_tee_contact() -> tuple[bytes, Rung, Contact, RefusedFieldWarning]:
    """Return the bytes and the decoded rung of a refused contact with a wire down, the
    contact inside its ``Tee``, and the warning that decoding it emits."""
    conditions = [["-", Tee(Contact("X101")), *["-"] * 29], ["-", "-", *[""] * 29]]
    rung = Rung(
        conditions=conditions,
        instructions=[Coil("Y001"), Coil("Y002")],
        comment_rtf=None,
        comment=None,
    )
    data = encode(rung).replace(_utf16z("X101"), _utf16z("X117"))
    decoded, [warning] = _decode_refused(data)
    tee = decoded.conditions[0][1]
    assert isinstance(tee, Tee) and isinstance(tee.contact, Contact)
    return data, decoded, tee.contact, warning


def test_a_decoded_tee_keeps_the_blob_and_the_refusals_of_its_contact() -> None:
    """The decoder wraps the contact in a ``Tee`` and does not copy it. Each refusal of
    the contact names that contact, and the warning names the contact, not the ``Tee``.
    A ``Tee`` around an unchanged copy of the contact encodes as the stored bytes."""
    data, decoded, contact, warning = _decoded_tee_contact()
    assert warning.instruction is contact
    assert warning.errors == refusals(contact)
    assert all(error.obj is contact for error in refusals(contact))
    assert stored_blob(contact) is not None
    assert encode(decoded) == data
    same = replace(contact)
    rows = [list(row) for row in decoded.conditions]
    rows[0][1] = Tee(same)
    assert encode(replace(decoded, conditions=rows)) == data


def test_copies_and_write_csv_leave_the_errors_of_the_original_alone(tmp_path) -> None:
    """Each copy holds its own errors. Making a copy, or writing the rung to CSV, does not
    change which instruction an error of the original names."""
    _, decoded, contact, _ = _decoded_tee_contact()
    held = refusals(contact)
    same = replace(contact)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RefusedFieldWarning)
        write_csv(tmp_path / "rung.csv", [decoded])
    again = rebuilt(contact)
    assert refusals(contact) == held
    assert all(error.obj is contact for error in held)
    for copy in (same, again):
        assert not set(map(id, refusals(copy))) & set(map(id, held))
        assert all(error.obj is copy for error in refusals(copy))
        assert _same_refusals(copy) == _same_refusals(contact)


def test_rebuilt_of_pin_rows_copies_each_error() -> None:
    """A copy that changes only ``pin_rows`` holds a copy of each error of the original,
    with the same message and location, that names the copy."""
    with unchecked():
        timer = Timer("on_delay", "T1", "TD2", "1000", "Tms")
    held = refusals(timer)
    assert [error.field for error in held] == ["Timer.accumulator"]
    down = rebuilt(timer, pin_rows=(2,))
    up = rebuilt(down, pin_rows=(1,))
    for copy in (down, up):
        assert _same_refusals(copy) == _same_refusals(timer)
        assert all(error.obj is copy for error in refusals(copy))
        assert not set(map(id, refusals(copy))) & set(map(id, held))
        [head] = refusals(copy)
        assert head.errors == (head,)
    assert down.pin_rows == (2,) and up.pin_rows == (1,)
    assert all(error.obj is timer for error in held)


# ---------------------------------------------------------------------------
# replace() on an instruction read from CSV
# ---------------------------------------------------------------------------


def _read_unchecked(tmp_path: Path, row: list[str]) -> tuple[Rung, list[RefusedFieldWarning]]:
    """Return the rung that ``read_csv(unchecked=True)`` reads from one CSV row, and the
    warnings that it emits."""
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(CSV_HEADER)
        writer.writerow(row)
    with pytest.warns(RefusedFieldWarning) as record:
        [rung] = read_csv(path, unchecked=True)
    return rung, [w.message for w in record if isinstance(w.message, RefusedFieldWarning)]


@pytest.mark.parametrize(
    ("cell", "typed", "field"),
    [
        ("x117", "'x117' (X117) is outside", "Contact.operand"),
        ("DS1==ds0", "'ds0' (DS0) is outside", "CompareContact.right"),
    ],
)
def test_read_csv_warns_with_the_typed_text_and_the_cell_of_a_contact(
    tmp_path, cell: str, typed: str, field: str
) -> None:
    """The warning names the contact that the laid-out rung holds, quotes the text as
    typed, and names the cell."""
    rung, [warning] = _read_unchecked(tmp_path, ["R", cell, *["-"] * 30, "out(Y001)"])
    contact = rung.conditions[0][0]
    assert warning.instruction is contact
    assert warning.error.field == field
    assert typed in str(warning.error)
    assert "line 2" in str(warning) and "column A" in str(warning)
    assert all(error.obj is contact for error in refusals(contact))


def test_replace_unchanged_of_a_csv_coil_keeps_the_message_and_location(tmp_path) -> None:
    rung, [warning] = _read_unchecked(tmp_path, ["R", "X001", *["-"] * 30, "out(y901)"])
    coil = rung.instructions[0]
    [held] = refusals(coil)
    assert "'y901' (Y901) is outside" in str(held)
    assert held.location is not None and held.location.column_name == "AF"
    for copy in (replace(coil), replace(coil, operand=coil.operand)):
        [error] = refusals(copy)
        assert error is not held and error.obj is copy
        assert (str(error), error.location) == (str(held), held.location)


def _refused_send(tmp_path: Path) -> tuple[Rung, object]:
    """Return the rung of a Send whose target holds a refused Slave ID, read unchecked from
    CSV, and the Send."""
    golden = FIXTURES / "coverage" / "golden" / "send__tcp_click_coil.csv"
    text = golden.read_text(encoding="utf-8")
    assert text.count("device_id=1") == 1
    path = tmp_path / "send.csv"
    path.write_text(text.replace("device_id=1", "device_id=256"), encoding="utf-8")
    with pytest.warns(RefusedFieldWarning):
        [rung] = read_csv(path, unchecked=True)
    [send] = [t for t in rung.instructions if refusals(t)]
    assert [error.field for error in refusals(send)] == ["ModbusTcpTarget.device_id"]
    return rung, send


def test_replace_unchanged_of_a_csv_instruction_still_refuses_to_encode(tmp_path) -> None:
    rung, send = _refused_send(tmp_path)
    same = replace(send)
    assert same == send
    assert _same_refusals(same) == _same_refusals(send)
    assert stored_blob(same) is None
    instructions = list(rung.instructions)
    instructions[instructions.index(send)] = same
    with pytest.raises(FieldError) as caught:
        encode(replace(rung, instructions=instructions))
    assert str(caught.value) == str(refusals(send)[0])


def test_replace_checks_a_target_that_holds_a_refusal(tmp_path) -> None:
    """A change to another field builds the target again, so its refusal raises."""
    _, send = _refused_send(tmp_path)
    [held] = refusals(send)
    with pytest.raises(FieldError) as caught:
        replace(send, word_swap=not send.word_swap)  # type: ignore[attr-defined]
    assert (caught.value.field, caught.value.code) == (held.field, held.code)
    target = send.target  # type: ignore[attr-defined]
    fixed = replace(send, target=replace(target, device_id=1))
    assert not refusals(fixed)
