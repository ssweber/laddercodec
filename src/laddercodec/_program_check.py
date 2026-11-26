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

In a subroutine that main calls from inside a loop, a Next with no open For of its own closes
one of the loops around the Call, and gets no finding.

The rules read no For, Next, Return, End or Call after a program's first undecoded marker,
because the rung that the marker stands for may hold a For or a Next.  A ``RawInstruction``
of one of those classes stops the walk in the same way.  A For that is open where the walk
stops gets no finding.

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
        Code.FOR_ONESHOT_INSIDE_LOOP,
        Code.RETURN_INSIDE_LOOP,
        Code.NESTED_CALL,
    }
)

#: The table of the projects that CLICK checked.  ``devtools/gen_program_answers.py`` writes
#: it from the cases in ``tests/fixtures/program_check/click/``.
ANSWERS_RESOURCE = "resources/program_answers.json"

_MAIN_PROG_IDX = 1
_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd"}
#: The binary class names of a ``RawInstruction`` that may be a For, Next, Return, End or Call.
_FLOW_CLASSES = frozenset({"For", "Next", "Return", "End", "Call"})

#: A finding as CLICK reports it: program, rung, row and code.
Answer = tuple[str, int, int, str]


@dataclass(frozen=True)
class ProgramFinding:
    """One program rule that a program breaks, at the AF cell of row ``row`` of rung ``rung``.

    ``what`` says what is wrong, and ``then`` says what to change.
    """

    rung: int
    row: int
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
    the deepest such Call.
    """

    is_main: bool
    carried: int = 0
    site: _CallSite | None = None
    main_name: str = "the main program"


_MAIN = _Place(is_main=True)


def _ordinal(n: int) -> str:
    return _ORDINALS.get(n, f"{n}th")


def _loops(n: int) -> str:
    return f"{n} loop{'' if n == 1 else 's'}"


def _stops_walk(token: object) -> bool:
    if isinstance(token, Undecoded):
        return True
    return isinstance(token, RawInstruction) and token.class_name in _FLOW_CLASSES


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
    calls: list[tuple[Call, _CallSite]] = field(default_factory=list)
    #: Whether the walk stopped at a marker, or at a raw For, Next, Return, End or Call.
    stopped: bool = False

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
            f"Move the Call on rung {site.rung} from 0 of {self.place.main_name} out of the loop "
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
                Code.FOR_ONESHOT_INSIDE_LOOP,
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
        else:
            self.add(
                rung,
                row,
                Code.NEXT_WITHOUT_FOR,
                "this Next has no open For before it",
                "Delete the Next, or add a For rung before it, such as for(2).",
            )

    def stop(self, rung: int, row: int, token: Return | End) -> None:
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
            self.calls.append((token, _CallSite(rung, len(self.loops), inner)))
            return
        self.add(
            rung,
            row,
            Code.NESTED_CALL,
            f"this Call is in subroutine {self.program.name}, and a paste into CLICK drops it",
            f"Call {token.subroutine} from {self.place.main_name}.",
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


def check_project(project: Project) -> list[tuple[Program, list[ProgramFinding]]]:
    """Return the program rules that each program of *project* breaks: main first, then the
    subroutines in their order.

    A Call names the first subroutine whose name matches without regard to case.  A
    subroutine that main calls inside loops is walked with the most loops that any of its
    Calls sits inside.
    """
    main = _run(project.main, _MAIN)
    by_name: dict[str, int] = {}
    for index, sub in enumerate(project.subroutines):
        by_name.setdefault(sub.name.casefold(), index)
    deepest: dict[int, _CallSite] = {}
    for call, site in main.calls:
        name = call.subroutine
        if isinstance(name, str) and name.casefold() in by_name:
            index = by_name[name.casefold()]
            if index not in deepest or site.loops > deepest[index].loops:
                deepest[index] = site
    out = [(project.main, _sorted(main.found))]
    for index, sub in enumerate(project.subroutines):
        site = deepest.get(index)
        place = _Place(
            is_main=False,
            carried=site.loops if site else 0,
            site=site,
            main_name=project.main.name,
        )
        out.append((sub, _sorted(_run(sub, place).found)))
    return out


_KINDS: tuple[tuple[type, str], ...] = (
    (Next, "next"),
    (Break, "break"),
    (Continue, "continue"),
    (Return, "return"),
    (End, "end"),
    (Undecoded, "undecoded"),
)


def _kind(token: object) -> str:
    """Return the kind of an AF token, as the shape of a project names it."""
    if isinstance(token, ForLoop):
        return "for-oneshot" if token.oneshot else "for"
    if isinstance(token, Call):
        return f"call:{token.subroutine}"
    if isinstance(token, RawInstruction):
        return f"raw:{token.class_name}"
    if isinstance(token, str):
        return token.lower()
    for cls, kind in _KINDS:
        if isinstance(token, cls):
            return kind
    return "other"


def rung_shape(rung: Rung) -> list[object]:
    """Return whether *rung* has a condition cell other than wires, and the kind of each of
    its AF tokens.
    """
    has_conditions = any(not isinstance(cell, str) for row in rung.conditions for cell in row)
    return [has_conditions, [_kind(token) for token in rung.instructions]]


def program_shape(program: Program) -> list[object]:
    """Return the name of *program* and the shape of each of its rungs."""
    return [program.name, [rung_shape(rung) for rung in program.rungs]]


def project_shape(project: Project) -> list[object]:
    """Return the shape of *project*: main's shape, then the subroutines' shapes by name.

    The subroutines are sorted by name, because their order in the project changes no answer.
    """
    subs = sorted((program_shape(sub) for sub in project.subroutines), key=lambda s: str(s[0]))
    return [program_shape(project.main), subs]


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
    return _table().get(shape_key(project_shape(project)))
