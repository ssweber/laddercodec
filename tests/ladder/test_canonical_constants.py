"""Every writer puts a Math or Copy constant in the form CLICK's dialog stores.

A constant typed another way that means the same (``1.50``, ``005``, ``0ffh``, ``$1``) is
built into CLICK's form where the instruction is built, so ``to_csv()``, ``write_csv`` and the
encoded blob all write that form, and a decoded save compares equal to the typed instruction.
"""

from __future__ import annotations

import csv
import warnings
from pathlib import Path

import pytest

from laddercodec import FieldError, Rung, decode, decode_program, encode, read_csv, write_csv
from laddercodec.csv import CSV_HEADER
from laddercodec.instructions.copy import Copy, Fill
from laddercodec.instructions.math import Math
from laddercodec.instructions.raw import _decompose_blob
from laddercodec.operands.unchecked import refusals

_COPY_SOURCE = 0x6074
_MATH_DISPLAY = 0x6228
_MATH_INTERNAL = 0x61FD

#: (typed source, destination, CLICK's form): CLICK's answers for a single Copy.
_COPY_ANSWERED = [
    ("005", "DS1", "5"),
    ("+5", "DS1", "+5"),
    ("+0", "DS1", "+0"),
    ("-0", "DS1", "0"),
    ("-005", "DS1", "-5"),
    ("0ffh", "DH1", "0FFh"),
    ("ffh", "DH1", "FFh"),
    ("ABCH", "DH1", "ABCh"),
    ("DH", "DH1", "Dh"),
    ("0FFFFh", "DH1", "0FFFFh"),
    ("10000h", "DD1", "10000h"),
    ("1.50", "DF1", "1.5"),
    ("1e3", "DF1", "1000.0"),
    (".5", "DF1", "0.5"),
    ("1E5", "DF1", "100000.0"),
    ("+1.5", "DS1", "1.5"),
    ("3.4028235E+38", "DS1", "3.402823E+38"),
    ("1E-45", "DS1", "1E-45"),
    ("1E-50", "DS1", "1E-50"),
    ("1.5e-3", "DS1", "0.0015"),
    ("70000", "DD1", "70000"),
    ("$1", "TXT1", "$01"),
    ("$41", "TXT1", "$41"),
]
#: The same rules on spellings CLICK was not asked about.
_COPY_DERIVED = [
    ("-007", "DS1", "-7"),
    ("-00", "DS1", "0"),
    ("+2.50", "DF1", "2.5"),
    ("3.40282355E+38", "DF1", "3.402823E+38"),
    ("0abch", "DD1", "0ABCh"),
    ('"AB"', "TXT1", '"AB"'),
]
_COPY = _COPY_ANSWERED + _COPY_DERIVED

#: (typed formula, mode, CLICK's display, CLICK's internal form): the constant forms of
#: CLICK's Math answers, in a formula; 1E3h is the form CLICK stores for a typed 1e3.
_MATH = [
    ("DS2 + 1.50", "decimal", "DS2 + 1.5", "DS2#+#F1.5"),
    ("DS2 + 1e3", "decimal", "DS2 + 1000.0", "DS2#+#F1000.0"),
    ("DS2 + .5", "decimal", "DS2 + 0.5", "DS2#+#F0.5"),
    ("DS2 + 1.5E+10", "decimal", "DS2 + 1.5E+10", "DS2#+#F1.5E+10"),
    ("DS2 + 6000000000", "decimal", "DS2 + 6000000000", "DS2#+#W6000000000"),
    ("DH2 + 0ffh", "hex", "DH2 + FFh", "DH2#+#UH255"),
    ("DH2 + 0000h", "hex", "DH2 + 0h", "DH2#+#UH0"),
    ("DH2 + 1E3h", "hex", "DH2 + 1E3h", "DH2#+#UH483"),
]


def _rung(instruction: object) -> Rung:
    return Rung(
        logical_rows=1,
        conditions=[["-"] * 31],
        instructions=[instruction],
        comment_rtf=None,
        comment=None,
    )


def _read_af(tmp_path: Path, af: str) -> object:
    path = tmp_path / "typed.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", "X001"] + ["-"] * 30 + [af])
    return read_csv(path)[0].instructions[0]


def _written_af(tmp_path: Path, instruction: object) -> str:
    path = tmp_path / "written.csv"
    write_csv(path, [_rung(instruction)])
    with path.open(newline="", encoding="utf-8") as f:
        rows = [row for row in csv.reader(f) if row and row[0] == "R"]
    return rows[0][-1]


def _fields(instruction: Copy | Math) -> dict[int, str]:
    return {tag: value for tag, _, value in _decompose_blob(instruction.build_blob())[4]}


@pytest.mark.parametrize(("typed", "destination", "stored"), _COPY)
def test_copy_source_every_writer_writes_clicks_form(
    tmp_path: Path, typed: str, destination: str, stored: str
) -> None:
    copy = Copy(typed, destination)
    assert copy.source == stored
    assert copy == Copy(stored, destination)
    assert copy.to_csv() == f"copy({stored},{destination})"
    assert _read_af(tmp_path, f"copy({typed},{destination})") == copy
    assert _written_af(tmp_path, copy) == f"copy({stored},{destination})"
    assert _fields(copy)[_COPY_SOURCE] == stored
    assert decode(encode(_rung(copy)))[0].instructions[0] == copy


