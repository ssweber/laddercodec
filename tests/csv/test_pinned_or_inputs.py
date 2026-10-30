"""OR legs on a pinned box's main input push its pins down, for every pinned box.

Each case builds a rung whose main input is an OR of N rows (1, 2, 3, 8),
then checks the pin rows the converter lays out, that encode → decode gives
the rung back, and that the writer emits the same CSV rows.

Ground truth: the N=1 shapes are the CLICK-verified coverage goldens
(tests/test_coverage.py, byte for byte).  A timer without ``.reset()`` keeps
its 2-row box beside a tall OR (native: tumbler ProductionErrors, checked
below).  The other tall-OR shapes follow the rule CLICK showed for legs under
a later pin (v4_captures/pins.bin) and still need a CLICK capture.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from laddercodec import decode, encode
from laddercodec.csv import read_csv
from laddercodec.csv.contract import CSV_HEADER
from laddercodec.csv.converter import ConvertError
from laddercodec.csv.writer import WriterError, decoded_rung_to_rows
from laddercodec.decode import Rung
from laddercodec.instructions import Coil, Contact, Counter, Drum, Timer
from laddercodec.model import InstructionType, PinnedInstruction

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
    """Condition rows of an input gated by X1 and ORed over ``n`` rows (as pyrung writes it)."""
    if n == 1:
        return [["X1", "X2"] + ["-"] * (COLUMNS - 2)]
    rows = [["X1", "T:X2", "T"] + ["-"] * (COLUMNS - 3)]
    for k in range(1, n - 1):
        rows.append(["", f"T:X{k + 2}", "|"] + [""] * (COLUMNS - 3))
    rows.append(["", f"X{n + 1}"] + [""] * (COLUMNS - 2))
    return rows


def _pin_row(index: int) -> list[str]:
    return [f"Y{index + 1}"] + ["-"] * (COLUMNS - 1)


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
    back = decode(encode(rung))
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
    # The box ends at its last pin; a 2-row timer's further legs sit below it.
    assert rung.logical_rows == max(box.pin_rows[-1] + 1, len(rows))
    assert all(af in ("", "NOP") for af in rung.instructions[1:])
    if box.lead_rows:
        assert rung.instructions[box.lead_rows] == "NOP"

    back = _roundtrip(rung)
    assert decoded_rung_to_rows(back) == rows


@pytest.mark.parametrize("n", [2, 3, 8])
def test_count_down_bridge_and_lead_row_forms(tmp_path: Path, n: int) -> None:
    """count_down's NOP-bridge and lead-row CSV forms take OR legs too."""
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
    assert counter.pin_rows == (1, n + 1)

    back = _roundtrip(from_bridge)
    assert decoded_rung_to_rows(back) == leading


def test_count_down_rejects_bridge_below_legs(tmp_path: Path) -> None:
    conds = _or_input(2)
    rows = [
        ["R", *conds[0], "count_down(CT3,CTD3,preset=50)"],
        ["", *conds[1], ""],
        ["", *_pin_row(0), "NOP"],
    ]
    with pytest.raises(ConvertError, match="NOP bridge row"):
        read_csv(_write(tmp_path / "main.csv", rows))


def test_timer_rejects_foreign_pin(tmp_path: Path) -> None:
    rows = _csv_rows("on_delay(T1,TD1,preset=3000,unit=Tms)", 2, (".down()",))
    with pytest.raises(ConvertError, match="not supported for on_delay"):
        read_csv(_write(tmp_path / "main.csv", rows))


def test_conformance_count_down_rungs() -> None:
    """pyrung's Conf_Counters count_down cases (ClickNick Guided Paste failures)."""
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
        assert counter.counter_type == "count_down"
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
    return [Contact(type=InstructionType.CONTACT_NO, operand=op)] + ["-"] * (COLUMNS - 1)


def _empty() -> list:
    return [""] * COLUMNS


def _timer() -> Timer:
    return Timer("on_delay", "T1", "TD1", "5", "Tms")


def _count_down() -> Counter:
    return Counter("count_down", "CT1", "CTD1", "5", reset_enabled=True)


def _drum(pin_rows: tuple[int, int, int] = (1, 2, 3)) -> Drum:
    return Drum(
        drum_kind="event",
        outputs=["C1", "C2"],
        events_or_presets=["C3", "C4"],
        pattern=[[1, 0], [0, 1]],
        current_step="DS1",
        completion_flag="C5",
        pin_rows=pin_rows,
    )


WRITER_CASES = {
    # An empty unused-pin row stays when a floating blank-AF row follows the box.
    "timer_then_floating_row": ([_wire("X1"), _empty(), _wire("X2")], [_timer(), "", ""]),
    "drum_then_floating_row": (
        [_wire("X1"), _wire("X9"), _empty(), _empty(), _wire("X2")],
        [_drum(), "", "", "", ""],
    ),
    # count_down's empty lead row is written when a blank-AF row sits above it.
    "count_down_under_or_leg": (
        [_wire("X1"), _wire("X2"), _empty(), _wire("X3"), _wire("X4")],
        [Coil(type=InstructionType.COIL_OUT, operand="Y1"), "", _count_down(), "NOP", ""],
    ),
    # A box above count_down keeps its padding, so the lead row stays the lead row.
    "timer_then_count_down_lead": (
        [_wire("X1"), _empty(), _wire("X2"), _wire("X3"), _wire("X4")],
        [_timer(), "", _count_down(), "NOP", ""],
    ),
}


@pytest.mark.parametrize("name", list(WRITER_CASES))
def test_writer_keeps_box_rows_in_place(name: str) -> None:
    conds, afs = WRITER_CASES[name]
    rung = Rung(logical_rows=len(conds), conditions=conds, instructions=afs, comment=None)
    (back,) = read_csv_rows(decoded_rung_to_rows(rung))
    assert back.conditions == rung.conditions
    assert back.instructions == rung.instructions


@pytest.mark.filterwarnings("ignore:CSV round-trip lost")
def test_writer_names_pin_rows_csv_cannot_express() -> None:
    """A leg on the row of an unused trailing pin (drum 01 03 04, jump/jog off)."""
    conds = [_wire("X1"), _wire("X9"), _wire("X8"), _empty(), _empty()]
    rung = Rung(
        logical_rows=5,
        conditions=conds,
        instructions=[_drum((1, 3, 4)), "", "", "", ""],
        comment=None,
    )
    with pytest.raises(WriterError, match=r"pins on rows \(1, 3, 4\).*\(1, 2, 3\)"):
        decoded_rung_to_rows(rung)


def read_csv_rows(rows: list[list[str]]) -> list[Rung]:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        return read_csv(_write(Path(tmp) / "main.csv", rows))
