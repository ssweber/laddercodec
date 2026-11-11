"""Field rules of Send and Receive: slave ID, TCP target, remote and local addresses, counts.

Limits follow CLICK v4.00 Help topics 180/181 (RTU) and 213/214 (TCP), and the dialog code
in Inst_SD.dll / Inst_RD.dll (addresses in the tests' docstrings).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from laddercodec import AddressError, FieldError, read_csv
from laddercodec.csv import CSV_HEADER
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


def _read_af(tmp_path: Path, af: str) -> object:
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", "C10"] + ["-"] * 30 + [af])
    return read_csv(path)[0].instructions[0]


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
    for dest in ("DS1", "DD1", "DH1", "DF1", "YD1"):
        receive(remote_start=ModbusAddress("400001"), dest=dest)
    receive(remote_start=ModbusAddress("400001"), dest="TXT1", quantity=2)
    with pytest.raises(AddressError, match="dest"):
        receive(remote_start="C1", dest="X1")  # inputs can't be written
    with pytest.raises(AddressError, match="dest"):
        receive(remote_start="C1", dest="DS1")


@pytest.mark.parametrize("dest", ["XD0", "TD1", "CTD1", "SD1"])
def test_receive_dest_mask_refuses(dest) -> None:
    """RD 0x100071c3: FC03/04 dest mask 0x8bc0 is DS, DD, DH, DF, YD and TXT (OBJ-004)."""
    with pytest.raises(AddressError, match="dest"):
        receive(remote_start=ModbusAddress("400001"), dest=dest)


@pytest.mark.parametrize(
    ("dest", "ok", "bad"),
    [
        ("DS1", ["DS1", "TD1", "SD1"], ["DD1", "CTD1", "DF1", "DH1", "XD0", "YD1", "TXT1"]),
        ("DD1", ["DD1", "CTD1"], ["DS1", "DF1", "DH1", "TXT1"]),
        ("DF1", ["DF1"], ["DS1", "DD1", "DH1"]),
        ("DH1", ["DH1", "XD1", "YD0u"], ["DS1", "DD1", "TXT1"]),
        ("YD1", ["DH1", "XD0", "YD1"], ["DS1", "DF1"]),
    ],
)
def test_receive_click_remote_pairs_with_dest_type(dest, ok, bad) -> None:
    """RD 0x10005019..0x100050a9: a CLICK remote register matches the dest's data type."""
    for remote in ok:
        receive(remote_start=remote, dest=dest)
    for remote in bad:
        with pytest.raises(AddressError, match="remote_start"):
            receive(remote_start=remote, dest=dest)


def test_receive_text_pairs_with_text() -> None:
    receive(remote_start="TXT1", dest="TXT1", quantity=2)
    with pytest.raises(AddressError, match="remote_start"):
        receive(remote_start="DS1", dest="TXT1", quantity=2)


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
        (receive, {"remote_start": "DD1", "dest": "DD1"}, 62, 63),
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
    receive(remote_start="DD1", dest="DD938", quantity=62)
    with pytest.raises(FieldError, match="runs past DD1000"):
        receive(remote_start="DD1", dest="DD940", quantity=62)
    with pytest.raises(FieldError, match="runs past C2000"):
        send(remote_start="C1", source="C1999", quantity=3)


COIL_HEX = ModbusAddress("0h", "coil")


@pytest.mark.parametrize(
    ("remote", "source", "room"),
    [
        # CLICK addressing: the CPU and option slots are one run, an expansion slot its own
        ("C1", "X001", 32),
        ("C1", "X016", 17),
        ("C1", "X021", 16),
        ("C1", "Y036", 1),
        ("C1", "X101", 16),
        ("C1", "X815", 2),
        ("C1990", "X001", 11),  # the room left in C is less
        ("Y001", "X001", 32),
        ("Y101", "X001", 16),  # the higher start number decides
        ("Y005", "X003", 28),
        # MODBUS 984 or hex: the points left through the last slot
        (ModbusAddress("1"), "X001", 160),
        (COIL_HEX, "X021", 144),
        (COIL_HEX, "X101", 128),
        (COIL_HEX, "Y815", 2),
    ],
)
def test_send_x_y_room_counts_by_slot(remote, source, room) -> None:
    """Inst_SD.dll 0x10017d80 (local X/Y case 0x10018501), C room 0x1001853f (Q-C6)."""
    send(remote_start=remote, source=source, quantity=room)
    with pytest.raises(FieldError, match=f"outside 1-{room} "):
        send(remote_start=remote, source=source, quantity=room + 1)


