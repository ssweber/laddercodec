"""Test the program rules that check() reports on a Program or a Project.

The bundles are in ``fixtures/program_check/``, and its README says what each one holds.
``EXPECTED`` holds the findings that laddercodec's rules give. CLICK's Syntax Check answer is
recorded for none of these bundles, so every program finding has ``click_id`` None and
``captured`` False.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec import (
    Call,
    Code,
    Coil,
    Contact,
    End,
    Finding,
    ForLoop,
    Next,
    Program,
    Project,
    Return,
    Rung,
    Undecoded,
    check,
    marker_rung,
    read_bundle,
)

FIX = Path(__file__).parent / "fixtures" / "program_check"

PROGRAM_CODES = {
    Code.FOR_WITHOUT_NEXT,
    Code.NEXT_WITHOUT_FOR,
    Code.FOR_NESTING_DEPTH,
    Code.FOR_ONESHOT_INSIDE_LOOP,
    Code.RETURN_INSIDE_LOOP,
    Code.NESTED_CALL,
}

MAIN = "Main Program"

#: Each bundle's findings, as (program, rung, code).  Each is at row 0, column AF.
EXPECTED: dict[str, list[tuple[str, int, Code]]] = {
    "for_without_next": [(MAIN, 0, Code.FOR_WITHOUT_NEXT)],
    "next_without_for": [(MAIN, 1, Code.NEXT_WITHOUT_FOR)],
    "for_and_next_split": [(MAIN, 0, Code.FOR_WITHOUT_NEXT), ("Sub1", 0, Code.NEXT_WITHOUT_FOR)],
    "two_fors_one_next": [(MAIN, 0, Code.FOR_WITHOUT_NEXT)],
    "depth_3": [],
    "depth_4": [(MAIN, 3, Code.FOR_NESTING_DEPTH)],
    "depth_4_through_call": [(MAIN, 3, Code.FOR_NESTING_DEPTH)],
    "depth_3_through_call": [],
    "depth_4_in_subroutine": [("Sub1", 3, Code.FOR_NESTING_DEPTH)],
    "oneshot_inner": [(MAIN, 1, Code.FOR_ONESHOT_INSIDE_LOOP)],
    "oneshot_outer": [],
    "oneshot_through_call": [],
    "return_inside_loop": [("Sub1", 1, Code.RETURN_INSIDE_LOOP)],
    "end_inside_loop": [(MAIN, 1, Code.RETURN_INSIDE_LOOP)],
    "return_after_loop": [],
    "nested_call": [("Sub1", 0, Code.NESTED_CALL)],
    "self_call": [("Sub1", 0, Code.NESTED_CALL)],
    "call_unknown": [],
    "call_other_case": [],
}


def _rung(token: object, contact: str | None = None, comment: str | None = None) -> Rung:
    first = Contact(contact) if contact else "-"
    return Rung([[first] + ["-"] * 30], [token], comment)


def _for(contact: str | None = None, *, oneshot: bool = False) -> Rung:
    return _rung(ForLoop(count="2", oneshot=oneshot), contact)


NEXT = _rung(Next())
OUT = _rung(Coil("Y001"))
END = _rung(End())
RET = _rung(Return())


def _call(name: str, contact: str | None = None) -> Rung:
    return _rung(Call(name), contact)


def _project(main: list[Rung], **subs: list[Rung]) -> Project:
    programs = [Program(name, i, rungs) for i, (name, rungs) in enumerate(subs.items(), start=2)]
    return Project(Program(MAIN, 1, main), programs)


def _found(findings: list[Finding]) -> list[tuple[str | None, int, Code]]:
    return [(f.program, f.rung, f.code) for f in findings]


def test_every_bundle_has_an_expectation() -> None:
    assert sorted(p.name for p in FIX.iterdir() if p.is_dir()) == sorted(EXPECTED)


@pytest.mark.parametrize("case", sorted(EXPECTED))
def test_bundle(case: str) -> None:
    findings = check(read_bundle(FIX / case))
    assert _found(findings) == EXPECTED[case]
    for f in findings:
        assert (f.click_id, f.captured, f.row, f.column) == (None, False, 0, 31)
        assert f.message.startswith("row 0 from 0, column AF: ")
        assert "(CLICK's response to this shape is not captured). " in f.message


def test_messages() -> None:
    def message(case: str) -> str:
        (finding,) = check(read_bundle(FIX / case))
        return finding.message.split("). ", 1)[1]

    assert message("for_without_next") == "Add a next() rung after the last rung of the loop."
    assert message("oneshot_inner").endswith("Write it as for(2).")
    assert message("nested_call") == "Call Sub2 from Main Program."
    (depth,) = check(read_bundle(FIX / "depth_4_through_call"))
    assert "this Call runs Sub1, whose loops nest 1 deep, inside 3 loops" in depth.message
    assert message("return_inside_loop") == "Move the return() rung after the loop's next() rung."
    assert message("end_inside_loop") == "Move the end() rung after the loop's next() rung."


def test_rungs_alone_get_no_program_finding() -> None:
    for case in EXPECTED:
        project = read_bundle(FIX / case)
        for program in [project.main, *project.subroutines]:
            assert not [f for f in check(program.rungs) if f.code in PROGRAM_CODES], case
            assert all(f.program is None for f in check(program.rungs))


def test_a_program_alone_follows_no_call() -> None:
    project = read_bundle(FIX / "depth_4_through_call")
    assert check(project.main) == []
    sub = read_bundle(FIX / "nested_call").subroutines[0]
    (finding,) = check(sub)
    assert (finding.program, finding.code) == ("Sub1", Code.NESTED_CALL)
    assert finding.message.endswith("Call Sub2 from the main program.")


def test_a_program_alone_is_main_by_prog_idx() -> None:
    rungs = [_call("Sub1", "X001"), END]
    assert check(Program(MAIN, 1, rungs)) == []
    assert _found(check(Program("Other", 3, rungs))) == [("Other", 0, Code.NESTED_CALL)]


def test_project_main_is_main_whatever_its_prog_idx() -> None:
    project = Project(Program("Main", 4, [_call("Sub1", "X001"), END]), [Program("Sub1", 1, [RET])])
    assert check(project) == []


def test_a_call_names_its_subroutine_exactly() -> None:
    main = [_for("X001"), _for(), _for(), _call("sub1"), NEXT, NEXT, NEXT, END]
    assert check(_project(main, Sub1=[_for(), OUT, NEXT, RET])) == []
    main[3] = _call("Sub1")
    assert _found(check(_project(main, Sub1=[_for(), OUT, NEXT, RET]))) == [
        (MAIN, 3, Code.FOR_NESTING_DEPTH)
    ]


def test_a_call_counts_the_loops_of_what_its_subroutine_calls() -> None:
    main = [_for("X001"), _call("Sub1"), NEXT, END]
    sub1 = [_for(), _call("Sub2"), NEXT, RET]
    sub2 = [_for(), _for(), OUT, NEXT, NEXT, RET]
    assert _found(check(_project(main, Sub1=sub1, Sub2=sub2))) == [
        (MAIN, 1, Code.FOR_NESTING_DEPTH),
        ("Sub1", 1, Code.NESTED_CALL),
    ]


def test_calls_that_loop_back_end_the_walk() -> None:
    main = [_for("X001"), _for(), _call("Sub1"), NEXT, NEXT, END]
    sub1 = [_for(), _call("Sub2"), NEXT, RET]
    sub2 = [_call("Sub1"), RET]
    assert _found(check(_project(main, Sub1=sub1, Sub2=sub2))) == [
        ("Sub1", 1, Code.NESTED_CALL),
        ("Sub2", 0, Code.NESTED_CALL),
    ]
    own = [_for(), _call("Sub1"), NEXT, RET]
    assert _found(check(_project(main, Sub1=own))) == [("Sub1", 1, Code.NESTED_CALL)]


def test_each_for_past_the_third_gets_a_finding() -> None:
    main = [_for("X001"), _for(), _for(), _for(), _for(), OUT, *[NEXT] * 5, END]
    assert _found(check(_project(main))) == [
        (MAIN, 3, Code.FOR_NESTING_DEPTH),
        (MAIN, 4, Code.FOR_NESTING_DEPTH),
    ]


def test_a_return_after_an_unclosed_for_gets_no_finding() -> None:
    main = [_for("X001"), _for("X002"), _rung(End(), "X003"), NEXT, END]
    assert _found(check(_project(main))) == [
        (MAIN, 0, Code.FOR_WITHOUT_NEXT),
        (MAIN, 2, Code.RETURN_INSIDE_LOOP),
    ]


def test_the_walk_stops_at_an_undecoded_marker() -> None:
    marker = marker_rung(Undecoded("why", 1))
    main = [_for("X001"), marker, _rung(Return(), "X002"), NEXT, NEXT, END]
    assert _found(check(_project(main))) == [(MAIN, 1, Code.UNDECODED_RUNG)]


def test_a_rung_finding_comes_before_the_rung_program_finding() -> None:
    long = _rung(ForLoop(count="2"), "X001", comment="x" * 1500)
    assert _found(check(_project([long, END]))) == [
        (MAIN, 0, Code.COMMENT_TOO_LONG),
        (MAIN, 0, Code.FOR_WITHOUT_NEXT),
    ]


def test_finding_built_by_position_has_no_program() -> None:
    finding = Finding(0, Code.NO_COIL, None, False, None, None, "m")
    assert finding.program is None
