"""The instruction classes, and the registry of instruction families.

The registry finds a family by CSV name or by instance, and builds instructions from the
tags that the decoders read.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar, cast

from ..codes import Code
from ..errors import CsvWriteError
from ..model import (
    Condition,
    FieldError,
    Instruction,
    PinnedInstruction,
    Reason,
    display_form_only,
)
from ..operands.checks import Refusals
from ..operands.message import says
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
from .coil import Coil, CoilKind
from .comparison import CompareContact, CompareOp
from .contact import Contact, ContactKind
from .copy import (
    BlockCopy,
    BlockCopyConvert,
    Copy,
    CopyConvert,
    Fill,
    Pack,
    PackKind,
    Unpack,
    UnpackKind,
)
from .counter import Counter, CounterKind
from .drum import Drum, DrumKind
from .email import Email
from .end import End
from .family import AfInstructionFamilySpec, ConditionInstructionFamilySpec
from .forloop import Break, Continue, ForLoop, Next
from .home import Home
from .math import Math, MathMode
from .out_variant import OutVariant, OutVariantKind, OutVariantUnit
from .position import PositionMove
from .raw import RawInstruction
from .return_ import Return
from .search import Search
from .send_receive import (
    ModbusAddress,
    ModbusRegisterType,
    ModbusRtuPort,
    ModbusRtuTarget,
    ModbusTcpPort,
    ModbusTcpTarget,
    Receive,
    ReceiveFunctionCode,
    Send,
    SendFunctionCode,
)
from .shift import Shift
from .timer import Timer, TimerKind, TimeUnit
from .undecoded import Undecoded, UndecodedStop
from .velocity import VelocityMove

if TYPE_CHECKING:
    from ..csv.ast import AfCall

_Parsed = TypeVar("_Parsed", bound=Condition | Instruction)

# ---------------------------------------------------------------------------
# Decode-side fallback types and token aliases
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UnknownCondition:
    """An instruction cell on a condition column (A..AE) that the decoder could not read.

    ``raw`` holds the instruction's own bytes, from cell offset ``+0x25`` to the cell
    boundary. When ``decode_program`` builds one, ``raw`` holds the class name instead.
    The class holds no wire flags. If the cell also has a wire down, the decoder wraps the
    ``UnknownCondition`` in a :class:`Tee`.
    """

    raw: bytes

    def __post_init__(self) -> None:
        # A frozen instance must hold bytes. A bytearray could change, and it does not hash.
        if isinstance(self.raw, bytearray):
            object.__setattr__(self, "raw", bytes(self.raw))


@dataclass(frozen=True)
class Tee:
    """A condition cell that holds a contact and a wire down from the cell's left edge.

    It is the contact form of the ``"T"`` wire token. In the CSV, the cell is the contact's
    token with a ``T:`` prefix. ``Tee(Contact("X001"))`` is ``T:X001``.

    ``contact`` is a ``Contact``, a ``CompareContact`` or another ``Condition``, or an
    ``UnknownCondition``. Building a ``Tee`` around anything else raises
    :class:`~laddercodec.FieldError`, and so does a ``Tee`` around a ``Tee``.
    """

    contact: Condition | UnknownCondition

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            if isinstance(self.contact, Tee):
                check.refuse(
                    "contact",
                    says("{contact!r} is a Tee already", contact=self.contact),
                    Reason.FORM,
                    code=Code.INVALID_TEE,
                    then="Wrap the contact once, such as Tee(Contact('X001')).",
                )
            elif not isinstance(self.contact, (Condition, UnknownCondition)):
                check.refuse(
                    "contact",
                    says("{contact!r} is not a contact", contact=self.contact),
                    Reason.FORM,
                    code=Code.INVALID_TEE,
                    then=(
                        "Wrap a Contact or a CompareContact, such as Tee(Contact('X001')). "
                        "For a wire down with no contact, write 'T'."
                    ),
                )

    def to_csv(self) -> str:
        """Return the CSV text of the cell: ``T:`` and the contact's token, such as ``T:X001``.

        ``write_csv`` writes this text for the cell. An ``UnknownCondition`` has no CSV
        token, so a ``Tee`` around one raises :class:`~laddercodec.CsvWriteError`.
        """
        if isinstance(self.contact, UnknownCondition):
            raise CsvWriteError(
                f"Tee holds an UnknownCondition ({len(self.contact.raw)} bytes), and no CSV "
                "token holds one. Replace the contact, such as Tee(Contact('X001'))."
            )
        return f"T:{self.contact.to_csv()}"


@dataclass(frozen=True)
class UnknownInstruction:
    """An instruction cell on the AF column that the decoder could not read.

    The decoder makes one only when it cannot find an instruction blob in the cell.  A blob
    that no parser accepts becomes a :class:`RawInstruction` instead.  ``raw`` holds the
    instruction's own bytes, from cell offset ``+0x25`` to the cell boundary.
    """

    raw: bytes

    def __post_init__(self) -> None:
        # A frozen instance must hold bytes. A bytearray could change, and it does not hash.
        if isinstance(self.raw, bytearray):
            object.__setattr__(self, "raw", bytes(self.raw))


ConditionToken = str | Contact | CompareContact | Condition | UnknownCondition | Tee
"""A condition-column cell of a ``Rung``.

