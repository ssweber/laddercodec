"""Compare — comparison contacts (type marker 0x2714).

Binary class name: ``"Compare"``.
Operators: EQ, NE, GT, LT, GE, LE.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, cast

from ..binary_helpers import tag_int, tag_value
from ..model import ConditionInstruction, FieldError, InstructionType, check_address
from .family import ConditionInstructionFamilySpec

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

CompareOp = Literal["==", "!=", ">", "<", ">=", "<="]

#: Compare func codes: func_code_str -> operator.
COMPARE_FUNC_CODES: dict[str, Literal["==", "!=", ">", "<", ">=", "<="]] = {
    "4103": "==",
    "4104": "!=",
    "4105": ">",
    "4106": "<",
    "4108": ">=",
    "4109": "<=",
}

#: Reverse lookup: operator → compare func_code string.
COMPARE_OP_TO_FUNC: dict[str, str] = {v: k for k, v in COMPARE_FUNC_CODES.items()}

#: Operator → compare type index string (field 3 in the binary blob).
COMPARE_OP_TO_TYPE_IDX: dict[str, str] = {
    "==": "0",
    "!=": "1",
    ">": "2",
    "<": "3",
    ">=": "4",
    "<=": "5",
}

#: Reverse: type index → operator (used by from_tags).
_TYPE_IDX_TO_OP: dict[str, Literal["==", "!=", ">", "<", ">=", "<="]] = {
    "0": "==",
    "1": "!=",
    "2": ">",
    "3": "<",
    "4": ">=",
    "5": "<=",
}


def split_comparison(token: str) -> tuple[str, str, str] | None:
    """Split ``left<op>right`` at the first operator outside a quoted text constant.

    A quote opens a text constant that runs to the next quote; an unmatched quote is an
    ordinary character.  Returns ``(left, op, right)``, or None when there is no operator
    or a side is empty.
    """
    i = 0
    while i < len(token):
        if token[i] == '"':
            close = token.find('"', i + 1)
            if close > i:
                i = close + 1
                continue
        for op in ("==", "!=", ">=", "<=", ">", "<"):
            if token.startswith(op, i):
                left, right = token[:i].strip(), token[i + len(op) :].strip()
                return (left, op, right) if left and right else None
        i += 1
    return None


# ---------------------------------------------------------------------------
# Operand rules (CLICK v4.00 Help CL164, CL202; Inst_Compare.dll and baseEx.dll)
# ---------------------------------------------------------------------------

#: Compare data banks by group.  A compare pairs two operands of one group.
_GROUP_BANKS: dict[str, frozenset[str]] = {
    "hex": frozenset({"XD", "YD", "DH"}),
    "numeric": frozenset({"TD", "CTD", "DS", "DD", "DF", "SD"}),
    "text": frozenset({"TXT"}),
}
_DATA_BANKS = frozenset().union(*_GROUP_BANKS.values())

_HEX_CONSTANT_RE = re.compile(r"[0-9A-Fa-f]+[hH]")
_INTEGER_CONSTANT_RE = re.compile(r"[+-]?[0-9]+")
_NUMERIC_CONSTANT_RE = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_ASCII_CODE_CONSTANT_RE = re.compile(r"\$[0-9A-Fa-f]{2}")

#: Limits of a compare constant (baseEx.dll CheckInputData @1000e6c0 and its numeric
#: classifier @1000d0e0; Inst_Compare.dll OnOK refuses anything else with OBJ-005).
_HEX_MAX = 0xFFFF
_INTEGER_MIN, _INTEGER_MAX = -2147483648, 2147483647

#: A quoted text constant is one printable ASCII character (Help CL196: "Single ASCII
#: Character, surround with double quotation marks"; a TXT register holds one).  The
#: dialog lets up to 128 characters through (baseEx.dll CheckInputData @1000e81c); the
#: user's decision 2026-11-11 treats that as a gap in CLICK's validation and refuses it.
_TEXT_CHARS = range(0x20, 0x7F)

#: Operators CLICK offers when Data A is text: the dialog hides >, <, >= and <=
#: (Q-B7: Inst_Compare.dll Data A handler 100029d0; user dialog check 2026-11-11: typing
#: TXT1 into Data A with > selected leaves only = and != to choose).
_TEXT_OPS = ("==", "!=")


def _operand_group(value: str, name: str) -> str:
    """Return the Help 202 group of a compare operand; raise if it is neither a data
    register nor a constant CLICK's compare dialog accepts."""
    if _HEX_CONSTANT_RE.fullmatch(value):
        if int(value[:-1], 16) > _HEX_MAX:
            raise FieldError(f"{name}: {value!r} is above FFFFh; a hex constant is 0h to FFFFh")
        return "hex"
    if _INTEGER_CONSTANT_RE.fullmatch(value):
        # The length guard keeps int() inside Python's digit limit for any input.
        too_long = len(value.lstrip("+-").lstrip("0")) > len(str(_INTEGER_MAX))
        if too_long or not _INTEGER_MIN <= int(value) <= _INTEGER_MAX:
            raise FieldError(f"{name}: {value!r} is outside {_INTEGER_MIN} to {_INTEGER_MAX}")
        return "numeric"
    if _NUMERIC_CONSTANT_RE.fullmatch(value):
        return "numeric"
    if _ASCII_CODE_CONSTANT_RE.fullmatch(value):
        return "text"
    if len(value) >= 2 and value[0] == value[-1] == '"':
        # The text is stored as written, quotes included (text_compare.bin).
        inner = value[1:-1]
        if len(inner) != 1 or ord(inner) not in _TEXT_CHARS:
            raise FieldError(
                f"{name}: {value!r} is refused; a text constant is one printable ASCII "
                "character in quotes (use $hh for a character by code)"
            )
        # A quote as the character would end the text in the CSV token (split_comparison),
        # and no capture shows CLICK writing one; $22 spells it.
        if inner == '"':
            raise FieldError(f"{name}: {value!r} is a quote; write the quote character as $22")
        return "text"
    bank = check_address(value, name, _DATA_BANKS).bank
    return next(group for group, banks in _GROUP_BANKS.items() if bank in banks)


# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

_COMPARE_TAGS = (0x3218, 0x6066, 0x6067, 0x21F7, 0x0000)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class CompareContact(ConditionInstruction):
    """A comparison contact (EQ, NE, GT, LT, GE, LE).

    Occupies a condition column.  The binary class name is ``Compare``
    (type marker 0x2714).
    """

    op: Literal["==", "!=", "<", ">", "<=", ">="]
    left: str  # left operand, e.g. "DS1"
    right: str  # right operand or literal, e.g. "1", "DS2", "1.1", "FFFFh", '"A"', "$41"
    wire_down: bool = False

    def __post_init__(self) -> None:
        left = _operand_group(self.left, "CompareContact.left")
        right = _operand_group(self.right, "CompareContact.right")
        if left != right:
            raise FieldError(
                f"CompareContact: {self.left!r} ({left}) and {self.right!r} ({right}) "
                "are not in one compare group; hex, numeric and text operands do not mix"
            )
        if left == "text" and self.op not in _TEXT_OPS:
            raise FieldError(
                f"CompareContact.op: {self.op!r} is not offered when Data A is text "
                f"({self.left!r}); a text compare takes == or !="
            )

    @classmethod
    def from_csv_token(cls, token: str) -> CompareContact:
        """Parse ``DS1==1``, ``DS2>=DS3``, etc.

        Also accepts wire-down prefix: ``T:DS1==1``.
        """
        token = token.strip()

        # Detect wire-down prefix: T:DS1==1 or |:DS1==1
        wire_down = False
        if len(token) > 2 and token[1] == ":" and token[0] in ("T", "|"):
            wire_down = True
            token = token[2:]

        parts = split_comparison(token)
        if parts is None:
            raise ValueError(f"Cannot parse compare contact: {token!r}")
        left, op, right = parts
        return cls(op=cast(CompareOp, op), left=left, right=right, wire_down=wire_down)

    @property
    def func_code(self) -> str:
        return COMPARE_OP_TO_FUNC[self.op]

    @property
    def compare_type_idx(self) -> str:
        return COMPARE_OP_TO_TYPE_IDX[self.op]

    def to_csv(self) -> str:
        inner = f"{self.left}{self.op}{self.right}"
        if self.wire_down:
            return f"T:{inner}"
        return inner

    def cell_params(self) -> dict:
        """Return ClickCell kwargs intrinsic to this instruction."""
        return {"is_contact": True, "wire_down": 1 if self.wire_down else 0}

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this compare contact cell."""
        from ..binary_helpers import _build_blob

        return _build_blob(
            "Compare",
            0x2700 | InstructionType.COMPARE,
            _COMPARE_TAGS,
            [self.func_code, self.left, self.right, self.compare_type_idx, ""],
        )


# ---------------------------------------------------------------------------
# Shared from_tags factory
# ---------------------------------------------------------------------------

_COMPARE_TYPE_CODE = 0x2714


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> CompareContact | None:
    """Construct a CompareContact from tag data (shared by both decoders)."""
    if class_name != "Compare" or type_code != _COMPARE_TYPE_CODE:
        return None
    left = tag_value(tags, 0x6066)
    right = tag_value(tags, 0x6067)
    type_idx = str(tag_int(tags, 0x21F7))
    op = _TYPE_IDX_TO_OP.get(type_idx)
    if not left or not right or op is None:
        return None
    return CompareContact(op=op, left=left, right=right)


SPEC = ConditionInstructionFamilySpec(
    family_name="comparison",
    instruction_types=(CompareContact,),
    binary_class_names=("Compare",),
    from_tags=from_tags,
)
