"""Instruction registry — dispatch by binary class name.

Each module under ``instructions/`` handles one binary class:
model dataclass, func code tables, blob builder, and blob parser.

The registry maps UTF-16LE class names found in instruction blobs
to ``(parse_blob, build_blob)`` callables for dispatch.
"""

from __future__ import annotations

# Re-export base classes and model classes for convenience.
from ..model import AfInstruction, ConditionInstruction
from . import coil as coil_mod
from . import comparison as comparison_mod
from . import contact as contact_mod
from . import copy as copy_mod
from . import timer as timer_mod
from .coil import Coil
from .comparison import CompareContact
from .contact import Contact
from .copy import BlockCopy, Copy, Fill
from .raw import RawInstruction
from .timer import Timer

# ---------------------------------------------------------------------------
# Registry: binary class name → (parse_blob, build_blob | None)
# ---------------------------------------------------------------------------

# Each entry: class_name → module with parse_blob(raw) and build_blob(obj).
INSTRUCTION_MODULES = {
    "ContactNO": contact_mod,
    "Edge": contact_mod,
    "Compare": comparison_mod,
    "Out": coil_mod,
    "Latch": coil_mod,  # all coil class names → same module
    "Reset": coil_mod,
    "Tmr": timer_mod,
    "Copy": copy_mod,
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
    if isinstance(result, ConditionInstruction):
        return result
    return None


def parse_af_blob(raw: bytes) -> Coil | Timer | Copy | BlockCopy | Fill | None:
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
    if isinstance(result, AfInstruction):
        return result
    return None


__all__ = [
    "INSTRUCTION_MODULES",
    "AfInstruction",
    "BlockCopy",
    "Coil",
    "CompareContact",
    "ConditionInstruction",
    "Contact",
    "Copy",
    "Fill",
    "RawInstruction",
    "Timer",
    "parse_af_blob",
    "parse_condition_blob",
]
