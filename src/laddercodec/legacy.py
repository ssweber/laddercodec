"""Warnings for saved rungs that an older laddercodec wrote in a form CLICK runs differently.

An instruction parser that sees such a form records a :class:`LegacyFinding` on the
decoded object (``_legacy_findings``). The decoders then call :func:`warn_legacy` once
the rungs are built, which adds the rung index and program name.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable
from typing import NamedTuple

from .instructions import AfInstruction


class LegacyFinding(NamedTuple):
    """What an instruction parser found: the instruction, the token, and what CLICK runs."""

    instruction: str
    token: str
    detail: str


class LegacyEncodingWarning(UserWarning):
    """A decoded rung holds bytes an older laddercodec wrote, which CLICK runs differently.

    Attributes
    ----------
    instruction:
        Instruction class name, e.g. ``"Math"``.
    token:
        The stored token, e.g. ``"H70000"``.
    detail:
        One sentence saying what CLICK runs instead.
    rung:
        0-based rung index in the decoded buffer or program, or ``None`` if unknown.
    program:
        Program name for :func:`laddercodec.decode_program`, else ``None``.
    """

    def __reduce__(self):
        return (
            type(self),
            (self.instruction, self.token, self.detail, self.rung, self.program),
        )

    def __init__(
        self,
        instruction: str,
        token: str,
        detail: str,
        rung: int | None = None,
        program: str | None = None,
    ) -> None:
        self.instruction = instruction
        self.token = token
        self.detail = detail
        self.rung = rung
        self.program = program
        where = []
        if program is not None:
            where.append(f"program {program!r}")
        if rung is not None:
            where.append(f"rung {rung}")
        prefix = ", ".join(where) + ": " if where else ""
        super().__init__(f"{prefix}{instruction} {token}: {detail} Re-paste this rung.")


def warn_legacy(rungs: Iterable[object], *, program: str | None = None) -> None:
    """Emit one :class:`LegacyEncodingWarning` per finding in ``rungs``."""
    for index, rung in enumerate(rungs):
        for af in getattr(rung, "instructions", ()):
            if not isinstance(af, AfInstruction):
                continue
            for finding in getattr(af, "_legacy_findings", ()):
                warnings.warn(
                    LegacyEncodingWarning(*finding, rung=index, program=program),
                    stacklevel=3,
                )
