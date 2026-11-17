"""Tests for laddercodec.instructions.counter."""

from __future__ import annotations

from laddercodec.instructions import Counter, parse_af_blob


class TestCounterBlobRoundTrip:
    def test_count_up_reset(self) -> None:
        counter = Counter(
            kind="count_up",
            done="CT1",
            accumulator="CTD1",
            preset="100",
            down_enabled=False,
            reset_enabled=True,
        )
        parsed = parse_af_blob(counter.build_blob())
        assert isinstance(parsed, Counter)
        assert parsed == counter
        assert parsed.to_csv() == "count_up(CT1,CTD1,preset=100)"

    def test_count_up_down_reset(self) -> None:
        counter = Counter(
            kind="count_up",
            done="CT2",
            accumulator="CTD2",
            preset="100",
            down_enabled=True,
            reset_enabled=True,
        )
        parsed = parse_af_blob(counter.build_blob())
        assert isinstance(parsed, Counter)
        assert parsed == counter
        assert parsed.to_csv() == "count_up(CT2,CTD2,preset=100)"

    def test_count_down_reset(self) -> None:
        counter = Counter(
            kind="count_down",
            done="CT3",
            accumulator="CTD3",
            preset="50",
            down_enabled=False,
            reset_enabled=True,
        )
        parsed = parse_af_blob(counter.build_blob())
        assert isinstance(parsed, Counter)
        assert parsed == counter
        assert parsed.to_csv() == "count_down(CT3,CTD3,preset=50)"
