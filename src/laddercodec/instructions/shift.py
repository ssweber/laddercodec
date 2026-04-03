"""SR — shift register instruction (type marker 0x2720).

Binary class name: ``"SR"``.

CSV form:

    shift(C99..C106)

Pin rows:
    ``.clock()`` and ``.reset()`` are handled by the CSV converter/writer.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..model import AfInstruction, InstructionType, _validate_operand
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SHIFT_FUNC_CODES = ("8448", "8449", "8450")
_SHIFT_SUB_MARKERS = (b"\x00\x00\x00\x00", b"\x01\x00\x00\x00", b"\x02\x00\x00\x00")

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Shift(AfInstruction):
    """A shift register instruction."""

    start_bit: str
    end_bit: str

    @classmethod
    def from_csv_token(cls, token: str) -> Shift:
        """Parse ``shift(C99..C106)``."""
        token = token.strip()
        m = re.fullmatch(r"shift\((.+)\)", token)
        if not m:
            raise ValueError(f"Cannot parse shift: {token!r}")

        inner = m.group(1).strip()
        if ".." not in inner:
            raise ValueError(f"shift expects a range arg (start..end): {token!r}")
        parts = [p.strip() for p in inner.split("..")]
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"Cannot parse shift range: {token!r}")

        return cls(
            start_bit=_validate_operand(parts[0]),
            end_bit=_validate_operand(parts[1]),
        )

    def to_csv(self) -> str:
        return f"shift({self.start_bit}..{self.end_bit})"

    def cell_params(self) -> dict:
        return {"visual_rows": 3}

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this shift register."""
        from ..binary_helpers import _tagged_field, _utf16le_null, _variant_tagged_field

        type_marker = 0x2700 | InstructionType.SHIFT

        out = bytearray()
        out += _utf16le_null("SR")
        out += struct.pack("<I", type_marker)
        out += b"\x03\x00"  # part count
        out += b"\x01\x02"  # extra part bytes
        out += struct.pack("<I", 6)  # field count
        out += _tagged_field(0x6066, self.start_bit)
        out += _tagged_field(0x6067, self.end_bit)
        for marker, func_code in zip(_SHIFT_SUB_MARKERS, _SHIFT_FUNC_CODES, strict=True):
            out += _variant_tagged_field(0x3A05, marker, func_code)
        out += _tagged_field(0x0000, "")
        return bytes(out)


# ---------------------------------------------------------------------------
# Shared from_tags factory
# ---------------------------------------------------------------------------

_SHIFT_TYPE_CODE = 0x2720


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    tag_byte_lens: dict[int, int] | None = None,
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Shift | None:
    """Construct a Shift from tag data (shared by both decoders)."""
    if class_name != "SR" or type_code != _SHIFT_TYPE_CODE:
        return None
    start_bit = tags.get(0x6066, "")
    end_bit = tags.get(0x6067, "")
    if not start_bit or not end_bit:
        return None
    return Shift(start_bit=start_bit, end_bit=end_bit)


# ---------------------------------------------------------------------------
# CSV parser
# ---------------------------------------------------------------------------


def parse_af_call(call: AfCall) -> Shift:
    """Parse an AF AST call into a Shift."""
    return Shift.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="shift",
    instruction_types=(Shift,),
    binary_class_names=("SR",),
    from_tags=from_tags,
    csv_names=("shift",),
    parse_csv_call=parse_af_call,
    pin_names=(".clock", ".reset"),
    min_csv_rows=3,
)
