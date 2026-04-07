"""Call — subroutine call instruction (type marker 0x2723).

Binary class name: ``"Call"``.
"""

from __future__ import annotations

import re
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
        from ..binary_helpers import _build_blob

        return _build_blob(
            "Call",
            CALL_TYPE_MARKER,
            _CALL_TAGS,
            ["0", self.subroutine, CALL_FUNC_CODE, ""],
        )


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


def parse_af_call(call: AfCall) -> Call:
    """Parse an AF AST call into a Call."""
    return Call.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="call",
    instruction_types=(Call,),
    binary_class_names=("Call",),
    from_tags=from_tags,
    csv_names=("call",),
    parse_csv_call=parse_af_call,
)
