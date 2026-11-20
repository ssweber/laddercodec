"""The ``OutVariant`` instruction, for CLICK v4's toggle, debounce, flasher and timed coils.

These coils have the same binary class name and type marker as a plain ``out`` coil:
``"Out"`` and 0x2715. Their func code (tag ``0x3218``) tells them apart from plain coils.

Their CSV tokens look like this::

    toggle(C1)
    toggle(immediate(Y001))
    debounce(C1,on_acc=TD1,on_preset=100,off_acc=TD2,off_preset=DS1,unit=Tms)
    debounce(C1,off_acc=TD1,off_preset=100,unit=Tms)
    flasher(C1,on_acc=TD1,on_preset=500,off_acc=TD2,off_preset=250,unit=Tms)
    timed(C1,on_acc=TD1,on_preset=1000,unit=Tms)
    timed(C1,on_acc=TD1,on_preset=3,unit=Ts,maintained=1)

Each phase names only its accumulator, a ``TD`` register. CLICK takes the ``T`` bit with the
same number for that phase as well.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from ..binary_helpers import tag_value
from ..codes import Code
from ..errors import CsvReadError
from ..model import Instruction, Reason, check_address
from ..operands.checks import (
    Constants,
    Refusals,
    check_csv_flag,
    check_operand,
    check_out_target,
    choice_operand,
    is_choice,
)
from ..operands.constants import INT16_MAX, Kind
from ..operands.message import Op, operand, says
from .family import AfInstructionFamilySpec
from .timer import TIMER_UNIT_TO_INDEX, TIMER_UNITS

if TYPE_CHECKING:
    from ..csv.ast import AfCall

OutVariantKind = Literal["toggle", "debounce", "flasher", "timed"]
"""The kind of an OutVariant coil. Each kind is also the name of its CSV call."""

OutVariantUnit = Literal["Tms", "Ts", "Tm"]
"""The time unit of a debounce, flasher or timed coil. A timed coil accepts all three. A
debounce or flasher coil accepts ``"Tms"`` or ``"Ts"``. A toggle has no unit, and its ``unit``
is ``""``."""

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

#: The value of tag 0x2248 for each variant.
_KIND_INDEX: dict[str, str] = {"toggle": "0", "debounce": "1", "flasher": "2", "timed": "3"}

OUT_VARIANT_FUNC_CODES: dict[tuple[OutVariantKind, OutVariantUnit | Literal[""], bool], str] = {
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

_FUNC_TO_VARIANT: dict[str, tuple[OutVariantKind, OutVariantUnit | Literal[""], bool]] = {
    v: k for k, v in OUT_VARIANT_FUNC_CODES.items()
}


def _units_of(kind: str) -> str:
    """Return the units that *kind* takes, as a refusal of another unit lists them, such as
    ``Tms, Ts or Tm``."""
    units = list(dict.fromkeys(unit for k, unit, _ in OUT_VARIANT_FUNC_CODES if k == kind))
    return " or ".join([", ".join(units[:-1]), units[-1]]) if len(units) > 1 else units[0]


_TWO_PHASE = frozenset({"debounce", "flasher"})

#: The ``ClickCell`` keyword arguments for each kind. A timed box spans 2 rows, but CLICK
#: writes 3 sub-rows in the cell header (+0x09 = 2, +0x0A = 3). A toggle is one row, like a
#: plain coil.
_KIND_CELL_PARAMS: dict[str, dict] = {
    "toggle": {},
    "debounce": {"visual_rows": 3},
    "flasher": {"visual_rows": 3},
    "timed": {"visual_rows": 2, "sub_rows": 3},
}

#: Accumulators are timer data registers.
_ACC_BANKS = frozenset({"TD"})

#: The lowest constant preset that each kind accepts: 0 for debounce, 1 for flasher and timed.
_PRESET_FLOORS: dict[str, int] = {"debounce": 0, "flasher": 1, "timed": 1}


#: The fields that each kind uses. Of these five fields, any that a kind does not use must be
#: empty.
_USED_FIELDS: dict[str, frozenset[str]] = {
    "toggle": frozenset(),
    "debounce": frozenset({"on_acc", "on_preset", "off_acc", "off_preset", "unit"}),
    "flasher": frozenset({"on_acc", "on_preset", "off_acc", "off_preset", "unit"}),
    "timed": frozenset({"on_acc", "on_preset", "unit"}),
}


def _check_preset(value: str, name: str, floor: int) -> None:
    """Raise ``FieldError`` unless the preset is a DS register or a digits-only constant from
    *floor* to 32767."""
    constants = Constants(frozenset({Kind.INTEGER}), signs="", low=floor, high=INT16_MAX)
    check_operand(value, name, {"DS"}, constants, letter_first=True)


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


@dataclass(frozen=True)
class OutVariant(Instruction):
    """A CLICK v4 Out coil variant: toggle, debounce, flasher or timed."""

    kind: OutVariantKind
    operand: str  # e.g. "C1"
    on_acc: str = ""  # e.g. "TD1"
    on_preset: str = ""  # literal or DS register
    off_acc: str = ""
    off_preset: str = ""
    unit: OutVariantUnit | Literal[""] = ""  # blank for a toggle
    immediate: bool = False  # toggle only
    maintained: bool = False  # timed only

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            check.normalize(
                "operand",
                "on_acc",
                "on_preset",
                "off_acc",
                "off_preset",
                values=("on_preset", "off_preset"),
            )
            # The target follows the same rules as an Out coil's target, including the list of
            # writable SC bits. A flag that is not a bool is passed on here as it is.
            # check.flag refuses it last, so its refusal comes after every other refusal.
            check("operand", check_out_target, immediate=self.immediate)
            if not isinstance(self.kind, str) or self.kind not in _KIND_INDEX:
                check.refuse(
                    "kind",
                    says(
                        "{kind} is not one of {kinds}",
                        kind=choice_operand(self.kind),
                        kinds=", ".join(_KIND_INDEX),
                    ),  # fmt: skip
                    Reason.CHOICE,
                    code=Code.INVALID_CHOICE,
                )
            else:
                self._check_kind_rules(check)
            check.flag("immediate", "maintained")

    def _check_kind_rules(self, check: Refusals) -> None:
        """Run the checks that need a valid ``kind``."""
        used = _USED_FIELDS[self.kind]
        for name in ("on_acc", "on_preset", "off_acc", "off_preset", "unit"):
            if name not in used and (value := getattr(self, name)):
                # A preset or accumulator is an address or a number, shown as written. The
                # unit is a choice, and keeps its quotes.
                number = name != "unit" and isinstance(value, str)
                check.refuse(
                    (name, "kind"),
                    says(
                        "{value} is not used by {kind}",
                        value=Op(value) if number else operand(value),
                        kind=self.kind,
                    ),  # fmt: skip
                    Reason.CONFLICT,
                    code=Code.OPTION_NOT_OFFERED,
                    then=f"Leave {name} blank for {self.kind}.",
                )
        if self.kind != "toggle" and self.immediate:
            check.refuse(
                ("immediate", "kind"),
                says("{kind} has no immediate form", kind=self.kind),
                Reason.CONFLICT,
                code=Code.IMMEDIATE_NOT_ALLOWED,
                then=f"Set immediate to False for {self.kind}.",
            )
        if self.kind != "timed" and self.maintained:
            check.refuse(
                ("maintained", "kind"),
                says("only a timed coil can be maintained"),
                Reason.CONFLICT,
                code=Code.OPTION_NOT_OFFERED,
                then=f"Set maintained to False for {self.kind}.",
            )
        if self.kind == "toggle":
            return
        # Look up the func code with ``maintained`` as given. If ``maintained`` is not a bool,
        # the lookup can fail, and then ``unit`` is refused first. check.flag refuses
        # ``maintained`` itself last. Skip the lookup if ``maintained`` was refused above,
        # for a kind that has no Output Maintained box, because that refusal already
        # explains the failure.
        if not check.refused("maintained") and not is_choice(
            (self.kind, self.unit, self.maintained), OUT_VARIANT_FUNC_CODES
        ):
            check.refuse(
                ("unit", "kind"),
                says(
                    "{kind} does not support unit={unit}",
                    kind=self.kind,
                    unit=choice_operand(self.unit),
                ),  # fmt: skip
                Reason.CHOICE,
                code=Code.COIL_TIME_UNIT,
                then=f"Set unit to {_units_of(self.kind)}.",
            )
        floor = _PRESET_FLOORS[self.kind]
        phases = ["on", "off"] if self.kind in _TWO_PHASE else ["on"]
        if self.kind == "debounce":
            # Skip a debounce phase whose two fields are both empty. If both phases are empty,
            # refuse the on preset with OBJ-006. CLICK writes a debounce with only an on phase
            # and one with only an off phase. tests/fixtures/v4_captures/debounce_one_phase.bin
            # holds both.
            filled = [ph for ph in phases if self._phase_fields(ph) != ("", "")]
            if not filled:
                check.refuse(
                    "on_preset",
                    says(
                        "debounce needs an on phase or an off phase "
                        "(on_acc and on_preset, or off_acc and off_preset)"
                    ),
                    Reason.MISSING,
                    "OBJ-006",
                    code=Code.DEBOUNCE_NEEDS_PHASE,
                )
                return
            phases = filled
        accs = []
        for ph in phases:
            accs.append(check(f"{ph}_acc", check_address, _ACC_BANKS))
            check(f"{ph}_preset", _check_preset, floor)
        # The same register for both phases is refused with OBJ-012.
        if len(accs) == 2 and accs[0] is not None and accs[1] is not None:
            if (accs[0].bank, accs[0].number) == (accs[1].bank, accs[1].number):
                check.refuse(
                    ("off_acc", "on_acc"),
                    says(
                        "{acc} is the on accumulator too",
                        "{kind} needs two different TD registers",
                        acc=operand(self.off_acc),
                        kind=self.kind,
                    ),  # fmt: skip
                    Reason.CONFLICT,
                    "OBJ-012",
                    code=Code.DUPLICATE_ADDRESS,
                )

    def _phase_fields(self, phase: str) -> tuple[str, str]:
        """Return ``(accumulator, preset)`` of the on or off phase."""
        if phase == "on":
            return (self.on_acc, self.on_preset)
        return (self.off_acc, self.off_preset)

    @classmethod
    def from_csv_token(cls, token: str) -> OutVariant:
        """Parse ``toggle(...)``, ``debounce(...)``, ``flasher(...)`` or ``timed(...)``."""
        token = token.strip()
        m = re.fullmatch(r"(toggle|debounce|flasher|timed)\((.+)\)", token)
        if not m:
            raise CsvReadError(
                f"Could not read {token!r} as a toggle, debounce, flasher or timed coil. "
                "Write the coil's address first, such as toggle(C1) or "
                "timed(C1,on_acc=TD1,on_preset=1000,unit=Tms)."
            )
        kind = cast(OutVariantKind, m.group(1))
        parts = [seg.strip() for seg in m.group(2).split(",") if seg.strip()]
        if not parts or "=" in parts[0]:
            raise CsvReadError(f"{kind} needs a target operand: {token!r}")

        arg = parts[0]
        if kind == "toggle" and len(parts) > 1:
            raise CsvReadError(
                f"Could not read {token!r}. toggle takes only the coil's address, such as "
                "toggle(C1) or toggle(immediate(Y001))."
            )
        kwargs: dict[str, str] = {}
        for seg in parts[1:]:
            if "=" not in seg:
                raise CsvReadError(
                    f"Could not read {token!r}. After the coil's address, {kind} takes only "
                    "keyword arguments, such as on_acc=TD1."
                )
            k, v = seg.split("=", 1)
            kwargs[k.strip()] = v.strip()

        if kind == "toggle":
            inner = re.fullmatch(r"immediate\((.+)\)", arg)
            if inner:
                return cls(kind="toggle", operand=inner.group(1).strip(), immediate=True)
            return cls(kind="toggle", operand=arg)

        required = {"on_acc", "on_preset", "unit"}
        allowed = set(required)
        if kind in _TWO_PHASE:
            required |= {"off_acc", "off_preset"}
            allowed = set(required)
        else:
            allowed.add("maintained")
        if kind == "debounce":
            # A debounce may leave out one phase; the constructor checks what is given.
            required = {"unit"}
        missing = required - set(kwargs)
        if missing:
            raise CsvReadError(f"{kind} missing keyword argument(s) {sorted(missing)}: {token!r}")
        unknown = set(kwargs) - allowed
        if unknown:
            raise CsvReadError(f"{kind} does not support keyword argument(s): {sorted(unknown)}")
        maintained = check_csv_flag(kwargs, "maintained", "OutVariant.maintained")

        return cls(
            kind=kind,
            operand=arg,
            on_acc=kwargs.get("on_acc", ""),
            on_preset=kwargs.get("on_preset", ""),
            off_acc=kwargs.get("off_acc", ""),
            off_preset=kwargs.get("off_preset", ""),
            unit=cast(OutVariantUnit, kwargs["unit"]),  # the OutVariant refuses any other unit
            maintained=maintained,
        )

    @property
    def func_code(self) -> str:
        flag = self.immediate if self.kind == "toggle" else self.maintained
        return OUT_VARIANT_FUNC_CODES[(self.kind, self.unit, flag)]

    def to_csv(self) -> str:
        if self.kind == "toggle":
            operand = f"immediate({self.operand})" if self.immediate else self.operand
            return f"toggle({operand})"
        parts = [self.operand]
        for ph in ("on", "off") if self.kind in _TWO_PHASE else ("on",):
            acc, preset = self._phase_fields(ph)
            # A one-phase debounce leaves out the empty phase's keywords.
            if self.kind != "debounce" or (acc, preset) != ("", ""):
                parts += [f"{ph}_acc={acc}", f"{ph}_preset={preset}"]
        parts.append(f"unit={self.unit}")
        if self.maintained:
            parts.append("maintained=1")
        return f"{self.kind}({','.join(parts)})"

    def cell_params(self) -> dict:
        """Return the ``ClickCell`` keyword arguments that depend on this instruction alone."""
        return dict(_KIND_CELL_PARAMS[self.kind])

    def _tag_values(self) -> list[str]:
        """Return the values to write for ``_OUT_VARIANT_TAGS``, in order."""
        return [
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
        ]

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this Out variant cell."""
        from ..binary_helpers import _build_blob

        return _build_blob("Out", 0x2715, _OUT_VARIANT_TAGS, self._tag_values())


