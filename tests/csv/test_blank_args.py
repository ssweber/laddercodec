"""Tests that a blank argument in an AF token reads as that field left blank.

``read_csv`` refuses a token with a blank argument in the same way as Python refuses the
instruction built with that field blank. It raises a ``FieldError`` with reason ``missing``.
The error names the field and gives the location of the token's cell.
``read_csv(..., unchecked=True)`` keeps the refusal on the instruction, as it does for any
refusal. A token that is malformed in another way still raises a syntax error. Every field
that Python accepts blank also reads blank from its CSV token.
"""

from __future__ import annotations

import csv
import dataclasses
import re
import warnings
from pathlib import Path
from typing import Any

import pytest

from laddercodec import (
    CsvLocation,
    FieldError,
    Reason,
    RefusedFieldWarning,
    Rung,
    read_csv,
    write_csv,
)
from laddercodec.csv.contract import CONDITION_COLUMNS, CSV_HEADER
from laddercodec.csv.converter import af_node_to_token
from laddercodec.csv.token_parser import fill_blank_args, parse_af_token
from laddercodec.instructions import from_tags_af
from laddercodec.instructions.copy import BlockCopy, Copy
from laddercodec.instructions.math import Math
from laddercodec.instructions.raw import _decompose_blob, _fields_to_tag_dicts
from laddercodec.operands.unchecked import refusals, unchecked
from tests.sweep_keys import kind_of

AF = 31
SEND = (
    'send(target=ModbusTcpTarget(name="tcp",ip="192.168.1.10",port=502,device_id=1),'
    "remote_start=ModbusAddress(address=0h,register_type=coil),source=C11,sending=C1,"
    "success=C2,error=C3,exception_response=DS100)"
)
EVENT_DRUM = (
    "event_drum(outputs=[C3],events=[C2],pattern=[[1]],current_step=DS1,completion_flag=C1)"
)
TIME_EVENT_DRUM = (
    "time_event_drum(outputs=[C1311,C1312,C1313],presets=[1000,None,500],"
    "events=[None,C1501,C1502],unit=Tms,pattern=[[1,0,0],[0,1,0],[0,0,1]],"
    "current_step=DS1201,accumulator=TD101,completion_flag=C1401)"
)
TIME_DRUM = (
    "time_drum(outputs=[C1],presets=[1000],unit=Tms,pattern=[[1]],current_step=DS1,"
    "accumulator=TD1,completion_flag=C2)"
)
RECEIVE = (
    'receive(target=ModbusRtuTarget(name="rtu",com_port="cpu2",device_id=5),'
    'remote_start="DS1",dest=DS1..DS5,receiving=C1,success=C2,error=C3,'
    "exception_response=DS100)"
)
TIMED = "timed(C1,on_acc=TD18,on_preset=1000,unit=Tms)"
TIMING = ("on_acc", "on_preset", "off_acc", "off_preset", "unit")

#: Each case is a token with a blank argument and the fields that the read refuses as missing.
BLANKS = [
    ("out()", ["Coil.operand"]),
    ("out( )", ["Coil.operand"]),
    ("latch(,oneshot=0)", ["Coil.operand"]),
    ("out(,oneshot=1)", ["Coil.operand"]),
    ("reset()", ["Coil.operand"]),
    ("toggle()", ["OutVariant.operand"]),
    ("timed(,on_acc=TD18,on_preset=1000,unit=Tms)", ["OutVariant.operand"]),
    (
        "flasher(,on_acc=TD12,on_preset=500,off_acc=TD13,off_preset=250,unit=Tms)",
        ["OutVariant.operand"],
    ),
    ("timed(C1,on_acc=,on_preset=1000,unit=Tms)", ["OutVariant.on_acc"]),
    ("on_delay(,TD1,preset=1,unit=Tms)", ["Timer.done"]),
    ("on_delay(T1,TD1,preset=,unit=Tms)", ["Timer.preset"]),
    ("count_up(CT1,,preset=1)", ["Counter.accumulator"]),
    ("count_up(CT1,CTD1,preset=)", ["Counter.preset"]),
    ("call()", ["Call.subroutine"]),
    ("for()", ["ForLoop.count"]),
    ("for(,oneshot=1)", ["ForLoop.count"]),
    ("shift()", ["Shift.start_bit", "Shift.end_bit"]),
    ("blockcopy(,DS40..DS43)", ["BlockCopy.source_start", "BlockCopy.source_end"]),
    ("blockcopy(DS1..DS4,)", ["BlockCopy.dest_start", "BlockCopy.dest_end"]),
    # write_csv writes a range whose ends are blank as `..`, and one whose start or end is
    # blank as `..END` or `START..`.
    ("shift(..)", ["Shift.start_bit", "Shift.end_bit"]),
    ("blockcopy(..,DS40..DS43)", ["BlockCopy.source_start", "BlockCopy.source_end"]),
    ("blockcopy(..DS4,DS40..DS43)", ["BlockCopy.source_start"]),
    ("blockcopy(DS1..DS4,DS40..)", ["BlockCopy.dest_end"]),
    ("out(Y001..)", ["Coil.range_end"]),
    ("pack_bits(,DS1)", ["Pack.source_start", "Pack.source_end"]),
    ("fill(,DS1..DS4)", ["Fill.value"]),
    ("copy(DS1,)", ["Copy.dest"]),
    ("search(DS72..DS81 == DS71,result=,found=C81)", ["Search.result"]),
    ("search(DS72..DS81 == DS71,result=DS82,found=)", ["Search.found"]),
    (SEND.replace("source=C11", "source="), ["Send.source"]),
    (SEND.replace('ip="192.168.1.10"', "ip="), ["ModbusTcpTarget.ip"]),
    (EVENT_DRUM.replace("current_step=DS1", "current_step="), ["Drum.current_step"]),
]

