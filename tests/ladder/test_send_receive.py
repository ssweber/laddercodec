"""Tests for laddercodec.instructions.send_receive: ports and slave IDs.

The protocol mode (0x220C), slave-ID fields (0x320E/0x60B2/0x223A) and func code
(0x3218) follow CLICK's InstCtl_SD / InstCtl_RD and v4_captures/sweep_comm.bin.
"""

from __future__ import annotations

import pytest

from laddercodec.csv.ast import AfCall
from laddercodec.csv.token_parser import parse_af_token
from laddercodec.instructions.raw import _decompose_blob
from laddercodec.instructions.send_receive import (
    ModbusRtuTarget,
    ModbusTcpTarget,
    Receive,
    Send,
    from_tags,
    parse_af_call,
)

_TCP = 'ModbusTcpTarget(name="tcp",ip="192.168.1.20",port=502,device_id={id}{port})'
_RTU = 'ModbusRtuTarget(name="rtu",com_port="{port}",device_id={id})'


def _parse(token: str) -> Receive | Send:
    node = parse_af_token(token)
    assert isinstance(node, AfCall)
    return parse_af_call(node)


def _send(target: str) -> str:
    return f'send(target={target},remote_start="DS1",source=DS2401)'


def _receive(target: str) -> str:
    return f'receive(target={target},remote_start="DS1",dest=DS2411)'


def _fields(instr: Receive | Send) -> dict[int, str]:
    return {tag: value for tag, _s, value in _decompose_blob(instr.build_blob())[4]}


@pytest.mark.parametrize(
    ("token", "func_code", "mode", "slave"),
    [
        (_send(_TCP.format(id=1, port="")), "9736", "2", ("1", "1", "0")),
        (_send(_TCP.format(id=1, port=',com_port="wlan"')), "9736", "3", ("1", "1", "0")),
        (_send(_TCP.format(id="DS2420", port="")), "9752", "2", ("1", "DS2420", "1")),
        (_send(_RTU.format(port="cpu2", id=7)), "9731", "0", ("7", "7", "0")),
        (_send(_RTU.format(port="cpu3", id="DS2420")), "9751", "1", ("1", "DS2420", "1")),
        (_receive(_TCP.format(id=1, port=',com_port="wlan"')), "9735", "3", ("1", "1", "0")),
        (_receive(_TCP.format(id="DS5", port="")), "9750", "2", ("1", "DS5", "1")),
        (_receive(_RTU.format(port="cpu3", id=2)), "9728", "1", ("2", "2", "0")),
        (_receive(_RTU.format(port="slot1_2", id="DS5")), "9749", "7", ("1", "DS5", "1")),
    ],
)
def test_port_and_slave_id_fields(
    token: str, func_code: str, mode: str, slave: tuple[str, str, str]
) -> None:
    instr = _parse(token)
    fields = _fields(instr)
    assert fields[0x3218] == func_code
    assert fields[0x220C] == mode
    assert (fields[0x320E], fields[0x60B2], fields[0x223A]) == slave
    assert instr.to_csv() == token
    class_name, type_code = ("SD", 0x2729) if isinstance(instr, Send) else ("RD", 0x2728)
    assert from_tags(class_name, type_code, fields) == instr


@pytest.mark.parametrize("device_id", ["DD1", "DH1", "C1", "DS0", "DS4501", "ds0"])
def test_slave_id_address_must_be_ds(device_id: str) -> None:
    """CLICK's Slave ID box takes a number or a DS address only."""
    with pytest.raises(ValueError, match="device_id"):
        ModbusRtuTarget(name="rtu", com_port="cpu2", device_id=device_id)
    with pytest.raises(ValueError, match="device_id"):
        _parse(_send(_TCP.format(id=device_id, port="")))


def test_ports_belong_to_their_target() -> None:
    with pytest.raises(ValueError, match="com_port"):
        ModbusRtuTarget(name="rtu", com_port="wlan", device_id=1)
    with pytest.raises(ValueError, match="com_port"):
        ModbusTcpTarget(name="tcp", ip="1.2.3.4", port=502, device_id=1, com_port="cpu2")


@pytest.mark.parametrize(
    ("tag", "value"),
    [
        (0x220C, "8"),  # no such port
        (0x3218, "9733"),  # ASCII static-message Send
        (0x60B2, "DD1"),  # address slave ID the dialog refuses
    ],
)
def test_unmodelled_blob_decodes_as_raw(tag: int, value: str) -> None:
    """A blob we can't represent isn't decoded as a different instruction."""
    send = _parse(_send(_RTU.format(port="cpu2", id="DS1")))
    fields = _fields(send)
    fields[tag] = value
    assert from_tags("SD", 0x2729, fields) is None
