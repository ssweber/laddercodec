"""The Search instruction (type marker 0x2722, binary class name ``"Search"``).

A Search looks through a table of registers for a value that meets a comparison.
It has six comparison operators (==, !=, >, <, >=, <=) and optional continuous
and oneshot flags.  The func code is 8964 plus the operator's index in the order
== != > >= < <=, plus 6 with oneshot.  Data and text searches use the same func
codes.

Field layout (10 fields):

- field[0]: tag=0x6065 — value (register or quoted text literal)
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
from typing import TYPE_CHECKING, cast

from ..binary_helpers import tag_flag, tag_int, tag_value
from ..codes import Code
from ..errors import CsvError
from ..model import Address, AfInstruction, Reason
from ..operands.checks import (
    ALL_KINDS,
    REGISTER_BANKS,
    Constants,
    Operand,
    Refusals,
    check_csv_flag,
    check_quoted_text,
)
from ..operands.constants import HEX16_MAX, SEARCH_TABLE_BANKS, Kind
from .comparison import CompareOp
from .copy import check_box_operand, check_range
from .family import AfInstructionFamilySpec, fixed_cell_params

if TYPE_CHECKING:
    from ..csv.ast import AfCall

#: Cell kwargs of a Search box.  The box spans two rows: cell header bytes +0x09 and +0x0A
#: are both 2.
_CELL_PARAMS: dict = {"visual_rows": 2}

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

#: CSV operator → func code without oneshot; oneshot adds 6 (8970–8975).
_OP_TO_FUNC: dict[CompareOp, int] = {
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

_OP_TO_CMP_CODE: dict[CompareOp, str] = {
    "==": "0",
    "!=": "1",
    ">": "2",
    "<": "3",
    ">=": "4",
    "<=": "5",
}

_CMP_CODE_TO_OP: dict[str, CompareOp] = {v: k for k, v in _OP_TO_CMP_CODE.items()}

# ---------------------------------------------------------------------------
# Operand banks
# ---------------------------------------------------------------------------

#: Banks a search table spans.
TABLE_BANKS = frozenset({"DS", "DD", "DH", "DF", "TD", "CTD", "TXT"})
#: The result is a DS register.  It receives the index of the address that was found.
RESULT_BANKS = frozenset({"DS"})
#: The Result Flag is a C bit (OBJ-004).
FOUND_BANKS = frozenset({"C"})
#: The operators offered for a text search value.  The four order operators are hidden for
#: text.  A TXT register counts as text, the same as a text constant.
_TEXT_OPS = frozenset({"==", "!="})
#: The constants a search value takes: any kind, with hex up to FFFFh.  A hex value above
#: FFFFh is a 32-bit hex constant, which is refused with OBJ-005.  Hex text with a sign, such
#: as ``+1h``, reads as a hex constant, so the field refuses it as a constant and not as an
#: address.  Text is not limited to printable ASCII here.  ``check_quoted_text`` checks it,
#: with its quotes, for the characters that CLICK keeps.
_VALUE = Constants(ALL_KINDS, hex_high=HEX16_MAX, hex_sign=True, printable=False)

# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

_SEARCH_TAGS = (
    0x6065,  # [0] value
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


@dataclass(frozen=True)
class Search(AfInstruction):
    """A search instruction.

    Attributes
    ----------
    table_start:
        Start of search table (e.g. ``"DS72"``).
    table_end:
        End of search table (e.g. ``"DS81"``).
    value:
        Value to search for — register (``"DS71"``) or literal (``"A"``).
    result:
        Destination register for the result index.
    found:
        Found flag bit (e.g. ``"C81"``).
    op:
        Comparison operator: ``"=="``, ``"!="``, ``">"``, ``"<"``,
        ``">="``, ``"<="``.
    continuous:
        Search continuously (every scan).
    oneshot:
        Execute once on OFF→ON transition.
    """

    table_start: str
    table_end: str
    value: str
    result: str
    found: str
    op: CompareOp
    continuous: bool = False
    oneshot: bool = False

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            # A constant search value comes back from normalize_address as written.
            check.normalize("table_start", "table_end", "value", "result", "found")
            if self.op not in _OP_TO_FUNC:
                check.refuse(
                    "op",
                    f"{self.op!r} is not allowed; it is one of {', '.join(_OP_TO_FUNC)}",
                    Reason.CHOICE,
                    code=Code.INVALID_CHOICE,
                )
            # No Search field takes a pointer.  The table's two ends are in one bank,
            # and the end comes after the start.  check_range refuses a table that
            # breaks this with OBJ-008, OBJ-009 or OBJ-012.
            start = check("table_start", check_box_operand, TABLE_BANKS)
            end = check("table_end", check_box_operand, TABLE_BANKS)
            table = None
            if start is not None and end is not None:
                ends = check.run(
                    check_range,
                    "Search",
                    "table_start",
                    self.table_start,
                    "table_end",
                    self.table_end,
                    TABLE_BANKS,
                )
                table = ends[0] if ends is not None else None
            check("result", check_box_operand, RESULT_BANKS)
            check("found", check_box_operand, FOUND_BANKS)
            if len(self.value) >= 2 and self.value[0] == self.value[-1] == '"':
                check("value", check_quoted_text, kept=True)
            # The search value is a constant or a data register, never a bit.
            value = check("value", check_box_operand, REGISTER_BANKS, _VALUE)
            if value is not None:
                self._check_value(check, value, table)
            check.flag("continuous", "oneshot")

    def _check_value(self, check: Refusals, value: Operand, table: Address | None) -> None:
        """Refuse a search value that does not suit the operator or the table's bank."""
        const = value.constant
        if (const is not None and const.kind in (Kind.TEXT, Kind.CHAR)) or value.bank == "TXT":
            if self.op not in _TEXT_OPS:
                check.refuse(
                    ("op", "value"),
                    f"{self.op!r} is not offered for text "
                    f"{self.value!r}; text searches with == or !=",
                    Reason.CONFLICT,
                    code=Code.TEXT_ORDER_COMPARE,
                )
        # A constant's kind decides which banks the table may be in.
        if (
            const is not None
            and table is not None
            and table.bank not in SEARCH_TABLE_BANKS[const.kind]
        ):
            check.refuse(
                ("value", "table_start"),
                f"{self.value!r} is a {const.kind} value, which searches "
                f"{', '.join(sorted(SEARCH_TABLE_BANKS[const.kind]))}, not {table.bank}",
                Reason.CONFLICT,
                code=Code.SEARCH_VALUE_BANK,
            )

    @property
    def func_code(self) -> str:
        return str(_OP_TO_FUNC[self.op] + (_ONESHOT_FUNC_OFFSET if self.oneshot else 0))

    def to_csv(self) -> str:
        expr = f"{self.table_start}..{self.table_end} {self.op} {self.value}"
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

        cmp_code = _OP_TO_CMP_CODE[self.op]

        return _build_blob(
            "Search",
            0x2722,
            _SEARCH_TAGS,
            [
                self.value,  # [0]
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
    """Build a Search from its decoded tags, or return None.

    Return None when the blob is not a Search, when an operand field is blank, or when the
    comparison code is unknown.  The clipboard decoder and the program file decoder both
    call this function.
    """
    if class_name != "Search" or type_code != _SEARCH_TYPE_CODE:
        return None

    value = tag_value(tags, 0x6065)
    table_start = tag_value(tags, 0x6066)
    table_end = tag_value(tags, 0x6067)
    result = tag_value(tags, 0x6079)
    found = tag_value(tags, 0x607A)
    cmp_idx = str(tag_int(tags, 0x21F7))
    op = _CMP_CODE_TO_OP.get(cmp_idx)

    if not all([value, table_start, table_end, result, found]) or op is None:
        return None

    return Search(
        table_start=table_start,
        table_end=table_end,
        value=value,
        result=result,
        found=found,
        op=op,
        continuous=tag_flag(tags, 0x1277),
        oneshot=tag_flag(tags, 0x11F8),
    )


def parse_af_call(call: AfCall) -> Search:
    """Parse an AF AST call into a Search."""
    if len(call.args) != 1:
        raise CsvError(f"search expects 1 positional arg (expression), got {len(call.args)}")

    expr = call.args[0]
    # DOTALL: a text value may hold a line break.
    m = re.fullmatch(r"(.+?)\.\.(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+)", expr, re.DOTALL)
    if not m:
        raise CsvError(
            f"Could not read the search expression {expr!r}. Write the table, an operator "
            "and a value, such as DS1..DS10 == DS20."
        )

    result = call.kwargs.get("result")
    found = call.kwargs.get("found")
    if not result or not found:
        raise CsvError(
            "search needs result= and found=, such as "
            "search(DS1..DS10 == DS20,result=DS30,found=C1)."
        )

    return Search(
        table_start=m.group(1).strip(),
        table_end=m.group(2).strip(),
        op=cast(CompareOp, m.group(3)),  # the regex matches only the six operators
        value=m.group(4).strip(),
        result=result,
        found=found,
        continuous=check_csv_flag(call.kwargs, "continuous", "Search.continuous"),
        oneshot=check_csv_flag(call.kwargs, "oneshot", "Search.oneshot"),
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
