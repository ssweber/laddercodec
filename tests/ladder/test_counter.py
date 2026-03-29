"""Tests for laddercodec.instructions.counter."""

from __future__ import annotations

import pytest

from laddercodec.instructions import Counter, parse_af_blob


class TestCounterBlobRoundTrip:
    def test_count_up_reset(self) -> None:
        counter = Counter(
            counter_type="count_up",
            done_bit="CT1",
            current="CTD1",
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
            counter_type="count_up",
            done_bit="CT2",
            current="CTD2",
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
            counter_type="count_down",
            done_bit="CT3",
            current="CTD3",
            preset="50",
            down_enabled=False,
            reset_enabled=True,
        )
        parsed = parse_af_blob(counter.build_blob())
        assert isinstance(parsed, Counter)
        assert parsed == counter
        assert parsed.to_csv() == "count_down(CT3,CTD3,preset=50)"

    def test_reject_unsupported_variant(self) -> None:
        counter = Counter(
            counter_type="count_up",
            done_bit="CT4",
            current="CTD4",
            preset="100",
            down_enabled=False,
            reset_enabled=False,
        )
        with pytest.raises(ValueError, match="Unsupported counter variant"):
            counter.build_blob()
