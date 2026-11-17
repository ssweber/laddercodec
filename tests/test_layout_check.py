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
  pyrung topology CSVs: every rung accepted;
- the 16 rungs of ``layout_check/check_shapes.csv``, compared rung by rung in
  ``test_check_shapes.py``.

The ladder-golden expectations below are the check's rules applied to rungs CLICK pasted but
was never asked to check; ``instr-coil-timer-ret`` is the shape of check_shapes rung 2.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from laddercodec import Finding, Rung, check, decode, encode, read_csv
from laddercodec.csv.contract import CONDITION_COLUMNS, OUTPUT_COLUMN
from laddercodec.csv.converter import convert_literal
from laddercodec.csv.parser import parse_csv_file
from laddercodec.instructions import Coil, Contact, Shift, Timer
from laddercodec.layout_check import _blank_rows
from laddercodec.undecoded import UndecodedRungWarning

FIX = Path(__file__).parent / "fixtures"
LC = FIX / "layout_check"
V4 = FIX / "v4_captures"
LADDER = FIX / "ladder_captures" / "golden"


def _rungs(path: Path) -> list[Rung]:
    if path.suffix == ".csv":
        return read_csv(path)
    got = decode(path.read_bytes())
    return got


def _cells(findings: list[Finding]) -> list[tuple[int, str, str | None, int | None, int | None]]:
    return [(f.rung, f.code, f.click_id, f.row, f.column) for f in findings]


def test_bridge_is_c0001() -> None:
    rungs = read_csv(LC / "wheatstone_bridge.csv")
    findings = check(rungs)
    assert _cells(findings) == [(0, "not-series-parallel", "C0001", None, None)]
    assert findings[0].captured
    encode(rungs)  # reported, not refused: the rung encodes as drawn


