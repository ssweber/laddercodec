"""Write the editor grids: the cases ClickNick's runner types into CLICK's instruction dialogs.

    make editor-grids                          # write tests/fixtures/editor_grids/, then check
    uv run devtools/editor_grids.py            # write only
    uv run devtools/editor_grids.py --check    # exit 1 if the committed files differ

A grid is a case list in the runner's own shape (``{"cases": [{"row", "case", "instruction",
"mode", "fields", "choices", "options"}, ...]}``), one file per dialog, built from
laddercodec's own bank lists, constant kinds and field rules so the lists keep in step with
the code. Each grid has a verdicts file beside it, ``<grid>.verdicts.json``: what
laddercodec's rules say about each case today, keyed by the case's label, for comparing with
CLICK's answers when they come. The runner reads only the grid. ClickNick wrote the grids in
``RUNNER_GRIDS`` itself, and the generator writes only their verdicts files.
"""

from __future__ import annotations

import argparse
import functools
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast, get_args

from laddercodec import FieldError, Reason
from laddercodec.instructions.coil import Coil
from laddercodec.instructions.comparison import CompareContact
from laddercodec.instructions.copy import BlockCopy, Copy, Fill, Pack, Unpack
from laddercodec.instructions.counter import Counter
from laddercodec.instructions.drum import _MAX_DRUM_SIZE, Drum
from laddercodec.instructions.forloop import ForLoop
from laddercodec.instructions.math import Math
from laddercodec.instructions.search import Search
from laddercodec.instructions.send_receive import (
    ModbusAddress,
    ModbusRtuPort,
    ModbusRtuTarget,
    ModbusTcpPort,
    ModbusTcpTarget,
    Receive,
    ReceiveFunctionCode,
    Send,
    SendFunctionCode,
)
from laddercodec.instructions.shift import Shift
from laddercodec.instructions.timer import Timer, TimerKind, TimeUnit
from laddercodec.model import (
    ADDRESS_BANKS,
    XY_SLOTS,
    Address,
    check_address,
    normalize_address,
)
from laddercodec.operands.checks import BIT_BANKS, REGISTER_BANKS
from laddercodec.operands.constants import (
    INT16_MAX,
    INT16_MIN,
    INT32_MAX,
    INT32_MIN,
    TEXT_MAX,
    Kind,
    classify,
)

OUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "editor_grids"
#: The seconds the runner takes for one case. main() uses it to estimate each file's hours.
SECONDS_PER_CASE = 4
#: The most cases a file should hold. main() flags a file with more as over the split limit.
SPLIT_AT = 2000

#: The banks in CLICK's order.
BANKS = tuple(ADDRESS_BANKS)
BIT_ORDER = tuple(b for b in BANKS if b in BIT_BANKS)
REGISTER_ORDER = tuple(b for b in BANKS if b in REGISTER_BANKS)
WORD_IO = ("XD", "YD")
XY = ("X", "Y")

# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------


def addr(bank: str, number: int, upper: bool = False) -> str:
    """Return the address in the form that CLICK shows."""
    return Address(bank, number, upper).display


def samples(bank: str) -> list[str]:
    """Return addresses of ``bank`` at the edges of its range, then addresses just outside.

    For X and Y, the edges are those of the slots."""
    lo, hi = ADDRESS_BANKS[bank]
    if bank in XY:
        slots = XY_SLOTS
        inside = [slots[0][0], slots[0][1], slots[1][0], slots[1][1], slots[2][0], slots[-1][1]]
        outside = [0, slots[0][1] + 1, slots[1][0] - 1, slots[1][1] + 1, slots[2][0] - 1]
        outside += [slots[2][1] + 1, hi + 1]
        return [addr(bank, n) for n in inside + outside]
    if bank in WORD_IO:
        return [addr(bank, 0), addr(bank, 0, True), addr(bank, 1), addr(bank, hi)] + [
            addr(bank, hi + 1),
            f"{bank}00",
            f"{bank}0U",
        ]
    return [addr(bank, lo), addr(bank, hi), addr(bank, lo - 1), addr(bank, hi + 1)]


def low(bank: str) -> str:
    """Return the lowest address of ``bank``."""
    return addr(bank, *((0,) if bank in WORD_IO else (ADDRESS_BANKS[bank][0],)))


def ranges(bank: str) -> list[tuple[str, str]]:
    """Return ``(start, end)`` ranges in ``bank``.

    The list holds a range of two addresses, the longest range, ranges at the edges, and
    the refused shapes, where the end is before the start or equal to it."""
    lo, hi = ADDRESS_BANKS[bank]
    if bank in XY:
        s = XY_SLOTS
        return [
            (addr(bank, s[0][0]), addr(bank, s[0][0] + 1)),
            (addr(bank, s[0][0]), addr(bank, s[0][1])),
            (addr(bank, s[0][0]), addr(bank, s[1][0])),
            (addr(bank, s[2][0]), addr(bank, s[2][1])),
            (addr(bank, s[2][0]), addr(bank, s[3][0])),
            (addr(bank, hi - 1), addr(bank, hi)),
            (addr(bank, hi), addr(bank, hi + 1)),
            (addr(bank, s[0][0] + 1), addr(bank, s[0][0])),
            (addr(bank, s[0][0]), addr(bank, s[0][0])),
        ]
    if bank in WORD_IO:
        return [
            (addr(bank, 0), addr(bank, 0, True)),
            (addr(bank, 0), addr(bank, 1)),
            (addr(bank, 0, True), addr(bank, 1)),
            (addr(bank, 1), addr(bank, hi)),
            (addr(bank, hi), addr(bank, hi + 1)),
            (addr(bank, 1), addr(bank, 0)),
            (addr(bank, 1), addr(bank, 1)),
        ]
    return [
        (addr(bank, lo), addr(bank, lo + 1)),
        (addr(bank, lo), addr(bank, hi)),
        (addr(bank, hi - 1), addr(bank, hi)),
        (addr(bank, hi), addr(bank, hi + 1)),
        (addr(bank, lo + 1), addr(bank, lo)),
        (addr(bank, lo), addr(bank, lo)),
    ]


def run_to(bank: str, count: int) -> str:
    """Return the last address of a run of ``count`` addresses from the first of ``bank``.

    The function only adds to the number, so the address may fall in a gap between slots
    or past the end of the bank."""
    start = 0 if bank in WORD_IO else ADDRESS_BANKS[bank][0]
    return addr(bank, start + count - 1)


#: Other ways to type an address.
TYPED_FORMS = ["ds1", "DS001", "DS01", "x1", "x001", "c001", " DS1", "DS1 ", "DS 1", "xd0U", "XD0u"]

