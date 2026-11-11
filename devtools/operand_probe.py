"""Record how a laddercodec source tree accepts or refuses every instruction field value.

    uv run python -I devtools/operand_probe.py <src_dir> <out.json> [--limit N]
    uv run python -I devtools/operand_probe.py --diff a.json b.json

``<src_dir>`` is the ``src`` directory of the checkout under test; it goes first on
``sys.path`` so ``import laddercodec`` loads it rather than the installed package.

For every instruction class in the family registry, each probe baseline (a known-good set
of constructor arguments) is varied one field at a time over a fixed value list, and each
range field pair is varied together.  Every case records, under ``<Class>/<baseline>/<field>=
<value>``:

``new``    ``ok`` or ``!<ExceptionClass>: <message>`` from the constructor
``csv``    ``to_csv()`` of the constructed instance (``ok`` only)
``blob``   sha256 of ``build_blob()`` and the ``cell_params()`` (``ok`` only)
``write``  the CSV writer's result for a rung holding the instance (``ok`` only)
``text``   ``to_csv()`` of an instance built without its checks, holding the raw value
``read``   that text read back through the CSV path (token parser and converter)
``dec``    the blob of the unchecked instance parsed back by the blob decoder
``tag``    the baseline's blob with the varied field's tag set to the case's value, parsed
           back by the blob decoder (only when one tag holds the baseline value)
``warn``   warnings raised by any path except the writer's (``write`` lists those)

``read`` and ``dec`` are ``=`` when they match ``text``.  The value lists are fixed here,
so two source trees get the same cases.  A registered instruction class with no baseline,
or a field with no value kind, stops the run.

``--diff`` prints only the differences between two outputs and exits 1 if there is any.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
import time
import warnings
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Value lists (fixed: never derived from the source tree under test)
# ---------------------------------------------------------------------------

#: (bank, lowest, highest) for every CLICK bank.  X/Y are written three digits wide.
BANKS: tuple[tuple[str, int, int], ...] = (
    ("X", 1, 816),
    ("Y", 1, 816),
    ("C", 1, 2000),
    ("T", 1, 500),
    ("CT", 1, 250),
    ("SC", 1, 1000),
    ("DS", 1, 4500),
    ("DD", 1, 1000),
    ("DH", 1, 500),
    ("DF", 1, 500),
    ("XD", 0, 8),
    ("YD", 0, 8),
    ("TD", 1, 500),
    ("CTD", 1, 250),
    ("SD", 1, 1000),
    ("TXT", 1, 1000),
)
XY = ("X", "Y")


def _addr(bank: str, number: int) -> str:
    return f"{bank}{number:03d}" if bank in XY else f"{bank}{number}"


def _dedupe(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out = []
    for value in values:
        key = repr(value)
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _bank_edges() -> list[str]:
    out = []
    for bank, lo, hi in BANKS:
        if lo > 0:
            out.append(_addr(bank, lo - 1))
        out += [_addr(bank, lo), _addr(bank, hi), _addr(bank, hi + 1)]
    return out


def _text(n: int) -> str:
    return '"' + "A" * n + '"'


OPERANDS: list[str] = _dedupe(
    _bank_edges()
    + [f"{b}{n:03d}" for b in XY for n in (16, 17, 20, 21, 36, 37, 100, 101, 116, 117, 816)]
    + ["XD0", "XD0u", "YD0u", "XD1u", "YD0U", "xd0u", "XD00"]
    + ["DS[DS1]", "DD[DS1]", "DH[DS1]", "DF[DS1]", "TXT[DS1]", "C[DS1]", "DS[DS4500]"]
    + ["DS[DD1]", "DS[ DS1 ]", "DS[DS0]", "ds[ds1]"]
    + ["C001", "X1", "ds7", "DS0007", "c1", "Ds1", "DS01", "TXT001", "CTD01", "x001"]
    + ["", "0", "-0", "007", "+1", "1", "-1", "10", "100", "9999"]
    + ["32767", "32768", "-32768", "-32769", "65535", "65536"]
    + ["2147483647", "2147483648", "-2147483648", "-2147483649", "3000000000", "6000000000"]
    + ["FFFFh", "ffffh", "FFFFH", "0FFFFh", "10000h", "+1h", "0H", "0h", "1h", "0000h"]
    + ["7FFFh", "8000h", "FFFFFFFFh", "100000000h", "h", "FFFF"]
    + ["٣", "1٣", "DS٣"]
    + ['"A"', '"AB"', _text(128), _text(129), '""', '"""', '"$41"', "$41", "$100", "$1"]
    + ["'A'", '"a,b"', '"A', "A"]
    + ["1.5", "1E5", ".5", "-1.5e-3", "1.", "3.4028235E+38", "3.5E+38", "nan", "inf"]
    + [" DS1", "DS1 ", "DS 1", " 5", "5 ", "1 0", " ", "DS1, DS2"]
    + ["Q1", "DSX1", "DS1..DS5", "DS-1", "DS1.5", "Tms", "none", "abc"]
)

#: Values for the opaque tag fields of the motion and email boxes (no checks to probe).
OPAQUE: list[str] = [
    "",
    "0",
    "1",
    "DS1",
    "X001",
    '"A"',
    "$41",
    "FFFFh",
    "٣",
    " 1",
    "a,b",
    "a(b)",
    "x=y",
]

