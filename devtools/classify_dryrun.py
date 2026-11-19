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
    sys.modules[name] = module  # @dataclass looks the module up in sys.modules
    spec.loader.exec_module(module)
    return module


#: Two sibling scripts, loaded as modules. operand_probe.py supplies the baselines and the case
#: keys. identity_diff.py reads the expected-diff file and judges its entries.
PROBE: Any = _load("operand_probe")
IDENTITY: Any = _load("identity_diff")


def _text(n: int) -> str:
    return '"' + "A" * n + '"'


#: The values tried on each field. The list starts with the constant values of
#: operand_probe.OPERANDS, then adds edge cases of each kind, then addresses.
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
    # Edge cases that operand_probe.OPERANDS does not hold.
    *["+2147483647", "1-2", "--5", "000000000005", "0000000000005", "-0.0", "1e5"],
    *["0x10", "1_000", "1,5", "１", "-1h", "1Gh", "1HH", "FFFEh", "FFFDh", "0FFFEh", "0000Fh"],
    *["FFFFFh", "0FFFFFFFFh", "$00", "$FF", "$ff", "$0d", "$0D", "$D", "$22", "$4142"],
    *['"a"b"', '"é"', '" "', '"~"', "1E999", "-1E999", "000000001h", "+1.5", "DH"],
    # Two strings longer than the 4300 digits that Python's int() accepts: 5000 zeros and
    # a 1, and 5000 ones.
    *["0" * 5000 + "1", "1" * 5000],
    # Addresses.
    *["DS1", "ds1", "DH1", "TXT1", "DS[DS1]", "DD[DS1]", "TXT[DS1]", "DS[DD1]", "DS0"],
    *["DD1", "DF1", "TD1", "CTD1", "SD1", "XD0", "XD0u", "YD1", "X001", "x1", "Y001"],
    *["C1", "T1", "CT1", "SC1", "SC50", "SC326"],
]

#: The two verdicts that a value can get.
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
    #: Turn a value into the field value that the case key holds. For Drum presets, the key
    #: holds the whole tuple of presets.
    keyed: Callable[[str], Any] = lambda value: value


class Namespace:
    """The laddercodec names that the rules use, imported from the source tree under test."""

    def __init__(self, src_dir: str) -> None:
        src = Path(src_dir).resolve()
        if not (src / "laddercodec" / "operands" / "checks.py").is_file():
            raise SystemExit(f"{src} has no laddercodec/operands/checks.py")
        sys.path.insert(0, str(src))
        import laddercodec
        from laddercodec import instructions
        from laddercodec.codes import Code
        from laddercodec.instructions.comparison import GROUP_BANKS
        from laddercodec.instructions.forloop import FOR_LIMIT_BANKS
        from laddercodec.model import AddressError, FieldError, InstructionType, normalize_address
        from laddercodec.operands import checks
        from laddercodec.operands.constants import SEARCH_TABLE_BANKS, Kind, real_beyond_kept_digits

        loaded = Path(laddercodec.__file__).resolve().parent.parent
        if loaded != src:
            raise SystemExit(f"laddercodec loaded from {loaded}, not {src}")
        self.inst: Any = instructions
        self.checks: Any = checks
        self.Kind: Any = Kind
        self.Code: Any = Code
        self.FieldError: Any = FieldError
        self.AddressError: Any = AddressError
        self.InstructionType: Any = InstructionType
        self.normalize: Any = normalize_address
        self.search_tables: Any = SEARCH_TABLE_BANKS
        self.real_beyond_kept_digits: Any = real_beyond_kept_digits
        # The shared checks hold their own banks. The banks below belong to one instruction
        # family each, and come from that family's module.
        self.compare_groups: Any = GROUP_BANKS
        self.compare_banks: Any = frozenset().union(*GROUP_BANKS.values())
        self.for_limit_banks: Any = FOR_LIMIT_BANKS

    def constants(self, kinds: Any = None, **limits: Any) -> Any:
        """Return ``Constants`` for ``kinds`` with ``limits``. None means every kind."""
        k = self.checks.ALL_KINDS if kinds is None else frozenset(kinds)
        return self.checks.Constants(k, **limits)

    def refuse(self, message: str, *, code: str, address: bool = False) -> None:
        """Raise a refusal that the instruction family makes itself, such as a refused pairing.

        Raise AddressError if ``address`` is true, and FieldError if it is not. ``code`` is
        the name of a ``Code`` member."""
        raise (self.AddressError if address else self.FieldError)(message, code=self.Code[code])


