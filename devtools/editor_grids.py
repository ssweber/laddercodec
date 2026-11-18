"""Write the editor grids: the cases ClickNick's runner types into CLICK's instruction dialogs.

    make editor-grids                          # write tests/fixtures/editor_grids/, then check
    uv run devtools/editor_grids.py            # write only
    uv run devtools/editor_grids.py --check    # exit 1 if the committed files differ

A grid is a case list in the runner's own shape (``{"cases": [{"row", "case", "instruction",
"mode", "fields", "options"}, ...]}``), one file per dialog, built from laddercodec's own bank
lists, constant kinds and field rules so the lists keep in step with the code. Each grid has a
verdicts file beside it, ``<grid>.verdicts.json``: what laddercodec's rules say about each
case today, keyed by the case's label, for comparing with CLICK's answers when they come. The
runner reads only the grid.
"""

from __future__ import annotations

import argparse
import functools
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from laddercodec.instructions.coil import Coil
from laddercodec.instructions.comparison import CompareContact
from laddercodec.instructions.copy import BlockCopy, Copy, Fill, Pack, Unpack
from laddercodec.instructions.math import Math
from laddercodec.instructions.search import Search
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
        """Add a case. If the file already has a case with this label, keep only the first.

        ``options`` maps a button's control id, as a decimal string, to 1 (on) or 0 (off). A
        case without it leaves every option as the dialog opens."""
        case: dict[str, Any] = {"row": row, "case": label, "instruction": instruction}
        if mode is not None:
            case["mode"] = mode
        case["fields"] = fields
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
    return grid


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
}

#: The whole grids that ``preflight.json`` and ``risky.json`` take their cases from, in order.
#: The runner places Compare only with ``--wire``, because Compare is a contact. The runner
#: does not drive Fill yet. So Compare and Fill each have a preflight and a risky file.
PREFLIGHT_GRIDS = ("math", "copy", "out", "search")


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
        "compare": _compare_check,
        "search": _search_check,
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
#: which holds every operator.
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
}


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
    return files


def counts() -> dict[str, int]:
    """Return the number of cases in each grid."""
    return {name: len(make().cases) for name, make in GRIDS.items()}


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
        with (OUT_DIR / name).open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    for name, n in counts().items():
        hours = n * SECONDS_PER_CASE / 3600
        flag = "  (over the split limit)" if n > SPLIT_AT else ""
        print(f"{name}.json: {n} cases, about {hours:.1f} h{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
