"""``read_csv(..., allow=...)`` and ``read_bundle(..., allow=...)``.

Most cases are those of ``tests/test_refused_fields.py``: a golden edited to hold a value
that CLICK's dialog refuses. The tests show that:

- an instruction keeps a refusal only if ``allow`` lists the code of every error in it;
- an instruction keeps it only if laddercodec writes its blob and reads it back the same;
- any other refusal raises as the default read raises it, with the same location;
- a refusal that no instruction can keep raises whatever ``allow`` lists;
- an allowed refusal emits no ``RefusedFieldWarning``;
- ``encode()``, ``write_csv`` and ``write_bundle`` write the instruction from its fields;
- ``decode()`` of that blob returns the instruction, holding the refusal and the blob;
- ``replace`` checks a changed copy again, and ``allowed()`` returns False for it;
- a bad ``allow`` raises ``CsvError`` before any file is read.
"""

from __future__ import annotations

import csv
import dataclasses
import warnings
from pathlib import Path
from typing import Any

import pytest

import laddercodec
from laddercodec import (
    Code,
    CsvError,
    FieldError,
    RefusedFieldWarning,
    Rung,
    decode,
    encode,
    read_bundle,
    read_csv,
    write_bundle,
    write_csv,
)
from laddercodec.csv import CSV_HEADER, CsvLocation
from laddercodec.instructions.coil import Coil
from laddercodec.instructions.drum import Drum
from laddercodec.instructions.send_receive import Receive, Send
from laddercodec.instructions.timer import Timer
from laddercodec.model import Program, Project
from laddercodec.operands.address import NotDisplayForm, display_form_only
from laddercodec.operands.unchecked import (
    allowed,
    holds_refusals,
    rebuilt,
    refusals,
    stored_blob,
    unchecked,
)
from tests.test_refused_fields import _IDS, CASES, _edited, _held, _stored_bytes

AF = 31


def _codes(path: Path) -> set[Code]:
    """Return the code of every refusal that ``read_csv(path, unchecked=True)`` keeps."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RefusedFieldWarning)
        rungs = read_csv(path, unchecked=True)
    _, held = _held(rungs)
    return {error.code for error in refusals(held) if error.code is not None}


def _read_allowed(path: Path, allow: Any) -> list[Rung]:
    """Return ``read_csv(path, allow=allow)``, and assert that it emits no warning."""
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        rungs = read_csv(path, allow=allow)
    assert [str(w.message) for w in record] == []
    return rungs


def _one_rung(path: Path, af: str, contact: str = "X1") -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        writer.writerow(["R", contact, *["-"] * 30, af])
    return path


def _rung(path: Path, *afs: str) -> Path:
    """Write one rung with a contact on each row and *afs* in the AF column, one per row."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        for row, af in enumerate(afs):
            writer.writerow(["R" if row == 0 else "", f"X{row + 1}", *["-"] * 30, af])
    return path


_RTU = 'target=ModbusRtuTarget(name="rtu",com_port="cpu2",device_id=5)'
_EVENTS = ",".join(f"C{i}" for i in range(10, 27))
_STEPS = ",".join(["[1]"] * 17)

