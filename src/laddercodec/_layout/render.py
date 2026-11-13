"""Draw a rung tree in the packed layout CLICK's syntax check leaves.

Columns.  Each net is one vertical, on the left edge of the column right after its longest
contact path from the rail.  A contact sits in the cell right after its start net; a shorter
path gets wire up to its end net.  A box input gets wire from its net to AE.

Rows.  Series terms start on one top row.  The legs of a parallel block stack downward in
their original order (the row of each leg's first contact).  The items hanging off a net
stack downward in output order: a box takes the first free AF row at or below the next free
row of its net (boxes never overlap), and a branch after the split starts on the row of its
first box.  A pinned box's inputs sit on their own rows below it: each slot starts on the row
after the circuit above it, so OR legs under a slot push the later slots down, and the box
ends on its last slot's row.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..model import AfInstruction, PinnedInstruction
from .network import COLUMNS, Network
from .tree import BoxItem, Branch, LayoutError, Leaf, Node, Parallel, PinCircuit, RungTree, Series

RAIL = 0


@dataclass
class _Net:
    col: int = 0
    top: int | None = None
    bottom: int | None = None

    def touch(self, row: int) -> None:
        self.top = row if self.top is None else min(self.top, row)
        self.bottom = row if self.bottom is None else max(self.bottom, row)


@dataclass(frozen=True)
class _Contact:
    src: int
    dst: int
    row: int
    contact: object


@dataclass(frozen=True)
class _Sink:
    net: int
    row: int


def box_height(token: object) -> int:
    """Rows a non-pinned box spans (a NOP spans one)."""
    if isinstance(token, AfInstruction):
        return max(1, int(token.cell_params().get("visual_rows", 1)))
    return 1


class _Painter:
    def __init__(self, network: Network, tree: RungTree) -> None:
        self.network = network
        self.tree = tree
        self.nets: list[_Net] = [_Net()]
        self.contacts: list[_Contact] = []
        self.sinks: list[_Sink] = []
        self.af: dict[int, object] = {}
        self.af_free = 0  # first AF row no box covers
        self.cond_bottom = -1  # lowest row a contact or sink wire uses

    def new_net(self) -> int:
        self.nets.append(_Net())
        return len(self.nets) - 1

    # ---- placement ----
    def first_lead(self, branch: Branch) -> int:
        item = branch.items[0]
        if isinstance(item, Branch):
            return self.first_lead(item)
        token = self.network.boxes[self.network.sinks[item.sink].box].token
        return token.lead_rows if isinstance(token, PinnedInstruction) else 0

    def place_branch(self, branch: Branch, start: int, top: int) -> int:
        """Place ``branch`` from net ``start`` with its top on ``top``; return its height."""
        net, height = self.place_series(branch.series, start, None, top)
        cursor = top
        for item in branch.items:
            if isinstance(item, BoxItem):
                cursor = self.place_box(item.sink, net, cursor)
            else:
                row = max(cursor, self.af_free + self.first_lead(item))
                cursor = row + self.place_branch(item, net, row)
        return max(height, cursor - top)

    def place_box(self, sink: int, net: int, cursor: int) -> int:
        """Place a box fed from ``net`` at the first free row; return the next free row."""
        box = self.network.boxes[self.network.sinks[sink].box]
        token = box.token
        lead = token.lead_rows if isinstance(token, PinnedInstruction) else 0
        row = max(cursor, self.af_free + lead)
        token_row = row - lead
        self.sinks.append(_Sink(net, row))
        self.nets[net].touch(row)
        self.cond_bottom = max(self.cond_bottom, row)
        if not isinstance(token, PinnedInstruction):
            self.af[row] = token
            self.af_free = row + box_height(token)
            return row + 1
        # Slots: lead slots (unused) on the rows above the main input, then each pin.
        slots = list(range(token_row, row + 1))
        nxt = max(row + 1, self.cond_bottom + 1)
        pin_sinks = {
            self.network.sinks[i].slot: p
            for i, p in self.tree.pins.items()
            if self.network.sinks[i].box == self.network.sinks[sink].box
        }
        last_used = max(i for i, used in enumerate(box.used) if used)
        for slot in range(box.main + 1, len(box.used)):
            if slot > last_used:
                # Unused pins after the last used input sit directly under it.
                slots.append(slots[-1] + 1)
                continue
            slots.append(nxt)
            circuit = pin_sinks.get(slot)
            if circuit is None:
                nxt += 1
                continue
            nxt += max(1, self.place_pin(circuit, nxt))
        pin_rows = tuple(s - token_row for s in slots[1:])
        self.af[token_row] = token.with_pin_rows(pin_rows)
        if lead:
            self.af[row] = "NOP"
        self.af_free = slots[-1] + 1
        return row + 1

    def place_pin(self, circuit: PinCircuit, row: int) -> int:
        net, height = self.place_series(circuit.series, RAIL, None, row)
        self.sinks.append(_Sink(net, row))
        self.nets[net].touch(row)
        self.cond_bottom = max(self.cond_bottom, row)
        return max(1, height)

    def place_series(self, terms: list[Node], start: int, end: int | None, top: int) -> tuple[int, int]:
        if not terms:
            if end is None:
                return start, 0
            raise LayoutError("an empty Or leg (a wire around the block) shorts it")
        net, height = start, 0
        for index, term in enumerate(terms):
            target = end if index == len(terms) - 1 else None
            net, h = self.place_term(term, net, target, top)
            height = max(height, h)
        return net, height

    def place_term(self, term: Node, start: int, end: int | None, top: int) -> tuple[int, int]:
        if isinstance(term, Parallel):
            merge = self.new_net() if end is None else end
            row = top
            for leg in term.children:
                legs = list(leg.children) if isinstance(leg, Series) else [leg]
                _net, h = self.place_series(legs, start, merge, row)
                row += h
            return merge, row - top
        if isinstance(term, Series):
            return self.place_series(list(term.children), start, end, top)
        if not isinstance(term, Leaf):
            raise AssertionError(f"unexpected term {term!r}")
        dst = self.new_net() if end is None else end
        self.contacts.append(_Contact(start, dst, top, term.edge.contact))
        self.nets[start].touch(top)
        self.nets[dst].touch(top)
        self.nets[dst].col = max(self.nets[dst].col, self.nets[start].col + 1)
        self.cond_bottom = max(self.cond_bottom, top)
        return dst, 1

    # ---- painting ----
    def paint(self) -> tuple[list[list[object]], list[object]]:
        height = max(
            [c.row + 1 for c in self.contacts] + [s.row + 1 for s in self.sinks] + [self.af_free, 1]
        )
        across: list[list[object | None]] = [[None] * COLUMNS for _ in range(height)]
        vertical = [[False] * COLUMNS for _ in range(height)]
        points: dict[tuple[int, int], int] = {}

        def claim(row: int, col: int, net: int) -> None:
            if points.setdefault((row, col), net) != net:
                raise LayoutError(f"two nets meet at row {row}, column {col}")

        def put(row: int, col: int, value: object) -> None:
            if col >= COLUMNS:
                raise LayoutError("the rung needs more than 31 condition columns")
            if across[row][col] is not None:
                raise LayoutError(f"two cells drawn at row {row}, column {col}")
            across[row][col] = value

        for c in self.contacts:
            col, dst_col = self.nets[c.src].col, self.nets[c.dst].col
            put(c.row, col, c.contact)
            for pad in range(col + 1, dst_col):
                put(c.row, pad, "-")
            claim(c.row, col, c.src)
            for point in range(col + 1, dst_col + 1):
                claim(c.row, point, c.dst)
        for s in self.sinks:
            for col in range(self.nets[s.net].col, COLUMNS):
                put(s.row, col, "-")
                claim(s.row, col, s.net)
        for index, net in enumerate(self.nets):
            if index == RAIL or net.top is None or net.bottom is None:
                continue
            for row in range(net.top, net.bottom):
                if net.col >= COLUMNS:
                    raise LayoutError("the rung needs more than 31 condition columns")
                vertical[row][net.col] = True
                claim(row, net.col, index)
                claim(row + 1, net.col, index)

        conditions: list[list[object]] = []
        for row in range(height):
            cells: list[object] = []
            for col in range(COLUMNS):
                value = across[row][col]
                down = vertical[row][col]
                if value is None:
                    cells.append("|" if down else "")
                elif value == "-":
                    cells.append("T" if down else "-")
                else:
                    cells.append(_with_down(value, down))
            conditions.append(cells)
        instructions = [self.af.get(row, "") for row in range(height)]
        return conditions, instructions


def _with_down(contact: object, down: bool) -> object:
    if hasattr(contact, "wire_down"):
        return replace(contact, wire_down=down)  # type: ignore[type-var]
    if down:
        raise LayoutError("a contact this layout cannot mark with a down wire")
    return contact


def render(network: Network, tree: RungTree) -> tuple[list[list[object]], list[object]]:
    """Condition rows and AF tokens of one CLICK rung."""
    painter = _Painter(network, tree)
    painter.place_branch(tree.branch, RAIL, painter.first_lead(tree.branch))
    return painter.paint()
