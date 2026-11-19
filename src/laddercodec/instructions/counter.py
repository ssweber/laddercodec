"""Cnt — counter instructions (type marker 0x2719).

In the binary, the class name is ``"Cnt"``.

laddercodec supports three forms of counter.  Each is stored with the mode shown:

- ``count_up(...)+.reset()``            -> mode 0
- ``count_up(...)+.down()+.reset()``    -> mode 2
- ``count_down(...)+.reset()``          -> mode 1
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal, cast, get_args

from ..binary_helpers import tag_int, tag_value
from ..codes import Code
from ..errors import CsvReadError, EncodeError
from ..model import InstructionType, PinnedInstruction, Reason, check_address
from ..operands.checks import Constants, Refusals, check_operand
from ..operands.constants import Kind
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

CounterKind = Literal["count_up", "count_down"]
"""The kind of a counter. Each kind is also the name of its CSV call."""

_COUNTER_KINDS: tuple[CounterKind, ...] = get_args(CounterKind)

# ---------------------------------------------------------------------------
# Variant encodings
# ---------------------------------------------------------------------------

# (kind, down_enabled, reset_enabled) -> (mode, up_fc, down_fc, reset_fc)
_VARIANT_TO_ENCODING: dict[tuple[str, bool, bool], tuple[str, str, str, str]] = {
    ("count_up", False, True): ("0", "8710", "0", "8711"),
    ("count_up", True, True): ("2", "8713", "8714", "8715"),
    ("count_down", False, True): ("1", "0", "8747", "8748"),
}

# Reverse: (mode, up_fc, down_fc, reset_fc) -> (kind, down_enabled, reset_enabled)
_ENCODING_TO_VARIANT: dict[tuple[str, str, str, str], tuple[str, bool, bool]] = {
    v: k for k, v in _VARIANT_TO_ENCODING.items()
}

# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

#: A constant set point is a 32-bit signed integer written in under 13 characters.
#: CLICK reports OBJ-005 if the value does not fit in 32 bits or the text is 13 characters
#: or longer.  A '-' may only come first, so ``1-2`` is refused.
_PRESET = Constants(frozenset({Kind.INTEGER}), signs="-", max_length=12)

#: The banks a preset register may be in.  CLICK reports OBJ-004 for any other bank.
COUNTER_PRESET_BANKS = frozenset({"DS", "DD"})

_COUNTER_STD_TAGS = (0x606B, 0x606A, 0x606C, 0x606D, 0x21FC)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Counter(PinnedInstruction):
    """A counter instruction (count_up / count_down)."""

    kind: CounterKind
    done: str
    accumulator: str
    preset: str
    down_enabled: bool = False
    reset_enabled: bool = True
    #: The rows of the Down and Reset inputs, counted from the box's top row,
    #: which is row 0.  count_up's Up input is on row 0.  count_down's main
    #: input is Down, on row 1 under its unused Up.  OR legs under an input
    #: push every later input down, ``.reset()`` included.
    pin_rows: tuple[int, ...] = (1, 2)

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            if self.kind not in _COUNTER_KINDS:
                check.refuse(
                    "kind",
                    f"{self.kind!r} is not count_up or count_down",
                    Reason.CHOICE,
                    code=Code.INVALID_CHOICE,
                )
            check.flag("down_enabled", "reset_enabled")
            if self.reset_enabled is False:
                check.refuse(
                    "reset_enabled",
                    "a counter always has a Reset input",
                    Reason.CHOICE,
                    code=Code.INVALID_CHOICE,
                )
            if self.down_enabled is True and self.kind == "count_down":
                # count_down's main input is Down.  Its box has no separate .down() input.
                check.refuse(
                    ("down_enabled", "kind"),
                    "count_down has no .down() input; only count_up does",
                    Reason.CONFLICT,
                    code=Code.OPTION_NOT_OFFERED,
                )
            check.normalize("done", "accumulator", "preset")
            done = check("done", check_address, banks={"CT"})
            accumulator = check("accumulator", check_address, banks={"CTD"})
            if done is not None and accumulator is not None and done.number != accumulator.number:
                check.refuse(
                    ("accumulator", "done"),
                    f"{self.accumulator!r} must be CTD{done.number} to match Counter.done "
                    f"{self.done!r}",
                    Reason.CONFLICT,
                    code=Code.TIMER_PAIR_MISMATCH,
                )
            check(
                "preset",
                check_operand,
                COUNTER_PRESET_BANKS,
                _PRESET,
                letter_first=True,
                bank_id="OBJ-004",
            )
            check.run(self._check_pin_rows)

    @property
    def lead_rows(self) -> int:
        return 1 if self.kind == "count_down" else 0

    def pin_names(self) -> tuple[str, ...]:
        return (".reset",) if self.kind == "count_down" else (".down", ".reset")

    def pin_labels(self) -> tuple[str | None, ...]:
        reset = ".reset()" if self.reset_enabled else None
        if self.kind == "count_down":
            return (reset,)
        return (".down()" if self.down_enabled else None, reset)

    def with_pins(self, pins: dict[str, tuple[str, ...]], pin_rows: tuple[int, ...]) -> Counter:
        if ".reset" not in pins:
            raise CsvReadError(f"{self.kind} requires a .reset() pin row")
        return replace(
            self,
            reset_enabled=True,
            down_enabled=".down" in pins,
            pin_rows=cast(tuple[int, int], pin_rows),
        )

    @classmethod
    def from_csv_token(cls, token: str) -> Counter:
        """Parse a CSV v1 counter token, such as ``count_up(CT1,CTD1,preset=100)``."""
        token = token.strip()
        m = re.fullmatch(r"(count_up|count_down)\((.+)\)", token)
        if not m:
            raise CsvReadError(
                f"Could not read {token!r} as a counter. Write it as "
                "count_up(done,accumulator,preset=...) or count_down(...), such as "
                "count_up(CT1,CTD1,preset=100)."
            )

        kind = cast(CounterKind, m.group(1))
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

        preset = kwargs.get("preset", "")
        if not preset:
            raise CsvReadError(f"{kind} missing preset kwarg: {token!r}")

        return cls(
            kind=kind,
            done=args[0],
            accumulator=args[1],
            preset=preset,
        )

    @property
    def mode_and_func_codes(self) -> tuple[str, str, str, str]:
        key = (self.kind, self.down_enabled, self.reset_enabled)
        result = _VARIANT_TO_ENCODING.get(key)
        if result is None:
            raise EncodeError(
                "Unsupported counter variant: "
                f"{self.kind}(down={self.down_enabled}, reset={self.reset_enabled})"
            )
        return result

    def to_csv(self) -> str:
        return f"{self.kind}({self.done},{self.accumulator},preset={self.preset})"

    def cell_params(self) -> dict:
        return {
            "visual_rows": self.pin_rows[-1] + 1,
            "sub_rows": 3,
            # CLICK stores 0 at +0x1D in row 0 of a count_down AF cell, and 1 for count_up.
            "wire_right": 0 if self.kind == "count_down" else 1,
        }

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this counter cell."""
        from ..binary_helpers import _tagged_field, _utf16le_null, _variant_tagged_field

        mode, up_fc, down_fc, reset_fc = self.mode_and_func_codes

        type_marker = 0x2700 | InstructionType.COUNTER

        out = bytearray()
        out += _utf16le_null("Cnt")
        out += struct.pack("<I", type_marker)
        out += b"\x03\x00"  # part count
        out += bytes(self.pin_rows)  # extra part bytes: each pin's row
        out += struct.pack("<I", 9)  # field count

        std_values = [
            self.done,
            self.preset,
            self.accumulator,
            self.done,
            mode,
        ]
        for tag, value in zip(_COUNTER_STD_TAGS, std_values, strict=True):
            out += _tagged_field(tag, value)

        out += _variant_tagged_field(0x3A05, b"\x00\x00\x00\x00", up_fc)
        out += _variant_tagged_field(0x3A05, b"\x01\x00\x00\x00", down_fc)
        out += _variant_tagged_field(0x3A05, b"\x02\x00\x00\x00", reset_fc)
        out += _tagged_field(0x0000, "")

        return bytes(out)


