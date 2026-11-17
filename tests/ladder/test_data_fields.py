"""Tests of the field checks on Timer, Counter, Shift and Drum.

The checks follow the limits of CLICK's instruction dialogs.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from laddercodec import (
    AddressError,
    CsvError,
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
from laddercodec.model import Reason
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


def drum(kind: str = "event_drum", steps: int = 2, outs: int = 2, **kw) -> Drum:
    args: dict = {
        "kind": kind,
        "outputs": [f"C{i + 1}" for i in range(outs)],
        "pattern": [[1] * outs for _ in range(steps)],
        "current_step": "DS1",
        "completion_flag": "C50",
    }
    if kind == "event_drum":
        args["events"] = [f"C{i + 10}" for i in range(steps)]
    else:
        args.update(presets=["100"] * steps, accumulator="TD1", unit="Tms")
    if kind == "time_event_drum":
        args["events"] = ["C10"] * steps
    return Drum(**{**args, **kw})


class TestDrum:
    @pytest.mark.parametrize("kind", ["event_drum", "time_drum", "time_event_drum"])
    def test_valid_extremes(self, kind: str) -> None:
        assert drum(kind, steps=16, outs=16).num_steps == 16
        assert drum(kind, steps=1, outs=1).num_outputs == 1

    @pytest.mark.parametrize("kind", ["event_drum", "time_drum", "time_event_drum"])
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
        for kind in ("time_drum", "time_event_drum"):
            with pytest.raises(AddressError, match="accumulator"):
                drum(kind, accumulator="DS1")
            with pytest.raises(AddressError, match="accumulator"):
                drum(kind, accumulator="")

    def test_jump_step(self) -> None:
        assert drum(jump_enabled=True, jump_step="DS5").jump_step == "DS5"
        with pytest.raises(AddressError, match="jump_step"):
            drum(jump_enabled=True, jump_step="")
        with pytest.raises(AddressError, match="jump_step"):
            drum(jump_enabled=True, jump_step="C1")

    def test_event_drum_needs_every_event(self) -> None:
        with pytest.raises(FieldError, match="OBJ-021"):
            drum(events=["C10", ""])

    def test_time_drum_needs_every_duration(self) -> None:
        with pytest.raises(FieldError, match="OBJ-022"):
            drum("time_drum", presets=["100", ""])

    def test_time_event_step_needs_one_of_two(self) -> None:
        assert drum("time_event_drum", presets=["100", ""], events=["", "C10"])
        with pytest.raises(FieldError, match="OBJ-1019"):
            drum("time_event_drum", presets=["100", ""], events=["C10", ""])
        with pytest.raises(FieldError, match="one event per step"):
            drum("time_event_drum", events=["C10"])

    def test_unit(self) -> None:
        with pytest.raises(FieldError, match="Drum.unit"):
            drum("time_drum", unit="x")


class TestDrumPatternCells:
    @pytest.mark.parametrize("cell", [1.0, 0.0, "1", None, True])
    def test_non_int_cell_is_a_field_error(self, cell: object) -> None:
        with pytest.raises(FieldError, match="Drum.pattern"):
            drum(steps=1, outs=1, pattern=[[cell]])


# A blob that the parser can read, but whose values the checks refuse, decodes as its
# instruction, and the instruction keeps the refusal. A blob with a value that is not in
# CLICK's display form, or that the parser can't read, decodes as raw(...). Each test
# starts from a valid instruction and changes a value in its bytes or its fields after the
# checks have run.

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
    """Replace ``old`` with ``new`` in an SCR fixture and decode it. Return the class name
    and the refused fields of each instruction that keeps refusals."""
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
        object.__setattr__(d, "events", (*d.events, "C99"))
        object.__setattr__(d, "pattern", (*d.pattern, (1, 1)))
        assert d.num_steps == 17
        data = encode_rung(1, [["-"] * 31], [d])
        [decoded] = decode(data)[0].instructions
        assert isinstance(decoded, RawInstruction)
        assert decoded.class_name == "Drum"


# ---------------------------------------------------------------------------
# Rules from CLICK v4.00's instruction dialogs, with their OBJ ids, and address normalization.
# ---------------------------------------------------------------------------


def _read_af(tmp_path: Path, af: str) -> object:
    """Write a one-rung CSV that holds ``af``, read it, and return the first instruction.

    A counter or drum also gets the ``.reset()`` row that it needs.
    """
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", "X001"] + ["-"] * 30 + [af])
        if af.startswith(("count_", "event_drum", "time_drum", "time_event_drum")):
            w.writerow(["", "X002"] + ["-"] * 30 + [".reset()"])
    return read_csv(path)[0].instructions[0]


#: The location that ``read_csv`` puts at the end of an error message about the AF cell
#: that ``_read_af`` writes.
_AT_AF = r" \(at .*rung\.csv, line 2, rung at line 2, row 0 from 0, column AF\)$"


def _decoded_after(model: object, *fields: str, **bad: object) -> object:
    """Set the ``bad`` fields on ``model`` without running the checks, then encode and
    decode it. Assert that the decoded instruction equals ``model`` and keeps a refusal for
    each name in ``fields``, and return it."""
    for name, value in bad.items():
        object.__setattr__(model, name, value)
    with pytest.warns(RefusedFieldWarning):
        [decoded] = decode(encode_rung(1, [["-"] * 31], [model]))[0].instructions
    assert decoded == model
    return kept(decoded, *fields)


class TestTimerPresetRange:
    # A timer preset is 0 to 32767 for every unit. 32768 and a preset with a sign are
    # refused with OBJ-005.
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
    # A counter preset is a signed 32-bit constant or a DS or DD register. A constant out of
    # range is refused with OBJ-005, and any other register with OBJ-004.
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
        # A counter's constant preset is at most 12 characters long, leading zeros
        # included. A longer one is refused with OBJ-005.
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
    # A shift range takes C bits only, or it is refused with OBJ-004. The same address at
    # both ends is refused with OBJ-012. A start above the end is accepted.
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
        # shift_scr.scr holds two shift(C1..C2) rungs, and C2 appears only as their end bits.
        data = (_SCR_DIR / "shift_scr.scr").read_bytes()
        assert data.count(_scr_text("C2")) == 2
        assert _scr_refused("C2", "C1", "shift_scr") == [("Shift", ["Shift.end_bit"])] * 2


class TestDrumDurations:
    # A drum duration is 0 to 32767 for every unit, written in digits only, or it is refused
    # with OBJ-005. A register duration must be DS, or it is refused with OBJ-004.
    @pytest.mark.parametrize("kind", ["time_drum", "time_event_drum"])
    @pytest.mark.parametrize("unit", ["Tms", "Ts", "Tm", "Th", "Td"])
    def test_limits(self, kind: str, unit: str) -> None:
        assert drum(kind, presets=["0", "32767"], unit=unit)
        assert drum(kind, presets=["DS1", "5"], unit=unit)
        with pytest.raises(
            FieldError, match=r"^Drum.presets\[1\]: '32768' is outside 0 to 32767 \(OBJ-005\)"
        ):
            drum(kind, presets=["1", "32768"], unit=unit)

    @pytest.mark.parametrize("preset", ["-1", "+5"])
    def test_sign_refused(self, preset: str) -> None:
        message = rf"^Drum.presets\[0\]: '{re.escape(preset)}' is refused; a constant here takes no sign \(OBJ-005\)"
        with pytest.raises(FieldError, match=message):
            drum("time_drum", presets=[preset, "1"])

    def test_fraction_refused(self) -> None:
        message = r"^Drum.presets\[0\]: '1.5' is a real; Drum.presets\[0\] takes a decimal integer"
        with pytest.raises(FieldError, match=message):
            drum("time_drum", presets=["1.5", "1"])

    @pytest.mark.parametrize("preset", ["DD1", "TD1", "DH1"])
    def test_other_registers_refused(self, preset: str) -> None:
        with pytest.raises(AddressError, match=r"^Drum.presets\[0\]: .* takes DS \(OBJ-004\)$"):
            drum("time_drum", presets=[preset, "1"])

    def test_csv(self, tmp_path: Path) -> None:
        token = (
            "time_drum(outputs=[C1,C2],presets=[32768,1],unit=Ts,pattern=[[1,0],[0,1]],"
            "current_step=DS1,accumulator=TD1,completion_flag=C9)"
        )
        with pytest.raises(FieldError, match=r"^Drum.presets\[0\]: '32768'"):
            _read_af(tmp_path, token)
        assert isinstance(_read_af(tmp_path, token.replace("32768", "32767")), Drum)

    def test_refused_duration_decodes(self) -> None:
        _decoded_after(drum("time_drum"), "Drum.presets[0]", presets=("40000", "1"))


class TestDrumEventsAndOutputs:
    # An event is an X, Y, C, T, CT or SC bit, or it is refused with OBJ-004. Each output
    # must differ from the other outputs and from the completion flag, or it is refused with
    # OBJ-014. The check compares addresses, not text, so C050 and C50 are the same.
    @pytest.mark.parametrize("event", ["X001", "Y001", "C5", "T1", "CT1", "SC1"])
    def test_event_banks_accepted(self, event: str) -> None:
        assert drum(events=[event, "C10"]).events[0] == event
        assert drum("time_event_drum", events=[event, ""]).events[0] == event

    @pytest.mark.parametrize("event", ["DS1", "TD1", "XD0", "TXT1"])
    def test_other_event_banks_refused(self, event: str) -> None:
        message = r"^Drum.events\[0\]: .* takes X, Y, C, T, CT, SC$"
        with pytest.raises(AddressError, match=message):
            drum(events=[event, "C10"])
        with pytest.raises(AddressError, match=message):
            drum("time_event_drum", events=[event, ""])

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
        # CLICK writes Y1 as Y001, so the two are the same output.
        with pytest.raises(FieldError, match="OBJ-014"):
            drum(outputs=["Y001", "Y1"])

    @pytest.mark.parametrize("kind", ["event_drum", "time_drum", "time_event_drum"])
    def test_output_is_completion_flag(self, kind: str) -> None:
        message = r"^Drum.outputs\[1\]: 'C50' is the completion flag"
        with pytest.raises(FieldError, match=message):
            drum(kind, outputs=["C1", "C050"], completion_flag="C50")

    @pytest.mark.parametrize(
        ("bad", "field"),
        [
            ({"outputs": ("C1", "C1")}, "Drum.outputs[1]"),
            ({"outputs": ("C1", "C50")}, "Drum.outputs[1]"),
            ({"events": ("DS1", "C10")}, "Drum.events[0]"),
        ],
    )
    def test_refused_blobs_decode(self, bad: dict[str, tuple[str, ...]], field: str) -> None:
        _decoded_after(drum(), field, **bad)

    @pytest.mark.parametrize(
        ("old", "new", "field"),
        [
            ("C184", "C183", "Drum.outputs[1]"),
            ("C184", "C187", "Drum.outputs[1]"),
            ("C185", "DS18", "Drum.events[0]"),
        ],
    )
    def test_scr_refused_blobs_decode(self, old: str, new: str, field: str) -> None:
        # coverage.scr holds
        # event_drum(outputs=[C183,C184],events=[C185,C186],...,completion_flag=C187).
        assert _scr_refused(old, new) == [("Drum", [field])]


class TestDrumNames:
    """A Drum's field names are its CSV keywords, it stores its lists as tuples, and its
    ``kind`` is the name of its CSV call."""

    def test_lists_are_stored_as_tuples(self) -> None:
        d = drum("time_event_drum")
        assert (type(d.outputs), type(d.presets), type(d.events)) == (tuple,) * 3
        assert type(d.pattern) is tuple and type(d.pattern[0]) is tuple

    def test_a_list_and_a_tuple_build_equal_drums(self) -> None:
        a = drum(outputs=["C1", "C2"], pattern=[[1, 0], [0, 1]], events=["C10", "C11"])
        b = drum(outputs=("C1", "C2"), pattern=((1, 0), (0, 1)), events=("C10", "C11"))
        assert a == b
        assert a.to_csv() == b.to_csv()
        assert a.build_blob() == b.build_blob()

    @pytest.mark.parametrize("kind", ["event_drum", "time_drum", "time_event_drum"])
    def test_csv_round_trip_keeps_the_kind(self, kind: str, tmp_path: Path) -> None:
        d = drum(kind)
        assert d.to_csv().startswith(f"{kind}(")
        assert _read_af(tmp_path, d.to_csv()) == d

    def test_an_event_drum_refuses_presets(self) -> None:
        with pytest.raises(FieldError) as error:
            drum("event_drum", presets=["100", "200"])
        assert (error.value.field, error.value.reason) == ("Drum.presets", Reason.CONFLICT)

    def test_a_time_drum_refuses_events(self) -> None:
        with pytest.raises(FieldError) as error:
            drum("time_drum", events=["C10", "C11"])
        assert (error.value.field, error.value.reason) == ("Drum.events", Reason.CONFLICT)

    def test_the_old_names_are_gone(self) -> None:
        with pytest.raises(TypeError):
            Drum(drum_kind="event_drum")  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            drum(events_or_presets=["C1", "C2"])

    def test_the_old_kind_values_are_refused(self) -> None:
        with pytest.raises(FieldError) as error:
            drum("time_event")
        assert (error.value.field, error.value.reason) == ("Drum.kind", Reason.CHOICE)


class TestDrumCsvChecks:
    """A drum token that lacks a required keyword raises CsvError. A value in the token that
    the Drum refuses raises the Drum's FieldError."""

    TIME = (
        "time_drum(outputs=[C1,C2],presets=[100,200],{unit}pattern={pattern},"
        "current_step=DS1,accumulator=TD1,completion_flag=C9)"
    )
    TIME_EVENT = (
        "time_event_drum(outputs=[C1,C2],presets=[100,None],events=[None,C20],{unit}"
        "pattern=[[1,0],[0,1]],current_step=DS1,{accumulator}completion_flag=C9)"
    )

    def _time(self, unit: str = "unit=Tms,", pattern: str = "[[1,0],[0,1]]") -> str:
        return self.TIME.format(unit=unit, pattern=pattern)

    def _time_event(self, unit: str = "unit=Tms,", accumulator: str = "accumulator=TD1,") -> str:
        return self.TIME_EVENT.format(unit=unit, accumulator=accumulator)

    @pytest.mark.parametrize("unit", ["", "unit=,"])
    def test_a_time_drum_without_a_unit_is_a_csv_error(self, tmp_path: Path, unit: str) -> None:
        with pytest.raises(CsvError, match="time_drum needs unit="):
            _read_af(tmp_path, self._time(unit))
        with pytest.raises(CsvError, match="time_event_drum needs unit="):
            _read_af(tmp_path, self._time_event(unit))

    def test_a_bad_unit_is_a_field_error(self, tmp_path: Path) -> None:
        for token in (self._time("unit=Bad,"), self._time_event("unit=Bad,")):
            with pytest.raises(FieldError, match="^Drum.unit: 'Bad' is not one of Tms") as error:
                _read_af(tmp_path, token)
            assert error.value.reason is Reason.CHOICE

    def test_a_time_event_drum_without_an_accumulator_is_a_csv_error(self, tmp_path: Path) -> None:
        with pytest.raises(CsvError, match="time_event_drum needs accumulator="):
            _read_af(tmp_path, self._time_event(accumulator=""))

    def test_a_blank_time_event_accumulator_is_a_field_error(self, tmp_path: Path) -> None:
        with pytest.raises(AddressError, match="^Drum.accumulator: is blank") as error:
            _read_af(tmp_path, self._time_event(accumulator="accumulator=,"))
        assert error.value.reason is Reason.MISSING

    def test_a_time_event_accumulator_outside_td_is_a_field_error(self, tmp_path: Path) -> None:
        with pytest.raises(AddressError, match="^Drum.accumulator") as error:
            _read_af(tmp_path, self._time_event(accumulator="accumulator=DS1,"))
        assert error.value.reason is Reason.BANK

    @pytest.mark.parametrize("pattern", ["[[1,2],[0,1]]", "[[1,x],[0,1]]", "[[1,],[0,1]]"])
    def test_a_pattern_cell_outside_0_and_1_is_a_field_error(
        self, tmp_path: Path, pattern: str
    ) -> None:
        with pytest.raises(FieldError, match="^Drum.pattern: .* cells are 0 or 1") as error:
            _read_af(tmp_path, self._time(pattern=pattern))
        assert error.value.reason is Reason.CHOICE

    def test_a_pattern_that_is_no_list_is_a_csv_error(self, tmp_path: Path) -> None:
        with pytest.raises(CsvError, match="Expected nested list"):
            _read_af(tmp_path, self._time(pattern="1"))


