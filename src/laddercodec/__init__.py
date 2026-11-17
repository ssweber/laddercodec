"""Read and write the ladder logic of AutomationDirect's CLICK PLC programming software.

``encode()`` turns ``Rung`` objects into the binary that CLICK puts on the clipboard, ready
to paste. ``decode()`` turns that binary back into ``Rung`` objects. ``decode_program()``
reads a program from a ``Scr*.tmp`` file, one of the temp files that CLICK writes to disk.
``read_csv()`` and ``write_csv()`` convert between ``Rung`` objects and a CSV form that
people and programs can read and edit. ``check()`` lists the shapes in your rungs that
CLICK's Syntax Check refuses.
"""

from .codes import CLICK_IDS, Code
from .compat import find_v4_only, is_v4_only
from .csv import CsvLocation, read_csv
from .csv.writer import write_csv
from .decode import Rung, decode
from .decode_program import decode_program
from .encode import encode
from .errors import CsvError, DecodeError, EncodeError, LaddercodecError, WriterError
from .instructions import (
    AfToken,
    BlockCopy,
    Break,
    Call,
    Coil,
    CompareContact,
    ConditionToken,
    Contact,
    Continue,
    Copy,
    Counter,
    Drum,
    Email,
    End,
    Fill,
    ForLoop,
    Home,
    Math,
    ModbusAddress,
    ModbusRtuTarget,
    ModbusTcpTarget,
    Next,
    OutVariant,
    Pack,
    Position,
    RawInstruction,
    Receive,
    Return,
    Search,
    Send,
    Shift,
    Timer,
    Undecoded,
    UnknownCondition,
    UnknownInstruction,
    Unpack,
    Velocity,
)
from .layout_check import Finding, check
from .legacy import LegacyEncodingWarning
from .model import (
    AddressError,
    AfInstruction,
    ConditionInstruction,
    FieldError,
    Program,
    Project,
    Reason,
)
from .operands.constants import constant_text
from .refused import RefusedFieldWarning
from .undecoded import UndecodedCommentWarning, UndecodedRungWarning

__all__ = [
    "encode",
    "decode",
    "decode_program",
    "read_csv",
    "write_csv",
    "CsvLocation",
    "find_v4_only",
    "is_v4_only",
    "check",
    "Finding",
    "Rung",
    "Program",
    "Project",
    "FieldError",
    "AddressError",
    "Reason",
    "Code",
    "CLICK_IDS",
    "LaddercodecError",
    "DecodeError",
    "EncodeError",
    "WriterError",
    "CsvError",
    "LegacyEncodingWarning",
    "RefusedFieldWarning",
    "UndecodedRungWarning",
    "UndecodedCommentWarning",
    "ConditionInstruction",
    "AfInstruction",
    "ConditionToken",
    "AfToken",
    "BlockCopy",
    "Call",
    "Contact",
    "CompareContact",
    "Counter",
    "Coil",
    "OutVariant",
    "Drum",
    "Copy",
    "Email",
    "End",
    "Fill",
    "ForLoop",
    "Home",
    "Math",
    "Next",
    "Break",
    "Continue",
    "ModbusAddress",
    "ModbusRtuTarget",
    "ModbusTcpTarget",
    "Pack",
    "Position",
    "Receive",
    "Send",
    "Timer",
    "Undecoded",
    "UnknownCondition",
    "UnknownInstruction",
    "Unpack",
    "Velocity",
    "RawInstruction",
    "Return",
    "Search",
    "Shift",
    "constant_text",
]
