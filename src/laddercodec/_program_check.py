"""The rules of a CLICK program that ``check()`` reports on a ``Program`` or a ``Project``.

These rules look across the rungs of a program, and from a Call into the subroutine that it
names:

- A Next closes the nearest open For.  A Next with no open For before it gets a finding.
- Loops nest at most 3 deep.  A For past that depth gets a finding, and it opens no loop.
  Each loop around a Call in the main program counts in the subroutine that the Call names.
- Only the outermost For of a nest can use One Shot.  A loop around the Call counts here too.
- A Return or an End inside a loop of its own program gets a finding.
- A loop that is still open at the last Return or End of its program gets a finding there.
  The For gets the finding when no Return or End comes after it.
- A Call in a subroutine gets a finding, because a paste into CLICK drops it.
- A Call in the main program that names no subroutine of the project gets a finding.  The
  names match without regard to case.
- A Break or a Continue that is not inside a loop gets a finding.
- In a ``Project``, the main program needs an End that always runs, and each subroutine needs a
  Return that always runs.  An End or a Return always runs when every condition cell of its
  row is a wire that runs right, ``-`` or ``T``.  A program without one gets a finding at the
  rung after its last rung, with no row.  A ``Program`` checked alone gets neither finding.

In a subroutine that main calls from inside a loop, a Next with no open For of its own closes
one of the loops around the Call, and gets no finding.  A Break or a Continue there is inside
those loops, and gets no finding.

The rules read no For, Next, Return, End, Call, Break or Continue after a program's first
undecoded marker, because the rung that the marker stands for may hold a For or a Next.  A
``RawInstruction`` of class For, Next, Return, End or Call stops the walk in the same way.
A For that is open where the walk stops gets no finding.  A program whose walk stops before an
End or a Return that always runs gets no finding for the lack of one.

When the walk of the main program stops, the loops around a later Call are not known.  In
that project, a Next, a Break or a Continue in a subroutine gets no finding when the
subroutine has no open For of its own.

Whether a finding is captured does not depend on the walk.  ``answers()`` looks up the
shape of the whole project in the table of the projects that CLICK checked.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import TYPE_CHECKING

from .codes import Code
from .errors import LaddercodecError
from .instructions import Condition, Instruction, Tee
from .instructions.call import Call
from .instructions.end import End
from .instructions.forloop import Break, Continue, ForLoop, Next
from .instructions.raw import RawInstruction
from .instructions.return_ import Return
from .instructions.undecoded import Undecoded

if TYPE_CHECKING:
    from .decode import Rung
    from .model import Program, Project

#: The deepest that loops nest.
MAX_NESTING = 3

#: The codes of the program rules.
PROGRAM_CODES = frozenset(
    {
        Code.FOR_WITHOUT_NEXT,
        Code.NEXT_WITHOUT_FOR,
        Code.FOR_NESTING_DEPTH,
        Code.ONESHOT_INSIDE_LOOP,
        Code.RETURN_INSIDE_LOOP,
        Code.NESTED_CALL,
        Code.CALL_WITHOUT_SUBROUTINE,
        Code.BREAK_OUTSIDE_LOOP,
        Code.CONTINUE_OUTSIDE_LOOP,
        Code.MISSING_END,
        Code.MISSING_RETURN,
    }
)

#: The table of the projects that CLICK checked.  ``devtools/gen_program_answers.py`` writes
#: it from the cases in ``tests/fixtures/program_check/click/``.
ANSWERS_RESOURCE = "resources/program_answers.json"

_MAIN_PROG_IDX = 1
_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd"}
#: The binary class names of a ``RawInstruction`` that may be a For, Next, Return, End or Call.
_FLOW_CLASSES = frozenset({"For", "Next", "Return", "End", "Call"})
#: The wires that run right.  An End or a Return on a row of these always runs.
_RUNS_RIGHT = frozenset({"-", "T"})

#: A finding as CLICK reports it: program, rung, row and code.  The row is ``None`` for a
#: finding about the whole program.
Answer = tuple[str, int, int | None, str]


@dataclass(frozen=True)
class ProgramFinding:
    """One program rule that a program breaks, at the AF cell of row ``row`` of rung ``rung``.

    ``row`` is ``None`` for a finding about the whole program.  Such a finding is at the rung
    after the program's last rung.  ``what`` says what is wrong, and ``then`` says what to
    change.
    """

    rung: int
    row: int | None
    code: Code
    what: str
    then: str


@dataclass(frozen=True)
class _CallSite:
    """A Call in the main program: its rung, the number of loops open around it, and the rung
    of the innermost of those loops.
    """

    rung: int
    loops: int
    inner: int | None


@dataclass(frozen=True)
class _Place:
    """Where a program sits in what ``check()`` was given.

    ``carried`` is the number of loops around main's Call to the program, and ``site`` is
    the deepest such Call.  ``unknown`` is true when the walk of main stopped.  A Call after
    that point may sit inside more loops.
    """

    is_main: bool
    carried: int = 0
    site: _CallSite | None = None
    main_name: str = "the main program"
    unknown: bool = False


_MAIN = _Place(is_main=True)


def _ordinal(n: int) -> str:
    return _ORDINALS.get(n, f"{n}th")


def _loops(n: int) -> str:
    return f"{n} loop{'' if n == 1 else 's'}"


def _stops_walk(token: object) -> bool:
    if isinstance(token, Undecoded):
        return True
    return isinstance(token, RawInstruction) and token.class_name in _FLOW_CLASSES


def _always_runs(rung: Rung, row: int) -> bool:
    """Return whether every condition cell of row *row* of *rung* is a wire that runs right.

    No contact then stands between the rail and the instruction in the row's AF cell.
    """
    rows = rung.conditions
    return row < len(rows) and all(isinstance(c, str) and c in _RUNS_RIGHT for c in rows[row])


@dataclass
class _Walk:
    """The state of one walk through a program."""

    program: Program
    place: _Place
    found: list[ProgramFinding] = field(default_factory=list)
    #: The open Fors of this program, outermost first, as (rung, row).
    loops: list[tuple[int, int]] = field(default_factory=list)
    #: The loops around the Call that are still open.  A Next with no open For of this
    #: program closes one of them.
    carried: int = 0
    #: The last Return or End, as (rung, row, name), when a loop of this program was open at it.
    last_stop: tuple[int, int, str] | None = None
    #: The Calls of the main program, each with the loops open around it.
    calls: list[tuple[Call, int, _CallSite]] = field(default_factory=list)
    #: Whether the walk stopped at a marker, or at a raw For, Next, Return, End or Call.
    stopped: bool = False
    #: Whether the walk read an End that always runs, in main, or a Return that always runs,
    #: in a subroutine.
    always: bool = False

    def __post_init__(self) -> None:
        self.carried = self.place.carried

    def tokens(self) -> Iterator[tuple[int, int, object]]:
        """Yield (rung, row, token) for each AF token, up to the first token that stops the
        walk.
        """
        for index, rung in enumerate(self.program.rungs):
            for row, token in enumerate(rung.instructions):
                if _stops_walk(token):
                    self.stopped = True
                    return
                yield index, row, token

    def add(self, rung: int, row: int, code: Code, what: str, then: str) -> None:
        self.found.append(ProgramFinding(rung, row, code, what, then))

    def around(self) -> str:
        """Return the text that names the Call in main and the number of loops around it."""
        site = self.place.site
        where = f" on rung {site.rung} from 0" if site is not None else ""
        return (
            f"{self.place.main_name} calls {self.program.name}{where} inside {_loops(self.carried)}"
        )

    def move_call(self) -> str:
        """Return the text that says to move main's Call out of the loop around it."""
        site = self.place.site
        if site is None or site.inner is None:
            return "Move the Call out of a loop."
        return (
            f"Move {self.place.main_name}'s Call on rung {site.rung} from 0 out of the loop "
            f"that starts on rung {site.inner} from 0."
        )

    def for_(self, rung: int, row: int, token: ForLoop) -> None:
        own = len(self.loops)
        if token.oneshot and own + self.carried:
            if own:
                what = f"inside the loop that starts on rung {self.loops[-1][0]} from 0"
            else:
                what = f"and {self.around()}"
            self.add(
                rung,
                row,
                Code.ONESHOT_INSIDE_LOOP,
                f"this For has One Shot on, {what}",
                f"Only the outermost For of a nest can use One Shot. Write it as "
                f"for({token.count}).",
            )
        if own + self.carried < MAX_NESTING:
            self.loops.append((rung, row))
            return
        if self.carried:
            what = f"counting the loops around the Call: {self.around()}"
            then = (
                f"Loops nest at most {MAX_NESTING} deep, counting the loops around a Call. "
                f"{self.move_call()}"
            )
        else:
            what = f"inside the loop that starts on rung {self.loops[-1][0]} from 0"
            then = (
                f"Loops nest at most {MAX_NESTING} deep. Move this loop out of the loop that "
                f"starts on rung {self.loops[-1][0]} from 0."
            )
        self.add(
            rung,
            row,
            Code.FOR_NESTING_DEPTH,
            f"this For would start a {_ordinal(own + self.carried + 1)} loop, {what}",
            then,
        )

    def next_(self, rung: int, row: int) -> None:
        if self.loops:
            self.loops.pop()
        elif self.carried:
            self.carried -= 1
        elif not self.place.unknown:
            self.add(
                rung,
                row,
                Code.NEXT_WITHOUT_FOR,
                "this Next has no open For before it",
                "Delete the Next, or add a For rung before it, such as for(2).",
            )

    def stop(self, rung: int, row: int, token: Return | End) -> None:
        wanted = End if self.place.is_main else Return
        if isinstance(token, wanted) and _always_runs(self.program.rungs[rung], row):
            self.always = True
        if not self.loops:
            self.last_stop = None
            return
        name = "Return" if isinstance(token, Return) else "End"
        self.last_stop = (rung, row, name)
        self.add(
            rung,
            row,
            Code.RETURN_INSIDE_LOOP,
            f"this {name} is inside the loop that starts on rung {self.loops[-1][0]} from 0",
            f"Move the {name.lower()}() rung out of the loop.",
        )

    def call(self, rung: int, row: int, token: Call) -> None:
        if self.place.is_main:
            inner = self.loops[-1][0] if self.loops else None
            self.calls.append((token, row, _CallSite(rung, len(self.loops), inner)))
            return
        self.add(
            rung,
            row,
            Code.NESTED_CALL,
            f"this Call is in subroutine {self.program.name}, and a paste into CLICK drops it",
            f"Call {token.subroutine} from {self.place.main_name}.",
        )

    def leave(self, rung: int, row: int, token: Break | Continue) -> None:
        if self.loops or self.carried or self.place.unknown:
            return
        if isinstance(token, Break):
            name, code = "Break", Code.BREAK_OUTSIDE_LOOP
        else:
            name, code = "Continue", Code.CONTINUE_OUTSIDE_LOOP
        self.add(
            rung,
            row,
            code,
            f"this {name} is not inside a loop",
            f"Move the {name.lower()}() rung between a for() rung and its next() rung, or "
            "delete it.",
        )

    def end(self) -> None:
        """Report a loop that is still open after the program's last rung."""
        if not self.loops or self.stopped:
            return
        start = self.loops[-1]
        then = "Add a next() rung after the last rung of the loop."
        if self.last_stop is not None and self.last_stop[:2] > start:
            rung, row, name = self.last_stop
            self.add(
                rung,
                row,
                Code.FOR_WITHOUT_NEXT,
                f"the loop that starts on rung {start[0]} from 0 has no Next before this {name}",
                then,
            )
        else:
            rung, row = start
            self.add(
                rung,
                row,
                Code.FOR_WITHOUT_NEXT,
                "this For has no Next, and no Return or End, after it",
                then,
            )


