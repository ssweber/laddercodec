"""Turn a :class:`~laddercodec.Circuit` into a network, and lay it out.

The builder makes the network that ``network()`` reads from a grid that draws the circuit.
Each contact is an edge between two nets, and each box input is a sink on a net.
``trees()`` and ``render()`` then run as they do for a grid.

The network has no rows or columns.  ``trees()`` orders Or legs by the row of their first
contact, and outputs by the row of their first box.  So the builder numbers every contact
and every box input depth-first, in the order that the circuit gives, and uses that number
as the row.  The legs and outputs are then drawn in source order.

A wire-only Or leg, ``Series(())`` as a leg of a ``Parallel``, is an edge whose contact is
``WIRE_LEG``.  ``render()`` draws it as wire.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..circuit import Box, Branch, Circuit, Parallel, Series, Term
from ..codes import Code
from ..errors import LayoutError
from ..model import PinnedInstruction
from .network import WIRE_LEG, BoxNode, Edge, Network, Sink
from .render import render
from .tree import trees

if TYPE_CHECKING:
    from ..decode import Rung

_MESSAGES = {
    Code.LAYOUT_TOO_WIDE: (
        "The circuit needs more than the 31 condition columns of a CLICK rung, A to AE. Put "
        "fewer contacts in series on its longest path. For example, end one Circuit with "
        "Box(Coil('C1')), and start the next with Contact('C1')."
    ),
    Code.LAYOUT_CANNOT_DRAW: (
        "laddercodec can't draw this circuit, because two of its wires would cross. If "
        "boxes come after a box with pins, or after a Branch that holds one, move each of "
        "those boxes into a Circuit of its own, such as "
        "Circuit(Branch((Contact('X001'),), (Box(Coil('Y001')),)))."
    ),
    Code.LAYOUT_NOP_SPLIT: (
        "The outputs of this circuit meet only at the rail, and one of them is a NOP. "
        "laddercodec can't split such a circuit into CLICK rungs. Put the NOP in a Circuit of "
        "its own, such as Circuit(Branch((), (Box('NOP'),)))."
    ),
}
_OTHER = (
    "laddercodec can't lay out this circuit. Report it at "
    "https://github.com/ssweber/laddercodec/issues with the Python that builds the Circuit."
)


class _Builder:
    def __init__(self) -> None:
        self.nets = 1  # net 0 is the rail
        self.order = 0
        self.edges: list[Edge] = []
        self.sinks: list[Sink] = []
        self.boxes: list[BoxNode] = []

    def new_net(self) -> int:
        self.nets += 1
        return self.nets - 1

    def next_row(self) -> int:
        """Return the next depth-first number, which stands for a row."""
        self.order += 1
        return self.order - 1

    def edge(self, src: int, dst: int | None, contact: object) -> int:
        dst = self.new_net() if dst is None else dst
        self.edges.append(Edge(src, dst, contact, self.next_row(), 0))
        return dst

    def term(self, term: Term, src: int, dst: int | None) -> int:
        """Add *term* from net *src*, ending on net *dst* if it is given; return its end net."""
        if isinstance(term, Series):
            net = src
            for index, part in enumerate(term.terms):
                net = self.term(part, net, dst if index == len(term.terms) - 1 else None)
            return net
        if isinstance(term, Parallel):
            merge = self.new_net() if dst is None else dst
            for leg in term.legs:
                if isinstance(leg, Series) and not leg.terms:
                    self.edge(src, merge, WIRE_LEG)
                else:
                    self.term(leg, src, merge)
            return merge
        return self.edge(src, dst, term)

    def branch(self, branch: Branch, src: int) -> None:
        net = src
        for term in branch.conditions:
            net = self.term(term, net, None)
        for item in branch.outputs:
            if isinstance(item, Branch):
                self.branch(item, net)
            else:
                self.box(item, net)

    def box(self, box: Box, net: int) -> None:
        index = len(self.boxes)
        token = box.instruction
        if not isinstance(token, PinnedInstruction):
            self.sinks.append(Sink(net, self.next_row(), index, 0))
            self.boxes.append(BoxNode(token, index, (0,), (True,), 0))
            return
        # The slots run as in a grid: the unused lead slots, the main input, then the pins.
        # Their rows are not used, so each slot's row is its index.
        lead = token.lead_rows
        used = (
            *(False for _ in range(lead)),
            True,
            *(label is not None for label in token.pin_labels()),
        )
        self.sinks.append(Sink(net, self.next_row(), index, lead))
        self.boxes.append(BoxNode(token, index, tuple(range(len(used))), used, lead))
        pins = dict(box.pins)
        for offset, name in enumerate(token.pin_names()):
            slot = lead + 1 + offset
            if not used[slot]:
                continue
            term = pins.get(name)
            # A used pin with no term gets a net that nothing reaches.  The layout draws its
            # row blank, as it does for such a pin in a grid.
            end = self.new_net() if term is None else self.term(term, 0, None)
            self.sinks.append(Sink(end, self.next_row(), index, slot))


def network_of(circuit: Circuit) -> Network:
    """Return the network of *circuit*, with its contacts and box inputs in source order."""
    builder = _Builder()
    builder.branch(circuit.branch, 0)
    return Network(0, builder.edges, builder.sinks, builder.boxes)


def lay_out(circuit: Circuit) -> list[Rung]:
    """Return *circuit* as CLICK's syntax check draws it.  See :func:`laddercodec.lay_out`."""
    from ..decode import Rung
    from ..encode import MAX_ROWS

    net = network_of(circuit)
    out: list[Rung] = []
    try:
        drawn = [render(net, tree) for tree in trees(net)]
    except LayoutError as exc:
        # The grid path's messages name rows and columns of the drawing, which a circuit
        # doesn't have.  Each code gets a message that says what to change in the circuit.
        message = _MESSAGES.get(exc.code, _OTHER)
        raise LayoutError(message, exc.click_id, code=exc.code) from exc
    for index, (conditions, instructions) in enumerate(drawn):
        if len(conditions) > MAX_ROWS:
            raise LayoutError(
                f"The circuit needs {len(conditions)} rows, and a CLICK rung holds at most "
                f"{MAX_ROWS}. Split it into circuits of {MAX_ROWS} rows or fewer, such as one "
                "Circuit for each group of outputs.",
                code=Code.LAYOUT_TOO_TALL,
            )
        comment = circuit.comment if index == 0 else None
        out.append(Rung(cast(Any, conditions), cast(Any, instructions), comment))
    return out
