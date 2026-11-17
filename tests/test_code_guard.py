"""Every refusal in ``src/`` names its code.

A function, method or error class that takes a required keyword-only ``code`` (``FieldError``,
``LayoutError``, ``Refusals.refuse``, ``_refusal``, ...) is found by its signature, and
every call of it in ``src/`` must pass ``code=``: the code is chosen at the refusal site.
A function passed to ``check.run(...)`` or ``check(...)`` counts as called there.  A call
of a parameter annotated ``type[FieldError]`` (or another error class that takes ``code``)
counts as a call of that class: ``_blank``'s ``cls(...)`` builds a refusal as surely as
``FieldError(...)`` does.  A new call without a code fails the test.  :data:`ALLOWED`
lists none and must stay empty.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "laddercodec"

#: ``file:name`` -> calls allowed without ``code=``.  Empty: every refusal names its code.
ALLOWED: dict[str, int] = {}


def _takes_code(args: ast.arguments) -> bool:
    """Whether a signature has ``code`` as a required keyword-only parameter."""
    return any(
        arg.arg == "code" and default is None
        for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)
    )


def code_takers(trees: list[ast.Module]) -> tuple[set[str], set[str], set[str]]:
    """The names a call must pass ``code=`` to: (functions, classes, methods).

    A class takes it when its ``__init__`` does, or when it subclasses one that does and
    defines no ``__init__`` of its own.
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
    """Map each call node, by ``id``, to the parameters of its enclosing functions that hold
    a code-taking class: those annotated ``type[C]`` with ``C`` in *classes*."""

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
    """``file:line name`` of each call of a code taker that passes no ``code=``."""
    missing = []
    tree = ast.parse(source)
    held = _class_params(tree, classes)
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and isinstance(node.exc, (ast.Name, ast.Attribute)):
            exc = node.exc
            name = exc.id if isinstance(exc, ast.Name) else exc.attr
            if name in classes:  # a bare ``raise FieldError``: no call, so no code
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
