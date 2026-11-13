"""check(): rungs CLICK's syntax check refuses for their lines are reported, never refused.

Ground truth, CLICK v4's syntax check on pasted rungs:

- the bridge (C0001, ``fixtures/layout_check/README.md``);
- layoutthy rung 23 (C0202, then C0001; ``v4_captures/layoutthy_pasted.bin``, copied back
  right after paste), every other rung in that capture accepted;
- the 21-rung layoutq stub (``v4_captures/layoutq_stub.csv``; ``layoutq_pasted.bin`` is its
  copy-back after paste, which changed no rung, then Subroutine01's own ``return()`` rung):
  CLICK's error list is ``_LAYOUTQ_ERRORS`` below, every other rung accepted
  (``layoutq_checked.bin``, the refused rungs deleted);
- the layoutq2 stub (``v4_captures/layoutq2_pasted.bin``, ``layoutq2_checked.bin``) and the
  pyrung topology CSVs: every rung accepted.

The ladder-golden expectations below are the check's rules applied to rungs CLICK pasted but
was never asked to check.
"""

from __future__ import annotations

import re
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

    X010 at zero-based (3, D) is the one contact whose input no line reaches.  The rung's
    first row is blank, and CLICK numbers its rows from 1 after it, so it prints row 3.  Why
    CLICK lists the C0202 line twice is not known; the check reports it once.
    """
    rungs = _rungs(V4 / "layoutthy_pasted.bin")
    findings = check(rungs)
    assert _cells(findings) == [
        (22, "no_rail", "C0202", 3, 3),
        (22, "not_series_parallel", "C0001", None, None),
    ]
    assert findings[0].message.startswith("row 3, column D in CLICK's numbering: ")
    assert findings[0].message.endswith("(CLICK: C0202)")
    assert [f.captured for f in findings] == [True, True]


def test_layoutthy_rungs_click_accepted_have_no_findings() -> None:
    """CLICK's check accepted every pasted layoutthy rung but rung 23 (index 22)."""
    rungs = _rungs(V4 / "layoutthy_pasted.bin")
    assert len(rungs) == 24
    for index, rung in enumerate(rungs):
        if index != 22:
            assert check(rung) == [], index


#: CLICK v4's syntax check output on the pasted layoutq stub, as CLICK printed it (pasted
#: into Subroutine01; rungs and rows count from 1).  Pasting changed no rung.
_LAYOUTQ_ERRORS = """\
Subroutine01 : Rung 12 : error C000A: All inputs of the box instruction must originate from the same branch.
Subroutine01 : Rung 14 : error C000A: All inputs of the box instruction must originate from the same branch.
Subroutine01 : Rung 15 : error C0205: There is no Contact for the Reset input.
Subroutine01 : Rung 16 : error C0212: There is no Contact for the Reset input.
Subroutine01 : Rung 17 : error C0202: Row 2, Column B : Missing line connection.
Subroutine01 : Rung 17 : error C0003: There is no Coil instruction in the rung.
Subroutine01 : Rung 18 : error C0202: Row 2, Column B : Missing line connection.
Subroutine01 : Rung 18 : error C0003: There is no Coil instruction in the rung.
Subroutine01 : Rung 19 : error C0202: Row 1, Column A : Missing line connection.
Subroutine01 : Rung 19 : error C0003: There is no Coil instruction in the rung.
Subroutine01 : Rung 20 : error C0202: Row 1, Column C : Missing line connection.
Subroutine01 : Rung 21 : error C0202: Row 3, Column E : Missing line connection.
Subroutine01 : Rung 21 : error C0001: Line connection error.
"""

_CLICK_LINE = re.compile(r"Rung (\d+) : error (C[0-9A-F]{4}): (?:Row (\d+), Column ([A-Z]+) : )?")


def _click_errors(text: str) -> list[tuple[int, str, str | None]]:
    """(rung from 0, code, CLICK's "row N, column X" or None) per line of CLICK's output."""
    out: list[tuple[int, str, str | None]] = []
    for line in text.splitlines():
        m = _CLICK_LINE.search(line)
        assert m, line
        rung, code, row, column = m.groups()
        out.append((int(rung) - 1, code, f"row {row}, column {column}" if row else None))
    return out


