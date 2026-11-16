"""Every bool field of an instruction is checked with ``check_flag`` in its ``__post_init__``.

``check_flag`` accepts True, False, 1 and 0 and refuses anything else with ``FieldError``.
The guard finds the bool fields by introspection and the calls by AST, so a new bool field
without its call fails here.  The table tests refuse and accept values field by field.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import textwrap
import types
import typing
from typing import Any

import pytest

from laddercodec import FieldError
from laddercodec.instructions import (
    BlockCopy,
    Copy,
    Fill,
    ForLoop,
    Math,
    OutVariant,
    Pack,
    Receive,
    Search,
    Send,
    Unpack,
)
from laddercodec.instructions.send_receive import ModbusRtuTarget
from laddercodec.model import AfInstruction, ConditionInstruction, check_flag

_PACKAGE = "laddercodec.instructions"


def _all_subclasses(base: type) -> set[type]:
    found: set[type] = set()
    for sub in base.__subclasses__():
        found.add(sub)
        found |= _all_subclasses(sub)
    return found


def instruction_classes() -> list[type]:
    """Every dataclass in laddercodec that is a condition or AF instruction."""
    for name in (
        "contact", "comparison", "coil", "out_variant", "timer", "counter", "shift", "drum",
        "forloop", "copy", "search", "math", "call", "return_", "end", "send_receive", "email",
        "home", "position", "velocity", "raw", "undecoded",
    ):  # fmt: skip
        importlib.import_module(f"{_PACKAGE}.{name}")
    classes = _all_subclasses(ConditionInstruction) | _all_subclasses(AfInstruction)
    return sorted(
        (
            cls
            for cls in classes
            if dataclasses.is_dataclass(cls) and cls.__module__.startswith("laddercodec.")
        ),
        key=lambda cls: (cls.__module__, cls.__qualname__),
    )


def _is_flag_hint(hint: Any) -> bool:
    return hint is bool or (
        typing.get_origin(hint) in (typing.Union, types.UnionType) and bool in typing.get_args(hint)
    )


def bool_fields(cls: type) -> list[str]:
    hints = typing.get_type_hints(cls)
    return [f.name for f in dataclasses.fields(cls) if _is_flag_hint(hints.get(f.name))]


def flag_checked_fields(source: str) -> set[str]:
    """Names ``x`` in ``self.x = check_flag(self.x, ...)`` or ``check_flag(self.x, ...)`` calls."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(textwrap.dedent(source))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "check_flag"
            and node.args
            and isinstance(node.args[0], ast.Attribute)
            and isinstance(node.args[0].value, ast.Name)
            and node.args[0].value.id == "self"
        ):
            names.add(node.args[0].attr)
    return names


def unchecked_flags(cls: type) -> list[str]:
    fields = bool_fields(cls)
    if not fields:
        return []
    post_init = cls.__dict__.get("__post_init__")
    checked = flag_checked_fields(inspect.getsource(post_init)) if post_init else set()
    return [name for name in fields if name not in checked]


def test_every_bool_field_is_checked() -> None:
    missing = {
        f"{cls.__name__}.{name}": "no check_flag(self.<name>, ...) in __post_init__"
        for cls in instruction_classes()
        for name in unchecked_flags(cls)
    }
    assert not missing


def test_guard_finds_the_known_flags() -> None:
    # A guard that finds nothing passes for the wrong reason.
    by_class = {cls.__name__: bool_fields(cls) for cls in instruction_classes()}
    assert by_class["Copy"] == ["oneshot"]
    assert by_class["Pack"] == ["allow_whitespace", "oneshot"]
    assert by_class["OutVariant"] == ["immediate", "maintained"]
    assert by_class["Coil"] == ["immediate", "oneshot"]
    assert sum(len(names) for names in by_class.values()) >= 24
    # math_formula's token has bool fields and is not an instruction: the guard walks the
    # instruction base classes, so it never sees it.
    assert not any(cls.__module__.endswith("math_formula") for cls in instruction_classes())


