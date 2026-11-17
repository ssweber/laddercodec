"""Math field rules, decimal and hex, and OBJ-10xx.

Each rule is checked through ``read_csv`` and direct construction; a refused blob decodes
as raw.
"""

from __future__ import annotations

import csv
import struct
from pathlib import Path

import pytest

from laddercodec import FieldError, RefusedFieldWarning, Rung, decode, encode, read_csv
from laddercodec.csv import CSV_HEADER
from laddercodec.instructions import from_tags_af, parse_af_blob
from laddercodec.instructions.math import Math
from laddercodec.instructions.raw import _decompose_blob
from laddercodec.operands.unchecked import refusals
from tests.kept_refusals import kept


def _read_af_rung(tmp_path: Path, af: str) -> Rung:
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", "C1"] + ["-"] * 30 + [af])
    return read_csv(path)[0]


def _read_af(tmp_path: Path, af: str) -> object:
    return _read_af_rung(tmp_path, af).instructions[0]


def _sum_of(n: int) -> str:
    return " + ".join(f"DS{i}" for i in range(1, n + 1))


_NINE_DEEP = "( " * 9 + "DS1" + " )" * 9
_HEX_ONLY = "a hex Math takes only DH, XD and YD registers and hex constants \\(OBJ-1002\\)"
_DECIMAL_ONLY = (
    "a decimal Math takes only DS, DD, DF, TD, CTD and SD registers and decimal constants, "
    "and X, Y, C, T and SC bits only as the range of SUM \\( a : b \\) \\(OBJ-1002\\)"
)
_DECIMAL_RAND = "a decimal RAND bound is a DS or DD register or an integer constant"
_HEX_RAND = "a hex RAND bound is a DH register or a hex constant"
_COPY_DS = ": copy .* into a DS or DD register first \\(OBJ-1002\\)"
_COPY_DH = ": copy .* into a DH register first \\(OBJ-1002\\)"

