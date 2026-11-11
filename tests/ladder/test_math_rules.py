"""Math field rules: CLICK v4.00 Help CL170 (decimal), CL203 (hex) and OBJ-10xx.

Each rule is checked through ``read_csv`` and direct construction; a refused blob decodes
as raw.
"""

from __future__ import annotations

import csv
import struct
from pathlib import Path

import pytest

from laddercodec import FieldError, read_csv
from laddercodec.csv import CSV_HEADER
from laddercodec.instructions import from_tags_af, parse_af_blob
from laddercodec.instructions.math import Math
from laddercodec.instructions.raw import _decompose_blob


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
    # result banks; DH only in hex mode
    ("DS1 + 1", "DH1", "decimal", "Math.result: 'DH1' is not allowed"),
    ("DS1", "X001", "decimal", "Math.result: 'X001' is not allowed"),
    ("DS1", "C1", "decimal", "Math.result: 'C1' is not allowed"),
    ("DS1", "SD1", "decimal", "Math.result: 'SD1' is not allowed"),
    ("DS1", "TXT1", "decimal", "Math.result: 'TXT1' is not allowed"),
    ("DH1", "YD1", "hex", "Math.result: 'YD1' is not allowed"),
    ("DS1", "DS4501", "decimal", "outside DS1-DS4500"),
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
    # the blob has 500 operand slots
    (_sum_of(501), "DD1", "decimal", "501 operands; the Math blob holds at most 500"),
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
        # range aggregate banks wait on a dialog check: kept as before
        ("SUM ( X001 : X036 )", "DS9", "decimal"),
        ("SUM ( T1 : T5 )", "DS9", "decimal"),
        ("MAX ( TD1 : TD5 )", "DD9", "decimal"),
        # a hex result into DS or DD waits on a dialog check
        ("DH1 + 1h", "DS9", "hex"),
        ("DH1 + 1h", "DD9", "hex"),
        # constants in the other mode are not refused
        ("DH1 + 1Eh", "DS9", "decimal"),
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
    ],
)
def test_accepted(tmp_path: Path, expression: str, result: str, mode: str) -> None:
    parsed = _read_af(tmp_path, f"math({expression},{result},mode={mode})")
    assert isinstance(parsed, Math)
    assert parse_af_blob(parsed.build_blob()) == parsed


def test_500_operands_fill_the_slots_and_match_the_header() -> None:
    """The header field count is what the blob holds (S1)."""
    blob = Math(_sum_of(500), "DD1").build_blob()
    header = struct.unpack_from("<I", blob, 16)[0]
    assert header == 1010
    assert len(_decompose_blob(blob)[4]) == header


def test_refused_blob_is_left_unparsed() -> None:
    tags = {0x6065: "C1", 0x61FF: "@ + @", 0x61FD: "DS1#+#DS2", 0x3218: "8451"}
    assert from_tags_af("Math", 0x271A, tags) is None
