"""Read Click Ladder CSV files.

:func:`read_csv` reads a file into ``Rung`` objects that ``encode_rung()`` and
``encode_rungs()`` accept.  :func:`parse_csv_file` parses the CSV text into an
AST, and :func:`convert_rung` turns each rung of the AST into ``Rung`` objects.
``convert_rung`` places the pin rows, such as ``.reset()``, and draws the layout
that CLICK's syntax check draws.
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

    Each rung is drawn as CLICK's syntax check draws it.  The CSV gives the
    circuit, and the layout sets the rows, the columns and the box heights.
    CLICK splits a rung whose outputs' circuits meet only at the rail into one
    rung per circuit, and ``read_csv`` does the same.  The list can therefore
    hold more rungs than the CSV.  A rung that ``laddercodec.check()`` reports
    is read as written.

    Instruction tokens (e.g. ``X001``, ``out(Y001)``) are parsed into
    ``Contact`` / ``Coil`` objects; wire tokens remain as strings.

    When *strict* is ``False``, unsupported AF instructions are silently
    replaced with blank tokens instead of raising.

    When *unchecked* is ``True``, an instruction whose values its checks refuse
    is read as written, the same way ``decode()`` reads a stored instruction.
    A ``RefusedFieldWarning`` carries the refusals, and ``encode()`` still
    refuses the instruction.  A value that no stored instruction can hold still
    raises: a timer unit that is none of CLICK's, a flag that is not 0 or 1, or
    pin rows the box can't take.  By default every refusal raises.

    A file that isn't UTF-8 text, or a row, token or rung that can't be read, raises
    ``CsvError``.  A value that CLICK's dialog refuses raises ``FieldError``, or
    ``AddressError`` for an address.  Each error carries a :class:`CsvLocation` as its
    ``location``, with the file, line, rung, row and column where they are known.
    ``CsvLocation.of(exc)`` returns it, and the error message ends with it.  When
    *unchecked* is ``True``, each refusal that an instruction keeps carries the
    location it would have raised with.
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