# Instructions whose refusals all have a code, but whose blob laddercodec can't write and
# read back the same.
_UNWRITABLE = [
    pytest.param(["math(TD501 + 1,DS1,mode=decimal)"], id="math-formula"),
    pytest.param(['copy("AB",TXT1001)'], id="copy-text-past-bank"),
    pytest.param(
        [f'send({_RTU},remote_start="DS1",source=x1,sending=C1,success=C2,error=C3)'],
        id="send-source",
    ),
    pytest.param(
        [f'send({_RTU},remote_start="X001",source=C1,sending=C10,success=C2,error=C3)'],
        id="send-remote",
    ),
    pytest.param(
        [f'receive({_RTU},remote_start="DS1",dest=,receiving=C1,success=C2,error=C3)'],
        id="receive-blank-dest",
    ),
    pytest.param(["out()"], id="out-blank"),
    pytest.param(["fill(,DS1..DS5)"], id="fill-blank"),
    pytest.param(["copy(,DS1)"], id="copy-blank"),
    pytest.param(["for()"], id="for-blank"),
    pytest.param(["on_delay(T1,TD1,preset=,unit=Tms)"], id="timer-blank-preset"),
    pytest.param(["count_up(CT1,CTD1,preset=)", ".reset()"], id="counter-blank-preset"),
    pytest.param(["math(DS1 + 1,,mode=decimal)"], id="math-blank-result"),
    pytest.param(["off_delay(T1,TD1,preset=100,unit=Tms)", ".reset()"], id="off-delay-reset"),
    pytest.param(
        ["off_delay(Y001,TD1,preset=100,unit=Tms)", ".reset()"], id="off-delay-cell-and-reset"
    ),
    pytest.param(
        [
            f"event_drum(outputs=[C3],events=[{_EVENTS}],pattern=[{_STEPS}],"
            "current_step=DS1,completion_flag=C1)",
            ".reset()",
        ],
        id="drum-17-steps",
    ),
]

# Instructions whose refusals all have a code, and whose blob laddercodec writes and reads
# back the same. The second item is the For count that the instruction holds.
_WRITABLE = [
    pytest.param(["for(x1)"], "X001", id="for-x1"),
    pytest.param(["for(XD0U)"], "XD0u", id="for-xd0u"),
    pytest.param(["for(DS[X1])"], "DS[X001]", id="for-pointer"),
    pytest.param(["math(DS1 + 1,x1,mode=decimal)"], None, id="math-result"),
    pytest.param(
        [f'receive({_RTU},remote_start="XD0",dest=DS1,receiving=C1,success=C2,error=C3)'],
        None,
        id="receive-remote",
    ),
    pytest.param(
        [
            'send(target=ModbusRtuTarget(name="pump",com_port="cpu2",device_id=5),'
            'remote_start="DS1",source=DS1,sending=DS5,success=C2,error=C3)'
        ],
        None,
        id="send-named-target",
    ),
    pytest.param(
        [
            'receive(target=ModbusTcpTarget(name="pump",ip="192.168.1.10",port=502,'
            'device_id=1),remote_start="DS1",dest=DS1,receiving=DS5,success=C2,error=C3)'
        ],
        None,
        id="receive-named-target",
    ),
]


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_an_allowed_refusal_is_kept_without_a_warning(
    tmp_path, golden, old, new, cls, fields
) -> None:
    path = _edited(tmp_path, golden, old, new)
    with pytest.raises(FieldError) as raised:
        read_csv(path)
    rungs = _read_allowed(path, _codes(path))
    _, held = _held(rungs)
    assert isinstance(held, cls)
    assert allowed(held)
    assert [e.field for e in refusals(held)] == fields

    def where(errors: tuple[FieldError, ...]) -> list[tuple[object, ...]]:
        return [(e.fields, e.reason, e.code, CsvLocation.of(e)) for e in errors]

    assert where(refusals(held)) == where(raised.value.errors)


@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_a_code_left_out_raises_as_the_default_read(
    tmp_path, golden, old, new, cls, fields
) -> None:
    """Allowing every code but one of the refusal's raises the refusal, as the default read
    raises it."""
    path = _edited(tmp_path, golden, old, new)
    codes = _codes(path)
    with pytest.raises(FieldError) as default:
        read_csv(path)
    for left_out in codes:
        # blank-field is never in these refusals, so the list is never empty.
        with pytest.raises(FieldError) as raised:
            read_csv(path, allow=[*(codes - {left_out}), Code.BLANK_FIELD])
        assert type(raised.value) is type(default.value)
        assert str(raised.value) == str(default.value)
        assert CsvLocation.of(raised.value) == CsvLocation.of(default.value)


