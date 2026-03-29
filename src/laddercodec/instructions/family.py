"""Shared instruction family metadata for registry and CSV dispatch."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..model import AfInstruction, ConditionInstruction

if TYPE_CHECKING:
    from ..csv.ast import AfCall


ConditionBlobParser = Callable[[bytes], ConditionInstruction | None]
AfBlobParser = Callable[[bytes], AfInstruction | None]
AfCallParser = Callable[["AfCall"], AfInstruction]

# Signature for from_tags() factory functions.
FromTagsParser = Callable[
    [
        str,  # class_name
        int,  # type_code
        dict[int, str],  # tags
        dict[int, int] | None,  # tag_byte_lens
        dict[int, dict[int, int]] | None,  # variant_u16_tags
        dict[int, dict[int, str]] | None,  # variant_string_tags
    ],
    ConditionInstruction | AfInstruction | None,
]


@dataclass(frozen=True)
class ConditionInstructionFamilySpec:
    """Metadata and hooks for one condition-side instruction family."""

    family_name: str
    instruction_types: tuple[type[ConditionInstruction], ...]
    binary_class_names: tuple[str, ...]
    parse_blob: ConditionBlobParser
    from_tags: FromTagsParser | None = None


@dataclass(frozen=True)
class AfInstructionFamilySpec:
    """Metadata and hooks for one AF-side instruction family."""

    family_name: str
    instruction_types: tuple[type[AfInstruction], ...]
    binary_class_names: tuple[str, ...]
    parse_blob: AfBlobParser
    from_tags: FromTagsParser | None = None
    csv_names: tuple[str, ...] = ()
    parse_csv_call: AfCallParser | None = None
    pin_names: tuple[str, ...] = ()
    min_csv_rows: int = 1
