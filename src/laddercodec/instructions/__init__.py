"""Instruction registry and shared family metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..model import AfInstruction, ConditionInstruction
from . import call as call_mod
from . import coil as coil_mod
from . import comparison as comparison_mod
from . import contact as contact_mod
from . import copy as copy_mod
from . import counter as counter_mod
from . import drum as drum_mod
from . import end as end_mod
from . import forloop as forloop_mod
from . import math as math_mod
from . import raw as raw_mod
from . import return_ as return_mod
from . import search as search_mod
from . import send_receive as send_receive_mod
from . import shift as shift_mod
from . import timer as timer_mod
from .call import Call
from .coil import Coil
from .comparison import CompareContact
from .contact import Contact
from .copy import BlockCopy, Copy, Fill, Pack, Unpack
from .counter import Counter
from .drum import Drum
from .end import End
from .family import AfInstructionFamilySpec, ConditionInstructionFamilySpec
from .forloop import ForLoop, Next
from .math import Math
from .raw import RawInstruction
from .return_ import Return
from .search import Search
from .send_receive import ModbusAddress, ModbusRtuTarget, ModbusTcpTarget, Receive, Send
from .shift import Shift
from .timer import Timer

if TYPE_CHECKING:
    from ..csv.ast import AfCall


CONDITION_FAMILY_SPECS: tuple[ConditionInstructionFamilySpec, ...] = (
    contact_mod.SPEC,
    comparison_mod.SPEC,
)

AF_FAMILY_SPECS: tuple[AfInstructionFamilySpec, ...] = (
    coil_mod.SPEC,
    timer_mod.SPEC,
    counter_mod.SPEC,
    copy_mod.SPEC,
    call_mod.SPEC,
    forloop_mod.SPEC,
    math_mod.SPEC,
    shift_mod.SPEC,
    search_mod.SPEC,
    drum_mod.SPEC,
    end_mod.SPEC,
    return_mod.SPEC,
    send_receive_mod.SPEC,
    raw_mod.SPEC,
)

_CONDITION_BINARY_TO_SPEC = {
    class_name: spec for spec in CONDITION_FAMILY_SPECS for class_name in spec.binary_class_names
}
_AF_BINARY_TO_SPEC = {
    class_name: spec for spec in AF_FAMILY_SPECS for class_name in spec.binary_class_names
}
_AF_CSV_TO_SPEC = {csv_name: spec for spec in AF_FAMILY_SPECS for csv_name in spec.csv_names}

KNOWN_AF_NAMES = frozenset(_AF_CSV_TO_SPEC) | frozenset(
    pin_name for spec in AF_FAMILY_SPECS for pin_name in spec.pin_names
)
KNOWN_PIN_NAMES = frozenset(pin_name for spec in AF_FAMILY_SPECS for pin_name in spec.pin_names)

# Backwards-compatible alias for the old binary-class-name registry.
INSTRUCTION_MODULES = {
    **{class_name: spec for class_name, spec in _CONDITION_BINARY_TO_SPEC.items()},
    **{class_name: spec for class_name, spec in _AF_BINARY_TO_SPEC.items()},
}


def _read_class_name(raw: bytes) -> str | None:
    """Read the UTF-16LE class name prefix from an instruction blob."""
    try:
        end = raw.index(b"\x00\x00")
        if end % 2 == 1:
            end += 1
        return raw[:end].decode("utf-16-le")
    except (ValueError, UnicodeDecodeError):
        return None


def get_af_family_by_csv_name(name: str) -> AfInstructionFamilySpec | None:
    """Return the AF family spec for a CSV token name."""
    return _AF_CSV_TO_SPEC.get(name)


def get_af_family_for_token(token: object) -> AfInstructionFamilySpec | None:
    """Return the AF family spec that owns an instruction instance."""
    for spec in AF_FAMILY_SPECS:
        if isinstance(token, spec.instruction_types):
            return spec
    return None


def parse_af_call(call: AfCall) -> AfInstruction | None:
    """Parse a CSV AF call node using the owning family spec."""
    spec = get_af_family_by_csv_name(call.name)
    if spec is None or spec.parse_csv_call is None:
        return None
    return spec.parse_csv_call(call)


def parse_condition_blob(raw: bytes) -> Contact | CompareContact | None:
    """Try to parse a condition-column instruction blob."""
    class_name = _read_class_name(raw)
    if class_name is None:
        return None

    spec = _CONDITION_BINARY_TO_SPEC.get(class_name)
    if spec is None:
        return None

    result = spec.parse_blob(raw)
    if isinstance(result, (Contact, CompareContact)):
        return result
    return None


def parse_af_blob(
    raw: bytes,
) -> AfInstruction | None:
    """Try to parse an AF-column instruction blob."""
    class_name = _read_class_name(raw)
    if class_name is None:
        return None

    spec = _AF_BINARY_TO_SPEC.get(class_name)
    if spec is None:
        return None

    result = spec.parse_blob(raw)
    if isinstance(result, AfInstruction):
        return result
    return None


__all__ = [
    "AF_FAMILY_SPECS",
    "CONDITION_FAMILY_SPECS",
    "INSTRUCTION_MODULES",
    "KNOWN_AF_NAMES",
    "KNOWN_PIN_NAMES",
    "AfInstruction",
    "AfInstructionFamilySpec",
    "BlockCopy",
    "Call",
    "Coil",
    "CompareContact",
    "ConditionInstruction",
    "ConditionInstructionFamilySpec",
    "Counter",
    "Contact",
    "Copy",
    "Drum",
    "End",
    "Fill",
    "ForLoop",
    "Math",
    "ModbusAddress",
    "ModbusRtuTarget",
    "ModbusTcpTarget",
    "Next",
    "Pack",
    "RawInstruction",
    "Receive",
    "Return",
    "Search",
    "Send",
    "Shift",
    "Timer",
    "Unpack",
    "get_af_family_by_csv_name",
    "get_af_family_for_token",
    "parse_af_blob",
    "parse_af_call",
    "parse_condition_blob",
]