def _run(program: Program, place: _Place) -> _Walk:
    walk = _Walk(program, place)
    for rung, row, token in walk.tokens():
        if isinstance(token, ForLoop):
            walk.for_(rung, row, token)
        elif isinstance(token, Next):
            walk.next_(rung, row)
        elif isinstance(token, (Return, End)):
            walk.stop(rung, row, token)
        elif isinstance(token, Call):
            walk.call(rung, row, token)
        elif isinstance(token, (Break, Continue)):
            walk.leave(rung, row, token)
    walk.end()
    return walk


def _sorted(found: list[ProgramFinding]) -> list[ProgramFinding]:
    return sorted(found, key=lambda f: (f.rung, f.row))


def check_program(program: Program) -> list[ProgramFinding]:
    """Return the program rules that *program*, checked alone, breaks, in rung and row order.

    A ``prog_idx`` of 1 means the main program.  Any other program is read as a subroutine
    that the main program calls outside any loop.
    """
    place = _MAIN if program.prog_idx == _MAIN_PROG_IDX else _Place(is_main=False)
    return _sorted(_run(program, place).found)


def _missing(name: str, project: Project) -> tuple[str, str]:
    """Return what is wrong with a Call to *name*, which no subroutine of *project* has, and
    what to change.
    """
    what = f'this Call names "{name}", and the project has no subroutine of that name'
    if project.subroutines:
        other = project.subroutines[0].name
        return (
            what,
            f'Call a subroutine that the project has, such as call("{other}"), or add a '
            f'subroutine named "{name}".',
        )
    return what, f'Add a subroutine named "{name}", or delete the Call.'