def test_guard_self_test() -> None:
    @dataclasses.dataclass
    class Unchecked(AfInstruction):
        flag: bool = False
        maybe: bool | None = None

        def __post_init__(self) -> None:
            self.flag = check_flag(self.flag, "Unchecked.flag")

    @dataclasses.dataclass
    class Plain(AfInstruction):
        count: int = 0

    assert bool_fields(Unchecked) == ["flag", "maybe"]
    # The call is found by name; ``maybe`` has none.
    assert flag_checked_fields(inspect.getsource(Unchecked.__post_init__)) == {"flag"}
    assert unchecked_flags(Unchecked) == ["maybe"]
    assert unchecked_flags(Plain) == []
    # Classes made here live in this module, so the real guard never sees them.
    assert Unchecked not in instruction_classes()


def _tcp() -> ModbusRtuTarget:
    return ModbusRtuTarget(name="rtu", com_port="cpu2", device_id=5)


def _modbus(**kw: Any) -> dict[str, Any]:
    return dict(
        target=_tcp(), remote_start="DS1", quantity=5, success="C2", error="C3",
        exception_response="DS100", **kw,
    )  # fmt: skip


CASES: list[tuple[str, Any, str]] = [
    ("Copy", lambda **kw: Copy("DS1", "DS2", **kw), "oneshot"),
    ("BlockCopy", lambda **kw: BlockCopy("DS1", "DS3", "DS10", "DS12", **kw), "oneshot"),
    ("Fill", lambda **kw: Fill("1", "DS1", "DS5", **kw), "oneshot"),
    ("Pack", lambda **kw: Pack("C1", "C16", "DS1", **kw), "allow_whitespace"),
    ("Pack", lambda **kw: Pack("C1", "C16", "DS1", **kw), "oneshot"),
    ("Unpack", lambda **kw: Unpack("DS1", "C1", "C16", **kw), "oneshot"),
    ("Search", lambda **kw: Search("DS1", "DS10", "1", "DS20", "C20", "==", **kw), "continuous"),
    ("Search", lambda **kw: Search("DS1", "DS10", "1", "DS20", "C20", "==", **kw), "oneshot"),
    ("Math", lambda **kw: Math("DS1 + 1", "DS2", **kw), "oneshot"),
    ("ForLoop", lambda **kw: ForLoop("3", **kw), "oneshot"),
    ("OutVariant", lambda **kw: OutVariant("toggle", "Y001", **kw), "immediate"),
    # A toggle has no Output Maintained box, so a truthy value was refused on this field
    # already; a falsy one was accepted.
    ("OutVariant", lambda **kw: OutVariant("toggle", "Y001", **kw), "maintained"),
    ("Send", lambda **kw: Send(**_modbus(source="DS1", sending="C1"), **kw), "word_swap"),
    ("Receive", lambda **kw: Receive(**_modbus(dest="DS1", receiving="C1"), **kw), "word_swap"),
]
_IDS = [f"{name}.{field}" for name, _, field in CASES]


@pytest.mark.parametrize(("name", "build", "field"), CASES, ids=_IDS)
@pytest.mark.parametrize("bad", [2, "yes", 1.0, None, "", -1], ids=repr)
def test_flag_refuses_a_non_flag(name: str, build: Any, field: str, bad: object) -> None:
    with pytest.raises(FieldError) as err:
        build(**{field: bad})
    assert err.value.field == f"{name}.{field}"


@pytest.mark.parametrize(("name", "build", "field"), CASES, ids=_IDS)
@pytest.mark.parametrize("good", [True, False, 1, 0], ids=repr)
def test_flag_accepts_a_flag(name: str, build: Any, field: str, good: object) -> None:
    if (name, field) == ("OutVariant", "maintained"):
        # Only a timed variant has the box, so it is the one that accepts True.
        def build(**kw: Any) -> Any:
            return OutVariant("timed", "C1", on_acc="TD1", on_preset="1", unit="Tms", **kw)

    instr = build(**{field: good})
    assert getattr(instr, field) is bool(good)