INTS: list[Any] = [
    0,
    1,
    -1,
    2,
    100,
    125,
    126,
    2000,
    2001,
    32767,
    32768,
    65535,
    65536,
    2147483648,
    True,
    "1",
    1.5,
]

PIN_ROWS: list[tuple[int, ...]] = [
    (),
    (0,),
    (1,),
    (2,),
    (1, 2),
    (2, 1),
    (1, 3),
    (2, 3),
    (1, 2, 3),
    (1, 3, 5),
    (2, 3, 4),
    (1, 1, 1),
]

PATTERNS: list[Any] = [
    [],
    [[1]],
    [[1, 0], [0, 1]],
    [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    [[1, 0], [0, 1], [1, 1]],
    [[2, 0], [0, 1]],
    [[1, 0, 1], [0, 1]],
    [[1] * 16] * 16,
    [[1] * 17] * 2,
    [[1, 0]] * 17,
]

PROGRAM_NAMES: list[str] = [
    "sub",
    "Conf_Shift",
    "a" * 24,
    "a" * 25,
    "CON",
    "con.txt",
    "a/b",
    "a b",
    " a",
    "a.",
]

EXPRESSIONS: list[str] = [
    "DS1 + 1",
    "DS1+1",
    "( DS1 + DS2 ) * 2",
    "DH1 + DH2",
    "DH401 + ( 0h - DH402 )",
    "MAX ( DH101 : DH104 )",
    "SUM ( DS1 : DS10 )",
    "DS1 / 0",
    "DF1 * 1.5",
    "SQRT ( DF1 )",
    "DS1 +",
    "( DS1",
    "DS1 MOD 3",
    "DS1 LSH 2",
    "1 + 2 * 3",
    "X001 + 1",
    "TXT1 + 1",
    "DS[DS1] + 1",
    "FFFFh + 1",
    "٣ + 1",
]

IPS: list[str] = [
    "192.168.1.10",
    "0.0.0.0",
    "255.255.255.255",
    "256.1.1.1",
    "1.1.1",
    "01.1.1.1",
    " 1.1.1.1",
    "",
]

DEVICE_IDS: list[Any] = [*INTS, 247, 248, "DS1", "DS4500", "DS4501", "DS01", "DD1", "1", ""]

MODBUS_ADDRESSES: list[tuple[str, str | None]] = [
    ("400001", None),
    ("000001", None),
    ("100001", None),
    ("300001", None),
    ("465536", None),
    ("0h", "holding"),
    ("FFFEh", "holding"),
    ("FFFFh", "holding"),
    ("0h", "coil"),
    ("0h", "input"),
    ("0h", "discrete_input"),
    ("0h", None),
    ("1h", "bogus"),
    ("40001a", None),
]


def _range_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    banks = [b for b in BANKS if b[0] not in ("XD", "YD")]
    for index, (bank, lo, hi) in enumerate(banks):
        nxt = banks[(index + 1) % len(banks)][0]
        if bank in XY:
            pairs += [
                (_addr(bank, 1), _addr(bank, 16)),
                (_addr(bank, 1), _addr(bank, 21)),
                (_addr(bank, 16), _addr(bank, 1)),
                (_addr(bank, 101), _addr(bank, 116)),
                (_addr(bank, 1), _addr(bank, 816)),
                (_addr(bank, 5), _addr(bank, 5)),
                (_addr(bank, 1), _addr(bank, 817)),
            ]
        else:
            pairs += [
                (_addr(bank, lo), _addr(bank, lo + 3)),
                (_addr(bank, lo + 4), _addr(bank, lo + 4)),
                (_addr(bank, lo + 4), _addr(bank, lo + 1)),
                (_addr(bank, lo), _addr(bank, hi)),
                (_addr(bank, lo), _addr(bank, hi + 1)),
            ]
        pairs.append((_addr(bank, lo), _addr(nxt, lo + 3)))
    pairs += [
        ("XD0", "XD0u"),
        ("XD0u", "XD1"),
        ("XD1", "XD8"),
        ("YD0", "YD8"),
        ("DS[DS1]", "DS5"),
        ("DS1", "DS[DS1]"),
        ("C001", "C016"),
        ("ds1", "ds4"),
        ("", ""),
        ("DS1", ""),
    ]
    return _dedupe(pairs)


RANGE_PAIRS = _range_pairs()

# ---------------------------------------------------------------------------
# Per-class probe tables
# ---------------------------------------------------------------------------


def _lit(*values: Any) -> tuple[str, list[Any]]:
    return ("lit", list(values))


TIMER_UNITS = _lit("Tms", "Ts", "Tm", "Th", "Td", "", "ms", "tms", "TMS")


@dataclasses.dataclass
class Probe:
    """How to probe one class: field value kinds, baselines, range pairs."""

    fields: dict[str, Any]
    baselines: Callable[[Any], dict[str, dict[str, Any]]]
    ranges: tuple[tuple[str, str], ...] = ()
    #: Nested value classes are only constructed (no CSV or blob path).
    nested: bool = False


def _opaque_probe(names: str) -> Probe:
    return Probe(
        fields={name: "opaque" for name in names.split()},
        baselines=lambda ns: {"default": {}},
    )


def _tcp(ns: Any) -> Any:
    return ns.ModbusTcpTarget(name="tcp", ip="192.168.1.10", port=502, device_id=1)


def _rtu(ns: Any) -> Any:
    return ns.ModbusRtuTarget(name="rtu", com_port="cpu2", device_id=5)


def _targets(ns: Any) -> list[Any]:
    return [
        _rtu(ns),
        ns.ModbusRtuTarget(name="rtu", com_port="slot1_2", device_id=3),
        ns.ModbusRtuTarget(name="rtu", com_port="cpu3", device_id="DS2420"),
        ns.ModbusRtuTarget(name="rtu", com_port="cpu2", device_id=0),
        _tcp(ns),
        ns.ModbusTcpTarget(name="tcp", ip="10.0.0.1", port=503, device_id=255, com_port="wlan"),
    ]


def _modbus(ns: Any) -> list[Any]:
    out = []
    for address, register_type in MODBUS_ADDRESSES:
        try:
            out.append(ns.ModbusAddress(address=address, register_type=register_type))
        except Exception:
            continue  # the refusals are probed as ModbusAddress cases
    return out


_MODBUS_FIELDS = {
    "target": "target",
    "remote_start": "remote",
    "quantity": "int",
    "success": "op",
    "error": "op",
    "exception_response": "op",
    "word_swap": "bool",
    "function_code": "int?",
}


def _receive_baselines(ns: Any) -> dict[str, dict[str, Any]]:
    common = {"success": "C2", "error": "C3", "exception_response": "DS100"}
    return {
        "rtu_ds": dict(
            target=_rtu(ns), remote_start="DS1", dest="DS1", quantity=5, receiving="C1", **common
        ),
        "tcp_c": dict(
            target=_tcp(ns), remote_start="C1", dest="C11", quantity=5, receiving="C1", **common
        ),
        "rtu_984": dict(
            target=_rtu(ns),
            remote_start=ns.ModbusAddress(address="400001"),
            dest="DS1",
            quantity=1,
            receiving="C1",
            **common,
        ),
    }


def _send_baselines(ns: Any) -> dict[str, dict[str, Any]]:
    out = {}
    for label, kwargs in _receive_baselines(ns).items():
        kwargs = dict(kwargs)
        kwargs["source"] = kwargs.pop("dest")
        kwargs["sending"] = kwargs.pop("receiving")
        out[label] = kwargs
    return out


PROBES: dict[str, Probe] = {
    "Contact": Probe(
        fields={
            "type": "itype",
            "operand": "op",
            "immediate": "bool",
            "edge_kind": _lit("rise", "fall", None, "up", ""),
            "wire_down": "bool",
        },
        baselines=lambda ns: {
            "no": dict(type=ns.IT.CONTACT_NO, operand="X001"),
            "nc": dict(type=ns.IT.CONTACT_NC, operand="C1"),
            "rise": dict(type=ns.IT.CONTACT_EDGE, operand="C1", edge_kind="rise"),
            "fall": dict(type=ns.IT.CONTACT_EDGE, operand="X001", edge_kind="fall"),
            "imm": dict(type=ns.IT.CONTACT_NO, operand="X001", immediate=True),
        },
    ),
    "CompareContact": Probe(
        fields={
            "op": _lit("==", "!=", "<", ">", "<=", ">=", "=", "<>", "", "eq"),
            "left": "op",
            "right": "op",
            "wire_down": "bool",
        },
        baselines=lambda ns: {
            "ds": dict(op="==", left="DS1", right="5"),
            "dh": dict(op="==", left="DH1", right="0000h"),
            "df": dict(op="<", left="DF1", right="DS1"),
            "txt": dict(op="==", left="TXT1", right="TXT2"),
            "dd": dict(op=">=", left="DD1", right="100000"),
        },
    ),
    "Coil": Probe(
        fields={
            "type": "itype",
            "operand": "op",
            "range_end": "op?",
            "immediate": "bool",
            "oneshot": "bool",
        },
        baselines=lambda ns: {
            "out": dict(type=ns.IT.COIL_OUT, operand="C1"),
            "latch": dict(type=ns.IT.COIL_LATCH, operand="Y001"),
            "reset": dict(type=ns.IT.COIL_RESET, operand="C1"),
            "out_range": dict(type=ns.IT.COIL_OUT, operand="C1", range_end="C4"),
            "out_imm": dict(type=ns.IT.COIL_OUT, operand="Y001", immediate=True),
            "out_oneshot": dict(type=ns.IT.COIL_OUT, operand="C1", oneshot=True),
        },
        ranges=(("operand", "range_end"),),
    ),
    "OutVariant": Probe(
        fields={
            "kind": _lit("toggle", "debounce", "flasher", "timed", "", "out"),
            "operand": "op",
            "on_acc": "op",
            "on_preset": "op",
            "off_acc": "op",
            "off_preset": "op",
            "unit": TIMER_UNITS,
            "immediate": "bool",
            "maintained": "bool",
        },
        baselines=lambda ns: {
            "toggle": dict(kind="toggle", operand="C1"),
            "debounce": dict(
                kind="debounce",
                operand="C1",
                on_acc="TD3",
                on_preset="100",
                off_acc="TD4",
                off_preset="200",
                unit="Tms",
            ),
            "flasher": dict(
                kind="flasher",
                operand="C1",
                on_acc="TD12",
                on_preset="500",
                off_acc="TD13",
                off_preset="250",
                unit="Tms",
            ),
            "timed": dict(kind="timed", operand="C1", on_acc="TD18", on_preset="1000", unit="Tms"),
        },
    ),
    "Timer": Probe(
        fields={
            "timer_type": _lit("on_delay", "off_delay", "", "on"),
            "done_bit": "op",
            "current": "op",
            "setpoint": "op",
            "unit": TIMER_UNITS,
            "retained": "bool",
            "pin_rows": "pins",
        },
        baselines=lambda ns: {
            "on": dict(
                timer_type="on_delay", done_bit="T1", current="TD1", setpoint="3000", unit="Tms"
            ),
            "on_ret": dict(
                timer_type="on_delay",
                done_bit="T2",
                current="TD2",
                setpoint="5000",
                unit="Tms",
                retained=True,
            ),
            "off": dict(
                timer_type="off_delay", done_bit="T3", current="TD3", setpoint="2000", unit="Tms"
            ),
        },
    ),
    "Counter": Probe(
        fields={
            "counter_type": _lit("count_up", "count_down", "", "up"),
            "done_bit": "op",
            "current": "op",
            "preset": "op",
            "down_enabled": "bool",
            "reset_enabled": "bool",
            "pin_rows": "pins",
        },
        baselines=lambda ns: {
            "up": dict(
                counter_type="count_up",
                done_bit="CT1",
                current="CTD1",
                preset="100",
                reset_enabled=True,
            ),
            "up_down": dict(
                counter_type="count_up",
                done_bit="CT2",
                current="CTD2",
                preset="100",
                down_enabled=True,
                reset_enabled=True,
            ),
            "down": dict(
                counter_type="count_down",
                done_bit="CT3",
                current="CTD3",
                preset="50",
                reset_enabled=True,
            ),
        },
    ),
    "Copy": Probe(
        fields={
            "source": "op",
            "destination": "op",
            "format": _lit("none", "value", "text", "binary", "ascii", "", "to_text"),
            "oneshot": "bool",
            "suppress_zero": "op",
            "exponential": "op",
            "termination_code": "op",
        },
        baselines=lambda ns: {
            "tag": dict(source="DS1", destination="DS2"),
            "int": dict(source="42", destination="DS9"),
            "float": dict(source="3.14", destination="DF1"),
            "text": dict(source="DS12", destination="TXT2", format="text", suppress_zero="1"),
            "text_df": dict(
                source="DF2", destination="TXT5", format="text", suppress_zero="1", exponential="1"
            ),
            "text_term": dict(
                source="DS20",
                destination="TXT7",
                format="text",
                suppress_zero="1",
                termination_code="$13",
            ),
            "binary": dict(source="DS22", destination="TXT9", format="binary"),
            "ascii": dict(source="TXT10", destination="DS25", format="ascii"),
            "value": dict(source="TXT1", destination="DS1", format="value"),
        },
    ),
    "BlockCopy": Probe(
        fields={
            "source_start": "op",
            "source_end": "op",
            "dest_start": "op",
            "dest_end": "op",
            "format": _lit("none", "value", "ascii", "text", ""),
            "oneshot": "bool",
        },
        baselines=lambda ns: {
            "block": dict(
                source_start="DS28", source_end="DS31", dest_start="DS32", dest_end="DS35"
            ),
            "ascii": dict(
                source_start="TXT17",
                source_end="TXT20",
                dest_start="DS65",
                dest_end="DS68",
                format="ascii",
            ),
            "value": dict(
                source_start="TXT13",
                source_end="TXT16",
                dest_start="DS40",
                dest_end="DS43",
                format="value",
            ),
        },
        ranges=(("source_start", "source_end"), ("dest_start", "dest_end")),
    ),
    "Fill": Probe(
        fields={"value": "op", "dest_start": "op", "dest_end": "op", "oneshot": "bool"},
        baselines=lambda ns: {
            "int": dict(value="0", dest_start="DS52", dest_end="DS55"),
            "tag": dict(value="DS56", dest_start="DS57", dest_end="DS60"),
            "txt": dict(value="TXT1", dest_start="TXT2", dest_end="TXT5"),
        },
        ranges=(("dest_start", "dest_end"),),
    ),
    "Pack": Probe(
        fields={
            "source_start": "op",
            "source_end": "op",
            "destination": "op",
            "pack_type": _lit("bits", "words", "text", "", "bit"),
            "allow_whitespace": "bool",
            "oneshot": "bool",
        },
        baselines=lambda ns: {
            "bits": dict(source_start="C108", source_end="C123", destination="DS167"),
            "text": dict(
                source_start="TXT1", source_end="TXT4", destination="DS170", pack_type="text"
            ),
        },
        ranges=(("source_start", "source_end"),),
    ),
    "Unpack": Probe(
        fields={
            "source": "op",
            "dest_start": "op",
            "dest_end": "op",
            "unpack_type": _lit("bits", "words", "text", ""),
            "oneshot": "bool",
        },
        baselines=lambda ns: {
            "bits": dict(source="DS172", dest_start="C128", dest_end="C143"),
            "words": dict(source="DD2", dest_start="DS173", dest_end="DS174", unpack_type="words"),
        },
        ranges=(("dest_start", "dest_end"),),
    ),
    "Call": Probe(
        fields={"subroutine": "name"},
        baselines=lambda ns: {"basic": dict(subroutine="coverage_sub")},
    ),
    "ForLoop": Probe(
        fields={"limit": "op", "oneshot": "bool"},
        baselines=lambda ns: {"int": dict(limit="3"), "tag": dict(limit="DS1", oneshot=True)},
    ),
    "Next": Probe(fields={}, baselines=lambda ns: {"basic": {}}),
    "Break": Probe(fields={}, baselines=lambda ns: {"basic": {}}),
    "Continue": Probe(fields={}, baselines=lambda ns: {"basic": {}}),
    "End": Probe(fields={}, baselines=lambda ns: {"basic": {}}),
    "Return": Probe(fields={}, baselines=lambda ns: {"basic": {}}),
    "Math": Probe(
        fields={
            "expression": "expr",
            "result": "op",
            "mode": _lit("decimal", "hex", "", "dec"),
            "oneshot": "bool",
        },
        baselines=lambda ns: {
            "decimal": dict(expression="DS1 + 1", result="DS1"),
            "hex": dict(expression="DH1 + DH2", result="DH3", mode="hex"),
            "float": dict(expression="DF1 * 1.5", result="DF2"),
        },
    ),
    "Shift": Probe(
        fields={"start_bit": "op", "end_bit": "op", "pin_rows": "pins"},
        baselines=lambda ns: {"basic": dict(start_bit="C99", end_bit="C106")},
        ranges=(("start_bit", "end_bit"),),
    ),
    "Search": Probe(
        fields={
            "table_start": "op",
            "table_end": "op",
            "source": "op",
            "result": "op",
            "found": "op",
            "comparison": _lit("==", "!=", ">", "<", ">=", "<=", "=", ""),
            "continuous": "bool",
            "oneshot": "bool",
        },
        baselines=lambda ns: {
            "ds": dict(
                table_start="DS72",
                table_end="DS81",
                source="DS71",
                result="DS82",
                found="C81",
                comparison="==",
            ),
            "txt": dict(
                table_start="TXT1",
                table_end="TXT10",
                source='"A"',
                result="DS166",
                found="C95",
                comparison="==",
            ),
        },
        ranges=(("table_start", "table_end"),),
    ),
    "Drum": Probe(
        fields={
            "drum_kind": _lit("event", "time", "time_event", "", "timed"),
            "outputs": "oplist",
            "events_or_presets": "oplist",
            "pattern": "pattern",
            "current_step": "op",
            "completion_flag": "op",
            "accumulator": "op",
            "unit": TIMER_UNITS,
            "jog_enabled": "bool",
            "jump_enabled": "bool",
            "jump_target": "op",
            "events": "oplist",
            "pin_rows": "pins",
        },
        baselines=lambda ns: {
            "event": dict(
                drum_kind="event",
                outputs=["C183", "C184"],
                events_or_presets=["C185", "C186"],
                pattern=[[1, 0], [0, 1]],
                current_step="DS182",
                completion_flag="C187",
            ),
            "time": dict(
                drum_kind="time",
                outputs=["C1361", "C1362"],
                events_or_presets=["DS1302", "DS1303"],
                pattern=[[1, 0], [0, 1]],
                current_step="DS1206",
                completion_flag="C1406",
                accumulator="TD106",
                unit="Tms",
            ),
            "time_event": dict(
                drum_kind="time_event",
                outputs=["C1321", "C1322"],
                events_or_presets=["DS1301", ""],
                pattern=[[1, 0], [0, 1]],
                current_step="DS1202",
                completion_flag="C1402",
                accumulator="TD102",
                unit="Ts",
                events=["C1503", "C1504"],
            ),
        },
    ),
    "Receive": Probe(
        fields={**_MODBUS_FIELDS, "dest": "op", "receiving": "op"},
        baselines=_receive_baselines,
    ),
    "Send": Probe(
        fields={**_MODBUS_FIELDS, "source": "op", "sending": "op"},
        baselines=_send_baselines,
    ),
    "ModbusRtuTarget": Probe(
        fields={
            "name": "op",
            "com_port": _lit(
                "cpu2", "cpu3", "slot0_1", "slot0_2", "slot1_1", "slot1_2", "ethernet", "", "CPU2"
            ),
            "device_id": "devid",
        },
        baselines=lambda ns: {"cpu2": dict(name="rtu", com_port="cpu2", device_id=5)},
        nested=True,
    ),
    "ModbusTcpTarget": Probe(
        fields={
            "name": "op",
            "ip": "ip",
            "port": "int",
            "device_id": "devid",
            "com_port": _lit("ethernet", "wlan", "cpu2", ""),
        },
        baselines=lambda ns: {
            "eth": dict(name="tcp", ip="192.168.1.10", port=502, device_id=1),
        },
        nested=True,
    ),
    "ModbusAddress": Probe(
        fields={
            "address": "op984",
            "register_type": _lit("coil", "discrete_input", "holding", "input", None, "", "x"),
        },
        baselines=lambda ns: {
            "984": dict(address="400001"),
            "hex": dict(address="0h", register_type="holding"),
        },
        nested=True,
    ),
    "Email": _opaque_probe(
        "tag_60a5 tag_60a6 tag_60a7 tag_2237 tag_6235 tag_6236 tag_60ae tag_60af tag_2206 "
        "tag_2238 tag_6217 tag_622a tag_6081 tag_6082 tag_607c tag_607b tag_607d tag_6083 "
        "tag_2239 tag_20ca tag_3218"
    ),
    "Home": _opaque_probe(
        "tag_222d tag_222e tag_6096 tag_6097 tag_609e tag_609f tag_60a0 tag_609c tag_609d "
        "tag_222f tag_11f5 tag_2230 tag_60a1 tag_60a3 tag_60a4 tag_607b tag_607d tag_6083 "
        "tag_2232 tag_2233 tag_3218"
    ),
    "Velocity": _opaque_probe(
        "tag_222d tag_609b tag_609c tag_609d tag_222f tag_11f5 tag_2231 tag_60a2 tag_60a3 "
        "tag_60a4 tag_607b tag_607d tag_6083 tag_3218"
    ),
    "Position": _opaque_probe(
        "tag_222d tag_6098 tag_6099 tag_609a tag_2206 tag_609b tag_609c tag_609d tag_222f "
        "tag_11f5 tag_2231 tag_60a2 tag_60a3 tag_60a4 tag_607b tag_607d tag_6083 tag_3218"
    ),
    "RawInstruction": Probe(
        fields={"class_name": "classname", "blob": "bytes", "part_count": "int"},
        baselines=lambda ns: {
            "email": dict(class_name="Email", blob=ns.Email().build_blob()),
        },
    ),
}

#: Value classes probed beside the registry's instruction classes.
NESTED = ("ModbusRtuTarget", "ModbusTcpTarget", "ModbusAddress")

# ---------------------------------------------------------------------------
# Running cases
# ---------------------------------------------------------------------------


class Namespace:
    """The laddercodec names the probe tables and runner use."""

    def __init__(self, src_dir: str) -> None:
        src = Path(src_dir).resolve()
        if not (src / "laddercodec" / "__init__.py").is_file():
            raise SystemExit(f"{src} has no laddercodec package")
        sys.path.insert(0, str(src))
        import laddercodec
        from laddercodec import instructions
        from laddercodec.csv.converter import convert_rung
        from laddercodec.csv.parser import _parse_single_rung_rows
        from laddercodec.csv.writer import decoded_rung_to_rows
        from laddercodec.decode import Rung
        from laddercodec.instructions.raw import _compose_blob, _decompose_blob
        from laddercodec.model import (
            AfInstruction,
            ConditionInstruction,
            InstructionType,
            PinnedInstruction,
        )

        loaded = Path(laddercodec.__file__).resolve().parent.parent
        if loaded != src:
            raise SystemExit(f"laddercodec loaded from {loaded}, not {src}")
        self.instructions = instructions
        self.IT = InstructionType
        self.AfInstruction = AfInstruction
        self.ConditionInstruction = ConditionInstruction
        self.PinnedInstruction = PinnedInstruction
        self.Rung = Rung
        self.parse_rows = _parse_single_rung_rows
        self.convert_rung = convert_rung
        self.rung_to_rows = decoded_rung_to_rows
        self.decompose = _decompose_blob
        self.compose = _compose_blob
        for name in NESTED + ("Email",):
            setattr(self, name, getattr(instructions, name))

    def registered_classes(self) -> list[type]:
        specs = (*self.instructions.CONDITION_FAMILY_SPECS, *self.instructions.AF_FAMILY_SPECS)
        classes = [cls for spec in specs for cls in spec.instruction_types]
        return classes + [getattr(self.instructions, name) for name in NESTED]


#: CLICK's tallest rung; a box taller than this skips the writer.
MAX_ROWS = 32


class ProbeSkip(Exception):
    """A case the probe does not run through one of its paths."""


def error_text(exc: BaseException) -> str:
    return f"!{type(exc).__name__}: {exc}"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:24]


