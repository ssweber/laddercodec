"""Return — instruction (type marker 0x2724).

Binary class name: ``"Return"``.
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

RETURN_TYPE_MARKER = 0x2724
RETURN_FUNC_CODE = "9223"
_RETURN_TAGS = (0x3218, 0x0000)


@dataclass
class Return(AfInstruction):
    """Return instruction."""

    @classmethod
    def from_csv_token(cls, token: str) -> Return:
        token = token.strip()
        if not re.fullmatch(r"return\(\s*\)", token):
            raise ValueError(f"Cannot parse return instruction: {token!r}")
        return cls()

    def to_csv(self) -> str:
        return "return()"

    def cell_params(self) -> dict:
        return {}

    def build_blob(self) -> bytes:
        from ..binary_helpers import _tagged_field, _utf16le_null

        out = bytearray()
        out += _utf16le_null("Return")
        out += struct.pack("<I", RETURN_TYPE_MARKER)
        out += b"\x01\x00"  # part_count
        out += struct.pack("<I", 2)  # field_count
        out += _tagged_field(_RETURN_TAGS[0], RETURN_FUNC_CODE)
        out += _tagged_field(_RETURN_TAGS[1], "")
        return bytes(out)


def build_blob(ret: Return) -> bytes:
    """Build the instruction data blob for a Return cell."""
    return ret.build_blob()


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    tag_byte_lens: dict[int, int] | None = None,
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Return | None:
    """Construct a Return instruction from tag data (shared by both decoders)."""
    if class_name != "Return" or type_code != RETURN_TYPE_MARKER:
        return None
    return Return()


def parse_af_call(call: AfCall) -> Return:
    """Parse an AF AST call into a Return."""
    if call.args or call.kwargs:
        raise ValueError("return expects no arguments")
    return Return()


SPEC = AfInstructionFamilySpec(
    family_name="return",
    instruction_types=(Return,),
    binary_class_names=("Return",),
    from_tags=from_tags,
    csv_names=("return",),
    parse_csv_call=parse_af_call,
)