def _as_click(findings: list[Finding]) -> list[tuple[int, str, str | None]]:
    """Each finding as CLICK prints it: the rung, the code, and a C0202 cell."""
    out: list[tuple[int, str, str | None]] = []
    for f in findings:
        assert f.code is not None and f.captured, f
        cell = f.message.split(" in CLICK's numbering")[0] if f.code == "C0202" else None
        out.append((f.rung, f.code, cell))
    return out


def _layoutq_pasted() -> list[Rung]:
    rungs = _rungs(V4 / "layoutq_pasted.bin")
    assert len(rungs) == 22
    assert rungs[21].instructions[0].to_csv() == "return()" and not rungs[21].comment
    return rungs


def test_layoutq_pasted_gets_clicks_errors() -> None:
    """Every rung, code and C0202 cell CLICK printed, in its order, and nothing more."""
    findings = check(_layoutq_pasted())
    assert _as_click(findings) == _click_errors(_LAYOUTQ_ERRORS)


def test_layoutq_stub_csv_matches_the_pasted_capture() -> None:
    """read_csv of the stub gives the findings decode of its copy-back gives."""
    assert check(read_csv(V4 / "layoutq_stub.csv")) == check(_layoutq_pasted()[:21])


def test_layoutq_kinds() -> None:
    findings = check(_layoutq_pasted())
    assert _cells(findings) == [
        (11, "output_above_pinned_box", "C000A", 1, 31),  # Q7a: out, then a retentive timer
        (13, "output_above_pinned_box", "C000A", 1, 31),  # Q7c: out, then a count_down
        (14, "pin_without_contact", "C0205", 1, 31),  # Q4a: timer Reset teed off its input
        (15, "pin_without_contact", "C0212", 1, 31),  # Q4b: drum Reset teed off the Or merge
        (16, "feeds_no_box", "C0202", 1, 1),  # Q6a: C94, the last contact of row 1
        (16, "no_coil", "C0003", None, None),
        (17, "feeds_no_box", "C0202", 1, 1),  # Q6b
        (17, "no_coil", "C0003", None, None),
        (18, "feeds_no_box", "C0202", 0, 0),  # Q6c: C101 into count_down's unused Up
        (18, "no_coil", "C0003", None, None),
        (19, "no_rail", "C0202", 0, 2),  # Q8a: the rail reaches no box, so no C0001
        (20, "no_rail", "C0202", 2, 4),  # Q8b
        (20, "not_series_parallel", "C0001", None, None),
    ]


def test_layoutq_raw_drum_with_a_leg_on_its_jump_row_has_no_findings() -> None:
    """Q3a: CLICK accepted it.  The stub writes the drum as raw(...); its part rows are pins."""
    rung = read_csv(V4 / "layoutq_stub.csv")[6]
    assert type(rung.instructions[0]).__name__ == "RawInstruction"
    assert check(rung) == []


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
        V4 / "layoutq_checked.bin",
        V4 / "layoutq2_pasted.bin",
        V4 / "layoutq2_checked.bin",
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


#: The ladder goldens CLICK's check would refuse: (rung, kind, code, row, column) per finding.
_LADDER_FINDINGS = {
    # Q6a's shape: X003 X004 on row 1 run to an AF cell with no box.
    "instr-2row-cond__and": [
        (0, "feeds_no_box", "C0202", 1, 1),
        (0, "no_coil", "C0003", None, None),
    ],
    "instr-2row-spread": [(0, "feeds_no_box", "C0202", 1, 10), (0, "no_coil", "C0003", None, None)],
    # X001's output joins the rail through B's vertical and the row 2 wire.
    "instr-3row-branch": [(0, "shorted_contact", None, 0, 0), (0, "unpowered_box", None, 1, 31)],
    "instr-3row-scatter": [
        (0, "feeds_no_box", "C0202", 1, 5),
        (0, "feeds_no_box", "C0202", 2, 15),
        (0, "no_coil", "C0003", None, None),
    ],
    # out(Y001) above the timer on one net; the reset is the out(Y001) circuit, the bridge.
    "instr-coil-timer-ret": [
        (0, "output_above_pinned_box", "C000A", 1, 31),
        (0, "pin_without_contact", "C0205", 2, 31),
        (0, "not_series_parallel", "C0001", None, None),
    ],
    # Q4b's shape: the drum's Reset tees off its main input.
    "instr-copy-multirow-2af-T": [(0, "pin_without_contact", "C0212", 1, 31)],
    # The Reset row is a wire from the rail.
    "instr-timer-ret": [(0, "pin_without_contact", "C0205", 1, 31)],
    "mr-cmt-3rung-multirow": [(1, "unpowered_box", None, 1, 31)],
}

