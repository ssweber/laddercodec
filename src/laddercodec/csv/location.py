"""Where in a CSV ``read_csv`` found the value it raised about."""

from __future__ import annotations

import csv
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import TypeVar

from .contract import CONDITION_COLUMNS, OUTPUT_COLUMN

_E = TypeVar("_E", bound=BaseException)
_COLUMN_NAMES = (*CONDITION_COLUMNS, OUTPUT_COLUMN)

#: The column index of ``AF``.
AF_COLUMN = len(CONDITION_COLUMNS)


@dataclass(frozen=True)
class CsvLocation:
    """Where in a CSV an error ``read_csv`` raised was found.

    Every exception ``read_csv`` raises for a bad CSV carries one as its ``location``
    attribute, whatever its class: ``ValueError``, ``FieldError``, ``AddressError``,
    ``csv.Error`` and the rest keep their class and gain the attribute.  :meth:`of` reads
    it.  A ``ValueError`` (``FieldError`` included) or ``csv.Error`` message ends with
    `` (at <location>)``; a ``UnicodeDecodeError`` keeps its message and its location
    holds ``file`` only.  A ``FieldError`` refused while a box takes its pin rows (a
    ``.jump()`` target, a ``.reset()`` on a timer that can't be retentive) arrives as the
    ``ConvertError`` it always was, with the field in its ``field``.  Each field is ``None``
    where it is not known or does not apply.

    Attributes
    ----------
    file:
        The CSV file being read.
    line:
        The line of the CSV file the row at fault starts on, counted from 1 as an editor
        counts them, blank lines included: the header is line 1 only when no blank line
        comes before it.  ``None`` for an error about the whole file.
    rung_line:
        The line of the ``R`` row that starts the rung the row is in, counted the same way.
        ``None`` when the row is in no rung: the header, a comment row, and a row with no
        ``R`` row between it and the last comment row or the header above it.
    row:
        The row within that rung, from 0: the ``R`` row is row 0, and the comment rows above
        it are not counted.  Rows are counted as the CSV holds them, before layout.  ``None``
        when ``rung_line`` is.  A refusal of what a pin row holds is at that pin row; a pin
        row that is missing is at the box's row.
    column:
        The cell's column, from 0: 0 is ``A``, 30 is ``AE`` and 31 is ``AF``, as
        :class:`laddercodec.Finding` counts them.  ``None`` for an error about a whole row or
        its marker.  :attr:`column_name` gives the letters.
    """

    file: Path | None = None
    line: int | None = None
    rung_line: int | None = None
    row: int | None = None
    column: int | None = None

    @property
    def column_name(self) -> str | None:
        """The column's letters, ``A`` to ``AE`` and ``AF``, or ``None``."""
        return None if self.column is None else _COLUMN_NAMES[self.column]

    @staticmethod
    def of(exc: BaseException) -> CsvLocation | None:
        """The location *exc* carries, or ``None`` when it carries none."""
        location = getattr(exc, "location", None)
        return location if isinstance(location, CsvLocation) else None

    def __str__(self) -> str:
        parts: list[str] = []
        if self.file is not None:
            parts.append(str(self.file))
        if self.line is not None:
            parts.append(f"line {self.line}")
        if self.rung_line is not None:
            parts.append(f"rung at line {self.rung_line}")
        if self.row is not None:
            parts.append(f"row {self.row} from 0")
        if self.column is not None:
            parts.append(f"column {self.column_name}")
        return ", ".join(parts)


def add_location(exc: BaseException, **known: object) -> None:
    """Give *exc* the fields of *known* its location does not have yet."""
    old = CsvLocation.of(exc) or CsvLocation()
    new = {
        f.name: known[f.name]
        for f in fields(CsvLocation)
        if known.get(f.name) is not None and getattr(old, f.name) is None
    }
    object.__setattr__(exc, "location", replace(old, **new))


def at(exc: _E, **known: object) -> _E:
    """*exc*, its location given the fields of *known*: ``raise at(ValueError(...), line=3)``."""
    add_location(exc, **known)
    return exc


@contextmanager
def located(**known: object) -> Generator[None]:
    """Add *known* to the location of any exception raised in the block."""
    try:
        yield
    except Exception as exc:
        add_location(exc, **known)
        raise


@contextmanager
def located_in_file(path: Path) -> Generator[None]:
    """Add *path* to the location of any exception raised in the block, and end its message
    with the location.

    The outermost step of reading one file: an exception that already names a file passes
    through unchanged.
    """
    try:
        yield
    except Exception as exc:
        found = CsvLocation.of(exc)
        if found is None or found.file is None:
            add_location(exc, file=path)
            _append_to_message(exc)
        raise


def _append_to_message(exc: BaseException) -> None:
    """End a one-string message with `` (at <location>)``.

    Only a ``ValueError`` or ``csv.Error`` whose only argument is its message is changed; a
    ``UnicodeError`` builds its message from other arguments and is left as it is.
    """
    if not isinstance(exc, (ValueError, csv.Error)) or isinstance(exc, UnicodeError):
        return
    if len(exc.args) != 1 or not isinstance(exc.args[0], str):
        return
    exc.args = (f"{exc.args[0]} (at {CsvLocation.of(exc)})",)
