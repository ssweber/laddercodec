"""Instruction registry — dispatch by binary class name.

Each module under ``instructions/`` handles one binary class:
model dataclass, func code tables, blob builder, and blob parser.

The registry maps UTF-16LE class names found in instruction blobs
to ``(parse_blob, build_blob)`` callables for dispatch.
"""

from __future__ import annotations

from . import compare as compare_mod
from . import contact_no as contact_no_mod
from . import edge as edge_mod
from . import out as out_mod
from . import tmr as tmr_mod

# Re-export model classes for convenience.
from .compare import CompareContact
from .contact_no import Contact
from .out import Coil
from .raw import RawInstruction
from .tmr import Timer

# ---------------------------------------------------------------------------
# Registry: binary class name → (parse_blob, build_blob | None)
# ---------------------------------------------------------------------------

# Each entry: class_name → module with parse_blob(raw) and build_blob(obj).
INSTRUCTION_MODULES = {
    "ContactNO": contact_no_mod,
    "Edge": edge_mod,
    "Compare": compare_mod,
    "Out": out_mod,
    "Latch": out_mod,  # all coil class names → same module
    "Reset": out_mod,
    "Tmr": tmr_mod,
}


def parse_condition_blob(raw: bytes) -> Contact | CompareContact | None:
    """Try to parse a condition-column instruction blob.

    Dispatches to the appropriate module based on the UTF-16LE class name.
    Returns None if unrecognised.
    """
    # Quick class name detection: read first few bytes as UTF-16LE.
    # Class names are short (< 20 chars), so read up to 40 bytes.
    try:
        end = raw.index(b"\x00\x00")
        # Ensure even alignment for UTF-16LE.
        if end % 2 == 1:
            end += 1
        class_name = raw[:end].decode("utf-16-le")
    except (ValueError, UnicodeDecodeError):
        return None

    mod = INSTRUCTION_MODULES.get(class_name)
    if mod is None:
        return None

    result = mod.parse_blob(raw)
    if isinstance(result, (Contact, CompareContact)):
        return result
    return None


def parse_af_blob(raw: bytes) -> Coil | Timer | None:
    """Try to parse an AF-column instruction blob.

    Dispatches to the appropriate module based on the UTF-16LE class name.
    Returns None if unrecognised.
    """
    try:
        end = raw.index(b"\x00\x00")
        if end % 2 == 1:
            end += 1
        class_name = raw[:end].decode("utf-16-le")
    except (ValueError, UnicodeDecodeError):
        return None

    mod = INSTRUCTION_MODULES.get(class_name)
    if mod is None:
        return None

    result = mod.parse_blob(raw)
    if isinstance(result, (Coil, Timer)):
        return result
    return None


__all__ = [
    "INSTRUCTION_MODULES",
    "Coil",
    "CompareContact",
    "Contact",
    "RawInstruction",
    "Timer",
    "parse_af_blob",
    "parse_condition_blob",
]