def _values(kind: Any, field: str, base: dict[str, Any], ns: Any) -> list[Any]:
    if isinstance(kind, tuple) and kind[0] == "lit":
        return kind[1]
    simple: dict[str, list[Any]] = {
        "op": OPERANDS,
        "op?": [*OPERANDS, None],
        "bool": [False, True],
        "int": INTS,
        "int?": [*INTS, None],
        "pins": PIN_ROWS,
        "pattern": PATTERNS,
        "opaque": OPAQUE,
        "name": [*PROGRAM_NAMES, *OPERANDS],
        "expr": [*EXPRESSIONS, *OPERANDS],
        "ip": IPS,
        "devid": DEVICE_IDS,
        "op984": [a for a, _ in MODBUS_ADDRESSES] + OPERANDS,
        "classname": ["Email", "Home", "Copy", "Coil", "Widget", *OPERANDS],
        "bytes": [b"", b"\x00" * 4, b"E\x00m\x00a\x00i\x00l\x00\x00\x00", b"\xff" * 64],
    }
    if kind in simple:
        return simple[kind]
    if kind == "itype":
        return [*ns.IT, 0x11, 0x99]
    if kind == "target":
        return _targets(ns)
    if kind == "remote":
        return [*OPERANDS, *_modbus(ns)]
    if kind == "oplist":
        current = list(base.get(field, []))
        lists = [[op, *current[1:]] for op in OPERANDS]
        return [*lists, [], [*current, *current[-1:]], ["C1"] * 16, ["C1"] * 17]
    raise SystemExit(f"no value kind {kind!r} for field {field!r}")


