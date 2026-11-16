"""Tests for laddercodec.operands: bank flags, field errors."""

from __future__ import annotations

import ast
import pickle

import pytest

from laddercodec import Coil, Contact, model
from laddercodec.instructions import copy, counter, forloop, search, send_receive, shift
from laddercodec.model import InstructionType
from laddercodec.operands import address, errors
from laddercodec.operands.banks import ALL, BITS, REGISTERS, Bank, banks, mask
from laddercodec.operands.checks import BIT_BANKS
from tests.test_operand_guards import (
    BANK_NAMES_ALLOWED,
    INSTRUCTIONS,
    _bank_items,
    _is_bank_literal,
)

# ---------------------------------------------------------------------------
# Bank
# ---------------------------------------------------------------------------


def test_bank_order_is_address_bank_order() -> None:
    assert list(Bank.__members__) == list(address.ADDRESS_BANKS)
    assert [bank.value for bank in Bank] == [1 << n for n in range(16)]


# (mask the dialog checks, the set the code holds, the field).
_MASKS = [
    (0x3F, send_receive.BIT_BANKS, "Send local bits FC01-FC05"),
    (0xDD40, send_receive._SEND_LOCAL_REGS_FC06, "Send local registers FC06"),
    (0xF3C0, send_receive._SEND_LOCAL_REGS_FC16, "Send local registers FC16"),
    (0x6, send_receive._RECEIVE_LOCAL_BITS, "Receive local bits FC01/02"),
    (0x8BC0, send_receive._RECEIVE_LOCAL_REGS, "Receive local registers"),
    (0xC0, counter.COUNTER_PRESET_BANKS, "Counter set point"),
    (0x3F, BIT_BANKS, "Drum event"),
    (0x70C0, forloop.FOR_LIMIT_BANKS, "For count"),
    (0x4, search.FOUND_BANKS, "Search Result Flag"),
    (0x4, shift.SHIFT_BANKS, "Shift start and end bits"),
]


def _literal_banks(module: str, field: str) -> frozenset[str]:
    """The literal banks of the ``check_address(..., field, banks=...)`` or
    ``check_operand(value, field, banks, ...)`` call in ``module``, or of the same check run
    through ``Refusals``: ``check(attr, check_operand, banks, ...)``."""
    tree = ast.parse((INSTRUCTIONS / module).read_text(encoding="utf-8"))
    attr = field.split(".", 1)[1]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        first, second = node.args[0], node.args[1]
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in ("check_address", "check_operand")
            and isinstance(second, ast.Constant)
            and second.value == field
        ):
            name, rest = node.func.id, node.args[2:]
        elif (
            isinstance(first, ast.Constant)
            and first.value == attr
            and isinstance(second, ast.Name)
            and second.id in ("check_address", "check_operand")
        ):
            name, rest = second.id, node.args[2:]
        else:
            continue
        if name == "check_operand":
            banks_arg = rest[0]
        else:
            (banks_arg,) = [k.value for k in node.keywords if k.arg == "banks"]
        return frozenset(ast.literal_eval(banks_arg))
    raise AssertionError(f"no check_address for {field} in {module}")


_MASKS.append((0x40, _literal_banks("timer.py", "Timer.setpoint"), "Timer set point"))


@pytest.mark.parametrize(("value", "expected", "field"), _MASKS, ids=[m[2] for m in _MASKS])
def test_dialog_masks_decode_to_the_code_sets(
    value: int, expected: frozenset[str], field: str
) -> None:
    assert banks(value) == expected
    assert mask(*expected) == value


def test_groups_are_the_copy_sets() -> None:
    assert banks(BITS) == copy.BIT_BANKS
    assert banks(REGISTERS) == copy.REGISTER_BANKS
    assert banks(ALL) == set(address.ADDRESS_BANKS)


def test_every_bank_set_names_only_banks() -> None:
    """A hand-typed bank set or bank-keyed dict in instructions/ holds no misspelled bank.

    Tuples and lists are left out: ``("T", "|")`` is a pair of wire tokens.
    """
    checked = 0
    for path in sorted(INSTRUCTIONS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Tuple, ast.List)):
                continue
            if not _is_bank_literal(node, parents.get(node)):
                continue
            items = _bank_items(node)
            assert items is not None, ast.unparse(node)
            assert set(items) <= set(Bank.__members__), (path.name, ast.unparse(node))
            checked += 1
    # Each set and dict the ratchet lists, counted once (``frozenset({...})`` is one).
    listed = sum(n for (_, key), n in BANK_NAMES_ALLOWED.items() if not key.startswith(("(", "[")))
    assert checked == listed


