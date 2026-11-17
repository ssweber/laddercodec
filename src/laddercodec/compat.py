"""Find the instructions that need CLICK v4.

An older CLICK accepts a v4 rung on paste with no warning, and changes it.  Break and
Continue, which CLICK stores in its ``Next`` class, copy back as a plain Next.  The loop
then closes at the first of them.  Check the rungs before you paste them into a CLICK
older than v4.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import TYPE_CHECKING

from .instructions.drum import Drum
from .instructions.forloop import Break, Continue
from .instructions.math import (
    RESERVED_SLOTS,
    Math,
    range_interiors,
    raw_formula_fields,
)
from .instructions.out_variant import OutVariant
from .instructions.raw import RawInstruction

if TYPE_CHECKING:
    from .decode import Rung

#: Math functions added in CLICK v4.  SUM is older, but SUM over a range of bits needs v4.
_V4_MATH_RE = re.compile(r"\b(?:MAX|MIN|MDN|AVG|ABS|RAND)\s*\(")
_V4_BIT_SUM_RE = re.compile(r"\bSUM\s*\(\s*(?:X|Y|C|T|CT|SC)[0-9]+\s*:")


def is_v4_only(instruction: object) -> bool:
    """Return True if *instruction* exists only in CLICK v4.  An older CLICK would change it."""
    if isinstance(instruction, (Break, Continue, OutVariant)):
        return True
    if isinstance(instruction, Drum):
        # Time & Event drums are v4, and so are time drum durations read from a register.
        return instruction.v4_blob
    if isinstance(instruction, Math):
        expression = instruction.expression
        # A v3 blob has room for 500 addresses listed from ranges.  More than that needs v4.
        return bool(_v4_formula(expression) or len(range_interiors(expression)) > RESERVED_SLOTS)
    if isinstance(instruction, RawInstruction) and instruction.class_name == "Math":
        return _raw_math_is_v4_only(instruction.blob)
    return False


def _v4_formula(text: str) -> bool:
    return bool(_V4_MATH_RE.search(text) or _V4_BIT_SUM_RE.search(text))


def _raw_math_is_v4_only(blob: bytes) -> bool:
    """Return True if a Math blob that laddercodec decodes as raw needs CLICK v4.

    The function reads the formulas stored in the blob.  It reads the internal formula
    (``0x61FD``) with each ``#`` replaced by a space.  It reads the display formula
    (``0x6228``) too, because the internal formula writes ``RAND`` between its operands.
    More than 500 filled reserved slots also need v4.  If the fields of the blob do not
    parse, as for ``raw(Math,00)`` from a CSV, the function returns False.
    """
    stored = raw_formula_fields(blob)
    if stored is None:
        return False
    internal, display, listed = stored
    return (
        _v4_formula(internal.replace("#", " ")) or _v4_formula(display) or listed > RESERVED_SLOTS
    )


def find_v4_only(rungs: Rung | Iterable[Rung]) -> list[tuple[int, object]]:
    """Return every v4-only instruction in *rungs* as ``(rung index, instruction)`` pairs.

    An empty list means that the rungs paste into an older CLICK unchanged.
    """
    from .decode import Rung  # decode imports csv, which imports decode

    if isinstance(rungs, Rung):
        rungs = [rungs]
    return [
        (index, instruction)
        for index, rung in enumerate(rungs)
        for instruction in rung.instructions
        if is_v4_only(instruction)
    ]
