"""The ``Undecoded`` marker, which stands in for a rung that laddercodec could not decode.

The marker is not a CLICK instruction.  It has no binary form, and ``encode()`` refuses it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ..codes import Code
from ..model import AfInstruction, FieldError, Reason
from ..operands.checks import Refusals
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

#: The index of the AF column, counted from 0 at column A.
_LAST_COLUMN = 31

Stop = Literal["end", "return"]
_STOPS: tuple[Stop, ...] = ("end", "return")


@dataclass
class Undecoded(AfInstruction):
    """A marker for a rung that laddercodec could not decode, with the reason.

    When a decoder cannot read a rung, it puts a marker rung in its place.  The marker rung
    is one row, wired from the rail, with this marker as its output.  The marker acts as
    ``end()`` in the main program and as ``return()`` in a subroutine, so a program never
    runs past a rung that could not be read.  ``encode()`` refuses the marker, so it is
    never pasted into CLICK.

    Attributes
    ----------
    error:
        Why the rung could not be decoded, on one line.
    rung:
        Index of the rung it stands for, from 0.
    row, column:
        Where in that rung decoding failed, both from 0 (column 0 is A, 31 is AF), or
        ``None`` when the failure is not at one row or cell.
    stop:
        What the marker acts as: ``"end"`` in the main program, ``"return"`` in a subroutine.
    """

    error: str
    rung: int
    row: int | None = None
    column: int | None = None
    stop: Stop = "end"

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            if not isinstance(self.error, str):
                check.refuse(
                    "error",
                    f"{self.error!r} must be text that says why",
                    Reason.FORM,
                    code=Code.INVALID_UNDECODED,
                )
            elif not self.error.strip():
                check.refuse(
                    "error",
                    "is blank; it must be text that says why",
                    Reason.MISSING,
                    code=Code.INVALID_UNDECODED,
                )
            elif "\n" in self.error or "\r" in self.error:
                check.refuse(
                    "error",
                    f"{self.error!r} must be one line",
                    Reason.FORM,
                    code=Code.INVALID_UNDECODED,
                )
            if not _is_index(self.rung):
                check.refuse(
                    "rung",
                    f"{self.rung!r} must be a whole number from 0",
                    _index_reason(self.rung),
                    code=Code.INVALID_UNDECODED,
                )
            if self.row is not None and not _is_index(self.row):
                check.refuse(
                    "row",
                    f"{self.row!r} must be None or a whole number from 0",
                    _index_reason(self.row),
                    code=Code.INVALID_UNDECODED,
                )
            if self.column is not None and not (
                _is_index(self.column) and self.column <= _LAST_COLUMN
            ):
                check.refuse(
                    "column",
                    f"{self.column!r} must be None or 0 to 31",
                    _index_reason(self.column),
                    code=Code.INVALID_UNDECODED,
                )
            if self.stop not in _STOPS:
                reason = Reason.CHOICE if isinstance(self.stop, str) else Reason.FORM
                check.refuse(
                    "stop",
                    f"{self.stop!r} must be 'end' or 'return'",
                    reason,
                    code=Code.INVALID_CHOICE,
                )

    @property
    def where(self) -> str:
        """Where decoding failed, as ``rung N, row R``, or ``rung N`` when ``row`` is ``None``."""
        return f"rung {self.rung}" if self.row is None else f"rung {self.rung}, row {self.row}"

    @property
    def headline(self) -> str:
        """The first line of the marker rung's comment: ``UNDECODED: rung N, row R: <error>``."""
        return f"UNDECODED: {self.where}: {self.error}"

    def refusal(self) -> str:
        """Return why ``encode()`` refuses the marker."""
        return (
            f"an undecoded marker stands in for a rung laddercodec could not decode "
            f"({self.headline}); it can't be pasted into CLICK. Replace the marker rung "
            "with the rung's logic, or remove it."
        )

    def to_csv(self) -> str:
        text = self.error.replace('"', '""')
        parts = [f'"{text}"', f"rung={self.rung}"]
        if self.row is not None:
            parts.append(f"row={self.row}")
        if self.column is not None:
            parts.append(f"column={self.column}")
        parts.append(f"stop={self.stop}")
        return f"undecoded({','.join(parts)})"

    def cell_params(self) -> dict:
        return {}

    def build_blob(self) -> bytes:
        raise NotImplementedError(self.refusal())


def _is_index(value: object) -> bool:
    return type(value) is int and value >= 0


def _index_reason(value: object) -> Reason:
    """Return the reason that *value* is not a valid index.

    An int is out of range (``Reason.RANGE``). Anything else has the wrong form (``Reason.FORM``).
    """
    return Reason.RANGE if type(value) is int else Reason.FORM


def _whole_number(call: AfCall, key: str) -> int | None:
    text = call.kwargs.get(key)
    if text is None:
        return None
    if not (text.isascii() and text.isdigit()):
        raise FieldError(
            f"Undecoded.{key}: {text!r} must be a whole number from 0",
            field=f"Undecoded.{key}",
            reason=Reason.FORM,
            code=Code.INVALID_UNDECODED,
        )
    return int(text)


def parse_af_call(call: AfCall) -> Undecoded:
    """Parse ``undecoded("<error>",rung=N[,row=R][,column=C],stop=end|return)``."""
    from ..csv.token_parser import _decode_af_string_literal

    known = {"rung", "row", "column", "stop"}
    extra = sorted(set(call.kwargs) - known)
    if len(call.args) != 1 or not call.args[0].startswith('"') or extra:
        raise FieldError(
            f"Undecoded: {call.to_token()!r} must be "
            'undecoded("<error>",rung=N,row=R,column=C,stop=end), row and column optional',
            field=None,  # The token's syntax is wrong, not a field's value.
            reason=Reason.FORM,
            code=Code.INVALID_TOKEN,
        )
    rung = _whole_number(call, "rung")
    if rung is None:
        raise FieldError(
            f"Undecoded.rung: {call.to_token()!r} has no rung=",
            field="Undecoded.rung",
            reason=Reason.MISSING,
            code=Code.INVALID_UNDECODED,
        )
    stop = call.kwargs.get("stop")
    if stop is None:
        raise FieldError(
            f"Undecoded.stop: {call.to_token()!r} has no stop=",
            field="Undecoded.stop",
            reason=Reason.MISSING,
            code=Code.INVALID_UNDECODED,
        )
    if stop not in _STOPS:
        raise FieldError(
            f"Undecoded.stop: {stop!r} must be 'end' or 'return'",
            field="Undecoded.stop",
            reason=Reason.CHOICE,
            code=Code.INVALID_CHOICE,
        )
    return Undecoded(
        error=_decode_af_string_literal(call.args[0]),
        rung=rung,
        row=_whole_number(call, "row"),
        column=_whole_number(call, "column"),
        stop=stop,
    )


SPEC = AfInstructionFamilySpec(
    family_name="undecoded",
    instruction_types=(Undecoded,),
    binary_class_names=(),
    csv_names=("undecoded",),
    parse_csv_call=parse_af_call,
)
