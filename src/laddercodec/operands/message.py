"""The parts of a refusal's message, and the text that they render.

A refusal keeps its message as parts (:class:`Parts`): the label before the colon, the
operand with its short rule, the explanation, CLICK's id and a sentence that says what to
do.  ``str(err)`` is the text that the parts render with no names.
:meth:`~laddercodec.errors.LaddercodecError.message`,
:meth:`~laddercodec.errors.LaddercodecError.short` and
:meth:`~laddercodec.errors.LaddercodecError.detail` render them with a caller's names for
the addresses.

Each value from the caller's input that a message names is an :class:`Op`.  A check builds
its rule with :func:`says`, and builds the error with :func:`make_refusal`::

    raise make_refusal(
        AddressError,
        name,
        says("{value} is not allowed", "{label} takes {banks}", value=Op(value), banks=listed),
        field=field,
        reason=Reason.BANK,
        code=Code.BANK_NOT_ALLOWED,
    )

Not public API.
"""

from __future__ import annotations

import dataclasses
import re
import reprlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from string import Formatter
from typing import TYPE_CHECKING, NamedTuple, TypeVar

if TYPE_CHECKING:
    from ..codes import Code
    from ..errors import LaddercodecError
    from .errors import FieldError, Reason

__all__ = [
    "LABEL",
    "Op",
    "Parts",
    "Rule",
    "from_parts",
    "named_addresses",
    "operand",
    "parts_of",
    "make_refusal",
    "says",
    "set_parts",
    "shown",
    "type_name",
    "with_click_id",
    "wrong_type",
]


class Op(NamedTuple):
    """A value from the caller's input that a refusal names, such as an address, a range, a
    pointer or a constant.

    ``text`` is the value in CLICK's form, as the message shows it.  A range is two ends
    joined by ``..`` (``C1..C2``).  With ``quoted``, ``str(err)`` shows the value in repr
    quotes (``'C1'``).  Without it, the value is shown bare (``C1..C2 spans two slots``).
    ``typed`` is the text that the caller typed, when it is not CLICK's form.  A quoted
    value with ``typed`` is shown as ``'x1' (X001)``.  The decorator in
    :mod:`~laddercodec.operands.address` sets ``typed``.  A check leaves it None.
    """

    text: str
    quoted: bool = True
    typed: str | None = None


def operand(value: object) -> Op | str:
    """Return ``value`` as an :class:`Op` if it is text, or its repr otherwise.

    Use it for a field that may hold a value that is not text, such as ``2`` in a flag.
    ``str(err)`` shows both forms as ``repr(value)``.  A value that is not text is never an
    address.
    """
    return Op(value) if isinstance(value, str) else _repr(value)


def _repr(value: object) -> str:
    """Return ``repr(value)``, or the default repr of the object if ``repr()`` raises."""
    try:
        return repr(value)
    except Exception:  # noqa: BLE001 - a caller's __repr__ can raise anything
        return object.__repr__(value)


#: The longest repr that :func:`shown` returns whole.
_SHOWN_MAX = 80

_SHORT = reprlib.Repr()
_SHORT.maxstring = 40
_SHORT.maxother = 40


def shown(value: object) -> str:
    """Return the repr of ``value`` for a message, shortened if it is long.

    A repr of up to 80 characters is returned whole.  :mod:`reprlib` shortens a longer one,
    so ``list(range(1000))`` is shown as ``[0, 1, 2, 3, 4, 5, ...]``.  If ``repr()`` raises,
    the result is the default repr of the object, such as ``<Thing object at 0x...>``.
    """
    text = _repr(value)
    if len(text) <= _SHOWN_MAX:
        return text
    try:
        return _SHORT.repr(value)
    except Exception:  # noqa: BLE001 - a caller's __repr__ can raise anything
        return text[:_SHOWN_MAX] + "..."


#: The names of the common Python types, as a refusal of a value of the wrong type says them.
_TYPE_NAMES: dict[type, str] = {
    type(None): "None",
    bool: "a bool",
    int: "an int",
    float: "a float",
    complex: "a complex",
    bytes: "bytes",
    bytearray: "a bytearray",
    str: "a str",
    list: "a list",
    tuple: "a tuple",
    dict: "a dict",
    set: "a set",
    frozenset: "a frozenset",
}


def type_name(value: object) -> str:
    """Return the name of the type of ``value`` for a message, such as ``an int``.

    A type that is not in :data:`_TYPE_NAMES` is named by its class, such as ``a Thing``.
    """
    known = _TYPE_NAMES.get(type(value))
    if known is not None:
        return known
    name = type(value).__name__
    return f"{'an' if name[:1].lower() in 'aeiou' else 'a'} {name}"


