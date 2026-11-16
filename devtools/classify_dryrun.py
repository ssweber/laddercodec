"""Compare today's per-field checks with the shared field checks, field by field.

    uv run python -I devtools/classify_dryrun.py [<src_dir>] [--expected FILE]

For every field that takes a constant (and the coil target), each value of a fixed list is
tried two ways:

- today: the instruction is built from a known-good baseline with the field set to the
  value; the verdict is ``accept`` or ``refuse`` with the exception.
- shared: the field's call to :mod:`laddercodec.operands.checks` (``check_operand``,
  ``check_constant``, ``check_out_target``) with that field's parameters, plus what the
  family keeps for itself (a Compare group, a Copy destination, a Search table, a few
  refusals of its own).

Every disagreement is printed: case key, today's verdict, the shared verdict.  A case is
keyed ``<Class>/<baseline>/<field>=<value>`` as ``operand_probe.py`` keys it, from the
probe's baseline of that name.  When both refuse with different exception classes the case
is listed as ``class``: the rule shows the order of calls that keeps today's class, and the
family that wires the shared check in follows it.  A disagreement that an entry of the
expected-diff file (``--expected``, default ``expected_diff.txt`` beside this script)
allows is listed as ``expected``.  Each entry is judged as ``identity_diff.py --tiers``
judges it (``Expected.judge``), on a disagreeing case only, with today's verdict as the
base's ``new`` and the shared verdict as the branch's (``ok`` or ``!<ExceptionClass>``);
a ``new=`` pin binds that verdict alone, since these records hold nothing else.  The script
exits 1 on any other disagreement, verdict or class, 2 when an entry is misused on a
disagreeing case (a kind (b) entry where today does not crash), and changes nothing.
``<src_dir>`` (default ``src``) is the laddercodec source tree under test.

Left out: Math, whose formula has its own grammar (``math_formula.parse``).
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEVTOOLS = Path(__file__).resolve().parent


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, DEVTOOLS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


#: Case keys and the expected-diff file, as operand_probe.py and identity_diff.py read them.
PROBE: Any = _load("operand_probe")
IDENTITY: Any = _load("identity_diff")


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
    # Digits beyond Python's int() string limit (4300): one significant digit, and 5000.
    *["0" * 5000 + "1", "1" * 5000],
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
    #: ``<Class>/<baseline>/<field>``, the case key without its value.
    key: str
    build: Callable[[Any, str], Any]  # (namespace, value) -> instance
    rule: Callable[[Any, str], Any]  # (namespace, value) -> raises if refused
    #: The field's value in the case key, as the probe varies it.
    keyed: Callable[[str], Any] = lambda value: value


class Namespace:
    """laddercodec names from the tree under test."""

    def __init__(self, src_dir: str) -> None:
        src = Path(src_dir).resolve()
        if not (src / "laddercodec" / "operands" / "checks.py").is_file():
            raise SystemExit(f"{src} has no laddercodec/operands/checks.py")
        sys.path.insert(0, str(src))
        import laddercodec
        from laddercodec import instructions
        from laddercodec.instructions.comparison import _GROUP_BANKS
        from laddercodec.instructions.forloop import FOR_LIMIT_BANKS
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
        # Shared banks come from checks; the family-only ones from their family.
        self.compare_groups: Any = _GROUP_BANKS
        self.compare_banks: Any = frozenset().union(*_GROUP_BANKS.values())
        self.for_limit_banks: Any = FOR_LIMIT_BANKS

    def constants(self, kinds: Any = None, **limits: Any) -> Any:
        """``Constants`` of ``kinds`` (default: every kind) with ``limits``."""
        k = self.checks.ALL_KINDS if kinds is None else frozenset(kinds)
        return self.checks.Constants(k, **limits)

    def refuse(self, message: str, *, address: bool = False) -> None:
        """A refusal the family keeps for itself (a pairing), in the family's class."""
        raise (self.AddressError if address else self.FieldError)(message)


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
        op = ns.checks.check_operand(text, "CompareContact.x", ns.compare_banks, constants)
        if op.constant is not None:
            kind = op.constant.kind
            group = {"integer": "numeric", "float": "numeric", "hex": "hex"}.get(kind, "text")
        else:
            group = next(g for g, banks in ns.compare_groups.items() if op.bank in banks)
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
    constant's limits (``constant_shape``), except that a ``$hh`` code is read first.  The
    family writes ``$`` and one hex digit with two first (``$1`` is ``$01``), as CLICK
    stores it.
    """

    def rule(ns: Any, value: str) -> None:
        text = ns.normalize(value)
        if len(text) == 2 and text[0] == "$" and text[1] in "0123456789ABCDEFabcdef":
            text = f"$0{text[1]}"
        constants = ns.constants(hex_sign=True)
        shape = ns.checks.constant_shape(text, constants)
        if shape == ns.Kind.CHAR:
            ns.checks.check_constant(text, "Copy.source", constants)
        if shape in (ns.Kind.TEXT, ns.Kind.CHAR) and dest != "TXT":
            ns.refuse("text copies to TXT", address=True)
        if shape == ns.Kind.HEX and _wide_hex(text) and dest not in ("DD", "CTD"):
            ns.refuse("hex above FFFFh copies to DD, CTD", address=True)
        op = ns.checks.check_operand(
            text,
            "Copy.source",
            ns.checks.BIT_BANKS | ns.checks.REGISTER_BANKS,
            constants,
            pointer=True,
        )
        if op.constant is None and op.bank in ns.checks.BIT_BANKS:
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
        op = ns.checks.check_operand(text, "Fill.value", ns.checks.REGISTER_BANKS, constants)
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
        op = ns.checks.check_operand(text, "Search.source", ns.checks.REGISTER_BANKS, constants)
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
    ns.checks.check_operand(ns.normalize(text), "ForLoop.limit", ns.for_limit_banks, constants)


def counter_rule(ns: Any, value: str) -> None:
    """Counter preset: an int32 integer, a leading ``-`` only, at most 12 characters; or a
    DS or DD register.  Text that starts with a letter is an address."""
    constants = ns.constants({ns.Kind.INTEGER}, signs="-", max_length=12)
    ns.checks.check_operand(
        ns.normalize(value), "Counter.preset", {"DS", "DD"}, constants, letter_first=True
    )


def modbus_hex_rule(ns: Any, value: str) -> None:
    """Remote address: a MODBUS 984 number (digits), or hex from 0h to FFFEh.

    The family keeps the digits branch: it takes any string of ASCII digits of up to 4300,
    beyond int32 too (int() refuses more), and calls no shared check.
    """
    if value.endswith(("h", "H")):
        constants = ns.constants({ns.Kind.HEX}, hex_high=0xFFFE)
        ns.checks.check_constant(value, "ModbusAddress.address", constants)
    elif not (value.isascii() and value.isdigit()) or len(value) > 4300:
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


#: The probe's Compare baselines, one per compare group; both sides of each are in it.
_COMPARE_BASELINES = {"ds": "numeric", "dh": "hex", "txt": "text"}


def _bits() -> list[Field]:
    out: list[Field] = []
    baselines = PROBE.PROBES["CompareContact"].baselines(None)
    for name, group in _COMPARE_BASELINES.items():
        base = baselines[name]
        for side, fixed in (("right", "left"), ("left", "right")):
            out.append(
                Field(
                    "bits",
                    f"CompareContact.{side} ({fixed}={base[fixed]})",
                    f"CompareContact/{name}/{side}",
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
                    f"OutVariant/{kind}/{phase}_preset",
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
        key = "Coil/out-immediate/operand" if immediate else "Coil/out/operand"
        out.append(Field("bits", label, key, coil, out_target_rule(immediate)))
    return out


def _move() -> list[Field]:
    out: list[Field] = []
    copy_dests = {"DS": "DS9", "DD": "DD1", "DF": "DF1", "DH": "DH1", "TXT": "TXT2"}
    for bank, dest in copy_dests.items():
        out.append(
            Field(
                "move",
                f"Copy.source (destination={dest})",
                f"Copy/to-{dest}/source",
                _make("Copy", destination=dest)("source"),
                copy_rule(bank),
            )
        )
    out.append(
        Field(
            "move",
            "Copy.termination_code (DS20 -> TXT7, to_text)",
            "Copy/to-text/termination_code",
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
                f"Fill/{start}..{end}/value",
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
            Field(
                "move",
                f"Search.source ({start}..{end} ==)",
                f"Search/{start}..{end}/source",
                search("source"),
                search_rule(bank),
            )
        )
    return out


def _data_flow_comm() -> list[Field]:
    out = [
        Field(
            "data",
            "Timer.setpoint (on_delay)",
            "Timer/on/setpoint",
            _make("Timer", timer_type="on_delay", done_bit="T1", current="TD1", unit="Tms")(
                "setpoint"
            ),
            # Digits only, 0 to 32767 for every unit; any other text is an address.
            digits_rule("Timer.setpoint", frozenset({"DS"}), 0, 32767, letter_first=False),
        ),
        Field(
            "data",
            "Counter.preset (count_up)",
            "Counter/up/preset",
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
    # The family keeps its own test of a register preset (letters, then digits) for the
    # blob's constant mask.
    out.append(
        Field(
            "data",
            "Drum.presets[0] (time)",
            "Drum/time/events_or_presets",
            drum,
            digits_rule("Drum.presets[0]", frozenset({"DS"}), 0, 32767, letter_first=True),
            lambda value: [value, "DS1303"],
        )
    )
    out.append(
        Field(
            "flow", "ForLoop.limit", "ForLoop/int/limit", _make("ForLoop")("limit"), for_limit_rule
        )
    )
    # Not here: the Modbus target's device_id, a number or a DS address.  The family keeps
    # its check, which refuses a bad DS address with a FieldError rather than the shared
    # AddressError, and today crashes on DS and more than 4300 digits (int()).
    out.append(
        Field(
            "comm",
            "ModbusAddress.address (holding)",
            "ModbusAddress/holding/address",
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


def _new(verdict: str, cls: str) -> str:
    """A verdict as the probe records ``new``: ``ok`` or ``!<ExceptionClass>``."""
    return "ok" if verdict == ACCEPT else f"!{cls}"


def _run(
    ns: Any, field: Field, entries: list[Any], problems: list[str]
) -> tuple[list[int], list[str]]:
    """``([compared, differ, class, expected], lines)`` for one field; an entry misused on
    one of its cases goes to ``problems``."""
    counts = [0, 0, 0, 0]
    lines: list[str] = []
    for value in VALUES:
        if _skip(field, value):
            continue
        counts[0] += 1
        today, today_cls, error = _verdict(lambda v=value: field.build(ns, v))
        shared, shared_cls, why = _verdict(lambda v=value: field.rule(ns, v))
        if today == shared and today_cls == shared_cls:
            continue
        key = f"{field.key}={PROBE._key(field.keyed(value))}"
        base, branch = {"new": _new(today, today_cls)}, {"new": _new(shared, shared_cls)}
        entry = None
        for candidate in entries:
            if not candidate.matches(key):
                continue
            judgement = candidate.judge(base, branch, verdict_only=True)
            if judgement.problem:
                problems.append(f"{key}: {judgement.problem}")
            elif judgement.allowed and entry is None:
                entry = candidate
        if entry is not None:
            counts[3] += 1
            mark = "expected"
        elif today != shared:
            counts[1] += 1
            mark = "DIFFERS "
        else:
            counts[2] += 1
            mark = "class   "
        shown = f"{today} ({today_cls}: {_short(error)})" if error else today
        rule = f"{shared} ({shared_cls}: {_short(why)})" if why else shared
        lines.append(f"  {mark} {key} | today {shown} | shared {rule}")
    return counts, lines


def _short(text: str) -> str:
    return text if len(text) <= 120 else text[:117] + "..."


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # ty: ignore[missing-union-attribute]
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("src_dir", nargs="?", default="src", help="src directory under test")
    parser.add_argument(
        "--expected", type=Path, default=IDENTITY.EXPECTED, help="expected-diff file"
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    entries = IDENTITY.read_expected(args.expected)
    ns = Namespace(args.src_dir)
    fields = _fields()
    totals: dict[str, list[int]] = {}
    problems: list[str] = []
    print(f"shared field check dry run: {len(fields)} fields x {len(VALUES)} values")
    print("format: case key | today | shared")
    print("left out: Math (its formula has its own grammar)")
    for field in fields:
        counts, lines = _run(ns, field, entries, problems)
        compared, differ, classes, expected = counts
        print()
        print(
            f"[{field.family}] {field.label}: {compared} compared, {differ} differ, "
            f"{classes} class, {expected} expected"
        )
        print("\n".join(lines) if lines else "  (no differences)")
        family = totals.setdefault(field.family, [0, 0, 0, 0])
        for index, count in enumerate(counts):
            family[index] += count
    print()
    print("Totals by family (compared / differ / class / expected):")
    for family, (compared, differ, classes, expected) in totals.items():
        print(f"  {family}: {compared} / {differ} / {classes} / {expected}")
    failures = sum(t[1] + t[2] for t in totals.values())
    expected = sum(t[3] for t in totals.values())
    print(f"{failures} failure(s), {expected} expected")
    if problems:
        IDENTITY.print_problems(problems, args.expected)
        return 2
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
