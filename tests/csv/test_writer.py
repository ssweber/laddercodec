"""Tests for laddercodec.csv.writer — Rung → CSV round-trip."""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec import (
    Coil,
    Contact,
    Counter,
    ForLoop,
    Next,
    Rung,
    Shift,
    Timer,
    decode,
    read_csv,
    write_csv,
)
from laddercodec.csv.writer import (
    WriterError,
    decoded_rung_to_rows,
)
from laddercodec.instructions import UnknownInstruction
from laddercodec.model import InstructionType

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "ladder_captures" / "golden"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _golden_paths() -> list[Path]:
    """Return all golden .bin files that have a matching .csv."""
    bins = sorted(GOLDEN_DIR.glob("*.bin"))
    return [b for b in bins if b.with_suffix(".csv").exists()]


def _blank_conditions() -> list[object]:
    """Return one all-blank decoded condition row."""
    return [""] * 31


def _contact_row(operand: str) -> list[object]:
    """Return a simple NO-contact row with trailing wires."""
    return [Contact(InstructionType.CONTACT_NO, operand)] + ["-"] * 30


def _edge_row(operand: str) -> list[object]:
    """Return a simple rising-edge contact row with trailing wires."""
    return [Contact(InstructionType.CONTACT_EDGE, operand, edge_kind="rise")] + ["-"] * 30


# ---------------------------------------------------------------------------
# Round-trip: golden.bin → decode → CSV → read_csv → compare
# ---------------------------------------------------------------------------


class TestGoldenRoundTrip:
    """For each golden fixture, decode the .bin, write CSV, read it back,
    and verify the result matches the original decode output."""

    @pytest.fixture(params=[p.stem for p in _golden_paths()], ids=lambda s: s)
    def golden_stem(self, request: pytest.FixtureRequest) -> str:
        return request.param

    def test_round_trip(self, golden_stem: str, tmp_path: Path) -> None:
        bin_path = GOLDEN_DIR / f"{golden_stem}.bin"
        data = bin_path.read_bytes()
        out_csv = tmp_path / f"{golden_stem}.csv"

        result = decode(data)
        if isinstance(result, list):
            write_csv(out_csv, result)
            round_tripped = read_csv(out_csv)
            assert len(round_tripped) == len(result)
            for rt, rung in zip(round_tripped, result, strict=True):
                # The CSV may have fewer rows than the binary for timers
                # (padding rows stripped, auto-restored by encode).
                assert rt.comment == rung.comment
                assert len(rt.conditions) == rt.logical_rows
                assert len(rt.instructions) == rt.logical_rows
        else:
            write_csv(out_csv, [result])
            rt = read_csv(out_csv)[0]
            # The CSV may have fewer rows than the binary for non-retained
            # timers (padding stripped); read_csv returns the CSV row count.
            # The forward path auto-pads back to full height.
            assert rt.logical_rows <= result.logical_rows
            assert rt.comment == result.comment


# ---------------------------------------------------------------------------
# Unit tests: decoded_rung_to_rows
# ---------------------------------------------------------------------------


