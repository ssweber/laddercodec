"""Compare today's per-field checks with the shared field checks, field by field.

    uv run python -I devtools/classify_dryrun.py [<src_dir>]

For every field that takes a constant (and the coil target), each value of a fixed list is
tried two ways:

- today: the instruction is built from a known-good baseline with the field set to the
  value; the verdict is ``accept`` or ``refuse`` with the exception.
- shared: the field's call to :mod:`laddercodec.operands.checks` (``check_operand``,
  ``check_constant``, ``check_out_target``) with that field's parameters, plus the pairing
  the family keeps for itself (a Compare group, a Copy destination, a Search table).

Every disagreement is printed: field, value, today's verdict, the shared verdict.  When
both refuse with different exception classes the case is listed as ``class``: the rule
shows the order of calls that keeps today's class, and the family that wires the shared
check in follows it.  The script exits 1 on any disagreement, verdict or class, and
changes nothing.  ``<src_dir>`` (default ``src``) is the laddercodec source tree under
test.

Left out: Math, whose formula has its own grammar (``math_formula.parse``).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _text(n: int) -> str:
    return '"' + "A" * n + '"'


#: The values tried: the constant values of operand_probe.OPERANDS, then edges of each kind,
#: then addresses.
VALUES: list[str] = [
    *["", "0", "-0", "007", "+1", "1", "-1", "10", "100", "9999"],
    *["32767", "32768", "-32768", "-32769", "65535", "65536"],
    *["2147483647", "2147483648", "-2147483648", "-2147483649", "3000000000", "6000000000"],
    *["FFFFh", "ffffh", "FFFFH", "0FFFFh", "10000h", "+1h", "0H", "0h", "1h", "0000h"],
    *["7FFFh", "8000h", "FFFFFFFFh", "100000000h", "h", "FFFF"],
    *["٣", "1٣", "DS٣"],
    *['"A"', '"AB"', _text(128), _text(129), '""', '"""', '"$41"', "$41", "$100", "$1"],
    *["'A'", '"a,b"', '"A', "A"],
    *["1.5", "1E5", ".5", "-1.5e-3", "1.", "3.4028235E+38", "3.5E+38", "nan", "inf"],
    *[" DS1", "DS1 ", "DS 1", " 5", "5 ", "1 0", " ", "DS1, DS2"],
    *["Q1", "DSX1", "DS1..DS5", "DS-1", "DS1.5", "Tms", "none", "abc"],
    # Edges beyond the probe's list.
    *["+2147483647", "1-2", "--5", "000000000005", "0000000000005", "-0.0", "1e5"],
    *["0x10", "1_000", "1,5", "１", "-1h", "1Gh", "1HH", "FFFEh", "FFFDh", "0FFFEh", "0000Fh"],
    *["FFFFFh", "0FFFFFFFFh", "$00", "$FF", "$ff", "$0d", "$0D", "$D", "$22", "$4142"],
    *['"a"b"', '"é"', '" "', '"~"', "1E999", "-1E999", "000000001h", "+1.5", "DH"],
    # Addresses.
    *["DS1", "ds1", "DH1", "TXT1", "DS[DS1]", "DD[DS1]", "TXT[DS1]", "DS[DD1]", "DS0"],
    *["DD1", "DF1", "TD1", "CTD1", "SD1", "XD0", "XD0u", "YD1", "X001", "x1", "Y001"],
    *["C1", "T1", "CT1", "SC1", "SC50", "SC326"],
]

#: Verdicts.
ACCEPT, REFUSE = "accept", "refuse"


@dataclass
class Field:
    """One field, probed from one baseline."""

    family: str
    label: str
    build: Callable[[Any, str], Any]  # (namespace, value) -> instance
    rule: Callable[[Any, str], Any]  # (namespace, value) -> raises if refused


