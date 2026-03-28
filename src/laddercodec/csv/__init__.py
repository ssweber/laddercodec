"""CSV parsing subpackage for Click Ladder rows/files.

Public API for reading Click Ladder CSV files into structured data ready
for ``encode_rung()`` / ``encode_rungs()``.

Delegates to :func:`parse_csv_file` for CSV parsing and
:func:`convert_rung` for AST → encode-argument conversion, including
pin-row handling (``.reset()`` etc.) and tall-instruction auto-padding.
"""

from __future__ import annotations

from pathlib import Path

from ..decode import Rung
from .contract import CONDITION_COLUMNS, CSV_HEADER
from .converter import convert_rung
from .parser import parse_csv_file


def read_csv(path: Path | str, *, strict: bool = True) -> list[Rung]:
    """Read any Click Ladder CSV and return one ``Rung`` per rung.

    Handles both single-rung and multi-rung CSV files in a single call.
    Each ``Rung`` is a dataclass with attributes ``logical_rows``,
    ``conditions``, ``instructions``, ``comment``, ``comment_rtf``::

        rungs = read_csv(path)
        r = rungs[0]
        r.logical_rows    # int
        r.conditions      # list[list[ConditionToken]]
        r.instructions    # list[AfToken]
        r.comment         # str | None

    Returns the exact data needed for ``encode_rung()``.
    Instruction tokens (e.g. ``X001``, ``out(Y001)``) are parsed into
    ``Contact`` / ``Coil`` objects; wire tokens remain as strings.

    When *strict* is ``False``, unsupported AF instructions are silently
    replaced with blank tokens instead of raising.
    """
    ast = parse_csv_file(Path(path), syntax="canonical")
    return [Rung(*convert_rung(rung, strict=strict)) for rung in ast.rungs]


__all__ = [
    "CONDITION_COLUMNS",
    "CSV_HEADER",
    "read_csv",
]
