"""Warnings for saved rungs that an older laddercodec wrote in a form CLICK runs differently.

When an instruction parser sees such a form, it records a :class:`LegacyFinding` in the
decoded instruction's ``_legacy_findings``. Once the rungs are built, the decoders call
:func:`warn_legacy`. It issues a warning for each finding, with the rung index and the
program name.
"""

from __future__ import annotations

import dataclasses
import warnings
from collections.abc import Callable, Iterable
from typing import NamedTuple

from .instructions import Tee
from .operands.message import shown


class LegacyFinding(NamedTuple):
    """A legacy form that an instruction parser found, with what CLICK runs instead."""

    instruction: str
    token: str
    detail: str


class LegacyEncodingWarning(UserWarning):
    """Issued when a decoded rung holds bytes that an older laddercodec wrote and CLICK runs
    differently.

    Attributes
    ----------
    instruction:
        Instruction class name, e.g. ``"Math"``. For a flag field that is stored empty, it
        names the field too, e.g. ``"Copy.oneshot"``.
    token:
        The stored token, e.g. ``"H70000"``. It is ``""`` for a flag field that is stored
        empty. If no field can be named, ``instruction`` is the class and ``token`` names
        the tag, e.g. ``"1246="``.
    detail:
        What CLICK runs instead. For a flag field, it also says what laddercodec reads.
    rung:
        0-based rung index in the decoded buffer or program, or ``None`` if unknown.
    program:
        The program name if :func:`laddercodec.decode_program` decoded the rung, else
        ``None``.
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
        head = f"{instruction} {token}" if token else instruction
        super().__init__(f"{prefix}{head}: {detail} Encode this rung again and paste it.")


def empty_flag_findings(
    parsed: object,
    tag: int,
    tags: dict[int, str],
    parse: Callable[[dict[int, str]], object | None],
) -> list[LegacyFinding]:
    """Return a finding for each field of *parsed* that the flag *tag*, stored empty, sets.

    laddercodec reads a flag that is stored empty as set, and CLICK runs it as clear.
    *parsed* was built from *tags*, and *parse* builds an instruction from tags in the same
    way. The function builds the instruction again without *tag*, so with the flag clear.
    Each field that differs between the two gets a finding. A flag that changes no field
    gets none, because laddercodec does not read it. If the instruction can't be built with
    the flag clear, the finding names the tag in the form of a ``raw(...)`` field, such as
    ``1221=``.
    """
    name = type(parsed).__name__
    cleared = {key: value for key, value in tags.items() if key != tag}
    try:
        clear = parse(cleared)
    except Exception:  # noqa: BLE001 - a parser that can't read the clear flag names the tag
        clear = None
    if clear is None or type(clear) is not type(parsed) or not dataclasses.is_dataclass(parsed):
        detail = "the flag is stored empty, so laddercodec reads it as set. CLICK runs it as clear."
        return [LegacyFinding(name, f"{tag:04x}=", detail)]
    found: list[LegacyFinding] = []
    for field in dataclasses.fields(parsed):
        read = getattr(parsed, field.name)
        runs = getattr(clear, field.name)
        if read != runs:
            detail = (
                f"the flag is stored empty, so laddercodec reads it as {shown(read)}. "
                f"CLICK runs it as {shown(runs)}."
            )
            found.append(LegacyFinding(f"{name}.{field.name}", "", detail))
    return found


def written_flags(inst: object) -> dict[int, str]:
    """Return the value that encoding *inst* writes for each flag tag of its blob.

    Return an empty dict if the encoder can't write *inst*.
    """
    from .binary_helpers import _STANDARD_SENTINEL, _tag_wire_type
    from .instructions.raw import _decompose_blob
    from .operands.unchecked import fields_blob

    try:
        fields = _decompose_blob(fields_blob(inst))[4]
    except Exception:  # noqa: BLE001 - an instruction the encoder can't write gives no values
        return {}
    return {
        tag: value
        for tag, sentinel, value in fields
        if sentinel == _STANDARD_SENTINEL and _tag_wire_type(tag) == "flag"
    }


def written_flag_finding(parsed: object, tag: int) -> LegacyFinding:
    """Return the finding for the flag *tag*, stored empty, that encoding *parsed* writes set.

    laddercodec does not read this flag. The encoder writes it from another field, so
    encoding the rung again sets a flag that CLICK runs as clear. The finding names the
    field if exactly one field, set to its clear value, makes the encoder write the flag
    as ``0``. A field's clear value is its default. A field with no default clears to
    ``False`` if it holds a bool and to ``""`` if it holds text. Otherwise the finding
    names the tag, such as ``1246=``.
    """
    from .operands.unchecked import unchecked

    name = type(parsed).__name__
    detail = (
        "the flag is stored empty, and encoding this rung again writes it set. "
        "CLICK runs it as clear."
    )
    named: list[str] = []
    if dataclasses.is_dataclass(parsed):
        for field in dataclasses.fields(parsed):
            value = getattr(parsed, field.name)
            if field.default is not dataclasses.MISSING:
                clear = field.default
            elif isinstance(value, bool):
                clear = False
            elif isinstance(value, str):
                clear = ""
            else:
                continue
            if value == clear:
                continue
            try:
                with unchecked():
                    cleared = dataclasses.replace(parsed, **{field.name: clear})  # ty: ignore[invalid-argument-type]
            except Exception:  # noqa: BLE001 - a field that can't be cleared names nothing
                continue
            if written_flags(cleared).get(tag) == "0":
                named.append(field.name)
    if len(named) == 1:
        return LegacyFinding(f"{name}.{named[0]}", "", detail)
    return LegacyFinding(name, f"{tag:04x}=", detail)


def warn_legacy(rungs: Iterable[object], *, program: str | None = None) -> None:
    """Emit one :class:`LegacyEncodingWarning` per finding in ``rungs``.

    Go through the rungs in order, and through the cells of each rung row by row.
    """
    for index, rung in enumerate(rungs):
        conditions = getattr(rung, "conditions", ())
        instructions = getattr(rung, "instructions", ())
        for row, af in zip(conditions, instructions, strict=False):
            for cell in (*row, af):
                token = cell.contact if isinstance(cell, Tee) else cell
                for finding in getattr(token, "_legacy_findings", ()):
                    warnings.warn(
                        LegacyEncodingWarning(*finding, rung=index, program=program),
                        stacklevel=3,
                    )