#: Tokens that are malformed in another way, whether or not an argument is blank, each with
#: the pattern of its error message. Each raises a syntax error that names no field.
SYNTAX = [
    # Without a closing paren it is not a call.
    ("out(C1", r"Could not read 'out\(C1' as an instruction"),
    ("bogus()", r"Could not read 'bogus\(\)' as an instruction"),
    ("on_delay(T1,TD1,,preset=1,unit=Tms)", "expects 2 positional args"),  # beyond the arity
    ("on_delay(,TD1)", "missing preset or unit"),
    ("count_up(CT1,CTD1,preset=,)", "Positional arg after keyword arg"),
    ("call(,)", r"Could not read 'call\(,\)' as a Call instruction"),
    ("toggle(C1,on_acc=)", "toggle takes no keyword arguments"),
]


def _cells(af: str) -> list[str]:
    return ["R", "X1", *(["-"] * (len(CONDITION_COLUMNS) - 1)), af]


def _write(path: Path, af: str) -> Path:
    """Write a CSV of two rungs to *path* and return *path*. The second rung's output is *af*.

    If *af* is a ``count_`` or ``event_drum`` token, add a ``.reset()`` row under it."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        writer.writerow(_cells("out(Y001)"))
        writer.writerow(_cells(af))
        if af.startswith(("count_", "event_drum")):
            writer.writerow(["", *_cells(".reset()")[1:]])
    return path


def _read(token: str) -> Any:
    return af_node_to_token(parse_af_token(token))


def _said(errors: tuple[FieldError, ...]) -> list[tuple[object, ...]]:
    return [(e.fields, e.reason, e.click_id, str(e)) for e in errors]


@pytest.mark.parametrize(("token", "fields"), BLANKS)
def test_a_blank_argument_is_its_field_missing(
    tmp_path: Path, token: str, fields: list[str]
) -> None:
    path = _write(tmp_path / "main.csv", token)
    with pytest.raises(FieldError) as raised:
        read_csv(path)
    assert raised.value.field == fields[0]
    assert [e.field for e in raised.value.errors] == fields
    want = CsvLocation(file=path, line=3, rung_line=3, row=0, column=AF)
    for error in raised.value.errors:
        assert error.reason is Reason.MISSING
        assert "is blank" in str(error)  # the same text that a blank field raises in Python
        assert CsvLocation.of(error) == want


@pytest.mark.parametrize(("token", "fields"), BLANKS)
def test_unchecked_keeps_what_the_default_read_raises(token: str, fields: list[str]) -> None:
    with pytest.raises(FieldError) as raised:
        _read(token)
    with unchecked():
        held = _read(token)
    assert _said(refusals(held)) == _said(raised.value.errors)


@pytest.mark.parametrize(("token", "fields"), BLANKS)
def test_unchecked_keeps_it_located(tmp_path: Path, token: str, fields: list[str]) -> None:
    path = _write(tmp_path / "main.csv", token)
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        read_csv(path, unchecked=True)
    [warning] = [w.message for w in record if isinstance(w.message, RefusedFieldWarning)]
    assert [e.field for e in warning.errors] == fields
    for error in warning.errors:
        assert error.reason is Reason.MISSING
        assert CsvLocation.of(error) == CsvLocation(
            file=path, line=3, rung_line=3, row=0, column=AF
        )


def _read_unchecked(path: Path) -> list[Rung]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RefusedFieldWarning)
        return read_csv(path, unchecked=True)


@pytest.mark.parametrize(("token", "fields"), BLANKS)
def test_write_csv_writes_it_back(tmp_path: Path, token: str, fields: list[str]) -> None:
    """An instruction read unchecked with a blank field writes a CSV that reads back the same."""
    rungs = _read_unchecked(_write(tmp_path / "main.csv", token))
    written = tmp_path / "written.csv"
    write_csv(written, rungs)
    assert _read_unchecked(written) == rungs


@pytest.mark.parametrize(("token", "match"), SYNTAX)
def test_a_token_broken_otherwise_stays_a_syntax_error(token: str, match: str) -> None:
    with pytest.raises(ValueError, match=match) as raised:
        _read(token)
    assert getattr(raised.value, "field", None) is None


def test_fill_blank_args() -> None:
    def fill(i: int) -> str:
        return f"<{i}>"

    assert fill_blank_args("out()", fill) == "out(<0>)"
    assert fill_blank_args("out(C1)", fill) is None
    assert fill_blank_args("copy(..,DS1)", fill) is None  # `..` is a value, not a blank
    assert fill_blank_args("blockcopy(..,DS1..DS4)", fill, ranges=True) == (
        "blockcopy(<0>..<0>,DS1..DS4)"
    )
    assert fill_blank_args("blockcopy(..DS4,DS1..)", fill, ranges=True) == (
        "blockcopy(<0>..DS4,DS1..<1>)"
    )
    assert fill_blank_args("blockcopy(DS1..DS4,)", fill, ranges=True) == (
        "blockcopy(DS1..DS4,<1>..<1>)"
    )
    assert fill_blank_args("timed(,on_acc=,unit=Tms)", fill) == "timed(<0>,on_acc=<1>,unit=Tms)"
    assert fill_blank_args('send(target=T(ip=),x="")', fill) is None  # nested, and quoted
    assert fill_blank_args("raw(,0000)", fill) is None  # a raw token's arguments are field specs
    assert fill_blank_args("NOP", fill) is None


def _blank(token: str, key: str) -> str:
    """Return *token* with the value of its keyword argument *key* made blank."""
    blanked, count = re.subn(rf"\b{key}=[^,()]*", f"{key}=", token, count=1)
    assert count == 1, (token, key)
    return blanked


#: A CSV token for each field that Python accepts blank. ``ACCEPTS_BLANK`` in
#: ``tests/test_blank_missing.py`` lists those fields, and this dict uses the same keys:
#: (class name, kind, field). Each token reads to the instruction with that field blank.
#: Where the token has no argument for the field, the token leaves the field out. A toggle
#: has none of the five timing fields. A ``timed`` token has no off phase. A drum with no
#: ``.jump()`` row has no jump target.
CSV_BLANKS: dict[tuple[str, str | None, str], str] = {
    ("Drum", "event_drum", "accumulator"): EVENT_DRUM[:-1] + ",accumulator=)",
    ("Drum", "event_drum", "unit"): EVENT_DRUM[:-1] + ",unit=)",
    ("Drum", "time_event_drum", "events"): TIME_EVENT_DRUM,  # events=[None,...]
    ("Drum", "time_event_drum", "presets"): TIME_EVENT_DRUM,  # presets=[1000,None,500]
    ("Drum", "event_drum, jump off", "jump_step"): EVENT_DRUM,
    ("Drum", "time_drum, jump off", "jump_step"): TIME_DRUM,
    ("Drum", "time_event_drum, jump off", "jump_step"): TIME_EVENT_DRUM,
    ("ModbusRtuTarget", None, "name"): RECEIVE.replace('name="rtu"', 'name=""'),
    ("ModbusTcpTarget", None, "name"): SEND.replace('name="tcp"', 'name=""'),
    **{("OutVariant", "toggle", attr): "toggle(C1)" for attr in TIMING},
    ("OutVariant", "timed", "off_acc"): TIMED,
    ("OutVariant", "timed", "off_preset"): TIMED,
    ("RawInstruction", None, "class_name"): "raw(,0000)",
    **{
        ("Receive", None, attr): _blank(RECEIVE, attr)
        for attr in ("error", "exception_response", "receiving", "success")
    },
    **{
        ("Send", None, attr): _blank(SEND, attr)
        for attr in ("error", "exception_response", "sending", "success")
    },
}


def test_csv_blanks_answer_every_blank_python_accepts() -> None:
    from tests.test_blank_missing import ACCEPTS_BLANK

    assert set(CSV_BLANKS) == ACCEPTS_BLANK


def _holder(inst: Any, cls: str) -> Any:
    """Return *inst*, or the value of one of its fields, whose class is named *cls*."""
    for value in (inst, *(getattr(inst, f.name) for f in dataclasses.fields(inst))):
        if type(value).__name__ == cls:
            return value
    raise AssertionError(f"no {cls} in {inst!r}")


@pytest.mark.parametrize(("key", "token"), list(CSV_BLANKS.items()), ids=str)
def test_a_blank_python_accepts_reads_from_its_csv_token(
    key: tuple[str, str | None, str], token: str
) -> None:
    cls, kind, attr = key
    holder = _holder(_read(token), cls)
    assert kind_of(holder, attr) == kind
    value = getattr(holder, attr)
    assert value == "" or (isinstance(value, tuple) and "" in value), value


#: In a field that takes one value, ``..`` is the value itself, not a blank range. Each case is
#: (token, field, the reason that the default read refuses it with, attribute).
#: ``read_csv(..., unchecked=True)`` keeps ``..`` in the field when the reason is ``address``.
#: It still raises when the reason is ``form``.
DOTS = [
    ("copy(..,DS1)", "Copy.source", Reason.ADDRESS, "source"),
    (TIMED.replace("on_acc=TD18", "on_acc=.."), "OutVariant.on_acc", Reason.ADDRESS, "on_acc"),
    (SEND.replace("error=C3", "error=.."), "Send.error", Reason.ADDRESS, "error"),
    (SEND.replace("source=C11", "source=.."), "Send.source", Reason.FORM, "source"),
    (RECEIVE.replace("dest=DS1..DS5", "dest=.."), "Receive.dest", Reason.FORM, "dest"),
]


@pytest.mark.parametrize(("token", "field", "reason", "attr"), DOTS)
def test_dots_in_a_one_value_field_are_its_value(
    tmp_path: Path, token: str, field: str, reason: Reason, attr: str
) -> None:
    path = _write(tmp_path / "main.csv", token)
    with pytest.raises(FieldError) as raised:
        read_csv(path)
    assert [(e.field, e.reason) for e in raised.value.errors] == [(field, reason)]
    if reason is Reason.FORM:  # no stored instruction holds a malformed range
        with pytest.raises(FieldError) as raised:
            read_csv(path, unchecked=True)
        assert [(e.field, e.reason) for e in raised.value.errors] == [(field, reason)]
        return
    [rung] = _read_unchecked(path)[1:]
    held = rung.instructions[0]
    assert getattr(held, attr) == ".."
    assert [(e.field, e.reason) for e in refusals(held)] == [(field, reason)]


def test_a_range_with_a_blank_end_writes_and_reads_back(tmp_path: Path) -> None:
    with unchecked():
        block = BlockCopy(source_start="", source_end="DS4", dest_start="DS40", dest_end="DS43")
    rung = Rung(
        logical_rows=1,
        conditions=[["-"] * len(CONDITION_COLUMNS)],
        instructions=[block],
        comment_rtf=None,
        comment=None,
    )
    path = tmp_path / "main.csv"
    write_csv(path, [rung])
    [read] = _read_unchecked(path)
    assert read.instructions[0] == block


@pytest.mark.parametrize(
    ("instruction", "attr"),
    [(Copy(source="DS1", dest="DS2"), "source"), (Math("DS2 + 1", "DS1"), "dest")],
)
def test_a_stored_dots_decodes_as_before(instruction: Any, attr: str) -> None:
    """A ``..`` stored in a one-value field decodes as the value ``..``, not as a blank range.

    The decoded instruction holds ``..`` and carries one refusal, with reason ``address``."""
    class_name, type_code, _parts, _extra, stored = _decompose_blob(instruction.build_blob())
    tags, variant_u16, variant_string = _fields_to_tag_dicts(stored)
    [tag] = [tag for tag, value in tags.items() if value == getattr(instruction, attr)]
    edited = tags | {tag: ".."}
    decoded = from_tags_af(class_name, type_code, edited, variant_u16, variant_string)
    assert decoded is not None
    assert getattr(decoded, attr) == ".."
    assert [e.reason for e in refusals(decoded)] == [Reason.ADDRESS]
