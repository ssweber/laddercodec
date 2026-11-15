"""Marker rungs: what the decoders and ``write_csv`` put in place of a rung they can't read.

The unit is the rung, because its rows share wires.  A rung that fails becomes one marker
rung (:func:`marker_rung`), and the decoder warns with :class:`UndecodedRungWarning`.  A
comment that fails, on a rung whose logic decodes, is not a marker: the rung keeps its
logic, its comment becomes :func:`comment_note`, and the decoder warns with
:class:`UndecodedCommentWarning`.
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


class UndecodedCommentWarning(UserWarning):
    """A rung's comment could not be decoded; the rung keeps its logic.

    The rung's comment is ``UNDECODED comment: <error>``, and its ``comment_rtf`` keeps the
    comment's bytes.  The rung is not a marker, so ``Program.undecoded`` does not list it.

    Attributes
    ----------
    rung:
        Index of the rung, from 0.
    error:
        Why the comment could not be decoded, on one line.
    program:
        Program name for :func:`laddercodec.decode_program`, else ``None``.
    """

    def __reduce__(self):
        return (type(self), (self.rung, self.error, self.program))

    def __init__(self, rung: int, error: str, program: str | None = None) -> None:
        self.rung = rung
        self.error = error
        self.program = program
        prefix = f"program {program!r}, " if program is not None else ""
        super().__init__(
            f"{prefix}the comment of rung {rung} is not decoded, and the rung keeps its "
            f"logic: {error}"
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


def comment_note(error: str) -> str:
    """The comment a rung gets in place of one that could not be decoded."""
    return f"UNDECODED comment: {error}"


def read_comment(rtf: bytes | None, rung: int, failed: list[tuple[int, str]]) -> str | None:
    """Rung *rung*'s comment from *rtf*, or :func:`comment_note` when it can't be decoded.

    A failure is added to *failed* as ``(rung, error)`` for :func:`warn_comments`.
    """
    if rtf is None:
        return None
    from .decode import _decode_rtf  # decode imports this module

    try:
        return _decode_rtf(rtf)
    except BAD_BYTES as exc:
        error = reason(exc)
        failed.append((rung, error))
        return comment_note(error)


def warn_comments(failed: Iterable[tuple[int, str]], *, program: str | None = None) -> None:
    """Emit one :class:`UndecodedCommentWarning` per ``(rung, error)`` in *failed*."""
    for rung, error in failed:
        warnings.warn(UndecodedCommentWarning(rung, error, program), stacklevel=3)


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
    "UndecodedCommentWarning",
    "UndecodedRungWarning",
    "comment_note",
    "marker_rung",
    "markers",
    "one_line",
    "read_comment",
    "reason",
    "to_the_end",
    "warn_comments",
    "warn_undecoded",
]
