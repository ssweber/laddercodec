"""Field errors: a value CLICK's dialog refuses."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class Reason(StrEnum):
    """Why a field refused its value: :attr:`FieldError.reason`.

    The set is fixed.  Each value compares equal to its text (``Reason.BANK == "bank"``).
    """

    #: Not a CLICK address: no bank of that name, or not an address at all.
    ADDRESS = "address"
    #: An address in a bank the field does not take.
    BANK = "bank"
    #: A number, an address or a length outside the field's limits.
    RANGE = "range"
    #: A pointer the field does not take: any pointer, one to this bank, or this index.
    POINTER = "pointer"
    #: A constant of a kind the field does not take, or text that is no constant.
    KIND = "kind"
    #: Written in a form the field does not take: a sign, a quote, a character, a shape.
    FORM = "form"
    #: An address the instruction can't write: a read-only SC bit.
    NOT_WRITABLE = "not_writable"
    #: Not True, False, 1 or 0.
    FLAG = "flag"
    #: Not one of the field's named values, such as a timer unit.
    CHOICE = "choice"
    #: A value the field takes, but not with another field's value.
    CONFLICT = "conflict"
    #: Blank where the field needs a value.
    MISSING = "missing"


class FieldError(ValueError):
    """An instruction field holds a value CLICK's dialog refuses.

    An instruction runs its checks when it is built and raises one error for every value
    refused: the first refusal, whose :attr:`errors` holds them all.  The decoders'
    ``from_tags`` dispatchers catch it and leave the blob unparsed.  The message is for
    people and may change; read the attributes.

    Attributes
    ----------
    field:
        The field refused, as ``Class.attr``, with ``[i]`` for an item of a list field:
        ``Coil.range_end``, ``Drum.outputs[2]``.  ``Class`` is the instruction's class name
        and ``attr`` one of its dataclass fields.  None only for a CSV token that does not
        follow its instruction's syntax.
    fields:
        Every field the refusal is about, :attr:`field` first: ``(field,)`` for one field,
        and both for a pair (``CompareContact.left`` with ``CompareContact.right``).
    reason:
        Why, a :class:`Reason`; None where a check names no reason yet.
    click_id:
        CLICK's id for the error (``"OBJ-005"``), or None where CLICK has none.
    errors:
        Every refusal of one construction, this one first; ``(self,)`` for one refusal.
    obj:
        The instruction being built when its checks refused the value, or None.
    """

    field: str | None
    fields: tuple[str, ...]
    reason: Reason | None
    click_id: str | None
    errors: tuple[FieldError, ...]
    obj: Any

    def __init__(
        self,
        *args: object,
        field: str | tuple[str, ...] | None = None,
        reason: Reason | None = None,
        click_id: str | None = None,
        obj: Any = None,
    ) -> None:
        """``field`` is one field, or a tuple of the fields a refusal of a pair names."""
        super().__init__(*args)
        self.fields = (field,) if isinstance(field, str) else tuple(field or ())
        self.field = self.fields[0] if self.fields else None
        self.reason = reason
        self.click_id = click_id
        self.errors = (self,)
        self.obj = obj


class AddressError(FieldError):
    """A field holds an address outside CLICK's banks, ranges or allowed banks."""
