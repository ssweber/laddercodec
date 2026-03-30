"""Contact — NO/NC/edge contacts (type markers 0x2711, 0x2712, 0x2713).

Binary class names: ``"ContactNO"`` (for NO and NC), ``"Edge"`` (for rise/fall).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Literal, cast

from ..model import TYPE_CODE_TO_ITYPE, ConditionInstruction, InstructionType, _validate_operand
from .family import ConditionInstructionFamilySpec

# ---------------------------------------------------------------------------
# Func code tables — NO/NC
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
# Func code tables — Edge
# ---------------------------------------------------------------------------

CONTACT_EDGE_FUNC_CODES: dict[Literal["rise", "fall"], str] = {
    "rise": "4101",
    "fall": "4102",
}

# Reverse lookup: func_code string → (InstructionType, immediate, edge_kind).
_FUNC_TO_EDGE: dict[str, tuple[InstructionType, bool, Literal["rise", "fall"] | None]] = {}
for _edge, _fc in CONTACT_EDGE_FUNC_CODES.items():
    _FUNC_TO_EDGE[_fc] = (InstructionType.CONTACT_EDGE, False, _edge)

# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

_CONTACT_NO_TAGS = (0x6065, 0x11F5, 0x3218, 0x0000)
_EDGE_TAGS = (0x6065, 0x21F6, 0x3218, 0x0000)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Contact(ConditionInstruction):
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

        # Detect negation prefix
        negated = token.startswith("~")
        if negated:
            token = token[1:]

        # Detect immediate — suffix (.immediate) or wrapper (immediate(...))
        immediate = token.endswith(".immediate")
        if immediate:
            token = token[: -len(".immediate")]

        if not immediate:
            inner = re.fullmatch(r"immediate\((.+)\)", token)
            if inner:
                immediate = True
                token = inner.group(1).strip()

        edge_match = re.fullmatch(r"(rise|fall)\((.+)\)", token)
        if edge_match:
            if immediate:
                raise ValueError("Immediate edge contacts are unsupported")
            edge_kind = cast(Literal["rise", "fall"], edge_match.group(1))
            operand = _validate_operand(edge_match.group(2).strip())
            return cls(
                InstructionType.CONTACT_EDGE,
                operand,
                immediate=False,
                edge_kind=edge_kind,
                wire_down=wire_down,
            )

        itype = InstructionType.CONTACT_NC if negated else InstructionType.CONTACT_NO
        return cls(
            itype,
            _validate_operand(token),
            immediate=immediate,
            wire_down=wire_down,
        )

    @property
    def func_code(self) -> str:
        if self.type == InstructionType.CONTACT_EDGE:
            if self.edge_kind not in CONTACT_EDGE_FUNC_CODES:
                raise ValueError("Edge contacts require edge_kind 'rise' or 'fall'")
            if self.immediate:
                raise ValueError("Immediate edge contacts are unsupported")
            return CONTACT_EDGE_FUNC_CODES[self.edge_kind]
        return CONTACT_FUNC_CODES[(self.type, self.immediate)]

    def to_csv(self) -> str:
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

    def cell_params(self) -> dict:
        """Return ClickCell kwargs intrinsic to this instruction."""
        return {"is_contact": True, "wire_down": 1 if self.wire_down else 0}

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this contact cell."""
        from ..binary_helpers import _tagged_field, _utf16le_null

        if self.type == InstructionType.CONTACT_EDGE:
            return _build_edge_blob(self)

        class_name = "ContactNO"
        tags = _CONTACT_NO_TAGS
        field1 = "1" if self.immediate else "0"

        type_marker = 0x2700 | self.type
        field_count = 4
        fields = [self.operand, field1, self.func_code, ""]

        out = bytearray()
        out += _utf16le_null(class_name)
        out += struct.pack("<I", type_marker)
        out += b"\x01\x00"
        out += struct.pack("<I", field_count)
        for tag, value in zip(tags, fields, strict=True):
            out += _tagged_field(tag, value)
        return bytes(out)


# ---------------------------------------------------------------------------
# Blob builder — Edge (private helper)
# ---------------------------------------------------------------------------


def _build_edge_blob(contact: Contact) -> bytes:
    """Build the instruction data blob for an edge contact cell."""
    from ..binary_helpers import _tagged_field, _utf16le_null

    class_name = "Edge"
    tags = _EDGE_TAGS
    field1 = "0" if contact.edge_kind == "rise" else "1"

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


# Module-level wrapper for backward compatibility.
def build_blob(contact: Contact) -> bytes:
    """Build the instruction data blob for a contact cell."""
    return contact.build_blob()


# ---------------------------------------------------------------------------
# Shared from_tags factory
# ---------------------------------------------------------------------------


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    tag_byte_lens: dict[int, int] | None = None,
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Contact | None:
    """Construct a Contact from tag data (shared by both decoders)."""
    itype = TYPE_CODE_TO_ITYPE.get(type_code)

    if class_name == "ContactNO" and itype in (
        InstructionType.CONTACT_NO,
        InstructionType.CONTACT_NC,
    ):
        operand = tags.get(0x6065, "")
        if not operand:
            return None
        immediate = 0x11F5 in tags
        return Contact(type=itype, operand=operand, immediate=immediate)

    if class_name == "Edge" and itype == InstructionType.CONTACT_EDGE:
        operand = tags.get(0x6065, "")
        if not operand:
            return None
        # SCR: tag absent = rise, present = fall.
        # Clipboard: tag always present, byte value 0 = rise, 1 = fall.
        edge_kind: Literal["rise", "fall"] = (
            "fall" if (tag_byte_lens or {}).get(0x21F6, 0) != 0 else "rise"
        )
        return Contact(
            type=InstructionType.CONTACT_EDGE,
            operand=operand,
            edge_kind=edge_kind,
        )

    return None


SPEC = ConditionInstructionFamilySpec(
    family_name="contact",
    instruction_types=(Contact,),
    binary_class_names=("ContactNO", "Edge"),
    from_tags=from_tags,
)
