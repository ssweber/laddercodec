"""Report rungs CLICK's syntax check refuses for their lines, without raising.

CLICK pastes and saves a rung whose circuit is not series-parallel, whose contacts no rail
reaches, or whose box inputs do not each have a branch of their own, and reports it only at its
syntax check.  laddercodec encodes and writes such rungs as drawn; ``check()`` reports them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from ._layout.network import AF_X, Box, Edge, GridCell, Network, Sink, cell_of, network
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
from .instructions.counter import Counter
from .instructions.drum import Drum
from .instructions.timer import Timer
from .instructions.undecoded import Undecoded
from .model import PinnedInstruction

if TYPE_CHECKING:
    from .decode import Rung

FindingKind = Literal[
    "not_series_parallel",
    "no_rail",
    "feeds_no_box",
    "no_coil",
    "nop_only_contact",
    "unwired_pin",
    "output_above_pinned_box",
    "shared_input_net",
    "pin_without_contact",
    "pin_shares_main",
    "pin_shares_pin",
    "unpowered_box",
    "shorted_contact",
    "undecoded",
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
        errors" table gives each kind's shape and code.
    code:
        CLICK's syntax check error code for the shape, or ``None`` where no code is known.
    captured:
        Whether CLICK's syntax check is known to report this shape with ``code``.
        ``False`` for every kind with no code, and for these shapes that have one:
        ``"not_series_parallel"`` on a pin input (C0001, as for a main input);
        ``"pin_without_contact"`` on a reset wired straight from the rail or whose contacts
        are all another pin's (C0205 or C0212, as for a reset whose contacts are all the main
        input's); ``"unwired_pin"`` on a pin other than a timer's or counter's reset, on a pin
        whose row holds a contact or a wire, or in a rung whose rail reaches no box (C0202, as
        for a reset whose row holds nothing, in a rung whose rail reaches a box);
        ``"output_above_pinned_box"`` with a ``NOP`` or a box with a used pin above
        (C000A, as for an output); and ``"shared_input_net"`` on a pin's net shared with a
        pin, with a ``NOP``, with a main input above the pin, or with the pinned box's own
        main input (C000A, as for a box's main input below the pin, on a net of the pin's
        own).  A ``"no_rail"`` or
        ``"feeds_no_box"`` finding on a loop of contacts, and a ``"no_coil"`` finding whose
        paths all end in such a loop, are not captured either.  The findings with
        ``captured`` ``False`` are provisional: their kinds may be renamed or dropped once
        CLICK's response to those shapes is captured.  An ``"undecoded"`` finding is not one
        of these: it reports an undecoded marker, which CLICK never sees.
    row, column:
        The cell, both counted from 0: ``row`` 0 is the rung's first row, ``column`` 0 is A
        and 31 is AF.  ``None`` for a finding about the whole rung.  A ``"no_rail"`` or
        ``"feeds_no_box"`` finding is at a contact; when captured, it is the contact CLICK
        named for C0202.  A finding about a box input is at its AF cell, and one about a
        whole box at its first row's AF cell.
    message:
        The finding in words.  A captured C0202 finding gives the cell as CLICK prints it,
        rows counted from 1: ``row`` 2, ``column`` 3 reads ``row 3, column D in CLICK's
        numbering``.  When the rung's first row is blank, the count starts on the second
        row, so the same cell reads ``row 2``; this is not known to hold for every rung,
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

    Empty means every rung has a series-parallel circuit from the rail into each box input,
    pins included, no box above a box with a used pin on its main input's net, no other box's
    input on a pin's net (the rail aside), and contacts of its own on every pin input.  On a
    rung whose circuit is not series-parallel, C0001 is the last finding: no C000A finding or
    finding about a pin's contacts follows it.  Findings never stop ``write_csv()``, and only
    an ``"undecoded"`` finding stops ``encode()``: the other rungs encode as drawn.  A finding
    with ``captured`` ``False`` may be a shape CLICK accepts, such as a reset wired straight
    from the rail.

    A rung that holds an undecoded marker gets one ``"undecoded"`` finding per marker, at its
    AF cell, before its other findings.  A marker rung as the decoders make it (one row of
    wires from the rail into the marker) gets no other finding: its lines are a stand-in,
    not the rung.
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


_NO_COIL_TEXT = (
    "a path from the rail reaches no box (CLICK's text: no Coil instruction in the rung)"
)
_NO_COIL_NOP = (
    "a contact feeds a NOP and no other box (CLICK's text: no Coil instruction in the rung)"
)
_C0001 = _Rule("not_series_parallel", "C0001", True)
_C0001_PIN = _Rule("not_series_parallel", "C0001", False, "a main input")
_NO_RAIL = _Rule("no_rail", "C0202", True)
_NO_RAIL_LOOP = _Rule("no_rail", "C0202", False, "a contact whose input no contact feeds")
_FEEDS_NO_BOX = _Rule("feeds_no_box", "C0202", True)
_FEEDS_NO_BOX_LOOP = _Rule("feeds_no_box", "C0202", False, "a contact no contact continues")
_NO_COIL = _Rule("no_coil", "C0003", True)
_NO_COIL_LOOP = _Rule("no_coil", "C0003", False, "a path that ends at a contact")
_UNWIRED_PIN = _Rule("unwired_pin", "C0202", True)
_UNWIRED_PIN_LIKE = _Rule("unwired_pin", "C0202", False, "a timer's or counter's reset")
_UNWIRED_PIN_NO_BOX = _Rule("unwired_pin", "C0202", False, "a rung whose rail reaches a box")
_UNWIRED_PIN_WIRED = _Rule("unwired_pin", "C0202", False, "a pin whose row holds nothing")
_ABOVE_PINNED = _Rule("output_above_pinned_box", "C000A", True)
_ABOVE_PINNED_LIKE = _Rule(
    "output_above_pinned_box", "C000A", False, "an output above the box on its main input's net"
)
_SHARED_NET = _Rule("shared_input_net", "C000A", True)
_SHARED_NET_LIKE = _Rule(
    "shared_input_net",
    "C000A",
    False,
    "a box's main input below the pin, on a net of the pin's own",
)
_PIN_SHARES = _Rule("pin_shares_main", None, False)
_PIN_SHARES_PIN = _Rule("pin_shares_pin", None, False)
_UNPOWERED = _Rule("unpowered_box", None, False)
_SHORTED = _Rule("shorted_contact", "C0002", True)
_NOP_ONLY = _Rule("nop_only_contact", "C0003", True)

#: CLICK's code for a pin with no contact of its own, per box class and pin: a
#: retentive on_delay or a time drum.
_PIN_CODES: dict[tuple[type[PinnedInstruction], str], str] = {
    (Timer, ".reset"): "C0205",
    (Drum, ".reset"): "C0212",
}


def _pin_rule(token: object, slot: int, lead: int, *, as_captured: bool) -> _Rule:
    """The rule for a pin input with no contact of its own, at ``slot`` of its box.

    ``as_captured``: its contacts are all the main input's.
    """
    if isinstance(token, PinnedInstruction):
        name = token.pin_names()[slot - lead - 1]
        for (cls, pin), code in _PIN_CODES.items():
            if isinstance(token, cls) and name == pin:
                if not as_captured:
                    like = "a reset whose contacts are all the main input's"
                    return _Rule("pin_without_contact", code, False, like)
                return _Rule("pin_without_contact", code, True)
    return _Rule("pin_without_contact", None, False)


def _unwired_rule(box: Box, slot: int, *, holds: bool, rail_feeds_a_box: bool) -> _Rule:
    """The rule for a pin of ``box`` at ``slot`` that no rail or contact reaches.

    ``holds``: the pin's row holds a contact or a wire.
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

    For a rung with a blank first row, CLICK prints "Row 3" for its one dead contact, on
    zero-based row 3; CLICK may instead have named the blank cell (2, D).  CLICK's check
    also removes a blank first row.  The rule is not known to hold for two blank first
    rows, so only one is skipped.
    """
    if not rung.conditions:
        return 0
    cells = [cell_of(t) for t in rung.conditions[0]]
    token = rung.instructions[0] if rung.instructions else ""
    if token not in ("", None) or any(c.contact is not None or c.right or c.down for c in cells):
        return 0
    return 1


def _undecoded(index: int, rung: Rung) -> list[Finding]:
    """A finding for each undecoded marker in *rung*: no CLICK check, as CLICK never sees one."""
    return [
        Finding(
            index,
            "undecoded",
            None,
            False,
            row,
            AF_X,
            f"row {row} from 0, column {OUTPUT_COLUMN}: an undecoded marker for {token.where}, "
            f"which encode() refuses: {token.error}",
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


def _check_rung(index: int, rung: Rung) -> list[Finding]:
    undecoded = _undecoded(index, rung)
    if _is_marker_rung(rung):
        return undecoded
    return undecoded + _layout_findings(index, rung)


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

    # C0202 at the broken end of each path and at each pin nothing reaches, in row and column
    # order, then C0003.
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
            # a captured finding wins over the uncaptured one for a path that ends in a loop
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

    # A box input fed by nothing is reported above; its arc into ``top`` would only stop the
    # reduction, and CLICK's response to it is not captured.
    dead = {net.sinks[i].net for i in unpowered}
    main_arcs = [a for a in c.main_arcs if not (a.dst is c.top and a.src in dead)]
    not_sp = bool(main_arcs) and rail_feeds_a_box and not _reduces(rail, c.top, main_arcs)
    if not_sp:
        # CLICK reports no C000A or C0205 on a bridge with an output above a retentive timer
        # on its net; check() drops every C000A finding and finding about a pin's contacts.
        add(_C0001, None, "the circuit is not series-parallel")
        return out

    in_shared: set[int] = set()
    for b, rule, group in _c000a(net, c):
        in_shared |= group
        if rule.kind == "output_above_pinned_box":
            what = "a box above this one hangs off its main input's net"
        else:
            what = "a pin of this box shares its net with another box's input"
        add(rule, (net.boxes[b].row, AF_X), what)

    # A contact on two pins' circuits counts as the earlier pin's.  CLICK's check on such a
    # pair is not known; a pin whose contacts are all another's has none of its own.  A box
    # reported for C000A gets no finding for its pins: CLICK reports C000A alone where a
    # timer's reset is on an output's net, and check() drops every pin finding of the group.
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
    """Whether a contact the rail reaches feeds a ``NOP`` and no other box, by any path.

    No finding when every contact that reaches the ``NOP`` also reaches another box (a
    coil on its net, or on another leg of the contact's own split); CLICK's check on that
    shape is not captured.  A ``NOP`` on the rail alone is not this shape either.
    """
    to_nop = _reaching(net, lambda s: net.boxes[s.box].token == "NOP")
    to_box = _reaching(net, lambda s: net.boxes[s.box].token != "NOP")
    return any(e.src in c.fwd and e.dst in to_nop and e.dst not in to_box for e in net.edges)


def _reaching(net: Network, wanted: Callable[[Sink], bool]) -> set[int]:
    """The nets from which a sink ``wanted`` is reached through contacts, each net included."""
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


def _unwired_pins(net: Network, c: Circuits, cells: list[list[GridCell]]) -> list[tuple[int, bool]]:
    """Each used pin no rail or contact reaches, and whether its row holds a contact or a wire.

    ``circuits`` leaves such a pin out of ``c.pins``, so the layout draws its row blank.  A
    row holds something when one of its cells holds a contact or a wire, or a vertical comes
    down into it.  A raw box is left out: which of its parts take an input is not known.
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
    """The boxes with a used pin: a retentive timer, a counter, a shift, a drum."""
    return {
        b
        for b, box in enumerate(net.boxes)
        if isinstance(box.token, PinnedInstruction) and any(box.used[box.main + 1 :])
    }


def _c000a(net: Network, c: Circuits) -> list[tuple[int, _Rule, set[int]]]:
    """One C000A finding per group of boxes that share a net: its box, its rule, the group.

    The net is one the rail reaches through a contact, not the rail itself: CLICK splits boxes
    that meet only at the rail into rungs of their own.  A box with a used pin is paired with
    another box when:

    - the other box's main input is on the pinned box's main input's net, above it
      (``"output_above_pinned_box"``), or
    - an input of the other box is on the net of one of its pins (``"shared_input_net"``).

    A box below the pinned box on its main input's net is not paired, nor are a box's own
    inputs on one net (a reset teed off the main input).  Paired boxes are one group, and each
    group is one finding, at its first pinned box with a captured pairing, else at its first
    pinned box.  The captured pairings are an output above the pinned box, and a box's main
    input below a pin on a net of the pin's own.  The others are not captured: a ``NOP`` as
    the other box, a pinned box above, a pin's net shared with another pin or with a main
    input above the pin, and a pin on its box's main input's net.
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
        for t in on[s.net]:
            other = net.boxes[t.box]
            if t.box == s.box:
                continue
            plain = other.token != "NOP"
            t_main = t.slot == other.main
            if is_main:
                if not t_main or t.row > s.row:
                    continue  # a box below is not paired; a pin is paired from its own box
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
