"""The ``Undecoded`` marker, which stands in for a rung that laddercodec could not decode.

The marker is not a CLICK instruction.  It has no binary form, and ``encode()`` refuses it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, get_args

from ..codes import Code
from ..model import FieldError, Instruction, Reason
from ..operands.address import digits_value, too_long
from ..operands.checks import Refusals, check_csv_flag
from ..operands.message import make_refusal, says
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

#: The index of the AF column, counted from 0 at column A.
_LAST_COLUMN = 31

UndecodedStop = Literal["end", "return"]
"""What an Undecoded marker acts as: ``"end"`` in the main program, ``"return"`` in a
subroutine."""

_STOPS: tuple[UndecodedStop, ...] = get_args(UndecodedStop)


@dataclass(frozen=True)
class Undecoded(Instruction):
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
    to_the_end:
        True when decoding stopped at this rung. The marker then stands for this rung and
        every rung after it.
    """

    error: str
    rung: int
    row: int | None = None
    column: int | None = None
    stop: UndecodedStop = "end"
    to_the_end: bool = False

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            if not isinstance(self.error, str):
                check.refuse(
                    "error",
                    says("{error!r} must be text that says why", error=self.error),
                    Reason.FORM,
                    code=Code.INVALID_UNDECODED,
                )
            elif not self.error.strip():
                check.refuse(
                    "error",
                    says("is blank", "it must be text that says why"),
                    Reason.MISSING,
                    code=Code.INVALID_UNDECODED,
                )
            elif "\n" in self.error or "\r" in self.error:
                check.refuse(
                    "error",
                    says("{error!r} must be one line", error=self.error),
                    Reason.FORM,
                    code=Code.INVALID_UNDECODED,
                )
            if not _is_index(self.rung):
                check.refuse(
                    "rung",
                    says("{rung!r} must be a whole number from 0", rung=self.rung),
                    _index_reason(self.rung),
                    code=Code.INVALID_UNDECODED,
                )
            if self.row is not None and not _is_index(self.row):
                check.refuse(
                    "row",
                    says("{row!r} must be None or a whole number from 0", row=self.row),
                    _index_reason(self.row),
                    code=Code.INVALID_UNDECODED,
                )
            if self.column is not None and not (
                _is_index(self.column) and self.column <= _LAST_COLUMN
            ):
                check.refuse(
                    "column",
                    says("{column!r} must be None or 0 to 31", column=self.column),
                    _index_reason(self.column),
                    code=Code.INVALID_UNDECODED,
                )
            if self.stop not in _STOPS:
                reason = Reason.CHOICE if isinstance(self.stop, str) else Reason.FORM
                check.refuse(
                    "stop",
                    says("{stop!r} must be 'end' or 'return'", stop=self.stop),
                    reason,
                    code=Code.INVALID_CHOICE,
                )
            check.flag("to_the_end")

    @property
    def where(self) -> str:
        """Where decoding failed, as ``rung N, row R``, or ``rung N`` when ``row`` is ``None``.

        The rung and the row count from 0."""
        return f"rung {self.rung}" if self.row is None else f"rung {self.rung}, row {self.row}"

    @property
    def headline(self) -> str:
        """The first line of the marker rung's comment.

        It reads ``UNDECODED: CLICK rung N, row R: <error>``, with the rung and the row
        counted from 1 as CLICK shows them. It leaves out ``, row R`` when ``row`` is
        ``None``. When ``to_the_end`` is True, the error is followed by
        ``; decoding stopped, so this marker stands for CLICK rung N to the end``.
        """
        rung = f"CLICK rung {self.rung + 1}"
        where = rung if self.row is None else f"{rung}, row {self.row + 1}"
        note = f"; decoding stopped, so this marker stands for {rung} to the end"
        return f"UNDECODED: {where}: {self.error}{note if self.to_the_end else ''}"

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
        if self.to_the_end:
            parts.append("to_the_end=1")
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
    if not (text.isascii() and text.isdigit()) or too_long(text):
        raise make_refusal(
            FieldError,
            f"Undecoded.{key}",
            says("{text!r} must be a whole number from 0", text=text),
            field=f"Undecoded.{key}",
            reason=Reason.FORM,
            code=Code.INVALID_UNDECODED,
        )
    return digits_value(text)


def parse_af_call(call: AfCall) -> Undecoded:
    """Parse ``undecoded("<error>",rung=N[,row=R][,column=C],stop=end|return[,to_the_end=1])``."""
    from ..csv.token_parser import _decode_af_string_literal

    known = {"rung", "row", "column", "stop", "to_the_end"}
    extra = sorted(set(call.kwargs) - known)
    if len(call.args) != 1 or not call.args[0].startswith('"') or extra:
        raise make_refusal(
            FieldError,
            "Undecoded",
            says(
                "{token!r} must be "
                'undecoded("<error>",rung=N,row=R,column=C,stop=end,to_the_end=1), '
                "row, column and to_the_end optional",
                token=call.to_token(),
            ),
            field=None,  # The token's syntax is wrong, not a field's value.
            reason=Reason.FORM,
            code=Code.INVALID_TOKEN,
        )
    rung = _whole_number(call, "rung")
    if rung is None:
        raise make_refusal(
            FieldError,
            "Undecoded.rung",
            says("{token!r} has no rung=", token=call.to_token()),
            field="Undecoded.rung",
            reason=Reason.MISSING,
            code=Code.INVALID_UNDECODED,
        )
    stop = call.kwargs.get("stop")
    if stop is None:
        raise make_refusal(
            FieldError,
            "Undecoded.stop",
            says("{token!r} has no stop=", token=call.to_token()),
            field="Undecoded.stop",
            reason=Reason.MISSING,
            code=Code.INVALID_UNDECODED,
        )
    if stop not in _STOPS:
        raise make_refusal(
            FieldError,
            "Undecoded.stop",
            says("{stop!r} must be 'end' or 'return'", stop=stop),
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
        to_the_end=check_csv_flag(call.kwargs, "to_the_end", "Undecoded.to_the_end"),
    )


SPEC = AfInstructionFamilySpec(
    family_name="undecoded",
    instruction_types=(Undecoded,),
    binary_class_names=(),
    csv_names=("undecoded",),
    parse_csv_call=parse_af_call,
)
