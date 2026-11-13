"""Lay a rung out from its circuit, as CLICK's syntax check draws it.

Pipeline: cell grid -> nets and contact edges (``network``) -> structural series-parallel tree
per CLICK rung (``tree``) -> packed layout (``render``).  The rules and their evidence are in
``docs/internals/layout.md``.  ``read_csv`` and ``write_csv`` use :func:`canonical`;
``laddercodec.check()`` uses ``network`` and ``tree.circuits``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any, cast

from ..model import PinnedInstruction
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
    """The nets of a decoded or CSV-read ``Rung``."""
    cells = [[cell_of(t) for t in row] for row in rung.conditions]
    return network(cells, list(rung.instructions), af_down)


def layout_grid(
    cells: Sequence[Sequence[GridCell]],
    instructions: Sequence[object],
    af_down: Sequence[bool] | None = None,
) -> list[tuple[list[list[object]], list[object]]]:
    """Each CLICK rung the grid lays out to, as (condition rows, AF tokens)."""
    net = network(cells, instructions, af_down)
    return [render(net, t) for t in trees(net)]


def layout(rung: Any, af_down: Sequence[bool] | None = None) -> list[Any]:
    """The rung (or rungs, when CLICK splits it) in CLICK's layout; the comment goes on the first.

    Raises :class:`LayoutError` for a rung this layout cannot draw.  A rung that holds wires
    and unwired NOPs at most comes back as it is.
    """
    net = network_of_rung(rung, af_down)
    found = trees(net)
    if not found:
        return [rung]  # an empty rung (no box, no contact) draws as it is
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
    """The rung as CLICK's syntax check draws it, one ``Rung`` per CLICK rung, or ``None``.

    ``None`` when the rung has no layout: it holds wires and unwired NOPs at most, or
    ``laddercodec.check()`` reports it (its circuit is not series-parallel, a contact or box
    no rail reaches, a shape CLICK's check refuses), or the layout cannot draw it.  Such a
    rung stays as drawn.
    """
    from ..layout_check import check

    if check(rung):
        return None
    try:
        net = network_of_rung(rung)
        found = trees(net)
        return _render(rung, net, found) if found else None
    except LayoutError:
        return None


def circuit(rungs: Sequence[Any]) -> list[object]:
    """The circuits of *rungs*, one per CLICK rung, with every row and column left out.

    Two lists of rungs with equal circuits hold the same contacts, in the same series and
    parallel blocks, feeding the same boxes with the same pin circuits.  A rung that holds
    wires and unwired NOPs at most has no circuit.  Raises :class:`LayoutError` for a rung
    with no series-parallel circuit.
    """
    out: list[object] = []
    for rung in rungs:
        net = network_of_rung(rung)
        for tree in trees(net):
            out.append(_Circuit(net, tree).branch(tree.branch))
    return out


class _Circuit:
    def __init__(self, net: Network, tree: RungTree) -> None:
        self.net = net
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
        """A box without its rows (a pinned box's pin rows are layout), with its pin circuits."""
        b = self.net.sinks[sink].box
        token = self.net.boxes[b].token
        if isinstance(token, PinnedInstruction):
            token = (type(token).__name__, token.to_csv(), token.pin_labels())
        return ("box", token, tuple(sorted(self.pins.get(b, []), key=lambda p: p[0])))

    def node(self, node: Node) -> object:
        if isinstance(node, Leaf):
            contact = node.edge.contact
            if hasattr(contact, "wire_down"):
                return replace(cast(Any, contact), wire_down=False)
            return contact
        if isinstance(node, Out):
            return self.box(node.sink)
        kind = "series" if isinstance(node, Series) else "parallel"
        return (kind, tuple(self.node(c) for c in node.children))