class Namespace:
    """laddercodec names from the tree under test."""

    def __init__(self, src_dir: str) -> None:
        src = Path(src_dir).resolve()
        if not (src / "laddercodec" / "operands" / "checks.py").is_file():
            raise SystemExit(f"{src} has no laddercodec/operands/checks.py")
        sys.path.insert(0, str(src))
        import laddercodec
        from laddercodec import instructions
        from laddercodec.model import AddressError, FieldError, InstructionType, normalize_address
        from laddercodec.operands import checks
        from laddercodec.operands.constants import SEARCH_TABLE_BANKS, Kind

        loaded = Path(laddercodec.__file__).resolve().parent.parent
        if loaded != src:
            raise SystemExit(f"laddercodec loaded from {loaded}, not {src}")
        self.inst: Any = instructions
        self.checks: Any = checks
        self.Kind: Any = Kind
        self.FieldError: Any = FieldError
        self.AddressError: Any = AddressError
        self.InstructionType: Any = InstructionType
        self.normalize: Any = normalize_address
        self.search_tables: Any = SEARCH_TABLE_BANKS

    def constants(self, kinds: Any = None, **limits: Any) -> Any:
        """``Constants`` of ``kinds`` (default: every kind) with ``limits``."""
        k = self.checks.ALL_KINDS if kinds is None else frozenset(kinds)
        return self.checks.Constants(k, **limits)

    def refuse(self, message: str, *, address: bool = False) -> None:
        """A refusal the family keeps for itself (a pairing), in the family's class."""
        raise (self.AddressError if address else self.FieldError)(message)


# ---------------------------------------------------------------------------
# Banks the families keep (their own rows; the shared checks take them as parameters)
# ---------------------------------------------------------------------------

BIT_BANKS = frozenset({"X", "Y", "C", "T", "CT", "SC"})
REGISTER_BANKS = frozenset({"DS", "DD", "DH", "DF", "XD", "YD", "TD", "CTD", "SD", "TXT"})
COMPARE_GROUPS = {
    "hex": frozenset({"XD", "YD", "DH"}),
    "numeric": frozenset({"TD", "CTD", "DS", "DD", "DF", "SD"}),
    "text": frozenset({"TXT"}),
}
COMPARE_BANKS = frozenset().union(*COMPARE_GROUPS.values())
FOR_LIMIT_BANKS = frozenset({"DS", "DD", "TD", "CTD", "SD"})


# ---------------------------------------------------------------------------
# Field rules: the shared calls with each field's parameters
# ---------------------------------------------------------------------------


def compare_rule(other_group: str) -> Callable[[Any, str], None]:
    """Compare operand opposite one of ``other_group``.

    Every kind; hex is 16-bit; a real is any spelling (a value beyond float32, such as
    ``3.5E+38``, is accepted until CLICK's edge is checked).  The family keeps the group
    pairing: a numeric operand takes an integer or a real, a hex one a hex constant, a text
    one quoted text or ``$hh``.
    """

    def rule(ns: Any, value: str) -> None:
        constants = ns.constants(hex_high=0xFFFF, float32=False)
        text = ns.normalize(value)
        op = ns.checks.check_operand(text, "CompareContact.x", COMPARE_BANKS, constants)
        if op.constant is not None:
            kind = op.constant.kind
            group = {"integer": "numeric", "float": "numeric", "hex": "hex"}.get(kind, "text")
        else:
            group = next(g for g, banks in COMPARE_GROUPS.items() if op.bank in banks)
        if group != other_group:
            ns.refuse("not in one compare group")

    return rule


def _wide_hex(text: str) -> bool:
    """Whether hex-shaped ``text`` is above FFFFh."""
    return int(text.upper().rstrip("H").lstrip("+-") or "0", 16) > 0xFFFF


def copy_rule(dest: str) -> Callable[[Any, str], None]:
    """Single Copy source into ``dest``.

    Every kind at the shared check's limits; a signed hex text reads as a (refused) hex
    constant.  The family keeps the pairing, in its own class (AddressError): text and
    ``$hh`` go to TXT only, hex above FFFFh to DD or CTD only, bits to Y and C only.  A
    number constant goes to every register, TXT included.  The pairing comes before a
    constant's limits (``constant_shape``), except that a ``$hh`` code is read first.
    """

    def rule(ns: Any, value: str) -> None:
        text = ns.normalize(value)
        constants = ns.constants(hex_sign=True)
        shape = ns.checks.constant_shape(text, constants)
        if shape == ns.Kind.CHAR:
            ns.checks.check_constant(text, "Copy.source", constants)
        if shape in (ns.Kind.TEXT, ns.Kind.CHAR) and dest != "TXT":
            ns.refuse("text copies to TXT", address=True)
        if shape == ns.Kind.HEX and _wide_hex(text) and dest not in ("DD", "CTD"):
            ns.refuse("hex above FFFFh copies to DD, CTD", address=True)
        op = ns.checks.check_operand(
            text, "Copy.source", BIT_BANKS | REGISTER_BANKS, constants, pointer=True
        )
        if op.constant is None and op.bank in BIT_BANKS:
            ns.refuse("a bit copies to Y, C", address=True)

    return rule


