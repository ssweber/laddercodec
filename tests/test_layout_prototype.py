"""laddercodec._layout (prototype, not wired into read_csv): CLICK's checked layouts are fixed points.

The full oracle (tumbler, SCR captures, layoutthy, pyrung's topology pairs) is
``scratchpad/layout/oracle.py``; this file keeps the in-repo cases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec import decode
from laddercodec._layout import LayoutError, layout
from laddercodec._layout.network import cell_of
from laddercodec.decode import Rung
from laddercodec.instructions import Coil, Contact
from laddercodec.model import InstructionType

V4 = Path(__file__).parent / "fixtures" / "v4_captures"


def _rungs(name: str) -> list[Rung]:
    got = decode((V4 / name).read_bytes())
    return got if isinstance(got, list) else [got]


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
