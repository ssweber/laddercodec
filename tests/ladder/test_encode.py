"""Byte-exact golden-file tests for encode_rung().

Each golden fixture is a CSV/BIN pair in tests/fixtures/ladder_captures/golden/.
The CSV defines the canonical rung layout (source of truth); the BIN is the
expected encode_rung() output, verified through Click paste round-trip.

Regenerate BIN files:  make golden
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from laddercodec import (
    Coil,
    CompareContact,
    Contact,
    Copy,
    FieldError,
    Return,
    Timer,
    decode,
    encode,
    read_csv,
)
from laddercodec.csv import CSV_HEADER
from laddercodec.encode import _sanitize_to_ascii, encode_rung
from laddercodec.instructions import from_tags_condition
from laddercodec.instructions.copy import from_tags as copy_from_tags
from laddercodec.model import InstructionType
from tests.golden_io import GOLDEN_DIR

# -- Golden CSV/BIN round-trip tests --

_GOLDEN_CSVS = sorted(p for p in GOLDEN_DIR.glob("*.csv") if not p.stem.startswith("mr-"))


@pytest.mark.parametrize("csv_path", _GOLDEN_CSVS, ids=[p.stem for p in _GOLDEN_CSVS])
def test_golden_encode(csv_path: Path) -> None:
    r = read_csv(csv_path)[0]
    result = encode(r)
    bin_path = csv_path.with_suffix(".bin")
    assert bin_path.exists(), f"Missing golden .bin: {bin_path.name}"
    expected = bin_path.read_bytes()
    assert result == expected, f"Golden file mismatch: {csv_path.stem}"


# -- Validation edge cases --


def _empty(n: int = 31) -> list[str]:
    return [""] * n


def test_encode_rung_rejects_multiple_nops() -> None:
    with pytest.raises(ValueError, match="Only one NOP"):
        encode_rung(2, [_empty(), _empty()], ["NOP", "NOP"])


def test_encode_rung_rejects_vertical_col_a() -> None:
    row = _empty()
    row[0] = "|"
    with pytest.raises(ValueError, match="column A"):
        encode_rung(2, [row, _empty()], ["", ""])


def test_encode_rung_rejects_vertical_last_row() -> None:
    row = _empty()
    row[1] = "|"
    with pytest.raises(ValueError, match="last row"):
        encode_rung(1, [row], [""])


def test_encode_rung_rejects_out_of_range_rows() -> None:
    with pytest.raises(ValueError, match="logical_rows"):
        encode_rung(0, [], [])
    with pytest.raises(ValueError, match="logical_rows"):
        encode_rung(33, [_empty() for _ in range(33)], [""] * 33)


def test_encode_rung_buffer_sizes() -> None:
    """Verify buffer sizing formula across key row counts."""
    cases = [
        (1, 0x2000),
        (2, 0x2000),
        (3, 0x3000),
        (4, 0x3000),
        (5, 0x4000),
        (9, 0x6000),
        (17, 0xA000),
        (32, 0x11000),
    ]
    for rows, expected_size in cases:
        result = encode_rung(rows, [_empty() for _ in range(rows)], [""] * rows)
        assert len(result) == expected_size, (
            f"rows={rows}: expected {expected_size}, got {len(result)}"
        )


# -- Instruction cell encode → decode round-trips --


def _wire_row(contact: Contact, col: int = 0) -> list[str | Contact]:
    """Build a condition row with a contact at *col* and wires elsewhere."""
    row: list[str | Contact] = ["-"] * 31
    row[col] = contact
    return row


class TestInstructionRoundTrip:
    """Encode a rung with Contact + Coil, decode, verify identity."""

    def test_no_contact_out_coil(self) -> None:
        contact = Contact(InstructionType.CONTACT_NO, "X001")
        coil = Coil(InstructionType.COIL_OUT, "Y001")
        buf = encode_rung(1, [_wire_row(contact)], [coil])
        d = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, Contact)
        assert c.type == InstructionType.CONTACT_NO
        assert c.operand == "X001"
        a = d.instructions[0]
        assert isinstance(a, Coil)
        assert a.type == InstructionType.COIL_OUT
        assert a.operand == "Y001"

    def test_nc_contact_latch_coil(self) -> None:
        contact = Contact(InstructionType.CONTACT_NC, "X002")
        coil = Coil(InstructionType.COIL_LATCH, "Y002")
        buf = encode_rung(1, [_wire_row(contact)], [coil])
        d = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, Contact) and c.type == InstructionType.CONTACT_NC
        a = d.instructions[0]
        assert isinstance(a, Coil) and a.type == InstructionType.COIL_LATCH

    def test_edge_rise_reset_coil(self) -> None:
        contact = Contact(InstructionType.CONTACT_EDGE, "X003", edge_kind="rise")
        coil = Coil(InstructionType.COIL_RESET, "Y003")
        buf = encode_rung(1, [_wire_row(contact)], [coil])
        d = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, Contact) and c.edge_kind == "rise"
        a = d.instructions[0]
        assert isinstance(a, Coil) and a.type == InstructionType.COIL_RESET

    def test_edge_fall(self) -> None:
        contact = Contact(InstructionType.CONTACT_EDGE, "X004", edge_kind="fall")
        coil = Coil(InstructionType.COIL_OUT, "Y004")
        buf = encode_rung(1, [_wire_row(contact)], [coil])
        d = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, Contact) and c.edge_kind == "fall"

    def test_immediate_contact(self) -> None:
        contact = Contact(InstructionType.CONTACT_NO, "X005", immediate=True)
        coil = Coil(InstructionType.COIL_OUT, "Y005")
        buf = encode_rung(1, [_wire_row(contact)], [coil])
        d = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, Contact) and c.immediate is True

    def test_immediate_coil(self) -> None:
        contact = Contact(InstructionType.CONTACT_NO, "X001")
        coil = Coil(InstructionType.COIL_OUT, "Y001", immediate=True)
        buf = encode_rung(1, [_wire_row(contact)], [coil])
        d = decode(buf)
        a = d.instructions[0]
        assert isinstance(a, Coil) and a.immediate is True

    def test_range_coil(self) -> None:
        contact = Contact(InstructionType.CONTACT_NO, "X001")
        coil = Coil(InstructionType.COIL_OUT, "C1", range_end="C2")
        buf = encode_rung(1, [_wire_row(contact)], [coil])
        d = decode(buf)
        a = d.instructions[0]
        assert isinstance(a, Coil) and a.range_end == "C2" and a.operand == "C1"

    def test_series_contacts(self) -> None:
        c1 = Contact(InstructionType.CONTACT_NO, "X001")
        c2 = Contact(InstructionType.CONTACT_NO, "X002")
        coil = Coil(InstructionType.COIL_OUT, "Y001")
        row: list[str | Contact] = [c1, "-", c2] + ["-"] * 28
        buf = encode_rung(1, [row], [coil])
        d = decode(buf)
        assert isinstance(d.conditions[0][0], Contact)
        assert d.conditions[0][0].operand == "X001"
        assert d.conditions[0][1] == "-"
        assert isinstance(d.conditions[0][2], Contact)
        assert d.conditions[0][2].operand == "X002"

    def test_contact_at_non_zero_col(self) -> None:
        contact = Contact(InstructionType.CONTACT_NO, "X001")
        coil = Coil(InstructionType.COIL_OUT, "Y001")
        buf = encode_rung(1, [_wire_row(contact, col=15)], [coil])
        d = decode(buf)
        c = d.conditions[0][15]
        assert isinstance(c, Contact) and c.operand == "X001"

    def test_contact_only_no_coil(self) -> None:
        """Contact-only rung (no AF coil) still round-trips."""
        contact = Contact(InstructionType.CONTACT_NO, "X001")
        buf = encode_rung(1, [_wire_row(contact)], [""])
        d = decode(buf)
        assert isinstance(d.conditions[0][0], Contact)
        assert d.instructions[0] == ""

    def test_coil_only_no_contact(self) -> None:
        """Coil-only rung (wire-in, no contact) still round-trips."""
        coil = Coil(InstructionType.COIL_OUT, "Y001")
        buf = encode_rung(1, [["-"] * 31], [coil])
        d = decode(buf)
        assert isinstance(d.instructions[0], Coil)
        assert d.instructions[0].operand == "Y001"

    def test_return_instruction(self) -> None:
        contact = Contact(InstructionType.CONTACT_NO, "C233")
        ret = Return()
        buf = encode_rung(1, [_wire_row(contact)], [ret])
        d = decode(buf)
        a = d.instructions[0]
        assert isinstance(a, Return)

    def test_mixed_wire_and_instruction(self) -> None:
        """Existing wire-only golden fixtures are not affected."""
        result = encode_rung(1, [_empty()], [""])
        # Just verify no crash; golden tests cover exact bytes.
        assert len(result) > 0

    # -- CompareContact round-trips --

    def test_compare_eq(self) -> None:
        compare = CompareContact(op="==", left="DS1", right="1")
        coil = Coil(InstructionType.COIL_OUT, "Y001")
        buf = encode_rung(1, [_wire_row(compare)], [coil])
        d = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, CompareContact)
        assert c.op == "==" and c.left == "DS1" and c.right == "1"

    def test_compare_ne(self) -> None:
        compare = CompareContact(op="!=", left="DS2", right="DS3")
        buf = encode_rung(1, [_wire_row(compare)], [""])
        d = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, CompareContact) and c.op == "!="

    def test_compare_gt(self) -> None:
        compare = CompareContact(op=">", left="DS1", right="100")
        buf = encode_rung(1, [_wire_row(compare)], [""])
        d = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, CompareContact) and c.op == ">"

    def test_compare_lt(self) -> None:
        compare = CompareContact(op="<", left="DS1", right="DS2")
        buf = encode_rung(1, [_wire_row(compare)], [""])
        d = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, CompareContact) and c.op == "<"

    def test_compare_ge(self) -> None:
        compare = CompareContact(op=">=", left="DS1", right="1")
        buf = encode_rung(1, [_wire_row(compare)], [""])
        d = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, CompareContact) and c.op == ">="

    def test_compare_le(self) -> None:
        compare = CompareContact(op="<=", left="DS1", right="1")
        buf = encode_rung(1, [_wire_row(compare)], [""])
        d = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, CompareContact) and c.op == "<="

    def test_compare_with_contact_and_coil(self) -> None:
        """CompareContact alongside a regular Contact and Coil."""
        contact = Contact(InstructionType.CONTACT_NO, "X001")
        compare = CompareContact(op="==", left="DS1", right="5")
        coil = Coil(InstructionType.COIL_OUT, "Y001")
        row: list[str | Contact | CompareContact] = [contact, "-", compare] + ["-"] * 28
        buf = encode_rung(1, [row], [coil])
        d = decode(buf)
        assert isinstance(d.conditions[0][0], Contact)
        assert isinstance(d.conditions[0][2], CompareContact)
        assert isinstance(d.instructions[0], Coil)

    # -- Timer round-trips --

    def test_timer_on_delay(self) -> None:
        contact = Contact(InstructionType.CONTACT_NO, "X001")
        timer = Timer(
            timer_type="on_delay",
            done_bit="T1",
            current="TD1",
            setpoint="1000",
            unit="Tms",
        )
        buf = encode_rung(2, [_wire_row(contact), _empty()], [timer, ""])
        d = decode(buf)
        t = d.instructions[0]
        assert isinstance(t, Timer)
        assert t.timer_type == "on_delay"
        assert t.done_bit == "T1" and t.current == "TD1"
        assert t.setpoint == "1000" and t.unit == "Tms"
        assert t.retained is False

    def test_timer_off_delay(self) -> None:
        contact = Contact(InstructionType.CONTACT_NO, "X001")
        timer = Timer(
            timer_type="off_delay",
            done_bit="T2",
            current="TD2",
            setpoint="500",
            unit="Ts",
        )
        buf = encode_rung(2, [_wire_row(contact), _empty()], [timer, ""])
        d = decode(buf)
        t = d.instructions[0]
        assert isinstance(t, Timer) and t.timer_type == "off_delay"
        assert t.unit == "Ts"

    def test_timer_retentive(self) -> None:
        contact = Contact(InstructionType.CONTACT_NO, "X001")
        timer = Timer(
            timer_type="on_delay",
            done_bit="T3",
            current="TD3",
            setpoint="10",
            unit="Tm",
            retained=True,
        )
        buf = encode_rung(2, [_wire_row(contact), _empty()], [timer, ""])
        d = decode(buf)
        t = d.instructions[0]
        assert isinstance(t, Timer) and t.retained is True
        assert t.unit == "Tm"

    def test_timer_all_units(self) -> None:
        """Verify all 5 time units round-trip correctly."""
        for unit in ("Tms", "Ts", "Tm", "Th", "Td"):
            contact = Contact(InstructionType.CONTACT_NO, "X001")
            timer = Timer(
                timer_type="on_delay",
                done_bit="T1",
                current="TD1",
                setpoint="1",
                unit=unit,
            )
            buf = encode_rung(2, [_wire_row(contact), _empty()], [timer, ""])
            d = decode(buf)
            t = d.instructions[0]
            assert isinstance(t, Timer) and t.unit == unit, f"Failed for unit={unit}"


# -- Text constants: "" refused on encode, $00 is the blank --


def _one_row_csv(tmp_path: Path, condition: str, af: str) -> Path:
    """Write a one-row rung: *condition* in column A, wire to *af*."""
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", condition] + ["-"] * 30 + [af])
    return path


_EMPTY_TEXT_SITES = [
    pytest.param("C1", 'copy("",TXT813)', id="copy_source"),
    pytest.param("C1", 'fill("",TXT1..TXT4)', id="fill_value"),
    pytest.param("C1", 'search(TXT1..TXT10 == "",result=DS1,found=C2)', id="search_value"),
]


@pytest.mark.parametrize(("condition", "af"), _EMPTY_TEXT_SITES)
def test_encode_refuses_empty_text_constant(tmp_path: Path, condition: str, af: str) -> None:
    # Reading the CSV is fine; only encoding refuses.
    rung = read_csv(_one_row_csv(tmp_path, condition, af))[0]
    with pytest.raises(ValueError, match=r'Empty text constant "" in .* use \$00') as exc:
        encode(rung)
    assert str(exc.value).isascii()


def test_encode_refuses_empty_text_constant_names_rung(tmp_path: Path) -> None:
    ok = read_csv(_one_row_csv(tmp_path, "C1", "out(Y001)"))[0]
    bad = read_csv(_one_row_csv(tmp_path, "C1", 'copy("",TXT813)'))[0]
    with pytest.raises(
        ValueError, match=r'^Rung 1: Empty text constant "" in copy\("",TXT813\) at row=0'
    ):
        encode([ok, bad])


def test_encode_refuses_empty_text_constant_in_objects() -> None:
    with pytest.raises(ValueError, match="Empty text constant"):
        encode_rung(2, [_empty(), _empty()], [Copy(source='""', destination="TXT1"), ""])


@pytest.mark.parametrize("condition", ['TXT842==""', '""!=TXT842', 'T:TXT842==""'])
def test_compare_refuses_empty_text_constant_on_read(tmp_path: Path, condition: str) -> None:
    # A compare refuses "" when it is built (bits.md N4: CLICK's dialog refuses it, OBJ-005).
    with pytest.raises(FieldError, match="a text constant holds 1 to 128 characters"):
        read_csv(_one_row_csv(tmp_path, condition, "out(Y001)"))
    with pytest.raises(FieldError):
        CompareContact("==", "TXT1", '""')


@pytest.mark.parametrize(
    ("condition", "af"),
    [
        pytest.param("C1", "copy($00,TXT813)", id="copy_source"),
        pytest.param("C1", "fill($00,TXT1..TXT4)", id="fill_value"),
        pytest.param("TXT842==$00", "out(Y001)", id="compare_right"),
        pytest.param("C1", 'copy("Q",TXT813)', id="copy_nonempty_text"),
        pytest.param('TXT842=="T"', "out(Y001)", id="compare_nonempty_text"),
    ],
)
def test_encode_accepts_nul_and_nonempty_text_constants(
    tmp_path: Path, condition: str, af: str
) -> None:
    rung = read_csv(_one_row_csv(tmp_path, condition, af))[0]
    d = decode(encode(rung))
    assert d.conditions[0][0].to_csv() == condition  # type: ignore[union-attr]
    assert d.instructions[0].to_csv() == af  # type: ignore[union-attr]


def test_decoder_accepts_empty_text_constant() -> None:
    """The Copy refusal is encode-only: decoded tags holding "" still build a Copy.

    A compare blob holding "" is refused when built, so it decodes as unknown.
    """
    c = copy_from_tags("Copy", 0x2721, {0x6074: '""', 0x6076: "TXT1"}, {0x2223: 0, 0x2227: 0})
    assert isinstance(c, Copy) and c.to_csv() == 'copy("",TXT1)'
    tags = {0x6066: "TXT1", 0x6067: '""', 0x21F7: "0"}
    assert from_tags_condition("Compare", 0x2714, tags) is None


# -- ASCII sanitization --


class TestSanitizeToAscii:
    def test_dashes(self) -> None:
        assert _sanitize_to_ascii("a\u2014b\u2013c") == "a-b-c"

    def test_arrows(self) -> None:
        assert _sanitize_to_ascii("\u2192") == "->"
        assert _sanitize_to_ascii("\u2190") == "<-"

    def test_math_operators(self) -> None:
        assert _sanitize_to_ascii("\u2265") == ">="
        assert _sanitize_to_ascii("\u2264") == "<="
        assert _sanitize_to_ascii("\u2260") == "!="

    def test_curly_quotes(self) -> None:
        assert _sanitize_to_ascii("\u201chello\u201d") == '"hello"'
        assert _sanitize_to_ascii("\u2018hi\u2019") == "'hi'"

    def test_accented_chars(self) -> None:
        assert _sanitize_to_ascii("caf\u00e9") == "cafe"
        assert _sanitize_to_ascii("na\u00efve") == "naive"

    def test_unknown_non_ascii_replaced(self) -> None:
        assert _sanitize_to_ascii("\u4e16\u754c") == "??"

    def test_pure_ascii_unchanged(self) -> None:
        assert _sanitize_to_ascii("hello world 123!") == "hello world 123!"

    def test_combined(self) -> None:
        assert _sanitize_to_ascii("\u201cval\u201d \u2265 10") == '"val" >= 10'

    def test_comment_round_trip(self) -> None:
        """Encode a rung with non-ASCII comment, decode, verify sanitized."""
        buf = encode_rung(1, [_empty()], [""], comment="\u201chello\u201d \u2014 world")
        d = decode(buf)
        assert d.comment == '"hello" - world'
