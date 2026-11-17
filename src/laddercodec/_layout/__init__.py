"""Lay a rung out from its circuit, as CLICK's syntax check draws it.

The work runs in three steps.  ``network`` reads the cell grid into nets and contact edges.
``tree`` reduces the nets to one series-parallel tree for each CLICK rung, by structure
alone.  ``render`` draws each tree in the packed layout.  ``docs/internals/layout.md`` gives
the rules.  ``read_csv`` and ``write_csv`` use :func:`canonical`.  ``laddercodec.check()``
uses ``network`` and ``tree.circuits``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any, cast

from ..codes import Code
from ..model import PinnedInstruction
from ..operands.unchecked import rebuilt
from .network import GridCell, Network, cell_of, network
from .render import render
from .tree import Branch, LayoutError, Leaf, Node, Out, RungTree, Series, trees

__all__ = [
    "LayoutError",
    "Network",
    "RungTree",
    "canonical",
    "circuit",
    "layout",
    "layout_grid",
    "network_of_rung",
]


def network_of_rung(rung: Any, af_down: Sequence[bool] | None = None) -> Network:
    """Return the network of a ``Rung`` that was decoded or read from CSV."""
    cells = [[cell_of(t) for t in row] for row in rung.conditions]
    return network(cells, list(rung.instructions), af_down)


def layout_grid(
    cells: Sequence[Sequence[GridCell]],
    instructions: Sequence[object],
    af_down: Sequence[bool] | None = None,
) -> list[tuple[list[list[object]], list[object]]]:
    """Lay out a cell grid and return each CLICK rung it makes, as (condition rows, AF tokens)."""
    net = network(cells, instructions, af_down)
    return [render(net, t) for t in trees(net)]


def layout(rung: Any, af_down: Sequence[bool] | None = None) -> list[Any]:
    """Return the rung in CLICK's layout, as several rungs when CLICK splits it.

    The rung's comment goes on the first rung returned.  Raises :class:`LayoutError` for a
    rung this layout cannot draw.  A rung with no contact, and no box except NOPs that no
    rail or contact reaches, comes back as it is.
    """
    net = network_of_rung(rung, af_down)
    found = trees(net)
    if not found:
        return [rung]  # nothing to lay out
    return _render(rung, net, found)


def _render(rung: Any, net: Network, found: list[RungTree]) -> list[Any]:
    from ..decode import Rung

    out = []
    for i, tree in enumerate(found):
        conditions, instructions = render(net, tree)
        out.append(
            Rung(
                logical_rows=len(conditions),
                conditions=cast(Any, conditions),
                instructions=cast(Any, instructions),
                comment=rung.comment if i == 0 else None,
                comment_rtf=rung.comment_rtf if i == 0 else None,
            )
        )
    return out


def canonical(rung: Any) -> list[Any] | None:
    """Return the rung as CLICK's syntax check draws it, one ``Rung`` per CLICK rung, or ``None``.

    Return ``None`` when the rung has no layout.  That happens in three cases:

    - The rung has no contact, and no box except NOPs that no rail or contact reaches.
    - ``laddercodec.check()`` reports the rung.  For example, its circuit is not
      series-parallel, no rail reaches one of its contacts or boxes, or CLICK's check refuses
      its shape.
    - The layout cannot draw the rung.

    The caller keeps such a rung as it was drawn.  Two findings of ``check()`` still allow a
    layout.  The first is a pin that no rail or contact reaches.  The layout draws the pin's
    row blank, the same way CLICK saves a pin whose row holds nothing.  The second is a contact
    that feeds only a NOP.  The layout draws that rung like any other.  CLICK keeps that layout
    when the rung is pasted.  What CLICK's check reports for the rung as written is not
    captured.
    """
    from ..layout_check import check

    if any(f.code not in (Code.UNWIRED_INPUT, Code.CONTACT_FEEDS_ONLY_NOP) for f in check(rung)):
        return None
    try:
        net = network_of_rung(rung)
        found = trees(net)
        return _render(rung, net, found) if found else None
    except LayoutError:
        return None


def circuit(rungs: Sequence[Any]) -> list[object]:
    """Return the circuits of *rungs*, one for each CLICK rung, without rows or columns.

    If two lists of rungs have equal circuits, they hold the same contacts in the same series
    and parallel blocks, and those contacts feed the same boxes with the same pin circuits.
    Each contact of a rung appears exactly once in the rung's circuit.  A contact that is
    drawn twice, or lost, therefore makes the circuits differ.  A rung with no contact, and
    no box except NOPs that no rail or contact reaches, has no circuit.  Raises
    :class:`LayoutError` for a rung with no series-parallel circuit, or whose circuit would
    hold a contact twice or not at all.
    """
    out: list[object] = []
    for rung in rungs:
        net = network_of_rung(rung)
        seen: Counter[int] = Counter()
        for tree in trees(net):
            found = _Circuit(net, tree)
            out.append(found.branch(tree.branch))
            seen.update(found.leaves)
        for e in net.edges:
            if seen[id(e)] != 1:
                raise LayoutError(
                    f"row {e.row} column {e.col}: the circuit holds the contact {seen[id(e)]} times",
                    code=Code.LAYOUT_CANNOT_DRAW,
                )
    return out


class _Circuit:
    def __init__(self, net: Network, tree: RungTree) -> None:
        self.net = net
        self.leaves: list[int] = []  # ``id`` of each contact edge, once per appearance
        self.pins: dict[int, list[tuple[int, object]]] = {}
        for i, pin in tree.pins.items():
            sink = net.sinks[i]
            series = tuple(self.node(n) for n in pin.series)
            self.pins.setdefault(sink.box, []).append((sink.slot, series))

    def branch(self, branch: Branch) -> object:
        items = tuple(
            self.branch(item) if isinstance(item, Branch) else self.box(item.sink)
            for item in branch.items
        )
        return ("branch", tuple(self.node(n) for n in branch.series), items)

    def box(self, sink: int) -> object:
        """Return a box with its pin circuits and without its rows.

        The pin rows of a pinned box belong to the layout, not to the circuit.
        """
        b = self.net.sinks[sink].box
        token = self.net.boxes[b].token
        if isinstance(token, PinnedInstruction):
            token = (type(token).__name__, token.to_csv(), token.pin_labels())
        return ("box", token, tuple(sorted(self.pins.get(b, []), key=lambda p: p[0])))

    def node(self, node: Node) -> object:
        if isinstance(node, Leaf):
            self.leaves.append(id(node.edge))
            contact = node.edge.contact
            if hasattr(contact, "wire_down"):
                return rebuilt(cast(Any, contact), wire_down=False)
            return contact
        if isinstance(node, Out):
            return self.box(node.sink)
        kind = "series" if isinstance(node, Series) else "parallel"
        return (kind, tuple(self.node(c) for c in node.children))
