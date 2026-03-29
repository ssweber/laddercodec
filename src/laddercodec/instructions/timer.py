"""Tmr — timer instructions (type marker 0x2718).

Binary class name: ``"Tmr"``.
Timer types: on_delay, off_delay (retentive flag set separately).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from ..model import AfInstruction
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

#: Timer time unit index -> CSV name (matches pyrung TimeUnit.name).
TIMER_UNITS: dict[str, str] = {
    "0": "Tms",
    "1": "Ts",
    "2": "Tm",
    "3": "Th",
    "4": "Td",
}

#: Timer unit name → unit index string.
TIMER_UNIT_TO_INDEX: dict[str, str] = {v: k for k, v in TIMER_UNITS.items()}

# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

_TIMER_STD_TAGS = (0x6068, 0x606A, 0x6069, 0x21F9, 0x21FA, 0x21FB)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Timer(AfInstruction):
    """A timer instruction (on_delay / off_delay).

    Occupies the AF column.  The binary class name is ``Tmr``
    (type marker 0x2718).  Each timer rung adds an extra grid row
    for the timer's visual height.
    """

    timer_type: Literal["on_delay", "off_delay"]
    done_bit: str  # e.g. "T1"
    current: str  # accumulator register, e.g. "TD1"
    setpoint: str  # preset value or operand, e.g. "1" or "DS1"
    unit: str  # "Tms", "Ts", "Tm", "Th", "Td"
    retained: bool = False  # True = retentive (RTON)

    @classmethod
    def from_csv_token(cls, token: str) -> Timer:
        """Parse v1 timer: ``on_delay(T1,TD1,preset=1000,unit=Tms)``.

        Positional: done_bit, current.  Kwargs: preset, unit.
        Retained is never in the CSV — it's set by ``.reset()`` pin presence.
        """
        token = token.strip()
        m = re.fullmatch(r"(on_delay|off_delay)\((.+)\)", token)
        if not m:
            raise ValueError(f"Cannot parse timer: {token!r}")
        timer_type = cast(Literal["on_delay", "off_delay"], m.group(1))
        args: list[str] = []
        kwargs: dict[str, str] = {}
        for seg in (a.strip() for a in m.group(2).split(",")):
            if "=" in seg:
                k, v = seg.split("=", 1)
                kwargs[k.strip()] = v.strip()
            else:
                args.append(seg)
        if len(args) != 2:
            raise ValueError(
                f"{timer_type} expects 2 positional args (done, acc), got {len(args)}: {token!r}"
            )
        done_bit, current = args
        setpoint = kwargs.get("preset", "")
        unit = kwargs.get("unit", "")
        if not setpoint or not unit:
            raise ValueError(f"{timer_type} missing preset or unit kwargs: {token!r}")
        if unit not in TIMER_UNIT_TO_INDEX:
            raise ValueError(f"Unknown timer unit: {unit!r}")
        return cls(
            timer_type=timer_type,
            done_bit=done_bit,
            current=current,
            setpoint=setpoint,
            unit=unit,
            retained=False,
        )

    @property
    def unit_idx(self) -> str:
        return TIMER_UNIT_TO_INDEX[self.unit]

    @property
    def enable_func_code(self) -> str:
        """Compute the enable func_code: base + offset."""
        base = 8717 + int(self.unit_idx) * 6
        if self.timer_type == "on_delay":
            return str(base + (2 if self.retained else 0))
        return str(base + 1)  # off_delay

    @property
    def reset_func_code(self) -> str:
        """Compute the reset func_code (retentive only; "0" otherwise)."""
        if not self.retained:
            return "0"
        base = 8717 + int(self.unit_idx) * 6
        return str(base + 3)

    def to_csv(self) -> str:
        return f"{self.timer_type}({self.done_bit},{self.current},preset={self.setpoint},unit={self.unit})"

    def cell_params(self) -> dict:
        """Return ClickCell kwargs intrinsic to this instruction."""
        return {"visual_rows": 2}

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this timer cell."""
        from ..binary_helpers import _tagged_field, _utf16le_null, _variant_tagged_field
        from ..model import InstructionType

        type_marker = 0x2700 | InstructionType.TIMER

        out = bytearray()
        out += _utf16le_null("Tmr")
        out += struct.pack("<I", type_marker)
        out += b"\x02\x00"  # part count (differs from contact/coil's 01 00)
        out += b"\x01"  # sub-marker
        out += struct.pack("<I", 9)  # field count

        # Fields 0–5: standard tagged fields.
        std_values = [
            self.done_bit,
            self.setpoint,
            self.current,
            self.unit_idx,
            "0" if self.timer_type == "on_delay" else "1",
            "1" if self.retained else "0",
        ]
        for tag, value in zip(_TIMER_STD_TAGS, std_values, strict=True):
            out += _tagged_field(tag, value)

        # Fields 6–7: variant format [2B tag][4B sub-marker][UTF-16LE value].
        out += _variant_tagged_field(0x3A05, b"\x00\x00\x00\x00", self.enable_func_code)
        out += _variant_tagged_field(0x3A05, b"\x01\x00\x00\x00", self.reset_func_code)

        # Field 8: empty sentinel field.
        out += _tagged_field(0x0000, "")

        return bytes(out)


# Module-level wrapper for backward compatibility.
def build_blob(timer: Timer) -> bytes:
    """Build the instruction data blob for a timer cell."""
    return timer.build_blob()


# ---------------------------------------------------------------------------
# Shared from_tags factory
# ---------------------------------------------------------------------------

_TIMER_TYPE_CODE = 0x2718


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    tag_byte_lens: dict[int, int] | None = None,
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Timer | None:
    """Construct a Timer from tag data (shared by both decoders)."""
    if class_name != "Tmr" or type_code != _TIMER_TYPE_CODE:
        return None
    done_bit = tags.get(0x6068, "")
    setpoint = tags.get(0x606A, "")
    current = tags.get(0x6069, "")
    unit_idx = tags.get(0x21F9, "0")
    unit = TIMER_UNITS.get(unit_idx)
    if not done_bit or not current or not setpoint or unit is None:
        return None
    # SCR: 0x21FA absent = on_delay, present = off_delay.
    # Clipboard: byte tag value 0 = on_delay, 1 = off_delay.
    timer_type = "off_delay" if (tag_byte_lens or {}).get(0x21FA, 0) != 0 else "on_delay"
    retained = (tag_byte_lens or {}).get(0x21FB, 0) != 0
    return Timer(
        timer_type=timer_type,
        done_bit=done_bit,
        current=current,
        setpoint=setpoint,
        unit=unit,
        retained=retained,
    )


# ---------------------------------------------------------------------------
# Blob parser
# ---------------------------------------------------------------------------


def parse_blob(raw: bytes) -> Timer | None:
    """Try to parse a Timer from an instruction blob."""
    from .raw import _decompose_blob, _fields_to_tag_dicts

    try:
        class_name, type_marker, _part_count, _extra, fields = _decompose_blob(raw)
    except (ValueError, struct.error):
        return None
    tags, tag_byte_lens, variant_u16, variant_string = _fields_to_tag_dicts(fields)
    return from_tags(class_name, type_marker, tags, tag_byte_lens, variant_u16, variant_string)


def parse_af_call(call: AfCall) -> Timer:
    """Parse an AF AST call into a Timer."""
    return Timer.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="timer",
    instruction_types=(Timer,),
    binary_class_names=("Tmr",),
    parse_blob=parse_blob,
    from_tags=from_tags,
    csv_names=("on_delay", "off_delay"),
    parse_csv_call=parse_af_call,
    pin_names=(".reset",),
    min_csv_rows=2,
)
