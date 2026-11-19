"""Odd input raises a `FieldError`, never a plain Python exception.

The tests cover two kinds of input. One is a field of the wrong type, such as `Contact(5)`.
The other is a number of more than 4300 digits, which `int()` refuses to convert. A long
number gets the refusal that a number of the same field that is merely too large gets.
"""

from __future__ import annotations

import csv
import warnings
from collections.abc import Callable
from pathlib import Path

import pytest

from laddercodec import (
    CSV_HEADER,
    Coil,
    CompareContact,
    Contact,
    Counter,
    FieldError,
    Math,
    Reason,
    Search,
    Shift,
    Timer,
    UndecodedCommentWarning,
    read_csv,
)
from laddercodec.instructions.call import Call
from laddercodec.instructions.copy import BlockCopy, Copy, Fill, Pack, Unpack
from laddercodec.instructions.drum import Drum
from laddercodec.instructions.forloop import ForLoop
from laddercodec.instructions.out_variant import OutVariant
from laddercodec.instructions.raw import RawInstruction
from laddercodec.instructions.send_receive import (
    ModbusAddress,
    ModbusRtuTarget,
    ModbusTcpTarget,
    Receive,
    Send,
)
from laddercodec.operands.message import parts_of, shown
from laddercodec.undecoded import read_comment, warn_comments

_TCP = ModbusTcpTarget(name="plc", ip="192.168.0.1", port=502, device_id=1)


def _send(**changes: object) -> Send:
    fields: dict[str, object] = {
        "target": _TCP,
        "remote_start": "DS1",
        "source": "DS2",
        "quantity": 1,
        "sending": "C1",
        "success": "C2",
        "error": "C3",
        "exception_response": "DS4",
    }
    return Send(**{**fields, **changes})  # type: ignore[arg-type]


def _receive(**changes: object) -> Receive:
    fields: dict[str, object] = {
        "target": _TCP,
        "remote_start": "DS1",
        "dest": "DS2",
        "quantity": 1,
        "receiving": "C1",
        "success": "C2",
        "error": "C3",
        "exception_response": "DS4",
    }
    return Receive(**{**fields, **changes})  # type: ignore[arg-type]


def _drum(**changes: object) -> Drum:
    fields: dict[str, object] = {
        "outputs": ("Y001",),
        "events": ("X001",),
        "pattern": ((1,),),
        "current_step": "DS1",
        "completion_flag": "C1",
    }
    return Drum("event_drum", **{**fields, **changes})  # type: ignore[arg-type]


def _time_drum(**changes: object) -> Drum:
    fields: dict[str, object] = {
        "outputs": ("Y001",),
        "presets": ("100",),
        "pattern": ((1,),),
        "current_step": "DS1",
        "completion_flag": "C1",
        "accumulator": "TD1",
        "unit": "Tms",
    }
    return Drum("time_drum", **{**fields, **changes})  # type: ignore[arg-type]


def _case(
    id: str,
    build: Callable[[object], object],
    bad: object,
    good: object,
    message: str,
    field: str,
    code: str = "not-an-address",
    reason: Reason = Reason.ADDRESS,
):
    """Return a case: ``build(bad)`` raises ``message``, and ``build(good)`` builds.

    ``good`` is a value of the type that the message asks for."""
    return pytest.param(build, bad, good, message, code, reason, field, id=id)