def _without_stop(walk: _Walk) -> list[ProgramFinding]:
    """Return the finding for a program with no End or Return that always runs, or no finding.

    Main needs an End, and a subroutine needs a Return.  The finding is at the rung after the
    program's last rung.  A program whose walk stopped gets no finding.
    """
    if walk.always or walk.stopped:
        return []
    program = walk.program
    if walk.place.is_main:
        code, what, token = Code.MISSING_END, f"{program.name} has no End", "end()"
    else:
        code, what, token = Code.MISSING_RETURN, f"{program.name} has no Return", "return()"
    return [
        ProgramFinding(
            len(program.rungs),
            None,
            code,
            f"{what} that always runs",
            f"Add a rung after the last rung, with only - wires from A to AE and {token} in AF.",
        )
    ]


def check_project(project: Project) -> list[tuple[Program, list[ProgramFinding]]]:
    """Return the program rules that each program of *project* breaks: main first, then the
    subroutines in their order.

    A Call names the first subroutine whose name matches without regard to case.  A Call
    in main whose name matches no subroutine gets a finding.  Main with no End that always
    runs, and a subroutine with no Return that always runs, each get a finding at the rung
    after the last rung.  That finding comes last in its program's list.  A subroutine that
    main calls inside loops is walked with the most loops that any of its Calls sits inside.
    When the walk of main stops, a Next, a Break or a Continue in a subroutine with no open
    For of its own gets no finding.
    """
    main = _run(project.main, _MAIN)
    by_name: dict[str, int] = {}
    for index, sub in enumerate(project.subroutines):
        by_name.setdefault(sub.name.casefold(), index)
    deepest: dict[int, _CallSite] = {}
    for call, row, site in main.calls:
        name = call.subroutine
        if not isinstance(name, str):
            continue
        if name.casefold() not in by_name:
            main.add(site.rung, row, Code.CALL_WITHOUT_SUBROUTINE, *_missing(name, project))
            continue
        index = by_name[name.casefold()]
        if index not in deepest or site.loops > deepest[index].loops:
            deepest[index] = site
    out = [(project.main, _sorted(main.found) + _without_stop(main))]
    for index, sub in enumerate(project.subroutines):
        site = deepest.get(index)
        place = _Place(
            is_main=False,
            carried=site.loops if site else 0,
            site=site,
            main_name=project.main.name,
            unknown=main.stopped,
        )
        walk = _run(sub, place)
        out.append((sub, _sorted(walk.found) + _without_stop(walk)))
    return out


