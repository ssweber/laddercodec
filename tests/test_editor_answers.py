"""Tests that compare CLICK's answers to the editor grids with laddercodec's rules.

The files ``tests/fixtures/editor_grids/*.answers.json`` record what CLICK's dialogs
answered for each case. The README in that folder describes them. Nobody edits them to make
the code pass. These tests rebuild each answered case with the builders that
``devtools/editor_grids.py`` uses, and compare the result three ways:

- The outcome. The rules accept a case that CLICK accepted and refuse a case that CLICK
  refused.
- The code. Where both refuse and CLICK gave an ``OBJ-nnn``, the refusal's ``click_id`` is
  the same. A ``click_id`` of None is not a disagreement. Most refusals have none yet, so
  only some codes are compared. ``CODES_COMPARED`` holds the number compared, so a change
  that adds or removes ids changes that number and fails the test. Where one click of OK
  raised a chain of error boxes (``boxes``), ``code`` is the code of the first box.
- The save. ``read_csv`` reads the ``stored`` rows of an accepted case back as an
  instruction that is not ``raw(...)``.

The tests skip a case whose text is longer than its field's ``limits``. The runner set the
text with WM_SETTEXT, which ignores the field's limit, so no user could type that text. The
skip depends on the length of the text, not on the case label.

``DISAGREEMENTS`` lists every difference, keyed by grid, case label and kind, with the
reason for it. The test fails on a difference that the list does not hold, and on an entry
whose difference is gone. ``tests/test_operand_guards.py`` checks its allowlists the same
way.
"""

from __future__ import annotations

import importlib.util
import json
import re
import tempfile
from pathlib import Path
from typing import Any

import pytest

from laddercodec import FieldError
from laddercodec.csv import read_csv
from laddercodec.decode_program import _scr_box
from laddercodec.instructions.coil import Coil
from laddercodec.instructions.copy import BlockCopy, Copy, Pack, Unpack
from laddercodec.instructions.math import Math
from laddercodec.instructions.raw import RawInstruction, _decompose_blob
from laddercodec.instructions.undecoded import Undecoded
from laddercodec.model import ADDRESS_BANKS, Instruction

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
    "compare",
    "search",
    "risky_compare",
    "preflight_compare",
    "timer",
    "counter",
    "shift",
    "for",
    "copy_fill",
    "drum",
    "send",
    "risky_timer",
    "risky_shift",
    "risky_for",
    "risky_drum",
    "risky_send",
    "risky_counter",
    "risky_fill",
    "receive_click",
    "drum_events",
    "drum_events_names",
    "drum_events_shapes",
    "drum_events_padded",
    "coil_sc",
    "coil_sc_ranges",
    "compare_const",
)

Key = tuple[str, str, str]  # (grid, case label or field, kind)

