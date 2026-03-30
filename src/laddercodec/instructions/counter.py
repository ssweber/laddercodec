"""Cnt — counter instructions (type marker 0x2719).

Binary class name: ``"Cnt"``.

Supported native variants (verified from Click captures):

- ``count_up(...)+.reset()``            -> mode 0
- ``count_up(...)+.down()+.reset()``    -> mode 2
- ``count_down(...)+.reset()``          -> mode 1
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from ..model import AfInstruction, InstructionType, _validate_operand
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

# ---------------------------------------------------------------------------
# Variant encodings
# ---------------------------------------------------------------------------

# (counter_type, down_enabled, reset_enabled) -> (mode, up_fc, down_fc, reset_fc)
_VARIANT_TO_ENCODING: dict[tuple[str, bool, bool], tuple[str, str, str, str]] = {
    ("count_up", False, True): ("0", "8710", "0", "8711"),
    ("count_up", True, True): ("2", "8713", "8714", "8715"),
    ("count_down", False, True): ("1", "0", "8747", "8748"),
}

# Reverse: (mode, up_fc, down_fc, reset_fc) -> (counter_type, down_enabled, reset_enabled)
_ENCODING_TO_VARIANT: dict[tuple[str, str, str, str], tuple[str, bool, bool]] = {
    v: k for k, v in _VARIANT_TO_ENCODING.items()
}

# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

_COUNTER_STD_TAGS = (0x606B, 0x606A, 0x606C, 0x606D, 0x21FC)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Counter(AfInstruction):
    """A counter instruction (count_up / count_down)."""

    counter_type: Literal["count_up", "count_down"]
    done_bit: str
    current: str
    preset: str
    down_enabled: bool = False
    reset_enabled: bool = False

    @classmethod
    def from_csv_token(cls, token: str) -> Counter:
        """Parse v1 counter: ``count_up(CT1,CTD1,preset=100)``."""
        token = token.strip()
        m = re.fullmatch(r"(count_up|count_down)\((.+)\)", token)
        if not m:
            raise ValueError(f"Cannot parse counter: {token!r}")

        counter_type = cast(Literal["count_up", "count_down"], m.group(1))
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
                f"{counter_type} expects 2 positional args (done, current), got {len(args)}: {token!r}"
            )

        preset = kwargs.get("preset", "")
        if not preset:
            raise ValueError(f"{counter_type} missing preset kwarg: {token!r}")

        return cls(
            counter_type=counter_type,
            done_bit=_validate_operand(args[0]),
            current=_validate_operand(args[1]),
            preset=preset,
        )

    @property
    def mode_and_func_codes(self) -> tuple[str, str, str, str]:
        key = (self.counter_type, self.down_enabled, self.reset_enabled)
        result = _VARIANT_TO_ENCODING.get(key)
        if result is None:
            raise ValueError(
                "Unsupported counter variant: "
                f"{self.counter_type}(down={self.down_enabled}, reset={self.reset_enabled})"
            )
        return result

    def to_csv(self) -> str:
        return f"{self.counter_type}({self.done_bit},{self.current},preset={self.preset})"

    def cell_params(self) -> dict:
        return {
            "visual_rows": 3,
            # Native count_down AF row 0 stores +0x1D=0 (while count_up uses 1).
            "wire_right": 0 if self.counter_type == "count_down" else 1,
        }

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this counter cell."""
        from ..binary_helpers import _tagged_field, _utf16le_null, _variant_tagged_field

        mode, up_fc, down_fc, reset_fc = self.mode_and_func_codes

        type_marker = 0x2700 | InstructionType.COUNTER

        out = bytearray()
        out += _utf16le_null("Cnt")
        out += struct.pack("<I", type_marker)
        out += b"\x03\x00"  # part count
        out += b"\x01\x02"  # extra part bytes
        out += struct.pack("<I", 9)  # field count

        std_values = [
            self.done_bit,
            self.preset,
            self.current,
            self.done_bit,
            mode,
        ]
        for tag, value in zip(_COUNTER_STD_TAGS, std_values, strict=True):
            out += _tagged_field(tag, value)

        out += _variant_tagged_field(0x3A05, b"\x00\x00\x00\x00", up_fc)
        out += _variant_tagged_field(0x3A05, b"\x01\x00\x00\x00", down_fc)
        out += _variant_tagged_field(0x3A05, b"\x02\x00\x00\x00", reset_fc)
        out += _tagged_field(0x0000, "")

        return bytes(out)


# Module-level wrapper for backward compatibility.
def build_blob(counter: Counter) -> bytes:
    """Build the instruction data blob for a counter cell."""
    return counter.build_blob()


# ---------------------------------------------------------------------------
# Shared from_tags factory
# ---------------------------------------------------------------------------

_COUNTER_TYPE_CODE = 0x2719

# Mode byte value → (counter_type, down_enabled, reset_enabled).
_MODE_TO_VARIANT: dict[int, tuple[Literal["count_up", "count_down"], bool, bool]] = {
    0: ("count_up", False, True),
    1: ("count_down", False, True),
    2: ("count_up", True, True),
}


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    tag_byte_lens: dict[int, int] | None = None,
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Counter | None:
    """Construct a Counter from tag data (shared by both decoders)."""
    if class_name != "Cnt" or type_code != _COUNTER_TYPE_CODE:
        return None
    done_bit = tags.get(0x606B, "")
    preset = tags.get(0x606A, "")
    current = tags.get(0x606C, "")
    mode = (tag_byte_lens or {}).get(0x21FC, 0)
    variant = _MODE_TO_VARIANT.get(mode)
    if not all([done_bit, preset, current]) or variant is None:
        return None
    counter_type, down_enabled, reset_enabled = variant
    return Counter(
        counter_type=counter_type,
        done_bit=done_bit,
        current=current,
        preset=preset,
        down_enabled=down_enabled,
        reset_enabled=reset_enabled,
    )


def parse_af_call(call: AfCall) -> Counter:
    """Parse an AF AST call into a Counter."""
    return Counter.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="counter",
    instruction_types=(Counter,),
    binary_class_names=("Cnt",),
    from_tags=from_tags,
    csv_names=("count_up", "count_down"),
    parse_csv_call=parse_af_call,
    pin_names=(".down", ".reset"),
    min_csv_rows=3,
)
