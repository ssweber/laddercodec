"""check(): rungs with no CLICK layout are reported, never refused.

Ground truth: CLICK's syntax check refused the bridge (C0001,
``fixtures/layout_check/README.md``) and layoutthy rung 23 (C0202, then C0001;
``v4_captures/layoutthy_pasted.bin``, copied back right after paste), and accepted every
other rung in those captures and in the pyrung topology CSVs. The ladder-golden expectations
below are the check's rules applied to rungs CLICK pasted but was never asked to check (design
questions Q4 and Q6).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec import Finding, Rung, check, decode, encode, read_csv
from laddercodec.decode import DecodeError
from laddercodec.instructions import Coil, Contact, Timer
from laddercodec.model import InstructionType

FIX = Path(__file__).parent / "fixtures"
LC = FIX / "layout_check"
V4 = FIX / "v4_captures"
LADDER = FIX / "ladder_captures" / "golden"


def _rungs(path: Path) -> list[Rung]:
    if path.suffix == ".csv":
        return read_csv(path)
    got = decode(path.read_bytes())
    return got if isinstance(got, list) else [got]


def _cells(findings: list[Finding]) -> list[tuple[int, str, str | None, int | None, int | None]]:
    return [(f.rung, f.kind, f.code, f.row, f.column) for f in findings]


def test_bridge_is_c0001() -> None:
    rungs = read_csv(LC / "wheatstone_bridge.csv")
    findings = check(rungs)
    assert _cells(findings) == [(0, "not_series_parallel", "C0001", None, None)]
    assert findings[0].captured
    encode(rungs)  # reported, not refused: the rung encodes as drawn


def test_layoutthy_rung_23_is_c0202_then_c0001() -> None:
    """CLICK: "Row 3, Column D : Missing line connection" (listed twice), then C0001.

    The codes are CLICK's.  The C0202 cell is the check's own answer, X010 at (3, D), the one
    contact whose input no line reaches: CLICK counts rows from 1 (layoutq Q8a, Q8b), so it
    names zero-based (2, D).  Which cell CLICK names for C0202 is open.
    """
    rungs = _rungs(V4 / "layoutthy_pasted.bin")
    findings = check(rungs)
    assert _cells(findings) == [
        (22, "no_rail", "C0202", 3, 3),
        (22, "not_series_parallel", "C0001", None, None),
    ]
    assert findings[0].message.startswith("row 4, column D in CLICK's numbering: ")
    assert findings[0].message.endswith("(CLICK: C0202)")
    assert [f.captured for f in findings] == [True, True]


def test_layoutthy_rungs_click_accepted_have_no_findings() -> None:
    """CLICK's check accepted every pasted layoutthy rung but rung 23 (index 22)."""
    rungs = _rungs(V4 / "layoutthy_pasted.bin")
    assert len(rungs) == 24
    for index, rung in enumerate(rungs):
        if index != 22:
            assert check(rung) == [], index


@pytest.mark.parametrize(
    "path",
    [
        V4 / "layoutthy_checked.bin",
        V4 / "windy_road_checked.bin",
        LC / "pyrung_topology_saved.csv",
        LC / "pyrung_topology_pasted-2026-11-12.csv",
        LC / "pyrung_topology_pasted-2026-11-13.csv",
        V4 / "or_compact_pasted.bin",
        V4 / "or_compact_checked.bin",
        V4 / "r30_tallbox_pasted.bin",
        V4 / "r30_tallbox_checked.bin",
    ],
    ids=lambda p: p.name,
)
def test_rungs_click_accepted_have_no_findings(path: Path) -> None:
    assert check(_rungs(path)) == []


def test_windy_road_pasted_is_refused_by_decode() -> None:
    """CLICK's check accepted this rung and redrew it as windy_road_checked.bin.

    Its path runs down the AF column, which decode refuses, so there is no Rung to check.
    layout-afdown (layout phase 2, step 4) decodes that flag; this then becomes a
    "no findings" test.
    """
    with pytest.raises(DecodeError):
        decode((V4 / "windy_road_pasted.bin").read_bytes())


_COVERAGE = sorted((FIX / "coverage" / "golden").glob("*.csv")) + sorted(
    (FIX / "coverage" / "subroutines").glob("*.csv")
)


@pytest.mark.parametrize("path", _COVERAGE, ids=lambda p: p.name)
def test_coverage_golden_has_no_findings(path: Path) -> None:
    assert check(read_csv(path)) == []


_TUMBLER = sorted(FIX.glob("tumbler/**/*.clipboard.bin"))


@pytest.mark.parametrize("path", _TUMBLER, ids=lambda p: p.name)
def test_tumbler_program_has_no_findings(path: Path) -> None:
    """Real programs, copied from CLICK (whether after a syntax check is not recorded)."""
    assert check(_rungs(path)) == []


