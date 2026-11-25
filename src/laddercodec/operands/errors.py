"""The error raised for an instruction field whose value CLICK's dialog refuses."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from ..codes import Code
from ..errors import LaddercodecError


class Reason(StrEnum):
    """Why a field refused its value.  :attr:`FieldError.reason` holds one of these.

    The set is fixed.  Each value compares equal to its text (``Reason.BANK == "bank"``).
    """

    ADDRESS = "address"
    """Not a CLICK address: not an address at all, no bank of that name, or a number
    outside its bank (``DS5000``)."""
    BANK = "bank"
    """A CLICK address in a bank the field does not take."""
    RANGE = "range"
    """A number, a constant or a length outside the field's limits."""
    POINTER = "pointer"
    """A pointer that the field does not take.  The field takes no pointer, or no pointer to
    this bank, or the pointer's index is not a DS address."""
    KIND = "kind"
    """A constant of a kind the field does not take, or text that is no constant."""
    FORM = "form"
    """Written in a form the field does not take: a sign, a quote, a character, a shape,
    ``XD0u`` where the field takes no upper byte, or an address not in display form."""
    NOT_WRITABLE = "not_writable"
    """An address the instruction can't write: a read-only SC bit or SD register."""
    FLAG = "flag"
    """Not True, False, 1 or 0."""
    CHOICE = "choice"
    """Not one of the field's named values, such as a timer unit."""
    CONFLICT = "conflict"
    """A value that the field takes, but not together with another field's value.  Most such
    refusals name the other field in :attr:`FieldError.fields` as well.  An immediate
    ``Coil`` on a C bit names ``Coil.operand`` and ``Coil.immediate``."""
    MISSING = "missing"
    """Blank where the field needs a value."""


class FieldError(LaddercodecError):
    """Raised when an instruction field holds a value that CLICK's dialog refuses.

    An instruction runs its checks when it is built.  If its checks refuse any values, it
    raises one error for the first refusal, and the :attr:`errors` of that error holds
    every refusal.  A decoder that meets this error keeps the instruction and its
    refusal.  A blob that no stored instruction holds, such as an address not in display
    form, stays unparsed.  The message is for people and may change.  Read the attributes
    instead.

    Attributes
    ----------
    field:
        The refused field, written as ``Class.attr``, with ``[i]`` for an item of a list
        field, such as ``Coil.range_end`` or ``Drum.outputs[2]``.  ``Class`` is the class
        whose checks refused the value.  It is an instruction or a Modbus target
        (``ModbusTcpTarget.port``).  ``attr`` is one of its dataclass fields.  ``field``
        is None only for a CSV token that does not follow its instruction's syntax.
    fields:
        Every field that the refusal is about, with :attr:`field` first.  It is
        ``(field,)`` for one field, and holds both fields for a pair, such as
        ``CompareContact.left`` with ``CompareContact.right``.
    reason:
        Why the field refused the value, as a :class:`Reason`.  None when the check
        names no reason.
    code:
        The rule that refused the value, as a :class:`~laddercodec.Code`, such as
        ``"bank-not-allowed"``.  Each refusal in :attr:`errors` has its own code.
    click_id:
        CLICK's id for the error (``"OBJ-005"``), or None where CLICK has none.
    errors:
        Every refusal from one construction, with this one first.  It is ``(self,)``
        when there is one refusal.
    obj:
        The instruction being built when its checks refused the value, or None.
    span:
        Where a refusal of a Math formula is in the formula: a ``(start, end)`` pair of
        character offsets into ``Math.expression`` as it was passed, before any trimming or
        change of case.  ``expression[start:end]`` is the refused text, and ``end`` is not
        part of it.  For a Math that a decoder built, the offsets index into the decoded
        Math's ``expression``, not into the display text that CLICK stored.  ``span`` is
        None for a refusal of any other field.  It is also None for a formula refusal that
        no one stretch of the formula causes: a blank formula, a formula that is too long,
        a ``(`` with no ``)``, and a key that only the other mode takes.
    """

    field: str | None
    fields: tuple[str, ...]
    reason: Reason | None
    code: Code
    click_id: str | None
    errors: tuple[FieldError, ...]
    obj: Any
    # The class default gives None for an error pickled before FieldError had a span.
    span: tuple[int, int] | None = None

    def __init__(
        self,
        *args: object,
        code: Code,
        field: str | tuple[str, ...] | None = None,
        reason: Reason | None = None,
        click_id: str | None = None,
        obj: Any = None,
    ) -> None:
        """Build the error.  ``field`` is one field, or a tuple of the fields of a pair."""
        super().__init__(*args)
        self.fields = (field,) if isinstance(field, str) else tuple(field or ())
        self.field = self.fields[0] if self.fields else None
        self.reason = reason
        self.code = code
        self.click_id = click_id
        self.errors = (self,)
        self.obj = obj
        self.span = None

    def __reduce__(self) -> tuple[Any, ...]:
        # Unpickling calls the class with args alone. FieldError requires code, so pass it too.
        return (_rebuild, (type(self), self.args, self.code), self.__dict__)


def _rebuild(cls: type[FieldError], args: tuple[object, ...], code: Code) -> FieldError:
    """Rebuild a pickled :class:`FieldError`.  Its other attributes come from its state."""
    return cls(*args, code=code)


class AddressError(FieldError):
    """Raised when a field holds an address outside CLICK's banks or ranges, or in a bank
    that the field does not allow."""
