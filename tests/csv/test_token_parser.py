"""Tests for clicknick.csv.token_parser."""

from __future__ import annotations

import pytest

from laddercodec.csv.ast import (
    AfCall,
    ComparisonCondition,
    ContactCondition,
    EdgeCondition,
    GenericCondition,
    VerticalPassThroughWire,
)
from laddercodec.csv.token_parser import parse_af_token, parse_condition_token


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ('call("normal")', "normal"),
        ('call("has""quote")', 'has"quote'),
        ('call("two""mid""quotes")', 'two"mid"quotes'),
        ('call("")', ""),
        ('call("no special chars")', "no special chars"),
    ],
)
def test_parse_af_token_decodes_quoted_string_args(token: str, expected: str) -> None:
    af = parse_af_token(token)
    assert isinstance(af, AfCall)
    assert af.name == "call"
    assert af.args == (expected,)


def test_parse_af_token_keeps_non_string_args() -> None:
    af = parse_af_token("future_call(1,[2,3])")
    assert isinstance(af, AfCall)
    assert af.args == ("1", "[2,3]")


def test_parse_af_token_handles_quoted_commas() -> None:
    af = parse_af_token('send(X001,"a,b",100)')
    assert isinstance(af, AfCall)
    assert af.args == ("X001", "a,b", "100")


def test_parse_af_token_treats_backslash_as_literal_character() -> None:
    af = parse_af_token('call("host\\name")')
    assert isinstance(af, AfCall)
    assert af.args == ("host\\name",)


@pytest.mark.parametrize(
    "token",
    [
        'call("unterminated)',
        'call("has\\"quote")',
    ],
)
def test_parse_af_token_rejects_malformed_quoted_strings(token: str) -> None:
    with pytest.raises(ValueError, match="Malformed AF"):
        parse_af_token(token)


def test_parse_condition_token_accepts_pipe_for_vertical_mid() -> None:
    condition = parse_condition_token("|")
    assert isinstance(condition, VerticalPassThroughWire)


def test_parse_condition_token_plus_falls_back_to_generic() -> None:
    condition = parse_condition_token("+")
    assert isinstance(condition, GenericCondition)
    assert condition.raw == "+"


# --- Wire-down prefix ---


def test_parse_condition_token_wire_down_contact() -> None:
    c = parse_condition_token("T:X001")
    assert isinstance(c, ContactCondition)
    assert c.operand == "X001"
    assert c.negated is False
    assert c.wire_down is True


def test_parse_condition_token_wire_down_nc() -> None:
    c = parse_condition_token("T:~X003")
    assert isinstance(c, ContactCondition)
    assert c.operand == "X003"
    assert c.negated is True
    assert c.wire_down is True


def test_parse_condition_token_pipe_wire_down() -> None:
    c = parse_condition_token("|:X001")
    assert isinstance(c, ContactCondition)
    assert c.operand == "X001"
    assert c.wire_down is True


def test_parse_condition_token_wire_down_edge() -> None:
    c = parse_condition_token("T:rise(X002)")
    assert isinstance(c, EdgeCondition)
    assert c.kind == "rise"
    assert c.operand == "X002"
    assert c.wire_down is True


def test_parse_condition_token_wire_down_compare() -> None:
    c = parse_condition_token("T:DS1==1")
    assert isinstance(c, ComparisonCondition)
    assert c.left == "DS1"
    assert c.op == "=="
    assert c.right == "1"
    assert c.wire_down is True


# --- Immediate syntax variants ---


def test_parse_condition_token_immediate_wrapper() -> None:
    c = parse_condition_token("immediate(X001)")
    assert isinstance(c, ContactCondition)
    assert c.operand == "X001"
    assert c.immediate is True


def test_parse_condition_token_immediate_suffix() -> None:
    c = parse_condition_token("X001.immediate")
    assert isinstance(c, ContactCondition)
    assert c.operand == "X001"
    assert c.immediate is True


def test_parse_condition_token_nc_immediate_wrapper() -> None:
    c = parse_condition_token("~immediate(X003)")
    assert isinstance(c, ContactCondition)
    assert c.operand == "X003"
    assert c.negated is True
    assert c.immediate is True


def test_parse_condition_token_nc_immediate_suffix() -> None:
    c = parse_condition_token("~X003.immediate")
    assert isinstance(c, ContactCondition)
    assert c.operand == "X003"
    assert c.negated is True
    assert c.immediate is True
