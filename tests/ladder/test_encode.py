"""Tests for encode() and encode_rung(), with byte-exact golden files.

Each golden fixture is a CSV and BIN pair in tests/fixtures/ladder_captures/golden/.
The CSV is the source of truth for the rung's layout. The BIN holds the bytes that the
encoder must produce, and they were checked by pasting them into CLICK and copying the
rung back.

To regenerate the BIN files, run ``make golden``.
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
    Drum,
    EncodeError,
    FieldError,
    Return,
    Rung,
    Timer,
    decode,
    encode,
    read_csv,
    replace,
)
from laddercodec._comment import sanitize_to_ascii as _sanitize_to_ascii
from laddercodec.csv import CSV_HEADER
from laddercodec.encode import encode_rung
from laddercodec.instructions import (
    UnknownCondition,
    UnknownInstruction,
    from_tags_af,
    from_tags_condition,
)
from tests.golden_io import GOLDEN_DIR
from tests.kept_refusals import kept

# -- Golden CSV/BIN round-trip tests --

_GOLDEN_CSVS = sorted(p for p in GOLDEN_DIR.glob("*.csv") if not p.stem.startswith("mr-"))


@pytest.mark.parametrize("csv_path", _GOLDEN_CSVS, ids=[p.stem for p in _GOLDEN_CSVS])
def test_golden_encode(csv_path: Path) -> None:
    rungs = read_csv(csv_path)  # several rungs when CLICK would split the CSV's rung
    result = encode(rungs if len(rungs) > 1 else rungs[0])
    bin_path = csv_path.with_suffix(".bin")
    assert bin_path.exists(), f"Missing golden .bin: {bin_path.name}"
    expected = bin_path.read_bytes()
    assert result == expected, f"Golden file mismatch: {csv_path.stem}"


# -- Validation edge cases --


def _empty(n: int = 31) -> list[str]:
    return [""] * n


def test_encode_rung_rejects_multiple_nops() -> None:
    with pytest.raises(EncodeError, match="Only one NOP"):
        encode_rung(2, [_empty(), _empty()], ["NOP", "NOP"])


def test_encode_rung_rejects_vertical_col_a() -> None:
    row = _empty()
    row[0] = "|"
    with pytest.raises(EncodeError, match="column A"):
        encode_rung(2, [row, _empty()], ["", ""])


def test_encode_rung_rejects_vertical_last_row() -> None:
    row = _empty()
    row[1] = "|"
    with pytest.raises(EncodeError, match="last row"):
        encode_rung(1, [row], [""])


def test_encode_rung_rejects_out_of_range_rows() -> None:
    with pytest.raises(EncodeError, match="A rung has 1 to 32 rows"):
        encode_rung(0, [], [])
    with pytest.raises(EncodeError, match="A rung has 1 to 32 rows"):
        encode_rung(33, [_empty() for _ in range(33)], [""] * 33)


def test_encode_rung_buffer_sizes() -> None:
    """The size of encode_rung's buffer follows the sizing formula across key row counts."""
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
    """A rung that encode_rung writes decodes to the same contacts and AF instructions."""

    def test_no_contact_out_coil(self) -> None:
        contact = Contact("X001")
        coil = Coil("Y001")
        buf = encode_rung(1, [_wire_row(contact)], [coil])
        [d] = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, Contact)
        assert c.kind == "no"
        assert c.operand == "X001"
        a = d.instructions[0]
        assert isinstance(a, Coil)
        assert a.kind == "out"
        assert a.operand == "Y001"

    def test_nc_contact_latch_coil(self) -> None:
        contact = Contact("X002", kind="nc")
        coil = Coil("Y002", kind="latch")
        buf = encode_rung(1, [_wire_row(contact)], [coil])
        [d] = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, Contact) and c.kind == "nc"
        a = d.instructions[0]
        assert isinstance(a, Coil) and a.kind == "latch"

    def test_edge_rise_reset_coil(self) -> None:
        contact = Contact("X003", kind="rise")
        coil = Coil("Y003", kind="reset")
        buf = encode_rung(1, [_wire_row(contact)], [coil])
        [d] = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, Contact) and c.kind == "rise"
        a = d.instructions[0]
        assert isinstance(a, Coil) and a.kind == "reset"

    def test_edge_fall(self) -> None:
        contact = Contact("X004", kind="fall")
        coil = Coil("Y004")
        buf = encode_rung(1, [_wire_row(contact)], [coil])
        [d] = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, Contact) and c.kind == "fall"

    def test_immediate_contact(self) -> None:
        contact = Contact("X005", immediate=True)
        coil = Coil("Y005")
        buf = encode_rung(1, [_wire_row(contact)], [coil])
        [d] = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, Contact) and c.immediate is True

    def test_immediate_coil(self) -> None:
        contact = Contact("X001")
        coil = Coil("Y001", immediate=True)
        buf = encode_rung(1, [_wire_row(contact)], [coil])
        [d] = decode(buf)
        a = d.instructions[0]
        assert isinstance(a, Coil) and a.immediate is True

    def test_range_coil(self) -> None:
        contact = Contact("X001")
        coil = Coil("C1", range_end="C2")
        buf = encode_rung(1, [_wire_row(contact)], [coil])
        [d] = decode(buf)
        a = d.instructions[0]
        assert isinstance(a, Coil) and a.range_end == "C2" and a.operand == "C1"

    def test_series_contacts(self) -> None:
        c1 = Contact("X001")
        c2 = Contact("X002")
        coil = Coil("Y001")
        row: list[str | Contact] = [c1, "-", c2] + ["-"] * 28
        buf = encode_rung(1, [row], [coil])
        [d] = decode(buf)
        assert isinstance(d.conditions[0][0], Contact)
        assert d.conditions[0][0].operand == "X001"
        assert d.conditions[0][1] == "-"
        assert isinstance(d.conditions[0][2], Contact)
        assert d.conditions[0][2].operand == "X002"

    def test_contact_at_non_zero_col(self) -> None:
        contact = Contact("X001")
        coil = Coil("Y001")
        buf = encode_rung(1, [_wire_row(contact, col=15)], [coil])
        [d] = decode(buf)
        c = d.conditions[0][15]
        assert isinstance(c, Contact) and c.operand == "X001"

    def test_contact_only_no_coil(self) -> None:
        """Contact-only rung (no AF coil) still round-trips."""
        contact = Contact("X001")
        buf = encode_rung(1, [_wire_row(contact)], [""])
        [d] = decode(buf)
        assert isinstance(d.conditions[0][0], Contact)
        assert d.instructions[0] == ""

    def test_coil_only_no_contact(self) -> None:
        """Coil-only rung (wire-in, no contact) still round-trips."""
        coil = Coil("Y001")
        buf = encode_rung(1, [["-"] * 31], [coil])
        [d] = decode(buf)
        assert isinstance(d.instructions[0], Coil)
        assert d.instructions[0].operand == "Y001"

    def test_return_instruction(self) -> None:
        contact = Contact("C233")
        ret = Return()
        buf = encode_rung(1, [_wire_row(contact)], [ret])
        [d] = decode(buf)
        a = d.instructions[0]
        assert isinstance(a, Return)

    def test_mixed_wire_and_instruction(self) -> None:
        """encode_rung writes the bytes of the golden instr-series for two contacts, wires and
        a coil, and the bytes decode to the same row and coil.

        The test builds the row by hand, so the CSV reader plays no part. The CSV file of the
        golden has X002 in column C, and read_csv packs it into column B. The row here puts
        X002 in column B, as the golden's bytes hold it.
        """
        row = _wire_row(Contact("X001"))
        row[1] = Contact("X002")
        buf = encode_rung(1, [row], [Coil("Y001")])
        assert buf == (GOLDEN_DIR / "instr-series.bin").read_bytes()
        [d] = decode(buf)
        assert d.conditions == (tuple(row),)
        assert d.instructions == (Coil("Y001"),)

    # -- CompareContact round-trips --

    def test_compare_eq(self) -> None:
        compare = CompareContact(op="==", left="DS1", right="1")
        coil = Coil("Y001")
        buf = encode_rung(1, [_wire_row(compare)], [coil])
        [d] = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, CompareContact)
        assert c.op == "==" and c.left == "DS1" and c.right == "1"

    def test_compare_ne(self) -> None:
        compare = CompareContact(op="!=", left="DS2", right="DS3")
        buf = encode_rung(1, [_wire_row(compare)], [""])
        [d] = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, CompareContact) and c.op == "!="

    def test_compare_gt(self) -> None:
        compare = CompareContact(op=">", left="DS1", right="100")
        buf = encode_rung(1, [_wire_row(compare)], [""])
        [d] = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, CompareContact) and c.op == ">"

    def test_compare_lt(self) -> None:
        compare = CompareContact(op="<", left="DS1", right="DS2")
        buf = encode_rung(1, [_wire_row(compare)], [""])
        [d] = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, CompareContact) and c.op == "<"

    def test_compare_ge(self) -> None:
        compare = CompareContact(op=">=", left="DS1", right="1")
        buf = encode_rung(1, [_wire_row(compare)], [""])
        [d] = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, CompareContact) and c.op == ">="

    def test_compare_le(self) -> None:
        compare = CompareContact(op="<=", left="DS1", right="1")
        buf = encode_rung(1, [_wire_row(compare)], [""])
        [d] = decode(buf)
        c = d.conditions[0][0]
        assert isinstance(c, CompareContact) and c.op == "<="

    def test_compare_with_contact_and_coil(self) -> None:
        """A Contact, a CompareContact and a Coil in one row decode to the same types."""
        contact = Contact("X001")
        compare = CompareContact(op="==", left="DS1", right="5")
        coil = Coil("Y001")
        row: list[str | Contact | CompareContact] = [contact, "-", compare] + ["-"] * 28
        buf = encode_rung(1, [row], [coil])
        [d] = decode(buf)
        assert isinstance(d.conditions[0][0], Contact)
        assert isinstance(d.conditions[0][2], CompareContact)
        assert isinstance(d.instructions[0], Coil)

    # -- Timer round-trips --

    def test_timer_on_delay(self) -> None:
        contact = Contact("X001")
        timer = Timer(
            kind="on_delay",
            done="T1",
            accumulator="TD1",
            preset="1000",
            unit="Tms",
        )
        buf = encode_rung(2, [_wire_row(contact), _empty()], [timer, ""])
        [d] = decode(buf)
        t = d.instructions[0]
        assert isinstance(t, Timer)
        assert t.kind == "on_delay"
        assert t.done == "T1" and t.accumulator == "TD1"
        assert t.preset == "1000" and t.unit == "Tms"
        assert t.retained is False

    def test_timer_off_delay(self) -> None:
        contact = Contact("X001")
        timer = Timer(
            kind="off_delay",
            done="T2",
            accumulator="TD2",
            preset="500",
            unit="Ts",
        )
        buf = encode_rung(2, [_wire_row(contact), _empty()], [timer, ""])
        [d] = decode(buf)
        t = d.instructions[0]
        assert isinstance(t, Timer) and t.kind == "off_delay"
        assert t.unit == "Ts"

    def test_timer_retentive(self) -> None:
        contact = Contact("X001")
        timer = Timer(
            kind="on_delay",
            done="T3",
            accumulator="TD3",
            preset="10",
            unit="Tm",
            retained=True,
        )
        buf = encode_rung(2, [_wire_row(contact), _empty()], [timer, ""])
        [d] = decode(buf)
        t = d.instructions[0]
        assert isinstance(t, Timer) and t.retained is True
        assert t.unit == "Tm"

    def test_timer_all_units(self) -> None:
        """Each of the 5 time units comes back from decode as it was encoded."""
        for unit in ("Tms", "Ts", "Tm", "Th", "Td"):
            contact = Contact("X001")
            timer = Timer(
                kind="on_delay",
                done="T1",
                accumulator="TD1",
                preset="1",
                unit=unit,
            )
            buf = encode_rung(2, [_wire_row(contact), _empty()], [timer, ""])
            [d] = decode(buf)
            t = d.instructions[0]
            assert isinstance(t, Timer) and t.unit == unit, f"Failed for unit={unit}"


