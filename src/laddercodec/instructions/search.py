"""Search instruction (type marker 0x2722).

Binary class name: ``"Search"``.

Searches a table range for a value matching a comparison condition.
Six comparison operators (==, !=, >, <, >=, <=), with optional
continuous and oneshot flags.  Text search (literal source) uses
func code 8970; data search uses 8964–8969.

Field layout (10 fields):

- field[0]: tag=0x6065 — source (register or quoted text literal)
- field[1]: tag=0x6066 — table_start
- field[2]: tag=0x6067 — table_end
- field[3]: tag=0x6079 — result register
- field[4]: tag=0x607A — found flag bit
- field[5]: tag=0x1277 — continuous (-1 = enabled)
- field[6]: tag=0x3218 — func_code
- field[7]: tag=0x11F8 — oneshot (-1 = enabled)
- field[8]: tag=0x21F7 — comparison_code
- field[9]: tag=0x0000 — terminator
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..model import OPERAND_RE, AfInstruction
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

#: CSV operator → func code (data search).
_OP_TO_FUNC: dict[str, str] = {
    "==": "8964",
    "!=": "8965",
    ">": "8966",
    ">=": "8967",
    "<": "8968",
    "<=": "8969",
}

#: Text search func code.
_TEXT_FUNC = "8970"

#: Reverse lookup: func code → CSV operator.
_FUNC_TO_OP: dict[str, str] = {v: k for k, v in _OP_TO_FUNC.items()}

# ---------------------------------------------------------------------------
# Comparison code tables (field[8])
# ---------------------------------------------------------------------------

_OP_TO_CMP_CODE: dict[str, str] = {
    "==": "0",
    "!=": "1",
    ">": "2",
    "<": "3",
    ">=": "4",
    "<=": "5",
}

_CMP_CODE_TO_OP: dict[str, str] = {v: k for k, v in _OP_TO_CMP_CODE.items()}

# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

_SEARCH_TAGS = (
    0x6065,  # [0] source
    0x6066,  # [1] table_start
    0x6067,  # [2] table_end
    0x6079,  # [3] result
    0x607A,  # [4] found
    0x1277,  # [5] continuous (-1 = enabled)
    0x3218,  # [6] func_code
    0x11F8,  # [7] oneshot (-1 = enabled)
    0x21F7,  # [8] comparison_code
    0x0000,  # [9] terminator
)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Search(AfInstruction):
    """A search instruction.

    Attributes
    ----------
    table_start:
        Start of search table (e.g. ``"DS72"``).
    table_end:
        End of search table (e.g. ``"DS81"``).
    source:
        Value to search for — register (``"DS71"``) or literal (``"A"``).
    result:
        Destination register for the result index.
    found:
        Found flag bit (e.g. ``"C81"``).
    comparison:
        Comparison operator: ``"=="``, ``"!="``, ``">"``, ``"<"``,
        ``">="``, ``"<="``.
    continuous:
        Search continuously (every scan).
    oneshot:
        Execute once on OFF→ON transition.
    """

    table_start: str
    table_end: str
    source: str
    result: str
    found: str
    comparison: str
    continuous: bool = False
    oneshot: bool = False

    @property
    def _is_text_search(self) -> bool:
        return not OPERAND_RE.fullmatch(self.source)

    @property
    def func_code(self) -> str:
        if self._is_text_search:
            return _TEXT_FUNC
        return _OP_TO_FUNC[self.comparison]

    def to_csv(self) -> str:
        expr = f"{self.table_start}..{self.table_end} {self.comparison} {self.source}"
        kw = [f"result={self.result}", f"found={self.found}"]
        if self.continuous:
            kw.append("continuous=1")
        if self.oneshot:
            kw.append("oneshot=1")
        return f"search({expr},{','.join(kw)})"

    def cell_params(self) -> dict:
        return {"visual_rows": 2}

    def build_blob(self) -> bytes:
        from ..binary_helpers import _tagged_field, _utf16le_null

        if self._is_text_search:
            source_field = f'"{self.source}"'
        else:
            source_field = self.source

        cmp_code = _OP_TO_CMP_CODE[self.comparison]

        type_marker = 0x2722
        field_count = 10
        fields = [
            source_field,  # [0]
            self.table_start,  # [1]
            self.table_end,  # [2]
            self.result,  # [3]
            self.found,  # [4]
            "-1" if self.continuous else "0",  # [5]
            self.func_code,  # [6]
            "-1" if self.oneshot else "0",  # [7]
            cmp_code,  # [8]
            "",  # [9] terminator
        ]

        out = bytearray()
        out += _utf16le_null("Search")
        out += struct.pack("<I", type_marker)
        out += b"\x01\x00"  # part count
        out += struct.pack("<I", field_count)
        for tag, value in zip(_SEARCH_TAGS, fields, strict=True):
            out += _tagged_field(tag, value)
        return bytes(out)


# ---------------------------------------------------------------------------
# Blob parser
# ---------------------------------------------------------------------------


def parse_blob(raw: bytes) -> Search | None:
    """Try to parse a Search instruction from an instruction blob."""
    from ..binary_helpers import _parse_tagged_fields, _read_utf16le

    class_name, pos = _read_utf16le(raw, 0)
    if class_name != "Search":
        return None
    if pos + 10 > len(raw):
        return None

    pos += 4  # skip type marker
    pos += 2  # skip part count (01 00)
    field_count = int.from_bytes(raw[pos : pos + 4], "little")
    pos += 4

    fields = _parse_tagged_fields(raw, pos, field_count)
    if len(fields) < 9:
        return None

    source = fields[0]
    table_start = fields[1]
    table_end = fields[2]
    result = fields[3]
    found = fields[4]
    continuous = fields[5] == "-1"
    func_code = fields[6]
    oneshot = fields[7] == "-1"

    if func_code == _TEXT_FUNC:
        comparison = "=="
        # Strip quotes from text literal source
        if source.startswith('"') and source.endswith('"'):
            source = source[1:-1]
    else:
        comparison = _FUNC_TO_OP.get(func_code)
        if comparison is None:
            return None

    return Search(
        table_start=table_start,
        table_end=table_end,
        source=source,
        result=result,
        found=found,
        comparison=comparison,
        continuous=continuous,
        oneshot=oneshot,
    )


def parse_af_call(call: AfCall) -> Search:
    """Parse an AF AST call into a Search."""
    if len(call.args) != 1:
        raise ValueError(f"search expects 1 positional arg (expression), got {len(call.args)}")

    expr = call.args[0]
    import re

    m = re.fullmatch(r"(.+?)\.\.(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+)", expr)
    if not m:
        raise ValueError(f"Cannot parse search expression: {expr!r}")

    result = call.kwargs.get("result")
    found = call.kwargs.get("found")
    if not result or not found:
        raise ValueError("search missing result or found kwargs")

    return Search(
        table_start=m.group(1).strip(),
        table_end=m.group(2).strip(),
        comparison=m.group(3),
        source=m.group(4).strip(),
        result=result,
        found=found,
        continuous=call.kwargs.get("continuous") == "1",
        oneshot=call.kwargs.get("oneshot") == "1",
    )


SPEC = AfInstructionFamilySpec(
    family_name="search",
    instruction_types=(Search,),
    binary_class_names=("Search",),
    parse_blob=parse_blob,
    csv_names=("search",),
    parse_csv_call=parse_af_call,
    min_csv_rows=2,
)
