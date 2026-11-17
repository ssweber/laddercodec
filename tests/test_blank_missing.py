"""A blank required field is refused with the reason ``missing``, never as a bad value.

pyrung tells a blank field from a bad one by the reason on the refusal.  These tests take
every instruction that the golden CSV files decode to (see ``devtools/field_sweep.py``).  They
blank each text field, and each text item of a list field, one at a time.  Every refusal that
names the blanked field must have the reason ``missing``.  A field that may be blank must be
accepted and listed in ``ACCEPTS_BLANK``.  The instructions come from the golden files, so the
tests cover an instruction class or field as soon as a golden file uses it.
"""

from __future__ import annotations

import dataclasses
import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from laddercodec import FieldError, Reason
from tests.sweep_keys import kind_of

ROOT = Path(__file__).resolve().parents[1]


def _sweep() -> Any:
    spec = importlib.util.spec_from_file_location(
        "field_sweep", ROOT / "devtools" / "field_sweep.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INSTRUCTIONS = _sweep().golden_instructions()


def _set(name: str, value: Any, *, nested: bool = False) -> Callable[[Any], Any]:
    """Return a function that rebuilds an instruction with the field ``name`` set to ``value``.

    With ``nested``, ``value`` is itself a rebuild function, and the field is set to what it
    returns for the object that the field holds."""

    def rebuild(inst: Any) -> Any:
        new = value(getattr(inst, name)) if nested else value
        return dataclasses.replace(inst, **{name: new})

    return rebuild


def _blanks(inst: Any) -> list[tuple[str, Callable[[Any], Any]]]:
    """Return a ``(field, rebuild)`` pair for each text field and each text item of a list
    field of ``inst``, and of a target or remote address that ``inst`` holds.

    ``rebuild(inst)`` builds ``inst`` again with that field or item blank."""
    found: list[tuple[str, Callable[[Any], Any]]] = []
    cls = type(inst).__name__
    for f in dataclasses.fields(inst):
        if not f.init:
            continue
        value = getattr(inst, f.name)
        if isinstance(value, str):
            found.append((f"{cls}.{f.name}", _set(f.name, "")))
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            # The field holds a target or a remote address.  Blank its text fields too.
            for inner, rebuild in _blanks(value):
                found.append((inner, _set(f.name, rebuild, nested=True)))
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                if isinstance(item, str):
                    items = list(value)
                    items[i] = ""
                    found.append((f"{cls}.{f.name}[{i}]", _set(f.name, type(value)(items))))
    return found


#: The fields that each kind of instruction accepts blank, as ``(class, kind, field)``.  An item
#: of a list is keyed by its list.  ``kind`` is the value that ``kind_of`` returns.  A blank in
#: any other field must be refused as ``missing``.  A test fails if an instruction accepts a
#: blank that is not listed here, and also if no accepted blank matches an entry listed here.
ACCEPTS_BLANK = frozenset(
    {
        ("Drum", "event_drum", "accumulator"),  # an event drum has none
        ("Drum", "event_drum", "unit"),
        ("Drum", "time_event_drum", "events"),  # a step with a duration needs no event
        ("Drum", "time_event_drum", "presets"),  # and one with an event needs no duration
        # A drum accepts a blank jump step only with the jump off.  With the jump on, the
        # drum checks the jump step.
        *(
            ("Drum", f"{kind}, jump off", "jump_step")
            for kind in ("event_drum", "time_drum", "time_event_drum")
        ),
        ("ModbusRtuTarget", None, "name"),  # the name is a label and is not in the binary
        ("ModbusTcpTarget", None, "name"),
        ("OutVariant", "toggle", "on_acc"),  # a toggle has none of the five
        ("OutVariant", "toggle", "on_preset"),
        ("OutVariant", "toggle", "off_acc"),
        ("OutVariant", "toggle", "off_preset"),
        ("OutVariant", "toggle", "unit"),
        ("OutVariant", "timed", "off_acc"),  # a timed box has an on phase only
        ("OutVariant", "timed", "off_preset"),
        ("RawInstruction", None, "class_name"),
        *(
            (cls, None, field)  # each is an optional status bit
            for cls, fields in {
                "Receive": ("error", "exception_response", "receiving", "success"),
                "Send": ("error", "exception_response", "sending", "success"),
            }.items()
            for field in fields
        ),
    }
)


def _key(inst: Any, field: str) -> tuple[str, str | None, str]:
    """Return the ``ACCEPTS_BLANK`` key for blanking ``field`` of ``inst``.

    ``field`` is ``Class.attr`` or ``Class.attr[i]``."""
    cls, _, attr = field.partition(".")
    attr = attr.split("[")[0]
    return cls, kind_of(inst, attr), attr


def _cases() -> list[Any]:
    cases = []
    for key, inst in INSTRUCTIONS.items():
        for field, rebuild in _blanks(inst):
            cases.append(pytest.param(inst, field, rebuild, id=f"{key}-{field}"))
    return cases


def test_the_goldens_give_blanks_to_try() -> None:
    assert len(_cases()) > 1000
    fields = {case.values[1] for case in _cases()}
    assert {"ModbusTcpTarget.ip", "ModbusRtuTarget.com_port"} <= fields


@pytest.mark.parametrize(("inst", "field", "rebuild"), _cases())
def test_a_blank_field_is_missing(inst: Any, field: str, rebuild: Callable[[Any], Any]) -> None:
    try:
        rebuild(inst)
    except FieldError as exc:
        wrong = [e for e in exc.errors if e.field == field and e.reason is not Reason.MISSING]
        assert not wrong, f"{inst!r} with {field} blank: " + "; ".join(
            f"{e.reason}: {e}" for e in wrong
        )
        for e in exc.errors:
            if e.field == field and len(e.fields) == 1:  # a pair's message names both fields
                assert ": is blank" in str(e), str(e)
    else:
        assert _key(inst, field) in ACCEPTS_BLANK, f"{inst!r} accepts {field} blank"


def test_accepts_blank_lists_only_fields_that_do() -> None:
    accepted = set()
    for case in _cases():
        inst, field, rebuild = case.values
        try:
            rebuild(inst)
        except FieldError:
            continue
        accepted.add(_key(inst, field))
    assert accepted == ACCEPTS_BLANK


def _shared_checks() -> list[Any]:
    from laddercodec.operands.checks import (
        ALL_KINDS,
        Constants,
        check_address,
        check_constant,
        check_operand,
        check_out_target,
        check_quoted_text,
    )

    constants = Constants(ALL_KINDS)
    return [
        lambda: check_address("", "X.f"),
        lambda: check_address("", "X.f", {"DS"}),
        lambda: check_constant("", "X.f", constants),
        lambda: check_operand("", "X.f", {"DS"}, constants),
        lambda: check_operand("", "X.f", {"DS"}, constants, letter_first=True),
        lambda: check_operand("", "X.f", {"DS"}, pointer=True),
        lambda: check_out_target("", "X.f"),
        lambda: check_quoted_text("", "X.f"),
    ]


@pytest.mark.parametrize("call", _shared_checks())
def test_a_shared_check_refuses_a_blank_as_missing(call: Callable[[], Any]) -> None:
    with pytest.raises(FieldError) as raised:
        call()
    assert raised.value.reason is Reason.MISSING
    assert raised.value.field == "X.f"
    assert raised.value.click_id is None