def test_receive_y_room_is_the_points_left() -> None:
    receive(remote_start="C1", dest="Y001", quantity=160)
    receive(remote_start="C1", dest="Y801", quantity=16)
    with pytest.raises(FieldError, match="outside 1-16 "):
        receive(remote_start="C1", dest="Y801", quantity=17)


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


@pytest.mark.parametrize(
    ("ref", "quantity"),
    [("source=X001..X016", 16), ("source=X001..X021", 17), ("source=X001..X036", 32),
     ("source=Y021..Y036", 16), ("source=X101..X116", 16)],
)  # fmt: skip
def test_csv_range_counts_x_points_by_slot(ref, quantity) -> None:
    assert _csv("send", ref, remote="C1").quantity == quantity


def test_csv_x_range_across_slots() -> None:
    """X001..X101 is 33 points: past the 32 a CLICK address allows, inside the 160 of 984."""
    with pytest.raises(FieldError, match="outside 1-32 "):
        _csv("send", "source=X001..X101", remote="C1")
    token = (
        'send(target=ModbusRtuTarget(name="r",com_port="cpu2",device_id=1),'
        "remote_start=ModbusAddress(address=1),source=X001..X101)"
    )
    node = parse_af_token(token)
    assert isinstance(node, AfCall)
    assert parse_af_call(node).quantity == 33


@pytest.mark.parametrize(
    ("source", "quantity", "end"),
    [("X001", 17, "X021"), ("X1", 17, "X21"), ("Y016", 2, "Y021"), ("X001", 32, "X036"),
     ("X815", 2, "X816")],
)  # fmt: skip
def test_x_range_end_counts_by_slot(source, quantity, end) -> None:
    assert f"source={source}..{end}" in send(
        remote_start="C1", source=source, quantity=quantity
    ).to_csv()


def test_csv_range_end_is_an_address() -> None:
    with pytest.raises(AddressError, match="range end"):
        _csv("send", "source=X001..X017", remote="C1")
    with pytest.raises(AddressError, match="range end"):
        _csv("send", "source=DS1..DS4501")


def test_csv_port_not_a_number() -> None:
    token = (
        'send(target=ModbusTcpTarget(name="t",ip="1.2.3.4",port=abc,device_id=1),'
        'remote_start="DS1",source=DS1)'
    )
    node = parse_af_token(token)
    assert isinstance(node, AfCall)
    with pytest.raises(FieldError, match="port"):
        parse_af_call(node)


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


@pytest.mark.parametrize("quantity", [17, 32])
@pytest.mark.parametrize("start", ["X001", "Y001"])
def test_x_y_range_round_trips_through_csv(start, quantity) -> None:
    sent = send(remote_start="C1", source=start, quantity=quantity)
    token = sent.to_csv()
    assert _csv("send", token[token.index("source=") :].rstrip(")"), remote="C1").quantity == (
        quantity
    )
    got = receive(remote_start="C1", dest="Y001", quantity=quantity)
    token = got.to_csv()
    assert _csv("receive", token[token.index("dest=") :].split(",")[0], remote="C1").quantity == (
        quantity
    )


# --- function codes (Inst_SD.dll 0x10006cb1, Inst_RD.dll 0x1000c0db) --------


def _fc_subtype(instr: Send | Receive) -> str:
    return _fields(instr)[0x2211]


