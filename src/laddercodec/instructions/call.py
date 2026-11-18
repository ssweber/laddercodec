"""The Call instruction, which calls a subroutine.

CLICK stores it with the binary class name ``"Call"`` and the type marker 0x2723.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..binary_helpers import tag_value
from ..codes import Code
from ..errors import CsvError
from ..model import AfInstruction, Reason, check_program_name
from ..operands.checks import Refusals
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

CALL_TYPE_MARKER = 0x2723
CALL_FUNC_CODE = "9221"
# 0x3219 is an index into the dialog's drop-down list. The dialog saves its own index
# when you click OK, so the encoder writes 0 and the decoder ignores the tag.
_CALL_TAGS = (0x3219, 0x6208, 0x3218, 0x0000)


@dataclass(frozen=True)
class Call(AfInstruction):
    """Subroutine call instruction."""

    subroutine: str  # subroutine name (e.g. "coverage_sub")

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            if not self.subroutine:
                check.refuse(
                    "subroutine",
                    "The subroutine name is blank. Enter the name of the subroutine to call.",
                    Reason.MISSING,
                    code=Code.BLANK_FIELD,
                )
            # A Call names a subroutine, so the name follows the Add New Subroutine rules.
            check("subroutine", check_program_name)

    @classmethod
    def from_csv_token(cls, token: str) -> Call:
        token = token.strip()
        m = re.fullmatch(r'call\("([^"]*)"\)', token)
        if not m:
            raise CsvError(
                f"Could not read {token!r} as a Call instruction. Write it as "
                'call("name"), with the subroutine name in double quotes.'
            )
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
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Call | None:
    """Construct a Call from the tags of a decoded blob, or return None if the blob is not a
    Call that names a subroutine. The clipboard and program-file decoders both use it."""
    if class_name != "Call" or type_code != CALL_TYPE_MARKER:
        return None
    subroutine = tag_value(tags, 0x6208)
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
