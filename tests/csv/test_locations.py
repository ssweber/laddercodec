"""Every error ``read_csv`` and the bundle reader raise for a bad CSV says where it is."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from laddercodec import AddressError, CsvLocation, FieldError, read_csv
from laddercodec.csv.bundle import parse_bundle
from laddercodec.csv.contract import CONDITION_COLUMNS, CSV_HEADER
from laddercodec.csv.converter import ConvertError

AF = 31
DRUM = "event_drum(outputs=[C3],events=[C2],pattern=[[1]],current_step=DS1,completion_flag=C1)"

Row = tuple[str, dict[int, str], str]


def _cells(marker: str, conditions: dict[int, str], af: str) -> list[str]:
    cells = [""] * len(CONDITION_COLUMNS)
    for column, token in conditions.items():
        cells[column] = token
    return [marker, *cells, af]


def _wired(contact: str) -> dict[int, str]:
    """A contact in A wired across to AF."""
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
    """Read *path*, which must raise exactly *kind* located in *path* at the given place."""
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
        _raises(path, ValueError, "Invalid CSV header", line=1)

    def test_header_after_blank_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "main.csv"
        path.write_text("\n\nmarker,A\n", encoding="utf-8")
        _raises(path, ValueError, "Invalid CSV header", line=3)

    def test_empty_file(self, tmp_path: Path) -> None:
        """The message names the file once, in its location."""
        path = tmp_path / "main.csv"
        path.write_text("", encoding="utf-8")
        exc = _raises(path, ValueError, "^CSV file is empty; expected header row \\(at ")
        assert str(exc).count(str(path)) == 1

    def test_invalid_marker_in_a_rung(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [GOOD, ("Q", {}, "")])
        _raises(path, ValueError, "Invalid marker 'Q'", line=3, rung_line=2, row=1)

    def test_invalid_marker_before_any_rung(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [("Q", {}, ""), GOOD])
        _raises(path, ValueError, "Invalid marker 'Q'", line=2)

    def test_invalid_marker_after_a_comment(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [GOOD, ("#", {0: "note"}, ""), ("Q", {}, "")])
        _raises(path, ValueError, "Invalid marker 'Q'", line=4)

    def test_comment_row_with_its_af_cell(self, tmp_path: Path) -> None:
        """A comment row longer than the header, its AF cell filled: column AF."""
        bad = ["#", "note", *[""] * 30, "stray", ""]
        path = _write(tmp_path / "main.csv", [bad, GOOD])
        _raises(path, ValueError, "Comment rows may only", line=2, column=AF)

    def test_every_shape_before_any_token(self, tmp_path: Path) -> None:
        """A token error on an earlier row loses to a shape error on a later one."""
        rows: list[Row | list[str]] = [("R", _wired("X1"), "frob(1)"), GOOD, ["", "X2"]]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, ValueError, "Expected 33 columns", line=4, rung_line=3, row=1)

    def test_wrong_column_count(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [GOOD, ["", "X002", "-", "out(Y002)"]])
        _raises(path, ValueError, "Expected 33 columns; got 4", line=3, rung_line=2, row=1)

    def test_comment_row_with_a_second_cell(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [("#", {0: "note", 2: "stray"}, ""), GOOD])
        _raises(path, ValueError, "Comment rows may only", line=2, column=2)

    def test_continuation_before_first_rung(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [("", _wired("X001"), "out(Y001)")])
        _raises(path, ValueError, "Continuation row encountered", line=2)

    def test_continuation_after_comment(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [GOOD, ("#", {0: "note"}, ""), ("", _wired("X2"), "")]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, ValueError, "Continuation row encountered", line=4)

    def test_comment_without_rung(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [GOOD, ("#", {0: "one"}, ""), ("#", {0: "two"}, "")]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, ValueError, "Comment row encountered without", line=3)

    def test_multiline_cell_counts_physical_lines(self, tmp_path: Path) -> None:
        """A quoted cell over two lines moves every later row's line by one."""
        rows: list[Row | list[str]] = [("#", {0: "two\nlines"}, ""), GOOD, ("Q", {}, "")]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, ValueError, "Invalid marker", line=5, rung_line=4, row=1)

    def test_csv_error(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [GOOD, ("R", {0: "X" * 200}, "out(Y001)")])
        limit = csv.field_size_limit(100)
        try:
            _raises(path, csv.Error, "field larger than field limit", line=3)
        finally:
            csv.field_size_limit(limit)

    def test_csv_error_in_a_multiline_cell(self, tmp_path: Path) -> None:
        """A csv.Error is at the line its row starts on, not the line it was found on."""
        path = _write(tmp_path / "main.csv", [GOOD, ("R", {0: "a\nb\n" + "X" * 200}, "out(Y1)")])
        limit = csv.field_size_limit(100)
        try:
            _raises(path, csv.Error, "field larger than field limit", line=3)
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
        """A shape error leaves the file closed: it can be removed while the error is held."""
        path = _write(tmp_path / "main.csv", [GOOD, bad, GOOD, GOOD])
        with pytest.raises(ValueError) as info:
            if reader == "read_csv":
                read_csv(path)
            else:
                parse_bundle(tmp_path)
        assert type(info.value) is ValueError
        path.unlink()  # PermissionError on Windows while the file is open
        assert not path.exists()

    def test_undecodable_file_names_only_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / "main.csv"
        path.write_bytes(b"marker,A\n\xff\xfe\n")
        with pytest.raises(UnicodeDecodeError) as info:
            read_csv(path)
        assert CsvLocation.of(info.value) == CsvLocation(file=path)
        assert "(at " not in str(info.value)


