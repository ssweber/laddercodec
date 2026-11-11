"""Tests for laddercodec.model.check_address and the construction checks that use it.

Bank ranges are CLICK v4.00 Help topic CL195 ("Memory Addresses").
"""

from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

import laddercodec.instructions as instructions_mod
from laddercodec import decode, decode_program, read_csv
from laddercodec.csv import CSV_HEADER
from laddercodec.encode import encode_rung
from laddercodec.instructions import (
    Coil,
    Contact,
    Counter,
    ForLoop,
    RawInstruction,
    Shift,
    UnknownCondition,
    parse_af_blob,
    parse_condition_blob,
)
from laddercodec.instructions.out_variant import OutVariant
from laddercodec.instructions.raw import _decompose_blob
from laddercodec.model import (
    ADDRESS_BANKS,
    Address,
    AddressError,
    FieldError,
    InstructionType,
    check_address,
)

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
    @pytest.mark.parametrize(
        "text", ["001", "1", "016", "16", "021", "21", "036", "36", "101", "116", "801", "816"]
    )
    def test_module_points_accepted(self, bank: str, text: str) -> None:
        """21-36 is the CPU's dual option slot; CLICK v4's dialog accepts it (Q-A1)."""
        assert check_address(f"{bank}{text}", "f") == Address(bank, int(text))

    @pytest.mark.parametrize("bank", ["X", "Y"])
    @pytest.mark.parametrize(
        "text",
        ["000", "0", "017", "020", "037", "100", "117", "200", "817", "900", "901"],
    )
    def test_module_points_refused(self, bank: str, text: str) -> None:
        with pytest.raises(
            ValueError,
            match=f"is outside {bank}001-{bank}016, {bank}021-{bank}036, "
            rf"{bank}101-{bank}116 \.\.\. {bank}801-{bank}816$",
        ):
            check_address(f"{bank}{text}", "f")

    @pytest.mark.parametrize("bank", ["XD", "YD"])
    @pytest.mark.parametrize("banks", [None, {"XD", "YD", "DS"}])
    def test_word_io_slots(self, bank: str, banks: set[str] | None) -> None:
        assert check_address(f"{bank}0", "f", banks) == Address(bank, 0)
        assert check_address(f"{bank}1", "f", banks) == Address(bank, 1)
        assert check_address(f"{bank}8", "f", banks) == Address(bank, 8)
        for bad in (f"{bank}9", f"{bank}1u", f"{bank}8u", f"{bank}00u", f"{bank}0000u"):
            with pytest.raises(
                AddressError, match=f"is outside {bank}0, {bank}0u, {bank}1-{bank}8$"
            ):
                check_address(bad, "f", banks)

    @pytest.mark.parametrize("bank", ["XD", "YD"])
    def test_upper_word_only_where_named(self, bank: str) -> None:
        assert check_address(f"{bank}0u", "f", banks={bank}) == Address(bank, 0, upper=True)
        with pytest.raises(AddressError) as info:
            check_address(f"{bank}0u", "f")
        assert str(info.value) == f"f: '{bank}0u' is not allowed; f does not take {bank}0u"
        with pytest.raises(AddressError, match="is not allowed; f takes DS$"):
            check_address(f"{bank}0u", "f", banks={"DS"})

    def test_upper_suffix_only_on_word_io(self) -> None:
        with pytest.raises(ValueError, match=r"'DS1u' is outside DS1-DS4500"):
            check_address("DS1u", "f", banks={"DS"})
        with pytest.raises(ValueError, match=r"'DS1u' is outside DS1-DS4500"):
            check_address("DS1u", "f")

    @pytest.mark.parametrize("value", ["X١", "DS١٠", "C１"])
    def test_ascii_digits_only(self, value: str) -> None:
        with pytest.raises(AddressError, match="is not a CLICK address$"):
            check_address(value, "f")

    def test_error_classes(self) -> None:
        assert issubclass(AddressError, FieldError)
        assert issubclass(FieldError, ValueError)
        with pytest.raises(AddressError):
            check_address("Q1", "f")

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
            "Contact.operand: 'X999' is outside X001-X016, X021-X036, X101-X116 ... X801-X816"
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

    def test_dual_option_slot_through_parse_paths(self, tmp_path: Path) -> None:
        """X021-X036 and Y021-Y036 are the CPU's dual option slot (Q-A1)."""
        assert Contact.from_csv_token("X021").operand == "X021"
        assert Contact.from_csv_token("~X036").operand == "X036"
        path = tmp_path / "rung.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(CSV_HEADER)
            w.writerow(["R", "X021"] + ["-"] * 30 + ["out(Y036)"])
        rung = read_csv(path)[0]
        assert rung.conditions[0][0].operand == "X021"
        assert rung.instructions[0].operand == "Y036"

    def test_leading_zero_text_kept(self) -> None:
        assert Contact.from_csv_token("X001").operand == "X001"
        assert Coil.from_csv_token("out(Y016)").operand == "Y016"

    @pytest.mark.parametrize(
        ("field", "build"),
        [
            ("Contact.operand", lambda: Contact.from_csv_token("XD0u")),
            ("Contact.operand", lambda: Contact(InstructionType.CONTACT_NO, "YD0u")),
            ("Coil.operand", lambda: Coil.from_csv_token("out(XD0u)")),
            ("Coil.operand", lambda: Coil.from_csv_token("out(YD0u..YD1)")),
            # Set takes Y, C and SC only (Q-B1), so the range starts at Y1, not YD0.
            ("Coil.range_end", lambda: Coil(InstructionType.COIL_LATCH, "Y1", range_end="YD0u")),
            ("Counter.done_bit", lambda: Counter("count_up", "XD0u", "CTD1", "1")),
            ("Counter.current", lambda: Counter("count_up", "CT1", "YD0u", "1")),
            ("Shift.start_bit", lambda: Shift.from_csv_token("shift(XD0u..XD1)")),
            ("Shift.end_bit", lambda: Shift(start_bit="XD0", end_bit="XD0u")),
            ("ForLoop.limit", lambda: ForLoop.from_csv_token("for(XD0u)")),
            ("OutVariant.operand", lambda: OutVariant.from_csv_token("toggle(YD0u)")),
            (
                "OutVariant.on_acc",
                lambda: OutVariant(
                    kind="timed", operand="C1", on_acc="XD0u", on_preset="1", unit="Tms"
                ),
            ),
            (
                "OutVariant.off_acc",
                lambda: OutVariant(
                    kind="debounce",
                    operand="C1",
                    on_acc="TD1",
                    on_preset="1",
                    off_acc="YD0u",
                    off_preset="1",
                    unit="Tms",
                ),
            ),
        ],
    )
    def test_upper_word_refused(self, field: str, build) -> None:
        with pytest.raises(AddressError, match=rf"^{field}: '[XY]D0u' is not allowed"):
            build()


