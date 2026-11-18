"""Test the ``Literal`` aliases that name the values of an instruction field.

A caller reads the values of a field from its alias, such as
``typing.get_args(laddercodec.ContactKind)``. These tests check four things:

- Each alias has the members listed in ``EXPECTED_MEMBERS``.
- Each alias has the members that the field's check accepts, and the tables that the
  encoder uses have an entry for each member.
- Each field in ``FIELD_VALUE_ALIASES`` is annotated with its alias.
- Every ``Literal`` in an instruction field's annotation, at any depth, is an exported
  alias, apart from ``Literal[""]``.
"""

from __future__ import annotations

import dataclasses
import types
import typing
from collections.abc import Collection
from typing import Any, Literal

import pytest

import laddercodec
import laddercodec.instructions
from laddercodec import BlockCopy, Code, FieldError
from laddercodec.instructions import coil as coil_mod
from laddercodec.instructions import comparison as comparison_mod
from laddercodec.instructions import contact as contact_mod
from laddercodec.instructions import copy as copy_mod
from laddercodec.instructions import counter as counter_mod
from laddercodec.instructions import drum as drum_mod
from laddercodec.instructions import math as math_mod
from laddercodec.instructions import out_variant as out_variant_mod
from laddercodec.instructions import search as search_mod
from laddercodec.instructions import send_receive as send_receive_mod
from laddercodec.instructions import timer as timer_mod
from laddercodec.instructions import undecoded as undecoded_mod
from tests.test_flag_fields import instruction_classes

#: Each alias, with the fields that it annotates.
FIELD_VALUE_ALIASES: dict[str, tuple[str, ...]] = {
    "BlockCopyConvert": ("BlockCopy.convert",),
    "CoilKind": ("Coil.kind",),
    "CompareOp": ("CompareContact.op", "Search.op"),
    "ContactKind": ("Contact.kind",),
    "CopyConvert": ("Copy.convert",),
    "CounterKind": ("Counter.kind",),
    "DrumKind": ("Drum.kind",),
    "MathMode": ("Math.mode",),
    "ModbusRegisterType": ("ModbusAddress.register_type",),
    "ModbusRtuPort": ("ModbusRtuTarget.com_port",),
    "ModbusTcpPort": ("ModbusTcpTarget.com_port",),
    "OutVariantKind": ("OutVariant.kind",),
    "OutVariantUnit": ("OutVariant.unit",),
    "PackKind": ("Pack.kind",),
    "ReceiveFunctionCode": ("Receive.function_code",),
    "SendFunctionCode": ("Send.function_code",),
    "TimeUnit": ("Timer.unit", "Drum.unit"),
    "TimerKind": ("Timer.kind",),
    "UndecodedStop": ("Undecoded.stop",),
    "UnpackKind": ("Unpack.kind",),
}

#: The members of each alias, in order, written out by hand. Several check constants are
#: built from their alias, so only this table catches a member added to or dropped from it.
EXPECTED_MEMBERS: dict[str, tuple[Any, ...]] = {
    "BlockCopyConvert": ("to_value", "to_ascii"),
    "CoilKind": ("out", "latch", "reset"),
    "CompareOp": ("==", "!=", ">", "<", ">=", "<="),
    "ContactKind": ("no", "nc", "rise", "fall"),
    "CopyConvert": ("to_value", "to_text", "to_binary", "to_ascii"),
    "CounterKind": ("count_up", "count_down"),
    "DrumKind": ("event_drum", "time_drum", "time_event_drum"),
    "MathMode": ("decimal", "hex"),
    "ModbusRegisterType": ("coil", "discrete_input", "holding", "input"),
    "ModbusRtuPort": ("cpu2", "cpu3", "slot0_1", "slot0_2", "slot1_1", "slot1_2"),
    "ModbusTcpPort": ("ethernet", "wlan"),
    "OutVariantKind": ("toggle", "debounce", "flasher", "timed"),
    "OutVariantUnit": ("Tms", "Ts", "Tm"),
    "PackKind": ("pack_bits", "pack_words", "pack_text"),
    "ReceiveFunctionCode": (1, 2, 3, 4),
    "SendFunctionCode": (5, 6, 15, 16),
    "TimeUnit": ("Tms", "Ts", "Tm", "Th", "Td"),
    "TimerKind": ("on_delay", "off_delay"),
    "UndecodedStop": ("end", "return"),
    "UnpackKind": ("unpack_to_bits", "unpack_to_words"),
}

