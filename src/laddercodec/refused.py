"""Warnings for decoded instructions that hold a value CLICK's dialog refuses.

The decoders build each instruction from what is stored, so an instruction that breaks a
dialog rule (an older paste of ``DH70 == DS3920``, say) decodes as that instruction and
keeps the refusals its construction would raise.  Once the rungs are built, the decoders,
and ``read_csv(..., unchecked=True)``, call :func:`warn_refused`, which emits one
:class:`RefusedFieldWarning` per such instruction with its rung index and program name.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable

from .operands.errors import FieldError
from .operands.unchecked import refusals


class RefusedFieldWarning(UserWarning):
    """A decoded instruction holds a value its checks refuse; it decodes as that instruction.

    Unchanged, the instruction encodes as the bytes it was decoded from.  Changed, it is
    checked again; read from CSV, or a condition read from a program file, it has no bytes
    to write.  Then ``encode()`` raises the refusal it holds, as building it would.

    Attributes
    ----------
    instruction:
        The decoded instruction, a contact or an AF instruction.
    error:
        The :class:`~laddercodec.FieldError` building the instruction would raise: the
        first refusal.
    errors:
        Every refusal, :attr:`error` first; those of a Send's or Receive's Modbus target
        and remote address come before its own.
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
        super().__init__(
            f"{prefix}{type(instruction).__name__} holds a value CLICK's dialog refuses, and "
            f"decodes as it is stored: {self.error}{more}"
        )


def warn_refused(rungs: Iterable[object], *, program: str | None = None) -> None:
    """Emit one :class:`RefusedFieldWarning` per instruction in ``rungs`` that keeps refusals,
    in rung order, each rung's cells row by row."""
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
