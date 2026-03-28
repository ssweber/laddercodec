"""Raw — opaque instruction passthrough for unrecognised class names.

Preserves the full instruction blob (from cell offset +0x25 to before
the tail) as hex.  The encoder reconstructs header and tail from grid
context; the blob is pasted verbatim.

CSV token format::

    raw(ClassName,hex_blob)

The class name is redundant (it's inside the hex) but makes the CSV
human-scannable.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..model import AfInstruction

# ---------------------------------------------------------------------------
# Blob boundary detection
# ---------------------------------------------------------------------------


def _read_utf16le_boundary(raw: bytes, offset: int) -> tuple[str, int]:
    """Read a null-terminated UTF-16LE string, return (string, pos_after_null).

    Raises ``ValueError`` if the string is unterminated within *raw*.
    """
    i = offset
    while i + 1 < len(raw):
        if raw[i] == 0 and raw[i + 1] == 0:
            return raw[offset:i].decode("utf-16-le"), i + 2
        i += 2
    raise ValueError(f"Unterminated UTF-16LE string at offset {offset:#x}")


def find_blob_boundary(raw: bytes) -> tuple[str, int, int]:
    """Find the end of the instruction blob in *raw* bytes.

    *raw* is everything from cell offset +0x25 to the next cell boundary
    (i.e. blob + optional af_summary + 16-byte tail).

    Returns ``(class_name, blob_end_offset, part_count)``.  The clean
    blob is ``raw[:blob_end_offset]``.

    Raises ``ValueError`` on malformed data.
    """
    pos = 0

    # 1. Class name (UTF-16LE null-terminated).
    class_name, pos = _read_utf16le_boundary(raw, pos)

    # 2. Type marker (uint32 LE).
    if pos + 4 > len(raw):
        raise ValueError("Truncated: no type marker")
    pos += 4

    # 3. Part count (uint16 LE).
    if pos + 2 > len(raw):
        raise ValueError("Truncated: no part count")
    part_count = struct.unpack_from("<H", raw, pos)[0]
    pos += 2

    # 4. Extra part bytes: (part_count - 1) sequential bytes.
    extra = max(0, part_count - 1)
    if pos + extra > len(raw):
        raise ValueError("Truncated: missing part extra bytes")
    pos += extra

    # 5. Field count (uint32 LE).
    if pos + 4 > len(raw):
        raise ValueError("Truncated: no field count")
    field_count = struct.unpack_from("<I", raw, pos)[0]
    pos += 4

    # 6. Tagged fields: [2B tag][4B sentinel/marker][UTF-16LE null value].
    for f_idx in range(field_count):
        if pos + 6 > len(raw):
            raise ValueError(f"Truncated at field {f_idx}/{field_count}")
        pos += 2  # tag
        pos += 4  # sentinel or sub-marker
        _, pos = _read_utf16le_boundary(raw, pos)

    return class_name, pos, part_count


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class RawInstruction(AfInstruction):
    """Opaque AF instruction — blob preserved for byte-exact round-trip.

    Attributes
    ----------
    class_name:
        Binary class name (e.g. ``"Copy"``, ``"Cnt"``).  Extracted from
        the blob for CSV readability; also present inside *blob*.
    blob:
        Full instruction blob bytes (from cell offset +0x25 to the end
        of tagged fields, excluding tail and af_summary).
    part_count:
        Number of parts (1 = single-row, >1 = multi-row).  Derived from
        the blob during construction.
    """

    class_name: str
    blob: bytes
    part_count: int = 1

    def cell_params(self) -> dict:
        """Return ClickCell kwargs intrinsic to this instruction."""
        if self.part_count > 1:
            return {"visual_rows": self.part_count}
        return {}

    def build_blob(self) -> bytes:
        """Return the raw blob bytes (no-op — already stored)."""
        return self.blob

    def to_csv(self) -> str:
        """Serialize to ``raw(ClassName,hex)`` CSV token."""
        return f"raw({self.class_name},{self.blob.hex()})"

    @classmethod
    def from_csv_token(cls, token: str) -> RawInstruction:
        """Parse ``raw(ClassName,hex)`` CSV token.

        Splits on the first comma inside ``raw(...)`` — class name,
        then hex blob.
        """
        token = token.strip()
        if not token.startswith("raw(") or not token.endswith(")"):
            raise ValueError(f"Not a raw token: {token!r}")
        inner = token[4:-1]
        comma = inner.index(",")
        class_name = inner[:comma].strip()
        hex_str = inner[comma + 1 :].strip()
        blob = bytes.fromhex(hex_str)

        # Extract part_count from the blob.
        try:
            _, _, part_count = find_blob_boundary(blob)
        except (ValueError, IndexError):
            part_count = 1

        return cls(class_name=class_name, blob=blob, part_count=part_count)
