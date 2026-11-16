"""Building an instruction from what is stored: it keeps the refusals of its checks.

Construction raises a :class:`~laddercodec.operands.errors.FieldError` for a value CLICK's
dialog refuses.  Inside :func:`unchecked`, an instruction whose checks refuse a value is
built anyway, with every value as given, and keeps the error construction would raise:
:func:`refusals` reads it.  The decoders build every instruction this way, so a stored
instruction that breaks a dialog rule decodes as that instruction; ``read_csv(...,
unchecked=True)`` does the same for a CSV.

A refusal no instruction can keep still raises inside the block:

- text not in CLICK's display form (``x1``, ``C001``): CLICK never writes it, and the CSV
  would read it back in display form;
- a value outside a field's named values (:attr:`~Reason.CHOICE`) or not a flag
  (:attr:`~Reason.FLAG`): the bytes name no such value;
- pin rows (``Timer.pin_rows``): the box can't be laid out;
- a refusal raised because a check crashed on a value it can't read.

An instruction class opts in with :func:`holds_refusals`; :class:`~laddercodec.model.AfInstruction`
and :class:`~laddercodec.model.ConditionInstruction` apply it to every subclass, and the Modbus
targets apply it themselves.

An instruction that holds refusals keeps its field values as built.  While they are
unchanged it holds those refusals; once one changes, :func:`refusals` runs construction's
checks on its values now, so a field fixed by assignment holds none.  Every dataclass field
counts (``pin_rows`` among them) except ``wire_down``, which the cell holds, not the blob.

The decoders keep the blob an instruction was read from when it holds refusals or read
stored text in another form: the clipboard's blob with the cell's row bytes, or for an
output box from a program file, the blob composed from its tags (:func:`keep_stored_blob`,
:func:`keep_cell_rows`).  While the fields are unchanged, ``build_blob()`` returns that
blob, and ``encode()`` writes it and the cell rows, as it does for a ``RawInstruction``.
Changed, or with no blob, ``build_blob()`` and ``encode()`` raise the first refusal it
holds; a changed one that holds none writes the blob of the copy construction makes from
its values now.  :func:`rebuilt` copies the blob to a copy that changes only
``wire_down``; ``dataclasses.replace`` does not.

Not public API.
"""

from __future__ import annotations

import functools
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import fields, is_dataclass, replace
from typing import Any, TypeVar, cast

from .address import NotDisplayForm
from .errors import FieldError, Reason

__all__ = [
    "checked",
    "holds_refusals",
    "keep_cell_rows",
    "keep_stored_blob",
    "needs_stored_blob",
    "read_in_another_form",
    "rebuilt",
    "refusals",
    "stored_blob",
    "stored_cell_rows",
    "unchecked",
]

#: Fields the cell holds rather than the blob: changing one keeps a stored blob.
_CELL_FIELDS = frozenset({"wire_down"})

#: The refusals kept inside the innermost :func:`unchecked` block; None outside one.
_KEPT: ContextVar[list[FieldError] | None] = ContextVar("_KEPT", default=None)

#: Reasons whose refusal no instruction keeps.
_STRICT_REASONS = frozenset({Reason.CHOICE, Reason.FLAG})

_T = TypeVar("_T")


@contextmanager
def unchecked() -> Generator[list[FieldError]]:
    """Inside the block, an instruction refused by its checks keeps the refusal and is built.

    The block yields a list of the errors kept in it, one per instruction (or Modbus
    target) built with refusals, in the order they were built.
    """
    kept: list[FieldError] = []
    token = _KEPT.set(kept)
    try:
        yield kept
    finally:
        _KEPT.reset(token)


@contextmanager
def checked() -> Generator[None]:
    """Inside the block, construction raises every refusal, as outside :func:`unchecked`."""
    token = _KEPT.set(None)
    try:
        yield
    finally:
        _KEPT.reset(token)


def _keepable(error: FieldError) -> bool:
    """Whether an instruction built from what is stored may keep *error* rather than raise."""
    from ..binary_helpers import NotANumber

    if isinstance(error, (NotDisplayForm, NotANumber)) or error.reason in _STRICT_REASONS:
        return False
    return not (error.field or "").endswith(".pin_rows")