_WRONG_TYPES = [
    _case(
        "contact-int",
        Contact,
        5,
        "X001",
        "Contact.operand: 5 is an int, not text. Pass the address as a str.",
        "Contact.operand",
    ),
    _case(
        "contact-bytes",
        Contact,
        b"X1",
        "X001",
        "Contact.operand: b'X1' is bytes, not text. Pass the address as a str.",
        "Contact.operand",
    ),
    _case(
        "coil-none",
        Coil,
        None,
        "Y001",
        "Coil.operand: None is not text. Pass the address as a str.",
        "Coil.operand",
    ),
    _case(
        "coil-list",
        Coil,
        ["X1"],
        "Y001",
        "Coil.operand: ['X1'] is a list, not text. Pass the address as a str.",
        "Coil.operand",
    ),
    _case(
        "coil-range-end",
        lambda v: Coil("Y001", range_end=v),
        5,
        "Y002",
        "Coil.range_end: 5 is an int, not text. Pass the address as a str.",
        "Coil.range_end",
    ),
    _case(
        "compare-left",
        lambda v: CompareContact("==", v, "100"),
        5,
        "DS1",
        "CompareContact.left: 5 is an int, not text. Pass the value as a str.",
        "CompareContact.left",
    ),
    _case(
        "compare-right",
        lambda v: CompareContact("==", "DS1", v),
        5,
        "100",
        "CompareContact.right: 5 is an int, not text. Pass the value as a str.",
        "CompareContact.right",
    ),
    _case(
        "copy-source",
        lambda v: Copy(v, "DS2"),
        1.5,
        "DS1",
        "Copy.source: 1.5 is a float, not text. Pass the value as a str.",
        "Copy.source",
    ),
    _case(
        "copy-dest",
        lambda v: Copy("DS1", v),
        1.5,
        "DS2",
        "Copy.dest: 1.5 is a float, not text. Pass the address as a str.",
        "Copy.dest",
    ),
    _case(
        "block-copy-dest-start",
        lambda v: BlockCopy("DS1", "DS3", v, "DS13"),
        5,
        "DS11",
        "BlockCopy.dest_start: 5 is an int, not text. Pass the address as a str.",
        "BlockCopy.dest_start",
    ),
    _case(
        "fill-value",
        lambda v: Fill(v, "DS1", "DS3"),
        5,
        "0",
        "Fill.value: 5 is an int, not text. Pass the value as a str.",
        "Fill.value",
    ),
    _case(
        "pack-dest",
        lambda v: Pack("C1", "C16", v),
        None,
        "DH1",
        "Pack.dest: None is not text. Pass the address as a str.",
        "Pack.dest",
    ),
    _case(
        "unpack-source",
        lambda v: Unpack(v, "C1", "C16"),
        b"DS1",
        "DH1",
        "Unpack.source: b'DS1' is bytes, not text. Pass the address as a str.",
        "Unpack.source",
    ),
    _case(
        "math-dest",
        lambda v: Math("DS1+1", v),
        5,
        "DS1",
        "Math.dest: 5 is an int, not text. Pass the address as a str.",
        "Math.dest",
    ),
    _case(
        "math-expression",
        lambda v: Math(v, "DS2"),
        5,
        "DS1 + 1",
        "Math.expression: 5 is an int, not text. Pass the formula as a str.",
        "Math.expression",
        "math-invalid-token",
        Reason.FORM,
    ),
    _case(
        "search-result",
        lambda v: Search("DS1", "DS5", "5", v, "C1", "=="),
        5,
        "DS11",
        "Search.result: 5 is an int, not text. Pass the address as a str.",
        "Search.result",
    ),
    _case(
        "shift-start",
        lambda v: Shift(v, "C8"),
        5,
        "C1",
        "Shift.start_bit: 5 is an int, not text. Pass the address as a str.",
        "Shift.start_bit",
    ),
    _case(
        "timer-preset",
        lambda v: Timer("on_delay", "T1", "TD1", v, unit="Tms"),
        None,
        "100",
        "Timer.preset: None is not text. Pass the value as a str.",
        "Timer.preset",
    ),
    _case(
        "counter-done",
        lambda v: Counter("count_up", v, "CTD1", "10"),
        5,
        "CT1",
        "Counter.done: 5 is an int, not text. Pass the address as a str.",
        "Counter.done",
    ),
    _case(
        "out-variant-operand",
        lambda v: OutVariant("timed", v, on_acc="TD1", on_preset="10", unit="Ts"),
        5,
        "Y001",
        "OutVariant.operand: 5 is an int, not text. Pass the address as a str.",
        "OutVariant.operand",
    ),
    _case(
        "out-variant-acc",
        lambda v: OutVariant("timed", "Y001", on_acc=v, on_preset="10", unit="Ts"),
        5,
        "TD1",
        "OutVariant.on_acc: 5 is an int, not text. Pass the address as a str.",
        "OutVariant.on_acc",
    ),
    _case(
        "for-count",
        ForLoop,
        5,
        "10",
        "ForLoop.count: 5 is an int, not text. Pass the count as a str.",
        "ForLoop.count",
    ),
    _case(
        "call-subroutine",
        Call,
        5,
        "Pump",
        "Call.subroutine: 5 is an int, not text. Pass the name as a str.",
        "Call.subroutine",
        "invalid-subroutine-name",
        Reason.FORM,
    ),
    _case(
        "drum-outputs-not-a-list",
        lambda v: _drum(outputs=v),
        5,
        ("Y001",),
        "Drum.outputs: 5 is an int, not a list. Pass a list of str.",
        "Drum.outputs",
        reason=Reason.FORM,
    ),
    _case(
        "drum-events-item",
        lambda v: _drum(events=(v,)),
        5,
        "X001",
        "Drum.events[0]: 5 is an int, not text. Pass each item as a str.",
        "Drum.events[0]",
    ),
    _case(
        "drum-presets-item",
        lambda v: _time_drum(presets=(v,)),
        5,
        "100",
        "Drum.presets[0]: 5 is an int, not text. Pass each item as a str.",
        "Drum.presets[0]",
    ),
    _case(
        "drum-current-step",
        lambda v: _drum(current_step=v),
        5,
        "DS1",
        "Drum.current_step: 5 is an int, not text. Pass the address as a str.",
        "Drum.current_step",
    ),
    _case(
        "modbus-address",
        ModbusAddress,
        5,
        "400001",
        "ModbusAddress.address: 5 is an int, not text. Pass the MODBUS address as a str.",
        "ModbusAddress.address",
        reason=Reason.KIND,
    ),
    _case(
        "send-target",
        lambda v: _send(target=v),
        5,
        ModbusTcpTarget(name="plc", ip="192.168.1.10", port=502, device_id=1),
        "Send.target: 5 is an int, not a Modbus target. Pass a ModbusTcpTarget or ModbusRtuTarget.",
        "Send.target",
        "invalid-modbus-target",
        Reason.FORM,
    ),
    _case(
        "receive-remote-start",
        lambda v: _receive(remote_start=v),
        None,
        "DS1",
        "Receive.remote_start: None is not text or a ModbusAddress. "
        "Pass the address as a str, or a ModbusAddress.",
        "Receive.remote_start",
    ),
    _case(
        "send-source",
        lambda v: _send(source=v),
        5,
        "DS1",
        "Send source: 5 is an int, not text. Pass the address as a str.",
        "Send.source",
    ),
    _case(
        "receive-dest",
        lambda v: _receive(dest=v),
        1.5,
        "DS1",
        "Receive dest: 1.5 is a float, not text. Pass the address as a str.",
        "Receive.dest",
    ),
    _case(
        "send-status",
        lambda v: _send(sending=v),
        5,
        "C1",
        "Send sending: 5 is an int, not text. Pass the address as a str.",
        "Send.sending",
    ),
    _case(
        "copy-termination-code",
        lambda v: Copy("DS1", "TXT1", convert="to_text", termination_code=v),
        5,
        "$0D",
        "Copy.termination_code: 5 is an int, not text. Pass the character code as a str.",
        "Copy.termination_code",
        "invalid-char-code",
        Reason.FORM,
    ),
]


