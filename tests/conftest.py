"""Every refusal raised while an instruction is built names a field of that instruction.

The fixture below wraps the step that completes a construction's refusals, so every test that
builds a refused instruction checks the error's shape too: each refusal's ``field`` (and each
of its ``fields``) is ``Class.attr`` or ``Class.attr[i]``, where ``Class`` is the class name
of the instance being built and ``attr`` one of its dataclass fields, and its ``reason`` is a
:class:`~laddercodec.Reason` or None.  A refusal that breaks this fails the test that built
it with an ``AssertionError``.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterator
from typing import Any

import pytest

from laddercodec.operands import address
from laddercodec.operands.errors import FieldError, Reason

_FIELD = re.compile(r"(\w+)\.(\w+)(?:\[\d+\])?")


def refusal_problems(error: FieldError) -> list[str]:
    """What is wrong with the shape of one refusal raised while ``error.obj`` was built."""
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
    return problems


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
