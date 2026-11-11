"""Field rules for Timer, Counter, Shift and Drum (CLICK dialog limits)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from laddercodec import AddressError, FieldError, decode, decode_program, read_csv
from laddercodec.csv import CSV_HEADER
from laddercodec.encode import encode_rung
from laddercodec.instructions.counter import Counter
from laddercodec.instructions.drum import Drum
from laddercodec.instructions.raw import RawInstruction
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


class TestDrumPatternCells:
    @pytest.mark.parametrize("cell", [1.0, 0.0, "1", None, True])
    def test_non_int_cell_is_a_field_error(self, cell: object) -> None:
        with pytest.raises(FieldError, match="Drum.pattern"):
            drum(steps=1, outs=1, pattern=[[cell]])


# A native-shaped blob the rules refuse decodes as raw(...).  The bytes come from
# a valid instruction, edited past the checks.

_SCR_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scr_captures"


def _utf16(text: str) -> bytes:
    return text.encode("utf-16-le")


def _scr_text(text: str) -> bytes:
    # The SCR fixtures store strings as a length byte, the text and one NUL byte.
    return bytes([len(text) * 2 + 1]) + _utf16(text) + b"\x00"


def _clipboard_raw(af: Timer | Counter | Drum, old: str, new: str) -> RawInstruction:
    data = encode_rung(1, [["-"] * 31], [af])
    assert data.count(_utf16(old)) == 1
    [decoded] = decode(data.replace(_utf16(old), _utf16(new))).instructions
    assert isinstance(decoded, RawInstruction)
    return decoded


def _scr_raw_names(old: str, new: str, name: str = "coverage") -> list[str]:
    data = (_SCR_DIR / f"{name}.scr").read_bytes()
    assert data.count(_scr_text(old)) >= 1
    rungs = decode_program(data.replace(_scr_text(old), _scr_text(new))).rungs
    return [a.class_name for r in rungs for a in r.instructions if isinstance(a, RawInstruction)]


class TestRefusedBlobsDecodeAsRaw:
    def test_timer_with_mismatched_current(self) -> None:
        raw = _clipboard_raw(timer(), "TD1", "TD2")
        assert raw.class_name == "Tmr"

    def test_timer_scr_with_non_numeric_setpoint(self) -> None:
        assert _scr_raw_names("3000", "abcd") == ["Tmr"]

    def test_counter_scr_with_mismatched_current(self) -> None:
        assert set(_scr_raw_names("CTD1", "CTD2", "counter_scr")) == {"Cnt"}

    def test_counter_with_non_numeric_preset(self) -> None:
        raw = _clipboard_raw(counter(preset="100", reset_enabled=True), "100", "abc")
        assert raw.class_name == "Cnt"

    def test_drum_scr_with_refused_current_step(self) -> None:
        assert _scr_raw_names("DS182", "DS000") == ["Drum"]

    def test_drum_with_17_steps(self) -> None:
        d = drum(steps=16, outs=2)
        object.__setattr__(d, "events_or_presets", d.events_or_presets + ["C99"])
        object.__setattr__(d, "pattern", d.pattern + [[1, 1]])
        assert d.num_steps == 17
        data = encode_rung(1, [["-"] * 31], [d])
        [decoded] = decode(data).instructions
        assert isinstance(decoded, RawInstruction)
        assert decoded.class_name == "Drum"


# ---------------------------------------------------------------------------
# Rules from CLICK v4.00's dialog code (jobs/dllqa/data.md, Q-D1..Q-D5: the
# Inst_*.dll OnOK checks and their OBJ ids) and the user's dialog checks of
# 2026-11-11 (address normalization).
# ---------------------------------------------------------------------------


def _read_af(tmp_path: Path, af: str) -> object:
    """Read one rung holding ``af``; a counter or drum gets its required ``.reset()`` row."""
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", "X001"] + ["-"] * 30 + [af])
        if af.startswith(("count_", "event_drum", "time_drum", "time_event_drum")):
            w.writerow(["", "X002"] + ["-"] * 30 + [".reset()"])
    return read_csv(path)[0].instructions[0]


def _raw_after(model: object, **bad: object) -> RawInstruction:
    """Encode ``model`` with ``bad`` fields set past the checks; decode it back."""
    for name, value in bad.items():
        object.__setattr__(model, name, value)
    [decoded] = decode(encode_rung(1, [["-"] * 31], [model])).instructions
    assert isinstance(decoded, RawInstruction)
    return decoded


class TestTimerSetpointRange:
    # Q-D1: 0..32767 for every unit; 32768 and any sign refused (OBJ-005).
    @pytest.mark.parametrize("unit", ["Tms", "Ts", "Tm", "Th", "Td"])
    def test_limits_for_every_unit(self, tmp_path: Path, unit: str) -> None:
        for value in ("0", "32767"):
            token = f"on_delay(T1,TD1,preset={value},unit={unit})"
            assert _read_af(tmp_path, token) == timer(setpoint=value, unit=unit)
        with pytest.raises(FieldError, match=r"^Timer.setpoint: '32768' is above 32767"):
            _read_af(tmp_path, f"on_delay(T1,TD1,preset=32768,unit={unit})")
        with pytest.raises(FieldError, match=r"^Timer.setpoint: '32768' is above 32767"):
            timer(setpoint="32768", unit=unit)

    @pytest.mark.parametrize("setpoint", ["-1", "+5", "1 0"])
    def test_sign_refused(self, tmp_path: Path, setpoint: str) -> None:
        with pytest.raises(FieldError, match="^Timer.setpoint"):
            _read_af(tmp_path, f"off_delay(T1,TD1,preset={setpoint},unit=Ts)")

    def test_refused_setpoint_decodes_as_raw(self) -> None:
        assert _raw_after(timer(), setpoint="40000").class_name == "Tmr"


class TestCounterPresetRange:
    # Q-D2: a 32-bit signed constant (OBJ-005); registers DS and DD only (OBJ-004).
    @pytest.mark.parametrize("preset", ["2147483647", "-2147483648", "0", "DS1", "DD1"])
    def test_accepted(self, tmp_path: Path, preset: str) -> None:
        parsed = _read_af(tmp_path, f"count_up(CT1,CTD1,preset={preset})")
        assert parsed == counter(preset=preset, reset_enabled=True)

    @pytest.mark.parametrize("preset", ["2147483648", "-2147483649", "99999999999"])
    def test_out_of_range(self, tmp_path: Path, preset: str) -> None:
        with pytest.raises(FieldError, match=rf"^Counter.preset: '{preset}' is outside"):
            _read_af(tmp_path, f"count_down(CT1,CTD1,preset={preset})")
        with pytest.raises(FieldError, match=rf"^Counter.preset: '{preset}' is outside"):
            counter(preset=preset)

    @pytest.mark.parametrize("preset", ["1.5", "abc", "1-2", "--5"])
    def test_not_an_integer(self, tmp_path: Path, preset: str) -> None:
        with pytest.raises(FieldError, match="^Counter.preset"):
            _read_af(tmp_path, f"count_up(CT1,CTD1,preset={preset})")

    def test_text_under_13_characters(self) -> None:
        # Inst_Counter.dll: a constant's text is under 13 characters (OBJ-005).
        assert counter(preset="000000000001").preset == "000000000001"
        with pytest.raises(FieldError, match="13 characters; a constant set point is at most 12"):
            counter(preset="0000000000001")

    @pytest.mark.parametrize("preset", ["DH1", "DF1", "TD1", "CTD1", "SD1", "XD1"])
    def test_other_registers_refused(self, tmp_path: Path, preset: str) -> None:
        message = rf"^Counter.preset: '{preset}' is not allowed; Counter.preset takes DS, DD$"
        with pytest.raises(AddressError, match=message):
            _read_af(tmp_path, f"count_up(CT1,CTD1,preset={preset})")
        with pytest.raises(AddressError, match=message):
            counter(preset=preset)

    @pytest.mark.parametrize("preset", ["DH1", "2147483648", "0000000000001"])
    def test_refused_presets_decode_as_raw(self, preset: str) -> None:
        assert _raw_after(counter(reset_enabled=True), preset=preset).class_name == "Cnt"


class TestShiftRules:
    # Q-D3: C only (OBJ-004); start == end refused (OBJ-012); start > end allowed.
    def test_c_range(self, tmp_path: Path) -> None:
        assert _read_af(tmp_path, "shift(C1..C2000)") == Shift(start_bit="C1", end_bit="C2000")
        assert _read_af(tmp_path, "shift(C106..C99)") == Shift(start_bit="C106", end_bit="C99")

    @pytest.mark.parametrize(
        ("token", "field"),
        [
            ("shift(Y1..Y8)", "start_bit"),
            ("shift(T1..T8)", "start_bit"),
            ("shift(SC1..SC8)", "start_bit"),
            ("shift(X001..X008)", "start_bit"),
            ("shift(C1..X008)", "end_bit"),
            ("shift(C1..Y8)", "end_bit"),
        ],
    )
    def test_other_banks_refused(self, tmp_path: Path, token: str, field: str) -> None:
        with pytest.raises(AddressError, match=rf"^Shift.{field}: .* takes C$"):
            _read_af(tmp_path, token)

    @pytest.mark.parametrize("end", ["C1", "C001"])
    def test_same_address_refused(self, tmp_path: Path, end: str) -> None:
        # CLICK normalizes C001 to C1 as it is typed (user dialog check 2026-11-11).
        with pytest.raises(FieldError, match=rf"^Shift.end_bit: '{end}' is the same address"):
            _read_af(tmp_path, f"shift(C1..{end})")
        with pytest.raises(FieldError, match="OBJ-012"):
            Shift(start_bit="C1", end_bit=end)

    @pytest.mark.parametrize("bad", [{"end_bit": "C1"}, {"start_bit": "Y1", "end_bit": "Y2"}])
    def test_refused_blobs_decode_as_raw(self, bad: dict[str, str]) -> None:
        assert _raw_after(Shift(start_bit="C1", end_bit="C2"), **bad).class_name == "SR"

    def test_scr_same_address_decodes_as_raw(self) -> None:
        # shift_scr: two shift(C1..C2) rungs; C2 occurs only as their end bits.
        data = (_SCR_DIR / "shift_scr.scr").read_bytes()
        assert data.count(_scr_text("C2")) == 2
        rungs = decode_program(data.replace(_scr_text("C2"), _scr_text("C1"))).rungs
        assert [type(r.instructions[0]) for r in rungs] == [RawInstruction, RawInstruction]


class TestDrumDurations:
    # Q-D4: 0..32767 for every unit, digits only (OBJ-005); a register is DS (OBJ-004).
    @pytest.mark.parametrize("kind", ["time", "time_event"])
    @pytest.mark.parametrize("unit", ["Tms", "Ts", "Tm", "Th", "Td"])
    def test_limits(self, kind: str, unit: str) -> None:
        assert drum(kind, events_or_presets=["0", "32767"], unit=unit)
        assert drum(kind, events_or_presets=["DS1", "5"], unit=unit)
        with pytest.raises(FieldError, match=r"^Drum.presets\[1\]: '32768' is above 32767"):
            drum(kind, events_or_presets=["1", "32768"], unit=unit)

    @pytest.mark.parametrize("preset", ["-1", "+5", "1.5"])
    def test_sign_or_fraction_refused(self, preset: str) -> None:
        with pytest.raises(FieldError, match=r"^Drum.presets\[0\].*OBJ-005"):
            drum("time", events_or_presets=[preset, "1"])

    @pytest.mark.parametrize("preset", ["DD1", "TD1", "DH1"])
    def test_other_registers_refused(self, preset: str) -> None:
        with pytest.raises(AddressError, match=r"^Drum.presets\[0\]: .* takes DS$"):
            drum("time", events_or_presets=[preset, "1"])

    def test_csv(self, tmp_path: Path) -> None:
        token = (
            "time_drum(outputs=[C1,C2],presets=[32768,1],unit=Ts,pattern=[[1,0],[0,1]],"
            "current_step=DS1,accumulator=TD1,completion_flag=C9)"
        )
        with pytest.raises(FieldError, match=r"^Drum.presets\[0\]: '32768'"):
            _read_af(tmp_path, token)
        assert isinstance(_read_af(tmp_path, token.replace("32768", "32767")), Drum)

    def test_refused_duration_decodes_as_raw(self) -> None:
        raw = _raw_after(drum("time"), events_or_presets=["40000", "1"])
        assert raw.class_name == "Drum"


class TestDrumEventsAndOutputs:
    # Q-D5: events X, Y, C, T, CT or SC (OBJ-004); outputs differ from each other and
    # from the completion flag (OBJ-014), compared as addresses.
    @pytest.mark.parametrize("event", ["X001", "Y1", "C5", "T1", "CT1", "SC1"])
    def test_event_banks_accepted(self, event: str) -> None:
        assert drum(events_or_presets=[event, "C10"]).events_or_presets[0] == event
        assert drum("time_event", events=[event, ""]).events[0] == event

    @pytest.mark.parametrize("event", ["DS1", "TD1", "XD0", "TXT1"])
    def test_other_event_banks_refused(self, event: str) -> None:
        message = r"^Drum.events\[0\]: .* takes X, Y, C, T, CT, SC$"
        with pytest.raises(AddressError, match=message):
            drum(events_or_presets=[event, "C10"])
        with pytest.raises(AddressError, match=message):
            drum("time_event", events=[event, ""])

    @pytest.mark.parametrize("second", ["C1", "C001"])
    def test_output_twice_refused(self, tmp_path: Path, second: str) -> None:
        # CLICK normalizes C001 to C1 as it is typed (user dialog check 2026-11-11).
        token = (
            f"event_drum(outputs=[C1,{second}],events=[X001,X002],pattern=[[1,0],[0,1]],"
            "current_step=DS1,completion_flag=C9)"
        )
        message = rf"^Drum.outputs\[1\]: '{second}' is already output 0"
        with pytest.raises(FieldError, match=message):
            _read_af(tmp_path, token)

    def test_y_output_twice_refused(self) -> None:
        # CLICK writes Y1 as Y001 (user dialog check 2026-11-11): the same output.
        with pytest.raises(FieldError, match="OBJ-014"):
            drum(outputs=["Y001", "Y1"])

    @pytest.mark.parametrize("kind", ["event", "time", "time_event"])
    def test_output_is_completion_flag(self, kind: str) -> None:
        message = r"^Drum.outputs\[1\]: 'C050' is the completion flag"
        with pytest.raises(FieldError, match=message):
            drum(kind, outputs=["C1", "C050"], completion_flag="C50")

    @pytest.mark.parametrize(
        "bad",
        [
            {"outputs": ["C1", "C1"]},
            {"outputs": ["C1", "C50"]},
            {"events_or_presets": ["DS1", "C10"]},
        ],
    )
    def test_refused_blobs_decode_as_raw(self, bad: dict[str, list[str]]) -> None:
        assert _raw_after(drum(), **bad).class_name == "Drum"

    @pytest.mark.parametrize(("old", "new"), [("C184", "C183"), ("C184", "C187"), ("C185", "DS18")])
    def test_scr_refused_blobs_decode_as_raw(self, old: str, new: str) -> None:
        # coverage: event_drum(outputs=[C183,C184],events=[C185,C186],...,completion_flag=C187).
        assert _scr_raw_names(old, new) == ["Drum"]
