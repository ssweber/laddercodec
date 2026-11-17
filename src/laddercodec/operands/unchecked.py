"""Build an instruction from stored data even when its checks refuse a value.

Building an instruction raises a :class:`~laddercodec.operands.errors.FieldError` for a
value that CLICK's dialog refuses. Inside a :func:`unchecked` block, the instruction is
built anyway, with every value as given. It keeps the error that construction would raise,
and :func:`refusals` returns the refusals. The decoders build every instruction this way.
Because of that, an instruction that CLICK stored but that breaks a rule of CLICK's dialog
still decodes as an instance of its own class. ``read_csv(..., unchecked=True)`` does the
same for a CSV.

Some refusals cannot be kept by any instruction. These still raise inside the block:

- Text that is not in CLICK's display form, such as ``x1`` or ``C001``, in a field that
  CLICK saves in display form. CLICK never writes such text, and the CSV would read it
  back in display form. For a field that CLICK saves as typed, such as a Copy
  destination, the decoder puts the text in display form before it builds the
  instruction.
- A value that is not one of a field's named values (:attr:`~Reason.CHOICE`), or that is
  not a flag (:attr:`~Reason.FLAG`). The stored bytes cannot name such a value.
- A refusal of pin rows (``Timer.pin_rows``), because the box can't be laid out.
- A refusal that a check raised because it crashed on a value that it can't read.

An instruction class opts in with :func:`holds_refusals`.
:class:`~laddercodec.model.AfInstruction` and :class:`~laddercodec.model.ConditionInstruction`
apply it to every subclass. The Modbus targets and the Modbus address apply it themselves.

An instruction that holds refusals also keeps a snapshot of its field values as built.
While its fields still have those values, :func:`refusals` returns the refusals that it
was built with. Once a field changes, :func:`refusals` runs the construction checks on the
current values. If you fix a refused field by assigning a valid value to it, that field
has no refusal any more. A change to any dataclass field counts, ``pin_rows`` included,
except a change to ``wire_down``. The cell stores ``wire_down``, not the blob.

The decoders keep the blob that an instruction was read from in two cases. In the first,
the instruction holds refusals. In the second, its fields do not reproduce what CLICK
saved, as :func:`read_in_another_form` describes. Examples are stored text that the
decoder reads in another form, and the conversion that CLICK saved for a single Copy.
From the clipboard, the decoder keeps the blob and the row bytes of the cell. For an
output box from a program file, it keeps a blob composed from the box's tags, and the
cell rows. :func:`keep_stored_blob` and :func:`keep_cell_rows` keep them.

While the fields are unchanged, ``build_blob()`` returns the kept blob, and ``encode()``
writes it with the kept cell rows, as it does for a ``RawInstruction``. If a field has
changed, or no blob was kept, ``build_blob()`` and ``encode()`` raise the first refusal
that the instruction holds. If a field has changed and the instruction holds no refusal,
they write the blob of the copy that construction makes from the current values.
:func:`rebuilt` passes the kept blob on to a copy that changes only ``wire_down``.
``dataclasses.replace`` does not.

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

#: Fields that the cell stores rather than the blob. A change to one does not discard a
#: kept blob.
_CELL_FIELDS = frozenset({"wire_down"})

#: The list of refusals kept in the innermost :func:`unchecked` block. It is None outside
#: such a block and inside :func:`checked`.
_KEPT: ContextVar[list[FieldError] | None] = ContextVar("_KEPT", default=None)

#: Reasons for a refusal that construction always raises, even inside :func:`unchecked`.
_STRICT_REASONS = frozenset({Reason.CHOICE, Reason.FLAG})

_T = TypeVar("_T")


@contextmanager
def unchecked() -> Generator[list[FieldError]]:
    """Let an instruction built inside the block keep a refusal of its checks instead of
    raising it.

    The block yields a list of the kept errors, one for each instruction, Modbus target or
    Modbus address built with refusals, in the order that they were built.
    """
    kept: list[FieldError] = []
    token = _KEPT.set(kept)
    try:
        yield kept
    finally:
        _KEPT.reset(token)


@contextmanager
def checked() -> Generator[None]:
    """Make construction inside the block raise every refusal, as it does outside
    :func:`unchecked`."""
    token = _KEPT.set(None)
    try:
        yield
    finally:
        _KEPT.reset(token)


def _keepable(error: FieldError) -> bool:
    """Return whether an instruction built inside :func:`unchecked` may keep *error*."""
    from ..binary_helpers import NotANumber

    if isinstance(error, (NotDisplayForm, NotANumber)) or error.reason in _STRICT_REASONS:
        return False
    return not (error.field or "").endswith(".pin_rows")


def holds_refusals(cls: type[_T]) -> type[_T]:
    """Wrap the ``__post_init__`` and ``build_blob`` that *cls* defines, and return *cls*.

    Inside :func:`unchecked`, the wrapped ``__post_init__`` keeps a refusal that the
    instance may hold instead of raising it. The wrapped ``build_blob`` returns the kept
    blob (:func:`stored_blob`), or raises the first refusal of an instance that holds
    refusals.

    The instance stores the error that construction raised as ``_refusal``, with a snapshot
    of its field values as built. That error is the first refusal, and its ``errors`` holds
    every refusal. Each refusal that names no ``obj`` gets the instance as its ``obj``.
    Outside the block, or for a refusal that no instruction may keep, the error is raised
    as usual.
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
            # A refusal raised from another exception means that a check crashed on the
            # value.
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
    """The state that an instruction keeps when it holds refusals or a decoded blob.

    It holds a snapshot of the field values when the instruction was built or decoded,
    without ``wire_down``. It also holds the blob and cell rows that the instruction was
    decoded from, if the decoder kept them.
    """

    __slots__ = ("blob", "cell", "values")

    def __init__(self, values: object, blob: bytes | None = None) -> None:
        self.values = values
        self.blob = blob
        self.cell: dict[str, int] = {}


