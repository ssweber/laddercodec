"""Lay a rung out from its circuit, as CLICK's syntax check draws it (prototype, not wired in).

Pipeline: cell grid -> nets and contact edges (``network``) -> structural series-parallel tree
per CLICK rung (``tree``) -> packed layout (``render``).  See ``scratchpad/layout/design.md``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from .network import GridCell, Network, cell_of, network
from .render import render
from .tree import LayoutError, RungTree, trees

__all__ = ["LayoutError", "Network", "RungTree", "layout", "layout_grid", "network_of_rung"]


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
    """The rung (or rungs, when CLICK splits it) in CLICK's layout; the comment goes on the first."""
    from ..decode import Rung

    net = network_of_rung(rung, af_down)
    out = []
    for i, tree in enumerate(trees(net)):
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
    if not out:
        out.append(rung)  # an empty rung (no box, no contact) draws as it is
    return out
