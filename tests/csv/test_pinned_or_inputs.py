"""For every pinned box, OR legs on the box's main input push its pins down.

A pinned box is an instruction box with inputs besides its main input, such as a counter's
reset. An OR leg is one row of an OR on an input. Each case builds a rung whose main input
is an OR of N rows, for N of 1, 2, 3 and 8. It checks the rows on which the converter places
the pins. It also checks that encoding and then decoding gives the rung back, and that the
writer produces the same CSV rows.

The N=1 shapes are those of the coverage golden files, which tests/test_coverage.py compares
byte for byte. A tall OR is an OR of more than one row. Two tall-OR shapes are checked
against CLICK. A timer without ``.reset()`` keeps its 2-row box beside a tall OR, and
tests/test_v4_captures.py checks count_down's tall OR. The other tall-OR shapes follow
laddercodec's rule that a leg under one input pushes every later pin down. They are not
checked against CLICK.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from laddercodec import decode, encode
from laddercodec.csv import read_csv
from laddercodec.csv.contract import CSV_HEADER
from laddercodec.csv.converter import CsvReadError
from laddercodec.csv.writer import CsvWriteError, decoded_rung_to_rows
from laddercodec.decode import Rung
from laddercodec.instructions import Coil, Contact, Counter, Drum, Timer
from laddercodec.model import PinnedInstruction

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
COLUMNS = 31

EVENT_DRUM = (
    "event_drum(outputs=[C183,C184],events=[C185,C186],pattern=[[1,0],[0,1]],"
    "current_step=DS182,completion_flag=C187)"
)
TIME_DRUM = (
    "time_drum(outputs=[C206,C207],presets=[1000,2000],unit=Tms,pattern=[[1,0],[0,1]],"
    "current_step=DS185,accumulator=TD4,completion_flag=C208)"
)
TIME_EVENT_DRUM = (
    "time_event_drum(outputs=[C1311,C1312,C1313],presets=[1000,None,500],"
    "events=[None,C1501,C1502],unit=Tms,pattern=[[1,0,0],[0,1,0],[0,0,1]],"
    "current_step=DS1201,accumulator=TD101,completion_flag=C1401)"
)


def _or_input(n: int) -> list[list[str]]:
    """Return the condition rows of X001 in series with an OR of ``n`` rows.

    The rows are laid out as pyrung writes them. The addresses are in display form, because
    the writer writes that form.
    """
    if n == 1:
        return [["X001", "X002"] + ["-"] * (COLUMNS - 2)]
    rows = [["X001", "T:X002", "T"] + ["-"] * (COLUMNS - 3)]
    for k in range(1, n - 1):
        rows.append(["", f"T:X{k + 2:03d}", "|"] + [""] * (COLUMNS - 3))
    rows.append(["", f"X{n + 1:03d}"] + [""] * (COLUMNS - 2))
    return rows


def _pin_row(index: int) -> list[str]:
    return [f"Y{index + 1:03d}"] + ["-"] * (COLUMNS - 1)


def _csv_rows(token: str, n: int, pins: tuple[str, ...]) -> list[list[str]]:
    conds = _or_input(n)
    rows = [["R", *conds[0], token]]
    rows += [["", *row, ""] for row in conds[1:]]
    rows += [["", *_pin_row(i), pin] for i, pin in enumerate(pins)]
    return rows


def _write(path: Path, rows: list[list[str]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        writer.writerows(rows)
    return path


def _roundtrip(rung: Rung) -> Rung:
    [back] = decode(encode(rung))
    assert isinstance(back, Rung)
    assert back.logical_rows == rung.logical_rows
    assert back.conditions == rung.conditions
    assert back.instructions == rung.instructions
    return back


# (id, token, pins, expected pin_rows for an N-row OR input)
CASES = [
    ("on_delay_retentive", "on_delay(T2,TD2,preset=5000,unit=Tms)", (".reset()",), lambda n: (n,)),
    ("on_delay", "on_delay(T1,TD1,preset=3000,unit=Tms)", (), lambda n: (1,)),
    ("off_delay", "off_delay(T3,TD3,preset=2000,unit=Tms)", (), lambda n: (1,)),
    ("count_up", "count_up(CT1,CTD1,preset=100)", (".reset()",), lambda n: (n, n + 1)),
    (
        "count_up_down",
        "count_up(CT2,CTD2,preset=100)",
        (".down()", ".reset()"),
        lambda n: (n, n + 1),
    ),
    ("count_down", "count_down(CT3,CTD3,preset=50)", (".reset()",), lambda n: (1, n + 1)),
    ("shift", "shift(C99..C106)", (".clock()", ".reset()"), lambda n: (n, n + 1)),
    ("event_drum", EVENT_DRUM, (".reset()",), lambda n: (n, n + 1, n + 2)),
    ("time_drum", TIME_DRUM, (".reset()",), lambda n: (n, n + 1, n + 2)),
    ("time_event_drum", TIME_EVENT_DRUM, (".reset()",), lambda n: (n, n + 1, n + 2)),
]


@pytest.mark.parametrize("n", [1, 2, 3, 8])
@pytest.mark.parametrize(
    ("token", "pins", "expected"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_or_input_pushes_pins_down(
    tmp_path: Path, token: str, pins: tuple[str, ...], expected, n: int
) -> None:
    rows = _csv_rows(token, n, pins)
    (rung,) = read_csv(_write(tmp_path / "main.csv", rows))

    box = rung.instructions[0]
    assert isinstance(box, PinnedInstruction)
    assert box.pin_rows == expected(n)
    # The box ends at its last pin. A timer without .reset() is 2 rows tall, so the rest of
    # its OR's rows sit below the box.
    assert rung.logical_rows == max(box.pin_rows[-1] + 1, len(rows))
    assert all(af in ("", "NOP") for af in rung.instructions[1:])
    if box.lead_rows:
        assert rung.instructions[box.lead_rows] == "NOP"

    back = _roundtrip(rung)
    assert decoded_rung_to_rows(back) == rows


@pytest.mark.parametrize("n", [2, 3, 8])
def test_count_down_bridge_and_lead_row_forms(tmp_path: Path, n: int) -> None:
    """count_down's NOP-bridge and lead-row CSV forms both accept OR legs on Down's input.

    In the NOP-bridge form, the token is on the first row and a NOP marks Down's row under
    it. In the lead-row form, the first row has no AF and the token is on Down's row. In both
    forms, C1 on the first row is one more leg of Down's input. The layout draws C1 on the
    Down row, as CLICK's syntax check does, with the rest of the OR below it.
    """
    conds = _or_input(n)
    lead = ["C1"] + ["-"] * 6 + ["T"] + [""] * (COLUMNS - 8)
    token = "count_down(CT3,CTD3,preset=50)"
    tail = [["", *row, ""] for row in conds[1:]] + [["", *_pin_row(0), ".reset()"]]
    bridge = [["R", *lead, token], ["", *conds[0], "NOP"], *tail]
    leading = [["R", *lead, ""], ["", *conds[0], token], *tail]

    (from_bridge,) = read_csv(_write(tmp_path / "bridge.csv", bridge))
    (from_leading,) = read_csv(_write(tmp_path / "leading.csv", leading))
    assert from_bridge.conditions == from_leading.conditions
    assert from_bridge.instructions == from_leading.instructions
    counter = from_bridge.instructions[0]
    assert isinstance(counter, Counter)
    assert counter.pin_rows == (1, n + 2)
    assert from_bridge.conditions[1][0] == Contact("C1")

    back = _roundtrip(from_bridge)
    (again,) = read_csv(_write(tmp_path / "again.csv", decoded_rung_to_rows(back)))
    assert again == from_bridge


def test_count_down_rejects_bridge_below_legs(tmp_path: Path) -> None:
    conds = _or_input(2)
    rows = [
        ["R", *conds[0], "count_down(CT3,CTD3,preset=50)"],
        ["", *conds[1], ""],
        ["", *_pin_row(0), "NOP"],
    ]
    with pytest.raises(CsvReadError, match="the row with NOP in column AF is the box.s Down input"):
        read_csv(_write(tmp_path / "main.csv", rows))


def test_count_down_rejects_bridge_under_a_lead_row(tmp_path: Path) -> None:
    """A blank-AF row above count_down() and a NOP row under it both claim the Up row."""

    def wired(first: str) -> list[str]:
        return [first] + ["-"] * (COLUMNS - 1)

    rows = [
        ["R", *wired("C1"), ""],
        ["", *wired("X001"), "count_down(CT3,CTD3,preset=50)"],
        ["", *wired("X002"), "NOP"],
        ["", *wired("Y001"), ".reset()"],
    ]
    with pytest.raises(
        CsvReadError, match=r"has only one Up row.* Leave no blank-AF row directly above count_down"
    ):
        read_csv(_write(tmp_path / "main.csv", rows))


def test_timer_rejects_foreign_pin(tmp_path: Path) -> None:
    rows = _csv_rows("on_delay(T1,TD1,preset=3000,unit=Tms)", 2, (".down()",))
    with pytest.raises(
        CsvReadError, match=r"on_delay\(\) has no \.down\(\) pin. Its only pin is \.reset\(\)"
    ):
        read_csv(_write(tmp_path / "main.csv", rows))


def test_conformance_count_down_rungs() -> None:
    """Three count_down rungs with a tall OR on Down read with the expected pin rows."""
    rungs = read_csv(FIXTURES / "pinned_or" / "conf_counters_count_down.csv")
    expected = {
        "counters/count_down_negative": (1, 4),
        "counters/acc_clamps_at_dint_range": (1, 5),
        "counters/count_down_done_at_preset": (1, 9),
    }
    assert [r.comment for r in rungs] == list(expected)
    for rung in rungs:
        counter = rung.instructions[0]
        assert isinstance(counter, Counter)
        assert counter.kind == "count_down"
        assert counter.reset_enabled
        assert counter.pin_rows == expected[rung.comment or ""]
        assert rung.instructions[1] == "NOP"
        assert rung.logical_rows == counter.pin_rows[-1] + 1
        _roundtrip(rung)


def test_native_timer_beside_tall_or_input() -> None:
    """CLICK keeps a non-retentive timer at 2 rows beside a 4-row OR input."""
    tumbler = FIXTURES / "tumbler" / "subroutines"
    native = decode((tumbler / "ProductionErrors.clipboard.bin").read_bytes())
    assert isinstance(native, list)
    from_csv = read_csv(tumbler / "ProductionErrors.clipboard.csv")
    timers = 0
    for ours, theirs in zip(from_csv, native, strict=True):
        for a, b in zip(ours.instructions, theirs.instructions, strict=True):
            if isinstance(b, Timer):
                timers += 1
                assert isinstance(a, Timer)
                assert a.pin_rows == b.pin_rows == (1,)
                assert a.build_blob() == b.build_blob()
    assert timers


# ---------------------------------------------------------------------------
# Writer: decoded rungs whose box rows must keep their place in the CSV
# ---------------------------------------------------------------------------


def _wire(op: str) -> list:
    return [Contact(op)] + ["-"] * (COLUMNS - 1)


def _empty() -> list:
    return [""] * COLUMNS


def _timer() -> Timer:
    return Timer("on_delay", "T1", "TD1", "5", "Tms")


def _count_down() -> Counter:
    return Counter("count_down", "CT1", "CTD1", "5", reset_enabled=True)


def _drum(pin_rows: tuple[int, int, int] = (1, 2, 3)) -> Drum:
    return Drum(
        kind="event_drum",
        outputs=["C1", "C2"],
        events=["C3", "C4"],
        pattern=[[1, 0], [0, 1]],
        current_step="DS1",
        completion_flag="C5",
        pin_rows=pin_rows,
    )


WRITER_CASES = {
    # The writer keeps the empty row of an unused pin when a row with a blank AF follows
    # the box.
    "timer_then_floating_row": ([_wire("X1"), _empty(), _wire("X2")], [_timer(), "", ""]),
    "drum_then_floating_row": (
        [_wire("X1"), _wire("X9"), _empty(), _empty(), _wire("X2")],
        [_drum(), "", "", "", ""],
    ),
    # The writer writes count_down's empty lead row when a row with a blank AF is above it.
    "count_down_under_or_leg": (
        [_wire("X1"), _wire("X2"), _empty(), _wire("X3"), _wire("X4")],
        [Coil("Y1"), "", _count_down(), "NOP", ""],
    ),
    # The writer keeps the empty row of the timer box above count_down, so that count_down's
    # lead row reads back as its lead row.
    "timer_then_count_down_lead": (
        [_wire("X1"), _empty(), _wire("X2"), _wire("X3"), _wire("X4")],
        [_timer(), "", _count_down(), "NOP", ""],
    ),
}


@pytest.mark.parametrize("name", list(WRITER_CASES))
def test_writer_keeps_box_rows_in_place(name: str) -> None:
    conds, afs = WRITER_CASES[name]
    rung = Rung(conditions=conds, instructions=afs, comment=None)
    (back,) = read_csv_rows(decoded_rung_to_rows(rung))
    assert back.conditions == rung.conditions
    assert back.instructions == rung.instructions


@pytest.mark.filterwarnings("ignore:CSV round-trip lost")
def test_writer_names_pin_rows_csv_cannot_express() -> None:
    """The writer names the pin rows when the CSV cannot place the pins where they are.

    The drum's pins are on rows 1, 3 and 4, its jump and jog pins are off, and X8 is a leg
    on row 2. The CSV reads back with the pins on rows 1, 2 and 3.
    """
    conds = [_wire("X1"), _wire("X9"), _wire("X8"), _empty(), _empty()]
    rung = Rung(
        conditions=conds,
        instructions=[_drum((1, 3, 4)), "", "", "", ""],
        comment=None,
    )
    with pytest.raises(CsvWriteError, match=r"pins on rows \(1, 3, 4\).*\(1, 2, 3\)"):
        decoded_rung_to_rows(rung)


def read_csv_rows(rows: list[list[str]]) -> list[Rung]:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        return read_csv(_write(Path(tmp) / "main.csv", rows))
