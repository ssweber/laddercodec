"""The ``Coil`` instruction, for CLICK's Out, Set and Reset coils.

The type markers are 0x2715 for Out, 0x2716 for Set and 0x2717 for Reset. All three kinds
use the binary class name ``"Out"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from ..binary_helpers import tag_flag, tag_value
from ..codes import Code
from ..errors import CsvError
from ..model import (
    TYPE_CODE_TO_ITYPE,
    AddressError,
    AfInstruction,
    InstructionType,
    Reason,
)
from ..operands.checks import Refusals, check_csv_flag, check_operand, check_out_target
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

#: The kind of a coil. Each kind is also the name of the coil's CSV call: ``out(...)``,
#: ``latch(...)`` or ``reset(...)``.
CoilKind = Literal["out", "latch", "reset"]

COIL_FUNC_CODES: dict[tuple[CoilKind, bool, bool, bool], str] = {
    # (kind, is_range, immediate, oneshot) -> func_code
    ("out", False, False, False): "8193",
    ("out", False, True, False): "8197",
    ("out", True, False, False): "8207",
    ("out", True, True, False): "8208",
    ("out", False, False, True): "8205",
    ("out", False, True, True): "8206",
    ("out", True, False, True): "8209",
    ("out", True, True, True): "8210",
    ("latch", False, False, False): "8195",
    ("latch", False, True, False): "8199",
    ("latch", True, False, False): "8213",
    ("latch", True, True, False): "8214",
    ("reset", False, False, False): "8196",
    ("reset", False, True, False): "8200",
    ("reset", True, False, False): "8219",
    ("reset", True, True, False): "8220",
}

_KIND_TO_ITYPE: dict[CoilKind, InstructionType] = {
    "out": InstructionType.COIL_OUT,
    "latch": InstructionType.COIL_LATCH,
    "reset": InstructionType.COIL_RESET,
}

_ITYPE_TO_KIND: dict[InstructionType, CoilKind] = {v: k for k, v in _KIND_TO_ITYPE.items()}

# Reverse lookup: func_code string → (kind, is_range, immediate, oneshot).
_FUNC_TO_COIL: dict[str, tuple[CoilKind, bool, bool, bool]] = {
    v: k for k, v in COIL_FUNC_CODES.items()
}

# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

_COIL_TAGS = (0x6066, 0x6067, 0x11F8, 0x11F5, 0x3218, 0x0000)

_COIL_FORM = (
    "Could not read {token!r} as a coil. Write it as out(address), latch(address) or "
    "reset(address), such as out(Y001) or out(C1..C8,oneshot=1)."
)


def _bank_of(value: str) -> str | None:
    """Return the bank of ``value``, or None if ``value`` is not an address CLICK accepts.

    ``value`` may be an address in any bank, or a pointer that CLICK accepts, such as
    ``DS[DS1]``. A pointer that CLICK does not accept, such as ``X[DS1]``, returns None."""
    try:
        return check_operand(value, "Coil.range_end", pointer=True).bank
    except AddressError:
        return None


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Coil(AfInstruction):
    """An output coil: ``out``, ``latch`` (Set) or ``reset``, on one bit or a range.

    ``Coil("Y001", kind="latch")`` is the CSV token ``latch(Y001)``, and
    ``Coil("C1", range_end="C8", oneshot=True)`` is ``out(C1..C8,oneshot=1)``.
    """

    operand: str  # e.g. "Y001"
    kind: CoilKind = "out"
    range_end: str | None = None
    immediate: bool = False
    oneshot: bool = False

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            # Test against a tuple, not the dict, so that an unhashable kind is refused and
            # does not raise TypeError.
            if self.kind not in tuple(_KIND_TO_ITYPE):
                check.refuse(
                    "kind",
                    f"{self.kind!r} is not a coil (out, latch or reset)",
                    Reason.CHOICE,
                    code=Code.INVALID_CHOICE,
                )
            check.flag("immediate", "oneshot")
            if self.oneshot and self.kind in ("latch", "reset"):
                # CLICK's Set/Reset dialog has no One Shot box, so it never writes these.
                check.refuse(
                    ("oneshot", "kind"),
                    f"{self.kind}() has no one-shot form; only out() does",
                    Reason.CONFLICT,
                    code=Code.OPTION_NOT_OFFERED,
                )
            check.normalize("operand")
            if self.range_end is not None:
                check.normalize("range_end")
            # If check.flag refused ``immediate`` because it is not a bool, count it as False,
            # so that the target checks below still run.
            immediate = self.immediate is True
            # Out, Set and Reset follow the same rules for targets and ranges, and CLICK gives
            # the same error ids for all three. OBJ-004 is for a bank that the coil does not
            # accept, and OBJ-003 is for an SC bit that it cannot write.
            ids = {"bank_id": "OBJ-004", "not_writable_id": "OBJ-003"}
            start = check("operand", check_out_target, immediate=immediate, **ids)
            if self.range_end is None:
                return
            # If the end of the range is in another bank, refuse it with OBJ-008 before the
            # end's own checks run. This applies even when a coil does not accept the end's
            # bank at all (C1..DS1), and when the end is a pointer (Y001..DS[DS1]).
            end_bank = _bank_of(self.range_end)
            if start is not None and end_bank is not None and end_bank != start.bank:
                check.refuse(
                    ("range_end", "operand"),
                    f"{self.range_end!r} is in bank {end_bank}; the range starts in bank "
                    f"{start.bank} and must stay in it",
                    Reason.CONFLICT,
                    "OBJ-008",
                    code=Code.RANGE_MIXED_BANKS,
                )
            # In an SC range, both ends must be writable. The bits between them are not
            # checked.
            end = check("range_end", check_out_target, immediate=immediate, **ids)
            if start is None or end is None:
                return
            if end.number <= start.number:
                # An end below the start is refused with OBJ-009. An end at the same address
                # as the start is refused with OBJ-012.
                check.refuse(
                    ("range_end", "operand"),
                    f"{self.range_end!r} is not above {self.operand!r}; a range runs from a "
                    "lower to a higher address",
                    Reason.CONFLICT,
                    "OBJ-009" if end.number < start.number else "OBJ-012",
                    code=Code.RANGE_NOT_ASCENDING,
                )

    @classmethod
    def from_csv_token(cls, token: str) -> Coil:
        """Parse the CSV token of a coil, such as ``out(Y001)`` or ``out(C1..C8,oneshot=1)``.

        An ``immediate(...)`` wrapper goes inside the call, as in ``out(immediate(Y001))``.
        """
        token = token.strip()
        if token.startswith("immediate("):
            raise CsvError(
                f"Immediate must be an inner wrapper (e.g. out(immediate(Y1))): {token!r}"
            )

        m = re.fullmatch(r"(out|latch|reset)\((.+)\)", token)
        if not m:
            raise CsvError(_COIL_FORM.format(token=token))

        kind = cast(CoilKind, m.group(1))
        inner = m.group(2).strip()
        parts = [seg.strip() for seg in inner.split(",") if seg.strip()]
        if not parts:
            raise CsvError(_COIL_FORM.format(token=token))

        arg = parts[0]
        kwargs: dict[str, str] = {}
        for seg in parts[1:]:
            if "=" not in seg:
                raise CsvError(_COIL_FORM.format(token=token))
            k, v = seg.split("=", 1)
            kwargs[k.strip()] = v.strip()

        unknown = set(kwargs) - {"oneshot"}
        if unknown:
            raise CsvError(f"Coil does not support keyword argument(s): {sorted(unknown)}")
        oneshot = check_csv_flag(kwargs, "oneshot", "Coil.oneshot")

        immediate_inner = False
        inner = re.fullmatch(r"immediate\((.+)\)", arg)
        if inner:
            immediate_inner = True
            arg = inner.group(1).strip()

        immediate = immediate_inner
        if ":" in arg:
            raise CsvError(
                f"{token!r} writes a range with ':'. Write it with '..', such as out(C1..C8)."
            )

        if ".." in arg:
            parts = [p.strip() for p in arg.split("..")]
            if len(parts) != 2 or not all(parts):
                raise CsvError(
                    f"Could not read the range in {token!r}. Write it as two addresses "
                    "joined by '..', such as out(C1..C8)."
                )
            return cls(
                parts[0],
                kind=kind,
                range_end=parts[1],
                immediate=immediate,
                oneshot=oneshot,
            )

        return cls(arg, kind=kind, immediate=immediate, oneshot=oneshot)

    @property
    def func_code(self) -> str:
        return COIL_FUNC_CODES[
            (self.kind, self.range_end is not None, self.immediate, self.oneshot)
        ]

    def to_csv(self) -> str:
        name = self.kind
        operand = self.operand
        if self.range_end is not None:
            operand = f"{operand}..{self.range_end}"
        if self.immediate:
            operand = f"immediate({operand})"
        if self.oneshot:
            return f"{name}({operand},oneshot=1)"
        return f"{name}({operand})"

    def cell_params(self) -> dict:
        """Return the ``ClickCell`` keyword arguments that depend on this instruction alone."""
        return {}

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this coil cell."""
        from ..binary_helpers import _build_blob

        return _build_blob(
            "Out",
            0x2700 | _KIND_TO_ITYPE[self.kind],
            _COIL_TAGS,
            [
                self.operand,
                self.range_end or "",
                "1" if self.oneshot else "0",  # CLICK writes 1, not -1
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
    """Build a ``Coil`` from the tags of an instruction blob, or return None.

    Return None if the blob is not a plain coil, or if it has no operand. The clipboard
    decoder and the program-file decoder both call this.
    """
    itype = TYPE_CODE_TO_ITYPE.get(type_code)
    kind = _ITYPE_TO_KIND.get(itype) if itype is not None else None
    if class_name not in ("Out", "Latch", "Reset") or kind is None:
        return None
    operand = tag_value(tags, 0x6066)
    if not operand:
        return None
    # CLICK v4's Out variants (toggle, debounce, flasher, timed) also use class "Out" and
    # type 0x2715. Return None for a func code that no plain coil has, so that the decoder
    # tries the next family (OutVariant) and keeps the blob raw if none decodes it.
    func_code = tags.get(0x3218)
    if func_code is not None and func_code not in _FUNC_TO_COIL:
        return None
    range_end_val = tag_value(tags, 0x6067)
    return Coil(
        operand,
        kind=kind,
        range_end=range_end_val or None,
        immediate=tag_flag(tags, 0x11F5),
        oneshot=tag_flag(tags, 0x11F8),
    )


def parse_af_call(call: AfCall) -> Coil:
    """Parse a coil call from the AF (output) column of a CSV rung into a ``Coil``."""
    return Coil.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="coil",
    instruction_types=(Coil,),
    binary_class_names=("Out", "Latch", "Reset"),
    from_tags=from_tags,
    csv_names=("out", "latch", "reset"),
    parse_csv_call=parse_af_call,
)
