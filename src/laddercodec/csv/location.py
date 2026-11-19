"""Record where in a CSV file ``read_csv`` found each error that it raises.

``CsvLocation`` holds the place. The helpers here attach one to an exception, or to a
refusal that ``read_csv`` keeps when it reads with ``unchecked=True``.
"""

from __future__ import annotations

import csv
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import TypeVar

from ..operands.unchecked import refusals
from .contract import CONDITION_COLUMNS, OUTPUT_COLUMN

_E = TypeVar("_E", bound=BaseException)
_COLUMN_NAMES = (*CONDITION_COLUMNS, OUTPUT_COLUMN)

#: The column index of ``AF``.
AF_COLUMN = len(CONDITION_COLUMNS)


@dataclass(frozen=True)
class CsvLocation:
    """The place in a CSV file of an error that ``read_csv`` raises, or of a refusal that
    it keeps.

    Every exception that ``read_csv`` raises for a bad CSV has a ``CsvLocation`` as its
    ``location`` attribute. This is so for a ``CsvReadError``, which is raised for a row or
    token that ``read_csv`` can't read. It is also so for a ``FieldError`` or an
    ``AddressError``, which keeps its own class. :meth:`of` returns the location of an
    exception. The message of each exception ends with `` (at <location>)``.

    ``read_csv`` raises a ``csv.Error``, or a ``UnicodeDecodeError`` for a file that isn't
    UTF-8, as a ``CsvReadError`` with the same message. The original exception is its
    ``__cause__``. For a file that isn't UTF-8, the location holds only ``file``.

    A check can refuse a value while a box takes its pin rows. Examples are a ``.jump()``
    target, or a ``.reset()`` on a timer that can't be retentive. ``read_csv`` then raises a
    ``CsvReadError`` that carries the data of the refusal. Each refusal in the ``errors`` of a
    ``FieldError`` has its own location. Each field of the location is ``None`` where it is
    not known or does not apply.

    When ``read_csv`` reads with ``unchecked=True``, an instruction keeps each refusal
    instead of raising it. The refusal appears in the ``errors`` of a
    :class:`~laddercodec.RefusedFieldWarning`. When ``read_csv`` reads with ``allow=``, an
    instruction keeps each refusal that ``allow=`` lists, and no warning is emitted. Each
    kept refusal has the location that the default read would give it when it raised. Its
    message does not end with the location.

    Attributes
    ----------
    file:
        The CSV file being read.
    line:
        The line of the CSV file that the bad row starts on. Lines are counted from 1, as an
        editor counts them, and blank lines count. The header is line 1 only when no blank
        line comes before it. It is ``None`` for an error about the whole file.
    rung_line:
        The line of the ``R`` row that starts the rung that holds the bad row, counted the
        same way. It is ``None`` when the row is in no rung. The header and a comment row are
        in no rung. So is a row that has no ``R`` row between it and the nearest comment row
        or header above it.
    row:
        The index of the row within its rung, from 0. The ``R`` row is row 0, and the comment
        rows above it are not counted. Rows are counted as they appear in the CSV file,
        before laddercodec lays out the rung. It is ``None`` when ``rung_line`` is ``None``.
        If a check refuses the value that a pin row holds, the row is that pin row. If a pin
        row is missing, the row is the box's row.
    column:
        The cell's column, counted from 0 as :class:`laddercodec.Finding` counts columns.
        0 is ``A``, 30 is ``AE`` and 31 is ``AF``. It is ``None`` for an error about a whole
        row or its marker. :attr:`column_name` returns the letters.
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
        """Return the location that *exc* carries, or ``None`` if it carries none."""
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


def add_own_location(exc: BaseException, **known: object) -> None:
    """Add to the location of *exc* each field of *known* that the location does not have yet.

    Leave the refusals in the ``errors`` of *exc* unchanged.
    """
    old = CsvLocation.of(exc) or CsvLocation()
    new = {
        f.name: known[f.name]
        for f in fields(CsvLocation)
        if known.get(f.name) is not None and getattr(old, f.name) is None
    }
    object.__setattr__(exc, "location", replace(old, **new))


def add_location(exc: BaseException, **known: object) -> None:
    """Add each field of *known* to the location of *exc*, and of every refusal in its
    ``errors``, where that location does not have the field yet."""
    add_own_location(exc, **known)
    for nested in getattr(exc, "errors", ()):
        if nested is not exc and isinstance(nested, BaseException):
            add_location(nested, **known)


def locate_held(tokens: Iterable[object], **known: object) -> None:
    """Add the fields of *known* to the location of every refusal that an instruction in
    *tokens* holds, as :func:`add_location` does for a raised exception.

    ``read_csv(..., unchecked=True)`` builds an instruction even when its checks refuse a
    value, and the instruction keeps the refusals.
    :func:`~laddercodec.operands.unchecked.refusals` returns them.
    """
    if all(value is None for value in known.values()):
        return
    for token in tokens:
        for refusal in refusals(token):
            add_location(refusal, **known)


def at(exc: _E, **known: object) -> _E:
    """Add the fields of *known* to the location of *exc*, and return *exc*.

    Use it in a raise statement: ``raise at(ValueError(...), line=3)``.
    """
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

    Wrap the whole read of one file in this block. If the location of an exception already
    names a file, the exception passes through unchanged.
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
    """Add `` (at <location>)`` to the end of the message of *exc*.

    Change only a ``ValueError`` or ``csv.Error`` whose only argument is its message. Leave a
    ``UnicodeError`` as it is, because it builds its message from other arguments.
    """
    if not isinstance(exc, (ValueError, csv.Error)) or isinstance(exc, UnicodeError):
        return
    if len(exc.args) != 1 or not isinstance(exc.args[0], str):
        return
    exc.args = (f"{exc.args[0]} (at {CsvLocation.of(exc)})",)
