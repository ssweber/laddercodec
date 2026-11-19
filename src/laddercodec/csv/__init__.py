"""Read Click Ladder CSV files.

:func:`read_csv` reads a file into ``Rung`` objects that ``encode_rung()`` and
``encode_rungs()`` accept.  :func:`parse_csv_file` parses the CSV text into an
AST, and :func:`convert_rung` turns each rung of the AST into ``Rung`` objects.
``convert_rung`` places the pin rows, such as ``.reset()``, and draws the layout
that CLICK's syntax check draws.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..decode import Rung
from ..refused import warn_refused
from .contract import CONDITION_COLUMNS, CSV_HEADER
from .location import CsvLocation
from .reader import allowed_codes, read_rungs


def read_csv(
    path: Path | str,
    *,
    strict: bool = True,
    unchecked: bool = False,
    allow: Iterable[str] = (),
) -> list[Rung]:
    """Read any Click Ladder CSV and return one ``Rung`` per CLICK rung.

    Handles both single-rung and multi-rung CSV files in a single call.
    Each ``Rung`` is a frozen dataclass with the fields ``conditions``,
    ``instructions``, ``comment`` and ``comment_rtf``::

        rungs = read_csv(path)
        r = rungs[0]
        r.logical_rows    # int, len(r.conditions)
        r.conditions      # tuple[tuple[ConditionToken, ...], ...]
        r.instructions    # tuple[InstructionToken, ...]
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

    *allow* lists the codes of the refusals that you accept, such as
    ``allow=["bank-not-allowed"]``.  Each item is a code's name or a ``Code``.  An
    instruction keeps a refusal only if every error in it (``FieldError.errors``) has a
    code in *allow*.  Any other refusal raises, as it does by default.  These refusals
    raise whatever *allow* lists:

    - a value that is not one of a field's named values, or a flag that is not 0 or 1;
    - text that is not in CLICK's display form;
    - a refusal of the rows of a box's pins;
    - a refusal that a check raised because it crashed on the value.

    ``read_csv`` keeps a refusal that *allow* lists only when laddercodec can write the
    instruction and read it back the same.  Otherwise the refusal raises, as it does by
    default.  A check that depends on a refused field does not run, so *allow* can let
    through a value that such a check would refuse.

    ``read_csv`` emits no ``RefusedFieldWarning`` for a refusal that *allow* lists.
    ``encode()``, ``write_csv`` and ``csv_rows`` write the instruction from its fields.
    If you change a field with :func:`laddercodec.replace`, the copy is checked again.  A
    refused value that the copy still holds then raises, even if *allow* listed its code.

    A file that isn't UTF-8 text, or a row, token or rung that can't be read, raises
    ``CsvReadError``.  A value that CLICK's dialog refuses raises ``FieldError``, or
    ``AddressError`` for an address.  Each error carries a :class:`CsvLocation` as its
    ``location``, with the file, line, rung, row and column where they are known.
    ``CsvLocation.of(exc)`` returns it, and the error message ends with it.  When
    *unchecked* is ``True`` or *allow* lists a code, each refusal that an instruction
    keeps carries the location it would have raised with.

    ``read_csv`` checks *allow* before it reads the file.  It raises ``CsvReadError``, with no
    location, in these cases:

    - an item is not a code's name;
    - *allow* is a single string, bytes, or a value that you can't iterate over;
    - you pass both ``unchecked=True`` and a non-empty *allow*.

    ``allow=None`` reads as no codes.
    """
    codes = allowed_codes(allow, unchecked=unchecked, caller="read_csv")
    rungs = read_rungs(Path(path), strict=strict, unchecked=unchecked, allow=codes)
    if unchecked:
        warn_refused(rungs)
    return rungs


__all__ = [
    "CONDITION_COLUMNS",
    "CSV_HEADER",
    "CsvLocation",
    "read_csv",
]