It is a wire token (``"-"``, ``"|"``, ``"T"`` or ``""``), a ``Condition`` such as a
``Contact`` or a ``CompareContact``, or an ``UnknownCondition`` for a cell that the decoder
could not read. A cell that holds one of these instructions and a wire down is a
:class:`Tee` around the instruction."""

InstructionToken = (
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
    | Instruction
    | UnknownInstruction
)
"""An AF-column cell of a ``Rung``.

It is ``""``, ``"NOP"``, an output instruction, or an ``UnknownInstruction`` for a cell that
the decoder could not read.  An output instruction is any ``Instruction``, including a
``RawInstruction`` and the ``Undecoded`` marker."""


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

# Maps each binary class name to its family spec. The name stays so that code that
# imports it keeps working.
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


def parse_af_call(call: AfCall) -> Instruction | None:
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


def parse_af_blob(raw: bytes) -> Instruction | None:
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
    """Return *parsed*, which keeps the blob at the start of *raw* if it needs one.

    It needs the blob if it holds refusals or was read in another form (see
    :func:`~laddercodec.operands.unchecked.keep_stored_blob`)."""
    import struct

    from .raw import find_blob_boundary

    if not needs_stored_blob(parsed):
        return parsed
    try:
        _class_name, end, _part_count = find_blob_boundary(raw)
    except (ValueError, struct.error):
        # With no stored blob, encode() handles it as it handles one read from CSV.
        return parsed
    keep_stored_blob(parsed, raw[:end])
    return parsed


def _with_pin_rows(parsed: Instruction | None, extra: bytes) -> Instruction | None:
    """Return *parsed* with its ``pin_rows`` set from the blob's part bytes, *extra*.

    Each part byte is the row of one pin. Return *parsed* unchanged if it is not a
    pinned instruction or *extra* has the wrong length. Return None if CLICK's dialog
    would not write those rows, so that the caller keeps the blob raw.
    """
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
) -> Condition | None:
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
    return cast(Condition | None, built)


def from_tags_af(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Instruction | None:
    """Build an AF instruction from tag data through the registered specs.

    See :func:`_from_tags`.
    """
    built = _from_tags(
        AF_FAMILY_SPECS, class_name, type_code, tags, variant_u16_tags, variant_string_tags
    )
    return cast(Instruction | None, built)


def _from_tags(
    specs: Sequence[ConditionInstructionFamilySpec | AfInstructionFamilySpec],
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None,
    variant_string_tags: dict[int, dict[int, str]] | None,
) -> object | None:
    """Return the instruction that the first spec to recognise the blob builds, or None.

    Both decoders build every instruction here, from the stored values, inside
    :func:`~laddercodec.operands.unchecked.unchecked`. If the instruction's checks refuse
    a value, the instruction keeps the refusals
    (:func:`~laddercodec.operands.unchecked.refusals`) and does not raise. A stored
    instruction that breaks a dialog rule therefore still decodes as that instruction.

    The function returns None, and the caller keeps the blob raw, in these cases:

    - a refusal that no instruction can keep, such as text CLICK never writes like ``x1``
      or ``C001`` (see :mod:`laddercodec.operands.unchecked`);
    - the parser fails on a value that the checks refused;
    - the instruction's CSV token does not read back to it.
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
                # The blob's own family refused it. Keep it unparsed, and do not try
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
    """Return True if *token*'s CSV token reads back to it. ``write_csv`` checks the same."""
    from ..csv.converter import reads_back  # the CSV reader imports this package

    return reads_back(token)


__all__ = [
    "AF_FAMILY_SPECS",
    "InstructionToken",
    "CONDITION_FAMILY_SPECS",
    "ConditionToken",
    "INSTRUCTION_MODULES",
    "KNOWN_AF_NAMES",
    "KNOWN_PIN_NAMES",
    "Instruction",
    "AfInstructionFamilySpec",
    "BlockCopy",
    "Call",
    "Coil",
    "CompareContact",
    "Condition",
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
    "PositionMove",
    "RawInstruction",
    "Receive",
    "Return",
    "Search",
    "Send",
    "Shift",
    "Tee",
    "Timer",
    "UnknownCondition",
    "UnknownInstruction",
    "Undecoded",
    "Unpack",
    "VelocityMove",
    "BlockCopyConvert",
    "CoilKind",
    "CompareOp",
    "ContactKind",
    "CopyConvert",
    "CounterKind",
    "DrumKind",
    "MathMode",
    "ModbusRegisterType",
    "ModbusRtuPort",
    "ModbusTcpPort",
    "OutVariantKind",
    "OutVariantUnit",
    "PackKind",
    "ReceiveFunctionCode",
    "SendFunctionCode",
    "TimeUnit",
    "TimerKind",
    "UndecodedStop",
    "UnpackKind",
    "from_tags_af",
    "from_tags_condition",
    "get_af_family_by_csv_name",
    "get_af_family_for_token",
    "parse_af_blob",
    "parse_af_call",
    "parse_condition_blob",
]
