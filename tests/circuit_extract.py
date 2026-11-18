"""Read the circuit of a laid-out rung as a public :class:`~laddercodec.Circuit`.

The tests use this to check that ``lay_out`` draws each rung that CLICK's syntax check left,
byte for byte.  It walks the same series-parallel trees as ``laddercodec._layout.circuit()``,
and builds the public types in place of tuples.
"""

from __future__ import annotations

from laddercodec import Box, Branch, Circuit, CompareContact, Contact, Parallel, Rung, Series
from laddercodec._layout import network_of_rung
from laddercodec._layout.network import Network
from laddercodec._layout.tree import (
    Leaf,
    Node,
    Out,
    OutputBranch,
    ParallelNode,
    RungTree,
    SeriesNode,
    trees,
)
from laddercodec.model import PinnedInstruction


class NoCircuit(Exception):
    """Raised when a rung holds a part that a public circuit can't express."""


def circuits_of(rung: Rung) -> list[Circuit]:
    """Return the circuit of each CLICK rung in *rung*.  The comment goes on the first.

    Raise :class:`NoCircuit` for a rung that the public types can't express, such as one with
    an ``UnknownCondition`` or a pin wired straight from the rail.  Raise ``LayoutError`` for
    a rung with no series-parallel circuit.
    """
    net = network_of_rung(rung)
    found = trees(net)
    if not found:
        raise NoCircuit("the rung has no circuit")
    return [
        Circuit(_Reader(net, tree).branch(tree.branch), rung.comment if index == 0 else None)
        for index, tree in enumerate(found)
    ]


class _Reader:
    def __init__(self, net: Network, tree: RungTree) -> None:
        self.net = net
        self.pins: dict[int, dict[str, object]] = {}
        for index, pin in tree.pins.items():
            sink = net.sinks[index]
            box = net.boxes[sink.box]
            token = box.token
            assert isinstance(token, PinnedInstruction)
            name = token.pin_names()[sink.slot - box.main - 1]
            if not pin.series:
                raise NoCircuit("a pin is wired straight from the rail")
            terms = [self.node(n) for n in pin.series]
            self.pins.setdefault(sink.box, {})[name] = (
                terms[0] if len(terms) == 1 else Series(terms)
            )

    def branch(self, branch: OutputBranch) -> Branch:
        outputs = [
            self.branch(item) if isinstance(item, OutputBranch) else self.box(item.sink)
            for item in branch.items
        ]
        return Branch(tuple(self.node(n) for n in branch.series), tuple(outputs))

    def box(self, sink: int) -> Box:
        index = self.net.sinks[sink].box
        return Box(self.net.boxes[index].token, self.pins.get(index, {}))  # type: ignore[arg-type]

    def node(self, node: Node) -> object:
        if isinstance(node, Leaf):
            contact = node.edge.contact
            if not isinstance(contact, (Contact, CompareContact)):
                raise NoCircuit(f"{contact!r} is not a contact")
            return contact
        if isinstance(node, Out):
            raise NoCircuit("a box inside the conditions")
        kind = Series if isinstance(node, SeriesNode) else Parallel
        assert isinstance(node, (SeriesNode, ParallelNode))
        return kind(tuple(self.node(c) for c in node.children))