@pytest.mark.parametrize(
    ("kw", "fc_subtype"),
    [
        ({"source": "DS1"}, "1"),  # FC06
        ({"source": "XD0"}, "1"),
        ({"source": "YD0u"}, "1"),
        ({"source": "DD1"}, "3"),  # FC16: FC06's mask refuses DD, DF and CTD
        ({"source": "DF1"}, "3"),
        ({"source": "CTD1"}, "3"),
        ({"remote_start": "DD1", "source": "DS1"}, "3"),
        ({"remote_start": ModbusAddress("400001"), "source": "DD1"}, "3"),
        ({"source": "DS1", "quantity": 2}, "3"),
        ({"remote_start": "C1", "source": "C1"}, "0"),  # FC05
        ({"remote_start": "C1", "source": "C1", "quantity": 2}, "2"),  # FC15
    ],
)
def test_send_default_function_code(kw, fc_subtype) -> None:
    sent = send(**kw)
    assert sent.function_code is None
    assert _fc_subtype(sent) == fc_subtype


@pytest.mark.parametrize(
    ("kw", "fc_subtype"),
    [
        ({"source": "DS1", "function_code": 16}, "3"),
        ({"remote_start": "C1", "source": "C1", "function_code": 15}, "2"),
    ],
)
def test_send_one_element_as_block_code(kw, fc_subtype) -> None:
    sent = send(**kw)
    assert _fc_subtype(sent) == fc_subtype
    assert f"function_code={kw['function_code']}" in sent.to_csv()
    assert from_tags("SD", 0x2729, _fields(sent)) == sent


def test_send_function_code_default_is_dropped() -> None:
    assert send(source="DS1", function_code=6) == send(source="DS1")
    assert "function_code" not in send(source="DS1", function_code=6).to_csv()


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"function_code": 3}, "function_code: 3 is not one of 5, 6, 15, 16"),
        ({"function_code": True}, "function_code"),
        ({"function_code": 5}, "FC05 cannot write a register"),
        ({"remote_start": "C1", "source": "C1", "function_code": 16}, "FC16 cannot write a coil"),
        ({"quantity": 2, "function_code": 6}, "FC06 writes one element, not 2"),
        ({"remote_start": "C1", "source": "C1", "quantity": 2, "function_code": 5}, "FC05"),
    ],
)
def test_send_function_code_refused(kw, message) -> None:
    with pytest.raises(FieldError, match=message):
        send(**kw)


@pytest.mark.parametrize(
    ("kw", "field"),
    [
        ({"source": "DD1", "function_code": 6}, "source"),  # FC06 mask 0xdd40
        ({"source": "XD0", "function_code": 16}, "source"),  # FC16 mask 0xf3c0
        ({"source": "YD1", "function_code": 16}, "source"),
        ({"remote_start": "YD1", "source": "DD1"}, "remote_start"),  # DD makes it FC16
        ({"remote_start": "DD1", "source": "XD0"}, "source"),
    ],
)
def test_send_banks_follow_function_code(kw, field) -> None:
    with pytest.raises(AddressError, match=field):
        send(**kw)


@pytest.mark.parametrize(
    ("remote", "dest", "fc", "fc_subtype"),
    [("X001", "C1", 2, "1"), ("C1", "Y001", 1, "0"), ("DS1", "DS1", 4, "3"),
     ("DS1", "DS1", 3, "2")],
)  # fmt: skip
def test_receive_click_address_keeps_its_function_code(remote, dest, fc, fc_subtype) -> None:
    """Q-C4: CLICK writes FC02 and FC04 as picked; a native FC02/FC04 rung round-trips (S9)."""
    got = receive(remote_start=remote, dest=dest, function_code=fc)
    assert _fc_subtype(got) == fc_subtype
    assert from_tags("RD", 0x2728, _fields(got)) == got
    assert ("function_code=" in got.to_csv()) == (fc in (2, 4))


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"function_code": 5}, "function_code: 5 is not one of 1, 2, 3, 4"),
        ({"function_code": 2}, "FC02 cannot read a register"),
        ({"remote_start": "X1", "dest": "C1", "function_code": 3}, "FC03 cannot read a bit"),
        ({"remote_start": ModbusAddress("400001"), "function_code": 4}, "is FC03"),
        ({"remote_start": ModbusAddress("0h", "input"), "function_code": 3}, "is FC04"),
    ],
)
def test_receive_function_code_refused(kw, message) -> None:
    with pytest.raises(FieldError, match=message):
        receive(**kw)


