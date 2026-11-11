"""Field rules of the bit instructions: contacts, compare, coils, Out variants."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from laddercodec import AddressError, FieldError, decode, read_csv
from laddercodec.csv import CSV_HEADER
from laddercodec.csv.ast import ComparisonCondition
from laddercodec.csv.token_parser import parse_condition_token
from laddercodec.encode import encode_rung
from laddercodec.instructions import from_tags_af, from_tags_condition
from laddercodec.instructions.coil import COIL_NAME_TO_TYPE as COIL_TYPES
from laddercodec.instructions.coil import WRITABLE_SC, Coil
from laddercodec.instructions.comparison import CompareContact
from laddercodec.instructions.contact import Contact
from laddercodec.instructions.out_variant import OutVariant
from laddercodec.instructions.timer import TIMER_UNIT_TO_INDEX
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
            'TXT1==" "',
            'TXT1!="~"',
            # Q-B7 (DLL, jobs/dllqa/bits.md): a constant on the left, two constants, and an
            # integer constant inside int32 against a 16-bit register.
            "100<DS1",
            "1==1",
            "DS1>40000",
            "DS1==2147483647",
            "DS1==-2147483648",
            "DH1==0FFFFh",
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

    # Q-B7 (DLL): an integer constant outside int32 is refused, OBJ-005.
    @pytest.mark.parametrize(
        ("token", "field"),
        [
            ("DS1==3000000000", "right"),
            ("DS1==2147483648", "right"),
            ("DS1==-2147483649", "right"),
            ("3000000000>DS1", "left"),
            ("DS1==" + "9" * 5000, "right"),
        ],
    )
    def test_integer_outside_int32_refused(self, token: str, field: str) -> None:
        with pytest.raises(
            FieldError, match=rf"^CompareContact.{field}: .* is outside -2147483648"
        ):
            CompareContact.from_csv_token(token)

    # Q-B7 and N6 (DLL): a hex constant above FFFFh is refused on either side, OBJ-005.
    @pytest.mark.parametrize(
        ("token", "field"),
        [("DH1==10000h", "right"), ("10000H==DH1", "left"), ("XD0==FFFFFFFFh", "right")],
    )
    def test_hex_above_ffff_refused(self, token: str, field: str) -> None:
        with pytest.raises(FieldError, match=rf"^CompareContact.{field}: .* is above FFFFh"):
            CompareContact.from_csv_token(token)

    # bits.md N4: the dialog takes 1 to 128 printable ASCII characters in quotes.
    @pytest.mark.parametrize(
        "token",
        [
            'TXT1==""',
            '""!=TXT1',
            'TXT1=="' + "A" * 129 + '"',
            'TXT1=="é"',
            'TXT1=="	"',
            'TXT1=="Aé"',
        ],
    )
    def test_text_is_one_to_128_printable_characters(self, token: str) -> None:
        with pytest.raises(FieldError, match="a text constant is 1 to 128 printable ASCII"):
            CompareContact.from_csv_token(token)

    def test_quoted_character_code_is_refused(self) -> None:
        with pytest.raises(FieldError, match=r"write the character code as [$]41"):
            CompareContact.from_csv_token('TXT1=="$41"')

    @pytest.mark.parametrize("text", ["AB", "A", "hello world", "a$41", "x" * 128, "=>"])
    def test_multi_character_text_round_trips(self, text: str) -> None:
        compare = CompareContact("==", "TXT771", f'"{text}"')
        again = CompareContact.from_csv_token(compare.to_csv())
        assert (again.op, again.left, again.right) == ("==", "TXT771", f'"{text}"')
        assert again.build_blob() == compare.build_blob()

    def test_multi_character_text_through_read_csv(self, tmp_path: Path) -> None:
        compare = _read_condition(tmp_path, 'TXT771=="AB"')
        assert isinstance(compare, CompareContact) and compare.right == '"AB"'

    def test_multi_character_text_encodes_and_decodes(self) -> None:
        compare = CompareContact.from_csv_token('TXT771=="AB"')
        rung = decode(encode_rung(1, [[compare] + ["-"] * 30], [""]))
        assert rung.conditions[0][0] == compare

    def test_multi_character_blob_differs_in_the_text_field_only(self) -> None:
        one = CompareContact("==", "TXT1", '"A"').build_blob()
        two = CompareContact("==", "TXT1", '"AB"').build_blob()
        text_one = '"A"'.encode("utf-16-le") + bytes(2)
        text_two = '"AB"'.encode("utf-16-le") + bytes(2)
        assert two == one.replace(text_one, text_two)
        # The tag's length prefix is derived from the text, not stored apart.
        assert len(two) - len(one) == len(text_two) - len(text_one)

    # Q-B7 (DLL): with text as Data A the dialog hides >, <, >= and <=.
    @pytest.mark.parametrize(
        "token", ['TXT1>"A"', "TXT1<TXT2", "TXT1>=$41", '"B"<=TXT1', "$41>TXT1"]
    )
    def test_text_takes_equal_and_not_equal_only(self, token: str) -> None:
        with pytest.raises(FieldError, match="^CompareContact.op: .* takes == or !="):
            CompareContact.from_csv_token(token)

    @pytest.mark.parametrize(
        "cell",
        ['TXT1>"A"', 'TXT1==""', 'TXT1=="$41"', "DS1==3000000000", "DH1==10000h", 'T:TXT1<"A"'],
    )
    def test_refusals_through_read_csv(self, tmp_path: Path, cell: str) -> None:
        with pytest.raises(FieldError, match="^CompareContact"):
            _read_condition(tmp_path, cell)

    # The quote character would end the text in the CSV token; $22 spells it.
    @pytest.mark.parametrize(
        ("left", "right", "field"), [('"""', "TXT1", "left"), ("TXT1", '"""', "right")]
    )
    def test_quote_character_refused(self, left: str, right: str, field: str) -> None:
        with pytest.raises(
            FieldError, match=rf"^CompareContact.{field}: .* holds a quote; .* \$22"
        ):
            CompareContact(op="==", left=left, right=right)
        assert CompareContact(op="==", left="TXT1", right="$22").right == "$22"

    def test_quote_inside_text_refused(self) -> None:
        with pytest.raises(FieldError, match="holds a quote"):
            CompareContact("==", '"a"=="b"', '"c"')

    def test_quote_character_refused_through_read_csv(self, tmp_path: Path) -> None:
        with pytest.raises(FieldError, match="^CompareContact.right: .* holds a quote"):
            _read_condition(tmp_path, 'TXT1=="""')
        with pytest.raises(FieldError, match="^CompareContact"):
            _read_condition(tmp_path, 'TXT1=="a"b"')

    # ``\d`` would match Unicode digits; CLICK's classifier takes 0-9 only.
    @pytest.mark.parametrize("token", ["DS1==\u0663", "DS1==1\u0663", "DF1==\u0663.5"])
    def test_unicode_digits_refused(self, token: str) -> None:
        with pytest.raises(FieldError, match="^CompareContact.right"):
            CompareContact.from_csv_token(token)

    def test_text_through_read_csv(self, tmp_path: Path) -> None:
        compare = _read_condition(tmp_path, 'TXT1!="="')
        assert isinstance(compare, CompareContact)
        assert (compare.left, compare.op, compare.right) == ("TXT1", "!=", '"="')

    @pytest.mark.parametrize(
        ("token", "op", "right"),
        [
            ('TXT1=="="', "==", '"="'),
            ('TXT1!="="', "!=", '"="'),
            ('TXT1==">"', "==", '">"'),
            ('TXT1!="<"', "!=", '"<"'),
            ('TXT1=="!"', "==", '"!"'),
            ("TXT1==$3D", "==", "$3D"),
        ],
    )
    def test_quoted_operator_characters(self, token: str, op: str, right: str) -> None:
        parsed = CompareContact.from_csv_token(token)
        assert (parsed.left, parsed.op, parsed.right) == ("TXT1", op, right)

    def test_text_blob_keeps_the_text_as_written(self) -> None:
        # text_compare.bin: CLICK stores the one-character "A" as typed, quotes included.
        compare = CompareContact.from_csv_token('TXT1!="a"')
        blob = compare.build_blob()
        assert '"a"'.encode("utf-16-le") + bytes(2) in blob
        rung = decode(encode_rung(1, [[compare] + ["-"] * 30], [""]))
        assert rung.conditions[0][0] == compare

    def test_hex_suffix_case_keeps_bytes(self) -> None:
        upper = CompareContact.from_csv_token("DH1==FFFFH")
        assert upper.right == "FFFFH"
        assert b"FFFFH".decode().encode("utf-16-le") in upper.build_blob()

    @pytest.mark.parametrize(
        ("cell", "left", "op", "right"),
        [
            ('TXT1=="="', "TXT1", "==", '"="'),
            ('TXT1!="<"', "TXT1", "!=", '"<"'),
            ('TXT1==">"', "TXT1", "==", '">"'),
            ('"<"==TXT1', '"<"', "==", "TXT1"),
            ('">"!=TXT1', '">"', "!=", "TXT1"),
            # The splitter pairs quotes around the whole text.
            ('"a>=b"!=TXT1', '"a>=b"', "!=", "TXT1"),
        ],
    )
    def test_csv_token_parser_skips_quoted_operators(
        self, cell: str, left: str, op: str, right: str
    ) -> None:
        node = parse_condition_token(cell)
        assert isinstance(node, ComparisonCondition)
        assert (node.left, node.op, node.right) == (left, op, right)

    def test_wire_down_prefix(self) -> None:
        assert CompareContact.from_csv_token('T:TXT1!=">"').wire_down


