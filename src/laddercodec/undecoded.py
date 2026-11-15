"""Marker rungs: what the decoders and ``write_csv`` put in place of a rung they can't read.

The unit is the rung, because its rows share wires.  A rung that fails becomes one marker
rung (:func:`marker_rung`), and the decoder warns with :class:`UndecodedRungWarning`.
"""

from __future__ import annotations

import struct
import warnings
from collections.abc import Iterable
from typing import TYPE_CHECKING

from .instructions.undecoded import Stop, Undecoded
from .topology import CONDITION_COLUMNS

if TYPE_CHECKING:
    from .decode import Rung


class UndecodedRungWarning(UserWarning):
    """A rung could not be decoded, and an undecoded marker stands in its place.

    Attributes
    ----------
    marker:
        The :class:`~laddercodec.instructions.Undecoded` marker: why, and where.
    program:
        Program name for :func:`laddercodec.decode_program`, else ``None``.
    """

    def __reduce__(self):
        return (type(self), (self.marker, self.program))

    def __init__(self, marker: Undecoded, program: str | None = None) -> None:
        self.marker = marker
        self.program = program
        prefix = f"program {program!r}, " if program is not None else ""
        super().__init__(
            f"{prefix}{marker.where} is not decoded, and an undecoded marker stands in for it: "
            f"{marker.error}"
        )


#: What a decoder catches as bytes it can't read: a malformed value, or a read past the end.
BAD_BYTES: tuple[type[Exception], ...] = (ValueError, IndexError, KeyError, struct.error)


def one_line(text: str) -> str:
    """*text* with its line breaks as spaces, for :attr:`Undecoded.error`."""
    return " ".join(text.split())


def reason(exc: BaseException) -> str:
    """The error an exception gives, on one line, for :attr:`Undecoded.error`."""
    return one_line(str(exc)) or type(exc).__name__


def to_the_end(error: str, rung: int) -> str:
    """*error* for a marker that stands for rung *rung* and every rung after it."""
    return f"{error}; decoding stopped, so this marker stands for rung {rung} to the end"


def marker_rung(marker: Undecoded, comment: str | None = None) -> Rung:
    """The one-row rung that stands for a rung that could not be decoded.

    Its comment is the marker's headline, then *comment* (the rung's own, when that
    decoded).  Its one row is wired from the rail, unconditional, into the marker.
    """
    from .decode import Rung

    lines = [marker.headline, comment] if comment else [marker.headline]
    return Rung(
        logical_rows=1,
        conditions=[["-"] * CONDITION_COLUMNS],
        instructions=[marker],
        comment="\n".join(lines),
    )


def markers(rungs: Iterable[Rung]) -> list[Undecoded]:
    """Every undecoded marker in *rungs*, in rung order."""
    return [af for rung in rungs for af in rung.instructions if isinstance(af, Undecoded)]


def warn_undecoded(rungs: Iterable[Rung], *, program: str | None = None) -> None:
    """Emit one :class:`UndecodedRungWarning` per marker in *rungs*."""
    for marker in markers(rungs):
        warnings.warn(UndecodedRungWarning(marker, program), stacklevel=3)


__all__ = [
    "BAD_BYTES",
    "Stop",
    "Undecoded",
    "UndecodedRungWarning",
    "marker_rung",
    "markers",
    "one_line",
    "reason",
    "to_the_end",
    "warn_undecoded",
]
