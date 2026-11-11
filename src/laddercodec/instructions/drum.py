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
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal, cast

from ..binary_helpers import tag_flag, tag_int, tag_value
from ..model import FieldError, PinnedInstruction, check_address
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
# jog group is at block+4: code 8479 is the unused one (InstCtl_Drum.dll,
# v4_captures/sweep_drum.bin), which makes the Th block 8 codes long.
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
# shape as the time drum (v4_captures/drum.bin, sweep_drum.bin).
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

# ---------------------------------------------------------------------------
# Pattern encoding
# ---------------------------------------------------------------------------


def _pattern_to_bitmasks(pattern: list[list[int]], num_steps: int) -> list[str]:
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


def _parse_simple_list(val: str) -> list[str]:
    """Parse ``"[a,b,c]"`` into a list of strings."""
    val = val.strip()
    if not val.startswith("[") or not val.endswith("]"):
        raise ValueError(f"Expected list: {val!r}")
    inner = val[1:-1].strip()
    if not inner:
        return []
    return [x.strip() for x in inner.split(",")]


def _parse_pattern(val: str) -> list[list[int]]:
    """Parse ``"[[1,0],[0,1]]"`` into a nested integer list."""
    val = val.strip()
    if not val.startswith("[") or not val.endswith("]"):
        raise ValueError(f"Expected nested list: {val!r}")
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
    return [[int(x) for x in _parse_simple_list(row_str)] for row_str in rows if row_str]


def _parse_optional_list(val: str) -> list[str]:
    """Parse ``"[1000,None,DS1]"``; ``None`` (an unused step slot) becomes ``""``."""
    return ["" if x == "None" else x for x in _parse_simple_list(val)]


def _format_optional_list(values: list[str]) -> str:
    return ",".join(value or "None" for value in values)


#: A preset that names a register rather than a literal duration.
_REGISTER_RE = re.compile(r"[A-Z]+\d+")


def is_register_preset(preset: str) -> bool:
    """Whether a time drum preset names a register (``DS1``) rather than a duration."""
    return bool(_REGISTER_RE.fullmatch(preset))


def _constant_preset_mask(presets: list[str]) -> str:
    """Tag 0x428A: bit *n* stays set unless step *n*'s preset is a register.

    All 16 bits set (``-1``) when every preset is a constant or blank; CLICK v4
    writes it on OK, and picks a time drum's func code series from it.
    """
    mask = -1
    for i, preset in enumerate(presets):
        if is_register_preset(preset):
            mask &= ~(1 << i)
    return str(mask)


