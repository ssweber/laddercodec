"""Field rules of the bit instructions: contacts, compare, coils, Out variants."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from laddercodec import AddressError, FieldError, read_csv
from laddercodec.csv import CSV_HEADER
from laddercodec.csv.ast import ComparisonCondition
from laddercodec.csv.token_parser import parse_condition_token
from laddercodec.instructions import from_tags_af, from_tags_condition
from laddercodec.instructions.coil import COIL_NAME_TO_TYPE as COIL_TYPES
from laddercodec.instructions.coil import WRITABLE_SC, Coil
from laddercodec.instructions.comparison import CompareContact
from laddercodec.instructions.contact import Contact
from laddercodec.instructions.out_variant import OutVariant
from laddercodec.model import InstructionType

NO = InstructionType.CONTACT_NO
OUT = InstructionType.COIL_OUT


def timed(**kw) -> OutVariant:
    base = {"kind": "timed", "operand": "C1", "on_acc": "TD1", "on_preset": "5", "unit": "Tms"}
    return OutVariant(**{**base, **kw})


def debounce(**kw) -> OutVariant:
    base = {
        "kind": "debounce",
        "operand": "C1",
        "on_acc": "TD1",
        "on_preset": "5",
        "off_acc": "TD2",
        "off_preset": "DS1",
        "unit": "Tms",
    }
    return OutVariant(**{**base, **kw})


class TestContact:
    @pytest.mark.parametrize("op", ["X1", "Y1", "C1", "T1", "CT1", "SC1"])
    def test_banks_accepted(self, op: str) -> None:
        Contact(NO, op)

    @pytest.mark.parametrize("op", ["DS1", "TXT1", "TD1", "XD0"])
    def test_other_banks_refused(self, op: str) -> None:
        with pytest.raises(AddressError, match="^Contact.operand"):
            Contact(NO, op)

    def test_immediate_only_on_x(self) -> None:
        Contact(NO, "X1", immediate=True)
        for op in ("Y1", "C1", "T1"):
            with pytest.raises(FieldError, match="^Contact.immediate"):
                Contact(NO, op, immediate=True)
        with pytest.raises(FieldError, match="^Contact.immediate"):
            Contact.from_csv_token("~C1.immediate")

    def test_edge_has_no_immediate(self) -> None:
        with pytest.raises(FieldError, match="^Contact.immediate"):
            Contact(InstructionType.CONTACT_EDGE, "X1", immediate=True, edge_kind="rise")


class TestCompare:
    @pytest.mark.parametrize(
        "token",
        [
            "DS1==5",
            "DS1>=-5",
            "DF1>1.5",
            "TD1<DS2",
            "CTD1!=SD1",
            "DH1==FFFFh",
            "DH1==FFFFH",
            "DH1==XD0u",
            "XD0==YD8",
            'TXT1=="A"',
            "TXT1==$0D",
            "TXT1==TXT2",
            'TXT1==""',
        ],
    )
    def test_pairs_accepted(self, token: str) -> None:
        assert CompareContact.from_csv_token(token).to_csv() == token

    @pytest.mark.parametrize("token", ["X1==1", "C1==DS1", "DS1==Y1", "T1>5", "SC1==1"])
    def test_bit_banks_refused(self, token: str) -> None:
        with pytest.raises(AddressError, match="^CompareContact"):
            CompareContact.from_csv_token(token)

    @pytest.mark.parametrize(
        "token",
        ["DS1==DH1", "DS1==0000h", 'DS1=="A"', "DH1==5", "TXT1==5", "TXT1==DS1", "DH1==1.5"],
    )
    def test_cross_group_refused(self, token: str) -> None:
        with pytest.raises(FieldError, match="not in one compare group"):
            CompareContact.from_csv_token(token)

    def test_pointer_refused(self) -> None:
        with pytest.raises(AddressError):
            CompareContact(op="==", left="DS[DS1]", right="1")

    @pytest.mark.parametrize(
        ("token", "op", "right"),
        [
            ('TXT1=="="', "==", '"="'),
            ('TXT1!="="', "!=", '"="'),
            ('TXT1<">"', "<", '">"'),
            ('TXT1>"<"', ">", '"<"'),
            ("TXT1==$3D", "==", "$3D"),
        ],
    )
    def test_quoted_operator_characters(self, token: str, op: str, right: str) -> None:
        parsed = CompareContact.from_csv_token(token)
        assert (parsed.left, parsed.op, parsed.right) == ("TXT1", op, right)

    def test_quoted_ascii_code_refused(self) -> None:
        with pytest.raises(AddressError):
            CompareContact.from_csv_token('TXT1=="$41"')

    def test_hex_suffix_case_keeps_bytes(self) -> None:
        upper = CompareContact.from_csv_token("DH1==FFFFH")
        assert upper.right == "FFFFH"
        assert b"FFFFH".decode().encode("utf-16-le") in upper.build_blob()

    @pytest.mark.parametrize(
        ("cell", "left", "op", "right"),
        [
            ('TXT1=="="', "TXT1", "==", '"="'),
            ('TXT1>"<"', "TXT1", ">", '"<"'),
            ('TXT1<">"', "TXT1", "<", '">"'),
            ('"<">TXT1', '"<"', ">", "TXT1"),
        ],
    )
    def test_csv_token_parser_skips_quoted_operators(
        self, cell: str, left: str, op: str, right: str
    ) -> None:
        node = parse_condition_token(cell)
        assert isinstance(node, ComparisonCondition)
        assert (node.left, node.op, node.right) == (left, op, right)

    def test_wire_down_prefix(self) -> None:
        assert CompareContact.from_csv_token('T:TXT1<">"').wire_down


_COILS = ("out", "latch", "reset")


def _read_af(tmp_path: Path, af: str) -> object:
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", "X1"] + ["-"] * 30 + [af])
    return read_csv(path)[0].instructions[0]


class TestCoil:
    @pytest.mark.parametrize("name", _COILS)
    @pytest.mark.parametrize("op", ["Y1", "C1", "SC50"])
    def test_banks_accepted(self, tmp_path: Path, name: str, op: str) -> None:
        coil = _read_af(tmp_path, f"{name}({op})")
        assert isinstance(coil, Coil) and coil.operand == op

    # Out: OBJ-004.  Set and Reset: Q-B1, user dialog check 2026-11-11.
    @pytest.mark.parametrize("name", _COILS)
    @pytest.mark.parametrize("op", ["X1", "T1", "CT1", "DS1"])
    def test_other_banks_refused(self, tmp_path: Path, name: str, op: str) -> None:
        with pytest.raises(AddressError, match=rf"^Coil.operand: '{op}' .*takes Y, C, SC"):
            _read_af(tmp_path, f"{name}({op})")
        with pytest.raises(AddressError, match="^Coil.operand"):
            Coil(COIL_TYPES[name], op)

    # Q-B2, user dialog check 2026-11-11; Set and Reset by ruling.
    @pytest.mark.parametrize("name", _COILS)
    @pytest.mark.parametrize("op", ["SC50", "SC51", "SC171", "SC303", "SC326"])
    def test_writable_sc_accepted(self, tmp_path: Path, name: str, op: str) -> None:
        Coil(COIL_TYPES[name], op)
        assert isinstance(_read_af(tmp_path, f"{name}({op})"), Coil)

    @pytest.mark.parametrize("name", _COILS)
    @pytest.mark.parametrize("op", ["SC1", "SC52", "SC327", "SC1000"])
    def test_other_sc_refused(self, tmp_path: Path, name: str, op: str) -> None:
        message = rf"^Coil.operand: '{op}' is not a writable SC bit; a coil writes SC50, SC51,"
        with pytest.raises(AddressError, match=message):
            _read_af(tmp_path, f"{name}({op})")
        with pytest.raises(AddressError, match=message):
            Coil(COIL_TYPES[name], op)

    def test_writable_sc_is_the_dialog_list(self) -> None:
        # Q-B2, user dialog check 2026-11-11: the 25 bits CLICK's address picker lists.
        assert WRITABLE_SC == {
            50, 51, 53, 55, 60, 61, 65, 66, 67, 75, 76, 120, 121,
            162, 165, 168, 171, 303, 304, 305, 306, 323, 324, 325, 326,
        }  # fmt: skip

    @pytest.mark.parametrize("token", ["out", "latch", "reset", "toggle"])
    @pytest.mark.parametrize("op", ["SC1", "SC50"])
    def test_immediate_sc_names_the_immediate_rule(
        self, tmp_path: Path, token: str, op: str
    ) -> None:
        with pytest.raises(FieldError, match=f"'{op}' is not allowed; an immediate coil takes Y"):
            _read_af(tmp_path, f"{token}(immediate({op}))")

    @pytest.mark.parametrize("name", _COILS)
    def test_sc_range_checks_both_ends(self, tmp_path: Path, name: str) -> None:
        # Q-B3: an SC range is accepted; the bits between are not checked (ruling).
        coil = _read_af(tmp_path, f"{name}(SC50..SC53)")
        assert isinstance(coil, Coil) and coil.range_end == "SC53"
        assert isinstance(_read_af(tmp_path, f"{name}(SC50..SC51)"), Coil)
        with pytest.raises(AddressError, match="^Coil.range_end: 'SC52' is not a writable"):
            _read_af(tmp_path, f"{name}(SC50..SC52)")
        with pytest.raises(AddressError, match="^Coil.operand: 'SC1' is not a writable"):
            _read_af(tmp_path, f"{name}(SC1..SC50)")

    def test_immediate_only_on_y(self) -> None:
        Coil(OUT, "Y1", immediate=True)
        Coil(OUT, "Y1", range_end="Y4", immediate=True)
        with pytest.raises(FieldError, match="^Coil.operand"):
            Coil(OUT, "C1", immediate=True)
        with pytest.raises(FieldError, match="^Coil.operand"):
            Coil(InstructionType.COIL_LATCH, "C1", immediate=True)

    def test_immediate_range_ends_both_y(self) -> None:
        with pytest.raises(FieldError, match="^Coil.range_end"):
            Coil(InstructionType.COIL_LATCH, "Y1", range_end="C2", immediate=True)

    @pytest.mark.parametrize("name", _COILS)
    def test_immediate_range_crosses_a_module(self, tmp_path: Path, name: str) -> None:
        # Q-B3, user dialog check 2026-11-11: immediate Y001..Y101 is accepted.
        coil = _read_af(tmp_path, f"{name}(immediate(Y001..Y101))")
        assert isinstance(coil, Coil) and coil.immediate and coil.range_end == "Y101"

    @pytest.mark.parametrize("name", _COILS)
    def test_whole_c_bank_range(self, tmp_path: Path, name: str) -> None:
        # Q-B3, user dialog check 2026-11-11: C1..C2000 is accepted.
        coil = _read_af(tmp_path, f"{name}(C1..C2000)")
        assert isinstance(coil, Coil) and coil.range_end == "C2000"

    # Out: OBJ-008.  Set and Reset: Q-B1, user dialog check 2026-11-11 (C5..Y5 refused).
    @pytest.mark.parametrize("name", _COILS)
    @pytest.mark.parametrize("token", ["C5..Y5", "C1..SC50", "Y1..C2"])
    def test_range_same_bank(self, tmp_path: Path, name: str, token: str) -> None:
        with pytest.raises(FieldError, match="^Coil.range_end: .* must stay in it"):
            _read_af(tmp_path, f"{name}({token})")
        start, end = token.split("..")
        with pytest.raises(FieldError, match="^Coil.range_end"):
            Coil(COIL_TYPES[name], start, range_end=end)

    # Out: OBJ-009 and Q-B3 (C5..C5).  Set and Reset: Q-B1 (C9..C1), and C5..C5 by ruling.
    @pytest.mark.parametrize("name", _COILS)
    @pytest.mark.parametrize("token", ["C9..C1", "C5..C5", "Y101..Y16", "Y001..Y1"])
    def test_range_ascends(self, tmp_path: Path, name: str, token: str) -> None:
        with pytest.raises(FieldError, match="lower to a higher"):
            _read_af(tmp_path, f"{name}({token})")
        start, end = token.split("..")
        with pytest.raises(FieldError, match="^Coil.range_end: .* is not above"):
            Coil(COIL_TYPES[name], start, range_end=end)

    @pytest.mark.parametrize("name", _COILS)
    def test_range_accepted(self, name: str) -> None:
        Coil(COIL_TYPES[name], "C1", range_end="C5")
        Coil(COIL_TYPES[name], "Y16", range_end="Y101")
        Coil(COIL_TYPES[name], "C1", range_end="C2")


class TestOutVariant:
    @pytest.mark.parametrize("op", ["Y1", "C1", "SC50", "SC326"])
    def test_target_banks(self, op: str) -> None:
        OutVariant(kind="toggle", operand=op)
        timed(operand=op)

    @pytest.mark.parametrize("op", ["X1", "T1", "DS1"])
    def test_target_refused(self, op: str) -> None:
        with pytest.raises(AddressError, match="^OutVariant.operand"):
            OutVariant(kind="toggle", operand=op)

    # The writable SC list applies to the variants too (ruling on Q-B2).
    @pytest.mark.parametrize("op", ["SC1", "SC52", "SC327"])
    def test_other_sc_refused(self, tmp_path: Path, op: str) -> None:
        message = rf"^OutVariant.operand: '{op}' is not a writable SC bit"
        with pytest.raises(AddressError, match=message):
            OutVariant(kind="toggle", operand=op)
        with pytest.raises(AddressError, match=message):
            debounce(operand=op)
        with pytest.raises(AddressError, match=message):
            _read_af(tmp_path, f"toggle({op})")

    def test_writable_sc_through_read_csv(self, tmp_path: Path) -> None:
        variant = _read_af(tmp_path, "toggle(SC50)")
        assert isinstance(variant, OutVariant) and variant.operand == "SC50"

    def test_toggle_immediate_only_on_y(self) -> None:
        OutVariant(kind="toggle", operand="Y1", immediate=True)
        with pytest.raises(FieldError, match="^OutVariant.operand"):
            OutVariant(kind="toggle", operand="C1", immediate=True)

    def test_accumulators_are_td(self) -> None:
        for acc in ("DS1", "T1", "TD0", "TD501", "CTD1"):
            with pytest.raises(AddressError, match="^OutVariant.on_acc"):
                timed(on_acc=acc)
        with pytest.raises(AddressError, match="^OutVariant.off_acc"):
            debounce(off_acc="DS2")

    @pytest.mark.parametrize("preset", ["0", "7", "32768", "DS1", "DS4500"])
    def test_debounce_presets(self, preset: str) -> None:
        debounce(on_preset=preset, off_preset=preset)

    @pytest.mark.parametrize("preset", ["", "1.5", "TD1", "DS0", "DD1", "1h"])
    def test_bad_presets(self, preset: str) -> None:
        with pytest.raises(FieldError, match="^OutVariant.on_preset"):
            debounce(on_preset=preset)
        with pytest.raises(FieldError, match="^OutVariant.off_preset"):
            debounce(off_preset=preset)

    @pytest.mark.parametrize("preset", ["-1", "+5"])
    def test_signed_preset_names_the_minimum(self, preset: str) -> None:
        with pytest.raises(FieldError, match="below the minimum 0"):
            debounce(on_preset=preset)

    def test_preset_floors(self) -> None:
        debounce(on_preset="0")
        for kind_args in (
            {"kind": "flasher", "off_acc": "TD2", "off_preset": "1"},
            {"kind": "timed"},
        ):
            with pytest.raises(FieldError, match="minimum 1"):
                OutVariant(
                    **{
                        "operand": "C1",
                        "on_acc": "TD1",
                        "on_preset": "0",
                        "unit": "Tms",
                        **kind_args,
                    }
                )

    def test_maintained_timed_only(self) -> None:
        timed(maintained=True)
        with pytest.raises(FieldError, match="^OutVariant.maintained"):
            debounce(maintained=True)
        with pytest.raises(FieldError, match="^OutVariant.maintained"):
            OutVariant(kind="toggle", operand="C1", maintained=True)

    def test_unused_fields_refused(self) -> None:
        with pytest.raises(FieldError, match="^OutVariant.on_acc: 'Q77' is not used by toggle"):
            OutVariant(kind="toggle", operand="C1", on_acc="Q77")
        with pytest.raises(FieldError, match="^OutVariant.off_acc"):
            timed(off_acc="TD2")
        with pytest.raises(FieldError, match="^OutVariant.off_preset"):
            timed(off_preset="5")
        with pytest.raises(FieldError, match="^OutVariant.unit"):
            OutVariant(kind="toggle", operand="C1", unit="Ts")
        with pytest.raises(FieldError, match="^OutVariant.immediate"):
            timed(operand="Y1", immediate=True)

    def test_bad_unit_is_a_field_error_on_construction(self) -> None:
        with pytest.raises(FieldError, match="^OutVariant.unit"):
            timed(unit="x")
        with pytest.raises(FieldError, match="^OutVariant.unit"):
            debounce(unit="Tm")
        timed(unit="Tm")

    def test_csv_unit_error_keeps_its_message(self) -> None:
        token = "debounce(C1,on_acc=TD1,on_preset=1,off_acc=TD2,off_preset=1,unit=Tm)"
        with pytest.raises(FieldError, match="does not support unit"):
            OutVariant.from_csv_token(token)


class TestDecodeRefusal:
    def test_refused_contact_blob_is_unknown(self) -> None:
        assert from_tags_condition("ContactNO", 0x2711, {0x6065: "DS1", 0x11F5: "0"}) is None

    def test_refused_coil_blob_is_not_a_coil(self) -> None:
        tags = {0x6066: "X1", 0x6067: "", 0x11F8: "0", 0x11F5: "0", 0x3218: "8193"}
        assert from_tags_af("Out", 0x2715, tags) is None

    @pytest.mark.parametrize(
        ("type_code", "operand", "range_end", "func_code"),
        [
            (0x2715, "SC52", "", "8193"),  # Out of a read-only SC
            (0x2716, "X1", "", "8195"),  # Set of X
            (0x2717, "C9", "C1", "8219"),  # Reset of a reversed range
        ],
    )
    def test_refused_coil_blobs(
        self, type_code: int, operand: str, range_end: str, func_code: str
    ) -> None:
        tags = {0x6066: operand, 0x6067: range_end, 0x11F8: "0", 0x11F5: "0", 0x3218: func_code}
        assert from_tags_af("Out", type_code, tags) is None
