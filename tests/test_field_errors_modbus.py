"""Send, Receive, the Modbus targets and address, raw and undecoded report every refusal.

Each class gives every refusal a reason and a field of its own; Send and Receive carry CLICK's
ids where the code records them.  A refusal while a target is built names the target's own
field (``ModbusTcpTarget.port``) and is raised before any Send or Receive exists; the checks
Send and Receive make of their target name ``Receive.target``.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

import laddercodec
from laddercodec import (
    FieldError,
    ModbusAddress,
    ModbusRtuTarget,
    ModbusTcpTarget,
    RawInstruction,
    Reason,
    Receive,
    Send,
    Undecoded,
)
from laddercodec.csv.ast import AfCall
from laddercodec.instructions import undecoded
from laddercodec.instructions.send_receive import parse_af_call

RTU = ModbusRtuTarget(name="r", com_port="cpu2", device_id=1)


def _refusals(build: Any) -> tuple[FieldError, ...]:
    with pytest.raises(FieldError) as caught:
        build()
    assert caught.value.errors[0] is caught.value
    return caught.value.errors


def _shape(errors: tuple[FieldError, ...]) -> list[tuple[str | None, str | None, str | None]]:
    return [(e.field, e.reason, e.click_id) for e in errors]


def send(**kw: Any) -> Send:
    args: dict[str, Any] = dict(
        target=RTU, remote_start="DS1", source="DS1", quantity=1,
        sending="C1", success="C2", error="C3", exception_response="DS100",
    )  # fmt: skip
    return Send(**{**args, **kw})


def receive(**kw: Any) -> Receive:
    args: dict[str, Any] = dict(
        target=RTU, remote_start="DS1", dest="DS1", quantity=1,
        receiving="C1", success="C2", error="C3", exception_response="DS100",
    )  # fmt: skip
    return Receive(**{**args, **kw})


# ---------------------------------------------------------------------------
# Targets and the Modbus address: not instructions, so the suite fixture does not see them
# ---------------------------------------------------------------------------


def test_rtu_target_gives_every_refusal() -> None:
    errors = _refusals(lambda: ModbusRtuTarget(name="r", com_port="usb", device_id=300))
    assert _shape(errors) == [
        ("ModbusRtuTarget.com_port", Reason.CHOICE, None),
        ("ModbusRtuTarget.device_id", Reason.RANGE, None),
    ]


def test_tcp_target_gives_every_refusal() -> None:
    errors = _refusals(
        lambda: ModbusTcpTarget(name="t", ip="1.2.3", port=0, device_id=1.5, com_port="usb")  # type: ignore[arg-type]
    )
    assert _shape(errors) == [
        ("ModbusTcpTarget.com_port", Reason.CHOICE, None),
        ("ModbusTcpTarget.device_id", Reason.FORM, None),
        ("ModbusTcpTarget.ip", Reason.FORM, None),
        ("ModbusTcpTarget.port", Reason.RANGE, None),
    ]


@pytest.mark.parametrize(
    ("device_id", "reason"),
    [
        (-1, Reason.RANGE),
        (248, Reason.RANGE),
        (True, Reason.FORM),
        (1.5, Reason.FORM),
        ("abc", Reason.ADDRESS),
        ("DD1", Reason.BANK),
        ("DS4501", Reason.ADDRESS),
        ("DS0", Reason.ADDRESS),
    ],
)
def test_target_device_id_reasons(device_id: Any, reason: Reason) -> None:
    (error,) = _refusals(lambda: ModbusRtuTarget(name="r", com_port="cpu2", device_id=device_id))
    assert (error.field, error.reason, error.click_id) == (
        "ModbusRtuTarget.device_id",
        reason,
        None,
    )


@pytest.mark.parametrize(
    ("ip", "port", "field", "reason"),
    [
        ("1.2.3", 502, "ip", Reason.FORM),
        ("1.2.3.256", 502, "ip", Reason.RANGE),
        ("1.2.3.4", "502", "port", Reason.FORM),
        ("1.2.3.4", True, "port", Reason.FORM),
        ("1.2.3.4", 65536, "port", Reason.RANGE),
    ],
)
def test_tcp_target_ip_and_port_reasons(ip: str, port: Any, field: str, reason: Reason) -> None:
    (error,) = _refusals(lambda: ModbusTcpTarget(name="t", ip=ip, port=port, device_id=1))
    assert (error.field, error.reason) == (f"ModbusTcpTarget.{field}", reason)


def test_target_slave_id_in_display_form_only() -> None:
    assert ModbusRtuTarget(name="r", com_port="cpu2", device_id="ds01").device_id == "DS1"


def test_modbus_address_gives_every_refusal() -> None:
    errors = _refusals(lambda: ModbusAddress("40x", "register"))
    assert _shape(errors) == [
        ("ModbusAddress.register_type", Reason.CHOICE, None),
        ("ModbusAddress.address", Reason.KIND, None),
    ]


def test_modbus_address_hex_range_is_the_constant_check() -> None:
    (error,) = _refusals(lambda: ModbusAddress("FFFFh", "holding"))
    assert (error.field, error.reason, error.click_id) == (
        "ModbusAddress.address",
        Reason.RANGE,
        None,  # the remote-start field has no id for it; Copy and Math keep OBJ-005
    )


def test_a_refused_target_never_reaches_the_instruction() -> None:
    with pytest.raises(FieldError) as caught:
        send(target=ModbusTcpTarget(name="t", ip="1.2.3.4", port=0, device_id=1))
    assert caught.value.field == "ModbusTcpTarget.port"
    assert caught.value.obj is None


def test_receive_names_its_own_target_field() -> None:
    low = ModbusRtuTarget(name="r", com_port="cpu2", device_id=0)
    (error,) = _refusals(lambda: receive(target=low))
    assert (error.field, error.reason) == ("Receive.target", Reason.RANGE)
    send(target=low)  # a Send starts at slave 0


# ---------------------------------------------------------------------------
# Send and Receive: every refusal, the raised one first
# ---------------------------------------------------------------------------


def test_send_gives_every_refusal() -> None:
    errors = _refusals(
        lambda: send(source="C1", sending="X1", exception_response="C5", word_swap=2)
    )
    assert _shape(errors) == [
        ("Send.source", Reason.BANK, "OBJ-004"),
        ("Send.sending", Reason.BANK, "OBJ-004"),
        ("Send.exception_response", Reason.BANK, "OBJ-004"),
        ("Send.word_swap", Reason.FLAG, None),
    ]
    assert all(isinstance(e.obj, Send) for e in errors)


def test_receive_gives_every_refusal() -> None:
    errors = _refusals(lambda: receive(dest="ZZ1", quantity="2", success="T1", function_code=9))
    assert _shape(errors) == [
        ("Receive.function_code", Reason.CHOICE, None),
        ("Receive.quantity", Reason.FORM, None),
        ("Receive.dest", Reason.ADDRESS, None),
        ("Receive.success", Reason.BANK, "OBJ-004"),
    ]


def test_send_refused_remote_start_still_checks_the_independent_fields() -> None:
    errors = _refusals(lambda: send(remote_start="X1", source="ZZ1", error="QQ9"))
    assert _shape(errors) == [
        ("Send.remote_start", Reason.BANK, "OBJ-004"),
        ("Send.source", Reason.ADDRESS, None),
        ("Send.error", Reason.ADDRESS, None),
    ]


def test_a_field_that_depends_on_a_refused_one_is_not_checked() -> None:
    # The quantity is no number, so no cap or room is read from it.
    assert _shape(_refusals(lambda: send(quantity=None, source="DS4500"))) == [
        ("Send.quantity", Reason.FORM, None)
    ]
    # The function code is refused, so FC05's one-element rule is not applied.
    assert _shape(_refusals(lambda: send(function_code=7, quantity=2))) == [
        ("Send.function_code", Reason.CHOICE, None)
    ]


@pytest.mark.parametrize(
    ("build", "fields", "reason", "click_id"),
    [
        (lambda: send(function_code=16, remote_start="C1", source="C1"), ("function_code", "remote_start"), Reason.CONFLICT, None),
        (lambda: send(function_code=6, quantity=2), ("function_code", "quantity"), Reason.CONFLICT, None),
        (lambda: send(sending="C1", success="C1"), ("success", "sending"), Reason.CONFLICT, "OBJ-014"),
        (lambda: send(remote_start=ModbusAddress("FFFEh", "holding"), source="DD1"), ("remote_start", "source"), Reason.CONFLICT, "OBJ-010"),
    ],
)  # fmt: skip
def test_send_conflicts_name_both_fields(
    build: Any, fields: tuple[str, str], reason: Reason, click_id: str | None
) -> None:
    (error,) = _refusals(build)
    assert error.fields == tuple(f"Send.{f}" for f in fields)
    assert (error.reason, error.click_id) == (reason, click_id)


@pytest.mark.parametrize(
    ("build", "fields", "reason", "click_id"),
    [
        (lambda: receive(function_code=1), ("function_code", "remote_start"), Reason.CONFLICT, None),
        (lambda: receive(remote_start=ModbusAddress("400001"), function_code=1), ("function_code", "remote_start"), Reason.CONFLICT, None),
        (lambda: receive(receiving="C1", success="C1"), ("success", "receiving"), Reason.CONFLICT, None),
        (lambda: receive(remote_start="C1", dest="C1", word_swap=True), ("word_swap", "remote_start"), Reason.CONFLICT, None),
        (lambda: receive(dest="YD1", remote_start="DH1", word_swap=True), ("word_swap", "dest"), Reason.CONFLICT, None),
        (lambda: receive(word_swap=True), ("word_swap", "quantity"), Reason.CONFLICT, None),
    ],
)  # fmt: skip
def test_receive_conflicts_name_both_fields(
    build: Any, fields: tuple[str, str], reason: Reason, click_id: str | None
) -> None:
    (error,) = _refusals(build)
    assert error.fields == tuple(f"Receive.{f}" for f in fields)
    assert (error.reason, error.click_id) == (reason, click_id)


def test_receive_first_refusal_of_a_conflict_is_the_one_a_later_pair_skips() -> None:
    errors = _refusals(lambda: receive(function_code=3, remote_start="C1", dest="C1"))
    assert _shape(errors) == [("Receive.function_code", Reason.CONFLICT, None)]


@pytest.mark.parametrize(
    ("build", "field", "reason", "click_id"),
    [
        (lambda: send(function_code=7), "function_code", Reason.CHOICE, None),
        (lambda: receive(function_code=True), "function_code", Reason.FORM, None),
        (lambda: send(function_code="6"), "function_code", Reason.FORM, None),
        (lambda: send(function_code=1.0), "function_code", Reason.FORM, None),
        (lambda: send(quantity=1.5), "quantity", Reason.FORM, None),
        (lambda: send(quantity=0), "quantity", Reason.RANGE, "OBJ-010"),
        (lambda: send(quantity=124), "quantity", Reason.RANGE, "OBJ-010"),
        (lambda: send(source="DS4500", quantity=2), "quantity", Reason.RANGE, "OBJ-010"),
        (lambda: send(source="X816", remote_start="C1", quantity=2), "quantity", Reason.RANGE, "OBJ-010"),
        (lambda: receive(dest="YD1", remote_start="DH1", quantity=2), "quantity", Reason.RANGE, "OBJ-010"),
        (lambda: receive(dest="TXT1", remote_start="TXT1", quantity=3), "quantity", Reason.RANGE, None),
        (lambda: send(remote_start="XD1"), "remote_start", Reason.BANK, "OBJ-004"),
        (lambda: send(remote_start="DS5000"), "remote_start", Reason.ADDRESS, None),
        (lambda: send(remote_start=ModbusAddress("0h", "input")), "remote_start", Reason.CHOICE, None),
        (lambda: send(remote_start=ModbusAddress("200000")), "remote_start", Reason.RANGE, None),
        (lambda: receive(remote_start=ModbusAddress("200000")), "remote_start", Reason.RANGE, None),
        (lambda: send(remote_start="DS1", source="DD1", function_code=6), "source", Reason.BANK, "OBJ-004"),
        (lambda: receive(dest="X1"), "dest", Reason.BANK, "OBJ-004"),
        (lambda: receive(dest="DS1", remote_start="DD1"), "remote_start", Reason.BANK, "OBJ-004"),
        (lambda: send(success="DS1"), "success", Reason.BANK, "OBJ-004"),
        (lambda: receive(exception_response="C1"), "exception_response", Reason.BANK, "OBJ-004"),
        (lambda: send(word_swap=2), "word_swap", Reason.FLAG, None),
    ],
)  # fmt: skip
def test_send_and_receive_reasons(
    build: Any, field: str, reason: Reason, click_id: str | None
) -> None:
    (error, *_) = _refusals(build)
    cls = "Send" if "send" in build.__code__.co_names else "Receive"
    assert (error.field, error.reason, error.click_id) == (f"{cls}.{field}", reason, click_id)


def test_send_and_receive_refusals_are_all_reasoned() -> None:
    for build in (
        lambda: send(source="C1", sending="X1", word_swap=2),
        lambda: receive(dest="ZZ1", quantity="2", function_code=9),
    ):
        assert all(isinstance(e.reason, Reason) for e in _refusals(build))


# ---------------------------------------------------------------------------
# CSV: a refusal while reading a token
# ---------------------------------------------------------------------------


def _call(name: str, **kwargs: str) -> AfCall:
    target = 'ModbusRtuTarget(name="r",com_port="cpu2",device_id=1)'
    base = {"target": target, "remote_start": '"DS1"'}
    return AfCall(name=name, args=(), known=True, kwargs={**base, **kwargs})


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"source": "DS1..DS2..DS3"}, "Send.source"),
        ({"source": "DS1..X2"}, "Send.source"),
        ({"source": "DS5..DS1"}, "Send.source"),
        ({"source": "DS1", "function_code": "x"}, "Send.function_code"),
    ],
)
def test_csv_range_and_function_code_syntax_is_form(kwargs: dict[str, str], field: str) -> None:
    with pytest.raises(FieldError) as caught:
        parse_af_call(_call("send", **kwargs))
    assert (caught.value.field, caught.value.reason) == (field, Reason.FORM)


def test_csv_target_port_text_is_form() -> None:
    target = 'ModbusTcpTarget(name="t",ip="1.2.3.4",port=abc,device_id=1)'
    with pytest.raises(FieldError) as caught:
        parse_af_call(_call("send", target=target, source="DS1"))
    assert (caught.value.field, caught.value.reason) == ("ModbusTcpTarget.port", Reason.FORM)


# ---------------------------------------------------------------------------
# RawInstruction and Undecoded
# ---------------------------------------------------------------------------


def test_raw_gives_every_refusal() -> None:
    errors = _refusals(
        lambda: RawInstruction(5, "x", 70000, 0, "2")  # type: ignore[arg-type]
    )
    assert _shape(errors) == [
        ("RawInstruction.class_name", Reason.FORM, None),
        ("RawInstruction.blob", Reason.FORM, None),
        ("RawInstruction.part_count", Reason.RANGE, None),
        ("RawInstruction.visual_rows", Reason.RANGE, None),
        ("RawInstruction.sub_rows", Reason.FORM, None),
    ]


def test_raw_part_count_and_rows_reasons() -> None:
    for bad, reason in ((None, Reason.FORM), (True, Reason.FORM), (-1, Reason.RANGE)):
        (error,) = _refusals(lambda: RawInstruction("X", b"", bad))  # noqa: B023
        assert (error.field, error.reason) == ("RawInstruction.part_count", reason)
    for bad, reason in ((1.5, Reason.FORM), (256, Reason.RANGE)):
        (error,) = _refusals(lambda: RawInstruction("X", b"", 1, bad))  # noqa: B023
        assert (error.field, error.reason) == ("RawInstruction.visual_rows", reason)


@pytest.mark.parametrize(
    ("token", "field", "reason"),
    [
        ("raw(Tmr,0x2718,2,rows=x)", "RawInstruction.visual_rows", Reason.FORM),
        ("raw(Tmr,0x2718,2,rows=99)", "RawInstruction.visual_rows", Reason.RANGE),
        ("raw(Tmr,0x2718,2,rows=1,sub=256)", "RawInstruction.sub_rows", Reason.RANGE),
        ("raw(Tmr,0x2718,2,rows=5,pins=2)", "RawInstruction.visual_rows", Reason.FORM),
        ("raw(Tmr,0x2718,1,pins=1)", None, Reason.FORM),
        ("raw(Tmr,0x2718,3,pins=2/1)", None, Reason.FORM),
        ("raw(Tmr,0x2718,2,pins=40)", None, Reason.FORM),
        ("raw(Tmr,0x2718,2,sub=1,rows=1)", None, Reason.FORM),
        ("raw(Tmr,00,pins=1)", None, Reason.FORM),
    ],
)
def test_raw_token_syntax_refusals_have_a_reason(
    token: str, field: str | None, reason: Reason
) -> None:
    with pytest.raises(FieldError) as caught:
        RawInstruction.from_csv_token(token)
    assert (caught.value.field, caught.value.reason) == (field, reason)


def test_undecoded_gives_every_refusal() -> None:
    errors = _refusals(lambda: Undecoded("", -1, "x", 99, "stop"))  # type: ignore[arg-type]
    assert _shape(errors) == [
        ("Undecoded.error", Reason.MISSING, None),
        ("Undecoded.rung", Reason.RANGE, None),
        ("Undecoded.row", Reason.FORM, None),
        ("Undecoded.column", Reason.RANGE, None),
        ("Undecoded.stop", Reason.CHOICE, None),
    ]


@pytest.mark.parametrize(
    ("kwargs", "field", "reason"),
    [
        ({"error": 5}, "error", Reason.FORM),
        ({"error": "a\nb"}, "error", Reason.FORM),
        ({"rung": 1.5}, "rung", Reason.FORM),
        ({"row": -1}, "row", Reason.RANGE),
        ({"column": 32}, "column", Reason.RANGE),
        ({"stop": "halt"}, "stop", Reason.CHOICE),
    ],
)
def test_undecoded_reasons(kwargs: dict[str, Any], field: str, reason: Reason) -> None:
    args: dict[str, Any] = {"error": "why", "rung": 0, **kwargs}
    (error,) = _refusals(lambda: Undecoded(**args))
    assert (error.field, error.reason) == (f"Undecoded.{field}", reason)


@pytest.mark.parametrize(
    ("kwargs", "args", "field", "reason"),
    [
        ({"rung": "x", "stop": "end"}, ['"why"'], "Undecoded.rung", Reason.FORM),
        ({"stop": "end"}, ['"why"'], "Undecoded.rung", Reason.MISSING),
        ({"rung": "1"}, ['"why"'], "Undecoded.stop", Reason.MISSING),
        ({"rung": "1", "stop": "halt"}, ['"why"'], "Undecoded.stop", Reason.CHOICE),
        ({"rung": "1", "stop": "end"}, [], None, Reason.FORM),
        ({"rung": "1", "stop": "end", "extra": "1"}, ['"why"'], None, Reason.FORM),
    ],
)
def test_undecoded_token_refusals_have_a_reason(
    kwargs: dict[str, str], args: list[str], field: str | None, reason: Reason
) -> None:
    with pytest.raises(FieldError) as caught:
        undecoded.parse_af_call(
            AfCall(name="undecoded", args=tuple(args), known=True, kwargs=kwargs)
        )
    assert (caught.value.field, caught.value.reason) == (field, reason)


# ---------------------------------------------------------------------------
# Every refusal written in these modules has a reason
# ---------------------------------------------------------------------------

_MODULES = ["send_receive", "raw", "undecoded", "email", "home", "position", "velocity"]


@pytest.mark.parametrize("name", _MODULES)
def test_every_refusal_written_in_the_module_has_a_reason(name: str) -> None:
    path = Path(laddercodec.__file__).parent / "instructions" / f"{name}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    missing = []
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        func = call.func
        if isinstance(func, ast.Name) and func.id in ("FieldError", "AddressError"):
            if not any(kw.arg == "reason" for kw in call.keywords):
                missing.append(call.lineno)
        elif isinstance(func, ast.Attribute) and func.attr == "refuse":
            reason_given = len(call.args) >= 3 or any(kw.arg == "reason" for kw in call.keywords)
            if not reason_given:
                missing.append(call.lineno)
    assert not missing, f"{name}.py: a refusal without a reason at lines {missing}"


# ---------------------------------------------------------------------------
# A value of the wrong type is form; choice is a wrong member of the right type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [5, None])
def test_a_port_that_is_no_text_is_form(bad: Any) -> None:
    (error,) = _refusals(lambda: ModbusRtuTarget(name="r", com_port=bad, device_id=1))
    assert (error.field, error.reason) == ("ModbusRtuTarget.com_port", Reason.FORM)
    (error,) = _refusals(
        lambda: ModbusTcpTarget(name="t", ip="1.2.3.4", port=1, device_id=1, com_port=bad)
    )
    assert (error.field, error.reason) == ("ModbusTcpTarget.com_port", Reason.FORM)


def test_a_register_type_that_is_no_text_is_form() -> None:
    (error,) = _refusals(lambda: ModbusAddress("0h", 3))  # type: ignore[arg-type]
    assert (error.field, error.reason) == ("ModbusAddress.register_type", Reason.FORM)


def test_an_undecoded_stop_that_is_no_text_is_form() -> None:
    (error,) = _refusals(lambda: Undecoded("why", 0, stop=3))  # type: ignore[arg-type]
    assert (error.field, error.reason) == ("Undecoded.stop", Reason.FORM)


# ---------------------------------------------------------------------------
# A refused start still has its count checked against every kind
# ---------------------------------------------------------------------------


def test_a_count_no_start_could_take_is_refused_beside_a_refused_address() -> None:
    assert _shape(_refusals(lambda: send(remote_start="bad", quantity=0))) == [
        ("Send.remote_start", Reason.ADDRESS, None),
        ("Send.quantity", Reason.RANGE, "OBJ-010"),
    ]
    assert _shape(_refusals(lambda: receive(dest="bad", quantity=2001))) == [
        ("Receive.dest", Reason.ADDRESS, None),
        ("Receive.quantity", Reason.RANGE, "OBJ-010"),
    ]
    # Registers cap lower, and a count either kind takes is left to the start.
    assert _shape(_refusals(lambda: send(source="bad", quantity=124))) == [
        ("Send.source", Reason.ADDRESS, None),
        ("Send.quantity", Reason.RANGE, "OBJ-010"),
    ]
    assert _shape(_refusals(lambda: send(remote_start="bad", quantity=124))) == [
        ("Send.remote_start", Reason.ADDRESS, None)
    ]


# ---------------------------------------------------------------------------
# Token syntax: no field, the reason form
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    ["nope", "raw(Tmr)", "raw(Tmr,zz)", "raw(Tmr,0x2718,x)", "raw(Tmr,0x2718,2,zz)"],
)
def test_raw_token_that_does_not_parse_is_form(token: str) -> None:
    with pytest.raises(FieldError) as caught:
        RawInstruction.from_csv_token(token)
    assert (caught.value.field, caught.value.reason) == (None, Reason.FORM)


def test_send_receive_token_that_does_not_parse_is_form() -> None:
    from laddercodec.instructions.send_receive import _parse_target

    for text in ("nonsense", 'Unknown(name="x")'):
        with pytest.raises(FieldError) as caught:
            _parse_target(text)
        assert (caught.value.field, caught.value.reason) == (None, Reason.FORM)
    with pytest.raises(FieldError) as caught:
        parse_af_call(_call("poll"))
    assert (caught.value.field, caught.value.reason) == (None, Reason.FORM)