class TestFieldNames:
    """A refusal's ``field`` names the dataclass field that it is about, even when its
    message does not name that field."""

    def test_drum_names_the_field_of_a_message_without_one(self) -> None:
        with pytest.raises(FieldError) as steps:
            drum("event_drum", events=["C1"] * 33, pattern=[[1, 0]] * 33)
        assert steps.value.field == "Drum.events"
        with pytest.raises(FieldError) as step:
            drum("time_event_drum", presets=["", "5"], events=["", ""])
        assert step.value.fields == ("Drum.presets[0]", "Drum.events[0]")
        with pytest.raises(FieldError) as outs:
            drum(outs=33, steps=1)
        assert outs.value.field == "Drum.outputs"

    def test_kind_and_unit_refusals_name_the_field(self) -> None:
        with pytest.raises(FieldError) as kind:
            drum("bogus")
        assert kind.value.field == "Drum.kind"
        with pytest.raises(FieldError) as unit:
            drum("time_drum", unit="Tx")
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
    """A preset of 5000 or 5001 digits is checked without a crash. A timer or drum reads
    5000 zeros and a 1 as the value 1, and refuses 5000 ones as above its limit. A counter
    refuses both."""

    ZEROS = "0" * 5000 + "1"
    ONES = "1" * 5000

    @pytest.mark.parametrize("kind", ["time_drum", "time_event_drum"])
    @pytest.mark.parametrize("index", [0, 1])
    def test_drum_presets(self, kind: str, index: int) -> None:
        for value, ok in ((self.ZEROS, True), (self.ONES, False)):
            presets = ["5", "5"]
            presets[index] = value
            if ok:
                assert drum(kind, presets=presets).presets[index] == value
            else:
                with pytest.raises(FieldError, match=rf"^Drum.presets\[{index}\]"):
                    drum(kind, presets=presets)

    @pytest.mark.parametrize("kind", ["on_delay", "off_delay"])
    def test_timer_preset(self, kind: str) -> None:
        assert timer(kind=kind, preset=self.ZEROS).preset == self.ZEROS
        with pytest.raises(FieldError, match="^Timer.preset"):
            timer(kind=kind, preset=self.ONES)

    @pytest.mark.parametrize("value", [ZEROS, ONES])
    def test_counter_preset_refused(self, value: str) -> None:
        with pytest.raises(FieldError, match="^Counter.preset"):
            counter(preset=value)
