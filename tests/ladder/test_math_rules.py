"""Math field rules: CLICK v4.00 Help CL170 (decimal), CL203 (hex) and OBJ-10xx.

Each rule is checked through ``read_csv`` and direct construction; a refused blob decodes
as raw.
"""

from __future__ import annotations

import csv
import struct
from pathlib import Path

import pytest

from laddercodec import FieldError, decode, read_csv
from laddercodec.csv import CSV_HEADER
from laddercodec.instructions import from_tags_af, parse_af_blob
from laddercodec.instructions.math import Math
from laddercodec.instructions.raw import RawInstruction, _decompose_blob


def _read_af(tmp_path: Path, af: str) -> object:
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", "C1"] + ["-"] * 30 + [af])
    return read_csv(path)[0].instructions[0]


def _sum_of(n: int) -> str:
    return " + ".join(f"DS{i}" for i in range(1, n + 1))


_NINE_DEEP = "( " * 9 + "DS1" + " )" * 9

_REFUSED = [
    # result banks per mode (Q-M9): decimal DS, DD, DF, TD, CTD, SD; hex DH, YD
    ("DS1 + 1", "DH1", "decimal", "Math.result: 'DH1' is not allowed"),
    ("DS1 + 1", "YD1", "decimal", "Math.result: 'YD1' is not allowed"),
    ("DS1", "X001", "decimal", "Math.result: 'X001' is not allowed"),
    ("DS1", "C1", "decimal", "Math.result: 'C1' is not allowed"),
    ("DS1", "TXT1", "decimal", "Math.result: 'TXT1' is not allowed"),
    ("DS1", "XD1", "decimal", "Math.result: 'XD1' is not allowed"),
    ("DH1 + 1h", "DS9", "hex", "Math.result: 'DS9' is not allowed"),
    ("DH1 + 1h", "DD9", "hex", "Math.result: 'DD9' is not allowed"),
    ("DH1 + 1h", "XD1", "hex", "Math.result: 'XD1' is not allowed"),
    ("DS1", "DS4501", "decimal", "outside DS1-DS4500"),
    # constants (Q-M9, OBJ-1009): 32-bit integers, hex at most 4 digits and FFFFh
    ("DS1 + 3000000000", "DD9", "decimal", "3000000000 is outside -2147483648..2147483647"),
    ("DS1 + ( -3000000000 )", "DD9", "decimal", "-3000000000 is outside"),
    # a decimal integer must print back at its typed length (Inst_Math.dll)
    ("DS1 + 007", "DS9", "decimal", "007 is refused; CLICK reads it back as 7"),
    ("DS1 + ( -0 )", "DS9", "decimal", "-0 is refused; CLICK reads it back as 0"),
    ("DH1 + 10000h", "DH9", "hex", "10000h is outside 0h..FFFFh"),
    ("DH1 + 1FFFFh", "DH9", "hex", "1FFFFh is outside 0h..FFFFh"),
    ("DH1 + 0FFFFh", "DH9", "hex", "0FFFFh is outside 0h..FFFFh"),
    # a hex constant in a decimal Math (Q-M13, dialog 2026-11-12)
    ("DH1 + 1Eh", "DS9", "decimal", "1Eh is a hex constant; a decimal Math"),
    ("DS1 + 10000h", "DD9", "decimal", "10000h is a hex constant"),
    ("DS1 + ( -1Fh )", "DD9", "decimal", "-1Fh is a hex constant"),
    # a text constant in a formula, either mode (Q-M20, dialog 2026-11-12)
    ('DS1 + "A"', "DS9", "decimal", "holds a text constant"),
    ("DS1 + $41", "DS9", "decimal", "holds a text constant"),
    ('DH1 + "A"', "DH9", "hex", "holds a text constant"),
    ("DH1 + $41", "DH9", "hex", "holds a text constant"),
    # SUM takes no CT range (Q-M8, OBJ-1002)
    ("SUM ( CT1 : CT3 )", "DS9", "decimal", "SUM over CT1 is refused; SUM takes no CT range"),
    # parentheses: at most 8 deep (OBJ-1010), balanced (OBJ-1004, OBJ-1005)
    (_NINE_DEEP, "DS9", "decimal", "nests parentheses 9 deep; CLICK allows 8"),
    ("( DS1 + DS2", "DS9", "decimal", "has a '\\(' with no '\\)'"),
    ("DS1 + DS2 )", "DS9", "decimal", "has a '\\)' with no '\\('"),
    # keys only one keypad has (CL170, CL203)
    ("SIN ( DH1 )", "DH9", "hex", "SIN is decimal only"),
    ("ABS ( DH1 )", "DH9", "hex", "ABS is decimal only"),
    ("DH1 ^ DH2", "DH9", "hex", "\\^ is decimal only"),
    ("DS1 AND DS2", "DS9", "decimal", "AND is hex only"),
    ("LSH ( DS1 , 1 )", "DS9", "decimal", "LSH is hex only"),
    # a bit stands only in SUM over a bit range
    ("C1 + DS1", "DS9", "decimal", "C1 is a bit"),
    ("X001 + 1", "DS9", "decimal", "X001 is a bit"),
    ("MAX ( C1 : C5 )", "DS9", "decimal", "C1 is a bit"),
    # ranges: one bank (OBJ-1015), low : high (OBJ-1014), median <= 1024 bytes (OBJ-1013)
    ("SUM ( DS1 : DD5 )", "DD9", "decimal", "DS1 : DD5 spans two banks"),
    ("SUM ( DS10 : DS1 )", "DD9", "decimal", "DS10 : DS1 runs high to low"),
    ("MAX ( XD3 : XD0 )", "DH9", "hex", "XD3 : XD0 runs high to low"),
    ("MDN ( DS1 : DS513 )", "DS9", "decimal", "covers 1026 bytes; a median covers at most 1024"),
    ("MDN ( DD1 : DD257 )", "DD9", "decimal", "covers 1028 bytes"),
    # 270 characters of the internal template (Q-M7, OBJ-1008): DS1..DS69 is 273
    (_sum_of(69), "DD1", "decimal", "the formula is 273 characters in CLICK's internal form"),
    ("SIN ( DS1 ) + " * 23 + "PI", "DF1", "decimal", "is 278 characters"),
    # a formula is required: a Math blob with none decodes as raw
    ("", "DS9", "decimal", "Math.expression: the formula is empty"),
    ("   ", "DS9", "decimal", "Math.expression: the formula is empty"),
    ("", "DH9", "hex", "Math.expression: the formula is empty"),
]