@pytest.mark.parametrize(
    ("build", "bad", "good", "message", "code", "reason", "field"), _WRONG_TYPES
)
def test_a_field_of_the_wrong_type_is_a_field_error(
    build, bad, good, message, code, reason, field
) -> None:
    with pytest.raises(FieldError) as raised:
        build(bad)
    error = raised.value
    assert (str(error), error.code, error.reason, error.field) == (message, code, reason, field)
    assert parts_of(error) is not None
    build(good)  # a value of that type builds


def test_a_later_wrong_type_field_is_among_the_errors_of_an_earlier_refusal() -> None:
    with pytest.raises(FieldError) as raised:
        Contact(7, immediate=5)  # type: ignore[arg-type]
    error = raised.value
    assert str(error) == "Contact.immediate: 5 is not True, False, 1 or 0"
    assert [(e.field, e.code) for e in error.errors] == [
        ("Contact.immediate", "not-a-flag"),
        ("Contact.operand", "not-an-address"),
    ]


def test_a_remote_start_of_the_wrong_type_is_refused_after_the_function_code() -> None:
    with pytest.raises(FieldError) as raised:
        _send(remote_start=None, function_code=99)
    error = raised.value
    assert str(error) == "Send.function_code: 99 is not one of 5, 6, 15, 16"
    assert [e.field for e in error.errors] == ["Send.function_code", "Send.remote_start"]