# ---------------------------------------------------------------------------
# Shared from_tags factory
# ---------------------------------------------------------------------------

_COUNTER_TYPE_CODE = 0x2719

# Mode byte value → (kind, down_enabled, reset_enabled).
_MODE_TO_VARIANT: dict[int, tuple[CounterKind, bool, bool]] = {
    0: ("count_up", False, True),
    1: ("count_down", False, True),
    2: ("count_up", True, True),
}


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Counter | None:
    """Build a Counter from tag data, or return None if the tags are not a counter's.

    The clipboard decoder and the program-file decoder both call it.
    """
    if class_name != "Cnt" or type_code != _COUNTER_TYPE_CODE:
        return None
    done = tag_value(tags, 0x606B)
    preset = tag_value(tags, 0x606A)
    accumulator = tag_value(tags, 0x606C)
    mode = tag_int(tags, 0x21FC)
    variant = _MODE_TO_VARIANT.get(mode)
    if not all([done, preset, accumulator]) or variant is None:
        return None
    kind, down_enabled, reset_enabled = variant
    return Counter(
        kind=kind,
        done=done,
        accumulator=accumulator,
        preset=preset,
        down_enabled=down_enabled,
        reset_enabled=reset_enabled,
    )


def parse_af_call(call: AfCall) -> Counter:
    """Parse an AF AST call into a Counter."""
    return Counter.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="counter",
    instruction_types=(Counter,),
    binary_class_names=("Cnt",),
    from_tags=from_tags,
    csv_names=("count_up", "count_down"),
    parse_csv_call=parse_af_call,
    pin_names=(".down", ".reset"),
)
