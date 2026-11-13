"""Report rungs CLICK's syntax check refuses for their lines, without raising.

CLICK pastes and saves a rung whose circuit is not series-parallel, whose contacts no rail
reaches, or whose box inputs do not each have a branch of their own, and reports it only at its
syntax check.  laddercodec encodes and writes such rungs as drawn; ``check()`` reports them.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ._layout.network import AF_X, Edge, Network, cell_of, network
from ._layout.tree import (
    Arc,
    Circuits,
    LayoutError,
    circuits,
    nothing_to_lay_out,
    reachable,
    reduce,
)
from .csv.contract import CONDITION_COLUMNS, OUTPUT_COLUMN
from .instructions.drum import Drum
from .instructions.timer import Timer
from .model import PinnedInstruction

if TYPE_CHECKING:
    from .decode import Rung

FindingKind = Literal[
    "not_series_parallel",
    "no_rail",
    "feeds_no_box",
    "no_coil",
    "output_above_pinned_box",
    "pin_without_contact",
    "pin_shares_main",
    "unpowered_box",
    "shorted_contact",
]

_COLUMN_NAMES = (*CONDITION_COLUMNS, OUTPUT_COLUMN)
_UNKNOWN = "CLICK's response to this shape is not captured"


@dataclass(frozen=True)
class Finding:
    """One shape in a rung that CLICK's syntax check refuses, or may refuse.

    Attributes
    ----------
    rung:
        Index of the rung in the checked list, from 0.
    kind:
        What is wrong with the rung's lines, with CLICK's code in brackets.  The last three
        kinds have no code and are provisional.

        - ``"not_series_parallel"`` (C0001): a circuit into a box input is not
          series-parallel.  Contacts no rail reaches count as part of the circuit when the
          rail reaches a main box input too; when it reaches none, CLICK reports only C0202.
        - ``"no_rail"`` (C0202): a contact whose input no line connects to the rail,
          reported once per group: at each contact whose input no other contact feeds,
          and, for a group whose contacts feed each other in a loop, at its first contact.
        - ``"feeds_no_box"`` (C0202): a path from the rail that ends at no box input,
          reported at its last contact: each contact whose output no other contact
          continues, and, for a path that ends in a loop of contacts, the loop's first
          contact.
        - ``"no_coil"`` (C0003): the rung has a ``"feeds_no_box"`` finding; one per rung.
        - ``"output_above_pinned_box"`` (C000A): a box sits above a box with a used pin
          row, and both main inputs hang off one net that is not the rail.
        - ``"pin_without_contact"`` (C0205 for a Timer's reset, C0212 for a Drum's reset,
          ``None`` for other pins): a pin input (a timer's or counter's reset, a drum's
          jog) has no contact of its own: every contact on its circuit is on a main
          input's circuit too, or it is wired straight from the rail.
        - ``"pin_shares_main"``: a pin input's circuit has contacts of its own and shares
          others with a main input.
        - ``"unpowered_box"``: a box input that neither the rail nor any contact reaches.
        - ``"shorted_contact"``: a contact whose two sides a wire joins.
    code:
        CLICK's syntax check error code for the shape, or ``None`` where no code is known.
    captured:
        Whether a CLICK capture shows its syntax check reporting this shape with ``code``.
        ``False`` for every kind with no code, and for two shapes that have one:
        ``"not_series_parallel"`` on a pin input (C0001, as for a main input), and
        ``"pin_without_contact"`` on a reset wired straight from the rail (C0205 or C0212,
        as for a reset whose contacts are all the main input's).  The findings with
        ``captured`` ``False`` are provisional: their kinds may be renamed or dropped once
        CLICK's response to those shapes is captured.
    row, column:
        The cell, both counted from 0: ``row`` 0 is the rung's first row, ``column`` 0 is A
        and 31 is AF.  ``None`` for a finding about the whole rung.  A ``"no_rail"`` or
        ``"feeds_no_box"`` finding is at the contact CLICK names for C0202; a finding about
        a box input is at its AF cell, and one about a whole box at its first row's AF cell.
    message:
        The finding in words.  It gives the cell as CLICK prints it: rows counted from 1,
        starting at the rung's first row that is not blank, so ``row`` 2, ``column`` 3 of a
        rung whose first row holds something reads ``row 3, column D in CLICK's
        numbering``.  It ends with ``(CLICK: <code>)`` when ``captured``, else with
        ``not captured``.
    """

    rung: int
    kind: FindingKind
    code: str | None
    captured: bool
    row: int | None
    column: int | None
    message: str


def check(rungs: Rung | Iterable[Rung]) -> list[Finding]:
    """Every shape in *rungs* that CLICK's syntax check refuses for its lines, in rung order.

    Empty means every rung has a series-parallel circuit from the rail into each box, with
    no box above a pinned box on its net and contacts of its own on every pin input.
    Findings never stop ``encode()`` or ``write_csv()``: the rungs encode as drawn.
    """
    from .decode import Rung  # decode imports csv, which imports decode

    if isinstance(rungs, Rung):
        rungs = [rungs]
    return [finding for index, rung in enumerate(rungs) for finding in _check_rung(index, rung)]


@dataclass(frozen=True)
class _Rule:
    kind: FindingKind
    code: str | None
    captured: bool
    #: For a code no capture shows on this shape: the shape a capture shows it on.
    like: str = ""


_C0001 = _Rule("not_series_parallel", "C0001", True)
_C0001_PIN = _Rule("not_series_parallel", "C0001", False, "a main input")
_NO_RAIL = _Rule("no_rail", "C0202", True)
_FEEDS_NO_BOX = _Rule("feeds_no_box", "C0202", True)
_NO_COIL = _Rule("no_coil", "C0003", True)
_ABOVE_PINNED = _Rule("output_above_pinned_box", "C000A", True)
_PIN_SHARES = _Rule("pin_shares_main", None, False)
_UNPOWERED = _Rule("unpowered_box", None, False)
_SHORTED = _Rule("shorted_contact", None, False)

#: CLICK's code for a pin with no contact of its own, per box class and pin: layoutq Q4a (a
#: retentive on_delay) and Q4b (a time drum).
_PIN_CODES: dict[tuple[type[PinnedInstruction], str], str] = {
    (Timer, ".reset"): "C0205",
    (Drum, ".reset"): "C0212",
}


def _pin_rule(token: object, slot: int, lead: int, *, on_rail: bool) -> _Rule:
    """The rule for a pin input with no contact of its own, at ``slot`` of its box."""
    if isinstance(token, PinnedInstruction):
        name = token.pin_names()[slot - lead - 1]
        for (cls, pin), code in _PIN_CODES.items():
            if isinstance(token, cls) and name == pin:
                if on_rail:
                    like = "a reset whose contacts are all the main input's"
                    return _Rule("pin_without_contact", code, False, like)
                return _Rule("pin_without_contact", code, True)
    return _Rule("pin_without_contact", None, False)


def _finding(
    rung: int, rule: _Rule, cell: tuple[int, int] | None, what: str, blank_rows: int
) -> Finding:
    if rule.captured:
        why = f"CLICK: {rule.code}"
    elif rule.code:
        why = f"{rule.code} as for {rule.like}; {_UNKNOWN}"
    else:
        why = _UNKNOWN
    kind, code, captured = rule.kind, rule.code, rule.captured
    if cell is None:
        return Finding(rung, kind, code, captured, None, None, f"{what} ({why})")
    row, column = cell
    where = f"row {row - blank_rows + 1}, column {_COLUMN_NAMES[column]} in CLICK's numbering"
    return Finding(rung, kind, code, captured, row, column, f"{where}: {what} ({why})")


def _blank_rows(rung: Rung) -> int:
    """How many rows at the top of *rung* hold nothing.  CLICK's check numbers the rows after.

    layoutthy rung 23 (``v4_captures/layoutthy_pasted.bin``) has one blank first row, and
    CLICK names its contact on zero-based row 3 as "Row 3"; CLICK's check also removes a
    blank first row (layoutthy rung 19).
    """
    count = 0
    for conditions, token in zip(rung.conditions, rung.instructions, strict=False):
        cells = [cell_of(t) for t in conditions]
        if token not in ("", None) or any(c.contact or c.right or c.down for c in cells):
            break
        count += 1
    return count


def _check_rung(index: int, rung: Rung) -> list[Finding]:
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

    # C0202 at the broken end of each path, in row and column order, then C0003.
    no_rail = [(e, _NO_RAIL, "the contact's input has no line connection") for e in _no_rail(c)]
    dead_ends = _dead_ends(c, net.edges)
    lost = [(e, _FEEDS_NO_BOX, "the contact's output reaches no box input") for e in dead_ends]
    for e, rule, what in sorted(no_rail + lost, key=lambda b: (b[0].row, b[0].col)):
        add(rule, (e.row, e.col), what)
    if dead_ends:
        add(_NO_COIL, None, "a path from the rail ends at no box")

    for e in net.bypassed:
        add(_SHORTED, (e.row, e.col), "a wire joins the contact's two sides")
    unpowered = {
        i for i in c.main + c.pins if net.sinks[i].net != rail and net.sinks[i].net not in c.fed
    }
    for i in sorted(unpowered, key=lambda i: net.sinks[i].row):
        add(_UNPOWERED, (net.sinks[i].row, AF_X), "no rail or contact reaches the box")
    for row in _below_a_box(net, c):
        add(_ABOVE_PINNED, (row, AF_X), "a box above this one hangs off its main input's net")

    main_used = {id(a) for a in c.main_arcs}
    for i in c.pins:
        if i in unpowered:
            continue
        s = net.sinks[i]
        box = net.boxes[s.box]
        mine = c.pin_arcs[i]
        shared = [a for a in mine if id(a) in main_used]
        if len(shared) == len(mine):
            rule = _pin_rule(box.token, s.slot, box.main, on_rail=not mine)
            add(rule, (s.row, AF_X), "the pin has no contact of its own")
        elif shared:
            add(_PIN_SHARES, (s.row, AF_X), "the pin's circuit shares contacts with a main input")
        elif s.net in c.fwd and not _reduces(rail, s.net, mine):
            add(_C0001_PIN, (s.row, AF_X), "the pin's circuit is not series-parallel")

    # A box input fed by nothing is reported above; its arc into ``top`` would only stop the
    # reduction, and CLICK's response to it is not captured.
    dead = {net.sinks[i].net for i in unpowered}
    main_arcs = [a for a in c.main_arcs if not (a.dst is c.top and a.src in dead)]
    rail_feeds_a_box = any(net.sinks[i].net in c.fwd for i in c.main)
    if main_arcs and rail_feeds_a_box and not _reduces(rail, c.top, main_arcs):
        add(_C0001, None, "the circuit is not series-parallel")
    return out


def _no_rail(c: Circuits) -> list[Edge]:
    """One contact per group the rail does not reach.

    A contact whose input no contact feeds starts a group; a group whose contacts feed each
    other in a loop starts at its first contact.  A contact a reported one reaches is part of
    that one's group.
    """
    dead = [a for a in c.arcs if a.src not in c.fwd]
    covered: set[object] = set()
    picked: list[Edge] = []
    for a in (a for a in dead if a.src not in c.fed):
        picked.append(_edge(a))
        covered |= reachable(a.src, c.arcs)
    for a in dead:
        # a contact on a loop no reported contact reaches; every other contact is reached
        if a.src not in covered and a.src in reachable(a.dst, c.arcs):
            picked.append(_edge(a))
            covered |= reachable(a.src, c.arcs)
    return picked


def _dead_ends(c: Circuits, edges: list[Edge]) -> list[Edge]:
    """One contact per end of a path from the rail that reaches no box input.

    A contact whose output no contact continues ends a path; a path that runs into a loop of
    contacts ends at the loop's first contact.  A contact that reaches a reported one is on
    that one's path.
    """
    used = c.used()
    lost = [a for a in c.arcs if id(a) not in used and a.src in c.fwd]
    starts = {e.src for e in edges}
    covered: set[object] = set()
    picked: list[Edge] = []
    for a in (a for a in lost if a.dst not in starts):
        picked.append(_edge(a))
        covered |= reachable(a.dst, c.arcs, reverse=True)
    for a in lost:
        if a.dst not in covered and a.src in reachable(a.dst, c.arcs):
            picked.append(_edge(a))
            covered |= reachable(a.dst, c.arcs, reverse=True)
    return picked


def _edge(a: Arc) -> Edge:
    """The contact of one of ``Circuits.arcs``: each is a leaf."""
    return a.node.edge  # type: ignore[union-attr]


def _below_a_box(net: Network, c: Circuits) -> list[int]:
    """The first row of each box with a used pin that another box sits above on one net.

    The net is the one both main inputs hang off, and is not the rail (layoutq Q7a, Q7c:
    C000A).  CLICK accepts a box below the pinned box on that net (Q7b), and splits boxes
    hanging off the rail into rungs of their own (Q5a-c).
    """
    rows: list[int] = []
    for b, box in enumerate(net.boxes):
        if not isinstance(box.token, PinnedInstruction) or not any(box.used[box.main + 1 :]):
            continue
        mains = [i for i in c.main if net.sinks[i].box == b]
        if not mains:
            continue
        n = net.sinks[mains[0]].net
        if n == net.rail or n not in c.fwd:
            continue
        if any(
            net.sinks[j].net == n and net.sinks[j].box != b and net.sinks[j].row < box.row
            for j in c.main
        ):
            rows.append(box.row)
    return rows


def _reduces(source: object, sink: object, arcs: list[Arc]) -> bool:
    try:
        reduce(source, sink, arcs)
    except LayoutError:
        return False
    return True