def test_a_target_of_the_wrong_type_is_refused_before_the_function_code() -> None:
    with pytest.raises(FieldError) as raised:
        _receive(target=None, function_code=99)
    error = raised.value
    assert error.field == "Receive.target"
    assert [e.field for e in error.errors] == ["Receive.target", "Receive.function_code"]


class _BadRepr:
    def __repr__(self) -> str:
        raise RuntimeError("repr fails")


def test_a_value_whose_repr_raises_is_named_by_its_default_repr() -> None:
    value = _BadRepr()
    with pytest.raises(FieldError) as raised:
        _send(source=value)
    assert str(raised.value) == (
        f"Send source: {object.__repr__(value)} is a _BadRepr, not text. Pass the address as a str."
    )


def test_a_long_value_is_named_short() -> None:
    with pytest.raises(FieldError) as raised:
        Contact(list(range(200_000)))  # type: ignore[arg-type]
    assert (
        str(raised.value)
        == "Contact.operand: [0, 1, 2, 3, 4, 5, ...] is a list, not text. Pass the address as a str."
    )
    assert shown(list(range(10))) == repr(list(range(10)))
    assert len(shown("x" * 300)) < 80


_WRONG_CHOICES = [
    pytest.param(
        lambda: Search("DS1", "DS5", "5", "DS6", "C1", ["=="]),  # type: ignore[arg-type]
        "Search.op: ['=='] is not allowed; it is one of ==, !=, >, >=, <, <=",
        "Search.op",
        id="search-op",
    ),
    pytest.param(
        lambda: OutVariant({}, "Y1"),  # type: ignore[arg-type]
        "OutVariant.kind: {} is not one of toggle, debounce, flasher, timed",
        "OutVariant.kind",
        id="out-variant-kind",
    ),
    pytest.param(
        lambda: Copy("DS1", "DS2", convert=["to_value"]),  # type: ignore[arg-type]
        "Copy.convert: ['to_value'] is not allowed; "
        "it is None, 'to_value', 'to_text', 'to_binary' or 'to_ascii'",
        "Copy.convert",
        id="copy-convert",
    ),
    pytest.param(
        lambda: Pack("C1", "C16", "DS1", kind=[]),  # type: ignore[arg-type]
        "Pack.kind: [] is not allowed; it is 'pack_bits', 'pack_words' or 'pack_text'",
        "Pack.kind",
        id="pack-kind",
    ),
    pytest.param(
        lambda: Math("DS1+1", "DS2", mode={}),  # type: ignore[arg-type]
        "Math.mode: {} is not 'decimal' or 'hex'",
        "Math.mode",
        id="math-mode",
    ),
    pytest.param(
        lambda: ModbusRtuTarget(name="rtu", com_port={}, device_id=1),  # type: ignore[arg-type]
        "ModbusRtuTarget.com_port: must be one of cpu2, cpu3, slot0_1, slot0_2, slot1_1, "
        "slot1_2, got {}",
        "ModbusRtuTarget.com_port",
        id="rtu-com-port",
    ),
    pytest.param(
        lambda: _time_drum(unit=[]),
        "Drum.unit: [] is not one of Tms, Ts, Tm, Th, Td",
        "Drum.unit",
        id="drum-unit",
    ),
]


def test_a_drum_pattern_that_is_not_rows_of_cells_is_refused_as_the_wrong_shape() -> None:
    for pattern in (5, (5,)):
        with pytest.raises(FieldError) as raised:
            Drum(
                "event_drum",
                outputs=("C1",),
                events=("C2",),
                pattern=pattern,  # type: ignore[arg-type]
                current_step="DS1",
                completion_flag="C3",
            )
        error = raised.value
        assert str(error) == f"Drum.pattern: needs 1 steps of 1 cells each, got {pattern!r}"
        assert (error.code, error.reason, error.field) == (
            "drum-pattern-shape",
            Reason.FORM,
            "Drum.pattern",
        )


