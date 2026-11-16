"""Write the editor grids: the cases ClickNick's runner types into CLICK's instruction dialogs.

    uv run devtools/editor_grids.py            # write tests/fixtures/editor_grids/
    uv run devtools/editor_grids.py --check    # exit 1 if the committed files differ

A grid is a case list in the runner's own shape (``{"cases": [{"row", "case", "instruction",
"mode", "fields"}, ...]}``), one file per dialog, built from laddercodec's own bank lists,
constant kinds and field rules so the lists keep in step with the code. Each grid has a
verdicts file beside it, ``<grid>.verdicts.json``: what laddercodec's rules say about each
case today, keyed by the case's label, for comparing with CLICK's answers when they come. The
runner reads only the grid.

The SD and SC sweeps are files of their own (``copy_sd_single``, ``copy_sd_block``,
``math_sd``, ``out_sc``): each is one case per address, so a run can take them apart from the
rest.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from laddercodec.instructions.coil import Coil
from laddercodec.instructions.copy import BlockCopy, Copy, Pack, Unpack
from laddercodec.instructions.math import Math
from laddercodec.model import ADDRESS_BANKS, XY_SLOTS, Address, InstructionType, check_address
from laddercodec.operands.checks import BIT_BANKS, REGISTER_BANKS
from laddercodec.operands.constants import (
    INT16_MAX,
    INT16_MIN,
    INT32_MAX,
    INT32_MIN,
    TEXT_MAX,
    Kind,
)

OUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "editor_grids"
#: Seconds one case takes the runner, for the estimates.
SECONDS_PER_CASE = 4
#: A file longer than this is split.
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
    """An address in the form CLICK shows."""
    return Address(bank, number, upper).display


def samples(bank: str) -> list[str]:
    """In-range addresses of ``bank`` at its edges, then the addresses just outside it."""
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
    """The lowest address of ``bank``."""
    return addr(bank, *((0,) if bank in WORD_IO else (ADDRESS_BANKS[bank][0],)))


def ranges(bank: str) -> list[tuple[str, str]]:
    """Ranges ``(start, end)`` in ``bank``: a pair, the longest, edges and the refused shapes."""
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
    """The end of a run of ``count`` addresses from the first of ``bank`` (the number is
    arithmetic, so it may fall in a gap or past the bank)."""
    start = 0 if bank in WORD_IO else ADDRESS_BANKS[bank][0]
    return addr(bank, start + count - 1)


#: Other ways to type an address.
TYPED_FORMS = ["ds1", "DS001", "DS01", "x1", "x001", "c001", " DS1", "DS1 ", "DS 1", "xd0U", "XD0u"]

#: The pointer forms: every bank as the pointed bank, and index texts.
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

#: Constants by kind (every :class:`Kind` has a list), spelled the ways the shared constant
#: reader tells apart.
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

#: Text that is no constant and no address.
NOT_CONSTANTS = ["abc", "", " ", "1 2", "1,5", "٣", "DS", "DS1.5", "5DS", "#5", "@5"]

#: One constant per kind and width, for the pairing with each bank.
REPRESENTATIVES = ["5", "-5", str(INT32_MAX), "1.5", "FFh", "10000h", '"A"', '"AB"', "$41"]
#: A few spellings, for a field the full list does not need.
FEW = ["5", "1.5", "FFh", '"A"', "$41"]
#: Other forms of an address, for a field that takes no pointer.
FORMS_SHORT = ["DS[DS1]", "X[DS1]", "ds1", "DS001", " DS1"]
#: Banks to pair every bank with, in a range that crosses banks.
PARTNERS = ("X", "C", "DS", "TXT")


def all_constants() -> list[str]:
    """Every spelling, kind by kind, then the texts that are none."""
    return [text for kind in Kind for text in CONSTANTS[kind]] + NOT_CONSTANTS


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


class Grid:
    """The cases of one file, and laddercodec's verdict on each."""

    def __init__(self, check: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.cases: list[dict[str, Any]] = []
        self.labels: set[str] = set()
        self.check = check

    def add(
        self,
        row: str,
        label: str,
        instruction: str,
        mode: str | None,
        **fields: str,
    ) -> None:
        """Add a case; one with a label already in the file is the same case and is kept once."""
        if label in self.labels:
            return
        self.labels.add(label)
        case: dict[str, Any] = {"row": row, "case": label, "instruction": instruction}
        if mode is not None:
            case["mode"] = mode
        case["fields"] = fields
        self.cases.append(case)

    def verdicts(self) -> dict[str, dict[str, Any]]:
        """laddercodec's verdict on each case, by label."""
        return {case["case"]: self.check(case) for case in self.cases}


def verdict_of(build: Callable[[], object]) -> dict[str, Any]:
    """Build an instruction: ``accepted``, or ``refused`` with the error, its field and message."""
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
    """The destination end CLICK works out for a Block Copy: the start plus the source's count."""
    try:
        first = check_address(source, "s", set(BANKS))
        last = check_address(source_end, "e", set(BANKS))
        dest = check_address(destination, "d", set(BANKS))
        return addr(dest.bank, dest.number + last.number - first.number)
    except ValueError:
        return destination


def _bank_of(text: str) -> str:
    """The bank letters of an address text, else ``""``."""
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
    """Math, decimal and hex."""
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
        # The result takes each bank, and a pointer.
        for bank in BANKS:
            for text in samples(bank):
                add(f"result.{mode}.banks", mode, text, base)
        for text in POINTERS + POINTER_INDEXES + TYPED_FORMS:
            add(f"result.{mode}.forms", mode, text, base)
        for text in ["5", "1.5", "FFh", '"A"', "$41", ""]:
            add(f"result.{mode}.not-an-address", mode, text, base)
        # An operand is each bank, alone and with a constant of the mode.
        one = "1" if mode == "decimal" else "1h"
        for bank in BANKS:
            for text in samples(bank):
                add(f"operand.{mode}.banks", mode, result, f"{text} + {one}")
                add(f"operand.{mode}.banks-alone", mode, result, text)
        for text in POINTERS + POINTER_INDEXES + TYPED_FORMS:
            add(f"operand.{mode}.forms", mode, result, f"{text} + {one}")
        # A constant of every kind and spelling, with an operand and alone.
        own = "DS1" if mode == "decimal" else "DH1"
        for text in all_constants():
            add(f"constants.{mode}", mode, result, f"{own} + {text}")
            add(f"constants.{mode}.alone", mode, result, text)
        # RAND: each bank as a bound, and the equal and reversed bounds.
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
        # SUM: each bank's ranges.
        for bank in BANKS:
            for start, end in ranges(bank):
                add(f"sum.{mode}.ranges", mode, result, f"SUM({start}:{end})")
    # Mixed-bank SUM ranges, and the other range functions, in decimal.
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


def math_sd_grid() -> Grid:
    """Every SD address as the result of a decimal Math."""
    grid = Grid(_math_check)
    for n in range(ADDRESS_BANKS["SD"][0], ADDRESS_BANKS["SD"][1] + 1):
        grid.add("math.result.sd", f"dec SD{n} = DS2 + 1", "math", "decimal",
                 result=f"SD{n}", formula="DS2 + 1")  # fmt: skip
    return grid


# ---------------------------------------------------------------------------
# Copy
# ---------------------------------------------------------------------------


def _copy_check(case: dict[str, Any]) -> dict[str, Any]:
    f, mode = case["fields"], case["mode"]
    if mode == "single":
        return verdict_of(lambda: Copy(f["source"], f["destination"]))
    if mode == "block":
        end = _block_end(f["source"], f["source_end"], f["destination"])
        return verdict_of(lambda: BlockCopy(f["source"], f["source_end"], f["destination"], end))
    if mode == "pack":
        bank = _bank_of(f["source"])
        kind = "text" if bank == "TXT" else "bits" if bank in BIT_BANKS else "words"
        return verdict_of(lambda: Pack(f["source"], f["source_end"], f["destination"], kind))
    if mode == "unpack":
        kind = "bits" if _bank_of(f["destination"]) in BIT_BANKS else "words"
        return verdict_of(lambda: Unpack(f["source"], f["destination"], f["destination_end"], kind))
    raise AssertionError(mode)


def _natural_dest(source_bank: str) -> str:
    """A destination that takes a source from ``source_bank``."""
    return "C1" if source_bank in BIT_BANKS else "DS1"


def _natural_source(dest_bank: str) -> str:
    """A source that goes to ``dest_bank``."""
    return "X001" if dest_bank in ("Y", "C") else "DS2"


def copy_grid() -> Grid:
    """Copy: single, block, pack and unpack."""
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
    # Text into TXT: where its characters end.
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
    return grid


def copy_sd_single_grid() -> Grid:
    """Every SD address as the destination of a single Copy."""
    grid = Grid(_copy_check)
    for n in range(ADDRESS_BANKS["SD"][0], ADDRESS_BANKS["SD"][1] + 1):
        grid.add("copy.single.sd", f"single DS1 -> SD{n}", "copy", "single",
                 source="DS1", destination=f"SD{n}")  # fmt: skip
    return grid


def copy_sd_block_grid() -> Grid:
    """Every SD address as the start of a Block Copy destination range of two."""
    grid = Grid(_copy_check)
    for n in range(ADDRESS_BANKS["SD"][0], ADDRESS_BANKS["SD"][1] + 1):
        grid.add("copy.block.sd", f"block DS1..DS2 -> SD{n}", "copy", "block",
                 source="DS1", source_end="DS2", destination=f"SD{n}")  # fmt: skip
    return grid


# ---------------------------------------------------------------------------
# Out
# ---------------------------------------------------------------------------


def _out_check(case: dict[str, Any]) -> dict[str, Any]:
    f = case["fields"]
    return verdict_of(lambda: Coil(InstructionType.COIL_OUT, f["address"], f.get("address_end")))


def out_grid() -> Grid:
    """Out (Out/Toggle, no One Shot, no Immediate)."""
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


def out_sc_grid() -> Grid:
    """Every SC address as an Out target."""
    grid = Grid(_out_check)
    for n in range(ADDRESS_BANKS["SC"][0], ADDRESS_BANKS["SC"][1] + 1):
        grid.add("out.sc", f"out SC{n}", "out", None, address=f"SC{n}")
    return grid


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def only(make: Callable[[], Grid], mode: str) -> Callable[[], Grid]:
    """The cases of ``make`` in one mode."""

    def part() -> Grid:
        whole = make()
        grid = Grid(whole.check)
        for case in whole.cases:
            if case["mode"] == mode:
                grid.cases.append(case)
                grid.labels.add(case["case"])
        return grid

    return part


#: One file per dialog and mode: Math and Copy have modes whose lists are long.
GRIDS: dict[str, Callable[[], Grid]] = {
    "math_decimal": only(math_grid, "decimal"),
    "math_hex": only(math_grid, "hex"),
    "math_sd": math_sd_grid,
    "copy_single": only(copy_grid, "single"),
    "copy_block": only(copy_grid, "block"),
    "copy_pack": only(copy_grid, "pack"),
    "copy_unpack": only(copy_grid, "unpack"),
    "copy_sd_single": copy_sd_single_grid,
    "copy_sd_block": copy_sd_block_grid,
    "out": out_grid,
    "out_sc": out_sc_grid,
}


def _lines(head: str, items: list[str], tail: str) -> str:
    return head + "\n" + ",\n".join(items) + "\n" + tail + "\n"


def render_cases(grid: Grid) -> str:
    """The grid file: one case per line."""
    items = ["  " + json.dumps(case, ensure_ascii=True) for case in grid.cases]
    return _lines('{\n "cases": [', items, " ]\n}")


def render_verdicts(grid: Grid) -> str:
    """The verdicts file: one verdict per line, keyed by the case's label."""
    items = [
        f"  {json.dumps(label, ensure_ascii=True)}: {json.dumps(v, ensure_ascii=True)}"
        for label, v in grid.verdicts().items()
    ]
    return _lines("{", items, "}")


def build() -> dict[str, str]:
    """Every file's name and text."""
    files: dict[str, str] = {}
    for name, make in GRIDS.items():
        grid = make()
        files[f"{name}.json"] = render_cases(grid)
        files[f"{name}.verdicts.json"] = render_verdicts(grid)
    return files


def counts() -> dict[str, int]:
    """The number of cases in each grid."""
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
