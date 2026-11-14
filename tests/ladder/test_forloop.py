"""Tests for laddercodec.instructions.forloop."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from laddercodec import AddressError, FieldError, decode, decode_program, read_csv
from laddercodec.binary_helpers import _build_blob
from laddercodec.csv import CSV_HEADER
from laddercodec.encode import encode_rung
from laddercodec.instructions import Break, Call, Continue, ForLoop, Next, parse_af_blob
from laddercodec.instructions.forloop import NEXT_TYPE_MARKER
from laddercodec.instructions.raw import RawInstruction

_SCR_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scr_captures"


class TestForLoopBlobRoundTrip:
    def test_forloop_basic(self) -> None:
        instr = ForLoop(limit="3", oneshot=False)
        parsed = parse_af_blob(instr.build_blob())
        assert isinstance(parsed, ForLoop)
        assert parsed == instr
        assert parsed.to_csv() == "for(3)"

    def test_forloop_oneshot(self) -> None:
        instr = ForLoop(limit="DS1", oneshot=True)
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
    """CLICK v4 Break/Continue share class ``Next``; the func code (0x3218) tells them apart."""

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
        assert parsed.limit == "3"
        assert parsed.oneshot is False

    def test_parses_native_next_blob_with_single_byte_terminator(self) -> None:
        blob = bytes.fromhex("4e006500780074000000262700000100010000000000ffffffff00")
        parsed = parse_af_blob(blob)
        assert isinstance(parsed, Next)
        assert parsed.to_csv() == "next()"

    def test_parses_native_next_blob_multi_rung(self) -> None:
        """Native multi-rung NEXT has 32-byte blob with proper UTF-16LE empty + trailing zeros."""
        blob = bytes.fromhex("4e006500780074000000262700000100010000000000ffffffff000000000000")
        parsed = parse_af_blob(blob)
        assert isinstance(parsed, Next)


class TestNextBlobSize:
    def test_next_blob_matches_native_size(self) -> None:
        """NEXT blob must be 28 bytes to match native Click encoding."""
        blob = Next().build_blob()
        assert len(blob) == 28

    def test_next_blob_ends_with_empty_field(self) -> None:
        """Terminal field uses proper UTF-16LE empty value (no trailing zeros)."""
        blob = Next().build_blob()
        assert blob[-2:] == b"\x00\x00"


class TestBlankFields:
    def test_blank_limit_is_a_field_error(self) -> None:
        for limit in ("", " ", "\t "):
            with pytest.raises(FieldError, match="ForLoop.limit"):
                ForLoop(limit=limit)

    def test_empty_call_is_a_field_error(self) -> None:
        with pytest.raises(FieldError, match="Call.subroutine"):
            Call(subroutine="")

    def test_empty_call_csv_is_a_field_error(self) -> None:
        with pytest.raises(FieldError, match="Call.subroutine"):
            Call.from_csv_token('call("")')

    def test_whitespace_limit_blob_is_raw(self) -> None:
        blob = ForLoop(limit="DS1").build_blob()
        assert isinstance(parse_af_blob(blob), ForLoop)
        assert (
            parse_af_blob(blob.replace("DS1".encode("utf-16-le"), "   ".encode("utf-16-le")))
            is None
        )

    def test_whitespace_limit_decodes_as_raw_clipboard(self) -> None:
        conditions = [["-"] * 31]
        data = encode_rung(1, conditions, [ForLoop(limit="DS1")])
        data = data.replace("DS1".encode("utf-16-le"), "   ".encode("utf-16-le"))
        [af] = decode(data).instructions
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


def _clipboard_af(model: ForLoop | Call, old: str, new: str) -> object:
    """Encode ``model``, swap one equal-length string, and decode the AF back."""
    assert len(old) == len(new)
    data = encode_rung(1, [["-"] * 31], [model])
    assert data.count(old.encode("utf-16-le")) == 1
    [af] = decode(data.replace(old.encode("utf-16-le"), new.encode("utf-16-le"))).instructions
    return af


class TestForCount:
    """Q-F1: Inst_For.dll OnOK and the user's dialog checks."""

    @pytest.mark.parametrize("limit", ["0", "1", "2147483647", "DS1", "DD1", "TD1", "CTD1", "SD1"])
    def test_accepted(self, tmp_path: Path, limit: str) -> None:
        assert _read_af(tmp_path, f"for({limit})") == ForLoop(limit=limit)

    def test_above_2147483647_refused(self, tmp_path: Path) -> None:
        message = r"^ForLoop.limit: '2147483648' is above 2147483647"
        with pytest.raises(FieldError, match=message):
            _read_af(tmp_path, "for(2147483648)")
        with pytest.raises(FieldError, match=message):
            ForLoop(limit="2147483648")

    @pytest.mark.parametrize("limit", ["-1", "+1", "1.5"])
    def test_sign_or_fraction_refused(self, limit: str) -> None:
        with pytest.raises(FieldError, match="^ForLoop.limit"):
            ForLoop(limit=limit)

    @pytest.mark.parametrize("limit", ["DF1", "DH1", "X001", "C1", "T1", "CT1", "TXT1", "XD0"])
    def test_other_banks_refused(self, tmp_path: Path, limit: str) -> None:
        message = (
            rf"^ForLoop.limit: '{limit}' is not allowed; ForLoop.limit takes DS, DD, TD, CTD, SD$"
        )
        with pytest.raises(AddressError, match=message):
            _read_af(tmp_path, f"for({limit})")
        with pytest.raises(AddressError, match=message):
            ForLoop(limit=limit)

    def test_pointer_refused(self, tmp_path: Path) -> None:
        # Q-F1, user dialog check 2026-11-11.
        message = r"^ForLoop.limit: 'DS\[DS1\]' is a pointer"
        with pytest.raises(AddressError, match=message):
            _read_af(tmp_path, "for(DS[DS1])")
        with pytest.raises(AddressError, match=message):
            ForLoop(limit="DS[DS1]")

    @pytest.mark.parametrize("limit", ["1 0", "1  2 3"])
    def test_inner_space_refused(self, limit: str) -> None:
        # Q-F1: the dialog lets it through; the user's decision of 2026-11-11 refuses it.
        with pytest.raises(FieldError, match="has a space inside"):
            ForLoop(limit=limit)

    def test_outer_space_kept_as_before(self) -> None:
        assert ForLoop(limit=" 5 ").limit == "5"

    @pytest.mark.parametrize(
        ("old", "new"),
        [("DS100", "DF100"), ("DS100", "DS[1]"), ("DS100", "3 000"), ("2000000000", "3000000000")],
    )
    def test_refused_blobs_decode_as_raw(self, old: str, new: str) -> None:
        af = _clipboard_af(ForLoop(limit=old), old, new)
        assert isinstance(af, RawInstruction)
        assert af.class_name == "For"

    def test_refused_bank_decodes_as_raw_scr(self) -> None:
        # coverage.scr: for(DS1), stored as a length byte then text and one NUL byte.
        data = (_SCR_DIR / "coverage.scr").read_bytes()
        old = bytes.fromhex("65600744005300310000")
        new = bytes.fromhex("65600744004600310000")  # DF1
        assert data.count(old) == 1
        rungs = decode_program(data.replace(old, new)).rungs
        raws = [a for r in rungs for a in r.instructions if isinstance(a, RawInstruction)]
        assert [a.class_name for a in raws if a.class_name == "For"] == ["For"]


