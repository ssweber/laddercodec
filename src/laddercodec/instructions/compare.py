"""Compare — comparison contacts (type marker 0x2714).

Binary class name: ``"Compare"``.
Operators: EQ, NE, GT, LT, GE, LE.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal

from ..model import InstructionType

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

#: Compare func codes: func_code_str -> operator.
COMPARE_FUNC_CODES: dict[str, Literal["==", "!=", ">", "<", ">=", "<="]] = {
    "4103": "==",
    "4104": "!=",
    "4105": ">",
    "4106": "<",
    "4108": ">=",
    "4109": "<=",
}

#: Reverse lookup: operator → compare func_code string.
COMPARE_OP_TO_FUNC: dict[str, str] = {v: k for k, v in COMPARE_FUNC_CODES.items()}

#: Operator → compare type index string (field 3 in the binary blob).
COMPARE_OP_TO_TYPE_IDX: dict[str, str] = {
    "==": "0",
    "!=": "1",
    ">": "2",
    "<": "3",
    ">=": "4",
    "<=": "5",
}

# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

_COMPARE_TAGS = (0x3218, 0x6066, 0x6067, 0x21F7, 0x0000)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class CompareContact:
    """A comparison contact (EQ, NE, GT, LT, GE, LE).

    Occupies a condition column.  The binary class name is ``Compare``
    (type marker 0x2714).
    """

    op: Literal["==", "!=", "<", ">", "<=", ">="]
    left: str  # left operand, e.g. "DS1"
    right: str  # right operand or literal, e.g. "1", "DS2", "1.1", "FFFFh", '"A"'
    wire_down: bool = False

    @classmethod
    def from_csv_token(cls, token: str) -> CompareContact:
        """Parse ``DS1==1``, ``DS2>=DS3``, etc.

        Also accepts wire-down prefix: ``T:DS1==1``.
        """
        token = token.strip()

        # Detect wire-down prefix: T:DS1==1 or |:DS1==1
        wire_down = False
        if len(token) > 2 and token[1] == ":" and token[0] in ("T", "|"):
            wire_down = True
            token = token[2:]

        # Try two-char ops first to avoid partial match on single-char.
        for op in ("==", "!=", ">=", "<=", ">", "<"):
            idx = token.find(op)
            if idx > 0:
                left = token[:idx]
                right = token[idx + len(op) :]
                if left and right:
                    return cls(op=op, left=left, right=right, wire_down=wire_down)
        raise ValueError(f"Cannot parse compare contact: {token!r}")

    @property
    def func_code(self) -> str:
        return COMPARE_OP_TO_FUNC[self.op]

    @property
    def compare_type_idx(self) -> str:
        return COMPARE_OP_TO_TYPE_IDX[self.op]

    def to_csv(self) -> str:
        inner = f"{self.left}{self.op}{self.right}"
        if self.wire_down:
            return f"T:{inner}"
        return inner


# ---------------------------------------------------------------------------
# Blob builder
# ---------------------------------------------------------------------------


def build_blob(compare: CompareContact) -> bytes:
    """Build the instruction data blob for a compare contact cell."""
    from ..cell import _tagged_field, _utf16le_null

    type_marker = 0x2700 | InstructionType.COMPARE
    field_count = 5
    fields = [
        compare.func_code,
        compare.left,
        compare.right,
        compare.compare_type_idx,
        "",
    ]

    out = bytearray()
    out += _utf16le_null("Compare")
    out += struct.pack("<I", type_marker)
    out += b"\x01\x00"
    out += struct.pack("<I", field_count)
    for tag, value in zip(_COMPARE_TAGS, fields, strict=True):
        out += _tagged_field(tag, value)
    return bytes(out)


# ---------------------------------------------------------------------------
# Blob parser
# ---------------------------------------------------------------------------


def parse_blob(raw: bytes) -> CompareContact | None:
    """Try to parse a CompareContact from an instruction blob."""
    from ..decode import _parse_tagged_fields, _read_utf16le

    class_name, pos = _read_utf16le(raw, 0)
    if class_name != "Compare":
        return None
    if pos + 10 > len(raw):
        return None

    pos += 4  # skip type marker
    pos += 2  # skip 01 00
    field_count = int.from_bytes(raw[pos : pos + 4], "little")
    pos += 4

    fields = _parse_tagged_fields(raw, pos, field_count)
    if len(fields) < 3:
        return None

    func_code = fields[0]
    left = fields[1]
    right = fields[2]

    op = COMPARE_FUNC_CODES.get(func_code)
    if op is None:
        return None

    return CompareContact(op=op, left=left, right=right)