# ---------------------------------------------------------------------------
# Shared from_tags factory
# ---------------------------------------------------------------------------


def _writes_tags(decoded: OutVariant, tags: dict[int, str]) -> bool:
    """Return True if encoding *decoded* again writes every value that the blob holds.

    A blob can hold a value that the kind's dialog never writes, such as an accumulator, a
    unit or a range end in a toggle, or an immediate flag in a timed coil. Encoding would
    lose that value, so such a blob stays raw. A blank or missing tag holds no value, because
    SCR files leave out each tag that has its default value.
    """
    for tag, written in zip(_OUT_VARIANT_TAGS, decoded._tag_values(), strict=True):
        held = tags.get(tag, "")
        if held and held != written:
            return False
    return True


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> OutVariant | None:
    """Build an ``OutVariant`` from the tags of an instruction blob, or return None.

    Return None if the blob is not an Out variant that this function can read, or if
    encoding the result again would lose a value that the blob holds. The clipboard
    decoder and the program-file decoder both call this.
    """
    if class_name != "Out" or type_code != 0x2715:
        return None
    # Read the func code with tags.get, not tag_value. Each family has its own func codes,
    # so the func code has no tag default (see binary_helpers.tag_default).
    variant = _FUNC_TO_VARIANT.get(tags.get(0x3218, ""))
    operand = tag_value(tags, 0x6066)
    if variant is None or not operand:
        return None
    kind, unit, flag = variant
    if kind == "toggle":
        decoded = OutVariant(kind="toggle", operand=operand, immediate=flag)
        return decoded if _writes_tags(decoded, tags) else None
    if TIMER_UNITS.get(tag_value(tags, 0x21F9)) != unit:
        return None
    decoded = OutVariant(
        kind=kind,
        operand=operand,
        on_acc=tag_value(tags, 0x60B4),
        on_preset=tag_value(tags, 0x60B3),
        off_acc=tag_value(tags, 0x60B6),
        off_preset=tag_value(tags, 0x60B5),
        unit=unit,
        maintained=flag,
    )
    return decoded if _writes_tags(decoded, tags) else None


def cell_params_from_tags(class_name: str, type_code: int, tags: dict[int, str]) -> dict | None:
    """Return the ``ClickCell`` keyword arguments of an Out blob whose func code (tag 0x3218)
    names a variant kind, or None for any other blob."""
    if class_name != "Out" or type_code != 0x2715:
        return None
    variant = _FUNC_TO_VARIANT.get(tags.get(0x3218, ""))
    return None if variant is None else dict(_KIND_CELL_PARAMS[variant[0]])


def parse_af_call(call: AfCall) -> OutVariant:
    """Parse a call from a CSV rung's AF (output) column into an ``OutVariant``."""
    return OutVariant.from_csv_token(call.to_token())


SPEC = AfInstructionFamilySpec(
    family_name="out_variant",
    instruction_types=(OutVariant,),
    # Coil also uses the class name "Out", and coil.py's SPEC registers that name in
    # INSTRUCTION_MODULES. The decoders try the from_tags of every family in turn, so the
    # func code decides which family decodes an Out blob.
    binary_class_names=(),
    from_tags=from_tags,
    csv_names=("toggle", "debounce", "flasher", "timed"),
    parse_csv_call=parse_af_call,
    cell_params_from_tags=cell_params_from_tags,
)
