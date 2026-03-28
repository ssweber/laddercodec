"""Binary codec for AutomationDirect CLICK PLC ladder clipboard format."""

from .csv.writer import decode_to_csv, write_decoded_csv
from .decode import (
    CellDump,
    DecodedRung,
    UnknownCondition,
    UnknownInstruction,
    decode_multi_rung,
    decode_rung,
    inspect_cells,
)
from .encode import encode_rung
from .encode_multi import encode_multi_rung
from .instructions import Coil, CompareContact, Contact, RawInstruction, Timer

__all__ = [
    "CellDump",
    "Coil",
    "CompareContact",
    "Contact",
    "RawInstruction",
    "Timer",
    "DecodedRung",
    "UnknownCondition",
    "UnknownInstruction",
    "decode_multi_rung",
    "decode_rung",
    "decode_to_csv",
    "encode_multi_rung",
    "encode_rung",
    "inspect_cells",
    "write_decoded_csv",
]
