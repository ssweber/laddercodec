"""CLICK version compatibility: which instructions need CLICK v4.

An older CLICK accepts a v4 rung on paste without complaint and silently
changes it: Break and Continue (class ``Next``) copy back as plain Next,
which closes the loop at the first one.  Check before pasting into a
pre-v4 CLICK.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import TYPE_CHECKING

from .instructions.drum import Drum
from .instructions.forloop import Break, Continue
from .instructions.math import Math
from .instructions.out_variant import OutVariant

if TYPE_CHECKING:
    from .decode import Rung

#: Math functions added in CLICK v4.  SUM is older, but not over a bit range.
_V4_MATH_RE = re.compile(r"\b(?:MAX|MIN|MDN|AVG|ABS|RAND)\s*\(")
_V4_BIT_SUM_RE = re.compile(r"\bSUM\s*\(\s*(?:X|Y|C|T|CT|SC)\d+\s*:")


def is_v4_only(instruction: object) -> bool:
    """Whether *instruction* exists only in CLICK v4 (an older CLICK would mangle it)."""
    if isinstance(instruction, (Break, Continue, OutVariant)):
        return True
    if isinstance(instruction, Drum):
        return instruction.drum_kind == "time_event"
    if isinstance(instruction, Math):
        expression = instruction.expression
        return bool(_V4_MATH_RE.search(expression) or _V4_BIT_SUM_RE.search(expression))
    return False


def find_v4_only(rungs: Rung | Iterable[Rung]) -> list[tuple[int, object]]:
    """Every v4-only instruction in *rungs*, as ``(rung index, instruction)`` pairs.

    Empty means the rungs paste into an older CLICK unchanged.
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
