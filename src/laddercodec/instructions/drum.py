"""Drum — event drum and time drum instructions (type marker 0x271B).

Binary class name: ``"Drum"``.
Drum types: event_drum (event-driven), time_drum (time-driven).
Both share the same 64-field blob structure.
4 grid rows: main + reset (row 1) + jump (row 2) + jog (row 3).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from ..model import AfInstruction
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

# Time drum: unit → (base, reset)
_TIME_FC: dict[str, tuple[int, int]] = {
    "Tms": (8455, 8456),
    "Td": (8484, 8485),
}

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


def _bitmasks_to_pattern(
    bitmask_strs: list[str], num_steps: int, num_outputs: int
) -> list[list[int]]:
    """Convert signed-int16 bitmask strings to pattern matrix."""
    result: list[list[int]] = []
    for step_idx in range(num_steps):
        bm = int(bitmask_strs[step_idx])
        if bm < 0:
            bm += 65536
        row = [(bm >> i) & 1 for i in range(num_outputs)]
        result.append(row)
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


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Drum(AfInstruction):
    """A drum sequencer instruction (event_drum / time_drum).

    Occupies the AF column.  The binary class name is ``Drum``
    (type marker 0x271B).  Each drum rung takes 4 grid rows:
    row 0 = main, row 1 = reset, row 2 = jump, row 3 = jog.
    """

    drum_kind: Literal["event", "time"]
    outputs: list[str] = field(default_factory=list)
    events_or_presets: list[str] = field(default_factory=list)
    pattern: list[list[int]] = field(default_factory=list)
    current_step: str = ""
    completion_flag: str = ""
    accumulator: str = ""  # TD address (time drum only)
    unit: str = ""  # "Tms" or "Td" (time drum only)
    jog_enabled: bool = False
    jump_enabled: bool = False
    jump_target: str = ""  # DS address

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
        return {"visual_rows": 4}

    def _compute_func_codes(self) -> list[str]:
        """Return the 4 func-code slot values [base, reset, jump, jog]."""
        if self.drum_kind == "event":
            if self.jog_enabled:
                base, reset = _EVENT_FC_JOG[0], _EVENT_FC_JOG[1]
                jump = _EVENT_FC_JOG[2] if self.jump_enabled else 0
                jog = _EVENT_FC_JOG[3]
            else:
                base, reset = _EVENT_FC_NO_JOG[0], _EVENT_FC_NO_JOG[1]
                jump = _EVENT_FC_NO_JOG[2] if self.jump_enabled else 0
                jog = 0
            return [str(base), str(reset), str(jump), str(jog)]
        fc = _TIME_FC.get(self.unit)
        if fc is None:
            raise ValueError(f"Unsupported time drum unit: {self.unit!r}")
        return [str(fc[0]), str(fc[1]), "0", "0"]

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this drum cell."""
        from ..binary_helpers import _tagged_field, _utf16le_null, _variant_tagged_field
        from ..model import InstructionType

        type_marker = 0x2700 | InstructionType.DRUM

        out = bytearray()
        out += _utf16le_null("Drum")
        out += struct.pack("<I", type_marker)
        out += struct.pack("<H", 4)  # part count
        out += b"\x01\x02\x03"  # extra bytes (part_count - 1 = 3)
        out += struct.pack("<I", 64)  # field count

        # Fields 0-3: func codes (sub-indexed 0x3A05)
        func_codes = self._compute_func_codes()
        for i, fc in enumerate(func_codes):
            out += _variant_tagged_field(0x3A05, struct.pack("<I", i), fc)

        # Field 4: is_event (1=event, 0=time)
        out += _tagged_field(0x2200, "1" if self.drum_kind == "event" else "0")

        # Field 5: time unit index
        unit_idx = _DRUM_UNIT_TO_INDEX.get(self.unit, "0") if self.drum_kind == "time" else "0"
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

        # Fields 14-29: events/presets (sub-indexed 0x6872, 16 slots)
        for i in range(16):
            value = self.events_or_presets[i] if i < self.num_steps else ""
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

        # Field 63: terminator
        out += _tagged_field(0x0000, "")

        return bytes(out)


# Module-level wrapper for backward compatibility.
def build_blob(drum: Drum) -> bytes:
    """Build the instruction data blob for a drum cell."""
    return drum.build_blob()


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

    lens = tag_byte_lens or {}
    variant_u16 = variant_u16_tags or {}
    variant_strings = variant_string_tags or {}

    num_steps = int(tags.get(0x3203, "0") or "0")
    num_outputs = int(tags.get(0x3204, "0") or "0")
    current_step = tags.get(0x606E, "")
    completion_flag = tags.get(0x6070, "")
    if num_steps <= 0 or num_outputs <= 0 or not current_step or not completion_flag:
        return None

    outputs_by_idx = variant_strings.get(0x6873, {})
    events_by_idx = variant_strings.get(0x6872, {})
    bitmasks_by_idx = variant_u16.get(0x3A26, {})

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
    csv_names=("event_drum", "time_drum"),
    parse_csv_call=parse_af_call,
    pin_names=(".reset", ".jump", ".jog"),
    min_csv_rows=4,
)