HEX_WORD = (
    "kept: laddercodec asks for the h; CLICK reads a word of hex digits typed without it as a "
    "hex constant, so 10 is 16 and DH0 is D0h (settled). A word shaped like an address (C0, "
    "DD0, DF0, DH0, DH501) is refused as outside its bank's range instead; to do: that "
    "message is to name the h form"
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

# Reasons for Compare and Search cases.
CMP_SPACE = (
    "deliberate: CLICK accepts a space at the start or end of this field, or inside an "
    "address, and the save trims it or keeps it; nothing in CLICK refuses it. An "
    "instruction holds the address in display form, so construction refuses the space, "
    "and read_csv refuses a save that keeps it"
)
DH_NO_NUMBER = "kept: CLICK accepts DH1 == DH and saves B empty, so laddercodec refuses it"
TEXT_QUOTE = (
    'CLICK accepts a quote inside the text of a Fill value. A Fill reads """" as one '
    "quote, and laddercodec refuses a quote inside a Fill text until it reads it that way"
)
TWO_WAY_COMPARE = (
    'deliberate: CLICK accepts Data A "A"=="B" with Data B "C" and saves both as typed. '
    'decode() reads the save as that compare. Its CSV cell "A"=="B"=="C" reads two ways. '
    "So write_csv writes the rung as an undecoded marker"
)
SEARCH_TABLE_ID = (
    "CLICK refuses this Search table with OBJ-004. The rules refuse it with OBJ-008, or "
    "OBJ-012 for TXT1..TXT1"
)

LONG_TEXT = (
    "CLICK's save holds all 128 characters. The recorded stored text is shorter; "
    "decode_program reads the full text"
)

# Reasons for Copy cases.  INNER_SPACE covers a Math result too, and RX2_COUNT is a
# Receive case.
INNER_SPACE = (
    "kept: CLICK takes DS 1 (a space inside) as a Copy source or destination and as a Math "
    "result, and a Copy's save drops the space from the source and keeps it in the "
    "destination; an instruction holds the address in display form, so construction refuses "
    "the space, and read_csv refuses the save that keeps it (settled)"
)
E_REAL = (
    "kept: laddercodec refuses; DS is an integer, so a real such as 0.0 or 1.0 is no source "
    "for a Copy into DS1, yet CLICK lets text that is not a number through as a real (E5 and "
    '"HELLO" are stored 0.0, 1E is 1.0); typing a valid constant can\'t make that rung, since '
    "0.0 into DS becomes 0 (settled)"
)
COPY_EH = (
    "kept: CLICK stores EH and 1Eh as the reals 0.0 and 1.0; laddercodec refuses them and names "
    "the forms to write, the real or the hex value as a decimal integer (settled)"
)
COPY_REAL_DIGITS = (
    "kept: CLICK keeps 7 significant digits and stores 3.4028235E+38 as 3.402823E+38, another "
    "value; laddercodec refuses a real of more than 7 and names the form CLICK stores (settled)"
)
RX2_COUNT = (
    "kept: the rx2 run recorded no count and the test takes 1, which CLICK refuses for TXT "
    "(OBJ-010); in the same setup the dialog holds 2 at OK (receive_count), which the rules "
    "accept; no answer says what rx2 held"
)

# Reasons for the Timer, Counter, Shift, For, Fill, Drum and Send cases.
INNER_SPACE_FIELD = (
    "kept: CLICK accepts a space inside an address in this field (DS 1), as it does in a Copy "
    "source. What it saves here is not recorded. A space inside an address stays refused "
    "(settled)"
)
EDGE_WHITESPACE = (
    "deliberate: CLICK accepts a space or a tab at the start or end of this field. What it "
    "saves is not recorded. An instruction holds the field in display form, so construction "
    "refuses the space or the tab"
)
EDGE_SAVED = (
    "deliberate: CLICK accepts a space or a tab at the start or end of this field, and the "
    "save keeps it. A Slave ID of ' 1' is saved as ' 1', and a Sending bit of C100 with a tab "
    "after it keeps the tab. An instruction holds the field in display form, so construction "
    "refuses the space or the tab"
)
PRESET_DROPPED = (
    "kept: CLICK accepts a preset with a space at either end, and the save of this one holds "
    "no preset. A rung with no preset is not what the CSV states, so laddercodec refuses the "
    "space"
)
PRESET_EDGE = (
    "kept: CLICK accepts a preset with a space at either end. What it saves for this one is "
    "not recorded. The save of the same preset with the space at the other end holds no "
    "preset, so laddercodec refuses the space"
)
FOR_SPACE = (
    "kept: CLICK stores the For count 1 0 as typed. That count is not a number, so "
    "laddercodec refuses it"
)
FOR_SPACE_UNSAVED = (
    "kept: CLICK accepts the For count 1 2. What it saves is not recorded. A count with a "
    "space inside it is not a number, so laddercodec refuses it"
)
FOR_BLANK = (
    "kept: CLICK accepts a For count of one space and stores the space. A space states no "
    "count, so laddercodec refuses it as blank. CLICK refuses an empty count (OBJ-006)"
)
COUNTER_NOT_NUMBER = (
    "kept: CLICK stores the Counter preset 1-2 as typed. It is not a number, so laddercodec "
    "refuses it"
)
COUNTER_NOT_NUMBER_UNSAVED = (
    "kept: CLICK accepts the Counter preset --5. What it saves is not recorded. It is not a "
    "number, so laddercodec refuses it"
)
COUNT_DIGITS = (
    "kept: CLICK accepts a Send count written as an Arabic-Indic digit. laddercodec reads a "
    "count written in ASCII digits only"
)
SERVER_PORT = (
    "kept: CLICK accepts the server port abc. The port is a number from 1 to 65535, the range "
    "that CLICK's dialog states, so laddercodec refuses abc"
)
LONG_DIGITS = (
    "kept: CLICK reads an address with more than five digits after its bank by its value, "
    "such as a Send source of DS with 41 digits or the drum event C000001. An address has at "
    "most five digits after its bank, so laddercodec refuses it. It reads leading zeros "
    "within the five, as in DS001"
)
FILL_TXT_REAL = (
    'kept: CLICK reads "HELLO" as a real and stores the real 0.0 for a Fill into TXT, not the '
    "text. laddercodec refuses it as text of more than one character"
)
FILL_TXT_REAL_UNSAVED = (
    'kept: CLICK accepts "HELLO" as a Fill into TXT999..TXT1000. What it saves is not '
    "recorded. laddercodec refuses it as text of more than one character"
)
FILL_TXT_CHAR = (
    'kept: CLICK accepts "é" as a Fill into TXT and stores it as typed. What a PLC writes '
    "into one TXT register for it is not known, so laddercodec refuses it"
)
FILL_TXT_CHAR_UNSAVED = (
    'kept: CLICK accepts "€" and a tab as a Fill into TXT. What it stores for them is not '
    "recorded, and what a PLC writes into one TXT register for them is not known, so "
    "laddercodec refuses them"
)
E_REAL_FILL = (
    "kept: CLICK accepts 1E and E5 as a Fill source into DS. What it saves is not recorded. "
    "Neither is an integer constant, so laddercodec refuses them"
)
SLOT_PORTS = (
    "The port list of the PLC that answered has no slot ports, so CLICK did not take these "
    "cases. The rules accept a slot port"
)
ONE_ELEMENT_COUNT = (
    "CLICK's dialog closes the count box for FC05 and FC06, which write one element. The "
    "rules accept the count 1"
)
START_984_ID = (
    "kept: both refuse a 984 start of a kind that the function code does not write. CLICK "
    "refuses the slave address with OBJ-010. laddercodec refuses the source with OBJ-004"
)
SEND_TXT_ODD_START = (
    "to do: CLICK refuses a Send from an even TXT address with OBJ-028, before it checks "
    "the count. The rules have no code for this refusal yet. They accept the start. With FC16 "
    "they refuse the count with OBJ-010, and with FC06 they accept the Send"
)


def _table(*groups: tuple[str, str, str, tuple[str, ...]]) -> dict[Key, str]:
    """Return the reason for each case label of each group, keyed by (grid, label, kind).

    Each group is (reason, grid, kind, labels). Raise ValueError if a case is listed twice,
    in one group or in two.
    """
    table: dict[Key, str] = {}
    for reason, grid, kind, labels in groups:
        for label in labels:
            key = (grid, label, kind)
            if key in table:
                raise ValueError(f"{key} is listed twice")
            table[key] = reason
    return table


#: Every difference between CLICK's answers and the rules. The kind ``outcome`` means that
#: one accepted the case and the other refused it. ``code`` means that the OBJ ids differ.
#: ``stored`` means that CLICK's save reads back as raw. ``list`` means that the writable SC
#: or SD addresses differ. Each group is one piece of work to do, or one difference kept on
#: purpose.
DISAGREEMENTS: dict[Key, str] = _table(
    (RX2_COUNT, "receive", "outcome", ("03 -> TXT1",)),
    (
        EDGE_SPACE + " (Math result)",
        "risky",
        "outcome",
        ("dec  DS1 = DS2 + 1", "dec DS1  = DS2 + 1"),
    ),
    (
        EDGE_SPACE + " (Copy source)",
        "risky",
        "outcome",
        ("single  DS1 -> DS1", "single DS1  -> DS1"),
    ),
    (
        EDGE_SPACE_KEPT + " (Copy destination)",
        "risky",
        "outcome",
        ("single DS2 ->  DS1", "single DS2 -> DS1 "),
    ),
    (EDGE_SPACE + " (Block Copy source)", "risky", "outcome", ("block  DS1..DS2 -> DS11",)),
    (EDGE_SPACE_KEPT + " (Pack destination)", "risky", "outcome", ("pack C1..C16 ->  DS1",)),
    (EDGE_SPACE + " (Unpack source)", "risky", "outcome", ("unpack  DS1 -> C1..C16",)),
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
    (CMP_SPACE, "compare", "outcome", ("compare DS 1 == DS2", "compare DS1 == DS 1")),
    (CMP_SPACE, "compare", "stored", ("compare DS1 == DS 1",)),
    (DH_NO_NUMBER, "compare", "outcome", ("compare DH1 == DH",)),
    (
        CMP_SPACE,
        "risky_compare",
        "outcome",
        (
            "compare  DS1 == DS2",
            "compare DS1  == DS2",
            "compare DS1 ==  DS1",
            "compare DS1 == DS1 ",
        ),
    ),
    (
        CMP_SPACE,
        "risky",
        "outcome",
        (
            "search DS1..DS10 ==  DS1 -> DS30,C1",
            "search DS1..DS10 == DS1  -> DS30,C1",
            "search DS1..DS10 == DS20 ->  DS1,C1",
        ),
    ),
    (CMP_SPACE, "search", "outcome", ("search DS1..DS10 == DS 1 -> DS30,C1",)),
    (
        TEXT_QUOTE,
        "copy_fill",
        "outcome",
        ('fill """" -> TXT1..TXT10', 'fill """ -> TXT1..TXT10'),
    ),
    (TEXT_QUOTE, "copy_fill", "stored", ('fill """ -> TXT1..TXT10',)),
    (TWO_WAY_COMPARE, "compare_const", "stored", ('compare "A"=="B" == "C"',)),
    (
        SEARCH_TABLE_ID,
        "search",
        "code",
        (
            "search DH1..DS1 == 5 -> DS30,C1",
            "search DH1..TXT1 == 5 -> DS30,C1",
            "search TXT1..DS1 == 5 -> DS30,C1",
            "search TXT1..TXT1 == 5 -> DS30,C1",
        ),
    ),
    (
        LONG_TEXT,
        "risky",
        "stored",
        ('search TXT1..TXT10 == "' + "A" * 128 + '" -> DS30,C1',),
    ),
    (LONG_TEXT, "risky_compare", "stored", ('compare TXT1 == "' + "A" * 128 + '"',)),
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
    (COPY_EH, "copy_single", "outcome", ("single 1Eh -> DS1", "single EH -> DS1")),
    (COPY_REAL_DIGITS, "copy_single", "outcome", ("single 3.4028235E+38 -> DS1",)),
    (COUNTER_NOT_NUMBER, "counter", "outcome", ("count_up CT1 preset=1-2",)),
    (COUNTER_NOT_NUMBER_UNSAVED, "counter", "outcome", ("count_up CT1 preset=--5",)),
    (
        COUNT_DIGITS,
        "risky_send",
        "outcome",
        ("send fc16 984 400001 <- DS1 x١",),
    ),
    (
        EDGE_SAVED,
        "risky_send",
        "outcome",
        (
            "send fc06 984 400001 <- DS1 id= 1",
            "send fc06 984 400001 <- DS1 sending=C100\t",
        ),
    ),
    (EDGE_SPACE + " (Fill source)", "risky_fill", "outcome", ("fill  DS1 -> DS10..DS11",)),
    (EDGE_SPACE + " (Shift range)", "risky_shift", "outcome", ("shift  C1..C8",)),
    (
        EDGE_WHITESPACE,
        "risky_counter",
        "outcome",
        (
            "count_up  CT1 preset=10",
            "count_up CT1  preset=10",
        ),
    ),
    (
        EDGE_WHITESPACE,
        "risky_drum",
        "outcome",
        (
            "event_drum events[0]= X001",
            "event_drum events[0]=X001 ",
            "time_drum jump_enabled=1 jump_step= DS1",
            "time_drum jump_enabled=1 jump_step=DS1 ",
            "time_drum outputs[0]= Y001",
            "time_drum outputs[0]=Y001 ",
            "time_drum presets[0]= DS1",
            "time_drum presets[0]=DS1 ",
        ),
    ),
    (EDGE_WHITESPACE, "risky_fill", "outcome", ("fill DS1  -> DS10..DS11",)),
    (
        EDGE_WHITESPACE,
        "risky_send",
        "outcome",
        (
            "send fc05 984 1 <-  C1",
            "send fc05 984 1 <- C1 ",
            "send fc06 984  400001 <- DS1",
            "send fc06 984 400001  <- DS1",
            "send fc06 984 400001 <-  DS1",
            "send fc06 984 400001 <- DS1 ",
            "send fc06 984 400001 <- DS1 error= C102",
            "send fc06 984 400001 <- DS1 error=C102\t",
            "send fc06 984 400001 <- DS1 error=C102 ",
            "send fc06 984 400001 <- DS1 exception= DS1",
            "send fc06 984 400001 <- DS1 exception= DS100",
            "send fc06 984 400001 <- DS1 exception=DS1 ",
            "send fc06 984 400001 <- DS1 exception=DS100\t",
            "send fc06 984 400001 <- DS1 exception=DS100 ",
            "send fc06 984 400001 <- DS1 id=1\t",
            "send fc06 984 400001 <- DS1 id=1 ",
            "send fc06 984 400001 <- DS1 sending= C1",
            "send fc06 984 400001 <- DS1 sending= C100",
            "send fc06 984 400001 <- DS1 sending=C1 ",
            "send fc06 984 400001 <- DS1 sending=C100 ",
            "send fc06 984 400001 <- DS1 success= C101",
            "send fc06 984 400001 <- DS1 success=C101\t",
            "send fc06 984 400001 <- DS1 success=C101 ",
            "send fc06 click  DS1 <- DS1",
            "send fc06 click DS1  <- DS1",
            "send fc16 984 400001 <- DS1 x 1",
            "send fc16 984 400001 <- DS1 x1\t",
            "send fc16 984 400001 <- DS1 x1 ",
        ),
    ),
    (EDGE_WHITESPACE, "risky_shift", "outcome", ("shift C1 ..C8",)),
    (
        EDGE_WHITESPACE,
        "risky_timer",
        "outcome",
        (
            "on_delay  T1 preset=100 unit=ms",
            "on_delay T1  preset=100 unit=ms",
        ),
    ),
    (
        E_REAL_FILL,
        "copy_fill",
        "outcome",
        (
            "fill 1E -> DS10..DS11",
            "fill E5 -> DS10..DS11",
        ),
    ),
    (
        FILL_TXT_CHAR,
        "risky_fill",
        "outcome",
        ('fill "é" -> TXT1..TXT2',),
    ),
    (
        FILL_TXT_CHAR_UNSAVED,
        "risky_fill",
        "outcome",
        (
            'fill "\t" -> TXT1..TXT2',
            'fill "€" -> TXT1..TXT2',
        ),
    ),
    (
        FILL_TXT_REAL,
        "copy_fill",
        "outcome",
        ('fill "HELLO" -> TXT1..TXT2',),
    ),
    (
        FILL_TXT_REAL_UNSAVED,
        "copy_fill",
        "outcome",
        ('fill "HELLO" -> TXT999..TXT1000',),
    ),
    (
        FOR_BLANK,
        "risky_for",
        "outcome",
        ("for  ",),
    ),
    (
        FOR_SPACE,
        "for",
        "outcome",
        ("for 1 0",),
    ),
    (
        FOR_SPACE_UNSAVED,
        "for",
        "outcome",
        ("for 1 2",),
    ),
    (
        INNER_SPACE_FIELD,
        "copy_fill",
        "outcome",
        ("fill DS 1 -> DS10..DS11",),
    ),
    (
        INNER_SPACE_FIELD,
        "counter",
        "outcome",
        (
            "count_up CT 1 preset=10",
            "count_up CT1 preset=DS 1",
        ),
    ),
    (
        INNER_SPACE_FIELD,
        "drum",
        "outcome",
        (
            "event_drum events[0]=X 001",
            "time_drum jump_enabled=1 jump_step=DS 1",
            "time_drum outputs[0]=Y 001",
            "time_drum presets[0]=DS 1",
        ),
    ),
    (
        INNER_SPACE_FIELD,
        "for",
        "outcome",
        ("for DS 1",),
    ),
    (
        INNER_SPACE_FIELD,
        "send",
        "outcome",
        (
            "send fc05 984 1 <- C 1",
            "send fc06 984 400001 <- DS 1",
            "send fc06 984 400001 <- DS1 exception=DS 1",
            "send fc06 984 400001 <- DS1 sending=C 1",
            "send fc06 click DS 1 <- DS1",
        ),
    ),
    (
        INNER_SPACE_FIELD,
        "shift",
        "outcome",
        (
            "shift C 1..C8",
            "shift C1..C 1",
        ),
    ),
    (
        INNER_SPACE_FIELD,
        "timer",
        "outcome",
        (
            "on_delay T 1 preset=100 unit=ms",
            "on_delay T1 preset=DS 1 unit=ms",
        ),
    ),
    (
        LONG_DIGITS,
        "risky_send",
        "outcome",
        ("send fc06 984 400001 <- DS00000000000000000000000000000000000000001",),
    ),
    (
        LONG_DIGITS,
        "drum_events_padded",
        "outcome",
        (
            "event_drum event 1 'C000001'",
            "event_drum event 1 'X0000001'",
            "event_drum event 1 'SC0000000001'",
        ),
    ),
    (
        LONG_DIGITS,
        "drum_events_padded",
        "stored",
        ("event_drum event 1 'C000001'", "event_drum event 1 'SC0000000001'"),
    ),
    (
        ONE_ELEMENT_COUNT,
        "send",
        "outcome",
        (
            "send fc05 984 1 <- C1 x1",
            "send fc06 984 400001 <- DS1 x1",
        ),
    ),
    (PRESET_DROPPED, "risky_counter", "outcome", ("count_up CT1 preset=DS1 ",)),
    (PRESET_DROPPED, "risky_timer", "outcome", ("on_delay T1 preset= DS1 unit=ms",)),
    (PRESET_EDGE, "risky_counter", "outcome", ("count_up CT1 preset= DS1",)),
    (PRESET_EDGE, "risky_timer", "outcome", ("on_delay T1 preset=DS1  unit=ms",)),
    (
        SEND_TXT_ODD_START,
        "send",
        "code",
        (
            "send fc16 984 400001 <- TXT1000 x1",
            "send fc16 984 400001 <- TXT1000 x2",
        ),
    ),
    (
        SEND_TXT_ODD_START,
        "send",
        "outcome",
        ("send fc06 984 400001 <- TXT1000",),
    ),
    (
        SERVER_PORT,
        "send",
        "outcome",
        ("send fc06 984 400001 <- DS1 port=CPU Port1 server_port=abc",),
    ),
    (
        SLOT_PORTS,
        "send",
        "outcome",
        (
            "send fc06 984 400001 <- DS1 port=Slot0 Port1",
            "send fc06 984 400001 <- DS1 port=Slot0 Port1 id=0",
            "send fc06 984 400001 <- DS1 port=Slot0 Port1 id=247",
            "send fc06 984 400001 <- DS1 port=Slot0 Port2",
            "send fc06 984 400001 <- DS1 port=Slot0 Port2 id=0",
            "send fc06 984 400001 <- DS1 port=Slot0 Port2 id=247",
            "send fc06 984 400001 <- DS1 port=Slot1 Port1",
            "send fc06 984 400001 <- DS1 port=Slot1 Port1 id=0",
            "send fc06 984 400001 <- DS1 port=Slot1 Port1 id=247",
            "send fc06 984 400001 <- DS1 port=Slot1 Port2",
            "send fc06 984 400001 <- DS1 port=Slot1 Port2 id=0",
            "send fc06 984 400001 <- DS1 port=Slot1 Port2 id=247",
        ),
    ),
    (
        START_984_ID,
        "send",
        "code",
        (
            "send fc05 984 400001 <- C1",
            "send fc06 984 1 <- DS1",
            "send fc15 984 400001 <- C1 x2",
            "send fc16 984 1 <- DS1 x2",
        ),
    ),
)

#: The number of cases whose codes are compared. A case counts when CLICK and the rules both
#: refuse it, CLICK gave an OBJ id, and the rules give a ``click_id``.
CODES_COMPARED = 4846

#: The cases that have no answer to compare, and the cases that lack a ``read_back``. A case
#: that is ``not_taken`` is one that CLICK did not let the runner enter. A case with no
#: outcome is one where CLICK closed before it answered.
NOT_TAKEN = 127
NO_OUTCOME = 2
CRASHED = 3
NO_READ_BACK = 27


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
    """Return the comparison of every answer file, built once for the tests that read it."""
    return compare(generator)


def _answers(name: str) -> list[dict[str, Any]]:
    path = GRIDS / f"{name}.answers.json"
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def too_long(case: dict[str, Any]) -> bool:
    """Return True if the runner put more text in a field than the field's limit allows.

    No user can type such text. A case whose ``limits`` is None returns False. The runner
    never reached its fields, and each such case is ``not_taken``. A field that is missing
    from ``limits`` has no limit. Send's IP address is one.
    """
    limits = case["limits"]
    if limits is None:
        return False
    return any(name in limits and len(text) > limits[name] for name, text in case["fields"].items())


def _receive(generator: Any, case: dict[str, Any]) -> object:
    """Build a Receive from a case with the generator's builder.

    The count is the one that the case types. A case that types no count is built with the
    count that the dialog held when OK was clicked (``read_back``). A case with no recorded
    count, as in ``receive.answers.json``, gets quantity 1."""
    count = case["fields"].get("count", (case["read_back"] or {}).get("count", "1"))
    return generator.receive_build(case, count)()


def rules_verdict(generator: Any, case: dict[str, Any]) -> tuple[bool, str | None]:
    """Return whether the rules accept the case, and the ``click_id`` of the refusal if they
    refuse it."""
    try:
        if case["instruction"] == "receive":
            _receive(generator, case)
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
    except ValueError as exc:  # FieldError is a ValueError. Any other exception fails the test.
        return False, getattr(exc, "click_id", None)
    return True, None


def _read_rows(path: Path, rows: list[str]) -> list[Any]:
    """Write *rows* to *path* under a CSV header, and return the rungs that ``read_csv``
    reads from it."""
    lines = ["marker," + ",".join(_columns()), *rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return read_csv(path)


def reads_as_raw(rows: list[str]) -> bool:
    """Return True if the saved rung does not read back as a decoded instruction.

    That is so when ``read_csv`` raises, when the rung holds an ``Undecoded`` marker, or when
    it holds a ``raw(...)`` that ``decode_program`` would also read as raw.

    The laddercodec of the run that recorded the answers wrote these rows from CLICK's
    program file. So a ``raw(...)`` among them is read again from its tags, the way
    ``decode_program`` reads that program file. That laddercodec wrote
    ``to_text(suppress_zero=...)`` for a real constant, but ``to_text`` of a real constant
    accepts only ``exponential``. Such a row is read without ``suppress_zero``.
    """
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "stored.csv"
        try:
            try:
                rungs = _read_rows(path, rows)
            except FieldError as exc:
                if exc.field != "Copy.suppress_zero":
                    raise
                rungs = _read_rows(path, [re.sub(r"suppress_zero=[01],", "", row) for row in rows])
        except Exception:
            return True
    return any(
        isinstance(i, Undecoded) or (isinstance(i, RawInstruction) and saved_box(i) is None)
        for r in rungs
        for i in r.instructions
    )


def saved_box(raw: RawInstruction) -> Instruction | None:
    """Return the box that ``decode_program`` reads from the program-file entry that *raw*
    was written from, or None if that box is raw too.

    *raw* holds a blob composed from the entry's tags.  Each tag is a standard field in it,
    and a flag that is set is a field with an empty value.  This function reads the tags
    back from the blob, with the part rows and the cell rows, and reads the box from them
    as ``decode_program`` reads the entry.
    """
    class_name, type_code, _parts, extra, fields = _decompose_blob(raw.blob)
    tags = {tag: value for tag, _sentinel, value in fields}
    part_rows = bytes([1, *(1 + row for row in extra)])
    cell_rows = bytes([raw.rows or 0, raw.sub or 0])
    box = _scr_box(class_name, type_code, tags, part_rows, {}, {}, cell_rows)
    return None if isinstance(box, RawInstruction) else box


def _columns() -> list[str]:
    letters = [chr(ord("A") + n) for n in range(26)] + ["AA", "AB", "AC", "AD", "AE"]
    return [*letters, "AF"]


def compare(
    generator: Any, answers: dict[str, list[dict[str, Any]]] | None = None
) -> tuple[dict[Key, str], dict[str, int]]:
    """Compare every answer file with the rules.

    Return each difference found, keyed by (grid, label, kind), and the counts of cases
    compared, cases skipped, codes compared, cases not taken, cases with no outcome and cases
    where CLICK crashed. *answers* maps a grid to its cases. It replaces the answer files.
    """
    found: dict[Key, str] = {}
    counts = {
        "compared": 0,
        "skipped": 0,
        "codes": 0,
        "not_taken": 0,
        "no_answer": 0,
        "crashed": 0,
    }
    if answers is None:
        answers = {grid: _answers(grid) for grid in ANSWER_FILES}
    for grid, cases in answers.items():
        for case in cases:
            # A case with no answer is counted before the length rule, as tally_answers counts
            # it.
            if case["outcome"] == "crashed":
                # CLICK exited after OK without answering. That says nothing about the case,
                # so it agrees with no verdict and disagrees with none.
                counts["crashed"] += 1
                continue
            if case["outcome"] is None:
                # The run recorded no answer: CLICK closed before it answered.
                counts["no_answer"] += 1
                continue
            if case["outcome"] == "not_taken":
                counts["not_taken"] += 1
            if too_long(case):
                counts["skipped"] += 1
                continue
            counts["compared"] += 1
            # The pickcheck file holds several cases for each list, so a difference there is
            # keyed by the row, not by the case.
            label = case["row"] if grid == "pickcheck" else case["case"]
            accepted, click_id = rules_verdict(generator, case)
            if case["outcome"] == "not_taken":
                # CLICK did not let the runner enter the text, so it has no answer. The
                # rules must refuse it as well.
                if accepted:
                    found[(grid, label, "outcome")] = "CLICK did not take the text, rules accept"
                continue
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


#: The files of the SC and SD addresses that the Address Picker lists, for each field.
PICKER_FILES = ("sc_sd_writable", "coil_sc_picker")


def _writable() -> list[dict[str, Any]]:
    fields = []
    for name in PICKER_FILES:
        path = GRIDS / f"{name}.answers.json"
        fields += json.loads(path.read_text(encoding="utf-8"))["fields"]
    return fields


def _accepts_address(field: dict[str, Any], bank: str, number: int) -> bool:
    """Return whether the rules accept the address ``bank`` + ``number`` in the picker's field.

    A Pack or Unpack uses the source that the picker had filled in (``filled``). If the
    picker had no source filled in, each source that could be there is tried, and the
    address counts as accepted if any of them builds.
    """
    address = f"{bank}{number}"
    filled = field.get("filled") or {}
    kind, mode = field["instruction"], field.get("mode")
    try:
        if kind in COIL_KINDS:
            Coil(address, kind=COIL_KINDS[kind])
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


#: The Coil kind of each coil dialog. For a range end in the picker's list, the test builds a
#: Coil with that address alone, the same way it checks the address field.
COIL_KINDS: dict[str, Any] = {"out": "out", "set": "latch", "reset": "reset"}

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
    return Pack(source, end, address, "pack_bits" if bank == "C" else "pack_words")


def _unpack(source: str, bank: str, number: int, as_end: bool) -> object:
    """Build an Unpack whose destination range starts at ``number``, or ends at it if
    ``as_end`` is true."""
    if bank in ("C", "Y", "SC", "X"):
        length = 16
        kind = "unpack_to_bits"
    else:
        length = 2
        kind = "unpack_to_words"
    first = number - length + 1 if as_end else number
    last = number if as_end else number + length - 1
    if bank == "Y":
        return Unpack(source, f"Y{first:03d}", f"Y{last:03d}", kind)
    return Unpack(source, f"{bank}{first}", f"{bank}{last}", kind)


def compare_lists() -> dict[Key, str]:
    """Return each field and bank whose list of writable addresses differs from the
    addresses that the rules accept.

    A bank whose tab the picker greys has null for its list. That counts as an empty list,
    so the rules must accept no address of that bank.
    """
    found: dict[Key, str] = {}
    for field in _writable():
        for bank in ("SC", "SD"):
            listed = set(field[bank] or [])
            lo, hi = ADDRESS_BANKS[bank]
            # CLICK's Address Picker lists each SC or SD address that the field may write. The
            # Block Copy that _accepts_address builds writes two addresses, n and n+1. So for
            # a Block Copy, address n is wanted only if n+1 is listed too.
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


#: The fields whose answers in the ``pickcheck`` file must agree with the writable lists.
PICKER_CHECKED = {("out", None), ("copy", "single"), ("copy", "block"), ("math", "decimal")}


def compare_picker_checks() -> list[str]:
    """Return the ``pickcheck`` cases whose answers disagree with the writable lists.

    A case should be accepted when its address is in the list, and for a Block Copy when the
    next address is in the list too. An SC or SD address outside the field's list should be
    refused.
    """
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
            expected = False  # such as an SC address in a Copy, where the SC tab is greyed
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


def test_drum_cases_click_accepts_have_no_id(generator: Any) -> None:
    """A Drum case that CLICK accepts and the rules refuse has no CLICK id in the refusal,
    such as the event ``X 001``."""
    with_id = [
        (grid, case["case"], click_id)
        for grid in ANSWER_FILES
        for case in _answers(grid)
        if case["instruction"] == "drum" and case["outcome"] == "accepted"
        for _, click_id in [rules_verdict(generator, case)]
        if click_id is not None
    ]
    assert with_id == []


def test_picker_checks_follow_the_picker_lists() -> None:
    assert compare_picker_checks() == []


def test_the_length_rule_skips_what_cannot_be_typed(
    compared: tuple[dict[Key, str], dict[str, int]],
) -> None:
    _, counts = compared
    assert counts["skipped"] == 16, "16 cases are past their field's limit"
    # Two crashed cases are past their field's limit too. compare() counts them as crashed.
    skipped = [
        c["case"]
        for g in ANSWER_FILES
        for c in _answers(g)
        if too_long(c) and c["outcome"] != "crashed"
    ]
    assert len(skipped) == 16


def test_every_case_was_answered() -> None:
    """Every case has an outcome, except a counted few that have none to compare.

    A new case that is not taken, or has no outcome or no read_back, fails this test on its
    count."""
    tally = tally_answers({grid: _answers(grid) for grid in ANSWER_FILES})
    assert tally == {
        "not_taken": NOT_TAKEN,
        "no_outcome": NO_OUTCOME,
        "crashed": CRASHED,
        "no_read_back": NO_READ_BACK,
    }


def tally_answers(answers: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    """Check each case's outcome and read_back, and return the counts of the cases that have
    no answer to compare.

    Raise AssertionError for an outcome that is not accepted, refused, not_taken, crashed or
    None, and for a read_back that differs from the case's fields. A not_taken case is
    compared with the fields that its dialog holds (held_fields).
    """
    tally = {"not_taken": 0, "no_outcome": 0, "crashed": 0, "no_read_back": 0}
    for grid, cases in answers.items():
        for case in cases:
            if case["outcome"] in ("not_taken", "crashed"):
                tally[case["outcome"]] += 1
            elif case["outcome"] is None:
                tally["no_outcome"] += 1
            else:
                assert case["outcome"] in ("accepted", "refused"), (grid, case["case"])
            read_back = case.get("read_back")
            if read_back is None:
                tally["no_read_back"] += 1
                continue
            fields = held_fields(case) if case["outcome"] == "not_taken" else case["fields"]
            if grid in ("receive_count", "receive_click"):
                # The dialog also held the Slave ID and, where a case left the count unset,
                # the count it defaults to.
                assert all(read_back[k] == v for k, v in fields.items()), case["case"]
            else:
                # The dialog also held the fields that CLICK fills itself, where the case did
                # not type them.
                filled = CLICK_FILLS.get(case["instruction"], ())
                shown = {k: v for k, v in read_back.items() if k not in filled or k in fields}
                assert shown == fields, (grid, case["case"])
    return tally


#: The fields that CLICK fills itself, by instruction: a Timer's current value, and a
#: Counter's current value and completion bit. CLICK fills them from the done bit.
CLICK_FILLS = {"timer": ("accumulator",), "counter": ("accumulator", "completion_bit")}

#: The bounds that a Drum's dialog holds its step and output counts to.
DRUM_COUNT_BOUNDS = {"num_steps": (1, 16), "num_outputs": (1, 16)}

#: The runner's message for a case whose dialog closed a field the case typed.
CLOSED_FIELDS = "these fields are closed for entry: "


def held_fields(case: dict[str, Any]) -> dict[str, str]:
    """Return the fields of a not_taken case as its dialog holds them.

    A not_taken case reads back as typed, with three exceptions:

    - A Drum's dialog holds a step or output count past its bound at the bound, so 0 reads
      back as 1 and 17 as 16.
    - A Receive's dialog holds the count of a YD master address at 1.
    - A dialog that closes the count box holds no count.

    Any other difference fails the test.
    """
    fields = dict(case["fields"])
    if case["instruction"] == "drum":
        for name, (low, high) in DRUM_COUNT_BOUNDS.items():
            if fields.get(name, "").isdecimal():
                fields[name] = str(min(max(int(fields[name]), low), high))
    if case["instruction"] == "receive" and fields.get("master_address", "").startswith("YD"):
        fields["count"] = "1"
    message = case["message"] or ""
    if message.startswith(CLOSED_FIELDS) and message[len(CLOSED_FIELDS) :] == "count":
        del fields["count"]
    return fields


def test_a_crashed_case_is_counted_and_never_compared(generator: Any) -> None:
    """A case with outcome ``crashed`` is counted, and ``compare`` neither accepts nor
    disagrees with it, whatever the rules say."""
    accepted = next(c for c in _answers("compare") if c["outcome"] == "accepted")
    refused = next(c for c in _answers("compare") if c["outcome"] == "refused")
    cases = [dict(accepted, outcome="crashed"), dict(refused, outcome="crashed", read_back=None)]
    found, counts = compare(generator, {"compare": cases})
    assert found == {}
    assert counts["crashed"] == 2
    assert counts["compared"] == 0
    assert tally_answers({"compare": cases}) == {
        "not_taken": 0,
        "no_outcome": 0,
        "crashed": 2,
        "no_read_back": 1,
    }


def test_codes_compared_are_the_count(compared: tuple[dict[Key, str], dict[str, int]]) -> None:
    _, counts = compared
    assert counts["codes"] == CODES_COMPARED, counts
    assert counts["not_taken"] == NOT_TAKEN, counts
    assert counts["no_answer"] == NO_OUTCOME, counts
    assert counts["crashed"] == CRASHED, counts


def test_a_case_listed_twice_fails() -> None:
    once = ("a reason", "out", "code", ("out C1..DS1",))
    with pytest.raises(ValueError, match="listed twice"):
        _table(once, ("another reason", "out", "code", ("out Y001..DS1", "out C1..DS1")))


def test_a_chain_of_boxes_starts_with_the_code() -> None:
    """When one click of OK raised several error boxes, the case lists them in ``boxes``,
    each as a code and its message. The case's ``code`` and ``message`` are those of the
    first box, and that code is the one compared."""
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


#: The dialogs and modes that the answers to ``preflight.json`` and ``risky.json`` cover.
ANSWERED_DIALOGS = {
    ("math", "decimal"),
    ("math", "hex"),
    ("copy", "single"),
    ("copy", "block"),
    ("copy", "pack"),
    ("copy", "unpack"),
    ("out", None),
    *(("compare", op) for op in ("==", "!=", ">", "<", ">=", "<=")),
    *(("search", op) for op in ("==", "!=", ">", "<", ">=", "<=")),
}


def test_answers_are_the_grids_cases() -> None:
    """The answer files of the editor grids that the loop names hold the cases of their
    grid files, with the same labels in the same order, the same instruction, mode, fields and
    options, and no lists set.

    In ``preflight.json`` and ``risky.json``, only the cases of the dialogs in
    ``ANSWERED_DIALOGS`` are compared. Every case of the other grids must be of one of those
    dialogs."""
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
        "compare",
        "search",
        "risky_compare",
        "preflight_compare",
    ):
        every = json.loads((GRIDS / f"{grid}.json").read_text(encoding="utf-8"))["cases"]
        cases = [c for c in every if (c["instruction"], c.get("mode")) in ANSWERED_DIALOGS]
        if grid not in ("preflight", "risky"):
            assert cases == every, grid
        answered = _answers(grid)
        assert [c["case"] for c in answered] == [c["case"] for c in cases], grid
        for case, answer in zip(cases, answered, strict=True):
            where = (grid, case["case"])
            assert answer["instruction"] == case["instruction"], where
            assert answer.get("mode") == case.get("mode"), where
            assert answer["fields"] == case["fields"], where
            # CLICK answered each case with its lists as the dialog opened them. A Search case
            # may set Continuous or One Shot, and its answer holds the same options.
            assert "choices" not in case, where
            assert answer.get("options") == case.get("options"), where


#: The answer files of the grids that ClickNick wrote, and the grids that each file answers,
#: in the order of its cases.
RUNNER_ANSWERS = {
    "receive_click": ("receive_click", "receive_click_count1"),
    "drum_events": ("drum_events",),
    "drum_events_names": ("drum_events_names",),
    "drum_events_shapes": ("drum_events_shapes",),
    "drum_events_padded": ("drum_events_padded", "drum_events_padded2"),
    "coil_sc": ("coil_sc",),
    "coil_sc_ranges": ("coil_sc_ranges",),
    "compare_const": ("compare_const",),
}


def test_runner_answers_are_the_grids_cases(generator: Any) -> None:
    """Each answer file of a grid that ClickNick wrote holds the cases of its grids, in order.
    Each answer holds its case's keys with the same values."""
    assert sorted(g for grids in RUNNER_ANSWERS.values() for g in grids) == sorted(
        generator.RUNNER_GRIDS
    )
    for name, grids in RUNNER_ANSWERS.items():
        cases = [
            case
            for grid in grids
            for case in json.loads((GRIDS / f"{grid}.json").read_text(encoding="utf-8"))["cases"]
        ]
        answered = _answers(name)
        assert len(answered) == len(cases), name
        for case, answer in zip(cases, answered, strict=True):
            assert {k: answer.get(k) for k in case} == case, (name, case["case"])
