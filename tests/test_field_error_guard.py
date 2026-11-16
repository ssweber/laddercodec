"""Every ``FieldError`` and ``AddressError`` call in ``src/`` names its field.

``FieldError.field`` is exactly what the raiser passes.  A refusal about no single field
passes ``field=None`` on purpose, so the choice shows at the raise site.
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


def calls_without_field(source: str, filename: str = "<src>") -> list[str]:
    """``file:line`` of each FieldError or AddressError call without a ``field=`` keyword."""
    missing = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _called_name(node) in _NAMES:
            if not any(kw.arg == "field" for kw in node.keywords):
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


def test_guard_fails_on_a_call_without_field() -> None:
    bad = "raise FieldError('Coil.x: no')\nraise AddressError('no')\nraise m.FieldError('no')\n"
    good = "raise FieldError('x', field='Coil.x')\nraise AddressError('x', field=None)\n"
    assert len(calls_without_field(bad)) == 3
    assert calls_without_field(good) == []