class TestSubroutineNames:
    """Q-F2: CLICK.exe's Add New Subroutine dialog and the user's dialog checks."""

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
        # Q-F2, user dialog check 2026-11-11: an all-space name is refused.
        with pytest.raises(FieldError, match="^Call.subroutine: .* is blank"):
            _read_af(tmp_path, f'call("{name}")')

    def test_refused_name_decodes_as_raw(self) -> None:
        af = _clipboard_af(Call(subroutine="coverage_sub"), "coverage_sub", "coverage:sub")
        assert isinstance(af, RawInstruction)
        assert af.class_name == "Call"

    def test_refused_name_decodes_as_raw_scr(self) -> None:
        # coverage.scr: call("coverage_sub"), stored as a length byte, the text and one NUL.
        old = bytes([25]) + "coverage_sub".encode("utf-16-le") + b"\x00"
        new = bytes([25]) + "coverage:sub".encode("utf-16-le") + b"\x00"
        data = (_SCR_DIR / "coverage.scr").read_bytes()
        assert data.count(old) == 1
        rungs = decode_program(data.replace(old, new)).rungs
        raws = [a for r in rungs for a in r.instructions if isinstance(a, RawInstruction)]
        assert [a.class_name for a in raws] == ["Call"]

    # CLICK trims the name before it checks it (Q-F2), so the checks see the trimmed text.
    @pytest.mark.parametrize("name", [" " + "x" * 24, "x" * 24 + " ", " a "])
    def test_checks_run_on_the_trimmed_name(self, name: str) -> None:
        assert Call(subroutine=name).subroutine == name

    @pytest.mark.parametrize("name", ["CON ", " con", " CON.x "])
    def test_device_name_with_outer_spaces_refused(self, name: str) -> None:
        with pytest.raises(FieldError, match="(?i)Windows device name 'con'"):
            Call(subroutine=name)
