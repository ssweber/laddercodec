"""Tests of Send.from_csv_token and Receive.from_csv_token."""

from __future__ import annotations

import csv
import dataclasses
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from laddercodec import (
    CSV_HEADER,
    CsvReadError,
    FieldError,
    ModbusRtuTarget,
    ModbusTcpTarget,
    Receive,
    Send,
    decode,
    read_csv,
    write_csv,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
GRIDS = FIXTURES / "editor_grids"

_TCP = 'ModbusTcpTarget(name="tcp",ip="192.168.1.10",port=502,device_id=1)'
SEND = f'send(target={_TCP},remote_start="DS1",source=DS1..DS5,sending=C1,success=C2,error=C3)'
RECEIVE = f'receive(target={_TCP},remote_start="DS1",dest=DS1,receiving=C1,success=C2)'


def _golden_boxes() -> list[Send | Receive]:
    """Return each Send and Receive in the coverage goldens, read from the CSV and the bin."""
    boxes: list[Send | Receive] = []
    for csv_path in sorted((FIXTURES / "coverage" / "golden").glob("*.csv")):
        if not csv_path.stem.startswith(("send__", "receive__")):
            continue
        rungs = list(read_csv(csv_path)) + decode(csv_path.with_suffix(".bin").read_bytes())
        for rung in rungs:
            boxes.extend(t for t in rung.instructions if isinstance(t, (Send, Receive)))
    return boxes


def _generator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "editor_grids", ROOT / "devtools" / "editor_grids.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _grid_boxes() -> list[Send | Receive]:
    """Return each Send and Receive that an editor-grid case builds without a refusal."""
    generator = _generator()
    boxes: list[Send | Receive] = []
    for path in sorted(GRIDS.glob("*.json")):
        if path.name.endswith((".answers.json", ".verdicts.json")):
            continue
        for case in json.loads(path.read_text(encoding="utf-8"))["cases"]:
            if case["instruction"] == "send":
                build = generator._send_build(case)
            elif case["instruction"] == "receive":
                build = generator.receive_build(case)
            else:
                continue
            try:
                boxes.append(build())
            except ValueError:
                continue
    return boxes


@pytest.mark.parametrize("box", _golden_boxes(), ids=lambda box: box.to_csv())
def test_golden_boxes_read_back(box: Send | Receive) -> None:
    assert type(box).from_csv_token(box.to_csv()) == box


def test_grid_boxes_read_back() -> None:
    boxes = _grid_boxes()
    assert {type(box) for box in boxes} == {Send, Receive}
    wrong = [box.to_csv() for box in boxes if type(box).from_csv_token(box.to_csv()) != box]
    assert wrong == []


def _cell_file(path: Path, token: str) -> Path:
    """Write a one-rung CSV file at *path* whose AF cell is *token*, and return *path*."""
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([CSV_HEADER, ["R", "X001", *["-"] * 30, token]])
    return path


def _read_cell(tmp_path: Path, token: str) -> object:
    """Return the instruction that ``read_csv`` reads from a rung whose AF cell is *token*."""
    (rung,) = read_csv(_cell_file(tmp_path / "rung.csv", token))
    (box,) = [t for t in rung.instructions if isinstance(t, (Send, Receive))]
    return box


@pytest.mark.parametrize(("cls", "token"), [(Send, SEND), (Receive, RECEIVE)])
def test_token_reads_as_read_csv_reads_the_cell(
    tmp_path: Path, cls: type[Send | Receive], token: str
) -> None:
    box = cls.from_csv_token(f"  {token}  ")
    assert box == _read_cell(tmp_path, token)
    assert box.quantity == (5 if cls is Send else 1)


@pytest.mark.parametrize(
    ("cls", "token"),
    [
        (Send, SEND.replace("device_id=1", "device_id=300")),
        (Send, SEND.replace("sending=C1", "sending=DS1")),
        (Send, SEND.replace("success=C2,error=C3", "success=C2 error=C3")),
        (Send, SEND.replace(f"target={_TCP}", "target=Foo()")),
        (Send, 'send(remote_start="DS1",source=DS1)'),
        (Send, 'send(target="unclosed)'),
        (Receive, RECEIVE.replace("dest=DS1", "dest=DS1,function_code=9")),
        (Receive, f"receive(target={_TCP},dest=DS1)"),
    ],
)
def test_token_raises_as_read_csv_raises_for_the_cell(
    tmp_path: Path, cls: type[Send | Receive], token: str
) -> None:
    with pytest.raises(ValueError) as from_token:
        cls.from_csv_token(token)
    with pytest.raises(ValueError) as from_csv:
        _read_cell(tmp_path, token)
    assert type(from_token.value) is type(from_csv.value)
    assert getattr(from_token.value, "code", None) == getattr(from_csv.value, "code", None)
    # read_csv adds the cell's location to the end of the message.
    assert str(from_csv.value).startswith(str(from_token.value))


@pytest.mark.parametrize("cls", [Send, Receive])
@pytest.mark.parametrize(
    "token",
    [
        "",
        "copy(DS1,DS2)",
        "send",
        "receive",
        "send(target=",
        'send(target="unclosed)',
        "raw(SD,00)",
    ],
)
def test_token_that_does_not_parse(cls: type[Send | Receive], token: str) -> None:
    with pytest.raises(CsvReadError) as info:
        cls.from_csv_token(token)
    assert not isinstance(info.value, FieldError)


def test_token_without_a_target_is_a_read_error() -> None:
    with pytest.raises(CsvReadError, match="target="):
        Send.from_csv_token('send(remote_start="DS1",source=DS1)')
    with pytest.raises(CsvReadError, match="remote_start="):
        Receive.from_csv_token(f"receive(target={_TCP},dest=DS1)")


@pytest.mark.parametrize(
    ("cls", "token", "field"),
    [
        (Send, SEND.replace("device_id=1", "device_id=300"), "ModbusTcpTarget.device_id"),
        (Send, SEND.replace("source=DS1..DS5", "source=DS5..DS1"), "Send.source"),
        (Send, SEND.replace("sending=C1", "sending=DS1"), "Send.sending"),
        # A missing comma between two plain values leaves them in one field.
        (Send, SEND.replace("success=C2,error=C3", "success=C2 error=C3"), "Send.success"),
        (Receive, RECEIVE.replace("dest=DS1", "dest=Q1"), "Receive.dest"),
        (Receive, RECEIVE.replace("dest=DS1", "dest=DS1,function_code=9"), "Receive.function_code"),
        (Receive, RECEIVE.replace('ip="192.168.1.10"', 'ip="1.2.3.256"'), "ModbusTcpTarget.ip"),
    ],
)
def test_refused_field_is_a_field_error(cls: type[Send | Receive], token: str, field: str) -> None:
    with pytest.raises(FieldError) as info:
        cls.from_csv_token(token)
    assert not isinstance(info.value, CsvReadError)
    assert field in info.value.fields


@pytest.mark.parametrize(
    ("cls", "token", "other"),
    [(Send, RECEIVE, "Receive"), (Receive, SEND, "Send")],
)
def test_token_of_the_other_class(cls: type[Send | Receive], token: str, other: str) -> None:
    with pytest.raises(CsvReadError) as info:
        cls.from_csv_token(token)
    message = str(info.value)
    assert f"as a {cls.__name__}, because it is a {other.lower()}(...) token" in message
    assert f"Read it with {other}.from_csv_token()" in message
    example = message.split(", such as ", 1)[1].removesuffix(".")
    assert isinstance(cls.from_csv_token(example), cls)


@pytest.mark.parametrize("cls", [Send, Receive])
def test_read_error_example_reads(cls: type[Send | Receive]) -> None:
    with pytest.raises(CsvReadError) as info:
        cls.from_csv_token("copy(DS1,DS2)")
    example = str(info.value).split(", such as ", 1)[1].removesuffix(".")
    assert isinstance(cls.from_csv_token(example), cls)


def _with_target(target: str) -> str:
    """Return a Send token whose target is *target*."""
    return f'send(target={target},remote_start="DS1",source=DS1)'


def _with_remote(remote: str) -> str:
    """Return a Send token whose remote start is *remote*."""
    return f"send(target={_TCP},remote_start={remote},source=DS1)"


#: Each argument that a Send or Receive token can't read, with the text of its refusal.
_REFUSED_ARGUMENTS = [
    pytest.param(
        Send,
        f'send(DS9,target={_TCP},remote_start="DS1",source=DS1)',
        "send(...) has the argument 'DS9' with no keyword",
        id="positional",
    ),
    pytest.param(
        Send,
        SEND.replace("success=C2", "sucess=C2"),
        "send(...) does not accept sucess=. Remove it, or use one of its keywords: target=,",
        id="unknown",
    ),
    pytest.param(
        Send,
        SEND.replace("source=DS1..DS5", "source=DS1,quantity=5"),
        "send(...) does not accept quantity=. Write the count as a range, such as source=DS1..DS5.",
        id="send-quantity",
    ),
    pytest.param(
        Receive,
        RECEIVE.replace("dest=DS1", "dest=DS1,quantity=5"),
        "receive(...) does not accept quantity=. Write the count as a range, such as "
        "dest=DS1..DS5.",
        id="receive-quantity",
    ),
    pytest.param(
        Send,
        SEND.replace("source=DS1..DS5", "dest=DS1"),
        "send(...) has dest=. Only receive(...) accepts it. Write source=DS1 instead.",
        id="send-dest",
    ),
    pytest.param(
        Send,
        SEND.replace("sending=C1", "receiving=C1"),
        "send(...) has receiving=. Only receive(...) accepts it. Write sending=C1 instead.",
        id="send-receiving",
    ),
    pytest.param(
        Receive,
        RECEIVE.replace("dest=DS1", "source=DS1"),
        "receive(...) has source=. Only send(...) accepts it. Write dest=DS1 instead.",
        id="receive-source",
    ),
    pytest.param(
        Receive,
        RECEIVE.replace("receiving=C1", "sending=C1"),
        "receive(...) has sending=. Only send(...) accepts it. Write receiving=C1 instead.",
        id="receive-sending",
    ),
    pytest.param(
        Send,
        SEND.replace("success=C2", "success=C2,success=C4"),
        "send(...) has success= more than once. Keep one, such as success=C2.",
        id="duplicate",
    ),
    pytest.param(
        Receive,
        f"{RECEIVE[:-1]},target={_TCP})",
        f"receive(...) has target= more than once. Keep one, such as target={_TCP}.",
        id="duplicate-target",
    ),
    pytest.param(
        Send,
        _with_target('ModbusTcpTarget("x","1.2.3.4")'),
        "ModbusTcpTarget(...) has the argument '\"x\"' with no keyword",
        id="target-positional",
    ),
    pytest.param(
        Send,
        _with_target('ModbusRtuTarget("x",com_port="cpu2")'),
        "ModbusRtuTarget(...) has the argument '\"x\"' with no keyword",
        id="rtu-positional",
    ),
    pytest.param(
        Send,
        _with_target('ModbusTcpTarget(name="x" ip="1.2.3.4")'),
        'Could not read \'name="x" ip="1.2.3.4"\' in ModbusTcpTarget(...). Put a comma '
        "between two arguments",
        id="target-missing-comma",
    ),
    pytest.param(
        Send,
        _with_target('ModbusTcpTarget(name="x",ip="1.2.3.4",port=502 device_id=1)'),
        "Could not read 'port=502 device_id=1' in ModbusTcpTarget(...)",
        id="target-missing-comma-number",
    ),
    pytest.param(
        Send,
        _with_target('ModbusTcpTarget(name="x",ip="1.2.3.4",)'),
        "ModbusTcpTarget(...) has an empty argument. Remove the extra comma",
        id="target-empty-argument",
    ),
    pytest.param(
        Send,
        _with_target('ModbusTcpTarget(name="x",ip="1.2.3.4",prot=502)'),
        "ModbusTcpTarget(...) does not accept prot=. Remove it, or use one of its keywords: "
        "name=, ip=, port=, device_id=, com_port=.",
        id="target-unknown",
    ),
    pytest.param(
        Send,
        _with_target('ModbusTcpTarget(name="x",ip="1.2.3.4",ip="1.2.3.5")'),
        'ModbusTcpTarget(...) has ip= more than once. Keep one, such as ip="1.2.3.4".',
        id="target-duplicate",
    ),
    pytest.param(
        Send,
        _with_target('ModbusRtuTarget(name="x",ip="1.2.3.4")'),
        "ModbusRtuTarget(...) has ip=. Only ModbusTcpTarget(...) accepts it. Remove ip=, "
        "or write a ModbusTcpTarget(...), such as",
        id="rtu-tcp-keyword",
    ),
    pytest.param(
        Send,
        _with_target("garbage"),
        "Could not read target=garbage. Write ModbusTcpTarget(...) or ModbusRtuTarget(...)",
        id="target-garbage",
    ),
    pytest.param(
        Send,
        _with_target("Foo(a=1)"),
        "Could not read target=Foo(a=1). Write ModbusTcpTarget(...) or ModbusRtuTarget(...)",
        id="target-type",
    ),
    pytest.param(
        Send,
        _with_remote("ModbusAddress(0h)"),
        "ModbusAddress(...) has the argument '0h' with no keyword",
        id="address-positional",
    ),
    pytest.param(
        Send,
        _with_remote("ModbusAddress(address=0h,regtype=holding)"),
        "ModbusAddress(...) does not accept regtype=",
        id="address-unknown",
    ),
    pytest.param(
        Send,
        _with_remote("ModbusAddress(address=0h,address=1h)"),
        "ModbusAddress(...) has address= more than once. Keep one, such as address=0h.",
        id="address-duplicate",
    ),
    pytest.param(
        Send,
        _with_remote("ModbusAddress(address=0h register_type=holding)"),
        "Could not read 'address=0h register_type=holding' in ModbusAddress(...). Put a comma "
        "between two arguments",
        id="address-missing-comma",
    ),
    pytest.param(
        Send,
        _with_target('ModbusRtuTarget(name="x",com_port="cpu2",slave=1)'),
        "ModbusRtuTarget(...) does not accept slave=. Remove it, or use one of its keywords: "
        "name=, com_port=, device_id=.",
        id="rtu-unknown",
    ),
    pytest.param(
        Send,
        f'send(,target={_TCP},remote_start="DS1",source=DS1)',
        "send(...) has an empty argument. Remove the extra comma",
        id="send-empty-argument",
    ),
]


@pytest.mark.parametrize(("cls", "token", "said"), _REFUSED_ARGUMENTS)
def test_refused_argument_is_a_read_error(
    tmp_path: Path, cls: type[Send | Receive], token: str, said: str
) -> None:
    with pytest.raises(CsvReadError) as from_token:
        cls.from_csv_token(token)
    with pytest.raises(CsvReadError) as from_csv:
        _read_cell(tmp_path, token)
    for raised in (from_token.value, from_csv.value):
        assert not isinstance(raised, FieldError)
        assert said in str(raised)
    # read_csv adds the cell's location to the end of the message.
    assert str(from_csv.value).startswith(str(from_token.value))


@pytest.mark.parametrize(
    ("token", "build"),
    [
        pytest.param(f'send(DS9,target={_TCP},remote_start="DS1",source=DS1)', str, id="send"),
        pytest.param(f'receive(DS9,target={_TCP},remote_start="DS1",dest=DS1)', str, id="receive"),
        pytest.param(_with_target('ModbusTcpTarget("x")'), _with_target, id="tcp"),
        pytest.param(_with_target('ModbusRtuTarget("x")'), _with_target, id="rtu"),
        pytest.param(_with_remote("ModbusAddress(0h)"), _with_remote, id="address"),
    ],
)
def test_positional_refusal_example_reads(token: str, build: Any) -> None:
    """The example in the refusal of a positional argument reads, in a token if it is a
    constructor."""
    cls = Receive if token.startswith("receive(") else Send
    with pytest.raises(CsvReadError) as info:
        cls.from_csv_token(token)
    example = str(info.value).split(", such as ", 1)[1].removesuffix(".")
    assert isinstance(cls.from_csv_token(build(example)), cls)


def test_unquoted_name_with_a_space_reads() -> None:
    box = Send.from_csv_token(_with_target('ModbusTcpTarget(name=my plc,ip="1.2.3.4")'))
    assert isinstance(box.target, ModbusTcpTarget)
    assert box.target.name == "my plc"


def test_doubled_quote_in_a_name_is_one_quote() -> None:
    box = Send.from_csv_token(_with_target('ModbusTcpTarget(name="a""b",ip="1.2.3.4")'))
    assert isinstance(box.target, ModbusTcpTarget)
    assert box.target.name == 'a"b'


@pytest.mark.parametrize("name", ['a"b"c', '"', 'a""b', "a,b", "a(b", "a)b", "a=b"])
@pytest.mark.parametrize(
    "target",
    [
        lambda name: ModbusTcpTarget(name=name, ip="1.2.3.4", port=502, device_id=1),
        lambda name: ModbusRtuTarget(name=name, com_port="cpu2", device_id=1),
    ],
    ids=["tcp", "rtu"],
)
def test_target_name_reads_back(tmp_path: Path, name: str, target: Any) -> None:
    box = Send.from_csv_token(SEND)
    box = dataclasses.replace(box, target=target(name))
    assert Send.from_csv_token(box.to_csv()) == box
    (rung,) = read_csv(_cell_file(tmp_path / "first.csv", box.to_csv()))
    write_csv(tmp_path / "again.csv", [rung])
    (again,) = read_csv(tmp_path / "again.csv")
    assert [t for t in again.instructions if isinstance(t, Send)] == [box]