#: The wire strings of a condition cell, and the strings of an AF cell with no instruction.
_WIRES = frozenset({"", "-", "|", "T"})
_NO_INSTRUCTION = frozenset({"", "NOP"})


def _cell(token: object, strings: frozenset[str]) -> str | None:
    """Return the CSV text of *token*, or ``None`` when it has none."""
    if isinstance(token, str):
        return token if token in strings else None
    if not isinstance(token, (Tee, Condition, Instruction)):
        return None
    try:
        text = token.to_csv()
    except (LaddercodecError, NotImplementedError):
        # A Tee around an unknown condition, a field that the CSV can't hold, or a
        # caller's subclass with no to_csv().
        return None
    return text if isinstance(text, str) else None


def rung_rows(rung: Rung) -> list[list[str]] | None:
    """Return *rung* as CSV rows: a ``["#", line]`` row for each line of its comment, then
    one row for each of its rows, with the marker, the 31 condition cells and the AF cell.

    Every row of the rung is kept, and no row is laid out again.  Return ``None`` when a
    cell has no CSV text, such as an unknown condition, when the comment is not text, or
    when the rung has a different number of condition rows and AF tokens.
    """
    comment = rung.comment
    if comment is not None and not isinstance(comment, str):
        return None
    if len(rung.conditions) != len(rung.instructions):
        return None
    rows = [["#", line] for line in comment.split("\n")] if comment is not None else []
    for index, (conditions, af) in enumerate(zip(rung.conditions, rung.instructions, strict=True)):
        cells = [_cell(c, _WIRES) for c in conditions] + [_cell(af, _NO_INSTRUCTION)]
        if None in cells:
            return None
        rows.append(["R" if index == 0 else "", *(c for c in cells if c is not None)])
    return rows


