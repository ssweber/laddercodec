"""Out — all coil types (type markers 0x2715, 0x2716, 0x2717).

Binary class name: ``"Out"`` (for out, latch, and reset).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..binary_helpers import tag_flag, tag_value
from ..model import (
    TYPE_CODE_TO_ITYPE,
    Address,
    AddressError,
    AfInstruction,
    FieldError,
    InstructionType,
    check_address,
    normalize_address,
)
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
    (InstructionType.COIL_OUT, False, True, True): "8206",  # v4_captures/sweep_coil.bin
    (InstructionType.COIL_OUT, True, False, True): "8209",
    (InstructionType.COIL_OUT, True, True, True): "8210",
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
# Target rules
# ---------------------------------------------------------------------------

#: Banks a coil writes.  Out: CLICK v4.00 Help CL167.  Set and Reset take the same three
#: (Q-B1, user dialog check 2026-11-11: X1, T1, CT1 and DS1 are refused).
OUT_BANKS = frozenset({"Y", "C", "SC"})

#: The SC bits a coil writes: CLICK's address picker lists these 25 read-write system bits
#: for Out, and no other SC is accepted (Q-B2, user dialog check 2026-11-11).  Ruling: the
#: list belongs to the address, so Set, Reset and the Out variants take the same bits.
WRITABLE_SC = frozenset(
    {50, 51, 53, 55, 60, 61, 65, 66, 67, 75, 76, 120, 121, 162, 165, 168, 171}
    | {303, 304, 305, 306, 323, 324, 325, 326}
)

_WRITABLE_SC_TEXT = ", ".join(f"SC{n}" for n in sorted(WRITABLE_SC))


def check_out_target(operand: str, name: str, *, immediate: bool = False) -> Address:
    """Check one address a coil writes (Out, Set, Reset or an Out variant); return it.

    The bank is Y, C or SC, an immediate target is Y, and an SC bit is one of
    :data:`WRITABLE_SC`.
    """
    address = check_address(operand, name, OUT_BANKS)
    # Immediate first: an immediate SC target is refused whatever its number.
    if immediate and address.bank != "Y":
        raise FieldError(f"{name}: {operand!r} is not allowed; an immediate coil takes Y only")
    if address.bank == "SC" and address.number not in WRITABLE_SC:
        raise AddressError(
            f"{name}: {operand!r} is not a writable SC bit; a coil writes {_WRITABLE_SC_TEXT}"
        )
    return address


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

    def __post_init__(self) -> None:
        self.operand = normalize_address(self.operand)
        if self.range_end is not None:
            self.range_end = normalize_address(self.range_end)
        # Out, Set and Reset follow the same target and range rules (Q-B1).
        start = check_out_target(self.operand, "Coil.operand", immediate=self.immediate)
        if self.range_end is None:
            return
        # An SC range needs both ends writable; the bits between are not checked (ruling).
        end = check_out_target(self.range_end, "Coil.range_end", immediate=self.immediate)
        # Out: OBJ-008; Set and Reset: Q-B1, user dialog check 2026-11-11 (C5..Y5 refused).
        if end.bank != start.bank:
            raise FieldError(
                f"Coil.range_end: {self.range_end!r} is in bank {end.bank}; "
                f"the range starts in bank {start.bank} and must stay in it"
            )
        # Out: OBJ-009 and Q-B3 (C5..C5 refused); Set and Reset: Q-B1 (C9..C1 refused),
        # and the ruling that they refuse C5..C5 as Out does.
        if end.number <= start.number:
            raise FieldError(
                f"Coil.range_end: {self.range_end!r} is not above {self.operand!r}; "
                "a range runs from a lower to a higher address"
            )

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
        if oneshot and coil_type != InstructionType.COIL_OUT:
            # CLICK's Set/Reset dialog has no One Shot box, so it never writes these.
            raise ValueError(f"only out() supports oneshot, not {token!r}")

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
            return cls(
                type=coil_type,
                operand=parts[0],
                range_end=parts[1],
                immediate=immediate,
                oneshot=oneshot,
            )

        return cls(
            type=coil_type,
            operand=arg,
            immediate=immediate,
            oneshot=oneshot,
        )

    @property
    def func_code(self) -> str:
        key = (self.type, self.range_end is not None, self.immediate, self.oneshot)
        if key not in COIL_FUNC_CODES:
            raise ValueError(f"only out() supports oneshot: {self.to_csv()}")
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
                "1" if self.oneshot else "0",  # CLICK writes 1, not -1 (scr_captures/coverage.bin)
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
    operand = tag_value(tags, 0x6066)
    if not operand:
        return None
    # CLICK v4's Out variants (toggle, debounce, flasher, timed) share class "Out" and
    # type 0x2715; an unknown func code must fall through to RawInstruction, not decode
    # as a plain coil.
    func_code = tags.get(0x3218)
    if func_code is not None and func_code not in _FUNC_TO_COIL:
        return None
    range_end_val = tag_value(tags, 0x6067)
    return Coil(
        type=itype,
        operand=operand,
        range_end=range_end_val or None,
        immediate=tag_flag(tags, 0x11F5),
        oneshot=tag_flag(tags, 0x11F8),
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
