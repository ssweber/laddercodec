"""The ``CompareContact`` instruction, a contact that compares two values.

Its binary class name is ``"Compare"`` and its type marker is 0x2714. It uses one of six
operators: EQ, NE, GT, LT, GE and LE.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, cast

from ..binary_helpers import tag_int, tag_value
from ..codes import Code
from ..errors import CsvReadError
from ..model import (
    Condition,
    InstructionType,
    Reason,
)
from ..operands.address import ADDRESS_BANKS, read_typed_address
from ..operands.checks import ALL_KINDS, Constants, Refusals, check_kept_text, check_operand
from ..operands.constants import HEX16_MAX, Kind
from ..operands.message import operand, says
from ..operands.unchecked import read_in_another_form
from .contact import refuse_down_prefix
from .family import ConditionInstructionFamilySpec

# ---------------------------------------------------------------------------
# Func code tables
# ---------------------------------------------------------------------------

CompareOp = Literal["==", "!=", ">", "<", ">=", "<="]
"""The operator of a compare contact or a Search."""

#: The operator of each compare func code.
COMPARE_FUNC_CODES: dict[str, CompareOp] = {
    "4103": "==",
    "4104": "!=",
    "4105": ">",
    "4106": "<",
    "4108": ">=",
    "4109": "<=",
}

#: The compare func code of each operator.
COMPARE_OP_TO_FUNC: dict[str, str] = {v: k for k, v in COMPARE_FUNC_CODES.items()}

#: The compare type index of each operator. The blob stores it in field 3, counting from 0.
COMPARE_OP_TO_TYPE_IDX: dict[str, str] = {
    "==": "0",
    "!=": "1",
    ">": "2",
    "<": "3",
    ">=": "4",
    "<=": "5",
}

#: The operator of each compare type index, for ``from_tags``.
_TYPE_IDX_TO_OP: dict[str, CompareOp] = {
    "0": "==",
    "1": "!=",
    "2": ">",
    "3": "<",
    "4": ">=",
    "5": "<=",
}


def split_comparison(token: str) -> tuple[str, str, str] | None:
    """Split ``left<op>right`` at the first operator outside a quoted text constant.

    A double quote starts a text constant that ends at the next double quote, and an
    operator inside the constant does not count. A double quote with no closing quote is an
    ordinary character. Returns ``(left, op, right)``, or None when there is no operator or
    one side is empty.
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
# Operand rules
# ---------------------------------------------------------------------------

#: The data banks that a compare accepts, in three groups. Both operands of a compare must be
#: in the same group. A Search value address and its table are in one group too.
GROUP_BANKS: dict[str, frozenset[str]] = {
    "hex": frozenset({"XD", "YD", "DH"}),
    "numeric": frozenset({"TD", "CTD", "DS", "DD", "DF", "SD"}),
    "text": frozenset({"TXT"}),
}
_DATA_BANKS = frozenset().union(*GROUP_BANKS.values())


def bank_group(bank: str) -> str | None:
    """Return the group of ``bank`` in :data:`GROUP_BANKS`, or None for a bank in no group."""
    return next((group for group, banks in GROUP_BANKS.items() if bank in banks), None)


#: The constants Data A takes. A compare accepts every kind of constant. A hex constant must
#: fit in 16 bits. A real constant must fit float32, and CLICK refuses a larger one with
#: OBJ-005. Text holds printable ASCII only.
_DATA_A = Constants(ALL_KINDS, hex_high=HEX16_MAX, real_id="OBJ-005")
#: The constants that Data B accepts. They are Data A's, with two differences. ``$`` and
#: one hex digit (``$1``) is a character code, kept as typed. Text may hold any character
#: that CLICK keeps, and :func:`_operand_group` checks it. The contact also refuses a hex
#: constant that spells a bank name (``DH``) in Data B, opposite a hex Data A.
_DATA_B = replace(_DATA_A, one_digit_char=True, printable=False)

_CONSTANT_GROUPS = {Kind.HEX: "hex", Kind.INTEGER: "numeric", Kind.FLOAT: "numeric"}

#: The operators that CLICK offers when Data A is text. If you type TXT1 into Data A, the
#: dialog hides >, <, >= and <=, and leaves only = and != to choose from.
_TEXT_OPS = ("==", "!=")


def _operand_group(value: str, name: str, constants: Constants) -> str:
    """Return the group of a compare operand: ``"hex"``, ``"numeric"`` or ``"text"``.

    Raise :class:`FieldError` if the operand is neither an address in a data bank that a
    compare accepts nor one of the ``constants`` that its side of the dialog accepts."""
    operand = check_operand(value, name, _DATA_BANKS, constants)
    const = operand.constant
    if const is not None:
        if const.kind is Kind.TEXT and not constants.printable:
            check_kept_text(value, str(const.value), name)
        return _CONSTANT_GROUPS.get(const.kind, "text")
    return next(group for group, banks in GROUP_BANKS.items() if operand.bank in banks)


# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

