"""Email — email instruction (type marker 0x2737).

Binary class name: ``"Email"``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..binary_helpers import _tagged_field, _utf16le_null, _variant_tagged_field
from ..model import AfInstruction
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TYPE_CODE = 0x2737
_CLASS_NAME = "Email"

_ARRAY_TAG_B1 = 0x68B1
_ARRAY_TAG_B0 = 0x68B0
_ARRAY_COUNT = 250

# 19 standard + 250 + 250 + 3 trailing = 522
_FIELD_COUNT = 522

# ---------------------------------------------------------------------------
# Shared field extraction
# ---------------------------------------------------------------------------


def _extract_fields(tags: dict[int, str]) -> dict[str, str]:
    return {
        "tag_60a5": tags.get(0x60A5, ""),
        "tag_60a6": tags.get(0x60A6, ""),
        "tag_60a7": tags.get(0x60A7, ""),
        "tag_2237": tags.get(0x2237) or "0",
        "tag_6235": tags.get(0x6235, ""),
        "tag_6236": tags.get(0x6236, ""),
        "tag_60ae": tags.get(0x60AE, ""),
        "tag_60af": tags.get(0x60AF, ""),
        "tag_2206": tags.get(0x2206) or "0",
        "tag_2238": tags.get(0x2238) or "0",
        "tag_6217": tags.get(0x6217, ""),
        "tag_622a": tags.get(0x622A, ""),
        "tag_6081": tags.get(0x6081, ""),
        "tag_6082": tags.get(0x6082, ""),
        "tag_607c": tags.get(0x607C, ""),
        "tag_607b": tags.get(0x607B, ""),
        "tag_607d": tags.get(0x607D, ""),
        "tag_6083": tags.get(0x6083, ""),
        "tag_2239": tags.get(0x2239) or "0",
        "tag_20ca": tags.get(0x20CA) or "2",
        "tag_3218": tags.get(0x3218) or "9748",
    }


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Email(AfInstruction):
    """Email instruction — opaque fields stored as tag-keyed strings.

    Binary class name ``"Email"`` (type marker 0x2737).
    """

    tag_60a5: str = ""
    tag_60a6: str = ""
    tag_60a7: str = ""
    tag_2237: str = "0"
    tag_6235: str = ""
    tag_6236: str = ""
    tag_60ae: str = ""
    tag_60af: str = ""
    tag_2206: str = "0"
    tag_2238: str = "0"
    tag_6217: str = ""
    tag_622a: str = ""
    tag_6081: str = ""
    tag_6082: str = ""
    tag_607c: str = ""
    tag_607b: str = ""
    tag_607d: str = ""
    tag_6083: str = ""
    tag_2239: str = "0"
    tag_20ca: str = "2"
    tag_3218: str = "9748"

    def cell_params(self) -> dict:
        return {}

    def build_blob(self) -> bytes:
        out = bytearray()
        out += _utf16le_null(_CLASS_NAME)
        out += struct.pack("<I", _TYPE_CODE)
        out += struct.pack("<H", 1)  # part_count
        out += struct.pack("<I", _FIELD_COUNT)

        out += _tagged_field(0x60A5, self.tag_60a5)
        out += _tagged_field(0x60A6, self.tag_60a6)
        out += _tagged_field(0x60A7, self.tag_60a7)
        out += _tagged_field(0x2237, self.tag_2237)
        out += _tagged_field(0x6235, self.tag_6235)
        out += _tagged_field(0x6236, self.tag_6236)
        out += _tagged_field(0x60AE, self.tag_60ae)
        out += _tagged_field(0x60AF, self.tag_60af)
        out += _tagged_field(0x2206, self.tag_2206)
        out += _tagged_field(0x2238, self.tag_2238)
        out += _tagged_field(0x6217, self.tag_6217)
        out += _tagged_field(0x622A, self.tag_622a)
        out += _tagged_field(0x6081, self.tag_6081)
        out += _tagged_field(0x6082, self.tag_6082)
        out += _tagged_field(0x607C, self.tag_607c)
        out += _tagged_field(0x607B, self.tag_607b)
        out += _tagged_field(0x607D, self.tag_607d)
        out += _tagged_field(0x6083, self.tag_6083)
        out += _tagged_field(0x2239, self.tag_2239)

        for tag in (_ARRAY_TAG_B1, _ARRAY_TAG_B0):
            for idx in range(_ARRAY_COUNT):
                out += _variant_tagged_field(tag, struct.pack("<I", idx), "")

        out += _tagged_field(0x20CA, self.tag_20ca)
        out += _tagged_field(0x3218, self.tag_3218)
        out += _tagged_field(0x0000, "")

        return bytes(out)

    def to_csv(self) -> str:
        specs = [
            f"60a5={self.tag_60a5}",
            f"60a6={self.tag_60a6}",
            f"60a7={self.tag_60a7}",
            f"2237={self.tag_2237}",
            f"6235={self.tag_6235}",
            f"6236={self.tag_6236}",
            f"60ae={self.tag_60ae}",
            f"60af={self.tag_60af}",
            f"2206={self.tag_2206}",
            f"2238={self.tag_2238}",
            f"6217={self.tag_6217}",
            f"622a={self.tag_622a}",
            f"6081={self.tag_6081}",
            f"6082={self.tag_6082}",
            f"607c={self.tag_607c}",
            f"607b={self.tag_607b}",
            f"607d={self.tag_607d}",
            f"6083={self.tag_6083}",
            f"2239={self.tag_2239}",
            f"68b1[{_ARRAY_COUNT}]=",
            f"68b0[{_ARRAY_COUNT}]=",
            f"20ca={self.tag_20ca}",
            f"3218={self.tag_3218}",
            "0000=",
        ]
        return f"raw({_CLASS_NAME},0x{_TYPE_CODE:04x},1,{','.join(specs)})"

    @classmethod
    def from_csv_token(cls, token: str) -> Email:
        """Parse ``raw(Email,0x2737,1,...)`` token."""
        from .raw import _FIELD_SPEC_RE, _split_raw_args

        if not token.startswith("raw(") or not token.endswith(")"):
            raise ValueError(f"Not a raw Email token: {token!r}")
        parts = _split_raw_args(token[4:-1])
        if parts[0] != _CLASS_NAME:
            raise ValueError(f"Not an Email token: {token!r}")

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
) -> Email | None:
    """Construct an Email from tag data (shared by both decoders)."""
    if class_name != _CLASS_NAME or type_code != _TYPE_CODE:
        return None
    return Email(**_extract_fields(tags))


def parse_af_call(call: AfCall) -> Email:
    """Parse an AF AST call into an Email."""
    return Email.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="email",
    instruction_types=(Email,),
    binary_class_names=(_CLASS_NAME,),
    from_tags=from_tags,
)
