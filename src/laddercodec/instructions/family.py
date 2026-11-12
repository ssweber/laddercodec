"""Shared instruction family metadata for registry and CSV dispatch."""

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

#: Cell kwargs (``visual_rows``, ``sub_rows``) of a box read from its blob alone: class name,
#: type code and tags.  None when the box is not of the family, or its height needs more
#: than the blob holds.
AfCellParamsFromTags = Callable[[str, int, dict[int, str]], dict | None]


def fixed_cell_params(params: dict, *types: tuple[str, int]) -> AfCellParamsFromTags:
    """Height hook for a family whose boxes all have one height.

    Returns a copy of *params* for a blob whose ``(class_name, type_code)`` is in *types*.
    The family's ``cell_params()`` methods return the same *params*, so a raw box of the
    family and a typed one get one height.
    """

    def hook(class_name: str, type_code: int, _tags: dict[int, str]) -> dict | None:
        return dict(params) if (class_name, type_code) in types else None

    return hook


@dataclass(frozen=True)
class ConditionInstructionFamilySpec:
    """Metadata and hooks for one condition-side instruction family."""

    family_name: str
    instruction_types: tuple[type[ConditionInstruction], ...]
    binary_class_names: tuple[str, ...]
    from_tags: ConditionFromTagsParser | None = None


@dataclass(frozen=True)
class AfInstructionFamilySpec:
    """Metadata and hooks for one AF-side instruction family."""

    family_name: str
    instruction_types: tuple[type[AfInstruction], ...]
    binary_class_names: tuple[str, ...]
    from_tags: AfFromTagsParser | None = None
    csv_names: tuple[str, ...] = ()
    parse_csv_call: AfCallParser | None = None
    pin_names: tuple[str, ...] = ()
    #: Height of a ``RawInstruction`` of this family that has no native cell header
    #: (one read from CSV).  Families whose height comes from pin rows leave it None.
    cell_params_from_tags: AfCellParamsFromTags | None = None
