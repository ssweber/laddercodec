"""Out variants — CLICK v4's toggle, debounce, flasher and timed coils.

Binary class name: ``"Out"``, type marker 0x2715 (same as a plain ``out``).
The func code (tag ``0x3218``) tells them apart from plain coils.

CSV token formats::

    toggle(C1)
    toggle(immediate(Y001))
    debounce(C1,on_acc=TD1,on_preset=100,off_acc=TD2,off_preset=DS1,unit=Tms)
    flasher(C1,on_acc=TD1,on_preset=500,off_acc=TD2,off_preset=250,unit=Tms)
    timed(C1,on_acc=TD1,on_preset=1000,unit=Tms)
    timed(C1,on_acc=TD1,on_preset=3,unit=Ts,maintained=1)

Each phase names only its accumulator (``TD``); Click claims the ``T`` of the
same number with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from ..model import AfInstruction, _validate_operand
from .family import AfInstructionFamilySpec
from .timer import TIMER_UNIT_TO_INDEX, TIMER_UNITS

if TYPE_CHECKING:
    from ..csv.ast import AfCall

OutVariantKind = Literal["toggle", "debounce", "flasher", "timed"]

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

#: Variant -> tag 0x2248 value.
_KIND_INDEX: dict[str, str] = {"toggle": "0", "debounce": "1", "flasher": "2", "timed": "3"}

OUT_VARIANT_FUNC_CODES: dict[tuple[OutVariantKind, str, bool], str] = {
    # (kind, unit, immediate/maintained) -> func_code
    ("toggle", "", False): "8224",
    ("toggle", "", True): "8225",
    ("debounce", "Tms", False): "8226",
    ("debounce", "Ts", False): "8227",
    ("flasher", "Tms", False): "8228",
    ("flasher", "Ts", False): "8229",
    ("timed", "Tms", False): "8230",
    ("timed", "Ts", False): "8231",
    ("timed", "Tm", False): "8232",
    ("timed", "Tms", True): "8233",
    ("timed", "Ts", True): "8234",
    ("timed", "Tm", True): "8235",
}

_FUNC_TO_VARIANT: dict[str, tuple[OutVariantKind, str, bool]] = {
    v: k for k, v in OUT_VARIANT_FUNC_CODES.items()
}

_TWO_PHASE = frozenset({"debounce", "flasher"})

# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

_OUT_VARIANT_TAGS = (
    0x6066,  # operand
    0x6067,  # range end (always empty)
    0x60B3,  # on preset
    0x60B4,  # on accumulator
    0x60B5,  # off preset
    0x60B6,  # off accumulator
    0x11F8,  # oneshot (always 0)
    0x11F5,  # immediate
    0x1246,  # toggle
    0x1247,  # maintained
    0x21F9,  # time unit index
    0x2248,  # variant index
    0x3218,  # func code
    0x20CA,  # always "2"
    0x0000,
)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class OutVariant(AfInstruction):
    """A CLICK v4 Out coil variant: toggle, debounce, flasher or timed."""

    kind: OutVariantKind
    operand: str  # e.g. "C1"
    on_acc: str = ""  # e.g. "TD1"
    on_preset: str = ""  # literal or DS register
    off_acc: str = ""
    off_preset: str = ""
    unit: str = ""  # "Tms", "Ts", "Tm"; empty for toggle
    immediate: bool = False  # toggle only
    maintained: bool = False  # timed only

    @classmethod
    def from_csv_token(cls, token: str) -> OutVariant:
        """Parse ``toggle(...)``, ``debounce(...)``, ``flasher(...)`` or ``timed(...)``."""
        token = token.strip()
        m = re.fullmatch(r"(toggle|debounce|flasher|timed)\((.+)\)", token)
        if not m:
            raise ValueError(f"Cannot parse Out variant: {token!r}")
        kind = cast(OutVariantKind, m.group(1))
        parts = [seg.strip() for seg in m.group(2).split(",") if seg.strip()]
        if not parts or "=" in parts[0]:
            raise ValueError(f"{kind} needs a target operand: {token!r}")

        arg = parts[0]
        kwargs: dict[str, str] = {}
        for seg in parts[1:]:
            if "=" not in seg:
                raise ValueError(f"Cannot parse {kind} keyword arg: {token!r}")
            k, v = seg.split("=", 1)
            kwargs[k.strip()] = v.strip()

        if kind == "toggle":
            if kwargs:
                raise ValueError(f"toggle takes no keyword arguments: {token!r}")
            inner = re.fullmatch(r"immediate\((.+)\)", arg)
            if inner:
                return cls(kind="toggle", operand=_validate_operand(inner.group(1)), immediate=True)
            return cls(kind="toggle", operand=_validate_operand(arg))

        required = {"on_acc", "on_preset", "unit"}
        allowed = set(required)
        if kind in _TWO_PHASE:
            required |= {"off_acc", "off_preset"}
            allowed = set(required)
        else:
            allowed.add("maintained")
        missing = required - set(kwargs)
        if missing:
            raise ValueError(f"{kind} missing keyword argument(s) {sorted(missing)}: {token!r}")
        unknown = set(kwargs) - allowed
        if unknown:
            raise ValueError(f"{kind} does not support keyword argument(s): {sorted(unknown)}")
        maintained_raw = kwargs.get("maintained", "0")
        if maintained_raw not in {"0", "1"}:
            raise ValueError("timed maintained must be 0 or 1")

        variant = cls(
            kind=kind,
            operand=_validate_operand(arg),
            on_acc=_validate_operand(kwargs["on_acc"]),
            on_preset=kwargs["on_preset"],
            off_acc=_validate_operand(kwargs["off_acc"]) if kind in _TWO_PHASE else "",
            off_preset=kwargs.get("off_preset", ""),
            unit=kwargs["unit"],
            maintained=maintained_raw == "1",
        )
        if (variant.kind, variant.unit, variant.maintained) not in OUT_VARIANT_FUNC_CODES:
            raise ValueError(f"{kind} does not support unit={variant.unit!r}: {token!r}")
        return variant

    @property
    def func_code(self) -> str:
        flag = self.immediate if self.kind == "toggle" else self.maintained
        return OUT_VARIANT_FUNC_CODES[(self.kind, self.unit, flag)]

    def to_csv(self) -> str:
        if self.kind == "toggle":
            operand = f"immediate({self.operand})" if self.immediate else self.operand
            return f"toggle({operand})"
        parts = [self.operand, f"on_acc={self.on_acc}", f"on_preset={self.on_preset}"]
        if self.kind in _TWO_PHASE:
            parts += [f"off_acc={self.off_acc}", f"off_preset={self.off_preset}"]
        parts.append(f"unit={self.unit}")
        if self.maintained:
            parts.append("maintained=1")
        return f"{self.kind}({','.join(parts)})"

    def cell_params(self) -> dict:
        """Return ClickCell kwargs intrinsic to this instruction."""
        if self.kind in _TWO_PHASE:
            return {"visual_rows": 3}
        if self.kind == "timed":
            # Click spans 2 rows but writes 3 visual sub-rows in the cell header.
            return {"visual_rows": 2, "sub_rows": 3}
        return {}

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this Out variant cell."""
        from ..binary_helpers import _build_blob

        return _build_blob(
            "Out",
            0x2715,
            _OUT_VARIANT_TAGS,
            [
                self.operand,
                "",
                self.on_preset,
                self.on_acc,
                self.off_preset,
                self.off_acc,
                "0",
                "1" if self.immediate else "0",
                "1" if self.kind == "toggle" else "0",
                "1" if self.maintained else "0",
                TIMER_UNIT_TO_INDEX[self.unit] if self.unit else "0",
                _KIND_INDEX[self.kind],
                self.func_code,
                "2",
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
) -> OutVariant | None:
    """Construct an OutVariant from tag data (shared by both decoders)."""
    if class_name != "Out" or type_code != 0x2715:
        return None
    variant = _FUNC_TO_VARIANT.get(tags.get(0x3218, ""))
    operand = tags.get(0x6066, "")
    if variant is None or not operand:
        return None
    kind, unit, flag = variant
    if kind == "toggle":
        return OutVariant(kind="toggle", operand=operand, immediate=flag)
    if TIMER_UNITS.get(tags.get(0x21F9, "")) != unit:
        return None
    two_phase = kind in _TWO_PHASE
    return OutVariant(
        kind=kind,
        operand=operand,
        on_acc=tags.get(0x60B4, ""),
        on_preset=tags.get(0x60B3, ""),
        off_acc=tags.get(0x60B6, "") if two_phase else "",
        off_preset=tags.get(0x60B5, "") if two_phase else "",
        unit=unit,
        maintained=flag,
    )


def parse_af_call(call: AfCall) -> OutVariant:
    """Parse an AF AST call into an OutVariant."""
    return OutVariant.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="out_variant",
    instruction_types=(OutVariant,),
    # Shares class name "Out" with coil.py, which owns the INSTRUCTION_MODULES entry;
    # from_tags dispatch tries every family, so the func code decides.
    binary_class_names=(),
    from_tags=from_tags,
    csv_names=("toggle", "debounce", "flasher", "timed"),
    parse_csv_call=parse_af_call,
)