def test_an_unhashable_out_unit_is_refused_as_an_unsupported_unit() -> None:
    with pytest.raises(FieldError) as raised:
        OutVariant("timed", "Y1", on_acc="TD1", on_preset="100", unit=["Tms"])  # type: ignore[arg-type]
    assert str(raised.value) == "OutVariant.unit: timed does not support unit=['Tms']"
    assert (raised.value.code, raised.value.field) == ("coil-time-unit", "OutVariant.unit")


@pytest.mark.parametrize(("build", "message", "field"), _WRONG_CHOICES)
def test_an_unhashable_choice_is_refused_as_a_wrong_choice(build, message, field) -> None:
    with pytest.raises(FieldError) as raised:
        build()
    assert (str(raised.value), raised.value.field) == (message, field)
    assert raised.value.code == "invalid-choice"


def test_a_blank_formula_that_is_not_text_is_still_blank() -> None:
    with pytest.raises(FieldError) as raised:
        Math({}, "DS1")  # type: ignore[arg-type]
    assert str(raised.value) == "Math.expression: is blank; a Math needs a formula"
    assert raised.value.code == "blank-field"


# ---------------------------------------------------------------------------
# A number too long for int()
# ---------------------------------------------------------------------------

_LONG = "1" * 5000


def _read_af(tmp_path: Path, af: str) -> list:
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        writer.writerow(["R", "X001"] + ["-"] * 30 + [af])
    return read_csv(path)


def _send_token(*, target: str = "", source: str = "DS1", extra: str = "") -> str:
    target = target or 'ModbusTcpTarget(name="plc",ip="192.168.0.1",port=502,device_id=1)'
    return (
        f'send(target={target},remote_start="DS1",{extra}source={source},sending=C1,'
        "success=C2,error=C3,exception_response=DS100)"
    )


def _read_error(tmp_path: Path, af: str) -> FieldError:
    with pytest.raises(FieldError) as raised:
        _read_af(tmp_path, af)
    return raised.value


def test_a_send_range_that_starts_with_too_many_digits_runs_backwards(tmp_path: Path) -> None:
    long = _read_error(tmp_path, _send_token(source=f"DS{_LONG}..DS5"))
    large = _read_error(tmp_path, _send_token(source="DS999999..DS5"))
    assert (long.code, long.reason, long.field) == (
        "range-not-ascending",
        Reason.FORM,
        "Send.source",
    )
    assert (long.code, long.reason, long.field) == (large.code, large.reason, large.field)
    assert str(large).startswith("range 'DS999999..DS5' runs backwards")
    assert str(long).startswith(f"range 'DS{_LONG}..DS5' runs backwards")


def test_a_send_range_that_ends_with_too_many_digits_is_not_an_address(tmp_path: Path) -> None:
    long = _read_error(tmp_path, _send_token(source=f"DS5..DS{_LONG}"))
    large = _read_error(tmp_path, _send_token(source="DS5..DS999999"))
    assert (
        (long.code, long.reason) == (large.code, large.reason) == ("not-an-address", Reason.ADDRESS)
    )
    assert long.field == large.field == "Send.source"


def test_a_target_port_with_too_many_digits_is_out_of_range(tmp_path: Path) -> None:
    target = 'ModbusTcpTarget(name="plc",ip="192.168.0.1",port={},device_id=1)'
    long = _read_error(tmp_path, _send_token(target=target.format(_LONG)))
    large = _read_error(tmp_path, _send_token(target=target.format("999999")))
    assert str(large).startswith("ModbusTcpTarget.port: must be 1-65535, got 999999")
    assert str(long).startswith(f"ModbusTcpTarget.port: must be 1-65535, got {_LONG}")
    assert (long.code, long.reason, long.field) == (
        "invalid-modbus-target",
        Reason.RANGE,
        "ModbusTcpTarget.port",
    )
    assert (long.code, long.reason, long.field) == (large.code, large.reason, large.field)


