"""Lay a rung out from its circuit, as CLICK's syntax check draws it.

The work runs in three steps.  ``network`` reads the cell grid into nets and contact edges.
``tree`` reduces the nets to one series-parallel tree for each CLICK rung, by structure
alone.  ``render`` draws each tree in the packed layout.  ``docs/internals/layout.md`` gives
the rules.  ``read_csv`` and ``write_csv`` use :func:`canonical`.  ``laddercodec.check()``
uses ``network`` and ``tree.circuits``.  Its program rules read each rung through
:func:`as_checked`.  ``build`` makes the network from a public
``Circuit`` for ``laddercodec.lay_out()``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any, cast

from ..codes import Code
from ..encode import MAX_ROWS
from ..model import Instruction, PinnedInstruction
from ..operands.unchecked import stored_cell_rows
from .network import GridCell, Network, cell_of, network, without_rail_nops
from .render import render, render_rows
from .tree import LayoutError, Leaf, Node, Out, OutputBranch, RungTree, SeriesNode, trees

__all__ = [
    "LayoutError",
    "Network",
    "RungTree",
    "as_checked",
    "canonical",
    "circuit",
    "drawn",
    "layout",
    "layout_grid",
    "network_of_rung",
    "rows_needed",
    "too_tall_message",
]


def rows_needed(rung: Any) -> int:
    """Return the number of rows that CLICK needs for *rung*.

    That is the number of rows in the rung, or more if a box runs past the rung's last row.
    A box spans the rows that ``encode()`` writes for it: ``visual_rows`` of its
    ``cell_params()``, or the row span stored with a decoded instruction's blob.
    """
    height = len(rung.conditions)
    for row, token in enumerate(rung.instructions):
        if isinstance(token, Instruction):
            params = {**token.cell_params(), **stored_cell_rows(token)}
            height = max(height, row + int(params.get("visual_rows", 1)))
    return height


def too_tall_message(subject: str, rows: int, parts: int = 1, k: int = 1) -> str:
    """Return the message for *subject*, a rung that needs more rows than CLICK holds.

    When *parts* is 1, the rung itself needs *rows* rows.  Otherwise CLICK splits the rung
    into *parts* rungs, and rung *k* of them, counted from 1, needs *rows* rows.
    """
    limit = f"and a CLICK rung holds at most {MAX_ROWS}. Split it into rungs of {MAX_ROWS} rows"
    fix = (
        f"{limit} or fewer. For example, move some of its outputs, with the contacts that feed "
        "them, to a rung of their own."
    )
    if parts == 1:
        return f"{subject} needs {rows} rows, {fix}"
    within = subject[:1].lower() + subject[1:]
    return f"CLICK splits {within} into {parts} rungs. Rung {k} of them needs {rows} rows, {fix}"


def drawn(rung: Any, subject: str = "The rung") -> tuple[list[Any], bool]:
    """Return the rungs that ``read_csv`` and ``write_csv`` keep for *rung*, and whether they
    are in CLICK's layout.

    They are the rungs that :func:`canonical` returns when the rung has a layout.
    Otherwise they are the rung itself, as drawn.  Raises :class:`LayoutError` with the code
    ``layout-too-tall`` if one of them needs more than 32 rows.  The message names
    *subject*.  The height is checked here, after the choice between the layout and the
    rung as drawn, because ``render()`` never sees a rung that has no layout.
    """
    parts = canonical(rung)
    kept, exact = ([rung], False) if parts is None else (parts, True)
    for k, part in enumerate(kept, start=1):
        rows = rows_needed(part)
        if rows > MAX_ROWS:
            message = too_tall_message(subject, rows, len(kept), k)
            raise LayoutError(message, code=Code.LAYOUT_TOO_TALL)
    return kept, exact


def network_of_rung(rung: Any, af_down: Sequence[bool] | None = None) -> Network:
    """Return the network that the layout draws for a ``Rung`` that was decoded or read
    from CSV.

    If the rung has a box that is not a NOP on the rail's net, the network leaves out each NOP
    on the rail's net.
    """
    cells = [[cell_of(t) for t in row] for row in rung.conditions]
    return without_rail_nops(network(cells, list(rung.instructions), af_down))


def layout_grid(
    cells: Sequence[Sequence[GridCell]],
    instructions: Sequence[object],
    af_down: Sequence[bool] | None = None,
) -> list[tuple[list[list[object]], list[object]]]:
    """Lay out a cell grid and return each CLICK rung it makes, as (condition rows, AF tokens)."""
    net = without_rail_nops(network(cells, instructions, af_down))
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
    return [part for part, _ in _render_rows(rung, net, found)]


def _render_rows(
    rung: Any, net: Network, found: list[RungTree]
) -> list[tuple[Any, list[int | None]]]:
    from ..decode import Rung

    out = []
    for i, tree in enumerate(found):
        conditions, instructions, rows = render_rows(net, tree)
        part = Rung(
            conditions=cast(Any, conditions),
            instructions=cast(Any, instructions),
            comment=rung.comment if i == 0 else None,
            comment_rtf=rung.comment_rtf if i == 0 else None,
        )
        out.append((part, rows))
    return out


def as_checked(rung: Any) -> list[tuple[Any, list[int | None]]]:
    """Return the rungs that CLICK's syntax check reads in place of *rung*, each paired with
    a list of rows.

    The rungs are those that :func:`canonical` returns.  When :func:`canonical` returns
    ``None``, the only rung is *rung* as you wrote it.  A rung's list has one entry for each
    of its rows.  The entry is the row of *rung* that the row's AF token comes from.  It is
    ``None`` when the AF token is not one of *rung*, such as the ``NOP`` that the layout puts
    on the main input's row of a pinned box.
    """
    parts = _canonical_rows(rung)
    if parts is None:
        return [(rung, list(range(len(rung.instructions))))]
    return parts


def canonical(rung: Any) -> list[Any] | None:
    """Return the rung as CLICK's syntax check draws it, one ``Rung`` per CLICK rung, or ``None``.

    Return ``None`` when the rung has no layout.  That happens in three cases:

    - The rung has no contact, and no box except NOPs that no rail or contact reaches.
    - ``laddercodec.check()`` reports the rung.  For example, its circuit is not
      series-parallel, no rail reaches one of its contacts or boxes, or CLICK's check refuses
      its shape.
    - The layout cannot draw the rung.

    The caller keeps such a rung as it was drawn.  Three findings of ``check()`` still allow
    a layout.  The first is ``layout-too-tall``, because CLICK may split the rung into rungs
    that each fit.  :func:`drawn` checks the height of the rungs that the caller keeps.  The
    second is a pin that no rail or contact reaches.  The layout draws the pin's
    row blank, the same way CLICK saves a pin whose row holds nothing.  The third is a contact
    that feeds only a NOP.  The layout draws that rung like any other.  CLICK keeps that layout
    when the rung is pasted.  What CLICK's check reports for the rung as written is not
    captured.
    """
    parts = _canonical_rows(rung)
    return None if parts is None else [part for part, _ in parts]


def _canonical_rows(rung: Any) -> list[tuple[Any, list[int | None]]] | None:
    """Return the rungs of :func:`canonical` with the rows of :func:`as_checked`, or ``None``."""
    from ..layout_check import check

    allowed = (Code.LAYOUT_TOO_TALL, Code.UNWIRED_INPUT, Code.CONTACT_FEEDS_ONLY_NOP)
    if any(f.code not in allowed for f in check(rung)):
        return None
    try:
        net = network_of_rung(rung)
        found = trees(net)
        return _render_rows(rung, net, found) if found else None
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

    def branch(self, branch: OutputBranch) -> object:
        items = tuple(
            self.branch(item) if isinstance(item, OutputBranch) else self.box(item.sink)
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
            return node.edge.contact
        if isinstance(node, Out):
            return self.box(node.sink)
        kind = "series" if isinstance(node, SeriesNode) else "parallel"
        return (kind, tuple(self.node(c) for c in node.children))
