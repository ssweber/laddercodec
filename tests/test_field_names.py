"""Tests that every field name written as a string in the source names a field of its class.

A refusal's ``field`` is ``Class.attr``, or ``Class.attr[i]`` for an item of a list. This
module reads laddercodec's source for each field name written as a string literal, in these
places:

- the ``field=`` argument of an error;
- the field argument of the shared checks and of the display-form helpers;
- the attributes passed to ``check(...)``, ``refuse(...)``, ``flag(...)`` and
  ``normalize(...)`` in a ``Refusals`` block. These name fields of the class whose
  ``__post_init__`` holds the block.

A fixture in ``tests/conftest.py`` checks the refusals that the test suite builds. This
module checks the ones that no test builds.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import re
from collections.abc import Iterator
from pathlib import Path

import laddercodec
from laddercodec import instructions, model
from laddercodec.operands import address, checks

SRC = Path(laddercodec.__file__).parent
_FIELD = re.compile(r"([A-Za-z_]\w*)\.([a-z_]\w*)(?:\[\d+\])?")
#: Calls whose second argument is a field name.
_FIELD_SECOND = {
    "check_address",
    "check_operand",
    "check_constant",
    "check_out_target",
    "check_quoted_text",
    "check_flag",
    "normalize_address",
    "check_box_operand",
}
#: The ``Refusals`` methods whose every string argument names an attribute. For ``check(...)``
#: and ``refuse(...)``, only the first argument names one.
_REFUSALS_ALL = {"flag", "normalize", "refused"}


def _classes() -> dict[str, type]:
    found: dict[str, type] = {}
    modules = [
        model,
        address,
        checks,
        instructions,
        *(m for _, m in inspect.getmembers(instructions, inspect.ismodule)),
    ]
    for module in modules:
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if dataclasses.is_dataclass(cls) and cls.__module__.startswith("laddercodec"):
                found[cls.__name__] = cls
    return found


CLASSES = _classes()


def _strings(node: ast.AST) -> Iterator[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.Tuple):
        for item in node.elts:
            yield from _strings(item)


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _refusals_names(tree: ast.AST) -> Iterator[tuple[str, str, int]]:
    """Yield ``(class, attr, line)`` for each attribute named in a call on a ``Refusals``
    block."""
    for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
        for with_ in (n for n in ast.walk(cls) if isinstance(n, ast.With)):
            names = {
                item.optional_vars.id
                for item in with_.items
                if isinstance(item.context_expr, ast.Call)
                and _call_name(item.context_expr) == "Refusals"
                and isinstance(item.optional_vars, ast.Name)
            }
            for call in (n for n in ast.walk(with_) if isinstance(n, ast.Call)):
                func = call.func
                if isinstance(func, ast.Name) and func.id in names and call.args:
                    args = call.args[:1]  # check(attr, fn, ...)
                elif (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id in names
                ):
                    if func.attr in _REFUSALS_ALL:
                        args = call.args
                    elif func.attr == "refuse":
                        args = call.args[:1]
                    else:
                        continue
                else:
                    continue
                for arg in args:
                    for attr in _strings(arg):
                        yield cls.name, attr, call.lineno


def _field_literals(tree: ast.AST) -> Iterator[tuple[str, int]]:
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        for kw in call.keywords:
            if kw.arg == "field":
                for value in _strings(kw.value):
                    yield value, call.lineno
        if _call_name(call) in _FIELD_SECOND and len(call.args) >= 2:
            for value in _strings(call.args[1]):
                yield value, call.lineno
        if _call_name(call) == "to_display" and len(call.args) >= 3:
            for value in _strings(call.args[2]):
                yield value, call.lineno


def problems() -> list[str]:
    found = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        where = path.relative_to(SRC).as_posix()
        for value, line in _field_literals(tree):
            m = _FIELD.fullmatch(value)
            cls = CLASSES.get(m.group(1)) if m else None
            if cls is None or m is None:
                found.append(f"{where}:{line}: {value!r} is no Class.attr")
            elif m.group(2) not in {f.name for f in dataclasses.fields(cls)}:
                found.append(f"{where}:{line}: {value!r}: {cls.__name__} has no field {m.group(2)}")
        for cls_name, attr, line in _refusals_names(tree):
            cls = CLASSES[cls_name]
            name = attr.partition("[")[0]
            if name not in {f.name for f in dataclasses.fields(cls)}:
                found.append(f"{where}:{line}: {cls_name} has no field {name!r}")
    return found


def test_every_literal_field_is_a_dataclass_field() -> None:
    assert problems() == []


def test_the_scan_reads_the_field_names() -> None:
    """The scan finds a sample of each kind of field name that it looks for."""
    tree = ast.parse((SRC / "instructions" / "timer.py").read_text(encoding="utf-8"))
    attrs = {(c, a) for c, a, _ in _refusals_names(tree)}
    assert {("Timer", "retained"), ("Timer", "preset"), ("Timer", "accumulator")} <= attrs
    tree = ast.parse((SRC / "instructions" / "copy.py").read_text(encoding="utf-8"))
    assert "Copy.convert" in {v for v, _ in _field_literals(tree)}
    bad = ast.parse('def f(self):\n    raise FieldError("x", field="Copy.nothing")\n')
    assert [v for v, _ in _field_literals(bad)] == ["Copy.nothing"]