def wrong_type(value: object, wanted: str) -> Rule:
    """Return the rule that ``value`` is not ``wanted``, such as ``5 is an int, not text``.

    The rule shows ``value`` with :func:`shown` and names its type with :func:`type_name`.
    None is its own type, so its rule is ``None is not text``.
    """
    if value is None:
        return says("None is not {wanted}", wanted=wanted)
    return says(
        "{value} is {kind}, not {wanted}", value=shown(value), kind=type_name(value), wanted=wanted
    )


class _Label(Enum):
    LABEL = "label"


#: The place in a rule where the refusal's label goes.  :func:`says` puts it at each
#: ``{label}`` of a template.  Two refusals that differ only in their label and their
#: operand then have equal rules (see :func:`~laddercodec.instructions.copy._range_refusal`).
LABEL = _Label.LABEL

#: A piece of a rule: plain text, an operand, or the label.
Piece = str | Op | _Label


class Rule(NamedTuple):
    """The text of a refusal after its label: the operand with its short rule, and the
    explanation.  ``str(err)`` joins them with ``"; "``."""

    short: tuple[Piece, ...]
    detail: tuple[Piece, ...] = ()


_FORMATTER = Formatter()


def _pieces(template: str, values: Mapping[str, object]) -> tuple[Piece, ...]:
    """Return ``template`` as pieces, with each ``{name}`` replaced by ``values[name]``.

    An :class:`Op` stays a piece of its own.  ``{label}`` is :data:`LABEL`.  Any other value
    is formatted into the text, with the template's conversion and format spec, as
    ``str.format`` does.
    """
    pieces: list[Piece] = []
    for literal, name, spec, conversion in _FORMATTER.parse(template):
        if literal:
            pieces.append(literal)
        if name is None:
            continue
        value = LABEL if name == "label" else values[name]
        if isinstance(value, (Op, _Label)):
            if spec or conversion:
                raise TypeError(f"{{{name}}} is an operand or the label; it takes no format")
            pieces.append(value)
            continue
        text = _FORMATTER.format_field(_FORMATTER.convert_field(value, conversion), spec or "")
        pieces.append(text)
    merged: list[Piece] = []
    for piece in pieces:
        if isinstance(piece, str) and merged and isinstance(merged[-1], str):
            merged[-1] += piece
        else:
            merged.append(piece)
    return tuple(merged)


def says(short: str, detail: str = "", /, **values: object) -> Rule:
    """Return the :class:`Rule` that the templates ``short`` and ``detail`` spell.

    A template is ``str.format`` text.  Each ``{name}`` takes ``values[name]``, and
    ``{label}`` takes the label of the refusal.  Pass each value from the caller's input as
    an :class:`Op`.  Pass any other value, such as a bank list or a limit, as itself.
    """
    if "label" in values:
        raise TypeError("{label} is the refusal's label; pass no value for it")
    return Rule(_pieces(short, values), _pieces(detail, values) if detail else ())


