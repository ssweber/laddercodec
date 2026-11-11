"""Field rules of Send and Receive: slave ID, TCP target, remote and local addresses, counts.

Limits follow CLICK v4.00 Help topics 180/181 (RTU) and 213/214 (TCP).
"""

from __future__ import annotations

import pytest

from laddercodec import AddressError, FieldError
from laddercodec.csv.ast import AfCall
from laddercodec.csv.token_parser import parse_af_token
from laddercodec.instructions import from_tags_af
from laddercodec.instructions.raw import _decompose_blob
from laddercodec.instructions.send_receive import (
    ModbusAddress,
    ModbusRtuTarget,
    ModbusTcpTarget,
    Receive,
    Send,
    from_tags,
    parse_af_call,
)

RTU = ModbusRtuTarget(name="rtu", com_port="cpu2", device_id=1)
TCP = ModbusTcpTarget(name="tcp", ip="192.168.1.10", port=502, device_id=1)


def send(**kw) -> Send:
    args = {
        "target": RTU,
        "remote_start": "DS1",
        "source": "DS1",
        "quantity": 1,
        "sending": "C1",
        "success": "C2",
        "error": "C3",
        "exception_response": "DS100",
    }
    args.update(kw)
    return Send(**args)


def receive(**kw) -> Receive:
    args = {
        "target": RTU,
        "remote_start": "DS1",
        "dest": "DS1",
        "quantity": 1,
        "receiving": "C1",
        "success": "C2",
        "error": "C3",
        "exception_response": "DS100",
    }
    args.update(kw)
    return Receive(**args)


def rtu(device_id) -> ModbusRtuTarget:
    return ModbusRtuTarget(name="rtu", com_port="cpu2", device_id=device_id)


def tcp(device_id) -> ModbusTcpTarget:
    return ModbusTcpTarget(name="tcp", ip="1.2.3.4", port=502, device_id=device_id)


# --- slave ID ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "target", "ok", "bad"),
    [
        (send, rtu, [0, 1, 247], [-1, 248]),
        (send, tcp, [0, 255], [256]),
        (receive, rtu, [1, 247], [0, 248]),
        (receive, tcp, [0, 255], [256]),
    ],
)
def test_slave_id_ranges(build, target, ok, bad) -> None:
    for device_id in ok:
        build(target=target(device_id))
    for device_id in bad:
        with pytest.raises(FieldError, match="device_id"):
            build(target=target(device_id))


def test_slave_id_ds_address_passes() -> None:
    send(target=rtu("DS2420"))
    receive(target=tcp("DS5"))


# --- TCP target -------------------------------------------------------------


@pytest.mark.parametrize("port", [1, 502, 65535])
def test_tcp_port_ok(port) -> None:
    ModbusTcpTarget(name="t", ip="1.2.3.4", port=port, device_id=1)


@pytest.mark.parametrize("port", [0, 65536, -1])
def test_tcp_port_out_of_range(port) -> None:
    with pytest.raises(FieldError, match="port"):
        ModbusTcpTarget(name="t", ip="1.2.3.4", port=port, device_id=1)


@pytest.mark.parametrize("ip", ["0.0.0.0", "255.255.255.255", "192.168.1.10"])
def test_tcp_ip_ok(ip) -> None:
    ModbusTcpTarget(name="t", ip=ip, port=502, device_id=1)


@pytest.mark.parametrize("ip", ["", "1.2.3", "1.2.3.4.5", "256.1.1.1", "1.2.3.x", "1..3.4"])
def test_tcp_ip_refused(ip) -> None:
    with pytest.raises(FieldError, match="ip"):
        ModbusTcpTarget(name="t", ip=ip, port=502, device_id=1)


# --- register_type and remote address --------------------------------------


@pytest.mark.parametrize("rt", ["coil", "discrete_input", "holding", "input", None])
def test_register_type_names(rt) -> None:
    ModbusAddress(address="0h", register_type=rt)


def test_register_type_unknown_raises_field_error() -> None:
    with pytest.raises(FieldError, match="register_type"):
        ModbusAddress(address="0h", register_type="bogus")


def test_send_cannot_write_discrete_input_or_input() -> None:
    for rt in ("discrete_input", "input"):
        with pytest.raises(FieldError, match="register_type"):
            send(remote_start=ModbusAddress("0h", rt), source="C1")
    send(remote_start=ModbusAddress("0h", "coil"), source="C1")
    send(remote_start=ModbusAddress("0h", "holding"))


@pytest.mark.parametrize("address", ["0h", "FFFEh", "ffeh", "1Ah"])
def test_hex_address_ok(address) -> None:
    ModbusAddress(address=address)


@pytest.mark.parametrize("address", ["FFFFh", "10000h", "h", "xh", "0H", "abc", "", "-1"])
def test_hex_or_984_address_refused(address) -> None:
    with pytest.raises(FieldError, match="address"):
        ModbusAddress(address=address)


