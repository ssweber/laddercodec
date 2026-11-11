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
from laddercodec.operands.sources import Src, SrcKind, dll_address
from tests.test_operand_guards import INSTRUCTIONS, _bank_items

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


def _literal_banks(module: str, field: str) -> frozenset[str]:
    """The literal ``banks=`` of the ``check_address(..., field, banks=...)`` call in ``module``."""
    tree = ast.parse((INSTRUCTIONS / module).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "check_address"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == field
        ):
            (banks_arg,) = [k.value for k in node.keywords if k.arg == "banks"]
            return frozenset(ast.literal_eval(banks_arg))
    raise AssertionError(f"no check_address for {field} in {module}")


_MASKS.append(
    (0x40, _literal_banks("timer.py", "Timer.setpoint"), "DLL: Inst_Timer.dll, set point")
)


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
    """A hand-typed bank set or bank-keyed dict in instructions/ holds no misspelled bank.

    Tuples and lists are left out: ``("T", "|")`` is a pair of wire tokens.
    """
    checked = 0
    for path in sorted(INSTRUCTIONS.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.Tuple, ast.List)):
                continue
            items = _bank_items(node)
            if items is None or not set(items) & set(Bank.__members__):
                continue
            assert set(items) <= set(Bank.__members__), (path.name, ast.unparse(node))
            checked += 1
    assert checked >= 70


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


#: A made-up address in a CLICK DLL's range and the image base, built here so this file
#: writes out no address.
_FAKE = f"{(0x1000 << 16) + 0x1234:08x}"
_BASE = f"{0x1000 << 16:x}"


@pytest.mark.parametrize(
    "ref",
    [
        f"Inst_SD.dll 0x{_FAKE}",
        f"Inst_SD.dll 0X{_FAKE.upper()}",
        f"baseEx.dll @{_FAKE}",
        f"Inst_SD.dll sub_{_FAKE}",
        f"FUN_{_FAKE}",
        f"LAB_{_FAKE}",
        f"Inst_SD.dll {_FAKE}",
        f"Inst_SD.dll {_FAKE}h",
        f"Inst_SD.dll 0x{_FAKE[:4]}_{_FAKE[4:]}",
        "Inst_SD.dll+0x1234",
        "Inst_SD.dll + 1234",
    ],
)
def test_src_refuses_a_dll_address(ref: str) -> None:
    with pytest.raises(ValueError, match="DLL address"):
        Src(SrcKind.DLL, ref)


@pytest.mark.parametrize(
    "ref",
    [
        "Inst_SD.dll, Send local banks",
        "CL195",
        "OBJ-004",
        "mask 0x3f",
        f"mask 0x{_BASE}",
        f"capture 0x{(0x1A2B << 16) + 0x3C4D:08X}.bin",
        f"value {_FAKE}0",
    ],
)
def test_src_takes_a_reference_without_an_address(ref: str) -> None:
    assert dll_address(ref) is None
    assert Src(SrcKind.DLL, ref).ref == ref


def test_src_refuses_blank_reference() -> None:
    with pytest.raises(ValueError, match="names its reference"):
        Src(SrcKind.HELP, " ")


def test_src_refuses_a_reference_that_is_not_text() -> None:
    with pytest.raises(TypeError, match="not text"):
        Src(SrcKind.HELP, None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="not a SrcKind"):
        Src("Help", "CL195")  # type: ignore[arg-type]
