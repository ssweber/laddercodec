"""Check an instruction a decoder built from stored values that its checks refuse."""

from __future__ import annotations

from typing import TypeVar

from laddercodec.operands.unchecked import refusals

_T = TypeVar("_T")


def kept(instruction: _T | None, *fields: str) -> _T:
    """Assert that *instruction* was built and keeps one refusal per name in *fields*, in
    the order construction raises them; return it.

    Each refusal names the instruction as its ``obj``, except one on a Send's or Receive's
    Modbus target or remote address, which names that object.
    """
    assert instruction is not None, "the blob was left unparsed"
    found = refusals(instruction)
    assert [error.field for error in found] == list(fields), found
    return instruction
