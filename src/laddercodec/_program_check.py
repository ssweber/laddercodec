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

A finding is captured when CLICK's answer for its shape is recorded.  ``_Place`` says which
programs those answers cover, and each rule says which of its shapes they cover.

The rules read no For, Next, Return, End or Call after a program's first undecoded marker,
because the rung that the marker stands for may hold a For or a Next.  A For that is open at
the marker gets no finding.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .codes import Code
from .instructions.call import Call
from .instructions.end import End
from .instructions.forloop import ForLoop, Next
from .instructions.return_ import Return
from .instructions.undecoded import Undecoded

if TYPE_CHECKING:
    from .model import Program, Project

#: The deepest that loops nest.
MAX_NESTING = 3

_MAIN_PROG_IDX = 1
_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd"}


@dataclass(frozen=True)
class ProgramFinding:
    """One program rule that a program breaks, at the AF cell of row ``row`` of rung ``rung``.

    ``what`` says what is wrong, and ``then`` says what to change.  ``captured`` says whether
    CLICK's answer for the shape is recorded.
    """

    rung: int
    row: int
    code: Code
    what: str
    then: str
    captured: bool


@dataclass(frozen=True)
class _CallSite:
    """A Call in the main program: its rung, and how many loops are open around it."""

    rung: int
    loops: int


@dataclass(frozen=True)
class _Place:
    """Where a program sits in what ``check()`` was given.

    ``answered`` is set for the programs that CLICK's recorded answers cover: the main
    program, and a subroutine whose Calls in main all sit inside the same number of loops and
    name it with the same case.
    ``carried`` is the number of loops around those Calls, and ``site`` is the deepest of them.
    """

    is_main: bool
    answered: bool
    carried: int = 0
    site: _CallSite | None = None
    main_name: str = "the main program"


_MAIN = _Place(is_main=True, answered=True)


def _ordinal(n: int) -> str:
    return _ORDINALS.get(n, f"{n}th")


def _loops(n: int) -> str:
    return f"{n} loop{'' if n == 1 else 's'}"


def _walk(program: Program) -> Iterator[tuple[int, int, object]]:
    """Yield (rung, row, token) for each AF token of *program*, up to its first undecoded marker."""
    for index, rung in enumerate(program.rungs):
        for row, token in enumerate(rung.instructions):
            if isinstance(token, Undecoded):
                return
            yield index, row, token


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
    #: How many Fors of this program were past the depth limit.
    refused: int = 0
    #: The last Return or End, as (rung, row, name), when a loop of this program was open at it.
    last_stop: tuple[int, int, str] | None = None
    #: The Calls of the main program, each with the number of loops open around it.
    calls: list[tuple[Call, _CallSite]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.carried = self.place.carried

    @property
    def top(self) -> bool:
        """Whether the program is main, or a subroutine that main calls outside any loop."""
        return self.place.answered and self.place.carried == 0

    def carried_only(self, n: int) -> bool:
        """Whether the program is a subroutine that main calls inside *n* loops, and none of
        those loops is closed yet, and no loop of its own is open.
        """
        return self.place.answered and self.place.carried == self.carried == n and not self.loops

    def add(self, rung: int, row: int, code: Code, what: str, then: str, *, captured: bool) -> None:
        self.found.append(ProgramFinding(rung, row, code, what, then, captured))

    def around(self) -> str:
        """Name the Call that the loops this program did not open are around."""
        site = self.place.site
        where = f" on rung {site.rung} from 0" if site is not None else ""
        return (
            f"{self.place.main_name} calls {self.program.name}{where} inside {_loops(self.carried)}"
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
                captured=(self.top and own == 1) or self.carried_only(1),
            )
        if own + self.carried < MAX_NESTING:
            self.loops.append((rung, row))
            return
        # CLICK's answer is recorded only for the first For past the limit in a program.
        first = not self.refused
        self.refused += 1
        if self.carried:
            what = f"counting the loops around the Call: {self.around()}"
            then = (
                f"Loops nest at most {MAX_NESTING} deep, counting the loops around a Call. "
                "Move this loop, or the Call, out of a loop."
            )
        else:
            what = f"inside the loop that starts on rung {self.loops[-1][0]} from 0"
            then = (
                f"Loops nest at most {MAX_NESTING} deep. Move this loop out of one of the "
                "loops around it."
            )
        self.add(
            rung,
            row,
            Code.FOR_NESTING_DEPTH,
            f"this For would start a {_ordinal(own + self.carried + 1)} loop, {what}",
            then,
            captured=first
            and ((self.top and own == MAX_NESTING) or self.carried_only(MAX_NESTING)),
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
                captured=self.top
                and self.refused <= 1
                and (self.place.is_main or self.refused == 1),
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
            captured=self.top,
        )

    def call(self, rung: int, row: int, token: Call) -> None:
        if self.place.is_main:
            self.calls.append((token, _CallSite(rung, len(self.loops))))
            return
        self.add(
            rung,
            row,
            Code.NESTED_CALL,
            f"this Call is in subroutine {self.program.name}, and a paste into CLICK drops it",
            f"Call {token.subroutine} from {self.place.main_name}.",
            captured=False,
        )

    def end(self) -> None:
        """Report a loop that is still open after the program's last rung."""
        if not self.loops or self.program.undecoded:
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
                captured=self.top and len(self.loops) == 1,
            )
        else:
            rung, row = start
            self.add(
                rung,
                row,
                Code.FOR_WITHOUT_NEXT,
                "this For has no Next, and no Return or End, after it",
                then,
                captured=False,
            )


def _run(program: Program, place: _Place) -> _Walk:
    walk = _Walk(program, place)
    for rung, row, token in _walk(program):
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
    that the main program calls outside any loop.  CLICK's answers for a subroutine are
    recorded only for a project that holds its Calls, so none of its findings is captured.
    """
    if program.prog_idx == _MAIN_PROG_IDX:
        return _sorted(_run(program, _MAIN).found)
    return _sorted(_run(program, _Place(is_main=False, answered=False)).found)


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
    sites: dict[int, list[_CallSite]] = {}
    #: The subroutines that a Call names with other case.
    other_case: set[int] = set()
    for call, site in main.calls:
        name = call.subroutine
        if isinstance(name, str) and name.casefold() in by_name:
            index = by_name[name.casefold()]
            sites.setdefault(index, []).append(site)
            if name != project.subroutines[index].name:
                other_case.add(index)
    out = [(project.main, _sorted(main.found))]
    for index, sub in enumerate(project.subroutines):
        calls = sites.get(index, [])
        deepest = max(calls, key=lambda site: site.loops, default=None)
        place = _Place(
            is_main=False,
            # main's Calls after its first marker are not read, so they may sit in other loops.
            answered=len({site.loops for site in calls}) == 1
            and index not in other_case
            and not project.main.undecoded,
            carried=deepest.loops if deepest else 0,
            site=deepest,
            main_name=project.main.name,
        )
        out.append((sub, _sorted(_run(sub, place).found)))
    return out
