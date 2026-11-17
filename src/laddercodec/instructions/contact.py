"""Contact — NO/NC/edge contacts (type markers 0x2711, 0x2712, 0x2713).

In the binary, an NO or NC contact has the class name ``"ContactNO"``, and a rise or fall
contact has the class name ``"Edge"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, cast

from ..binary_helpers import tag_flag, tag_int, tag_value
from ..codes import Code
from ..model import (
    TYPE_CODE_TO_ITYPE,
    ConditionInstruction,
    InstructionType,
    Reason,
    check_address,
)
from ..operands.checks import BIT_BANKS, Refusals
from .family import ConditionInstructionFamilySpec

#: A contact's kind.  The CSV tokens of the four kinds are ``X001``, ``~X001``,
#: ``rise(X001)`` and ``fall(X001)``.
ContactKind = Literal["no", "nc", "rise", "fall"]

# ---------------------------------------------------------------------------
# Func code and type marker tables
# ---------------------------------------------------------------------------

#: (kind, immediate) -> func_code.  An edge contact has no immediate form.
CONTACT_FUNC_CODES: dict[tuple[ContactKind, bool], str] = {
    ("no", False): "4097",
    ("nc", False): "4098",
    ("no", True): "4099",
    ("nc", True): "4100",
    ("rise", False): "4101",
    ("fall", False): "4102",
}

_KIND_TO_ITYPE: dict[ContactKind, InstructionType] = {
    "no": InstructionType.CONTACT_NO,
    "nc": InstructionType.CONTACT_NC,
    "rise": InstructionType.CONTACT_EDGE,
    "fall": InstructionType.CONTACT_EDGE,
}

_EDGE_KINDS: tuple[ContactKind, ...] = ("rise", "fall")

# ---------------------------------------------------------------------------
# Tag constants
# ---------------------------------------------------------------------------

_CONTACT_NO_TAGS = (0x6065, 0x11F5, 0x3218, 0x0000)
_EDGE_TAGS = (0x6065, 0x21F6, 0x3218, 0x0000)

# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Contact(ConditionInstruction):
    """A contact: normally open (``no``), normally closed (``nc``), or an edge contact
    (``rise``, ``fall``).

    ``Contact("X001", kind="nc", immediate=True)`` is the CSV token ``~X001.immediate``.
    Only an NO or NC contact on X has an immediate form.
    """

    operand: str  # e.g. "X001"
    kind: ContactKind = "no"
    immediate: bool = False
    wire_down: bool = False

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            check.flag("immediate", "wire_down")
            check.normalize("operand")
            address = check("operand", check_address, BIT_BANKS)
            if self.immediate is True and self.kind in _EDGE_KINDS:
                check.refuse(
                    ("immediate", "kind"),
                    "an edge contact has no immediate form",
                    Reason.CONFLICT,
                    code=Code.IMMEDIATE_EDGE_CONTACT,
                )
            if self.immediate is True and address is not None and address.bank != "X":
                check.refuse(
                    ("immediate", "operand"),
                    f"{self.operand!r} is not allowed; an immediate contact takes X only",
                    Reason.CONFLICT,
                    code=Code.IMMEDIATE_CONTACT_NOT_X,
                )
            # The kind is checked last, so a refused operand is reported first.
            if self.kind not in tuple(_KIND_TO_ITYPE):  # a dict would raise for an unhashable kind
                check.refuse(
                    "kind",
                    f"{self.kind!r} is not a contact kind (no, nc, rise or fall)",
                    Reason.CHOICE,
                    code=Code.INVALID_CHOICE,
                )

    @classmethod
    def from_csv_token(cls, token: str) -> Contact:
        """Parse NO/NC/immediate forms plus edge forms `rise(...)`/`fall(...)`.

        It also accepts the wire-down prefix ``T:`` or ``|:``, as in ``T:X001`` and
        ``T:rise(X002)``.
        """

        token = token.strip()

        # Detect wire-down prefix: T:X001 or |:rise(X002)
        wire_down = False
        if len(token) > 2 and token[1] == ":" and token[0] in ("T", "|"):
            wire_down = True
            token = token[2:]

        # Detect negation prefix
        negated = token.startswith("~")
        if negated:
            token = token[1:]

        # Detect immediate — suffix (.immediate) or wrapper (immediate(...))
        immediate = token.endswith(".immediate")
        if immediate:
            token = token[: -len(".immediate")]

        if not immediate:
            inner = re.fullmatch(r"immediate\((.+)\)", token)
            if inner:
                immediate = True
                token = inner.group(1).strip()

        edge_match = re.fullmatch(r"(rise|fall)\((.+)\)", token)
        if edge_match:
            # An immediate edge contact is refused when it is built.
            return cls(
                edge_match.group(2).strip(),
                kind=cast(ContactKind, edge_match.group(1)),
                immediate=immediate,
                wire_down=wire_down,
            )

        return cls(
            token.strip(),
            kind="nc" if negated else "no",
            immediate=immediate,
            wire_down=wire_down,
        )

    @property
    def func_code(self) -> str:
        return CONTACT_FUNC_CODES[(self.kind, self.immediate)]

    def to_csv(self) -> str:
        suffix = ".immediate" if self.immediate else ""
        if self.kind in _EDGE_KINDS:
            # An immediate edge contact exists only when a read with unchecked=True kept
            # the refusal instead of raising it.
            inner = f"{self.kind}({self.operand}){suffix}"
        else:
            prefix = "~" if self.kind == "nc" else ""
            inner = f"{prefix}{self.operand}{suffix}"
        if self.wire_down:
            return f"T:{inner}"
        return inner

    def cell_params(self) -> dict:
        """Return the ClickCell keyword arguments that this instruction sets."""
        return {"is_contact": True, "wire_down": 1 if self.wire_down else 0}

    def build_blob(self) -> bytes:
        """Build the instruction data blob for this contact cell."""
        from ..binary_helpers import _build_blob

        type_marker = 0x2700 | _KIND_TO_ITYPE[self.kind]
        if self.kind in _EDGE_KINDS:
            field1 = "0" if self.kind == "rise" else "1"
            return _build_blob(
                "Edge",
                type_marker,
                _EDGE_TAGS,
                [self.operand, field1, self.func_code, ""],
            )

        field1 = "1" if self.immediate else "0"
        return _build_blob(
            "ContactNO",
            type_marker,
            _CONTACT_NO_TAGS,
            [self.operand, field1, self.func_code, ""],
        )


# ---------------------------------------------------------------------------
# Shared from_tags factory
# ---------------------------------------------------------------------------


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Contact | None:
    """Build a Contact from tag data, or return None if the tags are not a contact's.

    The clipboard decoder and the program-file decoder both call it.
    """
    itype = TYPE_CODE_TO_ITYPE.get(type_code)

    if class_name == "ContactNO" and itype in (
        InstructionType.CONTACT_NO,
        InstructionType.CONTACT_NC,
    ):
        operand = tag_value(tags, 0x6065)
        if not operand:
            return None
        immediate = tag_flag(tags, 0x11F5)
        kind: ContactKind = "nc" if itype == InstructionType.CONTACT_NC else "no"
        return Contact(operand, kind=kind, immediate=immediate)

    if class_name == "Edge" and itype == InstructionType.CONTACT_EDGE:
        operand = tag_value(tags, 0x6065)
        if not operand:
            return None
        # SCR: tag absent = rise, present = fall.
        # Clipboard: tag always present, byte value 0 = rise, 1 = fall.
        edge: ContactKind = "fall" if tag_int(tags, 0x21F6) != 0 else "rise"
        return Contact(operand, kind=edge)

    return None


SPEC = ConditionInstructionFamilySpec(
    family_name="contact",
    instruction_types=(Contact,),
    binary_class_names=("ContactNO", "Edge"),
    from_tags=from_tags,
)