def _timer_done_bit(accumulator: str) -> str:
    """``TD101`` -> ``T101``: the timer a time & event drum's accumulator belongs to."""
    if not accumulator.startswith("TD"):
        raise ValueError(f"time_event_drum accumulator must be a TD address: {accumulator!r}")
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

    ``events_or_presets`` holds the events of an event drum and the presets of a
    time or time & event drum; ``events`` holds a time & event drum's events.
    A time & event step may leave either one blank (``""``, ``None`` in CSV).
    """

    drum_kind: Literal["event", "time", "time_event"]
    outputs: list[str] = field(default_factory=list)
    events_or_presets: list[str] = field(default_factory=list)
    pattern: list[list[int]] = field(default_factory=list)
    current_step: str = ""
    completion_flag: str = ""
    accumulator: str = ""  # TD address (time and time & event drums)
    unit: str = ""  # "Tms"/"Ts"/"Tm"/"Th"/"Td" (time and time & event drums)
    jog_enabled: bool = False
    jump_enabled: bool = False
    jump_target: str = ""  # DS address
    events: list[str] = field(default_factory=list)  # time & event drum only
    #: Rows of the reset, jump and jog inputs below the main row.  OR legs under
    #: a pin push the later pins down; an unused pin keeps its row.
    pin_rows: tuple[int, int, int] = (1, 2, 3)

    def __post_init__(self) -> None:
        kind = self.drum_kind
        if kind not in ("event", "time", "time_event"):
            raise FieldError(f"Drum.drum_kind: {kind!r} is not event, time or time_event")
        steps, outputs = self.num_steps, self.num_outputs
        if not 1 <= steps <= _MAX_DRUM_SIZE:
            raise FieldError(f"Drum steps: {steps} is outside 1-{_MAX_DRUM_SIZE}")
        if not 1 <= outputs <= _MAX_DRUM_SIZE:
            raise FieldError(f"Drum outputs: {outputs} is outside 1-{_MAX_DRUM_SIZE}")
        if len(self.pattern) != steps or any(len(row) != outputs for row in self.pattern):
            raise FieldError(
                f"Drum.pattern: needs {steps} steps of {outputs} cells each, got "
                f"{len(self.pattern)} steps of {sorted({len(row) for row in self.pattern})} cells"
            )
        for row in self.pattern:
            for cell in row:
                if type(cell) is not int or cell not in (0, 1):
                    raise FieldError(f"Drum.pattern: {cell!r} is not allowed, cells are 0 or 1")
        for i, output in enumerate(self.outputs):
            check_address(output, f"Drum.outputs[{i}]", banks={"Y", "C"})
        check_address(self.current_step, "Drum.current_step", banks={"DS"})
        check_address(self.completion_flag, "Drum.completion_flag", banks={"C"})
        if self.jump_enabled:
            check_address(self.jump_target, "Drum.jump_target", banks={"DS"})
        if kind == "event":
            if any(not event for event in self.events_or_presets):
                raise FieldError("Drum.events: every step needs an event (OBJ-021)")
            return
        if self.unit not in _DRUM_UNIT_TO_INDEX:
            raise FieldError(
                f"Drum.unit: {self.unit!r} is not one of {', '.join(_DRUM_UNIT_TO_INDEX)}"
            )
        check_address(self.accumulator, "Drum.accumulator", banks={"TD"})
        if kind == "time":
            if any(not preset for preset in self.events_or_presets):
                raise FieldError("Drum.presets: every step needs a duration (OBJ-022)")
            return
        if len(self.events) != steps:
            raise FieldError(
                f"Drum.events: needs one event per step ({steps}), got {len(self.events)}"
            )
        for i, (preset, event) in enumerate(zip(self.events_or_presets, self.events, strict=True)):
            if not preset and not event:
                raise FieldError(f"Drum step {i + 1}: needs a duration or an event (OBJ-1019)")

    @property
    def num_outputs(self) -> int:
        return len(self.outputs)

    @property
    def num_steps(self) -> int:
        return len(self.events_or_presets)

    @property
    def has_register_preset(self) -> bool:
        """A time or time & event drum reads a step's duration from a register."""
        return self.drum_kind != "event" and any(
            is_register_preset(preset) for preset in self.events_or_presets
        )

    @property
    def v4_blob(self) -> bool:
        """Written in v4's 82-field form: time & event, or a time drum with a register preset."""
        return self.drum_kind == "time_event" or self.has_register_preset

    def to_csv(self) -> str:
        outputs_str = ",".join(self.outputs)
        pattern_str = ",".join("[" + ",".join(str(v) for v in step) + "]" for step in self.pattern)
        if self.drum_kind == "event":
            events_str = ",".join(self.events_or_presets)
            return (
                f"event_drum(outputs=[{outputs_str}],"
                f"events=[{events_str}],"
                f"pattern=[{pattern_str}],"
                f"current_step={self.current_step},"
                f"completion_flag={self.completion_flag})"
            )
        if self.drum_kind == "time_event":
            return (
                f"time_event_drum(outputs=[{outputs_str}],"
                f"presets=[{_format_optional_list(self.events_or_presets)}],"
                f"events=[{_format_optional_list(self.events)}],"
                f"unit={self.unit},"
                f"pattern=[{pattern_str}],"
                f"current_step={self.current_step},"
                f"accumulator={self.accumulator},"
                f"completion_flag={self.completion_flag})"
            )
        presets_str = ",".join(self.events_or_presets)
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
            f".jump({self.jump_target})" if self.jump_enabled else None,
            ".jog()" if self.jog_enabled else None,
        )

    def with_pins(self, pins: dict[str, tuple[str, ...]], pin_rows: tuple[int, ...]) -> Drum:
        if ".reset" not in pins:
            raise ValueError("Drum requires a .reset() pin row")
        drum = replace(self, pin_rows=cast(tuple[int, int, int], pin_rows))
        if ".jump" in pins:
            target = pins[".jump"][0] if pins[".jump"] else ""
            drum = replace(drum, jump_enabled=True, jump_target=target)
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
        if self.drum_kind == "event":
            if self.jog_enabled:
                base, reset = _EVENT_FC_JOG[0], _EVENT_FC_JOG[1]
                jump = _EVENT_FC_JOG[2] if self.jump_enabled else 0
                jog = _EVENT_FC_JOG[3] if self.jump_enabled else _EVENT_FC_JOG[2]
            else:
                base, reset = _EVENT_FC_NO_JOG[0], _EVENT_FC_NO_JOG[1]
                jump = _EVENT_FC_NO_JOG[2] if self.jump_enabled else 0
                jog = 0
            return [str(base), str(reset), str(jump), str(jog)]
        if self.drum_kind == "time_event":
            block_base = _TIME_EVENT_FC_BASE.get(self.unit, 0)
        else:
            block_base = _TIME_FC_BASE.get(self.unit, 0)
            if block_base and self.has_register_preset:
                block_base += _REGISTER_PRESET_FC_OFFSET
        if not block_base:
            raise ValueError(f"Unsupported {self.drum_kind} drum unit: {self.unit!r}")
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
        time_event = self.drum_kind == "time_event"
        out += struct.pack("<I", 82 if self.v4_blob else 64)  # field count

        # Fields 0-3: func codes (sub-indexed 0x3A05)
        func_codes = self._compute_func_codes()
        for i, fc in enumerate(func_codes):
            out += _variant_tagged_field(0x3A05, struct.pack("<I", i), fc)

        # Field 4: drum base (0=time, 1=event, 2=time & event)
        base = {"time": _BASE_TIME, "event": _BASE_EVENT, "time_event": _BASE_TIME_EVENT}
        out += _tagged_field(0x2200, base[self.drum_kind])

        # Field 5: time unit index
        unit_idx = _DRUM_UNIT_TO_INDEX.get(self.unit, "0") if self.drum_kind != "event" else "0"
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
        out += _tagged_field(0x6071, self.jump_target)

        # Fields 14-29: events/presets (sub-indexed 0x6872, 16 slots); a time & event
        # drum keeps its events here and its presets in 0x6891.
        step_values = self.events if time_event else self.events_or_presets
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
                value = self.events_or_presets[i] if time_event and i < self.num_steps else ""
                out += _variant_tagged_field(0x6891, struct.pack("<I", i), value)
            # Field 79: which presets are constants.  A paste keeps it as written
            # (absent = -1), and a time drum's func code series follows it.
            out += _tagged_field(0x428A, _constant_preset_mask(self.events_or_presets))
            # Field 80: the done bit of the accumulator's timer (TD101 -> T101)
            out += _tagged_field(0x6068, _timer_done_bit(self.accumulator))

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
        outputs = [outputs_by_idx.get(i, "") for i in range(num_outputs)]
        unit = _DRUM_INDEX_TO_UNIT.get(tag_value(tags, 0x21F9))
        accumulator = tag_value(tags, 0x606F)
        if any(not value for value in outputs) or unit is None or not accumulator:
            return None
        return Drum(
            drum_kind="time_event",
            outputs=outputs,
            events_or_presets=[presets_by_idx.get(i, "") for i in range(num_steps)],
            events=[events_by_idx.get(i, "") for i in range(num_steps)],
            pattern=[
                [(bitmasks_by_idx.get(s, 0) >> o) & 1 for o in range(num_outputs)]
                for s in range(num_steps)
            ],
            current_step=current_step,
            completion_flag=completion_flag,
            accumulator=accumulator,
            unit=unit,
            jog_enabled=tag_flag(tags, 0x1201),
            jump_enabled=tag_flag(tags, 0x1202),
            jump_target=tag_value(tags, 0x6071),
        )

    outputs = [outputs_by_idx.get(i, "") for i in range(num_outputs)]
    events_or_presets = [events_by_idx.get(i, "") for i in range(num_steps)]
    if any(not value for value in outputs) or any(not value for value in events_or_presets):
        return None

    pattern = [
        [(bitmasks_by_idx.get(step_idx, 0) >> output_idx) & 1 for output_idx in range(num_outputs)]
        for step_idx in range(num_steps)
    ]

    if base == _BASE_EVENT:
        return Drum(
            drum_kind="event",
            outputs=outputs,
            events_or_presets=events_or_presets,
            pattern=pattern,
            current_step=current_step,
            completion_flag=completion_flag,
            jog_enabled=tag_flag(tags, 0x1201),
            jump_enabled=tag_flag(tags, 0x1202),
            jump_target=tag_value(tags, 0x6071),
        )

    unit = _DRUM_INDEX_TO_UNIT.get(tag_value(tags, 0x21F9), "Tms")
    accumulator = tag_value(tags, 0x606F)
    if not accumulator:
        return None
    return Drum(
        drum_kind="time",
        outputs=outputs,
        events_or_presets=events_or_presets,
        pattern=pattern,
        current_step=current_step,
        completion_flag=completion_flag,
        accumulator=accumulator,
        unit=unit,
        jog_enabled=tag_flag(tags, 0x1201),
        jump_enabled=tag_flag(tags, 0x1202),
        jump_target=tag_value(tags, 0x6071),
    )