def termination_rule(ns: Any, value: str) -> None:
    """Copy termination code: the keyword ``0`` or ``none`` (no code), or ``$hh``."""
    if value in ("0", "none"):
        return
    ns.checks.check_constant(value, "Copy.termination_code", ns.constants({ns.Kind.CHAR}))


def fill_rule(dest: str) -> Callable[[Any, str], None]:
    """Fill value into a ``dest`` range.

    Every kind at the shared check's limits, hex above FFFFh included; a Fill into TXT
    takes one character of text.  The family keeps the pairing, in its own class
    (AddressError): text goes to TXT only, a numeric register to the numeric banks, a TXT
    to TXT.  A number constant goes to every register, TXT included.  The pairing comes
    before a constant's limits (``constant_shape``), except that a ``$hh`` code is read
    first.
    """

    def rule(ns: Any, value: str) -> None:
        text = ns.normalize(value)
        text_max = 1 if dest == "TXT" else 128
        constants = ns.constants(hex_sign=True, text_max=text_max)
        shape = ns.checks.constant_shape(text, constants)
        if shape == ns.Kind.CHAR:
            ns.checks.check_constant(text, "Fill.value", constants)
        if shape in (ns.Kind.TEXT, ns.Kind.CHAR) and dest != "TXT":
            ns.refuse("text fills TXT", address=True)
        op = ns.checks.check_operand(text, "Fill.value", REGISTER_BANKS, constants)
        if op.constant is None and (op.bank == "TXT") != (dest == "TXT"):
            ns.refuse("a TXT fills TXT, a numeric register the numeric banks", address=True)

    return rule


def search_rule(table: str) -> Callable[[Any, str], None]:
    """Search value against a ``table`` range (``==``).

    Every kind; hex is 16-bit.  The family keeps the pairing of a constant's kind with the
    table banks: an integer or a real searches DS, DD, DF, TD and CTD, hex DH, text or
    ``$hh`` TXT.
    """

    def rule(ns: Any, value: str) -> None:
        constants = ns.constants(hex_high=0xFFFF, hex_sign=True)
        text = ns.normalize(value)
        op = ns.checks.check_operand(text, "Search.source", REGISTER_BANKS, constants)
        if op.constant is not None and table not in ns.search_tables[op.constant.kind]:
            ns.refuse("the value's kind does not search this table")

    return rule


def digits_rule(
    name: str,
    banks: frozenset[str],
    low: int,
    high: int,
    *,
    letter_first: bool,
) -> Callable[[Any, str], None]:
    """A digits-only constant from ``low`` to ``high``, or a register of ``banks``."""

    def rule(ns: Any, value: str) -> None:
        text = ns.normalize(value)
        constants = ns.constants({ns.Kind.INTEGER}, signs="", low=low, high=high)
        ns.checks.check_operand(text, name, banks, constants, letter_first=letter_first)

    return rule


def for_limit_rule(ns: Any, value: str) -> None:
    """For count: outer spaces stripped; digits only, 0 to 2147483647; or a register of
    DS, DD, TD, CTD or SD.  The family keeps two refusals of its own: a blank count, and
    digits with a space inside."""
    text = value.strip()
    if not text:
        ns.refuse("a For count is not blank")
    if re.fullmatch(r"[0-9]+(\s+[0-9]+)+", text):
        ns.refuse("a constant count is digits only")
    constants = ns.constants({ns.Kind.INTEGER}, signs="", low=0, high=2**31 - 1)
    ns.checks.check_operand(ns.normalize(text), "ForLoop.limit", FOR_LIMIT_BANKS, constants)


def counter_rule(ns: Any, value: str) -> None:
    """Counter preset: an int32 integer, a leading ``-`` only, at most 12 characters; or a
    DS or DD register.  Text that starts with a letter is an address."""
    constants = ns.constants({ns.Kind.INTEGER}, signs="-", max_length=12)
    ns.checks.check_operand(
        ns.normalize(value), "Counter.preset", {"DS", "DD"}, constants, letter_first=True
    )