# ---------------------------------------------------------------------------
# Field rules: the shared calls with each field's parameters
# ---------------------------------------------------------------------------


def compare_rule(other_group: str, *, data_b: bool) -> Callable[[Any, str], None]:
    """Return the rule for a Compare operand whose other side is in ``other_group``.

    The rule accepts a constant of every kind. A hex constant is at most FFFFh. A real must
    fit float32, and ``3.5E+38`` is refused with OBJ-005. The Compare family checks the group
    pairing itself. Opposite a numeric operand the rule accepts an integer or a real, opposite
    a hex operand a hex constant, and opposite a text operand quoted text or ``$hh``. Data B
    (``data_b``) also takes ``$`` and one hex digit, and text of the characters a single
    Copy's text holds, and refuses a hex constant that spells a bank name (``DH``) opposite
    a hex operand. Data A takes printable ASCII text.
    """

    def rule(ns: Any, value: str) -> None:
        constants = ns.constants(
            hex_high=0xFFFF,
            real_id="OBJ-005",
            one_digit_char=data_b,
            printable=not data_b,
        )
        text = ns.normalize(value)
        op = ns.checks.check_operand(text, "CompareContact.x", ns.compare_banks, constants)
        if op.constant is not None:
            kind = op.constant.kind
            if kind == ns.Kind.TEXT and not _COPY_TEXT_CHARS.issuperset(str(op.constant.value)):
                ns.refuse(
                    "text holds U+0001 to U+FFFF, no NUL and no surrogate",
                    code="INVALID_TEXT_CONSTANT",
                )
            group = {"integer": "numeric", "float": "numeric", "hex": "hex"}.get(kind, "text")
        else:
            group = next(g for g, banks in ns.compare_groups.items() if op.bank in banks)
        if group != other_group:
            ns.refuse("not in one compare group", code="COMPARE_MIXED_TYPES")
        if data_b and group == "hex" and text.upper() in ns.checks.ADDRESS_BANKS:
            ns.refuse("a bank name is no hex constant", code="INVALID_CONSTANT")

    return rule


def _wide_hex(text: str) -> bool:
    """Return True if the hex constant ``text`` is above FFFFh."""
    return int(text.upper().rstrip("H").lstrip("+-") or "0", 16) > 0xFFFF


#: The constant kinds that are numbers, by their ``Kind`` value.
_NUMBER_KINDS = frozenset({"integer", "hex", "float"})
#: The characters allowed in the quoted text of a single Copy. They are U+0001 to U+FFFF,
#: without the surrogates.
_COPY_TEXT_CHARS = frozenset(chr(c) for c in (*range(0x01, 0xD800), *range(0xE000, 0x10000)))