# ---------------------------------------------------------------------------
# CSV parser
# ---------------------------------------------------------------------------


def parse_af_call(call: AfCall) -> Drum:
    """Parse an AF AST call into a Drum."""
    is_event = call.name == "event_drum"
    outputs = _parse_simple_list(call.kwargs.get("outputs", "[]"))
    pattern = _parse_pattern(call.kwargs.get("pattern", "[]"))
    current_step = call.kwargs.get("current_step", "")
    completion_flag = call.kwargs.get("completion_flag", "")

    if call.name == "time_event_drum":
        presets = _parse_optional_list(call.kwargs.get("presets", "[]"))
        events = _parse_optional_list(call.kwargs.get("events", "[]"))
        if len(presets) != len(events):
            raise ValueError(
                f"time_event_drum needs one preset and one event per step "
                f"(None for unused): {len(presets)} presets, {len(events)} events"
            )
        unit = call.kwargs.get("unit", "")
        if unit not in _TIME_EVENT_FC_BASE:
            raise ValueError(f"Unsupported time_event_drum unit: {unit!r}")
        accumulator = call.kwargs.get("accumulator", "")
        _timer_done_bit(accumulator)
        return Drum(
            drum_kind="time_event",
            outputs=outputs,
            events_or_presets=presets,
            events=events,
            pattern=pattern,
            current_step=current_step,
            completion_flag=completion_flag,
            accumulator=accumulator,
            unit=unit,
        )

    if is_event:
        events_or_presets = _parse_simple_list(call.kwargs.get("events", "[]"))
        accumulator = ""
        unit = ""
    else:
        events_or_presets = _parse_simple_list(call.kwargs.get("presets", "[]"))
        accumulator = call.kwargs.get("accumulator", "")
        unit = call.kwargs.get("unit", "")
        if unit not in _TIME_FC_BASE:
            raise ValueError(f"Unsupported time drum unit: {unit!r}")

    return Drum(
        drum_kind="event" if is_event else "time",
        outputs=outputs,
        events_or_presets=events_or_presets,
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
    min_csv_rows=4,
)
