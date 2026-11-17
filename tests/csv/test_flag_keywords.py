"""A flag keyword is ``1`` or ``0``: another text is refused, never read as off."""

from __future__ import annotations

from typing import Any

import pytest

from laddercodec import FieldError, Reason
from laddercodec.csv.converter import af_node_to_token
from laddercodec.csv.token_parser import parse_af_token
from tests.csv.test_blank_args import RECEIVE, SEND


def _read(token: str) -> Any:
    return af_node_to_token(parse_af_token(token))


_FLAGS = [
    ("math(DS1 + 1,DS2,mode=decimal,oneshot={v})", "Math.oneshot"),
    ("search(DS1..DS10 == 1,result=DS20,found=C1,continuous={v})", "Search.continuous"),
    ("search(DS1..DS10 == 1,result=DS20,found=C1,oneshot={v})", "Search.oneshot"),
    ("for(3,oneshot={v})", "ForLoop.oneshot"),
    (
        "timed(C1,on_acc=TD1,on_preset=3,unit=Ts,maintained={v})",
        "OutVariant.maintained",
    ),
    (SEND[:-1] + ",word_swap={v})", "Send.word_swap"),
    (RECEIVE[:-1] + ",word_swap={v})", "Receive.word_swap"),
]


@pytest.mark.parametrize(("token", "field"), _FLAGS)
def test_a_flag_text_that_is_not_1_or_0_is_refused(token: str, field: str) -> None:
    with pytest.raises(FieldError) as raised:
        _read(token.format(v="yes"))
    assert (raised.value.field, raised.value.reason) == (field, Reason.FLAG)
    assert str(raised.value).startswith(f"{field}: 'yes' is not 1 or 0")


@pytest.mark.parametrize(("token", "field"), _FLAGS)
def test_a_blank_flag_is_missing(token: str, field: str) -> None:
    with pytest.raises(FieldError) as raised:
        _read(token.format(v=""))
    assert (raised.value.field, raised.value.reason) == (field, Reason.MISSING)


@pytest.mark.parametrize(("token", "field"), _FLAGS)
def test_a_flag_of_1_or_0_is_read(token: str, field: str) -> None:
    attr = field.split(".")[1]
    assert getattr(_read(token.format(v="1")), attr) is True
    assert getattr(_read(token.format(v="0")), attr) is False