def _program_rows(program: Program) -> list[object] | None:
    rungs = [rung_rows(rung) for rung in program.rungs]
    return None if None in rungs else [program.name, rungs]


def project_shape(project: Project) -> list[object] | None:
    """Return the shape of *project*: its main program, then its subroutines sorted by name.

    Each program is its name and the CSV rows of each of its rungs (``rung_rows()``).  The
    subroutines are sorted, because their order in the project changes no answer.  Return
    ``None`` when a rung has a cell with no CSV text.
    """
    main = _program_rows(project.main)
    subs = [rows for rows in map(_program_rows, project.subroutines) if rows is not None]
    if main is None or len(subs) != len(project.subroutines):
        return None
    return [main, sorted(subs, key=lambda s: str(s[0]))]


def shape_key(shape: object) -> str:
    """Return *shape* as the JSON text that the table of answers keys it by."""
    return json.dumps(shape, separators=(",", ":"))


@cache
def _table() -> dict[str, frozenset[Answer]]:
    text = resources.files("laddercodec").joinpath(ANSWERS_RESOURCE).read_text(encoding="utf-8")
    return {
        shape_key(case["shape"]): frozenset(
            (program, rung, row, code) for program, rung, row, code in case["errors"]
        )
        for case in json.loads(text)["cases"]
    }


def answers(project: Project) -> frozenset[Answer] | None:
    """Return the program findings that CLICK reported for a project of the same shape as
    *project*, or ``None`` when CLICK checked no project of that shape.
    """
    shape = project_shape(project)
    return None if shape is None else _table().get(shape_key(shape))
