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
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

from ..binary_helpers import tag_value
from ..codes import Code
from ..errors import CsvError
from ..model import InstructionType, PinnedInstruction, Reason, check_address
from ..operands.checks import Refusals
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: A shift register runs over C bits only.
SHIFT_BANKS = frozenset({"C"})

_SHIFT_FUNC_CODES = ("8448", "8449", "8450")
_SHIFT_FORM = (
    "Could not read {token!r} as a shift register. Write it as shift(start..end), such as "
    "shift(C1..C8)."
)
_SHIFT_SUB_MARKERS = (b"\x00\x00\x00\x00", b"\x01\x00\x00\x00", b"\x02\x00\x00\x00")

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Shift(PinnedInstruction):
    """A shift register instruction."""

    start_bit: str
    end_bit: str
    #: Rows of the clock and reset inputs, counted down from the main row. An OR leg
    #: under the data input pushes both down. An OR leg under ``.clock()`` pushes
    #: ``.reset()`` down.
    pin_rows: tuple[int, ...] = (1, 2)

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            check.normalize("start_bit", "end_bit")
            # Both ends must be C bits. CLICK refuses any other bank with OBJ-004, and that
            # includes an end in another bank than the start.
            start = check("start_bit", check_address, SHIFT_BANKS, bank_id="OBJ-004")
            end = check("end_bit", check_address, SHIFT_BANKS, bank_id="OBJ-004")
            # CLICK refuses an end equal to the start with OBJ-012. CLICK normalizes an
            # address as it is typed (C001 becomes C1), so this compares the parsed
            # addresses, not the text. A start above the end is allowed, and it reverses
            # the shift.
            if start is not None and end is not None and end == start:
                check.refuse(
                    ("end_bit", "start_bit"),
                    f"{self.end_bit!r} is the same address as Shift.start_bit "
                    f"{self.start_bit!r}; a shift register needs two different ends",
                    Reason.CONFLICT,
                    "OBJ-012",
                    code=Code.DUPLICATE_ADDRESS,
                )
            check.run(self._check_pin_rows)

    def pin_names(self) -> tuple[str, ...]:
        return (".clock", ".reset")

    def pin_labels(self) -> tuple[str | None, ...]:
        return (".clock()", ".reset()")

    def with_pins(self, pins: dict[str, tuple[str, ...]], pin_rows: tuple[int, ...]) -> Shift:
        return replace(self, pin_rows=cast(tuple[int, int], pin_rows))

    @classmethod
    def from_csv_token(cls, token: str) -> Shift:
        """Parse ``shift(C99..C106)``."""
        token = token.strip()
        m = re.fullmatch(r"shift\((.+)\)", token)
        if not m:
            raise CsvError(_SHIFT_FORM.format(token=token))

        inner = m.group(1).strip()
        if ".." not in inner:
            raise CsvError(f"shift expects a range arg (start..end): {token!r}")
        parts = [p.strip() for p in inner.split("..")]
        if len(parts) != 2 or not all(parts):
            raise CsvError(_SHIFT_FORM.format(token=token))

        return cls(
            start_bit=parts[0],
            end_bit=parts[1],
        )

    def to_csv(self) -> str:
        return f"shift({self.start_bit}..{self.end_bit})"

    def cell_params(self) -> dict:
        return {"visual_rows": self.pin_rows[-1] + 1, "sub_rows": 3}

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this shift register."""
        from ..binary_helpers import _tagged_field, _utf16le_null, _variant_tagged_field

        type_marker = 0x2700 | InstructionType.SHIFT

        out = bytearray()
        out += _utf16le_null("SR")
        out += struct.pack("<I", type_marker)
        out += b"\x03\x00"  # part count
        out += bytes(self.pin_rows)  # extra part bytes: each pin's row
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
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Shift | None:
    """Construct a Shift from tag data (shared by both decoders)."""
    if class_name != "SR" or type_code != _SHIFT_TYPE_CODE:
        return None
    start_bit = tag_value(tags, 0x6066)
    end_bit = tag_value(tags, 0x6067)
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
)
