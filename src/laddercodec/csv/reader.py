"""Read one CSV file into rungs. ``read_csv`` and ``read_bundle`` both read each file here."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

from ..codes import Code
from ..decode import Rung
from ..errors import CsvReadError
from ..instructions import Tee, writes_back
from ..model import Condition, Instruction
from ..operands.unchecked import allow_codes, allowed, refusals
from ..operands.unchecked import unchecked as _unchecked
from .converter import convert_rung, rung_tokens
from .location import _append_to_message, locate_held, located_in_file
from .parser import parse_csv_file


def allowed_codes(allow: Iterable[str] | None, *, unchecked: bool, caller: str) -> frozenset[Code]:
    """Return the codes that *allow* names, for the ``allow=`` of ``read_csv`` or
    ``read_bundle``.  Read None as no codes.

    Raise ``CsvReadError`` if *allow* is a string, bytes or not iterable, if an item names no
    ``Code``, or if *allow* names a code and *unchecked* is True.  *caller* starts the
    message.
    """
    codes = allow_codes(allow, caller=caller, error=CsvReadError)
    if codes and unchecked:
        raise CsvReadError(
            f"{caller}: you passed both unchecked=True and allow=. Pass one of them, such as "
            "allow=['bank-not-allowed'] alone."
        )
    return frozenset(codes)


def read_rungs(
    path: Path, *, strict: bool, unchecked: bool, allow: frozenset[Code] = frozenset()
) -> list[Rung]:
    """Parse the CSV file at *path* and return its rungs, as ``read_csv`` documents.

    *allow* is the set that :func:`allowed_codes` returns.  Do not emit the
    ``RefusedFieldWarning`` of an instruction that holds refusals.  The caller calls
    :func:`~laddercodec.refused.warn_refused` when *unchecked* is True, so that the warning
    names the line that called ``read_csv`` or ``read_bundle``.
    """
    ast = parse_csv_file(path, syntax="canonical")
    rungs: list[Rung] = []
    keeping: AbstractContextManager[object] = nullcontext()
    if unchecked:
        keeping = _unchecked()
    elif allow:
        keeping = _unchecked(allow=allow)
    with located_in_file(path), keeping:
        for rung in ast.rungs:
            converted = convert_rung(rung, strict=strict)
            # Check each CSV rung before the next one is read, so that the first bad rung
            # raises first, as it does by default.
            for drawn in converted:
                if unchecked or allow:
                    locate_held(rung_tokens(drawn), file=path)
                if allow:
                    _raise_unwritable(drawn)
            rungs.extend(converted)
    return rungs


def _raise_unwritable(rung: Rung) -> None:
    """Raise the first refusal of the first allowed instruction in *rung* that laddercodec
    can't write and read back the same.

    The refusal is raised as the default read raises it, with its location at the end of
    its message.
    """
    for token in rung_tokens(rung):
        inst = token.contact if isinstance(token, Tee) else token
        if not isinstance(inst, (Condition, Instruction)):
            continue
        if allowed(inst) and not writes_back(inst):
            first = refusals(inst)[0]
            _append_to_message(first)
            raise first.with_traceback(None)
