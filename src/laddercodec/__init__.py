"""Binary codec for AutomationDirect CLICK PLC ladder clipboard format."""

from .csv import read_csv
from .csv.writer import write_csv
from .decode import Rung, decode
from .encode import encode
from .instructions import (
    BlockCopy,
    Call,
    Coil,
    CompareContact,
    Contact,
    Copy,
    Counter,
    Drum,
    End,
    Fill,
    ForLoop,
    Math,
    Next,
    Pack,
    RawInstruction,
    Return,
    Search,
    Shift,
    Timer,
    Unpack,
)

__all__ = [
    "encode",
    "decode",
    "read_csv",
    "write_csv",
    "Rung",
    "BlockCopy",
    "Call",
    "Contact",
    "CompareContact",
    "Counter",
    "Coil",
    "Drum",
    "Copy",
    "End",
    "Fill",
    "ForLoop",
    "Math",
    "Next",
    "Pack",
    "Timer",
    "Unpack",
    "RawInstruction",
    "Return",
    "Search",
    "Shift",
]