def modbus_hex_rule(ns: Any, value: str) -> None:
    """Remote address: a MODBUS 984 number (digits), or hex from 0h to FFFEh."""
    if value.endswith(("h", "H")):
        constants = ns.constants({ns.Kind.HEX}, hex_high=0xFFFE)
        ns.checks.check_constant(value, "ModbusAddress.address", constants)
    elif not (value.isascii() and value.isdigit()):
        ns.refuse("not a MODBUS 984 number or hex")


def out_target_rule(immediate: bool) -> Callable[[Any, str], None]:
    """Coil target: Y, C or a writable SC bit; immediate takes Y only."""

    def rule(ns: Any, value: str) -> None:
        ns.checks.check_out_target(ns.normalize(value), "Coil.operand", immediate=immediate)

    return rule


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------


def _make(cls: str, **base: Any) -> Callable[[str], Callable[[Any, str], Any]]:
    def field(name: str) -> Callable[[Any, str], Any]:
        def build(ns: Any, value: str) -> Any:
            return getattr(ns.inst, cls)(**{**base, name: value})

        return build

    return field


_COMPARE_OTHER = {"numeric": "DS1", "hex": "DH1", "text": "TXT1"}


def _bits() -> list[Field]:
    out: list[Field] = []
    for group, other in _COMPARE_OTHER.items():
        for side, fixed in (("right", "left"), ("left", "right")):
            base = {"op": "==", fixed: other, side: "DS1"}
            out.append(
                Field(
                    "bits",
                    f"CompareContact.{side} ({fixed}={other})",
                    _make("CompareContact", **base)(side),
                    compare_rule(group),
                )
            )
    out_variants = {
        "debounce": dict(on_acc="TD3", on_preset="100", off_acc="TD4", off_preset="200"),
        "flasher": dict(on_acc="TD12", on_preset="500", off_acc="TD13", off_preset="250"),
        "timed": dict(on_acc="TD18", on_preset="1000"),
    }
    for kind, base in out_variants.items():
        # 0 to 32767 for debounce, 1 to 32767 for flasher and timed; digits only.
        floor = 0 if kind == "debounce" else 1
        make = _make("OutVariant", kind=kind, operand="C1", unit="Tms", **base)
        for phase in ("on", "off") if kind != "timed" else ("on",):
            name = f"OutVariant.{phase}_preset"
            out.append(
                Field(
                    "bits",
                    f"{name} ({kind})",
                    make(f"{phase}_preset"),
                    digits_rule(name, frozenset({"DS"}), floor, 32767, letter_first=True),
                )
            )
    for immediate in (False, True):

        def coil(ns: Any, value: str, immediate: bool = immediate) -> Any:
            return ns.inst.Coil(
                type=ns.InstructionType.COIL_OUT, operand=value, immediate=immediate
            )

        label = "Coil.operand (immediate)" if immediate else "Coil.operand"
        out.append(Field("bits", label, coil, out_target_rule(immediate)))
    return out


def _move() -> list[Field]:
    out: list[Field] = []
    copy_dests = {"DS": "DS9", "DD": "DD1", "DF": "DF1", "DH": "DH1", "TXT": "TXT2"}
    for bank, dest in copy_dests.items():
        out.append(
            Field(
                "move",
                f"Copy.source (destination={dest})",
                _make("Copy", destination=dest)("source"),
                copy_rule(bank),
            )
        )
    out.append(
        Field(
            "move",
            "Copy.termination_code (DS20 -> TXT7, to_text)",
            _make(
                "Copy",
                source="DS20",
                destination="TXT7",
                format="text",
                suppress_zero="1",
            )("termination_code"),
            termination_rule,
        )
    )
    for bank, (start, end) in {"DS": ("DS52", "DS55"), "TXT": ("TXT2", "TXT5")}.items():
        out.append(
            Field(
                "move",
                f"Fill.value ({start}..{end})",
                _make("Fill", dest_start=start, dest_end=end)("value"),
                fill_rule(bank),
            )
        )
    tables = {"DS": ("DS72", "DS81"), "DH": ("DH72", "DH81"), "TXT": ("TXT1", "TXT10")}
    for bank, (start, end) in tables.items():
        search = _make(
            "Search", table_start=start, table_end=end, result="DS82", found="C81", comparison="=="
        )
        out.append(
            Field("move", f"Search.source ({start}..{end} ==)", search("source"), search_rule(bank))
        )
    return out


