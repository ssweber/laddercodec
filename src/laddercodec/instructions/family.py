"""Spec types that describe each instruction family, for the registry and the CSV reader.

A family is the group of instruction classes that one module handles, such as the copy
instructions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..model import AfInstruction, ConditionInstruction

if TYPE_CHECKING:
    from ..csv.ast import AfCall


AfCallParser = Callable[["AfCall"], AfInstruction]

# Signature for from_tags() factory functions.
ConditionFromTagsParser = Callable[
    [
        str,  # class_name
        int,  # type_code
        dict[int, str],  # tags
        dict[int, dict[int, int]] | None,  # variant_u16_tags
        dict[int, dict[int, str]] | None,  # variant_string_tags
    ],
    ConditionInstruction | None,
]
AfFromTagsParser = Callable[
    [
        str,  # class_name
        int,  # type_code
        dict[int, str],  # tags
        dict[int, dict[int, int]] | None,  # variant_u16_tags
        dict[int, dict[int, str]] | None,  # variant_string_tags
    ],
    AfInstruction | None,
]

#: A hook that returns the cell kwargs (``visual_rows``, ``sub_rows``) of a box from its
#: blob alone: its class name, type code and tags. It returns None when the box is not of
#: the family, or when the blob does not hold enough to give the box's height.
AfCellParamsFromTags = Callable[[str, int, dict[int, str]], dict | None]


#: Cell kwargs of an Email, Home, Position or Velocity box. CLICK's editor creates these
#: boxes three rows tall, with cell header +0x09 = +0x0A = 3. If you paste a 1-row box
#: and save its dialog, CLICK rewrites +0x09 to 3 and the rung grows.
EMAIL_MOTION_CELL_PARAMS: dict = {"visual_rows": 3}


def cell_rows_spec(params: dict) -> str:
    """Return the ``rows=R,sub=S`` fields of a raw token for a box with cell kwargs *params*."""
    span = int(params.get("visual_rows", 1))
    return f"rows={span},sub={int(params.get('sub_rows', span))}"


def fixed_cell_params(params: dict, *types: tuple[str, int]) -> AfCellParamsFromTags:
    """Return a height hook for a family whose boxes all have the same height.

    The hook returns a copy of *params* for a blob whose ``(class_name, type_code)`` is
    in *types*, and None for any other blob. The family's ``cell_params()`` methods
    return the same *params*, so a raw box of the family and a typed box have the same
    height.
    """

    def hook(class_name: str, type_code: int, _tags: dict[int, str]) -> dict | None:
        return dict(params) if (class_name, type_code) in types else None

    return hook


@dataclass(frozen=True)
class ConditionInstructionFamilySpec:
    """Metadata and hooks for one family of condition-column instructions."""

    family_name: str
    instruction_types: tuple[type[ConditionInstruction], ...]
    binary_class_names: tuple[str, ...]
    from_tags: ConditionFromTagsParser | None = None


@dataclass(frozen=True)
class AfInstructionFamilySpec:
    """Metadata and hooks for one family of AF-column (output) instructions."""

    family_name: str
    instruction_types: tuple[type[AfInstruction], ...]
    binary_class_names: tuple[str, ...]
    from_tags: AfFromTagsParser | None = None
    csv_names: tuple[str, ...] = ()
    parse_csv_call: AfCallParser | None = None
    pin_names: tuple[str, ...] = ()
    #: A hook that gives the height of a ``RawInstruction`` of this family that has no
    #: cell header from CLICK, such as one read from CSV. A family whose height comes
    #: from its pin rows leaves it None.
    cell_params_from_tags: AfCellParamsFromTags | None = None
