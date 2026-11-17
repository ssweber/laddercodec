"""Every ``FieldError`` and ``AddressError`` call in ``src/`` names its field.

``FieldError.field`` holds exactly what the code that raises the error passes. A refusal that
is about no single field passes ``field=None`` explicitly, so that a reader sees the choice
where the error is raised.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "laddercodec"

_NAMES = frozenset({"FieldError", "AddressError"})


def _called_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def calls_without_field(source: str, filename: str = "<src>", keyword: str = "field") -> list[str]:
    """Return the ``file:line`` of each FieldError or AddressError in *source* with no *keyword*.

    A call that does not pass the *keyword* argument counts, and so does a ``raise`` of the
    class itself with no call.
    """
    missing = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _called_name(node) in _NAMES:
            if not any(kw.arg == keyword for kw in node.keywords):
                missing.append(f"{filename}:{node.lineno}")
        elif isinstance(node, ast.Raise) and isinstance(node.exc, (ast.Name, ast.Attribute)):
            # ``raise FieldError`` with no call passes no field at all.
            exc = node.exc
            if (exc.id if isinstance(exc, ast.Name) else exc.attr) in _NAMES:
                missing.append(f"{filename}:{node.lineno}")
    return missing


def test_every_field_error_passes_field() -> None:
    missing: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        missing += calls_without_field(path.read_text(encoding="utf-8"), rel)
    assert not missing, (
        "pass field=<Class>.<field> (or field=None for a refusal about no single field) at: "
        + ", ".join(missing)
    )


#: Modules in which every FieldError call must pass ``reason=``.
#: The fixture in ``conftest.py`` also checks that each refusal the suite builds for a class in
#: its ``REASONED`` set has a reason.
REASONED_MODULES = ("instructions/math.py", "instructions/math_formula.py")


def test_every_field_error_in_a_reasoned_module_passes_reason() -> None:
    missing: list[str] = []
    for rel in REASONED_MODULES:
        source = (SRC / rel).read_text(encoding="utf-8")
        missing += calls_without_field(source, rel, keyword="reason")
    assert not missing, "pass reason=Reason.<member> at: " + ", ".join(missing)


def test_guard_fails_on_a_call_without_field() -> None:
    bad = "raise FieldError('Coil.x: no')\nraise AddressError('no')\nraise m.FieldError('no')\n"
    good = "raise FieldError('x', field='Coil.x')\nraise AddressError('x', field=None)\n"
    bare = "raise FieldError\nraise errors.AddressError\n"
    assert len(calls_without_field(bad)) == 3
    assert len(calls_without_field(bare)) == 2
    assert calls_without_field(good) == []