_COMPARE_TAGS = (0x3218, 0x6066, 0x6067, 0x21F7, 0x0000)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompareContact(Condition):
    """A comparison contact (EQ, NE, GT, LT, GE, LE).

    It sits in a condition column, like any contact. Its binary class name is ``Compare``
    and its type marker is 0x2714.
    """

    op: CompareOp
    left: str  # left operand, e.g. "DS1"
    right: str  # right operand or literal, e.g. "1", "DS2", "1.1", "FFFFh", '"A"', "$41"

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            if not isinstance(self.op, str) or self.op not in COMPARE_OP_TO_FUNC:
                check.refuse(
                    "op",
                    says(
                        "{op} is not allowed",
                        "it is one of {ops}",
                        op=operand(self.op),
                        ops=", ".join(COMPARE_OP_TO_FUNC),
                    ),  # fmt: skip
                    Reason.CHOICE,
                    code=Code.INVALID_CHOICE,
                )
            # normalize_address returns a constant as it was written, so an operand that is a
            # constant is safe to normalize.
            check.normalize("left", "right", values=("left", "right"))
            left = check("left", _operand_group, _DATA_A)
            right = check("right", _operand_group, _DATA_B)
            if left is not None and right is not None and left != right:
                check.refuse(
                    ("left", "right"),
                    says(
                        "{left} ({left_group}) and {right} ({right_group}) "
                        "are not in one compare group",
                        "hex, numeric and text operands do not mix",
                        left=operand(self.left),
                        left_group=left,
                        right=operand(self.right),
                        right_group=right,
                    ),  # fmt: skip
                    Reason.CONFLICT,
                    code=Code.COMPARE_MIXED_TYPES,
                )
            elif right == "hex" and self.right.upper() in ADDRESS_BANKS:
                # CLICK saves Data B empty for a hex constant that spells a bank name (DH).
                check.refuse(
                    "right",
                    says(
                        "{right} is the bank name {bank}, not a hex constant",
                        right=operand(self.right),
                        bank=self.right.upper(),
                    ),  # fmt: skip
                    Reason.FORM,
                    code=Code.INVALID_CONSTANT,
                    then=f"Write the hex constant with a leading 0, such as 0{self.right.upper()}.",
                )
            if left == "text" and self.op not in _TEXT_OPS:
                check.refuse(
                    ("op", "left"),
                    says(
                        "{op} is not offered when Data A is text ({left})",
                        "a text compare takes == or !=",
                        op=operand(self.op),
                        left=operand(self.left),
                    ),  # fmt: skip
                    Reason.CONFLICT,
                    code=Code.TEXT_ORDER_COMPARE,
                )

    @classmethod
    def from_csv_token(cls, token: str) -> CompareContact:
        """Parse the CSV token of a compare contact, such as ``DS1==1`` or ``DS2>=DS3``.

        A token with the wire-down prefix ``T:`` or ``|:``, such as ``T:DS1==1``, raises
        :class:`~laddercodec.CsvReadError`. A contact holds no wire. Wrap the contact in a
        :class:`~laddercodec.Tee` instead.
        """
        token = token.strip()
        refuse_down_prefix(token, cls.__name__)

        parts = split_comparison(token)
        if parts is None:
            raise CsvReadError(
                f"Could not read {token!r} as a compare contact. Write two operands joined by "
                "==, !=, <, >, <= or >=, such as DS1==1."
            )
        left, op, right = parts
        return cls(op=cast(CompareOp, op), left=left, right=right)

    @property
    def func_code(self) -> str:
        return COMPARE_OP_TO_FUNC[self.op]

    @property
    def compare_type_idx(self) -> str:
        return COMPARE_OP_TO_TYPE_IDX[self.op]

    def to_csv(self) -> str:
        return f"{self.left}{self.op}{self.right}"

    def cell_params(self) -> dict:
        """Return the ``ClickCell`` keyword arguments that depend on this instruction alone."""
        return {"is_contact": True}

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
    """Build a ``CompareContact`` from the tags of an instruction blob, or return None.

    Return None if the blob is not a compare contact, or if it lacks an operand or a known
    operator. The clipboard decoder and the program-file decoder both call this.
    """
    if class_name != "Compare" or type_code != _COMPARE_TYPE_CODE:
        return None
    left = tag_value(tags, 0x6066)
    stored_right = tag_value(tags, 0x6067)
    # CLICK saves an address in Data B as typed, with any space at its ends (" DS1",
    # "ds1", "DS001", "XD0U"). It saves Data A in display form.
    right = read_typed_address(stored_right, trim=True)
    type_idx = str(tag_int(tags, 0x21F7))
    op = _TYPE_IDX_TO_OP.get(type_idx)
    if not left or not right or op is None:
        return None
    built = CompareContact(op=op, left=left, right=right)
    if right != stored_right:
        # While the contact is unchanged, it encodes as the bytes CLICK stored.
        read_in_another_form(built)
    return built


SPEC = ConditionInstructionFamilySpec(
    family_name="comparison",
    instruction_types=(CompareContact,),
    binary_class_names=("Compare",),
    from_tags=from_tags,
)
