"""CSV parsing subpackage for Click Ladder rows/files.

Public API for reading Click Ladder CSV files into structured data ready
for ``encode_rung()`` / ``encode_rungs()``.

Delegates to :func:`parse_csv_file` for CSV parsing and
:func:`convert_rung` for AST → ``Rung`` conversion: pin rows (``.reset()``
etc.) and the layout CLICK's syntax check draws.
"""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

from ..decode import Rung
from ..operands.unchecked import unchecked as _unchecked
from ..refused import warn_refused
from .contract import CONDITION_COLUMNS, CSV_HEADER
from .converter import convert_rung, rung_tokens
from .location import CsvLocation, locate_held, located_in_file
from .parser import parse_csv_file


def read_csv(path: Path | str, *, strict: bool = True, unchecked: bool = False) -> list[Rung]:
    """Read any Click Ladder CSV and return one ``Rung`` per CLICK rung.

    Handles both single-rung and multi-rung CSV files in a single call.
    Each ``Rung`` is a dataclass with attributes ``logical_rows``,
    ``conditions``, ``instructions``, ``comment``, ``comment_rtf``::

        rungs = read_csv(path)
        r = rungs[0]
        r.logical_rows    # int
        r.conditions      # list[list[ConditionToken]]
        r.instructions    # list[AfToken]
        r.comment         # str | None

    Each rung is drawn as CLICK's syntax check draws it: the CSV gives the
    circuit, and the rows, columns and box heights come from the layout.  A
    CSV rung whose outputs' circuits meet only at the rail reads as one rung
    per circuit, as CLICK splits it, so the list can hold more rungs than the
    CSV.  A rung ``laddercodec.check()`` reports reads as written.

    Instruction tokens (e.g. ``X001``, ``out(Y001)``) are parsed into
    ``Contact`` / ``Coil`` objects; wire tokens remain as strings.

    When *strict* is ``False``, unsupported AF instructions are silently
    replaced with blank tokens instead of raising.

    When *unchecked* is ``True``, an instruction whose values its checks refuse
    is read as written, as ``decode()`` reads a stored one, with a
    ``RefusedFieldWarning`` carrying the refusals; ``encode()`` still refuses
    it.  A value no stored instruction holds (a timer unit that is none of
    CLICK's, a flag that is not 0 or 1, pin rows the box can't take) still
    raises.  By default every refusal raises.

    An exception raised for a bad CSV keeps its class (``ValueError``,
    ``FieldError``, ``AddressError``, ...) and carries a :class:`CsvLocation`
    as its ``location``: the file, line, rung, row and column where they are
    known.  ``CsvLocation.of(exc)`` reads it, and the message ends with it.
    Each refusal an instruction keeps when *unchecked* is ``True`` carries the
    location it would raise with.
    """
    path = Path(path)
    ast = parse_csv_file(path, syntax="canonical")
    rungs: list[Rung] = []
    with located_in_file(path), _unchecked() if unchecked else nullcontext():
        for rung in ast.rungs:
            rungs.extend(convert_rung(rung, strict=strict))
    if unchecked:
        for rung in rungs:
            locate_held(rung_tokens(rung), file=path)
        warn_refused(rungs)
    return rungs


__all__ = [
    "CONDITION_COLUMNS",
    "CSV_HEADER",
    "CsvLocation",
    "read_csv",
]
