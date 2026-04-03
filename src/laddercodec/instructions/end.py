"""End — program terminator instruction (type marker 0x2727).

Binary class name: ``"End"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..model import AfInstruction
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

END_TYPE_MARKER = 0x2727
_END_TAGS = (0x0000,)


@dataclass
class End(AfInstruction):
    """Program terminator instruction."""

    @classmethod
    def from_csv_token(cls, token: str) -> End:
        token = token.strip()
        if not re.fullmatch(r"end\(\s*\)", token):
            raise ValueError(f"Cannot parse end instruction: {token!r}")
        return cls()

    def to_csv(self) -> str:
        return "end()"

    def cell_params(self) -> dict:
        return {}

    def build_blob(self) -> bytes:
        from ..binary_helpers import _build_blob

        return _build_blob("End", END_TYPE_MARKER, _END_TAGS, [""])


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    tag_byte_lens: dict[int, int] | None = None,
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> End | None:
    """Construct an End instruction from tag data (shared by both decoders)."""
    if class_name != "End" or type_code != END_TYPE_MARKER:
        return None
    return End()


def parse_af_call(call: AfCall) -> End:
    """Parse an AF AST call into an End."""
    return End.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="end",
    instruction_types=(End,),
    binary_class_names=("End",),
    from_tags=from_tags,
    csv_names=("end",),
    parse_csv_call=parse_af_call,
)