def copy_rule(dest: str) -> Callable[[Any, str], None]:
    """Return the rule for the source of a single Copy into a ``dest`` register.

    The rule accepts a constant of every kind within the shared check's limits. Text with a
    sign before hex digits, such as ``+1h``, is read as a hex constant and refused as one.

    The Copy family checks the pairing of source and destination itself, and raises
    AddressError when it refuses one:

    - Text and ``$hh`` copy to TXT only.
    - Hex above FFFFh copies to DD or CTD only.
    - A bit copies to Y or C only.

    A number constant copies to every register. A number constant or a number register
    copied into TXT needs a converter. The baseline Copy sets none, so the rule refuses
    these copies. It raises FieldError, because this is a refusal of the format. A TXT
    register copied into a number register other than DF needs to_value or to_ascii. That
    is also a refusal of the format.

    The rule checks a constant's own limits before the pairing, so ``""`` and
    ``100000000h`` into DS1 are refused as bad values. Two refusals come later. Text with a
    character outside U+0001 to U+FFFF, or with a surrogate, is refused after the pairing.
    A real of more than 7 significant digits is refused after the format.

    Before any check, the family writes ``$`` and one hex digit with two digits (``$1``
    becomes ``$01``), as CLICK stores it.
    """

    def rule(ns: Any, value: str) -> None:
        text = ns.normalize(value)
        if len(text) == 2 and text[0] == "$" and text[1] in "0123456789ABCDEFabcdef":
            text = f"$0{text[1]}"
        constants = ns.constants(hex_sign=True, printable=False, quote=True)
        shape = ns.checks.constant_shape(text, constants)
        if shape is not None:
            ns.checks.check_constant(text, "Copy.source", constants)
        if shape in (ns.Kind.TEXT, ns.Kind.CHAR) and dest != "TXT":
            ns.refuse("text copies to TXT", address=True, code="COPY_BANK_INCOMPATIBLE")
        if shape == ns.Kind.HEX and _wide_hex(text) and dest not in ("DD", "CTD"):
            ns.refuse(
                "hex above FFFFh copies to DD, CTD", address=True, code="COPY_BANK_INCOMPATIBLE"
            )
        op = ns.checks.check_operand(
            text,
            "Copy.source",
            ns.checks.BIT_BANKS | ns.checks.REGISTER_BANKS,
            constants,
            pointer=True,
        )
        if op.constant is None and op.bank in ns.checks.BIT_BANKS:
            ns.refuse("a bit copies to Y, C", address=True, code="COPY_BANK_INCOMPATIBLE")
        if op.constant is None and op.bank == "TXT" and dest not in ("DF", "TXT"):
            ns.refuse(
                "a TXT register into a number needs to_value or to_ascii",
                code="COPY_TXT_NEEDS_CONVERT",
            )
        number = op.constant.kind in _NUMBER_KINDS if op.constant else op.bank != "TXT"
        if dest == "TXT" and number:
            ns.refuse("a number into TXT needs a converter", code="COPY_TXT_NEEDS_CONVERT")
        if op.constant and op.constant.kind == ns.Kind.TEXT:
            if not _COPY_TEXT_CHARS.issuperset(str(op.constant.value)):
                ns.refuse(
                    "text holds U+0001 to U+FFFF, no NUL and no surrogate",
                    code="INVALID_TEXT_CONSTANT",
                )
        if op.constant and op.constant.kind == ns.Kind.FLOAT:
            if ns.real_beyond_kept_digits(text) is not None:
                ns.refuse("a real of more than 7 significant digits", code="INVALID_CONSTANT")

    return rule


def termination_rule(ns: Any, value: str) -> None:
    """Check a Copy termination code. Accept ``0`` or ``none``, which mean no code, or ``$hh``."""
    if value in ("0", "none"):
        return
    ns.checks.check_constant(value, "Copy.termination_code", ns.constants({ns.Kind.CHAR}))


def fill_rule(dest: str) -> Callable[[Any, str], None]:
    """Return the rule for the value of a Fill into a ``dest`` range.

    The rule accepts a constant of every kind within the shared check's limits, except
    hex above FFFFh. A Fill into TXT accepts text of one character, a real, or an integer or
    hex constant of one character. The Fill family checks
    the pairing itself, and raises AddressError when it refuses one. Text fills TXT only. A
    numeric register fills the numeric banks only, and a TXT register fills TXT only. A
    number constant fills every register, TXT included. The rule checks the pairing
    (``constant_shape``) before a constant's limits, except that it reads a ``$hh`` code
    first.
    """

    def rule(ns: Any, value: str) -> None:
        text = ns.normalize(value)
        text_max = 1 if dest == "TXT" else 128
        constants = ns.constants(hex_sign=True, text_max=text_max, hex_high=0xFFFF)
        shape = ns.checks.constant_shape(text, constants)
        if shape == ns.Kind.CHAR:
            ns.checks.check_constant(text, "Fill.value", constants)
        if shape in (ns.Kind.TEXT, ns.Kind.CHAR) and dest != "TXT":
            ns.refuse("text fills TXT", address=True, code="COPY_BANK_INCOMPATIBLE")
        op = ns.checks.check_operand(text, "Fill.value", ns.checks.REGISTER_BANKS, constants)
        if (
            dest == "TXT"
            and op.constant is not None
            and op.constant.kind in (ns.Kind.INTEGER, ns.Kind.HEX)
            and len(text) > 1
        ):
            ns.refuse(
                "an integer or hex constant fills one character", code="CONSTANT_OUT_OF_RANGE"
            )
        if op.constant is None and (op.bank == "TXT") != (dest == "TXT"):
            ns.refuse(
                "a TXT fills TXT, a numeric register the numeric banks",
                address=True,
                code="COPY_BANK_INCOMPATIBLE",
            )

    return rule


