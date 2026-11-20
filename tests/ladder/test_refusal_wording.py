"""A refusal of a constant states the rule of the field that refused it.

One check of constants serves every field. It builds each message from that field's own
kinds of constant, signs and limits. Each test here fixes the whole message for one field
and one case.
"""

from __future__ import annotations

import pytest

from laddercodec import FieldError
from laddercodec.instructions.counter import Counter
from laddercodec.instructions.out_variant import OutVariant
from laddercodec.instructions.send_receive import ModbusAddress


def _counter(preset: str) -> Counter:
    return Counter("count_up", "CT1", "CTD1", preset)


def _debounce(preset: str) -> OutVariant:
    return OutVariant(
        kind="debounce",
        operand="C1",
        on_acc="TD1",
        on_preset=preset,
        off_acc="TD2",
        off_preset="DS1",
        unit="Tms",
    )


def test_counter_preset_refuses_a_plus_sign_in_words() -> None:
    with pytest.raises(FieldError) as caught:
        _counter("+1")
    assert str(caught.value) == (
        "Counter.preset: +1 is refused; a constant here takes no plus sign (OBJ-005)"
    )


@pytest.mark.parametrize("preset", ["1.5", "3.5E+38"])
def test_integer_preset_names_a_real_by_its_kind(preset: str) -> None:
    with pytest.raises(FieldError) as caught:
        _debounce(preset)
    assert str(caught.value) == (
        f"OutVariant.on_preset: {preset} is a real; OutVariant.on_preset takes a decimal integer"
    )


def test_integer_preset_names_a_long_hex_value_by_its_kind() -> None:
    with pytest.raises(FieldError) as caught:
        _counter("123456789h")
    assert str(caught.value) == (
        "Counter.preset: 123456789h is a hex value; Counter.preset takes a decimal integer"
    )


def test_modbus_hex_address_allows_padding() -> None:
    assert ModbusAddress("000000001h").address == "1h"


@pytest.mark.parametrize(
    ("address", "message"),
    [
        ("h", "'h' is refused; ModbusAddress.address takes a hex value: hex digits then h"),
        ("+1h", "+1h is refused; a hex constant has no sign"),
        (
            "100000000h",
            "100000000h is above FFFEh; a hex constant here is 0h to FFFEh",
        ),
    ],
)
def test_modbus_hex_address_states_its_own_rule(address: str, message: str) -> None:
    with pytest.raises(FieldError) as caught:
        ModbusAddress(address)
    assert str(caught.value) == f"ModbusAddress.address: {message}"