#: Pointer addresses. POINTERS puts every bank before ``[DS1]``, and POINTER_INDEXES tries
#: different texts between the brackets.
POINTERS = [f"{bank}[DS1]" for bank in BANKS]
POINTER_INDEXES = [
    "DS[DS1]",
    "DS[DS4500]",
    "DS[DS4501]",
    "DS[DS0]",
    "DS[ds1]",
    "DS[DS001]",
    "DS[DS1+1]",
    "DS[DS1 + 1]",
    "DS[DS1-1]",
    "DS[1]",
    "DS[]",
    "DS[DS1",
    "DS[DS[DS1]]",
] + [f"DS[{bank}1]" for bank in BANKS if bank != "DS"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: A list of constants for every :class:`Kind`. Each list holds the spellings that the shared
#: constant reader treats differently.
CONSTANTS: dict[Kind, list[str]] = {
    Kind.INTEGER: [
        "0",
        "5",
        "-5",
        "+5",
        "005",
        "-005",
        "+0",
        "-0",
        str(INT16_MAX),
        str(INT16_MAX + 1),
        str(INT16_MIN),
        str(INT16_MIN - 1),
        str(INT32_MAX),
        str(INT32_MAX + 1),
        str(INT32_MIN),
        str(INT32_MIN - 1),
        "65535",
        "65536",
        "99999999999",
        "1-2",
        "--5",
        "+-5",
    ],
    Kind.FLOAT: [
        "1.5",
        "-1.5",
        "+1.5",
        "1.50",
        "01.5",
        ".5",
        "-.5",
        "1.",
        "1E5",
        "1e5",
        "1.5E+3",
        "1.5E3",
        "1.5e-3",
        "-1.5E-3",
        "1E",
        "E5",
        "1.5.2",
        "3.4028235E+38",
        "3.4028236E+38",
        "3.5E+38",
        "-3.5E+38",
        "1E39",
        "1E-45",
        "1E-50",
    ],
    Kind.HEX: [
        "0h",
        "0H",
        "5h",
        "FFh",
        "ffh",
        "0FFh",
        "0FFH",
        "000Fh",
        "FFFFh",
        "10000h",
        "7FFFh",
        "8000h",
        "FFFFFFFFh",
        "0FFFFFFFFh",
        "100000000h",
        "FFFFFFFFFh",
        "+FFh",
        "-FFh",
        "h",
        "1Eh",
        "DH",
        "EH",
        "ABCH",
    ],
    Kind.TEXT: [
        '"A"',
        '"AB"',
        '"HELLO"',
        '"a"',
        '"E"',
        '"e"',
        '"1E5"',
        '"5"',
        '"1.5"',
        '"$41"',
        '"A B"',
        '" "',
        '""',
        '"é"',
        '"\t"',
        '"' + "A" * TEXT_MAX + '"',
        '"' + "A" * (TEXT_MAX + 1) + '"',
        '"A',
        'A"',
    ],
    Kind.CHAR: [
        "$41",
        "$00",
        "$0D",
        "$FF",
        "$ff",
        "$1",
        "$100",
        "$G1",
        "$",
        "$ 41",
        "-$41",
    ],
}
assert set(CONSTANTS) == set(Kind), "a constant kind has no spellings"

#: Text that is neither a constant nor an address.
NOT_CONSTANTS = ["abc", "", " ", "1 2", "1,5", "٣", "DS", "DS1.5", "5DS", "#5", "@5"]

#: One constant for each kind and width, to pair with each bank.
REPRESENTATIVES = ["5", "-5", str(INT32_MAX), "1.5", "FFh", "10000h", '"A"', '"AB"', "$41"]
#: A few constants, for a field that does not need the full list.
FEW = ["5", "1.5", "FFh", '"A"', "$41"]
#: Other forms of an address, for a field that takes no pointer.
FORMS_SHORT = ["DS[DS1]", "X[DS1]", "ds1", "DS001", " DS1"]
#: Banks to pair every bank with, in a range that crosses banks.
PARTNERS = ("X", "C", "DS", "TXT")
#: Text with a quote inside it: a doubled quote, a lone quote, two quotes alone and one
#: quote alone.
QUOTED_TEXTS = ('"A""B"', '"A"B"', '""""', '"""')


def all_constants() -> list[str]:
    """Return every constant spelling, kind by kind, then the texts that are not constants."""
    return [text for kind in Kind for text in CONSTANTS[kind]] + NOT_CONSTANTS


#: A hex spelling that the Fill, Compare and Search grids add to CONSTANTS: lower case digits
#: after a leading zero.
LOWER_HEX = "0ffh"


def kinds_of_constants() -> list[tuple[Kind | None, str]]:
    """Return every constant spelling with its kind, then the texts that are not constants.

    The kind is the one that CONSTANTS lists the spelling under, and ``None`` for a text
    that is not a constant. ``0ffh`` is added to the hex spellings. The Fill, Compare and
    Search grids use this list. The Math, Copy and Out grids use ``all_constants()``. CLICK
    has answered those grids, so their list does not change."""
    pairs: list[tuple[Kind | None, str]] = []
    for kind in Kind:
        extra = [LOWER_HEX] if kind is Kind.HEX else []
        pairs += [(kind, text) for text in CONSTANTS[kind] + extra]
    return pairs + [(None, text) for text in NOT_CONSTANTS]


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


class Grid:
    """The cases of one file, and laddercodec's verdict on each."""

    def __init__(self, check: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.cases: list[dict[str, Any]] = []
        self.labels: dict[str, dict[str, Any]] = {}
        self.check = check

    def add(
        self,
        row: str,
        label: str,
        instruction: str,
        mode: str | None,
        *,
        options: dict[str, int] | None = None,
        **fields: str,
    ) -> None:
        """Add a case whose fields are the keyword arguments. See :meth:`add_case`."""
        self.add_case(row, label, instruction, mode, fields, options=options)

    def add_case(
        self,
        row: str,
        label: str,
        instruction: str,
        mode: str | None,
        fields: dict[str, str],
        *,
        choices: dict[str, str] | None = None,
        options: dict[str, int] | None = None,
    ) -> None:
        """Add a case. If the file already has a case with this label, keep only the first.

        ``choices`` maps a list to the item to pick in it. ``options`` maps a button's control
        id, as a decimal string, to 1 (on) or 0 (off). For a dialog that the runner does not
        drive yet, a list or a button is named by laddercodec's field name. A case without
        ``options`` leaves every option as the dialog opens."""
        case: dict[str, Any] = {"row": row, "case": label, "instruction": instruction}
        if mode is not None:
            case["mode"] = mode
        case["fields"] = fields
        if choices is not None:
            case["choices"] = choices
        if options is not None:
            case["options"] = options
        if label in self.labels:
            kept = self.labels[label]
            # The two cases must match in all but the row. The row may differ, because two
            # rows can try the same spelling.
            assert {k: v for k, v in kept.items() if k != "row"} == {
                k: v for k, v in case.items() if k != "row"
            }, f"two different cases share the label {label!r}"
            return
        self.labels[label] = case
        self.cases.append(case)

    def verdicts(self) -> dict[str, dict[str, Any]]:
        """Return laddercodec's verdict on each case, keyed by the case's label."""
        return {case["case"]: self.check(case) for case in self.cases}


def verdict_of(build: Callable[[], object]) -> dict[str, Any]:
    """Call ``build`` and return the verdict.

    The verdict is ``accepted``, or ``refused`` with the exception's class, field and message."""
    try:
        build()
    except Exception as exc:
        return {
            "verdict": "refused",
            "error": type(exc).__name__,
            "field": getattr(exc, "field", None),
            "message": str(exc),
        }
    return {"verdict": "accepted"}


def _block_end(source: str, source_end: str, destination: str) -> str:
    """Return the destination end that CLICK works out for a Block Copy.

    CLICK gives the destination range as many addresses as the source range. If an address
    does not parse, return ``destination``."""
    try:
        first = check_address(normalize_address(source), "s", set(BANKS))
        last = check_address(normalize_address(source_end), "e", set(BANKS))
        dest = check_address(normalize_address(destination), "d", set(BANKS))
        return addr(dest.bank, dest.number + last.number - first.number)
    except ValueError:
        return destination


def _bank_of(text: str) -> str:
    """Return the letters at the start of an address text in upper case, or ``""`` if none."""
    letters = ""
    for char in text.strip():
        if not char.isalpha():
            break
        letters += char
    return letters.upper()


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------


def _math_check(case: dict[str, Any]) -> dict[str, Any]:
    fields = case["fields"]
    return verdict_of(lambda: Math(fields["formula"], fields["result"], case["mode"]))


def math_grid() -> Grid:
    """Return the grid of the Math dialog, in decimal and hex mode."""
    grid = Grid(_math_check)

    def add(row: str, mode: str, result: str, formula: str) -> None:
        grid.add(
            f"math.{row}",
            f"{mode[:3]} {result} = {formula}",
            "math",
            mode,
            result=result,
            formula=formula,
        )

    dec_result, hex_result = "DS1", "DH1"
    dec_base, hex_base = "DS2 + 1", "DH2 + DH3"
    for mode, result, base in (("decimal", dec_result, dec_base), ("hex", hex_result, hex_base)):
        add("control", mode, result, base)
        # Try every bank in the result, then pointers and the other typed forms.
        for bank in BANKS:
            for text in samples(bank):
                add(f"result.{mode}.banks", mode, text, base)
        for text in POINTERS + POINTER_INDEXES + TYPED_FORMS:
            add(f"result.{mode}.forms", mode, text, base)
        for text in ["5", "1.5", "FFh", '"A"', "$41", ""]:
            add(f"result.{mode}.not-an-address", mode, text, base)
        # Try every bank as an operand, alone and with a constant of the mode.
        one = "1" if mode == "decimal" else "1h"
        for bank in BANKS:
            for text in samples(bank):
                add(f"operand.{mode}.banks", mode, result, f"{text} + {one}")
                add(f"operand.{mode}.banks-alone", mode, result, text)
        for text in POINTERS + POINTER_INDEXES + TYPED_FORMS:
            add(f"operand.{mode}.forms", mode, result, f"{text} + {one}")
        # Try a constant of every kind and spelling, with an operand and alone.
        own = "DS1" if mode == "decimal" else "DH1"
        for text in all_constants():
            add(f"constants.{mode}", mode, result, f"{own} + {text}")
            add(f"constants.{mode}.alone", mode, result, text)
        # Try every bank as a RAND bound, then bounds that are equal or reversed.
        bound = "10" if mode == "decimal" else "Ah"
        first = "1" if mode == "decimal" else "1h"
        for bank in BANKS:
            for text in samples(bank):
                add(f"rand.{mode}.low-bound", mode, result, f"RAND({text},{bound})")
                add(f"rand.{mode}.high-bound", mode, result, f"RAND({first},{text})")
        own_lo = "DS1" if mode == "decimal" else "DH1"
        own_hi = "DS2" if mode == "decimal" else "DH2"
        for lo_b, hi_b in (
            (first, bound),
            (bound, first),
            (first, first),
            (own_lo, own_hi),
            (own_hi, own_lo),
            (own_lo, own_lo),
            (own_lo, bound),
            (bound, own_lo),
        ):
            add(f"rand.{mode}.order", mode, result, f"RAND({lo_b},{hi_b})")
        for text in REPRESENTATIVES:
            add(f"rand.{mode}.constants", mode, result, f"RAND({text},{bound})")
            add(f"rand.{mode}.constants", mode, result, f"RAND({first},{text})")
        # Try SUM on the ranges of every bank.
        for bank in BANKS:
            for start, end in ranges(bank):
                add(f"sum.{mode}.ranges", mode, result, f"SUM({start}:{end})")
    # In decimal mode only, try SUM ranges that cross banks, and the other range functions.
    for first_bank in BANKS:
        for second_bank in PARTNERS:
            add(
                "sum.decimal.mixed",
                "decimal",
                dec_result,
                f"SUM({low(first_bank)}:{run_to(second_bank, 2)})",
            )
    for func in ("MAX", "MIN", "MDN", "AVG"):
        for bank in BANKS:
            for start, end in ranges(bank)[:2]:
                add(
                    f"{func.lower()}.decimal.ranges",
                    "decimal",
                    dec_result,
                    f"{func}({start}:{end})",
                )
    return grid


# ---------------------------------------------------------------------------
# Copy
# ---------------------------------------------------------------------------


#: The destination banks for which a Copy or Block Copy from TXT asks you to choose Copy
#: Character Value or Copy ASCII Code Value.
_TXT_CHOICE = frozenset({"DS", "DD", "DH", "YD", "TD", "CTD", "SD"})


def _txt_default(source: str, destination: str) -> tuple[bool | None, bool] | None:
    """Return the dialog's default converter for a number copied to TXT.

    The number is a constant or a register. The default converter is Copy Value as text,
    returned as ``(suppress_zero, exponential)``. It sets Suppress zero for an integer and
    Real Numbering for a real. Return ``None`` for any other copy."""
    if _bank_of(destination) != "TXT":
        return None
    constant = classify(source)
    if constant is not None:
        if constant.kind not in (Kind.INTEGER, Kind.HEX, Kind.FLOAT):
            return None
        real = constant.kind is Kind.FLOAT
    else:
        bank = _bank_of(source)
        if bank not in REGISTER_BANKS or bank == "TXT":
            return None
        real = bank == "DF"
    return (None, False) if real else (True, False)


def _copy_check(case: dict[str, Any]) -> dict[str, Any]:
    f, mode = case["fields"], case["mode"]
    if mode == "fill":
        return verdict_of(lambda: Fill(f["source"], f["destination"], f["destination_end"]))
    # A copy from TXT into a number register other than DF uses the dialog's default, Copy
    # Character Value.
    txt_choice = _bank_of(f["source"]) == "TXT" and _bank_of(f["destination"]) in _TXT_CHOICE
    convert = "to_value" if txt_choice else None
    if mode == "single":
        # A copy of a number into TXT uses the dialog's default, Copy Value as text.
        default = _txt_default(f["source"], f["destination"])
        if default is not None:
            zeros, exponential = default
            return verdict_of(
                lambda: Copy(
                    f["source"],
                    f["destination"],
                    convert="to_text",
                    suppress_zero=zeros,
                    exponential=exponential,
                )
            )
        return verdict_of(lambda: Copy(f["source"], f["destination"], convert=convert))
    if mode == "block":
        end = _block_end(f["source"], f["source_end"], f["destination"])
        return verdict_of(
            lambda: BlockCopy(f["source"], f["source_end"], f["destination"], end, convert=convert)
        )
    if mode == "pack":
        bank = _bank_of(f["source"])
        pack_kind = (
            "pack_text" if bank == "TXT" else "pack_bits" if bank in BIT_BANKS else "pack_words"
        )
        return verdict_of(lambda: Pack(f["source"], f["source_end"], f["destination"], pack_kind))
    if mode == "unpack":
        unpack_kind = (
            "unpack_to_bits" if _bank_of(f["destination"]) in BIT_BANKS else "unpack_to_words"
        )
        return verdict_of(
            lambda: Unpack(f["source"], f["destination"], f["destination_end"], unpack_kind)
        )
    raise AssertionError(mode)


def _natural_dest(source_bank: str) -> str:
    """Return a destination that accepts a source from ``source_bank``."""
    return "C1" if source_bank in BIT_BANKS else "DS1"


def _natural_source(dest_bank: str) -> str:
    """Return a source that can be copied to ``dest_bank``."""
    return "X001" if dest_bank in ("Y", "C") else "DS2"


def copy_grid() -> Grid:
    """Return the grid of the Copy dialog, in its single, block, pack and unpack modes."""
    grid = Grid(_copy_check)

    def single(row: str, source: str, destination: str) -> None:
        grid.add(
            f"copy.single.{row}",
            f"single {source} -> {destination}",
            "copy",
            "single",
            source=source,
            destination=destination,
        )

    def block(row: str, source: str, end: str, destination: str) -> None:
        grid.add(
            f"copy.block.{row}",
            f"block {source}..{end} -> {destination}",
            "copy",
            "block",
            source=source,
            source_end=end,
            destination=destination,
        )

    def pack(row: str, source: str, end: str, destination: str) -> None:
        grid.add(
            f"copy.pack.{row}",
            f"pack {source}..{end} -> {destination}",
            "copy",
            "pack",
            source=source,
            source_end=end,
            destination=destination,
        )

    def unpack(row: str, source: str, destination: str, end: str) -> None:
        grid.add(
            f"copy.unpack.{row}",
            f"unpack {source} -> {destination}..{end}",
            "copy",
            "unpack",
            source=source,
            destination=destination,
            destination_end=end,
        )

    # --- single -----------------------------------------------------------
    single("control", "DS1", "DS2")
    for bank in BANKS:
        for text in samples(bank):
            single("source.banks", text, _natural_dest(bank))
            single("destination.banks", _natural_source(bank), text)
    for text in POINTERS + POINTER_INDEXES + TYPED_FORMS:
        single("source.forms", text, "DS1")
        single("destination.forms", "DS2", text)
    for text in all_constants():
        single("source.constants", text, "DS1")
    # Each source bank against each destination bank, and each constant against each bank.
    for src in BANKS:
        for dst in BANKS:
            single("pairs.banks", low(src), low(dst))
    for text in REPRESENTATIVES:
        for dst in BANKS:
            single("pairs.constants", text, low(dst))
    for text in FEW:
        for pointer in POINTERS:
            single("pairs.constants-pointer", text, pointer)
    for src in ("C1", "DS1", "TXT1", "5", '"A"'):
        for pointer in POINTERS:
            single("pairs.pointer", src, pointer)
    for pointer in POINTERS:
        single("pairs.pointer-source", pointer, "DS1")
    # Copy text into TXT at the start and the end of the bank, to see where its characters end.
    for text in ('"AB"', '"ABC"', '"HELLO"', '"A"'):
        for target in ("TXT1", "TXT999", "TXT1000", "TXT1001", "TXT[DS1]"):
            single("text.fill", text, target)
    # Text with a quote inside it, into TXT1 and into a pointer. The end that CLICK saves
    # shows how many TXT registers the text fills.
    for text in (*QUOTED_TEXTS, '"A""', '"""A"', '"A"'):
        single("text.quotes", text, "TXT1")
    for text in QUOTED_TEXTS[:2]:
        single("text.quotes", text, "TXT[DS1]")

    # --- block ------------------------------------------------------------
    block("control", "DS1", "DS2", "DS11")
    for bank in BANKS:
        for start, end in ranges(bank):
            block("source.ranges", start, end, _natural_dest(bank))
        for text in samples(bank):
            block("source.banks", text, run_to(bank, 2) if text == low(bank) else text,
                  _natural_dest(bank))  # fmt: skip
            pair = ("C1", "C2") if bank in ("Y", "C") else ("DS1", "DS2")
            block("destination.banks", pair[0], pair[1], text)
    for src in BANKS:
        for dst in BANKS:
            block("pairs.banks", low(src), run_to(src, 2), low(dst))
        for other in PARTNERS:
            block("source.mixed-banks", low(src), low(other), "DS11")
    for dst in BANKS:
        for bank in XY:
            for end in (addr(bank, 16), addr(bank, 36)):
                block("pairs.xy-spans", low(bank), end, low(dst))
    for text in FORMS_SHORT:
        block("source.forms", text, "DS2", "DS11")
        block("source-end.forms", "DS1", text, "DS11")
        block("destination.forms", "DS1", "DS2", text)
    for text in REPRESENTATIVES:
        block("source.constants", text, "DS2", "DS11")
        block("source-end.constants", "DS1", text, "DS11")
        block("destination.constants", "DS1", "DS2", text)

    # --- pack -------------------------------------------------------------
    pack("control", "C1", "C16", "DS1")
    for bit in BIT_ORDER:
        for word in REGISTER_ORDER:
            for count in (16, 32):
                pack("bits.widths", low(bit), run_to(bit, count), low(word))
            if word in ("DS", "DD"):
                for count in (1, 2, 17, 33):
                    pack("bits.widths", low(bit), run_to(bit, count), low(word))
            if bit in XY:
                # Two full slots (X001..X036 is 32 points), and a span inside one slot.
                pack("bits.xy-spans", low(bit), addr(bit, 36), low(word))
                pack("bits.xy-spans", low(bit), addr(bit, 16), low(word))
    for word in REGISTER_ORDER:
        for dst in REGISTER_ORDER:
            pack("words.widths", low(word), run_to(word, 2), low(dst))
            if word in ("DS", "DD"):
                for count in (1, 3):
                    pack("words.widths", low(word), run_to(word, count), low(dst))
    for bank in BANKS:
        for start, end in ranges(bank):
            pack("source.ranges", start, end, "DH1")
        for text in samples(bank):
            pack("destination.banks", "C1", "C16", text)
            pack("source.banks", text, run_to(bank, 16) if text == low(bank) else text, "DH1")
    for text in FORMS_SHORT:
        pack("source.forms", text, "C16", "DS1")
        pack("source-end.forms", "C1", text, "DS1")
        pack("destination.forms", "C1", "C16", text)
    for text in REPRESENTATIVES:
        pack("source.constants", text, "C16", "DS1")
        pack("source-end.constants", "C1", text, "DS1")
        pack("destination.constants", "C1", "C16", text)

    # --- unpack -----------------------------------------------------------
    unpack("control", "DS1", "C1", "C16")
    for word in REGISTER_ORDER:
        for bit in BIT_ORDER:
            for count in (16, 32):
                unpack("bits.widths", low(word), low(bit), run_to(bit, count))
            if word in ("DS", "DD"):
                for count in (1, 2, 17, 33):
                    unpack("bits.widths", low(word), low(bit), run_to(bit, count))
            if bit in XY:
                unpack("bits.xy-spans", low(word), low(bit), addr(bit, 36))
                unpack("bits.xy-spans", low(word), low(bit), addr(bit, 16))
        for dst in REGISTER_ORDER:
            unpack("words.widths", low(word), low(dst), run_to(dst, 2))
            if dst in ("DS", "DD"):
                for count in (1, 3):
                    unpack("words.widths", low(word), low(dst), run_to(dst, count))
    for bank in BANKS:
        for start, end in ranges(bank):
            unpack("destination.ranges", "DS1", start, end)
        for text in samples(bank):
            unpack("source.banks", text, "C1", "C16")
            unpack(
                "destination.banks", "DS1", text, run_to(bank, 16) if text == low(bank) else text
            )
    for text in FORMS_SHORT:
        unpack("source.forms", text, "C1", "C16")
        unpack("destination.forms", "DS1", text, "C16")
        unpack("destination-end.forms", "DS1", "C1", text)
    for text in REPRESENTATIVES:
        unpack("source.constants", text, "C1", "C16")
        unpack("destination.constants", "DS1", text, "C16")
        unpack("destination-end.constants", "DS1", "C1", text)

    # --- block into SD: ranges that mix writable and read-only SD (appended to an existing row) ---
    for end, destination in (
        ("DS8", "SD140"),  # SD140..SD147, all writable
        ("DS3", "SD40"),  # SD40..SD42, all writable
        ("DS10", "SD29"),  # starts writable, reaches read-only SD below SD215
        ("DS10", "SD140"),  # SD148 and SD149 are read-only
        ("DS10", "SD214"),  # SD216 on is read-only, past the last writable SD
        ("DS120", "SD106"),  # read-only SD on both sides of SD215
        ("DS10", "SD205"),  # starts read-only, ends writable (SD214)
        ("DS3", "SD212"),  # starts read-only, ends writable (SD214)
        ("DS4", "SD212"),  # starts read-only, ends at SD215
    ):
        block("destination.banks", "DS1", end, destination)
    return grid


# ---------------------------------------------------------------------------
# Out
# ---------------------------------------------------------------------------


def _out_check(case: dict[str, Any]) -> dict[str, Any]:
    f = case["fields"]
    return verdict_of(lambda: Coil(f["address"], range_end=f.get("address_end")))


def _set_check(case: dict[str, Any]) -> dict[str, Any]:
    f = case["fields"]
    return verdict_of(lambda: Coil(f["address"], kind="latch", range_end=f.get("address_end")))


def _reset_check(case: dict[str, Any]) -> dict[str, Any]:
    f = case["fields"]
    return verdict_of(lambda: Coil(f["address"], kind="reset", range_end=f.get("address_end")))


def out_grid() -> Grid:
    """Return the grid of the Out dialog, with Out/Toggle and without One Shot or Immediate."""
    grid = Grid(_out_check)

    def out(row: str, address: str, end: str | None = None) -> None:
        if end is None:
            grid.add(f"out.{row}", f"out {address}", "out", None, address=address)
        else:
            grid.add(f"out.{row}", f"out {address}..{end}", "out", None,
                     address=address, address_end=end)  # fmt: skip

    out("control", "Y001")
    for bank in BANKS:
        for text in samples(bank):
            out("banks", text)
    for text in POINTERS + POINTER_INDEXES + TYPED_FORMS:
        out("forms", text)
    for text in all_constants():
        out("constants", text)
    for bank in BANKS:
        for start, end in ranges(bank):
            out("ranges", start, end)
        for text in samples(bank):
            out("range-end.banks", low(bank), text)
    for first in BANKS:
        for second in PARTNERS:
            out("ranges.mixed", low(first), low(second))
    for text in FORMS_SHORT:
        out("range-end.forms", "Y001", text)
        out("range-start.forms", text, "Y002")
    for text in REPRESENTATIVES:
        out("range-end.constants", "Y001", text)
    return grid


# ---------------------------------------------------------------------------
# Fill
# ---------------------------------------------------------------------------


def _fill_value(dest_bank: str) -> str:
    """Return a value to fill ``dest_bank`` with.

    The value is one character of text for TXT, 1 for a bit bank and 5 for any other bank."""
    if dest_bank == "TXT":
        return '"A"'
    return "1" if dest_bank in BIT_BANKS else "5"


def _fill_range(source_bank: str) -> tuple[str, str]:
    """Return a destination range for a Fill from ``source_bank``.

    The range is TXT10..TXT11 for TXT, C10..C11 for a bit bank and DS10..DS11 for any other
    bank."""
    bank = "TXT" if source_bank == "TXT" else "C" if source_bank in BIT_BANKS else "DS"
    return f"{bank}10", f"{bank}11"


#: SD ranges for a Fill. The comment on each range says which of its SD addresses are
#: writable.
FILL_SD = [
    ("SD140", "SD147"),  # all writable
    ("SD40", "SD42"),  # all writable
    ("SD29", "SD38"),  # starts writable, reaches read-only SD
    ("SD140", "SD149"),  # SD148 and SD149 are read-only
    ("SD214", "SD223"),  # SD216 on is read-only
    ("SD106", "SD225"),  # read-only SD on both sides of SD215
    ("SD205", "SD214"),  # starts read-only, ends writable
    ("SD212", "SD215"),  # starts read-only, ends at SD215
    ("SD1", "SD2"),  # read-only
]


def fill_grid() -> Grid:
    """Return the grid of the Copy dialog in its Fill mode.

    The fields have the names that the runner gives the Copy dialog's fields: the value is
    the ``source``, and the range is ``destination`` to ``destination_end``."""
    grid = Grid(_copy_check)

    def fill(row: str, value: str, start: str, end: str) -> None:
        grid.add(
            f"copy.fill.{row}",
            f"fill {value} -> {start}..{end}",
            "copy",
            "fill",
            source=value,
            destination=start,
            destination_end=end,
        )

    fill("control", "DS1", "DS10", "DS11")
    # The rows of the open questions come first. When a later row tries the same case, the
    # case stays in the row of its question.
    # Hex above FFFFh into each register bank, with FFFFh to compare. The pairs rows try a
    # constant into a bit bank.
    for text in ("FFFFh", "10000h", "FFFFFFFFh", "0FFFFFFFFh", "100000000h"):
        for bank in REGISTER_ORDER:
            fill("hex-wide", text, low(bank), run_to(bank, 2))
    # A number into TXT. No case touches an option. The text of some numbers takes more
    # than one TXT.
    for text in ("5", "-5", "123", "1.5", "FFh", "10h", "1234567.8"):
        for start, end in (("TXT1", "TXT2"), ("TXT999", "TXT1000")):
            fill("text.numbers", text, start, end)
    # Text into TXT: one character, several, none, and a character code.
    for text in ('"A"', '"AB"', '"ABC"', '"HELLO"', '""', '" "', '"~"', '"$41"', "$41", "$00"):
        for start, end in (("TXT1", "TXT2"), ("TXT999", "TXT1000")):
            fill("text.constants", text, start, end)
    # A character outside space to ~.
    for text in ('"é"', '"€"', '"\t"'):
        fill("text.characters", text, "TXT1", "TXT2")
    # A register into TXT.
    for value, start, end in (
        ("TXT1", "TXT2", "TXT3"),
        ("DS1", "TXT1", "TXT2"),
        ("DD1", "TXT1", "TXT2"),
        ("DH1", "TXT1", "TXT2"),
        ("DF1", "TXT1", "TXT2"),
    ):
        fill("text.registers", value, start, end)
    # Reals with 7 significant digits and with more.
    for text in ("123456.7", "1.234567", "1234567.8", "1.2345678", "0.33333334", "3.4028235E+38"):
        fill("real-digits", text, "DF1", "DF2")
    # Into SD.
    for start, end in FILL_SD:
        for value in ("5", "DS1"):
            fill("sd", value, start, end)

    # Each bank, pointer form and constant spelling as the value.
    for bank in BANKS:
        for text in samples(bank):
            fill("value.banks", text, *_fill_range(bank))
    for text in POINTERS + POINTER_INDEXES + TYPED_FORMS:
        fill("value.forms", text, "DS10", "DS11")
    for _, text in kinds_of_constants():
        fill("value.constants", text, "DS10", "DS11")
    # Each bank as the destination range, with its ends.
    for bank in BANKS:
        for start, end in ranges(bank):
            fill("destination.ranges", _fill_value(bank), start, end)
        for text in samples(bank):
            fill("destination-end.banks", _fill_value(bank), low(bank), text)
    for first in BANKS:
        for second in PARTNERS:
            fill("destination.mixed-banks", "5", low(first), low(second))
    for text in FORMS_SHORT:
        fill("destination-start.forms", "5", text, "DS11")
        fill("destination-end.forms", "5", "DS10", text)
    for text in REPRESENTATIVES:
        fill("destination-start.constants", "5", text, "DS11")
        fill("destination-end.constants", "5", "DS10", text)
    # Each value bank against each destination bank, and each constant against each bank.
    for src in BANKS:
        for dst in BANKS:
            fill("pairs.banks", low(src), low(dst), run_to(dst, 2))
    for text in REPRESENTATIVES:
        for dst in BANKS:
            fill("pairs.constants", text, low(dst), run_to(dst, 2))
    # Text with a quote inside it.
    for text in QUOTED_TEXTS:
        fill("text.quotes", text, "TXT1", "TXT10")
    return grid


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

#: The operators of the Compare and Search dialogs, in the dialogs' order.
OPERATORS = ("==", "!=", ">", "<", ">=", "<=")

#: The register bank to pair with a constant of each kind. Each bank is in the compare group
#: of its kind. An integer, and a text that is no constant, go with DS.
_KIND_BANK = {Kind.HEX: "DH", Kind.FLOAT: "DF", Kind.TEXT: "TXT", Kind.CHAR: "TXT"}


def _kind_bank(kind: Kind | None) -> str:
    """Return the register bank to pair with a constant of ``kind``."""
    return _KIND_BANK.get(kind, "DS") if kind is not None else "DS"


def _group_bank(bank: str) -> str:
    """Return a register bank in the compare group of ``bank``.

    The bank is DH for XD, YD and DH, TXT for TXT and DS for any other bank."""
    if bank in ("XD", "YD", "DH"):
        return "DH"
    return "TXT" if bank == "TXT" else "DS"


def _compare_check(case: dict[str, Any]) -> dict[str, Any]:
    f = case["fields"]
    return verdict_of(lambda: CompareContact(op=case["mode"], left=f["a"], right=f["b"]))


def compare_grid() -> Grid:
    """Return the grid of the Compare dialog."""
    grid = Grid(_compare_check)

    def compare(row: str, a: str, op: str, b: str) -> None:
        grid.add(f"compare.{row}", f"compare {a} {op} {b}", "compare", op, a=a, b=b)

    for a, b in (("DS1", "DS2"), ("TXT1", "TXT2"), ("DH1", "DH2")):
        compare("control", a, "==", b)
    # The rows that try every operator come first. When a later row tries the same case
    # under ==, the case stays in the row that tries every operator.
    for a, b in (("DS1", "DS2"), ("DS1", "5"), ("DF1", "1.5"), ("DH1", "DH2"), ("DH1", "Fh")):
        for op in OPERATORS:
            compare("operators", a, op, b)
    # Two texts under each operator.
    for a, b in (
        ("TXT1", "TXT2"),
        ("TXT1", '"T"'),
        ('"T"', "TXT1"),
        ("TXT1", "$41"),
        ("TXT1", '"AB"'),
    ):
        for op in OPERATORS:
            compare("text.operators", a, op, b)
    # Operands of two groups under each operator: hex against a number, and a number
    # against text.
    for a, b in (
        ("DH1", "DS1"),
        ("DS1", "DH1"),
        ("XD1", "DS1"),
        ("DH1", "5"),
        ("DS1", "5h"),
        ("DF1", "FFh"),
        ("DS1", "TXT1"),
        ("TXT1", "DS1"),
        ("DS1", '"A"'),
        ("TXT1", "5"),
    ):
        for op in OPERATORS:
            compare("mixed.operators", a, op, b)
    # Each bank and pointer form as A and as B.
    for bank in BANKS:
        for text in samples(bank):
            compare("a.banks", text, "==", f"{_group_bank(bank)}2")
            compare("b.banks", f"{_group_bank(bank)}1", "==", text)
    for text in POINTERS + POINTER_INDEXES + TYPED_FORMS:
        compare("a.forms", text, "==", "DS2")
        compare("b.forms", "DS1", "==", text)
    # Every constant spelling as B, and one constant of each kind and width as A, against a
    # register of its own group.
    for kind, text in kinds_of_constants():
        compare("b.constants", f"{_kind_bank(kind)}1", "==", text)
    for text in REPRESENTATIVES:
        constant = classify(text)
        bank = _kind_bank(constant.kind if constant is not None else None)
        compare("a.constants", text, "==", f"{bank}2")
    # Each register bank against each register bank, and against a constant of each kind.
    # The bank rows above try each bit bank.
    for a_bank in REGISTER_ORDER:
        for b_bank in REGISTER_ORDER:
            compare("pairs.banks", low(a_bank), "==", low(b_bank))
    for bank in REGISTER_ORDER:
        for text in REPRESENTATIVES:
            compare("pairs.constants", low(bank), "==", text)
    # Text with a quote inside it, as B and then as A.
    for text in QUOTED_TEXTS:
        compare("text.quotes", "TXT1", "==", text)
    for text in QUOTED_TEXTS:
        compare("text.quotes", text, "==", "TXT1")
    return grid


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

#: The control ids of the Search dialog's options. Both are off when the dialog opens.
CONTINUOUS = "5021"
ONE_SHOT = "5022"


def _search_check(case: dict[str, Any]) -> dict[str, Any]:
    f, options = case["fields"], case.get("options", {})
    return verdict_of(
        lambda: Search(
            table_start=f["start"],
            table_end=f["end"],
            value=f["value"],
            result=f["result"],
            found=f["found"],
            op=case["mode"],
            continuous=options.get(CONTINUOUS) == 1,
            oneshot=options.get(ONE_SHOT) == 1,
        )
    )


def _search_value(table_bank: str) -> str:
    """Return a value to search a table in ``table_bank`` for.

    The value is text for TXT, a hex constant for XD, YD and DH, and 5 for any other bank."""
    if table_bank == "TXT":
        return '"A"'
    return "Fh" if table_bank in ("XD", "YD", "DH") else "5"


def _search_table(bank: str) -> tuple[str, str]:
    """Return a table of ten registers in the compare group of ``bank``."""
    group = _group_bank(bank)
    return f"{group}1", f"{group}10"


def search_grid() -> Grid:
    """Return the grid of the Search dialog."""
    grid = Grid(_search_check)

    def search(
        row: str,
        start: str,
        end: str,
        op: str,
        value: str,
        result: str = "DS30",
        found: str = "C1",
        options: dict[str, int] | None = None,
    ) -> None:
        label = f"search {start}..{end} {op} {value} -> {result},{found}"
        if options:
            label += " [" + ",".join(f"{k}={v}" for k, v in options.items()) + "]"
        grid.add(
            f"search.{row}",
            label,
            "search",
            op,
            options=options,
            value=value,
            start=start,
            end=end,
            result=result,
            found=found,
        )

    search("control", "DS1", "DS10", "==", "DS20")
    search("control", "TXT1", "TXT10", "==", '"A"')
    # Each option alone, both, and both set off, on a number search and a text search.
    for start, end, value in (("DS1", "DS10", "DS20"), ("TXT1", "TXT10", '"A"')):
        for options in (
            {CONTINUOUS: 1},
            {ONE_SHOT: 1},
            {CONTINUOUS: 1, ONE_SHOT: 1},
            {CONTINUOUS: 0, ONE_SHOT: 0},
        ):
            search("options", start, end, "==", value, options=options)
    # The rows that try every operator come before the rows that try only ==.
    for start, end, value in (
        ("DS1", "DS10", "5"),
        ("DS1", "DS10", "DS20"),
        ("DF1", "DF10", "1.5"),
        ("DH1", "DH10", "Fh"),
    ):
        for op in OPERATORS:
            search("operators", start, end, op, value)
    # A text search under each operator, and a DS table searched for a TXT register.
    for start, end, value in (
        ("TXT1", "TXT10", '"A"'),
        ("TXT1", "TXT10", "TXT20"),
        ("TXT1", "TXT10", "65"),
        ("TXT1", "TXT10", "$41"),
        ("TXT1", "TXT10", '"AB"'),
        ("TXT1", "TXT10", '"A""B"'),
        ("DS1", "DS10", "TXT20"),
    ):
        for op in OPERATORS:
            search("text.operators", start, end, op, value)
    # Each bank as the table. For a register bank, each end of the bank as the start and as
    # the end of the table too.
    for bank in BANKS:
        for start, end in ranges(bank):
            search("table.ranges", start, end, "==", _search_value(bank))
    for bank in REGISTER_ORDER:
        last = addr(bank, ADDRESS_BANKS[bank][1])
        for text in samples(bank):
            search("table-start.banks", text, last, "==", _search_value(bank))
            search("table-end.banks", low(bank), text, "==", _search_value(bank))
    for first in BANKS:
        for second in PARTNERS:
            search("table.mixed-banks", low(first), low(second), "==", "5")
    for text in FORMS_SHORT:
        search("table-start.forms", text, "DS10", "==", "5")
        search("table-end.forms", "DS1", text, "==", "5")
    # Each bank, pointer form and constant spelling as the value.
    for bank in BANKS:
        for text in samples(bank):
            search("value.banks", *_search_table(bank), "==", text)
    for text in POINTERS + POINTER_INDEXES + TYPED_FORMS:
        search("value.forms", "DS1", "DS10", "==", text)
    for kind, text in kinds_of_constants():
        bank = _kind_bank(kind)
        search("value.constants", f"{bank}1", f"{bank}10", "==", text)
    # The table rows above try each bit bank as the table.
    for text in REPRESENTATIVES:
        for bank in REGISTER_ORDER:
            search("value.pairs", low(bank), run_to(bank, 10), "==", text)
    # Each bank as the result and as the found flag.
    for bank in BANKS:
        for text in samples(bank):
            search("result.banks", "DS1", "DS10", "==", "DS20", result=text)
            search("found.banks", "DS1", "DS10", "==", "DS20", found=text)
    for text in FORMS_SHORT:
        search("result.forms", "DS1", "DS10", "==", "DS20", result=text)
        search("found.forms", "DS1", "DS10", "==", "DS20", found=text)
    # Text with a quote inside it. The text.operators row already tries "A""B".
    for text in QUOTED_TEXTS[1:]:
        search("text.quotes", "TXT1", "TXT10", "==", text)
    return grid


# ---------------------------------------------------------------------------
# Timer, Counter, Shift, For and Drum
# ---------------------------------------------------------------------------
#
# The runner does not drive these five dialogs yet. Until it does, a case names the dialog,
# its mode, its fields, its lists (``choices``) and its buttons (``options``) by laddercodec's
# names: the kind as the mode, and the field names of the instruction's class. The item that
# a case picks in a list is the text that the list shows, such as ``sec``.


def address_forms(bank: str) -> list[str]:
    """Return a pointer into ``bank``, then other ways to type the lowest address of ``bank``.

    After the pointer come the address in lower case and the address with its number padded
    to three digits (for X and Y, with no leading zeros). Last come the address with a space
    before it, with a space after it, and with a space between the bank and the number."""
    shown = low(bank)
    digits = shown[len(bank) :]
    other = str(int(digits)) if bank in XY else digits.zfill(3)
    return [
        f"{bank}[DS1]",
        shown.lower(),
        f"{bank}{other}",
        f" {shown}",
        f"{shown} ",
        f"{bank} {digits}",
    ]


def _current_value(done: str, bank: str, register: str) -> str:
    """Return the register that holds the current value of the timer or counter ``done``.

    CLICK assigns it from the number of ``done``: T1 has TD1, and CT1 has CTD1. If ``done``
    is not an address in ``bank``, return the first register, so that only ``done`` is
    refused."""
    try:
        number = check_address(normalize_address(done), "done", {bank}).number
    except ValueError:
        return f"{register}1"
    return addr(register, number)


def _option(case: dict[str, Any], name: str) -> bool:
    return case.get("options", {}).get(name) == 1


#: Each item of the dialog's unit list, from milliseconds to days, and the unit that it picks.
UNITS: dict[str, TimeUnit] = {"ms": "Tms", "sec": "Ts", "min": "Tm", "hour": "Th", "day": "Td"}
assert set(UNITS.values()) == set(get_args(TimeUnit))
TIMER_KINDS: tuple[str, ...] = get_args(TimerKind)
#: The most steps, and the most outputs, that a drum has.
DRUM_SIZE = _MAX_DRUM_SIZE


def _timer_check(case: dict[str, Any]) -> dict[str, Any]:
    f = case["fields"]
    accumulator = f["accumulator"] if "accumulator" in f else _current_value(f["done"], "T", "TD")
    return verdict_of(
        lambda: Timer(
            kind=case["mode"],
            done=f["done"],
            accumulator=accumulator,
            preset=f["preset"],
            unit=UNITS[case["choices"]["unit"]],
            retained=_option(case, "retained"),
        )
    )


def timer_grid() -> Grid:
    """Return the grid of the Timer dialog, in its on-delay and off-delay modes."""
    grid = Grid(_timer_check)

    def timer(
        row: str,
        kind: str,
        preset: str,
        unit: str = "ms",
        done: str = "T1",
        accumulator: str | None = None,
        retained: int | None = None,
    ) -> None:
        fields = (
            {"done": done} if accumulator is None else {"done": done, "accumulator": accumulator}
        )
        fields["preset"] = preset
        label = f"{kind} {done}" + ("" if accumulator is None else f",{accumulator}")
        label += f" preset={preset} unit={unit}"
        options = None if retained is None else {"retained": retained}
        if retained is not None:
            label += f" retained={retained}"
        grid.add_case(
            f"timer.{row}", label, "timer", kind, fields, choices={"unit": unit}, options=options
        )

    for kind in TIMER_KINDS:
        timer("control", kind, "100")
    # Each kind with each unit.
    for kind in TIMER_KINDS:
        for unit in UNITS:
            timer("units", kind, "100", unit)
    # Retentive on in each unit. An off-delay timer has no retentive option.
    for unit in UNITS:
        timer("retained", "on_delay", "100", unit, retained=1)
    timer("retained", "off_delay", "100", retained=1)
    # The edges of a constant preset, in each kind and unit.
    for kind in TIMER_KINDS:
        for unit in UNITS:
            for text in ("0", str(INT16_MAX), str(INT16_MAX + 1), "-1"):
                timer("preset.edges", kind, text, unit)
    # Each constant spelling, bank and pointer form as the preset.
    for _, text in kinds_of_constants():
        timer("preset.constants", "on_delay", text)
    for bank in BANKS:
        for text in samples(bank):
            timer("preset.banks", "on_delay", text)
    for text in POINTERS + POINTER_INDEXES + TYPED_FORMS:
        timer("preset.forms", "on_delay", text)
    # Each bank as the timer number, then other ways to type it.
    for bank in BANKS:
        for text in samples(bank):
            timer("done.banks", "on_delay", "100", done=text)
    for text in address_forms("T"):
        timer("done.forms", "on_delay", "100", done=text)
    # CLICK assigns the current value from the timer number. This case types it, to see
    # whether the dialog takes it.
    timer("accumulator", "on_delay", "100", accumulator="TD1")
    return grid


#: The modes of the Counter dialog: laddercodec's two kinds, and an up counter with a down
#: input.
COUNTER_MODES = ("count_up", "count_down", "count_up_down")


def _counter_check(case: dict[str, Any]) -> dict[str, Any]:
    f, mode = case["fields"], case["mode"]
    accumulator = f["accumulator"] if "accumulator" in f else _current_value(f["done"], "CT", "CTD")
    return verdict_of(
        lambda: Counter(
            kind="count_down" if mode == "count_down" else "count_up",
            done=f["done"],
            accumulator=accumulator,
            preset=f["preset"],
            down_enabled=mode == "count_up_down",
        )
    )


#: Counter presets of 12 and of 13 characters. CLICK refuses a constant of 13 characters or
#: more.
COUNTER_LENGTHS = ["000000000005", "0000000000005", "-00000000005", "-000000000005"]


def counter_grid() -> Grid:
    """Return the grid of the Counter dialog, in its up, down and up-down modes."""
    grid = Grid(_counter_check)

    def counter(
        row: str, mode: str, preset: str, done: str = "CT1", accumulator: str | None = None
    ) -> None:
        fields = (
            {"done": done} if accumulator is None else {"done": done, "accumulator": accumulator}
        )
        fields["preset"] = preset
        label = f"{mode} {done}" + ("" if accumulator is None else f",{accumulator}")
        grid.add_case(f"counter.{row}", f"{label} preset={preset}", "counter", mode, fields)

    for mode in COUNTER_MODES:
        counter("control", mode, "10")
    # The edges of a constant preset, in each mode.
    for mode in COUNTER_MODES:
        for text in ("0", "-1", str(INT32_MAX), str(INT32_MAX + 1), str(INT32_MIN)):
            counter("preset.edges", mode, text)
        counter("preset.edges", mode, str(INT32_MIN - 1))
    # Each constant spelling, bank and pointer form as the preset.
    for _, text in kinds_of_constants():
        counter("preset.constants", "count_up", text)
    for text in COUNTER_LENGTHS:
        counter("preset.lengths", "count_up", text)
    for bank in BANKS:
        for text in samples(bank):
            counter("preset.banks", "count_up", text)
    for text in POINTERS + POINTER_INDEXES + TYPED_FORMS:
        counter("preset.forms", "count_up", text)
    # Each bank as the counter number, then other ways to type it.
    for bank in BANKS:
        for text in samples(bank):
            counter("done.banks", "count_up", "10", done=text)
    for text in address_forms("CT"):
        counter("done.forms", "count_up", "10", done=text)
    # CLICK assigns the current value from the counter number. This case types it, to see
    # whether the dialog takes it.
    counter("accumulator", "count_up", "10", accumulator="CTD1")
    return grid


def _shift_check(case: dict[str, Any]) -> dict[str, Any]:
    f = case["fields"]
    return verdict_of(lambda: Shift(f["start_bit"], f["end_bit"]))


def shift_grid() -> Grid:
    """Return the grid of the Shift Register dialog."""
    grid = Grid(_shift_check)

    def shift(row: str, start: str, end: str) -> None:
        grid.add(f"shift.{row}", f"shift {start}..{end}", "shift", None,
                 start_bit=start, end_bit=end)  # fmt: skip

    shift("control", "C1", "C8")
    # Eight bits of X or Y.
    for bank in XY:
        shift("xy", addr(bank, 1), addr(bank, 8))
    # The ranges of C, X and Y: two bits, the whole bank, its end, past its end, reversed and
    # one bit. Each other bank tries only its first range, because the rows shift.start.banks
    # and shift.end.banks already try each bank.
    for bank in BANKS:
        for start, end in ranges(bank) if bank in {"C", *XY} else ranges(bank)[:1]:
            shift("ranges", start, end)
    # Each bank as the start and as the end, against a C bit.
    for bank in BANKS:
        for text in samples(bank):
            shift("start.banks", text, "C8")
            shift("end.banks", "C1", text)
    for text in address_forms("C"):
        shift("start.forms", text, "C8")
        shift("end.forms", "C1", text)
    for text in FEW:
        shift("start.constants", text, "C8")
        shift("end.constants", "C1", text)
    return grid


def _for_check(case: dict[str, Any]) -> dict[str, Any]:
    return verdict_of(lambda: ForLoop(case["fields"]["count"], oneshot=_option(case, "oneshot")))


def for_grid() -> Grid:
    """Return the grid of the For dialog."""
    grid = Grid(_for_check)

    def for_(row: str, count: str, oneshot: int | None = None) -> None:
        label = f"for {count}" + ("" if oneshot is None else f" oneshot={oneshot}")
        options = None if oneshot is None else {"oneshot": oneshot}
        grid.add(f"for.{row}", label, "for", None, options=options, count=count)

    for_("control", "10")
    # One Shot on and off, with a constant and a register count.
    for count in ("10", "DS1"):
        for oneshot in (1, 0):
            for_("oneshot", count, oneshot)
    # Each constant spelling, bank and pointer form as the count. CLICK's dialog accepts 1 0.
    # It is not a number, so laddercodec refuses it.
    for _, text in kinds_of_constants():
        for_("count.constants", text)
    for_("count.constants", "1 0")
    for bank in BANKS:
        for text in samples(bank):
            for_("count.banks", text)
    for text in POINTERS + POINTER_INDEXES + TYPED_FORMS:
        for_("count.forms", text)
    return grid


def _drum_check(case: dict[str, Any]) -> dict[str, Any]:
    f, choices, kind = case["fields"], case.get("choices", {}), case["mode"]
    steps, outputs = int(f["num_steps"]), int(f["num_outputs"])

    def items(name: str, count: int) -> tuple[str, ...]:
        return tuple(f.get(f"{name}[{i}]", "") for i in range(count))

    return verdict_of(
        lambda: Drum(
            kind=kind,
            outputs=items("outputs", outputs),
            presets=() if kind == "event_drum" else items("presets", steps),
            events=() if kind == "time_drum" else items("events", steps),
            # The dialog opens with no cell of the pattern set.
            pattern=((0,) * outputs,) * steps,
            current_step=f.get("current_step", ""),
            completion_flag=f.get("completion_flag", ""),
            accumulator=f.get("accumulator", ""),
            unit=UNITS[choices["unit"]] if "unit" in choices else "",
            jog_enabled=_option(case, "jog_enabled"),
            jump_enabled=_option(case, "jump_enabled"),
            jump_step=f.get("jump_step", ""),
        )
    )


#: The drum kinds that the grid tries. It leaves out time_event_drum, the Time & Event drum
#: that only CLICK v4 has.
DRUM_KINDS = ("time_drum", "event_drum")


def _drum_base(
    kind: str, steps: int = 2, outputs: int = 2
) -> tuple[dict[str, str], dict[str, str]]:
    """Return the fields and the choices of a drum that laddercodec accepts.

    The outputs run from Y001. Each step of a time drum lasts 1000 s, and the events of an
    event drum run from X001. The dialog has at most DRUM_SIZE steps and DRUM_SIZE outputs.
    For a larger ``steps`` or ``outputs``, the function fills only the first DRUM_SIZE."""
    fields = {"num_steps": str(steps), "num_outputs": str(outputs)}
    fields |= {f"outputs[{i}]": addr("Y", i + 1) for i in range(min(outputs, DRUM_SIZE))}
    if kind == "time_drum":
        fields |= {f"presets[{i}]": "1000" for i in range(min(steps, DRUM_SIZE))}
    else:
        fields |= {f"events[{i}]": addr("X", i + 1) for i in range(min(steps, DRUM_SIZE))}
    fields["current_step"] = "DS1"
    if kind == "time_drum":
        fields["accumulator"] = "TD1"
    fields["completion_flag"] = "C1"
    choices = {"unit": "sec"} if kind == "time_drum" else {}
    return fields, choices


def drum_grid() -> Grid:
    """Return the grid of the Drum dialog, in its time and event modes.

    Each drum case starts from a drum that laddercodec accepts and changes one field, list or
    option. A refusal then names the field that the case changed. A refusal of ``num_steps``
    names ``presets`` or ``events``, and a refusal of ``num_outputs`` names ``outputs``. When a
    case changes the number of steps or outputs, it also fills each step or output that the
    new number adds."""
    grid = Grid(_drum_check)

    def drum(
        row: str,
        kind: str,
        field: str | None = None,
        text: str = "",
        *,
        steps: int = 2,
        outputs: int = 2,
        choices: dict[str, str] | None = None,
        options: dict[str, int] | None = None,
    ) -> None:
        """Add the base drum with ``field`` set to ``text``, ``choices`` picked and
        ``options`` set. The label names only what differs from the base drum."""
        fields, picked = _drum_base(kind, steps, outputs)
        changed = {} if field is None else {field: text}
        fields |= changed
        picked |= choices or {}
        base_fields, base_choices = _drum_base(kind)
        diff = [f"{k}={v}" for k, v in picked.items() if base_choices.get(k) != v]
        diff += [f"{k}={v}" for k, v in (options or {}).items()]
        diff += [f"{k}={v}" for k, v in changed.items() if base_fields.get(k) != v]
        label = f"{kind} " + (" ".join(diff) if diff else "base")
        grid.add_case(
            f"drum.{row}", label, "drum", kind, fields, choices=picked or None, options=options
        )

    for kind in DRUM_KINDS:
        drum("control", kind)
    # Each unit, a unit on an event drum, and the edges of a constant duration in each unit.
    for unit in UNITS:
        drum("units", "time_drum", choices={"unit": unit})
    drum("units", "event_drum", choices={"unit": "sec"})
    for unit in UNITS:
        for text in ("0", str(INT16_MAX), str(INT16_MAX + 1), "39999", "40000", "-1"):
            drum("presets.edges", "time_drum", "presets[0]", text, choices={"unit": unit})
    # Each constant spelling, bank and pointer form as the first step's duration, and a
    # register as the second's.
    for _, text in kinds_of_constants():
        drum("presets.constants", "time_drum", "presets[0]", text)
    for bank in BANKS:
        for text in samples(bank):
            drum("presets.banks", "time_drum", "presets[0]", text)
    for text in POINTERS + POINTER_INDEXES + TYPED_FORMS:
        drum("presets.forms", "time_drum", "presets[0]", text)
    drum("presets.forms", "time_drum", "presets[1]", "DS2")
    # The number of steps and of outputs at their edges, and one past each edge.
    for kind in DRUM_KINDS:
        for count in (0, 1, DRUM_SIZE, DRUM_SIZE + 1):
            drum("steps", kind, "num_steps", str(count), steps=count)
        for count in (0, 1, DRUM_SIZE, DRUM_SIZE + 1):
            drum("outputs", kind, "num_outputs", str(count), outputs=count)
    # An output used twice, the completion flag as an output, then each bank as the first
    # output.
    for key, text in (("outputs[1]", "Y001"), ("outputs[1]", "Y1"), ("outputs[0]", "C1")):
        drum("outputs.conflicts", "time_drum", key, text)
    for bank in BANKS:
        for text in samples(bank):
            drum("outputs.banks", "time_drum", "outputs[0]", text)
    for text in address_forms("Y"):
        drum("outputs.forms", "time_drum", "outputs[0]", text)
    # Each bank as the current step, the accumulator and the completion flag.
    for name in ("current_step", "accumulator", "completion_flag"):
        for bank in BANKS:
            for text in samples(bank):
                drum(f"{name.replace('_', '-')}.banks", "time_drum", name, text)
    # Each bank as the first event.
    for bank in BANKS:
        for text in samples(bank):
            drum("events.banks", "event_drum", "events[0]", text)
    for text in address_forms("X"):
        drum("events.forms", "event_drum", "events[0]", text)
    # Jog, and the jump input with each bank of step number.
    for kind in DRUM_KINDS:
        drum("jog", kind, options={"jog_enabled": 1})
        drum("jump", kind, "jump_step", "DS2", options={"jump_enabled": 1})
    for text in samples("DS") + ["DD1", "TD1", "C1"] + address_forms("DS"):
        drum("jump", "time_drum", "jump_step", text, options={"jump_enabled": 1})
    return grid


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------
#
# The runner does not drive the Send dialog yet. A field or list that mirrors one in the
# runner's Receive dialog has Receive's name. ``sending`` and ``ip`` have the names of
# laddercodec's fields, Send's and ModbusTcpTarget's. ``server_port`` is the Server Port
# Number, ModbusTcpTarget's ``port``. A list item is the text that the list shows.

#: Each item of the Com Port list, and the laddercodec port that it picks.
SEND_PORTS: dict[str, str] = {
    "CPU Port1": "ethernet",
    "WLAN Port": "wlan",
    "CPU Port2": "cpu2",
    "CPU Port3": "cpu3",
    "Slot0 Port1": "slot0_1",
    "Slot0 Port2": "slot0_2",
    "Slot1 Port1": "slot1_1",
    "Slot1 Port2": "slot1_2",
}
assert set(SEND_PORTS.values()) == set(get_args(ModbusRtuPort)) | set(get_args(ModbusTcpPort))
TCP_PORTS = frozenset(get_args(ModbusTcpPort))
#: Each item of the Modbus Function Code list, by its function code.
SEND_FUNCTIONS: dict[SendFunctionCode, str] = {
    5: "05 - Write Single Coil",
    6: "06 - Write Single Register",
    15: "15 - Write Multiple Coils",
    16: "16 - Write Multiple Registers",
}
assert set(SEND_FUNCTIONS) == set(get_args(SendFunctionCode))
#: Each item of the Addressing Type list, by the short name that a case label uses.
SEND_ADDRESSING: dict[str, str] = {
    "984": "Modbus 984 Addressing",
    "hex": "Modbus Hex Addressing",
    "click": "CLICK Addressing",
}
#: The function codes that write bits.
BIT_FUNCTIONS = (5, 15)
#: The function codes that write one element. A case of one of these leaves the count out,
#: except in the row that types the count.
SINGLE_FUNCTIONS = (5, 6)
#: The local banks that only function code 16 can send.
FC16_BANKS = ("DD", "DF", "CTD")
#: The IP address and server port that a case on a TCP port types, unless it changes them.
SEND_IP = "192.168.1.10"
SEND_SERVER_PORT = "502"
#: The status fields of a Send that laddercodec accepts.
SEND_STATUS = {"sending": "C100", "success": "C101", "error": "C102", "exception": "DS100"}


def _send_number(text: str) -> Any:
    """Return ``text`` as an int if it is decimal digits, with an optional minus sign.

    Return any other text as it is. laddercodec then refuses it as not a number, or reads a
    Slave ID as a DS address."""
    if len(text) <= 4300 and text[1 if text.startswith("-") else 0 :].isdigit() and text.isascii():
        return int(text)
    return text


def _send_build(case: dict[str, Any]) -> Callable[[], Send]:
    """Return a function that builds the Send of ``case``."""
    f, choices = case["fields"], case["choices"]
    com_port = SEND_PORTS[choices["port"]]
    code = next(n for n, item in SEND_FUNCTIONS.items() if item == choices["function"])
    addressing = choices["addressing"]

    def build() -> Send:
        device_id = _send_number(f["slave_id"])
        target: ModbusRtuTarget | ModbusTcpTarget
        if com_port in TCP_PORTS:
            target = ModbusTcpTarget(
                name="send",
                ip=f["ip"],
                port=_send_number(f["server_port"]),
                device_id=device_id,
                com_port=cast(ModbusTcpPort, com_port),
            )
        else:
            target = ModbusRtuTarget(
                name="send",
                com_port=cast(ModbusRtuPort, com_port),
                device_id=device_id,
            )
        text = f["slave_address"]
        remote: str | ModbusAddress
        if addressing == SEND_ADDRESSING["click"]:
            remote = text
        elif addressing == SEND_ADDRESSING["hex"]:
            remote = ModbusAddress(text, "coil" if code in BIT_FUNCTIONS else "holding")
        else:
            remote = ModbusAddress(text)
        return Send(
            target=target,
            remote_start=remote,
            source=f["master_address"],
            quantity=_send_number(f.get("count", "1")),
            sending=f["sending"],
            success=f["success"],
            error=f["error"],
            exception_response=f["exception"],
            word_swap=choices.get("word_swap") == "ON",
            function_code=code,
        )

    return build


def _send_check(case: dict[str, Any]) -> dict[str, Any]:
    return verdict_of(_send_build(case))


def _send_remote(code: SendFunctionCode, addressing: str) -> str:
    """Return a slave address that laddercodec accepts for ``code`` in ``addressing``."""
    bit = code in BIT_FUNCTIONS
    if addressing == "984":
        return "1" if bit else "400001"
    if addressing == "hex":
        return "0h"
    return "C1" if bit else "DS1"


def _send_code(bank: str) -> SendFunctionCode:
    """Return the function code that sends one element from ``bank``.

    The code is 05 for a bit bank, 16 for DD, DF and CTD, and 06 for any other bank."""
    if bank in BIT_BANKS:
        return 5
    return 16 if bank in FC16_BANKS else 6


def _send_takes_remote(code: SendFunctionCode, bank: str) -> bool:
    """Return True unless laddercodec leaves ``bank`` out of the CLICK slave banks of ``code``.

    The grid keeps a case for each source when a Send refuses the bank for another reason,
    such as SD or a source of another data type."""
    source = "C1" if code in BIT_FUNCTIONS else "DS1"
    fields = {"slave_id": "1", "slave_address": low(bank), "master_address": source}
    case = {
        "fields": fields | {"count": "1"} | SEND_STATUS,
        "choices": {
            "port": "CPU Port2",
            "function": SEND_FUNCTIONS[code],
            "addressing": SEND_ADDRESSING["click"],
        },
    }
    try:
        _send_build(case)()
    except FieldError as exc:
        return not any(
            error.fields == ("Send.remote_start",) and error.reason is Reason.BANK
            for error in exc.errors
        )
    return True


def send_grid() -> Grid:
    """Return the grid of the Modbus Send dialog.

    Each case starts from a Send that laddercodec accepts with the case's function code and
    addressing, and changes one field or list. The FC06 Send in 984 addressing writes DS1 to
    the holding register 400001 of slave 1 on CPU Port2, with the status fields in
    SEND_STATUS. A case types every field that its port shows, and picks an item in the port,
    function and addressing lists.

    laddercodec checks the fields in its own order, so a refusal does not always name the
    field that the case changed. For example, laddercodec refuses a 984 start of a kind that
    the function code does not write on the source."""
    grid = Grid(_send_check)

    def send(
        row: str,
        code: SendFunctionCode = 6,
        addressing: str = "984",
        remote: str | None = None,
        source: str | None = None,
        count: str | None = None,
        *,
        port: str = "CPU Port2",
        slave_id: str = "1",
        ip: str = SEND_IP,
        server_port: str = SEND_SERVER_PORT,
        word_swap: str | None = None,
        status: dict[str, str] | None = None,
    ) -> None:
        """Add a Send case. ``remote`` and ``source`` default to addresses that suit ``code``.

        A case whose function code writes more than one element types a count of 2, unless
        ``count`` names one. A code that writes one element leaves the count out unless
        ``count`` names one. ``status`` changes the status fields by name."""
        remote = _send_remote(code, addressing) if remote is None else remote
        if source is None:
            source = "C1" if code in BIT_FUNCTIONS else "DS1"
        if count is None and code not in SINGLE_FUNCTIONS:
            count = "2"
        # laddercodec reads a slave address that ends in h as hex, and one of digits only as
        # MODBUS 984. So laddercodec can't build a case that types 1h in 984 addressing, or 10
        # in hex addressing.
        hex_text = remote.endswith(("h", "H"))
        assert not (addressing == "984" and hex_text), remote
        assert not (addressing == "hex" and remote.isdigit()), remote
        fields = {"slave_id": slave_id}
        if SEND_PORTS[port] in TCP_PORTS:
            fields |= {"ip": ip, "server_port": server_port}
        fields |= {"slave_address": remote, "master_address": source}
        if count is not None:
            fields["count"] = count
        status = status or {}
        assert set(status) <= set(SEND_STATUS), status
        fields |= {name: status.get(name, text) for name, text in SEND_STATUS.items()}
        choices = {
            "port": port,
            "function": SEND_FUNCTIONS[code],
            "addressing": SEND_ADDRESSING[addressing],
        }
        if word_swap is not None:
            choices["word_swap"] = word_swap
        label = f"send fc{code:02d} {addressing} {remote} <- {source}"
        if count is not None:
            label += f" x{count}"
        extras = {"port": port} if port != "CPU Port2" else {}
        if slave_id != "1":
            extras["id"] = slave_id
        if SEND_PORTS[port] in TCP_PORTS:
            extras |= {"ip": ip} if ip != SEND_IP else {}
            extras |= {"server_port": server_port} if server_port != SEND_SERVER_PORT else {}
        extras |= {k: v for k, v in status.items() if v != SEND_STATUS[k]}
        if word_swap is not None:
            extras["word_swap"] = word_swap
        label += "".join(f" {k}={v}" for k, v in extras.items())
        grid.add_case(f"send.{row}", label, "send", None, fields, choices=choices)

    # Each function code with 984 addressing, then each code with CLICK addressing, from C1
    # to C1 and from DS1 to DS1.
    for code in SEND_FUNCTIONS:
        send("control", code)
    for code in SEND_FUNCTIONS:
        send("control", code, "click")
    # Each port. A TCP port shows the IP address and the server port.
    for port in SEND_PORTS:
        send("ports", port=port)
    # Each function code with a 984 start of each kind: coil, input, input register and
    # holding register.
    for code in SEND_FUNCTIONS:
        for remote in ("1", "100001", "300001", "400001"):
            send("function.remote", code, remote=remote)
    # Each function code with each bank as the source, to a 984 start that suits the code.
    for code in SEND_FUNCTIONS:
        for bank in BANKS:
            send("function.source-banks", code, source=low(bank))
    # With CLICK addressing, each bit bank against each bit bank under the bit codes, and
    # each register bank against each register bank under the register codes. A remote bank
    # that laddercodec refuses for the code gets one case, with the code's plain source.
    for code in SEND_FUNCTIONS:
        order = BIT_ORDER if code in BIT_FUNCTIONS else REGISTER_ORDER
        for remote_bank in order:
            if not _send_takes_remote(code, remote_bank):
                send("function.click-pairs", code, "click", low(remote_bank))
                continue
            for source_bank in order:
                send("function.click-pairs", code, "click", low(remote_bank), low(source_bank))
    # Each bank as the source, with the code that sends one element from it.
    for bank in BANKS:
        code = _send_code(bank)
        for text in samples(bank):
            send("source.banks", code, source=text, count="1" if code == 16 else None)
    for text in address_forms("DS") + FORMS_SHORT:
        send("source.forms", source=text)
    for text in address_forms("C"):
        send("source.forms", 5, source=text)
    for text in FEW:
        send("source.constants", source=text)
    # The count with a code that writes one element: one, two and none.
    for code in SINGLE_FUNCTIONS:
        for text in ("1", "2", "0"):
            send("count.single", code, count=text)
    # The count at its caps, from the first address of a bank, and past the end of the bank.
    for code, start, counts in (
        (15, "C1", ("1968", "1969", "0", "-1")),
        (16, "DS1", ("123", "124", "0", "-1")),
        (16, "DD1", ("61", "62")),
        (16, "DF1", ("61", "62")),
        (16, "CTD1", ("61", "62")),
        (16, "DH1", ("123", "124")),
        (16, "TD1", ("123", "124")),
        (16, "SD1", ("123", "124")),
    ):
        for text in counts:
            send("count.edges", code, source=start, count=text)
    for bank in ("C", "T", "CT", "SC", "DS", "DD", "DH", "DF", "TD", "CTD", "SD"):
        last = ADDRESS_BANKS[bank][1]
        code = 15 if bank in BIT_BANKS else 16
        for text in ("1", "2"):
            send("count.edges", code, source=addr(bank, last), count=text)
        # The room left near the end, and one more.
        for text in ("10", "11"):
            send("count.edges", code, source=addr(bank, last - 9), count=text)
    # X and Y counts from X001, X005 and Y001. The slots X001-X016 and X021-X036 make 32
    # points from X001, and the slots through X816 make 160.
    for start, counts in (
        ("X001", ("16", "17", "32", "33", "160", "161")),
        ("X005", ("12", "13", "28", "29", "156", "157")),
        ("Y001", ("16", "17", "32", "33", "160", "161")),
        ("X101", ("16", "17")),
        ("X816", ("1", "2")),
    ):
        for text in counts:
            send("count.xy", 15, source=start, count=text)
    for remote in ("C1", "Y001", "C1990"):
        for start, counts in (("X001", ("16", "17", "32", "33")), ("X005", ("28", "29"))):
            for text in counts:
                send("count.xy", 15, "click", remote, start, text)
    # An X source with a register as the remote start.
    for start in ("X001", "X005"):
        send("click.x-to-register", 6, "click", "DS1", start)
        send("click.x-to-register", 16, "click", "DS1", start, "1")
        send("click.x-to-register", 16, "click", "DS1", start, "16")
    # The TXT count: in characters or in registers, odd or even, and its limits.
    for text in ("1", "2", "3", "4", "122", "123", "124", "125", "126", "246", "247", "248",
                 "249", "250", "251", "252", "0"):  # fmt: skip
        send("count.txt", 16, source="TXT1", count=text)
    for start, counts in (("TXT999", ("1", "2", "3")), ("TXT1000", ("1", "2"))):
        for text in counts:
            send("count.txt", 16, source=start, count=text)
    send("count.txt", 6, source="TXT1")
    send("count.txt", 6, source="TXT1000")
    for text in ("1", "2", "3", "250", "251"):
        send("count.txt", 16, "click", "TXT1", "TXT1", text)
        send("count.txt", 16, "hex", "0h", "TXT1", text)
    # Each spelling of a 984 slave address. A coil spelling goes with the coil code and a
    # holding register spelling with the register code, since function.remote asks each code
    # with a start of the other kind. Any other spelling goes with both codes.
    for text in ("0", "01", "000001", "65535", "065535", "65536"):
        send("remote.984", 5, remote=text)
    for text in ("400000", "0400001", "465535", "465536", "4000001"):
        send("remote.984", 6, remote=text)
    for text in ("165535", "1.5", "-1", "+1", "1 0", "abc", "DS1"):
        send("remote.984", 5, remote=text)
        send("remote.984", 6, remote=text)
    # Each spelling of a hex slave address, with a coil code and a register code: the edges
    # 0h and FFFEh, past FFFEh, other cases and leading zeros, h alone, and an h typed twice.
    for text in ("0h", "0H", "1h", "00001h", "ffh", "FFFDh", "FFFEh", "0FFFEh", "FFFFh",
                 "10000h", "h", "H", "1HH", "1hh", "hh", "-1h", "+1h", "1.5h", "Gh", "1 0h",
                 "FFFE", "ABC"):  # fmt: skip
        send("remote.hex", 5, "hex", text)
        send("remote.hex", 16, "hex", text)
    # A hex start near FFFEh with a 32-bit, real or text source: one element and two.
    for source in ("DS1", "DD1", "DF1", "CTD1", "TXT1"):
        for text in ("FFFCh", "FFFDh", "FFFEh"):
            for count in ("1", "2"):
                send("remote.hex-wide", 16, "hex", text, source, count)
    for count in ("13", "14", "15"):
        send("remote.hex-wide", 16, "hex", "FFF0h", "DD1", count)
    # Each bank as a CLICK slave address, with a code and a source that suit the bank.
    for bank in BANKS:
        code = _send_code(bank)
        source = "DD1" if code == 16 else ("C1" if code == 5 else "DS1")
        count = "1" if code == 16 else None
        for text in samples(bank):
            send("remote.click.banks", code, "click", text, source, count)
    for text in address_forms("DS") + ["DS[DS1]", "400001", "0h"]:
        send("remote.click.forms", 6, "click", text)
    # The Slave ID on an RTU port and on a TCP port: each edge, a DS address and other text.
    ids = ["0", "1", "01", "247", "248", "255", "256", "-1", "1.5", "abc"]
    ids += ["DS1", "DS4500", "DS4501", "DS0", "ds1", "DS001", "DD1", "C1", "DS[DS1]"]
    for text in ids:
        send("slave-id.rtu", slave_id=text)
        send("slave-id.tcp", port="CPU Port1", slave_id=text)
    for port in SEND_PORTS:
        for text in ("0", "247", "248", "255", "256"):
            send("slave-id.ports", port=port, slave_id=text)
    # The server port and the IP address of a TCP port.
    for text in ("1", "502", "65535", "0", "65536", "abc"):
        send("tcp.server-port", port="CPU Port1", server_port=text)
    for text in ("0.0.0.0", "255.255.255.255", "10.0.0.1"):
        send("tcp.ip", port="CPU Port1", ip=text)
    # Each bank in each status field, then other ways to type a status address. laddercodec
    # checks the success and error bits as it checks the sending bit, so they get only the
    # first address of each bank.
    for name in SEND_STATUS:
        for bank in BANKS:
            texts = [low(bank)] if name in ("success", "error") else samples(bank)
            for text in texts:
                send(f"status.{name}.banks", status={name: text})
    for text in address_forms("C"):
        send("status.forms", status={"sending": text})
    for text in address_forms("DS"):
        send("status.forms", status={"exception": text})
    # One C bit in two status fields, or in all three.
    for status in (
        {"success": "C100"},
        {"error": "C100"},
        {"error": "C101"},
        {"success": "C100", "error": "C100"},
        {"success": "c100"},
        {"error": "C0101"},
    ):
        send("status.shared", status=status)
    # A status bit inside the source range.
    send("status.shared", 15, source="C100", count="2")
    send("status.shared", 15, "click", "C1", "C99", "2")
    # Word Swap on a 32-bit or real source, on DS and TXT, and on bits.
    for source, code, count in (
        ("DD1", 16, "1"),
        ("DF1", 16, "1"),
        ("CTD1", 16, "1"),
        ("DD1", 16, "2"),
        ("DS1", 16, "2"),
        ("DS1", 6, None),
        ("TXT1", 16, "2"),
        ("C1", 15, "2"),
    ):
        send("word-swap", code, source=source, count=count, word_swap="ON")
    send("word-swap", 16, source="DD1", count="1", word_swap="OFF")
    # The risky spellings: empty, a space at either end, a tab, a character outside ASCII,
    # and more than RISKY_LENGTH characters.
    overlong = "DS" + "0" * RISKY_LENGTH + "1"
    for text in ("", " DS1", "DS1 ", "DS\t1", "DS1é", overlong):
        send("source.risky", source=text)
    for text in ("", " 400001", "400001 ", "4000\t01", "40000١", "4" + "0" * RISKY_LENGTH + "1"):
        send("remote.risky", remote=text)
    for text in ("", " 1", "1 ", "1\t", "١", "0" * RISKY_LENGTH + "1"):
        send("slave-id.risky", slave_id=text)
        send("count.risky", 16, count=text)
    for name, sample in SEND_STATUS.items():
        long_text = _bank_of(sample) + "0" * RISKY_LENGTH + "1"
        for text in ("", f" {sample}", f"{sample} ", f"{sample}\t", f"{sample}é", long_text):
            send(f"status.{name}.risky", status={name: text})
    return grid


# ---------------------------------------------------------------------------
# Receive
# ---------------------------------------------------------------------------
#
# The generator writes no Receive grid. The Receive grids are ClickNick's own (RUNNER_GRIDS),
# and the generator writes their verdicts.

#: Each item of the Receive dialog's Modbus Function Code list, by its function code.
RECEIVE_FUNCTIONS: dict[ReceiveFunctionCode, str] = {
    1: "01 - Read Coil Status",
    2: "02 - Read Input Status",
    3: "03 - Read Holding Registers",
    4: "04 - Read Input Registers",
}
assert set(RECEIVE_FUNCTIONS) == set(get_args(ReceiveFunctionCode))


def receive_build(case: dict[str, Any], count: str | None = None) -> Callable[[], Receive]:
    """Return a function that builds the Receive of ``case``.

    The Receive reads from slave 1 on CPU Port2, unless the case types a Slave ID. With
    CLICK addressing, the slave address is the address text. With any other addressing, or
    with none picked, it is a ``ModbusAddress`` of the text. ``count`` is the text of the
    count to build with. If it is None, the count is the one that the case types, or 1."""
    f, choices = case["fields"], case["choices"]
    code = next(n for n, item in RECEIVE_FUNCTIONS.items() if item == choices["function"])
    text = f["slave_address"]
    click = choices.get("addressing") == SEND_ADDRESSING["click"]
    quantity = f.get("count", "1") if count is None else count

    def build() -> Receive:
        return Receive(
            target=ModbusRtuTarget(
                name="r", com_port="cpu2", device_id=_send_number(f.get("slave_id", "1"))
            ),
            remote_start=text if click else ModbusAddress(text),
            dest=f["master_address"],
            quantity=_send_number(quantity),
            receiving=f["receiving"],
            success=f["success"],
            error=f["error"],
            exception_response=f["exception"],
            function_code=code,
        )

    return build


def _receive_check(case: dict[str, Any]) -> dict[str, Any]:
    return verdict_of(receive_build(case))


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


#: A field longer than this is risky.
RISKY_LENGTH = 40


def is_risky(case: dict[str, Any]) -> bool:
    """Return True if a field's text may not survive typing into the dialog.

    Such a field is empty, has a space at either end, holds a tab or a character outside
    ASCII, or is longer than RISKY_LENGTH. These cases go in the risky files. The other
    files then hold only text that a field is expected to read back as typed."""
    return any(
        not v or v != v.strip() or "\t" in v or not v.isascii() or len(v) > RISKY_LENGTH
        for v in case["fields"].values()
    )


#: The builder of each whole grid. Fill is a mode of the Copy dialog, but its grid is built
#: on its own.
WHOLE: dict[str, Callable[[], Grid]] = {
    "math": math_grid,
    "copy": copy_grid,
    "out": out_grid,
    "fill": fill_grid,
    "compare": compare_grid,
    "search": search_grid,
    "timer": timer_grid,
    "counter": counter_grid,
    "shift": shift_grid,
    "for": for_grid,
    "drum": drum_grid,
    "send": send_grid,
}

#: The whole grids that ``preflight.json`` and ``risky.json`` take their cases from, in order.
#: The runner places Compare only with ``--wire``, because Compare is a contact. The runner
#: does not drive Fill yet. So Compare and Fill each have a preflight and a risky file.
PREFLIGHT_GRIDS = ("math", "copy", "out", "search")

#: The dialogs that the runner does not drive yet. Each has a grid, a preflight file and a
#: risky file of its own.
UNDRIVEN = ("timer", "counter", "shift", "for", "drum", "send")


@functools.cache
def _whole(name: str) -> Grid:
    return WHOLE[name]()


def only(name: str, mode: str | None = None, *, every_mode: bool = False) -> Callable[[], Grid]:
    """Return a function that builds a grid of the cases of grid ``name`` in ``mode``.

    With ``every_mode``, the grid holds the cases of every mode. Compare and Search use it,
    because their mode is the operator. The grid leaves out the risky cases."""

    def part() -> Grid:
        whole = _whole(name)
        grid = Grid(whole.check)
        for case in whole.cases:
            if (every_mode or case.get("mode") == mode) and not is_risky(case):
                grid.labels[case["case"]] = case
                grid.cases.append(case)
        return grid

    return part


def check_case(case: dict[str, Any]) -> dict[str, Any]:
    """Return laddercodec's verdict on a case from any dialog."""
    checks = {
        "math": _math_check,
        "copy": _copy_check,
        "out": _out_check,
        "set": _set_check,
        "reset": _reset_check,
        "compare": _compare_check,
        "search": _search_check,
        "timer": _timer_check,
        "counter": _counter_check,
        "shift": _shift_check,
        "for": _for_check,
        "drum": _drum_check,
        "send": _send_check,
        "receive": _receive_check,
    }
    return checks[case["instruction"]](case)


def risky(*names: str) -> Callable[[], Grid]:
    """Return a function that builds a grid of the risky cases of the grids ``names``."""

    def part() -> Grid:
        grid = Grid(check_case)
        for name in names:
            for case in _whole(name).cases:
                if is_risky(case):
                    grid.labels[case["case"]] = case
                    grid.cases.append(case)
        return grid

    return part


def preflight(*names: str) -> Callable[[], Grid]:
    """Return a function that builds a grid of the first case that is not risky from each
    row of the grids ``names``.

    The grid tries once each field and state that the control cases do not type into, such
    as Out's range end, or a constant or pointer in a range end. A field that will not take
    text then shows in this short run and not in a long one."""

    def part() -> Grid:
        grid = Grid(check_case)
        for name in names:
            seen: set[str] = set()
            for case in _whole(name).cases:
                if case["row"] not in seen and not is_risky(case):
                    seen.add(case["row"])
                    grid.labels[case["case"]] = case
                    grid.cases.append(case)
        return grid

    return part


#: The preflight and risky files, then one file for each dialog and mode. Math and Copy have a
#: file for each mode because their lists are long. Compare and Search have one file each,
#: which holds every operator. Each dialog in UNDRIVEN has one file, which holds every mode.
GRIDS: dict[str, Callable[[], Grid]] = {
    "preflight": preflight(*PREFLIGHT_GRIDS),
    "risky": risky(*PREFLIGHT_GRIDS),
    "preflight_compare": preflight("compare"),
    "risky_compare": risky("compare"),
    "preflight_fill": preflight("fill"),
    "risky_fill": risky("fill"),
    "math_decimal": only("math", "decimal"),
    "math_hex": only("math", "hex"),
    "copy_single": only("copy", "single"),
    "copy_block": only("copy", "block"),
    "copy_pack": only("copy", "pack"),
    "copy_unpack": only("copy", "unpack"),
    "out": only("out"),
    "copy_fill": only("fill", "fill"),
    "compare": only("compare", every_mode=True),
    "search": only("search", every_mode=True),
    **{f"preflight_{name}": preflight(name) for name in UNDRIVEN},
    **{f"risky_{name}": risky(name) for name in UNDRIVEN},
    **{name: only(name, every_mode=True) for name in UNDRIVEN},
}

#: The grids that ClickNick wrote. The files hold ClickNick's text as it is. The generator
#: reads each grid and writes only its verdicts file.
RUNNER_GRIDS = (
    "receive_click",
    "receive_click_count1",
    "drum_events",
    "drum_events_names",
    "drum_events_shapes",
    "drum_events_padded",
    "drum_events_padded2",
    "coil_sc",
    "coil_sc_ranges",
    "compare_const",
)


def runner_grid(name: str) -> Grid:
    """Return the grid ``name`` of RUNNER_GRIDS, read from its file."""
    grid = Grid(check_case)
    path = OUT_DIR / f"{name}.json"
    for case in json.loads(path.read_text(encoding="utf-8"))["cases"]:
        grid.add_case(
            case["row"],
            case["case"],
            case["instruction"],
            case.get("mode"),
            case["fields"],
            choices=case.get("choices"),
            options=case.get("options"),
        )
    return grid


def _lines(head: str, items: list[str], tail: str) -> str:
    return head + "\n" + ",\n".join(items) + "\n" + tail + "\n"


def render_cases(grid: Grid) -> str:
    """Return the text of the grid file, with one case on each line."""
    items = ["  " + json.dumps(case, ensure_ascii=True) for case in grid.cases]
    return _lines('{\n "cases": [', items, " ]\n}")


def render_verdicts(grid: Grid) -> str:
    """Return the text of the verdicts file, with one verdict on each line, keyed by label."""
    items = [
        f"  {json.dumps(label, ensure_ascii=True)}: {json.dumps(v, ensure_ascii=True)}"
        for label, v in grid.verdicts().items()
    ]
    return _lines("{", items, "}")


def build() -> dict[str, str]:
    """Return the name and text of every file."""
    files: dict[str, str] = {}
    for name, make in GRIDS.items():
        grid = make()
        files[f"{name}.json"] = render_cases(grid)
        files[f"{name}.verdicts.json"] = render_verdicts(grid)
    for name in RUNNER_GRIDS:
        files[f"{name}.verdicts.json"] = render_verdicts(runner_grid(name))
    return files


def counts() -> dict[str, int]:
    """Return the number of cases in each grid."""
    return {name: len(make().cases) for name, make in GRIDS.items()}


def write_keeping_eol(path: Path, text: str) -> None:
    """Write ``text`` (LF line ends) to ``path``. Leave the file alone when only its line ends differ.

    A file that exists keeps its own line ending. A new file gets LF."""
    data = text.encode("utf-8")
    eol = b"\n"
    if path.is_file():
        old = path.read_bytes()
        if old.replace(b"\r\n", b"\n") == data:
            return
        if b"\r\n" in old:
            eol = b"\r\n"
    path.write_bytes(data.replace(b"\n", eol))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="compare, write nothing")
    args = parser.parse_args()
    files = build()
    if args.check:
        stale = [
            name
            for name, text in files.items()
            if not (OUT_DIR / name).is_file()
            or (OUT_DIR / name).read_text(encoding="utf-8") != text
        ]
        if stale:
            print("out of date:", ", ".join(stale), file=sys.stderr)
            return 1
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        write_keeping_eol(OUT_DIR / name, text)
    for name, n in counts().items():
        hours = n * SECONDS_PER_CASE / 3600
        flag = "  (over the split limit)" if n > SPLIT_AT else ""
        print(f"{name}.json: {n} cases, about {hours:.1f} h{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