@pytest.mark.parametrize(
    ("kind", "target", "high"),
    [
        pytest.param(
            "tcp",
            'ModbusTcpTarget(name="plc",ip="192.168.0.1",port=502,device_id={})',
            255,
            id="tcp",
        ),
        pytest.param(
            "rtu",
            'ModbusRtuTarget(name="rtu",com_port="cpu2",device_id={})',
            247,
            id="rtu",
        ),
    ],
)
def test_a_slave_id_with_too_many_digits_is_out_of_range(
    tmp_path: Path, kind: str, target: str, high: int
) -> None:
    field = "ModbusTcpTarget.device_id" if kind == "tcp" else "ModbusRtuTarget.device_id"
    long = _read_error(tmp_path, _send_token(target=target.format(_LONG)))
    large = _read_error(tmp_path, _send_token(target=target.format("999999")))
    assert str(large).startswith(f"{field}: must be 0-{high} or a DS address, got 999999")
    assert str(long).startswith(f"{field}: must be 0-{high} or a DS address, got {_LONG}")
    assert (long.code, long.reason, long.field) == ("invalid-modbus-target", Reason.RANGE, field)
    assert (long.code, long.reason, long.field) == (large.code, large.reason, large.field)


def test_a_doubled_minus_sign_in_a_target_is_refused_as_a_number(tmp_path: Path) -> None:
    target = 'ModbusRtuTarget(name="rtu",com_port="cpu2",device_id=--5)'
    error = _read_error(tmp_path, _send_token(target=target))
    assert str(error).startswith(
        "ModbusRtuTarget.device_id: must be a number or a DS address (DS1..DS4500), got '--5'"
    )
    assert error.code == "invalid-modbus-target"


def test_a_function_code_with_too_many_digits_is_not_a_number(tmp_path: Path) -> None:
    error = _read_error(tmp_path, _send_token(extra=f"function_code={_LONG},"))
    assert str(error).startswith(f"function_code must be a number, got '{_LONG}'")
    assert (error.code, error.reason, error.field) == (
        "invalid-choice",
        Reason.FORM,
        "Send.function_code",
    )


def test_a_raw_part_count_with_too_many_digits_is_out_of_range() -> None:
    with pytest.raises(FieldError) as long:
        RawInstruction.from_csv_token(f"raw(Email,0x1,{_LONG})")
    with pytest.raises(FieldError) as large:
        RawInstruction.from_csv_token("raw(Email,0x1,99999)")
    assert str(large.value) == (
        "raw(Email,...): part count 99999 is not a whole number from 0 to 65535"
    )
    assert str(long.value) == (
        f"raw(Email,...): part count {_LONG} is not a whole number from 0 to 65535"
    )
    assert (long.value.code, long.value.reason) == ("invalid-token", Reason.RANGE)
    assert (long.value.code, long.value.reason) == (large.value.code, large.value.reason)


def test_a_raw_type_marker_past_32_bits_is_out_of_range() -> None:
    marker = "0x1" + "0" * 8  # one past the largest 32-bit value
    with pytest.raises(FieldError) as raised:
        RawInstruction.from_csv_token(f"raw(Email,{marker},1)")
    assert str(raised.value) == (
        f"raw(Email,...): type marker {marker} is not a whole number from 0 to 0x" + "F" * 8
    )
    assert (raised.value.code, raised.value.reason) == ("invalid-token", Reason.RANGE)


def test_a_raw_rows_count_with_too_many_digits_is_out_of_range() -> None:
    with pytest.raises(FieldError) as long:
        RawInstruction.from_csv_token(f"raw(Email,0x1,1,rows={_LONG})")
    with pytest.raises(FieldError) as large:
        RawInstruction.from_csv_token("raw(Email,0x1,1,rows=99999)")
    assert str(large.value) == ("raw(Email,...): rows='99999' is not a whole number from 1 to 32")
    assert str(long.value) == (f"raw(Email,...): rows='{_LONG}' is not a whole number from 1 to 32")
    assert (long.value.code, long.value.reason, long.value.field) == (
        "invalid-raw",
        Reason.RANGE,
        "RawInstruction.rows",
    )


def test_a_raw_array_count_with_too_many_digits_is_an_invalid_field_spec() -> None:
    with pytest.raises(FieldError) as raised:
        RawInstruction.from_csv_token(f"raw(Email,0x1,1,2237[{_LONG}]=0)")
    assert str(raised.value) == f"Invalid field spec: '2237[{_LONG}]=0'"