#: An unclosed ``(`` already stops the CSV argument split, before Math is built.
_CSV_REFUSED = [r for r in _REFUSED if r[0] != "( DS1 + DS2"]


@pytest.mark.parametrize(("expression", "result", "mode", "message"), _CSV_REFUSED)
def test_refused_through_read_csv(
    tmp_path: Path, expression: str, result: str, mode: str, message: str
) -> None:
    with pytest.raises(FieldError, match=message):
        _read_af(tmp_path, f"math({expression},{result},mode={mode})")


@pytest.mark.parametrize(("expression", "result", "mode", "message"), _REFUSED)
def test_refused_on_construction(expression: str, result: str, mode: str, message: str) -> None:
    with pytest.raises(FieldError, match=message):
        Math(expression, result, mode=mode)  # type: ignore[arg-type]


def test_unknown_mode_refused() -> None:
    with pytest.raises(FieldError, match="Math.mode: 'fast'"):
        Math("DS1", "DS2", mode="fast")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("expression", "result", "mode"),
    [
        ("SUM ( C1 : C16 )", "DS9", "decimal"),
        # SUM over X, Y, T and SC, and MAX over TD and DS (Q-M8)
        ("SUM ( X001 : X036 )", "DS9", "decimal"),
        ("SUM ( Y001 : Y008 )", "DS9", "decimal"),
        ("SUM ( T1 : T5 )", "DS9", "decimal"),
        ("SUM ( SC1 : SC3 )", "DS9", "decimal"),
        ("SUM ( TD1 : TD3 )", "DS9", "decimal"),
        ("MAX ( TD1 : TD5 )", "DD9", "decimal"),
        ("MAX ( DS1 : DS3 )", "DS9", "decimal"),
        # result banks (Q-M9)
        ("DS1 + 1", "SD9", "decimal"),
        ("DH1 + 1h", "YD1", "hex"),
        ("DH1 + 1h", "YD0u", "hex"),
        # 32-bit integers and 4-digit hex constants (Q-M9)
        ("DS1 + 2147483647", "DD9", "decimal"),
        ("DS1 + ( -2147483648 )", "DD9", "decimal"),
        ("DH1 + FFFFh", "DH9", "hex"),
        # its low 32 bits print at the same length, so CLICK passes it
        ("DS1 + 6000000000", "DD9", "decimal"),
        ("DS1 + 0", "DS9", "decimal"),
        # a decimal integer in a hex Math is not ruled on yet (Q-M13b)
        ("DH1 + 1.5", "DH9", "hex"),
        ("SUM ( DS1 : DS1 )", "DS9", "decimal"),
        ("MAX ( XD0 : XD0u )", "DH9", "hex"),
        ("MDN ( DS1 : DS512 )", "DS9", "decimal"),
        ("MDN ( DD1 : DD256 )", "DD9", "decimal"),
        ("<a> + 1", "DS9", "decimal"),
        ("( " * 8 + "DS1" + " )" * 8, "DS9", "decimal"),
        ("ABS ( DS1 ) ^ 2 + PI", "DF9", "decimal"),
        ("LSH ( DH1 , 1h ) XOR DH2", "DH9", "hex"),
        (_sum_of(68), "DD1", "decimal"),
        # the shortest formulas
        ("1", "DS9", "decimal"),
        ("DH1", "DH9", "hex"),
    ],
)
def test_accepted(tmp_path: Path, expression: str, result: str, mode: str) -> None:
    parsed = _read_af(tmp_path, f"math({expression},{result},mode={mode})")
    assert isinstance(parsed, Math)
    assert parse_af_blob(parsed.build_blob()) == parsed


