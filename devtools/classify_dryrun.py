"""Compare today's constant checks with operands.constants.classify(), field by field.

    uv run python -I devtools/classify_dryrun.py [<src_dir>]

For every field that takes a constant, each value of a fixed list is tried two ways:

- today: the instruction is built from a known-good baseline with the field set to the
  value; the verdict is ``accept`` or ``refuse`` with the exception.
- classifier: :func:`classify` (or :func:`parse_digits`) reads the value, and the field's
  documented kinds and limits (the arc.md answers and rulings, each cited at its rule)
  decide.  A valid address is outside this check and is skipped; a rule that waits on an
  arc.md question gives ``open``.

Every disagreement is printed: field, value, today's verdict, the classifier's verdict.
The script changes nothing; a disagreement is a finding for the step that wires the
classifier into that field.  ``<src_dir>`` (default ``src``) is the laddercodec source
tree under test.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _text(n: int) -> str:
    return '"' + "A" * n + '"'


#: The values tried: the constant values of operand_probe.OPERANDS, then edges of each kind.
#: A few addresses stay in to show they are skipped.
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
    *["0x10", "1_000", "1,5", "１", "-1h", "1Gh", "FFFEh", "FFFDh", "0FFFEh", "0000Fh"],
    *["FFFFFh", "0FFFFFFFFh", "$00", "$FF", "$ff", "$0d", "$0D", "$D", "$22", "$4142"],
    *['"a"b"', '"é"', '" "', '"~"'],
    *["DS1", "ds1", "DH1", "TXT1", "DS[DS1]"],
]

#: Verdicts.
ACCEPT, REFUSE, ADDRESS, OPEN = "accept", "refuse", "address", "open"


@dataclass
class Field:
    """One constant-taking field, probed from one baseline."""

    family: str
    label: str
    build: Callable[[Any, str], Any]  # (namespace, value) -> instance
    rule: Callable[[Any, str], tuple[str, str]]  # (namespace, value) -> (verdict, why)


class Namespace:
    """laddercodec names from the tree under test."""

    def __init__(self, src_dir: str) -> None:
        src = Path(src_dir).resolve()
        if not (src / "laddercodec" / "operands" / "constants.py").is_file():
            raise SystemExit(f"{src} has no laddercodec/operands/constants.py")
        sys.path.insert(0, str(src))
        import laddercodec
        from laddercodec import instructions
        from laddercodec.model import check_address, normalize_address
        from laddercodec.operands import constants

        loaded = Path(laddercodec.__file__).resolve().parent.parent
        if loaded != src:
            raise SystemExit(f"laddercodec loaded from {loaded}, not {src}")
        self.inst: Any = instructions
        self.c: Any = constants
        self.check_address: Any = check_address
        self.normalize_address: Any = normalize_address

    def is_address(self, value: str) -> bool:
        """True for an address or pointer in any CLICK bank: not this check's business."""
        text = self.normalize_address(value)
        if "[" in text and text.endswith("]"):
            bank, _, inner = text[:-1].partition("[")
            text = f"{bank}1" if self._valid(inner) else ""
        return self._valid(text)

    def _valid(self, text: str) -> bool:
        try:
            self.check_address(text, "dryrun")
        except ValueError:
            return False
        return True


# ---------------------------------------------------------------------------
# Field rules: the documented kinds and limits, applied to classify()'s result
# ---------------------------------------------------------------------------


def _show(value: Any) -> str:
    """A value as ASCII, long text shortened."""
    if isinstance(value, str) and len(value) > 24:
        return f"{ascii(value[:8])}...({len(value)} chars)"
    return ascii(value)


def _describe(const: Any) -> str:
    if const is None:
        return "no constant"
    wide = " wide" if const.wide else ""
    return f"{const.kind}{wide} {_show(const.value)}"


def _by_kind(ns: Any, value: str, take: Callable[[Any], str | None]) -> tuple[str, str]:
    """Verdict from classify(): ``take(constant)`` returns a verdict, or None to refuse."""
    const = ns.c.classify(value)
    if const is None:
        if ns.is_address(value):
            return ADDRESS, "address"
        return REFUSE, "no constant"
    verdict = take(const)
    return (verdict or REFUSE), _describe(const)


