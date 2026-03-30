"""Home — home instruction (type marker 0x2734).

Binary class name: ``"Home"``.
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

_TYPE_CODE = 0x2734
_CLASS_NAME = "Home"
_FIELD_COUNT = 21

# ---------------------------------------------------------------------------
# Shared field extraction
# ---------------------------------------------------------------------------


def _extract_fields(tags: dict[int, str]) -> dict[str, str]:
    try:
        home_variant = int(tags.get(0x222E, "0") or "0")
    except ValueError:
        home_variant = 0
    return {
        "tag_222d": tags.get(0x222D) or "0",
        "tag_222e": tags.get(0x222E) or "0",
        "tag_6096": tags.get(0x6096, ""),
        "tag_6097": tags.get(0x6097, ""),
        "tag_609e": tags.get(0x609E, ""),
        "tag_609f": tags.get(0x609F, ""),
        "tag_60a0": tags.get(0x60A0, ""),
        "tag_609c": tags.get(0x609C, ""),
        "tag_609d": tags.get(0x609D, ""),
        "tag_222f": tags.get(0x222F) or "0",
        "tag_11f5": tags.get(0x11F5) or "0",
        "tag_2230": tags.get(0x2230) or "0",
        "tag_60a1": tags.get(0x60A1, ""),
        "tag_60a3": tags.get(0x60A3, ""),
        "tag_60a4": tags.get(0x60A4, ""),
        "tag_607b": tags.get(0x607B, ""),
        "tag_607d": tags.get(0x607D, ""),
        "tag_6083": tags.get(0x6083, ""),
        "tag_2232": tags.get(0x2232) or "0",
        "tag_2233": tags.get(0x2233) or "0",
        "tag_3218": tags.get(0x3218) or str(9738 + home_variant),
    }


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Home(AfInstruction):
    """Home instruction — opaque fields stored as tag-keyed strings.

    Binary class name ``"Home"`` (type marker 0x2734).
    """

    tag_222d: str = "0"
    tag_222e: str = "0"
    tag_6096: str = ""
    tag_6097: str = ""
    tag_609e: str = ""
    tag_609f: str = ""
    tag_60a0: str = ""
    tag_609c: str = ""
    tag_609d: str = ""
    tag_222f: str = "0"
    tag_11f5: str = "0"
    tag_2230: str = "0"
    tag_60a1: str = ""
    tag_60a3: str = ""
    tag_60a4: str = ""
    tag_607b: str = ""
    tag_607d: str = ""
    tag_6083: str = ""
    tag_2232: str = "0"
    tag_2233: str = "0"
    tag_3218: str = "9738"

    def cell_params(self) -> dict:
        return {}

    def build_blob(self) -> bytes:
        out = bytearray()
        out += _utf16le_null(_CLASS_NAME)
        out += struct.pack("<I", _TYPE_CODE)
        out += struct.pack("<H", 1)  # part_count
        out += struct.pack("<I", _FIELD_COUNT)

        out += _tagged_field(0x222D, self.tag_222d)
        out += _tagged_field(0x222E, self.tag_222e)
        out += _tagged_field(0x6096, self.tag_6096)
        out += _tagged_field(0x6097, self.tag_6097)
        out += _tagged_field(0x609E, self.tag_609e)
        out += _tagged_field(0x609F, self.tag_609f)
        out += _tagged_field(0x60A0, self.tag_60a0)
        out += _tagged_field(0x609C, self.tag_609c)
        out += _tagged_field(0x609D, self.tag_609d)
        out += _tagged_field(0x222F, self.tag_222f)
        out += _tagged_field(0x11F5, self.tag_11f5)
        out += _tagged_field(0x2230, self.tag_2230)
        out += _tagged_field(0x60A1, self.tag_60a1)
        out += _tagged_field(0x60A3, self.tag_60a3)
        out += _tagged_field(0x60A4, self.tag_60a4)
        out += _tagged_field(0x607B, self.tag_607b)
        out += _tagged_field(0x607D, self.tag_607d)
        out += _tagged_field(0x6083, self.tag_6083)
        out += _tagged_field(0x2232, self.tag_2232)
        out += _tagged_field(0x2233, self.tag_2233)
        out += _tagged_field(0x3218, self.tag_3218)
        out += _tagged_field(0x0000, "")

        return bytes(out)

    def to_csv(self) -> str:
        specs = [
            f"222d={self.tag_222d}",
            f"222e={self.tag_222e}",
            f"6096={self.tag_6096}",
            f"6097={self.tag_6097}",
            f"609e={self.tag_609e}",
            f"609f={self.tag_609f}",
            f"60a0={self.tag_60a0}",
            f"609c={self.tag_609c}",
            f"609d={self.tag_609d}",
            f"222f={self.tag_222f}",
            f"11f5={self.tag_11f5}",
            f"2230={self.tag_2230}",
            f"60a1={self.tag_60a1}",
            f"60a3={self.tag_60a3}",
            f"60a4={self.tag_60a4}",
            f"607b={self.tag_607b}",
            f"607d={self.tag_607d}",
            f"6083={self.tag_6083}",
            f"2232={self.tag_2232}",
            f"2233={self.tag_2233}",
            f"3218={self.tag_3218}",
            "0000=",
        ]
        return f"raw({_CLASS_NAME},0x{_TYPE_CODE:04x},1,{','.join(specs)})"

    @classmethod
    def from_csv_token(cls, token: str) -> Home:
        """Parse ``raw(Home,0x2734,1,...)`` token."""
        from .raw import _FIELD_SPEC_RE, _split_raw_args

        if not token.startswith("raw(") or not token.endswith(")"):
            raise ValueError(f"Not a raw Home token: {token!r}")
        parts = _split_raw_args(token[4:-1])
        if parts[0] != _CLASS_NAME:
            raise ValueError(f"Not a Home token: {token!r}")

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
) -> Home | None:
    """Construct a Home from tag data (shared by both decoders)."""
    if class_name != _CLASS_NAME or type_code != _TYPE_CODE:
        return None
    return Home(**_extract_fields(tags))


def parse_af_call(call: AfCall) -> Home:
    """Parse an AF AST call into a Home."""
    return Home.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="home",
    instruction_types=(Home,),
    binary_class_names=(_CLASS_NAME,),
    from_tags=from_tags,
)
