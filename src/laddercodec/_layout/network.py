"""A rung's wire nets and contact edges, read from its cell grid.

A grid point ``(row, x)`` sits on row ``row`` at the left edge of column ``x``.  ``x = 0`` is
the left rail, and ``x = 31`` is the left edge of the AF column, where a box input lands.
Every ``(row, 0)`` is the rail.

A cell ``(row, c)`` with its right flag set joins ``(row, c)`` to ``(row, c + 1)`` with a wire.
A contact cell does not join them with a wire.  It adds an edge from ``(row, c)`` to
``(row, c + 1)`` instead.  A cell's down flag joins ``(row, c)`` to ``(row + 1, c)``, as a
vertical wire on the left edge of the column.  The down flag of the AF cell joins
``(row, 31)`` to ``(row + 1, 31)``.

Points joined by wires form one net.  Contacts conduct left to right only.  A ``NOP`` is left
out of the boxes when its net is not the rail and no contact ends on that net.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ..instructions import UnknownCondition
from ..instructions.raw import RawInstruction
from ..model import AfInstruction, ConditionInstruction, PinnedInstruction

COLUMNS = 31
AF_X = COLUMNS


@dataclass(frozen=True)
class GridCell:
    """One condition cell: the contact on it (or None) and its right and down flags."""

    contact: object | None
    right: bool
    down: bool


def cell_of(token: object) -> GridCell:
    """Return the grid cell that a decoded or CSV-read condition token stands for."""
    if isinstance(token, (ConditionInstruction, UnknownCondition)):
        return GridCell(token, True, bool(getattr(token, "wire_down", False)))
    text = str(token)
    return GridCell(None, text in ("-", "T"), text in ("T", "|"))


@dataclass(frozen=True)
class Edge:
    """A contact from net ``src`` to net ``dst``, drawn at ``(row, col)``."""

    src: int
    dst: int
    contact: object
    row: int
    col: int


@dataclass(frozen=True)
class Box:
    """An AF box, or a NOP, whose token is on row ``row``.

    ``slots`` holds the absolute row of every input, top first.  The lead slots come first,
    then the main input, then the pins.  A lead slot is a row of the box above its main
    input.  ``used`` says which of the inputs take a circuit.
    """

    token: object
    row: int
    slots: tuple[int, ...]
    used: tuple[bool, ...]
    main: int  # index of the main input in ``slots``


@dataclass(frozen=True)
class Sink:
    """A box input that takes a circuit.

    ``net`` is the net that feeds the AF column on ``row``.  ``box`` is the index of the box,
    and ``slot`` is the index of the input in the box's ``slots``.
    """

    net: int
    row: int
    box: int
    slot: int


@dataclass
class Network:
    rail: int
    edges: list[Edge]
    sinks: list[Sink]
    boxes: list[Box]
    #: The number of wire cells on a net that no contact and no box input uses.
    dead_wire_cells: int = 0
    #: Contacts whose two sides are on one net, because a wire joins them.
    bypassed: list[Edge] = field(default_factory=list)


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[object, object] = {}

    def find(self, a: object) -> object:
        self.parent.setdefault(a, a)
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def union(self, a: object, b: object) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def boxes_of(instructions: Sequence[object], rows: int, *, raw_pins: bool = False) -> list[Box]:
    """Return every box in an AF column, with the rows of its inputs.

    If ``raw_pins`` is true, a ``RawInstruction`` box of several parts gets an input on the
    row of each part, and every one of those inputs counts as used.  laddercodec does not
    know which of the pins a raw box uses.
    """
    boxes: list[Box] = []
    for r, token in enumerate(instructions):
        if token == "NOP":
            if any(r in b.slots for b in boxes):
                continue  # an earlier box's input row, such as count_down's main input
            boxes.append(Box("NOP", r, (r,), (True,), 0))
        elif isinstance(token, PinnedInstruction):
            lead = token.lead_rows
            slots = (r, *(r + off for off in token.pin_rows))
            used = (
                *(False for _ in range(lead)),
                True,
                *(lab is not None for lab in token.pin_labels()),
            )
            boxes.append(Box(token, r, tuple(s for s in slots if s < rows), used, lead))
        elif raw_pins and isinstance(token, RawInstruction) and token.part_rows():
            slots = tuple(s for s in (r, *(r + off for off in token.part_rows())) if s < rows)
            boxes.append(Box(token, r, slots, tuple(True for _ in slots), 0))
        elif isinstance(token, AfInstruction):
            boxes.append(Box(token, r, (r,), (True,), 0))
        elif token not in ("", None):
            boxes.append(Box(token, r, (r,), (True,), 0))
    return boxes


def network(
    cells: Sequence[Sequence[GridCell]],
    instructions: Sequence[object],
    af_down: Sequence[bool] | None = None,
    *,
    raw_pins: bool = False,
) -> Network:
    """Return the nets, contact edges and boxes of a grid.

    ``cells`` has one row of 31 condition cells for each grid row.  ``instructions`` has
    one AF token for each row, and ``af_down`` has the down flag of each AF cell.
    ``raw_pins`` is passed to :func:`boxes_of`.
    """
    rows = len(cells)
    uf = _UnionFind()
    for r in range(rows):
        uf.union((r, 0), "RAIL")
        for c in range(COLUMNS):
            cell = cells[r][c]
            if cell.right and cell.contact is None:
                uf.union((r, c), (r, c + 1))
            if cell.down and r + 1 < rows:
                uf.union((r, c), (r + 1, c))
        if af_down is not None and af_down[r] and r + 1 < rows:
            uf.union((r, AF_X), (r + 1, AF_X))

    ids: dict[object, int] = {}

    def net(point: object) -> int:
        return ids.setdefault(uf.find(point), len(ids))

    rail = net("RAIL")
    edges: list[Edge] = []
    bypassed: list[Edge] = []
    for r in range(rows):
        for c in range(COLUMNS):
            cell = cells[r][c]
            if cell.contact is None:
                continue
            edge = Edge(net((r, c)), net((r, c + 1)), cell.contact, r, c)
            (bypassed if edge.src == edge.dst else edges).append(edge)

    # Leave out a NOP that neither the rail nor a contact reaches.  CLICK's syntax check drops
    # such a NOP and reports no error.
    fed = {rail} | {e.dst for e in edges}
    boxes = [
        box
        for box in boxes_of(instructions, rows, raw_pins=raw_pins)
        if box.token != "NOP" or net((box.row, AF_X)) in fed
    ]
    sinks: list[Sink] = []
    for b, box in enumerate(boxes):
        for s, (row, used) in enumerate(zip(box.slots, box.used, strict=False)):
            if used:
                sinks.append(Sink(net((row, AF_X)), row, b, s))

    live = {e.src for e in edges} | {e.dst for e in edges} | {s.net for s in sinks}
    dead = 0
    for r in range(rows):
        for c in range(COLUMNS):
            cell = cells[r][c]
            if cell.contact is None and (cell.right or cell.down) and net((r, c)) not in live:
                dead += 1
    return Network(rail, edges, sinks, boxes, dead, bypassed)