_REFUSED = [
    # result banks per mode: decimal DS, DD, DF, TD, CTD, SD; hex DH, YD
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
    # constants (OBJ-1009): 32-bit integers, hex at most 4 digits and FFFFh
    ("DS1 + 3000000000", "DD9", "decimal", "3000000000 is outside -2147483648..2147483647"),
    ("DS1 + ( -3000000000 )", "DD9", "decimal", "-3000000000 is outside"),
    # a decimal integer must print back at its typed length
    ("DS1 + 007", "DS9", "decimal", "007 is refused; CLICK reads it back as 7"),
    ("DS1 + ( -0 )", "DS9", "decimal", "-0 is refused; CLICK reads it back as 0"),
    ("DH1 + 10000h", "DH9", "hex", "10000h is outside 0h..FFFFh"),
    ("DH1 + 1FFFFh", "DH9", "hex", "1FFFFh is outside 0h..FFFFh"),
    ("DH1 + 0FFFFh", "DH9", "hex", "0FFFFh is outside 0h..FFFFh"),
    ("DH1 + 10000H", "DH9", "hex", "10000h is outside 0h..FFFFh"),
    # a hex constant in a decimal Math, H as h
    ("DH1 + 1Eh", "DS9", "decimal", "1Eh is a hex constant; a decimal Math"),
    ("DS1 + 10000h", "DD9", "decimal", "10000h is a hex constant"),
    ("DS1 + ( -1Fh )", "DD9", "decimal", "1Fh is a hex constant"),
    ("DS1 + 1FH", "DS9", "decimal", "1Fh is a hex constant; a decimal Math"),
    ("DS1 + ( -1FH )", "DD9", "decimal", "1Fh is a hex constant"),
    # a decimal constant in a hex Math
    ("DH1 + 70000", "DH9", "hex", "70000 is a decimal constant; a hex Math"),
    ("DH1 + 1.5", "DH9", "hex", "1.5 is a decimal constant"),
    # hex digits without h: CLICK reads them as hex; the message names the h form
    ("DH1 + 7", "DH9", "hex", "7 has no h; .* write 7h"),
    ("DH1 + 007", "DH9", "hex", "007 has no h; .* write 7h"),
    ("DH1 + 1E5", "DH9", "hex", "1E5 has no h; .* write 1E5h"),
    ("DH1 + ( -5 )", "DH9", "hex", "-5 has no h; .* write -5h"),
    ("DH1 + FF", "DH9", "hex", "FF has no h; .* write FFh"),
    ("LSH ( DH1 , 1 )", "DH9", "hex", "1 has no h; .* write 1h"),
    ("RAND ( 1 , 10 )", "DH9", "hex", "1 has no h; .* write 1h"),
    # a text constant in a formula, either mode
    ('DS1 + "A"', "DS9", "decimal", "holds a text constant"),
    ("DS1 + $41", "DS9", "decimal", "holds a text constant"),
    ('DH1 + "A"', "DH9", "hex", "holds a text constant"),
    ("DH1 + $41", "DH9", "hex", "holds a text constant"),
    # a decimal formula takes DS, DD, DF, TD, CTD and SD, and X, Y, C, T and SC only as the
    # range of a SUM (OBJ-1002)
    (
        "SUM ( CT1 : CT3 )",
        "DS9",
        "decimal",
        "SUM \\( CT1 : CT3 \\) is refused for CT1; " + _DECIMAL_ONLY,
    ),
    (
        "SUM ( DH1 : DH3 )",
        "DS9",
        "decimal",
        "SUM \\( DH1 : DH3 \\) is refused for DH1; " + _DECIMAL_ONLY,
    ),
    (
        "SUM ( XD0 : XD1 )",
        "DS9",
        "decimal",
        "SUM \\( XD0 : XD1 \\) is refused for XD0; " + _DECIMAL_ONLY,
    ),
    (
        "SUM ( TXT1 : TXT3 )",
        "DS9",
        "decimal",
        "SUM \\( TXT1 : TXT3 \\) is refused for TXT1; " + _DECIMAL_ONLY,
    ),
    ("DS1 + DH1", "DS9", "decimal", "DH1 is refused; " + _DECIMAL_ONLY),
    ("DS1 + XD0", "DS9", "decimal", "XD0 is refused; " + _DECIMAL_ONLY),
    ("DS1 + YD0u", "DS9", "decimal", "YD0u is refused; " + _DECIMAL_ONLY),
    ("DS1 + TXT1", "DS9", "decimal", "TXT1 is refused; " + _DECIMAL_ONLY),
    ("RAND ( DH1 , 10 )", "DS9", "decimal", "DH1 is refused"),
    ("MAX ( TXT1 : TXT3 )", "DS9", "decimal", "TXT1 is refused"),
    # parentheses: at most 8 deep (OBJ-1010), balanced (OBJ-1004, OBJ-1005)
    (_NINE_DEEP, "DS9", "decimal", "nests parentheses 9 deep; CLICK allows 8"),
    ("( DS1 + DS2", "DS9", "decimal", "has a '\\(' with no '\\)'"),
    ("DS1 + DS2 )", "DS9", "decimal", "has a '\\)' with no '\\('"),
    # keys only one keypad has
    ("SIN ( DH1 )", "DH9", "hex", "SIN is decimal only"),
    ("ABS ( DH1 )", "DH9", "hex", "ABS is decimal only"),
    ("DH1 ^ DH2", "DH9", "hex", "\\^ is decimal only"),
    ("DS1 AND DS2", "DS9", "decimal", "AND is hex only"),
    ("LSH ( DS1 , 1 )", "DS9", "decimal", "LSH is hex only"),
    # a decimal formula takes X, Y, C, T and SC bits only as the range of a SUM
    ("C1 + DS1", "DS9", "decimal", "C1 is refused; " + _DECIMAL_ONLY),
    ("X001 + 1", "DS9", "decimal", "X001 is refused; " + _DECIMAL_ONLY),
    ("MAX ( C1 : C5 )", "DS9", "decimal", "C1 is refused; " + _DECIMAL_ONLY),
    # a hex formula takes only DH, XD and YD registers, in a SUM too (OBJ-1002)
    (
        "SUM ( X001 : X002 )",
        "DH9",
        "hex",
        "SUM \\( X001 : X002 \\) is refused for X001; " + _HEX_ONLY,
    ),
    ("SUM ( C1 : C16 )", "DH9", "hex", "SUM \\( C1 : C16 \\) is refused for C1; " + _HEX_ONLY),
    ("SUM ( CT1 : CT3 )", "DH9", "hex", "SUM \\( CT1 : CT3 \\) is refused for CT1; " + _HEX_ONLY),
    ("SUM ( DS1 : DS3 )", "DH9", "hex", "SUM \\( DS1 : DS3 \\) is refused for DS1; " + _HEX_ONLY),
    (
        "SUM ( TXT1 : TXT3 )",
        "DH9",
        "hex",
        "SUM \\( TXT1 : TXT3 \\) is refused for TXT1; " + _HEX_ONLY,
    ),
    ("DH1 + C1", "DH9", "hex", "C1 is refused; " + _HEX_ONLY),
    ("DS1 + 1h", "DH9", "hex", "DS1 is refused; " + _HEX_ONLY),
    ("DD1 + 1h", "DH9", "hex", "DD1 is refused; " + _HEX_ONLY),
    ("DF1 + 1h", "DH9", "hex", "DF1 is refused; " + _HEX_ONLY),
    ("TD1 + 1h", "DH9", "hex", "TD1 is refused; " + _HEX_ONLY),
    ("CTD1 + 1h", "DH9", "hex", "CTD1 is refused; " + _HEX_ONLY),
    ("SD1 + 1h", "DH9", "hex", "SD1 is refused; " + _HEX_ONLY),
    ("TXT1 + 1h", "DH9", "hex", "TXT1 is refused; " + _HEX_ONLY),
    ("RAND ( DS1 , Ah )", "DH9", "hex", "DS1 is refused"),
    ("MAX ( DD1 : DD3 )", "DH9", "hex", "DD1 is refused"),
    ("LSH ( DS1 , 1h )", "DH9", "hex", "DS1 is refused"),
    # a RAND bound: a DS or DD register or an integer in decimal, a DH register or a hex
    # constant in hex (OBJ-1002 for a bank); no real bound and no equal bounds (OBJ-1001)
    ("RAND ( DF1 , 10 )", "DS9", "decimal", "DF1 is refused; " + _DECIMAL_RAND + _COPY_DS),
    ("RAND ( 1 , TD500 )", "DS9", "decimal", "TD500 is refused; " + _DECIMAL_RAND + _COPY_DS),
    ("RAND ( CTD1 , 10 )", "DS9", "decimal", "CTD1 is refused; " + _DECIMAL_RAND + _COPY_DS),
    ("RAND ( 1 , SD1 )", "DS9", "decimal", "SD1 is refused; " + _DECIMAL_RAND + _COPY_DS),
    ("RAND ( X001 , 10 )", "DS9", "decimal", "X001 is refused; " + _DECIMAL_RAND + " \\(OBJ"),
    ("RAND ( 1 , DH1 )", "DS9", "decimal", "DH1 is refused; " + _DECIMAL_RAND + " \\(OBJ"),
    ("RAND ( 1.5 , 10 )", "DS9", "decimal", "1.5 is a real constant; " + _DECIMAL_RAND),
    ("RAND ( 1 , 1e3 )", "DS9", "decimal", "1000.0 is a real constant; " + _DECIMAL_RAND),
    ("RAND ( 1 , 1 )", "DS9", "decimal", "RAND \\( 1 , 1 \\) has equal bounds; RAND takes"),
    ("RAND ( DS1 , ds1 )", "DS9", "decimal", "RAND \\( DS1 , DS1 \\) has equal bounds"),
    ("RAND ( 1h , 01h )", "DH9", "hex", "RAND \\( 1h , 1h \\) has equal bounds"),
    ("RAND ( DH1 , DH1 )", "DH9", "hex", "RAND \\( DH1 , DH1 \\) has equal bounds"),
    ("RAND ( XD0 , Ah )", "DH9", "hex", "XD0 is refused; " + _HEX_RAND + _COPY_DH),
    ("RAND ( 1h , YD0u )", "DH9", "hex", "YD0u is refused; " + _HEX_RAND + _COPY_DH),
    ("RAND ( 1h , DS1 )", "DH9", "hex", "DS1 is refused; " + _HEX_RAND + " \\(OBJ"),
    # a decimal result in SD is a writable SD register (OBJ-003)
    ("DS1 + 1", "SD1", "decimal", "Math.result: 'SD1' is not a writable SD register"),
    ("DS1 + 1", "SD62", "decimal", "Math.result: 'SD62' is not a writable SD register"),
    ("DS1 + 1", "SD148", "decimal", "Math.result: 'SD148' is not a writable SD"),
    ("DS1 + 1", "SD216", "decimal", "Math.result: 'SD216' is not a writable SD"),
    ("DS1 + 1", "SD1000", "decimal", "Math.result: 'SD1000' is not a writable SD"),
    # ranges: one bank (OBJ-1015), low : high (OBJ-1014), median <= 1024 bytes (OBJ-1013)
    ("SUM ( DS1 : DD5 )", "DD9", "decimal", "DS1 : DD5 spans two banks"),
    ("SUM ( DS10 : DS1 )", "DD9", "decimal", "DS10 : DS1 runs high to low"),
    ("MAX ( XD3 : XD0 )", "DH9", "hex", "XD3 : XD0 runs high to low"),
    ("MDN ( DS1 : DS513 )", "DS9", "decimal", "covers 1026 bytes; a median covers at most 1024"),
    ("MDN ( DD1 : DD257 )", "DD9", "decimal", "covers 1028 bytes"),
    # an X/Y range with an end in the option slot, 21-36, but not from the CPU slot to 21,
    # of one point, or of two points numbered one apart (X036 : X101 is refused)
    (
        "SUM ( X001 : X036 )",
        "DS9",
        "decimal",
        "Math.expression: SUM \\( X001 : X036 \\) is refused: X036 is in the "
        "option slot \\(X021-X036\\), and CLICK sums the wrong bits for this range\\.",
    ),
    (
        "SUM ( Y016 : Y022 )",
        "DS9",
        "decimal",
        "SUM \\( Y016 : Y022 \\) is refused: Y022 is in the option slot \\(Y021-Y036\\), and "
        "CLICK sums the wrong bits for this range\\.",
    ),
    ("SUM ( Y001 : Y036 )", "DS9", "decimal", "refused: Y036 is in the option slot"),
    ("SUM ( X021 : X116 )", "DS9", "decimal", "refused: X021 is in the option slot"),
    (
        "SUM ( X025 : X036 )",
        "DS9",
        "decimal",
        "SUM \\( X025 : X036 \\) is refused: X025 and X036 are in the option slot",
    ),
    ("SUM ( X036 : X101 )", "DS9", "decimal", "SUM \\( X036 : X101 \\) is refused"),
    ("SUM ( X016 : X022 )", "DS9", "decimal", "SUM \\( X016 : X022 \\) is refused"),
    ("SUM ( Y021 : Y023 )", "DS9", "decimal", "SUM \\( Y021 : Y023 \\) is refused"),
    ("DS1 + SUM ( X1 : X36 )", "DS9", "decimal", "SUM \\( X001 : X036 \\) is refused"),
    # 270 characters of the internal template (OBJ-1008): DS1..DS69 is 273
    (_sum_of(69), "DD1", "decimal", "the formula is 273 characters in CLICK's internal form"),
    ("SIN ( DS1 ) + " * 23 + "PI", "DF1", "decimal", "is 278 characters"),
    # a formula is required: a Math blob with none decodes as raw
    ("", "DS9", "decimal", "Math.expression: is blank"),
    ("   ", "DS9", "decimal", "Math.expression: is blank"),
    ("", "DH9", "hex", "Math.expression: is blank"),
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
        # SUM over X, Y, T and SC, and MAX over TD and DS
        ("SUM ( X001 : X101 )", "DS9", "decimal"),
        ("SUM ( Y001 : Y008 )", "DS9", "decimal"),
        # an X/Y range with no end in the option slot, from the CPU slot to 21, of one point,
        # or of two points numbered one apart (X001 : X116, X001 : X021 and X025 : X026
        # captured)
        ("SUM ( X001 : X116 )", "DS9", "decimal"),
        ("SUM ( X001 : X021 )", "DS9", "decimal"),
        ("SUM ( Y016 : Y021 )", "DS9", "decimal"),
        ("SUM ( Y101 : Y201 )", "DS9", "decimal"),
        ("SUM ( X025 : X026 )", "DS9", "decimal"),
        ("SUM ( Y035 : Y036 )", "DS9", "decimal"),
        ("SUM ( X021 : X021 )", "DS9", "decimal"),
        ("SUM ( X036 : X036 )", "DS9", "decimal"),
        ("SUM ( T1 : T5 )", "DS9", "decimal"),
        ("SUM ( SC1 : SC3 )", "DS9", "decimal"),
        ("SUM ( TD1 : TD3 )", "DS9", "decimal"),
        ("MAX ( TD1 : TD5 )", "DD9", "decimal"),
        ("MAX ( DS1 : DS3 )", "DS9", "decimal"),
        # the decimal registers: DS, DD, DF, TD, CTD and SD
        ("DS1 + DD1 + DF1 + TD1 + CTD1 + SD1 + SUM ( CTD1 : CTD3 )", "DF9", "decimal"),
        # result banks
        ("DS1 + 1", "SD29", "decimal"),
        ("DS1 + 1", "SD215", "decimal"),
        ("DH1 + 1h", "YD1", "hex"),
        ("DH1 + 1h", "YD0u", "hex"),
        # 32-bit integers and 4-digit hex constants
        ("DS1 + 2147483647", "DD9", "decimal"),
        ("DS1 + ( -2147483648 )", "DD9", "decimal"),
        ("DH1 + FFFFh", "DH9", "hex"),
        ("DH1 + FFFFH", "DH9", "hex"),
        # its low 32 bits print at the same length, so CLICK passes it
        ("DS1 + 6000000000", "DD9", "decimal"),
        ("DS1 + 0", "DS9", "decimal"),
        ("SUM ( DS1 : DS1 )", "DS9", "decimal"),
        ("MAX ( XD0 : XD0u )", "DH9", "hex"),
        # the hex registers: DH, XD and YD
        ("SUM ( DH1 : DH3 ) + XD0 + YD0u", "DH9", "hex"),
        ("MDN ( DS1 : DS512 )", "DS9", "decimal"),
        ("MDN ( DD1 : DD256 )", "DD9", "decimal"),
        ("( " * 8 + "DS1" + " )" * 8, "DS9", "decimal"),
        ("ABS ( DS1 ) ^ 2 + PI", "DF9", "decimal"),
        ("LSH ( DH1 , 1h ) XOR DH2", "DH9", "hex"),
        # RAND bounds: DS, DD and integers in decimal, DH and hex constants in hex, reversed
        # too; equal bounds are the same text, so 1 and +1 differ
        ("RAND ( DS1 , DD1000 )", "DS9", "decimal"),
        ("RAND ( -5 , 2147483647 )", "DD9", "decimal"),
        ("RAND ( 10 , 1 )", "DS9", "decimal"),
        ("RAND ( 1 , +1 )", "DS9", "decimal"),
        ("DF1 + RAND ( DS1 , 10 )", "DF9", "decimal"),
        ("RAND ( DH500 , FFFFh )", "DH9", "hex"),
        ("RAND ( Ah , 1h ) + XD0", "DH9", "hex"),
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
    ("fields", "field"),
    [
        ({0x6065: "C1"}, "Math.result"),  # a bit result
        ({0x6065: "SD62"}, "Math.result"),  # an SD that is not writable
        ({0x11FE: "-1", 0x6065: "DH9", 0x61FD: "DS1#+#DH2"}, "Math.expression"),  # hex DS
        ({0x11FE: "-1", 0x61FD: "DH1#+#DH2"}, "Math.result"),  # a hex Math into DS9
        ({0x61FF: "SUM ( @ : @ )", 0x61FD: "SUM#(#CT1#:#CT3#)"}, "Math.expression"),  # CT
        ({0x61FF: "@ + 3000000000", 0x61FD: "DS1#+#W3000000000"}, "Math.expression"),  # int32
        ({0x61FF: "@ + 007", 0x61FD: "DS1#+#H007"}, "Math.expression"),  # reads back as 7
        ({0x61FF: "@ + 1Fh", 0x61FD: "DS1#+#1Fh"}, "Math.expression"),  # hex in a decimal Math
        ({0x61FF: "@ + 1FH", 0x61FD: "DS1#+#1FH"}, "Math.expression"),
        ({0x61FF: '@ + "A"', 0x61FD: 'DS1#+#"A"'}, "Math.expression"),  # text in a formula
        (
            {0x61FF: " + ".join(["@"] * 69), 0x61FD: "#+#".join(f"DS{i}" for i in range(1, 70))},
            "Math.expression",
        ),
    ],
)
def test_refused_blob_keeps_its_refusal(fields: dict[int, str], field: str) -> None:
    tags = {0x6065: "DS9", 0x61FF: "@ + @", 0x61FD: "DS1#+#DS2", 0x3218: "8451"}
    assert kept(from_tags_af("Math", 0x271A, tags)) is not None
    math = from_tags_af("Math", 0x271A, tags | fields)
    assert isinstance(math, Math)
    assert [error.field for error in refusals(math)] == [field]


