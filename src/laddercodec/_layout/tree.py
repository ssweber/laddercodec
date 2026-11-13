"""A rung's network reduced to a series-parallel tree, the way CLICK's syntax check reads it.

The reduction is structural: two edges between the same two nets become one parallel block,
and a net with one edge in and one edge out joins its two edges in series.  It does not
simplify logic (``Or(C1, C1)`` stays two legs) and does not factor a prefix drawn twice.

Every main box input gets an edge from its net to one shared sink ``TOP``; the reduction runs
from the rail to ``TOP``, so the outputs hanging off one net become one parallel block of
items.  Each pin input is reduced on its own, from the rail to its pin.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import cast

from .network import Edge, Network


class LayoutError(ValueError):
    """A rung CLICK's syntax check refuses, or one this layout cannot draw.

    ``code`` is CLICK's error code when CLICK is known to refuse the shape (``C0001``: not
    series-parallel; ``C0202``: a contact no rail reaches), else ``None``.
    """

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# SP nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Leaf:
    edge: Edge

    @property
    def key(self) -> tuple[int, int]:
        return (self.edge.row, self.edge.col)


@dataclass(frozen=True)
class Out:
    """A box's main input (index into ``Network.sinks``), at the sink's row."""

    sink: int
    row: int

    @property
    def key(self) -> tuple[int, int]:
        return (self.row, 99)


@dataclass(frozen=True)
class Series:
    children: tuple[Node, ...]

    @property
    def key(self) -> tuple[int, int]:
        return min(c.key for c in self.children)


@dataclass(frozen=True)
class Parallel:
    children: tuple[Node, ...]

    @property
    def key(self) -> tuple[int, int]:
        return min(c.key for c in self.children)


Node = Leaf | Out | Series | Parallel


def _has_out(node: Node) -> bool:
    if isinstance(node, Out):
        return True
    if isinstance(node, Leaf):
        return False
    return any(_has_out(c) for c in node.children)


def _out_key(node: Node) -> tuple[int, int]:
    """Order of an output item: its first box's row."""
    if isinstance(node, Out):
        return node.key
    if isinstance(node, (Series, Parallel)):
        return min(_out_key(c) for c in node.children if _has_out(c))
    raise AssertionError("an output item holds a box")


def _compound(kind: type[Series] | type[Parallel], children: list[Node]) -> Node:
    flat: list[Node] = []
    for child in children:
        flat.extend(child.children if isinstance(child, kind) else (child,))
    if kind is Parallel:
        items = [c for c in flat if _has_out(c)]
        legs = [c for c in flat if not _has_out(c)]
        if items and legs:
            raise AssertionError("an Or leg and an output share both ends")
        flat = sorted(flat, key=_out_key if items else (lambda c: c.key))
    return flat[0] if len(flat) == 1 else kind(tuple(flat))


# ---------------------------------------------------------------------------
# Reduction
# ---------------------------------------------------------------------------


@dataclass
class Arc:
    src: object
    dst: object
    node: Node