def _frozen(value: object) -> object:
    """Return a snapshot of *value* to compare with ``==`` later.

    A dataclass becomes its type and fields. A list, tuple or dict becomes its type and
    items.
    """
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
    """Return a snapshot of the field values of *inst*, without ``wire_down``, which the
    cell stores."""
    if not is_dataclass(inst):
        return ()
    return tuple(
        (f.name, _frozen(getattr(inst, f.name))) for f in fields(inst) if f.name not in _CELL_FIELDS
    )


def _unchanged(inst: object, held: _Held) -> bool:
    return _values(inst) == held.values


def _refusals_now(inst: object) -> tuple[FieldError, ...]:
    """Return the refusals that construction raises for the current values of *inst*, with
    every check raising as it does outside :func:`unchecked`."""
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
    """Return whether *obj* is the value of one of the fields of *inst*."""
    return is_dataclass(inst) and any(getattr(inst, f.name) is obj for f in fields(inst))


def refusals(inst: object) -> tuple[FieldError, ...]:
    """Return every refusal that *inst* holds, or an empty tuple if it holds none.

    While the field values of an instruction built inside :func:`unchecked` are as built,
    it holds the refusals that it was built with. Once a field changes, it holds the
    refusals that construction raises for the current values. The refusals of a Modbus
    target or Modbus address in a field of *inst* come first, because those are built
    first. The refusals of *inst* itself follow, in the order of each error's ``errors``.
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
    """Return ``replace(inst, **changes)``, built inside :func:`unchecked` if *inst* holds
    a refusal.

    If *inst* holds refusals, the copy keeps the refusals of its own values instead of
    raising them. If *inst* holds none, the copy runs its checks as construction does. A
    copy that changes only ``wire_down`` of an unchanged instruction also keeps the blob
    and cell rows that *inst* was decoded from. Each refusal that the copy keeps gets the
    ``location`` of the refusal of *inst* with the same fields, reason, code, CLICK id and
    message. The location says where ``read_csv`` read the value.
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
    """Give each refusal in *copies* that has no ``location`` the location of the refusal
    in *found* with the same fields, reason, code, CLICK id and message."""
    located = {_same(error): getattr(error, "location", None) for error in found}
    for error in copies:
        location = located.get(_same(error))
        if location is not None and getattr(error, "location", None) is None:
            object.__setattr__(error, "location", location)


