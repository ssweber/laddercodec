"""Write docs/guides/codes.md, the error codes page, from ``laddercodec.Code``.

    uv run python docs/gen_codes.py

The page lists each code under the group comment above it in ``src/laddercodec/codes.py``,
with its docstring and its CLICK ids (``CLICK_IDS``).  ``tests/test_codes.py`` fails when the
page is out of date; ``make docs-generate`` rewrites it.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "laddercodec" / "codes.py"
PAGE = ROOT / "docs" / "guides" / "codes.md"

INTRO = """\
<!-- Written by docs/gen_codes.py from laddercodec.Code; edit codes.py, not this page. -->

# Error codes

Every refusal and every `check()` finding names its rule in `code`.
The tables below list every code.

```python
from laddercodec import Coil, FieldError

try:
    Coil("X001")
except FieldError as error:
    print(error.code, error.click_id, error.field)
    # bank-not-allowed OBJ-004 Coil.operand
```

`code` is a `Code`, a string enum. Each code compares equal to its name, so
`error.code == "bank-not-allowed"` is true, and `Code.BANK_NOT_ALLOWED` is the same code.
A `FieldError` lists every refusal of one construction in `errors`, and each refusal has
its own `code`. A `Finding` from `check()` also has a `code`.

`click_id` is CLICK's own id for the error, such as `OBJ-004` or `C0202`. It is `None`
when CLICK has no id for the error or when no id is known. One code can come with several
ids, and the tables list the ids that are known. A `blank-field` refusal has the id of the
check that refused the blank.
"""


def _markdown(text: str) -> str:
    """reStructuredText literals as Markdown code: ``x`` becomes `x`."""
    return re.sub(r"``(.+?)``", r"`\1`", text)


def groups(source: str) -> list[tuple[str, str, list[tuple[str, str, str]]]]:
    """Each group of ``Code``: (heading, lead, [(name, value, docstring)]), in source order."""
    tree = ast.parse(source)
    (cls,) = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Code"]
    lines = source.splitlines()
    found: list[tuple[str, str, list[tuple[str, str, str]]]] = []
    body = cls.body
    last_line = cls.lineno
    for i, node in enumerate(body):
        if not isinstance(node, ast.Assign):
            continue
        for line in lines[last_line : node.lineno - 1]:
            comment = line.strip()
            if comment.startswith("# "):
                heading, _, lead = comment[2:].partition(": ")
                found.append((heading, lead, []))
        (target,) = node.targets
        assert isinstance(target, ast.Name) and isinstance(node.value, ast.Constant)
        doc = body[i + 1] if i + 1 < len(body) else None
        if not (
            isinstance(doc, ast.Expr)
            and isinstance(doc.value, ast.Constant)
            and isinstance(doc.value.value, str)
        ):
            raise SystemExit(f"Code.{target.id} has no docstring")
        found[-1][2].append((target.id, str(node.value.value), doc.value.value))
        last_line = (doc.end_lineno or doc.lineno) if doc else node.lineno
    return found


def render() -> str:
    """The page's text."""
    sys.path.insert(0, str(ROOT / "src"))
    from laddercodec.codes import CLICK_IDS, Code

    out = [INTRO]
    for heading, lead, members in groups(SOURCE.read_text(encoding="utf-8")):
        out.append(f"## {_markdown(heading)}\n")
        if lead:
            lead = _markdown(lead)
            out.append(f"{lead[0].upper()}{lead[1:]}\n")
        out.append("| Code | Meaning | CLICK id |")
        out.append("|---|---|---|")
        for name, value, doc in members:
            ids = ", ".join(CLICK_IDS.get(Code[name], ()))
            out.append(f"| `{value}` | {_markdown(doc)} | {ids} |")
        out.append("")
    return "\n".join(out)


def main() -> None:
    PAGE.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {PAGE.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