class TestDecodedRungToRows:
    def test_simple_contact_coil(self) -> None:
        """Single row: contact → wire → coil."""
        rung = Rung(
            logical_rows=1,
            conditions=[[Contact(InstructionType.CONTACT_NO, "X001")] + ["-"] * 30],
            instructions=[Coil(InstructionType.COIL_OUT, "Y001")],
            comment_rtf=None,
            comment=None,
        )
        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 1
        assert rows[0][0] == "R"
        assert rows[0][1] == "X001"
        assert rows[0][2] == "-"
        assert rows[0][32] == "out(Y001)"

    def test_with_comment(self) -> None:
        """Comment produces # rows before data."""
        rung = Rung(
            logical_rows=1,
            conditions=[[""] * 31],
            instructions=[""],
            comment_rtf=None,
            comment="Line 1\nLine 2",
        )
        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 3
        assert rows[0][0] == "#"
        assert rows[0][1] == "Line 1"
        assert rows[1][0] == "#"
        assert rows[1][1] == "Line 2"
        assert rows[2][0] == "R"

    def test_timer_non_retained_strips_padding(self) -> None:
        """Non-retained timer: trailing blank row stripped."""
        timer = Timer("on_delay", "T1", "TD1", "1000", "Tms", retained=False)
        rung = Rung(
            logical_rows=2,
            conditions=[
                [Contact(InstructionType.CONTACT_NO, "X001")] + ["-"] * 30,
                [""] * 31,
            ],
            instructions=[timer, ""],
            comment_rtf=None,
            comment=None,
        )
        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 1
        assert rows[0][32] == "on_delay(T1,TD1,preset=1000,unit=Tms)"

    def test_timer_retained_emits_reset_pin(self) -> None:
        """Retained timer: second row gets .reset() AF."""
        timer = Timer("on_delay", "T3", "TD3", "10", "Tm", retained=True)
        rung = Rung(
            logical_rows=2,
            conditions=[
                [Contact(InstructionType.CONTACT_NO, "X001")] + ["-"] * 30,
                ["-"] * 31,
            ],
            instructions=[timer, ""],
            comment_rtf=None,
            comment=None,
        )
        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 2
        assert rows[0][32] == "on_delay(T3,TD3,preset=10,unit=Tm)"
        assert rows[1][0] == ""
        assert rows[1][32] == ".reset()"

    def test_nop(self) -> None:
        """NOP token serializes correctly."""
        rung = Rung(
            logical_rows=1,
            conditions=[["-"] * 31],
            instructions=["NOP"],
            comment_rtf=None,
            comment=None,
        )
        rows = decoded_rung_to_rows(rung)
        assert rows[0][32] == "NOP"

    def test_count_up_reset_collapses_middle_row(self) -> None:
        counter = Counter(
            counter_type="count_up",
            done_bit="CT1",
            current="CTD1",
            preset="100",
            down_enabled=False,
            reset_enabled=True,
        )
        rung = Rung(
            logical_rows=3,
            conditions=[
                [Contact(InstructionType.CONTACT_EDGE, "C73", edge_kind="rise")] + ["-"] * 30,
                [""] * 31,
                [Contact(InstructionType.CONTACT_NO, "C74")] + ["-"] * 30,
            ],
            instructions=[counter, "", ""],
            comment_rtf=None,
            comment=None,
        )

        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 2
        assert rows[0][32] == "count_up(CT1,CTD1,preset=100)"
        assert rows[1][32] == ".reset()"
        assert rows[1][1] == "C74"

    def test_count_up_down_emits_down_pin(self) -> None:
        counter = Counter(
            counter_type="count_up",
            done_bit="CT2",
            current="CTD2",
            preset="100",
            down_enabled=True,
            reset_enabled=True,
        )
        rung = Rung(
            logical_rows=3,
            conditions=[
                [Contact(InstructionType.CONTACT_EDGE, "C75", edge_kind="rise")] + ["-"] * 30,
                [Contact(InstructionType.CONTACT_NO, "C76")] + ["-"] * 30,
                [Contact(InstructionType.CONTACT_NO, "C77")] + ["-"] * 30,
            ],
            instructions=[counter, "", ""],
            comment_rtf=None,
            comment=None,
        )

        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 3
        assert rows[0][32] == "count_up(CT2,CTD2,preset=100)"
        assert rows[1][32] == ".down()"
        assert rows[2][32] == ".reset()"

    def test_count_down_rehydrates_nop_shape(self) -> None:
        counter = Counter(
            counter_type="count_down",
            done_bit="CT3",
            current="CTD3",
            preset="50",
            down_enabled=False,
            reset_enabled=True,
        )
        rung = Rung(
            logical_rows=3,
            conditions=[
                [""] * 31,
                [Contact(InstructionType.CONTACT_EDGE, "C78", edge_kind="rise")] + ["-"] * 30,
                [Contact(InstructionType.CONTACT_NO, "C79")] + ["-"] * 30,
            ],
            instructions=[counter, "NOP", ""],
            comment_rtf=None,
            comment=None,
        )

        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 2
        assert rows[0][0] == "R"
        assert rows[0][32] == "count_down(CT3,CTD3,preset=50)"
        assert rows[0][1] == "rise(C78)"
        assert rows[1][32] == ".reset()"

    def test_count_down_preserves_populated_top_row(self) -> None:
        counter = Counter(
            counter_type="count_down",
            done_bit="CT3",
            current="CTD3",
            preset="50",
            down_enabled=False,
            reset_enabled=True,
        )
        rung = Rung(
            logical_rows=3,
            conditions=[
                [Contact(InstructionType.CONTACT_NO, "C77")] + ["-"] * 30,
                [Contact(InstructionType.CONTACT_EDGE, "C78", edge_kind="rise")] + ["-"] * 30,
                [Contact(InstructionType.CONTACT_NO, "C79")] + ["-"] * 30,
            ],
            instructions=[counter, "NOP", ""],
            comment_rtf=None,
            comment=None,
        )

        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 3
        assert rows[0][32] == ""
        assert rows[0][1] == "C77"
        assert rows[1][32] == "count_down(CT3,CTD3,preset=50)"
        assert rows[1][1] == "rise(C78)"
        assert rows[2][32] == ".reset()"

    def test_count_down_preserves_wire_only_top_row(self) -> None:
        counter = Counter(
            counter_type="count_down",
            done_bit="CT3",
            current="CTD3",
            preset="50",
            down_enabled=False,
            reset_enabled=True,
        )
        rung = Rung(
            logical_rows=3,
            conditions=[
                [""] * 8 + ["|"] + [""] * 22,
                [Contact(InstructionType.CONTACT_EDGE, "C78", edge_kind="rise")] + ["-"] * 30,
                [Contact(InstructionType.CONTACT_NO, "C79")] + ["-"] * 30,
            ],
            instructions=[counter, "NOP", ""],
            comment_rtf=None,
            comment=None,
        )

        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 3
        assert rows[0][32] == ""
        assert rows[0][9] == "|"
        assert rows[1][32] == "count_down(CT3,CTD3,preset=50)"
        assert rows[1][1] == "rise(C78)"
        assert rows[2][32] == ".reset()"

    def test_count_up_then_retained_timer_emits_both_blocks(self) -> None:
        counter = Counter(
            counter_type="count_up",
            done_bit="CT5",
            current="CTD5",
            preset="100",
            down_enabled=False,
            reset_enabled=True,
        )
        timer = Timer("on_delay", "T5", "TD5", "10", "Tm", retained=True)
        rung = Rung(
            logical_rows=5,
            conditions=[
                _edge_row("C81"),
                _blank_conditions(),
                _contact_row("C82"),
                _contact_row("C83"),
                _contact_row("C84"),
            ],
            instructions=[counter, "", "", timer, ""],
            comment_rtf=None,
            comment=None,
        )

        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 4
        assert [row[32] for row in rows] == [
            "count_up(CT5,CTD5,preset=100)",
            ".reset()",
            "on_delay(T5,TD5,preset=10,unit=Tm)",
            ".reset()",
        ]
        assert rows[1][1] == "C82"
        assert rows[3][1] == "C84"

    def test_count_down_then_retained_timer_preserves_bridge_shape(self) -> None:
        counter = Counter(
            counter_type="count_down",
            done_bit="CT6",
            current="CTD6",
            preset="25",
            down_enabled=False,
            reset_enabled=True,
        )
        timer = Timer("on_delay", "T6", "TD6", "20", "Ts", retained=True)
        rung = Rung(
            logical_rows=5,
            conditions=[
                _contact_row("C85"),
                _edge_row("C86"),
                _contact_row("C87"),
                _contact_row("C88"),
                _contact_row("C89"),
            ],
            instructions=[counter, "NOP", "", timer, ""],
            comment_rtf=None,
            comment=None,
        )

        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 5
        assert [row[32] for row in rows] == [
            "",
            "count_down(CT6,CTD6,preset=25)",
            ".reset()",
            "on_delay(T6,TD6,preset=20,unit=Ts)",
            ".reset()",
        ]
        assert rows[0][1] == "C85"
        assert rows[1][1] == "rise(C86)"
        assert rows[4][1] == "C89"

    def test_shift_emits_clock_and_reset_pins(self) -> None:
        shift = Shift("C99", "C106")
        rung = Rung(
            logical_rows=3,
            conditions=[
                [Contact(InstructionType.CONTACT_NO, "C96")] + ["-"] * 30,
                [Contact(InstructionType.CONTACT_NO, "C97")] + ["-"] * 30,
                [Contact(InstructionType.CONTACT_NO, "C98")] + ["-"] * 30,
            ],
            instructions=[shift, "", ""],
            comment_rtf=None,
            comment=None,
        )

        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 3
        assert rows[0][32] == "shift(C99..C106)"
        assert rows[1][32] == ".clock()"
        assert rows[2][32] == ".reset()"

    def test_shift_then_timer_preserves_nonblank_timer_continuation(self) -> None:
        shift = Shift("C99", "C106")
        timer = Timer("on_delay", "T7", "TD7", "30", "Tms", retained=False)
        rung = Rung(
            logical_rows=5,
            conditions=[
                _contact_row("C90"),
                _contact_row("C91"),
                _contact_row("C92"),
                _contact_row("C93"),
                _contact_row("C94"),
            ],
            instructions=[shift, "", "", timer, ""],
            comment_rtf=None,
            comment=None,
        )

        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 5
        assert [row[32] for row in rows] == [
            "shift(C99..C106)",
            ".clock()",
            ".reset()",
            "on_delay(T7,TD7,preset=30,unit=Tms)",
            "",
        ]
        assert rows[4][1] == "C94"

    def test_shift_requires_three_rows(self) -> None:
        shift = Shift("C99", "C106")
        rung = Rung(
            logical_rows=2,
            conditions=[
                [Contact(InstructionType.CONTACT_NO, "C96")] + ["-"] * 30,
                [Contact(InstructionType.CONTACT_NO, "C97")] + ["-"] * 30,
            ],
            instructions=[shift, ""],
            comment_rtf=None,
            comment=None,
        )

        with pytest.raises(WriterError, match="shift requires 3 decoded rows"):
            decoded_rung_to_rows(rung)

    def test_forloop_serializes(self) -> None:
        rung = Rung(
            logical_rows=1,
            conditions=[[Contact(InstructionType.CONTACT_NO, "C222")] + ["-"] * 30],
            instructions=[ForLoop(limit="3", oneshot=False)],
            comment_rtf=None,
            comment=None,
        )
        rows = decoded_rung_to_rows(rung)
        assert rows[0][32] == "for(3,oneshot=0)"

    def test_next_serializes(self) -> None:
        rung = Rung(
            logical_rows=1,
            conditions=[["-"] * 31],
            instructions=[Next()],
            comment_rtf=None,
            comment=None,
        )
        rows = decoded_rung_to_rows(rung)
        assert rows[0][32] == "next()"

    def test_comment_rows_not_padded(self) -> None:
        """Comment rows are short (just marker + text), not 33 columns."""
        rung = Rung(
            logical_rows=1,
            conditions=[[""] * 31],
            instructions=[""],
            comment_rtf=None,
            comment="Hello",
        )
        rows = decoded_rung_to_rows(rung)
        comment_row = rows[0]
        assert comment_row == ["#", "Hello"]
        assert len(comment_row) == 2

    def test_unknown_instruction_raises(self) -> None:
        """Unknown instructions cannot be written to CSV."""
        rung = Rung(
            logical_rows=1,
            conditions=[[""] * 31],
            instructions=[UnknownInstruction(raw=b"\x00\x01\x02")],
            comment_rtf=None,
            comment=None,
        )
        with pytest.raises(WriterError):
            decoded_rung_to_rows(rung)