@dataclass(frozen=True)
class Parts:
    """The parts of a refusal's message.

    The message is ``label: short (id); detail (id). then``, with CLICK's id in one of its
    two places.  A part that is empty or None is left out with its separator.
    """

    #: The name before the colon, such as ``Copy.dest``, or None for no prefix.
    label: str | None
    #: The operand and its short rule.
    short: tuple[Piece, ...]
    #: The explanation.
    detail: tuple[Piece, ...] = ()
    #: CLICK's id as the message shows it.  A refusal can hold a ``click_id`` that its
    #: message does not show.
    click_id: str | None = None
    #: Whether the id follows the short rule.  It follows the explanation otherwise.
    id_after_short: bool = False
    #: A sentence that tells the user what to do.  It follows the id.
    then: str = ""

    def text(self, named: Mapping[str, str] | None = None) -> str:
        """Return the whole message, with ``named`` (display form to name) applied."""
        label = self.label or ""
        body = self._render(self.short, named, label)
        tail = f" ({self.click_id})" if self.click_id else ""
        if self.id_after_short:
            body += tail
        if self.detail:
            body += "; " + self._render(self.detail, named, label)
        if not self.id_after_short:
            body += tail
        if self.then:
            body += f". {self.then}"
        return body if self.label is None else f"{self.label}: {body}"

    def short_text(self, named: Mapping[str, str] | None = None) -> str:
        """Return the operand and its short rule.

        Where the rule names the label, it says ``this field`` instead (see
        :func:`_this_field`).
        """
        return self._render(self.short, named, _this_field(self.label))

    def detail_text(self, named: Mapping[str, str] | None = None) -> str:
        """Return the explanation, followed by the sentence that says what to do.

        Where the explanation names the label, it says ``this field`` instead (see
        :func:`_this_field`).
        """
        detail = self._render(self.detail, named, _this_field(self.label))
        if detail and self.then:
            return f"{detail}. {self.then}"
        return detail or self.then

    def _render(
        self, pieces: tuple[Piece, ...], named: Mapping[str, str] | None, label: str
    ) -> str:
        out = []
        for piece in pieces:
            if isinstance(piece, Op):
                out.append(_shown(piece, named))
            elif piece is LABEL:
                out.append(label)
            else:
                assert isinstance(piece, str)
                out.append(piece)
        return "".join(out)

    def ops(self) -> tuple[Op, ...]:
        """Return the operands of the short rule and the explanation, in order."""
        return tuple(p for p in (*self.short, *self.detail) if isinstance(p, Op))

    def map_ops(self, change: Callable[[Op], Op]) -> Parts:
        """Return the parts with each operand ``op`` replaced by ``change(op)``."""

        def each(pieces: tuple[Piece, ...]) -> tuple[Piece, ...]:
            return tuple(change(p) if isinstance(p, Op) else p for p in pieces)

        return dataclasses.replace(self, short=each(self.short), detail=each(self.detail))

    def typed(self, single: Mapping[str, str]) -> Parts:
        """Return the parts with the typed text of each quoted operand that the caller typed
        in another form.

        ``single`` maps a display form to the one text that the caller typed for it.  A
        range gets the typed text of both ends when both are in ``single`` and either end
        was typed in another form.
        """

        def change(op: Op) -> Op:
            if not op.quoted or not isinstance(op.text, str):
                return op
            first, dots, last = op.text.partition("..")
            if dots and first in single and last in single:
                typed = f"{single[first]}..{single[last]}"
            else:
                typed = single.get(op.text, op.text)
            return op if typed == op.text else op._replace(typed=typed)

        return self.map_ops(change)


#: A label that names one field: ``Copy.dest``, ``Drum.events[0]``, ``Send source`` or a
#: bare ``done``.  It may end in `` pointer`` or in a note in brackets, such as ``(FC16)``.
_FIELD_LABEL = re.compile(r"(?:[A-Z]\w*[. ])?[a-z_]\w*(?:\[\d+\])?(?P<rest>| pointer| \(.*\))")


def _this_field(label: str | None) -> str:
    """Return the words that :meth:`Parts.short_text` and :meth:`Parts.detail_text` put in
    place of ``label``.

    A caller shows these texts next to the field, so a label that names the field becomes
    ``this field``.  ``Copy.source pointer`` becomes ``the pointer``, and
    ``Send source (FC16)`` becomes ``this field (FC16)``.  Any other label is kept, such
    as ``range end of 'C1..'``.
    """
    if label is None:
        return ""
    match = _FIELD_LABEL.fullmatch(label)
    if match is None:
        return label
    rest = match.group("rest")
    return "the pointer" if rest == " pointer" else f"this field{rest}"


def _shown(op: Op, named: Mapping[str, str] | None) -> str:
    """Return ``op`` as a message shows it.

    With ``named`` None, a quoted operand is in repr quotes, with its typed text in front
    of CLICK's form when there is one.  With ``named`` a mapping, even an empty one, an
    operand that holds an address is shown as typed without quotes, with each address in
    ``named`` replaced by its name.  CLICK's form follows in parentheses when the two
    differ.  They do not differ when each name that is not CLICK's form is another form of
    the same address, such as ``X1`` for ``X001``.  An operand that holds no address is
    shown as it is with ``named`` None.

    A text constant such as ``"AB"`` is shown in its own double quotes, with no repr
    quotes around them.
    """
    # A caller can pass a field a value that is not text.  Such a value names no address.
    if (
        named is not None
        and isinstance(op.text, str)
        and _renamed(op.text, {}, loose=False) is not None
    ):
        base = op.text if op.typed is None else op.typed
        loose = op.typed is not None
        shown = _renamed(base, named, loose=loose)
        if shown is not None:
            if shown == op.text:
                return shown
            # Compare with each name that is its own address put back in CLICK's form.
            own = {d: d for d, name in named.items() if _display(name, loose=True) == d}
            if own and _renamed(base, {**named, **own}, loose=loose) == op.text:
                return shown
            return f"{shown} ({op.text})"
    if not op.quoted or _is_text_constant(op.text):
        return op.text
    if op.typed is not None and op.typed != op.text:
        return f"{op.typed!r} ({op.text})"
    return repr(op.text)


def _is_text_constant(text: object) -> bool:
    """Return whether ``text`` is a text constant in its double quotes, such as ``"AB"``.

    Text with a quote inside, or with a character that repr would escape, such as a
    newline, is not one here.  Without the repr quotes, a reader could not tell where it
    ends.
    """
    return (
        isinstance(text, str)
        and len(text) >= 2
        and text[0] == text[-1] == '"'
        and '"' not in text[1:-1]
        and text.isprintable()
    )


