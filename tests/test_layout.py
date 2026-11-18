"""``read_csv`` and ``write_csv`` draw rungs as CLICK's syntax check draws them.

The layout code is in ``laddercodec._layout``.  The reference is what CLICK v4 copied back
to the clipboard for pasted rungs, before and after its syntax check
(``v4_captures/*_pasted.bin`` and ``*_checked.bin``).  In the checked copy, CLICK has deleted
the rungs that it refused, and each rung that CLICK split appears as its separate parts.
"""

from __future__ import annotations

import copy
import csv as csv_mod
import pickle
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from laddercodec import Code, check, decode, encode, read_csv, write_csv
from laddercodec._layout import LayoutError, canonical, circuit, layout
from laddercodec._layout.network import cell_of
from laddercodec.csv.contract import CSV_HEADER
from laddercodec.csv.converter import convert_literal, convert_rung
from laddercodec.csv.parser import parse_csv_file
from laddercodec.csv.writer import WriterError, decoded_rung_to_rows
from laddercodec.decode import Rung
from laddercodec.instructions import Coil, Contact, Tee
from tests.undecoded_captures import without_marker

V4 = Path(__file__).parent / "fixtures" / "v4_captures"
LADDER = Path(__file__).parent / "fixtures" / "ladder_captures" / "golden"
TUMBLER = Path(__file__).parent / "fixtures" / "tumbler"


def _rungs(name: str | Path) -> list[Rung]:
    got = decode((V4 / name).read_bytes())
    return got


def _through_csv(rungs: list[Rung], tmp_path: Path) -> list[Rung]:
    path = tmp_path / "rungs.csv"
    write_csv(path, rungs)
    return read_csv(path)


def _drawing(rung: Rung) -> tuple[object, ...]:
    return rung.logical_rows, rung.conditions, rung.instructions, rung.comment


_CHECKED = [
    "layoutthy_checked.bin",
    "layoutq_checked.bin",
    "layoutq2_checked.bin",
    "or_compact_checked.bin",
    "r30_tallbox_checked.bin",
    "windy_road_checked.bin",
    "unpowered_nop_checked.bin",
]


@pytest.mark.parametrize("name", _CHECKED)
def test_checked_capture_is_a_fixed_point_of_csv(name: str, tmp_path: Path) -> None:
    """A rung as CLICK's check drew it writes to CSV and reads back unchanged."""
    rungs = _rungs(name)
    assert [_drawing(r) for r in _through_csv(rungs, tmp_path)] == [_drawing(r) for r in rungs]


@pytest.mark.parametrize(
    ("pasted", "checked"),
    [
        ("layoutthy_pasted.bin", "layoutthy_checked.bin"),
        ("layoutq_pasted.bin", "layoutq_checked.bin"),
        ("layoutq2_pasted.bin", "layoutq2_checked.bin"),
        ("or_compact_pasted.bin", "or_compact_checked.bin"),
        ("r30_tallbox_pasted.bin", "r30_tallbox_checked.bin"),
    ],
)
def test_pasted_capture_reads_back_as_checked(pasted: str, checked: str, tmp_path: Path) -> None:
    """Each pasted rung that ``check`` finds no fault in writes to CSV and reads back as
    CLICK's check redrew it."""
    accepted = [r for r in _rungs(pasted) if not check(r)]
    got = _through_csv(accepted, tmp_path)
    assert [_drawing(r) for r in got] == [_drawing(r) for r in _rungs(checked)]


_ALL_CAPTURES = without_marker(sorted(V4.glob("*.bin"))) + sorted(TUMBLER.rglob("*.clipboard.bin"))


@pytest.mark.parametrize("path", _ALL_CAPTURES, ids=lambda p: p.stem)
def test_layout_keeps_the_circuit(path: Path) -> None:
    """The layout may move cells and split a rung, but it draws the circuit of the rung that
    was read."""
    for rung in _rungs(path):
        laid_out = canonical(rung)
        if laid_out is not None:
            assert circuit(laid_out) == circuit([rung]), rung.comment


def _flags(rung: Rung) -> list[list[tuple[str, bool, bool]]]:
    out = []
    for row in rung.conditions:
        cells = []
        for token in row:
            cell = cell_of(token)
            name = cell.contact.to_csv().removeprefix("T:") if cell.contact is not None else ""
            cells.append((name, cell.right, cell.down))
        out.append(cells)
    return out


