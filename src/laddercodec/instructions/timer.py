"""The Timer instruction.

CLICK stores a timer with the binary class name ``"Tmr"`` and the type marker 0x2718. A
timer is ``on_delay`` or ``off_delay``. A separate flag, ``retained``, makes an on-delay
timer retentive.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal, cast, get_args

from ..binary_helpers import tag_int, tag_value
from ..codes import Code
from ..errors import CsvReadError
from ..model import PinnedInstruction, Reason, check_address
from ..operands.checks import Constants, Refusals, check_operand
from ..operands.constants import INT16_MAX, Kind
from ..operands.message import Op, operand, says
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

TimerKind = Literal["on_delay", "off_delay"]
"""The kind of a timer. Each kind is also the name of its CSV call."""

TimeUnit = Literal["Tms", "Ts", "Tm", "Th", "Td"]
"""The time unit of a timer or a drum: milliseconds, seconds, minutes, hours or days."""

_TIMER_KINDS: tuple[TimerKind, ...] = get_args(TimerKind)

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

#: The CSV name of each timer unit, by the unit index that tag 0x21F9 stores. The units are
#: milliseconds, seconds, minutes, hours and days.
TIMER_UNITS: dict[str, TimeUnit] = {
    "0": "Tms",
    "1": "Ts",
    "2": "Tm",
    "3": "Th",
    "4": "Td",
}

#: Timer unit name → unit index string.
TIMER_UNIT_TO_INDEX: dict[TimeUnit, str] = {v: k for k, v in TIMER_UNITS.items()}

# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

#: A constant preset is digits only, with no sign, from 0 to 32767, whatever the unit.
#: CLICK refuses a digits-only value above 0x7fff with OBJ-005, whatever the unit.
_PRESET = Constants(frozenset({Kind.INTEGER}), signs="", low=0, high=INT16_MAX)

_TIMER_STD_TAGS = (0x6068, 0x606A, 0x6069, 0x21F9, 0x21FA, 0x21FB)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Timer(PinnedInstruction):
    """An on-delay or off-delay timer instruction.

    The timer sits in the AF column. CLICK stores it with the binary class name ``Tmr``
    and the type marker 0x2718. The box spans the grid rows from its own row down to the
    row of the reset input, which ``pin_rows`` gives, so it is at least two rows tall.
    """

    kind: TimerKind
    done: str  # e.g. "T1"
    accumulator: str  # accumulator register, e.g. "TD1"
    preset: str  # preset value or operand, e.g. "1" or "DS1"
    unit: TimeUnit
    retained: bool = False  # True = retentive (RTON)
    #: The row of the reset input within the box. Rows of OR branches under the
    #: enable input of a retentive timer push the reset input down. A timer without
    #: ``.reset()`` is always 2 rows tall, and the OR branch rows of its enable input
    #: sit beside and below the box.
    pin_rows: tuple[int, ...] = (1,)

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            check.flag("retained")
            if self.kind not in _TIMER_KINDS:
                check.refuse(
                    "kind",
                    says("{kind} is not on_delay or off_delay", kind=operand(self.kind)),
                    Reason.CHOICE,
                    code=Code.INVALID_CHOICE,
                )
            if self.unit not in tuple(TIMER_UNIT_TO_INDEX):
                units = ", ".join(TIMER_UNIT_TO_INDEX)
                check.refuse(
                    "unit",
                    says("{unit} is not one of {units}", unit=operand(self.unit), units=units),
                    Reason.CHOICE,
                    code=Code.INVALID_CHOICE,
                )
            check.normalize("done", "accumulator", "preset", values=("preset",))
            done = check("done", check_address, banks={"T"})
            accumulator = check("accumulator", check_address, banks={"TD"})
            if done is not None and accumulator is not None and done.number != accumulator.number:
                check.refuse(
                    ("accumulator", "done"),
                    says(
                        "{accumulator} must be {td} to match Timer.done {done}",
                        accumulator=Op(self.accumulator),
                        td=Op(f"TD{done.number}", quoted=False),
                        done=Op(self.done),
                    ),
                    Reason.CONFLICT,
                    code=Code.TIMER_PAIR_MISMATCH,
                )
            # A preset address must be in DS. CLICK refuses any other bank with OBJ-004.
            check("preset", check_operand, {"DS"}, _PRESET, bank_id="OBJ-004")
            if self.kind == "off_delay" and self.retained:
                check.refuse(
                    ("retained", "kind"),
                    says("an off_delay timer can't be retentive"),
                    Reason.CONFLICT,
                    code=Code.OPTION_NOT_OFFERED,
                    then=(
                        "Use on_delay for a retentive timer. Otherwise remove the .reset() row, "
                        "or set retained=False."
                    ),
                )
            check.run(self._check_pin_rows)

    @classmethod
    def from_csv_token(cls, token: str) -> Timer:
        """Parse a timer token such as ``on_delay(T1,TD1,preset=1000,unit=Tms)``.

        The positional arguments are done and accumulator. The keyword arguments are
        preset and unit. The token never names ``retained``. A ``.reset()`` pin row makes
        the timer retentive.
        """
        token = token.strip()
        m = re.fullmatch(r"(on_delay|off_delay)\((.+)\)", token)
        if not m:
            raise CsvReadError(
                f"Could not read {token!r} as a timer. Write it as "
                "on_delay(done,accumulator,preset=...,unit=...) or off_delay(...), such as "
                "on_delay(T1,TD1,preset=1000,unit=Tms)."
            )
        kind = cast(TimerKind, m.group(1))
        args: list[str] = []
        kwargs: dict[str, str] = {}
        for seg in (a.strip() for a in m.group(2).split(",")):
            if "=" in seg:
                k, v = seg.split("=", 1)
                kwargs[k.strip()] = v.strip()
            else:
                args.append(seg)
        if len(args) != 2:
            raise CsvReadError(
                f"{kind} expects 2 positional args (done, accumulator), got {len(args)}: {token!r}"
            )
        done, accumulator = args
        if "preset" not in kwargs or "unit" not in kwargs:
            raise CsvReadError(f"{kind} missing preset or unit kwargs: {token!r}")
        # The Timer refuses a blank preset or unit as missing.
        preset = kwargs["preset"]
        unit = kwargs["unit"]
        return cls(
            kind=kind,
            done=done,
            accumulator=accumulator,
            preset=preset,
            unit=cast(TimeUnit, unit),  # the Timer refuses a unit that is not a TimeUnit
            retained=False,
        )

    @property
    def unit_idx(self) -> str:
        return TIMER_UNIT_TO_INDEX[self.unit]

    @property
    def enable_func_code(self) -> str:
        """Return the func code of the enable input.

        It is 8717 plus 6 times the unit index, plus 1 for an off-delay timer or 2 for a
        retentive on-delay timer.
        """
        base = 8717 + int(self.unit_idx) * 6
        if self.kind == "on_delay":
            return str(base + (2 if self.retained else 0))
        return str(base + 1)  # off_delay

    @property
    def reset_func_code(self) -> str:
        """Return the func code of the reset input.

        For a retentive timer it is 8717 plus 6 times the unit index, plus 3. For any other
        timer it is ``"0"``.
        """
        if not self.retained:
            return "0"
        base = 8717 + int(self.unit_idx) * 6
        return str(base + 3)

    def to_csv(self) -> str:
        return f"{self.kind}({self.done},{self.accumulator},preset={self.preset},unit={self.unit})"

    def cell_params(self) -> dict:
        """Return the ``ClickCell`` keyword arguments that the timer sets: the box's height
        in grid rows and its number of sub-rows."""
        return {"visual_rows": self.pin_rows[-1] + 1, "sub_rows": 2}

    def pin_names(self) -> tuple[str, ...]:
        return (".reset",)

    def pin_labels(self) -> tuple[str | None, ...]:
        return (".reset()" if self.retained else None,)

    def with_pins(self, pins: dict[str, tuple[str, ...]], pin_rows: tuple[int, ...]) -> Timer:
        return replace(self, retained=".reset" in pins, pin_rows=cast(tuple[int], pin_rows))

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this timer cell."""
        from ..binary_helpers import _tagged_field, _utf16le_null, _variant_tagged_field
        from ..model import InstructionType

        type_marker = 0x2700 | InstructionType.TIMER

        out = bytearray()
        out += _utf16le_null("Tmr")
        out += struct.pack("<I", type_marker)
        out += b"\x02\x00"  # part count (differs from contact/coil's 01 00)
        out += bytes(self.pin_rows)  # extra part byte: the reset input's row
        out += struct.pack("<I", 9)  # field count

        # Fields 0–5: standard tagged fields.
        std_values = [
            self.done,
            self.preset,
            self.accumulator,
            self.unit_idx,
            "0" if self.kind == "on_delay" else "1",
            "1" if self.retained else "0",
        ]
        for tag, value in zip(_TIMER_STD_TAGS, std_values, strict=True):
            out += _tagged_field(tag, value)

        # Fields 6–7: variant format [2B tag][4B sub-marker][UTF-16LE value].
        out += _variant_tagged_field(0x3A05, b"\x00\x00\x00\x00", self.enable_func_code)
        out += _variant_tagged_field(0x3A05, b"\x01\x00\x00\x00", self.reset_func_code)

        # Field 8: empty sentinel field.
        out += _tagged_field(0x0000, "")

        return bytes(out)


