"""Tests for laddercodec.operands: bank flags, field errors and rule sources."""

from __future__ import annotations

import ast
import pickle

import pytest

from laddercodec import Coil, Contact, model
from laddercodec.instructions import copy, counter, drum, forloop, search, send_receive, shift
from laddercodec.model import InstructionType
from laddercodec.operands import address, errors
from laddercodec.operands.banks import ALL, BITS, REGISTERS, Bank, banks, mask
from laddercodec.operands.sources import Src, SrcKind
from tests.test_operand_guards import INSTRUCTIONS, _bank_items, scan

# ---------------------------------------------------------------------------
# Bank
# ---------------------------------------------------------------------------


def test_bank_order_is_address_bank_order() -> None:
    assert list(Bank.__members__) == list(address.ADDRESS_BANKS)
    assert [bank.value for bank in Bank] == [1 << n for n in range(16)]


# (mask the dialog checks, the set the code holds, where the mask is read).
_MASKS = [
    (0x3F, send_receive._SEND_LOCAL_BITS, "DLL: Inst_SD.dll, Send local bits FC01-FC05"),
    (0xDD40, send_receive._SEND_LOCAL_REGS_FC06, "DLL: Inst_SD.dll, Send local registers FC06"),
    (0xF3C0, send_receive._SEND_LOCAL_REGS_FC16, "DLL: Inst_SD.dll, Send local registers FC16"),
    (0x6, send_receive._RECEIVE_LOCAL_BITS, "DLL: Inst_RD.dll, Receive local bits FC01/02"),
    (0x8BC0, send_receive._RECEIVE_LOCAL_REGS, "DLL: Inst_RD.dll, Receive local registers"),
    (0xC0, counter.COUNTER_PRESET_BANKS, "DLL: Inst_Counter.dll, set point"),
    (0x3F, drum.DRUM_EVENT_BANKS, "DLL: Inst_Drum.dll, event"),
    (0x70C0, forloop.FOR_LIMIT_BANKS, "DLL: Inst_For.dll, count"),
    (0x4, search.FOUND_BANKS, "DLL: Inst_Search.dll, Result Flag"),
    (0x4, shift.SHIFT_BANKS, "DLL: Inst_ShiftRegister.dll, start and end bits"),
]


@pytest.mark.parametrize(("value", "expected", "source"), _MASKS, ids=[m[2] for m in _MASKS])
def test_dialog_masks_decode_to_the_code_sets(
    value: int, expected: frozenset[str], source: str
) -> None:
    assert banks(value) == expected
    assert mask(*expected) == value


def test_groups_are_the_copy_sets() -> None:
    assert banks(BITS) == copy.BIT_BANKS
    assert banks(REGISTERS) == copy.REGISTER_BANKS
    assert banks(ALL) == set(address.ADDRESS_BANKS)


def test_every_bank_set_names_only_banks() -> None:
    """A hand-typed bank set in instructions/ holds no misspelled bank."""
    checked = 0
    for path in sorted(INSTRUCTIONS.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            items = _bank_items(node)
            if items is None or not set(items) & set(Bank.__members__):
                continue
            assert set(items) <= set(Bank.__members__), (path.name, ast.unparse(node))
            checked += 1
    assert checked >= sum(scan()["BANK_SET"].values())


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
    assert (exc.field, exc.obj, exc.source) == (None, None, None)


@pytest.mark.parametrize(
    ("message", "field"),
    [
        ("Coil.range_end: 'C5' is not above 'C9'; a range runs up", "Coil.range_end"),
        ("Drum.outputs[2]: 'Y001' is already output 0", "Drum.outputs[2]"),
        ("Call.subroutine cannot be empty: CLICK requires a subroutine name", "Call.subroutine"),
        ("CompareContact: 'DS1' (numeric) and 'DH1' (hex) do not mix", None),
        ("Drum steps: 0 is outside 1-16", None),
        ("to_binary: 'x' is not an option", None),
    ],
)
def test_field_from_message(message: str, field: str | None) -> None:
    assert errors.FieldError(message).field == field


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
    assert info.value.field is None


def test_pickle_keeps_message_and_attributes() -> None:
    source = Src(SrcKind.HELP, "CL195")
    exc = errors.AddressError("Coil.operand: 'C0' is outside C1-C2000", source=source)
    copy_ = pickle.loads(pickle.dumps(exc))
    assert type(copy_) is errors.AddressError
    assert str(copy_) == str(exc)
    assert (copy_.field, copy_.obj, copy_.source) == ("Coil.operand", None, source)


def test_pickle_keeps_explicit_field() -> None:
    exc = errors.FieldError("refused", field="Send source")
    assert pickle.loads(pickle.dumps(exc)).field == "Send source"


# ---------------------------------------------------------------------------
# Src
# ---------------------------------------------------------------------------


def test_src_text() -> None:
    assert str(Src(SrcKind.DLL, "Inst_SD.dll, Send local banks")) == (
        "DLL: Inst_SD.dll, Send local banks"
    )
    assert [kind.name for kind in SrcKind] == [
        "DLL",
        "HELP",
        "DIALOG",
        "CAPTURE",
        "RULING",
        "CODEC",
    ]


#: A made-up address in a CLICK DLL's range, built here so no address is written out.
_FAKE_ADDRESS = f"{0x1000_0000 + 0x1234:08x}"


@pytest.mark.parametrize("ref", [f"Inst_SD.dll 0x{_FAKE_ADDRESS}", f"baseEx.dll @{_FAKE_ADDRESS}"])
def test_src_refuses_a_dll_address(ref: str) -> None:
    with pytest.raises(ValueError, match="DLL address"):
        Src(SrcKind.DLL, ref)


def test_src_refuses_blank_reference() -> None:
    with pytest.raises(ValueError, match="names its reference"):
        Src(SrcKind.HELP, " ")