def test_a_refusal_needs_every_code_allowed(tmp_path) -> None:
    """A Block Copy whose refusal holds two codes raises unless both are allowed."""
    path = _edited(tmp_path, "blockcopy__block", "blockcopy(DS28..", "blockcopy(Y001..")
    assert _codes(path) == {Code.COPY_BANK_INCOMPATIBLE, Code.RANGE_MIXED_BANKS}
    with pytest.raises(FieldError, match="^BlockCopy.source_end"):
        read_csv(path, allow=["range-mixed-banks"])
    with pytest.raises(FieldError, match="^BlockCopy.source_end"):
        read_csv(path, allow=[Code.COPY_BANK_INCOMPATIBLE])
    _, held = _held(_read_allowed(path, ["range-mixed-banks", Code.COPY_BANK_INCOMPATIBLE]))
    assert allowed(held)


@pytest.mark.parametrize(
    ("af", "code"),
    [
        ("on_delay(T1,TD1,preset=1,unit=Txx)", Code.INVALID_CHOICE),
        ("out(Y1,oneshot=2)", Code.NOT_A_FLAG),
        ("copy(DS1,TXT1,convert=to_text(suppress_zero=2))", Code.NOT_A_FLAG),
    ],
)
def test_a_value_no_instruction_holds_raises_whatever_is_allowed(tmp_path, af, code) -> None:
    path = _one_rung(tmp_path / "r.csv", af)
    with pytest.raises(FieldError) as default:
        read_csv(path)
    assert code in {e.code for e in default.value.errors}
    with pytest.raises(FieldError) as raised:
        read_csv(path, allow=list(Code))
    assert str(raised.value) == str(default.value)


@pytest.mark.parametrize("afs", _UNWRITABLE)
def test_an_instruction_laddercodec_cant_write_raises_as_the_default_read(tmp_path, afs) -> None:
    """The instruction keeps its refusal with every code allowed. Its blob does not read back
    to it, so ``read_csv`` raises the first refusal as the default read raises it."""
    path = _rung(tmp_path / "r.csv", *afs)
    # A box that refuses a value that a pin row sets raises CsvError.
    with pytest.raises((FieldError, CsvError)) as default:
        read_csv(path)
    # Read with unchecked=True, the instruction keeps the refusal. A box whose own cell
    # and pins both refuse keeps the refusals of both.
    assert {e.code for e in default.value.errors} <= _codes(path)
    with pytest.raises((FieldError, CsvError)) as raised:
        read_csv(path, allow=list(Code))
    assert type(raised.value) is type(default.value)
    assert str(raised.value) == str(default.value)
    assert CsvLocation.of(raised.value) == CsvLocation.of(default.value)
    assert [e.field for e in raised.value.errors] == [e.field for e in default.value.errors]


@pytest.mark.parametrize(("afs", "count"), _WRITABLE)
def test_an_instruction_laddercodec_can_write_round_trips(tmp_path, afs, count) -> None:
    path = _rung(tmp_path / "r.csv", *afs)
    codes = _codes(path)
    rungs = _read_allowed(path, codes)
    _, held = _held(rungs)
    assert allowed(held)
    if count is not None:
        assert held.count == count
    with pytest.warns(RefusedFieldWarning):
        decoded = decode(encode(rungs))
    _, back = _held(decoded)
    assert stored_blob(back) == held.build_blob()
    if isinstance(held, (Send, Receive)) and back.target.name != held.target.name:
        # The blob does not store the target's name. Compare with the name put back.
        assert rebuilt(back, target=rebuilt(back.target, name=held.target.name)) == held
    else:
        assert decoded == rungs


def test_the_first_bad_rung_raises_first(tmp_path) -> None:
    path = tmp_path / "r.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        writer.writerow(["R", "X1", *["-"] * 30, "out()"])
        writer.writerow(["R", "X2", *["-"] * 30, "frob(C1)"])
    with pytest.raises(FieldError) as default:
        read_csv(path)
    with pytest.raises(FieldError) as raised:
        read_csv(path, allow=list(Code))
    assert str(raised.value) == str(default.value)
    assert CsvLocation.of(raised.value) == CsvLocation.of(default.value)