@pytest.mark.parametrize(("typed", "mode", "display", "internal"), _MATH)
def test_math_constant_every_writer_writes_clicks_form(
    tmp_path: Path, typed: str, mode: str, display: str, internal: str
) -> None:
    result = "DH1" if mode == "hex" else "DF1"
    math = Math(typed, result, mode=mode)  # type: ignore[arg-type]
    assert math.expression == display
    assert math == Math(display, result, mode=mode)  # type: ignore[arg-type]
    csv_form = math.to_csv()
    assert display in csv_form
    assert _read_af(tmp_path, csv_form.replace(display, typed)) == math
    assert _written_af(tmp_path, math) == csv_form
    fields = _fields(math)
    assert fields[_MATH_DISPLAY] == display
    assert fields[_MATH_INTERNAL] == internal
    assert decode(encode(_rung(math)))[0].instructions[0] == math


_E_FIX = "write 0.0 for the real, or 14 for the value of hex E"
_1E_FIX = "write 1.0 for the real, or 30 for the value of hex 1E"


@pytest.mark.parametrize(
    ("source", "fix"),
    [
        ("EH", _E_FIX),
        ("eh", _E_FIX),
        ("Eh", _E_FIX),
        ("1Eh", _1E_FIX),
        ("1EH", _1E_FIX),
        ("1eh", _1E_FIX),
    ],
)
def test_copy_source_hex_word_read_as_a_real_is_refused(source: str, fix: str) -> None:
    # CLICK stores a Copy typed EH as the real 0.0 and 1Eh as 1.0, not as hex.
    with pytest.raises(FieldError, match=fix) as caught:
        Copy(source, "DH1")
    assert caught.value.field == "Copy.source"


def test_fill_keeps_its_value_as_typed() -> None:
    # Only a single Copy's source is written in CLICK's form; Fill is not part of this change.
    assert Fill("005", "DS1", "DS3").value == "005"


_SAVES = Path(__file__).parent.parent / "fixtures" / "scr_captures" / "constants"

#: (save, the instruction as typed, as CLICK stored it).
_SAVED = [
    ("math_hex_005", "math(005,DH1,mode=hex)", "math(5h,DH1,mode=hex)"),
    ("math_hex_0ffh", "math(0ffh,DH1,mode=hex)", "math(FFh,DH1,mode=hex)"),
    ("math_hex_1e3", "math(1e3,DH1,mode=hex)", "math(1E3h,DH1,mode=hex)"),
    ("math_hex_dh2_plus_1e3", "math(DH2 + 1e3,DH1,mode=hex)", "math(DH2 + 1E3h,DH1,mode=hex)"),
    ("math_hex_0000h", "math(0000h,DH1,mode=hex)", "math(0h,DH1,mode=hex)"),
    ("math_dec_1_50", "math(1.50,DF1,mode=decimal)", "math(1.5,DF1,mode=decimal)"),
    ("math_dec_1e3", "math(1e3,DF1,mode=decimal)", "math(1000.0,DF1,mode=decimal)"),
    ("math_dec_point_5", "math(.5,DF1,mode=decimal)", "math(0.5,DF1,mode=decimal)"),
    (
        "math_dec_6000000000",
        "math(6000000000,DF1,mode=decimal)",
        "math(6000000000,DF1,mode=decimal)",
    ),
    ("math_dec_1_5E10", "math(1.5E+10,DF1,mode=decimal)", "math(1.5E+10,DF1,mode=decimal)"),
    ("copy_005", "copy(005,DS1)", "copy(5,DS1)"),
    ("copy_plus_5", "copy(+5,DS1)", "copy(+5,DS1)"),
    ("copy_0ffh", "copy(0ffh,DS1)", "copy(0FFh,DS1)"),
    ("copy_1_50", "copy(1.50,DS1)", "copy(1.5,DS1)"),
    ("copy_1e3", "copy(1e3,DS1)", "copy(1000.0,DS1)"),
    ("copy_point_5", "copy(.5,DS1)", "copy(0.5,DS1)"),
    ("copy_1E5", "copy(1E5,DF1)", "copy(100000.0,DF1)"),
    ("copy_ABCH", "copy(ABCH,DH1)", "copy(ABCh,DH1)"),
    ("copy_DH", "copy(DH,DH1)", "copy(Dh,DH1)"),
    ("copy_EH", "copy(EH,DH1)", "copy(0.0,DH1)"),
    ("copy_dollar_1", "copy($1,TXT1)", "copy($01,TXT1)"),
]


#: The typed forms laddercodec refuses, though CLICK takes them: a hex Math constant needs
#: its h, and EH reads as hex E where CLICK stores the real 0.0.
_REFUSED_TYPED = {"math_hex_005", "math_hex_1e3", "math_hex_dh2_plus_1e3", "copy_EH"}


@pytest.mark.parametrize(("save", "typed", "stored"), _SAVED, ids=[s[0] for s in _SAVED])
def test_clicks_save_is_the_typed_instruction(
    tmp_path: Path, save: str, typed: str, stored: str
) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        program = decode_program((_SAVES / f"{save}.scr").read_bytes())
    decoded = next(i for i in program.rungs[0].instructions if isinstance(i, (Copy, Math)))
    assert refusals(decoded) == ()
    assert decoded.to_csv() == stored
    built = _read_af(tmp_path, stored)
    assert built == decoded
    # The blob laddercodec builds holds the text CLICK stored.
    assert _fields(built) == _fields(decoded)
    if save in _REFUSED_TYPED:
        with pytest.raises(FieldError):
            _read_af(tmp_path, typed)
    else:
        assert _read_af(tmp_path, typed) == decoded
