"""Test check(), read_csv, write_csv and encode on rungs that CLICK v4.00 pastes and keeps.

The expected results come from CLICK, as ``fixtures/layout_check/README.md`` describes.
``accepted_shapes.csv``, ``two_wires.csv`` and ``nop_leg.csv`` were each pasted into CLICK.
For each one, ``*_errors.txt`` holds the answer of CLICK's Syntax Check, and
``*_checked.scr`` is the program that CLICK saved after the check. The saved program holds
every rung as it was pasted. Neither CLICK's paste nor laddercodec refuses these rungs. Only
the Syntax Check reports errors on them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from laddercodec import Rung, check, decode_program, encode, read_csv, write_csv

LC = Path(__file__).parent / "fixtures" / "layout_check"

#: The shape of each rung in each file, by rung number. CLICK numbers rungs from 1.
FILES = {
    "accepted_shapes": {
        1: "a contact in parallel with a wire-only leg",
        2: "a contact feeding only a NOP",
        3: "two contacts in parallel feeding only a NOP",
        4: "end",
    },
    "two_wires": {
        1: "a contact feeding a NOP above a contact feeding a coil",
        2: "a contact feeding a coil above a contact feeding a NOP",
        3: "end",
    },
    "nop_leg": {
        1: "a coil on the top leg, a contact into a NOP on the lower leg",
        2: "a contact into a NOP on the top leg, a coil on the lower leg",
        3: "end",
    },
}

CASES = [(name, n) for name, shapes in FILES.items() for n in shapes]

_LINE = re.compile(r"Rung (\d+) : error (C[0-9A-F]{4}): ")


def _click(name: str) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {n: [] for n in FILES[name]}
    for line in (LC / f"{name}_errors.txt").read_text(encoding="utf-8").splitlines():
        m = _LINE.search(line)
        if m:
            out[int(m.group(1))].append(m.group(2))
    return out


def _read(name: str) -> list[Rung]:
    rungs = read_csv(LC / f"{name}.csv")
    assert len(rungs) == len(FILES[name])
    return rungs


def _saved(name: str) -> list[Rung]:
    rungs = decode_program((LC / f"{name}_checked.scr").read_bytes()).rungs
    assert len(rungs) == len(FILES[name])
    return rungs


def _id(case: tuple[str, int]) -> str:
    return f"{case[0]}-{case[1]}-{FILES[case[0]][case[1]]}"


@pytest.mark.parametrize("case", CASES, ids=_id)
def test_check_codes_match_click(case: tuple[str, int]) -> None:
    name, number = case
    findings = check(_read(name)[number - 1])
    assert sorted(f.click_id or "" for f in findings) == sorted(_click(name)[number])
    assert all(f.captured for f in findings)


@pytest.mark.parametrize("case", CASES, ids=_id)
def test_read_csv_is_the_rung_click_saved(case: tuple[str, int]) -> None:
    name, number = case
    read, saved = _read(name)[number - 1], _saved(name)[number - 1]
    assert [list(row) for row in read.conditions] == [list(row) for row in saved.conditions]
    assert list(read.instructions) == list(saved.instructions)
    assert read.comment == saved.comment


@pytest.mark.parametrize("name", FILES)
def test_write_csv_round_trips(name: str, tmp_path: Path) -> None:
    rungs = _read(name)
    out = tmp_path / "again.csv"
    write_csv(out, rungs)
    again = read_csv(out)
    assert len(again) == len(rungs)
    for a, b in zip(rungs, again, strict=True):
        assert [list(r) for r in a.conditions] == [list(r) for r in b.conditions]
        assert list(a.instructions) == list(b.instructions)


@pytest.mark.parametrize("name", FILES)
def test_encode_is_the_payload_click_was_given(name: str) -> None:
    """encode accepts every rung and gives the clipboard payload that was pasted into CLICK."""
    assert encode(_read(name)) == (LC / f"{name}_pasted.clip.bin").read_bytes()


def test_a_mesh_of_contacts_checks_quickly(tmp_path: Path) -> None:
    """read_csv and check() take under 2 s on a rung of 32 rows of 31 contacts.

    Each row ends in out(Y001). Every contact above the last row has a down wire. The
    reachability walk once took 20 s on this rung.
    """
    import time

    head = "marker," + ",".join(
        [chr(65 + i) for i in range(26)] + ["AA", "AB", "AC", "AD", "AE", "AF"]
    )
    rows = [head]
    for r in range(32):
        cells = [("T:" if r < 31 else "") + f"C{col + 1}" for col in range(31)]
        rows.append(",".join(["R" if r == 0 else "", *cells, "out(Y001)"]))
    path = tmp_path / "mesh.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    start = time.perf_counter()
    for rung in read_csv(path):
        check(rung)
    assert time.perf_counter() - start < 2
