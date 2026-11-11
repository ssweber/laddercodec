"""Tests for laddercodec.model.check_address and the construction checks that use it.

Bank ranges are CLICK v4.00 Help topic CL195 ("Memory Addresses").
"""

from __future__ import annotations

import pytest

from laddercodec import decode
from laddercodec.encode import encode_rung
from laddercodec.instructions import (
    Coil,
    Contact,
    Counter,
    ForLoop,
    RawInstruction,
    Shift,
    parse_af_blob,
    parse_condition_blob,
)
from laddercodec.instructions.out_variant import OutVariant
from laddercodec.instructions.raw import _decompose_blob
from laddercodec.model import ADDRESS_BANKS, Address, InstructionType, check_address

# (bank, lowest, highest) for every bank without module or slot numbering.
_LINEAR_BANKS = [
    ("C", 1, 2000),
    ("T", 1, 500),
    ("CT", 1, 250),
    ("SC", 1, 1000),
    ("DS", 1, 4500),
    ("DD", 1, 1000),
    ("DH", 1, 500),
    ("DF", 1, 500),
    ("TD", 1, 500),
    ("CTD", 1, 250),
    ("SD", 1, 1000),
    ("TXT", 1, 1000),
]


class TestCheckAddress:
    def test_banks_are_clicks(self) -> None:
        assert set(ADDRESS_BANKS) == {
            *("X", "Y", "C", "T", "CT", "SC"),
            *("DS", "DD", "DH", "DF", "XD", "YD", "TD", "CTD", "SD", "TXT"),
        }

    @pytest.mark.parametrize(("bank", "lo", "hi"), _LINEAR_BANKS)
    def test_linear_bank_edges(self, bank: str, lo: int, hi: int) -> None:
        assert check_address(f"{bank}{lo}", "f") == Address(bank, lo)
        assert check_address(f"{bank}{hi}", "f") == Address(bank, hi)
        with pytest.raises(ValueError, match=f"is outside {bank}{lo}-{bank}{hi}$"):
            check_address(f"{bank}{lo - 1}", "f")
        with pytest.raises(ValueError, match=f"is outside {bank}{lo}-{bank}{hi}$"):
            check_address(f"{bank}{hi + 1}", "f")

    @pytest.mark.parametrize("bank", ["X", "Y"])
    @pytest.mark.parametrize("text", ["001", "1", "016", "16", "101", "116", "801", "816"])
    def test_module_points_accepted(self, bank: str, text: str) -> None:
        assert check_address(f"{bank}{text}", "f") == Address(bank, int(text))

    @pytest.mark.parametrize("bank", ["X", "Y"])
    @pytest.mark.parametrize("text", ["000", "0", "017", "100", "117", "200", "817", "900", "901"])
    def test_module_points_refused(self, bank: str, text: str) -> None:
        with pytest.raises(ValueError, match=r"\(module 0-8, point 01-16\)$"):
            check_address(f"{bank}{text}", "f")

    @pytest.mark.parametrize("bank", ["XD", "YD"])
    def test_word_io_slots(self, bank: str) -> None:
        assert check_address(f"{bank}0", "f") == Address(bank, 0)
        assert check_address(f"{bank}0u", "f") == Address(bank, 0, upper=True)
        assert check_address(f"{bank}1", "f") == Address(bank, 1)
        assert check_address(f"{bank}8", "f") == Address(bank, 8)
        for bad in (f"{bank}9", f"{bank}1u", f"{bank}8u"):
            with pytest.raises(ValueError, match=f"is outside {bank}0, {bank}0u, {bank}1-{bank}8$"):
                check_address(bad, "f")

    def test_upper_suffix_only_on_word_io(self) -> None:
        with pytest.raises(ValueError, match=r"'DS1u' is outside DS1-DS4500"):
            check_address("DS1u", "f")

    def test_leading_zeros_accepted(self) -> None:
        assert check_address("DS0001", "f") == Address("DS", 1)
        assert check_address("C02000", "f") == Address("C", 2000)

    @pytest.mark.parametrize("value", ["Q1", "XY1", "Z99", "DT1"])
    def test_unknown_bank(self, value: str) -> None:
        with pytest.raises(ValueError, match=f"^f: '{value}' has no CLICK bank"):
            check_address(value, "f")

    @pytest.mark.parametrize(
        "value", ["", "X", "1", "x1", "ds1", " X1", "X1 ", "DS[DS1]", "C123456", "TXTA1", "C-1"]
    )
    def test_not_an_address(self, value: str) -> None:
        with pytest.raises(ValueError, match="is not a CLICK address$"):
            check_address(value, "f")

    def test_allowed_banks(self) -> None:
        assert check_address("C5", "f", banks={"Y", "C"}) == Address("C", 5)
        with pytest.raises(
            ValueError, match=r"^Coil\.operand: 'X1' is not allowed; Coil\.operand takes Y, C$"
        ):
            check_address("X1", "Coil.operand", banks={"C", "Y"})

    def test_allowed_bank_still_range_checked(self) -> None:
        with pytest.raises(ValueError, match="outside C1-C2000"):
            check_address("C2001", "f", banks={"C"})

    def test_messages(self) -> None:
        with pytest.raises(ValueError) as info:
            check_address("C9999", "Coil.operand")
        assert str(info.value) == "Coil.operand: 'C9999' is outside C1-C2000"
        with pytest.raises(ValueError) as info:
            check_address("X999", "Contact.operand")
        assert str(info.value) == (
            "Contact.operand: 'X999' is outside X001-X816 (module 0-8, point 01-16)"
        )
        with pytest.raises(ValueError) as info:
            check_address("Q1", "Contact.operand")
        assert str(info.value) == (
            "Contact.operand: 'Q1' has no CLICK bank 'Q'; banks are "
            "X, Y, C, T, CT, SC, DS, DD, DH, DF, XD, YD, TD, CTD, SD, TXT"
        )


