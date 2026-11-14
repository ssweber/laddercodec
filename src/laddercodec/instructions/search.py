"""Search instruction (type marker 0x2722).

Binary class name: ``"Search"``.

Searches a table range for a value matching a comparison condition.
Six comparison operators (==, !=, >, <, >=, <=), with optional
continuous and oneshot flags.  Func code is 8964 + operator index
(== != > >= < <=) + 6 if oneshot, for data and text search alike.

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

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..binary_helpers import tag_flag, tag_int, tag_value
from ..model import AfInstruction, FieldError, normalize_address
from ..operands.constants import SEARCH_TABLE_BANKS, classify
from .comparison import check_quoted_text
from .copy import REGISTER_BANKS, _check_range, check_constant, check_operand
from .family import AfInstructionFamilySpec, fixed_cell_params

if TYPE_CHECKING:
    from ..csv.ast import AfCall

#: Cell kwargs of a Search box: two rows (cell header +0x09 = +0x0A = 2).
_CELL_PARAMS: dict = {"visual_rows": 2}

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

#: CSV operator → func code without oneshot; oneshot adds 6 (8970–8975).
#: From InstCtl_Search.dll, confirmed by v4_captures/sweep_search.bin.
_OP_TO_FUNC: dict[str, int] = {
    "==": 8964,
    "!=": 8965,
    ">": 8966,
    ">=": 8967,
    "<": 8968,
    "<=": 8969,
}
_ONESHOT_FUNC_OFFSET = 6

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
# Operand banks
# ---------------------------------------------------------------------------

#: Banks a search table spans.
TABLE_BANKS = frozenset({"DS", "DD", "DH", "DF", "TD", "CTD", "TXT"})
#: The result holds the found address's index, a DS (Help CL174).
RESULT_BANKS = frozenset({"DS"})
#: The Result Flag is a C bit (Inst_Search.dll validator mask 4; OBJ-004).
FOUND_BANKS = frozenset({"C"})
#: A text search value hides the four order operators, leaving these.  The search-value
#: change handler (Inst_Search.dll) reaches the same text test (0x140)
#: from a TXT register and from a text constant.
_TEXT_OPS = frozenset({"==", "!="})
#: A hex search value above FFFFh is a 32-bit hex constant (baseEx.dll decides by value),
#: which the value check refuses (Inst_Search.dll, OBJ-005).
_HEX_CONSTANT_RE = re.compile(r"[+-]?([0-9A-Fa-f]+)[hH]")

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

    def __post_init__(self) -> None:
        # A constant search value comes back from normalize_address as written.
        for name in ("table_start", "table_end", "source", "result", "found"):
            setattr(self, name, normalize_address(getattr(self, name)))
        if self.comparison not in _OP_TO_FUNC:
            raise FieldError(
                f"Search.comparison: {self.comparison!r} is not allowed; it is one of "
                f"{', '.join(_OP_TO_FUNC)}"
            )
        # Inst_Search.dll has no pointer path, so no field takes one (Q-M6).  The table is
        # one bank, start before end (range check: OBJ-008, OBJ-009, OBJ-012).
        table, _ = _check_range(
            "Search", "table_start", self.table_start, "table_end", self.table_end, TABLE_BANKS
        )
        check_operand(self.result, "Search.result", RESULT_BANKS)
        check_operand(self.found, "Search.found", FOUND_BANKS)
        if len(self.source) >= 2 and self.source[0] == self.source[-1] == '"':
            check_quoted_text(self.source, "Search.source")
        # The search value is a constant or a data register, never a bit (Help CL174).
        source = check_operand(self.source, "Search.source", REGISTER_BANKS, constant=True)
        m = _HEX_CONSTANT_RE.fullmatch(self.source)
        if m and int(m.group(1), 16) > 0xFFFF:
            raise FieldError(
                f"Search.source: {self.source!r} is above FFFFh; a hex search value is 16-bit"
            )
        if (source.kind == "text" or source.bank == "TXT") and self.comparison not in _TEXT_OPS:
            raise FieldError(
                f"Search.comparison: {self.comparison!r} is not offered for text "
                f"{self.source!r}; text searches with == or !="
            )
        if source.kind in ("number", "text"):
            # The value field runs CLICK's shared input check (arc.md Q-M10 ruling).
            check_constant(self.source, "Search.source")
            # The value's kind ties to the table banks (arc.md Q-M21).
            const = classify(self.source)
            if const is not None and table.bank not in SEARCH_TABLE_BANKS[const.kind]:
                raise FieldError(
                    f"Search.source: {self.source!r} is a {const.kind} value, which searches "
                    f"{', '.join(sorted(SEARCH_TABLE_BANKS[const.kind]))}, not {table.bank}"
                )

    @property
    def func_code(self) -> str:
        return str(_OP_TO_FUNC[self.comparison] + (_ONESHOT_FUNC_OFFSET if self.oneshot else 0))

    def to_csv(self) -> str:
        expr = f"{self.table_start}..{self.table_end} {self.comparison} {self.source}"
        kw = [f"result={self.result}", f"found={self.found}"]
        if self.continuous:
            kw.append("continuous=1")
        if self.oneshot:
            kw.append("oneshot=1")
        return f"search({expr},{','.join(kw)})"

    def cell_params(self) -> dict:
        return dict(_CELL_PARAMS)

    def build_blob(self) -> bytes:
        from ..binary_helpers import _build_blob

        cmp_code = _OP_TO_CMP_CODE[self.comparison]

        return _build_blob(
            "Search",
            0x2722,
            _SEARCH_TAGS,
            [
                self.source,  # [0]
                self.table_start,  # [1]
                self.table_end,  # [2]
                self.result,  # [3]
                self.found,  # [4]
                "-1" if self.continuous else "0",  # [5]
                self.func_code,  # [6]
                "-1" if self.oneshot else "0",  # [7]
                cmp_code,  # [8]
                "",  # [9] terminator
            ],
        )


# ---------------------------------------------------------------------------
# Shared from_tags factory
# ---------------------------------------------------------------------------

_SEARCH_TYPE_CODE = 0x2722


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Search | None:
    """Construct a Search from tag data (shared by both decoders)."""
    if class_name != "Search" or type_code != _SEARCH_TYPE_CODE:
        return None

    source = tag_value(tags, 0x6065)
    table_start = tag_value(tags, 0x6066)
    table_end = tag_value(tags, 0x6067)
    result = tag_value(tags, 0x6079)
    found = tag_value(tags, 0x607A)
    cmp_idx = str(tag_int(tags, 0x21F7))
    comparison = _CMP_CODE_TO_OP.get(cmp_idx)

    if not all([source, table_start, table_end, result, found]) or comparison is None:
        return None

    return Search(
        table_start=table_start,
        table_end=table_end,
        source=source,
        result=result,
        found=found,
        comparison=comparison,
        continuous=tag_flag(tags, 0x1277),
        oneshot=tag_flag(tags, 0x11F8),
    )


def parse_af_call(call: AfCall) -> Search:
    """Parse an AF AST call into a Search."""
    if len(call.args) != 1:
        raise ValueError(f"search expects 1 positional arg (expression), got {len(call.args)}")

    expr = call.args[0]
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
    from_tags=from_tags,
    csv_names=("search",),
    parse_csv_call=parse_af_call,
    cell_params_from_tags=fixed_cell_params(_CELL_PARAMS, ("Search", _SEARCH_TYPE_CODE)),
)
