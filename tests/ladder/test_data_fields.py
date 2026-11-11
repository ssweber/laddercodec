"""Field rules for Timer, Counter, Shift and Drum (CLICK dialog limits)."""

from __future__ import annotations

import pytest

from laddercodec import AddressError, FieldError
from laddercodec.instructions.counter import Counter
from laddercodec.instructions.drum import Drum
from laddercodec.instructions.shift import Shift
from laddercodec.instructions.timer import Timer


def timer(**kw) -> Timer:
    args = {
        "timer_type": "on_delay",
        "done_bit": "T1",
        "current": "TD1",
        "setpoint": "100",
        "unit": "Tms",
    }
    return Timer(**{**args, **kw})


def counter(**kw) -> Counter:
    args = {"counter_type": "count_up", "done_bit": "CT1", "current": "CTD1", "preset": "10"}
    return Counter(**{**args, **kw})


class TestTimer:
    def test_valid(self) -> None:
        assert timer(done_bit="T500", current="TD500", setpoint="0").setpoint == "0"
        assert timer(setpoint="DS4500").setpoint == "DS4500"

    @pytest.mark.parametrize("done_bit", ["T0", "T501", "C1", "TD1", "X001", "abc"])
    def test_done_bit(self, done_bit: str) -> None:
        with pytest.raises(AddressError, match="Timer.done_bit"):
            timer(done_bit=done_bit)

    @pytest.mark.parametrize("current", ["DS1", "T1", "TD501", "CTD1"])
    def test_current_bank(self, current: str) -> None:
        with pytest.raises(AddressError, match="Timer.current"):
            timer(current=current)

    def test_current_number_matches_done_bit(self) -> None:
        with pytest.raises(FieldError, match="must be TD2"):
            timer(done_bit="T2", current="TD1")

    @pytest.mark.parametrize("setpoint", ["abc", "1.5", "-1", "DD1", "DS0", "TD1", ""])
    def test_setpoint(self, setpoint: str) -> None:
        with pytest.raises(FieldError, match="Timer.setpoint"):
            timer(setpoint=setpoint)

    def test_unit_checked_on_construction(self) -> None:
        with pytest.raises(FieldError, match="Timer.unit"):
            timer(unit="x")

    def test_csv_goes_through_the_rules(self) -> None:
        with pytest.raises(FieldError):
            Timer.from_csv_token("on_delay(T1,TD2,preset=1,unit=Ts)")


class TestCounter:
    def test_valid(self) -> None:
        assert counter(preset="-5").preset == "-5"
        assert counter(preset="DS1").preset == "DS1"
        assert counter(preset="DD1000", done_bit="CT250", current="CTD250")

    @pytest.mark.parametrize("done_bit", ["CT0", "CT251", "C1", "CTD1"])
    def test_done_bit(self, done_bit: str) -> None:
        with pytest.raises(AddressError, match="Counter.done_bit"):
            counter(done_bit=done_bit)

    @pytest.mark.parametrize("current", ["DS1", "CT1", "CTD251", "TD1"])
    def test_current_bank(self, current: str) -> None:
        with pytest.raises(AddressError, match="Counter.current"):
            counter(current=current)

    def test_current_number_matches_done_bit(self) -> None:
        with pytest.raises(FieldError, match="must be CTD2"):
            counter(done_bit="CT2", current="CTD1")

    @pytest.mark.parametrize("preset", ["abc", "1.5", "", "DS0", "Q1", "DS4501"])
    def test_preset(self, preset: str) -> None:
        with pytest.raises(FieldError, match="Counter.preset"):
            counter(preset=preset)


class TestShift:
    def test_start_after_end_allowed(self) -> None:
        assert Shift(start_bit="C106", end_bit="C99").to_csv() == "shift(C106..C99)"


def drum(kind: str = "event", steps: int = 2, outs: int = 2, **kw) -> Drum:
    args: dict = {
        "drum_kind": kind,
        "outputs": [f"C{i + 1}" for i in range(outs)],
        "events_or_presets": [f"C{i + 10}" if kind == "event" else "100" for i in range(steps)],
        "pattern": [[1] * outs for _ in range(steps)],
        "current_step": "DS1",
        "completion_flag": "C50",
    }
    if kind != "event":
        args.update(accumulator="TD1", unit="Tms")
    if kind == "time_event":
        args["events"] = ["C10"] * steps
    return Drum(**{**args, **kw})


class TestDrum:
    @pytest.mark.parametrize("kind", ["event", "time", "time_event"])
    def test_valid_extremes(self, kind: str) -> None:
        assert drum(kind, steps=16, outs=16).num_steps == 16
        assert drum(kind, steps=1, outs=1).num_outputs == 1

    @pytest.mark.parametrize("kind", ["event", "time", "time_event"])
    def test_step_and_output_counts(self, kind: str) -> None:
        with pytest.raises(FieldError, match="steps: 17"):
            drum(kind, steps=17)
        with pytest.raises(FieldError, match="outputs: 17"):
            drum(kind, outs=17)
        with pytest.raises(FieldError, match="steps: 0"):
            drum(kind, steps=0)
        with pytest.raises(FieldError, match="outputs: 0"):
            drum(kind, outs=0)

    def test_pattern_shape_and_cells(self) -> None:
        with pytest.raises(FieldError, match="Drum.pattern"):
            drum(pattern=[[1, 1]])  # one step short
        with pytest.raises(FieldError, match="Drum.pattern"):
            drum(pattern=[[1, 1], [1]])  # short row
        with pytest.raises(FieldError, match="Drum.pattern"):
            drum(pattern=[[1, 1, 1], [1, 1, 1]])  # wide row
        with pytest.raises(FieldError, match="0 or 1"):
            drum(pattern=[[1, 2], [0, 0]])

    def test_operand_banks(self) -> None:
        assert drum(outputs=["Y1", "C2"])
        with pytest.raises(AddressError, match=r"outputs\[1\]"):
            drum(outputs=["C1", "X1"])
        with pytest.raises(AddressError, match="current_step"):
            drum(current_step="DD1")
        with pytest.raises(AddressError, match="completion_flag"):
            drum(completion_flag="Y1")
        for kind in ("time", "time_event"):
            with pytest.raises(AddressError, match="accumulator"):
                drum(kind, accumulator="DS1")
            with pytest.raises(AddressError, match="accumulator"):
                drum(kind, accumulator="")

    def test_jump_target(self) -> None:
        assert drum(jump_enabled=True, jump_target="DS5").jump_target == "DS5"
        with pytest.raises(AddressError, match="jump_target"):
            drum(jump_enabled=True, jump_target="")
        with pytest.raises(AddressError, match="jump_target"):
            drum(jump_enabled=True, jump_target="C1")

    def test_event_drum_needs_every_event(self) -> None:
        with pytest.raises(FieldError, match="OBJ-021"):
            drum(events_or_presets=["C10", ""])

    def test_time_drum_needs_every_duration(self) -> None:
        with pytest.raises(FieldError, match="OBJ-022"):
            drum("time", events_or_presets=["100", ""])

    def test_time_event_step_needs_one_of_two(self) -> None:
        assert drum("time_event", events_or_presets=["100", ""], events=["", "C10"])
        with pytest.raises(FieldError, match="OBJ-1019"):
            drum("time_event", events_or_presets=["100", ""], events=["C10", ""])
        with pytest.raises(FieldError, match="one event per step"):
            drum("time_event", events=["C10"])

    def test_unit(self) -> None:
        with pytest.raises(FieldError, match="Drum.unit"):
            drum("time", unit="x")