def test_a_not_display_form_refusal_of_a_real_instruction_raises_whatever_is_allowed() -> None:
    with display_form_only(), unchecked(allow=list(Code)), pytest.raises(NotDisplayForm):
        Coil("y1")


def test_a_pin_rows_refusal_of_a_real_instruction_raises_whatever_is_allowed() -> None:
    timer = Timer("on_delay", "T1", "TD1", "100", "Tms", retained=True)
    with unchecked(allow=list(Code)), pytest.raises(FieldError) as raised:
        timer.with_pin_rows((0,))
    assert raised.value.field == "Timer.pin_rows"


@holds_refusals
@dataclasses.dataclass(frozen=True)
class _Box:
    """A stand-in instruction whose construction raises *error*."""

    error: Any

    def __post_init__(self) -> None:
        raise self.error

    def build_blob(self) -> bytes:
        return b"built"


def _crashed() -> FieldError:
    try:
        try:
            int("x")
        except ValueError as exc:
            raise FieldError("Box.value: crashed", code=Code.NOT_A_CONSTANT) from exc
    except FieldError as error:
        return error
    raise AssertionError


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(
            FieldError("Box.pin_rows: refused", field="Box.pin_rows", code=Code.NOT_A_CONSTANT),
            id="pin-rows",
        ),
        pytest.param(
            NotDisplayForm("Box.operand: x1", field="Box.operand", code=Code.NOT_CLICK_FORM),
            id="not-display-form",
        ),
        pytest.param(_crashed(), id="crashed-check"),
    ],
)
def test_a_refusal_no_instruction_can_keep_raises_whatever_is_allowed(error) -> None:
    with unchecked(allow=list(Code)), pytest.raises(FieldError) as raised:
        _Box(error)
    assert raised.value is error


def test_an_allowed_box_builds_its_blob_and_a_kept_one_raises() -> None:
    refusal = FieldError("Box.value: refused", field="Box.value", code=Code.NOT_A_CONSTANT)
    with unchecked(allow=[Code.NOT_A_CONSTANT]):
        box = _Box(refusal)
    assert allowed(box)
    assert box.build_blob() == b"built"
    with unchecked():
        kept = _Box(refusal)
    assert refusals(kept) and not allowed(kept)
    with pytest.raises(FieldError, match="Box.value: refused"):
        kept.build_blob()


def test_a_nested_plain_block_allows_nothing_by_code() -> None:
    """A block inside an allowing block keeps refusals as plain ``unchecked()`` keeps them."""
    refusal = FieldError("Box.value: refused", field="Box.value", code=Code.NOT_A_CONSTANT)
    with unchecked(allow=[Code.NOT_A_CONSTANT]):
        with unchecked():
            inner = _Box(refusal)
        outer = _Box(refusal)
    assert not allowed(inner)
    assert allowed(outer)


def test_pins_of_an_allowed_box_are_located_at_their_rows(tmp_path) -> None:
    """A Drum's own refusal and its ``.jump(...)`` target's refusal are both allowed. Each
    has the location that the default read raises it with."""
    drum = "event_drum(outputs=[C3],events=[C2],pattern=[[1]],current_step=Y001,completion_flag=C1)"
    path = tmp_path / "main.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        writer.writerow(["R", "C1", *["-"] * 30, drum])
        writer.writerow(["", "C2", *["-"] * 30, ".reset()"])
        writer.writerow(["", "C4", *[""] * 30, ""])
        writer.writerow(["", "C5", *["-"] * 30, ".jump(C5)"])
    [rung] = _read_allowed(path, _codes(path))
    held = rung.instructions[0]
    assert isinstance(held, Drum)
    assert allowed(held)
    located = {e.field: CsvLocation.of(e) for e in refusals(held)}
    assert located == {
        "Drum.current_step": CsvLocation(file=path, line=2, rung_line=2, row=0, column=AF),
        "Drum.jump_step": CsvLocation(file=path, line=5, rung_line=2, row=3, column=AF),
    }
    data = encode([rung])
    with pytest.warns(RefusedFieldWarning):
        [back] = decode(data)
    assert back.instructions[0] == held
    assert stored_blob(back.instructions[0]) == held.build_blob()


