"""Compare check() and read_csv with CLICK v4.00's Syntax Check on 16 pasted rungs.

The expected results come from CLICK, as ``fixtures/layout_check/README.md`` describes.
``check_shapes.csv`` was pasted into CLICK as one program of 16 rungs.
``check_shapes_errors.txt`` is the output of CLICK's Syntax Check on that program, and
``check_shapes_checked.scr`` is the program that CLICK saved after the check.

Two tests run on each rung. The first requires that ``check()`` reports the same set of
codes as CLICK, and that it names the same C0202 cells as CLICK. The second requires that
``read_csv`` lays the rung out as CLICK saved it. A rung that is known to differ is listed
in ``CODES_DIFFER`` or ``LAYOUT_DIFFERS`` with the reason. A test fails if a rung differs
and is not listed, and also if a rung is listed and does not differ.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from laddercodec import Rung, check, decode_program, read_csv

LC = Path(__file__).parent / "fixtures" / "layout_check"

#: The shape of each rung, from 1 as CLICK numbers them.
SHAPES = {
    1: "bridge",
    2: "bridge with a timer reset",
    3: "counter, its reset on a contact of its own",
    4: "timer, its reset on a contact of its own",
    5: "a counter's reset also feeding a timer, whose reset continues from it",
    6: "a counter's reset also feeding a timer",
    7: "a timer reset's wire also feeding an output",
    8: "a comment and a NOP",
    9: "a comment and wires",
    10: "a comment only",
    11: "a NOP alone",
    12: "a NOP on the coil's net",
    13: "a NOP on a net of its own beside a coil",
    14: "wires only",
    15: "a counter with its reset unwired",
    16: "a timer with its reset unwired",
}

#: Rungs whose check() codes differ from CLICK's, with the reason.
CODES_DIFFER: dict[int, str] = {}

#: Rungs whose read_csv layout differs from the rung CLICK saved after its check.
LAYOUT_DIFFERS = {
    14: "CLICK's check wires a rung of only wires through AF, stored as a NOP; read_csv keeps"
    " the wires",
}

_LINE = re.compile(r"Rung (\d+) : error (C[0-9A-F]{4}): (?:Row (\d+), Column ([A-Z]+) : )?")


def _click() -> dict[int, list[tuple[str, str | None]]]:
    """Return CLICK's errors for each rung, as (code, cell) pairs.

    The cell is "row N, column X", or None when CLICK names no cell. The error about the
    whole program is left out.
    """
    out: dict[int, list[tuple[str, str | None]]] = {n: [] for n in SHAPES}
    for line in (LC / "check_shapes_errors.txt").read_text(encoding="utf-8").splitlines():
        m = _LINE.search(line)
        assert m, line
        rung, code, row, column = m.groups()
        # C0201 says that the main program has no END. It is about the program, not a rung.
        if code == "C0201":
            assert int(rung) == len(SHAPES) + 1
            continue
        out[int(rung)].append((code, f"row {row}, column {column}" if row else None))
    return out


CLICK = _click()


def _read() -> list[Rung]:
    rungs = read_csv(LC / "check_shapes.csv")
    assert len(rungs) == len(SHAPES)  # the 4-row rung of two boxes reads as rungs 3 and 4
    return rungs


def _saved() -> list[Rung]:
    rungs = decode_program((LC / "check_shapes_checked.scr").read_bytes()).rungs
    assert len(rungs) == len(SHAPES)
    return rungs


def _codes(rung: Rung) -> set[str | None]:
    return {f.click_id for f in check(rung)}


def _c0202_cells(rung: Rung) -> list[str]:
    """Return the cell of each captured C0202 finding from check(), as CLICK prints it."""
    return [
        f.message.split(" in CLICK's numbering")[0]
        for f in check(rung)
        if f.click_id == "C0202" and f.captured
    ]


@pytest.mark.parametrize("number", sorted(SHAPES), ids=lambda n: f"{n}-{SHAPES[n]}")
def test_check_codes_match_click(number: int) -> None:
    rung = _read()[number - 1]
    want = {code for code, _ in CLICK[number]}
    differs = _codes(rung) != want
    assert differs == (number in CODES_DIFFER), (number, _codes(rung), want)
    if not differs:
        cells = [cell for code, cell in CLICK[number] if code == "C0202"]
        assert _c0202_cells(rung) == cells


@pytest.mark.parametrize("number", sorted(SHAPES), ids=lambda n: f"{n}-{SHAPES[n]}")
def test_read_csv_layout_matches_the_rung_click_saved(number: int) -> None:
    read, saved = _read()[number - 1], _saved()[number - 1]
    same = (
        [list(row) for row in read.conditions] == [list(row) for row in saved.conditions]
        and list(read.instructions) == list(saved.instructions)
        and read.comment == saved.comment
    )
    assert same != (number in LAYOUT_DIFFERS), number


def test_differences_name_known_rungs() -> None:
    assert set(CODES_DIFFER) <= set(SHAPES)
    assert set(LAYOUT_DIFFERS) <= set(SHAPES)
