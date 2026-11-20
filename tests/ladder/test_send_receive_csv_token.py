"""Tests of Send.from_csv_token and Receive.from_csv_token."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from laddercodec import CSV_HEADER, CsvReadError, FieldError, Receive, Send, decode, read_csv

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


def _read_cell(tmp_path: Path, token: str) -> object:
    """Return the instruction that ``read_csv`` reads from a rung whose AF cell is *token*."""
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([CSV_HEADER, ["R", "X001", *["-"] * 30, token]])
    (rung,) = read_csv(path)
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
