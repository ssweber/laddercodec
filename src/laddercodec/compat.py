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
from .instructions.math import (
    _RESERVED_SLOTS,
    Math,
    _range_interiors,
    raw_formula_fields,
)
from .instructions.out_variant import OutVariant
from .instructions.raw import RawInstruction

if TYPE_CHECKING:
    from .decode import Rung

#: Math functions added in CLICK v4.  SUM is older, but not over a bit range.
_V4_MATH_RE = re.compile(r"\b(?:MAX|MIN|MDN|AVG|ABS|RAND)\s*\(")
_V4_BIT_SUM_RE = re.compile(r"\bSUM\s*\(\s*(?:X|Y|C|T|CT|SC)[0-9]+\s*:")


def is_v4_only(instruction: object) -> bool:
    """Whether *instruction* exists only in CLICK v4 (an older CLICK would mangle it)."""
    if isinstance(instruction, (Break, Continue, OutVariant)):
        return True
    if isinstance(instruction, Drum):
        # Time & Event drums are v4, and so are time drum durations read from a register.
        return instruction.v4_blob
    if isinstance(instruction, Math):
        expression = instruction.expression
        # Past 500 range interiors the blob needs v4's capacity; v3 holds 500.
        return bool(_v4_formula(expression) or len(_range_interiors(expression)) > _RESERVED_SLOTS)
    if isinstance(instruction, RawInstruction) and instruction.class_name == "Math":
        return _raw_math_is_v4_only(instruction.blob)
    return False


def _v4_formula(text: str) -> bool:
    return bool(_V4_MATH_RE.search(text) or _V4_BIT_SUM_RE.search(text))


def _raw_math_is_v4_only(blob: bytes) -> bool:
    """The Math check on a Math blob laddercodec decodes as raw, read from its stored fields.

    The internal formula (``0x61FD``) is read with spaces for its ``#``; the display
    formula (``0x6228``) is read too, since the internal form writes ``RAND`` infix.  A blob
    whose fields do not parse (``raw(Math,00)`` from CSV) is not flagged.
    """
    stored = raw_formula_fields(blob)
    if stored is None:
        return False
    internal, display, listed = stored
    return (
        _v4_formula(internal.replace("#", " ")) or _v4_formula(display) or listed > _RESERVED_SLOTS
    )


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
