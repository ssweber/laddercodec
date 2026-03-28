"""Edge — rise/fall edge contacts (type marker 0x2713).

Binary class name: ``"Edge"``.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Literal

from ..model import InstructionType

if TYPE_CHECKING:
    from .contact_no import Contact

# ---------------------------------------------------------------------------
# Func code tables
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

_EDGE_TAGS = (0x6065, 0x21F6, 0x3218, 0x0000)

# ---------------------------------------------------------------------------
# Blob builder
# ---------------------------------------------------------------------------


def build_blob(contact: Contact) -> bytes:
    """Build the instruction data blob for an edge contact cell."""
    from ..cell import _tagged_field, _utf16le_null

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


# ---------------------------------------------------------------------------
# Blob parser
# ---------------------------------------------------------------------------


def parse_blob(raw: bytes) -> Contact | None:
    """Try to parse a Contact from an instruction blob starting with "Edge"."""
    from ..decode import _parse_tagged_fields, _read_utf16le
    from .contact_no import Contact

    class_name, pos = _read_utf16le(raw, 0)
    if class_name != "Edge":
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

    info = _FUNC_TO_EDGE.get(func_code)
    if info is None:
        return None

    itype, immediate, edge_kind = info
    return Contact(
        type=itype,
        operand=operand,
        immediate=immediate,
        edge_kind=edge_kind,
    )
