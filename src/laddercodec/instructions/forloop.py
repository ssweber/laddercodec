"""For/Next loop instructions (type markers 0x2725 and 0x2726).

Binary class names:
    - ``"For"``
    - ``"Next"`` (also CLICK v4's Break and Continue, told apart by func code)

CSV forms:
    - ``for(3)``
    - ``for(DS1,oneshot=1)``
    - ``next()``
    - ``break()``
    - ``continue()``
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..binary_helpers import tag_flag, tag_value
from ..codes import Code
from ..errors import CsvReadError
from ..model import FieldError, Instruction, InstructionType, Reason, normalize_address
from ..operands.address import require_text
from ..operands.checks import Constants, Refusals, check_csv_flag, check_operand
from ..operands.constants import INT32_MAX, Kind
from ..operands.message import Op, make_refusal, says
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

FOR_TYPE_MARKER = 0x2700 | InstructionType.FOR_LOOP
NEXT_TYPE_MARKER = 0x2700 | InstructionType.NEXT

_FOR_FUNC_CODES: dict[bool, str] = {
    False: "9218",
    True: "9219",
}
_FOR_TAGS = (0x6065, 0x3218, 0x11F8, 0x0000)
#: A constant count is digits only, from 0 to 2147483647, with no sign. The one exception is
#: a minus sign before zero (``-0``), which is stored as ``0``. Any other constant is refused
#: with OBJ-005. A register count must be a DS, DD, TD, CTD or SD address. Any
#: other bank is refused with OBJ-004.
_FOR_SPACED_RE = re.compile(r"[0-9]+(\s+[0-9]+)+")
FOR_LIMIT_BANKS = frozenset({"DS", "DD", "TD", "CTD", "SD"})
_FOR_LIMIT_CONSTANTS = Constants(frozenset({Kind.INTEGER}), signs="", low=0, high=INT32_MAX)

# Func codes of binary class "Next", in tag 0x3218.  CLICK v3 writes a Next with no func
# code, and v4 writes 9220.
_NEXT_FUNC_CODE = "9220"
_CONTINUE_FUNC_CODE = "9232"
_BREAK_FUNC_CODE = "9233"
_LOOP_EXIT_TAGS = (0x3218, 0x0000)

_FOR_FORM = (
    "Could not read {token!r} as a For instruction. Write it as for(count), or "
    "for(count,oneshot=1)."
)


def _normalized_count(value: str) -> str:
    """Return *value* without the spaces at either end, in display form if it is an address,
    and as ``0`` if it is ``-0``. Raise :class:`FieldError` if it is blank or has a space
    inside it."""
    text = require_text(value, "ForLoop.count", what="the count").strip()
    if not text:
        raise make_refusal(
            FieldError,
            "ForLoop.count",
            says("The count is blank"),
            field="ForLoop.count",
            reason=Reason.MISSING,
            code=Code.BLANK_FIELD,
            then="Enter a number of loops, or an address that holds one.",
        )
    if _FOR_SPACED_RE.fullmatch(text):
        # CLICK's dialog accepts ``1 0``.  It is not a number, so laddercodec refuses it.
        raise make_refusal(
            FieldError,
            "ForLoop.count",
            says("{text} has a space in it", text=Op(text)),
            field="ForLoop.count",
            reason=Reason.FORM,
            code=Code.INVALID_CONSTANT,
            then="Write the count as digits only, such as 10.",
        )
    if len(text) > 1 and text[0] == "-" and not text[1:].strip("0"):
        return "0"
    return normalize_address(text, "ForLoop.count")


def _check_for_count(text: str) -> None:
    """Raise :class:`FieldError` if CLICK's For dialog refuses *text*, a count in display
    form."""
    check_operand(
        text,
        "ForLoop.count",
        FOR_LIMIT_BANKS,
        _FOR_LIMIT_CONSTANTS,
        bank_id="OBJ-004",
        bank_code=Code.FOR_COUNT_BANK,
    )


@dataclass(frozen=True)
class ForLoop(Instruction):
    """FOR loop instruction."""

    count: str
    oneshot: bool = False

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            # Write the count in display form before the bank check, so that a count that
            # the check refuses, such as ``x1``, is held as ``X001``.
            count = check.run(_normalized_count, self.count)
            if count is not None:
                object.__setattr__(self, "count", count)
                check.run(_check_for_count, count)
            check.flag("oneshot")

    @classmethod
    def from_csv_token(cls, token: str) -> ForLoop:
        token = token.strip()
        m = re.fullmatch(r"for\((.+)\)", token)
        if not m:
            raise CsvReadError(_FOR_FORM.format(token=token))

        args: list[str] = []
        kwargs: dict[str, str] = {}
        for seg in (a.strip() for a in m.group(1).split(",")):
            if "=" in seg:
                k, v = seg.split("=", 1)
                kwargs[k.strip()] = v.strip()
            else:
                args.append(seg)

        if len(args) != 1:
            raise CsvReadError(_FOR_FORM.format(token=token))
        unknown = set(kwargs) - {"oneshot"}
        if unknown:
            raise CsvReadError(f"for does not support keyword argument(s): {sorted(unknown)}")

        return cls(count=args[0], oneshot=check_csv_flag(kwargs, "oneshot", "ForLoop.oneshot"))

    @property
    def func_code(self) -> str:
        return _FOR_FUNC_CODES[self.oneshot]

    def to_csv(self) -> str:
        if self.oneshot:
            return f"for({self.count},oneshot=1)"
        return f"for({self.count})"

    def cell_params(self) -> dict:
        return {}

    def build_blob(self) -> bytes:
        from ..binary_helpers import _build_blob

        return _build_blob(
            "For",
            FOR_TYPE_MARKER,
            _FOR_TAGS,
            # The One Shot flag.  CLICK writes 1 when it is on.
            [self.count, self.func_code, "1" if self.oneshot else "0", ""],
        )


@dataclass(frozen=True)
class Next(Instruction):
    """NEXT loop instruction."""

    @classmethod
    def from_csv_token(cls, token: str) -> Next:
        token = token.strip()
        if not re.fullmatch(r"next\(\s*\)", token):
            raise CsvReadError(
                f"Could not read {token!r} as a Next instruction. Write it as next()."
            )
        return cls()

    def to_csv(self) -> str:
        return "next()"

    def cell_params(self) -> dict:
        return {}

    def build_blob(self) -> bytes:
        from ..binary_helpers import _build_blob

        return _build_blob("Next", NEXT_TYPE_MARKER, (0x0000,), [""])


@dataclass(frozen=True)
class Break(Instruction):
    """The CLICK v4 BREAK instruction, which leaves the innermost loop.

    Its binary class is ``Next``, with func code 9233."""

    @classmethod
    def from_csv_token(cls, token: str) -> Break:
        token = token.strip()
        if not re.fullmatch(r"break\(\s*\)", token):
            raise CsvReadError(
                f"Could not read {token!r} as a Break instruction. Write it as break()."
            )
        return cls()

    def to_csv(self) -> str:
        return "break()"

    def cell_params(self) -> dict:
        return {}

    def build_blob(self) -> bytes:
        from ..binary_helpers import _build_blob

        return _build_blob("Next", NEXT_TYPE_MARKER, _LOOP_EXIT_TAGS, [_BREAK_FUNC_CODE, ""])


@dataclass(frozen=True)
class Continue(Instruction):
    """The CLICK v4 CONTINUE instruction, which skips to the next iteration of the loop.

    Its binary class is ``Next``, with func code 9232."""

    @classmethod
    def from_csv_token(cls, token: str) -> Continue:
        token = token.strip()
        if not re.fullmatch(r"continue\(\s*\)", token):
            raise CsvReadError(
                f"Could not read {token!r} as a Continue instruction. Write it as continue()."
            )
        return cls()

    def to_csv(self) -> str:
        return "continue()"

    def cell_params(self) -> dict:
        return {}

    def build_blob(self) -> bytes:
        from ..binary_helpers import _build_blob

        return _build_blob("Next", NEXT_TYPE_MARKER, _LOOP_EXIT_TAGS, [_CONTINUE_FUNC_CODE, ""])


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> ForLoop | Next | Break | Continue | None:
    """Build a ForLoop, Next, Break or Continue from tag data, or return None.

    The clipboard decoder and the program file decoder both call this.
    """
    if class_name == "Next" and type_code == NEXT_TYPE_MARKER:
        func_code = tags.get(0x3218, _NEXT_FUNC_CODE)
        if func_code == _NEXT_FUNC_CODE:
            return Next()
        if func_code == _BREAK_FUNC_CODE:
            return Break()
        if func_code == _CONTINUE_FUNC_CODE:
            return Continue()
        return None

    if class_name == "For" and type_code == FOR_TYPE_MARKER:
        count = tag_value(tags, 0x6065)
        if not count:
            return None
        oneshot = tag_flag(tags, 0x11F8)
        return ForLoop(count=count, oneshot=oneshot)

    return None


_CSV_TYPES: dict[str, type[ForLoop | Next | Break | Continue]] = {
    "for": ForLoop,
    "next": Next,
    "break": Break,
    "continue": Continue,
}


def parse_af_call(call: AfCall) -> ForLoop | Next | Break | Continue:
    """Parse an AF AST call into a ForLoop, Next, Break or Continue."""
    return _CSV_TYPES[call.name].from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="loop",
    instruction_types=(ForLoop, Next, Break, Continue),
    binary_class_names=("For", "Next"),
    from_tags=from_tags,
    csv_names=tuple(_CSV_TYPES),
    parse_csv_call=parse_af_call,
)
