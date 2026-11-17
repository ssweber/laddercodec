"""Check the refusals that a decoded instruction keeps.

A refusal is the ``FieldError`` that building an instruction raises for a value that CLICK's
dialog rejects. A decoder builds the instruction anyway, and the instruction keeps the error.
"""

from __future__ import annotations

from typing import TypeVar

from laddercodec.operands.unchecked import refusals

_T = TypeVar("_T")


def kept(instruction: _T | None, *fields: str) -> _T:
    """Assert that a decoder built *instruction* and that it keeps one refusal for each name
    in *fields*, in the order that construction raises them. Return *instruction*.

    Only the field names are compared. A refusal's ``obj`` is the instruction, except for a
    refusal on the Modbus target or remote address of a Send or Receive. That refusal's
    ``obj`` is the target or the address.
    """
    assert instruction is not None, "the blob was left unparsed"
    found = refusals(instruction)
    assert [error.field for error in found] == list(fields), found
    return instruction
