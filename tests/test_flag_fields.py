"""Every bool field of an instruction is checked with ``check_flag`` in its ``__post_init__``.

``check_flag`` accepts True, False, 1 and 0 and refuses anything else with ``FieldError``.
The guard finds the bool fields from each class's type hints, and it finds the calls by
parsing the source of each ``__post_init__``.  A bool field with no call fails the guard.
The tests over ``CASES`` give each listed field values that it must refuse and values that it
must accept.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import pkgutil
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
from laddercodec.model import Condition, Instruction, check_flag

_PACKAGE = "laddercodec.instructions"


def _all_subclasses(base: type) -> set[type]:
    found: set[type] = set()
    for sub in base.__subclasses__():
        found.add(sub)
        found |= _all_subclasses(sub)
    return found


def instruction_classes() -> list[type]:
    """Return every dataclass in laddercodec that subclasses ``Condition`` or
    ``Instruction``, sorted by module and name."""
    package = importlib.import_module(_PACKAGE)
    for info in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"{_PACKAGE}.{info.name}")
    classes = _all_subclasses(Condition) | _all_subclasses(Instruction)
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


def _post_init_tree(source: str) -> ast.AST:
    return ast.parse(textwrap.dedent(source))


def flag_checked_fields(source: str, class_name: str) -> set[str]:
    """Return the names of the fields that *source* checks as flags.

    A name ``x`` counts when *source* assigns ``self.x = check_flag(self.x, "<class_name>.x")``.
    Each plain string passed to a call such as ``check.flag("x", ...)`` counts too.  That is
    the form a ``Refusals`` block uses, and the block stores each checked bool back on the
    instance.  A ``check_flag`` call does not count if its result is not stored, if it is
    stored on another field, if it checks another field's value, or if its label is not a
    plain ``"<class_name>.x"``.
    """
    names: set[str] = set()
    for node in ast.walk(_post_init_tree(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "flag"
            and isinstance(node.func.value, ast.Name)
        ):
            names.update(
                arg.value
                for arg in node.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            )
            continue
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target, call = node.targets[0], node.value
        if not (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "check_flag"
            and len(call.args) == 2
        ):
            continue
        value, label = call.args
        if (
            isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id == "self"
            and value.attr == target.attr
            and isinstance(label, ast.Constant)
            and label.value == f"{class_name}.{target.attr}"
        ):
            names.add(target.attr)
    return names


def calls_super_post_init(source: str) -> bool:
    for node in ast.walk(_post_init_tree(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "__post_init__"
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "super"
        ):
            return True
    return False


def is_flag_checked(cls: type, name: str) -> bool:
    """Return whether building ``cls`` runs a flag check on the field ``name``.

    Walk the MRO.  Skip a class that has no ``__post_init__`` of its own.  For a class that
    has one, return True if it checks the field.  Go on to the parent only if it calls
    ``super().__post_init__()``.
    """
    for klass in cls.__mro__:
        post_init = klass.__dict__.get("__post_init__")
        if post_init is None:
            continue
        source = inspect.getsource(post_init)
        if name in flag_checked_fields(source, klass.__name__):
            return True
        if not calls_super_post_init(source):
            return False
    return False


def unchecked_flags(cls: type) -> list[str]:
    return [name for name in bool_fields(cls) if not is_flag_checked(cls, name)]


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
    assert by_class["Copy"] == ["oneshot", "suppress_zero", "exponential"]
    assert by_class["Pack"] == ["allow_whitespace", "oneshot"]
    assert by_class["OutVariant"] == ["immediate", "maintained"]
    assert by_class["Coil"] == ["immediate", "oneshot"]
    assert sum(len(names) for names in by_class.values()) >= 24
    # The token class in math_formula has bool fields but is not an instruction.  The guard
    # collects only subclasses of the instruction base classes, so it never sees the token.
    assert not any(cls.__module__.endswith("math_formula") for cls in instruction_classes())


def test_guard_self_test() -> None:
    @dataclasses.dataclass(frozen=True)
    class Unchecked(Instruction):
        flag: bool = False
        maybe: bool | None = None

        def __post_init__(self) -> None:
            self.flag = check_flag(self.flag, "Unchecked.flag")

    @dataclasses.dataclass(frozen=True)
    class Plain(Instruction):
        count: int = 0

    assert bool_fields(Unchecked) == ["flag", "maybe"]
    assert unchecked_flags(Unchecked) == ["maybe"]
    assert unchecked_flags(Plain) == []
    # Classes made here live in this module, so the real guard never sees them.
    assert Unchecked not in instruction_classes()


def test_guard_counts_only_an_assignment_with_the_class_label() -> None:
    def found(body: str, name: str = "C") -> set[str]:
        source = "def __post_init__(self):\n    " + body + "\n"
        return flag_checked_fields(source, name)

    assert found('self.x = check_flag(self.x, "C.x")') == {"x"}
    assert found('check_flag(self.x, "C.x")') == set()  # result discarded
    assert found('y = check_flag(self.x, "C.x")') == set()  # not stored back
    assert found('self.x = check_flag(self.y, "C.x")') == set()  # another field's value
    assert found('self.x = check_flag(self.x, "C.y")') == set()  # label of another field
    assert found('self.x = check_flag(self.x, "D.x")') == set()  # label of another class
    assert found('self.x = check_flag(self.x, f"C.x")') == set()  # not a plain string
    assert found('check.flag("x", "y")') == {"x", "y"}  # Refusals stores each one back
    assert found('check.flag(f"x")') == set()  # not a plain string


def test_guard_resolves_inherited_checks() -> None:
    @dataclasses.dataclass(frozen=True)
    class Base(Instruction):
        flag: bool = False

        def __post_init__(self) -> None:
            self.flag = check_flag(self.flag, "Base.flag")

    @dataclasses.dataclass(frozen=True)
    class Inherits(Base):
        pass

    @dataclasses.dataclass(frozen=True)
    class Calls(Base):
        def __post_init__(self) -> None:
            super().__post_init__()

    @dataclasses.dataclass(frozen=True)
    class Skips(Base):
        def __post_init__(self) -> None:
            pass

    @dataclasses.dataclass(frozen=True)
    class OwnLabel(Base):
        def __post_init__(self) -> None:
            self.flag = check_flag(self.flag, "OwnLabel.flag")

    assert unchecked_flags(Base) == []
    assert unchecked_flags(Inherits) == []  # no __post_init__ of its own: the parent's runs
    assert unchecked_flags(Calls) == []  # super().__post_init__() runs the parent's
    assert unchecked_flags(Skips) == ["flag"]  # replaces the parent's and never runs it
    assert unchecked_flags(OwnLabel) == []  # its own check, with its own label


def _tcp() -> ModbusRtuTarget:
    return ModbusRtuTarget(name="rtu", com_port="cpu2", device_id=5)


def _modbus(**kw: Any) -> dict[str, Any]:
    return dict(
        target=_tcp(), remote_start="DS1", quantity=5, success="C2", error="C3",
        exception_response="DS100", **kw,
    )  # fmt: skip


CASES: list[tuple[str, Any, str]] = [
    ("Copy", lambda **kw: Copy("DS1", "DS2", **kw), "oneshot"),
    # suppress_zero also takes None, so the non-flag cases here do not apply to it.
    ("Copy", lambda **kw: Copy("DF1", "TXT1", convert="to_text", **kw), "exponential"),
    ("BlockCopy", lambda **kw: BlockCopy("DS1", "DS3", "DS10", "DS12", **kw), "oneshot"),
    ("Fill", lambda **kw: Fill("1", "DS1", "DS5", **kw), "oneshot"),
    ("Pack", lambda **kw: Pack("TXT1", "TXT4", "DS1", "pack_text", **kw), "allow_whitespace"),
    ("Pack", lambda **kw: Pack("C1", "C16", "DS1", **kw), "oneshot"),
    ("Unpack", lambda **kw: Unpack("DS1", "C1", "C16", **kw), "oneshot"),
    ("Search", lambda **kw: Search("DS1", "DS10", "1", "DS20", "C20", "==", **kw), "continuous"),
    ("Search", lambda **kw: Search("DS1", "DS10", "1", "DS20", "C20", "==", **kw), "oneshot"),
    ("Math", lambda **kw: Math("DS1 + 1", "DS2", **kw), "oneshot"),
    ("ForLoop", lambda **kw: ForLoop("3", **kw), "oneshot"),
    ("OutVariant", lambda **kw: OutVariant("toggle", "Y001", **kw), "immediate"),
    # A toggle has no Output Maintained box, and its check of ``kind`` refuses any truthy
    # value on this field.  ``check_flag`` refuses a falsy one, such as None or "".
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
