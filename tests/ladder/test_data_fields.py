"""Field rules for Timer, Counter, Shift and Drum (CLICK dialog limits)."""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from laddercodec import (
    AddressError,
    FieldError,
    RefusedFieldWarning,
    decode,
    decode_program,
    read_csv,
)
from laddercodec.csv import CSV_HEADER
from laddercodec.encode import encode_rung
from laddercodec.instructions.counter import Counter
from laddercodec.instructions.drum import Drum
from laddercodec.instructions.raw import RawInstruction
from laddercodec.instructions.shift import Shift
from laddercodec.instructions.timer import Timer
from laddercodec.operands.unchecked import refusals
from tests.kept_refusals import kept


def timer(**kw) -> Timer:
    args = {
        "kind": "on_delay",
        "done": "T1",
        "accumulator": "TD1",
        "preset": "100",
        "unit": "Tms",
    }
    return Timer(**{**args, **kw})


def counter(**kw) -> Counter:
    args = {"kind": "count_up", "done": "CT1", "accumulator": "CTD1", "preset": "10"}
    return Counter(**{**args, **kw})


class TestTimer:
    def test_valid(self) -> None:
        assert timer(done="T500", accumulator="TD500", preset="0").preset == "0"
        assert timer(preset="DS4500").preset == "DS4500"

    @pytest.mark.parametrize("done", ["T0", "T501", "C1", "TD1", "X001", "abc"])
    def test_done(self, done: str) -> None:
        with pytest.raises(AddressError, match="Timer.done"):
            timer(done=done)

    @pytest.mark.parametrize("accumulator", ["DS1", "T1", "TD501", "CTD1"])
    def test_accumulator_bank(self, accumulator: str) -> None:
        with pytest.raises(AddressError, match="Timer.accumulator"):
            timer(accumulator=accumulator)

    def test_accumulator_number_matches_done(self) -> None:
        with pytest.raises(FieldError, match="must be TD2"):
            timer(done="T2", accumulator="TD1")

    @pytest.mark.parametrize("preset", ["abc", "1.5", "-1", "DD1", "DS0", "TD1", ""])
    def test_preset(self, preset: str) -> None:
        with pytest.raises(FieldError, match="Timer.preset"):
            timer(preset=preset)

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
        assert counter(preset="DD1000", done="CT250", accumulator="CTD250")

    @pytest.mark.parametrize("done", ["CT0", "CT251", "C1", "CTD1"])
    def test_done(self, done: str) -> None:
        with pytest.raises(AddressError, match="Counter.done"):
            counter(done=done)

    @pytest.mark.parametrize("accumulator", ["DS1", "CT1", "CTD251", "TD1"])
    def test_accumulator_bank(self, accumulator: str) -> None:
        with pytest.raises(AddressError, match="Counter.accumulator"):
            counter(accumulator=accumulator)

    def test_accumulator_number_matches_done(self) -> None:
        with pytest.raises(FieldError, match="must be CTD2"):
            counter(done="CT2", accumulator="CTD1")

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
        with pytest.raises(FieldError, match="17 steps"):
            drum(kind, steps=17)
        with pytest.raises(FieldError, match="17 outputs"):
            drum(kind, outs=17)
        with pytest.raises(FieldError, match="0 steps"):
            drum(kind, steps=0)
        with pytest.raises(FieldError, match="0 outputs"):
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


# A native-shaped blob the rules refuse decodes as that instruction, keeping the
# refusal; one not in display form, or the parser can't read, decodes as raw(...).  The
# bytes come from a valid instruction, edited past the checks.

_SCR_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scr_captures"


def _utf16(text: str) -> bytes:
    return text.encode("utf-16-le")


def _scr_text(text: str) -> bytes:
    # The SCR fixtures store strings as a length byte, the text and one NUL byte.
    return bytes([len(text) * 2 + 1]) + _utf16(text) + b"\x00"


def _clipboard_decoded(af: Timer | Counter | Drum, old: str, new: str) -> object:
    data = encode_rung(1, [["-"] * 31], [af])
    assert data.count(_utf16(old)) == 1
    with pytest.warns(RefusedFieldWarning):
        [decoded] = decode(data.replace(_utf16(old), _utf16(new)))[0].instructions
    return decoded