def _digits_rule(low: int, high: int, strip: bool = False) -> Callable[[Any, str], tuple[str, str]]:
    """A digits-only field: parse_digits() from ``low`` to ``high``."""

    def rule(ns: Any, value: str) -> tuple[str, str]:
        text = value.strip() if strip else value
        n = ns.c.parse_digits(text)
        if n is None:
            if ns.is_address(text):
                return ADDRESS, "address"
            return REFUSE, "not digits"
        return (ACCEPT if low <= n <= high else REFUSE), f"digits {n}"

    return rule


def compare_rule(group: str) -> Callable[[Any, str], tuple[str, str]]:
    """Compare, against an operand of ``group``.

    bits.md Q-B7, N5, N6: numeric pairs with an int32 integer or a float, hex with a 16-bit
    hex constant (32-bit hex is OBJ-005 on either side), text with quoted text or ``$hh``.
    arc.md Q-B7 rulings: text is 1 to 128 printable ASCII characters, no quote inside.
    """
    kinds = {"numeric": {"integer", "float"}, "hex": {"hex"}, "text": {"text", "char"}}[group]

    def rule(ns: Any, value: str) -> tuple[str, str]:
        def take(c: Any) -> str | None:
            if c.kind == "hex" and c.wide:
                return None
            return ACCEPT if c.kind in kinds else None

        return _by_kind(ns, value, take)

    return rule


def copy_rule(dest: str) -> Callable[[Any, str], tuple[str, str]]:
    """Single Copy source into ``dest`` (move.md Q-M5; arc.md move field rules).

    A number constant is an int32 integer, a float or hex; hex above FFFFh goes to DD or
    CTD only.  A text constant goes to TXT only.  A number into TXT has no DLL reading or
    ruling: open.
    """

    def rule(ns: Any, value: str) -> tuple[str, str]:
        def take(c: Any) -> str | None:
            if c.kind in ("text", "char"):
                return ACCEPT if dest == "TXT" else None
            if dest == "TXT":
                return OPEN
            if c.kind == "hex" and c.wide:
                return ACCEPT if dest in ("DD", "CTD") else None
            return ACCEPT

        return _by_kind(ns, value, take)

    return rule


def fill_rule(dest: str) -> Callable[[Any, str], tuple[str, str]]:
    """Fill value into ``dest``: Copy's constant kinds (Inst_Copy.dll serves both dialogs).

    No reading covers a 32-bit hex constant or a number constant into a TXT fill: open.
    """

    def rule(ns: Any, value: str) -> tuple[str, str]:
        def take(c: Any) -> str | None:
            if c.kind in ("text", "char"):
                return ACCEPT if dest == "TXT" else None
            if dest == "TXT" or (c.kind == "hex" and c.wide):
                return OPEN
            return ACCEPT

        return _by_kind(ns, value, take)

    return rule


def search_rule(table: str) -> Callable[[Any, str], tuple[str, str]]:
    """Search value against a ``table`` range (move.md Q-M10; arc.md Q-M10 answers, ruling).

    The value's kind picks the table banks: an int32 integer or a float searches DS, DD, DF,
    TD, CTD; 16-bit hex searches DH; text or ``$hh`` searches TXT.  32-bit hex is OBJ-005.
    Text is 1 to 128 printable ASCII characters, no quote inside (ruling).
    """
    table_kinds = {"DS": {"integer", "float"}, "DH": {"hex"}, "TXT": {"text", "char"}}[table]

    def rule(ns: Any, value: str) -> tuple[str, str]:
        def take(c: Any) -> str | None:
            if c.kind == "hex" and c.wide:
                return None
            return ACCEPT if c.kind in table_kinds else None

        return _by_kind(ns, value, take)

    return rule