# ---------------------------------------------------------------------------
# Writing and the round trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_encode_writes_the_blob_of_its_fields(
    tmp_path, monkeypatch, golden, old, new, cls, fields
) -> None:
    path = _edited(tmp_path, golden, old, new)
    rungs = _read_allowed(path, _codes(path))
    _, held = _held(rungs)
    data = encode(rungs)
    assert held.build_blob() in data
    # The bytes that encode() writes for the CSV with every check turned off. For a Send or
    # Receive, whose blob builder runs its checks, these are the golden's bytes with the
    # edit made in them.
    assert data == _stored_bytes(tmp_path, monkeypatch, golden, old, new, cls, fields)


@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_decode_returns_it_holding_its_refusal_and_blob(
    tmp_path, golden, old, new, cls, fields
) -> None:
    path = _edited(tmp_path, golden, old, new)
    rungs = _read_allowed(path, _codes(path))
    index, held = _held(rungs)
    with pytest.warns(RefusedFieldWarning):
        decoded = decode(encode(rungs))
    found = _held(decoded)
    assert found[0] == index
    assert decoded == rungs
    back = found[1]
    assert back == held
    assert [e.field for e in refusals(back)] == fields
    assert stored_blob(back) == held.build_blob()
    assert not allowed(back)


@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_write_csv_writes_it_and_it_reads_back(tmp_path, golden, old, new, cls, fields) -> None:
    path = _edited(tmp_path, golden, old, new)
    codes = _codes(path)
    rungs = _read_allowed(path, codes)
    out = tmp_path / "out.csv"
    write_csv(out, rungs)
    again = _read_allowed(out, codes)
    assert again == rungs
    assert allowed(_held(again)[1])
    assert encode(again) == encode(rungs)


def test_read_with_unchecked_still_raises_at_encode(tmp_path) -> None:
    path = _edited(tmp_path, "out__tag", "out(C23)", "out(X001)")
    with pytest.warns(RefusedFieldWarning):
        rungs = read_csv(path, unchecked=True)
    _, held = _held(rungs)
    assert not allowed(held)
    with pytest.raises(FieldError, match="^Coil.operand"):
        encode(rungs)


# ---------------------------------------------------------------------------
# replace() and rebuilt()
# ---------------------------------------------------------------------------


def _allowed_coil(tmp_path: Path) -> tuple[list[Rung], Any]:
    path = _edited(tmp_path, "out__tag", "out(C23)", "out(X001)")
    rungs = _read_allowed(path, ["bank-not-allowed"])
    return rungs, _held(rungs)[1]


def test_replace_checks_a_changed_copy_again(tmp_path) -> None:
    _, held = _allowed_coil(tmp_path)
    with pytest.raises(FieldError, match="^Coil.operand"):
        laddercodec.replace(held, operand="X002")


def test_replace_with_no_change_is_still_allowed(tmp_path) -> None:
    _, held = _allowed_coil(tmp_path)
    same = laddercodec.replace(held, operand=held.operand)
    assert allowed(same)
    assert same.build_blob() == held.build_blob()


def test_rebuilt_with_a_changed_field_is_not_allowed(tmp_path) -> None:
    _, held = _allowed_coil(tmp_path)
    copy = rebuilt(held, operand="X002")
    assert refusals(copy)
    assert not allowed(copy)
    with pytest.raises(FieldError, match="^Coil.operand"):
        copy.build_blob()


def test_rebuilt_with_new_pin_rows_is_still_allowed(tmp_path) -> None:
    path = _edited(tmp_path, "off_delay__tof", "off_delay(T3,", "off_delay(Y001,")
    _, held = _held(_read_allowed(path, ["bank-not-allowed"]))
    assert isinstance(held, Timer)
    moved = held.with_pin_rows(held.pin_rows)
    assert allowed(moved)


