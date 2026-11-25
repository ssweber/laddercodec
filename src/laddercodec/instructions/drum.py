"""Drum instructions: the event drum, the time drum and the time & event drum.

The binary class name is ``"Drum"``, and the type marker is 0x271B.

There are three kinds of drum.  An event_drum is event-driven, and a time_drum is
time-driven.  CLICK v4 adds the time_event_drum.  Each of its steps has a preset time, an
event, or both.  A step with both ends when its time has elapsed and its event is on.

Event and time drums use the 64-field v3 blob.  Two drums exist only in v4: the time &
event drum, and a time drum with a register preset.  They use v4's 82-field blob, which
holds 16 preset slots (``0x6891``), a constant-preset mask (``0x428A``) and a timer done
bit (``0x6068``).

A drum has 4 grid rows: the main row, the reset pin on row 1, the jump pin on row 2 and
the jog pin on row 3.  OR legs under a pin push the later pins down and make the drum
taller.  ``pin_rows`` holds the row of each pin, and the blob stores it in its part bytes.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast, get_args

from ..binary_helpers import tag_flag, tag_int, tag_value
from ..codes import Code
from ..errors import CsvReadError, EncodeError
from ..model import (
    Address,
    AddressError,
    PinnedInstruction,
    Reason,
    check_address,
    normalize_items,
)
from ..operands.address import (
    ADDRESS_BANKS,
    address_shape,
    digits_value,
    is_pointer,
    parse_address,
)
from ..operands.banks import BIT_BANKS, XY_BANKS
from ..operands.checks import Constants, Refusals, check_operand, choice_operand, is_choice
from ..operands.constants import INT16_MAX, Kind
from ..operands.message import Op, Rule, from_parts, operand, parts_of, says, shown
from ..operands.unchecked import AllowsRefusals
from .family import AfInstructionFamilySpec
from .timer import TimeUnit

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..csv.ast import AfCall

_L = TypeVar("_L")

DrumKind = Literal["event_drum", "time_drum", "time_event_drum"]
"""The kind of a drum. Each kind is also the name of its CSV call."""

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

# The func codes of an event drum without jog: base, reset, jump.
_EVENT_FC_NO_JOG = (8491, 8492, 8493)
# The func codes of an event drum with jog: base, reset, jump, jog.
_EVENT_FC_JOG = (8494, 8495, 8496, 8497)

# The first func code of a time drum's block, for each unit.  A block starts with the
# no-jog group (base, reset, jump).  The jog group (base, reset, jump, jog) follows at
# block+3.  For Th the jog group is at block+4, because code 8479 is not used.  The Th
# block is therefore 8 codes long.
_TIME_FC_BASE: dict[str, int] = {
    "Tms": 8455,
    "Ts": 8462,
    "Tm": 8469,
    "Th": 8476,
    "Td": 8484,
}
_TH_JOG_SKIP = 1

# A time drum with a register preset (CLICK v4) uses the same blocks, 1792 codes higher,
# so its Tms block starts at 10247.  A time drum whose presets are all constants uses the
# series that starts at 8455.
_REGISTER_PRESET_FC_OFFSET = 10247 - 8455

# The first func code of a time & event drum's block (CLICK v4), for each unit.  The
# blocks have the same shape as the time drum's.
_TIME_EVENT_FC_BASE: dict[str, int] = {
    "Tms": 10503,
    "Ts": 10510,
    "Tm": 10517,
    "Th": 10524,
    "Td": 10532,
}

#: A drum has at most 16 steps and 16 outputs.
_MAX_DRUM_SIZE = 16

# The values of tag 0x2200, the drum base.
_BASE_TIME, _BASE_EVENT, _BASE_TIME_EVENT = "0", "1", "2"

# The index string of each time unit.  Timer uses the same indexes.
_DRUM_UNIT_TO_INDEX: dict[TimeUnit, str] = {
    "Tms": "0",
    "Ts": "1",
    "Tm": "2",
    "Th": "3",
    "Td": "4",
}
_DRUM_INDEX_TO_UNIT: dict[str, TimeUnit] = {v: k for k, v in _DRUM_UNIT_TO_INDEX.items()}

_DRUM_KINDS: tuple[DrumKind, ...] = get_args(DrumKind)

#: The list fields that each kind of drum uses.
_KIND_LISTS: dict[str, tuple[str, ...]] = {
    "event_drum": ("outputs", "events", "pattern"),
    "time_drum": ("outputs", "presets", "pattern"),
    "time_event_drum": ("outputs", "presets", "events", "pattern"),
}

#: The list fields of addresses and constants.
_LISTS = ("outputs", "presets", "events")


def _is_blank(value: object) -> bool:
    """Return True if *value* is ``""``.

    A list field holds ``""`` when it is blank."""
    return value == ""


# ---------------------------------------------------------------------------
# Pattern encoding
# ---------------------------------------------------------------------------


def _pattern_to_bitmasks(pattern: tuple[tuple[int, ...], ...], num_steps: int) -> list[str]:
    """Return the pattern as 16 bitmask strings, one per step slot, each a signed int16."""
    result: list[str] = []
    for step_idx in range(16):
        if step_idx < num_steps:
            bitmask = sum(bit << i for i, bit in enumerate(pattern[step_idx]))
            if bitmask >= 32768:
                bitmask -= 65536
            result.append(str(bitmask))
        else:
            result.append("0")
    return result


def _parse_simple_list(val: str) -> tuple[str, ...]:
    """Parse ``"[a,b,c]"`` into a tuple of strings."""
    val = val.strip()
    if not val.startswith("[") or not val.endswith("]"):
        raise CsvReadError(
            f"{val!r} is not a list. Write it in square brackets, such as [Y001,Y002]."
        )
    inner = val[1:-1].strip()
    if not inner:
        return ()
    return tuple(x.strip() for x in inner.split(","))


def _parse_pattern(val: str) -> tuple[tuple[int | str, ...], ...]:
    """Parse ``"[[1,0],[0,1]]"`` into rows of cells.

    A cell other than 0 or 1 stays text, for the Drum to refuse."""
    val = val.strip()
    if not val.startswith("[") or not val.endswith("]"):
        raise CsvReadError(
            f"{val!r} is not a pattern. Write one bracketed row of 0s and 1s per step, such as "
            "[[1,0],[0,1]]."
        )
    inner = val[1:-1].strip()
    rows: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(inner):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "," and depth == 0:
            rows.append(inner[start:i].strip())
            start = i + 1
    rows.append(inner[start:].strip())
    pattern: list[tuple[int | str, ...]] = []
    for row_str in rows:
        if not row_str:
            continue
        cells = _parse_simple_list(row_str)
        pattern.append(tuple(_pattern_cell(x) for x in cells))
    return tuple(pattern)


def _pattern_cell(text: str) -> int | str:
    return int(text) if text in ("0", "1") else text


def _parse_optional_list(val: str) -> tuple[str, ...]:
    """Parse ``"[1000,None,DS1]"``, with ``""`` for each ``None``.

    ``None`` marks a step that leaves this value blank."""
    return tuple("" if x == "None" else x for x in _parse_simple_list(val))


def _format_optional_list(values: tuple[str, ...]) -> str:
    return ",".join(value or "None" for value in values)


def is_register_preset(preset: str) -> bool:
    """Return True if a time drum preset names a register, such as ``DS1``, not a duration."""
    return address_shape(preset) is not None


def _constant_preset_mask(presets: tuple[str, ...]) -> str:
    """Return the value of tag 0x428A, a mask of the presets that are constants.

    Bit *n* is set unless step *n*'s preset is a register.  When every preset is a
    constant or blank, all 16 bits are set and the value is ``-1``.  CLICK v4 writes the
    tag when you click OK in the drum's dialog.  CLICK picks a time drum's func code series
    from the mask.
    """
    mask = -1
    for i, preset in enumerate(presets):
        if is_register_preset(preset):
            mask &= ~(1 << i)
    return str(mask)


#: A constant step duration is digits only, from 0 to 32767 for every unit, with no ``-``
#: or ``+``.  Any other constant is refused with OBJ-005.  A register duration must be a DS
#: address, and another bank is refused with OBJ-004.  Some CPUs do not support a register
#: duration.  On such a CPU, CLICK's syntax check reports C0227.  A rung does not say which
#: CPU the project selects, so laddercodec does not check this.
_DURATION = Constants(frozenset({Kind.INTEGER}), signs="", low=0, high=INT16_MAX)


#: The operators that CLICK refuses before an event's address, such as ``~X001``.
_EVENT_PREFIXES = ("~", "!", "/", "-", "NC ", "NOT ")
#: The edge calls that CLICK refuses as an event, such as ``rise(X001)``.
_EVENT_EDGES = ("rise(", "fall(")
_HEX_DIGITS = frozenset("0123456789ABCDEFabcdef")
#: The comparison operators of the event expressions that have OBJ-005, such as ``DS5>3``.
_EVENT_COMPARISONS = ("==", "<>", ">")
_ONE_ADDRESS = "Write one bit address, such as X001."
#: The refusal codes to which :func:`_check_event` adds the id from :func:`_event_id`.
_EVENT_ID_CODES = (Code.NOT_AN_ADDRESS, Code.ADDRESS_OUT_OF_RANGE)


def _one_address(text: str) -> bool:
    return parse_address(text.upper()) is not None


def _bit_address(text: str) -> bool:
    """Return whether ``text`` is an X, Y, C, T, CT or SC address written in uppercase."""
    address = parse_address(text)
    return address is not None and address.bank in BIT_BANKS


def _expression(text: str) -> bool:
    """Return whether ``text`` is one of the expressions that CLICK refuses with OBJ-005."""
    for operator in _EVENT_COMPARISONS:
        sides = text.split(operator)
        if len(sides) == 2:
            left, right = sides
            digits = right.isascii() and right.isdigit()
            return parse_address(left) is not None and (digits or _bit_address(right))
    inner = text[1:-1]
    items = inner.split(",")
    words = text.split(" ")
    return (
        (text.startswith("(") and text.endswith(")") and _bit_address(inner))
        or (
            text.startswith("[")
            and text.endswith("]")
            and len(items) >= 2
            and all(_bit_address(item) for item in items)
        )
        or (len(words) == 2 and all(_bit_address(word) for word in words))
    )


def _not_one_address(text: str) -> bool:
    """Return whether ``text`` is one of the forms that CLICK refuses with OBJ-005."""
    prefix = next((p for p in _EVENT_PREFIXES if text.startswith(p)), None)
    edge = next((e for e in _EVENT_EDGES if text.startswith(e) and text.endswith(")")), None)
    ends = text.split("..")
    items = [item for item in text.split(",") if item]
    shape = address_shape(text.upper())
    return (
        (prefix is not None and _one_address(text[len(prefix) :]))
        or (edge is not None and _one_address(text[len(edge) : -1]))
        or (len(ends) == 2 and all(_one_address(end) for end in ends))
        or ("," in text and bool(items) and all(_one_address(item) for item in items))
        or is_pointer(text.upper())
        or (text.startswith("$") and len(text) > 1 and set(text[1:]) <= _HEX_DIGITS)
        or _expression(text)
        or (
            text.isascii()
            and text.isalnum()
            and (shape is None or shape[0] not in ADDRESS_BANKS)
            and text.upper() not in ADDRESS_BANKS
        )
    )


def _event_id(text: object) -> tuple[str, str] | None:
    """Return the CLICK id and the advice for an event that is not a bit address in its
    bank's range, or None.

    CLICK refuses these events with OBJ-005:

    - an address after an operator, such as ``~X001``, ``!X001``, ``/X001``, ``-X001``,
      ``NC X001`` or ``NOT X001``;
    - an address in an edge call, such as ``rise(X001)``;
    - a range, such as ``X001..X002``;
    - addresses with commas after or between them, such as ``X001,X002`` or ``Y001,``;
    - a pointer, such as ``X[DS1]``;
    - ``$`` and hex digits, such as ``$41``;
    - ASCII letters and digits that are neither a bank and a number nor a bank alone, such
      as ``Q1``, ``ABC``, ``1`` or ``C1A``;
    - an uppercase address, then ``>``, ``==`` or ``<>``, then digits or an uppercase bit
      address, such as ``DS5>3``, ``X1==1`` or ``C1<>C2``;
    - one uppercase bit address in parentheses, such as ``(C1)``;
    - two or more uppercase bit addresses in brackets, with a comma between each two, such
      as ``[C1,C2]``;
    - two uppercase bit addresses with one space between them, such as ``C1 C2``.

    It refuses a bank name alone with OBJ-002 for a bank that an event takes, such as ``X``,
    and with OBJ-004 for any other bank, such as ``DS``.  It reads the number after a bit
    bank by its value, so ``C000001`` is C1.  It refuses a number above the bank's highest
    address with OBJ-003, such as ``C2001``, ``X817``, ``X99999999`` or ``C0002001``.  It
    refuses an X or Y number that no X or Y point has with OBJ-002, such as ``X017``,
    ``X100`` or ``X00000100``.  It refuses ``X000``, ``Y000``, ``C0``, ``T0``, ``CT0`` and
    ``SC0`` with OBJ-003.  Another spelling of 0, such as ``X0`` or ``X0000000``, gets no
    id here.  CLICK ignores
    spaces in an event.  It refuses ``DS 1`` and `` DS1`` with OBJ-004, as it refuses
    ``DS1``.  Any other text has no id here.
    """
    if not isinstance(text, str):
        return None
    if text in ADDRESS_BANKS:
        if text in BIT_BANKS:
            example = f"{text}001" if text in XY_BANKS else f"{text}1"
            return "OBJ-002", f"Write the number after the bank, such as {example}."
        return "OBJ-004", _ONE_ADDRESS
    if _not_one_address(text):
        return "OBJ-005", _ONE_ADDRESS
    if " " in text:
        address = parse_address(text.replace(" ", "").upper())
        if address is not None and address.bank not in BIT_BANKS:
            return "OBJ-004", _ONE_ADDRESS
        return None
    shape = address_shape(text)
    if shape is not None and shape[0] in BIT_BANKS:
        bank, digits = shape
        value = digits_value(digits)
        if value > ADDRESS_BANKS[bank][1] or text == Address(bank, 0, False).display:
            return "OBJ-003", _ONE_ADDRESS
        if bank in XY_BANKS and value > 0 and parse_address(f"{bank}{value:03d}") is None:
            return "OBJ-002", _ONE_ADDRESS
    return None


def _check_event(value: str, field: str, *, label: str, typed: object = None) -> Address:
    """Check a step's event and return its address, or raise :class:`AddressError`.

    An event is one bit address in X, Y, C, T, CT or SC.  It has no NC or edge form.  An
    address in another bank has OBJ-004.  Text that is not an address, and an address
    outside its bank's range, have the id that :func:`_event_id` gives them.  The refusal of
    text that is not an address also gets the advice of :func:`_event_id`.

    ``value`` is the event in display form.  ``typed`` is the text that the caller gave for
    it, if that is known.  The id is the one for ``typed``, because CLICK keeps an event as
    it is typed.  For example, ``X0`` has no id, and ``X000`` has OBJ-003.
    """
    try:
        return check_address(value, field, BIT_BANKS, label=label, bank_id="OBJ-004")
    except AddressError as exc:
        parts = parts_of(exc)
        found = _event_id(value if typed is None else typed)
        if exc.code not in _EVENT_ID_CODES or parts is None or found is None:
            raise
        click_id, then = found
        if exc.code is not Code.NOT_AN_ADDRESS:
            then = parts.then
        raise from_parts(
            AddressError,
            replace(parts, click_id=click_id, then=then),
            field=exc.fields,
            reason=exc.reason,
            code=exc.code,
            click_id=click_id,
        ) from None


def _check_distinct_outputs(
    check: Refusals, outputs: list[Address | None], texts: tuple[str, ...], flag: Address | None
) -> None:
    """Refuse an output used twice, or used as the completion flag (OBJ-014).

    CLICK normalizes an address as it is typed (``C001`` becomes ``C1``) before it
    compares, so ``C1`` and ``C001`` are the same output.  An output that its own check
    refused is ``None`` in *outputs*, and this does not compare it.
    """
    seen: dict[Address, int] = {}
    for i, (output, text) in enumerate(zip(outputs, texts, strict=True)):
        if output is None:
            continue
        if output in seen:
            check.refuse(
                (f"outputs[{i}]", f"outputs[{seen[output]}]"),
                says(
                    "{text} is already output {first}",
                    "each output is a different bit",
                    text=Op(text),
                    first=seen[output],
                ),
                Reason.CONFLICT,
                "OBJ-014",
                code=Code.DUPLICATE_ADDRESS,
            )
            continue
        seen[output] = i
        if output == flag:
            check.refuse(
                (f"outputs[{i}]", "completion_flag"),
                says(
                    "{text} is the completion flag",
                    "an output is a different bit",
                    text=Op(text),
                ),
                Reason.CONFLICT,
                "OBJ-014",
                code=Code.DUPLICATE_ADDRESS,
            )


def _refuse_blank_steps(
    check: Refusals, attr: str, blank: list[int], rule: Rule, click_id: str, then: str
) -> None:
    """Refuse the list field *attr* if any of its steps is blank.

    Refuse the list itself.  If another refusal already covers the list, refuse each blank
    step instead, so that the other refusal does not hide this one."""
    if not blank:
        return
    code = Code.DRUM_STEP_EMPTY
    if check.refused(attr):
        for i in blank:
            check.refuse(f"{attr}[{i}]", rule, Reason.MISSING, click_id, code=code, then=then)
    else:
        check.refuse(attr, rule, Reason.MISSING, click_id, code=code, then=then)


def _timer_done_bit(accumulator: str) -> str:
    """Return the done bit of the timer that owns *accumulator*: ``TD101`` -> ``T101``."""
    if not accumulator.startswith("TD"):
        raise CsvReadError(f"time_event_drum accumulator must be a TD address: {accumulator!r}")
    return f"T{accumulator[2:]}"


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def _iterable(value: Any) -> bool:
    """Return whether ``value`` can be iterated."""
    try:
        iter(value)
    except TypeError:
        return False
    return True


@dataclass(frozen=True)
class Drum(PinnedInstruction, AllowsRefusals):
    """A drum sequencer instruction: an event_drum, a time_drum or a time_event_drum.

    The drum sits in the AF column.  Its binary class name is ``Drum``, and its type
    marker is 0x271B.  A drum takes at least 4 grid rows.  Row 0 is the main row, and the
    reset, jump and jog pins sit at ``pin_rows``.  These are rows 1, 2 and 3 unless OR
    legs push them down.

    ``kind`` is the CSV call name.  An event drum has ``events``, a time drum has
    ``presets``, and a time & event drum has both, one of each per step.  The drum refuses
    the list that its kind does not use.  A time & event step may leave either one blank,
    as ``""`` here and ``None`` in CSV.  The lists are stored as tuples.

    A list field that is ``""`` is blank, as in the CSV token ``event_drum(outputs=,...)``.
    The drum refuses a blank list that its kind uses, with the reason ``missing``.  It
    stores a blank list that its kind does not use as an empty tuple.
    """

    kind: DrumKind
    outputs: tuple[str, ...] = ()
    presets: tuple[str, ...] = ()  # time and time & event drums
    events: tuple[str, ...] = ()  # event and time & event drums
    pattern: tuple[tuple[int, ...], ...] = ()
    current_step: str = ""
    completion_flag: str = ""
    accumulator: str = ""  # TD address (time and time & event drums)
    unit: TimeUnit | Literal[""] = ""  # blank for an event drum
    jog_enabled: bool = False
    jump_enabled: bool = False
    jump_step: str = ""  # DS address
    #: The rows of the reset, jump and jog inputs, counting the main row as 0.  OR legs
    #: under a pin push the later pins down.  An unused pin keeps a row of its own.
    pin_rows: tuple[int, ...] = (1, 2, 3)

    def __post_init__(self) -> None:  # ty: ignore[invalid-dataclass]
        with Refusals(self) as check:
            check.flag("jog_enabled", "jump_enabled")
            check.run(self._check_pin_rows)
            # A blank list that the kind uses stays "", so that it is refused as missing.
            uses = _KIND_LISTS[self.kind] if self.kind in _DRUM_KINDS else ()
            blank = [name for name in uses if _is_blank(getattr(self, name))]
            # The events as given, before they are written in display form.
            typed = tuple(self.events) if isinstance(self.events, (list, tuple)) else ()
            for name in _LISTS:
                if name not in blank:
                    check.run(normalize_items, self, name)
            if not all(_iterable(getattr(self, name)) for name in _LISTS):
                return  # The checks below read these lists, so they can't run.
            if "pattern" not in blank:
                self._freeze_pattern()
            check.normalize("current_step", "completion_flag", "accumulator", "jump_step")
            kind = self.kind
            if kind not in _DRUM_KINDS:
                check.refuse(
                    "kind",
                    says(
                        "{kind} is not one of {kinds}",
                        kind=operand(kind),
                        kinds=", ".join(_DRUM_KINDS),
                    ),
                    Reason.CHOICE,
                    code=Code.INVALID_CHOICE,
                )
            else:
                if kind == "event_drum" and self.presets:
                    check.refuse(
                        "presets",
                        says("an event drum has events, not presets"),
                        Reason.CONFLICT,
                        code=Code.OPTION_NOT_OFFERED,
                        then="Leave presets empty.",
                    )
                if kind == "event_drum" and self.unit:
                    check.refuse(
                        "unit",
                        says("an event drum has no time unit"),
                        Reason.CONFLICT,
                        code=Code.OPTION_NOT_OFFERED,
                        then="Leave unit blank.",
                    )
                if kind == "time_drum" and self.events:
                    check.refuse(
                        "events",
                        says("a time drum has presets, not events"),
                        Reason.CONFLICT,
                        code=Code.OPTION_NOT_OFFERED,
                        then="Leave events empty.",
                    )
                # A blank list is refused once, here. The size and pattern checks skip it.
                for name in blank:
                    check.refuse(
                        name,
                        says("is blank", "it needs a value"),
                        Reason.MISSING,
                        code=Code.BLANK_FIELD,
                    )
            steps, outputs = self.num_steps, self.num_outputs
            steps_field = "events" if kind == "event_drum" else "presets"
            sizes_ok = True
            if not 1 <= steps <= _MAX_DRUM_SIZE:
                sizes_ok = False
                check.refuse(
                    steps_field,
                    says("{steps} steps is outside 1-{limit}", steps=steps, limit=_MAX_DRUM_SIZE),
                    Reason.RANGE,
                    code=Code.DRUM_SIZE_OUT_OF_RANGE,
                )
            if not 1 <= outputs <= _MAX_DRUM_SIZE:
                sizes_ok = False
                check.refuse(
                    "outputs",
                    says(
                        "{outputs} outputs is outside 1-{limit}",
                        outputs=outputs,
                        limit=_MAX_DRUM_SIZE,
                    ),
                    Reason.RANGE,
                    code=Code.DRUM_SIZE_OUT_OF_RANGE,
                )
            if sizes_ok and not check.refused("pattern"):
                self._check_pattern(check, steps, outputs)
            addresses = [
                check(f"outputs[{i}]", check_address, banks={"Y", "C"})
                for i in range(len(self.outputs))
            ]
            check("current_step", check_address, banks={"DS"})
            flag = check("completion_flag", check_address, banks={"C"})
            _check_distinct_outputs(check, addresses, self.outputs, flag)
            # The checks of the list items depend on the kind, so skip them if it was refused.
            if not check.refused("kind"):
                for i, event in enumerate(self.events):
                    if event:
                        check(
                            f"events[{i}]",
                            _check_event,
                            label=f"Drum.events[{i}]",
                            typed=typed[i] if i < len(typed) else None,
                        )
                for i, preset in enumerate(self.presets):
                    if preset:
                        check(
                            f"presets[{i}]",
                            check_operand,
                            {"DS"},
                            _DURATION,
                            letter_first=True,
                            label=f"Drum.presets[{i}]",
                            bank_id="OBJ-004",
                        )
            if self.jump_enabled is True:
                check("jump_step", check_address, banks={"DS"})
            if not check.refused("kind"):
                if kind == "event_drum":
                    _refuse_blank_steps(
                        check,
                        "events",
                        [i for i, event in enumerate(self.events) if not event],
                        says("every step needs an event"),
                        "OBJ-021",
                        "Give each step an event, such as X001.",
                    )
                else:
                    self._check_timed(check, kind, steps, sizes_ok)

    def _freeze_pattern(self) -> None:
        """Store the pattern as a tuple of tuples, even if it was given as lists of lists.

        A pattern that can't be iterated stays as it is, so that the shape check finds it."""
        try:
            pattern = tuple(tuple(row) for row in self.pattern)
        except TypeError:
            return
        object.__setattr__(self, "pattern", pattern)

    def _check_pattern(self, check: Refusals, steps: int, outputs: int) -> None:
        """Refuse the pattern unless it has a row per step and a cell per output, each 0 or 1."""
        # The pattern is a tuple of tuples unless it, or a row of it, can't be iterated.
        if not isinstance(self.pattern, tuple) or not all(
            isinstance(row, tuple) for row in self.pattern
        ):
            check.refuse(
                "pattern",
                says(
                    "needs {steps} steps of {outputs} cells each, got {pattern}",
                    steps=steps,
                    outputs=outputs,
                    pattern=shown(self.pattern),
                ),
                Reason.FORM,
                code=Code.DRUM_PATTERN_SHAPE,
            )
            return
        if len(self.pattern) != steps or any(len(row) != outputs for row in self.pattern):
            check.refuse(
                "pattern",
                says(
                    "needs {steps} steps of {outputs} cells each, got {have} steps of "
                    "{sizes} cells",
                    steps=steps,
                    outputs=outputs,
                    have=len(self.pattern),
                    sizes=sorted({len(row) for row in self.pattern}),
                ),
                Reason.FORM,
                code=Code.DRUM_PATTERN_SHAPE,
            )
            return
        for row in self.pattern:
            for cell in row:
                if type(cell) is not int or cell not in (0, 1):
                    check.refuse(
                        "pattern",
                        says("{cell} is not allowed, cells are 0 or 1", cell=operand(cell)),
                        Reason.CHOICE,
                        code=Code.INVALID_CHOICE,
                    )
                    return

    def _check_timed(self, check: Refusals, kind: str, steps: int, sizes_ok: bool) -> None:
        """Check the fields that a time or time & event drum adds.

        These are the unit, the accumulator, and each step's duration and event."""
        if not is_choice(self.unit, _DRUM_UNIT_TO_INDEX):
            check.refuse(
                "unit",
                says(
                    "{unit} is not one of {units}",
                    unit=choice_operand(self.unit),
                    units=", ".join(_DRUM_UNIT_TO_INDEX),
                ),
                Reason.CHOICE,
                code=Code.INVALID_CHOICE,
            )
        check("accumulator", check_address, banks={"TD"})
        if kind == "time_drum":
            _refuse_blank_steps(
                check,
                "presets",
                [i for i, preset in enumerate(self.presets) if not preset],
                says("every step needs a duration"),
                "OBJ-022",
                "Give each step a duration, such as 100.",
            )
            return
        if not sizes_ok:
            return
        if len(self.events) != steps:
            check.refuse(
                ("events", "presets"),
                says(
                    "needs one event per step ({steps}), got {have}",
                    steps=steps,
                    have=len(self.events),
                ),
                Reason.CONFLICT,
                code=Code.DRUM_PATTERN_SHAPE,
            )
            return
        for i, (preset, event) in enumerate(zip(self.presets, self.events, strict=True)):
            if not preset and not event:
                check.refuse(
                    (f"presets[{i}]", f"events[{i}]"),
                    says("step {step} needs a duration or an event", step=i + 1),
                    Reason.MISSING,
                    "OBJ-1019",
                    code=Code.DRUM_STEP_EMPTY,
                    then=f"Give step {i + 1} a duration, such as 100, or an event, such as X001.",
                )

    @property
    def num_outputs(self) -> int:
        return len(self.outputs)

    @property
    def num_steps(self) -> int:
        return len(self.events if self.kind == "event_drum" else self.presets)

    @property
    def has_register_preset(self) -> bool:
        """True if this time or time & event drum reads a step's duration from a register."""
        return self.kind != "event_drum" and any(
            is_register_preset(preset) for preset in self.presets
        )

    @property
    def v4_blob(self) -> bool:
        """True if the drum is a time & event drum or a time drum with a register preset.

        Such a drum is written in v4's 82-field form."""
        return self.kind == "time_event_drum" or self.has_register_preset

    def to_csv(self) -> str:
        def listed(name: str, items: str) -> str:
            # A blank list is written blank, as in outputs=, so that it reads back blank.
            return "" if _is_blank(getattr(self, name)) else f"[{items}]"

        outputs_str = listed("outputs", ",".join(self.outputs))
        pattern_str = listed(
            "pattern", ",".join("[" + ",".join(str(v) for v in step) + "]" for step in self.pattern)
        )
        if self.kind == "event_drum":
            events_str = listed("events", ",".join(self.events))
            return (
                f"event_drum(outputs={outputs_str},"
                f"events={events_str},"
                f"pattern={pattern_str},"
                f"current_step={self.current_step},"
                f"completion_flag={self.completion_flag})"
            )
        if self.kind == "time_event_drum":
            return (
                f"time_event_drum(outputs={outputs_str},"
                f"presets={listed('presets', _format_optional_list(self.presets))},"
                f"events={listed('events', _format_optional_list(self.events))},"
                f"unit={self.unit},"
                f"pattern={pattern_str},"
                f"current_step={self.current_step},"
                f"accumulator={self.accumulator},"
                f"completion_flag={self.completion_flag})"
            )
        presets_str = listed("presets", ",".join(self.presets))
        return (
            f"time_drum(outputs={outputs_str},"
            f"presets={presets_str},"
            f"unit={self.unit},"
            f"pattern={pattern_str},"
            f"current_step={self.current_step},"
            f"accumulator={self.accumulator},"
            f"completion_flag={self.completion_flag})"
        )

    def cell_params(self) -> dict:
        # The cell's +0x0A byte (sub_rows) keeps the base height when OR legs make the
        # box taller.
        return {"visual_rows": self.pin_rows[-1] + 1, "sub_rows": 4}

    def pin_names(self) -> tuple[str, ...]:
        return (".reset", ".jump", ".jog")

    def pin_labels(self) -> tuple[str | None, ...]:
        return (
            ".reset()",
            f".jump({self.jump_step})" if self.jump_enabled else None,
            ".jog()" if self.jog_enabled else None,
        )

    def with_pins(self, pins: dict[str, tuple[str, ...]], pin_rows: tuple[int, ...]) -> Drum:
        if ".reset" not in pins:
            raise CsvReadError("Drum requires a .reset() pin row")
        drum = replace(self, pin_rows=cast(tuple[int, int, int], pin_rows))
        if ".jump" in pins:
            target = pins[".jump"][0] if pins[".jump"] else ""
            drum = replace(drum, jump_enabled=True, jump_step=target)
        if ".jog" in pins:
            drum = replace(drum, jog_enabled=True)
        return drum

    def _compute_func_codes(self) -> list[str]:
        """Return the 4 func-code slot values [base, reset, jump, jog].

        The codes run without a gap over the enabled pins.  With jump off, jog
        takes the code that jump would have had: 8496, not 8497.  CLICK v3 accepts
        either.  v4's syntax check rejects the gap with C000A ("All inputs of the box
        instruction must originate from the same branch").
        """
        if self.kind == "event_drum":
            if self.jog_enabled:
                base, reset = _EVENT_FC_JOG[0], _EVENT_FC_JOG[1]
                jump = _EVENT_FC_JOG[2] if self.jump_enabled else 0
                jog = _EVENT_FC_JOG[3] if self.jump_enabled else _EVENT_FC_JOG[2]
            else:
                base, reset = _EVENT_FC_NO_JOG[0], _EVENT_FC_NO_JOG[1]
                jump = _EVENT_FC_NO_JOG[2] if self.jump_enabled else 0
                jog = 0
            return [str(base), str(reset), str(jump), str(jog)]
        if self.kind == "time_event_drum":
            block_base = _TIME_EVENT_FC_BASE.get(self.unit, 0)
        else:
            block_base = _TIME_FC_BASE.get(self.unit, 0)
            if block_base and self.has_register_preset:
                block_base += _REGISTER_PRESET_FC_OFFSET
        if not block_base:
            raise EncodeError(f"Unsupported {self.kind} unit: {self.unit!r}")
        # Each time unit's block has the event drum's shape.  The no-jog group (base,
        # reset, jump) comes first, then the jog group (base, reset, jump, jog).
        if self.jog_enabled:
            jog_base = block_base + 3 + (_TH_JOG_SKIP if self.unit == "Th" else 0)
            base, reset = jog_base, jog_base + 1
            jump = jog_base + 2 if self.jump_enabled else 0
            jog = jog_base + 3 if self.jump_enabled else jog_base + 2
        else:
            base, reset = block_base, block_base + 1
            jump = block_base + 2 if self.jump_enabled else 0
            jog = 0
        return [str(base), str(reset), str(jump), str(jog)]

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this drum cell."""
        from ..binary_helpers import _tagged_field, _utf16le_null, _variant_tagged_field
        from ..model import InstructionType

        type_marker = 0x2700 | InstructionType.DRUM

        out = bytearray()
        out += _utf16le_null("Drum")
        out += struct.pack("<I", type_marker)
        out += struct.pack("<H", 4)  # part count
        out += bytes(self.pin_rows)  # one extra part byte per pin, holding its row
        time_event = self.kind == "time_event_drum"
        out += struct.pack("<I", 82 if self.v4_blob else 64)  # field count

        # Fields 0-3: func codes (sub-indexed 0x3A05)
        func_codes = self._compute_func_codes()
        for i, fc in enumerate(func_codes):
            out += _variant_tagged_field(0x3A05, struct.pack("<I", i), fc)

        # Field 4: drum base (0=time, 1=event, 2=time & event)
        base = {
            "time_drum": _BASE_TIME,
            "event_drum": _BASE_EVENT,
            "time_event_drum": _BASE_TIME_EVENT,
        }
        out += _tagged_field(0x2200, base[self.kind])

        # Field 5: time unit index
        unit_idx = _DRUM_UNIT_TO_INDEX.get(self.unit, "0") if self.kind != "event_drum" else "0"
        out += _tagged_field(0x21F9, unit_idx)

        # Fields 6-7: num_steps, num_outputs
        out += _tagged_field(0x3203, str(self.num_steps))
        out += _tagged_field(0x3204, str(self.num_outputs))

        # Field 8: current_step
        out += _tagged_field(0x606E, self.current_step)

        # Field 9: accumulator (time drum: TD address, event: empty)
        out += _tagged_field(0x606F, self.accumulator)

        # Field 10: completion_flag
        out += _tagged_field(0x6070, self.completion_flag)

        # Field 11: jog enabled
        out += _tagged_field(0x1201, "-1" if self.jog_enabled else "0")

        # Field 12: jump enabled
        out += _tagged_field(0x1202, "-1" if self.jump_enabled else "0")

        # Field 13: jump target
        out += _tagged_field(0x6071, self.jump_step)

        # Fields 14-29: events/presets (sub-indexed 0x6872, 16 slots).  A time & event
        # drum stores its events here and its presets in 0x6891.
        step_values = self.presets if self.kind == "time_drum" else self.events
        for i in range(16):
            value = step_values[i] if i < len(step_values) else ""
            out += _variant_tagged_field(0x6872, struct.pack("<I", i), value)

        # Fields 30-45: pattern bitmasks (sub-indexed 0x3A26, 16 slots)
        bitmasks = _pattern_to_bitmasks(self.pattern, self.num_steps)
        for i in range(16):
            out += _variant_tagged_field(0x3A26, struct.pack("<I", i), bitmasks[i])

        # Fields 46-61: outputs (sub-indexed 0x6873, 16 slots)
        for i in range(16):
            value = self.outputs[i] if i < self.num_outputs else ""
            out += _variant_tagged_field(0x6873, struct.pack("<I", i), value)

        # Field 62: visual rows marker
        out += _tagged_field(0x20CA, "2")

        if self.v4_blob:
            # Fields 63-78: a time & event drum's presets (sub-indexed 0x6891, 16
            # slots).  A time drum stores its presets in 0x6872 and leaves these blank.
            for i in range(16):
                value = self.presets[i] if time_event and i < self.num_steps else ""
                out += _variant_tagged_field(0x6891, struct.pack("<I", i), value)
            # Field 79: which presets are constants.  When the rung is pasted, CLICK
            # keeps the value as written, and a missing tag counts as -1.  A time drum's
            # func code series follows the value.
            out += _tagged_field(0x428A, _constant_preset_mask(self.presets))
            # Field 80: the done bit of the accumulator's timer (TD101 -> T101)
            try:
                done_bit = _timer_done_bit(self.accumulator)
            except CsvReadError as exc:  # The accumulator was changed after the drum was built.
                raise EncodeError(str(exc)) from exc
            out += _tagged_field(0x6068, done_bit)

        # Last field: terminator
        out += _tagged_field(0x0000, "")

        return bytes(out)


# ---------------------------------------------------------------------------
# Shared from_tags factory
# ---------------------------------------------------------------------------

_DRUM_TYPE_CODE = 0x271B


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Drum | None:
    """Build a Drum from tag data, or return None.

    The clipboard decoder and the program file decoder both call this.
    """
    if class_name != "Drum" or type_code != _DRUM_TYPE_CODE:
        return None

    # Tag 0x2200 is the drum base: 0 or absent for time, 1 for event, and 2 for time &
    # event (CLICK v4, with events in 0x6872 and presets in 0x6891).  For any other base,
    # return None so that the blob stays a RawInstruction and its step slots are not
    # misread.
    base = tag_value(tags, 0x2200)
    if base not in (_BASE_TIME, _BASE_EVENT, _BASE_TIME_EVENT):
        return None

    variant_u16 = variant_u16_tags or {}
    variant_strings = variant_string_tags or {}

    current_step = tag_value(tags, 0x606E)
    completion_flag = tag_value(tags, 0x6070)

    outputs_by_idx = variant_strings.get(0x6873, {})
    events_by_idx = variant_strings.get(0x6872, {})
    bitmasks_by_idx = variant_u16.get(0x3A26, {})

    num_steps = tag_int(tags, 0x3203)
    num_outputs = tag_int(tags, 0x3204)

    if num_steps <= 0 or num_outputs <= 0 or not current_step or not completion_flag:
        return None

    if base == _BASE_TIME_EVENT:
        presets_by_idx = variant_strings.get(0x6891, {})
        outputs = tuple(outputs_by_idx.get(i, "") for i in range(num_outputs))
        unit = _DRUM_INDEX_TO_UNIT.get(tag_value(tags, 0x21F9))
        accumulator = tag_value(tags, 0x606F)
        if any(not value for value in outputs) or unit is None or not accumulator:
            return None
        return Drum(
            kind="time_event_drum",
            outputs=outputs,
            presets=tuple(presets_by_idx.get(i, "") for i in range(num_steps)),
            events=tuple(events_by_idx.get(i, "") for i in range(num_steps)),
            pattern=tuple(
                tuple((bitmasks_by_idx.get(s, 0) >> o) & 1 for o in range(num_outputs))
                for s in range(num_steps)
            ),
            current_step=current_step,
            completion_flag=completion_flag,
            accumulator=accumulator,
            unit=unit,
            jog_enabled=tag_flag(tags, 0x1201),
            jump_enabled=tag_flag(tags, 0x1202),
            jump_step=tag_value(tags, 0x6071),
        )

    outputs = tuple(outputs_by_idx.get(i, "") for i in range(num_outputs))
    step_values = tuple(events_by_idx.get(i, "") for i in range(num_steps))
    if any(not value for value in outputs) or any(not value for value in step_values):
        return None

    pattern = tuple(
        tuple(
            (bitmasks_by_idx.get(step_idx, 0) >> output_idx) & 1
            for output_idx in range(num_outputs)
        )
        for step_idx in range(num_steps)
    )

    if base == _BASE_EVENT:
        return Drum(
            kind="event_drum",
            outputs=outputs,
            events=step_values,
            pattern=pattern,
            current_step=current_step,
            completion_flag=completion_flag,
            jog_enabled=tag_flag(tags, 0x1201),
            jump_enabled=tag_flag(tags, 0x1202),
            jump_step=tag_value(tags, 0x6071),
        )

    unit = _DRUM_INDEX_TO_UNIT.get(tag_value(tags, 0x21F9), "Tms")
    accumulator = tag_value(tags, 0x606F)
    if not accumulator:
        return None
    return Drum(
        kind="time_drum",
        outputs=outputs,
        presets=step_values,
        pattern=pattern,
        current_step=current_step,
        completion_flag=completion_flag,
        accumulator=accumulator,
        unit=unit,
        jog_enabled=tag_flag(tags, 0x1201),
        jump_enabled=tag_flag(tags, 0x1202),
        jump_step=tag_value(tags, 0x6071),
    )


# ---------------------------------------------------------------------------
# CSV parser
# ---------------------------------------------------------------------------


def _list_arg(call: AfCall, key: str, parse: Callable[[str], _L]) -> _L:
    """Return the list in keyword *key* of *call*, read with *parse*.

    An absent keyword reads as an empty list.  A blank one, as in ``outputs=``, reads as
    ``""``.  The Drum refuses ``""`` as missing."""
    text = call.kwargs.get(key, "[]")
    return parse(text) if text else cast("_L", "")


def parse_af_call(call: AfCall) -> Drum:
    """Parse an AF AST call into a Drum.

    Raise ``CsvReadError`` if the call lacks a keyword it needs, such as ``unit`` or a
    time & event drum's ``accumulator``.  A value that the Drum refuses raises the Drum's
    ``FieldError``.  The Drum refuses a blank value, such as ``unit=``, as missing."""
    outputs = _list_arg(call, "outputs", _parse_simple_list)
    # A cell that is not 0 or 1 stays text, which the Drum refuses.
    pattern = cast("tuple[tuple[int, ...], ...]", _list_arg(call, "pattern", _parse_pattern))
    current_step = call.kwargs.get("current_step", "")
    completion_flag = call.kwargs.get("completion_flag", "")

    if call.name == "event_drum":
        return Drum(
            kind="event_drum",
            outputs=outputs,
            events=_list_arg(call, "events", _parse_simple_list),
            pattern=pattern,
            current_step=current_step,
            completion_flag=completion_flag,
            # The Drum refuses a unit on an event drum.
            unit=cast("TimeUnit | Literal['']", call.kwargs.get("unit", "")),
        )

    if "unit" not in call.kwargs:
        raise CsvReadError(f"{call.name} needs unit=")
    # The Drum refuses a unit that is not a TimeUnit.
    unit = cast("TimeUnit | Literal['']", call.kwargs["unit"])
    accumulator = call.kwargs.get("accumulator", "")

    if call.name == "time_event_drum":
        presets = _list_arg(call, "presets", _parse_optional_list)
        events = _list_arg(call, "events", _parse_optional_list)
        if not _is_blank(presets) and not _is_blank(events) and len(presets) != len(events):
            raise CsvReadError(
                f"time_event_drum needs one preset and one event per step "
                f"(None for unused): {len(presets)} presets, {len(events)} events"
            )
        if "accumulator" not in call.kwargs:
            raise CsvReadError("time_event_drum needs accumulator=")
        return Drum(
            kind="time_event_drum",
            outputs=outputs,
            presets=presets,
            events=events,
            pattern=pattern,
            current_step=current_step,
            completion_flag=completion_flag,
            accumulator=accumulator,
            unit=unit,
        )

    return Drum(
        kind="time_drum",
        outputs=outputs,
        presets=_list_arg(call, "presets", _parse_simple_list),
        pattern=pattern,
        current_step=current_step,
        completion_flag=completion_flag,
        accumulator=accumulator,
        unit=unit,
    )


SPEC = AfInstructionFamilySpec(
    family_name="drum",
    instruction_types=(Drum,),
    binary_class_names=("Drum",),
    from_tags=from_tags,
    csv_names=("event_drum", "time_drum", "time_event_drum"),
    parse_csv_call=parse_af_call,
    pin_names=(".reset", ".jump", ".jog"),
)