def search_rule(table: str) -> Callable[[Any, str], None]:
    """Return the rule for the value of a Search with ``==`` in a ``table`` range.

    The rule accepts a constant of every kind. A hex constant is at most FFFFh. The Search
    family itself checks which table banks each kind of constant may search. An integer or
    a real searches DS, DD, DF, TD and CTD. Hex searches DH, and text or ``$hh`` searches
    TXT. ``$`` and one hex digit is a character code too. An address value is in the table's
    compare group. Text may hold the same characters as the text of a single Copy: U+0001 to
    U+FFFF, without the surrogates.
    """

    def rule(ns: Any, value: str) -> None:
        constants = ns.constants(
            hex_high=0xFFFF,
            hex_sign=True,
            printable=False,
            quote=True,
            real_id="OBJ-005",
            one_digit_char=True,
        )
        text = ns.normalize(value)
        op = ns.checks.check_operand(text, "Search.value", ns.checks.REGISTER_BANKS, constants)
        if op.constant is not None and table not in ns.search_tables[op.constant.kind]:
            ns.refuse("the value's kind does not search this table", code="SEARCH_VALUE_BANK")
        groups = ns.compare_groups.values()
        if op.bank is not None and not any(op.bank in g and table in g for g in groups):
            ns.refuse("the value's bank is not in the table's group", code="SEARCH_VALUE_BANK")
        if op.constant and op.constant.kind == ns.Kind.TEXT:
            if not _COPY_TEXT_CHARS.issuperset(str(op.constant.value)):
                ns.refuse(
                    "text holds U+0001 to U+FFFF, no NUL and no surrogate",
                    code="INVALID_TEXT_CONSTANT",
                )

    return rule


def digits_rule(
    name: str,
    banks: frozenset[str],
    low: int,
    high: int,
    *,
    letter_first: bool,
) -> Callable[[Any, str], None]:
    """Return a rule that accepts a constant of digits only, from ``low`` to ``high``.

    The rule also accepts a register in ``banks``."""

    def rule(ns: Any, value: str) -> None:
        text = ns.normalize(value)
        constants = ns.constants({ns.Kind.INTEGER}, signs="", low=low, high=high)
        ns.checks.check_operand(text, name, banks, constants, letter_first=letter_first)

    return rule


def for_limit_rule(ns: Any, value: str) -> None:
    """Check a For count. Strip spaces from both ends, then accept digits only from 0 to
    2147483647, or a register in DS, DD, TD, CTD or SD. The For family makes two refusals
    itself: a blank count, and digits with a space between them. It also reads ``-0`` as
    ``0``, so the rule accepts it."""
    text = value.strip()
    if not text:
        ns.refuse("a For count is not blank", code="BLANK_FIELD")
    if re.fullmatch(r"[0-9]+(\s+[0-9]+)+", text):
        ns.refuse("a constant count is digits only", code="INVALID_CONSTANT")
    if re.fullmatch(r"-0+", text):
        return
    constants = ns.constants({ns.Kind.INTEGER}, signs="", low=0, high=2**31 - 1)
    ns.checks.check_operand(ns.normalize(text), "ForLoop.count", ns.for_limit_banks, constants)


def counter_rule(ns: Any, value: str) -> None:
    """Check a Counter preset. Accept an int32 integer of at most 12 characters whose only
    sign is a leading ``-``, or a DS or DD register. Read text that starts with a letter as
    an address."""
    constants = ns.constants({ns.Kind.INTEGER}, signs="-", max_length=12)
    ns.checks.check_operand(
        ns.normalize(value), "Counter.preset", {"DS", "DD"}, constants, letter_first=True
    )


def modbus_hex_rule(ns: Any, value: str) -> None:
    """Check a Modbus remote address. Accept a MODBUS 984 number in digits, or hex from 0h
    to FFFEh.

    The ModbusAddress family checks the digits itself and calls no shared check. It accepts
    any string of up to 4300 ASCII digits, even a value beyond int32. Python's int()
    refuses a longer string.
    """
    if value.endswith(("h", "H")):
        constants = ns.constants({ns.Kind.HEX}, hex_high=0xFFFE)
        ns.checks.check_constant(value, "ModbusAddress.address", constants)
    elif not (value.isascii() and value.isdigit()) or len(value) > 4300:
        ns.refuse("not a MODBUS 984 number or hex", code="NOT_AN_ADDRESS")


def out_target_rule(immediate: bool) -> Callable[[Any, str], None]:
    """Return the rule for a coil target: Y, C or a writable SC bit, or Y only if ``immediate``."""

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


