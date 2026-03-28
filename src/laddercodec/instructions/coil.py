"""Out — all coil types (type markers 0x2715, 0x2716, 0x2717).

Binary class name: ``"Out"`` (for out, latch, and reset).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

from ..model import InstructionType, _validate_operand

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

COIL_FUNC_CODES: dict[tuple[InstructionType, bool, bool], str] = {
    # (type, is_range, immediate) -> func_code
    (InstructionType.COIL_OUT, False, False): "8193",
    (InstructionType.COIL_OUT, False, True): "8197",
    (InstructionType.COIL_OUT, True, False): "8207",
    (InstructionType.COIL_OUT, True, True): "8208",
    (InstructionType.COIL_LATCH, False, False): "8195",
    (InstructionType.COIL_LATCH, False, True): "8199",
    (InstructionType.COIL_LATCH, True, False): "8213",
    (InstructionType.COIL_LATCH, True, True): "8214",
    (InstructionType.COIL_RESET, False, False): "8196",
    (InstructionType.COIL_RESET, False, True): "8200",
    (InstructionType.COIL_RESET, True, False): "8219",
    (InstructionType.COIL_RESET, True, True): "8220",
}

COIL_NAME_TO_TYPE = {
    "out": InstructionType.COIL_OUT,
    "latch": InstructionType.COIL_LATCH,
    "reset": InstructionType.COIL_RESET,
}

COIL_TYPE_TO_NAME = {v: k for k, v in COIL_NAME_TO_TYPE.items()}

# Reverse lookup: func_code string → (InstructionType, is_range, immediate).
_FUNC_TO_COIL: dict[str, tuple[InstructionType, bool, bool]] = {
    v: k for k, v in COIL_FUNC_CODES.items()
}

# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

_COIL_TAGS = (0x6066, 0x6067, 0x11F8, 0x11F5, 0x3218, 0x0000)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Coil:
    """An output coil instruction."""

    type: InstructionType  # COIL_OUT, COIL_LATCH, COIL_RESET
    operand: str  # e.g. "Y001"
    range_end: str | None = None
    immediate: bool = False

    @classmethod
    def from_csv_token(cls, token: str) -> Coil:
        """Parse coil forms with inner immediate wrapper and ranges."""
        token = token.strip()
        if token.startswith("immediate("):
            raise ValueError(
                f"Immediate must be an inner wrapper (e.g. out(immediate(Y1))): {token!r}"
            )

        m = re.fullmatch(r"(out|latch|reset)\((.+)\)", token)
        if not m:
            raise ValueError(f"Cannot parse coil: {token!r}")

        coil_type = COIL_NAME_TO_TYPE[m.group(1)]
        arg = m.group(2).strip()

        immediate_inner = False
        inner = re.fullmatch(r"immediate\((.+)\)", arg)
        if inner:
            immediate_inner = True
            arg = inner.group(1).strip()

        immediate = immediate_inner
        if ":" in arg:
            raise ValueError(f"Range delimiter ':' is unsupported: {token!r}")

        if ".." in arg:
            parts = [p.strip() for p in arg.split("..")]
            if len(parts) != 2 or not all(parts):
                raise ValueError(f"Cannot parse coil range: {token!r}")
            op1 = _validate_operand(parts[0])
            op2 = _validate_operand(parts[1])
            return cls(type=coil_type, operand=op1, range_end=op2, immediate=immediate)

        return cls(type=coil_type, operand=_validate_operand(arg), immediate=immediate)

    @property
    def func_code(self) -> str:
        key = (self.type, self.range_end is not None, self.immediate)
        return COIL_FUNC_CODES[key]

    def to_csv(self) -> str:
        name = COIL_TYPE_TO_NAME[self.type]
        operand = self.operand
        if self.range_end is not None:
            operand = f"{operand}..{self.range_end}"
        if self.immediate:
            operand = f"immediate({operand})"
        return f"{name}({operand})"


# ---------------------------------------------------------------------------
# Blob builder
# ---------------------------------------------------------------------------


def build_blob(coil: Coil) -> bytes:
    """Build the instruction data blob for a coil cell."""
    from ..cell import _tagged_field, _utf16le_null

    type_marker = 0x2700 | coil.type
    field_count = 6
    fields = [
        coil.operand,
        coil.range_end or "",
        "0",  # oneshot (always "0" for basic coils)
        "1" if coil.immediate else "0",
        coil.func_code,
        "",
    ]

    out = bytearray()
    out += _utf16le_null("Out")
    out += struct.pack("<I", type_marker)
    out += b"\x01\x00"
    out += struct.pack("<I", field_count)
    for tag, value in zip(_COIL_TAGS, fields, strict=True):
        out += _tagged_field(tag, value)
    return bytes(out)


# ---------------------------------------------------------------------------
# Blob parser
# ---------------------------------------------------------------------------

_COIL_CLASSES = {"Out", "Latch", "Reset"}


def parse_blob(raw: bytes) -> Coil | None:
    """Try to parse a Coil from an instruction blob."""
    from ..decode import _parse_tagged_fields, _read_utf16le

    class_name, pos = _read_utf16le(raw, 0)
    if class_name not in _COIL_CLASSES:
        return None
    if pos + 10 > len(raw):
        return None

    pos += 4  # skip type marker
    pos += 2  # skip unknown 01 00
    field_count = int.from_bytes(raw[pos : pos + 4], "little")
    pos += 4

    fields = _parse_tagged_fields(raw, pos, field_count)
    if len(fields) < 5:
        return None

    operand = fields[0]
    range_end = fields[1] if fields[1] else None
    func_code = fields[4]

    info = _FUNC_TO_COIL.get(func_code)
    if info is None:
        return None

    itype, is_range, immediate = info
    return Coil(
        type=itype,
        operand=operand,
        range_end=range_end if is_range else None,
        immediate=immediate,
    )