# -- Text constants: "" refused when built (encode checks again), $00 is the blank --


def _one_row_csv(tmp_path: Path, condition: str, af: str) -> Path:
    """Write a CSV of one one-row rung and return its path.

    The rung has *condition* in column A and wires from there to *af*.
    """
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", condition] + ["-"] * 30 + [af])
    return path


_EMPTY_TEXT_SITES = [
    pytest.param("C1", 'copy("",TXT813)', "Copy.source", id="copy_source"),
    pytest.param("C1", 'fill("",TXT1..TXT4)', "Fill.value", id="fill_value"),
]


@pytest.mark.parametrize(("condition", "af", "field"), _EMPTY_TEXT_SITES)
def test_read_csv_refuses_empty_text_constant(
    tmp_path: Path, condition: str, af: str, field: str
) -> None:
    # A Copy or Fill refuses "" when it is built, as Compare and Search do.
    with pytest.raises(FieldError, match=rf"{field}: '\"\"' is refused; a text constant") as exc:
        read_csv(_one_row_csv(tmp_path, condition, af))
    assert str(exc.value).isascii()


def test_replace_refuses_an_empty_text_constant(tmp_path: Path) -> None:
    # replace() raises the same FieldError that building the instance with that value raises.
    [rung] = read_csv(_one_row_csv(tmp_path, "C1", 'copy("Q",TXT813)'))
    with pytest.raises(FieldError, match=r"^Copy.source: '\"\"' is refused") as exc:
        replace(rung.instructions[0], source='""')
    assert exc.value.field == "Copy.source"
    copy = Copy(source='"Q"', dest="TXT1")
    with pytest.raises(FieldError, match="a text constant is 1 to 128 characters"):
        replace(copy, source='""')