#: The probe's Compare baselines, one for each compare group. Both operands of each baseline
#: are in that group.
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
                    compare_rule(group, data_b=side == "right"),
                )
            )
    out_variants = {
        "debounce": dict(on_acc="TD3", on_preset="100", off_acc="TD4", off_preset="200"),
        "flasher": dict(on_acc="TD12", on_preset="500", off_acc="TD13", off_preset="250"),
        "timed": dict(on_acc="TD18", on_preset="1000"),
    }
    for kind, base in out_variants.items():
        # A preset is digits only. Debounce accepts 0 to 32767, and flasher and timed
        # accept 1 to 32767.
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
            return ns.inst.Coil(value, kind="out", immediate=immediate)

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
                f"Copy.source (dest={dest})",
                f"Copy/to-{dest}/source",
                _make("Copy", dest=dest)("source"),
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
                dest="TXT7",
                convert="to_text",
                suppress_zero=True,
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
            "Search", table_start=start, table_end=end, result="DS82", found="C81", op="=="
        )
        out.append(
            Field(
                "move",
                f"Search.value ({start}..{end} ==)",
                f"Search/{start}..{end}/value",
                search("value"),
                search_rule(bank),
            )
        )
    return out


def _data_flow_comm() -> list[Field]:
    out = [
        Field(
            "data",
            "Timer.preset (on_delay)",
            "Timer/on/setpoint",
            _make("Timer", kind="on_delay", done="T1", accumulator="TD1", unit="Tms")("preset"),
            # The preset is digits only, from 0 to 32767 for every unit. Any other text is
            # read as an address.
            digits_rule("Timer.preset", frozenset({"DS"}), 0, 32767, letter_first=False),
        ),
        Field(
            "data",
            "Counter.preset (count_up)",
            "Counter/up/preset",
            _make(
                "Counter",
                kind="count_up",
                done="CT1",
                accumulator="CTD1",
                reset_enabled=True,
            )("preset"),
            counter_rule,
        ),
    ]

    def drum(ns: Any, value: str) -> Any:
        return ns.inst.Drum(
            kind="time_drum",
            outputs=("C1361", "C1362"),
            presets=(value, "DS1303"),
            pattern=((1, 0), (0, 1)),
            current_step="DS1206",
            completion_flag="C1406",
            accumulator="TD106",
            unit="Tms",
        )

    # The preset is digits only, from 0 to 32767 for every unit. Text that starts with a
    # letter is read as an address. The Drum family has its own test of whether a preset is
    # a register (letters, then digits). It uses that test for the constant mask in the
    # encoded blob.
    out.append(
        Field(
            "data",
            "Drum.presets[0] (time)",
            "Drum/time/presets",
            drum,
            digits_rule("Drum.presets[0]", frozenset({"DS"}), 0, 32767, letter_first=True),
            lambda value: (value, "DS1303"),
        )
    )
    out.append(
        Field(
            "flow", "ForLoop.count", "ForLoop/int/count", _make("ForLoop")("count"), for_limit_rule
        )
    )
    # This list leaves out the device_id of a Modbus target. A device_id is a number or a
    # DS address, and the Modbus family keeps its own check of it. That check raises FieldError
    # for a bad DS address, where the shared check raises AddressError.
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
    """Return ``value`` as ASCII, and shorten a string of more than 24 characters."""
    if isinstance(value, str) and len(value) > 24:
        return f"{ascii(value[:8])}...({len(value)} chars)"
    return ascii(value)


def _verdict(call: Callable[[], Any]) -> tuple[str, str, str]:
    """Run ``call`` and return ``(verdict, exception class, message)``."""
    try:
        call()
    except Exception as exc:  # count any exception as a refusal
        return REFUSE, type(exc).__name__, str(exc)
    return ACCEPT, "", ""


def _skip(field: Field, value: str) -> bool:
    # OutVariant checks an empty preset by its rules for which phases are filled, not as a
    # constant.
    return field.label.startswith("OutVariant") and value == ""


def _new(verdict: str, cls: str) -> str:
    """Return a verdict as the probe records ``new``: ``ok`` or ``!<ExceptionClass>``."""
    return "ok" if verdict == ACCEPT else f"!{cls}"


def _run(
    ns: Any, field: Field, entries: list[Any], problems: list[str]
) -> tuple[list[int], list[str]]:
    """Try every value on one field and return ``([compared, differ, class, expected], lines)``.

    If an expected-diff entry is misused on one of the field's cases, append the problem to
    ``problems``."""
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