def test_longest_formula_fits_the_slots_and_matches_the_header() -> None:
    """The header field count is what the blob holds (S1); 68 operands is 269 characters."""
    blob = Math(_sum_of(68), "DD1").build_blob()
    header = struct.unpack_from("<I", blob, 16)[0]
    assert header == 1010
    assert len(_decompose_blob(blob)[4]) == header


@pytest.mark.parametrize(
    "fields",
    [
        {0x6065: "C1"},  # a bit result
        {0x11FE: "-1"},  # a hex Math into DS9
        {0x61FF: "SUM ( @ : @ )", 0x61FD: "SUM#(#CT1#:#CT3#)"},  # SUM over CT
        {0x61FF: "@ + 3000000000", 0x61FD: "DS1#+#W3000000000"},  # outside int32
        {0x61FF: "@ + 007", 0x61FD: "DS1#+#H007"},  # reads back as 7
        {0x61FF: "@ + 1Fh", 0x61FD: "DS1#+#1Fh"},  # hex constant in a decimal Math
        {0x61FF: '@ + "A"', 0x61FD: 'DS1#+#"A"'},  # text in a formula
        {0x61FF: " + ".join(["@"] * 69), 0x61FD: "#+#".join(f"DS{i}" for i in range(1, 70))},
    ],
)
def test_refused_blob_is_left_unparsed(fields: dict[int, str]) -> None:
    tags = {0x6065: "DS9", 0x61FF: "@ + @", 0x61FD: "DS1#+#DS2", 0x3218: "8451"}
    assert from_tags_af("Math", 0x271A, tags) is not None
    assert from_tags_af("Math", 0x271A, tags | fields) is None


def test_pasted_formula_over_the_cap_decodes_as_raw() -> None:
    """CLICK keeps a pasted 69-operand sum (273 characters) that its dialog refuses."""
    path = Path(__file__).parents[1] / "fixtures/v4_captures/retyped/math_wide.bin"
    rungs = decode(path.read_bytes())
    assert isinstance(rungs, list)
    by_name = {r.comment.split("\n")[0]: r for r in rungs if r.comment}
    assert isinstance(by_name["math_operands__ops_69"].instructions[0], RawInstruction)
    assert isinstance(by_name["math_operands__spacing_add"].instructions[0], Math)