@pytest.mark.parametrize("address", ["1", "65535", "400001", "465535"])
def test_send_984_ok(address) -> None:
    bit = int(address) < 100000
    send(remote_start=ModbusAddress(address), source="C1" if bit else "DS1")


@pytest.mark.parametrize(
    "address", ["0", "65536", "100001", "200001", "300001", "465536", "500000"]
)
def test_send_984_outside_banks(address) -> None:
    with pytest.raises(FieldError, match="remote_start"):
        send(remote_start=ModbusAddress(address))


@pytest.mark.parametrize(
    ("address", "dest"),
    [("1", "C1"), ("65535", "C1"), ("100001", "C1"), ("165535", "Y1"), ("300001", "DS1"),
     ("365535", "DS1"), ("400001", "DS1"), ("465535", "DS1")],
)  # fmt: skip
def test_receive_984_ok(address, dest) -> None:
    receive(remote_start=ModbusAddress(address), dest=dest)


@pytest.mark.parametrize("address", ["0", "65536", "99999", "165536", "200001", "365536", "500000"])
def test_receive_984_outside_banks(address) -> None:
    with pytest.raises(FieldError, match="remote_start"):
        receive(remote_start=ModbusAddress(address))


def test_984_bank_decides_local_kind() -> None:
    with pytest.raises(AddressError, match="dest"):
        receive(remote_start=ModbusAddress("100001"), dest="DS1")  # input status needs bits
    with pytest.raises(AddressError, match="dest"):
        receive(remote_start=ModbusAddress("400001"), dest="C1")


# --- CLICK-addressed banks --------------------------------------------------


@pytest.mark.parametrize("remote", ["Y1", "C1"])
def test_send_remote_bits(remote) -> None:
    send(remote_start=remote, source="C1")


@pytest.mark.parametrize("remote", ["X1", "T1", "SC1", "XD0", "DS0"])
def test_send_remote_refused(remote) -> None:
    with pytest.raises(AddressError, match="remote_start"):
        send(remote_start=remote)


def test_send_remote_register_lists() -> None:
    for remote in ("DS1", "DH1", "SD1", "TD1", "TXT1", "YD1"):
        send(remote_start=remote)
    for remote in ("CTD1", "DD1", "DF1"):
        send(remote_start=remote, source="DS1", quantity=2)
    with pytest.raises(AddressError, match="remote_start"):
        send(remote_start="YD1", quantity=2)  # YD is FC06 only


def test_send_local_lists() -> None:
    for source in ("X1", "Y1", "C1", "T1", "CT1", "SC1"):
        send(remote_start="C1", source=source)
    for source in ("DD1", "DF1", "CTD1"):
        send(remote_start="DS1", source=source, quantity=2)
    for source in ("XD0", "YD0u"):
        send(remote_start="DS1", source=source)
    with pytest.raises(AddressError, match="source"):
        send(remote_start="C1", source="DS1")  # bit remote, register local
    with pytest.raises(AddressError, match="source"):
        send(remote_start="DS1", source="C1")
    with pytest.raises(AddressError, match="source"):
        send(remote_start="DS1", source="XD0", quantity=2)  # FC16 has no XD


def test_receive_lists() -> None:
    for remote in ("X1", "Y1", "C1", "T1", "CT1", "SC1"):
        receive(remote_start=remote, dest="C1")
    for remote in ("CTD1", "DS1", "DD1", "DH1", "DF1", "SD1", "TD1", "YD1", "TXT1"):
        receive(remote_start=remote)
    for dest in ("CTD1", "DS1", "DD1", "DH1", "DF1", "SD1", "TD1", "YD1", "TXT1"):
        receive(dest=dest)
    with pytest.raises(AddressError, match="remote_start"):
        receive(remote_start="XD0")
    with pytest.raises(AddressError, match="dest"):
        receive(remote_start="C1", dest="X1")  # inputs can't be written
    with pytest.raises(AddressError, match="dest"):
        receive(remote_start="C1", dest="DS1")
    with pytest.raises(AddressError, match="dest"):
        receive(dest="XD0")


# --- counts -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "kw", "ok", "bad"),
    [
        (send, {"remote_start": "C1", "source": "C1"}, 1968, 1969),
        (send, {"source": "DS1"}, 123, 124),
        (send, {"source": "DD1"}, 61, 62),
        (send, {"source": "DF1"}, 61, 62),
        (send, {"source": "CTD1"}, 61, 62),
        (receive, {"remote_start": "C1", "dest": "C1"}, 2000, 2001),
        (receive, {"dest": "DS1"}, 125, 126),
        (receive, {"dest": "DD1"}, 62, 63),
    ],
)
def test_count_caps(build, kw, ok, bad) -> None:
    build(quantity=ok, **kw)
    with pytest.raises(FieldError, match="quantity"):
        build(quantity=bad, **kw)
    with pytest.raises(FieldError, match="quantity"):
        build(quantity=0, **kw)


