"""Tests for laddercodec.instructions.forloop."""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec import FieldError, decode, decode_program
from laddercodec.binary_helpers import _build_blob
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
