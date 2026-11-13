"""Report rungs CLICK's syntax check refuses for their lines, without raising.

CLICK pastes and saves a rung whose circuit is not series-parallel, whose contacts no rail
reaches, or whose box inputs do not each have a branch of their own, and reports it only at its
syntax check.  laddercodec encodes and writes such rungs as drawn; ``check()`` reports them.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from ._layout.network import AF_X, Edge, Network, cell_of, network
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
        The shape, one of ``FindingKind``.  The decoding guide's "Check for line connection
        errors" table gives each kind's shape, code and evidence.
    code:
        CLICK's syntax check error code for the shape, or ``None`` where no code is known.
    captured:
        Whether a CLICK capture shows its syntax check reporting this shape with ``code``.
        ``False`` for every kind with no code, and for two shapes that have one:
        ``"not_series_parallel"`` on a pin input (C0001, as for a main input), and
        ``"pin_without_contact"`` on a reset wired straight from the rail (C0205 or C0212,
        as for a reset whose contacts are all the main input's).  A ``"no_rail"`` or
        ``"feeds_no_box"`` finding on a loop of contacts, and a ``"no_coil"`` finding whose
        paths all end in such a loop, are not captured either.  The findings with
        ``captured`` ``False`` are provisional: their kinds may be renamed or dropped once
        CLICK's response to those shapes is captured.
    row, column:
        The cell, both counted from 0: ``row`` 0 is the rung's first row, ``column`` 0 is A
        and 31 is AF.  ``None`` for a finding about the whole rung.  A ``"no_rail"`` or
        ``"feeds_no_box"`` finding is at a contact; when captured, it is the contact CLICK
        named for C0202 in the layoutq captures (Q6a-c, Q8a-b).  A finding about
        a box input is at its AF cell, and one about a whole box at its first row's AF cell.
    message:
        The finding in words.  A captured C0202 finding gives the cell as CLICK prints it,
        rows counted from 1: ``row`` 2, ``column`` 3 reads ``row 3, column D in CLICK's
        numbering``.  When the rung's first row is blank, the count starts on the second
        row, so the same cell reads ``row 2``; this rests on one capture (layoutthy rung 23)
        and CLICK may count otherwise.  Every other finding with a cell gives it counted
        from 0, ``row 2 from 0, column D``.  The message ends with ``(CLICK: <code>)`` when
        ``captured``, else with ``not captured``.
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
    Findings never stop ``encode()`` or ``write_csv()``: the rungs encode as drawn.  A
    finding with ``captured`` ``False`` may be a shape CLICK accepts, such as a reset wired
    straight from the rail.
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
_NO_RAIL_LOOP = _Rule("no_rail", "C0202", False, "a contact whose input no contact feeds")
_FEEDS_NO_BOX = _Rule("feeds_no_box", "C0202", True)
_FEEDS_NO_BOX_LOOP = _Rule("feeds_no_box", "C0202", False, "a contact no contact continues")
_NO_COIL = _Rule("no_coil", "C0003", True)
_NO_COIL_LOOP = _Rule("no_coil", "C0003", False, "a path that ends at a contact")
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
    name = _COLUMN_NAMES[column]
    if captured and code == "C0202":
        where = f"row {row - blank_rows + 1}, column {name} in CLICK's numbering"
    else:
        where = f"row {row} from 0, column {name}"
    return Finding(rung, kind, code, captured, row, column, f"{where}: {what} ({why})")


def _blank_rows(rung: Rung) -> int:
    """1 when the rung's first row holds nothing, else 0: where CLICK starts counting rows.

    Inferred from one capture: layoutthy rung 23 (``v4_captures/layoutthy_pasted.bin``) has a
    blank first row, and CLICK prints "Row 3" for it.  Read this way, that is its one dead
    contact, on zero-based row 3; CLICK may instead have named the blank cell (2, D).
    CLICK's check also removes a blank first row (layoutthy rung 19).  No capture shows two
    blank first rows, so only one is skipped.
    """
    if not rung.conditions:
        return 0
    cells = [cell_of(t) for t in rung.conditions[0]]
    token = rung.instructions[0] if rung.instructions else ""
    if token not in ("", None) or any(c.contact is not None or c.right or c.down for c in cells):
        return 0
    return 1


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
    no_rail = [
        (e, _NO_RAIL_LOOP if loop else _NO_RAIL, "the contact's input has no line connection")
        for e, loop in _no_rail(c)
    ]
    dead_ends = _dead_ends(c, net.edges)
    lost = [
        (e, _FEEDS_NO_BOX_LOOP if loop else _FEEDS_NO_BOX, "the contact's output reaches no box")
        for e, loop in dead_ends
    ]
    for e, rule, what in sorted(no_rail + lost, key=lambda b: (b[0].row, b[0].col)):
        add(rule, (e.row, e.col), what)
    if dead_ends:
        rule = _NO_COIL_LOOP if all(loop for _, loop in dead_ends) else _NO_COIL
        what = "a path from the rail reaches no box (CLICK's text: no Coil instruction in the rung)"
        add(rule, None, what)

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


def _no_rail(c: Circuits) -> list[tuple[Edge, bool]]:
    """One contact per group the rail does not reach, and whether it is on a loop.

    A contact whose input no contact feeds starts a group; a group whose contacts feed each
    other in a loop starts at its first contact.  A contact a reported one reaches is part of
    that one's group.
    """
    dead = [a for a in c.arcs if a.src not in c.fwd]
    covered: set[object] = set()
    picked: list[tuple[Edge, bool]] = []
    for a in (a for a in dead if a.src not in c.fed):
        picked.append((_edge(a), False))
        covered |= reachable(a.src, c.arcs)
    for a in dead:
        # a contact on a loop no reported contact reaches; every other contact is reached
        if a.src not in covered and a.src in reachable(a.dst, c.arcs):
            picked.append((_edge(a), True))
            covered |= reachable(a.src, c.arcs)
    return picked


def _dead_ends(c: Circuits, edges: list[Edge]) -> list[tuple[Edge, bool]]:
    """One contact per end of a path from the rail that reaches no box, and whether on a loop.

    A contact whose output no contact continues ends a path; a path that runs into a loop of
    contacts ends at the loop's first contact.  A contact that reaches a reported one is on
    that one's path.
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
    """The contact of one of ``Circuits.arcs``: each is a leaf."""
    return cast(Leaf, a.node).edge


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