def _scr_raw_names(old: str, new: str, name: str = "coverage") -> list[str]:
    data = (_SCR_DIR / f"{name}.scr").read_bytes()
    assert data.count(_scr_text(old)) >= 1
    rungs = decode_program(data.replace(_scr_text(old), _scr_text(new))).rungs
    return [a.class_name for r in rungs for a in r.instructions if isinstance(a, RawInstruction)]


def _scr_refused(old: str, new: str, name: str = "coverage") -> list[tuple[str, list[str]]]:
    """Each instruction of the edited SCR program that keeps refusals: class and fields."""
    data = (_SCR_DIR / f"{name}.scr").read_bytes()
    assert data.count(_scr_text(old)) >= 1
    with pytest.warns(RefusedFieldWarning):
        rungs = decode_program(data.replace(_scr_text(old), _scr_text(new))).rungs
    return [
        (type(a).__name__, [error.field for error in refusals(a)])
        for r in rungs
        for a in r.instructions
        if refusals(a)
    ]


class TestRefusedBlobsDecode:
    def test_timer_with_mismatched_accumulator(self) -> None:
        decoded = kept(_clipboard_decoded(timer(), "TD1", "TD2"), "Timer.accumulator")
        assert isinstance(decoded, Timer) and decoded.accumulator == "TD2"

    def test_timer_scr_with_non_numeric_preset(self) -> None:
        assert _scr_refused("3000", "abcd") == [("Timer", ["Timer.preset"])]

    def test_counter_scr_with_mismatched_accumulator(self) -> None:
        refused = _scr_refused("CTD1", "CTD2", "counter_scr")
        assert refused and set(map(str, refused)) == {str(("Counter", ["Counter.accumulator"]))}

    def test_counter_with_non_numeric_preset(self) -> None:
        af = counter(preset="100", reset_enabled=True)
        decoded = kept(_clipboard_decoded(af, "100", "abc"), "Counter.preset")
        assert isinstance(decoded, Counter) and decoded.preset == "abc"

    def test_drum_scr_with_refused_current_step(self) -> None:
        assert _scr_raw_names("DS182", "DS000") == ["Drum"]

    def test_drum_with_17_steps(self) -> None:
        d = drum(steps=16, outs=2)
        object.__setattr__(d, "events_or_presets", d.events_or_presets + ["C99"])
        object.__setattr__(d, "pattern", d.pattern + [[1, 1]])
        assert d.num_steps == 17
        data = encode_rung(1, [["-"] * 31], [d])
        [decoded] = decode(data)[0].instructions
        assert isinstance(decoded, RawInstruction)
        assert decoded.class_name == "Drum"


# ---------------------------------------------------------------------------
# Rules from CLICK v4.00's instruction dialogs, with their OBJ ids, and address normalization.
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


#: The location ``read_csv`` ends a message about ``_read_af``'s AF cell with.
_AT_AF = r" \(at .*rung\.csv, line 2, rung at line 2, row 0 from 0, column AF\)$"


def _decoded_after(model: object, *fields: str, **bad: object) -> object:
    """Encode ``model`` with ``bad`` fields set past the checks; decode it back as the same
    instruction, holding them and keeping the refusals of ``fields``."""
    for name, value in bad.items():
        object.__setattr__(model, name, value)
    with pytest.warns(RefusedFieldWarning):
        [decoded] = decode(encode_rung(1, [["-"] * 31], [model]))[0].instructions
    assert decoded == model
    return kept(decoded, *fields)


class TestTimerPresetRange:
    # 0..32767 for every unit; 32768 and any sign refused (OBJ-005).
    @pytest.mark.parametrize("unit", ["Tms", "Ts", "Tm", "Th", "Td"])
    def test_limits_for_every_unit(self, tmp_path: Path, unit: str) -> None:
        for value in ("0", "32767"):
            token = f"on_delay(T1,TD1,preset={value},unit={unit})"
            assert _read_af(tmp_path, token) == timer(preset=value, unit=unit)
        with pytest.raises(
            FieldError, match=r"^Timer.preset: '32768' is outside 0 to 32767 \(OBJ-005\)"
        ):
            _read_af(tmp_path, f"on_delay(T1,TD1,preset=32768,unit={unit})")
        with pytest.raises(
            FieldError, match=r"^Timer.preset: '32768' is outside 0 to 32767 \(OBJ-005\)"
        ):
            timer(preset="32768", unit=unit)

    @pytest.mark.parametrize("preset", ["-1", "+5", "1 0"])
    def test_sign_refused(self, tmp_path: Path, preset: str) -> None:
        with pytest.raises(FieldError, match="^Timer.preset"):
            _read_af(tmp_path, f"off_delay(T1,TD1,preset={preset},unit=Ts)")

    def test_refused_preset_decodes(self) -> None:
        _decoded_after(timer(), "Timer.preset", preset="40000")