def _data_flow_comm() -> list[Field]:
    out = [
        Field(
            "data",
            "Timer.setpoint (on_delay)",
            _make("Timer", timer_type="on_delay", done_bit="T1", current="TD1", unit="Tms")(
                "setpoint"
            ),
            # Digits only, 0 to 32767 for every unit; any other text is an address.
            digits_rule("Timer.setpoint", frozenset({"DS"}), 0, 32767, letter_first=False),
        ),
        Field(
            "data",
            "Counter.preset (count_up)",
            _make(
                "Counter",
                counter_type="count_up",
                done_bit="CT1",
                current="CTD1",
                reset_enabled=True,
            )("preset"),
            counter_rule,
        ),
    ]

    def drum(ns: Any, value: str) -> Any:
        return ns.inst.Drum(
            drum_kind="time",
            outputs=["C1361", "C1362"],
            events_or_presets=[value, "DS1303"],
            pattern=[[1, 0], [0, 1]],
            current_step="DS1206",
            completion_flag="C1406",
            accumulator="TD106",
            unit="Tms",
        )

    # Digits only, 0 to 32767 for every unit; text that starts with a letter is an address.
    out.append(
        Field(
            "data",
            "Drum.presets[0] (time)",
            drum,
            digits_rule("Drum.presets[0]", frozenset({"DS"}), 0, 32767, letter_first=True),
        )
    )
    out.append(Field("flow", "ForLoop.limit", _make("ForLoop")("limit"), for_limit_rule))
    out.append(
        Field(
            "comm",
            "ModbusAddress.address (holding)",
            _make("ModbusAddress", register_type="holding")("address"),
            modbus_hex_rule,
        )
    )
    return out


def _fields() -> list[Field]:
    return [*_bits(), *_move(), *_data_flow_comm()]


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def _show(value: Any) -> str:
    """A value as ASCII, long text shortened."""
    if isinstance(value, str) and len(value) > 24:
        return f"{ascii(value[:8])}...({len(value)} chars)"
    return ascii(value)


def _verdict(call: Callable[[], Any]) -> tuple[str, str, str]:
    """``(verdict, exception class, message)`` of ``call``."""
    try:
        call()
    except Exception as exc:  # any refusal counts
        return REFUSE, type(exc).__name__, str(exc)
    return ACCEPT, "", ""


def _skip(field: Field, value: str) -> bool:
    # An empty Out variant preset is the phase rule, not a constant.
    return field.label.startswith("OutVariant") and value == ""


def _run(ns: Any, field: Field) -> tuple[int, int, int, list[str]]:
    """``(compared, differ, class, lines)`` for one field."""
    compared = differ = classes = 0
    lines: list[str] = []
    for value in VALUES:
        if _skip(field, value):
            continue
        compared += 1
        today, today_cls, error = _verdict(lambda v=value: field.build(ns, v))
        shared, shared_cls, why = _verdict(lambda v=value: field.rule(ns, v))
        if today != shared:
            differ += 1
            shown = f"{today} ({today_cls}: {error})" if error else today
            rule = f"{shared} ({shared_cls}: {why})" if why else shared
            lines.append(f"  DIFFERS {_show(value)} | today {shown} | shared {rule}")
        elif today_cls != shared_cls:
            classes += 1
            lines.append(f"  class   {_show(value)} | today {today_cls} | shared {shared_cls}")
    return compared, differ, classes, lines


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # ty: ignore[missing-union-attribute]
    args = sys.argv[1:] if argv is None else argv
    ns = Namespace(args[0] if args else "src")
    fields = _fields()
    totals: dict[str, list[int]] = {}
    print(f"shared field check dry run: {len(fields)} fields x {len(VALUES)} values")
    print("format: field | value | today | shared")
    print("left out: Math (its formula has its own grammar)")
    for field in fields:
        compared, differ, classes, lines = _run(ns, field)
        print()
        print(
            f"[{field.family}] {field.label}: {compared} compared, {differ} differ, {classes} class"
        )
        print("\n".join(lines) if lines else "  (no differences)")
        family = totals.setdefault(field.family, [0, 0, 0])
        family[0] += compared
        family[1] += differ
        family[2] += classes
    print()
    print("Totals by family (compared / differ / class):")
    for family, (compared, differ, classes) in totals.items():
        print(f"  {family}: {compared} / {differ} / {classes}")
    return 1 if any(t[1] or t[2] for t in totals.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
