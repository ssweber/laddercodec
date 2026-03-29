"""Call — subroutine call instruction (type marker 0x2723).

Binary class name: ``"Call"``.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..model import AfInstruction
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

CALL_TYPE_MARKER = 0x2723
CALL_FUNC_CODE = "9221"
_CALL_TAGS = (0x3219, 0x6208, 0x3218, 0x0000)


@dataclass
class Call(AfInstruction):
    """Subroutine call instruction."""

    subroutine: str  # subroutine name (e.g. "coverage_sub")

    @classmethod
    def from_csv_token(cls, token: str) -> Call:
        token = token.strip()
        m = re.fullmatch(r'call\("([^"]+)"\)', token)
        if not m:
            raise ValueError(f"Cannot parse call instruction: {token!r}")
        return cls(subroutine=m.group(1))

    def to_csv(self) -> str:
        return f'call("{self.subroutine}")'

    def cell_params(self) -> dict:
        return {}

    def build_blob(self) -> bytes:
        from ..binary_helpers import _tagged_field, _utf16le_null

        out = bytearray()
        out += _utf16le_null("Call")
        out += struct.pack("<I", CALL_TYPE_MARKER)
        out += b"\x01\x00"  # part_count
        out += struct.pack("<I", 4)  # field_count
        out += _tagged_field(_CALL_TAGS[0], "0")
        out += _tagged_field(_CALL_TAGS[1], self.subroutine)
        out += _tagged_field(_CALL_TAGS[2], CALL_FUNC_CODE)
        out += _tagged_field(_CALL_TAGS[3], "")
        return bytes(out)


def build_blob(call: Call) -> bytes:
    """Build the instruction data blob for a Call cell."""
    return call.build_blob()


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    tag_byte_lens: dict[int, int] | None = None,
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Call | None:
    """Construct a Call instruction from tag data (shared by both decoders)."""
    if class_name != "Call" or type_code != CALL_TYPE_MARKER:
        return None
    subroutine = tags.get(0x6208, "")
    if not subroutine:
        return None
    return Call(subroutine=subroutine)


def parse_blob(raw: bytes) -> Call | None:
    """Try to parse a Call instruction from an instruction blob."""
    from .raw import _decompose_blob, _fields_to_tag_dicts

    try:
        class_name, type_marker, _part_count, _extra, fields = _decompose_blob(raw)
    except (ValueError, struct.error):
        return None
    tags, tag_byte_lens, variant_u16, variant_string = _fields_to_tag_dicts(fields)
    return from_tags(class_name, type_marker, tags, tag_byte_lens, variant_u16, variant_string)


def parse_af_call(call: AfCall) -> Call:
    """Parse an AF AST call into a Call."""
    return Call.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="call",
    instruction_types=(Call,),
    binary_class_names=("Call",),
    parse_blob=parse_blob,
    from_tags=from_tags,
    csv_names=("call",),
    parse_csv_call=parse_af_call,
)
