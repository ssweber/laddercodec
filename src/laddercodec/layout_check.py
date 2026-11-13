"""Report rungs CLICK's syntax check cannot lay out, without raising.

CLICK pastes and saves a rung whose circuit is not series-parallel, or whose contacts no rail
reaches, and reports it only at its syntax check.  laddercodec encodes and writes such rungs as
drawn; ``check()`` reports them.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ._layout.network import AF_X, cell_of, network
from ._layout.tree import Arc, LayoutError, circuits, nothing_to_lay_out, reduce
from .csv.contract import CONDITION_COLUMNS, OUTPUT_COLUMN

if TYPE_CHECKING:
    from .decode import Rung

FindingKind = Literal[
    "not_series_parallel",
    "no_rail",
    "unpowered_box",
    "feeds_no_box",
    "pin_shares_main",
    "shorted_contact",
]

_COLUMN_NAMES = (*CONDITION_COLUMNS, OUTPUT_COLUMN)
_UNKNOWN = "CLICK's response to this shape is not captured"


@dataclass(frozen=True)
class Finding:
    """One shape in a rung that has no CLICK layout.

    Attributes
    ----------
    rung:
        Index of the rung in the checked list, from 0.
    kind:
        ``"not_series_parallel"``: a circuit into a box input is not series-parallel
        (CLICK: C0001).  ``"no_rail"``: a contact whose input has no line connection, by
        wire or contact, from the rail (CLICK: C0202); contacts after it are not reported
        again.  ``"unpowered_box"``: a box input that neither the rail nor any contact
        reaches.  ``"feeds_no_box"``: a contact on a path from the rail that ends at no box
        input.  ``"pin_shares_main"``: a pin input (a timer's or counter's reset, a drum's
        jog) whose circuit shares contacts with a main input.  ``"shorted_contact"``: a
        contact whose two sides a wire joins.
    code:
        CLICK's syntax check error code for the shape (``"C0001"``, ``"C0202"``), or ``None``
        where no code is known.
    captured:
        Whether a CLICK capture shows its syntax check reporting this shape with ``code``.
        ``False`` for every kind with no code, for ``"shorted_contact"``, and for a
        ``"not_series_parallel"`` finding on a pin input (``code`` is ``"C0001"``, as for a
        main input, but no capture shows it).
    row, column:
        The cell, both counted from 0: ``column`` 0 is A and 31 is AF.  ``None`` for a finding
        about the whole circuit.
    message:
        The finding in words, with the cell as ``row <n> (from 0), column <letter>``.  It ends
        with ``(CLICK: <code>)`` when ``captured``, else with ``not captured``.
    """

    rung: int
    kind: FindingKind
    code: str | None
    captured: bool
    row: int | None
    column: int | None
    message: str


def check(rungs: Rung | Iterable[Rung]) -> list[Finding]:
    """Every shape in *rungs* that has no CLICK layout, in rung order.

    Empty means every rung has a series-parallel circuit from the rail into each box.  Findings
    never stop ``encode()`` or ``write_csv()``: the rungs encode as drawn.
    """
    from .decode import Rung  # decode imports csv, which imports decode

    if isinstance(rungs, Rung):
        rungs = [rungs]
    return [finding for index, rung in enumerate(rungs) for finding in _check_rung(index, rung)]


#: (kind, code, whether a CLICK capture shows the code) per rule.
_Rule = tuple[FindingKind, str | None, bool]
_C0001: _Rule = ("not_series_parallel", "C0001", True)
_C0001_PIN: _Rule = ("not_series_parallel", "C0001", False)
_C0202: _Rule = ("no_rail", "C0202", True)
_SHORTED: _Rule = ("shorted_contact", None, False)
_UNPOWERED: _Rule = ("unpowered_box", None, False)
_FEEDS_NO_BOX: _Rule = ("feeds_no_box", None, False)
_PIN_SHARES: _Rule = ("pin_shares_main", None, False)


def _finding(rung: int, rule: _Rule, cell: tuple[int, int] | None, what: str) -> Finding:
    kind, code, captured = rule
    if captured:
        why = f"CLICK: {code}"
    elif code:
        why = f"{code} as for a main input; {_UNKNOWN}"
    else:
        why = _UNKNOWN
    if cell is None:
        return Finding(rung, kind, code, captured, None, None, f"{what} ({why})")
    row, column = cell
    where = f"row {row} (from 0), column {_COLUMN_NAMES[column]}"
    return Finding(rung, kind, code, captured, row, column, f"{where}: {what} ({why})")


def _check_rung(index: int, rung: Rung) -> list[Finding]:
    net = network([[cell_of(t) for t in row] for row in rung.conditions], rung.instructions)
    c = circuits(net)
    if nothing_to_lay_out(net, c.main):
        return []
    rail = net.rail
    out: list[Finding] = []

    def add(rule: _Rule, cell: tuple[int, int] | None, what: str) -> None:
        out.append(_finding(index, rule, cell, what))

    for e in net.edges:
        if e.src != rail and e.src not in c.fed:
            add(_C0202, (e.row, e.col), "the contact's input has no line connection")
    for e in net.bypassed:
        add(_SHORTED, (e.row, e.col), "a wire joins the contact's two sides")
    unpowered = {
        i for i in c.main + c.pins if net.sinks[i].net != rail and net.sinks[i].net not in c.fed
    }
    for i in sorted(unpowered, key=lambda i: net.sinks[i].row):
        add(_UNPOWERED, (net.sinks[i].row, AF_X), "no rail or contact reaches the box")
    used = c.used()
    for a, e in zip(c.arcs, net.edges, strict=True):
        if id(a) not in used and e.src in c.fwd:
            add(_FEEDS_NO_BOX, (e.row, e.col), "the contact's output reaches no box")
    main_used = {id(a) for a in c.main_arcs}
    for i in c.pins:
        s = net.sinks[i]
        cell = (s.row, AF_X)
        if any(id(a) in main_used for a in c.pin_arcs[i]):
            add(_PIN_SHARES, cell, "the pin's circuit shares contacts with a main input")
        elif i not in unpowered and s.net != rail and not _reduces(rail, s.net, c.pin_arcs[i]):
            add(_C0001_PIN, cell, "the pin's circuit is not series-parallel")
    # A box input fed by nothing is reported above; its arc into ``top`` would only stop the
    # reduction, and CLICK's response to it is not captured.
    dead = {net.sinks[i].net for i in unpowered}
    main_arcs = [a for a in c.main_arcs if not (a.dst is c.top and a.src in dead)]
    if main_arcs and not _reduces(rail, c.top, main_arcs):
        add(_C0001, None, "the circuit is not series-parallel")
    return out


def _reduces(source: object, sink: object, arcs: list[Arc]) -> bool:
    try:
        reduce(source, sink, arcs)
    except LayoutError:
        return False
    return True
