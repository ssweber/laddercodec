"""Every refusal in ``src/`` names its code.

The guard finds each function, method and error class whose signature has a required
keyword-only ``code`` parameter, such as ``FieldError``, ``LayoutError``,
``Refusals.refuse`` and ``_refusal``. Every call of one of them in ``src/`` must pass
``code=``, so that each place that makes a refusal chooses its code. A function passed to
``check.run(...)`` or ``check(...)`` counts as called there. A call of a parameter annotated
``type[FieldError]``, or ``type[C]`` for another error class that takes ``code``, counts as
a call of that class. For example, ``cls(...)`` in ``_blank`` builds a refusal just as
``FieldError(...)`` does. Any call without a code fails the test. :data:`ALLOWED` lists
no such call and must stay empty.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "laddercodec"

#: Maps ``file:name`` to the number of calls allowed without ``code=``. It is empty because
#: every refusal names its code.
ALLOWED: dict[str, int] = {}


def _takes_code(args: ast.arguments) -> bool:
    """Return whether a signature has ``code`` as a required keyword-only parameter."""
    return any(
        arg.arg == "code" and default is None
        for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)
    )


def code_takers(trees: list[ast.Module]) -> tuple[set[str], set[str], set[str]]:
    """Return the names whose calls must pass ``code=``, as (functions, classes, methods).

    A class is included when its ``__init__`` requires ``code``. It is also included when it
    subclasses an included class and defines no ``__init__`` of its own.
    """
    functions: set[str] = set()
    classes: set[str] = set()
    methods: set[str] = set()
    bases: dict[str, list[str]] = {}
    own_init: set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases[node.name] = [b.id for b in node.bases if isinstance(b, ast.Name)]
                for item in node.body:
                    if not isinstance(item, ast.FunctionDef):
                        continue
                    if item.name == "__init__":
                        own_init.add(node.name)
                        if _takes_code(item.args):
                            classes.add(node.name)
                    elif _takes_code(item.args):
                        methods.add(item.name)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and _takes_code(node.args):
                functions.add(node.name)
    grew = True
    while grew:
        grew = False
        for cls, parents in bases.items():
            if cls not in classes and cls not in own_init and classes.intersection(parents):
                classes.add(cls)
                grew = True
    return functions, classes, methods


def _class_params(tree: ast.Module, classes: set[str]) -> dict[int, set[str]]:
    """Return a dict from the ``id`` of each call node to the parameters that can hold a class
    in *classes*.

    These are the parameters of the functions that enclose the call and are annotated
    ``type[C]``, with ``C`` in *classes*. A call with no such parameter is left out.
    """

    def holds_class(arg: ast.arg) -> bool:
        ann = arg.annotation
        return (
            isinstance(ann, ast.Subscript)
            and isinstance(ann.value, ast.Name)
            and ann.value.id == "type"
            and isinstance(ann.slice, ast.Name)
            and ann.slice.id in classes
        )

    found: dict[int, set[str]] = {}

    def visit(node: ast.AST, held: frozenset[str]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            every = [*args.posonlyargs, *args.args, *args.kwonlyargs]
            held = held | {a.arg for a in every if holds_class(a)}
        if isinstance(node, ast.Call) and held:
            found[id(node)] = set(held)
        for child in ast.iter_child_nodes(node):
            visit(child, held)

    visit(tree, frozenset())
    return found


def calls_without_code(
    source: str,
    functions: set[str],
    classes: set[str],
    methods: set[str],
    filename: str = "<src>",
) -> list[str]:
    """Return ``file:line name`` for each call of a name in the given sets that passes no
    ``code=``.

    A bare ``raise`` of one of the classes counts as such a call.
    """
    missing = []
    tree = ast.parse(source)
    held = _class_params(tree, classes)
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and isinstance(node.exc, (ast.Name, ast.Attribute)):
            exc = node.exc
            name = exc.id if isinstance(exc, ast.Name) else exc.attr
            if name in classes:  # a bare ``raise FieldError`` makes no call, so passes no code
                missing.append(f"{filename}:{node.lineno} {name}")
            continue
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            local = held.get(id(node), set())
            taker = func.id if func.id in functions | classes | local else None
        elif isinstance(func, ast.Attribute):
            taker = func.attr if func.attr in classes | methods else None
        else:
            taker = None
        # check.run(f, ...) and check("field", f, ...) call f with the arguments after it.
        if taker is None and node.args:
            passed = [a.id for a in node.args[:2] if isinstance(a, ast.Name)]
            taker = next((p for p in passed if p in functions), None)
        if taker is None:
            continue
        if any(kw.arg in ("code", None) for kw in node.keywords):
            continue
        missing.append(f"{filename}:{node.lineno} {taker}")
    return missing


def _sources() -> list[tuple[str, str]]:
    return [
        (path.relative_to(SRC).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(SRC.rglob("*.py"))
    ]


def test_the_guard_finds_the_code_takers() -> None:
    functions, classes, methods = code_takers([ast.parse(text) for _, text in _sources()])
    expected = {"FieldError", "AddressError", "NotANumber", "NotDisplayForm", "LayoutError"}
    assert expected <= classes, expected - classes
    assert {"_refusal", "_error", "_check_pair"} <= functions
    assert {"refuse", "error"} <= methods


def test_every_refusal_passes_code() -> None:
    sources = _sources()
    takers = code_takers([ast.parse(text) for _, text in sources])
    found: dict[str, int] = {}
    for rel, text in sources:
        for entry in calls_without_code(text, *takers, rel):
            key = f"{rel}:{entry.rsplit(' ', 1)[1]}"
            found[key] = found.get(key, 0) + 1
    assert found == ALLOWED, "pass code=Code.<member> at every refusal; without one: " + ", ".join(
        f"{key} ({n})" for key, n in sorted(found.items())
    )


_BAD = """
raise FieldError('x', field='Coil.x')
raise m.LayoutError('x', 'C0001')
check.refuse('kind', 'no', Reason.CHOICE)
check.run(_refusal, 'Copy', ('dest',), 'no', Reason.BANK)
raise FieldError
def _blank(at, cls: type[FieldError] = FieldError):
    return cls('blank', field=at)
"""

_GOOD = """
raise FieldError('x', field='Coil.x', code=Code.BLANK_FIELD)
raise LayoutError('x', code=Code.NO_COIL)
check.refuse('kind', 'no', Reason.CHOICE, code=code)
refuse(error, 'const')  # a local helper named refuse, not the method
isinstance(exc, FieldError)  # a class passed is not a call of it
def _rebuild(cls: type[FieldError], args, code):
    return cls(*args, code=code)
def _other(cls: type[str]):
    return cls('a str, not a refusal')
"""


def test_guard_fails_on_a_refusal_without_code() -> None:
    takers = {"_refusal"}, {"FieldError", "LayoutError"}, {"refuse"}
    assert len(calls_without_code(_BAD, *takers)) == 6
    assert calls_without_code(_GOOD, *takers) == []