_COILS = ("out", "latch", "reset")


def _read_af(tmp_path: Path, af: str) -> object:
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", "X1"] + ["-"] * 30 + [af])
    return read_csv(path)[0].instructions[0]


def _read_condition(tmp_path: Path, cell: str) -> object:
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", cell] + ["-"] * 30 + ["out(Y001)"])
    return read_csv(path)[0].conditions[0][0]


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

    @pytest.mark.parametrize("preset", ["0", "7", "32767", "00032767", "DS1", "DS4500"])
    def test_debounce_presets(self, preset: str) -> None:
        debounce(on_preset=preset, off_preset=preset)

    # Q-B6 (DLL, jobs/dllqa/bits.md): 32768 is refused for all three kinds, OBJ-005.
    @pytest.mark.parametrize("preset", ["32768", "99999", "9" * 5000])
    def test_preset_above_32767_refused(self, preset: str) -> None:
        with pytest.raises(FieldError, match="^OutVariant.on_preset: .* above the maximum 32767"):
            debounce(on_preset=preset)
        with pytest.raises(FieldError, match="^OutVariant.off_preset: .* above the maximum 32767"):
            debounce(off_preset=preset)
        with pytest.raises(FieldError, match="above the maximum 32767"):
            timed(on_preset=preset)
        with pytest.raises(FieldError, match="above the maximum 32767"):
            OutVariant(
                kind="flasher", operand="C1", on_acc="TD1", on_preset="1",
                off_acc="TD2", off_preset=preset, unit="Tms",
            )  # fmt: skip

    def test_preset_cap_through_read_csv(self, tmp_path: Path) -> None:
        good = "timed(C1,on_acc=TD1,on_preset=32767,unit=Tm)"
        assert isinstance(_read_af(tmp_path, good), OutVariant)
        with pytest.raises(FieldError, match="above the maximum 32767"):
            _read_af(tmp_path, good.replace("32767", "32768"))

    # Q-B5 (DLL): one TD for both phases is refused for debounce and flasher, OBJ-012.
    @pytest.mark.parametrize(("on_acc", "off_acc"), [("TD1", "TD1"), ("TD1", "TD001")])
    def test_same_accumulator_refused(self, tmp_path: Path, on_acc: str, off_acc: str) -> None:
        message = "^OutVariant.off_acc: .* needs two different TD registers"
        with pytest.raises(FieldError, match=message):
            debounce(on_acc=on_acc, off_acc=off_acc)
        token = f"flasher(C1,on_acc={on_acc},on_preset=5,off_acc={off_acc},off_preset=5,unit=Ts)"
        with pytest.raises(FieldError, match=message):
            _read_af(tmp_path, token)

    # Q-B4 (DLL) and v4_captures/debounce_one_phase.bin: a debounce saves with one phase.
    @pytest.mark.parametrize(
        "token",
        [
            "debounce(C1,on_acc=TD1,on_preset=100,unit=Tms)",
            "debounce(C1,off_acc=TD1,off_preset=DS1,unit=Ts)",
        ],
    )
    def test_one_phase_debounce(self, tmp_path: Path, token: str) -> None:
        variant = _read_af(tmp_path, token)
        assert isinstance(variant, OutVariant) and variant.to_csv() == token
        assert OutVariant.from_csv_token(variant.to_csv()) == variant

    def test_one_phase_debounce_fields(self) -> None:
        on_only = debounce(off_acc="", off_preset="")
        assert (on_only.off_acc, on_only.off_preset) == ("", "")
        # One TD for both is checked only when both phases are filled.
        debounce(on_acc="", on_preset="", off_acc="TD1")

    def test_debounce_needs_a_phase(self, tmp_path: Path) -> None:
        # Q-B4 (DLL): both phases empty is refused, OBJ-006.
        message = "^OutVariant.on_preset: debounce needs an on phase or an off phase"
        with pytest.raises(FieldError, match=message):
            debounce(on_acc="", on_preset="", off_acc="", off_preset="")
        with pytest.raises(FieldError, match=message):
            _read_af(tmp_path, "debounce(C1,unit=Tms)")

    def test_half_filled_phase_refused(self, tmp_path: Path) -> None:
        with pytest.raises(FieldError, match="^OutVariant.off_preset"):
            debounce(off_preset="")
        with pytest.raises(AddressError, match="^OutVariant.on_acc"):
            debounce(on_acc="")
        with pytest.raises(FieldError, match="^OutVariant.off_preset"):
            _read_af(tmp_path, "debounce(C1,on_acc=TD1,on_preset=5,off_acc=TD2,unit=Tms)")

    def test_flasher_needs_both_phases(self, tmp_path: Path) -> None:
        with pytest.raises(FieldError, match="^OutVariant.off_acc"):
            OutVariant(kind="flasher", operand="C1", on_acc="TD1", on_preset="5", unit="Tms")
        with pytest.raises(ValueError, match="missing keyword"):
            _read_af(tmp_path, "flasher(C1,on_acc=TD1,on_preset=5,unit=Tms)")

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
    @pytest.mark.parametrize(
        ("left", "right", "type_idx"),
        [
            ("TXT1", '""', "0"),  # empty text
            ("TXT1", '"A"', "2"),  # > with text as Data A
            ("DS1", "3000000000", "0"),  # outside int32
            ("DH1", "10000h", "0"),  # above FFFFh
            ("TXT1", '"' + "A" * 129 + '"', "0"),  # more than 128 characters
            ("TXT1", '"$41"', "0"),  # quoted character code
            ("TXT1", '"""', "0"),  # the quote character
        ],
    )
    def test_refused_compare_blob_is_unknown(self, left: str, right: str, type_idx: str) -> None:
        tags = {0x3218: "4103", 0x6066: left, 0x6067: right, 0x21F7: type_idx}
        assert from_tags_condition("Compare", 0x2714, tags) is None

    def test_multi_character_compare_blob_decodes(self) -> None:
        tags = {0x3218: "4103", 0x6066: "TXT771", 0x6067: '"AB"', 0x21F7: "0"}
        compare = from_tags_condition("Compare", 0x2714, tags)
        assert isinstance(compare, CompareContact) and compare.right == '"AB"'

    def test_one_character_compare_blob_decodes(self) -> None:
        tags = {0x3218: "4104", 0x6066: "TXT1", 0x6067: '"A"', 0x21F7: "1"}
        compare = from_tags_condition("Compare", 0x2714, tags)
        assert isinstance(compare, CompareContact) and compare.right == '"A"'

    @pytest.mark.parametrize(("on_preset", "off_acc"), [("32768", "TD2"), ("5", "TD1")])
    def test_refused_debounce_blob_is_not_a_variant(self, on_preset: str, off_acc: str) -> None:
        tags = {
            0x6066: "C1", 0x60B3: on_preset, 0x60B4: "TD1", 0x60B5: "5", 0x60B6: off_acc,
            0x21F9: TIMER_UNIT_TO_INDEX["Tms"], 0x2248: "1", 0x3218: "8226",
        }  # fmt: skip
        assert from_tags_af("Out", 0x2715, tags) is None
        tags[0x60B3], tags[0x60B6] = "5", "TD2"
        assert isinstance(from_tags_af("Out", 0x2715, tags), OutVariant)

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
