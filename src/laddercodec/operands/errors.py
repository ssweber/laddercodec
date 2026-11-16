"""Field errors: a value CLICK's dialog refuses."""

from __future__ import annotations

from typing import Any


class FieldError(ValueError):
    """An instruction field holds a value CLICK's dialog refuses.

    The decoders' ``from_tags`` dispatchers catch it and leave the blob unparsed.

    Attributes
    ----------
    field:
        The field the raiser names (``Coil.range_end``, ``Drum.outputs[2]``), or None when the
        refusal is about no single field.
    obj:
        The instruction being built when its checks refused the value, or None.
    """

    field: str | None
    obj: Any

    def __init__(self, *args: object, field: str | None = None, obj: Any = None) -> None:
        super().__init__(*args)
        self.field = field
        self.obj = obj


class AddressError(FieldError):
    """A field holds an address outside CLICK's banks, ranges or allowed banks."""