def holds_refusals(cls: type[_T]) -> type[_T]:
    """Wrap ``cls.__post_init__`` so that inside :func:`unchecked` the instance keeps a
    refusal it can hold, rather than raise it, and ``cls.build_blob`` so that it writes a
    stored blob (:func:`stored_blob`) or refuses an instance that holds refusals.

    The instance keeps the error construction raises (the first refusal, whose ``errors``
    holds them all, each with the instance as its ``obj``) as ``_refusal``, with its field
    values as built.  Outside the block, or for a refusal no instruction keeps, the error
    is raised as before.
    """
    build_blob = cls.__dict__.get("build_blob")
    if build_blob is not None:
        cast("Any", cls).build_blob = _writing_stored_blob(build_blob)
    post_init = cls.__dict__.get("__post_init__")
    if post_init is None:
        return cls

    @functools.wraps(post_init)
    def wrapper(self: Any) -> None:
        try:
            post_init(self)
        except FieldError as exc:
            kept = _KEPT.get()
            # A refusal raised from another exception: a check crashed on the value.
            if kept is None or exc.__cause__ is not None:
                raise
            if not all(_keepable(error) for error in exc.errors):
                raise
            for error in exc.errors:
                if error.obj is None:
                    error.obj = self
            object.__setattr__(self, "_refusal", exc)  # a Modbus target is frozen
            object.__setattr__(self, "_held", _Held(_values(self)))
            kept.append(exc)

    cast("Any", cls).__post_init__ = wrapper
    return cls


class _Held:
    """What an instruction holds since it was built from what is stored: its field values
    then (``wire_down`` aside), and the blob and cell rows it was decoded from, if kept."""

    __slots__ = ("blob", "cell", "values")

    def __init__(self, values: object, blob: bytes | None = None) -> None:
        self.values = values
        self.blob = blob
        self.cell: dict[str, int] = {}


def _frozen(value: object) -> object:
    """*value* as a comparable snapshot: dataclasses by their fields, containers by items."""
    if is_dataclass(value) and not isinstance(value, type):
        return (
            type(value),
            tuple((f.name, _frozen(getattr(value, f.name))) for f in fields(value)),
        )
    if isinstance(value, (list, tuple)):
        return (type(value), tuple(_frozen(item) for item in value))
    if isinstance(value, dict):
        return (dict, tuple((key, _frozen(item)) for key, item in value.items()))
    return value


def _values(inst: object) -> object:
    """A snapshot of *inst*'s field values, but those the cell holds (``wire_down``)."""
    if not is_dataclass(inst):
        return ()
    return tuple(
        (f.name, _frozen(getattr(inst, f.name))) for f in fields(inst) if f.name not in _CELL_FIELDS
    )


def _unchanged(inst: object, held: _Held) -> bool:
    return _values(inst) == held.values


def _refusals_now(inst: object) -> tuple[FieldError, ...]:
    """The refusals construction raises for *inst*'s values now, run as outside a block."""
    try:
        with checked():
            replace(cast("Any", inst))
    except FieldError as exc:
        for error in exc.errors:
            if not _is_nested(error.obj, inst):
                error.obj = inst
        return tuple(exc.errors)
    return ()


def _is_nested(obj: object, inst: object) -> bool:
    """Whether *obj* is a value one of *inst*'s fields holds."""
    return is_dataclass(inst) and any(getattr(inst, f.name) is obj for f in fields(inst))


def refusals(inst: object) -> tuple[FieldError, ...]:
    """Every refusal *inst* holds; empty when none.

    An instruction built inside :func:`unchecked` holds the refusals it was built with
    while its field values are as built; once one changes, it holds those construction
    raises for its values now.  Those of the Modbus target and address it holds come
    first, as they are built first, then its own, each error's ``errors`` in order.
    """
    found: list[FieldError] = []
    if is_dataclass(inst):
        for f in fields(inst):
            nested = getattr(inst, f.name)
            if getattr(nested, "_held", None) is not None:
                found.extend(refusals(nested))
    held = getattr(inst, "_held", None)
    if held is None:
        return tuple(found)
    if not _unchanged(inst, held):
        return (*found, *_refusals_now(inst))
    own = getattr(inst, "_refusal", None)
    if own is not None:
        found.extend(own.errors)
    return tuple(found)