#: Findings above whose shape no capture shows with that code.
_UNCAPTURED = {
    ("instr-3row-branch", 0),
    ("instr-3row-branch", 1),
    ("instr-timer-ret", 0),
    ("mr-cmt-3rung-multirow", 0),
}


@pytest.mark.parametrize("path", sorted(LADDER.glob("*.csv")), ids=lambda p: p.stem)
def test_ladder_golden_findings(path: Path) -> None:
    findings = check(read_csv(path))
    assert _cells(findings) == _LADDER_FINDINGS.get(path.stem, [])
    want = [(path.stem, i) not in _UNCAPTURED for i in range(len(findings))]
    assert [f.captured for f in findings] == want


def test_unknown_shapes_say_so() -> None:
    (finding,) = check(read_csv(LADDER / "mr-cmt-3rung-multirow.csv"))
    assert finding.code is None
    assert not finding.captured
    assert finding.message == (
        "row 2, column AF in CLICK's numbering: no rail or contact reaches the box"
        " (CLICK's response to this shape is not captured)"
    )


def test_reset_wired_from_the_rail_is_not_captured() -> None:
    (finding,) = check(read_csv(LADDER / "instr-timer-ret.csv"))
    assert (finding.kind, finding.code, finding.captured) == ("pin_without_contact", "C0205", False)
    assert finding.message == (
        "row 2, column AF in CLICK's numbering: the pin has no contact of its own"
        " (C0205 as for a reset whose contacts are all the main input's;"
        " CLICK's response to this shape is not captured)"
    )


def _contact(name: str, *, down: bool = False) -> Contact:
    return Contact(type=InstructionType.CONTACT_NO, operand=name, wire_down=down)


def _rung(conditions: list[list[object]], instructions: list[object]) -> Rung:
    rows = [row + [""] * (31 - len(row)) for row in conditions]
    return Rung(len(rows), rows, instructions, None)  # type: ignore[arg-type]


def _out(name: str) -> Coil:
    return Coil(type=InstructionType.COIL_OUT, operand=name)


def _timer(*, retained: bool = True) -> Timer:
    return Timer(
        timer_type="on_delay",
        done_bit="T1",
        current="TD1",
        setpoint="1",
        unit="Tms",
        retained=retained,
    )


def _bridge_rows() -> list[list[object]]:
    # X001 X003 | X001 X005 X004 | X002 X004, as wheatstone_bridge.csv draws it
    return [
        [_contact("X001"), _contact("X003", down=True), "-", "T", *["-"] * 27],
        ["", _contact("X005"), "|", "|"],
        [_contact("X002"), "-", _contact("X004")],
    ]


def test_bridge_into_a_pin_is_c0001_at_the_pin() -> None:
    rung = _rung([[_contact("X010"), *["-"] * 30], *_bridge_rows()], [_timer(), "", "", ""])
    (finding,) = check(rung)
    assert _cells([finding]) == [(0, "not_series_parallel", "C0001", 1, 31)]
    assert not finding.captured  # no capture shows CLICK's check on a pin's bridge
    assert finding.message == (
        "row 2, column AF in CLICK's numbering: the pin's circuit is not series-parallel"
        " (C0001 as for a main input; CLICK's response to this shape is not captured)"
    )


def test_pin_with_a_contact_of_its_own_after_the_main_input_is_provisional() -> None:
    """Reset = X001 (the main input's contact), then X002 of its own."""
    rung = _rung(
        [
            [_contact("X001"), "T", *["-"] * 29],
            ["", _contact("X002"), *["-"] * 29],
        ],
        [_timer(), ""],
    )
    (finding,) = check(rung)
    assert _cells([finding]) == [(0, "pin_shares_main", None, 1, 31)]
    assert not finding.captured


def test_box_below_a_pinned_box_on_its_net_is_accepted() -> None:
    """Q7b's order with a used Reset: the timer first, then out(Y001) under its Reset row.

    The vertical from the timer's net down to out(Y001) crosses the Reset row, so the drawing
    joins the two nets: the reset has no contact of its own.  No C000A: no box is above.
    """
    rung = _rung(
        [
            [_contact("X001"), "T", *["-"] * 29],
            ["", "T", *["-"] * 29],
            ["", "-", *["-"] * 29],
        ],
        [_timer(), "", _out("Y001")],
    )
    assert _cells(check(rung)) == [(0, "pin_without_contact", "C0205", 1, 31)]


