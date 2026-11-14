"""Field errors: a value CLICK's dialog refuses."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .sources import Src

#: A message that starts with the field it is about: ``Coil.range_end: ...``,
#: ``Drum.outputs[2]: ...``, ``Call.subroutine cannot be empty``.
_FIELD_PREFIX_RE = re.compile(r"([A-Z][A-Za-z0-9]*\.[a-z_][a-z0-9_]*(?:\[[0-9]+\])?)[: ]")


class FieldError(ValueError):
    """An instruction field holds a value CLICK's dialog refuses.

    The decoders' ``from_tags`` dispatchers catch it and leave the blob unparsed.

    Attributes
    ----------
    field:
        The field the message names (``Coil.range_end``, ``Drum.outputs[2]``), or None.
    obj:
        The instruction being built when its checks refused the value, or None.
    source:
        The rule's source, or None; internal, for laddercodec's own checks.
    """

    field: str | None
    obj: Any
    source: Src | None

    def __init__(
        self, *args: object, field: str | None = None, obj: Any = None, source: Src | None = None
    ) -> None:
        super().__init__(*args)
        if field is None and args and isinstance(args[0], str):
            match = _FIELD_PREFIX_RE.match(args[0])
            field = match.group(1) if match else None
        self.field = field
        self.obj = obj
        self.source = source


class AddressError(FieldError):
    """A field holds an address outside CLICK's banks, ranges or allowed banks."""
