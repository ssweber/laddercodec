"""Every error that ``read_csv`` and the bundle reader raise for a bad CSV says where in the
file the fault is."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from laddercodec import (
    AddressError,
    CsvError,
    CsvLocation,
    FieldError,
    RefusedFieldWarning,
    read_csv,
)
from laddercodec.codes import Code
from laddercodec.csv.bundle import parse_bundle
from laddercodec.csv.contract import CONDITION_COLUMNS, CSV_HEADER
from laddercodec.operands.unchecked import refusals

AF = 31
DRUM = "event_drum(outputs=[C3],events=[C2],pattern=[[1]],current_step=DS1,completion_flag=C1)"

Row = tuple[str, dict[int, str], str]


def _cells(marker: str, conditions: dict[int, str], af: str) -> list[str]:
    cells = [""] * len(CONDITION_COLUMNS)
    for column, token in conditions.items():
        cells[column] = token
    return [marker, *cells, af]


def _wired(contact: str) -> dict[int, str]:
    """Return condition cells with ``contact`` in column A and a wire from there to AF."""
    return {0: contact, **{c: "-" for c in range(1, len(CONDITION_COLUMNS))}}


def _write(path: Path, rows: list[Row | list[str]], *, header: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if header:
            writer.writerow(CSV_HEADER)
        for row in rows:
            writer.writerow(row if isinstance(row, list) else _cells(*row))
    return path


def _raises(
    path: Path,
    kind: type[BaseException],
    match: str,
    *,
    line: int | None = None,
    rung_line: int | None = None,
    row: int | None = None,
    column: int | None = None,
) -> BaseException:
    """Read *path*, assert that it raises exactly *kind* at the given place in *path*, and
    return the error."""
    with pytest.raises(kind, match=match) as info:
        read_csv(path)
    exc = info.value
    assert type(exc) is kind
    want = CsvLocation(file=path, line=line, rung_line=rung_line, row=row, column=column)
    assert CsvLocation.of(exc) == want
    assert str(exc).endswith(f" (at {want})")
    return exc


GOOD: Row = ("R", _wired("X001"), "out(Y001)")


class TestCsvLocation:
    def test_str_and_column_name(self) -> None:
        location = CsvLocation(file=Path("main.csv"), line=5, rung_line=4, row=1, column=AF)
        assert location.column_name == "AF"
        assert str(location) == "main.csv, line 5, rung at line 4, row 1 from 0, column AF"
        assert CsvLocation(column=0).column_name == "A"
        assert CsvLocation(column=30).column_name == "AE"
        assert CsvLocation().column_name is None
        assert str(CsvLocation(line=1)) == "line 1"

    def test_of_without_location(self) -> None:
        assert CsvLocation.of(ValueError("x")) is None


class TestParser:
    def test_bad_header(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [["marker", "A"], list(_cells(*GOOD))], header=False)
        _raises(path, CsvError, "Invalid CSV header", line=1)

    def test_header_after_blank_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "main.csv"
        path.write_text("\n\nmarker,A\n", encoding="utf-8")
        _raises(path, CsvError, "Invalid CSV header", line=3)

    def test_empty_file(self, tmp_path: Path) -> None:
        """The message names the file once, in its location."""
        path = tmp_path / "main.csv"
        path.write_text("", encoding="utf-8")
        exc = _raises(path, CsvError, "^CSV file is empty; expected header row \\(at ")
        assert str(exc).count(str(path)) == 1

    def test_invalid_marker_in_a_rung(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [GOOD, ("Q", {}, "")])
        _raises(path, CsvError, "Invalid marker 'Q'", line=3, rung_line=2, row=1)

    def test_invalid_marker_before_any_rung(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [("Q", {}, ""), GOOD])
        _raises(path, CsvError, "Invalid marker 'Q'", line=2)

    def test_invalid_marker_after_a_comment(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [GOOD, ("#", {0: "note"}, ""), ("Q", {}, "")])
        _raises(path, CsvError, "Invalid marker 'Q'", line=4)

    def test_comment_row_with_its_af_cell(self, tmp_path: Path) -> None:
        """A comment row that is longer than the header and has text in its AF cell is
        refused at column AF."""
        bad = ["#", "note", *[""] * 30, "stray", ""]
        path = _write(tmp_path / "main.csv", [bad, GOOD])
        _raises(path, CsvError, "Comment rows may only", line=2, column=AF)

    def test_every_shape_before_any_token(self, tmp_path: Path) -> None:
        """The reader checks every row's shape before it reads any token.  A shape error on
        a later row is raised, not a token error on an earlier row."""
        rows: list[Row | list[str]] = [("R", _wired("X1"), "frob(1)"), GOOD, ["", "X2"]]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, CsvError, "Expected 33 columns", line=4, rung_line=3, row=1)

    def test_wrong_column_count(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [GOOD, ["", "X002", "-", "out(Y002)"]])
        _raises(path, CsvError, "Expected 33 columns; got 4", line=3, rung_line=2, row=1)

    def test_comment_row_with_a_second_cell(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [("#", {0: "note", 2: "stray"}, ""), GOOD])
        _raises(path, CsvError, "Comment rows may only", line=2, column=2)

    def test_continuation_before_first_rung(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [("", _wired("X001"), "out(Y001)")])
        _raises(path, CsvError, "Continuation row encountered", line=2)

    def test_continuation_after_comment(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [GOOD, ("#", {0: "note"}, ""), ("", _wired("X2"), "")]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, CsvError, "Continuation row encountered", line=4)

    def test_comment_without_rung(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [GOOD, ("#", {0: "one"}, ""), ("#", {0: "two"}, "")]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, CsvError, "Comment row encountered without", line=3)

    def test_multiline_cell_counts_physical_lines(self, tmp_path: Path) -> None:
        """A quoted cell that spans two lines adds one to the line number of every later row."""
        rows: list[Row | list[str]] = [("#", {0: "two\nlines"}, ""), GOOD, ("Q", {}, "")]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, CsvError, "Invalid marker", line=5, rung_line=4, row=1)

    def test_csv_error(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [GOOD, ("R", {0: "X" * 200}, "out(Y001)")])
        limit = csv.field_size_limit(100)
        try:
            exc = _raises(path, CsvError, "field larger than field limit", line=3)
            assert isinstance(exc.__cause__, csv.Error)
        finally:
            csv.field_size_limit(limit)

    def test_csv_error_in_a_multiline_cell(self, tmp_path: Path) -> None:
        """A csv.Error is at the line its row starts on, not the line it was found on."""
        path = _write(tmp_path / "main.csv", [GOOD, ("R", {0: "a\nb\n" + "X" * 200}, "out(Y1)")])
        limit = csv.field_size_limit(100)
        try:
            exc = _raises(path, CsvError, "field larger than field limit", line=3)
            assert isinstance(exc.__cause__, csv.Error)
        finally:
            csv.field_size_limit(limit)

    @pytest.mark.parametrize(
        "bad",
        [("Q", {}, ""), ["", "X2"], ("#", {0: "note", 2: "stray"}, "")],
        ids=["marker", "column_count", "comment_cell"],
    )
    @pytest.mark.parametrize("reader", ["read_csv", "parse_bundle"])
    def test_file_closed_while_the_error_is_held(
        self, tmp_path: Path, bad: Row | list[str], reader: str
    ) -> None:
        """After a shape error the file is closed, so a caller can delete it while it still
        holds the error."""
        path = _write(tmp_path / "main.csv", [GOOD, bad, GOOD, GOOD])
        with pytest.raises(CsvError) as info:
            if reader == "read_csv":
                read_csv(path)
            else:
                parse_bundle(tmp_path)
        assert type(info.value) is CsvError
        path.unlink()  # raises PermissionError on Windows if the file is still open
        assert not path.exists()

    def test_undecodable_file_names_only_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / "main.csv"
        path.write_bytes(b"marker,A\n\xff\xfe\n")
        exc = _raises(path, CsvError, "'utf-8' codec can't decode byte 0xff")
        assert isinstance(exc.__cause__, UnicodeDecodeError)


class TestTokenParser:
    @pytest.mark.parametrize("keyword", ["target", "remote_start"])
    def test_send_receive_missing_keyword(self, tmp_path: Path, keyword: str) -> None:
        kwargs = {
            "target": 'ModbusRtuTarget(name="rtu",com_port="cpu2",device_id=5)',
            "remote_start": '"DS1"',
            "dest": "DS1",
            "receiving": "C1",
            "success": "C2",
            "error": "C3",
            "exception_response": "DS100",
        }
        del kwargs[keyword]
        af = f"receive({','.join(f'{k}={v}' for k, v in kwargs.items())})"
        path = _write(tmp_path / "main.csv", [("R", _wired("X1"), af)])
        match = f"receive needs a {keyword}= keyword"
        _raises(path, CsvError, match, line=2, rung_line=2, row=0, column=AF)

    def test_unmatched_quote(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [GOOD, ("R", _wired("X2"), 'copy("ab,DS1)')])
        _raises(path, CsvError, "unmatched quote", line=3, rung_line=3, row=0, column=AF)

    def test_positional_after_keyword(self, tmp_path: Path) -> None:
        af = "on_delay(T1,preset=5,TD1)"
        path = _write(tmp_path / "main.csv", [("R", _wired("X1"), af)])
        _raises(path, CsvError, "Positional arg after", line=2, rung_line=2, row=0, column=AF)

    @pytest.mark.parametrize(
        "value",
        ['"a"b"c"', '"ab"c'],
        ids=["lone_quote_inside", "no_closing_quote"],
    )
    def test_malformed_quoted_kwarg(self, tmp_path: Path, value: str) -> None:
        af = f"send(target=x,remote_start={value})"
        path = _write(tmp_path / "main.csv", [("R", _wired("X1"), af)])
        _raises(path, CsvError, "Malformed AF quoted", line=2, rung_line=2, row=0, column=AF)


class TestInstructions:
    def test_contact_address_refused(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [
            ("R", {0: "X001", 1: "T", **{c: "-" for c in range(2, 31)}}, "out(Y001)"),
            ("", {0: "X002", 1: "-", 2: "X999", **{c: "-" for c in range(3, 31)}}, "out(Y002)"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        exc = _raises(path, AddressError, "X999", line=3, rung_line=2, row=1, column=2)
        assert isinstance(exc, FieldError)
        assert exc.field == "Contact.operand"

    def test_coil_address_refused(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [GOOD, GOOD, ("R", _wired("X3"), "out(C9999)")])
        exc = _raises(path, AddressError, "C9999", line=4, rung_line=4, row=0, column=AF)
        assert isinstance(exc, FieldError)
        assert exc.field == "Coil.operand"

    def test_compare_field_refused(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [("R", _wired("DH1==1FFFFh"), "out(Y001)")])
        exc = _raises(path, FieldError, "1FFFFh", line=2, rung_line=2, row=0, column=0)
        assert exc.field is not None

    def test_condition_token_not_understood(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [("R", _wired("+"), "out(Y001)")])
        _raises(
            path,
            CsvError,
            r"Could not read '\+' as a condition cell",
            line=2,
            rung_line=2,
            row=0,
            column=0,
        )

    def test_contact_with_non_ascii_digits(self, tmp_path: Path) -> None:
        """An address written with digits outside 0-9 is refused as an address, at its cell."""
        cells = {0: "X001", 1: "-", 2: "X١", **{c: "-" for c in range(3, 31)}}
        path = _write(tmp_path / "main.csv", [("R", cells, "out(Y001)")])
        exc = _raises(path, AddressError, "Contact.operand", line=2, rung_line=2, row=0, column=2)
        assert isinstance(exc, FieldError)
        assert exc.field == "Contact.operand"

    def test_unsupported_af(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [("R", _wired("X1"), "frob(1)")])
        _raises(
            path,
            CsvError,
            r"Could not read 'frob\(1\)' as an instruction",
            line=2,
            rung_line=2,
            row=0,
            column=AF,
        )

    def test_rung_after_comment_counts_from_its_r_row(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [
            GOOD,
            ("#", {0: "second rung"}, ""),
            ("R", {0: "X001", 1: "T", **{c: "-" for c in range(2, 31)}}, "out(Y001)"),
            ("", {0: "X002", 1: "-", **{c: "-" for c in range(2, 31)}}, "out(C9999)"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, AddressError, "C9999", line=5, rung_line=4, row=1, column=AF)


class TestConverterPins:
    def test_unknown_pin(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [
            ("R", _wired("X1"), "on_delay(T1,TD1,preset=100,unit=Tms)"),
            ("", _wired("X2"), ".bogus()"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        _raises(
            path, CsvError, r"bogus\(\) is not a pin token", line=3, rung_line=2, row=1, column=AF
        )

    def test_pin_not_for_instruction(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [
            ("R", _wired("C96"), "shift(C99..C106)"),
            ("", _wired("C97"), ".down()"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        _raises(
            path,
            CsvError,
            r"shift\(\) has no \.down\(\) pin",
            line=3,
            rung_line=2,
            row=1,
            column=AF,
        )

    def test_pin_out_of_order(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [
            GOOD,
            ("R", _wired("C1"), DRUM),
            ("", _wired("C3"), ".jog()"),
            ("", _wired("C2"), ".reset()"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, CsvError, "out of order", line=5, rung_line=3, row=2, column=AF)

    def test_nop_bridge_not_under_counter(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [
            ("R", _wired("C77"), "count_down(CT3,CTD3,preset=50)"),
            ("", {}, ""),
            ("", _wired("C78"), "NOP"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, CsvError, "is the box.s Down input", line=4, rung_line=2, row=2, column=AF)

    def test_missing_reset_is_at_the_box(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [GOOD, ("R", _wired("C80"), "count_up(CT4,CTD4,preset=10)")]
        path = _write(tmp_path / "main.csv", rows)
        exc = _raises(path, CsvError, "requires a .reset", line=3, rung_line=3, row=0, column=AF)
        assert isinstance(exc, CsvError)
        assert exc.field is None

    def test_refused_pin_keeps_its_field(self, tmp_path: Path) -> None:
        """When the instruction refuses a field that a pin sets, the error is a CsvError that
        names the field.

        The ``.reset()`` row causes the fault, so the error is located at that row, not at
        the box.
        """
        rows: list[Row | list[str]] = [
            ("R", _wired("X1"), "off_delay(T1,TD1,preset=1000,unit=Tms)"),
            ("", _wired("X2"), ".reset()"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        exc = _raises(path, CsvError, "can't be retentive", line=3, rung_line=2, row=1, column=AF)
        assert isinstance(exc, CsvError)
        assert exc.field == "Timer.retained"
        assert isinstance(exc.__cause__, FieldError)

    def test_refused_jump_step_keeps_its_field(self, tmp_path: Path) -> None:
        """The refused jump target comes from the ``.jump(...)`` row, so the error is located
        at that row."""
        rows: list[Row | list[str]] = [
            ("R", _wired("C1"), DRUM),
            ("", _wired("C2"), ".reset()"),
            ("", _wired("C5"), ".jump(C5)"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        exc = _raises(path, CsvError, "jump_step", line=4, rung_line=2, row=2, column=AF)
        assert isinstance(exc, CsvError)
        assert exc.field == "Drum.jump_step"
        assert isinstance(exc.__cause__, AddressError)

    def test_refused_jump_step_with_pins_after_it(self, tmp_path: Path) -> None:
        """A branch row under the reset and a ``.jog()`` row after the jump do not move the
        error off the jump row."""
        rows: list[Row | list[str]] = [
            ("R", _wired("C1"), DRUM),
            ("", _wired("C2"), ".reset()"),
            ("", {0: "C4"}, ""),
            ("", _wired("C5"), ".jump(C5)"),
            ("", _wired("C3"), ".jog()"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, CsvError, "jump_step", line=5, rung_line=2, row=3, column=AF)

    def test_box_open_at_the_rungs_end(self, tmp_path: Path) -> None:
        """If the rung ends before a box gets its required pin row, the error is located at
        the box's row, not at the rung's last row."""
        rows: list[Row | list[str]] = [
            ("R", _wired("X1"), "out(Y001)"),
            ("", _wired("C80"), "count_up(CT4,CTD4,preset=10)"),
            ("", {}, ""),
        ]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, CsvError, "requires a .reset", line=3, rung_line=2, row=1, column=AF)

    def test_box_closed_by_a_later_row(self, tmp_path: Path) -> None:
        """If a later output row ends a box before it gets its required pin row, the error is
        located at the box's row, not at that later row."""
        rows: list[Row | list[str]] = [
            (
                "R",
                {0: "C80", 1: "T", **{c: "-" for c in range(2, 31)}},
                "count_up(CT4,CTD4,preset=1)",
            ),
            ("", {0: "C81", 1: "-", **{c: "-" for c in range(2, 31)}}, "out(Y002)"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, CsvError, "requires a .reset", line=2, rung_line=2, row=0, column=AF)


class TestBundle:
    def test_missing_main(self, tmp_path: Path) -> None:
        with pytest.raises(CsvError, match="missing required main.csv") as info:
            parse_bundle(tmp_path)
        assert CsvLocation.of(info.value) == CsvLocation(file=tmp_path / "main.csv")

    def test_bad_main(self, tmp_path: Path) -> None:
        _write(tmp_path / "main.csv", [GOOD, ("Q", {}, "")])
        with pytest.raises(CsvError, match="Invalid marker") as info:
            parse_bundle(tmp_path)
        assert CsvLocation.of(info.value) == CsvLocation(
            file=tmp_path / "main.csv", line=3, rung_line=2, row=1
        )

    def test_bad_subroutine(self, tmp_path: Path) -> None:
        _write(tmp_path / "main.csv", [GOOD])
        _write(tmp_path / "subroutines" / "alpha.csv", [("R", _wired("X1"), "return()")])
        sub = _write(tmp_path / "subroutines" / "beta.csv", [GOOD, ["R", "X1"]])
        with pytest.raises(CsvError, match="Expected 33 columns") as info:
            parse_bundle(tmp_path)
        assert CsvLocation.of(info.value) == CsvLocation(file=sub, line=3, rung_line=3, row=0)
        assert str(info.value).endswith(f"(at {sub}, line 3, rung at line 3, row 0 from 0)")


BAD_TIMER = "on_delay(T1,TD2,preset=40000,unit=Tms)"


def _assert_every_refusal_located(exc: BaseException, path: Path) -> None:
    assert isinstance(exc, (FieldError, CsvError))
    assert len(exc.errors) >= 2
    for refusal in exc.errors:
        assert isinstance(refusal, FieldError)
        assert refusal.reason is not None
        found = CsvLocation.of(refusal)
        assert found is not None
        assert found.file == path
        assert found.line == 3
        assert found.column == AF


class TestEveryRefusal:
    def test_two_bad_fields_both_arrive_located(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [GOOD, ("R", _wired("X1"), BAD_TIMER)])
        with pytest.raises(FieldError) as info:
            read_csv(path)
        _assert_every_refusal_located(info.value, path)
        by_field = {e.field: e for e in info.value.errors}
        assert len(by_field) == len(info.value.errors)
        assert by_field["Timer.preset"].click_id == "OBJ-005"
        assert "Timer.accumulator" in by_field  # a refusal CLICK has no id for

    def test_refused_pin_row_keeps_its_row_and_reason(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [
            ("R", _wired("X1"), "off_delay(T1,TD1,preset=1000,unit=Tms)"),
            ("", _wired("X2"), ".reset()"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        with pytest.raises(CsvError) as info:
            read_csv(path)
        exc = info.value
        assert exc.field == "Timer.retained"
        assert exc.reason is not None
        assert exc.errors and all(isinstance(e, FieldError) for e in exc.errors)
        for refusal in exc.errors:
            assert CsvLocation.of(refusal) == CsvLocation(
                file=path, line=3, rung_line=2, row=1, column=AF
            )
        assert exc.errors[0].reason == exc.reason
        assert exc.errors[0].click_id == exc.click_id

    def test_other_convert_errors_hold_themselves(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [("R", _wired("X1"), ".bogus()")])
        with pytest.raises(CsvError) as info:
            read_csv(path)
        assert info.value.errors == (info.value,)
        assert info.value.reason is None


class TestOwnLocations:
    def test_pin_and_box_refusals_each_have_their_own_row(self) -> None:
        """When ``with_pins`` refuses both a pin's value and an unrelated field, each refusal
        is located at its own row.

        ``_refusing_pin`` returns the pin for the pin's refusal and None for the other
        refusal.  No CSV can produce this case, because a box refuses its own fields when it is
        built, before it gets its pins.  A stub box stands in for a real one.
        """
        from laddercodec.csv import converter

        pin_error = FieldError("pin", field="Box.pin", code=Code.INVALID_CHOICE)
        box_error = FieldError("box", field="Box.other", code=Code.INVALID_CHOICE)
        both = FieldError("pin", field="Box.pin", code=Code.INVALID_CHOICE)
        both.errors = (both, box_error)

        class Box:
            def with_pins(self, pins: dict, slots: tuple) -> object:
                if pins:
                    raise both
                if True:
                    raise FieldError("box", field="Box.other", code=Code.INVALID_CHOICE)

        owner = converter._refusing_pin(Box(), {"p": ()}, (), pin_error)  # type: ignore[arg-type]
        assert owner == "p"
        assert converter._refusing_pin(Box(), {"p": ()}, (), box_error) is None

    def test_pins_are_probed_with_their_checks_when_reading_unchecked(self) -> None:
        """Under ``unchecked=True``, a box would keep the refusal that a pin's value causes
        instead of raising it.  Each probe runs the checks and raises the refusal anyway, so
        the probes still find the pin that sets the value."""
        from laddercodec.csv import converter
        from laddercodec.operands import unchecked as unchecked_mod

        refusal = FieldError("q", field="Box.q", code=Code.INVALID_CHOICE)

        class Box:
            def with_pins(self, pins: dict, slots: tuple) -> object:
                if "q" in pins and unchecked_mod._KEPT.get() is None:
                    raise FieldError("q", field="Box.q", code=Code.INVALID_CHOICE)
                return self

        box = Box()
        pins: dict = {"p": (), "q": ()}
        with unchecked_mod.unchecked():
            assert converter._refusing_pin(box, pins, (), refusal) == "q"  # type: ignore[arg-type]
            assert converter._refused_pin(box, pins, ()) == "q"  # type: ignore[arg-type]

    def test_condition_cell_refusals_are_each_located(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [("R", _wired("X9999"), "out(Y001)")])
        with pytest.raises(FieldError) as info:
            read_csv(path)
        for refusal in info.value.errors:
            found = CsvLocation.of(refusal)
            assert found is not None
            assert (found.file, found.line, found.column) == (path, 2, 0)


def _held_refusals(path: Path) -> list[FieldError]:
    """Read *path* with ``unchecked=True`` and return every refusal in its warnings, in order."""
    with pytest.warns(RefusedFieldWarning) as record:
        read_csv(path, unchecked=True)
    return [
        e for w in record if isinstance(w.message, RefusedFieldWarning) for e in w.message.errors
    ]


class TestHeldRefusals:
    """``read_csv(..., unchecked=True)`` gives each refusal that it keeps the location that
    the default read gives the raised error."""

    def test_condition_cell(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [GOOD, ("R", {**_wired("X1"), 1: "DS2"}, "out(Y001)")]
        path = _write(tmp_path / "main.csv", rows)
        [refusal] = _held_refusals(path)
        want = CsvLocation(file=path, line=3, rung_line=3, row=0, column=1)
        assert CsvLocation.of(refusal) == want
        with pytest.raises(FieldError) as raised:
            read_csv(path)
        assert CsvLocation.of(raised.value) == want

    def test_a_contact_with_a_down_wire(self, tmp_path: Path) -> None:
        """The layout copies the contact to set its down wire, and the copy keeps the
        location of the refusal."""
        rows: list[Row | list[str]] = [
            ("R", {**_wired("X1"), 1: "T:DS2"}, "out(Y001)"),
            ("", {0: "X2", 1: "X3"}, ""),
        ]
        path = _write(tmp_path / "main.csv", rows)
        with pytest.warns(RefusedFieldWarning):
            [rung] = read_csv(path, unchecked=True)
        contact = rung.conditions[0][1]
        assert getattr(contact, "wire_down", False)
        want = CsvLocation(file=path, line=2, rung_line=2, row=0, column=1)
        assert [CsvLocation.of(e) for e in refusals(contact)] == [want]
        with pytest.raises(FieldError) as raised:
            read_csv(path)
        assert CsvLocation.of(raised.value) == want

    def test_a_pin_rows_value_is_at_its_row(self, tmp_path: Path) -> None:
        """A refusal of the box's own field is located at the box's row, and a refusal of the
        ``.jump(...)`` target at the jump row.  The locations stay right although the layout
        moves the box's pin rows."""
        rows: list[Row | list[str]] = [
            ("R", _wired("C1"), DRUM.replace("current_step=DS1", "current_step=Y001")),
            ("", _wired("C2"), ".reset()"),
            ("", {0: "C4"}, ""),
            ("", _wired("C5"), ".jump(C5)"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        located = {e.field: CsvLocation.of(e) for e in _held_refusals(path)}
        assert located == {
            "Drum.current_step": CsvLocation(file=path, line=2, rung_line=2, row=0, column=AF),
            "Drum.jump_step": CsvLocation(file=path, line=5, rung_line=2, row=3, column=AF),
        }

    def test_the_warning_ends_with_the_first_refusals_location(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [GOOD, ("R", _wired("X1"), BAD_TIMER)])
        with pytest.warns(RefusedFieldWarning) as record:
            read_csv(path, unchecked=True)
        [warning] = [w.message for w in record]
        assert isinstance(warning, RefusedFieldWarning)
        assert len(warning.errors) >= 2
        assert str(warning).endswith(
            f" (at {path}, line 3, rung at line 3, row 0 from 0, column AF)"
        )


@pytest.mark.parametrize(
    ("token", "message"),
    [
        (
            "copy(DS1,TXT1,convert=to_text(suppress_zero=2))",
            "Copy.suppress_zero: '2' is not 1 or 0",
        ),
        ("copy(DF1,TXT1,convert=to_text(exponential=x))", "Copy.exponential: 'x' is not 1 or 0"),
        ("copy(DS1,TXT1,convert=to_text(suppress_zero=))", "Copy.suppress_zero: is blank"),
    ],
)
@pytest.mark.parametrize("unchecked", [False, True])
def test_a_bad_text_option_raises_located_while_the_token_is_read(
    tmp_path: Path, token: str, message: str, unchecked: bool
) -> None:
    """A ``to_text`` option whose value is not 1 or 0 raises when the token is parsed, as
    ``oneshot=2`` does.  It raises even under ``unchecked=True``, because ``unchecked=True``
    keeps only what the instruction's own checks refuse."""
    path = _write(tmp_path / "main.csv", [("R", _wired("X001"), token)])
    with pytest.raises(FieldError, match=message) as info:
        read_csv(path, unchecked=unchecked)
    want = CsvLocation(file=path, line=2, rung_line=2, row=0, column=AF)
    assert CsvLocation.of(info.value) == want
