"""Tests for laddercodec.instructions.forloop."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from laddercodec import (
    AddressError,
    FieldError,
    RefusedFieldWarning,
    decode,
    decode_program,
    read_csv,
)
from laddercodec.binary_helpers import _build_blob
from laddercodec.codes import Code
from laddercodec.csv import CSV_HEADER
from laddercodec.encode import encode_rung
from laddercodec.instructions import Break, Call, Continue, ForLoop, Next, parse_af_blob
from laddercodec.instructions.forloop import NEXT_TYPE_MARKER
from laddercodec.instructions.raw import RawInstruction
from tests.kept_refusals import kept

_SCR_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scr_captures"


class TestForLoopBlobRoundTrip:
    def test_forloop_basic(self) -> None:
        instr = ForLoop(count="3", oneshot=False)
        parsed = parse_af_blob(instr.build_blob())
        assert isinstance(parsed, ForLoop)
        assert parsed == instr
        assert parsed.to_csv() == "for(3)"

    def test_forloop_oneshot(self) -> None:
        instr = ForLoop(count="DS1", oneshot=True)
        parsed = parse_af_blob(instr.build_blob())
        assert isinstance(parsed, ForLoop)
        assert parsed == instr
        assert parsed.to_csv() == "for(DS1,oneshot=1)"

    def test_next(self) -> None:
        instr = Next()
        parsed = parse_af_blob(instr.build_blob())
        assert isinstance(parsed, Next)
        assert parsed.to_csv() == "next()"


class TestLoopExits:
    """CLICK v4 stores Break and Continue under the class name ``Next``.

    The function code in tag 0x3218 tells Next, Break and Continue apart.
    """

    def test_break_round_trip(self) -> None:
        parsed = parse_af_blob(Break().build_blob())
        assert isinstance(parsed, Break)
        assert parsed.to_csv() == "break()"

    def test_continue_round_trip(self) -> None:
        parsed = parse_af_blob(Continue().build_blob())
        assert isinstance(parsed, Continue)
        assert parsed.to_csv() == "continue()"

    def test_v4_next_func_code_is_next(self) -> None:
        blob = _build_blob("Next", NEXT_TYPE_MARKER, (0x3218, 0x0000), ["9220", ""])
        assert isinstance(parse_af_blob(blob), Next)

    def test_unknown_func_code_is_not_next(self) -> None:
        blob = _build_blob("Next", NEXT_TYPE_MARKER, (0x3218, 0x0000), ["9299", ""])
        assert not isinstance(parse_af_blob(blob), (Next, Break, Continue))


class TestNativeBlobParsing:
    def test_parses_native_for_blob(self) -> None:
        blob = bytes.fromhex(
            "46006f0072000000252700000100040000006560ffffffff330000001832ffffffff"
            "39003200310038000000f811ffffffff300000000000ffffffff0000"
        )
        parsed = parse_af_blob(blob)
        assert isinstance(parsed, ForLoop)
        assert parsed.count == "3"
        assert parsed.oneshot is False

    def test_parses_native_next_blob_with_single_byte_terminator(self) -> None:
        blob = bytes.fromhex("4e006500780074000000262700000100010000000000ffffffff00")
        parsed = parse_af_blob(blob)
        assert isinstance(parsed, Next)
        assert parsed.to_csv() == "next()"

    def test_parses_native_next_blob_multi_rung(self) -> None:
        """A 32-byte Next blob as CLICK writes it in multi-rung data parses as Next.

        The blob ends with an empty UTF-16LE string (two zero bytes) and four more zero bytes.
        """
        blob = bytes.fromhex("4e006500780074000000262700000100010000000000ffffffff000000000000")
        parsed = parse_af_blob(blob)
        assert isinstance(parsed, Next)


class TestNextBlobSize:
    def test_next_blob_matches_native_size(self) -> None:
        """NEXT blob must be 28 bytes to match native Click encoding."""
        blob = Next().build_blob()
        assert len(blob) == 28

    def test_next_blob_ends_with_empty_field(self) -> None:
        """The last field of a Next blob is an empty UTF-16LE string of two zero bytes.

        No padding zeros follow it.
        """
        blob = Next().build_blob()
        assert blob[-2:] == b"\x00\x00"


class TestBlankFields:
    def test_blank_limit_is_a_field_error(self) -> None:
        for limit in ("", " ", "\t "):
            with pytest.raises(FieldError, match="ForLoop.count"):
                ForLoop(count=limit)

    def test_empty_call_is_a_field_error(self) -> None:
        with pytest.raises(FieldError, match="Call.subroutine"):
            Call(subroutine="")

    def test_empty_call_csv_is_a_field_error(self) -> None:
        with pytest.raises(FieldError, match="Call.subroutine"):
            Call.from_csv_token('call("")')

    def test_whitespace_limit_blob_is_raw(self) -> None:
        blob = ForLoop(count="DS1").build_blob()
        assert isinstance(parse_af_blob(blob), ForLoop)
        assert (
            parse_af_blob(blob.replace("DS1".encode("utf-16-le"), "   ".encode("utf-16-le")))
            is None
        )

    def test_whitespace_limit_decodes_as_raw_clipboard(self) -> None:
        conditions = [["-"] * 31]
        data = encode_rung(1, conditions, [ForLoop(count="DS1")])
        data = data.replace("DS1".encode("utf-16-le"), "   ".encode("utf-16-le"))
        [af] = decode(data)[0].instructions
        assert isinstance(af, RawInstruction)
        assert af.class_name == "For"

    def test_whitespace_limit_decodes_as_raw_scr(self) -> None:
        # coverage.scr stores strings as a length byte then text and one NUL byte.
        data = (_SCR_DIR / "coverage.scr").read_bytes()
        old = bytes.fromhex("65600744005300310000")
        assert data.count(old) == 1
        rungs = decode_program(data.replace(old, bytes.fromhex("65600720002000200000"))).rungs
        raws = [a for r in rungs for a in r.instructions if isinstance(a, RawInstruction)]
        assert [a.class_name for a in raws if a.class_name == "For"] == ["For"]


def _read_af(tmp_path: Path, af: str) -> object:
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", "X001"] + ["-"] * 30 + [af])
    return read_csv(path)[0].instructions[0]


#: The location that ``read_csv`` puts at the end of an error about the AF cell that
#: ``_read_af`` writes.
_AT_AF = r" \(at .*rung\.csv, line 2, rung at line 2, row 0 from 0, column AF\)$"


def _clipboard_af(model: ForLoop | Call, old: str, new: str) -> object:
    """Encode a rung with ``model``, replace ``old`` with ``new``, and return the decoded AF.

    ``old`` and ``new`` must be the same length, and ``old`` must appear once in the bytes.
    """
    assert len(old) == len(new)
    data = encode_rung(1, [["-"] * 31], [model])
    assert data.count(old.encode("utf-16-le")) == 1
    [af] = decode(data.replace(old.encode("utf-16-le"), new.encode("utf-16-le")))[0].instructions
    return af


class TestForCount:
    """Test which counts a For instruction accepts."""

    @pytest.mark.parametrize("limit", ["0", "1", "2147483647", "DS1", "DD1", "TD1", "CTD1", "SD1"])
    def test_accepted(self, tmp_path: Path, limit: str) -> None:
        assert _read_af(tmp_path, f"for({limit})") == ForLoop(count=limit)

    def test_above_2147483647_refused(self, tmp_path: Path) -> None:
        message = r"^ForLoop.count: '2147483648' is outside 0 to 2147483647 \(OBJ-005\)"
        with pytest.raises(FieldError, match=message):
            _read_af(tmp_path, "for(2147483648)")
        with pytest.raises(FieldError, match=message):
            ForLoop(count="2147483648")

    def test_a_count_of_thousands_of_digits(self) -> None:
        # Both counts are longer than the 4300 digits that Python's int() reads. The first is
        # accepted because its value is 1, and the second raises FieldError. Neither raises
        # the ValueError from int().
        assert ForLoop(count="0" * 5000 + "1").count == "0" * 5000 + "1"
        with pytest.raises(FieldError):
            ForLoop(count="1" * 5000)

    @pytest.mark.parametrize("limit", ["-1", "+1", "1.5"])
    def test_sign_or_fraction_refused(self, limit: str) -> None:
        with pytest.raises(FieldError, match="^ForLoop.count"):
            ForLoop(count=limit)

    @pytest.mark.parametrize(
        ("count", "rule"),
        [
            ("3.5", "is not a whole number"),
            ("0.4", "is not a whole number"),
            ("2.6", "is not a whole number"),
            ("-1.5", "is not a whole number"),
            ("5.0", "is a real"),
            ("1e3", "is a real"),
            ("1E5", "is a real"),
            ("7FFFh", "is a hex value"),
            ("0h", "is a hex value"),
            ("5h", "is a hex value"),
            ("10000h", "is a hex value"),
            ("FFh", "is a hex value"),
            ("0FFh", "is a hex value"),
            ("-5", "has a minus sign"),
            ("-005", "has a minus sign"),
            ("+5", "has a plus sign"),
            ("$41", "is text"),
            ("$G1", "is text"),
            ("$", "is text"),
        ],
    )
    def test_a_constant_the_count_does_not_take_says_its_kind(self, count: str, rule: str) -> None:
        with pytest.raises(AddressError) as caught:
            ForLoop(count=count)
        exc = caught.value
        # A real with a point has OBJ-005, as 1.5 and -1.5 have.
        click_id = "OBJ-005" if count in ("3.5", "0.4", "2.6", "-1.5", "5.0") else None
        assert (exc.code, exc.click_id) == (Code.NOT_AN_ADDRESS, click_id)
        assert exc.short() == f"{count!r} {rule}"
        assert exc.detail() == (
            "Write a whole number from 0 to 2147483647, or an address in DS, DD, TD, CTD or "
            "SD, such as DS1."
        )

    @pytest.mark.parametrize("count", ['"A"', '"$ 41"'])
    def test_a_quoted_count_says_it_is_text(self, count: str) -> None:
        with pytest.raises(AddressError) as caught:
            ForLoop(count=count)
        assert str(caught.value) == (
            f"ForLoop.count: {count} is quoted text. Write a whole number from 0 to 2147483647, "
            "or an address in DS, DD, TD, CTD or SD, such as DS1."
        )

    @pytest.mark.parametrize("count", ["0x10", "#5", "abc", "DH"])
    def test_a_count_that_is_no_number_is_no_address(self, count: str) -> None:
        with pytest.raises(AddressError, match="is not a CLICK address$"):
            ForLoop(count=count)

    @pytest.mark.parametrize(
        "count",
        [
            *("1.5", "1.50", "01.5", "-1.5", "+1.5", ".5", "-.5", "1."),
            *("1.5E+3", "1.5E3", "1.5e-3", "-1.5E-3", "3.4028235E+38", "3.5E+38", "-3.5E+38"),
            "0" * 13 + "1.5",
        ],
    )
    def test_a_real_with_a_point_has_obj_005(self, count: str) -> None:
        with pytest.raises(AddressError) as caught:
            ForLoop(count=count)
        assert caught.value.click_id == "OBJ-005"
        assert str(caught.value).startswith(f"ForLoop.count: '{count}' is ")
        assert " (OBJ-005). Write a whole number" in str(caught.value)

    @pytest.mark.parametrize(
        "count", ["0" * 14 + "1.5", "0000000000000001.5", ".5E3", "1.E3", "1.5E", "+-1.5"]
    )
    def test_a_count_outside_the_real_rule_has_no_id(self, count: str) -> None:
        """A count of more than 16 characters has no id, because the For dialog's count
        takes 16. An exponent has no id after a point with digits on one side only."""
        with pytest.raises(AddressError) as caught:
            ForLoop(count=count)
        assert caught.value.click_id is None

    @pytest.mark.parametrize("count", ["-0", "-00", " -0 "])
    def test_minus_zero_is_zero(self, count: str) -> None:
        assert ForLoop(count=count).count == "0"
        assert ForLoop(count=count).to_csv() == "for(0)"

    @pytest.mark.parametrize("count", ["-0.0", "--0", "-0x", "+0", "-01"])
    def test_other_signed_counts_refused(self, count: str) -> None:
        with pytest.raises(FieldError, match="^ForLoop.count"):
            ForLoop(count=count)

    @pytest.mark.parametrize("limit", ["DF1", "DH1", "X001", "C1", "T1", "CT1", "TXT1", "XD0"])
    def test_other_banks_refused(self, tmp_path: Path, limit: str) -> None:
        message = (
            rf"^ForLoop.count: '{limit}' is not allowed; ForLoop.count takes DS, DD, TD, CTD, SD"
            r" \(OBJ-004\)"
        )
        with pytest.raises(AddressError, match=message + _AT_AF):
            _read_af(tmp_path, f"for({limit})")
        with pytest.raises(AddressError, match=message + "$"):
            ForLoop(count=limit)

    def test_pointer_refused(self, tmp_path: Path) -> None:
        # The For count takes no pointer.
        message = r"^ForLoop.count: 'DS\[DS1\]' is a pointer"
        with pytest.raises(AddressError, match=message):
            _read_af(tmp_path, "for(DS[DS1])")
        with pytest.raises(AddressError, match=message):
            ForLoop(count="DS[DS1]")

    @pytest.mark.parametrize("limit", ["1 0", "1  2 3"])
    def test_inner_space_refused(self, limit: str) -> None:
        # CLICK's dialog accepts a count with a space inside. laddercodec refuses it because
        # it is not a number.
        with pytest.raises(FieldError, match="has a space in it. Write the count as digits only"):
            ForLoop(count=limit)

    def test_outer_space_kept_as_before(self) -> None:
        assert ForLoop(count=" 5 ").count == "5"

    @pytest.mark.parametrize(
        ("old", "new"),
        [("DS100", "DF100"), ("DS100", "DS[1]"), ("DS100", "3 000"), ("2000000000", "3000000000")],
    )
    def test_refused_blobs_keep_their_refusal(self, old: str, new: str) -> None:
        with pytest.warns(RefusedFieldWarning):
            af = _clipboard_af(ForLoop(count=old), old, new)
        kept(af, "ForLoop.count")
        assert isinstance(af, ForLoop) and af.count == new

    def test_refused_bank_keeps_its_refusal_scr(self) -> None:
        # coverage.scr holds one for(DS1). Its count is stored as a length byte, the text and
        # one NUL byte.
        data = (_SCR_DIR / "coverage.scr").read_bytes()
        old = bytes.fromhex("65600744005300310000")
        new = bytes.fromhex("65600744004600310000")  # DF1
        assert data.count(old) == 1
        with pytest.warns(RefusedFieldWarning):
            rungs = decode_program(data.replace(old, new)).rungs
        loops = [a for r in rungs for a in r.instructions if isinstance(a, ForLoop)]
        assert [kept(a, "ForLoop.count").count for a in loops if a.count == "DF1"] == ["DF1"]


class TestSubroutineNames:
    """Test that a Call's subroutine name follows the rules of CLICK's Add New Subroutine dialog."""

    @pytest.mark.parametrize(
        "name",
        [
            "Main",
            "main",
            ".",
            "a b",
            "a-b",
            "1st",
            "x" * 24,
            "sm_StateComplete2Request",
            "CON1",
            "x.CON",
            "CON.x.y",
            "COM0",
            "COM10",
        ],
    )
    def test_accepted(self, tmp_path: Path, name: str) -> None:
        assert _read_af(tmp_path, f'call("{name}")') == Call(subroutine=name)

    def test_longer_than_24_refused(self, tmp_path: Path) -> None:
        name = "x" * 25
        with pytest.raises(
            FieldError, match="^Call.subroutine: .* is 25 characters; .* at most 24"
        ):
            _read_af(tmp_path, f'call("{name}")')

    @pytest.mark.parametrize("ch", list("\\/:*?<>|"))
    def test_forbidden_characters_refused(self, tmp_path: Path, ch: str) -> None:
        with pytest.raises(FieldError, match="^Call.subroutine: .*GUI-040"):
            _read_af(tmp_path, f'call("a{ch}b")')
        with pytest.raises(FieldError, match="GUI-040"):
            Call(subroutine=f"a{ch}b")

    def test_quote_refused(self) -> None:
        with pytest.raises(FieldError, match="GUI-040"):
            Call(subroutine='a"b')

    @pytest.mark.parametrize(
        "name", ["CON", "con", "Aux.txt", "NUL.", "prn", "CLOCK$", "COM1", "lpt9.x"]
    )
    def test_device_names_refused(self, tmp_path: Path, name: str) -> None:
        with pytest.raises(FieldError, match="^Call.subroutine: .* Windows device name"):
            _read_af(tmp_path, f'call("{name}")')

    @pytest.mark.parametrize("name", [" ", "   "])
    def test_blank_refused(self, tmp_path: Path, name: str) -> None:
        with pytest.raises(FieldError, match="^Call.subroutine: .* is blank"):
            _read_af(tmp_path, f'call("{name}")')

    def test_refused_name_keeps_its_refusal(self) -> None:
        with pytest.warns(RefusedFieldWarning):
            af = _clipboard_af(Call(subroutine="coverage_sub"), "coverage_sub", "coverage:sub")
        kept(af, "Call.subroutine")
        assert isinstance(af, Call) and af.subroutine == "coverage:sub"

    def test_refused_name_keeps_its_refusal_scr(self) -> None:
        # coverage.scr holds one call("coverage_sub"). Its name is stored as a length byte, the
        # text and one NUL byte.
        old = bytes([25]) + "coverage_sub".encode("utf-16-le") + b"\x00"
        new = bytes([25]) + "coverage:sub".encode("utf-16-le") + b"\x00"
        data = (_SCR_DIR / "coverage.scr").read_bytes()
        assert data.count(old) == 1
        with pytest.warns(RefusedFieldWarning):
            rungs = decode_program(data.replace(old, new)).rungs
        calls = [a for r in rungs for a in r.instructions if isinstance(a, Call)]
        assert [kept(a, "Call.subroutine").subroutine for a in calls] == ["coverage:sub"]

    # CLICK trims the name before it checks it. Call checks the trimmed name too, and keeps
    # the name as given.
    @pytest.mark.parametrize("name", [" " + "x" * 24, "x" * 24 + " ", " a "])
    def test_checks_run_on_the_trimmed_name(self, name: str) -> None:
        assert Call(subroutine=name).subroutine == name

    @pytest.mark.parametrize("name", ["CON ", " con", " CON.x "])
    def test_device_name_with_outer_spaces_refused(self, name: str) -> None:
        with pytest.raises(FieldError, match="(?i)Windows device name 'con'"):
            Call(subroutine=name)
