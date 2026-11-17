"""Typed AST for Click Ladder CSV parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..errors import CsvError
from ..instructions import KNOWN_AF_NAMES as _KNOWN_AF_NAMES
from .contract import CONDITION_COLUMNS

KNOWN_AF_NAMES = _KNOWN_AF_NAMES


@dataclass(frozen=True)
class CanonicalRow:
    marker: str
    conditions: tuple[str, ...]
    af: str

    def __post_init__(self) -> None:
        if len(self.conditions) != len(CONDITION_COLUMNS):
            raise CsvError(
                f"CanonicalRow.conditions must contain {len(CONDITION_COLUMNS)} values; "
                f"got {len(self.conditions)}"
            )

    @property
    def is_comment(self) -> bool:
        return self.marker == "#"

    @property
    def comment_text(self) -> str | None:
        if not self.is_comment:
            return None
        return self.conditions[0]


@dataclass(frozen=True)
class BlankCondition:
    pass


@dataclass(frozen=True)
class HorizontalWire:
    pass


@dataclass(frozen=True)
class JunctionDownWire:
    pass


@dataclass(frozen=True)
class VerticalPassThroughWire:
    pass


@dataclass(frozen=True)
class ContactCondition:
    operand: str
    negated: bool
    immediate: bool
    wire_down: bool = False


@dataclass(frozen=True)
class EdgeCondition:
    kind: Literal["rise", "fall"]
    operand: str
    wire_down: bool = False
    immediate: bool = False  # Never valid. The Contact built from this node refuses it.


@dataclass(frozen=True)
class ComparisonCondition:
    left: str
    op: Literal["==", "!=", "<", ">", "<=", ">="]
    right: str
    wire_down: bool = False


@dataclass(frozen=True)
class GenericCondition:
    raw: str


ConditionCellNode = (
    BlankCondition
    | HorizontalWire
    | JunctionDownWire
    | VerticalPassThroughWire
    | ContactCondition
    | EdgeCondition
    | ComparisonCondition
    | GenericCondition
)


@dataclass(frozen=True)
class AfBlank:
    pass


@dataclass(frozen=True)
class AfCall:
    name: str
    args: tuple[str, ...]
    known: bool
    kwargs: dict[str, str] = field(default_factory=dict)
    raw: str | None = None

    def to_token(self) -> str:
        """Return the CSV token of this call.

        Return ``raw`` if it is set. Otherwise build the token from the name and the arguments.
        """
        if self.raw is not None:
            return self.raw
        parts = list(self.args)
        parts.extend(f"{k}={v}" for k, v in self.kwargs.items())
        if not parts:
            return f"{self.name}()"
        return f"{self.name}({','.join(parts)})"


AfNode = AfBlank | AfCall


@dataclass(frozen=True)
class RowAst:
    canonical: CanonicalRow
    condition_nodes: tuple[ConditionCellNode, ...]
    af_node: AfNode
    #: The CSV line that the row starts on, counted from 1. It is ``None`` if the row was not
    #: read from a file.
    line: int | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if len(self.condition_nodes) != len(self.canonical.conditions):
            raise CsvError("RowAst.condition_nodes length must match canonical.conditions length")


@dataclass(frozen=True)
class RungAst:
    rows: tuple[RowAst, ...]
    comment_rows: tuple[RowAst, ...] = ()


@dataclass(frozen=True)
class ParsedCsvFileAst:
    path: Path
    role: Literal["main", "subroutine"]
    subroutine_slug: str | None
    rows: tuple[RowAst, ...]
    rungs: tuple[RungAst, ...]


@dataclass(frozen=True)
class ProgramBundleAst:
    directory: Path
    main: ParsedCsvFileAst
    subroutines: tuple[ParsedCsvFileAst, ...]