# ---------------------------------------------------------------------------
# Shared from_tags factory
# ---------------------------------------------------------------------------

_TIMER_TYPE_CODE = 0x2718


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Timer | None:
    """Construct a Timer from the tags of a decoded blob.

    Return None if the blob is not a timer, lacks a field, stores a time unit that is not
    known, or is a retentive off-delay timer. The clipboard and program-file decoders both
    use it.
    """
    if class_name != "Tmr" or type_code != _TIMER_TYPE_CODE:
        return None
    done = tag_value(tags, 0x6068)
    preset = tag_value(tags, 0x606A)
    accumulator = tag_value(tags, 0x6069)
    unit_idx = tag_value(tags, 0x21F9)
    unit = TIMER_UNITS.get(unit_idx)
    if not done or not accumulator or not preset or unit is None:
        return None
    # A program file (SCR) leaves out 0x21FA for an on-delay timer and stores it for an
    # off-delay timer. The clipboard stores the byte 0 for on-delay and 1 for off-delay.
    kind = "off_delay" if tag_int(tags, 0x21FA) != 0 else "on_delay"
    retained = tag_int(tags, 0x21FB) != 0
    if kind == "off_delay" and retained:
        return None  # CLICK's dialog never writes this, so the decoder keeps the raw blob
    return Timer(
        kind=kind,
        done=done,
        accumulator=accumulator,
        preset=preset,
        unit=unit,
        retained=retained,
    )


def parse_af_call(call: AfCall) -> Timer:
    """Parse an AF AST call into a Timer."""
    return Timer.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="timer",
    instruction_types=(Timer,),
    binary_class_names=("Tmr",),
    from_tags=from_tags,
    csv_names=("on_delay", "off_delay"),
    parse_csv_call=parse_af_call,
    pin_names=(".reset",),
)
