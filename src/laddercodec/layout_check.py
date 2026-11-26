"""Report the rungs that CLICK's syntax check refuses for how their lines connect, without raising.

CLICK pastes and saves a rung whose circuit is not series-parallel, whose contacts no rail
reaches, or whose box inputs do not each have a branch of their own.  It reports such a rung
only when its syntax check runs.  laddercodec encodes and writes these rungs as drawn, and
``check()`` reports them.  ``check()`` also reports a rung that needs more than 32 rows.
CLICK can't hold such a rung.  ``check()`` also reports a rung comment that ``encode()``
refuses as too long.  On a ``Program`` or a ``Project``, it also reports the rules of For/Next
loops and of Calls (``_program_check.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

from ._layout import rows_needed, too_tall_message
from ._layout.network import AF_X, BoxNode, Edge, GridCell, Network, Sink, cell_of, network
from ._layout.tree import (
    Arc,
    Circuits,
    LayoutError,
    Leaf,
    circuits,
    nothing_to_lay_out,
    reachable,
    reduce,
)
from ._program_check import Answer, ProgramFinding, answers, check_program, check_project
from .codes import CLICK_IDS, Code
from .csv.contract import CONDITION_COLUMNS, OUTPUT_COLUMN
from .encode import COMMENT_MAX_BYTES, MAX_ROWS, _comment_bytes
from .instructions.counter import Counter
from .instructions.drum import Drum
from .instructions.timer import Timer
from .instructions.undecoded import Undecoded, to_the_end_note
from .model import PinnedInstruction, Program, Project

if TYPE_CHECKING:
    from .decode import Rung

_COLUMN_NAMES = (*CONDITION_COLUMNS, OUTPUT_COLUMN)
_UNKNOWN = "CLICK's response to this shape is not captured"


@dataclass(frozen=True)
class Finding:
    """One shape in a rung that CLICK's syntax check refuses, or may refuse.

    Attributes
    ----------
    rung:
        Index of the rung in the checked list, or in its program's ``rungs``, from 0.
    code:
        The :class:`~laddercodec.Code` that names the shape.  In the decoding guide, the
        table under "Check for rungs CLICK's syntax check rejects or redraws" gives each
        code's shape and CLICK id.
    click_id:
        CLICK's syntax check error code for the shape, or ``None`` where no code is known.
    captured:
        Whether CLICK's syntax check is known to report this shape with ``click_id``.
        ``False`` for every finding with no CLICK id.  Also ``False`` for the findings
        below, which have a CLICK id.  For each, the brackets give the id and the shape
        that CLICK is known to report with it.

        - ``"not-series-parallel"`` on a pin input (C0001, as for a main input).
        - ``"input-without-contact"`` on a reset that is wired straight from the rail, or
          whose contacts all belong to another pin (C0205 or C0212, as for a reset whose
          contacts all belong to the main input).
        - ``"unwired-input"`` on a pin other than a timer's or counter's reset, on a pin
          whose row holds a contact or a wire, or in a rung whose rail reaches no box
          (C0202, as for a reset whose row holds nothing, in a rung whose rail reaches a
          box).
        - ``"output-above-box-inputs"`` where the box above is a ``NOP`` or a box with a
          used pin (C000A, as for an output above).
        - ``"shared-input-net"`` where a pin's net is shared with another pin, with a
          ``NOP``, with a main input above the pin, or with the pinned box's own main input
          (C000A, as for another box's main input below the pin, on a net that is not the
          pinned box's main input net).
        - ``"no-rail"`` or ``"feeds-no-box"`` on a loop of contacts, and ``"no-coil"`` when
          all of its paths end in such a loop.

        A program finding, such as ``"for-without-next"``, is captured only in a project
        of the exact shape of one that CLICK checked, and only when CLICK reported that
        finding there.  A larger project that contains such a shape is not captured.  A
        ``"nested-call"`` finding has no CLICK id.

        These findings are provisional.  Their codes may be renamed or dropped once CLICK's
        response to those shapes is captured.  An ``"undecoded-rung"`` finding is not
        provisional.  It reports an undecoded marker, which CLICK never sees.
    row, column:
        The cell, with both counted from 0.  ``row`` 0 is the rung's first row.  ``column``
        0 is A and 31 is AF.  Both are ``None`` for a finding about the whole rung.  A
        ``"no-rail"`` or ``"feeds-no-box"`` finding is at a contact.  When the finding is
        captured, that is the contact CLICK names in its C0202 error.  A finding about a
        box input is at the input's AF cell.  A finding about a whole box is at the AF cell
        of the box's first row.
    message:
        The finding in words.  A captured C0202 finding gives the cell as CLICK prints it,
        with rows counted from 1.  ``row`` 2, ``column`` 3 reads ``row 3, column D in
        CLICK's numbering``.  When the rung's first row is blank, the count starts on the
        second row, so the same cell reads ``row 2``.  This rule is not known to hold for
        every rung, and CLICK may count otherwise.  Every other finding with a cell gives
        it counted from 0, as ``row 2 from 0, column D``.  The message ends with
        ``(CLICK: <click_id>)`` when ``captured`` is ``True``.  Otherwise it ends by saying
        that CLICK's response to the shape is not captured.  Four kinds of finding end
        otherwise.  An ``"undecoded-rung"`` finding ends with the marker's error.  A
        ``"layout-too-tall"`` finding ends by saying how to split the rung.  A
        ``"comment-too-long"`` finding ends by saying how many bytes to cut from the comment.
        A program finding, such as ``"for-without-next"``, gives its CLICK id, or says that
        CLICK's response is not captured.  A ``"nested-call"`` finding says that it has no
        CLICK id.  It then ends with what to change.
    program:
        The ``Program.name`` of the program that holds the rung, such as ``"Main Program"``.
        It is ``None`` when ``check()`` was given rungs.
    """

    rung: int
    code: Code
    click_id: str | None
    captured: bool
    row: int | None
    column: int | None
    message: str
    program: str | None = None


def check(rungs: Rung | Iterable[Rung] | Program | Project) -> list[Finding]:
    """Return a finding for every shape in *rungs* that CLICK's syntax check refuses for how
    its lines connect, in rung order.

    *rungs* can also be a :class:`~laddercodec.Program` or a :class:`~laddercodec.Project`.
    ``check()`` then also reports the rules of a program that need more than one rung:

    - ``"next-without-for"``: a Next closes the nearest open For.  A Next with no open For
      before it gets a finding.
    - ``"for-nesting-depth"``: loops nest at most 3 deep.  A For past that depth gets a
      finding, and it opens no loop.
    - ``"for-oneshot-inside-loop"``: only the outermost For of a nest can use One Shot.
    - ``"return-inside-loop"``: a Return or End inside a loop of its own program gets a
      finding.  So does every Return or End after a For with no Next.
    - ``"for-without-next"``: a loop that is still open at the last Return or End of its
      program gets a finding there, after that rung's ``"return-inside-loop"``.  When no
      Return or End comes after the For, the For gets the finding.
    - ``"nested-call"``: a Call in a subroutine gets a finding, because a paste into CLICK
      drops it.  In a ``Project``, the main program is ``project.main``.  For a
      ``Program`` alone, it is the program with ``prog_idx`` 1.

    In a ``Project``, the loops around a Call in the main program count in the subroutine
    that the Call names.  They count for its depth and for One Shot.  In that subroutine, a
    Next with no open For of its own closes one of those loops, and gets no finding.  A Call
    names the first subroutine whose name matches ``Call.subroutine`` without regard to case.
    When main calls a subroutine from loops of different depths, the loops around the
    deepest Call count.
    ``check()`` reads any ``Program`` alone other than main as a subroutine that main calls
    outside any loop.

    A program finding is at the instruction's AF cell.  Its message ends with what to change.
    It is captured, with its CLICK id, only in a project of the exact shape of one that CLICK
    checked, and only when CLICK reported that finding there.  The shape is the project's
    exact CSV: each program's name, a ``#`` row for each line of each rung's comment, and
    each row of the rung as it is, with each cell's CSV text.  ``check()`` does not lay the
    rung out first.  The subroutines may come in any order.  A main program alone has the
    shape of a project with no subroutines.  A subroutine alone, and a rung with a cell that
    the CSV can't hold, are never captured.

    ``check()`` reads no For, Next, Return, End or Call after a program's first undecoded
    marker, because the rung that the marker stands for may hold a For or a Next.  A
    ``RawInstruction`` of one of those classes stops the reading in the same way.  A For that
    is open where the reading stops gets no ``"for-without-next"`` finding.

    A ``Project`` is checked in the order ``project.main``, then ``project.subroutines``.
    Within a program, the findings come in rung order.  A rung's own findings come first, then
    its program findings in row order.  Each finding's ``program`` names its program.

    ``check()`` also reports two problems that are not rules of CLICK's syntax check.  A
    rung that needs more than the 32 rows of a CLICK rung gets a ``"layout-too-tall"``
    finding.  A rung whose comment ``encode()`` refuses as too long gets a
    ``"comment-too-long"`` finding.

    An empty list means that every rung has all of these:

    - a series-parallel circuit from the rail into each box input, pins included;
    - no box above a box with a used pin, on the pinned box's main input's net or on a net
      that the main input's circuit runs through;
    - no input of another box on a pin's net, unless that net is the rail;
    - contacts of its own on every pin input.

    On a rung whose circuit is not series-parallel, the C0001 finding is the last one for
    that rung.  No C000A finding, and no finding about a pin's contacts, follows it.
    ``encode()`` refuses a rung with an ``"undecoded-rung"`` or ``"comment-too-long"``
    finding, and a rung of more than 32 rows.  It encodes a rung with any other finding as
    drawn.  That includes a 32-row rung with a box that runs past the last row.  ``check()``
    reports that rung as ``"layout-too-tall"``.  A finding with ``captured`` ``False`` may
    be a shape that CLICK accepts, such as a reset wired straight from the rail.

    A rung that holds an undecoded marker gets one ``"undecoded-rung"`` finding for each
    marker, at the marker's AF cell, before its other findings.  A marker rung, as the
    decoders make it, is one row of wires from the rail into the marker.  It gets no other
    finding, because its wires only stand in for the rung or rungs that did not decode.  That
    includes ``"comment-too-long"``.  ``encode()`` refuses the rung for its marker, whatever
    its comment.

    A rung that needs more than the 32 rows of a CLICK rung gets one ``"layout-too-tall"``
    finding about the whole rung, after its ``"undecoded-rung"`` findings.  The count
    includes every row that a box spans, as ``encode()`` writes the box.  ``write_csv()``
    refuses the rung too, unless the rungs that it would write each fit in 32 rows.  They
    can fit when CLICK splits the rung, or when the layout drops blank rows.

    A rung whose comment's RTF body is longer than the 1400 bytes that ``encode()`` accepts
    gets one ``"comment-too-long"`` finding about the whole rung.  The size counts each
    character as ``encode()`` writes it.  The finding comes after the rung's
    ``"undecoded-rung"`` and ``"layout-too-tall"`` findings, and before its other findings.
    On one rung, ``encode()`` refuses a marker, or more than 32 rows, before it reads the
    comment.  A comment that is not text gets no finding.
    """
    from .decode import Rung  # decode imports csv, which imports decode

    if isinstance(rungs, Project):
        programs = check_project(rungs)
        answered = _answers(rungs, [f for _, found in programs for f in found])
        return [
            finding
            for program, found in programs
            for finding in _check_program(program, found, answered)
        ]
    if isinstance(rungs, Program):
        found = check_program(rungs)
        # A main program alone is a project with no subroutines.
        answered = _answers(Project(rungs), found) if rungs.prog_idx == 1 else None
        return _check_program(rungs, found, answered)
    if isinstance(rungs, Rung):
        rungs = [rungs]
    return [finding for index, rung in enumerate(rungs) for finding in _check_rung(index, rung)]


def _answers(project: Project, found: list[ProgramFinding]) -> frozenset[Answer] | None:
    """Return CLICK's answers for *project*, or ``None``.

    The table is read only when a finding in *found* has a code with a CLICK id, because
    no other finding can be captured.
    """
    if not any(f.code in CLICK_IDS for f in found):
        return None
    return answers(project)


def _check_program(
    program: Program, found: list[ProgramFinding], answered: frozenset[Answer] | None
) -> list[Finding]:
    """Return the findings of each rung of *program*, each followed by the rung's program
    findings in *found*.

    *answered* holds the program findings that CLICK reported for a project of the same
    shape, or is ``None`` when CLICK checked no project of that shape.
    """
    by_rung: dict[int, list[ProgramFinding]] = {}
    for f in found:
        by_rung.setdefault(f.rung, []).append(f)
    name = program.name
    out: list[Finding] = []
    for index, rung in enumerate(program.rungs):
        out += [replace(f, program=name) for f in _check_rung(index, rung)]
        out += [_program_finding(index, f, name, answered) for f in by_rung.get(index, ())]
    return out


def _program_finding(
    rung: int, f: ProgramFinding, program: str, answered: frozenset[Answer] | None
) -> Finding:
    ids = CLICK_IDS.get(f.code, ())
    captured = bool(ids) and answered is not None and (program, rung, f.row, f.code) in answered
    click_id = ids[0] if captured else None
    if click_id:
        why = f"CLICK: {click_id}"
    else:
        why = _UNKNOWN if ids else "no CLICK id"
    where = f"row {f.row} from 0, column {OUTPUT_COLUMN}"
    message = f"{where}: {f.what} ({why}). {f.then}"
    return Finding(rung, f.code, click_id, click_id is not None, f.row, AF_X, message, program)


@dataclass(frozen=True)
class _Rule:
    code: Code
    click_id: str | None
    captured: bool
    #: A shape that CLICK is known to report with ``click_id``. It is set when CLICK is not
    #: known to report this rule's own shape with that id. The message then reads
    #: ``<click_id> as for <like>``.
    like: str = ""


_NO_COIL_TEXT = (
    "a path from the rail reaches no box (CLICK's text: no Coil instruction in the rung)"
)
_NO_COIL_NOP = (
    "a contact feeds a NOP and no other box (CLICK's text: no Coil instruction in the rung)"
)
_C0001 = _Rule(Code.NOT_SERIES_PARALLEL, "C0001", True)
_C0001_PIN = _Rule(Code.NOT_SERIES_PARALLEL, "C0001", False, "a main input")
_NO_RAIL = _Rule(Code.NO_RAIL, "C0202", True)
_NO_RAIL_LOOP = _Rule(Code.NO_RAIL, "C0202", False, "a contact whose input no contact feeds")
_FEEDS_NO_BOX = _Rule(Code.FEEDS_NO_BOX, "C0202", True)
_FEEDS_NO_BOX_LOOP = _Rule(Code.FEEDS_NO_BOX, "C0202", False, "a contact no contact continues")
_NO_COIL = _Rule(Code.NO_COIL, "C0003", True)
_NO_COIL_LOOP = _Rule(Code.NO_COIL, "C0003", False, "a path that ends at a contact")
_UNWIRED_PIN = _Rule(Code.UNWIRED_INPUT, "C0202", True)
_UNWIRED_PIN_LIKE = _Rule(Code.UNWIRED_INPUT, "C0202", False, "a timer's or counter's reset")
_UNWIRED_PIN_NO_BOX = _Rule(Code.UNWIRED_INPUT, "C0202", False, "a rung whose rail reaches a box")
_UNWIRED_PIN_WIRED = _Rule(Code.UNWIRED_INPUT, "C0202", False, "a pin whose row holds nothing")
_ABOVE_PINNED = _Rule(Code.OUTPUT_ABOVE_BOX_INPUTS, "C000A", True)
_ABOVE_PINNED_LIKE = _Rule(
    Code.OUTPUT_ABOVE_BOX_INPUTS, "C000A", False, "an output above the box on its main input's net"
)
_SHARED_NET = _Rule(Code.SHARED_INPUT_NET, "C000A", True)
_SHARED_NET_LIKE = _Rule(
    Code.SHARED_INPUT_NET,
    "C000A",
    False,
    "a box's main input below the pin, on a net of the pin's own",
)
_PIN_SHARES = _Rule(Code.INPUT_SHARES_ENABLE, None, False)
_PIN_SHARES_PIN = _Rule(Code.INPUTS_SHARE_CONTACTS, None, False)
_UNPOWERED = _Rule(Code.UNPOWERED_BOX, None, False)
_SHORTED = _Rule(Code.SHORTED_CONTACT, "C0002", True)
_NOP_ONLY = _Rule(Code.CONTACT_FEEDS_ONLY_NOP, "C0003", True)

#: CLICK's id for a pin with no contact of its own, by box class and pin name.  The Timer
#: entry is for a retentive on_delay, and the Drum entry for a time drum.
_PIN_CODES: dict[tuple[type[PinnedInstruction], str], str] = {
    (Timer, ".reset"): "C0205",
    (Drum, ".reset"): "C0212",
}


def _pin_rule(token: object, slot: int, lead: int, *, as_captured: bool) -> _Rule:
    """Return the rule for the pin input at ``slot`` of its box, which has no contact of its own.

    Set ``as_captured`` when the pin's contacts all belong to the main input.
    """
    if isinstance(token, PinnedInstruction):
        name = token.pin_names()[slot - lead - 1]
        for (cls, pin), click_id in _PIN_CODES.items():
            if isinstance(token, cls) and name == pin:
                if not as_captured:
                    like = "a reset whose contacts are all the main input's"
                    return _Rule(Code.INPUT_WITHOUT_CONTACT, click_id, False, like)
                return _Rule(Code.INPUT_WITHOUT_CONTACT, click_id, True)
    return _Rule(Code.INPUT_WITHOUT_CONTACT, None, False)


def _unwired_rule(box: BoxNode, slot: int, *, holds: bool, rail_feeds_a_box: bool) -> _Rule:
    """Return the rule for the pin of ``box`` at ``slot``, which no rail or contact reaches.

    Set ``holds`` when the pin's row holds a contact or a wire.
    """
    token = cast(PinnedInstruction, box.token)
    name = token.pin_names()[slot - box.main - 1]
    if holds:
        return _UNWIRED_PIN_WIRED
    if not isinstance(token, (Timer, Counter)) or name != ".reset":
        return _UNWIRED_PIN_LIKE
    return _UNWIRED_PIN if rail_feeds_a_box else _UNWIRED_PIN_NO_BOX


def _finding(
    rung: int, rule: _Rule, cell: tuple[int, int] | None, what: str, blank_rows: int
) -> Finding:
    if rule.captured:
        why = f"CLICK: {rule.click_id}"
    elif rule.click_id:
        why = f"{rule.click_id} as for {rule.like}; {_UNKNOWN}"
    else:
        why = _UNKNOWN
    code, click_id, captured = rule.code, rule.click_id, rule.captured
    if cell is None:
        return Finding(rung, code, click_id, captured, None, None, f"{what} ({why})")
    row, column = cell
    name = _COLUMN_NAMES[column]
    if captured and click_id == "C0202":
        where = f"row {row - blank_rows + 1}, column {name} in CLICK's numbering"
    else:
        where = f"row {row} from 0, column {name}"
    return Finding(rung, code, click_id, captured, row, column, f"{where}: {what} ({why})")


def _blank_rows(rung: Rung) -> int:
    """Return 1 when the rung's first row holds nothing, else 0.  CLICK skips that row when
    it counts rows.

    In a rung with a blank first row and one contact that no rail reaches, on row 3 counted
    from 0, CLICK prints "Row 3" for the contact.  CLICK may instead have named the blank
    cell at row 2, column D.  CLICK's check also removes a blank first row.  The rule is not
    known to hold when the first two rows are blank, so only one row is skipped.
    """
    if not rung.conditions:
        return 0
    cells = [cell_of(t) for t in rung.conditions[0]]
    token = rung.instructions[0] if rung.instructions else ""
    if token not in ("", None) or any(c.contact is not None or c.right or c.down for c in cells):
        return 0
    return 1


def _undecoded(index: int, rung: Rung) -> list[Finding]:
    """Return a finding for each undecoded marker in *rung*, with no CLICK id.

    CLICK never sees a marker, so its check has no id for one.
    """
    return [
        Finding(
            index,
            Code.UNDECODED_RUNG,
            None,
            False,
            row,
            AF_X,
            f"row {row} from 0, column {OUTPUT_COLUMN}: an undecoded marker for {token.where}, "
            f"which encode() refuses: {token.error}{to_the_end_note(token)}",
        )
        for row, token in enumerate(rung.instructions)
        if isinstance(token, Undecoded)
    ]


def _is_marker_rung(rung: Rung) -> bool:
    """Whether *rung* is exactly a marker rung: one row of wires from the rail into a marker."""
    return (
        len(rung.conditions) == 1
        and list(rung.conditions[0]) == ["-"] * len(CONDITION_COLUMNS)
        and len(rung.instructions) == 1
        and isinstance(rung.instructions[0], Undecoded)
    )


def _too_tall(index: int, rung: Rung) -> list[Finding]:
    """Return a finding if *rung* needs more than the 32 rows of a CLICK rung.

    The finding has no CLICK id, because CLICK can't hold the rung at all.
    """
    rows = rows_needed(rung)
    if rows <= MAX_ROWS:
        return []
    message = too_tall_message("the rung", rows)
    return [Finding(index, Code.LAYOUT_TOO_TALL, None, False, None, None, message)]


def _comment_too_long(index: int, rung: Rung) -> list[Finding]:
    """Return a finding if ``encode()`` would refuse the comment of *rung* as too long.

    The finding has no CLICK id, because the limit is ``encode()``'s.
    """
    if not isinstance(rung.comment, str) or not rung.comment:
        return []
    size = len(_comment_bytes(rung.comment))
    if size <= COMMENT_MAX_BYTES:
        return []
    cut = size - COMMENT_MAX_BYTES
    message = (
        f"the comment is too long: CLICK would store {size} bytes, and the limit is "
        f"{COMMENT_MAX_BYTES}. Shorten the comment by at least {cut} byte{'' if cut == 1 else 's'}."
    )
    return [Finding(index, Code.COMMENT_TOO_LONG, None, False, None, None, message)]


def _check_rung(index: int, rung: Rung) -> list[Finding]:
    undecoded = _undecoded(index, rung)
    if _is_marker_rung(rung):
        return undecoded
    whole = _too_tall(index, rung) + _comment_too_long(index, rung)
    return undecoded + whole + _layout_findings(index, rung)


def _layout_findings(index: int, rung: Rung) -> list[Finding]:
    cells = [[cell_of(t) for t in row] for row in rung.conditions]
    net = network(cells, rung.instructions, raw_pins=True)
    c = circuits(net)
    if nothing_to_lay_out(net, c.main):
        return []
    rail = net.rail
    blank = _blank_rows(rung)
    out: list[Finding] = []

    def add(rule: _Rule, cell: tuple[int, int] | None, what: str) -> None:
        out.append(_finding(index, rule, cell, what, blank))

    # Report C0202 at the broken end of each path and at each pin that nothing reaches, in row
    # and column order.  Then report C0003.
    broken: list[tuple[tuple[int, int], _Rule, str]] = [
        (
            (e.row, e.col),
            _NO_RAIL_LOOP if loop else _NO_RAIL,
            "the contact's input has no line connection",
        )
        for e, loop in _no_rail(c)
    ]
    dead_ends = _dead_ends(c, net.edges)
    broken += [
        (
            (e.row, e.col),
            _FEEDS_NO_BOX_LOOP if loop else _FEEDS_NO_BOX,
            "the contact's output reaches no box",
        )
        for e, loop in dead_ends
    ]
    rail_feeds_a_box = any(net.sinks[i].net in c.fwd for i in c.main)
    for i, holds in _unwired_pins(net, c, cells):
        s = net.sinks[i]
        box = net.boxes[s.box]
        rule = _unwired_rule(box, s.slot, holds=holds, rail_feeds_a_box=rail_feeds_a_box)
        broken.append(((s.row, AF_X), rule, "the pin's input has no line connection"))
    for cell, rule, what in sorted(broken, key=lambda b: b[0]):
        add(rule, cell, what)
    nop_only = _nop_only_contact(net, c)
    if dead_ends:
        loops = all(loop for _, loop in dead_ends)
        if nop_only and loops:
            # Every path that reaches no box ends in a loop, so a no-coil finding would not
            # be captured.  Report the captured NOP finding instead.
            add(_NOP_ONLY, None, _NO_COIL_NOP)
        else:
            rule = _NO_COIL_LOOP if loops else _NO_COIL
            add(rule, None, _NO_COIL_TEXT)
    elif nop_only:
        add(_NOP_ONLY, None, _NO_COIL_NOP)

    for e in net.bypassed:
        add(_SHORTED, (e.row, e.col), "a wire joins the contact's two sides")
    unpowered = {
        i for i in c.main + c.pins if net.sinks[i].net != rail and net.sinks[i].net not in c.fed
    }
    for i in sorted(unpowered, key=lambda i: net.sinks[i].row):
        add(_UNPOWERED, (net.sinks[i].row, AF_X), "no rail or contact reaches the box")

    # A box input that nothing feeds is reported above.  Its arc into ``top``, the sink that
    # all main inputs share, is left out of the series-parallel test.  The arc would only make
    # the reduction fail, and CLICK's response to such an input is not captured.
    dead = {net.sinks[i].net for i in unpowered}
    main_arcs = [a for a in c.main_arcs if not (a.dst is c.top and a.src in dead)]
    not_sp = bool(main_arcs) and rail_feeds_a_box and not _reduces(rail, c.top, main_arcs)
    if not_sp:
        # CLICK reports neither C000A nor C0205 on a bridge circuit with an output above a
        # retentive timer on the timer's net.  check() does the same.  It stops here, with no
        # C000A finding and no finding about a pin's contacts.
        add(_C0001, None, "the circuit is not series-parallel")
        return out

    in_shared: set[int] = set()
    for b, rule, group in _c000a(net, c):
        in_shared |= group
        if rule.code is Code.OUTPUT_ABOVE_BOX_INPUTS:
            what = "a box above this one hangs off its main input's circuit"
        else:
            what = "a pin of this box shares its net with another box's input"
        add(rule, (net.boxes[b].row, AF_X), what)

    # A contact on the circuits of two pins counts as the earlier pin's.  A pin whose contacts
    # all belong to another pin therefore has none of its own.  CLICK's check on such a pair
    # is not known.  A box in a C000A group gets no finding for its pins.  Where a timer's
    # reset is on an output's net, CLICK reports C000A alone, and check() drops every pin
    # finding of the group to match.
    main_used = {id(a) for a in c.main_arcs}
    pin_used: set[int] = set()
    for i in c.pins:
        if i in unpowered:
            continue
        s = net.sinks[i]
        if s.box in in_shared:
            pin_used.update(id(a) for a in c.pin_arcs[i])
            continue
        box = net.boxes[s.box]
        mine = c.pin_arcs[i]
        shared = [a for a in mine if id(a) in main_used]
        shared_pin = [a for a in mine if id(a) in pin_used and id(a) not in main_used]
        pin_used.update(id(a) for a in mine)
        if len(shared) + len(shared_pin) == len(mine):
            captured = bool(mine) and not shared_pin
            rule = _pin_rule(box.token, s.slot, box.main, as_captured=captured)
            add(rule, (s.row, AF_X), "the pin has no contact of its own")
        elif shared:
            add(_PIN_SHARES, (s.row, AF_X), "the pin's circuit shares contacts with a main input")
        elif shared_pin:
            add(
                _PIN_SHARES_PIN, (s.row, AF_X), "the pin's circuit shares contacts with another pin"
            )
        elif s.net in c.fwd and not _reduces(rail, s.net, mine):
            add(_C0001_PIN, (s.row, AF_X), "the pin's circuit is not series-parallel")
    return out


def _nop_only_contact(net: Network, c: Circuits) -> bool:
    """Return whether a contact that the rail reaches feeds a ``NOP`` and no other box, by any
    path.

    Return False when every contact that reaches the ``NOP`` also reaches another box, such
    as a coil on the same net or on another leg of the contact's own split.  CLICK's check
    on that shape is not captured.  A ``NOP`` wired straight from the rail, with no
    contact, does not count either.
    """
    to_nop = _reaching(net, lambda s: net.boxes[s.box].token == "NOP")
    to_box = _reaching(net, lambda s: net.boxes[s.box].token != "NOP")
    return any(e.src in c.fwd and e.dst in to_nop and e.dst not in to_box for e in net.edges)


def _reaching(net: Network, wanted: Callable[[Sink], bool]) -> set[int]:
    """Return the nets from which contacts lead to a sink that ``wanted`` accepts.

    The nets of those sinks are included.
    """
    seen = {s.net for s in net.sinks if wanted(s)}
    todo = list(seen)
    back: dict[int, list[int]] = {}
    for e in net.edges:
        back.setdefault(e.dst, []).append(e.src)
    while todo:
        for src in back.get(todo.pop(), ()):
            if src not in seen:
                seen.add(src)
                todo.append(src)
    return seen


def _no_rail(c: Circuits) -> list[tuple[Edge, bool]]:
    """Return one contact for each group of contacts that the rail does not reach, with
    whether the contact is on a loop.

    A contact whose input no contact feeds starts a group.  A group whose contacts feed each
    other in a loop starts at its first contact.  Every contact that a reported contact
    reaches belongs to the reported contact's group.
    """
    dead = [a for a in c.arcs if a.src not in c.fwd]
    covered: set[object] = set()
    picked: list[tuple[Edge, bool]] = []
    for a in (a for a in dead if a.src not in c.fed):
        picked.append((_edge(a), False))
        covered |= reachable(a.src, c.arcs)
    for a in dead:
        # Pick a contact on a loop that no reported contact reaches.  Every other contact that
        # the rail does not reach is reached from a reported contact.
        if a.src not in covered and a.src in reachable(a.dst, c.arcs):
            picked.append((_edge(a), True))
            covered |= reachable(a.src, c.arcs)
    return picked


def _dead_ends(c: Circuits, edges: list[Edge]) -> list[tuple[Edge, bool]]:
    """Return one contact for each end of a path from the rail that reaches no box, with
    whether the contact is on a loop.

    A path ends at a contact whose output feeds no other contact.  A path that runs into a
    loop of contacts ends at the loop's first contact.  Every contact that reaches a
    reported contact is on the reported contact's path.
    """
    used = c.used()
    lost = [a for a in c.arcs if id(a) not in used and a.src in c.fwd]
    starts = {e.src for e in edges}
    covered: set[object] = set()
    picked: list[tuple[Edge, bool]] = []
    for a in (a for a in lost if a.dst not in starts):
        picked.append((_edge(a), False))
        covered |= reachable(a.dst, c.arcs, reverse=True)
    for a in lost:
        if a.dst not in covered and a.src in reachable(a.dst, c.arcs):
            picked.append((_edge(a), True))
            covered |= reachable(a.dst, c.arcs, reverse=True)
    return picked


def _edge(a: Arc) -> Edge:
    """Return the contact edge of an arc from ``Circuits.arcs``.  Each of those arcs is a leaf."""
    return cast(Leaf, a.node).edge


def _unwired_pins(net: Network, c: Circuits, cells: list[list[GridCell]]) -> list[tuple[int, bool]]:
    """Return each used pin that no rail or contact reaches, with whether its row holds a
    contact or a wire.

    ``circuits`` leaves such a pin out of ``c.pins``, so the layout draws its row blank.  A
    row holds something when one of its cells holds a contact or a wire, or when a vertical
    line comes down into it from the row above.  A raw box is left out, because it is not
    known which of its parts take an input.
    """
    pins = set(c.pins)
    found: list[tuple[int, bool]] = []
    for i, s in enumerate(net.sinks):
        box = net.boxes[s.box]
        if s.slot == box.main or i in pins or not isinstance(box.token, PinnedInstruction):
            continue
        above = cells[s.row - 1] if s.row else []
        holds = any(x.contact is not None or x.right or x.down for x in cells[s.row])
        found.append((i, holds or any(x.down for x in above)))
    return found


def _pinned(net: Network) -> set[int]:
    """Return the boxes that have a used pin: a retentive timer, a counter, a shift or a drum."""
    return {
        b
        for b, box in enumerate(net.boxes)
        if isinstance(box.token, PinnedInstruction) and any(box.used[box.main + 1 :])
    }


def _c000a(net: Network, c: Circuits) -> list[tuple[int, _Rule, set[int]]]:
    """Return one C000A finding for each group of boxes that share a net, as (box, rule, group).

    The shared net is one that the rail reaches through a contact, and not the rail itself.
    CLICK splits boxes that meet only at the rail into rungs of their own.  A box with a used
    pin is paired with another box when:

    - the other box's main input is above the pinned box, on the pinned box's main input's
      net or on a net that the main input's circuit runs through from the rail
      (``"output-above-box-inputs"``), or
    - an input of the other box is on the net of one of its pins (``"shared-input-net"``).

    A box below the pinned box on its main input's net is not paired.  Neither are two inputs
    of one box on the same net, such as a reset teed off the main input.  Paired boxes form
    one group, and each group gives one finding.  The finding is at the group's first pinned
    box with a captured pairing, or else at its first pinned box.  Two pairings are captured:
    an output above the pinned box, and another box's main input below a pin, where the pin's
    net is not its own box's main input net.  The other pairings are not captured.  In those,
    the other box is a ``NOP``, or a pinned box is above, or a pin's net is shared with
    another pin or with a main input above the pin, or a pin is on its own box's main input
    net.
    """
    # In CLICK's words: all inputs of the box instruction must originate from the same branch.
    pinned = _pinned(net)
    mains = {s.box: s.net for s in net.sinks if s.slot == net.boxes[s.box].main}
    on: dict[int, list[Sink]] = {}
    for s in net.sinks:
        if s.net != net.rail and s.net in c.fwd:
            on.setdefault(s.net, []).append(s)
    pairs: list[tuple[int, int, _Rule]] = []
    for s in (s for sinks in on.values() for s in sinks if s.box in pinned):
        is_main = s.slot == net.boxes[s.box].main
        # A main input is paired with a box on its own net, or on a net that its circuit
        # runs through on the way from the rail.
        nets = net.upstream(s.net) if is_main else {s.net}
        for t in (t for n in nets for t in on.get(n, ())):
            other = net.boxes[t.box]
            if t.box == s.box:
                continue
            plain = other.token != "NOP"
            t_main = t.slot == other.main
            if is_main:
                if not t_main or t.row > s.row:
                    # Skip a box below.  Skip another box's pin too, because the loop pairs
                    # it when it reaches that pin's own box.
                    continue
                rule = _ABOVE_PINNED if plain and t.box not in pinned else _ABOVE_PINNED_LIKE
            else:
                own = s.net != mains.get(s.box)
                rule = (
                    _SHARED_NET if plain and t_main and t.row > s.row and own else _SHARED_NET_LIKE
                )
            pairs.append((s.box, t.box, rule))

    parent = list(range(len(net.boxes)))

    def find(b: int) -> int:
        while parent[b] != b:
            parent[b] = parent[parent[b]]
            b = parent[b]
        return b

    for p, q, _ in pairs:
        parent[find(p)] = find(q)
    found: list[tuple[int, _Rule, set[int]]] = []
    seen: set[int] = set()
    for p, _, rule in sorted(pairs, key=lambda x: (not x[2].captured, net.boxes[x[0]].row)):
        root = find(p)
        if root not in seen:
            seen.add(root)
            found.append((p, rule, {b for b in range(len(net.boxes)) if find(b) == root}))
    return sorted(found, key=lambda f: net.boxes[f[0]].row)


def _reduces(source: object, sink: object, arcs: list[Arc]) -> bool:
    try:
        reduce(source, sink, arcs)
    except LayoutError:
        return False
    return True