def test_layoutthy_rung_23_is_c0202_then_c0001() -> None:
    """CLICK: "Row 3, Column D : Missing line connection" (listed twice), then C0001.

    X010 at zero-based (3, D) is the one contact whose input no line reaches.  The rung's
    first row is blank; read as counting from 1 after it, CLICK's "Row 3" is X010.  That
    reading rests on this rung alone: CLICK may instead name the blank cell (2, D).  Why
    CLICK lists the C0202 line twice is not known; the check reports it once.
    """
    rungs = _rungs(V4 / "layoutthy_pasted.bin")
    findings = check(rungs)
    assert _cells(findings) == [
        (22, "no-rail", "C0202", 3, 3),
        (22, "not-series-parallel", "C0001", None, None),
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
        assert f.click_id is not None and f.captured, f
        cell = f.message.split(" in CLICK's numbering")[0] if f.click_id == "C0202" else None
        out.append((f.rung, f.click_id, cell))
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
    """The stub as written gives the findings decode of its copy-back gives.

    read_csv gives the same findings on more rungs: it splits outputs off the rail
    into rungs of their own, as CLICK's check does, and keeps every reported rung as written.
    """
    pasted = check(_layoutq_pasted()[:21])
    stub = parse_csv_file(V4 / "layoutq_stub.csv").rungs
    assert check([convert_literal(r) for r in stub]) == pasted
    read = read_csv(V4 / "layoutq_stub.csv")
    assert len(read) == 21 + 5
    assert [replace(f, rung=0) for f in check(read)] == [replace(f, rung=0) for f in pasted]


def test_layoutq_kinds() -> None:
    findings = check(_layoutq_pasted())
    assert _cells(findings) == [
        (11, "output-above-box-inputs", "C000A", 1, 31),  # out, then a retentive timer
        (13, "output-above-box-inputs", "C000A", 1, 31),  # out, then a count_down
        (14, "input-without-contact", "C0205", 1, 31),  # timer Reset teed off its input
        (15, "input-without-contact", "C0212", 1, 31),  # drum Reset teed off the Or merge
        (16, "feeds-no-box", "C0202", 1, 1),  # C94, the last contact of row 1
        (16, "no-coil", "C0003", None, None),
        (17, "feeds-no-box", "C0202", 1, 1),
        (17, "no-coil", "C0003", None, None),
        (18, "feeds-no-box", "C0202", 0, 0),  # C101 into count_down's unused Up
        (18, "no-coil", "C0003", None, None),
        (19, "no-rail", "C0202", 0, 2),  # the rail reaches no box, so no C0001
        (20, "no-rail", "C0202", 2, 4),
        (20, "not-series-parallel", "C0001", None, None),
    ]


def test_layoutq_raw_drum_with_a_leg_on_its_jump_row_has_no_findings() -> None:
    """CLICK accepted it.  The stub writes the drum as raw(...); its part rows are pins."""
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

    Its path runs down the AF column, which decode refuses, so the rung decodes as an
    undecoded marker and check reports only that.  layout-afdown (layout phase 2, step 4)
    decodes that flag; this then becomes a "no findings" test.
    """
    with pytest.warns(UndecodedRungWarning):
        rung = decode((V4 / "windy_road_pasted.bin").read_bytes())
    assert [(f.code, f.click_id, f.captured, f.row, f.column) for f in check(rung)] == [
        ("undecoded-rung", None, False, 0, 31)
    ]


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
    # A shape: X003 X004 on row 1 run to an AF cell with no box.
    "instr-2row-cond__and": [
        (0, "feeds-no-box", "C0202", 1, 1),
        (0, "no-coil", "C0003", None, None),
    ],
    # C20 C21 in series feed only a NOP: C0003, as for one contact (accepted_shapes.csv rung 2).
    "instr-cond__and": [(0, "contact-feeds-only-nop", "C0003", None, None)],
    "mr-instr-cond__and": [(0, "contact-feeds-only-nop", "C0003", None, None)],
    "instr-2row-spread": [(0, "feeds-no-box", "C0202", 1, 10), (0, "no-coil", "C0003", None, None)],
    # X001's output joins the rail through B's vertical and the row 2 wire.
    "instr-3row-branch": [(0, "shorted-contact", "C0002", 0, 0), (0, "unpowered-box", None, 1, 31)],
    "instr-3row-scatter": [
        (0, "feeds-no-box", "C0202", 1, 5),
        (0, "feeds-no-box", "C0202", 2, 15),
        (0, "no-coil", "C0003", None, None),
    ],
    # out(Y001) above the timer on one net; the reset is the out(Y001) circuit, the bridge.
    # CLICK reports C0001 alone on this shape (check_shapes.csv rung 2).
    "instr-coil-timer-ret": [(0, "not-series-parallel", "C0001", None, None)],
    # The drum's Reset tees off its main input, and copy(1,DS1) below hangs off that net too:
    # no capture shows a box below the pinned box through a reset teed off its main input.
    "instr-copy-multirow-2af-T": [(0, "shared-input-net", "C000A", 0, 31)],
    # The Reset row is a wire from the rail.
    "instr-timer-ret": [(0, "input-without-contact", "C0205", 1, 31)],
}

#: Findings above whose shape no capture shows with that code.
_UNCAPTURED = {
    ("instr-3row-branch", 1),
    ("instr-copy-multirow-2af-T", 0),
    ("instr-timer-ret", 0),
}


@pytest.mark.parametrize("path", sorted(LADDER.glob("*.csv")), ids=lambda p: p.stem)
def test_ladder_golden_findings(path: Path) -> None:
    findings = check(read_csv(path))
    assert _cells(findings) == _LADDER_FINDINGS.get(path.stem, [])
    want = [(path.stem, i) not in _UNCAPTURED for i in range(len(findings))]
    assert [f.captured for f in findings] == want


def test_unknown_shapes_say_so() -> None:
    _, finding = check(read_csv(LADDER / "instr-3row-branch.csv"))
    assert finding.click_id is None
    assert not finding.captured
    assert finding.message == (
        "row 1 from 0, column AF: no rail or contact reaches the box"
        " (CLICK's response to this shape is not captured)"
    )


def test_reset_wired_from_the_rail_is_not_captured() -> None:
    (finding,) = check(read_csv(LADDER / "instr-timer-ret.csv"))
    assert (finding.code, finding.click_id, finding.captured) == (
        "input-without-contact",
        "C0205",
        False,
    )
    assert finding.message == (
        "row 1 from 0, column AF: the pin has no contact of its own"
        " (C0205 as for a reset whose contacts are all the main input's;"
        " CLICK's response to this shape is not captured)"
    )


def _contact(name: str, *, down: bool = False) -> Contact:
    return Contact(name, wire_down=down)


def _rung(conditions: list[list[object]], instructions: list[object]) -> Rung:
    rows = [row + [""] * (31 - len(row)) for row in conditions]
    return Rung(len(rows), rows, instructions, None)  # type: ignore[arg-type]


def _out(name: str) -> Coil:
    return Coil(name)


def _timer(*, retained: bool = True) -> Timer:
    return Timer(
        kind="on_delay",
        done="T1",
        accumulator="TD1",
        preset="1",
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
    assert _cells([finding]) == [(0, "not-series-parallel", "C0001", 1, 31)]
    assert not finding.captured  # no capture shows CLICK's check on a pin's bridge
    assert finding.message == (
        "row 1 from 0, column AF: the pin's circuit is not series-parallel"
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
    assert _cells([finding]) == [(0, "input-shares-enable", None, 1, 31)]
    assert not finding.captured


def test_box_below_a_pinned_box_through_its_teed_reset_is_provisional_c000a() -> None:
    """The order with a used Reset: the timer first, then out(Y001) under its Reset row.

    The vertical from the timer's net down to out(Y001) crosses the Reset row, so the drawing
    joins the two nets: out(Y001) hangs off the reset's net, which is the main input's net
    too.  No capture shows CLICK's check on this shape.  The reset has no contact of its own
    either; a box reported for C000A gets no pin finding.
    """
    rung = _rung(
        [
            [_contact("X001"), "T", *["-"] * 29],
            ["", "T", *["-"] * 29],
            ["", "-", *["-"] * 29],
        ],
        [_timer(), "", _out("Y001")],
    )
    (finding,) = check(rung)
    assert _cells([finding]) == [(0, "shared-input-net", "C000A", 0, 31)]
    assert not finding.captured
    assert finding.message == (
        "row 0 from 0, column AF: a pin of this box shares its net with another box's input"
        " (C000A as for a box's main input below the pin, on a net of the pin's own;"
        " CLICK's response to this shape is not captured)"
    )


def test_reset_teed_off_its_own_main_input_is_not_c000a() -> None:
    """A box's own inputs on one net join it to no other box: C0205 (layoutq rung 15)."""
    rung = _rung(
        [[_contact("X001"), "T", *["-"] * 29], ["", "-", *["-"] * 29]],
        [_timer(), ""],
    )
    assert _cells(check(rung)) == [(0, "input-without-contact", "C0205", 1, 31)]


@pytest.mark.parametrize("number", [5, 6, 7])
def test_one_c000a_per_group_of_boxes_sharing_nets(number: int) -> None:
    """A pin's net feeds another box's main input below it: CLICK prints one C000A line.

    Rungs 5 and 6 of check_shapes.csv: the counter's Reset net feeds a timer's main input
    (rung 5: the timer's Reset continues from that net too).  Rung 7: a timer's Reset net
    feeds out(C3).  The finding is at the group's first pinned box, and no box of the group
    gets a pin finding: CLICK reports C000A alone on rung 7, where the timer's Reset has no
    contact of its own outside out(C3)'s circuit.
    """
    rung = read_csv(LC / "check_shapes.csv")[number - 1]
    (finding,) = check(rung)
    assert _cells([finding]) == [(0, "shared-input-net", "C000A", 0, 31)]
    assert finding.captured


def test_nop_above_a_pinned_box_on_its_net_is_provisional_c000a() -> None:
    """CLICK accepts a NOP on a coil's net; no capture shows one above a pinned box."""
    rung = _rung(
        [
            [_contact("X001"), "T", *["-"] * 29],
            ["", "-", *["-"] * 29],
            [_contact("X002"), *["-"] * 30],
        ],
        ["NOP", _timer(), ""],
    )
    (finding,) = check(rung)
    assert _cells([finding]) == [(0, "output-above-box-inputs", "C000A", 1, 31)]
    assert not finding.captured


def test_pinned_box_above_a_pinned_box_on_its_net_is_provisional_c000a() -> None:
    """Two retentive timers on one net, the upper one's Reset row crossed by a vertical alone.

    No capture shows a pinned box as the box above.  No rail or contact reaches the upper
    timer's Reset, and its row holds the vertical: C0202 with ``captured`` ``False``.
    """
    rung = _rung(
        [
            [_contact("X001"), "T", *["-"] * 29],
            ["", "|"],
            ["", "-", *["-"] * 29],
            [_contact("X002"), *["-"] * 30],
        ],
        [_timer(), "", _timer(), ""],
    )
    findings = check(rung)
    assert _cells(findings) == [
        (0, "unwired-input", "C0202", 1, 31),
        (0, "output-above-box-inputs", "C000A", 2, 31),
    ]
    assert [f.captured for f in findings] == [False, False]


def test_pin_row_of_wires_no_rail_reaches_is_not_captured() -> None:
    """A Reset row of wires that start at no rail or contact: C0202 as for an empty row."""
    rung = _rung(
        [[_contact("X001"), *["-"] * 30], ["", "", *["-"] * 29]],
        [_timer(), ""],
    )
    (finding,) = check(rung)
    assert _cells([finding]) == [(0, "unwired-input", "C0202", 1, 31)]
    assert not finding.captured
    assert finding.message == (
        "row 1 from 0, column AF: the pin's input has no line connection"
        " (C0202 as for a pin whose row holds nothing; CLICK's response to this shape is not"
        " captured)"
    )


def test_unwired_reset_where_the_rail_reaches_no_box_is_not_captured() -> None:
    rung = _rung(
        [["", _contact("X001"), *["-"] * 29], []],
        [_timer(), ""],
    )
    findings = check(rung)
    assert _cells(findings) == [
        (0, "no-rail", "C0202", 0, 1),
        (0, "unwired-input", "C0202", 1, 31),
    ]
    assert [f.captured for f in findings] == [True, False]
    assert findings[1].message.endswith(
        "(C0202 as for a rung whose rail reaches a box; CLICK's response to this shape is not"
        " captured)"
    )


def test_unwired_reset_is_c0202_at_its_af_cell() -> None:
    """CLICK: "Row 3, Column AF : Missing line connection" for a counter's unwired Reset."""
    rung = read_csv(LC / "check_shapes.csv")[14]
    (finding,) = check(rung)
    assert _cells([finding]) == [(0, "unwired-input", "C0202", 2, 31)]
    assert finding.captured
    assert finding.message == (
        "row 3, column AF in CLICK's numbering: the pin's input has no line connection"
        " (CLICK: C0202)"
    )


def test_unwired_shift_reset_is_not_captured() -> None:
    """No capture shows CLICK's check on a shift's unwired pin; C0202 as for a reset."""
    rows = [
        [_contact("X001"), *["-"] * 30],
        [_contact("X002"), *["-"] * 30],
        [],
    ]
    rung = _rung(rows, [Shift(start_bit="C1", end_bit="C8"), "", ""])
    (finding,) = check(rung)
    assert _cells([finding]) == [(0, "unwired-input", "C0202", 2, 31)]
    assert not finding.captured
    assert finding.message == (
        "row 2 from 0, column AF: the pin's input has no line connection"
        " (C0202 as for a timer's or counter's reset; CLICK's response to this shape is not"
        " captured)"
    )


def test_read_csv_lays_out_a_rung_whose_only_finding_is_an_unwired_pin(tmp_path: Path) -> None:
    """The layout draws an unwired pin's row blank, so read_csv still lays the rung out."""
    header = ",".join(["marker", *CONDITION_COLUMNS, OUTPUT_COLUMN])
    rows = [
        "R," + ",".join(["-", "X001", *["-"] * 29]) + ',"count_up(CT1,CTD1,preset=1)"',
        "," + ",".join([""] * 31) + ",.reset()",
    ]
    path = tmp_path / "unwired.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    (rung,) = read_csv(path)
    assert getattr(rung.conditions[0][0], "operand", None) == "X001"  # packed left
    assert [f.code for f in check(rung)] == ["unwired-input"]


def test_box_above_a_timer_with_no_reset_is_accepted() -> None:
    """C000A is for a box with a used pin row; a non-retentive timer has none."""
    rung = _rung(
        [[_contact("X001"), "T", *["-"] * 29], ["", "-", *["-"] * 29]],
        [_out("Y001"), _timer(retained=False)],
    )
    assert check(rung) == []


def test_boxes_off_the_rail_are_not_c000a() -> None:
    """out(Y001) and the timer both hang off the rail: CLICK splits them."""
    rung = _rung(
        [["-", "T", *["-"] * 29], ["", "-", *["-"] * 29], [_contact("X002"), *["-"] * 30]],
        [_out("Y001"), _timer(), ""],
    )
    assert check(rung) == []


def test_shorted_contact_is_c0002() -> None:
    shorted = check(read_csv(LADDER / "instr-3row-branch.csv"))[0]
    assert (shorted.code, shorted.click_id, shorted.captured) == ("shorted-contact", "C0002", True)
    assert shorted.message.endswith("(CLICK: C0002)")


def test_contact_after_a_dead_contact_is_not_reported_again() -> None:
    """A second contact: C0202 at the first; the rail reaches no box, so no C0001."""
    rung = _rung([["", "", _contact("X001"), _contact("X002"), *["-"] * 27]], [_out("Y001")])
    assert _cells(check(rung)) == [(0, "no-rail", "C0202", 0, 2)]


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
    (finding,) = check(rung)
    assert _cells([finding]) == [(0, "no-rail", "C0202", 0, 1)]
    assert not finding.captured  # no capture shows a loop
    assert finding.message == (
        "row 0 from 0, column B: the contact's input has no line connection"
        " (C0202 as for a contact whose input no contact feeds;"
        " CLICK's response to this shape is not captured)"
    )


def test_dead_contact_beside_a_powered_box_is_c0202_then_c0001() -> None:
    """A shape: the rail reaches out(Y001), and X002's input has no line connection."""
    rung = _rung(
        [[_contact("X001"), *["-"] * 30], ["", _contact("X002"), *["-"] * 29]],
        [_out("Y001"), _out("Y002")],
    )
    assert _cells(check(rung)) == [
        (0, "no-rail", "C0202", 1, 1),
        (0, "not-series-parallel", "C0001", None, None),
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
    findings = check(rung)
    assert _cells(findings) == [
        (0, "feeds-no-box", "C0202", 0, 1),
        (0, "no-coil", "C0003", None, None),
    ]
    assert [f.captured for f in findings] == [False, False]  # no capture shows a loop


def test_no_coil_message_says_what_triggers_it() -> None:
    findings = check(read_csv(LADDER / "instr-2row-spread.csv"))
    assert findings[1].message == (
        "a path from the rail reaches no box"
        " (CLICK's text: no Coil instruction in the rung) (CLICK: C0003)"
    )


def test_message_rows_skip_one_blank_first_row() -> None:
    """A rung with one blank first row counts its rows from the second."""
    rung = _rung([[], ["", "", _contact("X001"), *["-"] * 28]], ["", _out("Y001")])
    (finding,) = check(rung)
    assert (finding.row, finding.column) == (1, 2)
    assert finding.message.startswith("row 1, column C in CLICK's numbering: ")


def test_message_rows_skip_no_more_than_one_blank_row() -> None:
    """Two blank first rows are not known to count the same way; only the first is skipped."""
    rung = _rung([[], [], ["", "", _contact("X001"), *["-"] * 28]], ["", "", _out("Y001")])
    (finding,) = check(rung)
    assert (finding.row, finding.column) == (2, 2)
    assert finding.message.startswith("row 2, column C in CLICK's numbering: ")


def test_blank_first_row_count_takes_a_rung_with_no_outputs() -> None:
    assert _blank_rows(Rung(1, [[""] * 31], [], None)) == 1
    assert _blank_rows(Rung(0, [], [], None)) == 0


def test_one_rung_or_a_list() -> None:
    bridge = read_csv(LC / "wheatstone_bridge.csv")[0]
    plain = read_csv(LADDER / "instr-series.csv")[0]
    assert _cells(check(bridge)) == [(0, "not-series-parallel", "C0001", None, None)]
    assert [f.rung for f in check([plain, plain, bridge])] == [2]


def test_wires_and_unwired_nop_have_no_findings() -> None:
    rung = _rung([["-", "-", "T"], ["", "", "-"]], ["NOP", ""])
    assert check(rung) == []


def test_unpowered_nop_has_no_finding() -> None:
    """CLICK's check dropped the golden's unpowered NOP with no error (unpowered_nop_checked)."""
    ast = parse_csv_file(LADDER / "mr-cmt-3rung-multirow.csv")
    drawn = [convert_literal(r) for r in ast.rungs]
    assert drawn[1].instructions[1] == "NOP"
    assert check(drawn) == []


@pytest.mark.parametrize("box", ["NOP", _out("Y2")], ids=["nop", "coil"])
def test_only_an_unpowered_nop_goes_unreported(box: object) -> None:
    """An unpowered coil keeps its finding: no capture shows CLICK's check on one."""
    stub = ["-"] + [""] * 30
    rung = _rung([[_contact("C1")] + ["-"] * 30, stub], [_out("Y1"), box])
    want = [] if box == "NOP" else [(0, "unpowered-box", None, 1, 31)]
    assert _cells(check(rung)) == want
