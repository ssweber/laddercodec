"""Every refusal that an instruction's ``__post_init__`` raises names a field of that instruction.

The fixture below wraps ``address._refused``, the step that completes each refusal of an
instruction class's ``__post_init__``.  Every test that builds a refused instruction therefore
also checks the shape of each refusal:

- ``field`` is the first item of ``fields``.
- Each item of ``fields`` is ``Class.attr`` or ``Class.attr[i]``.  ``Class`` is the class name
  of the instance that the refusal is about, and ``attr`` is one of its dataclass fields.
- ``reason`` is a :class:`~laddercodec.Reason` or None.  A refusal by a class in ``REASONED``
  always has a reason.
- ``code`` is a :class:`~laddercodec.Code`.  ``click_id`` is None or one of the ids that
  ``CLICK_IDS`` lists for that code.
- A refusal by a class in ``NAMED`` keeps the parts of its message, and ``str(err)`` is the
  text that the parts render.  ``err.message(names)`` can then show the user's names.

A refusal that breaks a rule fails the test that built it with an ``AssertionError``.

The fixture sees only the refusals that the suite builds, and only those that an instruction
class's ``__post_init__`` raises.  It does not see the refusals of CSV token parsing.
``tests/test_field_names.py`` checks every field name that is written out in the source.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterator
from typing import Any

import pytest

from laddercodec.codes import CLICK_IDS, Code
from laddercodec.operands import address
from laddercodec.operands.errors import FieldError, Reason
from laddercodec.operands.message import parts_of

_FIELD = re.compile(r"(\w+)\.(\w+)(?:\[\d+\])?")

#: The instruction classes in which every refusal must have a reason, a member of ``Reason``.
REASONED = frozenset(
    {
        "Coil",
        "Timer",
        "Contact",
        "CompareContact",
        "OutVariant",
        "Counter",
        "Shift",
        "Call",
        "ForLoop",
        "Drum",
        "Search",
        "Copy",
        "BlockCopy",
        "Fill",
        "Pack",
        "Unpack",
        "Math",
        "Send",
        "Receive",
        "RawInstruction",
        "Undecoded",
    }
)

#: The instruction classes whose refusals keep the parts of their messages.
NAMED = frozenset(
    {
        "Copy", "BlockCopy", "Fill", "Pack", "Unpack",
        "Coil", "OutVariant", "Contact", "CompareContact",
        "Timer", "Counter", "Shift", "ForLoop", "Drum",
        "Send", "Receive", "ModbusRtuTarget", "ModbusTcpTarget", "ModbusAddress",
    }
)  # fmt: skip


def refusal_problems(error: FieldError) -> list[str]:
    """Return a message for each fault in the shape of *error*, a refusal raised while
    ``error.obj`` was built."""
    obj = error.obj
    cls = type(obj)
    problems = []
    if not error.fields or error.field != error.fields[0]:
        problems.append(f"field {error.field!r} is not the first of fields {error.fields!r}")
    names = {f.name for f in dataclasses.fields(obj)} if dataclasses.is_dataclass(obj) else set()
    for field in error.fields:
        m = _FIELD.fullmatch(field)
        if m is None or m.group(1) != cls.__name__ or m.group(2) not in names:
            problems.append(f"{field!r} is no {cls.__name__}.<dataclass field>")
    if error.reason is not None and not isinstance(error.reason, Reason):
        problems.append(f"reason {error.reason!r} is not a Reason")
    if error.reason is None and cls.__name__ in REASONED:
        problems.append(f"{error.field!r} has no reason")
    if cls.__name__ in NAMED and parts_of(error) is None:
        problems.append(f"{error.field!r}: {str(error)!r} keeps no parts")
    problems += code_problems(error)
    return problems


def code_problems(error: FieldError) -> list[str]:
    """Return a list with one message if the code of *error* is not a ``Code``, or if its
    CLICK id is not one that ``CLICK_IDS`` lists for the code.  Otherwise return an empty list.

    A ``blank-field`` refusal keeps the CLICK id of the check that refused the blank, so its
    id is not checked.
    """
    if not isinstance(error.code, Code):
        return [f"{error.field!r}: code {error.code!r} is not a Code"]
    if error.click_id is None or error.code is Code.BLANK_FIELD:
        return []
    if error.click_id not in CLICK_IDS.get(error.code, ()):
        return [f"{error.field!r}: {error.code} does not list {error.click_id}"]
    return []


@pytest.fixture(autouse=True, scope="session")
def _refusals_name_their_fields() -> Iterator[None]:
    real = address._refused

    def checked(inst: object, exc: FieldError, before: dict[str, Any] | None) -> None:
        real(inst, exc, before)
        assert exc.errors[0] is exc, "the error raised is not the first of its errors"
        problems = [p for error in exc.errors for p in refusal_problems(error)]
        assert not problems, f"{type(inst).__name__}: " + "; ".join(problems)

    address._refused = checked
    yield
    address._refused = real