class TestCounterPresetRange:
    # a 32-bit signed constant (OBJ-005); registers DS and DD only (OBJ-004).
    @pytest.mark.parametrize("preset", ["2147483647", "-2147483648", "0", "DS1", "DD1"])
    def test_accepted(self, tmp_path: Path, preset: str) -> None:
        parsed = _read_af(tmp_path, f"count_up(CT1,CTD1,preset={preset})")
        assert parsed == counter(preset=preset, reset_enabled=True)

    @pytest.mark.parametrize("preset", ["2147483648", "-2147483649", "99999999999"])
    def test_out_of_range(self, tmp_path: Path, preset: str) -> None:
        message = rf"^Counter.preset: '{preset}' is outside -2147483648 to 2147483647 \(OBJ-005\)"
        with pytest.raises(FieldError, match=message):
            _read_af(tmp_path, f"count_down(CT1,CTD1,preset={preset})")
        with pytest.raises(FieldError, match=message):
            counter(preset=preset)

    @pytest.mark.parametrize("preset", ["1.5", "abc", "1-2", "--5"])
    def test_not_an_integer(self, tmp_path: Path, preset: str) -> None:
        with pytest.raises(FieldError, match="^Counter.preset"):
            _read_af(tmp_path, f"count_up(CT1,CTD1,preset={preset})")

    def test_text_under_13_characters(self) -> None:
        # Counter: a constant's text is under 13 characters (OBJ-005).
        assert counter(preset="000000000001").preset == "000000000001"
        with pytest.raises(
            FieldError, match="13 characters; a constant here is at most 12 .OBJ-005."
        ):
            counter(preset="0000000000001")

    @pytest.mark.parametrize("preset", ["DH1", "DF1", "TD1", "CTD1", "SD1", "XD1"])
    def test_other_registers_refused(self, tmp_path: Path, preset: str) -> None:
        message = (
            rf"^Counter.preset: '{preset}' is not allowed; Counter.preset takes DS, DD \(OBJ-004\)"
        )
        with pytest.raises(AddressError, match=message + _AT_AF):
            _read_af(tmp_path, f"count_up(CT1,CTD1,preset={preset})")
        with pytest.raises(AddressError, match=message + "$"):
            counter(preset=preset)

    @pytest.mark.parametrize("preset", ["DH1", "2147483648", "0000000000001"])
    def test_refused_presets_decode(self, preset: str) -> None:
        _decoded_after(counter(reset_enabled=True), "Counter.preset", preset=preset)


class TestShiftRules:
    # C only (OBJ-004); start == end refused (OBJ-012); start > end allowed.
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
        with pytest.raises(AddressError, match=rf"^Shift.{field}: .* takes C \(OBJ-004\){_AT_AF}"):
            _read_af(tmp_path, token)

    @pytest.mark.parametrize("end", ["C1", "C001"])
    def test_same_address_refused(self, tmp_path: Path, end: str) -> None:
        # CLICK normalizes C001 to C1 as it is typed.
        with pytest.raises(FieldError, match=r"^Shift.end_bit: 'C1' is the same address"):
            _read_af(tmp_path, f"shift(C1..{end})")
        with pytest.raises(FieldError, match="OBJ-012"):
            Shift(start_bit="C1", end_bit=end)

    def test_refused_blob_decodes(self) -> None:
        _decoded_after(Shift(start_bit="C1", end_bit="C2"), "Shift.end_bit", end_bit="C1")

    def test_blob_not_in_display_form_decodes_as_raw(self) -> None:
        shift = Shift(start_bit="C1", end_bit="C2")
        object.__setattr__(shift, "start_bit", "Y1")
        object.__setattr__(shift, "end_bit", "Y2")
        [decoded] = decode(encode_rung(1, [["-"] * 31], [shift]))[0].instructions
        assert isinstance(decoded, RawInstruction) and decoded.class_name == "SR"

    def test_scr_same_address_decodes(self) -> None:
        # shift_scr: two shift(C1..C2) rungs; C2 occurs only as their end bits.
        data = (_SCR_DIR / "shift_scr.scr").read_bytes()
        assert data.count(_scr_text("C2")) == 2
        assert _scr_refused("C2", "C1", "shift_scr") == [("Shift", ["Shift.end_bit"])] * 2