def _same(a: Rung, b: Rung) -> bool:
    return (
        a.logical_rows == b.logical_rows
        and _flags(a) == _flags(b)
        and [x if isinstance(x, str) else x.to_csv() for x in a.instructions]
        == [x if isinstance(x, str) else x.to_csv() for x in b.instructions]
    )


@pytest.mark.parametrize("name", ["or_compact_checked.bin", "r30_tallbox_checked.bin"])
def test_checked_rungs_are_fixed_points(name: str) -> None:
    for rung in _rungs(name):
        got = layout(rung)
        assert len(got) == 1
        assert _same(got[0], rung)


#: The index of each rung in or_compact_pasted, mapped to the indexes of the rungs in
#: or_compact_checked that CLICK made from it.  CLICK splits pasted rung 1 in two.
_PAIRS = {0: [0], 1: [1, 2], 2: [3], 3: [4], 4: [5]}


@pytest.mark.parametrize("pasted", sorted(_PAIRS))
def test_pasted_rung_lays_out_as_checked(pasted: int) -> None:
    before = _rungs("or_compact_pasted.bin")[pasted]
    after = [_rungs("or_compact_checked.bin")[i] for i in _PAIRS[pasted]]
    got = layout(before)
    assert len(got) == len(after)
    assert all(_same(g, a) for g, a in zip(got, after, strict=True))


def _contact(name: str, *, down: bool = False) -> Contact | Tee:
    return Tee(Contact(name)) if down else Contact(name)


def _rung(conditions: list[list[object]], instructions: list[object]) -> Rung:
    rows = [row + [""] * (31 - len(row)) for row in conditions]
    return Rung(rows, instructions, None)  # type: ignore[arg-type]


def test_bridge_is_not_series_parallel() -> None:
    """``layout`` refuses a Wheatstone bridge with C0001, the id that CLICK's check gives it."""
    # out(Y001) <= X001 X003 | X001 X005 X004 | X002 X004
    rung = _rung(
        [
            [_contact("X001"), _contact("X003", down=True), "-", "T", *["-"] * 27],
            ["", _contact("X005"), "|", "|"],
            [_contact("X002"), "-", _contact("X004")],
        ],
        [Coil("Y001"), "", ""],
    )
    with pytest.raises(LayoutError) as info:
        layout(rung)
    assert info.value.click_id == "C0001"


@pytest.mark.parametrize("clone", [copy.copy, lambda e: pickle.loads(pickle.dumps(e))])
def test_layout_error_pickles_and_copies(clone: Callable[[LayoutError], LayoutError]) -> None:
    error = LayoutError(
        "the rung's circuit is not series-parallel", "C0001", code=Code.NOT_SERIES_PARALLEL
    )
    error.extra = 1
    again = clone(error)
    assert type(again) is LayoutError
    assert (str(again), again.code, again.click_id, again.extra) == (
        str(error),
        Code.NOT_SERIES_PARALLEL,
        "C0001",
        1,
    )


# ---------------------------------------------------------------------------
# A contact on the circuits of two box inputs
# ---------------------------------------------------------------------------

_TIME_DRUM = (
    "time_drum(outputs=[C141],presets=[1000],unit=Tms,pattern=[[1]],"
    "current_step=DS41,accumulator=TD41,completion_flag=C142)"
)


def _csv_row(marker: str, cells: list[str], af: str) -> list[str]:
    """Return a CSV data row with ``cells`` from column A, then wire up to column AE if
    ``af`` is set."""
    return [marker, *cells, *(["-"] if af else [""]) * (31 - len(cells)), af]


def _read_rows(tmp_path: Path, rows: list[list[str]]) -> tuple[Rung, list[Rung]]:
    """Write ``rows`` to a CSV file and return its first rung as drawn, and as ``read_csv``
    lays it out."""
    path = tmp_path / "main.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv_mod.writer(handle).writerows([CSV_HEADER, *rows])
    ast = parse_csv_file(path).rungs[0]
    return convert_literal(ast), convert_rung(ast)


def _contacts(rungs: list[Rung]) -> list[str]:
    return sorted(
        cell.contact.to_csv().removeprefix("T:")
        for rung in rungs
        for row in rung.conditions
        for cell in map(cell_of, row)
        if cell.contact is not None
    )