def test_banks_refuses_bits_above_txt() -> None:
    with pytest.raises(ValueError, match="above TXT"):
        banks(0x10000)


def test_mask_refuses_unknown_bank() -> None:
    with pytest.raises(KeyError):
        mask("DQ")


# ---------------------------------------------------------------------------
# FieldError attributes
# ---------------------------------------------------------------------------


def test_model_reexports_the_operands_objects() -> None:
    assert model.FieldError is errors.FieldError
    assert model.AddressError is errors.AddressError
    assert model.ADDRESS_BANKS is address.ADDRESS_BANKS
    for name in (
        "OPERAND_RE",
        "XY_SLOTS",
        "Address",
        "check_address",
        "display_form_only",
        "normalize_address",
        "to_display",
        "xy_slot",
    ):
        assert getattr(model, name) is getattr(address, name), name


def test_errors_are_value_errors() -> None:
    assert issubclass(errors.AddressError, errors.FieldError)
    assert issubclass(errors.FieldError, ValueError)


def test_attributes_default_to_none() -> None:
    exc = errors.FieldError("'x' is not CLICK's display form 'X'")
    assert (exc.field, exc.obj) == (None, None)


@pytest.mark.parametrize(
    "message",
    [
        "Coil.range_end: 'C5' is not above 'C9'; a range runs up",
        "Drum.outputs[2]: 'Y001' is already output 0",
        "Call.subroutine cannot be empty: CLICK requires a subroutine name",
        "to_binary: 'x' is not an option",
    ],
)
def test_field_is_not_read_from_the_message(message: str) -> None:
    assert errors.FieldError(message).field is None
    assert errors.FieldError(message, field="Coil.operand").field == "Coil.operand"


def test_check_address_names_the_field() -> None:
    with pytest.raises(errors.AddressError) as info:
        address.check_address("C2001", "Send source (FC05)")
    assert info.value.field == "Send source (FC05)"
    assert str(info.value) == "Send source (FC05): 'C2001' is outside C1-C2000"


def test_constructor_refusal_names_field_and_instance() -> None:
    with pytest.raises(errors.AddressError) as info:
        Coil(InstructionType.COIL_OUT, "x0")
    exc = info.value
    assert str(exc) == "Coil.operand: 'x0' (X000) is not allowed; Coil.operand takes Y, C, SC"
    assert exc.field == "Coil.operand"
    assert isinstance(exc.obj, Coil)


def test_display_form_refusal_names_instance() -> None:
    with address.display_form_only(), pytest.raises(errors.FieldError) as info:
        Contact(InstructionType.CONTACT_NO, "x1")
    assert isinstance(info.value.obj, Contact)
    assert info.value.field == "Contact.operand"
    assert info.value.reason == "form"


def test_pickle_keeps_message_and_attributes() -> None:
    exc = errors.AddressError("Coil.operand: 'C0' is outside C1-C2000", field="Coil.operand")
    copy_ = pickle.loads(pickle.dumps(exc))
    assert type(copy_) is errors.AddressError
    assert str(copy_) == str(exc)
    assert (copy_.field, copy_.obj) == ("Coil.operand", None)


def test_pickle_keeps_explicit_field() -> None:
    exc = errors.FieldError("refused", field="Send source")
    assert pickle.loads(pickle.dumps(exc)).field == "Send source"


def test_token_rows_refusal_names_a_field_only_for_a_raw_token() -> None:
    from laddercodec.instructions import Velocity
    from laddercodec.instructions.raw import RawInstruction

    with pytest.raises(errors.FieldError) as info:
        RawInstruction.from_csv_token("raw(Timer,0x0001,2,rows=abc)")
    assert info.value.field == "RawInstruction.visual_rows"
    with pytest.raises(errors.FieldError) as info:
        RawInstruction.from_csv_token("raw(Timer,0x0001,2,sub=0)")
    assert info.value.field == "RawInstruction.sub_rows"
    with pytest.raises(errors.FieldError) as info:
        Velocity.from_csv_token("raw(Velocity,0x2735,1,rows=abc)")
    assert info.value.field is None
