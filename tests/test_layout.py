"""laddercodec._layout: read_csv and write_csv draw rungs as CLICK's syntax check draws them.

Ground truth is CLICK v4's copy-back of pasted rungs before and after its syntax check
(``v4_captures/*_pasted.bin`` and ``*_checked.bin``).  The checked copy has the rungs CLICK
refused deleted, and a rung CLICK split stands as its parts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec import check, decode, read_csv, write_csv
from laddercodec._layout import LayoutError, canonical, circuit, layout
from laddercodec._layout.network import cell_of
from laddercodec.decode import Rung
from laddercodec.instructions import Coil, Contact
from laddercodec.model import InstructionType
from tests.fixtures_refused import is_refused

V4 = Path(__file__).parent / "fixtures" / "v4_captures"
TUMBLER = Path(__file__).parent / "fixtures" / "tumbler"


def _rungs(name: str | Path) -> list[Rung]:
    got = decode((V4 / name).read_bytes())
    return got if isinstance(got, list) else [got]


def _through_csv(rungs: list[Rung], tmp_path: Path) -> list[Rung]:
    path = tmp_path / "rungs.csv"
    write_csv(path, rungs)
    return read_csv(path)


def _drawing(rung: Rung) -> tuple[object, ...]:
    return rung.logical_rows, rung.conditions, rung.instructions, rung.comment


_CHECKED = [
    "layoutthy_checked.bin",
    "layoutq_checked.bin",
    "layoutq2_checked.bin",
    "or_compact_checked.bin",
    "r30_tallbox_checked.bin",
    "windy_road_checked.bin",
]


@pytest.mark.parametrize("name", _CHECKED)
def test_checked_capture_is_a_fixed_point_of_csv(name: str, tmp_path: Path) -> None:
    """What CLICK's check drew writes to CSV and reads back unchanged."""
    rungs = _rungs(name)
    assert [_drawing(r) for r in _through_csv(rungs, tmp_path)] == [_drawing(r) for r in rungs]


@pytest.mark.parametrize(
    ("pasted", "checked"),
    [
        ("layoutthy_pasted.bin", "layoutthy_checked.bin"),
        ("layoutq_pasted.bin", "layoutq_checked.bin"),
        ("layoutq2_pasted.bin", "layoutq2_checked.bin"),
        ("or_compact_pasted.bin", "or_compact_checked.bin"),
        ("r30_tallbox_pasted.bin", "r30_tallbox_checked.bin"),
    ],
)
def test_pasted_capture_reads_back_as_checked(pasted: str, checked: str, tmp_path: Path) -> None:
    """Each rung CLICK accepted writes to CSV and reads back as CLICK's check redrew it."""
    accepted = [r for r in _rungs(pasted) if not check(r)]
    got = _through_csv(accepted, tmp_path)
    assert [_drawing(r) for r in got] == [_drawing(r) for r in _rungs(checked)]


_ALL_CAPTURES = [p for p in sorted(V4.glob("*.bin")) if not is_refused(p)] + sorted(
    TUMBLER.rglob("*.clipboard.bin")
)


@pytest.mark.parametrize("path", _ALL_CAPTURES, ids=lambda p: p.stem)
def test_layout_keeps_the_circuit(path: Path) -> None:
    """The layout moves cells and splits rungs; the circuit it draws is the circuit read."""
    for rung in _rungs(path):
        laid_out = canonical(rung)
        if laid_out is not None:
            assert circuit(laid_out) == circuit([rung]), rung.comment


def _flags(rung: Rung) -> list[list[tuple[str, bool, bool]]]:
    out = []
    for row in rung.conditions:
        cells = []
        for token in row:
            cell = cell_of(token)
            name = cell.contact.to_csv().removeprefix("T:") if cell.contact is not None else ""
            cells.append((name, cell.right, cell.down))
        out.append(cells)
    return out


def _same(a: Rung, b: Rung) -> bool:
    return (
        a.logical_rows == b.logical_rows
        and _flags(a) == _flags(b)
        and [x if isinstance(x, str) else x.to_csv() for x in a.instructions]
        == [x if isinstance(x, str) else x.to_csv() for x in b.instructions]
    )


@pytest.mark.parametrize("name", ["or_compact_checked.bin", "r30_tallbox_checked.bin"])
def test_checked_rungs_are_fixed_points(name: str) -> None:
    for rung in _rungs(name):
        got = layout(rung)
        assert len(got) == 1
        assert _same(got[0], rung)


#: or_compact_pasted rung -> its checked rung(s); CLICK splits pasted rung 1 in two.
_PAIRS = {0: [0], 1: [1, 2], 2: [3], 3: [4], 4: [5]}


@pytest.mark.parametrize("pasted", sorted(_PAIRS))
def test_pasted_rung_lays_out_as_checked(pasted: int) -> None:
    before = _rungs("or_compact_pasted.bin")[pasted]
    after = [_rungs("or_compact_checked.bin")[i] for i in _PAIRS[pasted]]
    got = layout(before)
    assert len(got) == len(after)
    assert all(_same(g, a) for g, a in zip(got, after, strict=True))


def _contact(name: str, *, down: bool = False) -> Contact:
    return Contact(type=InstructionType.CONTACT_NO, operand=name, wire_down=down)


def _rung(conditions: list[list[object]], instructions: list[object]) -> Rung:
    rows = [row + [""] * (31 - len(row)) for row in conditions]
    return Rung(len(rows), rows, instructions, None)  # type: ignore[arg-type]


def test_bridge_is_not_series_parallel() -> None:
    """The Wheatstone bridge: CLICK's check refuses it with C0001."""
    # out(Y001) <= X001 X003 | X001 X005 X004 | X002 X004
    rung = _rung(
        [
            [_contact("X001"), _contact("X003", down=True), "-", "T", *["-"] * 27],
            ["", _contact("X005"), "|", "|"],
            [_contact("X002"), "-", _contact("X004")],
        ],
        [Coil(type=InstructionType.COIL_OUT, operand="Y001"), "", ""],
    )
    with pytest.raises(LayoutError) as info:
        layout(rung)
    assert info.value.code == "C0001"
