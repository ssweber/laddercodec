"""The rules of a CLICK program that ``check()`` reports on a ``Program`` or a ``Project``.

These rules look across the rungs of a program, and through a Call into the subroutine that
it names:

- Each For has a Next after it, and each Next has an open For before it.  A Next closes the
  nearest open For.
- Loops nest at most 3 deep.  A Call inside a loop adds the loops of the subroutine that it
  calls.  A Call inside that subroutine adds none, because only the main program can call.
- Only the outermost For of a nest can use One Shot.
- No Return and no End between a For and its Next.  A Return or End gets no finding when
  the innermost loop around it has no Next.  That For gets its own finding.
- Only the main program can call a subroutine.

The rules read no For, Next, Return, End or Call after a program's first undecoded marker,
because the rung that the marker stands for may hold a For or a Next.  A For that is open at
the marker gets no finding.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
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

    ``what`` says what is wrong, and ``then`` says what to change.
    """

    rung: int
    row: int
    code: Code
    what: str
    then: str


def _ordinal(n: int) -> str:
    return _ORDINALS.get(n, f"{n}th")


def _walk(program: Program) -> Iterator[tuple[int, int, object]]:
    """Yield (rung, row, token) for each AF token of *program*, up to its first undecoded marker."""
    for index, rung in enumerate(program.rungs):
        for row, token in enumerate(rung.instructions):
            if isinstance(token, Undecoded):
                return
            yield index, row, token


class _Calls:
    """Finds the subroutine that a Call names, and how deep its own loops nest."""

    def __init__(self, project: Project) -> None:
        self._by_name: dict[str, Program] = {}
        for sub in project.subroutines:
            self._by_name.setdefault(sub.name, sub)
        self._depth: dict[int, int] = {}

    def target(self, call: Call) -> Program | None:
        """Return the subroutine whose name is ``call.subroutine`` as stored, or ``None``."""
        name = call.subroutine
        return self._by_name.get(name) if isinstance(name, str) else None

    def depth(self, program: Program) -> int:
        """Return how deep the loops of *program* nest, from its own Fors only.

        A Call in *program* adds no loops.  Such a Call gets a ``nested-call`` finding, because
        only the main program can call a subroutine.
        """
        key = id(program)
        if key not in self._depth:
            open_loops = deepest = 0
            for _, _, token in _walk(program):
                if isinstance(token, ForLoop):
                    open_loops += 1
                    deepest = max(deepest, open_loops)
                elif isinstance(token, Next):
                    open_loops = max(open_loops - 1, 0)
            self._depth[key] = deepest
        return self._depth[key]


def check_program(
    program: Program,
    *,
    is_main: bool | None = None,
    calls: _Calls | None = None,
    main_name: str = "",
) -> list[ProgramFinding]:
    """Return the program rules that *program* breaks, in rung and row order.

    *is_main* says whether *program* is the main program.  When it is ``None``, a
    ``prog_idx`` of 1 means main.  With *calls*, a Call inside a loop counts the loops of the
    subroutine that it names.  *main_name* is the main program's name, for a message.
    """
    if is_main is None:
        is_main = program.prog_idx == _MAIN_PROG_IDX
    main = main_name or "the main program"
    found: list[ProgramFinding] = []
    #: The open Fors, outermost first, as (rung, row).
    loops: list[tuple[int, int]] = []
    #: For each open For, the Returns and Ends that it is the innermost loop around.  They
    #: are reported when its Next closes the loop.  A For with no Next gets its own finding,
    #: and they get none.
    inside: list[list[ProgramFinding]] = []

    def add(rung: int, row: int, code: Code, what: str, then: str) -> None:
        found.append(ProgramFinding(rung, row, code, what, then))

    for rung, row, token in _walk(program):
        if isinstance(token, ForLoop):
            if loops and token.oneshot:
                add(
                    rung,
                    row,
                    Code.FOR_ONESHOT_INSIDE_LOOP,
                    f"this For has One Shot on, inside the loop that starts on rung {loops[-1][0]} "
                    "from 0",
                    f"Only the outermost For of a nest can use One Shot. Write it as "
                    f"for({token.count}).",
                )
            loops.append((rung, row))
            inside.append([])
            if len(loops) > MAX_NESTING:
                add(
                    rung,
                    row,
                    Code.FOR_NESTING_DEPTH,
                    f"this For starts a {_ordinal(len(loops))} loop inside the loop that starts on "
                    f"rung {loops[-2][0]} from 0",
                    f"Loops nest at most {MAX_NESTING} deep. Move this loop out of one of the "
                    "loops around it.",
                )
        elif isinstance(token, Next):
            if loops:
                loops.pop()
                found.extend(inside.pop())
            else:
                add(
                    rung,
                    row,
                    Code.NEXT_WITHOUT_FOR,
                    "this Next has no For before it",
                    "Delete the Next, or add a For rung before it, such as for(2).",
                )
        elif isinstance(token, (Return, End)):
            if loops:
                name = "Return" if isinstance(token, Return) else "End"
                inside[-1].append(
                    ProgramFinding(
                        rung,
                        row,
                        Code.RETURN_INSIDE_LOOP,
                        f"this {name} is inside the loop that starts on rung {loops[-1][0]} from 0",
                        f"Move the {name.lower()}() rung after the loop's next() rung.",
                    )
                )
        elif isinstance(token, Call):
            sub = calls.target(token) if calls else None
            if not is_main:
                add(
                    rung,
                    row,
                    Code.NESTED_CALL,
                    f"this Call is in subroutine {program.name}, and only the main program can "
                    "call a subroutine",
                    f"Call {token.subroutine} from {main}.",
                )
            elif calls and sub is not None and loops:
                inner = calls.depth(sub)
                if inner and len(loops) + inner > MAX_NESTING:
                    add(
                        rung,
                        row,
                        Code.FOR_NESTING_DEPTH,
                        f"this Call to {sub.name} is inside {len(loops)} "
                        f"loop{'' if len(loops) == 1 else 's'}, and {sub.name}'s own loops nest "
                        f"{inner} deep, so the loops nest {len(loops) + inner} deep",
                        f"Loops nest at most {MAX_NESTING} deep. Call {sub.name} outside the loop "
                        f"that starts on rung {loops[0][0]} from 0.",
                    )
    if not program.undecoded:
        for rung, row in loops:
            add(
                rung,
                row,
                Code.FOR_WITHOUT_NEXT,
                "this For has no Next after it",
                "Add a next() rung after the last rung of the loop.",
            )
    return sorted(found, key=lambda f: (f.rung, f.row))


def check_project(project: Project) -> list[tuple[Program, list[ProgramFinding]]]:
    """Return the program rules that each program of *project* breaks: main first, then the
    subroutines in their order.
    """
    calls = _Calls(project)
    main_name = project.main.name
    return [(project.main, check_program(project.main, is_main=True, calls=calls))] + [
        (sub, check_program(sub, is_main=False, calls=calls, main_name=main_name))
        for sub in project.subroutines
    ]
