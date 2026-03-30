"""Position — position instruction (type marker 0x2736).

Binary class name: ``"Position"``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..binary_helpers import _tagged_field, _utf16le_null
from ..model import AfInstruction
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TYPE_CODE = 0x2736
_CLASS_NAME = "Position"
_FIELD_COUNT = 18

# ---------------------------------------------------------------------------
# Shared field extraction
# ---------------------------------------------------------------------------


def _extract_fields(tags: dict[int, str]) -> dict[str, str]:
    return {
        "tag_222d": tags.get(0x222D) or "0",
        "tag_6098": tags.get(0x6098, ""),
        "tag_6099": tags.get(0x6099, ""),
        "tag_609a": tags.get(0x609A, ""),
        "tag_2206": tags.get(0x2206) or "0",
        "tag_609b": tags.get(0x609B, ""),
        "tag_609c": tags.get(0x609C, ""),
        "tag_609d": tags.get(0x609D, ""),
        "tag_222f": tags.get(0x222F) or "2",
        "tag_11f5": tags.get(0x11F5) or "0",
        "tag_2231": tags.get(0x2231) or "0",
        "tag_60a2": tags.get(0x60A2, ""),
        "tag_60a3": tags.get(0x60A3, ""),
        "tag_60a4": tags.get(0x60A4, ""),
        "tag_607b": tags.get(0x607B, ""),
        "tag_607d": tags.get(0x607D, ""),
        "tag_6083": tags.get(0x6083, ""),
        "tag_3218": tags.get(0x3218) or "9745",
    }


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Position(AfInstruction):
    """Position instruction — opaque fields stored as tag-keyed strings.

    Binary class name ``"Position"`` (type marker 0x2736).
    """

    tag_222d: str = "0"
    tag_6098: str = ""
    tag_6099: str = ""
    tag_609a: str = ""
    tag_2206: str = "0"
    tag_609b: str = ""
    tag_609c: str = ""
    tag_609d: str = ""
    tag_222f: str = "2"
    tag_11f5: str = "0"
    tag_2231: str = "0"
    tag_60a2: str = ""
    tag_60a3: str = ""
    tag_60a4: str = ""
    tag_607b: str = ""
    tag_607d: str = ""
    tag_6083: str = ""
    tag_3218: str = "9745"

    def cell_params(self) -> dict:
        return {}

    def build_blob(self) -> bytes:
        out = bytearray()
        out += _utf16le_null(_CLASS_NAME)
        out += struct.pack("<I", _TYPE_CODE)
        out += struct.pack("<H", 1)  # part_count
        out += struct.pack("<I", _FIELD_COUNT)

        out += _tagged_field(0x222D, self.tag_222d)
        out += _tagged_field(0x6098, self.tag_6098)
        out += _tagged_field(0x6099, self.tag_6099)
        out += _tagged_field(0x609A, self.tag_609a)
        out += _tagged_field(0x2206, self.tag_2206)
        out += _tagged_field(0x609B, self.tag_609b)
        out += _tagged_field(0x609C, self.tag_609c)
        out += _tagged_field(0x609D, self.tag_609d)
        out += _tagged_field(0x222F, self.tag_222f)
        out += _tagged_field(0x11F5, self.tag_11f5)
        out += _tagged_field(0x2231, self.tag_2231)
        out += _tagged_field(0x60A2, self.tag_60a2)
        out += _tagged_field(0x60A3, self.tag_60a3)
        out += _tagged_field(0x60A4, self.tag_60a4)
        out += _tagged_field(0x607B, self.tag_607b)
        out += _tagged_field(0x607D, self.tag_607d)
        out += _tagged_field(0x6083, self.tag_6083)
        out += _tagged_field(0x3218, self.tag_3218)
        out += _tagged_field(0x0000, "")

        return bytes(out)

    def to_csv(self) -> str:
        specs = [
            f"222d={self.tag_222d}",
            f"6098={self.tag_6098}",
            f"6099={self.tag_6099}",
            f"609a={self.tag_609a}",
            f"2206={self.tag_2206}",
            f"609b={self.tag_609b}",
            f"609c={self.tag_609c}",
            f"609d={self.tag_609d}",
            f"222f={self.tag_222f}",
            f"11f5={self.tag_11f5}",
            f"2231={self.tag_2231}",
            f"60a2={self.tag_60a2}",
            f"60a3={self.tag_60a3}",
            f"60a4={self.tag_60a4}",
            f"607b={self.tag_607b}",
            f"607d={self.tag_607d}",
            f"6083={self.tag_6083}",
            f"3218={self.tag_3218}",
            "0000=",
        ]
        return f"raw({_CLASS_NAME},0x{_TYPE_CODE:04x},1,{','.join(specs)})"

    @classmethod
    def from_csv_token(cls, token: str) -> Position:
        """Parse ``raw(Position,0x2736,1,...)`` token."""
        from .raw import _FIELD_SPEC_RE, _split_raw_args

        if not token.startswith("raw(") or not token.endswith(")"):
            raise ValueError(f"Not a raw Position token: {token!r}")
        parts = _split_raw_args(token[4:-1])
        if parts[0] != _CLASS_NAME:
            raise ValueError(f"Not a Position token: {token!r}")

        tags: dict[int, str] = {}
        for spec in parts[3:]:
            m = _FIELD_SPEC_RE.fullmatch(spec)
            if m and m.group(2) is None and m.group(3) is None:
                tags[int(m.group(1), 16)] = m.group(4)

        return cls(**_extract_fields(tags))


# ---------------------------------------------------------------------------
# from_tags factory
# ---------------------------------------------------------------------------


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    tag_byte_lens: dict[int, int] | None = None,
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Position | None:
    """Construct a Position from tag data (shared by both decoders)."""
    if class_name != _CLASS_NAME or type_code != _TYPE_CODE:
        return None
    return Position(**_extract_fields(tags))


def parse_af_call(call: AfCall) -> Position:
    """Parse an AF AST call into a Position."""
    return Position.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="position",
    instruction_types=(Position,),
    binary_class_names=(_CLASS_NAME,),
    from_tags=from_tags,
)
