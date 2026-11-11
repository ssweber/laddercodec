"""Compare — comparison contacts (type marker 0x2714).

Binary class name: ``"Compare"``.
Operators: EQ, NE, GT, LT, GE, LE.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ..binary_helpers import tag_int, tag_value
from ..model import ConditionInstruction, FieldError, InstructionType, check_address
from .family import ConditionInstructionFamilySpec

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Operand rules (CLICK v4.00 Help CL164, CL196, CL202)
# ---------------------------------------------------------------------------

#: Compare data banks by group.  A compare pairs two operands of one group.
_GROUP_BANKS: dict[str, frozenset[str]] = {
    "hex": frozenset({"XD", "YD", "DH"}),
    "numeric": frozenset({"TD", "CTD", "DS", "DD", "DF", "SD"}),
    "text": frozenset({"TXT"}),
}
_DATA_BANKS = frozenset().union(*_GROUP_BANKS.values())

_HEX_CONSTANT_RE = re.compile(r"[0-9A-Fa-f]+h")
_NUMERIC_CONSTANT_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_TEXT_CONSTANT_RE = re.compile(r'"[^"]?"|\$[0-9A-Fa-f]{2}')


def _operand_group(value: str, name: str) -> str:
    """Return the Help 202 group of a compare operand; raise if it is neither a data
    register nor a constant."""
    if _HEX_CONSTANT_RE.fullmatch(value):
        return "hex"
    if _NUMERIC_CONSTANT_RE.fullmatch(value):
        return "numeric"
    if _TEXT_CONSTANT_RE.fullmatch(value):
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
    right: str  # right operand or literal, e.g. "1", "DS2", "1.1", "FFFFh", '"A"'
    wire_down: bool = False

    def __post_init__(self) -> None:
        left = _operand_group(self.left, "CompareContact.left")
        right = _operand_group(self.right, "CompareContact.right")
        if left != right:
            raise FieldError(
                f"CompareContact: {self.left!r} ({left}) and {self.right!r} ({right}) "
                "are not in one compare group; hex, numeric and text operands do not mix"
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

        # Split at the first operator outside a quoted text constant.
        i = 0
        while i < len(token):
            if token[i] == '"' and token[i + 2 : i + 3] == '"':
                i += 3
                continue
            for op in ("==", "!=", ">=", "<=", ">", "<"):
                if token.startswith(op, i):
                    left = token[:i]
                    right = token[i + len(op) :]
                    if i > 0 and left and right:
                        return cls(op=op, left=left, right=right, wire_down=wire_down)
                    raise ValueError(f"Cannot parse compare contact: {token!r}")
            i += 1
        raise ValueError(f"Cannot parse compare contact: {token!r}")

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