def _display(text: str, *, loose: bool) -> str | None:
    """Return the display form of the address ``text``, or None if it is no CLICK address.

    With ``loose``, ``text`` may be in any letter case and have leading zeros (``x1``).
    """
    # Imported here because the address module builds its refusals with this one.
    from .address import _loose_display, parse_address

    if loose:
        loosened = _loose_display(text)
        if loosened is None:
            return None
        text = loosened
    address = parse_address(text)
    return None if address is None else address.display


def _renamed(text: str, named: Mapping[str, str], *, loose: bool) -> str | None:
    """Return ``text`` with each address in it replaced by its name in ``named``.

    ``text`` is an address, a pointer or a range of two of them.  In a pointer, only the
    index is an address.  Return None if ``text`` holds no address.
    """
    from .address import ADDRESS_BANKS, _loose_pointer, split_pointer

    ends = text.split("..")
    if len(ends) > 2:
        return None
    out: list[str] = []
    found = False
    for end in ends:
        pointer = _loose_pointer(end) if loose else split_pointer(end)
        if pointer is not None and pointer[0] in ADDRESS_BANKS:
            index = pointer[1]
            display = _display(index, loose=loose)
            if display is not None:
                found = True
                out.append(f"{end[: end.index('[')]}[{named.get(display, index)}]")
                continue
        else:
            display = _display(end, loose=loose)
            if display is not None:
                found = True
                out.append(named.get(display, end))
                continue
        out.append(end)
    return "..".join(out) if found else None


def named_addresses(names: Mapping[str, object] | None) -> dict[str, str]:
    """Return ``names`` keyed by display form, as :meth:`Parts.text` reads it.

    A key may be in any form that CLICK reads (``ds1``, ``DS001``).  A key that is no CLICK
    address is left out.  If two keys are one address, the later key's name is kept.
    """
    out: dict[str, str] = {}
    for key, name in (names or {}).items():
        display = _display(key, loose=True) if isinstance(key, str) else None
        if display is not None:
            out[display] = str(name)
    return out


# ---------------------------------------------------------------------------
# Errors with parts
# ---------------------------------------------------------------------------

_E = TypeVar("_E", bound="FieldError")


def make_refusal(
    cls: type[_E],
    label: str | None,
    said: Rule,
    *,
    field: str | tuple[str, ...] | None,
    reason: Reason | None,
    code: Code,
    click_id: str | None = None,
    id_after_short: bool = False,
    then: str = "",
) -> _E:
    """Return a ``cls`` error whose message is ``label: said`` and keeps its parts.

    The message shows ``click_id`` after the explanation, or after the short rule with
    ``id_after_short``.  ``then`` follows the id.
    """
    parts = Parts(label, said.short, said.detail, click_id, id_after_short, then)
    return from_parts(cls, parts, field=field, reason=reason, code=code, click_id=click_id)


def from_parts(
    cls: type[_E],
    parts: Parts,
    *,
    field: str | tuple[str, ...] | None,
    reason: Reason | None,
    code: Code,
    click_id: str | None,
) -> _E:
    """Return a ``cls`` error whose message is the text of ``parts``, and keep the parts."""
    error = cls(parts.text(), field=field, reason=reason, code=code, click_id=click_id)
    error._parts = parts
    return error


def parts_of(error: LaddercodecError) -> Parts | None:
    """Return the parts of ``error``'s message, or None if it has none.

    Return None also when ``str(error)`` is not the text that the parts render, which
    happens if code outside this module rewrote the message.
    """
    parts = error._parts
    if not isinstance(parts, Parts) or str(error) != parts.text() + error._suffix:
        return None
    return parts


def set_parts(error: LaddercodecError, parts: Parts) -> None:
    """Give ``error`` the message that ``parts`` render, and keep the parts."""
    error._parts = parts
    error.args = (parts.text() + error._suffix,)


def with_click_id(error: _E, click_id: str) -> _E:
    """Return a copy of ``error`` with ``(click_id)`` at the end of its message.

    The copy has the same class, fields, reason and code, and ``click_id`` as its id.
    ``error`` must show no id.
    """
    parts = parts_of(error)
    kwargs = {"field": error.fields, "reason": error.reason, "code": error.code}
    if parts is None or parts.click_id is not None or parts.then:
        return type(error)(f"{error} ({click_id})", click_id=click_id, **kwargs)
    shown = dataclasses.replace(parts, click_id=click_id, id_after_short=False)
    return from_parts(type(error), shown, click_id=click_id, **kwargs)