@pytest.mark.parametrize(
    ("typed", "display"), [("0H", "0h"), ("00h", "0h"), ("0FFFh", "FFFh"), ("0fH", "Fh")]
)
def test_hex_constant_drops_leading_zeros(typed: str, display: str) -> None:
    assert Math(f"DH1 + {typed}", "DH9", "hex").expression == f"DH1 + {display}"


def test_hex_constant_digit_limit_counts_typed_zeros() -> None:
    """CLICK refuses ``0FFFEh`` (5 digits typed), though its value fits 4."""
    with pytest.raises(FieldError, match="0FFFEh is outside 0h..FFFFh"):
        Math("DH1 + 0FFFEh", "DH9", "hex")


@pytest.mark.parametrize(
    "expression", ["DS1 + FOO", "DS1 + DS1X", "DH1 + 7H7", "DS1 + _x", "DS1 + _", "DS1 + __"]
)
def test_math_refuses_a_word_that_is_no_name(expression: str) -> None:
    mode = "hex" if expression.startswith("DH") else "decimal"
    with pytest.raises(FieldError, match="Math.expression: '.*' is not an address"):
        Math(expression, "DH9" if mode == "hex" else "DS9", mode)


@pytest.mark.parametrize(
    ("expression", "result", "mode"),
    [
        ("XD0u + 1h", "DH9", "hex"),
        ("PI * SQRT ( DF1 )", "DF9", "decimal"),
        ("SUM ( DS1 : DS9 ) MOD 3", "DS9", "decimal"),
        ("SD1 + CTD1 + TD1 + DD1 + DF1", "DS9", "decimal"),
        ("LRO ( DH1 , 1h ) XOR RRO ( DH2 , 1h )", "DH9", "hex"),
    ],
)
def test_math_keeps_its_words(expression: str, result: str, mode: str) -> None:
    Math(expression, result, mode)


