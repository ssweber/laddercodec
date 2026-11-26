"""``lay_out`` draws every laid-out rung of the captures and goldens, byte for byte.

For each rung that the grid layout leaves as it is (``canonical(rung) == [rung]``), the test
reads the rung's circuit as a public :class:`~laddercodec.Circuit`.  ``lay_out`` of that
circuit must encode to the same bytes as the rung.  The rungs are the v4 captures that CLICK
copied back after its syntax check, every other v4 and tumbler capture, and the ladder and
coverage goldens.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from laddercodec import Rung, decode, encode, lay_out
from laddercodec._layout import canonical
from tests.circuit_extract import NoCircuit, circuits_of
from tests.undecoded_captures import without_marker

FIXTURES = Path(__file__).parent / "fixtures"
V4 = FIXTURES / "v4_captures"

#: The v4 captures that CLICK copied back after its syntax check.  Every rung in them is
#: laid out.
CHECKED = sorted(V4.glob("*_checked.bin"))

CORPORA: dict[str, list[Path]] = {
    "v4 checked": CHECKED,
    "v4 other": without_marker(p for p in sorted(V4.rglob("*.bin")) if p not in CHECKED),
    "tumbler": sorted((FIXTURES / "tumbler").rglob("*.clipboard.bin")),
    "ladder golden": sorted((FIXTURES / "ladder_captures" / "golden").glob("*.bin")),
    "coverage golden": sorted((FIXTURES / "coverage" / "golden").glob("*.bin")),
}

#: The number of rungs in each corpus that the grid layout leaves as they are.  A change to
#: the layout that moves a rung out of its layout lowers a count, and the test fails.
LAID_OUT = {
    "v4 checked": 74,
    "v4 other": 293,
    "tumbler": 495,
    "ladder golden": 41,
    "coverage golden": 247,
}


@dataclass
class Tally:
    rungs: int = 0
    laid_out: int = 0
    same: int = 0
    no_circuit: list[str] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)


def _rungs(path: Path) -> list[Rung]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return decode(path.read_bytes())


def _drawing(rung: Rung) -> tuple[object, ...]:
    return rung.conditions, rung.instructions, rung.comment


def round_trip(paths: list[Path]) -> Tally:
    """Return the counts of rungs in *paths*, laid out, and drawn the same by ``lay_out``."""
    tally = Tally()
    for path in paths:
        for index, rung in enumerate(_rungs(path)):
            tally.rungs += 1
            laid = canonical(rung)
            if laid is None or [_drawing(r) for r in laid] != [_drawing(rung)]:
                continue
            tally.laid_out += 1
            where = f"{path.name} rung {index}"
            try:
                (circuit,) = circuits_of(rung)
            except NoCircuit as exc:
                tally.no_circuit.append(f"{where}: {exc}")
                continue
            got = lay_out(circuit)
            if len(got) == 1 and encode(got) == encode(rung):
                tally.same += 1
            else:
                tally.mismatches.append(where)
    return tally


@pytest.mark.parametrize("name", sorted(CORPORA))
def test_lay_out_draws_every_laid_out_rung(name: str) -> None:
    tally = round_trip(CORPORA[name])
    assert tally.mismatches == []
    assert tally.no_circuit == []
    assert tally.same == tally.laid_out == LAID_OUT[name]


def test_every_checked_rung_is_laid_out() -> None:
    """Every rung that CLICK copied back after its syntax check takes part."""
    tally = round_trip(CHECKED)
    assert tally.rungs == tally.laid_out == tally.same