#: Rungs in which one contact feeds two pin inputs of one box, each with the code that
#: ``check`` reports.  Each pin's circuit is drawn on rows of its own, so a layout would draw
#: the shared contact once for each pin.
_SHARED_PINS = {
    "shift clock and reset": (
        [
            _csv_row("R", ["C1"], "shift(C99..C106)"),
            _csv_row("", ["C5", "T"], ".clock()"),
            _csv_row("", ["", "-"], ".reset()"),
        ],
        "input-without-contact",
    ),
    "count_up down and reset": (
        [
            _csv_row("R", ["C1"], "count_up(CT1,CTD1,preset=5)"),
            _csv_row("", ["rise(C5)", "T"], ".down()"),
            _csv_row("", ["", "-"], ".reset()"),
        ],
        "input-without-contact",
    ),
    "shift reset with a contact of its own": (
        [
            _csv_row("R", ["C1"], "shift(C99..C106)"),
            _csv_row("", ["C5", "T"], ".clock()"),
            _csv_row("", ["", "C6"], ".reset()"),
        ],
        "inputs-share-contacts",
    ),
    "time drum reset and jog past the jump row": (
        [
            _csv_row("R", ["C1"], _TIME_DRUM),
            _csv_row("", ["C5", "T"], ".reset()"),
            _csv_row("", ["", "|"], ""),
            _csv_row("", ["", "-"], ".jog()"),
        ],
        "input-without-contact",
    ),
}


@pytest.mark.parametrize("name", sorted(_SHARED_PINS))
def test_contact_on_two_pins_stays_as_drawn(name: str, tmp_path: Path) -> None:
    rows, kind = _SHARED_PINS[name]
    drawn, got = _read_rows(tmp_path, rows)
    assert got == [drawn]
    (finding,) = check(drawn)
    assert (finding.code, finding.captured) == (kind, False)
    with pytest.raises(LayoutError, match="another pin input"):
        layout(drawn)
    # The decoded rung writes as drawn too.
    [decoded] = decode(encode(drawn))
    assert isinstance(decoded, Rung)
    assert _contacts(_through_csv([decoded], tmp_path)) == _contacts([decoded])


def test_time_drum_jog_sharing_the_reset_is_not_captured(tmp_path: Path) -> None:
    rows, _ = _SHARED_PINS["time drum reset and jog past the jump row"]
    drawn, _ = _read_rows(tmp_path, rows)
    (finding,) = check(drawn)
    assert (finding.click_id, finding.row, finding.column) == (None, 4, 31)
    assert finding.message == (
        "row 4 from 0, column AF: the pin has no contact of its own"
        " (CLICK's response to this shape is not captured)"
    )


def _shift_with_two_pins(tmp_path: Path) -> Rung:
    drawn, got = _read_rows(
        tmp_path,
        [
            _csv_row("R", ["C1"], "shift(C99..C106)"),
            _csv_row("", ["C5"], ".clock()"),
            _csv_row("", ["C6"], ".reset()"),
        ],
    )
    assert got == [drawn]  # already in CLICK's layout
    return drawn


