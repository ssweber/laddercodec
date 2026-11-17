"""Warnings for decoded instructions that hold a value CLICK's dialog refuses.

The decoders build each instruction from the stored values without refusing them. An
instruction that breaks a dialog rule, such as an older paste of ``DH70 == DS3920``, still
decodes as that instruction. It holds the refusals that building it would raise. When the
rungs are built, the decoders and ``read_csv(..., unchecked=True)`` call
:func:`warn_refused`. That function emits one :class:`RefusedFieldWarning` for each such
instruction, with its rung index and program name.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable

from .operands.errors import FieldError
from .operands.unchecked import refusals


class RefusedFieldWarning(UserWarning):
    """Emitted when a decoded instruction holds a value that its checks refuse. The
    instruction still decodes as that instruction.

    If you leave the instruction unchanged, it encodes as the bytes it was decoded from.
    If you change it, it is checked again. An instruction read from CSV, or a condition
    read from a program file, has no stored bytes to write. When the instruction does not
    write stored bytes and still holds a refusal, ``encode()`` raises that refusal, as
    building the instruction would.

    Attributes
    ----------
    instruction:
        The decoded instruction, a contact or an AF instruction.
    error:
        The :class:`~laddercodec.FieldError` that building the instruction would raise.
        It is the first refusal.
    errors:
        Every refusal, with :attr:`error` first. For a Send or Receive, the refusals of
        its Modbus target and remote address come before its own. When
        ``read_csv(..., unchecked=True)`` reads the instruction, each refusal has a
        :class:`~laddercodec.CsvLocation` as its ``location``, the same location that the
        default read raises it with. The warning message then ends with the location of
        :attr:`error`.
    rung:
        0-based rung index in the decoded buffer, program or CSV, or ``None`` if unknown.
    program:
        Program name for :func:`laddercodec.decode_program`, else ``None``.
    """

    def __reduce__(self):
        return (type(self), (self.instruction, self.errors, self.rung, self.program))

    def __init__(
        self,
        instruction: object,
        errors: tuple[FieldError, ...],
        rung: int | None = None,
        program: str | None = None,
    ) -> None:
        self.instruction = instruction
        self.errors = errors
        self.error = errors[0]
        self.rung = rung
        self.program = program
        where = []
        if program is not None:
            where.append(f"program {program!r}")
        if rung is not None:
            where.append(f"rung {rung}")
        prefix = ", ".join(where) + ": " if where else ""
        more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
        location = str(getattr(self.error, "location", None) or "")
        at = f" (at {location})" if location else ""
        super().__init__(
            f"{prefix}{type(instruction).__name__} holds a value CLICK's dialog refuses, and "
            f"decodes as it is stored: {self.error}{more}{at}"
        )


def warn_refused(rungs: Iterable[object], *, program: str | None = None) -> None:
    """Emit one :class:`RefusedFieldWarning` for each instruction in ``rungs`` that holds
    refusals. Go through the rungs in order, and through the cells of each rung row by row."""
    for index, rung in enumerate(rungs):
        conditions = getattr(rung, "conditions", ())
        instructions = getattr(rung, "instructions", ())
        for row, af in zip(conditions, instructions, strict=False):
            for token in (*row, af):
                found = refusals(token)
                if found:
                    warnings.warn(
                        RefusedFieldWarning(token, found, rung=index, program=program),
                        stacklevel=3,
                    )
