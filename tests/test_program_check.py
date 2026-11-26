"""Test the program rules that check() reports on a Program or a Project.

``fixtures/program_check/click/`` holds CLICK v4.00's answers.  Each case holds the program
that was pasted, CLICK's saves of it, and its Syntax Check output.  ``check()`` on those saves
gives each error that CLICK printed, as a captured finding with CLICK's id.  A program finding
is captured only on a project of the same shape as one of these cases.

``fixtures/program_check/own/`` holds bundles that CLICK did not check.  ``OWN`` holds the
findings that laddercodec's rules give for them.  The README says what each one holds.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

from laddercodec import (
    Call,
    Code,
    Coil,
    Condition,
    Contact,
    End,
    Finding,
    ForLoop,
    Next,
    Program,
    Project,
    RawInstruction,
    Return,
    Rung,
    Tee,
    Timer,
    Undecoded,
    UnknownCondition,
    check,
    decode_program,
    marker_rung,
    read_bundle,
)
from laddercodec._program_check import answers, rung_rows
from laddercodec.csv.contract import CONDITION_COLUMNS, OUTPUT_COLUMN

ROOT = Path(__file__).resolve().parents[1]

FIX = Path(__file__).parent / "fixtures" / "program_check"
CLICK = FIX / "click"
CASES = sorted(p.name for p in CLICK.iterdir() if p.is_dir())
SAVES = ("pasted", "info", "checked")

#: CLICK errors whose rules ``check()`` does not report yet: a Call to a missing subroutine,
#: and a Break or a Continue outside a loop.
NOT_BUILT = {"C010C", "C010F", "C0110"}

#: The cases whose Call in a subroutine CLICK dropped at the paste.
DROPPED_CALL = {"q5a", "q5b"}

PROGRAM_CODES = {
    Code.FOR_WITHOUT_NEXT,
    Code.NEXT_WITHOUT_FOR,
    Code.FOR_NESTING_DEPTH,
    Code.FOR_ONESHOT_INSIDE_LOOP,
    Code.RETURN_INSIDE_LOOP,
    Code.NESTED_CALL,
}

MAIN = "Main Program"

#: Each own bundle's findings, as (program, rung, code, click_id).  Each is at row 0, column AF.
OWN: dict[str, list[tuple[str, int, Code, str | None]]] = {
    "depth_3": [],
    "return_after_loop": [],
    "call_other_case": [("Sub1", 0, Code.FOR_NESTING_DEPTH, None)],
}

_ERROR = re.compile(
    r"(?P<program>.+?) : Rung (?P<rung>\d+) : error (?P<id>C[0-9A-F]{4}):"
    r"(?: Row (?P<row>\d+), Column (?P<column>[A-Z]+) :)?"
)
_COLUMNS = (*CONDITION_COLUMNS, OUTPUT_COLUMN)

Error = tuple[str | None, int, str | None, int | None, str | None]


def _click_errors(case: str) -> tuple[list[str], list[Error]]:
    """Return the programs that CLICK's Syntax Check names, in its order, and its errors.

    Each error is (program, rung, CLICK id, row, column), with rung and row counted from 0.
    """
    text = (CLICK / case / f"{case}_errors.txt").read_bytes().decode("ascii")
    lines = text.split("\r\n")
    body = lines[lines.index("Syntax Check...") + 1 : lines.index("")]
    programs: list[str] = []
    errors: list[Error] = []
    for line in body:
        m = _ERROR.match(line)
        if m is None:
            programs.append(line)
            continue
        row = int(m["row"]) - 1 if m["row"] else None
        errors.append((m["program"], int(m["rung"]) - 1, m["id"], row, m["column"]))
    (summary,) = [line for line in lines if " error(s), " in line]
    assert summary.split(" - ")[-1].startswith(f"{len(errors)} error(s)")
    return programs, errors


def _scr_project(folder: Path) -> Project:
    """Return the project that CLICK saved in *folder*: ``Scr1.tmp`` is main, and each
    ``ScrN.tmp`` after it is a subroutine.
    """
    files = sorted(folder.glob("Scr*.tmp"), key=lambda p: int(p.stem[3:]))
    main, *subs = (decode_program(p.read_bytes()) for p in files)
    return Project(main, subs)


def _errors(findings: list[Finding], programs: list[str]) -> list[Error]:
    """Return *findings* as CLICK lists errors: by program, in CLICK's order of *programs*."""
    found = [
        (f.program, f.rung, f.click_id, f.row, None if f.column is None else _COLUMNS[f.column])
        for f in findings
    ]
    return sorted(found, key=lambda e: programs.index(str(e[0])))


