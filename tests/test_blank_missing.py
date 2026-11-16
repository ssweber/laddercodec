"""A blank required field is refused as ``missing``, never as a bad value.

pyrung tells a blank field from a bad one by the refusal's reason.  This takes every
instruction the golden CSVs read to (see ``devtools/field_sweep.py``), blanks each text
field and each text item of a list field in turn, and checks every refusal that names the
blanked field: its reason is ``missing``.  A field that may be blank is accepted and
passes.  The instructions come from the goldens, so a new instruction class or field is
covered once a golden uses it.
"""

from __future__ import annotations

import dataclasses
import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from laddercodec import FieldError, Reason

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
    """Rebuild an instruction with ``name`` set to ``value``, or to what ``value`` (a rebuild)
    makes of the object ``name`` holds."""

    def rebuild(inst: Any) -> Any:
        new = value(getattr(inst, name)) if nested else value
        return dataclasses.replace(inst, **{name: new})

    return rebuild


def _blanks(inst: Any) -> list[tuple[str, Callable[[Any], Any]]]:
    """``(field, rebuild)`` for each text field and each text item of ``inst`` blanked, and
    of a target or remote address it holds: ``rebuild(inst)`` builds ``inst`` with it blank."""
    found: list[tuple[str, Callable[[Any], Any]]] = []
    cls = type(inst).__name__
    for f in dataclasses.fields(inst):
        if not f.init:
            continue
        value = getattr(inst, f.name)
        if isinstance(value, str):
            found.append((f"{cls}.{f.name}", _set(f.name, "")))
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            # A target or a remote address: blank its own text fields too.
            for inner, rebuild in _blanks(value):
                found.append((inner, _set(f.name, rebuild, nested=True)))
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                if isinstance(item, str):
                    items = list(value)
                    items[i] = ""
                    found.append((f"{cls}.{f.name}[{i}]", _set(f.name, type(value)(items))))
    return found


#: What each kind of instruction accepts blank, as ``(class, kind, field)`` (an item of a list as
#: its list).  ``kind`` is the OutVariant or Drum kind, ``None`` for a class without one.  A blank
#: anywhere else must be refused as ``missing``; one accepted that is not here fails, and an
#: entry no blank reaches fails too.
ACCEPTS_BLANK = frozenset(
    {
        ("Drum", "event", "accumulator"),  # an event drum has none
        ("Drum", "event", "unit"),
        ("Drum", "time_event", "events"),  # a step with a duration needs no event
        ("Drum", "time_event", "events_or_presets"),  # and one with an event needs no duration
        *(("Drum", kind, "jump_target") for kind in ("event", "time", "time_event")),  # no jump
        ("ModbusRtuTarget", None, "name"),  # a label, not in the binary
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
            (cls, None, field)  # an optional status bit
            for cls, fields in {
                "Receive": ("error", "exception_response", "receiving", "success"),
                "Send": ("error", "exception_response", "sending", "success"),
            }.items()
            for field in fields
        ),
    }
)


def _kind(inst: Any) -> str | None:
    """The OutVariant or Drum kind of ``inst``, ``None`` for a class without one."""
    return getattr(inst, "kind", None) or getattr(inst, "drum_kind", None)


def _key(inst: Any, field: str) -> tuple[str, str | None, str]:
    """The ``ACCEPTS_BLANK`` key of the blank ``field`` (``Class.attr`` or ``Class.attr[i]``)."""
    cls, _, attr = field.partition(".")
    return cls, _kind(inst), attr.split("[")[0]


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
            if e.field == field and len(e.fields) == 1:  # a pair is a rule of two fields
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
