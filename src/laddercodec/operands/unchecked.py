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
:class:`~laddercodec.model.Instruction` and :class:`~laddercodec.model.Condition`
apply it to every subclass. The Modbus targets and the Modbus address apply it themselves.

An instruction is frozen, so the refusals that it holds are the refusals that it was
built with. If you change a field with :func:`replace`, it builds a new instruction and
runs every check again. A refused value raises. :func:`rebuilt` builds a copy that holds
the refusals of its values instead of raising them.

The decoders keep the blob that an instruction was read from in two cases. In the first,
the instruction holds refusals. In the second, its fields do not reproduce what CLICK
saved, as :func:`read_in_another_form` describes. Examples are stored text that the
decoder reads in another form, and the conversion that CLICK saved for a single Copy.
From the clipboard, the decoder keeps the blob and the row bytes of the cell. For an
instruction from a program file, it keeps the clipboard form of the entry's tags, and
the cell rows of an output box. :func:`keep_stored_blob` and :func:`keep_cell_rows` keep them.

``build_blob()`` returns the kept blob, and ``encode()`` writes it with the kept cell
rows, as it does for a ``RawInstruction``. If no blob was kept, ``build_blob()`` and
``encode()`` raise the first refusal that the instruction holds, unless the refusals were
allowed. A copy that :func:`replace` or :func:`rebuilt` makes keeps the blob only when the
copy changes no field. ``dataclasses.replace`` never passes the blob on.

A block can allow refusals by their codes: ``unchecked(allow=codes)``. Inside it, an
instruction keeps a refusal only if every error in the refusal has a code in *codes*, and
any other refusal raises. :func:`allowed` returns True for an instruction whose refusals
were all kept this way. ``build_blob()`` and ``encode()`` build the blob of such an
instruction from its fields. ``read_csv(..., allow=...)`` reads a CSV inside such a block.

Each instruction class, Modbus target and Modbus address accepts ``allow=codes`` as a
keyword (:class:`AllowsRefusals`). The constructor builds the instance inside
``unchecked(allow=codes)``, as ``read_csv(..., allow=codes)`` builds it.