def _same(error: FieldError) -> tuple[object, ...]:
    return (error.fields, error.reason, error.code, error.click_id, str(error))


def read_in_another_form(inst: object) -> None:
    """Mark *inst* to keep the blob that it was decoded from, because its fields do not
    reproduce what CLICK saved.

    Two kinds of save need this. In the first, the decoder reads stored text in another
    form. It drops a space at the start or end of an address, or it reads in display form
    an address that CLICK saved as typed. In the second, a single Copy keeps the conversion
    type and destination end that CLICK saved. This applies to a type 7 conversion other
    than DD to or from DF, to a number's end in TXT, and to a pair that the encoder would
    write differently for those fields."""
    object.__setattr__(inst, "_read_in_another_form", True)


def needs_stored_blob(inst: object) -> bool:
    """Return whether the decoder should keep the blob that *inst* was read from.

    It should when *inst* holds refusals, or when :func:`read_in_another_form` marked it.
    """
    return bool(refusals(inst)) or getattr(inst, "_read_in_another_form", False)


def keep_stored_blob(inst: object, blob: bytes) -> None:
    """Store *blob*, the bytes that *inst* was decoded from, with a snapshot of the current
    field values of *inst*. :func:`stored_blob` returns the blob.

    The decoders call it only for an instruction for which :func:`needs_stored_blob`
    returns True. No other instruction keeps a blob.
    """
    held = _Held(_values(inst), blob)
    object.__setattr__(inst, "_held", held)


def keep_cell_rows(inst: object, span: int, sub_rows: int) -> None:
    """Store the cell's row span (+0x09) and sub-rows (+0x0A) with the kept blob of *inst*,
    as a ``RawInstruction`` keeps them.

    Do nothing if *inst* has no kept blob. A value of zero is not stored.
    """
    held = getattr(inst, "_held", None)
    if held is None or held.blob is None:
        return
    held.cell = {
        key: value for key, value in (("visual_rows", span), ("sub_rows", sub_rows)) if value
    }


def stored_blob(inst: object) -> bytes | None:
    """Return the blob that *inst* was decoded from, or None if no blob was kept or a field
    other than ``wire_down`` has changed since."""
    held = getattr(inst, "_held", None)
    if held is None or held.blob is None or not _unchanged(inst, held):
        return None
    return held.blob


def stored_cell_rows(inst: object) -> dict[str, int]:
    """Return the cell rows kept with the blob of *inst* (:func:`keep_cell_rows`) while
    :func:`stored_blob` returns that blob, or an empty dict otherwise."""
    held: _Held | None = getattr(inst, "_held", None)
    if held is None or stored_blob(inst) is None:
        return {}
    return dict(held.cell)


def _writing_stored_blob(build_blob: Any) -> Any:
    """Wrap a ``build_blob`` method.

    The wrapper returns the kept blob if :func:`stored_blob` returns one. Otherwise it
    raises the first refusal of an instance that holds refusals, or builds the blob.
    """

    @functools.wraps(build_blob)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> bytes:
        blob = stored_blob(self)
        if blob is not None:
            return blob
        found = refusals(self)
        if found:
            raise found[0].with_traceback(None)
        if getattr(self, "_held", None) is not None:
            # The instance has changed since it was built from stored data, and its checks
            # pass. Write the blob of the copy that construction makes from its current
            # values, which has each address in display form.
            return build_blob(_as_constructed(self), *args, **kwargs)
        return build_blob(self, *args, **kwargs)

    return wrapper


def _as_constructed(inst: Any) -> Any:
    """Return a copy of *inst* that construction makes from its current values, with every
    check raising.

    A field value that keeps its own refusals, such as a Modbus target, is copied the same
    way.
    """
    changes = {}
    for f in fields(inst):
        nested = getattr(inst, f.name)
        if getattr(nested, "_held", None) is not None:
            changes[f.name] = _as_constructed(nested)
    with checked():
        return replace(inst, **changes)