# ---------------------------------------------------------------------------
# read_bundle and write_bundle
# ---------------------------------------------------------------------------


def test_read_bundle_allows_in_every_file(tmp_path) -> None:
    edited = _edited(tmp_path, "out__tag", "out(C23)", "out(X001)")
    bundle = tmp_path / "bundle"
    (bundle / "subroutines").mkdir(parents=True)
    (bundle / "main.csv").write_text(edited.read_text(encoding="utf-8"), encoding="utf-8")
    (bundle / "subroutines" / "Pump.csv").write_text(
        edited.read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(FieldError, match="^Coil.operand"):
        read_bundle(bundle)
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        project = read_bundle(bundle, allow=["bank-not-allowed"])
    assert [str(w.message) for w in record] == []
    for program in (project.main, *project.subroutines):
        _, held = _held(program.rungs)
        assert allowed(held)
        assert encode(program.rungs)
    out = tmp_path / "out"
    write_bundle(out, project)
    again = read_bundle(out, allow=["bank-not-allowed"])
    assert again.main.rungs == project.main.rungs
    assert again.subroutines[0].rungs == project.subroutines[0].rungs


def test_write_bundle_writes_an_allowed_instruction(tmp_path) -> None:
    rungs, _ = _allowed_coil(tmp_path)
    project = Project(main=Program("Main Program", 1, rungs), subroutines=[])
    write_bundle(tmp_path / "out", project)
    assert (tmp_path / "out" / "main.csv").read_text(encoding="utf-8").count("out(X001)") == 1


# ---------------------------------------------------------------------------
# A bad allow=
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reader", [read_csv, read_bundle], ids=["read_csv", "read_bundle"])
@pytest.mark.parametrize(
    ("allow", "unchecked_", "message"),
    [
        (["bank-not-alowed"], False, "allow= holds 'bank-not-alowed', which is not a code"),
        (["BANK_NOT_ALLOWED"], False, "allow= holds 'BANK_NOT_ALLOWED', which is not a code"),
        ([4], False, "allow= holds 4, which is not a code"),
        (
            "bank-not-allowed",
            False,
            r"allow='bank-not-allowed' is one code name\. Pass a list of code names, such as "
            r"allow=\['bank-not-allowed'\]\.$",
        ),
        (
            Code.BANK_NOT_ALLOWED,
            False,
            r"allow='bank-not-allowed' is one code name\. Pass a list of code names, such as "
            r"allow=\['bank-not-allowed'\]\.$",
        ),
        (b"bank", False, r"allow=b'bank' is not a list of code names"),
        (5, False, r"allow=5 is not a list of code names"),
        (
            ["bank-not-allowed"],
            True,
            r"you passed both unchecked=True and allow=\. Pass one of them, such as "
            r"allow=\['bank-not-allowed'\] alone\.$",
        ),
    ],
)
def test_a_bad_allow_raises_before_any_file_is_read(
    tmp_path, reader, allow, unchecked_, message
) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(CsvError, match=message) as raised:
        reader(missing, allow=allow, unchecked=unchecked_)
    assert str(raised.value).startswith(f"{reader.__name__}: ")
    assert CsvLocation.of(raised.value) is None


def test_an_empty_allow_reads_as_the_default(tmp_path) -> None:
    path = _edited(tmp_path, "out__tag", "out(C23)", "out(X001)")
    with pytest.raises(FieldError, match="^Coil.operand"):
        read_csv(path, allow=[])
    with pytest.warns(RefusedFieldWarning):
        read_csv(path, unchecked=True, allow=())


def test_allow_none_reads_as_the_default(tmp_path) -> None:
    path = _edited(tmp_path, "out__tag", "out(C23)", "out(X001)")
    with pytest.raises(FieldError, match="^Coil.operand"):
        read_csv(path, allow=None)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "main.csv").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(FieldError, match="^Coil.operand"):
        read_bundle(bundle, allow=None)