@pytest.mark.parametrize("lose", [False, True], ids=["drawn twice", "drawn twice and lost"])
def test_circuit_catches_a_contact_drawn_twice(
    lose: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A layout that also draws the clock's contact on the reset's rows changes the circuit.

    The test patches ``trees`` to give the reset the clock's circuit, either before the
    reset's own circuit or in place of it.  ``circuit()`` then holds C5 twice and raises, and
    the writer refuses the layout.  ``test_layout_keeps_the_circuit`` would fail on such a
    layout too.
    """
    import laddercodec._layout as layout_mod

    drawn = _shift_with_two_pins(tmp_path)
    real = layout_mod.trees

    def doubled(net):
        found = real(net)
        for tree in found:
            clock, reset = sorted(tree.pins, key=lambda i: net.sinks[i].slot)
            series = tree.pins[clock].series + ([] if lose else tree.pins[reset].series)
            tree.pins[reset] = replace(tree.pins[reset], series=series)
        return found

    monkeypatch.setattr(layout_mod, "trees", doubled)
    parts = canonical(drawn)
    assert parts is not None
    assert _contacts(parts) == (["C1", "C5", "C5"] if lose else ["C1", "C5", "C5", "C6"])
    with pytest.raises(LayoutError, match="2 times"):
        circuit([drawn])
    with pytest.raises(WriterError, match="changed the rung's circuit"):
        decoded_rung_to_rows(drawn)


#: Rungs with a contact on the circuits of two box inputs, where neither input is a pin.  The
#: layout's series-parallel tree holds each contact once.
_SHARED_MAIN = {
    "a box and a branch after it": [
        _csv_row("R", ["C1", "T"], "out(Y1)"),
        _csv_row("", ["", "C2"], "out(Y2)"),
    ],
    "two branches": [
        _csv_row("R", ["C1", "T", "C2"], "out(Y1)"),
        _csv_row("", ["", "-", "C3"], "out(Y2)"),
    ],
    "two boxes, an Or block before them": [
        _csv_row("R", ["C1", "T"], "out(Y1)"),
        _csv_row("", ["C2", "-"], "out(Y2)"),
    ],
    "a pinned box below a branch": [
        _csv_row("R", ["C1", "T", "C2"], "out(Y1)"),
        _csv_row("", ["", "-"], "count_up(CT1,CTD1,preset=5)"),
        _csv_row("", ["C3"], ".reset()"),
    ],
}


@pytest.mark.parametrize("name", sorted(_SHARED_MAIN))
def test_contact_on_two_main_inputs_is_drawn_once(name: str, tmp_path: Path) -> None:
    drawn, got = _read_rows(tmp_path, _SHARED_MAIN[name])
    assert not check(drawn)
    assert _contacts(got) == _contacts([drawn])
    assert circuit(got) == circuit([drawn])


@pytest.mark.parametrize(
    "rows",
    [
        [_csv_row("R", ["C1"], "out(Y1)"), _csv_row("", ["-"], "NOP")],
        [_csv_row("R", ["-"], "NOP"), _csv_row("", ["C2"], "out(Y2)")],
        [_csv_row("R", ["C1"], "out(Y1)"), _csv_row("", ["C2"], "NOP")],
    ],
    ids=["wired from the rail", "first", "behind a contact"],
)
def test_rung_that_would_split_off_a_nop_stays_as_drawn(rows, tmp_path: Path) -> None:
    """A rung whose layout would split a NOP into a rung of its own stays as drawn.

    No capture shows CLICK making that split."""
    drawn, got = _read_rows(tmp_path, rows)
    assert got == [drawn]
    assert canonical(drawn) is None


def test_golden_reads_as_click_checked_its_unpowered_nop() -> None:
    """The golden CSV reads as CLICK's check drew the rungs.

    Reading drops the middle rung's NOP, its wire stubs at columns A and C, and its blank
    row, as CLICK's check does.  CLICK reports no error for that rung."""
    golden = read_csv(LADDER / "mr-cmt-3rung-multirow.csv")
    native = _rungs("unpowered_nop_checked.bin")
    assert [_drawing(r) for r in golden] == [_drawing(r) for r in native]
    assert native[1].logical_rows == 1


def test_unpowered_nop_is_dropped(tmp_path: Path) -> None:
    """A NOP that no rail or contact reaches is dropped, and the rung lays out without it."""
    nop_row = ["", "-", "", "-", *[""] * 28, "NOP"]
    drawn, got = _read_rows(tmp_path, [_csv_row("R", ["C1"], "out(Y1)"), nop_row])
    assert drawn.instructions[1] == "NOP"
    _, alone = _read_rows(tmp_path, [_csv_row("R", ["C1"], "out(Y1)")])
    assert [_drawing(r) for r in got] == [_drawing(r) for r in alone]


def test_unpowered_nop_is_dropped_before_a_split(tmp_path: Path) -> None:
    """After the NOP is dropped, two outputs that meet only at the rail split into two rungs.

    No capture shows CLICK doing both in one rung."""
    rows = [
        _csv_row("R", ["C1"], "out(Y1)"),
        ["", *[""] * 31, "NOP"],
        _csv_row("", ["C2"], "out(Y2)"),
    ]
    drawn, got = _read_rows(tmp_path, rows)
    assert drawn.instructions[1] == "NOP"
    _, one = _read_rows(tmp_path, [_csv_row("R", ["C1"], "out(Y1)")])
    _, two = _read_rows(tmp_path, [_csv_row("R", ["C2"], "out(Y2)")])
    assert [r.conditions for r in got] == [one[0].conditions, two[0].conditions]
    assert [r.instructions for r in got] == [one[0].instructions, two[0].instructions]


def test_nop_behind_a_contact_with_a_coil_lays_out(tmp_path: Path) -> None:
    """A NOP and a coil on one net do not split the rung, and the rung lays out as one."""
    drawn, got = _read_rows(
        tmp_path,
        [_csv_row("R", ["C1", "T"], "out(Y1)"), _csv_row("", ["", "-"], "NOP")],
    )
    assert len(got) == 1
    assert circuit(got) == circuit([drawn])