def test_an_undecoded_rung_number_with_too_many_digits_is_not_a_number(tmp_path: Path) -> None:
    error = _read_error(tmp_path, f'undecoded("why",rung={_LONG},stop=end)')
    assert str(error).startswith(f"Undecoded.rung: '{_LONG}' must be a whole number from 0")
    assert (error.code, error.reason, error.field) == (
        "invalid-undecoded",
        Reason.FORM,
        "Undecoded.rung",
    )


def test_a_33_bit_raw_type_marker_does_not_hide_an_earlier_refusal() -> None:
    """The type marker is checked after the rest of the token is read."""
    marker = f"0x{2**32:X}"
    for rest in ("99999", "1,rows=99", "1,zz", "2,pins=99"):
        with pytest.raises(FieldError) as small:
            RawInstruction.from_csv_token(f"raw(Email,0x1,{rest})")
        with pytest.raises(FieldError) as large:
            RawInstruction.from_csv_token(f"raw(Email,{marker},{rest})")
        heads = [(str(e), e.field, e.code, e.reason) for e in (small.value, large.value)]
        assert heads[0] == heads[1], rest


# ---------------------------------------------------------------------------
# Leading zeros
# ---------------------------------------------------------------------------

_ZEROS = "0" * 5000


def test_a_raw_count_with_many_leading_zeros_reads_as_its_value() -> None:
    padded = RawInstruction.from_csv_token(f"raw(Email,0x1,{_ZEROS}1,rows={_ZEROS}2)")
    assert padded == RawInstruction.from_csv_token("raw(Email,0x1,1,rows=2)")


def test_a_raw_part_count_of_many_leading_zeros_is_zero() -> None:
    padded = RawInstruction.from_csv_token(f"raw(Email,0x1,{_ZEROS})")
    assert padded == RawInstruction.from_csv_token("raw(Email,0x1,0)")


def test_a_long_raw_part_count_is_shown_without_its_leading_zeros() -> None:
    with pytest.raises(FieldError) as raised:
        RawInstruction.from_csv_token(f"raw(Email,0x1,{_ZEROS}{_LONG})")
    assert str(raised.value) == (
        f"raw(Email,...): part count {_LONG} is not a whole number from 0 to 65535"
    )


def test_a_send_token_with_many_leading_zeros_reads_as_its_values(tmp_path: Path) -> None:
    target = 'ModbusTcpTarget(name="plc",ip="192.168.0.1",port={port},device_id={id})'
    padded = _send_token(
        target=target.format(port=_ZEROS + "502", id=_ZEROS + "1"),
        source="DS1..DS5",
        extra=f"function_code={_ZEROS}16,",
    )
    plain = _send_token(
        target=target.format(port="502", id="1"), source="DS1..DS5", extra="function_code=16,"
    )
    assert _read_af(tmp_path, padded) == _read_af(tmp_path, plain)


def test_a_send_range_start_with_many_leading_zeros_is_not_an_address(tmp_path: Path) -> None:
    """A CLICK address has at most five digits, so leading zeros can make it too long."""
    padded = _read_error(tmp_path, _send_token(source=f"DS{_ZEROS}1..DS5"))
    six = _read_error(tmp_path, _send_token(source="DS000001..DS5"))
    assert (padded.code, padded.reason, padded.field) == (six.code, six.reason, six.field)
    assert (six.code, six.field) == ("not-an-address", "Send.source")


def test_an_undecoded_rung_number_with_many_leading_zeros_reads_as_its_value(
    tmp_path: Path,
) -> None:
    padded = _read_af(tmp_path, f'undecoded("why",rung={_ZEROS}3,stop=end)')
    assert padded == _read_af(tmp_path, 'undecoded("why",rung=3,stop=end)')


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


def test_an_rtf_control_number_of_too_many_digits_leaves_the_comment_undecoded() -> None:
    """The rung keeps a recovered comment and an UndecodedCommentWarning."""
    prefix = rb"{\rtf1\ansi\ansicpg1252\deff0 \fs20 "
    for number in (_LONG, _ZEROS):
        failed: list[tuple[int, str]] = []
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            comment = read_comment(prefix + rb"\b" + number.encode() + rb" hi\par }", 0, failed)
            warn_comments(failed)
        assert comment is not None
        assert comment.startswith("UNDECODED comment: ")
        assert comment.endswith("\nhi")
        assert [type(w.message) for w in caught] == [UndecodedCommentWarning]
