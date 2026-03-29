"""Tests for laddercodec.instructions.forloop."""

from __future__ import annotations

from laddercodec.instructions import ForLoop, Next, parse_af_blob


class TestForLoopBlobRoundTrip:
    def test_forloop_basic(self) -> None:
        instr = ForLoop(limit="3", oneshot=False)
        parsed = parse_af_blob(instr.build_blob())
        assert isinstance(parsed, ForLoop)
        assert parsed == instr
        assert parsed.to_csv() == "for(3,oneshot=0)"

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