def test_receive_hex_and_984_codes_need_no_function_code() -> None:
    assert receive(remote_start=ModbusAddress("300001"), function_code=4).function_code is None
    got = receive(remote_start=ModbusAddress("0h", "discrete_input"), dest="C1")
    assert _fc_subtype(got) == "1"


def test_function_code_through_read_csv(tmp_path: Path) -> None:
    target = 'ModbusTcpTarget(name="t",ip="1.2.3.4",port=502,device_id=1)'
    got = _read_af(
        tmp_path,
        f'receive(target={target},remote_start="X001",function_code=2,dest=C1..C5)',
    )
    assert isinstance(got, Receive) and got.function_code == 2
    sent = _read_af(tmp_path, f'send(target={target},remote_start="DS1",source=DD1)')
    assert isinstance(sent, Send) and _fc_subtype(sent) == "3"
    with pytest.raises(FieldError, match="function_code must be a number"):
        _read_af(tmp_path, f'send(target={target},remote_start="DS1",source=DS1,function_code=x)')


@pytest.mark.parametrize(
    ("class_name", "type_code", "instr", "fc_subtype"),
    [
        ("SD", 0x2729, send(), "0"),  # FC05 with a register remote
        ("SD", 0x2729, send(), "7"),
        ("RD", 0x2728, receive(), "1"),  # FC02 with a register remote
        ("RD", 0x2728, receive(remote_start=ModbusAddress("400001")), "3"),  # 4xxxxx is FC03
    ],
)
def test_function_code_that_does_not_fit_decodes_as_raw(
    class_name, type_code, instr, fc_subtype
) -> None:
    fields = _fields(instr)
    fields[0x2211] = fc_subtype
    assert from_tags_af(class_name, type_code, fields) is None


# --- Receive counts and Word Swap (Inst_RD.dll, Q-C3) -------------------------


def test_receive_yd_dest_is_one_element() -> None:
    """RD 0x100141ec: a YD dest is capped at 1."""
    receive(remote_start=ModbusAddress("400001"), dest="YD1")
    with pytest.raises(FieldError, match="outside 1-1"):
        receive(remote_start=ModbusAddress("400001"), dest="YD1", quantity=2)


def test_receive_dh_from_xd_or_yd_is_one_element() -> None:
    """RD 0x1001420d: "(1 to 1)" for a DH dest read from a CLICK XD/YD."""
    receive(remote_start="DH1", dest="DH1", quantity=5)
    for remote in ("XD1", "YD1"):
        receive(remote_start=remote, dest="DH1")
        with pytest.raises(FieldError, match="outside 1-1"):
            receive(remote_start=remote, dest="DH1", quantity=2)


@pytest.mark.parametrize("quantity", [1, 3, 125])
def test_receive_text_count_is_even(quantity) -> None:
    """RD 0x10006bab: at least 2 TXT characters, and an even count."""
    with pytest.raises(FieldError, match="even count"):
        receive(remote_start="TXT1", dest="TXT1", quantity=quantity)


def test_receive_text_even_counts() -> None:
    for quantity in (2, 4, 124):
        receive(remote_start="TXT1", dest="TXT1", quantity=quantity)


