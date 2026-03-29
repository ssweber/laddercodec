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


# Module-level wrapper for backward compatibility.
def build_blob(shift: Shift) -> bytes:
    """Build the instruction data blob for a shift register."""
    return shift.build_blob()


# ---------------------------------------------------------------------------
# Blob parser
# ---------------------------------------------------------------------------


def parse_blob(raw: bytes) -> Shift | None:
    """Try to parse a Shift from an instruction blob."""
    from ..binary_helpers import _read_utf16le

    class_name, pos = _read_utf16le(raw, 0)
    if class_name != "SR":
        return None
    if pos + 10 > len(raw):
        return None

    type_marker = int.from_bytes(raw[pos : pos + 4], "little")
    if type_marker != (0x2700 | InstructionType.SHIFT):
        return None
    pos += 4

    part_count = int.from_bytes(raw[pos : pos + 2], "little")
    pos += 2
    if part_count != 3:
        return None

    extra = part_count - 1
    if pos + extra + 4 > len(raw):
        return None
    if raw[pos : pos + extra] != b"\x01\x02":
        return None
    pos += extra

    field_count = int.from_bytes(raw[pos : pos + 4], "little")
    pos += 4
    if field_count < 6:
        return None

    parsed_fields: list[tuple[int, bytes, str]] = []
    for _ in range(field_count):
        if pos + 6 > len(raw):
            return None
        tag = int.from_bytes(raw[pos : pos + 2], "little")
        pos += 2
        marker = raw[pos : pos + 4]
        pos += 4
        value, pos = _read_utf16le(raw, pos)
        parsed_fields.append((tag, marker, value))

    if len(parsed_fields) < 6:
        return None

    if parsed_fields[0][0] != 0x6066 or parsed_fields[1][0] != 0x6067:
        return None
    for idx, marker in enumerate(_SHIFT_SUB_MARKERS):
        field = parsed_fields[2 + idx]
        if field[0] != 0x3A05 or field[1] != marker or field[2] != _SHIFT_FUNC_CODES[idx]:
            return None
    if parsed_fields[5][0] != 0x0000:
        return None

    return Shift(start_bit=parsed_fields[0][2], end_bit=parsed_fields[1][2])


def parse_af_call(call: AfCall) -> Shift:
    """Parse an AF AST call into a Shift."""
    return Shift.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="shift",
    instruction_types=(Shift,),
    binary_class_names=("SR",),
    parse_blob=parse_blob,
    csv_names=("shift",),
    parse_csv_call=parse_af_call,
    pin_names=(".clock", ".reset"),
    min_csv_rows=3,
)
