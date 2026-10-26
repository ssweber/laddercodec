"""For/Next loop instructions (type markers 0x2725 and 0x2726).

Binary class names:
    - ``"For"``
    - ``"Next"`` (also CLICK v4's Break and Continue, told apart by func code)

CSV forms:
    - ``for(3,oneshot=0)``
    - ``for(DS1,oneshot=1)``
    - ``next()``
    - ``break()``
    - ``continue()``
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..model import AfInstruction, InstructionType, _validate_operand
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
_FOR_LITERAL_RE = re.compile(r"^\d+$")

# Class "Next" func codes (0x3218).  v3 writes Next without one; v4 writes 9220.
_NEXT_FUNC_CODE = "9220"
_CONTINUE_FUNC_CODE = "9232"
_BREAK_FUNC_CODE = "9233"
_LOOP_EXIT_TAGS = (0x3218, 0x0000)


def _validate_for_limit(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("for() limit cannot be blank")
    if _FOR_LITERAL_RE.fullmatch(text):
        return text
    return _validate_operand(text)


@dataclass
class ForLoop(AfInstruction):
    """FOR loop instruction."""

    limit: str
    oneshot: bool = False

    def __post_init__(self) -> None:
        self.limit = _validate_for_limit(self.limit)

    @classmethod
    def from_csv_token(cls, token: str) -> ForLoop:
        token = token.strip()
        m = re.fullmatch(r"for\((.+)\)", token)
        if not m:
            raise ValueError(f"Cannot parse for instruction: {token!r}")

        args: list[str] = []
        kwargs: dict[str, str] = {}
        for seg in (a.strip() for a in m.group(1).split(",")):
            if "=" in seg:
                k, v = seg.split("=", 1)
                kwargs[k.strip()] = v.strip()
            else:
                args.append(seg)

        if len(args) != 1:
            raise ValueError(f"for expects 1 positional arg (limit), got {len(args)}")
        unknown = set(kwargs) - {"oneshot"}
        if unknown:
            raise ValueError(f"for does not support keyword argument(s): {sorted(unknown)}")

        oneshot_raw = kwargs.get("oneshot", "0")
        if oneshot_raw not in {"0", "1"}:
            raise ValueError("for oneshot must be 0 or 1")

        return cls(limit=args[0], oneshot=oneshot_raw == "1")

    @property
    def func_code(self) -> str:
        return _FOR_FUNC_CODES[self.oneshot]

    def to_csv(self) -> str:
        return f"for({self.limit},oneshot={1 if self.oneshot else 0})"

    def cell_params(self) -> dict:
        return {}

    def build_blob(self) -> bytes:
        from ..binary_helpers import _build_blob

        return _build_blob(
            "For",
            FOR_TYPE_MARKER,
            _FOR_TAGS,
            [self.limit, self.func_code, "-1" if self.oneshot else "0", ""],
        )


@dataclass
class Next(AfInstruction):
    """NEXT loop instruction."""

    @classmethod
    def from_csv_token(cls, token: str) -> Next:
        token = token.strip()
        if not re.fullmatch(r"next\(\s*\)", token):
            raise ValueError(f"Cannot parse next instruction: {token!r}")
        return cls()

    def to_csv(self) -> str:
        return "next()"

    def cell_params(self) -> dict:
        return {}

    def build_blob(self) -> bytes:
        from ..binary_helpers import _build_blob

        return _build_blob("Next", NEXT_TYPE_MARKER, (0x0000,), [""])


@dataclass
class Break(AfInstruction):
    """BREAK (CLICK v4): leave the innermost loop.  Class ``Next``, func code 9233."""

    @classmethod
    def from_csv_token(cls, token: str) -> Break:
        token = token.strip()
        if not re.fullmatch(r"break\(\s*\)", token):
            raise ValueError(f"Cannot parse break instruction: {token!r}")
        return cls()

    def to_csv(self) -> str:
        return "break()"

    def cell_params(self) -> dict:
        return {}

    def build_blob(self) -> bytes:
        from ..binary_helpers import _build_blob

        return _build_blob("Next", NEXT_TYPE_MARKER, _LOOP_EXIT_TAGS, [_BREAK_FUNC_CODE, ""])


@dataclass
class Continue(AfInstruction):
    """CONTINUE (CLICK v4): skip to the next iteration.  Class ``Next``, func code 9232."""

    @classmethod
    def from_csv_token(cls, token: str) -> Continue:
        token = token.strip()
        if not re.fullmatch(r"continue\(\s*\)", token):
            raise ValueError(f"Cannot parse continue instruction: {token!r}")
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
    tag_byte_lens: dict[int, int] | None = None,
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> ForLoop | Next | Break | Continue | None:
    """Construct a ForLoop, Next, Break or Continue from tag data (shared by both decoders)."""
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
        limit = tags.get(0x6065, "")
        if not limit:
            return None
        oneshot = 0x11F8 in tags
        try:
            return ForLoop(limit=limit, oneshot=oneshot)
        except ValueError:
            return None

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