@pytest.mark.parametrize(
    "kw",
    [
        {"remote_start": "C1", "dest": "C1", "quantity": 2},  # FC01/02: 0x10006b78
        {"remote_start": ModbusAddress("100001"), "dest": "Y001", "quantity": 2},
        {"remote_start": ModbusAddress("400001"), "dest": "YD1"},  # 0x1000686d
        {"remote_start": ModbusAddress("400001"), "dest": "TXT1", "quantity": 4},  # 0x10006bab
        {"remote_start": "DD1", "dest": "DD1", "quantity": 2},  # CLICK DD/DF: 0x10006afa
        {"remote_start": "DF1", "dest": "DF1", "quantity": 2},
        {"remote_start": "XD1", "dest": "DH1"},  # "(1 to 1)": 0x1001420d
    ],
)
def test_receive_word_swap_forced_off(kw) -> None:
    receive(**kw)
    with pytest.raises(FieldError, match="word_swap"):
        receive(word_swap=True, **kw)


@pytest.mark.parametrize(
    "kw",
    [
        {"remote_start": ModbusAddress("400001"), "dest": "DD1", "quantity": 5},  # native
        {"remote_start": ModbusAddress("0h", "holding"), "dest": "DF1", "quantity": 2},
        {"remote_start": "DS1", "dest": "DS1", "quantity": 2},
        {"remote_start": "DH1", "dest": "DH1", "quantity": 2},
        {"remote_start": "DS1", "dest": "DS1"},  # disabled at 1, not forced off
    ],
)
def test_receive_word_swap_allowed(kw) -> None:
    receive(word_swap=True, **kw)


def test_refused_receive_decodes_as_raw() -> None:
    fields = _fields(receive(remote_start="C1", dest="C1", quantity=2))
    fields[0x221C] = "0"  # word swap on a bit Receive
    assert from_tags_af("RD", 0x2728, fields) is None
    fields = _fields(receive(remote_start=ModbusAddress("400001")))
    fields[0x607E] = "TD1"
    assert from_tags_af("RD", 0x2728, fields) is None
    fields = _fields(receive(remote_start="DD1", dest="DD1"))
    fields[0x6085] = "DS1"
    assert from_tags_af("RD", 0x2728, fields) is None


# --- Send status bits and hex start (Inst_SD.dll, Q-C5) -----------------------


@pytest.mark.parametrize(
    "kw",
    [
        {"sending": "C1", "success": "C1", "error": "C3"},
        {"sending": "C1", "success": "C2", "error": "C0001"},
        {"sending": "", "success": "C5", "error": "C5"},
    ],
)
def test_send_status_bit_used_twice(kw) -> None:
    """SD 0x100095f0: one C bit can't serve two status fields (OBJ-014)."""
    with pytest.raises(FieldError, match="already the"):
        send(**kw)


def test_send_status_bit_used_twice_decodes_as_raw() -> None:
    fields = _fields(send())
    fields[0x607B] = "C1"
    assert from_tags_af("SD", 0x2729, fields) is None


@pytest.mark.parametrize("source", ["DD1", "DF1", "CTD1", "TXT1"])
def test_send_32_bit_or_text_hex_start_stops_at_fffd(source) -> None:
    """SD 0x10005511: a 32-bit, float or text source starts at 0h-FFFDh (OBJ-010)."""
    holding = ModbusAddress("FFFDh", "holding")
    send(remote_start=holding, source=source)
    with pytest.raises(FieldError, match="outside 0h-FFFDh"):
        send(remote_start=ModbusAddress("FFFEh", "holding"), source=source)


def test_send_16_bit_hex_start_reaches_fffe() -> None:
    send(remote_start=ModbusAddress("FFFEh", "holding"), source="DS1")


def test_send_dd_hex_count_room() -> None:
    """SD 0x100191c9: a DD source from hex start a has room for min(61, FFFEh - a)."""
    send(remote_start=ModbusAddress("FFFCh", "holding"), source="DD1", quantity=2)
    with pytest.raises(FieldError, match="outside 1-1"):
        send(remote_start=ModbusAddress("FFFDh", "holding"), source="DD1", quantity=2)
    send(remote_start=ModbusAddress("FFC1h", "holding"), source="DD1", quantity=61)
    with pytest.raises(FieldError, match="outside 1-60"):
        send(remote_start=ModbusAddress("FFC2h", "holding"), source="DD1", quantity=61)
