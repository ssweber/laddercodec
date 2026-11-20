"""Tests of the form of a Modbus TCP address.

A part of the address is a decimal number, so the target holds and writes it without leading
zeros. A padded address that a clipboard or program file holds decodes to that form, and the
instruction writes the stored blob again while it is unchanged.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from laddercodec import (
    FieldError,
    RawInstruction,
    Rung,
    decode,
    encode,
    read_csv,
    replace,
    write_csv,
)
from laddercodec.decode_program import _scr_box
from laddercodec.instructions.raw import _compose_blob, _decompose_blob, _fields_to_tag_dicts
from laddercodec.instructions.send_receive import ModbusTcpTarget, Receive, Send
from tests.ladder.test_send_receive_fields import receive, send

PADDED = "010.002.003.004"
WRITTEN = "10.2.3.4"


def _target(ip: str) -> ModbusTcpTarget:
    return ModbusTcpTarget(name="tcp", ip=ip, port=502, device_id=1)


@pytest.mark.parametrize(
    ("given", "held"),
    [
        (PADDED, WRITTEN),
        ("01.2.3.4", "1.2.3.4"),
        ("001.002.003.004", "1.2.3.4"),
        ("000.0.00.000", "0.0.0.0"),
        ("0.0.0.0", "0.0.0.0"),
        ("192.168.001.010", "192.168.1.10"),
        ("255.255.255.255", "255.255.255.255"),
    ],
)
def test_constructor_holds_decimal_parts(given: str, held: str) -> None:
    assert _target(given).ip == held


@pytest.mark.parametrize("ip", ["256.0.0.1", "0256.0.0.1", "1.2.3", "1.2.3.4.5", "", "-1.2.3.4"])
def test_a_refused_address_is_still_refused(ip: str) -> None:
    with pytest.raises(FieldError) as info:
        _target(ip)
    assert info.value.field == "ModbusTcpTarget.ip"


def test_out_of_range_part_keeps_its_reason_and_code() -> None:
    with pytest.raises(FieldError) as info:
        _target("300.1.1.1")
    assert (info.value.reason.value, info.value.code.value) == ("range", "invalid-modbus-target")


@pytest.mark.parametrize("make", [send, receive])
def test_csv_reads_and_writes_decimal_parts(make, tmp_path: Path) -> None:
    built = make(target=_target(PADDED))
    token = built.to_csv()
    assert WRITTEN in token
    assert PADDED not in token
    padded_token = token.replace(WRITTEN, PADDED)
    parsed = type(built).from_csv_token(padded_token)
    assert parsed.target.ip == WRITTEN
    assert parsed.to_csv() == token

    path = tmp_path / "rung.csv"
    write_csv(path, [Rung(conditions=[["-"] * 31], instructions=[built], comment=None)])
    text = path.read_text(encoding="utf-8")
    assert WRITTEN in text
    assert PADDED not in text
    path.write_text(text.replace(WRITTEN, PADDED), encoding="utf-8")
    [read] = read_csv(path)
    assert read.instructions[0].target.ip == WRITTEN


def test_encode_writes_decimal_parts() -> None:
    blob = send(target=_target(PADDED)).build_blob()
    assert WRITTEN.encode("utf-16-le") in blob
    assert PADDED.encode("utf-16-le") not in blob


def _padded_blob(built: Send | Receive) -> bytes:
    name, marker, parts, extra, fields = _decompose_blob(built.build_blob())
    fields = [(t, s, PADDED if t == 0x622B else v) for t, s, v in fields]
    return _compose_blob(name, marker, parts, extra, fields)


def _padded_rung(built: Send | Receive) -> Rung:
    blob = _padded_blob(built)
    raw = RawInstruction(_decompose_blob(blob)[0], blob)
    return Rung(conditions=[["-"] * 31], instructions=[raw], comment=None)


@pytest.mark.parametrize("make", [send, receive])
def test_clipboard_padded_address_decodes_decimal_and_encodes_stored(make) -> None:
    built = make(target=_target(WRITTEN))
    rung = _padded_rung(built)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        [got] = decode(encode(rung))
    inst = got.instructions[0]
    assert isinstance(inst, type(built))
    assert inst.target.ip == WRITTEN
    assert inst == built
    assert inst.build_blob() == _padded_blob(built)
    assert encode(got) == encode(rung)
    assert inst.to_csv() == built.to_csv()


@pytest.mark.parametrize("make", [send, receive])
def test_clipboard_padded_address_encodes_decimal_once_changed(make) -> None:
    built = make(target=_target(WRITTEN))
    [got] = decode(encode(_padded_rung(built)))
    blob = replace(got.instructions[0], quantity=2).build_blob()
    assert WRITTEN.encode("utf-16-le") in blob
    assert PADDED.encode("utf-16-le") not in blob


def _program_box(blob: bytes) -> Send | Receive:
    name, marker, parts, _extra, fields = _decompose_blob(blob)
    assert parts == 1
    tags, variant_u16, variant_string = _fields_to_tag_dicts(fields)
    return _scr_box(name, marker, tags, b"", variant_u16, variant_string, bytes([0, 0]))


@pytest.mark.parametrize("make", [send, receive])
def test_program_padded_address_decodes_decimal_and_encodes_stored(make) -> None:
    built = make(target=_target(WRITTEN))
    box = _program_box(_padded_blob(built))
    assert isinstance(box, type(built))
    assert box.target.ip == WRITTEN
    assert box == built
    # Only the address differs from the blob of the same entry with a decimal address. The
    # flag tags are left out, because the entry that this test builds from a clipboard blob
    # does not store a Receive's flags the way a program file does.
    stored = _decompose_blob(box.build_blob())[4]
    plain = _decompose_blob(_program_box(built.build_blob()).build_blob())[4]
    assert [(t, v) for t, _s, v in stored if t == 0x622B] == [(0x622B, PADDED)]
    assert [(t, v) for t, _s, v in plain if t == 0x622B] == [(0x622B, WRITTEN)]
    assert [(t, v) for t, _s, v in stored if t != 0x622B and t >> 8 not in (0x11, 0x12)] == [
        (t, v) for t, _s, v in plain if t != 0x622B and t >> 8 not in (0x11, 0x12)
    ]