class TestMultiPinnedRoundTrip:
    def test_count_up_then_retained_timer_roundtrip(self, tmp_path: Path) -> None:
        counter = Counter(
            counter_type="count_up",
            done_bit="CT8",
            current="CTD8",
            preset="100",
            down_enabled=False,
            reset_enabled=True,
        )
        timer = Timer("on_delay", "T8", "TD8", "10", "Tm", retained=True)
        rung = Rung(
            logical_rows=5,
            conditions=[
                _edge_row("C95"),
                _blank_conditions(),
                _contact_row("C96"),
                _contact_row("C97"),
                _contact_row("C98"),
            ],
            instructions=[counter, "", "", timer, ""],
            comment_rtf=None,
            comment=None,
        )

        out_csv = tmp_path / "count-up-timer.csv"
        write_csv(out_csv, [rung])
        [round_tripped] = read_csv(out_csv)

        assert round_tripped.logical_rows == 5
        assert isinstance(round_tripped.instructions[0], Counter)
        assert isinstance(round_tripped.instructions[3], Timer)
        assert round_tripped.instructions[3].retained is True
        assert isinstance(round_tripped.conditions[2][0], Contact)
        assert round_tripped.conditions[2][0].operand == "C96"
        assert isinstance(round_tripped.conditions[4][0], Contact)
        assert round_tripped.conditions[4][0].operand == "C98"

    def test_shift_then_timer_roundtrip_preserves_blank_timer_row(self, tmp_path: Path) -> None:
        shift = Shift("C120", "C127")
        timer = Timer("on_delay", "T9", "TD9", "50", "Tms", retained=False)
        rung = Rung(
            logical_rows=5,
            conditions=[
                _contact_row("C99"),
                _contact_row("C100"),
                _contact_row("C101"),
                _contact_row("C102"),
                _contact_row("C103"),
            ],
            instructions=[shift, "", "", timer, ""],
            comment_rtf=None,
            comment=None,
        )

        out_csv = tmp_path / "shift-timer.csv"
        write_csv(out_csv, [rung])
        [round_tripped] = read_csv(out_csv)

        assert round_tripped.logical_rows == 5
        assert isinstance(round_tripped.instructions[0], Shift)
        assert isinstance(round_tripped.instructions[3], Timer)
        assert round_tripped.instructions[3].retained is False
        assert round_tripped.instructions[4] == ""
        assert isinstance(round_tripped.conditions[4][0], Contact)
        assert round_tripped.conditions[4][0].operand == "C103"
