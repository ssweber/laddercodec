"""Observed Productivity XML records, independent of CLICK's instruction model."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TagReference:
    name: str
    system_id: str
    data_type: int


@dataclass(frozen=True)
class Instruction:
    """An XML instruction, including properties not interpreted by the codec."""

    kind: str
    xml: bytes
    tags: tuple[TagReference, ...]


@dataclass(frozen=True)
class Element:
    """A cell record; repeat counts additional consecutive cells."""

    position: int
    repeat: int
    element_type: int
    subtype: int
    instruction: Instruction | None

    @property
    def positions(self) -> range:
        return range(self.position, self.position + self.repeat + 1)


@dataclass(frozen=True)
class Rung:
    """One stored row; a logical rung may have several subrung rows."""

    number: int
    subrung: int
    comment: str
    disabled: bool
    elements: tuple[Element, ...]


@dataclass(frozen=True)
class Program:
    """Inspection view with original XML retained for unknown fields."""

    rungs: tuple[Rung, ...]
    xml: bytes
