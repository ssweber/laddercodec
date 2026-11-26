"""Write src/laddercodec/resources/program_answers.json from CLICK's answered program cases.

    uv run python devtools/gen_program_answers.py

Each case in ``tests/fixtures/program_check/click/`` holds the bundle that was pasted into
CLICK (``program/``), CLICK's saves of it (``pasted/``, ``info/``, ``checked/``) and CLICK's
Syntax Check output (``<case>_errors.txt``).  The table maps the shape of the pasted project,
and the shape of each save, to the program findings that CLICK reported for the case.  A
project's shape is its exact CSV: the name of each program, and every row of every rung, comment
rows included.  A save has the shape of the pasted project, unless CLICK dropped a rung's Call
at the paste.
``check()`` gives a program finding its CLICK id only when the shape of the project that it
checks is in the table, and the table lists that finding.

``tests/test_program_check.py`` fails when the table is out of date.  ``make
program-answers`` rewrites it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "fixtures" / "program_check" / "click"
TABLE = ROOT / "src" / "laddercodec" / "resources" / "program_answers.json"
SAVES = ("pasted", "info", "checked")

#: The cases whose pasted program CLICK changed at the paste: it replaced a rung that holds a
#: Return in Main, or an End in a subroutine, with an empty one.  Its errors answer the saves.
#: They are not its answer for the pasted program, which has no shape in the table.
CHANGED_ON_PASTE = {"f3", "f4"}

_ERROR = re.compile(
    r"(?P<program>.+?) : Rung (?P<rung>\d+) : error (?P<id>C[0-9A-F]{4}):"
    r"(?: Row (?P<row>\d+), Column (?P<column>[A-Z]+) :)?"
)


def click_errors(case: Path) -> list[tuple[str, int, str, int | None]]:
    """Return each error in the Syntax Check output of *case*, in CLICK's order.

    Each error is (program, rung, CLICK id, row), with rung and row counted from 0.
    """
    text = (case / f"{case.name}_errors.txt").read_bytes().decode("ascii")
    errors = []
    for line in text.split("\r\n"):
        m = _ERROR.match(line)
        if m is not None:
            row = int(m["row"]) - 1 if m["row"] else None
            errors.append((m["program"], int(m["rung"]) - 1, m["id"], row))
    return errors


def shapes(case: Path) -> list[Any]:
    """Return the shape of the project pasted in *case*, then the shape of each save that
    differs from it.  A case that CLICK changed on paste has the shapes of its saves only.
    """
    from laddercodec import Project, decode_program, read_bundle
    from laddercodec._program_check import project_shape

    found: list[Any] = []
    if case.name not in CHANGED_ON_PASTE:
        pasted = project_shape(read_bundle(case / "program"))
        if pasted is None:
            raise SystemExit(f"{case.name}: program/ has a cell with no CSV text")
        found.append(pasted)
    for save in SAVES:
        files = sorted((case / save).glob("Scr*.tmp"), key=lambda p: int(p.stem[3:]))
        if files:
            main, *subs = (decode_program(p.read_bytes()) for p in files)
            shape = project_shape(Project(main, subs))
            if shape is None:
                raise SystemExit(f"{case.name}: {save} has a cell with no CSV text")
            if shape not in found:
                found.append(shape)
    return found


def render() -> str:
    """Return the text of the table, from the cases as they are on disk."""
    from laddercodec import CLICK_IDS
    from laddercodec._program_check import PROGRAM_CODES, shape_key

    codes = {CLICK_IDS[code][0]: str(code) for code in PROGRAM_CODES if code in CLICK_IDS}
    by_shape: dict[str, list[Any]] = {}
    lines = []
    for case in sorted(p for p in CASES.iterdir() if p.is_dir()):
        errors = sorted(
            [program, rung, row, codes[click_id]]
            for program, rung, click_id, row in click_errors(case)
            if click_id in codes
        )
        for shape in shapes(case):
            key = shape_key(shape)
            if by_shape.get(key, errors) != errors:
                raise SystemExit(
                    f"{case.name}: CLICK's errors differ from those of another case of the same shape"
                )
            by_shape[key] = errors
            entry = {"case": case.name, "shape": shape, "errors": errors}
            lines.append("  " + json.dumps(entry, separators=(",", ":")))
    about = (
        "Written by devtools/gen_program_answers.py from tests/fixtures/program_check/click/. "
        "Do not edit."
    )
    return (
        '{\n "about": ' + json.dumps(about) + ',\n "cases": [\n' + ",\n".join(lines) + "\n ]\n}\n"
    )


def main() -> int:
    TABLE.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {TABLE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