class TestTokenParser:
    def test_unmatched_quote(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [GOOD, ("R", _wired("X2"), 'copy("ab,DS1)')])
        _raises(path, ValueError, "unmatched quote", line=3, rung_line=3, row=0, column=AF)

    def test_positional_after_keyword(self, tmp_path: Path) -> None:
        af = "on_delay(T1,preset=5,TD1)"
        path = _write(tmp_path / "main.csv", [("R", _wired("X1"), af)])
        _raises(path, ValueError, "Positional arg after", line=2, rung_line=2, row=0, column=AF)

    @pytest.mark.parametrize(
        "value",
        ['"a"b"c"', '"ab"c'],
        ids=["lone_quote_inside", "no_closing_quote"],
    )
    def test_malformed_quoted_kwarg(self, tmp_path: Path, value: str) -> None:
        af = f"send(target=x,remote_start={value})"
        path = _write(tmp_path / "main.csv", [("R", _wired("X1"), af)])
        _raises(path, ValueError, "Malformed AF quoted", line=2, rung_line=2, row=0, column=AF)


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
        _raises(path, ValueError, "Cannot convert generic", line=2, rung_line=2, row=0, column=0)

    def test_contact_with_non_ascii_digits(self, tmp_path: Path) -> None:
        """An address written with digits outside 0-9 is refused as an address, at its cell."""
        cells = {0: "X001", 1: "-", 2: "X١", **{c: "-" for c in range(3, 31)}}
        path = _write(tmp_path / "main.csv", [("R", cells, "out(Y001)")])
        exc = _raises(path, AddressError, "Contact.operand", line=2, rung_line=2, row=0, column=2)
        assert isinstance(exc, FieldError)
        assert exc.field == "Contact.operand"

    def test_unsupported_af(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [("R", _wired("X1"), "frob(1)")])
        _raises(path, ValueError, "Unsupported AF", line=2, rung_line=2, row=0, column=AF)

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
        _raises(path, ConvertError, "Unknown pin", line=3, rung_line=2, row=1, column=AF)

    def test_pin_not_for_instruction(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [
            ("R", _wired("C96"), "shift(C99..C106)"),
            ("", _wired("C97"), ".down()"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        _raises(
            path, ConvertError, "not supported for shift", line=3, rung_line=2, row=1, column=AF
        )

    def test_pin_out_of_order(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [
            GOOD,
            ("R", _wired("C1"), DRUM),
            ("", _wired("C3"), ".jog()"),
            ("", _wired("C2"), ".reset()"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, ConvertError, "out of order", line=5, rung_line=3, row=2, column=AF)

    def test_nop_bridge_not_under_counter(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [
            ("R", _wired("C77"), "count_down(CT3,CTD3,preset=50)"),
            ("", {}, ""),
            ("", _wired("C78"), "NOP"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, ConvertError, "NOP bridge", line=4, rung_line=2, row=2, column=AF)

    def test_missing_reset_is_at_the_box(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [GOOD, ("R", _wired("C80"), "count_up(CT4,CTD4,preset=10)")]
        path = _write(tmp_path / "main.csv", rows)
        exc = _raises(
            path, ConvertError, "requires a .reset", line=3, rung_line=3, row=0, column=AF
        )
        assert isinstance(exc, ConvertError)
        assert exc.field is None

    def test_refused_pin_keeps_its_field(self, tmp_path: Path) -> None:
        """A field a pin sets, refused, stays a ConvertError and keeps the field it names.

        The ``.reset()`` row is the fault, so the error is at that row, not the box.
        """
        rows: list[Row | list[str]] = [
            ("R", _wired("X1"), "off_delay(T1,TD1,preset=1000,unit=Tms)"),
            ("", _wired("X2"), ".reset()"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        exc = _raises(
            path, ConvertError, "can't be retentive", line=3, rung_line=2, row=1, column=AF
        )
        assert isinstance(exc, ConvertError)
        assert exc.field == "Timer.retained"
        assert isinstance(exc.__cause__, FieldError)

    def test_refused_jump_target_keeps_its_field(self, tmp_path: Path) -> None:
        """The refused target is the ``.jump(...)`` row's value: the error is at that row."""
        rows: list[Row | list[str]] = [
            ("R", _wired("C1"), DRUM),
            ("", _wired("C2"), ".reset()"),
            ("", _wired("C5"), ".jump(C5)"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        exc = _raises(path, ConvertError, "jump_target", line=4, rung_line=2, row=2, column=AF)
        assert isinstance(exc, ConvertError)
        assert exc.field == "Drum.jump_target"
        assert isinstance(exc.__cause__, AddressError)

    def test_refused_jump_target_with_pins_after_it(self, tmp_path: Path) -> None:
        """A leg under the reset and a jog after the jump don't move the error off the jump."""
        rows: list[Row | list[str]] = [
            ("R", _wired("C1"), DRUM),
            ("", _wired("C2"), ".reset()"),
            ("", {0: "C4"}, ""),
            ("", _wired("C5"), ".jump(C5)"),
            ("", _wired("C3"), ".jog()"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, ConvertError, "jump_target", line=5, rung_line=2, row=3, column=AF)

    def test_box_open_at_the_rungs_end(self, tmp_path: Path) -> None:
        """A box still open at the rung's end is located at its own row, not the last."""
        rows: list[Row | list[str]] = [
            ("R", _wired("X1"), "out(Y001)"),
            ("", _wired("C80"), "count_up(CT4,CTD4,preset=10)"),
            ("", {}, ""),
        ]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, ConvertError, "requires a .reset", line=3, rung_line=2, row=1, column=AF)

    def test_box_closed_by_a_later_row(self, tmp_path: Path) -> None:
        """A box a later output row closes is located at its own row, not that later row."""
        rows: list[Row | list[str]] = [
            (
                "R",
                {0: "C80", 1: "T", **{c: "-" for c in range(2, 31)}},
                "count_up(CT4,CTD4,preset=1)",
            ),
            ("", {0: "C81", 1: "-", **{c: "-" for c in range(2, 31)}}, "out(Y002)"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        _raises(path, ConvertError, "requires a .reset", line=2, rung_line=2, row=0, column=AF)


class TestBundle:
    def test_missing_main(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="missing required main.csv") as info:
            parse_bundle(tmp_path)
        assert CsvLocation.of(info.value) == CsvLocation(file=tmp_path / "main.csv")

    def test_bad_main(self, tmp_path: Path) -> None:
        _write(tmp_path / "main.csv", [GOOD, ("Q", {}, "")])
        with pytest.raises(ValueError, match="Invalid marker") as info:
            parse_bundle(tmp_path)
        assert CsvLocation.of(info.value) == CsvLocation(
            file=tmp_path / "main.csv", line=3, rung_line=2, row=1
        )

    def test_bad_subroutine(self, tmp_path: Path) -> None:
        _write(tmp_path / "main.csv", [GOOD])
        _write(tmp_path / "subroutines" / "alpha.csv", [("R", _wired("X1"), "return()")])
        sub = _write(tmp_path / "subroutines" / "beta.csv", [GOOD, ["R", "X1"]])
        with pytest.raises(ValueError, match="Expected 33 columns") as info:
            parse_bundle(tmp_path)
        assert CsvLocation.of(info.value) == CsvLocation(file=sub, line=3, rung_line=3, row=0)
        assert str(info.value).endswith(f"(at {sub}, line 3, rung at line 3, row 0 from 0)")


BAD_TIMER = "on_delay(T1,TD2,preset=40000,unit=Tms)"


def _assert_every_refusal_located(exc: BaseException, path: Path) -> None:
    assert isinstance(exc, (FieldError, ConvertError))
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
        assert by_field["Timer.setpoint"].click_id == "OBJ-005"
        assert "Timer.current" in by_field  # a refusal CLICK has no id for

    def test_refused_pin_row_keeps_its_row_and_reason(self, tmp_path: Path) -> None:
        rows: list[Row | list[str]] = [
            ("R", _wired("X1"), "off_delay(T1,TD1,preset=1000,unit=Tms)"),
            ("", _wired("X2"), ".reset()"),
        ]
        path = _write(tmp_path / "main.csv", rows)
        with pytest.raises(ConvertError) as info:
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
        with pytest.raises(ConvertError) as info:
            read_csv(path)
        assert info.value.errors == (info.value,)
        assert info.value.reason is None


class TestOwnLocations:
    def test_pin_and_box_refusals_each_have_their_own_row(self) -> None:
        """``with_pins`` refusing a pin's value and an unrelated field: each is at its own row.

        No CSV reaches this (a box's own fields are refused when it is built, before its
        pins), so a stub box stands in for one.
        """
        from laddercodec.csv import converter

        pin_error = FieldError("pin", field="Box.pin")
        box_error = FieldError("box", field="Box.other")
        both = FieldError("pin", field="Box.pin")
        both.errors = (both, box_error)

        class Box:
            def with_pins(self, pins: dict, slots: tuple) -> object:
                if pins:
                    raise both
                if True:
                    raise FieldError("box", field="Box.other")

        owner = converter._refusing_pin(Box(), {"p": ()}, (), pin_error)  # type: ignore[arg-type]
        assert owner == "p"
        assert converter._refusing_pin(Box(), {"p": ()}, (), box_error) is None

    def test_condition_cell_refusals_are_each_located(self, tmp_path: Path) -> None:
        path = _write(tmp_path / "main.csv", [("R", _wired("X9999"), "out(Y001)")])
        with pytest.raises(FieldError) as info:
            read_csv(path)
        for refusal in info.value.errors:
            found = CsvLocation.of(refusal)
            assert found is not None
            assert (found.file, found.line, found.column) == (path, 2, 0)