@pytest.mark.parametrize("condition", ['TXT842==""', '""!=TXT842', 'T:TXT842==""'])
def test_compare_refuses_empty_text_constant_on_read(tmp_path: Path, condition: str) -> None:
    # A compare refuses "" when it is built. CLICK's dialog refuses it too, with OBJ-005.
    with pytest.raises(FieldError, match="a text constant is 1 to 128 characters"):
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
    [d] = decode(encode(rung))
    assert d.conditions[0][0].to_csv() == condition  # type: ignore[union-attr]
    assert d.instructions[0].to_csv() == af  # type: ignore[union-attr]


def test_decoded_empty_text_constant_is_refused_by_encode() -> None:
    """A Copy, Fill or compare blob that holds "" decodes, and encode() then raises.

    The decoded instruction holds the refusal that building it with "" raises, and encode()
    raises that refusal.
    """
    copy_tags = {0x6074: '""', 0x6076: "TXT1"}
    copy = kept(from_tags_af("Copy", 0x2721, copy_tags), "Copy.source")
    fill_tags = {0x6074: '""', 0x6076: "TXT1", 0x6077: "TXT4", 0x2223: "2"}
    fill = kept(from_tags_af("Copy", 0x2721, fill_tags), "Fill.value")
    tags = {0x6066: "TXT1", 0x6067: '""', 0x21F7: "0"}
    compare = kept(from_tags_condition("Compare", 0x2714, tags), "CompareContact.right")
    for af in (copy, fill):
        with pytest.raises(FieldError, match="is refused; a text constant"):
            encode_rung(1, [["-"] * 31], [af])
    with pytest.raises(FieldError, match="is refused; a text constant"):
        encode_rung(1, [[compare, *["-"] * 30]], [""])


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
        """encode_rung writes a non-ASCII comment as ASCII, and decode reads the ASCII back."""
        buf = encode_rung(1, [_empty()], [""], comment="\u201chello\u201d \u2014 world")
        [d] = decode(buf)
        assert d.comment == '"hello" - world'