def rebuilt(inst: _T, **changes: Any) -> _T:
    """``replace(inst, **changes)``, built inside :func:`unchecked` when *inst* holds a refusal.

    A copy of an instruction built from what is stored keeps its refusals; one that
    changes only ``wire_down`` keeps the blob and cell rows it was decoded from too.  Any
    other copy runs its checks as construction does.  Each refusal the copy keeps takes the
    ``location`` (where ``read_csv`` read it) of the one *inst* holds with the same field,
    reason, id and message.
    """
    found = refusals(inst)
    if found:
        with unchecked():
            copied = replace(cast("Any", inst), **changes)
    else:
        copied = replace(cast("Any", inst), **changes)
    held = getattr(inst, "_held", None)
    if held is not None and set(changes) <= _CELL_FIELDS and _unchanged(inst, held):
        object.__setattr__(copied, "_held", held)
        own = getattr(inst, "_refusal", None)
        if own is not None:
            object.__setattr__(copied, "_refusal", own)
    _carry_locations(found, refusals(copied))
    return cast("_T", copied)


def _carry_locations(found: tuple[FieldError, ...], copies: tuple[FieldError, ...]) -> None:
    """Give each refusal in *copies* without a ``location`` that of the refusal in *found*
    with the same fields, reason, id and message."""
    located = {_same(error): getattr(error, "location", None) for error in found}
    for error in copies:
        location = located.get(_same(error))
        if location is not None and getattr(error, "location", None) is None:
            object.__setattr__(error, "location", location)


def _same(error: FieldError) -> tuple[object, ...]:
    return (error.fields, error.reason, error.click_id, str(error))


def read_in_another_form(inst: object) -> None:
    """Mark *inst*, built from stored text it reads in another form (an address with a
    space at its edge read without it), as one that keeps its stored blob when decoded."""
    object.__setattr__(inst, "_read_in_another_form", True)


def needs_stored_blob(inst: object) -> bool:
    """Whether *inst*, decoded, keeps the blob it was read from: it holds
    refusals, or was read in another form (:func:`read_in_another_form`)."""
    return bool(refusals(inst)) or getattr(inst, "_read_in_another_form", False)


def keep_stored_blob(inst: object, blob: bytes) -> None:
    """Keep *blob*, the bytes *inst* was decoded from, for :func:`stored_blob`, with
    *inst*'s field values now.

    The decoders call it for an instruction :func:`needs_stored_blob` names; no other
    instruction keeps a blob.
    """
    held = _Held(_values(inst), blob)
    object.__setattr__(inst, "_held", held)


def keep_cell_rows(inst: object, span: int, sub_rows: int) -> None:
    """Keep the cell's row span (+0x09) and sub-rows (+0x0A) with *inst*'s stored blob, as a
    ``RawInstruction`` keeps them; a zero is not kept."""
    held = getattr(inst, "_held", None)
    if held is None or held.blob is None:
        return
    held.cell = {
        key: value for key, value in (("visual_rows", span), ("sub_rows", sub_rows)) if value
    }


def stored_blob(inst: object) -> bytes | None:
    """The blob *inst* was decoded from, while every field it holds is as decoded; else None."""
    held = getattr(inst, "_held", None)
    if held is None or held.blob is None or not _unchanged(inst, held):
        return None
    return held.blob


def stored_cell_rows(inst: object) -> dict[str, int]:
    """The cell rows kept with *inst*'s stored blob (:func:`keep_cell_rows`), while it
    writes that blob; else empty."""
    held: _Held | None = getattr(inst, "_held", None)
    if held is None or stored_blob(inst) is None:
        return {}
    return dict(held.cell)


def _writing_stored_blob(build_blob: Any) -> Any:
    """Wrap a ``build_blob``: write the stored blob, refuse an instance that holds refusals
    and has none, else build as before."""

    @functools.wraps(build_blob)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> bytes:
        blob = stored_blob(self)
        if blob is not None:
            return blob
        found = refusals(self)
        if found:
            raise found[0].with_traceback(None)
        if getattr(self, "_held", None) is not None:
            # Changed since it was built from what is stored, and accepted: write what
            # construction makes of its values now (an address in display form).
            return build_blob(_as_constructed(self), *args, **kwargs)
        return build_blob(self, *args, **kwargs)

    return wrapper


def _as_constructed(inst: Any) -> Any:
    """A copy of *inst* that construction makes from its values now, checked, with each
    held instruction it holds (a Modbus target) made the same way."""
    changes = {}
    for f in fields(inst):
        nested = getattr(inst, f.name)
        if getattr(nested, "_held", None) is not None:
            changes[f.name] = _as_constructed(nested)
    with checked():
        return replace(inst, **changes)