@pytest.mark.parametrize(
    ("expression", "result", "mode", "click_id"),
    [
        ("SUM ( X001 : X002 )", "DH9", "hex", "OBJ-1002"),
        ("DS1 + 1h", "DH9", "hex", "OBJ-1002"),
        ("DS1 + 1", "SD62", "decimal", "OBJ-003"),
        ("DS1 + 1", "SD148", "decimal", "OBJ-003"),
        ("DS1 + 1", "SD999", "decimal", "OBJ-003"),
    ],
)
def test_hex_formula_and_sd_result_refusals_carry_clicks_id(
    expression: str, result: str, mode: str, click_id: str
) -> None:
    with pytest.raises(FieldError) as caught:
        Math(expression, result, mode=mode)  # type: ignore[arg-type]
    assert caught.value.click_id == click_id
    assert caught.value.reason == ("not_writable" if result.startswith("SD") else "bank")


def test_hex_formula_takes_dh_and_decimal_sum_takes_bits() -> None:
    assert Math("SUM ( DH1 : DH3 ) + DH4", "DH9", "hex").expression == "SUM ( DH1 : DH3 ) + DH4"
    assert Math("SUM ( X001 : X002 )", "DS9", "decimal").expression == "SUM ( X001 : X002 )"


def test_pasted_formula_over_the_cap_keeps_its_refusal() -> None:
    """CLICK keeps a pasted 69-operand sum (273 characters) that its dialog refuses."""
    path = Path(__file__).parents[1] / "fixtures/v4_captures/retyped/math_wide.bin"
    with pytest.warns(RefusedFieldWarning, match="CLICK allows 270"):
        rungs = decode(path.read_bytes())
    assert isinstance(rungs, list)
    by_name = {r.comment.split("\n")[0]: r for r in rungs if r.comment}
    wide = by_name["math_operands__ops_69"].instructions[0]
    assert isinstance(wide, Math) and wide.expression == " + ".join(
        f"DS{i}" for i in range(401, 470)
    )
    kept(wide, "Math.expression")
    assert isinstance(by_name["math_operands__spacing_add"].instructions[0], Math)