def reachable(start: object, arcs: list[Arc], *, reverse: bool = False) -> set[object]:
    adj: dict[object, list[object]] = defaultdict(list)
    for a in arcs:
        if reverse:
            adj[a.dst].append(a.src)
        else:
            adj[a.src].append(a.dst)
    seen = {start}
    stack = [start]
    while stack:
        for nxt in adj[stack.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def reduce(source: object, sink: object, arcs: list[Arc]) -> Node:
    """The SP tree of ``arcs`` between ``source`` and ``sink``; LayoutError when none exists."""
    arcs = list(arcs)
    while True:
        changed = False
        groups: dict[tuple[object, object], list[Arc]] = defaultdict(list)
        for a in arcs:
            groups[a.src, a.dst].append(a)
        merged: list[Arc] = []
        for (s, d), group in groups.items():
            if len(group) > 1:
                changed = True
                merged.append(Arc(s, d, _compound(Parallel, [a.node for a in group])))
            else:
                merged.append(group[0])
        arcs = merged
        ins: dict[object, list[Arc]] = defaultdict(list)
        outs: dict[object, list[Arc]] = defaultdict(list)
        for a in arcs:
            outs[a.src].append(a)
            ins[a.dst].append(a)
        for node in list(ins):
            if node in (source, sink) or len(ins[node]) != 1 or len(outs[node]) != 1:
                continue
            a, b = ins[node][0], outs[node][0]
            arcs = [x for x in arcs if x is not a and x is not b]
            arcs.append(Arc(a.src, b.dst, _compound(Series, [a.node, b.node])))
            changed = True
            break
        if not changed:
            break
    if len(arcs) == 1 and arcs[0].src == source and arcs[0].dst == sink:
        return arcs[0].node
    raise LayoutError("the rung's circuit is not series-parallel", "C0001")


# ---------------------------------------------------------------------------
# Output tree
# ---------------------------------------------------------------------------


@dataclass
class BoxItem:
    """A box hanging off a net (``sink`` indexes ``Network.sinks``)."""

    sink: int


@dataclass
class Branch:
    """Contacts in series from a net, then the items hanging off their end net, in order."""

    series: list[Node]
    items: list[BoxItem | Branch] = field(default_factory=list)


@dataclass
class PinCircuit:
    """The circuit feeding one pin input: series terms from the rail."""

    sink: int
    series: list[Node]


@dataclass
class RungTree:
    """One CLICK rung: its main branch from the rail, and the circuit of every used pin."""

    branch: Branch
    pins: dict[int, PinCircuit]  # sink index -> circuit


def _items(node: Node) -> list[BoxItem | Branch]:
    if isinstance(node, Out):
        return [BoxItem(node.sink)]
    if isinstance(node, Parallel):
        out: list[BoxItem | Branch] = []
        for child in node.children:
            out.extend(_items(child))
        return out
    if isinstance(node, Series):
        *series, last = node.children
        return [Branch(list(series), _items(last))]
    raise AssertionError("a leaf cannot end at an output")


def _series_terms(node: Node | None) -> list[Node]:
    if node is None:
        return []
    return list(node.children) if isinstance(node, Series) else [node]


@dataclass
class Circuits:
    """A rung's contact arcs, split into the circuit of each box input.

    ``main_arcs`` holds every arc on a path into a main box input, including the arc from
    each main input's net to ``top``; ``pin_arcs`` holds, per used pin input, the contact arcs
    on a path into it.  Arcs no rail reaches are included: layoutthy rung 23, where CLICK
    reports C0001 as well as C0202, is series-parallel only without them.
    """

    arcs: list[Arc]  # one per contact edge
    fwd: set[object]  # nets the rail reaches through contacts
    fed: set[object]  # nets a contact ends on
    main: list[int]  # indexes into Network.sinks
    pins: list[int]
    top: object
    main_arcs: list[Arc]
    pin_arcs: dict[int, list[Arc]]

    def used(self) -> set[int]:
        """``id`` of every arc in a box's circuit."""
        found = {id(a) for a in self.main_arcs}
        for mine in self.pin_arcs.values():
            found.update(id(a) for a in mine)
        return found


def circuits(net: Network) -> Circuits:
    """Split ``net``'s contacts into the circuit feeding each box input."""
    arcs = [Arc(e.src, e.dst, Leaf(e)) for e in net.edges]
    main = [i for i, s in enumerate(net.sinks) if s.slot == net.boxes[s.box].main]
    # A pin input that no wire or contact reaches is left unwired: CLICK saves such a box
    # (scr_captures/counter_scr.bin), and the pin's row stays blank.
    touched = {e.src for e in net.edges} | {e.dst for e in net.edges}
    pins = [
        i
        for i, s in enumerate(net.sinks)
        if s.slot != net.boxes[s.box].main and (s.net == net.rail or s.net in touched)
    ]
    top = object()
    with_outs = arcs + [Arc(net.sinks[i].net, top, Out(i, net.sinks[i].row)) for i in main]
    keep = reachable(top, with_outs, reverse=True)
    pin_arcs: dict[int, list[Arc]] = {}
    for i in pins:
        back = reachable(net.sinks[i].net, arcs, reverse=True)
        pin_arcs[i] = [a for a in arcs if a.src in back and a.dst in back]
    return Circuits(
        arcs=arcs,
        fwd=reachable(net.rail, arcs),
        fed={e.dst for e in net.edges},
        main=main,
        pins=pins,
        top=top,
        main_arcs=[a for a in with_outs if a.src in keep and a.dst in keep],
        pin_arcs=pin_arcs,
    )


def nothing_to_lay_out(net: Network, main: list[int]) -> bool:
    """Whether the rung holds wires and unwired NOPs at most: no contact and no wired box."""
    return not net.edges and all(
        net.boxes[net.sinks[i].box].token == "NOP" and net.sinks[i].net != net.rail for i in main
    )


def trees(net: Network) -> list[RungTree]:
    """The rung's SP trees: one per CLICK rung it splits into.

    Raises LayoutError for a shape CLICK refuses (C0001, C0202) or one this layout does not
    cover yet.
    """
    rail = net.rail
    c = circuits(net)
    for e in net.edges:
        if e.src not in c.fwd:
            raise LayoutError(
                f"row {e.row} column {e.col}: the contact's input reaches no rail", "C0202"
            )
    main, pins = c.main, c.pins
    if nothing_to_lay_out(net, main):
        return []
    for i in main + pins:
        s = net.sinks[i]
        if s.net != rail and s.net not in c.fwd:
            raise LayoutError(f"row {s.row}: the box input reaches no rail", "C0202")

    main_used = {id(a) for a in c.main_arcs}
    pin_trees: dict[int, PinCircuit] = {}
    for i in pins:
        s = net.sinks[i]
        mine = c.pin_arcs[i]
        if any(id(a) in main_used for a in mine):
            raise LayoutError(f"row {s.row}: a pin input shares contacts with a main input")
        node = None if s.net == rail else reduce(rail, s.net, mine)
        pin_trees[i] = PinCircuit(i, _series_terms(node))
    used = c.used()
    for a in c.arcs:
        if id(a) not in used:
            e = cast(Leaf, a.node).edge
            raise LayoutError(f"row {e.row} column {e.col}: the contact feeds no box")
    if not main:
        if net.edges:
            raise LayoutError("the rung has contacts but no box")
        return []
    root = reduce(rail, c.top, c.main_arcs)
    items = _items(root)
    out: list[RungTree] = []
    for item in items:
        branch = item if isinstance(item, Branch) else Branch([], [item])
        boxes = _box_ids(branch, net)
        mine_pins = {i: p for i, p in pin_trees.items() if net.sinks[i].box in boxes}
        out.append(RungTree(branch, mine_pins))
    return out


def _box_ids(branch: Branch, net: Network) -> set[int]:
    found: set[int] = set()
    for item in branch.items:
        if isinstance(item, BoxItem):
            found.add(net.sinks[item.sink].box)
        else:
            found |= _box_ids(item, net)
    return found
