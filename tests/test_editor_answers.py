"""CLICK's answers to the editor grids, compared with laddercodec's rules.

``tests/fixtures/editor_grids/*.answers.json`` hold what CLICK's dialogs said to each case
(see that folder's README); they are never edited to fit the code.  Each answered case is
rebuilt here with the builders ``devtools/editor_grids.py`` uses and compared three ways:

- the outcome: CLICK accepted or refused, and so do the rules;
- the code: where both refuse and CLICK gave an ``OBJ-nnn``, the refusal's ``click_id`` is the
  same (a ``click_id`` of None is not a disagreement, and most refusals have none yet, so
  only some codes are compared: ``CODES_COMPARED`` is today's number, and a change that
  adds or drops ids changes it and fails); where one OK raised a chain of error boxes
  (``boxes``), ``code`` is the first;
- the save: an accepted case's ``stored`` rows read back with ``read_csv`` as an instruction
  that is not ``raw(...)``.

A case whose text is longer than its field's ``limits`` is skipped: the runner sets text by
WM_SETTEXT, which ignores the limit, so no user can type it.  The rule is the text length,
not the label.

``DISAGREEMENTS`` lists every difference, keyed by grid, case label and kind, with its reason
and the roadmap item that owns it.  The test fails on a difference not listed and on an entry
that no longer differs, as ``tests/test_operand_guards.py`` does for its allowlists.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from laddercodec.csv import read_csv
from laddercodec.instructions import parse_af_blob
from laddercodec.instructions.coil import Coil
from laddercodec.instructions.copy import BlockCopy, Copy, Pack, Unpack
from laddercodec.instructions.math import Math
from laddercodec.instructions.raw import RawInstruction
from laddercodec.instructions.send_receive import ModbusAddress, ModbusRtuTarget, Receive
from laddercodec.instructions.undecoded import Undecoded
from laddercodec.model import ADDRESS_BANKS, InstructionType

ROOT = Path(__file__).resolve().parent.parent
GRIDS = ROOT / "tests" / "fixtures" / "editor_grids"

#: The files of cases CLICK answered, in the order they are compared.
ANSWER_FILES = (
    "preflight",
    "risky",
    "receive",
    "receive_count",
    "pickcheck",
    "picker_lists",
    "rule_rows",
    "out",
    "copy_single",
    "copy_block",
    "copy_pack",
    "copy_unpack",
    "math_decimal",
    "math_hex",
)

Key = tuple[str, str, str]  # (grid, case label or field, kind)

HEX_WORD = (
    "kept: laddercodec asks for the h; CLICK reads a word of hex digits typed without it as a "
    "hex constant, so DH0 is D0h and 10 is 16 (settled)"
)
EDGE_SPACE = (
    "deliberate: CLICK accepts an edge space and the save trims it; an instruction holds the "
    "address in display form, so construction refuses the space"
)
EDGE_SPACE_KEPT = (
    "deliberate: CLICK accepts an edge space and the save keeps it; an instruction holds the "
    "address in display form, so construction refuses the space, and decode reads that save "
    "as the address without it"
)

# Math (roadmap item 3, except where marked).
RAND_BANK = (
    "to do: a RAND bound in a bank CLICK refuses there (DF, TD, CTD and SD in decimal, XD and "
    "YD in hex) is OBJ-1002; the rules accept it"
)
RAND_EQUAL = "to do: equal RAND bounds are OBJ-1001; the rules accept them"
RAND_REAL = "to do: a real RAND bound is OBJ-1001; the rules accept it"
FLOAT_EDGE = "to do: the constant 3.4028235E+38 in a Math is OBJ-1009; the rules accept it"
SUM_ORDER = (
    "to do: a SUM whose ends are reversed is OBJ-1014, over a bank the mode refuses too; the "
    "rules give OBJ-1002"
)
SUM_BLOCK = (
    "to do: a SUM whose ends are in two banks is OBJ-1015, where a bank is refused too; the "
    "rules give OBJ-1002"
)
HEX_RESULT_SD = (
    "to do: a hex Math result past SD's range (SD0, SD1001) is OBJ-004; the rules give OBJ-003"
)

# Copy (roadmap item 3, except where marked).
INNER_SPACE = (
    "to do: CLICK takes DS 1 (a space inside) as a Copy source or destination and as a Math "
    "result; the rules refuse it, and read_csv refuses the save that keeps it"
)
BLOCK_LOWERCASE = (
    "to do: CLICK takes a lowercase address (ds1) as a Block Copy's source and destination; "
    "the rules refuse it there"
)
SD_POINTER = (
    "to do: CLICK takes an SD pointer (SD[DS1]) as a Copy source and saves it as typed; the "
    "rules refuse it"
)
E_REAL = (
    "kept: laddercodec refuses; DS is an integer, so a real such as 0.0 or 1.0 is no source "
    "for a Copy into DS1, yet CLICK lets text that is not a number through as a real (E5 and "
    '"HELLO" are stored 0.0, 1E is 1.0); typing a valid constant can\'t make that rung, since '
    "0.0 into DS becomes 0 (settled)"
)
COPY_EH = (
    "kept: CLICK stores EH as the real 0.0; laddercodec refuses it and names the forms to write, "
    "0Eh for hex or 0.0 for the real (settled)"
)
TEXT_AS_REAL = (
    'to do (roadmap item 4): CLICK stores quoted text with an E ("HELLO") into TXT as its float '
    "value too (0.0, filling TXT1..TXT3); the rules accept it as text, and decode reads the "
    "save as raw(...)"
)
ASCII_SOURCE = (
    "to do: a $ code source ($41, $1) into a bank other than TXT is OBJ-004; the rules give OBJ-024"
)
SOURCE_VALUE = (
    'to do: an empty text ("") or a hex source of more than 8 digits into DS1 is OBJ-005; the '
    "rules give OBJ-024"
)
SD_PAIRING = (
    "to do: a bit, a text or 10000h into an SD it does not write (SD1) is OBJ-024, the pairing "
    "first; the rules give OBJ-004"
)
BIT_PAST_RANGE = (
    "to do: a DS into an X, T, CT or SC address past its bank's range is OBJ-004; the rules give "
    "OBJ-024"
)
PACK_TXT = "to do: a Pack of TXT into DH is OBJ-003; the rules accept it"
PACK_TWO_BOXES = (
    "to do: a Pack of 33 T, CT or SC bits into DS or DD shows OBJ-041 (the count), then "
    "OBJ-024; the rules give OBJ-024"
)
PACK_DH_COUNT = (
    "to do: a Pack of more than 2 DH into DH is OBJ-040 (the count); the rules give OBJ-024"
)
UNPACK_BANK_FIRST = (
    "to do: an Unpack into a bank its source can't unpack to is OBJ-004 before the range "
    "checks; the rules give OBJ-008, OBJ-009 or OBJ-012"
)
UNPACK_Y_PAIRING = (
    "to do: an Unpack of DS, DD or DF into Y is OBJ-024 before the range checks; the rules give "
    "OBJ-004, OBJ-009, OBJ-012 or OBJ-019"
)
UNPACK_Y_COUNT = "to do: an Unpack of DH into more than 16 Y is OBJ-1009; the rules give OBJ-019"

# Out (roadmap item 3).
OUT_ACROSS = (
    "to do: an Out range whose end is in another bank is OBJ-008, where that bank is refused "
    "too; the rules give OBJ-004"
)

# Saves decode reads as raw(...) (roadmap item 3).
TYPED_ADDRESS = (
    "to do: CLICK saves an address as typed (DS001, ds1, XD00, YD0U), not in display form, and "
    "decode reads it as raw(...)"
)
CONVERSION_7 = (
    "to do: a Copy between a real and a DD, CTD or DF register saves conversion type 7, which "
    "decode reads as raw(...)"
)
TXT_NUMBER = (
    "to do: a number into TXT saves the text CLICK prints, with its last TXT and a conversion "
    "type decode reads as raw(...)"
)


def _table(*groups: tuple[str, str, str, tuple[str, ...]]) -> dict[Key, str]:
    """One entry for each case of each group (reason, grid, kind, labels); a case in two
    groups fails."""
    table: dict[Key, str] = {}
    for reason, grid, kind, labels in groups:
        for label in labels:
            key = (grid, label, kind)
            if key in table:
                raise ValueError(f"{key} is listed twice")
            table[key] = reason
    return table


#: Every difference between CLICK's answers and the rules.  Kinds: ``outcome`` (accepted or
#: refused), ``code`` (the OBJ id), ``stored`` (the save reads back as raw), ``list`` (the
#: writable SC or SD addresses).  Each group is one thing to do (or one kept on purpose).
DISAGREEMENTS: dict[Key, str] = {
    ("receive", "03 -> TXT1", "outcome"): (
        "kept: the rx2 run recorded no count and the test takes 1, which CLICK refuses for TXT "
        "(OBJ-010); in the same setup the dialog holds 2 at OK (receive_count), which the rules "
        "accept; no answer says what rx2 held"
    ),
    ("risky", "dec  DS1 = DS2 + 1", "outcome"): EDGE_SPACE + " (Math result)",
    ("risky", "dec DS1  = DS2 + 1", "outcome"): EDGE_SPACE + " (Math result)",
    ("risky", "single  DS1 -> DS1", "outcome"): EDGE_SPACE + " (Copy source)",
    ("risky", "single DS1  -> DS1", "outcome"): EDGE_SPACE + " (Copy source)",
    ("risky", "single DS2 ->  DS1", "outcome"): EDGE_SPACE_KEPT + " (Copy destination)",
    ("risky", "single DS2 -> DS1 ", "outcome"): EDGE_SPACE_KEPT + " (Copy destination)",
    ("risky", "block  DS1..DS2 -> DS11", "outcome"): EDGE_SPACE + " (Block Copy source)",
    ("risky", "pack C1..C16 ->  DS1", "outcome"): EDGE_SPACE_KEPT + " (Pack destination)",
    ("risky", "unpack  DS1 -> C1..C16", "outcome"): EDGE_SPACE + " (Unpack source)",
    **_table(
        (
            HEX_WORD,
            "preflight",
            "outcome",
            (
                "hex DH1 = 0",
                "hex DH1 = DH1 + 0",
                "hex DH1 = RAND(5,Ah)",
            ),
        ),
        (
            HEX_WORD,
            "math_hex",
            "outcome",
            (
                "hex DH1 = +0",
                "hex DH1 = +5",
                "hex DH1 = -0",
                "hex DH1 = -005",
                "hex DH1 = -5",
                "hex DH1 = 0",
                "hex DH1 = 005",
                "hex DH1 = 1-2",
                "hex DH1 = 1E39",
                "hex DH1 = 1E5",
                "hex DH1 = 1e5",
                "hex DH1 = 5",
                "hex DH1 = C0",
                "hex DH1 = C0 + 1h",
                "hex DH1 = DD0",
                "hex DH1 = DD0 + 1h",
                "hex DH1 = DF0",
                "hex DH1 = DF0 + 1h",
                "hex DH1 = DH0",
                "hex DH1 = DH0 + 1h",
                "hex DH1 = DH1 + 0",
                "hex DH1 = DH1 + 005",
                "hex DH1 = DH1 + 1-2",
                "hex DH1 = DH1 + 1E39",
                "hex DH1 = DH1 + 1E5",
                "hex DH1 = DH1 + 1e5",
                "hex DH1 = DH1 + 5",
                "hex DH1 = DH1 + E5",
                "hex DH1 = DH1 + abc",
                "hex DH1 = DH501",
                "hex DH1 = DH501 + 1h",
                "hex DH1 = E5",
                "hex DH1 = RAND(1h,5)",
                "hex DH1 = RAND(1h,C0)",
                "hex DH1 = RAND(1h,DD0)",
                "hex DH1 = RAND(1h,DF0)",
                "hex DH1 = RAND(1h,DH0)",
                "hex DH1 = RAND(1h,DH501)",
                "hex DH1 = RAND(5,Ah)",
                "hex DH1 = RAND(C0,Ah)",
                "hex DH1 = RAND(DD0,Ah)",
                "hex DH1 = RAND(DF0,Ah)",
                "hex DH1 = RAND(DH0,Ah)",
                "hex DH1 = RAND(DH501,Ah)",
                "hex DH1 = abc",
            ),
        ),
        (
            RAND_BANK,
            "math_decimal",
            "outcome",
            (
                "dec DS1 = RAND(1,CTD1)",
                "dec DS1 = RAND(1,CTD250)",
                "dec DS1 = RAND(1,DF1)",
                "dec DS1 = RAND(1,DF500)",
                "dec DS1 = RAND(1,SD1)",
                "dec DS1 = RAND(1,SD1000)",
                "dec DS1 = RAND(1,TD1)",
                "dec DS1 = RAND(1,TD500)",
                "dec DS1 = RAND(CTD1,10)",
                "dec DS1 = RAND(CTD250,10)",
                "dec DS1 = RAND(DF1,10)",
                "dec DS1 = RAND(DF500,10)",
                "dec DS1 = RAND(SD1,10)",
                "dec DS1 = RAND(SD1000,10)",
                "dec DS1 = RAND(TD1,10)",
                "dec DS1 = RAND(TD500,10)",
            ),
        ),
        (
            RAND_BANK,
            "math_hex",
            "outcome",
            (
                "hex DH1 = RAND(1h,XD0)",
                "hex DH1 = RAND(1h,XD00)",
                "hex DH1 = RAND(1h,XD0U)",
                "hex DH1 = RAND(1h,XD0u)",
                "hex DH1 = RAND(1h,XD1)",
                "hex DH1 = RAND(1h,XD8)",
                "hex DH1 = RAND(1h,YD0)",
                "hex DH1 = RAND(1h,YD00)",
                "hex DH1 = RAND(1h,YD0U)",
                "hex DH1 = RAND(1h,YD0u)",
                "hex DH1 = RAND(1h,YD1)",
                "hex DH1 = RAND(1h,YD8)",
                "hex DH1 = RAND(XD0,Ah)",
                "hex DH1 = RAND(XD00,Ah)",
                "hex DH1 = RAND(XD0U,Ah)",
                "hex DH1 = RAND(XD0u,Ah)",
                "hex DH1 = RAND(XD1,Ah)",
                "hex DH1 = RAND(XD8,Ah)",
                "hex DH1 = RAND(YD0,Ah)",
                "hex DH1 = RAND(YD00,Ah)",
                "hex DH1 = RAND(YD0U,Ah)",
                "hex DH1 = RAND(YD0u,Ah)",
                "hex DH1 = RAND(YD1,Ah)",
                "hex DH1 = RAND(YD8,Ah)",
            ),
        ),
        (
            RAND_EQUAL,
            "math_decimal",
            "outcome",
            (
                "dec DS1 = RAND(1,1)",
                "dec DS1 = RAND(DS1,DS1)",
            ),
        ),
        (
            RAND_EQUAL,
            "math_hex",
            "outcome",
            (
                "hex DH1 = RAND(1h,1h)",
                "hex DH1 = RAND(DH1,DH1)",
            ),
        ),
        (
            RAND_REAL,
            "math_decimal",
            "outcome",
            (
                "dec DS1 = RAND(1,1.5)",
                "dec DS1 = RAND(1.5,10)",
            ),
        ),
        (
            FLOAT_EDGE,
            "math_decimal",
            "outcome",
            (
                "dec DS1 = 3.4028235E+38",
                "dec DS1 = DS1 + 3.4028235E+38",
            ),
        ),
        (
            SUM_ORDER,
            "math_decimal",
            "code",
            (
                "dec DS1 = SUM(CT2:CT1)",
                "dec DS1 = SUM(DH2:DH1)",
                "dec DS1 = SUM(TXT2:TXT1)",
                "dec DS1 = SUM(XD1:XD0)",
                "dec DS1 = SUM(YD1:YD0)",
            ),
        ),
        (
            SUM_ORDER,
            "math_hex",
            "code",
            (
                "hex DH1 = SUM(C2:C1)",
                "hex DH1 = SUM(CT2:CT1)",
                "hex DH1 = SUM(CTD2:CTD1)",
                "hex DH1 = SUM(DD2:DD1)",
                "hex DH1 = SUM(DF2:DF1)",
                "hex DH1 = SUM(DS2:DS1)",
                "hex DH1 = SUM(SC2:SC1)",
                "hex DH1 = SUM(SD2:SD1)",
                "hex DH1 = SUM(T2:T1)",
                "hex DH1 = SUM(TD2:TD1)",
                "hex DH1 = SUM(TXT2:TXT1)",
                "hex DH1 = SUM(X002:X001)",
                "hex DH1 = SUM(Y002:Y001)",
            ),
        ),
        (
            SUM_BLOCK,
            "math_decimal",
            "code",
            (
                "dec DS1 = SUM(C1:TXT2)",
                "dec DS1 = SUM(CT1:C2)",
                "dec DS1 = SUM(CT1:DS2)",
                "dec DS1 = SUM(CT1:TXT2)",
                "dec DS1 = SUM(CT1:X002)",
                "dec DS1 = SUM(CTD1:TXT2)",
                "dec DS1 = SUM(DD1:TXT2)",
                "dec DS1 = SUM(DF1:TXT2)",
                "dec DS1 = SUM(DH1:C2)",
                "dec DS1 = SUM(DH1:DS2)",
                "dec DS1 = SUM(DH1:TXT2)",
                "dec DS1 = SUM(DH1:X002)",
                "dec DS1 = SUM(DS1:TXT2)",
                "dec DS1 = SUM(SC1:TXT2)",
                "dec DS1 = SUM(SD1:TXT2)",
                "dec DS1 = SUM(T1:TXT2)",
                "dec DS1 = SUM(TD1:TXT2)",
                "dec DS1 = SUM(TXT1:C2)",
                "dec DS1 = SUM(TXT1:DS2)",
                "dec DS1 = SUM(TXT1:X002)",
                "dec DS1 = SUM(X001:TXT2)",
                "dec DS1 = SUM(XD0:C2)",
                "dec DS1 = SUM(XD0:DS2)",
                "dec DS1 = SUM(XD0:TXT2)",
                "dec DS1 = SUM(XD0:X002)",
                "dec DS1 = SUM(Y001:TXT2)",
                "dec DS1 = SUM(YD0:C2)",
                "dec DS1 = SUM(YD0:DS2)",
                "dec DS1 = SUM(YD0:TXT2)",
                "dec DS1 = SUM(YD0:X002)",
            ),
        ),
        (
            HEX_RESULT_SD,
            "math_hex",
            "code",
            (
                "hex SD0 = DH2 + DH3",
                "hex SD1001 = DH2 + DH3",
            ),
        ),
        (
            INNER_SPACE,
            "copy_single",
            "outcome",
            (
                "single DS 1 -> DS1",
                "single DS2 -> DS 1",
            ),
        ),
        (INNER_SPACE, "copy_single", "stored", ("single DS2 -> DS 1",)),
        (INNER_SPACE, "math_decimal", "outcome", ("dec DS 1 = DS2 + 1",)),
        (
            BLOCK_LOWERCASE,
            "copy_block",
            "outcome",
            (
                "block DS1..DS2 -> ds1",
                "block ds1..DS2 -> DS11",
            ),
        ),
        (SD_POINTER, "copy_single", "outcome", ("single SD[DS1] -> DS1",)),
        (SD_POINTER, "copy_single", "stored", ("single SD[DS1] -> DS1",)),
        (
            E_REAL,
            "copy_single",
            "outcome",
            (
                'single "1E5" -> DS1',
                'single "E" -> DS1',
                'single "HELLO" -> DS1',
                'single "e" -> DS1',
                "single 1E -> DS1",
                "single E5 -> DS1",
            ),
        ),
        (COPY_EH, "copy_single", "outcome", ("single EH -> DS1",)),
        (TEXT_AS_REAL, "copy_single", "stored", ('single "HELLO" -> TXT1',)),
        (
            ASCII_SOURCE,
            "copy_single",
            "code",
            (
                "single $00 -> DS1",
                "single $1 -> DS1",
                "single $0D -> DS1",
                "single $41 -> C1",
                "single $41 -> CT1",
                "single $41 -> CTD1",
                "single $41 -> CTD[DS1]",
                "single $41 -> C[DS1]",
                "single $41 -> DD1",
                "single $41 -> DD[DS1]",
                "single $41 -> DF1",
                "single $41 -> DF[DS1]",
                "single $41 -> DH1",
                "single $41 -> DH[DS1]",
                "single $41 -> DS1",
                "single $41 -> DS[DS1]",
                "single $41 -> SC1",
                "single $41 -> T1",
                "single $41 -> TD1",
                "single $41 -> TD[DS1]",
                "single $41 -> X001",
                "single $41 -> Y001",
                "single $41 -> YD0",
                "single $41 -> YD[DS1]",
                "single $FF -> DS1",
                "single $ff -> DS1",
            ),
        ),
        (
            SOURCE_VALUE,
            "copy_single",
            "code",
            (
                'single "" -> DS1',
                "single 0FFFFFFFFh -> DS1",
                "single 100000000h -> DS1",
                "single FFFFFFFFFh -> DS1",
            ),
        ),
        (
            SD_PAIRING,
            "copy_single",
            "code",
            (
                'single "A" -> SD1',
                'single "AB" -> SD1',
                "single 10000h -> SD1",
                "single C1 -> SD1",
                "single CT1 -> SD1",
                "single SC1 -> SD1",
                "single T1 -> SD1",
                "single X001 -> SD1",
                "single Y001 -> SD1",
            ),
        ),
        (
            BIT_PAST_RANGE,
            "copy_single",
            "code",
            (
                "single DS2 -> CT0",
                "single DS2 -> CT251",
                "single DS2 -> SC0",
                "single DS2 -> SC1001",
                "single DS2 -> T0",
                "single DS2 -> T501",
                "single DS2 -> X000",
                "single DS2 -> X017",
                "single DS2 -> X020",
                "single DS2 -> X037",
                "single DS2 -> X100",
                "single DS2 -> X117",
                "single DS2 -> X817",
            ),
        ),
        (
            PACK_TXT,
            "copy_pack",
            "outcome",
            (
                "pack TXT1..TXT1000 -> DH1",
                "pack TXT1..TXT16 -> DH1",
            ),
        ),
        (
            PACK_TWO_BOXES,
            "copy_pack",
            "code",
            (
                "pack CT1..CT33 -> DD1",
                "pack CT1..CT33 -> DS1",
                "pack SC1..SC33 -> DD1",
                "pack SC1..SC33 -> DS1",
                "pack T1..T33 -> DD1",
                "pack T1..T33 -> DS1",
            ),
        ),
        (
            PACK_DH_COUNT,
            "copy_pack",
            "code",
            (
                "pack DH1..DH16 -> DH1",
                "pack DH1..DH500 -> DH1",
            ),
        ),
        (
            UNPACK_BANK_FIRST,
            "copy_unpack",
            "code",
            (
                "unpack DH1 -> DS1..DS1",
                "unpack DS1 -> DH1..DH1",
                "unpack DS1 -> DH2..DH1",
                "unpack DS1 -> DH500..DH500",
                "unpack DS1 -> DS001..C16",
                "unpack DS1 -> DS1..DS1",
                "unpack DS1 -> DS2..DS1",
                "unpack DS1 -> DS4500..DS4500",
                "unpack DS1 -> ds1..C16",
            ),
        ),
        (
            UNPACK_Y_PAIRING,
            "copy_unpack",
            "code",
            (
                "unpack DD1 -> Y001..Y001",
                "unpack DD1 -> Y001..Y002",
                "unpack DD1 -> Y001..Y016",
                "unpack DD1 -> Y001..Y032",
                "unpack DD1 -> Y001..Y033",
                "unpack DD1 -> Y001..Y036",
                "unpack DF1 -> Y001..Y016",
                "unpack DF1 -> Y001..Y032",
                "unpack DF1 -> Y001..Y036",
                "unpack DS1 -> Y001..Y001",
                "unpack DS1 -> Y001..Y002",
                "unpack DS1 -> Y001..Y016",
                "unpack DS1 -> Y001..Y021",
                "unpack DS1 -> Y001..Y032",
                "unpack DS1 -> Y001..Y033",
                "unpack DS1 -> Y001..Y036",
                "unpack DS1 -> Y002..Y001",
                "unpack DS1 -> Y016..Y016",
                "unpack DS1 -> Y021..Y021",
                "unpack DS1 -> Y036..Y036",
                "unpack DS1 -> Y101..Y101",
                "unpack DS1 -> Y101..Y116",
                "unpack DS1 -> Y101..Y201",
                "unpack DS1 -> Y815..Y816",
                "unpack DS1 -> Y816..Y816",
            ),
        ),
        (
            UNPACK_Y_COUNT,
            "copy_unpack",
            "code",
            (
                "unpack DH1 -> Y001..Y032",
                "unpack DH1 -> Y001..Y036",
            ),
        ),
        (
            OUT_ACROSS,
            "out",
            "code",
            (
                "out C1..DS1",
                "out C1..TXT1",
                "out C1..X001",
                "out Y001..DS001",
                "out Y001..DS1",
                "out Y001..TXT1",
                "out Y001..X001",
                "out Y001..ds1",
            ),
        ),
        (
            TYPED_ADDRESS,
            "copy_single",
            "stored",
            (
                "single DS2 -> DS001",
                "single DS2 -> DS01",
                "single DS2 -> DS[DS001]",
                "single DS2 -> DS[ds1]",
                "single DS2 -> YD00",
                "single DS2 -> YD0U",
                "single DS2 -> ds1",
            ),
        ),
        (
            TYPED_ADDRESS,
            "copy_block",
            "stored",
            (
                "block DS1..DS2 -> DS001",
                "block DS1..DS2 -> ds1",
            ),
        ),
        (
            TYPED_ADDRESS,
            "copy_pack",
            "stored",
            (
                "pack C1..C16 -> DS001",
                "pack C1..C16 -> ds1",
            ),
        ),
        (
            TYPED_ADDRESS,
            "math_decimal",
            "stored",
            (
                "dec DS1 = DS001 + 1",
                "dec DS1 = DS01 + 1",
                "dec DS1 = ds1 + 1",
            ),
        ),
        (
            TYPED_ADDRESS,
            "math_hex",
            "stored",
            (
                "hex DH1 = XD00",
                "hex DH1 = XD00 + 1h",
                "hex DH1 = XD0U",
                "hex DH1 = XD0U + 1h",
                "hex DH1 = YD00",
                "hex DH1 = YD00 + 1h",
                "hex DH1 = YD0U",
                "hex DH1 = YD0U + 1h",
                "hex DH1 = xd0U + 1h",
                "hex YD00 = DH2 + DH3",
                "hex YD0U = DH2 + DH3",
            ),
        ),
        (
            CONVERSION_7,
            "copy_single",
            "stored",
            (
                "single 1.5 -> CTD1",
                "single 1.5 -> CTD[DS1]",
                "single 1.5 -> DD1",
                "single 1.5 -> DD[DS1]",
                "single 2147483647 -> DF1",
                "single CTD1 -> DF1",
                "single DF1 -> CTD1",
            ),
        ),
        (
            TXT_NUMBER,
            "copy_single",
            "stored",
            (
                "single -5 -> TXT1",
                "single 1.5 -> TXT1",
                "single 2147483647 -> TXT1",
                "single FFh -> TXT1",
            ),
        ),
    ),
}

#: The codes compared today: both CLICK and the rules refuse, and the rules give a ``click_id``.
CODES_COMPARED = 2768


@pytest.fixture(scope="module")
def generator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "editor_grids", ROOT / "devtools" / "editor_grids.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def compared(generator: Any) -> tuple[dict[Key, str], dict[str, int]]:
    """The comparison of every answer file, made once for the tests that read it."""
    return compare(generator)


def _answers(name: str) -> list[dict[str, Any]]:
    path = GRIDS / f"{name}.answers.json"
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def too_long(case: dict[str, Any]) -> bool:
    """Whether the runner put in more text than the field takes: text no user can type."""
    return any(len(text) > case["limits"][name] for name, text in case["fields"].items())


def _receive(case: dict[str, Any]) -> object:
    """A Receive from a case, with the count the dialog held at OK (``read_back``).  A case
    with no recorded count (the rx2 file) is compared at quantity 1."""
    f = case["fields"]
    count = int(case["read_back"].get("count", 1))
    code = int(case["choices"]["function"].split(" ")[0])
    return Receive(
        target=ModbusRtuTarget(name="r", com_port="cpu2", device_id=1),
        remote_start=ModbusAddress(f["slave_address"]),
        dest=f["master_address"],
        quantity=count,
        receiving=f["receiving"],
        success=f["success"],
        error=f["error"],
        exception_response=f["exception"],
        function_code=code,
    )


def rules_verdict(generator: Any, case: dict[str, Any]) -> tuple[bool, str | None]:
    """Whether the rules accept the case, and the ``click_id`` of the refusal."""
    try:
        if case["instruction"] == "receive":
            _receive(case)
        else:
            seen: list[BaseException] = []

            def record(build: Any) -> dict[str, Any]:
                try:
                    build()
                except ValueError as exc:
                    seen.append(exc)
                    raise
                return {"verdict": "accepted"}

            original = generator.verdict_of
            generator.verdict_of = record
            try:
                generator.check_case(case)
            finally:
                generator.verdict_of = original
    except ValueError as exc:  # FieldError is one; any other exception fails the test
        return False, getattr(exc, "click_id", None)
    return True, None


def reads_as_raw(rows: list[str]) -> bool:
    """Whether the saved rung reads back as ``raw(...)`` (or an unknown condition).

    The rows were written by the laddercodec of the run; a ``raw(...)`` among them is read
    again from its bytes, as decode reads that save today.
    """
    lines = ["marker," + ",".join(_columns()), *rows]
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "stored.csv"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            rungs = read_csv(path)
        except Exception:
            return True
    return any(
        isinstance(i, Undecoded)
        or (isinstance(i, RawInstruction) and parse_af_blob(i.blob) is None)
        for r in rungs
        for i in r.instructions
    )


def _columns() -> list[str]:
    letters = [chr(ord("A") + n) for n in range(26)] + ["AA", "AB", "AC", "AD", "AE"]
    return [*letters, "AF"]


def compare(generator: Any) -> tuple[dict[Key, str], dict[str, int]]:
    """Each difference found, by key, and the counts."""
    found: dict[Key, str] = {}
    counts = {"compared": 0, "skipped": 0, "codes": 0}
    for grid in ANSWER_FILES:
        for case in _answers(grid):
            if too_long(case):
                counts["skipped"] += 1
                continue
            counts["compared"] += 1
            # Picker checks are several cases per list: a difference is keyed by the row.
            label = case["row"] if grid == "pickcheck" else case["case"]
            accepted, click_id = rules_verdict(generator, case)
            clicks = case["outcome"] == "accepted"
            if case["outcome"] not in ("accepted", "refused") or clicks != accepted:
                found[(grid, label, "outcome")] = (
                    f"CLICK {case['outcome']}, rules accepted={accepted}"
                )
            elif not clicks and click_id is not None and case["code"].startswith("OBJ-"):
                counts["codes"] += 1
                if case["code"] != click_id:
                    found[(grid, label, "code")] = f"CLICK {case['code']}, rules {click_id}"
            if clicks and case.get("stored") and reads_as_raw(case["stored"]):
                found[(grid, label, "stored")] = f"saved as {case['stored']}"
    return found, counts


def _writable() -> list[dict[str, Any]]:
    path = GRIDS / "sc_sd_writable.answers.json"
    return json.loads(path.read_text(encoding="utf-8"))["fields"]


def _accepts_address(field: dict[str, Any], bank: str, number: int) -> bool:
    """Whether the rules accept the address ``bank`` + ``number`` in the picker's field, with the other
    fields as the picker had them (``filled``; a field left empty is tried with each source
    that could be there)."""
    address = f"{bank}{number}"
    filled = field.get("filled") or {}
    kind, mode = field["instruction"], field.get("mode")
    try:
        if kind == "out":
            Coil(InstructionType.COIL_OUT, address, None)
        elif mode == "single":
            Copy("DS1", address)
        elif mode == "block":
            BlockCopy("DS1", "DS2", address, f"{bank}{number + 1}")
        elif mode == "pack":
            sources = [(filled["source"], filled["source_end"])] if filled else PACK_SOURCES
            return any(_builds(_pack, s, e, address) for s, e in sources)
        elif mode == "unpack":
            sources = [filled["source"]] if filled else UNPACK_SOURCES
            as_end = field["field"] == "destination_end"
            return any(_builds(_unpack, s, bank, number, as_end) for s in sources)
        elif mode == "hex":
            Math("DH1", address, "hex")
        else:
            Math("DS2 + 1", address, "decimal")
    except Exception:
        return False
    return True


#: Sources a Pack or Unpack field may have when the picker was opened with nothing filled.
PACK_SOURCES = [("C1", "C16"), ("DS1", "DS2"), ("DD1", "DD2"), ("DH1", "DH2"), ("DF1", "DF2")]
UNPACK_SOURCES = ["DS1", "DD1", "DH1", "DF1"]


def _builds(build: Any, *args: Any) -> bool:
    try:
        build(*args)
    except Exception:
        return False
    return True


def _pack(source: str, end: str, address: str) -> object:
    bank = source.rstrip("0123456789")
    return Pack(source, end, address, "bits" if bank == "C" else "words")


def _unpack(source: str, bank: str, number: int, as_end: bool) -> object:
    """An Unpack whose destination range holds ``number`` as its start, or as its end."""
    if bank in ("C", "Y", "SC", "X"):
        length = 16
        kind = "bits"
    else:
        length = 2
        kind = "words"
    first = number - length + 1 if as_end else number
    last = number if as_end else number + length - 1
    if bank == "Y":
        return Unpack(source, f"Y{first:03d}", f"Y{last:03d}", kind)
    return Unpack(source, f"{bank}{first}", f"{bank}{last}", kind)


def compare_lists() -> dict[Key, str]:
    """Each field and bank whose writable list differs from the addresses the rules accept.
    A bank with no list (null: its tab is greyed) is an empty list, which the rules must match
    by accepting no address of that bank."""
    found: dict[Key, str] = {}
    for field in _writable():
        for bank in ("SC", "SD"):
            listed = set(field[bank] or [])
            lo, hi = ADDRESS_BANKS[bank]
            # A Block Copy needs the second address as well: the picker lists the start of a pair.
            accepted = {n for n in range(lo, hi + 1) if _accepts_address(field, bank, n)}
            wanted = listed
            if field.get("mode") == "block":
                numbers = {int(a[2:]) for a in listed}
                wanted = {f"{bank}{n}" for n in numbers if n + 1 in numbers}
            if {f"{bank}{n}" for n in accepted} != wanted:
                parts = [str(field[k]) for k in ("instruction", "mode", "field") if field.get(k)]
                name = ".".join(parts)
                if field.get("filled"):
                    name += " (after " + " ".join(field["filled"].values()) + ")"
                found[("sc_sd_writable", f"{name}.{bank}", "list")] = (
                    f"{len(accepted)} accepted, {len(wanted)} listed"
                )
    return found


#: The fields whose picker-check answers (the ``pickcheck`` file) follow the lists.
PICKER_CHECKED = {("out", None), ("copy", "single"), ("copy", "block"), ("math", "decimal")}


def compare_picker_checks() -> list[str]:
    """Picker-check answers that do not follow the list (a start in the list, and for a Block
    Copy the next address too, is accepted; an SC or SD outside its field's list is refused)."""
    lists = {
        (f["instruction"], f.get("mode")): {
            int(a[2:]) for a in f["SC" if f["instruction"] == "out" else "SD"]
        }
        for f in _writable()
        if (f["instruction"], f.get("mode")) in PICKER_CHECKED
    }
    wrong: list[str] = []
    for case in _answers("pickcheck"):
        f = case["fields"]
        key = (case["instruction"], case.get("mode"))
        target = f.get("destination") or f.get("result") or f["address"]
        bank_wanted = "SC" if case["instruction"] == "out" else "SD"
        if not target.startswith(bank_wanted):
            expected = False  # an SC address in a Copy: the field's tab is greyed
        else:
            number = int(target[2:])
            listed = lists[key]
            expected = number in listed and (key[1] != "block" or number + 1 in listed)
        if (case["outcome"] == "accepted") != expected:
            wrong.append(case["case"])
    return wrong


def test_answers_match_the_rules(compared: tuple[dict[Key, str], dict[str, int]]) -> None:
    found = dict(compared[0])
    found.update(compare_lists())
    assert set(found) - set(DISAGREEMENTS) == set(), (
        "a difference between CLICK's answers and the rules that DISAGREEMENTS does not list: "
        + "; ".join(f"{k}: {v}" for k, v in sorted(found.items()) if k not in DISAGREEMENTS)
    )
    assert set(DISAGREEMENTS) - set(found) == set(), (
        "DISAGREEMENTS lists a difference that is gone (remove it)"
    )


def test_picker_checks_follow_the_picker_lists() -> None:
    assert compare_picker_checks() == []


def test_the_length_rule_skips_what_cannot_be_typed(
    compared: tuple[dict[Key, str], dict[str, int]],
) -> None:
    _, counts = compared
    assert counts["skipped"] == 3, "RESULTS names three risky cases past their field's limit"
    skipped = [c["case"] for g in ANSWER_FILES for c in _answers(g) if too_long(c)]
    assert len(skipped) == 3


def test_every_case_was_answered() -> None:
    for grid in ANSWER_FILES:
        for case in _answers(grid):
            assert case["outcome"] in ("accepted", "refused"), (grid, case["case"])
            read_back = case["read_back"]
            if grid == "receive_count":
                # The dialog also held the Slave ID and, where a case left the count unset,
                # the count it defaults to.
                assert all(read_back[k] == v for k, v in case["fields"].items()), case["case"]
            else:
                assert read_back == case["fields"], (grid, case["case"])


def test_codes_compared_are_the_count(compared: tuple[dict[Key, str], dict[str, int]]) -> None:
    _, counts = compared
    assert counts["codes"] == CODES_COMPARED, counts


def test_a_chain_of_boxes_starts_with_the_code() -> None:
    """Where one OK raised several error boxes (``boxes``, each a code and its message), the
    case's ``code`` and ``message`` are the first box's, and that code is the one compared."""
    chains = [
        (grid, case)
        for grid in ANSWER_FILES
        for case in _answers(grid)
        if case.get("boxes") is not None
    ]
    assert chains, "the copy_pack answers hold the chains of boxes"
    for grid, case in chains:
        assert case["outcome"] == "refused", (grid, case["case"])
        assert len(case["boxes"]) >= 2, (grid, case["case"])
        assert all(len(box) == 2 for box in case["boxes"]), (grid, case["case"])
        assert case["boxes"][0] == [case["code"], case["message"]], (grid, case["case"])


def test_answers_are_the_grids_cases() -> None:
    """The answered cases are the grid file's, label for label, with the same fields."""
    for grid in (
        "preflight",
        "risky",
        "out",
        "copy_single",
        "copy_block",
        "copy_pack",
        "copy_unpack",
        "math_decimal",
        "math_hex",
    ):
        cases = json.loads((GRIDS / f"{grid}.json").read_text(encoding="utf-8"))["cases"]
        answered = _answers(grid)
        assert [c["case"] for c in answered] == [c["case"] for c in cases], grid
        for case, answer in zip(cases, answered, strict=True):
            assert answer["fields"] == case["fields"], (grid, case["case"])
