"""Drum — event, time, and time & event drum instructions (type marker 0x271B).

Binary class name: ``"Drum"``.
Drum types: event_drum (event-driven), time_drum (time-driven), and CLICK v4's
time_event_drum (each step ends on its preset time and/or its event).
Event and time drums use the 64-field v3 blob; time & event drums use v4's
82-field blob (16 preset slots ``0x6891``, ``0x428A``, timer done bit ``0x6068``).
4 grid rows: main + reset (row 1) + jump (row 2) + jog (row 3), more when OR
legs under a pin push the later pins down (``pin_rows``, the blob's part bytes).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal, cast

from ..model import PinnedInstruction
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

# Time drum: unit → (base, reset) func codes for the no-jog group.
# Captured from native Click (timer_and_drums.bin, rungs 5-10).  reset = base+1;
# blocks stride by 7 except Td (+8; code 8483 is skipped/reserved).
_TIME_FC: dict[str, tuple[int, int]] = {
    "Tms": (8455, 8456),
    "Ts": (8462, 8463),
    "Tm": (8469, 8470),
    "Th": (8476, 8477),
    "Td": (8484, 8485),
}

# Time & event drum (CLICK v4): unit → no-jog base func code; same 7-code block
# shape and Td skip as the time drum (v4_captures/drum.bin).
_TIME_EVENT_FC_BASE: dict[str, int] = {
    "Tms": 10503,
    "Ts": 10510,
    "Tm": 10517,
    "Th": 10524,
    "Td": 10532,
}

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

    @property
    def num_outputs(self) -> int:
        return len(self.outputs)

    @property
    def num_steps(self) -> int:
        return len(self.events_or_presets)

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
            block_base = _TIME_FC.get(self.unit, (0, 0))[0]
        if not block_base:
            raise ValueError(f"Unsupported {self.drum_kind} drum unit: {self.unit!r}")
        # Each time unit reserves a 7-code block, same shape as event drums:
        # no-jog group (base, reset, jump) then jog group (base, reset, jump, jog).
        if self.jog_enabled:
            base, reset = block_base + 3, block_base + 4
            jump = block_base + 5 if self.jump_enabled else 0
            jog = block_base + 6 if self.jump_enabled else block_base + 5
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
        out += struct.pack("<I", 82 if time_event else 64)  # field count

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

        if time_event:
            # Fields 63-78: presets (sub-indexed 0x6891, 16 slots)
            for i in range(16):
                value = self.events_or_presets[i] if i < self.num_steps else ""
                out += _variant_tagged_field(0x6891, struct.pack("<I", i), value)
            # Field 79: unexplained; Click writes -1 (once -2) and itself fills in -1
            # for a pasted drum that lacks it.
            out += _tagged_field(0x428A, "-1")
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
    tag_byte_lens: dict[int, int] | None = None,
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Drum | None:
    """Construct a Drum from tag data (shared by both decoders)."""
    if class_name != "Drum" or type_code != _DRUM_TYPE_CODE:
        return None

    # Tag 0x2200 is the drum base: absent/0 time, 1 event, 2 time & event (CLICK v4,
    # events in 0x6872, presets in 0x6891).  Any other base falls through to
    # RawInstruction rather than misreading its step slots.
    base = tags.get(0x2200, "")
    if base not in ("", _BASE_TIME, _BASE_EVENT, _BASE_TIME_EVENT):
        return None

    lens = tag_byte_lens or {}
    variant_u16 = variant_u16_tags or {}
    variant_strings = variant_string_tags or {}

    current_step = tags.get(0x606E, "")
    completion_flag = tags.get(0x6070, "")

    outputs_by_idx = variant_strings.get(0x6873, {})
    events_by_idx = variant_strings.get(0x6872, {})
    bitmasks_by_idx = variant_u16.get(0x3A26, {})

    # The clipboard blob always carries explicit step/output counts, but Click's
    # SCR (Scr*.tmp) format omits 0x3203/0x3204 when the count is 1.  Fall back to
    # the highest populated variant slot so single-step drums still decode.
    num_steps = int(tags.get(0x3203, "0") or "0")
    if num_steps <= 0 and events_by_idx:
        num_steps = max(events_by_idx) + 1
    num_outputs = int(tags.get(0x3204, "0") or "0")
    if num_outputs <= 0 and outputs_by_idx:
        num_outputs = max(outputs_by_idx) + 1

    if num_steps <= 0 or num_outputs <= 0 or not current_step or not completion_flag:
        return None

    if base == _BASE_TIME_EVENT:
        presets_by_idx = variant_strings.get(0x6891, {})
        outputs = [outputs_by_idx.get(i, "") for i in range(num_outputs)]
        unit = _DRUM_INDEX_TO_UNIT.get(tags.get(0x21F9, "0"))
        accumulator = tags.get(0x606F, "")
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
            jog_enabled=0x1201 in tags,
            jump_enabled=0x1202 in tags,
            jump_target=tags.get(0x6071, ""),
        )

    outputs = [outputs_by_idx.get(i, "") for i in range(num_outputs)]
    events_or_presets = [events_by_idx.get(i, "") for i in range(num_steps)]
    if any(not value for value in outputs) or any(not value for value in events_or_presets):
        return None

    pattern = [
        [(bitmasks_by_idx.get(step_idx, 0) >> output_idx) & 1 for output_idx in range(num_outputs)]
        for step_idx in range(num_steps)
    ]

    is_event = lens.get(0x2200, 0) == 1
    # Also handle string-valued tag from clipboard path.
    if tags.get(0x2200) == "1":
        is_event = True

    if is_event:
        return Drum(
            drum_kind="event",
            outputs=outputs,
            events_or_presets=events_or_presets,
            pattern=pattern,
            current_step=current_step,
            completion_flag=completion_flag,
            jog_enabled=0x1201 in tags,
            jump_enabled=0x1202 in tags,
            jump_target=tags.get(0x6071, ""),
        )

    unit = _DRUM_INDEX_TO_UNIT.get(tags.get(0x21F9, "0"), "Tms")
    accumulator = tags.get(0x606F, "")
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
        jog_enabled=0x1201 in tags,
        jump_enabled=0x1202 in tags,
        jump_target=tags.get(0x6071, ""),
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
        if unit not in _TIME_FC:
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