def _fill(cls: type, kwargs: dict[str, Any]) -> dict[str, Any]:
    full = {}
    for f in dataclasses.fields(cls):  # ty: ignore[invalid-argument-type]
        if f.name in kwargs:
            full[f.name] = kwargs[f.name]
        elif f.default is not dataclasses.MISSING:
            full[f.name] = f.default
        elif f.default_factory is not dataclasses.MISSING:
            full[f.name] = f.default_factory()
    return full


def _unchecked(cls: type, kwargs: dict[str, Any]) -> Any:
    """An instance holding ``kwargs`` as given, without ``__post_init__``'s checks."""
    obj = object.__new__(cls)
    for name, value in _fill(cls, kwargs).items():
        object.__setattr__(obj, name, value)
    return obj


class Runner:
    def __init__(self, ns: Namespace) -> None:
        self.ns = ns
        self.templates: dict[str, list[list[str]]] = {}
        self.base_fields: dict[str, Any] = {}

    def describe(self, token: Any) -> str:
        """Type and CSV text of a token; pinned boxes add their pin rows."""
        ns = self.ns
        if isinstance(token, (ns.AfInstruction, ns.ConditionInstruction)):
            try:
                text = token.to_csv()
            except Exception as exc:
                return f"{type(token).__name__}{error_text(exc)}"
            if isinstance(token, ns.PinnedInstruction):
                try:
                    text += f" @pins={list(token.pin_rows)} {list(token.pin_labels())}"
                except Exception as exc:
                    text += f" @pins{error_text(exc)}"
            return f"{type(token).__name__}:{text}"
        return f"{type(token).__name__}:{token!r}"

    def rung_for(self, inst: Any) -> Any:
        """A rung holding ``inst``: a contact in column A, or an AF box with its rows."""
        ns = self.ns
        if isinstance(inst, ns.ConditionInstruction):
            return ns.Rung(1, [[inst] + ["-"] * 30], [""], None)
        rows, nop_row = 1, None
        if isinstance(inst, ns.PinnedInstruction):
            rows = inst.pin_rows[-1] + 1
            nop_row = inst.lead_rows or None
        else:
            rows = int(inst.cell_params().get("visual_rows", 1))
        if not 1 <= rows <= MAX_ROWS:
            raise ProbeSkip(f"a {rows}-row box is past CLICK's {MAX_ROWS} rows")
        conditions: list[list[Any]] = [["-"] * 31] + [[""] * 31 for _ in range(rows - 1)]
        afs: list[Any] = [inst] + [""] * (rows - 1)
        if nop_row is not None:
            afs[nop_row] = "NOP"
        return ns.Rung(rows, conditions, afs, None)

    def template(self, inst: Any) -> tuple[list[list[str]], str]:
        """The writer's CSV rows for a rung holding ``inst``, and any warnings it gave."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            rows = [list(row) for row in self.ns.rung_to_rows(self.rung_for(inst))]
        notes = "; ".join(f"{w.category.__name__}: {w.message}" for w in caught)
        return rows, notes

    def read_back(self, rows: list[list[str]], condition: bool) -> str:
        ns = self.ns
        try:
            _rows, conditions, instructions, _comment = ns.convert_rung(ns.parse_rows(rows))
        except Exception as exc:
            return error_text(exc)
        if condition:
            return self.describe(conditions[0][0])
        token = next((t for t in instructions if t not in ("", "NOP")), None)
        return self.describe(token) if token is not None else f"none:{instructions!r}"

    def decode_blob(self, blob: bytes, condition: bool) -> str:
        parse = (
            self.ns.instructions.parse_condition_blob
            if condition
            else self.ns.instructions.parse_af_blob
        )
        try:
            parsed = parse(blob)
        except Exception as exc:
            return error_text(exc)
        return "None" if parsed is None else self.describe(parsed)

    def run(self, cls: type, key_base: str, base: dict[str, Any], kwargs: dict[str, Any]) -> dict:
        ns = self.ns
        nested = PROBES[cls.__name__].nested
        record: dict[str, Any] = {}
        inst = None
        try:
            inst = cls(**kwargs)
        except Exception as exc:
            record["new"] = error_text(exc)
        else:
            record["new"] = "ok"
        if nested:
            if inst is not None:
                record["repr"] = repr(inst)
            return record
        condition = issubclass(cls, ns.ConditionInstruction)
        if inst is not None:
            record["csv"] = self.describe(inst)
            try:
                record["blob"] = f"{_sha(inst.build_blob())} {sorted(inst.cell_params().items())}"
            except Exception as exc:
                record["blob"] = error_text(exc)
            try:
                rows, notes = self.template(inst)
                record["write"] = f"ok ({notes})" if notes else "ok"
                anchor = inst
            except ProbeSkip as exc:
                record["write"] = f"skipped: {exc}"
                rows, anchor = None, None
            except Exception as exc:
                record["write"] = error_text(exc)
                rows, anchor = None, None
        else:
            rows, anchor = None, None
        if rows is None or anchor is None:
            anchor = cls(**base)
            if key_base not in self.templates:
                self.templates[key_base] = self.template(anchor)[0]
            rows = [list(row) for row in self.templates[key_base]]
        raw = _unchecked(cls, kwargs)
        text = self.describe(raw)
        record["text"] = text
        try:
            raw_csv = raw.to_csv()
        except Exception:
            raw_csv = None
        if raw_csv is not None:
            anchor_csv = anchor.to_csv()
            cells = [
                (r, c) for r, row in enumerate(rows) for c, v in enumerate(row) if v == anchor_csv
            ]
            if not cells:
                record["read"] = f"!probe: {anchor_csv!r} not found in its CSV rows"
            else:
                r, c = cells[0]
                rows[r][c] = raw_csv
                read = self.read_back(rows, condition)
                record["read"] = "=" if read == text else read
        try:
            blob = raw.build_blob()
        except Exception as exc:
            record["dec"] = f"build{error_text(exc)}"
        else:
            dec = self.decode_blob(blob, condition)
            record["dec"] = "=" if dec == text else dec
        tag = self.tag_swap(cls, key_base, base, kwargs, condition)
        if tag is not None:
            record["tag"] = tag
        return record

    def tag_swap(
        self,
        cls: type,
        key_base: str,
        base: dict[str, Any],
        kwargs: dict[str, Any],
        condition: bool,
    ) -> str | None:
        """Decode the baseline's blob with each varied field's tag holding the case's value.

        A field is located by its baseline value: it must be a non-empty string held by
        exactly one tag.  Returns None when a varied field cannot be located.
        """
        changed = [name for name in kwargs if name not in base or kwargs[name] != base[name]]
        if not changed:
            return None
        if key_base not in self.base_fields:
            blob = cls(**base).build_blob()
            self.base_fields[key_base] = self.ns.decompose(blob)
        class_name, marker, part_count, extra, fields = self.base_fields[key_base]
        fields = list(fields)
        swapped = []
        for name in changed:
            old, new = base.get(name), kwargs[name]
            if not isinstance(old, str) or not old or not isinstance(new, str):
                return None
            hits = [i for i, (_tag, _sentinel, value) in enumerate(fields) if value == old]
            if len(hits) != 1:
                return None
            tag, sentinel, _value = fields[hits[0]]
            fields[hits[0]] = (tag, sentinel, new)
            swapped.append(f"{tag:04x}")
        try:
            blob = self.ns.compose(class_name, marker, part_count, extra, fields)
        except Exception as exc:
            return f"{','.join(swapped)} compose{error_text(exc)}"
        return f"{','.join(swapped)} {self.decode_blob(blob, condition)}"


def _cases(probe: Probe, label: str, base: dict[str, Any], ns: Any) -> list[tuple[str, dict]]:
    cases: list[tuple[str, dict]] = [("-", dict(base))]
    for field, kind in probe.fields.items():
        for value in _values(kind, field, base, ns):
            cases.append((f"{field}={value!r}", {**base, field: value}))
    for a, b in probe.ranges:
        for va, vb in RANGE_PAIRS:
            cases.append((f"{a},{b}={(va, vb)!r}", {**base, a: va, b: vb}))
    return cases


def probe(src_dir: str, limit: int | None = None) -> dict[str, Any]:
    ns = Namespace(src_dir)
    runner = Runner(ns)
    classes = ns.registered_classes()
    missing = [cls.__name__ for cls in classes if cls.__name__ not in PROBES]
    if missing:
        raise SystemExit(f"no probe baseline for registered class(es): {', '.join(missing)}")
    cases: dict[str, Any] = {}
    per_class: dict[str, dict[str, Any]] = {}
    for cls in sorted(classes, key=lambda c: c.__name__):
        name = cls.__name__
        spec = PROBES[name]
        field_names = [f.name for f in dataclasses.fields(cls)]  # ty: ignore[invalid-argument-type]
        if sorted(field_names) != sorted(spec.fields):
            raise SystemExit(
                f"{name}: probe fields {sorted(spec.fields)} do not match the class's "
                f"fields {sorted(field_names)}"
            )
        outcomes: Counter[str] = Counter()
        count = 0
        for label, base in spec.baselines(ns).items():
            key_base = f"{name}/{label}"
            for case, kwargs in _cases(spec, label, base, ns):
                if limit is not None and count >= limit:
                    break
                key = f"{key_base}/{case}"
                if key in cases:
                    continue
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    record = runner.run(cls, key_base, base, kwargs)
                if caught:
                    record["warn"] = [f"{w.category.__name__}: {w.message}" for w in caught]
                if case == "-" and record["new"] != "ok":
                    raise SystemExit(f"{key_base}: baseline refused: {record['new']}")
                cases[key] = record
                count += 1
                new = record["new"]
                outcomes["ok" if new == "ok" else new.split(":", 1)[0].lstrip("!")] += 1
        per_class[name] = {"cases": count, "outcomes": dict(sorted(outcomes.items()))}
    meta = {"cases": len(cases), "per_class": per_class}
    return {"tool": "operand_probe", "meta": meta, "cases": cases}


def load_diff_module() -> Any:
    import importlib.util

    path = Path(__file__).resolve().parent / "identity_diff.py"
    spec = importlib.util.spec_from_file_location("identity_diff", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("src_dir", nargs="?", help="src directory holding laddercodec")
    parser.add_argument("out", nargs="?", help="JSON output path")
    parser.add_argument("--diff", nargs=2, metavar=("A", "B"), help="compare two outputs")
    parser.add_argument("--limit", type=int, help="at most N cases per class")
    args = parser.parse_args(argv)
    if args.diff:
        return load_diff_module().diff_files(*args.diff)
    if not args.src_dir or not args.out:
        parser.error("src_dir and out are required unless --diff is given")
    start = time.perf_counter()
    doc = probe(args.src_dir, args.limit)
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(doc, handle, ensure_ascii=False, sort_keys=True, indent=1)
        handle.write("\n")
    seconds = time.perf_counter() - start
    for name, info in doc["meta"]["per_class"].items():
        print(f"{name:16} {info['cases']:6}  {info['outcomes']}")
    print(f"{doc['meta']['cases']} cases in {seconds:.1f} s -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
