"""Build a rung from its circuit, and lay it out as CLICK's syntax check draws it.

A :class:`Circuit` says which contacts are in series, which are in parallel and which boxes
they feed.  It has no rows or columns.  :func:`lay_out` returns the rungs that CLICK's syntax
check draws for it::

    from laddercodec import Box, Branch, Circuit, Coil, Contact, Parallel, lay_out

    circuit = Circuit(
        Branch(
            conditions=(Contact("X001"), Parallel((Contact("X002"), Contact("C1")))),
            outputs=(Box(Coil("Y001")),),
        ),
        comment="Start the pump",
    )
    rungs = lay_out(circuit)

Every class here is frozen and can be hashed.  Each one stores its parts as tuples.  A part
that the class does not take raises :class:`~laddercodec.FieldError` with the code
``invalid-circuit``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypeAlias

from .codes import Code
from .instructions.comparison import CompareContact
from .instructions.contact import Contact
from .model import Instruction, PinnedInstruction, Reason
from .operands.checks import Refusals

if TYPE_CHECKING:
    from .decode import Rung

__all__ = ["Box", "Branch", "Circuit", "Parallel", "Series", "Term", "lay_out"]

_CONTACT = "Contact('X001')"
_COIL_BOX = "Box(Coil('Y001'))"

#: The field that turns on each pin that an instruction can turn off.
_PIN_FLAGS = {
    ("Timer", ".reset"): "retained=True",
    ("Counter", ".down"): "down_enabled=True",
    ("Drum", ".jump"): "jump_enabled=True and a jump_step",
    ("Drum", ".jog"): "jog_enabled=True",
}


@dataclass(frozen=True, init=False)
class Series:
    """Terms in series, from left to right.

    ``Series(())``, an empty Series, is a wire.  It is allowed only as a leg of a
    :class:`Parallel`, where it is a wire-only Or leg.  CLICK holds such a leg, and its
    syntax check refuses it.  ``laddercodec.check()`` reports it.  The finding is C0002 when
    the wire is beside one contact.  It is C0001 when the wire is beside contacts in series.
    """

    terms: tuple[Term, ...]

    def __init__(self, terms: Iterable[Term]) -> None:
        with Refusals(self) as check:
            items = _store(self, check, "terms", terms, f"Series(({_CONTACT}, Contact('X002')))")
            for index, term in enumerate(items or ()):
                _check_term(check, f"terms[{index}]", term)


@dataclass(frozen=True, init=False)
class Parallel:
    """Two or more legs in parallel, drawn from the top down in the order given.

    A leg is a term.  ``Series(())`` as a leg is a wire-only Or leg.  At least one leg is
    not a wire.
    """

    legs: tuple[Term, ...]

    def __init__(self, legs: Iterable[Term]) -> None:
        example = f"Parallel(({_CONTACT}, Contact('X002')))"
        with Refusals(self) as check:
            items = _store(self, check, "legs", legs, example)
            if items is not None and len(items) < 2:
                one = " For one term, write the term without a Parallel." if items else ""
                check.refuse(
                    "legs",
                    f"has {len(items)} leg{'' if len(items) == 1 else 's'}. A Parallel needs two "
                    f"or more legs, such as {example}.{one}",
                    Reason.FORM,
                    code=Code.INVALID_CIRCUIT,
                )
            elif items and all(isinstance(leg, Series) and not leg.terms for leg in items):
                check.refuse(
                    "legs",
                    "holds only wires. A Parallel needs at least one leg that is not a wire, "
                    f"such as Parallel(({_CONTACT}, Series(()))).",
                    Reason.FORM,
                    code=Code.INVALID_CIRCUIT,
                )
            for index, leg in enumerate(items or ()):
                _check_term(check, f"legs[{index}]", leg, leg=True)


@dataclass(frozen=True, init=False)
class Box:
    """An output box: an ``Instruction``, or ``"NOP"``, with the circuit of each pin it uses.

    ``pins`` maps the name of a pin, such as ``".reset"``, to the term that feeds it.  The
    names are those of ``instruction.pin_names()`` whose entry in ``pin_labels()`` is not
    ``None``.  You may pass a dict.  The box stores the pins as ``(name, term)`` pairs, in
    the instruction's pin order.  A pin that the instruction uses and that ``pins`` leaves
    out is drawn with nothing wired to it.  ``laddercodec.check()`` reports such a pin.
    """

    instruction: Instruction | Literal["NOP"]
    pins: tuple[tuple[str, Term], ...]

    def __init__(
        self,
        instruction: Instruction | Literal["NOP"],
        pins: Mapping[str, Term] | Iterable[tuple[str, Term]] = (),
    ) -> None:
        object.__setattr__(self, "instruction", instruction)
        with Refusals(self) as check:
            is_box = isinstance(instruction, Instruction) or (
                isinstance(instruction, str) and instruction == "NOP"
            )
            if not is_box:
                check.refuse(
                    "instruction",
                    f"{instruction!r} is not an output instruction. Write an Instruction or "
                    f"'NOP', such as {_COIL_BOX}.",
                    Reason.FORM,
                    code=Code.INVALID_CIRCUIT,
                )
            pairs = _pairs(self, check, pins)
            names = instruction.pin_names() if isinstance(instruction, PinnedInstruction) else ()
            for index, (name, term) in enumerate(pairs):
                if is_box:
                    _check_pin(check, f"pins[{index}]", instruction, name)
                _check_term(check, f"pins[{index}]", term)
            pairs.sort(key=lambda pair: names.index(pair[0]) if pair[0] in names else len(names))
            object.__setattr__(self, "pins", tuple(pairs))


@dataclass(frozen=True, init=False)
class Branch:
    """Conditions in series from a net, then the outputs that hang off their end.

    ``conditions`` are terms in series.  With none, the outputs hang off the net that the
    branch starts from, which is the rail for a :class:`Circuit`'s branch.  ``outputs``
    are boxes and branches, drawn from the top down in the order given.  A branch needs at
    least one output.
    """

    conditions: tuple[Term, ...]
    outputs: tuple[Box | Branch, ...]

    def __init__(
        self, conditions: Iterable[Term] = (), outputs: Iterable[Box | Branch] = ()
    ) -> None:
        example = f"Branch(({_CONTACT},), ({_COIL_BOX},))"
        with Refusals(self) as check:
            terms = _store(self, check, "conditions", conditions, example)
            for index, term in enumerate(terms or ()):
                _check_term(check, f"conditions[{index}]", term)
            items = _store(self, check, "outputs", outputs, example)
            if items == ():
                check.refuse(
                    "outputs",
                    f"is empty. A Branch needs at least one output, such as {example}.",
                    Reason.MISSING,
                    code=Code.INVALID_CIRCUIT,
                )
            for index, item in enumerate(items or ()):
                if not isinstance(item, (Box, Branch)):
                    check.refuse(
                        f"outputs[{index}]",
                        f"{item!r} is not a Box or a Branch. Put an instruction in a Box, such "
                        f"as {_COIL_BOX}.",
                        Reason.FORM,
                        code=Code.INVALID_CIRCUIT,
                    )


@dataclass(frozen=True, init=False)
class Circuit:
    """One rung's circuit: a :class:`Branch` from the rail, and the rung's comment.

    The comment is Markdown text, as in ``Rung.comment``, or ``None``.
    """

    branch: Branch
    comment: str | None

    def __init__(self, branch: Branch, comment: str | None = None) -> None:
        object.__setattr__(self, "branch", branch)
        object.__setattr__(self, "comment", comment)
        with Refusals(self) as check:
            if not isinstance(branch, Branch):
                check.refuse(
                    "branch",
                    f"{branch!r} is not a Branch. Write a Branch from the rail, such as "
                    f"Circuit(Branch(({_CONTACT},), ({_COIL_BOX},))).",
                    Reason.FORM,
                    code=Code.INVALID_CIRCUIT,
                )
            if comment is not None and not isinstance(comment, str):
                check.refuse(
                    "comment",
                    f"{comment!r} is not text. Write the comment as a str, or pass None.",
                    Reason.FORM,
                    code=Code.INVALID_CIRCUIT,
                )


Term: TypeAlias = Contact | CompareContact | Series | Parallel
"""A term of a circuit: a ``Contact``, a ``CompareContact``, a ``Series`` or a ``Parallel``."""


def lay_out(circuit: Circuit) -> list[Rung]:
    """Return *circuit* as CLICK's syntax check draws it, one ``Rung`` for each CLICK rung.

    The list has more than one rung when outputs meet only at the rail.  CLICK splits such a
    circuit into one rung for each output, in order.  The comment goes on the first rung.
    Or legs and outputs are drawn from the top down in the order that the circuit gives.
    If the circuit has another output, ``lay_out`` drops a ``NOP`` that the rail feeds with
    no contact, and lays out the rest.  CLICK's syntax check does the same.

    ``lay_out`` draws any circuit that CLICK can hold, including the shapes that only CLICK's
    syntax check refuses, such as a wire-only Or leg or a contact that feeds only a ``NOP``.
    To find those shapes, call ``laddercodec.check()`` on the rungs that it returns.

    Raises :class:`~laddercodec.LayoutError` for a circuit that CLICK can't hold.  The
    error's ``code`` says why:

    - ``layout-too-tall``: a rung needs more than 32 rows;
    - ``layout-too-wide``: a rung needs more than the 31 condition columns, A to AE;
    - ``layout-cannot-draw``: two cells or two wires would fall on one place in the drawing;
    - ``layout-nop-split``: outputs meet only at the rail, and one of them is a ``NOP``
      behind a contact, or all of them are ``NOP`` boxes;
    - ``output-above-box-inputs`` or ``shared-input-net``, with ``click_id`` ``C000A``: an
      output comes before or after a box whose pin is used, and it hangs off the net of that
      box's main input, or off a net that the main input's circuit runs through.  The code is
      ``output-above-box-inputs`` for an output before the box, and ``shared-input-net`` for
      one after it.
    """
    from ._layout.build import lay_out as _lay_out

    return _lay_out(circuit)


def _store(
    obj: object, check: Refusals, attr: str, value: object, example: str
) -> tuple[object, ...] | None:
    """Store *value* on *obj* as a tuple, and return the tuple.

    Refuse a value that is not a sequence of parts, such as one bare contact, store it as
    it is, and return None.
    """
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Iterable):
        object.__setattr__(obj, attr, value)
        check.refuse(
            attr,
            f"{value!r} is not a tuple of parts. Write a tuple, such as {example}.",
            Reason.FORM,
            code=Code.INVALID_CIRCUIT,
        )
        return None
    items = tuple(value)
    object.__setattr__(obj, attr, items)
    return items


def _pairs(box: Box, check: Refusals, pins: object) -> list[tuple[object, object]]:
    """Return the (name, term) pairs of *pins*, a mapping or pairs.

    Refuse anything else, and a name given twice.
    """
    example = "{'.reset': Contact('X002')}"
    if isinstance(pins, Mapping):
        pairs = list(pins.items())
    elif isinstance(pins, Iterable) and not isinstance(pins, (str, bytes)):
        pairs = list(pins)
    else:
        pairs = None
    if pairs is None or not all(isinstance(p, tuple) and len(p) == 2 for p in pairs):
        object.__setattr__(box, "pins", pins)
        check.refuse(
            "pins",
            f"{pins!r} is not a mapping of pin names to terms. Write a dict, such as {example}.",
            Reason.FORM,
            code=Code.INVALID_CIRCUIT,
        )
        return []
    for index, (name, _term) in enumerate(pairs):
        if any(name == earlier for earlier, _ in pairs[:index]):
            check.refuse(
                f"pins[{index}]",
                f"names the pin {name!r} twice. Give each pin one term.",
                Reason.CONFLICT,
                code=Code.INVALID_CIRCUIT,
            )
    return pairs


def _check_pin(check: Refusals, attr: str, instruction: object, name: object) -> None:
    """Refuse *name* unless it is a pin that *instruction* uses."""
    cls = "NOP" if isinstance(instruction, str) else type(instruction).__name__
    if not isinstance(instruction, PinnedInstruction):
        check.refuse(
            attr,
            f"{name!r} is not a pin of {cls}. A {cls} has no pins, so pass no pins.",
            Reason.CHOICE,
            code=Code.INVALID_CIRCUIT,
        )
        return
    names = instruction.pin_names()
    used = [n for n, label in zip(names, instruction.pin_labels(), strict=True) if label]
    if name not in names:
        listed = ", ".join(repr(n) for n in names)
        check.refuse(
            attr,
            f"{name!r} is not a pin of {cls}. Write one of {listed}, such as "
            f"{{{names[0]!r}: Contact('X002')}}.",
            Reason.CHOICE,
            code=Code.INVALID_CIRCUIT,
        )
    elif name not in used:
        flag = _PIN_FLAGS.get((cls, str(name)))
        turn_on = f"Turn it on with {flag}" if flag else f"Turn it on in the {cls}"
        check.refuse(
            attr,
            f"{name!r} is turned off in this {cls}. {turn_on}, or leave {name!r} out of pins.",
            Reason.CONFLICT,
            code=Code.INVALID_CIRCUIT,
        )


def _check_term(check: Refusals, attr: str, term: object, *, leg: bool = False) -> None:
    """Refuse *term* unless it is a contact, a Series or a Parallel.

    An empty Series is refused unless *leg* is set, for a leg of a Parallel.
    """
    if isinstance(term, Series) and not term.terms and not leg:
        check.refuse(
            attr,
            "Series(()) is empty, and an empty Series is a wire. Use one only as a leg of a "
            f"Parallel, such as Parallel(({_CONTACT}, Series(()))).",
            Reason.FORM,
            code=Code.INVALID_CIRCUIT,
        )
    elif not isinstance(term, (Contact, CompareContact, Series, Parallel)):
        check.refuse(
            attr,
            f"{term!r} is not a contact or a circuit. Write a Contact, a CompareContact, a "
            f"Series or a Parallel, such as {_CONTACT}.",
            Reason.FORM,
            code=Code.INVALID_CIRCUIT,
        )
