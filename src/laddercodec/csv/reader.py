"""Read one CSV file into rungs. ``read_csv`` and ``read_bundle`` both read each file here."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

from ..decode import Rung
from ..operands.unchecked import unchecked as _unchecked
from .converter import convert_rung, rung_tokens
from .location import locate_held, located_in_file
from .parser import parse_csv_file


def read_rungs(path: Path, *, strict: bool, unchecked: bool) -> list[Rung]:
    """Parse the CSV file at *path* and return its rungs, as ``read_csv`` documents.

    Do not emit the ``RefusedFieldWarning`` of an instruction that holds refusals.  The
    caller calls :func:`~laddercodec.refused.warn_refused`, so that the warning names the
    line that called ``read_csv`` or ``read_bundle``.
    """
    ast = parse_csv_file(path, syntax="canonical")
    rungs: list[Rung] = []
    with located_in_file(path), _unchecked() if unchecked else nullcontext():
        for rung in ast.rungs:
            rungs.extend(convert_rung(rung, strict=strict))
    if unchecked:
        for rung in rungs:
            locate_held(rung_tokens(rung), file=path)
    return rungs
