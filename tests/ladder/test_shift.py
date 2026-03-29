"""Tests for laddercodec.instructions.shift."""

from __future__ import annotations

from laddercodec.instructions import Shift, parse_af_blob


class TestShiftBlobRoundTrip:
    def test_shift_basic(self) -> None:
        shift = Shift(start_bit="C99", end_bit="C106")
        parsed = parse_af_blob(shift.build_blob())
        assert isinstance(parsed, Shift)
        assert parsed == shift
        assert parsed.to_csv() == "shift(C99..C106)"

    def test_from_csv_token(self) -> None:
        shift = Shift.from_csv_token("shift(C99..C106)")
        assert shift.start_bit == "C99"
        assert shift.end_bit == "C106"
