"""Instruction registry and shared family metadata."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar, cast

from ..model import (
    AfInstruction,
    ConditionInstruction,
    FieldError,
    PinnedInstruction,
    display_form_only,
)
from ..operands.unchecked import keep_stored_blob, needs_stored_blob, refusals, unchecked
from . import call as call_mod
from . import coil as coil_mod
from . import comparison as comparison_mod
from . import contact as contact_mod
from . import copy as copy_mod
from . import counter as counter_mod
from . import drum as drum_mod
from . import email as email_mod
from . import end as end_mod
from . import forloop as forloop_mod
from . import home as home_mod
from . import math as math_mod
from . import out_variant as out_variant_mod
from . import position as position_mod
from . import raw as raw_mod
from . import return_ as return_mod
from . import search as search_mod
from . import send_receive as send_receive_mod
from . import shift as shift_mod
from . import timer as timer_mod
from . import undecoded as undecoded_mod
from . import velocity as velocity_mod
from .call import Call
from .coil import Coil
from .comparison import CompareContact
from .contact import Contact
from .copy import BlockCopy, Copy, Fill, Pack, Unpack
from .counter import Counter
from .drum import Drum
from .email import Email
from .end import End
from .family import AfInstructionFamilySpec, ConditionInstructionFamilySpec
from .forloop import Break, Continue, ForLoop, Next
from .home import Home
from .math import Math
from .out_variant import OutVariant
from .position import Position
from .raw import RawInstruction
from .return_ import Return
from .search import Search
from .send_receive import ModbusAddress, ModbusRtuTarget, ModbusTcpTarget, Receive, Send
from .shift import Shift
from .timer import Timer
from .undecoded import Undecoded
from .velocity import Velocity

if TYPE_CHECKING:
    from ..csv.ast import AfCall

_Parsed = TypeVar("_Parsed", bound=ConditionInstruction | AfInstruction)

# ---------------------------------------------------------------------------
# Decode-side fallback types and token aliases
# ---------------------------------------------------------------------------


@dataclass
class UnknownCondition:
    """Instruction cell on a condition column (A..AE).

    The wire flags (always ``(1,1,0)`` for contacts) are implicit.
    ``raw`` carries the instruction-specific bytes from cell offset
    ``+0x25`` to the cell boundary.
    """

    raw: bytes


@dataclass
class UnknownInstruction:
    """Instruction cell on the AF column.

    ``raw`` carries the instruction-specific bytes from cell offset
    ``+0x25`` to the cell boundary.
    """

    raw: bytes


ConditionToken = str | Contact | CompareContact | ConditionInstruction | UnknownCondition
"""A condition-column cell of a ``Rung``: a wire token (``"-"``, ``"|"``, ``"T"``, ``""``),
a ``Contact`` or ``CompareContact``, or an ``UnknownCondition`` decode could not read."""

AfToken = (
    str
    | Coil
    | OutVariant
    | Timer
    | Counter
    | Copy
    | BlockCopy
    | Fill
    | Pack
    | Unpack
    | ForLoop
    | Next
    | Break
    | Continue
    | Shift
    | End
    | Return
    | Undecoded
    | RawInstruction
    | AfInstruction
    | UnknownInstruction
)
"""An AF-column cell of a ``Rung``: ``""`` or ``"NOP"``, an output instruction (an
``AfInstruction``, ``RawInstruction`` and ``Undecoded`` among them), or an
``UnknownInstruction`` decode could not read."""


CONDITION_FAMILY_SPECS: tuple[ConditionInstructionFamilySpec, ...] = (
    contact_mod.SPEC,
    comparison_mod.SPEC,
)

AF_FAMILY_SPECS: tuple[AfInstructionFamilySpec, ...] = (
    coil_mod.SPEC,
    out_variant_mod.SPEC,
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
    email_mod.SPEC,
    home_mod.SPEC,
    velocity_mod.SPEC,
    position_mod.SPEC,
    undecoded_mod.SPEC,
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
    import struct

    from .raw import _decompose_blob, _fields_to_tag_dicts

    try:
        class_name, type_marker, _part_count, _extra, fields = _decompose_blob(raw)
    except (ValueError, struct.error):
        return None
    tags, variant_u16, variant_string = _fields_to_tag_dicts(fields)
    result = from_tags_condition(class_name, type_marker, tags, variant_u16, variant_string)
    if isinstance(result, (Contact, CompareContact)):
        return _keeping_blob(result, raw)
    return None


def parse_af_blob(raw: bytes) -> AfInstruction | None:
    """Try to parse an AF-column instruction blob."""
    import struct

    from .raw import _decompose_blob, _fields_to_tag_dicts

    try:
        class_name, type_marker, _part_count, extra, fields = _decompose_blob(raw)
    except (ValueError, struct.error):
        return None
    tags, variant_u16, variant_string = _fields_to_tag_dicts(fields)
    parsed = from_tags_af(class_name, type_marker, tags, variant_u16, variant_string)
    parsed = _with_pin_rows(parsed, extra)
    return None if parsed is None else _keeping_blob(parsed, raw)


def _keeping_blob(parsed: _Parsed, raw: bytes) -> _Parsed:
    """*parsed*, keeping the blob at the start of *raw* when it keeps refusals or was read
    in another form (see :func:`~laddercodec.operands.unchecked.keep_stored_blob`)."""
    import struct

    from .raw import find_blob_boundary

    if not needs_stored_blob(parsed):
        return parsed
    try:
        _class_name, end, _part_count = find_blob_boundary(raw)
    except (ValueError, struct.error):
        # Without a blob it can write, encode() refuses it as one read from CSV.
        return parsed
    keep_stored_blob(parsed, raw[:end])
    return parsed


def _with_pin_rows(parsed: AfInstruction | None, extra: bytes) -> AfInstruction | None:
    """Carry a pinned instruction's part bytes (each pin's row) onto the model."""
    if not isinstance(parsed, PinnedInstruction) or len(extra) != len(parsed.pin_rows):
        return parsed
    try:
        return parsed.with_pin_rows(tuple(extra))
    except FieldError:
        return None  # rows CLICK's dialog would not write: keep the blob raw


def from_tags_condition(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> ConditionInstruction | None:
    """Build a condition instruction from tag data through the registered specs.

    See :func:`_from_tags`.
    """
    built = _from_tags(
        CONDITION_FAMILY_SPECS,
        class_name,
        type_code,
        tags,
        variant_u16_tags,
        variant_string_tags,
    )
    return cast(ConditionInstruction | None, built)


def from_tags_af(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> AfInstruction | None:
    """Build an AF instruction from tag data through the registered specs.

    See :func:`_from_tags`.
    """
    built = _from_tags(
        AF_FAMILY_SPECS, class_name, type_code, tags, variant_u16_tags, variant_string_tags
    )
    return cast(AfInstruction | None, built)


def _from_tags(
    specs: Sequence[ConditionInstructionFamilySpec | AfInstructionFamilySpec],
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None,
    variant_string_tags: dict[int, dict[int, str]] | None,
) -> object | None:
    """The instruction the first spec that knows the blob builds from what is stored, or None.

    Both decoders build every instruction here.  The instruction is built from the stored
    values, unchecked: one whose values its checks refuse keeps the refusals
    (:func:`~laddercodec.operands.unchecked.refusals`), so a stored instruction that
    breaks a dialog rule still decodes as that instruction.  It stays unparsed (None,
    and the caller keeps the blob raw) when the refusal is one no instruction keeps (text
    CLICK never writes, such as ``x1`` or ``C001``; see :mod:`laddercodec.operands.unchecked`),
    when the parser fails on a refused value, or when the instruction's CSV token does not
    read back to it.
    """
    for spec in specs:
        if spec.from_tags is None:
            continue
        with display_form_only(), unchecked() as kept:
            try:
                result = spec.from_tags(
                    class_name, type_code, tags, variant_u16_tags, variant_string_tags
                )
            except FieldError:
                # The blob's own family refused it: keep it unparsed rather than try
                # another family.
                return None
            except Exception:
                if kept:
                    return None  # the parser failed on a value the checks refused
                raise
            if result is None:
                continue
            if refusals(result) and not _reads_back(result):
                return None
            return result
    return None


def _reads_back(token: object) -> bool:
    """Whether *token*'s CSV token reads back to it, as ``write_csv`` checks it does."""
    from ..csv.converter import reads_back  # the CSV reader imports this package

    return reads_back(token)


__all__ = [
    "AF_FAMILY_SPECS",
    "AfToken",
    "CONDITION_FAMILY_SPECS",
    "ConditionToken",
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
    "Email",
    "End",
    "Fill",
    "ForLoop",
    "Home",
    "Math",
    "ModbusAddress",
    "ModbusRtuTarget",
    "ModbusTcpTarget",
    "Next",
    "Break",
    "Continue",
    "OutVariant",
    "Pack",
    "Position",
    "RawInstruction",
    "Receive",
    "Return",
    "Search",
    "Send",
    "Shift",
    "Timer",
    "UnknownCondition",
    "UnknownInstruction",
    "Undecoded",
    "Unpack",
    "Velocity",
    "from_tags_af",
    "from_tags_condition",
    "get_af_family_by_csv_name",
    "get_af_family_for_token",
    "parse_af_blob",
    "parse_af_call",
    "parse_condition_blob",
]