class TestDrumDurations:
    # 0..32767 for every unit, digits only (OBJ-005); a register is DS (OBJ-004).
    @pytest.mark.parametrize("kind", ["time", "time_event"])
    @pytest.mark.parametrize("unit", ["Tms", "Ts", "Tm", "Th", "Td"])
    def test_limits(self, kind: str, unit: str) -> None:
        assert drum(kind, events_or_presets=["0", "32767"], unit=unit)
        assert drum(kind, events_or_presets=["DS1", "5"], unit=unit)
        with pytest.raises(
            FieldError, match=r"^Drum.presets\[1\]: '32768' is outside 0 to 32767 \(OBJ-005\)"
        ):
            drum(kind, events_or_presets=["1", "32768"], unit=unit)

    @pytest.mark.parametrize("preset", ["-1", "+5"])
    def test_sign_refused(self, preset: str) -> None:
        message = rf"^Drum.presets\[0\]: '{re.escape(preset)}' is refused; a constant here takes no sign \(OBJ-005\)"
        with pytest.raises(FieldError, match=message):
            drum("time", events_or_presets=[preset, "1"])

    def test_fraction_refused(self) -> None:
        message = r"^Drum.presets\[0\]: '1.5' is a real; Drum.presets\[0\] takes a decimal integer"
        with pytest.raises(FieldError, match=message):
            drum("time", events_or_presets=["1.5", "1"])

    @pytest.mark.parametrize("preset", ["DD1", "TD1", "DH1"])
    def test_other_registers_refused(self, preset: str) -> None:
        with pytest.raises(AddressError, match=r"^Drum.presets\[0\]: .* takes DS \(OBJ-004\)$"):
            drum("time", events_or_presets=[preset, "1"])

    def test_csv(self, tmp_path: Path) -> None:
        token = (
            "time_drum(outputs=[C1,C2],presets=[32768,1],unit=Ts,pattern=[[1,0],[0,1]],"
            "current_step=DS1,accumulator=TD1,completion_flag=C9)"
        )
        with pytest.raises(FieldError, match=r"^Drum.presets\[0\]: '32768'"):
            _read_af(tmp_path, token)
        assert isinstance(_read_af(tmp_path, token.replace("32768", "32767")), Drum)

    def test_refused_duration_decodes(self) -> None:
        _decoded_after(drum("time"), "Drum.events_or_presets[0]", events_or_presets=["40000", "1"])


class TestDrumEventsAndOutputs:
    # events X, Y, C, T, CT or SC (OBJ-004); outputs differ from each other and
    # from the completion flag (OBJ-014), compared as addresses.
    @pytest.mark.parametrize("event", ["X001", "Y001", "C5", "T1", "CT1", "SC1"])
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
        # CLICK normalizes C001 to C1 as it is typed.
        token = (
            f"event_drum(outputs=[C1,{second}],events=[X001,X002],pattern=[[1,0],[0,1]],"
            "current_step=DS1,completion_flag=C9)"
        )
        message = r"^Drum.outputs\[1\]: 'C1' is already output 0"
        with pytest.raises(FieldError, match=message):
            _read_af(tmp_path, token)

    def test_y_output_twice_refused(self) -> None:
        # CLICK writes Y1 as Y001: the same output.
        with pytest.raises(FieldError, match="OBJ-014"):
            drum(outputs=["Y001", "Y1"])

    @pytest.mark.parametrize("kind", ["event", "time", "time_event"])
    def test_output_is_completion_flag(self, kind: str) -> None:
        message = r"^Drum.outputs\[1\]: 'C50' is the completion flag"
        with pytest.raises(FieldError, match=message):
            drum(kind, outputs=["C1", "C050"], completion_flag="C50")

    @pytest.mark.parametrize(
        ("bad", "field"),
        [
            ({"outputs": ["C1", "C1"]}, "Drum.outputs[1]"),
            ({"outputs": ["C1", "C50"]}, "Drum.outputs[1]"),
            ({"events_or_presets": ["DS1", "C10"]}, "Drum.events_or_presets[0]"),
        ],
    )
    def test_refused_blobs_decode(self, bad: dict[str, list[str]], field: str) -> None:
        _decoded_after(drum(), field, **bad)

    @pytest.mark.parametrize(
        ("old", "new", "field"),
        [
            ("C184", "C183", "Drum.outputs[1]"),
            ("C184", "C187", "Drum.outputs[1]"),
            ("C185", "DS18", "Drum.events_or_presets[0]"),
        ],
    )
    def test_scr_refused_blobs_decode(self, old: str, new: str, field: str) -> None:
        # coverage: event_drum(outputs=[C183,C184],events=[C185,C186],...,completion_flag=C187).
        assert _scr_refused(old, new) == [("Drum", [field])]


