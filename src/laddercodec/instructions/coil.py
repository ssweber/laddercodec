"""Out — all coil types (type markers 0x2715, 0x2716, 0x2717).

Binary class name: ``"Out"`` (for out, latch, and reset).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..model import TYPE_CODE_TO_ITYPE, AfInstruction, InstructionType, _validate_operand
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

COIL_FUNC_CODES: dict[tuple[InstructionType, bool, bool, bool], str] = {
    # (type, is_range, immediate, oneshot) -> func_code
    (InstructionType.COIL_OUT, False, False, False): "8193",
    (InstructionType.COIL_OUT, False, True, False): "8197",
    (InstructionType.COIL_OUT, True, False, False): "8207",
    (InstructionType.COIL_OUT, True, True, False): "8208",
    (InstructionType.COIL_OUT, False, False, True): "8205",
    (InstructionType.COIL_LATCH, False, False, False): "8195",
    (InstructionType.COIL_LATCH, False, True, False): "8199",
    (InstructionType.COIL_LATCH, True, False, False): "8213",
    (InstructionType.COIL_LATCH, True, True, False): "8214",
    (InstructionType.COIL_RESET, False, False, False): "8196",
    (InstructionType.COIL_RESET, False, True, False): "8200",
    (InstructionType.COIL_RESET, True, False, False): "8219",
    (InstructionType.COIL_RESET, True, True, False): "8220",
}

COIL_NAME_TO_TYPE = {
    "out": InstructionType.COIL_OUT,
    "latch": InstructionType.COIL_LATCH,
    "reset": InstructionType.COIL_RESET,
}

COIL_TYPE_TO_NAME = {v: k for k, v in COIL_NAME_TO_TYPE.items()}

# Reverse lookup: func_code string → (InstructionType, is_range, immediate, oneshot).
_FUNC_TO_COIL: dict[str, tuple[InstructionType, bool, bool, bool]] = {
    v: k for k, v in COIL_FUNC_CODES.items()
}

# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

_COIL_TAGS = (0x6066, 0x6067, 0x11F8, 0x11F5, 0x3218, 0x0000)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Coil(AfInstruction):
    """An output coil instruction."""

    type: InstructionType  # COIL_OUT, COIL_LATCH, COIL_RESET
    operand: str  # e.g. "Y001"
    range_end: str | None = None
    immediate: bool = False
    oneshot: bool = False

    @classmethod
    def from_csv_token(cls, token: str) -> Coil:
        """Parse coil forms with inner immediate wrapper and ranges."""
        token = token.strip()
        if token.startswith("immediate("):
            raise ValueError(
                f"Immediate must be an inner wrapper (e.g. out(immediate(Y1))): {token!r}"
            )

        m = re.fullmatch(r"(out|latch|reset)\((.+)\)", token)
        if not m:
            raise ValueError(f"Cannot parse coil: {token!r}")

        coil_type = COIL_NAME_TO_TYPE[m.group(1)]
        inner = m.group(2).strip()
        parts = [seg.strip() for seg in inner.split(",") if seg.strip()]
        if not parts:
            raise ValueError(f"Cannot parse coil: {token!r}")

        arg = parts[0]
        kwargs: dict[str, str] = {}
        for seg in parts[1:]:
            if "=" not in seg:
                raise ValueError(f"Cannot parse coil keyword arg: {token!r}")
            k, v = seg.split("=", 1)
            kwargs[k.strip()] = v.strip()

        unknown = set(kwargs) - {"oneshot"}
        if unknown:
            raise ValueError(f"Coil does not support keyword argument(s): {sorted(unknown)}")
        oneshot_raw = kwargs.get("oneshot", "0")
        if oneshot_raw not in {"0", "1"}:
            raise ValueError("coil oneshot must be 0 or 1")
        oneshot = oneshot_raw == "1"

        immediate_inner = False
        inner = re.fullmatch(r"immediate\((.+)\)", arg)
        if inner:
            immediate_inner = True
            arg = inner.group(1).strip()

        immediate = immediate_inner
        if ":" in arg:
            raise ValueError(f"Range delimiter ':' is unsupported: {token!r}")

        if ".." in arg:
            parts = [p.strip() for p in arg.split("..")]
            if len(parts) != 2 or not all(parts):
                raise ValueError(f"Cannot parse coil range: {token!r}")
            op1 = _validate_operand(parts[0])
            op2 = _validate_operand(parts[1])
            return cls(
                type=coil_type,
                operand=op1,
                range_end=op2,
                immediate=immediate,
                oneshot=oneshot,
            )

        return cls(
            type=coil_type,
            operand=_validate_operand(arg),
            immediate=immediate,
            oneshot=oneshot,
        )

    @property
    def func_code(self) -> str:
        key = (self.type, self.range_end is not None, self.immediate, self.oneshot)
        return COIL_FUNC_CODES[key]

    def to_csv(self) -> str:
        name = COIL_TYPE_TO_NAME[self.type]
        operand = self.operand
        if self.range_end is not None:
            operand = f"{operand}..{self.range_end}"
        if self.immediate:
            operand = f"immediate({operand})"
        if self.oneshot:
            return f"{name}({operand},oneshot=1)"
        return f"{name}({operand})"

    def cell_params(self) -> dict:
        """Return ClickCell kwargs intrinsic to this instruction."""
        return {}

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this coil cell."""
        from ..binary_helpers import _build_blob

        return _build_blob(
            "Out",
            0x2700 | self.type,
            _COIL_TAGS,
            [
                self.operand,
                self.range_end or "",
                "-1" if self.oneshot else "0",
                "1" if self.immediate else "0",
                self.func_code,
                "",
            ],
        )


# ---------------------------------------------------------------------------
# Shared from_tags factory
# ---------------------------------------------------------------------------


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    tag_byte_lens: dict[int, int] | None = None,
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Coil | None:
    """Construct a Coil from tag data (shared by both decoders)."""
    itype = TYPE_CODE_TO_ITYPE.get(type_code)
    if class_name not in ("Out", "Latch", "Reset") or itype not in (
        InstructionType.COIL_OUT,
        InstructionType.COIL_LATCH,
        InstructionType.COIL_RESET,
    ):
        return None
    operand = tags.get(0x6066, "")
    if not operand:
        return None
    range_end_val = tags.get(0x6067, "")
    return Coil(
        type=itype,
        operand=operand,
        range_end=range_end_val or None,
        immediate=0x11F5 in tags,
        oneshot=0x11F8 in tags,
    )


def parse_af_call(call: AfCall) -> Coil:
    """Parse an AF AST call into a Coil."""
    return Coil.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="coil",
    instruction_types=(Coil,),
    binary_class_names=("Out", "Latch", "Reset"),
    from_tags=from_tags,
    csv_names=("out", "latch", "reset"),
    parse_csv_call=parse_af_call,
)