def test_encode_refuses_an_unknown_condition() -> None:
    # decode() keeps a condition cell it can't read as an UnknownCondition.
    row: list = [UnknownCondition(b"\x00" * 8)] + ["-"] * 30
    with pytest.raises(EncodeError, match=r"^Unknown condition at row=0, col=0: "):
        encode(Rung([row], [""], None))


def test_encode_refuses_an_unknown_instruction() -> None:
    # decode() keeps an AF cell it can't read as an UnknownInstruction.
    rung = Rung([["-"] * 31], [UnknownInstruction(b"\x00" * 8)], None)
    with pytest.raises(EncodeError, match=r"^Rung 1: Unknown instruction at row=0, AF: "):
        encode([Rung([["-"] * 31], [""], None), rung])


def test_encode_refuses_an_output_cell_that_is_not_a_string_or_instruction() -> None:
    instructions: list = [None]
    with pytest.raises(EncodeError, match=r"^Unsupported AF token: None\. "):
        encode(Rung([["-"] * 31], instructions, None))


def test_encode_refuses_a_comment_too_long() -> None:
    with pytest.raises(EncodeError, match="Comment body exceeds 1400 bytes"):
        encode(Rung([_empty()], [""], "x" * 1500))


def test_replace_refuses_a_drum_accumulator_changed_to_a_non_td_address() -> None:
    drum = Drum(
        kind="time_event_drum",
        outputs=["C1"],
        pattern=[[1]],
        presets=["1"],
        events=["X1"],
        unit="Ts",
        accumulator="TD1",
        current_step="DS1",
        completion_flag="C2",
    )
    with pytest.raises(FieldError, match="^Drum.accumulator: 'DS5' is not allowed") as exc:
        replace(drum, accumulator="DS5")
    assert exc.value.code == "bank-not-allowed"