def _expected(case: str) -> tuple[list[str], list[Error]]:
    programs, errors = _click_errors(case)
    return programs, [e for e in errors if e[2] not in NOT_BUILT]


def _saves() -> list[tuple[str, str]]:
    return [(case, save) for case in CASES for save in SAVES if (CLICK / case / save).is_dir()]


@pytest.mark.parametrize(("case", "save"), _saves())
def test_check_on_clicks_save_gives_clicks_errors(case: str, save: str) -> None:
    programs, expected = _expected(case)
    findings = check(_scr_project(CLICK / case / save))
    assert _errors(findings, programs) == expected
    assert all(f.captured for f in findings)


@pytest.mark.parametrize("case", sorted(set(CASES) - DROPPED_CALL))
def test_check_on_the_pasted_program_gives_clicks_errors(case: str) -> None:
    programs, expected = _expected(case)
    findings = check(read_bundle(CLICK / case / "program"))
    assert _errors(findings, programs) == expected
    assert all(f.captured for f in findings)


def _load_generator() -> ModuleType:
    path = ROOT / "devtools" / "gen_program_answers.py"
    spec = importlib.util.spec_from_file_location("gen_program_answers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_table_of_answers_is_current() -> None:
    gen = _load_generator()
    text = gen.TABLE.read_text(encoding="utf-8")
    assert text == gen.render(), "run make program-answers"


@pytest.mark.parametrize("case", CASES)
def test_every_case_is_answered_from_its_program_and_its_saves(case: str) -> None:
    _, errors = _click_errors(case)
    ids = {"C0101", "C0102", "C010D", "C0111", "C0115"}
    expected = {(e[0], e[1], e[3]) for e in errors if e[2] in ids}
    projects = [read_bundle(CLICK / case / "program")]
    projects += [_scr_project(CLICK / case / s) for s in SAVES if (CLICK / case / s).is_dir()]
    for project in projects:
        found = answers(project)
        assert found is not None
        assert {(program, rung, row) for program, rung, row, _ in found} == expected


@pytest.mark.parametrize("case", sorted(DROPPED_CALL))
def test_a_call_in_a_subroutine_gets_nested_call(case: str) -> None:
    # CLICK drops the Call when it is pasted, so its saves hold the rung without it.
    (finding,) = check(read_bundle(CLICK / case / "program"))
    assert (finding.program, finding.rung, finding.code) == ("Sub1", 0, Code.NESTED_CALL)
    assert (finding.click_id, finding.captured) == (None, False)
    assert "a paste into CLICK drops it" in finding.message


def test_rules_not_built_yet_are_in_clicks_answers() -> None:
    ids = {e[2] for case in CASES for e in _click_errors(case)[1]}
    assert ids >= NOT_BUILT


def test_every_case_has_an_errors_file_and_a_program() -> None:
    assert CASES
    for case in CASES:
        assert (CLICK / case / f"{case}_errors.txt").is_file(), case
        assert (CLICK / case / "program" / "main.csv").is_file(), case


def test_every_own_bundle_has_an_expectation() -> None:
    assert sorted(p.name for p in (FIX / "own").iterdir() if p.is_dir()) == sorted(OWN)


@pytest.mark.parametrize("case", sorted(OWN))
def test_own_bundle(case: str) -> None:
    findings = check(read_bundle(FIX / "own" / case))
    assert [(f.program, f.rung, f.code, f.click_id) for f in findings] == OWN[case]
    for f in findings:
        assert (f.captured, f.row, f.column) == (f.click_id is not None, 0, 31)


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


def _found(findings: list[Finding]) -> list[tuple[str | None, int, Code, str | None]]:
    return [(f.program, f.rung, f.code, f.click_id) for f in findings]


def _then(finding: Finding) -> str:
    return finding.message.split("). ", 1)[1]


def test_messages() -> None:
    def findings(case: str) -> list[Finding]:
        return check(_scr_project(CLICK / case / "checked"))

    inside, open_for = findings("q1a")
    assert inside.message == (
        "row 0 from 0, column AF: this End is inside the loop that starts on rung 0 from 0 "
        "(CLICK: C0115). Move the end() rung out of the loop."
    )
    assert open_for.message == (
        "row 0 from 0, column AF: the loop that starts on rung 0 from 0 has no Next before "
        "this End (CLICK: C0102). Add a next() rung after the last rung of the loop."
    )
    (stray,) = findings("q1b")
    assert stray.message.endswith(
        "this Next has no open For before it (CLICK: C0101). Delete the Next, or add a For "
        "rung before it, such as for(2)."
    )
    depth, _ = findings("q2a")
    assert "this For would start a 4th loop, inside the loop that starts on rung 2" in depth.message
    assert _then(depth) == (
        "Loops nest at most 3 deep. Move this loop out of the loop that starts on rung 2 from 0."
    )
    (carried,) = findings("q2b")
    assert (
        "this For would start a 4th loop, counting the loops around the Call: Main Program "
        "calls Sub1 on rung 3 from 0 inside 3 loops (CLICK: C010D)" in carried.message
    )
    assert _then(carried) == (
        "Loops nest at most 3 deep, counting the loops around a Call. Move Main Program's Call "
        "on rung 3 from 0 out of the loop that starts on rung 2 from 0."
    )
    (oneshot,) = findings("q3a")
    assert (
        _then(oneshot) == "Only the outermost For of a nest can use One Shot. Write it as for(2)."
    )
    (oneshot,) = findings("q3c")
    assert (
        "this For has One Shot on, and Main Program calls Sub1 on rung 1 from 0 inside 1 loop"
        in oneshot.message
    )
    (nested,) = check(read_bundle(CLICK / "q5a" / "program"))
    assert _then(nested) == "Call Sub2 from Main Program."


def test_rungs_alone_get_no_program_finding() -> None:
    bundles = [CLICK / case / "program" for case in CASES]
    bundles += [FIX / "own" / case for case in OWN]
    for bundle in bundles:
        project = read_bundle(bundle)
        for program in [project.main, *project.subroutines]:
            found = check(program.rungs)
            assert not [f for f in found if f.code in PROGRAM_CODES], bundle
            assert all(f.program is None for f in found)


def test_a_program_alone_counts_no_loops_around_a_call() -> None:
    project = read_bundle(CLICK / "q2b" / "program")
    assert check(project.main) == []
    assert check(project.subroutines[0]) == []


def test_a_subroutine_alone_has_no_captured_finding() -> None:
    sub = read_bundle(CLICK / "q4a" / "program").subroutines[0]
    assert _found(check(sub)) == [("Sub1", 1, Code.RETURN_INSIDE_LOOP, None)]
    sub = read_bundle(CLICK / "q5a" / "program").subroutines[0]
    (finding,) = check(sub)
    assert (finding.program, finding.code) == ("Sub1", Code.NESTED_CALL)
    assert _then(finding) == "Call Sub2 from the main program."


def test_a_program_alone_is_main_by_prog_idx() -> None:
    rungs = [_call("Sub1", "X001"), END]
    assert check(Program(MAIN, 1, rungs)) == []
    assert _found(check(Program("Other", 3, rungs))) == [("Other", 0, Code.NESTED_CALL, None)]
    rungs = [_for("X001"), OUT, END]
    assert [f.click_id for f in check(Program(MAIN, 1, rungs))] == ["C0115", "C0102"]


def test_project_main_is_main_whatever_its_prog_idx() -> None:
    project = Project(Program("Main", 4, [_call("Sub1", "X001"), END]), [Program("Sub1", 1, [RET])])
    assert check(project) == []


def test_a_call_names_its_subroutine_without_regard_to_case() -> None:
    # The finding is not captured, because the Call names Sub1 with other case.
    main = [_for("X001"), _for(), _for(), _call("SUB1"), NEXT, NEXT, NEXT, END]
    assert _found(check(_project(main, Sub1=[_for(), OUT, NEXT, RET]))) == [
        ("Sub1", 0, Code.FOR_NESTING_DEPTH, None)
    ]
    main[3] = _call("Sub1")
    assert _found(check(_project(main, Sub1=[_for(), OUT, NEXT, RET]))) == [
        ("Sub1", 0, Code.FOR_NESTING_DEPTH, "C010D")
    ]
    main[3] = _call("Sub2")
    assert _found(check(_project(main, Sub1=[_for(), OUT, NEXT, RET]))) == []


def test_a_call_in_a_subroutine_carries_no_loops() -> None:
    main = [_for("X001"), _for(), _call("Sub1"), NEXT, NEXT, END]
    sub1 = [_for(), _call("Sub2"), NEXT, RET]
    sub2 = [_for(), _for(), OUT, NEXT, NEXT, RET]
    assert _found(check(_project(main, Sub1=sub1, Sub2=sub2))) == [
        ("Sub1", 1, Code.NESTED_CALL, None)
    ]


def test_a_stray_next_closes_a_loop_around_the_call() -> None:
    # Sub1's first Next closes one of the 2 loops around the Call, and its second the other.
    main = [_for("X001"), _for(), _call("Sub1"), NEXT, NEXT, END]
    assert check(_project(main, Sub1=[NEXT, NEXT, RET])) == []
    assert _found(check(_project(main, Sub1=[NEXT, NEXT, NEXT, RET]))) == [
        ("Sub1", 2, Code.NEXT_WITHOUT_FOR, None)
    ]
    # With 1 of the 2 loops closed, Sub1's own loops can nest 2 deep.
    sub1 = [NEXT, _for(), _for(), OUT, NEXT, NEXT, RET]
    assert check(_project(main, Sub1=sub1)) == []


def test_a_stray_next_in_a_subroutine_called_outside_a_loop_is_not_captured() -> None:
    main = [_call("Sub1", "X001"), END]
    assert _found(check(_project(main, Sub1=[NEXT, RET]))) == [
        ("Sub1", 0, Code.NEXT_WITHOUT_FOR, None)
    ]


def test_a_subroutine_called_from_loops_of_different_depths() -> None:
    # Sub1 is read with the deepest Call's loops, and none of its findings is captured.
    main = [_for("X001"), _call("Sub1"), NEXT, _for(), _for(), _call("Sub1"), NEXT, NEXT, END]
    sub1 = [_for(), _for(), OUT, NEXT, NEXT, RET]
    findings = check(_project(main, Sub1=sub1))
    assert _found(findings) == [("Sub1", 1, Code.FOR_NESTING_DEPTH, None)]
    assert "Main Program calls Sub1 on rung 5 from 0 inside 2 loops" in findings[0].message


def test_an_uncalled_subroutine_has_no_captured_finding() -> None:
    sub1 = [_for(), _for(), _for(), _for(), OUT, NEXT, NEXT, NEXT, NEXT, RET]
    assert _found(check(_project([OUT, END], Sub1=sub1))) == [
        ("Sub1", 3, Code.FOR_NESTING_DEPTH, None),
        ("Sub1", 8, Code.NEXT_WITHOUT_FOR, None),
    ]


def test_inside_a_called_loop_only_the_answered_shapes_are_captured() -> None:
    main = [_for("X001"), _call("Sub1"), NEXT, END]
    # A Return inside Sub1's own loop, with 1 loop around the Call.
    sub1 = [_for(), _rung(Return(), "X002"), NEXT, RET]
    assert _found(check(_project(main, Sub1=sub1))) == [("Sub1", 1, Code.RETURN_INSIDE_LOOP, None)]
    # One Shot on Sub1's second For, with 1 loop around the Call.
    sub1 = [_for(), _for(oneshot=True), OUT, NEXT, NEXT, RET]
    assert _found(check(_project(main, Sub1=sub1))) == [
        ("Sub1", 1, Code.FOR_ONESHOT_INSIDE_LOOP, None)
    ]
    # Sub1's third loop, with 1 loop around the Call.  Its last Next closes the loop around
    # the Call.
    sub1 = [_for(), _for(), _for(), OUT, NEXT, NEXT, NEXT, RET]
    assert _found(check(_project(main, Sub1=sub1))) == [("Sub1", 2, Code.FOR_NESTING_DEPTH, None)]


def test_each_for_past_the_third_gets_a_finding() -> None:
    main = [_for("X001"), _for(), _for(), _for(), _for(), OUT, *[NEXT] * 5, END]
    assert _found(check(_project(main))) == [
        (MAIN, 3, Code.FOR_NESTING_DEPTH, None),
        (MAIN, 4, Code.FOR_NESTING_DEPTH, None),
        (MAIN, 9, Code.NEXT_WITHOUT_FOR, None),
        (MAIN, 10, Code.NEXT_WITHOUT_FOR, None),
    ]


def test_an_open_for_with_no_end_after_it() -> None:
    findings = check(_project([OUT, END, _for("X001"), OUT]))
    assert _found(findings) == [(MAIN, 2, Code.FOR_WITHOUT_NEXT, None)]
    assert "this For has no Next, and no Return or End, after it" in findings[0].message


def test_two_open_loops_at_the_end() -> None:
    main = [_for("X001"), _for("X002"), OUT, END]
    findings = check(_project(main))
    assert _found(findings) == [
        (MAIN, 3, Code.RETURN_INSIDE_LOOP, None),
        (MAIN, 3, Code.FOR_WITHOUT_NEXT, None),
    ]
    assert "the loop that starts on rung 1 from 0" in findings[1].message


def test_every_end_after_an_open_for_is_inside_the_loop() -> None:
    main = [_for("X001"), _rung(End(), "X002"), OUT, END]
    assert _found(check(_project(main))) == [
        (MAIN, 1, Code.RETURN_INSIDE_LOOP, None),
        (MAIN, 3, Code.RETURN_INSIDE_LOOP, None),
        (MAIN, 3, Code.FOR_WITHOUT_NEXT, None),
    ]


X2_END = _rung(End(), "X002")
CUT_FOR = Rung([[Contact("X001")] + [""] * 30], [ForLoop(count="2")], None)
EMPTY_NEXT = Rung([[""] * 31], [Next()], None)
EMPTY_OUT = Rung([[""] * 31], [Coil("Y001")], None)
TIMER = Rung([["-"] * 31, [""] * 31], [Timer("on_delay", "T1", "TD1", "5", "Ts"), ""], None)
X2_RET = _rung(Return(), "X002")

#: Projects near an answered case that CLICK has not checked, as (main, subroutines).
UNANSWERED: dict[str, tuple[list[Rung], dict[str, list[Rung]]]] = {
    # An End inside 2 open loops.
    "b1a": ([_for("X001"), _for(), X2_END, NEXT, NEXT, END], {}),
    # 2 loops open at the last End.
    "b1b": ([_for("X001"), _for(), OUT, END], {}),
    # A Return inside a loop in main.
    "b1c": ([_for("X001"), X2_RET, NEXT, END], {}),
    # A loop open at a Return in main.
    "b1d": ([_for("X001"), OUT, RET], {}),
    # An End inside a loop in a subroutine.
    "b1e": ([_call("Sub1", "X001"), END], {"Sub1": [_for(), X2_END, NEXT, RET]}),
    # A loop open at an End in a subroutine.
    "b1f": ([_call("Sub1", "X001"), END], {"Sub1": [_for(), OUT, END]}),
    # 2 loops open at the End, and a Next after it.
    "b1g": ([_for("X001"), _for(), END, NEXT], {}),
    # One Shot on a subroutine's second For.
    "b1h": (
        [_call("Sub1", "X001"), END],
        {"Sub1": [_for(), _for(oneshot=True), OUT, NEXT, NEXT, RET]},
    ),
    # A refused 4th For in main before the Call.
    "b1i": (
        [_for("X001"), _for(), _for(), _for(), _call("Sub1"), *[NEXT] * 4, END],
        {"Sub1": [_for(), OUT, NEXT, RET]},
    ),
    # A 5th For after a refused 4th.
    "reading10": ([_for("X001"), _for(), _for(), _for(), _for(), OUT, *[NEXT] * 5, END], {}),
    # A Call that names Sub1 with other case, inside 3 loops.
    "reading12": (
        [_for("X001"), _for(), _for(), _call("SUB1"), NEXT, NEXT, NEXT, END],
        {"Sub1": [_for(), OUT, NEXT, RET]},
    ),
    # Two Calls to Sub1 inside 3 loops.
    "two_calls": (
        [_for("X001"), _for(), _for(), _call("Sub1"), _call("Sub1", "X005"), *[NEXT] * 3, END],
        {"Sub1": [_for(), OUT, NEXT, RET]},
    ),
    # A rung after the End that is inside a loop.
    "after_stop": ([_for("X001"), END, OUT], {}),
    # q1a with the For cut off from the rail: X001, then 30 empty cells.
    "q1a_for_cut_from_rail": ([CUT_FOR, OUT, END], {}),
    # q1b with the Next rung's cells all empty.
    "q1b_next_with_empty_cells": ([OUT, EMPTY_NEXT, END], {}),
    # q1b with the Out rung's cells all empty.
    "q1b_out_with_empty_cells": ([EMPTY_OUT, NEXT, END], {}),
    # q1a with the contact C1 on the For.
    "q1a_contact_c1": ([_for("C1"), OUT, END], {}),
    # q1a with for(DS1).
    "q1a_for_ds1": ([_rung(ForLoop(count="DS1"), "X001"), OUT, END], {}),
    # q1a with a Timer inside the loop in place of the Out.
    "q1a_timer_in_loop": ([_for("X001"), TIMER, END], {}),
    # q2a with the string "for" in place of its second For.
    "q2a_string_for": (
        [_for("X001"), _rung("for"), _for(), _for(), OUT, *[NEXT] * 4, END],
        {},
    ),
}


@pytest.mark.parametrize("case", sorted(UNANSWERED))
def test_a_shape_that_click_did_not_answer_has_no_click_id(case: str) -> None:
    main, subs = UNANSWERED[case]
    project = _project(main, **subs)
    findings = [f for f in check(project) if f.code in PROGRAM_CODES]
    assert findings
    assert answers(project) is None
    assert [(f.click_id, f.captured) for f in findings] == [(None, False)] * len(findings)
    assert all("(CLICK's response to this shape is not captured)" in f.message for f in findings)


def test_the_table_reads_only_findings_that_click_reported() -> None:
    # q1a's shape, with a finding that CLICK did not report in it.
    found = answers(read_bundle(CLICK / "q1a" / "program"))
    assert found is not None
    assert ("Main Program", 0, 0, "next-without-for") not in found


def test_a_raw_for_or_next_stops_the_walk() -> None:
    raw = _rung(RawInstruction("For", b"\x00"))
    assert _found(check(_project([raw, NEXT, END]))) == []
    raw = _rung(RawInstruction("Next", b"\x00"))
    assert _found(check(_project([_for("X001"), raw, OUT, END]))) == []


def test_a_nested_call_says_it_has_no_click_id() -> None:
    (finding,) = check(read_bundle(CLICK / "q5b" / "program"))
    assert "drops it (no CLICK id). Call Sub1 from Main Program." in finding.message


def test_the_walk_stops_at_an_undecoded_marker() -> None:
    marker = marker_rung(Undecoded("why", 1))
    main = [_for("X001"), marker, _rung(Return(), "X002"), NEXT, NEXT, END]
    assert _found(check(_project(main))) == [(MAIN, 1, Code.UNDECODED_RUNG, None)]


def test_a_marker_in_main_leaves_its_subroutines_unanswered() -> None:
    marker = marker_rung(Undecoded("why", 2))
    main = [_call("Sub1", "X001"), END, marker]
    sub1 = [_for(), _rung(Return(), "X002"), NEXT, RET]
    found = _found(check(_project(main, Sub1=sub1)))
    assert found[-1] == ("Sub1", 1, Code.RETURN_INSIDE_LOOP, None)


def test_a_rung_finding_comes_before_the_rung_program_finding() -> None:
    long = _rung(End(), comment="x" * 1500)
    assert [(f.rung, f.code) for f in check(_project([_for("X001"), long]))] == [
        (1, Code.COMMENT_TOO_LONG),
        (1, Code.RETURN_INSIDE_LOOP),
        (1, Code.FOR_WITHOUT_NEXT),
    ]


def test_finding_built_by_position_has_no_program() -> None:
    finding = Finding(0, Code.NO_COIL, None, False, None, None, "m")
    assert finding.program is None


class _NoCsv(Condition):
    """A caller's own condition, with no ``to_csv()``."""


#: Rungs that have no CSV form, each in place of q1a's Out.
NO_CSV: dict[str, Rung] = {
    # A Tee around an unknown contact, as both decoders make one, driving out(Y002).
    "tee_around_unknown": Rung(
        [[Tee(UnknownCondition(b"Foo"))] + ["-"] * 30], [Coil("Y002")], None
    ),
    # A comment that is not text.
    "comment_not_text": Rung(
        [[Contact("X002")] + ["-"] * 30],
        [Coil("Y002")],
        5,  # type: ignore[arg-type]
    ),
    # More condition rows than AF tokens.
    "more_rows_than_af": Rung([[Contact("X002")] + ["-"] * 30, ["-"] * 31], [Coil("Y002")], None),
    # A caller's own condition with no to_csv().
    "condition_with_no_to_csv": Rung([[_NoCsv()] + ["-"] * 30], [Coil("Y002")], None),
}


@pytest.mark.parametrize("case", sorted(NO_CSV))
def test_a_rung_with_no_csv_form_is_not_captured(case: str) -> None:
    rung = NO_CSV[case]
    assert rung_rows(rung) is None
    # The open For gives findings whose codes have CLICK ids, so check() reads the table.
    main = Program(MAIN, 1, [_for("X001"), rung, END])
    for given in (main, Project(main)):
        assert answers(Project(main)) is None
        found = [(f.rung, f.code, f.click_id) for f in check(given) if f.code in PROGRAM_CODES]
        assert found == [
            (2, Code.RETURN_INSIDE_LOOP, None),
            (2, Code.FOR_WITHOUT_NEXT, None),
        ]


def test_the_table_is_not_read_without_a_finding_that_has_a_click_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import laddercodec.layout_check as layout_check

    def fail(project: Project) -> None:
        raise AssertionError("read the table")

    monkeypatch.setattr(layout_check, "answers", fail)
    main = Program(MAIN, 1, [_for("X001"), NO_CSV["tee_around_unknown"], NEXT, END])
    assert [f for f in check(main) if f.code in PROGRAM_CODES] == []
    assert [f.code for f in check(read_bundle(CLICK / "q5b" / "program"))] == [Code.NESTED_CALL]