#: Each alias, with the collection of values that a field's check accepts. A collection
#: that also holds None is for a field that accepts None, and the test leaves None out.
CHECKED_SETS: list[tuple[str, Collection[Any]]] = [
    ("ContactKind", contact_mod._KIND_TO_ITYPE),
    ("CoilKind", coil_mod._KIND_TO_ITYPE),
    ("CompareOp", comparison_mod.COMPARE_OP_TO_FUNC),
    ("CompareOp", search_mod._OP_TO_FUNC),
    ("OutVariantKind", out_variant_mod._KIND_INDEX),
    ("OutVariantUnit", {unit for _, unit, _ in out_variant_mod.OUT_VARIANT_FUNC_CODES if unit}),
    ("TimerKind", timer_mod._TIMER_KINDS),
    ("TimeUnit", timer_mod.TIMER_UNIT_TO_INDEX),
    ("TimeUnit", drum_mod._DRUM_UNIT_TO_INDEX),
    ("CounterKind", counter_mod._COUNTER_KINDS),
    ("DrumKind", drum_mod._DRUM_KINDS),
    ("MathMode", math_mod.RESULT_BANKS),
    ("CopyConvert", copy_mod._VALID_CONVERTS),
    ("BlockCopyConvert", copy_mod._BLOCKCOPY_CONVERTS),
    ("PackKind", copy_mod._PACK_KINDS),
    ("UnpackKind", copy_mod._UNPACK_KINDS),
    ("ModbusRtuPort", send_receive_mod._RTU_PORT_MODE),
    ("ModbusTcpPort", send_receive_mod._TCP_PORT_MODE),
    ("ModbusRegisterType", send_receive_mod.REGISTER_TYPES),
    ("ReceiveFunctionCode", send_receive_mod._RD_FC_SUBTYPE),
    ("SendFunctionCode", send_receive_mod._SD_FC_SUBTYPE),
    ("UndecodedStop", undecoded_mod._STOPS),
]

_COPY_CSV_NAMES = copy_mod.SPEC.csv_names

#: Each alias, with a table that the encoder or the CSV reader keys by the alias's members.
ENCODER_TABLES: list[tuple[str, Collection[Any]]] = [
    ("CoilKind", coil_mod.SPEC.csv_names),
    ("CompareOp", comparison_mod.COMPARE_OP_TO_TYPE_IDX),
    ("CompareOp", search_mod._OP_TO_CMP_CODE),
    ("OutVariantKind", out_variant_mod.SPEC.csv_names),
    ("TimerKind", timer_mod.SPEC.csv_names),
    ("TimeUnit", timer_mod.TIMER_UNITS.values()),
    ("TimeUnit", drum_mod._TIME_FC_BASE),
    ("TimeUnit", drum_mod._TIME_EVENT_FC_BASE),
    ("CounterKind", counter_mod.SPEC.csv_names),
    ("DrumKind", drum_mod.SPEC.csv_names),
    ("MathMode", {mode for mode, _ in math_mod.MATH_FUNC_CODES}),
    ("CopyConvert", {opts[0] for opts in copy_mod._CONVTYPE_TO_OPTS.values()}),
    ("PackKind", [name for name in _COPY_CSV_NAMES if name.startswith("pack_")]),
    ("UnpackKind", [name for name in _COPY_CSV_NAMES if name.startswith("unpack_")]),
    ("ModbusRegisterType", send_receive_mod._RD_FC_REGISTER_TYPE.values()),
    ("ReceiveFunctionCode", send_receive_mod._RD_FC_REGISTER_TYPE),
]


def _alias(name: str) -> Any:
    return getattr(laddercodec, name)


def _members(name: str) -> set[Any]:
    return set(typing.get_args(_alias(name)))


