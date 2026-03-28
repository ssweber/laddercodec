"""ContactNO — NO/NC contacts (type markers 0x2711, 0x2712).

Binary class name: ``"ContactNO"`` (for both NO and NC).
Edge contacts use class ``"Edge"`` — see :mod:`edge`.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Literal

from ..model import InstructionType, _validate_operand

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

CONTACT_FUNC_CODES: dict[tuple[InstructionType, bool], str] = {
    (InstructionType.CONTACT_NO, False): "4097",
    (InstructionType.CONTACT_NC, False): "4098",
    (InstructionType.CONTACT_NO, True): "4099",
    (InstructionType.CONTACT_NC, True): "4100",
}

# Reverse lookup: func_code string → (InstructionType, immediate, edge_kind).
_FUNC_TO_CONTACT: dict[str, tuple[InstructionType, bool, Literal["rise", "fall"] | None]] = {}
for (_ct, _imm), _fc in CONTACT_FUNC_CODES.items():
    _FUNC_TO_CONTACT[_fc] = (_ct, _imm, None)

# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

_CONTACT_NO_TAGS = (0x6065, 0x11F5, 0x3218, 0x0000)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Contact:
    """A contact instruction (NO or NC)."""

    type: InstructionType  # CONTACT_NO, CONTACT_NC, or CONTACT_EDGE
    operand: str  # e.g. "X001"
    immediate: bool = False
    edge_kind: Literal["rise", "fall"] | None = None
    wire_down: bool = False

    @classmethod
    def from_csv_token(cls, token: str) -> Contact:
        """Parse NO/NC/immediate forms plus edge forms `rise(...)`/`fall(...)`.

        Also accepts wire-down prefix: ``T:X001``, ``T:rise(X002)``.
        """

        token = token.strip()

        # Detect wire-down prefix: T:X001 or |:rise(X002)
        wire_down = False
        if len(token) > 2 and token[1] == ":" and token[0] in ("T", "|"):
            wire_down = True
            token = token[2:]

        immediate = token.endswith(".immediate")
        if immediate:
            token = token[: -len(".immediate")]

        edge_match = re.fullmatch(r"(rise|fall)\((.+)\)", token)
        if edge_match:
            if immediate:
                raise ValueError("Immediate edge contacts are unsupported")
            edge_kind: Literal["rise", "fall"] = edge_match.group(1)  # type: ignore[assignment]
            operand = _validate_operand(edge_match.group(2).strip())
            return cls(
                InstructionType.CONTACT_EDGE,
                operand,
                immediate=False,
                edge_kind=edge_kind,
                wire_down=wire_down,
            )

        if token.startswith("~"):
            return cls(
                InstructionType.CONTACT_NC,
                _validate_operand(token[1:]),
                immediate=immediate,
                wire_down=wire_down,
            )
        return cls(
            InstructionType.CONTACT_NO,
            _validate_operand(token),
            immediate=immediate,
            wire_down=wire_down,
        )

    @property
    def func_code(self) -> str:
        from .edge import CONTACT_EDGE_FUNC_CODES

        if self.type == InstructionType.CONTACT_EDGE:
            if self.edge_kind not in CONTACT_EDGE_FUNC_CODES:
                raise ValueError("Edge contacts require edge_kind 'rise' or 'fall'")
            if self.immediate:
                raise ValueError("Immediate edge contacts are unsupported")
            return CONTACT_EDGE_FUNC_CODES[self.edge_kind]
        return CONTACT_FUNC_CODES[(self.type, self.immediate)]

    def to_csv(self) -> str:
        from .edge import CONTACT_EDGE_FUNC_CODES

        if self.type == InstructionType.CONTACT_EDGE:
            if self.edge_kind not in CONTACT_EDGE_FUNC_CODES:
                raise ValueError("Edge contacts require edge_kind 'rise' or 'fall'")
            inner = f"{self.edge_kind}({self.operand})"
        else:
            prefix = "~" if self.type == InstructionType.CONTACT_NC else ""
            suffix = ".immediate" if self.immediate else ""
            inner = f"{prefix}{self.operand}{suffix}"
        if self.wire_down:
            return f"T:{inner}"
        return inner


# ---------------------------------------------------------------------------
# Blob builder
# ---------------------------------------------------------------------------


def build_blob(contact: Contact) -> bytes:
    """Build the instruction data blob for a NO/NC contact cell.

    Edge contacts are handled by :func:`edge.build_blob`.
    """
    from ..cell import _tagged_field, _utf16le_null

    if contact.type == InstructionType.CONTACT_EDGE:
        from .edge import build_blob as build_edge_blob

        return build_edge_blob(contact)

    class_name = "ContactNO"
    tags = _CONTACT_NO_TAGS
    field1 = "1" if contact.immediate else "0"

    type_marker = 0x2700 | contact.type
    field_count = 4
    fields = [contact.operand, field1, contact.func_code, ""]

    out = bytearray()
    out += _utf16le_null(class_name)
    out += struct.pack("<I", type_marker)
    out += b"\x01\x00"
    out += struct.pack("<I", field_count)
    for tag, value in zip(tags, fields, strict=True):
        out += _tagged_field(tag, value)
    return bytes(out)


# ---------------------------------------------------------------------------
# Blob parser
# ---------------------------------------------------------------------------


def parse_blob(raw: bytes) -> Contact | None:
    """Try to parse a Contact from an instruction blob starting with "ContactNO"."""
    from ..decode import _parse_tagged_fields, _read_utf16le

    class_name, pos = _read_utf16le(raw, 0)
    if class_name != "ContactNO":
        return None
    if pos + 10 > len(raw):
        return None

    pos += 4  # skip type marker
    pos += 2  # skip unknown 01 00
    field_count = int.from_bytes(raw[pos : pos + 4], "little")
    pos += 4

    fields = _parse_tagged_fields(raw, pos, field_count)
    if len(fields) < 3:
        return None

    operand = fields[0]
    func_code = fields[2]

    info = _FUNC_TO_CONTACT.get(func_code)
    if info is None:
        return None

    itype, immediate, edge_kind = info
    return Contact(
        type=itype,
        operand=operand,
        immediate=immediate,
        edge_kind=edge_kind,
    )