#: The ladder goldens with no layout: (rung, kind, code, row, column) of each finding.
_LADDER_FINDINGS = {
    "instr-2row-cond__and": [(0, "feeds_no_box", None, 1, 0), (0, "feeds_no_box", None, 1, 1)],
    "instr-2row-spread": [(0, "feeds_no_box", None, 1, 10)],
    # X001's output joins the rail through B's vertical and the row 2 wire.
    "instr-3row-branch": [(0, "shorted_contact", None, 0, 0), (0, "unpowered_box", None, 1, 31)],
    "instr-3row-scatter": [(0, "feeds_no_box", None, 1, 5), (0, "feeds_no_box", None, 2, 15)],
    # The reset shares the out(Y001) circuit, which is the bridge.
    "instr-coil-timer-ret": [
        (0, "pin_shares_main", None, 2, 31),
        (0, "not_series_parallel", "C0001", None, None),
    ],
    "instr-copy-multirow-2af-T": [(0, "pin_shares_main", None, 1, 31)],
    "mr-cmt-3rung-multirow": [(1, "unpowered_box", None, 1, 31)],
}


@pytest.mark.parametrize("path", sorted(LADDER.glob("*.csv")), ids=lambda p: p.stem)
def test_ladder_golden_findings(path: Path) -> None:
    findings = check(read_csv(path))
    assert _cells(findings) == _LADDER_FINDINGS.get(path.stem, [])
    # Only the main-circuit C0001 is a shape a CLICK capture shows.
    assert [f.captured for f in findings] == [f.code == "C0001" for f in findings]


def test_unknown_shapes_say_so() -> None:
    (finding,) = check(read_csv(LADDER / "instr-2row-spread.csv"))
    assert finding.code is None
    assert not finding.captured
    assert finding.message == (
        "row 2, column K in CLICK's numbering: the contact's output reaches no box"
        " (CLICK's response to this shape is not captured)"
    )


def _contact(name: str, *, down: bool = False) -> Contact:
    return Contact(type=InstructionType.CONTACT_NO, operand=name, wire_down=down)


def _rung(conditions: list[list[object]], instructions: list[object]) -> Rung:
    rows = [row + [""] * (31 - len(row)) for row in conditions]
    return Rung(len(rows), rows, instructions, None)  # type: ignore[arg-type]


def _bridge_rows() -> list[list[object]]:
    # X001 X003 | X001 X005 X004 | X002 X004, as wheatstone_bridge.csv draws it
    return [
        [_contact("X001"), _contact("X003", down=True), "-", "T", *["-"] * 27],
        ["", _contact("X005"), "|", "|"],
        [_contact("X002"), "-", _contact("X004")],
    ]


def test_bridge_into_a_pin_is_c0001_at_the_pin() -> None:
    timer = Timer(
        timer_type="on_delay",
        done_bit="T1",
        current="TD1",
        setpoint="1",
        unit="Tms",
        retained=True,
    )
    rung = _rung([[_contact("X010"), *["-"] * 30], *_bridge_rows()], [timer, "", "", ""])
    (finding,) = check(rung)
    assert _cells([finding]) == [(0, "not_series_parallel", "C0001", 1, 31)]
    assert not finding.captured  # no capture shows CLICK's check on a pin's bridge
    assert finding.message == (
        "row 2, column AF in CLICK's numbering: the pin's circuit is not series-parallel"
        " (C0001 as for a main input; CLICK's response to this shape is not captured)"
    )


def test_shorted_contact_is_not_captured() -> None:
    shorted = check(read_csv(LADDER / "instr-3row-branch.csv"))[0]
    assert (shorted.kind, shorted.code, shorted.captured) == ("shorted_contact", None, False)
    assert shorted.message.endswith("(CLICK's response to this shape is not captured)")


def test_contact_after_a_dead_contact_is_not_reported_again() -> None:
    rung = _rung(
        [["", "", _contact("X001"), _contact("X002"), *["-"] * 27]],
        [Coil(type=InstructionType.COIL_OUT, operand="Y001")],
    )
    assert _cells(check(rung)) == [
        (0, "no_rail", "C0202", 0, 2),
        (0, "not_series_parallel", "C0001", None, None),
    ]


def test_contacts_in_a_loop_no_rail_reaches_are_c0202_once() -> None:
    """X002 and X001 feed each other through B's vertical and the row 2 wire; A is blank."""
    rung = _rung(
        [
            ["", _contact("X002", down=True), _contact("X001"), "T", *["-"] * 27],
            ["", "|", "", "|"],
            ["", "-", "-"],
        ],
        [Coil(type=InstructionType.COIL_OUT, operand="Y001"), "", ""],
    )
    assert _cells(check(rung)) == [
        (0, "no_rail", "C0202", 0, 1),
        (0, "not_series_parallel", "C0001", None, None),
    ]


def test_one_rung_or_a_list() -> None:
    bridge = read_csv(LC / "wheatstone_bridge.csv")[0]
    plain = read_csv(LADDER / "instr-series.csv")[0]
    assert _cells(check(bridge)) == [(0, "not_series_parallel", "C0001", None, None)]
    assert [f.rung for f in check([plain, plain, bridge])] == [2]


def test_wires_and_unwired_nop_have_no_findings() -> None:
    rung = _rung([["-", "-", "T"], ["", "", "-"]], ["NOP", ""])
    assert check(rung) == []