def test_dh_counts_as_16_bit() -> None:
    send(source="DH1", quantity=123)


def test_count_must_fit_local_bank() -> None:
    send(source="DS4378", quantity=123)
    with pytest.raises(FieldError, match="runs past DS4500"):
        send(source="DS4379", quantity=123)
    receive(dest="DD938", quantity=62)
    with pytest.raises(FieldError, match="runs past DD1000"):
        receive(dest="DD940", quantity=62)
    with pytest.raises(FieldError, match="runs past C2000"):
        send(remote_start="C1", source="C1999", quantity=3)


def test_count_fits_across_x_modules() -> None:
    send(remote_start="C1", source="X101", quantity=16)
    with pytest.raises(FieldError, match="runs past X816"):
        send(remote_start="C1", source="X815", quantity=3)


# --- status operands --------------------------------------------------------


@pytest.mark.parametrize("name", ["sending", "success", "error"])
def test_status_bits_are_c_bits(name) -> None:
    send(**{name: ""})
    for bad in ("DS1", "Y1", "C2001"):
        with pytest.raises(AddressError, match=name):
            send(**{name: bad})
    key = "receiving" if name == "sending" else name
    for bad in ("DS1", "Y1", "C0"):
        with pytest.raises(AddressError, match=key):
            receive(**{key: bad})


def test_exception_response_is_ds_or_dd() -> None:
    send(exception_response="DD1")
    receive(exception_response="DD1")
    for bad in ("C1", "DH1", "DS4501"):
        with pytest.raises(AddressError, match="exception_response"):
            send(exception_response=bad)
        with pytest.raises(AddressError, match="exception_response"):
            receive(exception_response=bad)


# --- CSV --------------------------------------------------------------------


def _csv(call: str, ref: str, remote: str = "DS1") -> Send | Receive:
    token = (
        f'{call}(target=ModbusRtuTarget(name="r",com_port="cpu2",device_id=1),'
        f'remote_start="{remote}",{ref})'
    )
    node = parse_af_token(token)
    assert isinstance(node, AfCall)
    return parse_af_call(node)


def test_csv_range_counts() -> None:
    assert _csv("send", "source=DS1..DS5").quantity == 5
    assert _csv("receive", "dest=DS7").quantity == 1
    assert _csv("send", "source=DS3..DS3").quantity == 1


@pytest.mark.parametrize(
    "ref", ["source=DS5..DS1", "source=DS1..DD5", "source=DS1..", "source=DS1..5"]
)
def test_csv_range_must_run_forward_in_one_bank(ref) -> None:
    with pytest.raises(FieldError, match="range"):
        _csv("send", ref)


def test_csv_range_error_for_receive() -> None:
    with pytest.raises(FieldError, match="range"):
        _csv("receive", "dest=DS5..DS1")


def test_csv_range_counts_x_points_not_numbers() -> None:
    sent = _csv("send", "source=X001..X101", remote="C1")
    assert sent.quantity == 17
    assert "source=X001..X101" in sent.to_csv()


def test_csv_construction_goes_through_rules() -> None:
    with pytest.raises(FieldError, match="quantity"):
        _csv("send", "source=DS1..DS200")


# --- decode -----------------------------------------------------------------


def _fields(instr: Send | Receive) -> dict[int, str]:
    return {tag: value for tag, _s, value in _decompose_blob(instr.build_blob())[4]}


def test_refused_blob_decodes_as_raw() -> None:
    fields = _fields(receive(quantity=5))
    fields[0x3210] = "200"
    assert from_tags_af("RD", 0x2728, fields) is None
    fields = _fields(send())
    fields[0x6085] = "200001"
    fields[0x320F] = "0"
    assert from_tags_af("SD", 0x2729, fields) is None


@pytest.mark.parametrize("instr", [send(quantity=5), receive(quantity=5)])
def test_valid_instruction_round_trips(instr) -> None:
    cls = "SD" if isinstance(instr, Send) else "RD"
    code = 0x2729 if isinstance(instr, Send) else 0x2728
    assert from_tags(cls, code, _fields(instr)) == instr


@pytest.mark.parametrize(
    ("class_name", "type_code", "build", "enables"),
    [
        ("SD", 0x2729, send, (0x120A, 0x1209, 0x120B, 0x121A)),
        ("RD", 0x2728, receive, (0x120A, 0x1209, 0x120B, 0x121A)),
    ],
)
def test_status_strings_decode_whatever_the_enable_flag(
    class_name, type_code, build, enables
) -> None:
    """CLICK v4 rederives each enable from its string, so Send and Receive ignore the flags."""
    instr = build()
    fields = _fields(instr)
    for tag in enables:
        fields[tag] = "0"
    assert from_tags(class_name, type_code, fields) == instr