class TestConstructionRaises:
    def test_contact(self) -> None:
        with pytest.raises(ValueError, match="^Contact.operand: 'X999'"):
            Contact(InstructionType.CONTACT_NO, "X999")
        with pytest.raises(ValueError, match="^Contact.operand: 'Q1'"):
            Contact(InstructionType.CONTACT_EDGE, "Q1", edge_kind="rise")

    def test_coil(self) -> None:
        with pytest.raises(ValueError, match="^Coil.operand: 'C9999'"):
            Coil(InstructionType.COIL_OUT, "C9999")
        with pytest.raises(ValueError, match="^Coil.range_end: 'C2001'"):
            Coil(InstructionType.COIL_OUT, "C1", range_end="C2001")

    def test_counter(self) -> None:
        with pytest.raises(ValueError, match="^Counter.done_bit: 'CT251'"):
            Counter("count_up", "CT251", "CTD1", "10")
        with pytest.raises(ValueError, match="^Counter.current: 'CTD0'"):
            Counter("count_up", "CT1", "CTD0", "10")

    def test_shift(self) -> None:
        with pytest.raises(ValueError, match="^Shift.start_bit: 'C0'"):
            Shift(start_bit="C0", end_bit="C10")
        with pytest.raises(ValueError, match="^Shift.end_bit: 'C2001'"):
            Shift(start_bit="C1", end_bit="C2001")

    def test_forloop(self) -> None:
        with pytest.raises(ValueError, match="^ForLoop.limit: 'DS4501'"):
            ForLoop(limit="DS4501")
        assert ForLoop(limit="5").limit == "5"

    def test_out_variant(self) -> None:
        with pytest.raises(ValueError, match="^OutVariant.operand: 'Y017'"):
            OutVariant(kind="toggle", operand="Y017")
        with pytest.raises(ValueError, match="^OutVariant.on_acc: 'TD501'"):
            OutVariant(kind="timed", operand="C1", on_acc="TD501", on_preset="1", unit="Tms")
        with pytest.raises(ValueError, match="^OutVariant.off_acc: 'TD0'"):
            OutVariant(
                kind="flasher",
                operand="C1",
                on_acc="TD1",
                on_preset="1",
                off_acc="TD0",
                off_preset="1",
                unit="Tms",
            )

    def test_csv_tokens_raise_with_field(self) -> None:
        with pytest.raises(ValueError, match="^Contact.operand: 'X017'"):
            Contact.from_csv_token("~X017")
        with pytest.raises(ValueError, match="^Contact.operand: 'Q1'"):
            Contact.from_csv_token("rise(Q1)")
        with pytest.raises(ValueError, match="^Coil.range_end: 'Y817'"):
            Coil.from_csv_token("out(Y801..Y817)")
        with pytest.raises(ValueError, match="^Counter.current: 'CTD251'"):
            Counter.from_csv_token("count_up(CT1,CTD251,preset=1)")
        with pytest.raises(ValueError, match="^Shift.end_bit: 'C2001'"):
            Shift.from_csv_token("shift(C1..C2001)")
        with pytest.raises(ValueError, match="^ForLoop.limit: 'DS0'"):
            ForLoop.from_csv_token("for(DS0)")
        with pytest.raises(ValueError, match="^OutVariant.operand: 'Y900'"):
            OutVariant.from_csv_token("toggle(immediate(Y900))")

    def test_leading_zero_text_kept(self) -> None:
        assert Contact.from_csv_token("X001").operand == "X001"
        assert Coil.from_csv_token("out(Y016)").operand == "Y016"