def math_rule(mode: str) -> Callable[[Any, str], tuple[str, str]]:
    """A constant in a Math formula (move.md Q-M9; arc.md Q-M9, Q-M13, Q-M13b).

    Decimal: an integer whose int32 value prints back as typed (``007``, ``+1``, ``-0``
    refused), or a float; hex in a decimal Math waits on Q-M13.  Hex: hex of at most four
    digits and FFFFh; a decimal number in a hex Math waits on Q-M13b.  Math reads its
    constants with its own check, not the shared one, so ``6000000000`` (accepted by Math's
    32-bit length test) is a known gap of this rule.
    """

    def rule(ns: Any, value: str) -> tuple[str, str]:
        def take(c: Any) -> str | None:
            if c.kind in ("text", "char"):
                return None
            if mode == "decimal":
                if c.kind == "hex":
                    return OPEN
                if c.kind == "integer":
                    return ACCEPT if str(c.value) == value else None
                return ACCEPT
            if c.kind != "hex":
                return OPEN
            return ACCEPT if len(value) - 1 <= 4 and not c.wide else None

        return _by_kind(ns, value, take)

    return rule


def counter_rule(ns: Any, value: str) -> tuple[str, str]:
    """Counter preset (data.md Q-D2; arc.md Q-D2 dialog check).

    An int32 integer: digits with an optional leading ``-`` (no ``+``), under 13 characters.
    """

    def take(c: Any) -> str | None:
        ok = c.kind == "integer" and not value.startswith("+") and len(value) <= 12
        return ACCEPT if ok else None

    return _by_kind(ns, value, take)


def termination_rule(ns: Any, value: str) -> tuple[str, str]:
    """Copy termination code: ``0`` (none) or a character code ``$hh`` (arc.md D1)."""
    if value == "0":
        return ACCEPT, "none"
    return _by_kind(ns, value, lambda c: ACCEPT if c.kind == "char" else None)


def modbus_hex_rule(ns: Any, value: str) -> tuple[str, str]:
    """Remote hex start (comm.md Q-C7): hex in either case, 0h to FFFEh.

    The dialog upper-cases the text and wants ``H`` last; it counts no digits.  A MODBUS 984
    number is no constant and is skipped.
    """
    if ns.c.parse_digits(value) is not None:
        return ADDRESS, "984 number"
    return _by_kind(ns, value, lambda c: ACCEPT if c.kind == "hex" and c.value <= 0xFFFE else None)


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


def _fields() -> list[Field]:
    out: list[Field] = []
    for group, other in _COMPARE_OTHER.items():
        out.append(
            Field(
                "bits",
                f"CompareContact.right (left={other})",
                _make("CompareContact", op="==", left=other, right="DS1")("right"),
                compare_rule(group),
            )
        )
        out.append(
            Field(
                "bits",
                f"CompareContact.left (right={other})",
                _make("CompareContact", op="==", left="DS1", right=other)("left"),
                compare_rule(group),
            )
        )
    out_variants = {
        "debounce": dict(on_acc="TD3", on_preset="100", off_acc="TD4", off_preset="200"),
        "flasher": dict(on_acc="TD12", on_preset="500", off_acc="TD13", off_preset="250"),
        "timed": dict(on_acc="TD18", on_preset="1000"),
    }
    for kind, base in out_variants.items():
        # Q-B6: 0 to 32767 for debounce, 1 to 32767 for flasher and timed; digits only (N3).
        floor = 0 if kind == "debounce" else 1
        make = _make("OutVariant", kind=kind, operand="C1", unit="Tms", **base)
        for phase in ("on", "off") if kind != "timed" else ("on",):
            out.append(
                Field(
                    "bits",
                    f"OutVariant.{phase}_preset ({kind})",
                    make(f"{phase}_preset"),
                    _digits_rule(floor, 32767),
                )
            )
    copy_dests = {"DS": "DS9", "DD": "DD1", "DF": "DF1", "DH": "DH1", "TXT": "TXT2"}
    for bank, dest in copy_dests.items():
        out.append(
            Field(
                "move",
                f"Copy.source (destination={dest})",
                _make("Copy", source="1", destination=dest)("source"),
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
                termination_code="$13",
            )("termination_code"),
            termination_rule,
        )
    )
    for bank, (start, end) in {"DS": ("DS52", "DS55"), "TXT": ("TXT2", "TXT5")}.items():
        out.append(
            Field(
                "move",
                f"Fill.value ({start}..{end})",
                _make("Fill", value="0", dest_start=start, dest_end=end)("value"),
                fill_rule(bank),
            )
        )
    tables = {"DS": ("DS72", "DS81"), "DH": ("DH72", "DH81"), "TXT": ("TXT1", "TXT10")}
    for bank, (start, end) in tables.items():
        out.append(
            Field(
                "move",
                f"Search.source ({start}..{end} ==)",
                _make(
                    "Search",
                    table_start=start,
                    table_end=end,
                    source="DS71",
                    result="DS82",
                    found="C81",
                    comparison="==",
                )("source"),
                search_rule(bank),
            )
        )
    for mode, (left, result) in {"decimal": ("DS1", "DS2"), "hex": ("DH1", "DH3")}.items():

        def build(ns: Any, value: str, left: str = left, result: str = result, mode: str = mode):
            return ns.inst.Math(expression=f"{left} + {value}", result=result, mode=mode)

        out.append(Field("move", f"Math ({mode}): '{left} + <value>'", build, math_rule(mode)))
    out.append(
        Field(
            "data",
            "Timer.setpoint (on_delay)",
            _make("Timer", timer_type="on_delay", done_bit="T1", current="TD1", unit="Tms")(
                "setpoint"
            ),
            # Q-D1: digits only, 0 to 32767 for every unit.
            _digits_rule(0, 32767),
        )
    )
    out.append(
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
        )
    )

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

    # Q-D4: digits only, 0 to 32767 for every unit; an empty step is OBJ-022.
    out.append(Field("data", "Drum.presets[0] (time)", drum, _digits_rule(0, 32767)))
    out.append(
        Field(
            "flow",
            "ForLoop.limit",
            _make("ForLoop")("limit"),
            # Q-F1: digits only, 0 to 2147483647; outer spaces stripped, an inner one refused.
            _digits_rule(0, 2**31 - 1, strip=True),
        )
    )
    out.append(
        Field(
            "comm",
            "ModbusAddress.address (holding)",
            _make("ModbusAddress", register_type="holding")("address"),
            modbus_hex_rule,
        )
    )
    return out


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def _today(ns: Any, field: Field, value: str) -> tuple[str, str]:
    try:
        field.build(ns, value)
    except Exception as exc:  # any refusal counts
        return REFUSE, f"{type(exc).__name__}: {exc}"
    return ACCEPT, ""