:func:`replace` is public as ``laddercodec.replace``. The rest of this module is not
public API.
"""

from __future__ import annotations

import copy
import dataclasses
import functools
from collections.abc import Generator, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import InitVar, field, fields, is_dataclass
from typing import Any, TypeVar, cast

from ..codes import Code
from ..errors import LaddercodecError
from .address import NotDisplayForm
from .errors import FieldError, Reason

__all__ = [
    "AllowsRefusals",
    "allow_codes",
    "allowed",
    "checked",
    "fields_blob",
    "holds_refusals",
    "keep_cell_rows",
    "keep_stored_blob",
    "needs_stored_blob",
    "read_in_another_form",
    "rebuilt",
    "refusals",
    "replace",
    "stored_blob",
    "stored_cell_rows",
    "unchecked",
]

#: Fields that say where a box sits in the rung. No refusal that an instruction keeps
#: depends on one. A pin_rows that the check refuses always raises.
_LAYOUT_FIELDS = frozenset({"pin_rows"})

#: The list of refusals kept in the innermost :func:`unchecked` block. It is None outside
#: such a block and inside :func:`checked`.
_KEPT: ContextVar[list[FieldError] | None] = ContextVar("_KEPT", default=None)

#: The codes that the innermost :func:`unchecked` block allows. It is None when that block
#: allows every refusal that an instruction can keep, and outside any block.
_ALLOW: ContextVar[frozenset[str] | None] = ContextVar("_ALLOW", default=None)

#: Reasons for a refusal that construction always raises, even inside :func:`unchecked`.
_STRICT_REASONS = frozenset({Reason.CHOICE, Reason.FLAG})

_T = TypeVar("_T")


@contextmanager
def unchecked(allow: Iterable[str] | None = None) -> Generator[list[FieldError]]:
    """Let an instruction built inside the block keep a refusal of its checks instead of
    raising it.

    The block yields a list of the kept errors, one for each instruction, Modbus target or
    Modbus address built with refusals, in the order that they were built.

    With *allow*, an instruction keeps a refusal only if every error in the refusal has a
    code in *allow*. Any other refusal raises. Each instruction, Modbus target or Modbus
    address that keeps a refusal is marked, and :func:`allowed` reads the mark. A block
    nested inside this one allows only what its own *allow* names.
    """
    codes = None if allow is None else frozenset(allow)
    kept: list[FieldError] = []
    token = _KEPT.set(kept)
    allow_token = _ALLOW.set(codes)
    try:
        yield kept
    finally:
        _ALLOW.reset(allow_token)
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


def allow_codes(
    allow: Iterable[str] | None, *, caller: str, error: type[LaddercodecError] = LaddercodecError
) -> frozenset[Code]:
    """Return the codes that *allow* names. Read None as no codes.

    Each item is a code's name or a ``Code``. Raise *error* if *allow* is a string, bytes or
    not iterable, or if an item names no ``Code``. *caller* starts the message.
    """
    if allow is None:
        allow = ()
    if isinstance(allow, str):
        text = str(allow)
        raise error(
            f"{caller}: allow={text!r} is one code name. Pass a list of code names, such as "
            f"allow=[{text!r}]."
        )
    names: list[object] | None = None
    if not isinstance(allow, (bytes, bytearray)):
        try:
            names = list(allow)
        except TypeError:
            names = None  # not iterable
    if names is None:
        raise error(
            f"{caller}: allow={allow!r} is not a list of code names. Pass a list, such as "
            "allow=['bank-not-allowed']."
        )
    codes: set[Code] = set()
    for name in names:
        try:
            codes.add(Code(name))
        except ValueError:
            raise error(
                f"{caller}: allow= holds {name!r}, which is not a code. Use the name of a "
                "Code, such as 'bank-not-allowed'."
            ) from None
    return frozenset(codes)


@dataclasses.dataclass(frozen=True, eq=False, repr=False)
class AllowsRefusals:
    """A base class of each instruction class, Modbus target and Modbus address in
    laddercodec. It adds the keyword-only ``allow`` to the constructor of each dataclass
    that subclasses it. ``Condition`` and ``Instruction`` do not subclass it, so a
    caller's own subclass of them does not accept ``allow``.

    ``allow`` lists the codes of the refusals that you accept, such as
    ``Coil("X001", allow=["bank-not-allowed"])``. The instance keeps a refusal only if
    every error in it has a listed code. Any other refusal raises, as it does without
    ``allow``. The limits of ``read_csv(..., allow=...)`` apply too:

    - a refusal that construction always raises still raises;
    - an instruction that laddercodec can't write and read back the same raises its first
      refusal.

    The instance does not store ``allow``. Equality, hashing and ``repr`` ignore it.
    ``allow=None`` and ``allow=()`` build the instance as if you passed no ``allow``.

    A dataclass that subclasses this class must be frozen. A class that has no checks, such
    as ``End``, accepts ``allow``, checks the value and ignores it.

    A bad *allow* raises :class:`~laddercodec.LaddercodecError`, as :func:`allow_codes`
    describes.
    """

    allow: InitVar[Iterable[str] | None] = field(default=None, kw_only=True)

    def __post_init__(self, allow: Iterable[str] | None = None) -> None:
        allow_codes(allow, caller=type(self).__name__)


def holds_refusals(cls: type[_T]) -> type[_T]:
    """Wrap the ``__post_init__`` and ``build_blob`` that *cls* defines, and return *cls*.

    Inside :func:`unchecked`, the wrapped ``__post_init__`` keeps a refusal that the
    instance may hold instead of raising it. The wrapped ``build_blob`` returns the kept
    blob (:func:`stored_blob`), or raises the first refusal of an instance that holds
    refusals. It builds the blob of an instance whose refusals were all allowed
    (:func:`allowed`).

    The instance stores the error that construction raised as ``_refusal``. That error is
    the first refusal, and its ``errors`` holds every refusal. Each refusal that names no
    ``obj`` gets the instance as its ``obj``.
    Outside the block, or for a refusal that no instruction may keep, the error is raised
    as usual.

    The wrapped ``__post_init__`` takes the ``allow`` of :class:`AllowsRefusals`. With
    codes in it, construction runs inside ``unchecked(allow=codes)``. First, inside the
    same block, it builds again each Modbus target or Modbus address in a field of the
    instance, if that target or address holds refusals. Then, if no :func:`unchecked`
    block was open when construction started, and :func:`allowed` returns True for the
    instruction, construction checks that its blob reads back to it (``writes_back``). If
    the blob does not, construction raises the instruction's first refusal.
    """
    build_blob = cls.__dict__.get("build_blob")
    if build_blob is not None:
        cast("Any", cls).build_blob = _writing_stored_blob(build_blob)
    post_init = cls.__dict__.get("__post_init__")
    if post_init is None:
        return cls

    def keeping(self: Any) -> None:
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
            allow = _ALLOW.get()
            if allow is not None and not all(error.code in allow for error in exc.errors):
                raise
            for error in exc.errors:
                if error.obj is None:
                    error.obj = self
            object.__setattr__(self, "_refusal", exc)  # a Modbus target is frozen
            if allow is not None:
                object.__setattr__(self, "_allowed", True)
            kept.append(exc)

    @functools.wraps(post_init)
    def wrapper(self: Any, allow: Iterable[str] | None = None) -> None:
        if allow is None:
            if _KEPT.get() is not None:
                keeping(self)
                return
            # Outside a block, the instance can't keep a refusal of its own. Only a Modbus
            # target or address in a field can hold one, if it was built with allow=.
            post_init(self)
            if _nested_refusal(self):
                _raise_unwritable(self)
            return
        codes = allow_codes(allow, caller=type(self).__name__)
        outside = _KEPT.get() is None
        if codes:
            with unchecked(allow=codes):
                for f in fields(self):
                    nested = getattr(self, f.name)
                    if is_dataclass(nested) and not isinstance(nested, type) and refusals(nested):
                        object.__setattr__(self, f.name, _as_built(nested, {}))
                keeping(self)
        else:
            keeping(self)
        if outside:
            _raise_unwritable(self)

    cast("Any", cls).__post_init__ = wrapper
    return cls


def _nested_refusal(inst: object) -> bool:
    """Return whether a dataclass in a field of *inst*, or in a field of that dataclass,
    holds a refusal."""
    for value in getattr(inst, "__dict__", {}).values():
        if hasattr(type(value), "__dataclass_fields__") and (
            getattr(value, "_refusal", None) is not None or _nested_refusal(value)
        ):
            return True
    return False


def _raise_unwritable(inst: Any) -> None:
    """Raise the first refusal of *inst* if :func:`allowed` returns True for it and
    laddercodec can't write it and read it back the same.

    Do nothing for an object that is not an instruction, such as a Modbus target. The
    Send or Receive that holds it is checked when it is built.
    """
    if not allowed(inst):
        return
    from ..instructions import writes_back
    from ..model import Condition, Instruction

    if isinstance(inst, (Condition, Instruction)) and not writes_back(inst):
        raise refusals(inst)[0].with_traceback(None)


class _Held:
    """The blob and cell rows that an instruction was decoded from."""

    __slots__ = ("blob", "cell")

    def __init__(self, blob: bytes) -> None:
        self.blob = blob
        self.cell: dict[str, int] = {}


def refusals(inst: object) -> tuple[FieldError, ...]:
    """Return every refusal that *inst* holds, or an empty tuple if it holds none.

    An instruction built inside :func:`unchecked` holds the refusals that it was built
    with. The refusals of a Modbus target or Modbus address in a field of *inst* come
    first, because those are built first. The refusals of *inst* itself follow, in the
    order of each error's ``errors``.
    """
    return tuple(error for holder in _holders(inst) for error in holder._refusal.errors)


def allowed(inst: object) -> bool:
    """Return whether *inst* holds refusals and every one of them was kept inside an
    :func:`unchecked` block that allows its code.

    A Modbus target or Modbus address in a field of *inst* holds its own refusals, and they
    count too.
    """
    holders = list(_holders(inst))
    return bool(holders) and all(getattr(holder, "_allowed", False) for holder in holders)


def _holders(inst: object) -> Iterator[Any]:
    """Yield each object in *inst* that holds a refusal of its own, in the order of
    :func:`refusals`: the Modbus targets and Modbus addresses in its fields, then *inst*."""
    if is_dataclass(inst) and not isinstance(inst, type):
        for f in fields(inst):
            nested = getattr(inst, f.name)
            if is_dataclass(nested):
                yield from _holders(nested)
    if getattr(inst, "_refusal", None) is not None:
        yield inst


def rebuilt(inst: _T, **changes: Any) -> _T:
    """Return ``dataclasses.replace(inst, **changes)``, built inside :func:`unchecked` if
    *inst* holds a refusal.

    If *inst* holds refusals, the copy holds refusals too, instead of raising them. If
    *inst* holds none, the copy runs its checks as construction does.

    If *changes* names no field other than ``pin_rows``, the copy holds a copy of each of
    *inst*'s own errors. Each copy has the message, ``location``, fields,
    reason, code and CLICK id of its original, and names the copy of *inst* as its ``obj``.
    The errors of *inst* are not changed. A Modbus target or Modbus address in a field is
    the same object in *inst* and in the copy, so its errors are not copied. If *changes*
    names any other field, the checks run on the copy's values, and the copy holds the
    errors that they raise.

    If *changes* is empty, the copy also keeps the blob and cell rows that *inst* was
    decoded from.

    If *changes* names no field but ``pin_rows``, :func:`allowed` returns the same for the
    copy as for *inst*. Otherwise the copy is checked again. Inside an :func:`unchecked`
    block with *allow*, it keeps only the refusals that *allow* lists. Anywhere else,
    :func:`allowed` returns False for it, and ``encode()`` raises its first refusal.
    """
    if refusals(inst):
        with unchecked(allow=_ALLOW.get()):
            copied = dataclasses.replace(cast("Any", inst), **changes)
    else:
        copied = dataclasses.replace(cast("Any", inst), **changes)
    held = getattr(inst, "_held", None)
    if held is not None and not changes:
        object.__setattr__(copied, "_held", held)
    own = getattr(inst, "_refusal", None)
    if own is not None and set(changes) <= _LAYOUT_FIELDS:
        object.__setattr__(copied, "_refusal", _copied_errors(own, inst, copied))
        if getattr(inst, "_allowed", False):
            object.__setattr__(copied, "_allowed", True)
    return cast("_T", copied)


def _copied_errors(head: FieldError, inst: object, owner: object) -> FieldError:
    """Return a copy of *head*, whose ``errors`` holds a copy of each error in
    ``head.errors``.

    A copy of an error that names *inst* as its ``obj`` names *owner* instead.
    """
    twins = {id(error): copy.copy(error) for error in (head, *head.errors)}
    for error in (head, *head.errors):
        twin = twins[id(error)]
        twin.errors = tuple(twins.get(id(other), other) for other in error.errors)
        if error.obj is inst:
            twin.obj = owner
    return twins[id(head)]


def replace(inst: _T, /, **changes: Any) -> _T:
    """Return a copy of *inst*, an instruction or a ``Rung``, with the fields in *changes* set.

    An instruction is frozen, so call this to get one that differs. Name each field as a
    keyword, as for ``dataclasses.replace``. A name that is not a field of *inst* raises
    ``TypeError``.

    A value that is equal to the field's current value is no change. A value that the
    constructor would write in another form, such as ``"ds1"`` for ``"DS1"``, is a change.

    If any field changes, ``replace`` builds the copy from its values as if you built it
    new, and every check of the instruction runs. It also builds again each Modbus target
    or Modbus address in a field that holds a refusal. A refused value raises the
    :class:`~laddercodec.FieldError` that building the instruction raises. It raises even
    for a code that ``read_csv(..., allow=...)`` allowed when it read *inst*. The copy has
    no stored blob, so ``encode()`` writes the blob of its values.

    If no field changes, ``replace`` raises no refusal. The copy has the stored blob of
    *inst*, and the same refusals as *inst*:

    - ``encode()`` writes the blob and cell rows that *inst* was decoded from;
    - if *inst* was read with ``allow=`` and its refusals were allowed, ``encode()`` writes
      the blob of the copy's values;
    - otherwise, if *inst* has no stored blob, ``encode()`` raises the first refusal that
      the copy holds.

    ``allow`` is not a field, so ``replace(inst, allow=...)`` raises ``TypeError``. *inst*
    does not remember the ``allow=`` that it was built with. To build a changed copy that
    keeps a refusal, call the constructor with ``allow=``.

    A ``Rung`` is frozen too. ``replace(rung, instructions=...)`` returns a copy of the
    rung with those instructions. On a ``Rung``, no check runs. The copy holds the cells
    that you pass, and the cells of *rung* that you do not change, as they are.
    ``replace`` does not build them again.
    """
    if not is_dataclass(inst) or isinstance(inst, type):
        raise TypeError(f"replace() takes an instruction or a Rung, not {type(inst).__name__}")
    names = {f.name for f in fields(inst)}
    for name in changes:
        # dataclasses.replace would pass allow on, because allow is an InitVar of the class.
        if name not in names:
            raise TypeError(f"replace(): {type(inst).__name__} has no field {name!r}")
    changed = {name: value for name, value in changes.items() if value != getattr(inst, name)}
    if not changed:
        return rebuilt(inst)
    with checked():
        return _as_built(inst, changed)


def _as_built(inst: Any, changes: dict[str, Any]) -> Any:
    """Return ``dataclasses.replace(inst, **changes)``, and build again each Modbus target
    or Modbus address in a field that holds refusals.

    Call it inside :func:`checked`, so that each build raises its first refusal, or inside
    an :func:`unchecked` block, so that each build keeps what the block allows.
    """
    values = {f.name: getattr(inst, f.name) for f in fields(inst)} | changes
    nested = {
        name: _as_built(value, {})
        for name, value in values.items()
        if is_dataclass(value) and not isinstance(value, type) and refusals(value)
    }
    return dataclasses.replace(inst, **(changes | nested))


def read_in_another_form(inst: object) -> None:
    """Mark *inst* to keep the blob that it was decoded from, because its fields do not
    reproduce what CLICK saved.

    Two kinds of save need this. In the first, the decoder reads stored text in another
    form. It drops a space at the start or end of an address, it reads in display form
    an address that CLICK saved as typed, or it reads a TCP address without the leading
    zeros that CLICK saved. A decoded Math also holds laddercodec's form of a real that
    CLICK saved in another text, such as ``3E+38`` for ``3.0E+38``. In the second, a
    single Copy keeps the conversion type and destination end that CLICK saved. This
    applies to a type 7 conversion other than DD to or from DF, to a number's end in TXT,
    and to a pair that the encoder would write differently for those fields."""
    object.__setattr__(inst, "_read_in_another_form", True)


def needs_stored_blob(inst: object) -> bool:
    """Return whether the decoder should keep the blob that *inst* was read from.

    It should when *inst* holds refusals, or when :func:`read_in_another_form` marked it.
    """
    return bool(refusals(inst)) or getattr(inst, "_read_in_another_form", False)


def keep_stored_blob(inst: object, blob: bytes) -> None:
    """Store *blob*, the bytes that *inst* was decoded from. :func:`stored_blob` returns
    the blob.

    The decoders call it only for an instruction for which :func:`needs_stored_blob`
    returns True. No other instruction keeps a blob.
    """
    object.__setattr__(inst, "_held", _Held(blob))


def keep_cell_rows(inst: object, span: int, sub_rows: int) -> None:
    """Store the cell's row span (+0x09) and sub-rows (+0x0A) with the kept blob of *inst*,
    as a ``RawInstruction`` keeps them.

    Do nothing if *inst* has no kept blob. A value of zero is not stored.
    """
    held = getattr(inst, "_held", None)
    if held is None:
        return
    held.cell = {
        key: value for key, value in (("visual_rows", span), ("sub_rows", sub_rows)) if value
    }


def stored_blob(inst: object) -> bytes | None:
    """Return the blob that *inst* was decoded from, or None if no blob was kept."""
    held = getattr(inst, "_held", None)
    return None if held is None else held.blob


def stored_cell_rows(inst: object) -> dict[str, int]:
    """Return the cell rows kept with the blob of *inst* (:func:`keep_cell_rows`), or an
    empty dict if no blob was kept."""
    held: _Held | None = getattr(inst, "_held", None)
    return {} if held is None else dict(held.cell)


def fields_blob(inst: Any) -> bytes:
    """Return the blob that the fields of *inst* encode to.

    It ignores a stored blob, and it does not raise a refusal that *inst* holds. It
    raises what the encoder raises for a value that it cannot write.
    """
    build_blob = type(inst).build_blob
    return getattr(build_blob, "__wrapped__", build_blob)(inst)


def _writing_stored_blob(build_blob: Any) -> Any:
    """Wrap a ``build_blob`` method.

    The wrapper returns the kept blob if :func:`stored_blob` returns one. Otherwise it
    raises the first refusal of an instance that holds refusals that were not allowed
    (:func:`allowed`), or builds the blob.
    """

    @functools.wraps(build_blob)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> bytes:
        blob = stored_blob(self)
        if blob is not None:
            return blob
        found = refusals(self)
        if found and not allowed(self):
            raise found[0].with_traceback(None)
        return build_blob(self, *args, **kwargs)

    return wrapper
