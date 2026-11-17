"""Drum — event, time, and time & event drum instructions (type marker 0x271B).

Binary class name: ``"Drum"``.
Drum types: event_drum (event-driven), time_drum (time-driven), and CLICK v4's
time_event_drum (each step ends on its preset time and/or its event).
Event and time drums use the 64-field v3 blob.  The v4-only drums, time & event
and a time drum with a register preset, use v4's 82-field blob (16 preset slots
``0x6891``, constant-preset mask ``0x428A``, timer done bit ``0x6068``).
4 grid rows: main + reset (row 1) + jump (row 2) + jog (row 3), more when OR
legs under a pin push the later pins down (``pin_rows``, the blob's part bytes).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal, cast

from ..binary_helpers import tag_flag, tag_int, tag_value
from ..errors import CsvError, EncodeError
from ..model import (
    Address,
    PinnedInstruction,
    Reason,
    check_address,
    normalize_items,
)
from ..operands.checks import BIT_BANKS, Constants, Refusals, check_operand
from ..operands.constants import INT16_MAX, Kind
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

# Event drum: no-jog group (base, reset, jump)
_EVENT_FC_NO_JOG = (8491, 8492, 8493)
# Event drum: jog group (base, reset, jump, jog)
_EVENT_FC_JOG = (8494, 8495, 8496, 8497)

# Time drum: unit → first func code of its block (no-jog group: base, reset, jump).
# The jog group (base, reset, jump, jog) follows at block+3, except for Th, whose
# jog group is at block+4: code 8479 is the unused one,
# which makes the Th block 8 codes long.
_TIME_FC_BASE: dict[str, int] = {
    "Tms": 8455,
    "Ts": 8462,
    "Tm": 8469,
    "Th": 8476,
    "Td": 8484,
}
_TH_JOG_SKIP = 1

# A time drum with a register preset (CLICK v4) uses the same blocks 1792 codes up
# (Tms 10247); constant presets only keep the 8455 series.
_REGISTER_PRESET_FC_OFFSET = 10247 - 8455

# Time & event drum (CLICK v4): unit → first func code of its block; same block
# shape as the time drum.
_TIME_EVENT_FC_BASE: dict[str, int] = {
    "Tms": 10503,
    "Ts": 10510,
    "Tm": 10517,
    "Th": 10524,
    "Td": 10532,
}

#: A drum has at most 16 steps and 16 outputs.
_MAX_DRUM_SIZE = 16

# Drum base (tag 0x2200).
_BASE_TIME, _BASE_EVENT, _BASE_TIME_EVENT = "0", "1", "2"

# Time unit name → index string (same convention as Timer).
_DRUM_UNIT_TO_INDEX: dict[str, str] = {
    "Tms": "0",
    "Ts": "1",
    "Tm": "2",
    "Th": "3",
    "Td": "4",
}
_DRUM_INDEX_TO_UNIT: dict[str, str] = {v: k for k, v in _DRUM_UNIT_TO_INDEX.items()}

_DRUM_KINDS = ("event_drum", "time_drum", "time_event_drum")

# ---------------------------------------------------------------------------
# Pattern encoding
# ---------------------------------------------------------------------------


def _pattern_to_bitmasks(pattern: tuple[tuple[int, ...], ...], num_steps: int) -> list[str]:
    """Convert pattern matrix to signed-int16 bitmask strings (16 slots)."""
    result: list[str] = []
    for step_idx in range(16):
        if step_idx < num_steps:
            bitmask = sum(bit << i for i, bit in enumerate(pattern[step_idx]))
            if bitmask >= 32768:
                bitmask -= 65536
            result.append(str(bitmask))
        else:
            result.append("0")
    return result


def _parse_simple_list(val: str) -> tuple[str, ...]:
    """Parse ``"[a,b,c]"`` into a tuple of strings."""
    val = val.strip()
    if not val.startswith("[") or not val.endswith("]"):
        raise CsvError(f"Expected list: {val!r}")
    inner = val[1:-1].strip()
    if not inner:
        return ()
    return tuple(x.strip() for x in inner.split(","))


def _parse_pattern(val: str) -> tuple[tuple[int | str, ...], ...]:
    """Parse ``"[[1,0],[0,1]]"`` into rows of cells.

    A cell that is not an integer stays text, for the Drum to refuse."""
    val = val.strip()
    if not val.startswith("[") or not val.endswith("]"):
        raise CsvError(f"Expected nested list: {val!r}")
    inner = val[1:-1].strip()
    rows: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(inner):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "," and depth == 0:
            rows.append(inner[start:i].strip())
            start = i + 1
    rows.append(inner[start:].strip())
    pattern: list[tuple[int | str, ...]] = []
    for row_str in rows:
        if not row_str:
            continue
        cells = _parse_simple_list(row_str)
        pattern.append(tuple(_pattern_cell(x) for x in cells))
    return tuple(pattern)


def _pattern_cell(text: str) -> int | str:
    return int(text) if text in ("0", "1") else text


def _parse_optional_list(val: str) -> tuple[str, ...]:
    """Parse ``"[1000,None,DS1]"``; ``None`` (an unused step slot) becomes ``""``."""
    return tuple("" if x == "None" else x for x in _parse_simple_list(val))


def _format_optional_list(values: tuple[str, ...]) -> str:
    return ",".join(value or "None" for value in values)


#: A preset that names a register rather than a literal duration.
_REGISTER_RE = re.compile(r"[A-Z]+[0-9]+")


def is_register_preset(preset: str) -> bool:
    """Whether a time drum preset names a register (``DS1``) rather than a duration."""
    return bool(_REGISTER_RE.fullmatch(preset))


def _constant_preset_mask(presets: tuple[str, ...]) -> str:
    """Tag 0x428A: bit *n* stays set unless step *n*'s preset is a register.

    All 16 bits set (``-1``) when every preset is a constant or blank; CLICK v4
    writes it on OK, and picks a time drum's func code series from it.
    """
    mask = -1
    for i, preset in enumerate(presets):
        if is_register_preset(preset):
            mask &= ~(1 << i)
    return str(mask)


#: A constant step duration is 0 to 32767 for every unit, digits only: an int16
#: with no ``-`` or ``+``, else OBJ-005.  A register duration is DS (OBJ-004 for another
#: bank); whether the CPU takes a register at all is a project rule and is not checked.
_DURATION = Constants(frozenset({Kind.INTEGER}), signs="", low=0, high=INT16_MAX)


def _check_distinct_outputs(
    check: Refusals, outputs: list[Address | None], texts: tuple[str, ...], flag: Address | None
) -> None:
    """Refuse an output used twice, or used as the completion flag (OBJ-014).

    CLICK normalizes an address as it is typed (``C001`` becomes ``C1``) before it
    compares, so ``C1`` and ``C001`` are the same output.  An output refused on its own
    (``None``) is not compared.
    """
    seen: dict[Address, int] = {}
    for i, (output, text) in enumerate(zip(outputs, texts, strict=True)):
        if output is None:
            continue
        if output in seen:
            check.refuse(
                (f"outputs[{i}]", f"outputs[{seen[output]}]"),
                f"{text!r} is already output {seen[output]}; each output is a different bit",
                Reason.CONFLICT,
                "OBJ-014",
            )
            continue
        seen[output] = i
        if output == flag:
            check.refuse(
                (f"outputs[{i}]", "completion_flag"),
                f"{text!r} is the completion flag; an output is a different bit",
                Reason.CONFLICT,
                "OBJ-014",
            )


def _refuse_blank_steps(
    check: Refusals, attr: str, blank: list[int], rule: str, click_id: str
) -> None:
    """Refuse a list field with a blank step: the list itself, or, where another refusal
    already covers the list, each blank step, so that refusal does not hide this one."""
    if not blank:
        return
    if check.refused(attr):
        for i in blank:
            check.refuse(f"{attr}[{i}]", rule, Reason.MISSING, click_id)
    else:
        check.refuse(attr, rule, Reason.MISSING, click_id)


def _timer_done_bit(accumulator: str) -> str:
    """``TD101`` -> ``T101``: the timer a time & event drum's accumulator belongs to."""
    if not accumulator.startswith("TD"):
        raise CsvError(f"time_event_drum accumulator must be a TD address: {accumulator!r}")
    return f"T{accumulator[2:]}"


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Drum(PinnedInstruction):
    """A drum sequencer instruction (event_drum / time_drum / time_event_drum).

    Occupies the AF column.  The binary class name is ``Drum``
    (type marker 0x271B).  A drum takes at least 4 grid rows: row 0 = main,
    then reset, jump and jog at ``pin_rows`` (1, 2, 3 unless OR legs grow it).

    ``kind`` is the CSV call name.  An event drum has ``events``, a time drum has
    ``presets``, and a time & event drum has both, one of each per step; giving a
    drum the one its kind does not use is refused.  A time & event step may leave
    either one blank (``""``, ``None`` in CSV).  The lists are stored as tuples.
    """

    kind: Literal["event_drum", "time_drum", "time_event_drum"]
    outputs: tuple[str, ...] = ()
    presets: tuple[str, ...] = ()  # time and time & event drums
    events: tuple[str, ...] = ()  # event and time & event drums
    pattern: tuple[tuple[int, ...], ...] = ()
    current_step: str = ""
    completion_flag: str = ""
    accumulator: str = ""  # TD address (time and time & event drums)
    unit: str = ""  # "Tms"/"Ts"/"Tm"/"Th"/"Td" (time and time & event drums)
    jog_enabled: bool = False
    jump_enabled: bool = False
    jump_step: str = ""  # DS address
    #: Rows of the reset, jump and jog inputs below the main row.  OR legs under
    #: a pin push the later pins down; an unused pin keeps its row.
    pin_rows: tuple[int, ...] = (1, 2, 3)

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            check.flag("jog_enabled", "jump_enabled")
            check.run(self._check_pin_rows)
            for name in ("outputs", "presets", "events"):
                check.run(normalize_items, self, name)
            self._freeze_pattern()
            check.normalize("current_step", "completion_flag", "accumulator", "jump_step")
            kind = self.kind
            if kind not in _DRUM_KINDS:
                check.refuse(
                    "kind", f"{kind!r} is not one of {', '.join(_DRUM_KINDS)}", Reason.CHOICE
                )
            else:
                if kind == "event_drum" and self.presets:
                    check.refuse(
                        "presets", "an event drum has events, not presets", Reason.CONFLICT
                    )
                elif kind == "time_drum" and self.events:
                    check.refuse("events", "a time drum has presets, not events", Reason.CONFLICT)
            steps, outputs = self.num_steps, self.num_outputs
            steps_field = "events" if kind == "event_drum" else "presets"
            sizes_ok = True
            if not 1 <= steps <= _MAX_DRUM_SIZE:
                sizes_ok = False
                check.refuse(
                    steps_field,
                    f"{steps} steps is outside 1-{_MAX_DRUM_SIZE}",
                    Reason.RANGE,
                )
            if not 1 <= outputs <= _MAX_DRUM_SIZE:
                sizes_ok = False
                check.refuse(
                    "outputs", f"{outputs} outputs is outside 1-{_MAX_DRUM_SIZE}", Reason.RANGE
                )
            if sizes_ok:
                self._check_pattern(check, steps, outputs)
            addresses = [
                check(f"outputs[{i}]", check_address, banks={"Y", "C"})
                for i in range(len(self.outputs))
            ]
            check("current_step", check_address, banks={"DS"})
            flag = check("completion_flag", check_address, banks={"C"})
            _check_distinct_outputs(check, addresses, self.outputs, flag)
            # The checks of the items read the kind: a refused kind leaves them out.
            if not check.refused("kind"):
                for i, event in enumerate(self.events):
                    if event:
                        check(
                            f"events[{i}]",
                            check_address,
                            banks=BIT_BANKS,
                            label=f"Drum.events[{i}]",
                        )
                for i, preset in enumerate(self.presets):
                    if preset:
                        check(
                            f"presets[{i}]",
                            check_operand,
                            {"DS"},
                            _DURATION,
                            letter_first=True,
                            label=f"Drum.presets[{i}]",
                            bank_id="OBJ-004",
                        )
            if self.jump_enabled is True:
                check("jump_step", check_address, banks={"DS"})
            if not check.refused("kind"):
                if kind == "event_drum":
                    _refuse_blank_steps(
                        check,
                        "events",
                        [i for i, event in enumerate(self.events) if not event],
                        "every step needs an event",
                        "OBJ-021",
                    )
                else:
                    self._check_timed(check, kind, steps, sizes_ok)

    def _freeze_pattern(self) -> None:
        """Store the pattern as a tuple of tuples, as given lists of lists.  A pattern that
        can't be iterated stays as it is, for the checks of its shape to find."""
        try:
            pattern = tuple(tuple(row) for row in self.pattern)
        except TypeError:
            return
        object.__setattr__(self, "pattern", pattern)

    def _check_pattern(self, check: Refusals, steps: int, outputs: int) -> None:
        """The pattern is one row per step and one cell per output, each 0 or 1."""
        if len(self.pattern) != steps or any(len(row) != outputs for row in self.pattern):
            check.refuse(
                "pattern",
                f"needs {steps} steps of {outputs} cells each, got "
                f"{len(self.pattern)} steps of {sorted({len(row) for row in self.pattern})} cells",
                Reason.FORM,
            )
            return
        for row in self.pattern:
            for cell in row:
                if type(cell) is not int or cell not in (0, 1):
                    check.refuse(
                        "pattern", f"{cell!r} is not allowed, cells are 0 or 1", Reason.CHOICE
                    )
                    return

    def _check_timed(self, check: Refusals, kind: str, steps: int, sizes_ok: bool) -> None:
        """What a time or time & event drum adds: the unit, the accumulator, each step's
        duration and event."""
        if self.unit not in _DRUM_UNIT_TO_INDEX:
            check.refuse(
                "unit",
                f"{self.unit!r} is not one of {', '.join(_DRUM_UNIT_TO_INDEX)}",
                Reason.CHOICE,
            )
        check("accumulator", check_address, banks={"TD"})
        if kind == "time_drum":
            _refuse_blank_steps(
                check,
                "presets",
                [i for i, preset in enumerate(self.presets) if not preset],
                "every step needs a duration",
                "OBJ-022",
            )
            return
        if not sizes_ok:
            return
        if len(self.events) != steps:
            check.refuse(
                ("events", "presets"),
                f"needs one event per step ({steps}), got {len(self.events)}",
                Reason.CONFLICT,
            )
            return
        for i, (preset, event) in enumerate(zip(self.presets, self.events, strict=True)):
            if not preset and not event:
                check.refuse(
                    (f"presets[{i}]", f"events[{i}]"),
                    f"step {i + 1} needs a duration or an event",
                    Reason.MISSING,
                    "OBJ-1019",
                )

    @property
    def num_outputs(self) -> int:
        return len(self.outputs)

    @property
    def num_steps(self) -> int:
        return len(self.events if self.kind == "event_drum" else self.presets)

    @property
    def has_register_preset(self) -> bool:
        """A time or time & event drum reads a step's duration from a register."""
        return self.kind != "event_drum" and any(
            is_register_preset(preset) for preset in self.presets
        )

    @property
    def v4_blob(self) -> bool:
        """Written in v4's 82-field form: time & event, or a time drum with a register preset."""
        return self.kind == "time_event_drum" or self.has_register_preset

    def to_csv(self) -> str:
        outputs_str = ",".join(self.outputs)
        pattern_str = ",".join("[" + ",".join(str(v) for v in step) + "]" for step in self.pattern)
        if self.kind == "event_drum":
            events_str = ",".join(self.events)
            return (
                f"event_drum(outputs=[{outputs_str}],"
                f"events=[{events_str}],"
                f"pattern=[{pattern_str}],"
                f"current_step={self.current_step},"
                f"completion_flag={self.completion_flag})"
            )
        if self.kind == "time_event_drum":
            return (
                f"time_event_drum(outputs=[{outputs_str}],"
                f"presets=[{_format_optional_list(self.presets)}],"
                f"events=[{_format_optional_list(self.events)}],"
                f"unit={self.unit},"
                f"pattern=[{pattern_str}],"
                f"current_step={self.current_step},"
                f"accumulator={self.accumulator},"
                f"completion_flag={self.completion_flag})"
            )
        presets_str = ",".join(self.presets)
        return (
            f"time_drum(outputs=[{outputs_str}],"
            f"presets=[{presets_str}],"
            f"unit={self.unit},"
            f"pattern=[{pattern_str}],"
            f"current_step={self.current_step},"
            f"accumulator={self.accumulator},"
            f"completion_flag={self.completion_flag})"
        )

    def cell_params(self) -> dict:
        # +0x0A keeps the base height when OR legs grow the box (pins.bin).
        return {"visual_rows": self.pin_rows[-1] + 1, "sub_rows": 4}

    def pin_names(self) -> tuple[str, ...]:
        return (".reset", ".jump", ".jog")

    def pin_labels(self) -> tuple[str | None, ...]:
        return (
            ".reset()",
            f".jump({self.jump_step})" if self.jump_enabled else None,
            ".jog()" if self.jog_enabled else None,
        )

    def with_pins(self, pins: dict[str, tuple[str, ...]], pin_rows: tuple[int, ...]) -> Drum:
        if ".reset" not in pins:
            raise CsvError("Drum requires a .reset() pin row")
        drum = replace(self, pin_rows=cast(tuple[int, int, int], pin_rows))
        if ".jump" in pins:
            target = pins[".jump"][0] if pins[".jump"] else ""
            drum = replace(drum, jump_enabled=True, jump_step=target)
        if ".jog" in pins:
            drum = replace(drum, jog_enabled=True)
        return drum

    def _compute_func_codes(self) -> list[str]:
        """Return the 4 func-code slot values [base, reset, jump, jog].

        Codes run consecutively over the enabled pins: with jump off, jog takes
        the code jump would have had (8496, not 8497).  CLICK v3 accepts either;
        v4's syntax check rejects the gap with C000A ("All inputs of the box
        instruction must originate from the same branch").
        """
        if self.kind == "event_drum":
            if self.jog_enabled:
                base, reset = _EVENT_FC_JOG[0], _EVENT_FC_JOG[1]
                jump = _EVENT_FC_JOG[2] if self.jump_enabled else 0
                jog = _EVENT_FC_JOG[3] if self.jump_enabled else _EVENT_FC_JOG[2]
            else:
                base, reset = _EVENT_FC_NO_JOG[0], _EVENT_FC_NO_JOG[1]
                jump = _EVENT_FC_NO_JOG[2] if self.jump_enabled else 0
                jog = 0
            return [str(base), str(reset), str(jump), str(jog)]
        if self.kind == "time_event_drum":
            block_base = _TIME_EVENT_FC_BASE.get(self.unit, 0)
        else:
            block_base = _TIME_FC_BASE.get(self.unit, 0)
            if block_base and self.has_register_preset:
                block_base += _REGISTER_PRESET_FC_OFFSET
        if not block_base:
            raise EncodeError(f"Unsupported {self.kind} unit: {self.unit!r}")
        # Each time unit's block has the event drum's shape: no-jog group (base,
        # reset, jump) then jog group (base, reset, jump, jog).
        if self.jog_enabled:
            jog_base = block_base + 3 + (_TH_JOG_SKIP if self.unit == "Th" else 0)
            base, reset = jog_base, jog_base + 1
            jump = jog_base + 2 if self.jump_enabled else 0
            jog = jog_base + 3 if self.jump_enabled else jog_base + 2
        else:
            base, reset = block_base, block_base + 1
            jump = block_base + 2 if self.jump_enabled else 0
            jog = 0
        return [str(base), str(reset), str(jump), str(jog)]

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this drum cell."""
        from ..binary_helpers import _tagged_field, _utf16le_null, _variant_tagged_field
        from ..model import InstructionType

        type_marker = 0x2700 | InstructionType.DRUM

        out = bytearray()
        out += _utf16le_null("Drum")
        out += struct.pack("<I", type_marker)
        out += struct.pack("<H", 4)  # part count
        out += bytes(self.pin_rows)  # extra bytes: each pin's row
        time_event = self.kind == "time_event_drum"
        out += struct.pack("<I", 82 if self.v4_blob else 64)  # field count

        # Fields 0-3: func codes (sub-indexed 0x3A05)
        func_codes = self._compute_func_codes()
        for i, fc in enumerate(func_codes):
            out += _variant_tagged_field(0x3A05, struct.pack("<I", i), fc)

        # Field 4: drum base (0=time, 1=event, 2=time & event)
        base = {
            "time_drum": _BASE_TIME,
            "event_drum": _BASE_EVENT,
            "time_event_drum": _BASE_TIME_EVENT,
        }
        out += _tagged_field(0x2200, base[self.kind])

        # Field 5: time unit index
        unit_idx = _DRUM_UNIT_TO_INDEX.get(self.unit, "0") if self.kind != "event_drum" else "0"
        out += _tagged_field(0x21F9, unit_idx)

        # Fields 6-7: num_steps, num_outputs
        out += _tagged_field(0x3203, str(self.num_steps))
        out += _tagged_field(0x3204, str(self.num_outputs))

        # Field 8: current_step
        out += _tagged_field(0x606E, self.current_step)

        # Field 9: accumulator (time drum: TD address, event: empty)
        out += _tagged_field(0x606F, self.accumulator)

        # Field 10: completion_flag
        out += _tagged_field(0x6070, self.completion_flag)

        # Field 11: jog enabled
        out += _tagged_field(0x1201, "-1" if self.jog_enabled else "0")

        # Field 12: jump enabled
        out += _tagged_field(0x1202, "-1" if self.jump_enabled else "0")

        # Field 13: jump target
        out += _tagged_field(0x6071, self.jump_step)

        # Fields 14-29: events/presets (sub-indexed 0x6872, 16 slots); a time & event
        # drum keeps its events here and its presets in 0x6891.
        step_values = self.presets if self.kind == "time_drum" else self.events
        for i in range(16):
            value = step_values[i] if i < len(step_values) else ""
            out += _variant_tagged_field(0x6872, struct.pack("<I", i), value)

        # Fields 30-45: pattern bitmasks (sub-indexed 0x3A26, 16 slots)
        bitmasks = _pattern_to_bitmasks(self.pattern, self.num_steps)
        for i in range(16):
            out += _variant_tagged_field(0x3A26, struct.pack("<I", i), bitmasks[i])

        # Fields 46-61: outputs (sub-indexed 0x6873, 16 slots)
        for i in range(16):
            value = self.outputs[i] if i < self.num_outputs else ""
            out += _variant_tagged_field(0x6873, struct.pack("<I", i), value)

        # Field 62: visual rows marker
        out += _tagged_field(0x20CA, "2")

        if self.v4_blob:
            # Fields 63-78: a time & event drum's presets (sub-indexed 0x6891, 16
            # slots); a time drum keeps its presets in 0x6872 and leaves these blank.
            for i in range(16):
                value = self.presets[i] if time_event and i < self.num_steps else ""
                out += _variant_tagged_field(0x6891, struct.pack("<I", i), value)
            # Field 79: which presets are constants.  A paste keeps it as written
            # (absent = -1), and a time drum's func code series follows it.
            out += _tagged_field(0x428A, _constant_preset_mask(self.presets))
            # Field 80: the done bit of the accumulator's timer (TD101 -> T101)
            try:
                done_bit = _timer_done_bit(self.accumulator)
            except CsvError as exc:  # the accumulator was changed after it was built
                raise EncodeError(str(exc)) from exc
            out += _tagged_field(0x6068, done_bit)

        # Last field: terminator
        out += _tagged_field(0x0000, "")

        return bytes(out)


# ---------------------------------------------------------------------------
# Shared from_tags factory
# ---------------------------------------------------------------------------

_DRUM_TYPE_CODE = 0x271B


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Drum | None:
    """Construct a Drum from tag data (shared by both decoders)."""
    if class_name != "Drum" or type_code != _DRUM_TYPE_CODE:
        return None

    # Tag 0x2200 is the drum base: absent/0 time, 1 event, 2 time & event (CLICK v4,
    # events in 0x6872, presets in 0x6891).  Any other base falls through to
    # RawInstruction rather than misreading its step slots.
    base = tag_value(tags, 0x2200)
    if base not in (_BASE_TIME, _BASE_EVENT, _BASE_TIME_EVENT):
        return None

    variant_u16 = variant_u16_tags or {}
    variant_strings = variant_string_tags or {}

    current_step = tag_value(tags, 0x606E)
    completion_flag = tag_value(tags, 0x6070)

    outputs_by_idx = variant_strings.get(0x6873, {})
    events_by_idx = variant_strings.get(0x6872, {})
    bitmasks_by_idx = variant_u16.get(0x3A26, {})

    num_steps = tag_int(tags, 0x3203)
    num_outputs = tag_int(tags, 0x3204)

    if num_steps <= 0 or num_outputs <= 0 or not current_step or not completion_flag:
        return None

    if base == _BASE_TIME_EVENT:
        presets_by_idx = variant_strings.get(0x6891, {})
        outputs = tuple(outputs_by_idx.get(i, "") for i in range(num_outputs))
        unit = _DRUM_INDEX_TO_UNIT.get(tag_value(tags, 0x21F9))
        accumulator = tag_value(tags, 0x606F)
        if any(not value for value in outputs) or unit is None or not accumulator:
            return None
        return Drum(
            kind="time_event_drum",
            outputs=outputs,
            presets=tuple(presets_by_idx.get(i, "") for i in range(num_steps)),
            events=tuple(events_by_idx.get(i, "") for i in range(num_steps)),
            pattern=tuple(
                tuple((bitmasks_by_idx.get(s, 0) >> o) & 1 for o in range(num_outputs))
                for s in range(num_steps)
            ),
            current_step=current_step,
            completion_flag=completion_flag,
            accumulator=accumulator,
            unit=unit,
            jog_enabled=tag_flag(tags, 0x1201),
            jump_enabled=tag_flag(tags, 0x1202),
            jump_step=tag_value(tags, 0x6071),
        )

    outputs = tuple(outputs_by_idx.get(i, "") for i in range(num_outputs))
    step_values = tuple(events_by_idx.get(i, "") for i in range(num_steps))
    if any(not value for value in outputs) or any(not value for value in step_values):
        return None

    pattern = tuple(
        tuple(
            (bitmasks_by_idx.get(step_idx, 0) >> output_idx) & 1
            for output_idx in range(num_outputs)
        )
        for step_idx in range(num_steps)
    )

    if base == _BASE_EVENT:
        return Drum(
            kind="event_drum",
            outputs=outputs,
            events=step_values,
            pattern=pattern,
            current_step=current_step,
            completion_flag=completion_flag,
            jog_enabled=tag_flag(tags, 0x1201),
            jump_enabled=tag_flag(tags, 0x1202),
            jump_step=tag_value(tags, 0x6071),
        )

    unit = _DRUM_INDEX_TO_UNIT.get(tag_value(tags, 0x21F9), "Tms")
    accumulator = tag_value(tags, 0x606F)
    if not accumulator:
        return None
    return Drum(
        kind="time_drum",
        outputs=outputs,
        presets=step_values,
        pattern=pattern,
        current_step=current_step,
        completion_flag=completion_flag,
        accumulator=accumulator,
        unit=unit,
        jog_enabled=tag_flag(tags, 0x1201),
        jump_enabled=tag_flag(tags, 0x1202),
        jump_step=tag_value(tags, 0x6071),
    )


# ---------------------------------------------------------------------------
# CSV parser
# ---------------------------------------------------------------------------


def parse_af_call(call: AfCall) -> Drum:
    """Parse an AF AST call into a Drum.

    A keyword the call lacks or leaves blank (``unit``, a time & event drum's
    ``accumulator``) is a CSV error; a value the Drum refuses is its ``FieldError``."""
    outputs = _parse_simple_list(call.kwargs.get("outputs", "[]"))
    # A cell that is not 0 or 1 stays text, which the Drum refuses.
    pattern = cast("tuple[tuple[int, ...], ...]", _parse_pattern(call.kwargs.get("pattern", "[]")))
    current_step = call.kwargs.get("current_step", "")
    completion_flag = call.kwargs.get("completion_flag", "")

    if call.name == "event_drum":
        return Drum(
            kind="event_drum",
            outputs=outputs,
            events=_parse_simple_list(call.kwargs.get("events", "[]")),
            pattern=pattern,
            current_step=current_step,
            completion_flag=completion_flag,
        )

    unit = call.kwargs.get("unit", "")
    if not unit:
        raise CsvError(f"{call.name} needs unit=")
    accumulator = call.kwargs.get("accumulator", "")

    if call.name == "time_event_drum":
        presets = _parse_optional_list(call.kwargs.get("presets", "[]"))
        events = _parse_optional_list(call.kwargs.get("events", "[]"))
        if len(presets) != len(events):
            raise CsvError(
                f"time_event_drum needs one preset and one event per step "
                f"(None for unused): {len(presets)} presets, {len(events)} events"
            )
        if not accumulator:
            raise CsvError("time_event_drum needs accumulator=")
        return Drum(
            kind="time_event_drum",
            outputs=outputs,
            presets=presets,
            events=events,
            pattern=pattern,
            current_step=current_step,
            completion_flag=completion_flag,
            accumulator=accumulator,
            unit=unit,
        )

    return Drum(
        kind="time_drum",
        outputs=outputs,
        presets=_parse_simple_list(call.kwargs.get("presets", "[]")),
        pattern=pattern,
        current_step=current_step,
        completion_flag=completion_flag,
        accumulator=accumulator,
        unit=unit,
    )


SPEC = AfInstructionFamilySpec(
    family_name="drum",
    instruction_types=(Drum,),
    binary_class_names=("Drum",),
    from_tags=from_tags,
    csv_names=("event_drum", "time_drum", "time_event_drum"),
    parse_csv_call=parse_af_call,
    pin_names=(".reset", ".jump", ".jog"),
)
