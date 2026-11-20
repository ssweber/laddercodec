"""Tests of the form of a Modbus TCP address.

A part of the address is a decimal number, so the target holds and writes it without leading
zeros. A padded address that a clipboard or program file holds decodes to that form, and the
instruction writes the stored blob again while it is unchanged.
"""

from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

import pytest

from laddercodec import (
    FieldError,
    RawInstruction,
    RefusedFieldWarning,
    Rung,
    decode,
    decode_program,
    encode,
    read_csv,
    replace,
    write_csv,
)
from laddercodec.instructions.raw import _compose_blob, _decompose_blob
from laddercodec.instructions.send_receive import ModbusTcpTarget, Receive, Send
from laddercodec.operands.unchecked import stored_blob
from tests.ladder.test_send_receive_fields import receive, send

decode_program_module = sys.modules["laddercodec.decode_program"]
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


SCR_CAPTURES = Path(__file__).parent.parent / "fixtures" / "scr_captures"


def _tcp_boxes(rungs: list[Rung]) -> list[Send | Receive]:
    return [
        inst
        for rung in rungs
        for inst in rung.instructions
        if isinstance(inst, Send | Receive) and isinstance(inst.target, ModbusTcpTarget)
    ]


def _fields_with_ip(blob: bytes, ip: str) -> list[tuple[int, str]]:
    return [(t, ip if t == 0x622B else v) for t, _s, v in _decompose_blob(blob)[4]]


def test_program_padded_address_decodes_decimal_and_encodes_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pad the address of every TCP Send and Receive in a real program file. Each decodes to
    the decimal address, and its kept blob is the clipboard's blob of the same box with the
    address padded and nothing else changed."""
    scr = (SCR_CAPTURES / "coverage.scr").read_bytes()
    clipboard = _tcp_boxes(decode((SCR_CAPTURES / "coverage.bin").read_bytes()))
    plain = _tcp_boxes(decode_program(scr).rungs)
    assert plain
    assert len(plain) == len(clipboard)

    real = decode_program_module._parse_scr_tags

    def padded_tags(*args, **kwargs):
        name, code, tags, variant_u16, variant_string = real(*args, **kwargs)
        if re.fullmatch(r"\d+(\.\d+){3}", tags.get(0x622B, "")):
            tags = {**tags, 0x622B: ".".join(f"{int(p):03d}" for p in tags[0x622B].split("."))}
        return name, code, tags, variant_u16, variant_string

    monkeypatch.setattr(decode_program_module, "_parse_scr_tags", padded_tags)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RefusedFieldWarning)
        padded = _tcp_boxes(decode_program(scr).rungs)
    assert len(padded) == len(plain)

    for box, unpadded, native in zip(padded, plain, clipboard, strict=True):
        written = unpadded.target.ip
        stored_ip = ".".join(f"{int(p):03d}" for p in written.split("."))
        assert stored_ip != written
        assert box.target.ip == written
        assert box == unpadded
        kept = stored_blob(box)
        assert kept is not None
        assert _fields_with_ip(kept, stored_ip) == _fields_with_ip(native.build_blob(), stored_ip)
        assert [v for t, _s, v in _decompose_blob(kept)[4] if t == 0x622B] == [stored_ip]
        assert box.build_blob() == kept