class TestFieldNames:
    """A refusal names the dataclass field it came from, where the message does not."""

    def test_drum_names_the_field_of_a_message_without_one(self) -> None:
        with pytest.raises(FieldError) as steps:
            drum("event", events_or_presets=["C1"] * 33, pattern=[[1, 0]] * 33)
        assert steps.value.field == "Drum.events_or_presets"
        with pytest.raises(FieldError) as step:
            drum("time_event", events_or_presets=["", "5"], events=["", ""])
        assert step.value.fields == ("Drum.events_or_presets[0]", "Drum.events[0]")
        with pytest.raises(FieldError) as outs:
            drum(outs=33, steps=1)
        assert outs.value.field == "Drum.outputs"

    def test_kind_and_unit_refusals_name_the_field(self) -> None:
        with pytest.raises(FieldError) as kind:
            drum("bogus")
        assert kind.value.field == "Drum.drum_kind"
        with pytest.raises(FieldError) as unit:
            drum("time", unit="Tx")
        assert unit.value.field == "Drum.unit"
        with pytest.raises(FieldError) as timer_unit:
            timer(unit="Tx")
        assert timer_unit.value.field == "Timer.unit"
        with pytest.raises(FieldError) as kind:
            timer(kind="bogus")
        assert kind.value.field == "Timer.kind"
        with pytest.raises(FieldError) as kind:
            counter(kind="bogus")
        assert kind.value.field == "Counter.kind"

    def test_a_refusal_across_fields_names_the_class_or_the_field_it_names(self) -> None:
        with pytest.raises(FieldError) as mismatch:
            timer(accumulator="TD2")
        assert mismatch.value.field == "Timer.accumulator"
        with pytest.raises(FieldError) as ends:
            Shift(start_bit="C1", end_bit="C001")
        assert ends.value.field == "Shift.end_bit"


class TestLongDigitRuns:
    """5001 digits: leading zeros read as their value, above the limit is refused."""

    ZEROS = "0" * 5000 + "1"
    ONES = "1" * 5000

    @pytest.mark.parametrize("kind", ["time", "time_event"])
    @pytest.mark.parametrize("index", [0, 1])
    def test_drum_presets(self, kind: str, index: int) -> None:
        for value, ok in ((self.ZEROS, True), (self.ONES, False)):
            presets = ["5", "5"]
            presets[index] = value
            if ok:
                assert drum(kind, events_or_presets=presets).events_or_presets[index] == value
            else:
                with pytest.raises(FieldError, match=rf"^Drum.presets\[{index}\]"):
                    drum(kind, events_or_presets=presets)

    @pytest.mark.parametrize("kind", ["on_delay", "off_delay"])
    def test_timer_preset(self, kind: str) -> None:
        assert timer(kind=kind, preset=self.ZEROS).preset == self.ZEROS
        with pytest.raises(FieldError, match="^Timer.preset"):
            timer(kind=kind, preset=self.ONES)

    @pytest.mark.parametrize("value", [ZEROS, ONES])
    def test_counter_preset_refused(self, value: str) -> None:
        with pytest.raises(FieldError, match="^Counter.preset"):
            counter(preset=value)