def test_box_above_a_timer_with_no_reset_is_accepted() -> None:
    """C000A is for a box with a used pin row; a non-retentive timer has none."""
    rung = _rung(
        [[_contact("X001"), "T", *["-"] * 29], ["", "-", *["-"] * 29]],
        [_out("Y001"), _timer(retained=False)],
    )
    assert check(rung) == []


def test_boxes_off_the_rail_are_not_c000a() -> None:
    """out(Y001) and the timer both hang off the rail: CLICK splits them (layoutq Q5)."""
    rung = _rung(
        [["-", "T", *["-"] * 29], ["", "-", *["-"] * 29], [_contact("X002"), *["-"] * 30]],
        [_out("Y001"), _timer(), ""],
    )
    assert check(rung) == []


def test_shorted_contact_is_not_captured() -> None:
    shorted = check(read_csv(LADDER / "instr-3row-branch.csv"))[0]
    assert (shorted.kind, shorted.code, shorted.captured) == ("shorted_contact", None, False)
    assert shorted.message.endswith("(CLICK's response to this shape is not captured)")


def test_contact_after_a_dead_contact_is_not_reported_again() -> None:
    """Q8a with a second contact: C0202 at the first; the rail reaches no box, so no C0001."""
    rung = _rung([["", "", _contact("X001"), _contact("X002"), *["-"] * 27]], [_out("Y001")])
    assert _cells(check(rung)) == [(0, "no_rail", "C0202", 0, 2)]


def test_contacts_in_a_loop_no_rail_reaches_are_c0202_once() -> None:
    """X002 and X001 feed each other through B's vertical and the row 2 wire; A is blank."""
    rung = _rung(
        [
            ["", _contact("X002", down=True), _contact("X001"), "T", *["-"] * 27],
            ["", "|", "", "|"],
            ["", "-", "-"],
        ],
        [_out("Y001"), "", ""],
    )
    assert _cells(check(rung)) == [(0, "no_rail", "C0202", 0, 1)]


def test_dead_contact_beside_a_powered_box_is_c0202_then_c0001() -> None:
    """Q8b's shape: the rail reaches out(Y001), and X002's input has no line connection."""
    rung = _rung(
        [[_contact("X001"), *["-"] * 30], ["", _contact("X002"), *["-"] * 29]],
        [_out("Y001"), _out("Y002")],
    )
    assert _cells(check(rung)) == [
        (0, "no_rail", "C0202", 1, 1),
        (0, "not_series_parallel", "C0001", None, None),
    ]


def test_path_ending_in_a_loop_is_c0202_once() -> None:
    """X001 feeds a loop of X002 and X003 that reaches no box: C0202 at the loop's first."""
    rung = _rung(
        [
            [_contact("X001"), _contact("X002", down=True), _contact("X003"), "T"],
            ["", "|", "", "|"],
            ["", "-", "-"],
            [_contact("X004"), *["-"] * 30],
        ],
        ["", "", "", _out("Y001")],
    )
    assert _cells(check(rung)) == [
        (0, "feeds_no_box", "C0202", 0, 1),
        (0, "no_coil", "C0003", None, None),
    ]


def test_message_rows_count_from_the_first_row_that_is_not_blank() -> None:
    rung = _rung([[], ["", "", _contact("X001"), *["-"] * 28]], ["", _out("Y001")])
    (finding,) = check(rung)
    assert (finding.row, finding.column) == (1, 2)
    assert finding.message.startswith("row 1, column C in CLICK's numbering: ")


def test_one_rung_or_a_list() -> None:
    bridge = read_csv(LC / "wheatstone_bridge.csv")[0]
    plain = read_csv(LADDER / "instr-series.csv")[0]
    assert _cells(check(bridge)) == [(0, "not_series_parallel", "C0001", None, None)]
    assert [f.rung for f in check([plain, plain, bridge])] == [2]


def test_wires_and_unwired_nop_have_no_findings() -> None:
    rung = _rung([["-", "-", "T"], ["", "", "-"]], ["NOP", ""])
    assert check(rung) == []