def _skip(field: Field, value: str) -> bool:
    # A space or an empty text changes a Math formula's tokens, not one constant; an empty
    # Out variant preset is the phase rule (Q-B4), not a constant.
    if field.label.startswith("Math"):
        return not value.strip() or any(ch.isspace() for ch in value)
    return field.label.startswith("OutVariant") and value == ""


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # ty: ignore[unresolved-attribute]
    args = sys.argv[1:] if argv is None else argv
    ns = Namespace(args[0] if args else "src")
    fields = _fields()
    totals: dict[str, list[int]] = {}
    lines: list[str] = []
    print(f"classify() dry run: {len(fields)} fields x {len(VALUES)} values")
    print("format: field | value | today | classifier (what classify() read)")
    for field in fields:
        disagree = opened = addresses = skipped = 0
        lines.clear()
        for value in VALUES:
            if _skip(field, value):
                skipped += 1
                continue
            verdict, why = field.rule(ns, value)
            if verdict == ADDRESS:
                addresses += 1
                continue
            today, error = _today(ns, field, value)
            if verdict == OPEN:
                opened += 1
                lines.append(f"  open     {_show(value)} | today {today} | classifier: {why}")
                continue
            if verdict != today:
                disagree += 1
                shown = f"{today} ({error})" if error else today
                lines.append(
                    f"  DIFFERS  {_show(value)} | today {shown} | classifier {verdict} ({why})"
                )
        compared = len(VALUES) - skipped - addresses - opened
        print()
        print(
            f"[{field.family}] {field.label}: {compared} compared, {disagree} differ, "
            f"{opened} open, {addresses} addresses skipped, {skipped} skipped"
        )
        print("\n".join(lines) if lines else "  (no differences)")
        family = totals.setdefault(field.family, [0, 0, 0])
        family[0] += compared
        family[1] += disagree
        family[2] += opened
    print()
    print("Totals by family (compared / differ / open):")
    for family, (compared, disagree, opened) in totals.items():
        print(f"  {family}: {compared} / {disagree} / {opened}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