def _swap_operand(blob: bytes, old: str, new: str) -> bytes:
    """Rewrite one UTF-16LE operand string of equal length inside a blob."""
    assert len(old) == len(new)
    before, after = old.encode("utf-16-le"), new.encode("utf-16-le")
    assert blob.count(before) == 1
    return blob.replace(before, after)


class TestDecodeRefusedAddress:
    """A blob whose address CLICK refuses decodes unparsed, not as the model."""

    def test_af_families(self) -> None:
        cases = [
            (Coil(InstructionType.COIL_OUT, "Y801"), "Y801", "Y901"),
            (Coil(InstructionType.COIL_OUT, "C1", range_end="C1999"), "C1999", "C2999"),
            (Counter("count_up", "CT1", "CTD1", "10", reset_enabled=True), "CTD1", "CTD0"),
            (Shift(start_bit="C1", end_bit="C10"), "C10", "C00"),
            (ForLoop(limit="DS100"), "DS100", "DS000"),
            (OutVariant(kind="toggle", operand="C1"), "C1", "C0"),
            (
                OutVariant(kind="timed", operand="C1", on_acc="TD1", on_preset="1", unit="Tms"),
                "TD1",
                "TD0",
            ),
        ]
        for model, old, new in cases:
            blob = model.build_blob()
            assert parse_af_blob(blob) is not None
            assert parse_af_blob(_swap_operand(blob, old, new)) is None, model

    def test_contact(self) -> None:
        blob = Contact(InstructionType.CONTACT_NO, "X101").build_blob()
        assert isinstance(parse_condition_blob(blob), Contact)
        assert parse_condition_blob(_swap_operand(blob, "X101", "X117")) is None

    def test_clipboard_decode_keeps_raw(self) -> None:
        data = encode_rung(1, [[""] * 31], [Coil(InstructionType.COIL_OUT, "Y801")])
        rung = decode(_swap_operand(data, "Y801", "Y901"))
        [af] = rung.instructions
        assert isinstance(af, RawInstruction)
        assert af.class_name == "Out"
        fields = _decompose_blob(af.blob)[4]
        assert "Y901" in [value for _tag, _sentinel, value in fields]