#: A RAND CLICK's dialog takes, the same-length edits of its stored text that make one it
#: refuses, and the refusal: (formula, result, mode, edits, message).
_STORED_RAND = [
    ("RAND ( DD1 , 10 )", "DS9", "decimal", [("DD1", "DF1")], "DF1 is refused"),
    ("RAND ( DH1 , Ah )", "DH9", "hex", [("DH1", "XD1")], "XD1 is refused"),
    ("RAND ( DS1 , DS2 )", "DD9", "decimal", [("DS2", "DS1")], "has equal bounds"),
    ("RAND ( DH1 , DH2 )", "DH9", "hex", [("DH2", "DH1")], "has equal bounds"),
    (
        "RAND ( 1 , 1000 )",
        "DS9",
        "decimal",
        [("H1000", "F10.5"), ("1000", "10.5")],
        "10.5 is a real constant",
    ),
]


@pytest.mark.parametrize(
    ("expression", "result", "mode", "edits", "message"),
    _STORED_RAND,
    ids=[case[3][0][1] for case in _STORED_RAND],
)
def test_a_stored_rand_its_dialog_refuses_decodes_and_writes_its_bytes(
    tmp_path: Path,
    expression: str,
    result: str,
    mode: str,
    edits: list[tuple[str, str]],
    message: str,
) -> None:
    rung = _read_af_rung(tmp_path, f"math({expression},{result},mode={mode})")
    data = encode(rung)
    for old, new in edits:
        assert old.encode("utf-16-le") in data, old
        data = data.replace(old.encode("utf-16-le"), new.encode("utf-16-le"))
    with pytest.warns(RefusedFieldWarning, match=message):
        [decoded] = decode(data)
    assert isinstance(decoded, Rung)
    [math] = decoded.instructions
    assert isinstance(math, Math)
    kept(math, "Math.expression")
    assert encode(decoded) == data


def test_a_stored_real_above_the_largest_float32_decodes_and_writes_its_bytes(
    tmp_path: Path,
) -> None:
    """CLICK's Math dialog refuses 3.4028235E+38 (OBJ-1009); a Math stored with it decodes
    as that Math, keeping the refusal, and encodes its bytes unchanged."""
    rung = _read_af_rung(tmp_path, "math(DF1 * 3.4028234E+38,DF9,mode=decimal)")
    data = encode(rung)
    old, new = "3.4028234E+38".encode("utf-16-le"), "3.4028235E+38".encode("utf-16-le")
    assert data.count(old) == 4  # the display formula, the template and both internal forms
    data = data.replace(old, new)
    with pytest.warns(RefusedFieldWarning, match=r"3\.4028235E\+38 is outside the float32 range"):
        [decoded] = decode(data)
    assert isinstance(decoded, Rung)
    [math] = decoded.instructions
    assert isinstance(math, Math) and math.expression == "DF1 * 3.4028235E+38"
    kept(math, "Math.expression")
    assert refusals(math)[0].click_id == "OBJ-1009"
    assert encode(decoded) == data
