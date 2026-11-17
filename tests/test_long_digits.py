"""A constant of more than 4300 digits is refused, never a crash.

``int()`` refuses a string of more than 4300 digits with a ``ValueError``, so a field that
reads its constant with ``int()`` before checking its length crashes.  Every instruction the
golden CSVs read to (``devtools/field_sweep.py`` lists them), and a minimal Email, Home,
Position and Velocity, is rebuilt with each text field (nested ones too: a Send's
``ModbusAddress``), each text in a list field and each optional text field left empty,
replaced by digit text in the spellings a constant takes:
decimal, signed, hex, real, with an exponent, and inside an expression.  Each rebuild is
accepted or refused with ``FieldError``; any other exception fails.  A spelling beyond every
field's range must be refused.  Leading zeros and a long fraction hold a value in range, so a
field may take them.  The fields no check reads, by kind, are named in ``UNCHECKED``.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import warnings
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from laddercodec import FieldError
from tests.sweep_keys import kind_of

ROOT = Path(__file__).resolve().parents[1]


def _sweep() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "field_sweep", ROOT / "devtools" / "field_sweep.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SWEEP = _sweep()

_RUN = "7" * 4400
_ZEROS = "0" * 4400
#: Spellings whose value is in range: a field may take them.
IN_RANGE = [
    _ZEROS + "1",
    "1." + _RUN,
]
#: Compare takes a real of any size (its constants are not held to float32).
HUGE_REALS = [_RUN + ".5", "1E" + _RUN, "1E+" + _RUN]
HUGE_REAL_FIELDS = {"CompareContact.left", "CompareContact.right"}
OUT_OF_RANGE = [
    _RUN,
    "-" + _RUN,
    "+" + _RUN,
    _RUN + "h",
    "-" + _RUN + "h",
    _RUN + ".5",
    "1E" + _RUN,
    "1E+" + _RUN,
    "DS1 + " + _RUN,
    "DS1 + " + _RUN + "h",
    "(" + _RUN + ")",
    "$" + _RUN,
    "DS" + _RUN,
    "DS[" + _RUN + "]",
]

#: Fields no check reads, so any text is kept, as ``(Class.field, kind)``: a drum's jump target
#: while its jump is off, its accumulator and unit where its kind has none (an event drum), a
#: Modbus target's name, and a raw instruction's class name.  ``kind`` is the Drum or OutVariant
#: kind (a jump target's also says whether the jump is on), ``None`` for a class without one:
#: a time drum's accumulator and unit, and a jump-on drum's target, are checked.
UNCHECKED = {
    ("Drum.jump_step", "event_drum, jump off"),
    ("Drum.jump_step", "time_drum, jump off"),
    ("Drum.jump_step", "time_event_drum, jump off"),
    ("Drum.accumulator", "event_drum"),
    ("Drum.unit", "event_drum"),
    ("ModbusRtuTarget.name", None),
    ("ModbusTcpTarget.name", None),
    ("RawInstruction.class_name", None),
}

#: Classes whose fields are opaque tag-keyed text, kept as written.
OPAQUE = {"Email", "Home", "Position", "Velocity"}

#: Instruction classes with no text field to sweep.
NO_TEXT_FIELDS = {"End", "Return", "Next", "Break", "Continue"}


def _roots() -> list[Any]:
    from laddercodec.instructions import Email, Home, Position, Velocity

    return [*SWEEP.golden_instructions().values(), Email(), Home(), Position(), Velocity()]


Path_ = tuple[tuple[str, int | None], ...]


def _walk(obj: Any, label: str, path: Path_) -> list[tuple[str, Path_, Any]]:
    """Each (label, path, original value) of a text field in ``obj`` and what it holds."""
    found = []
    for f in dataclasses.fields(obj):
        if not f.init:
            continue
        value = getattr(obj, f.name)
        here = f"{label}.{f.name}"
        if isinstance(value, str) or (value is None and "str" in str(f.type)):
            found.append((here, (*path, (f.name, None)), value))
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            found += _walk(value, type(value).__name__, (*path, (f.name, None)))
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                if isinstance(item, str):
                    found.append((f"{here}[{i}]", (*path, (f.name, i)), item))
    return found


def _replace(obj: Any, path: Path_, text: str) -> Any:
    (name, index), rest = path[0], path[1:]
    value = getattr(obj, name)
    if rest:
        new: Any = _replace(value, rest, text)
    elif index is None:
        new = text
    else:
        new = list(value)
        new[index] = text
    return dataclasses.replace(obj, **{name: new})


def _cases() -> list[tuple[str, Any, Path_]]:
    """One case per (field, value it held) in the golden set, with the instruction to rebuild."""
    seen: dict[tuple[str, str, str | None], tuple[str, Any, Path_]] = {}
    for inst in _roots():
        for label, path, value in _walk(inst, type(inst).__name__, ()):
            kind = kind_of(inst, label.split(".")[-1])
            seen.setdefault((label, repr(value), kind), (label, inst, path))
    return list(seen.values())


CASES = _cases()


def test_every_instruction_class_is_swept() -> None:
    from laddercodec.instructions import INSTRUCTION_MODULES

    swept = {label.split(".")[0] for label, *_ in CASES}
    classes = {t.__name__ for spec in INSTRUCTION_MODULES.values() for t in spec.instruction_types}
    assert not classes - swept - NO_TEXT_FIELDS, classes - swept - NO_TEXT_FIELDS
    assert not NO_TEXT_FIELDS & swept, "an exempt class has a text field: sweep it"
    assert {"ModbusAddress", "ModbusRtuTarget", "ModbusTcpTarget"} <= swept
    assert OPAQUE <= swept


@pytest.mark.parametrize("case", CASES, ids=[f"{c[0]}#{i}" for i, c in enumerate(CASES)])
def test_long_digit_text_is_refused_not_a_crash(case: tuple[str, Any, Path_]) -> None:
    label, inst, path = case
    crashes = []
    accepted = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for text in [*IN_RANGE, *OUT_OF_RANGE]:
            try:
                _replace(inst, path, text)
            except FieldError:
                continue
            except Exception as exc:  # noqa: BLE001 - the crash is what this test looks for
                crashes.append(f"{text[:6]}...{text[-6:]}: {type(exc).__name__}: {exc}"[:120])
                continue
            if text in OUT_OF_RANGE and not (label in HUGE_REAL_FIELDS and text in HUGE_REALS):
                accepted.append(text[:6] + "..." + text[-6:])
    assert not crashes, f"{label} crashed: {crashes}"
    if (label, kind_of(inst, label.split(".")[-1])) not in UNCHECKED and label.split(".")[
        0
    ] not in OPAQUE:
        assert not accepted, f"{label} accepted long digit text: {accepted}"


@pytest.mark.parametrize("name", ["receive__rtu_modbus_block", "send__rtu_modbus_block"])
@pytest.mark.parametrize("text", ["7" * 4400, "0" * 4400 + "1", "4" + "7" * 4400])
def test_long_modbus_address_is_refused_through_read_csv(
    name: str, text: str, tmp_path: Path
) -> None:
    from laddercodec import read_csv

    source = (ROOT / "tests" / "fixtures" / "coverage" / "golden" / f"{name}.csv").read_text(
        encoding="utf-8"
    )
    assert "ModbusAddress(address=400001)" in source
    path = tmp_path / "long.csv"
    path.write_text(source.replace("address=400001", f"address={text}"), encoding="utf-8")
    with pytest.raises(FieldError, match="ModbusAddress.address"):
        read_csv(path)


@pytest.mark.parametrize("op", ["=", "<>", "7" * 4400, "DS1", None, ["=="]])
def test_compare_op_outside_the_six_is_refused(op: Any) -> None:
    from laddercodec.instructions import CompareContact

    with pytest.raises(FieldError) as caught:
        CompareContact(op, "DS1", "5")
    error = caught.value
    assert (error.field, error.reason, error.click_id) == ("CompareContact.op", "choice", None)


def test_a_blank_compare_op_is_missing() -> None:
    from laddercodec.instructions import CompareContact

    with pytest.raises(FieldError) as caught:
        CompareContact("", "DS1", "5")
    error = caught.value
    assert (error.field, error.reason, error.click_id) == ("CompareContact.op", "missing", None)


@pytest.mark.parametrize("op", ["==", "!=", "<", ">", "<=", ">="])
def test_compare_op_the_six_are_accepted(op: str) -> None:
    from laddercodec.instructions import CompareContact

    assert CompareContact(op, "DS1", "5").build_blob()