_SCR_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scr_captures"


def _utf16z(text: str) -> bytes:
    return text.encode("utf-16-le") + b"\x00\x00"


def _swap_operand(blob: bytes, old: str, new: str) -> bytes:
    """Rewrite one UTF-16LE operand string of equal length inside a blob."""
    assert len(old) == len(new)
    before, after = old.encode("utf-16-le"), new.encode("utf-16-le")
    assert blob.count(before) == 1
    return blob.replace(before, after)


class TestDecodeRefusedAddress:
    """A blob whose address CLICK refuses decodes unparsed, not as the model.

    Both decoders reach the families through ``from_tags_af``/``from_tags_condition``,
    which turn the family's ``ValueError`` into "not parsed".
    """

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

    def test_clipboard_decode(self) -> None:
        conditions = [[Contact(InstructionType.CONTACT_NO, "X101"), *["-"] * 30]]
        data = encode_rung(1, conditions, [Coil(InstructionType.COIL_OUT, "Y801")])
        data = _swap_operand(_swap_operand(data, "Y801", "Y901"), "X101", "X117")
        rung = decode(data)
        assert isinstance(rung.conditions[0][0], UnknownCondition)
        [af] = rung.instructions
        assert isinstance(af, RawInstruction)
        assert af.class_name == "Out"
        fields = _decompose_blob(af.blob)[4]
        assert "Y901" in [value for _tag, _sentinel, value in fields]

    def test_scr_decode(self) -> None:
        # shift_scr: two shift(C1..C2) rungs; C2 occurs only as their end bits.
        data = (_SCR_DIR / "shift_scr.scr").read_bytes()
        data = data.replace(_utf16z("C2"), _utf16z("C0"))
        for rung in decode_program(data).rungs:
            assert isinstance(rung.instructions[0], RawInstruction)
            assert rung.instructions[0].class_name == "SR"
        # coverage rung 1 is ~C4 -> out(C3); C4 occurs once.
        data = (_SCR_DIR / "coverage.scr").read_bytes()
        assert data.count(_utf16z("C4")) == 1
        rung = decode_program(data.replace(_utf16z("C4"), _utf16z("C0"))).rungs[1]
        assert isinstance(rung.conditions[0][0], UnknownCondition)
        assert rung.instructions[0] == Coil(InstructionType.COIL_OUT, "C3")

    def test_dispatchers_catch_only_field_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def refuse(*_args: object) -> None:
            raise AddressError("refused")

        def broken(*_args: object) -> None:
            raise ValueError("parser bug")

        never = SimpleNamespace(from_tags=lambda *_args: pytest.fail("tried another family"))
        for attr, dispatch in (
            ("AF_FAMILY_SPECS", instructions_mod.from_tags_af),
            ("CONDITION_FAMILY_SPECS", instructions_mod.from_tags_condition),
        ):
            monkeypatch.setattr(instructions_mod, attr, (SimpleNamespace(from_tags=refuse), never))
            assert dispatch("Out", 0x2715, {}) is None
            monkeypatch.setattr(instructions_mod, attr, (SimpleNamespace(from_tags=broken),))
            with pytest.raises(ValueError, match="parser bug"):
                dispatch("Out", 0x2715, {})
