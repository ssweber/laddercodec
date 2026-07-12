"""Tests for laddercodec.csv.writer — Rung → CSV round-trip."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from laddercodec import (
    Coil,
    CompareContact,
    Contact,
    Counter,
    Drum,
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
    _validate_roundtrip,
    decoded_rung_to_rows,
)
from laddercodec.instructions import (
    Copy,
    ModbusRtuTarget,
    RawInstruction,
    Receive,
    Search,
    Send,
    UnknownInstruction,
)
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


def _generic_tall_af_cases() -> list[pytest.ParameterSet]:
    """Return representative non-pinned tall AF instructions."""
    return [
        pytest.param(Copy("DS7", "DS8"), 2, id="copy"),
        pytest.param(Search("DS72", "DS81", "DS71", "DS82", "C81", "=="), 2, id="search"),
        pytest.param(
            Send(
                ModbusRtuTarget("rtu", "cpu2", 5),
                "DS1",
                "DS1",
                1,
                "C1",
                "C2",
                "C3",
                "DS100",
            ),
            3,
            id="send",
        ),
        pytest.param(
            Receive(
                ModbusRtuTarget("rtu", "cpu2", 5),
                "DS1",
                "DS1",
                1,
                "C1",
                "C2",
                "C3",
                "DS100",
            ),
            3,
            id="receive",
        ),
        pytest.param(
            RawInstruction.from_csv_token("raw(X,0x2711,3,0000=)"),
            3,
            id="raw",
        ),
    ]


def _search_continuation_row() -> list[object]:
    """Return a nonblank continuation row with comparison and wire geometry."""
    return [CompareContact("==", "DS300", "1", wire_down=True), "T", "|"] + [""] * 28


def _event_drum() -> Drum:
    """Return a compact event drum that exercises reset/jump/jog pin rows."""
    return Drum(
        drum_kind="event",
        outputs=["Y10", "Y11"],
        events_or_presets=["C10", "C11"],
        pattern=[[1, 0], [0, 1]],
        current_step="DS10",
        completion_flag="C12",
        jog_enabled=True,
        jump_enabled=True,
        jump_target="DS11",
    )


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


class TestGenericTallRoundTrip:
    @pytest.mark.parametrize(("af", "visual_rows"), _generic_tall_af_cases())
    def test_later_tall_block_at_end_roundtrips(
        self,
        tmp_path: Path,
        af: object,
        visual_rows: int,
    ) -> None:
        lead = Coil(InstructionType.COIL_OUT, "Y900")
        rung = Rung(
            logical_rows=visual_rows + 1,
            conditions=[
                _contact_row("C200"),
                _contact_row("C201"),
                *[_blank_conditions() for _ in range(visual_rows - 1)],
            ],
            instructions=[lead, af, *([""] * (visual_rows - 1))],
            comment_rtf=None,
            comment=None,
        )

        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 2
        assert [row[32] for row in rows] == ["out(Y900)", af.to_csv()]

        out_csv = tmp_path / f"later-tall-end-{type(af).__name__}.csv"
        write_csv(out_csv, [rung])
        [round_tripped] = read_csv(out_csv)

        assert round_tripped.logical_rows == rung.logical_rows
        assert round_tripped.conditions == rung.conditions
        assert round_tripped.instructions == rung.instructions

    @pytest.mark.parametrize(("af", "visual_rows"), _generic_tall_af_cases())
    def test_later_tall_block_before_following_af_roundtrips(
        self,
        tmp_path: Path,
        af: object,
        visual_rows: int,
    ) -> None:
        lead = Coil(InstructionType.COIL_OUT, "Y901")
        tail = Coil(InstructionType.COIL_OUT, "Y902")
        rung = Rung(
            logical_rows=visual_rows + 2,
            conditions=[
                _contact_row("C210"),
                _contact_row("C211"),
                *[_blank_conditions() for _ in range(visual_rows - 1)],
                _contact_row("C212"),
            ],
            instructions=[lead, af, *([""] * (visual_rows - 1)), tail],
            comment_rtf=None,
            comment=None,
        )

        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 3
        assert [row[32] for row in rows] == ["out(Y901)", af.to_csv(), "out(Y902)"]

        out_csv = tmp_path / f"later-tall-mid-{type(af).__name__}.csv"
        write_csv(out_csv, [rung])
        [round_tripped] = read_csv(out_csv)

        assert round_tripped.logical_rows == rung.logical_rows
        assert round_tripped.conditions == rung.conditions
        assert round_tripped.instructions == rung.instructions


class TestDehydrateHydrateWires:
    def test_T_wire_pipe_dehydrate_hydrate_roundtrip(self, tmp_path: Path) -> None:
        """Padding row with | under T is stripped by writer, restored by converter."""
        search = Search("DS72", "DS81", "DS71", "DS82", "C81", "==")
        rung = Rung(
            logical_rows=3,
            conditions=[
                [Contact(InstructionType.CONTACT_NO, "C10"), "T"] + ["-"] * 29,
                ["", "|"] + [""] * 29,
                [Contact(InstructionType.CONTACT_NO, "C11")] + ["-"] * 30,
            ],
            instructions=[search, "", Coil(InstructionType.COIL_OUT, "Y001")],
            comment_rtf=None,
            comment=None,
        )

        # Writer dehydrates: padding row (only blank + |) is stripped
        rows = decoded_rung_to_rows(rung)
        assert len(rows) == 2
        assert rows[0][2] == "T"  # T preserved in col B

        # Full round-trip: hydration restores | under T
        out = tmp_path / "t-wire.csv"
        write_csv(out, [rung])
        [rt] = read_csv(out)

        assert rt.logical_rows == 3
        assert rt.conditions[0][1] == "T"
        assert rt.conditions[1][1] == "|"  # hydrated back

    def test_multi_column_T_wires_roundtrip(self, tmp_path: Path) -> None:
        """Multiple T wires in different non-A columns all hydrate correctly."""
        search = Search("DS72", "DS81", "DS71", "DS82", "C81", "==")
        conds_row0 = [Contact(InstructionType.CONTACT_NO, "C20")] + ["-"] * 30
        conds_row0[5] = "T"  # col F
        conds_row0[15] = "T"  # col P
        rung = Rung(
            logical_rows=3,
            conditions=[
                conds_row0,
                ["", "", "", "", "", "|"] + [""] * 9 + ["|"] + [""] * 15,
                [Contact(InstructionType.CONTACT_NO, "C21")] + ["-"] * 30,
            ],
            instructions=[search, "", Coil(InstructionType.COIL_OUT, "Y002")],
            comment_rtf=None,
            comment=None,
        )

        out = tmp_path / "multi-t-wire.csv"
        write_csv(out, [rung])
        [rt] = read_csv(out)

        assert rt.logical_rows == 3
        assert rt.conditions[0][5] == "T"
        assert rt.conditions[0][15] == "T"
        assert rt.conditions[1][5] == "|"  # hydrated
        assert rt.conditions[1][15] == "|"  # hydrated


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


class TestRoundTripValidator:
    def test_accepts_retained_timer(self) -> None:
        rung = Rung(
            logical_rows=2,
            conditions=[
                _contact_row("C300"),
                _contact_row("C301"),
            ],
            instructions=[Timer("on_delay", "T30", "TD30", "10", "Tm", retained=True), ""],
            comment_rtf=None,
            comment=None,
        )

        _validate_roundtrip(rung, decoded_rung_to_rows(rung))

    def test_accepts_count_down_bridge_shape(self) -> None:
        rung = Rung(
            logical_rows=3,
            conditions=[
                _contact_row("C302"),
                _edge_row("C303"),
                _contact_row("C304"),
            ],
            instructions=[
                Counter(
                    counter_type="count_down",
                    done_bit="CT30",
                    current="CTD30",
                    preset="50",
                    down_enabled=False,
                    reset_enabled=True,
                ),
                "NOP",
                "",
            ],
            comment_rtf=None,
            comment=None,
        )

        _validate_roundtrip(rung, decoded_rung_to_rows(rung))

    def test_accepts_generic_tall_continuation_with_comparison_and_t(self) -> None:
        rung = Rung(
            logical_rows=2,
            conditions=[
                _contact_row("C305"),
                _search_continuation_row(),
            ],
            instructions=[Search("DS72", "DS81", "DS71", "DS82", "C81", "=="), ""],
            comment_rtf=None,
            comment=None,
        )

        _validate_roundtrip(rung, decoded_rung_to_rows(rung))

    def test_accepts_drum_pin_rows(self) -> None:
        rung = Rung(
            logical_rows=4,
            conditions=[
                _contact_row("C306"),
                _contact_row("C307"),
                _contact_row("C308"),
                _contact_row("C309"),
            ],
            instructions=[_event_drum(), "", "", ""],
            comment_rtf=None,
            comment=None,
        )

        _validate_roundtrip(rung, decoded_rung_to_rows(rung))

    def test_raises_on_missing_retained_timer_reset_pin(self) -> None:
        rung = Rung(
            logical_rows=2,
            conditions=[
                _contact_row("C310"),
                _contact_row("C311"),
            ],
            instructions=[Timer("on_delay", "T31", "TD31", "20", "Tm", retained=True), ""],
            comment_rtf=None,
            comment=None,
        )

        rows = decoded_rung_to_rows(rung)
        rows[1][32] = ""

        with pytest.raises(WriterError, match=r"AF mismatch at row 1"):
            _validate_roundtrip(rung, rows)

    def test_raises_on_missing_count_down_top_row_contact(self) -> None:
        rung = Rung(
            logical_rows=3,
            conditions=[
                _contact_row("C312"),
                _edge_row("C313"),
                _contact_row("C314"),
            ],
            instructions=[
                Counter(
                    counter_type="count_down",
                    done_bit="CT31",
                    current="CTD31",
                    preset="75",
                    down_enabled=False,
                    reset_enabled=True,
                ),
                "NOP",
                "",
            ],
            comment_rtf=None,
            comment=None,
        )

        rows = decoded_rung_to_rows(rung)
        rows[0][1] = ""

        with pytest.raises(WriterError, match=r"condition mismatch at row 1 col A"):
            _validate_roundtrip(rung, rows)

    def test_raises_on_missing_generic_tall_continuation_comparison(self) -> None:
        rung = Rung(
            logical_rows=2,
            conditions=[
                _contact_row("C315"),
                _search_continuation_row(),
            ],
            instructions=[Search("DS90", "DS99", "DS89", "DS100", "C316", "=="), ""],
            comment_rtf=None,
            comment=None,
        )

        rows = decoded_rung_to_rows(rung)
        rows[1][1] = ""

        with pytest.raises(WriterError, match=r"condition mismatch at row 2 col A"):
            _validate_roundtrip(rung, rows)

    def test_raises_on_missing_drum_jump_pin(self) -> None:
        rung = Rung(
            logical_rows=4,
            conditions=[
                _contact_row("C317"),
                _contact_row("C318"),
                _contact_row("C319"),
                _contact_row("C320"),
            ],
            instructions=[_event_drum(), "", "", ""],
            comment_rtf=None,
            comment=None,
        )

        rows = decoded_rung_to_rows(rung)
        rows[2][32] = ""

        with pytest.raises(WriterError, match=r"AF mismatch at row 1"):
            _validate_roundtrip(rung, rows)


# ---------------------------------------------------------------------------
# Indexed rung markers (write_csv index=True)
# ---------------------------------------------------------------------------


def _markers(path: Path) -> list[str]:
    """Return the marker column of every data/comment row in a written CSV."""
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        return [row[0] for row in reader if row]


def _simple_rung(operand: str, coil: str) -> Rung:
    """A single-row NO-contact → coil rung."""
    return Rung(
        logical_rows=1,
        conditions=[[Contact(InstructionType.CONTACT_NO, operand)] + ["-"] * 30],
        instructions=[Coil(InstructionType.COIL_OUT, coil)],
        comment_rtf=None,
        comment=None,
    )


class TestIndexedMarkers:
    def test_index_true_emits_sequential_rung_markers(self, tmp_path: Path) -> None:
        rungs = [
            _simple_rung("X001", "Y001"),
            _simple_rung("X002", "Y002"),
            _simple_rung("X003", "Y003"),
        ]
        out = tmp_path / "indexed.csv"
        write_csv(out, rungs, index=True)
        assert _markers(out) == ["R1", "R2", "R3"]

    def test_index_false_default_emits_plain_R(self, tmp_path: Path) -> None:
        rungs = [_simple_rung("X001", "Y001"), _simple_rung("X002", "Y002")]
        default_out = tmp_path / "default.csv"
        explicit_out = tmp_path / "explicit.csv"
        write_csv(default_out, rungs)
        write_csv(explicit_out, rungs, index=False)

        assert _markers(default_out) == ["R", "R"]
        assert default_out.read_bytes() == explicit_out.read_bytes()

    def test_index_true_indexes_only_first_row_of_multirow_rung(self, tmp_path: Path) -> None:
        timer = Timer("on_delay", "T3", "TD3", "10", "Tm", retained=True)
        multirow = Rung(
            logical_rows=2,
            conditions=[
                [Contact(InstructionType.CONTACT_NO, "X001")] + ["-"] * 30,
                ["-"] * 31,
            ],
            instructions=[timer, ""],
            comment_rtf=None,
            comment=None,
        )
        out = tmp_path / "multirow.csv"
        write_csv(out, [multirow, _simple_rung("X002", "Y002")], index=True)
        # First rung: data row R1, retained .reset() continuation stays blank.
        # Second rung: R2.
        assert _markers(out) == ["R1", "", "R2"]

    def test_index_true_leaves_comment_rows_untouched(self, tmp_path: Path) -> None:
        commented = Rung(
            logical_rows=1,
            conditions=[[Contact(InstructionType.CONTACT_NO, "X001")] + ["-"] * 30],
            instructions=[Coil(InstructionType.COIL_OUT, "Y001")],
            comment_rtf=None,
            comment="Line 1\nLine 2",
        )
        out = tmp_path / "comment.csv"
        write_csv(out, [commented], index=True)
        assert _markers(out) == ["#", "#", "R1"]

    def test_index_true_roundtrips_via_read_csv(self, tmp_path: Path) -> None:
        rungs = [
            _simple_rung("X001", "Y001"),
            _simple_rung("X002", "Y002"),
            _simple_rung("X003", "Y003"),
        ]
        indexed = tmp_path / "indexed.csv"
        plain = tmp_path / "plain.csv"
        write_csv(indexed, rungs, index=True)
        write_csv(plain, rungs, index=False)

        from_indexed = read_csv(indexed)
        from_plain = read_csv(plain)

        assert len(from_indexed) == len(from_plain) == 3
        for rt_indexed, rt_plain in zip(from_indexed, from_plain, strict=True):
            assert rt_indexed.logical_rows == rt_plain.logical_rows
            assert rt_indexed.conditions == rt_plain.conditions
            assert rt_indexed.instructions == rt_plain.instructions
            assert rt_indexed.comment == rt_plain.comment