@pytest.mark.parametrize(("name", "accepted"), CHECKED_SETS, ids=[n for n, _ in CHECKED_SETS])
def test_alias_members_are_the_values_that_the_check_accepts(
    name: str, accepted: Collection[Any]
) -> None:
    assert _members(name) == set(accepted) - {None}


@pytest.mark.parametrize(("name", "table"), ENCODER_TABLES, ids=[n for n, _ in ENCODER_TABLES])
def test_encoder_table_has_an_entry_for_each_alias_member(
    name: str, table: Collection[Any]
) -> None:
    assert _members(name) == set(table) - {None}


def test_block_copy_converts_are_copy_converts() -> None:
    assert _members("BlockCopyConvert") < _members("CopyConvert")


def test_out_variant_units_are_time_units() -> None:
    assert _members("OutVariantUnit") < _members("TimeUnit")


def test_every_alias_is_one_object_in_both_namespaces() -> None:
    for name in FIELD_VALUE_ALIASES:
        assert name in laddercodec.instructions.__all__, name
        alias = getattr(laddercodec, name)
        assert alias is getattr(laddercodec.instructions, name), name
        assert typing.get_origin(alias) is Literal, name


def test_contact_kinds_example() -> None:
    assert typing.get_args(laddercodec.ContactKind) == ("no", "nc", "rise", "fall")


def test_expected_members_names_every_alias() -> None:
    assert set(EXPECTED_MEMBERS) == set(FIELD_VALUE_ALIASES)


@pytest.mark.parametrize("name", sorted(EXPECTED_MEMBERS))
def test_alias_has_the_expected_members(name: str) -> None:
    assert typing.get_args(_alias(name)) == EXPECTED_MEMBERS[name]


@pytest.mark.parametrize("convert", ["to_text", "to_binary"])
def test_block_copy_refuses_a_single_copy_convert(convert: str) -> None:
    with pytest.raises(FieldError) as caught:
        BlockCopy("DS1", "DS4", "DS10", "DS13", convert=convert)  # ty: ignore[invalid-argument-type]
    assert [(e.field, e.code) for e in caught.value.errors] == [
        ("BlockCopy.convert", Code.INVALID_CHOICE)
    ]


def _union_members(hint: Any) -> tuple[Any, ...]:
    if typing.get_origin(hint) in (typing.Union, types.UnionType):
        return typing.get_args(hint)
    return (hint,)


_FIELDS = [(name, field) for name, fields in FIELD_VALUE_ALIASES.items() for field in fields]


@pytest.mark.parametrize(("name", "field"), _FIELDS, ids=[f for _, f in _FIELDS])
def test_field_is_annotated_with_its_alias(name: str, field: str) -> None:
    class_name, field_name = field.split(".")
    hint = typing.get_type_hints(getattr(laddercodec, class_name))[field_name]
    members = _union_members(hint)
    assert _alias(name) in members
    # The rest of the annotation may only add None or a blank.
    for other in members:
        assert other is _alias(name) or other is type(None) or other == Literal[""], other


def _classes_with_fields() -> list[type]:
    helpers = [
        send_receive_mod.ModbusAddress,
        send_receive_mod.ModbusRtuTarget,
        send_receive_mod.ModbusTcpTarget,
    ]
    return instruction_classes() + helpers


def _literals(hint: Any) -> list[Any]:
    """Return each ``Literal`` in *hint*, at any depth, apart from ``Literal[""]``."""
    if typing.get_origin(hint) is Literal:
        return [] if hint == Literal[""] else [hint]
    return [found for arg in typing.get_args(hint) for found in _literals(arg)]


def test_every_literal_field_uses_an_exported_alias() -> None:
    aliases = [_alias(name) for name in FIELD_VALUE_ALIASES]
    found: list[tuple[str, Any]] = []
    for cls in _classes_with_fields():
        hints = typing.get_type_hints(cls)
        for field in dataclasses.fields(cls):
            found += [(f"{cls.__name__}.{field.name}", lit) for lit in _literals(hints[field.name])]
    unnamed = [(field, hint) for field, hint in found if not any(hint is a for a in aliases)]
    assert not unnamed
    assert {field for field, _ in found} == {
        field for fields in FIELD_VALUE_ALIASES.values() for field in fields
    }
