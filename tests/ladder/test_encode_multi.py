"""Byte-exact golden-file tests and validation tests for encode_multi_rung().

Golden fixtures are multi-rung CSV/BIN pairs in tests/fixtures/ladder_captures/golden/
named mr-*.csv. Each CSV uses multiple R markers (one per rung). The BIN is the
expected encode_multi_rung() output, verified through Click paste round-trip.

Regenerate BIN files:  uv run python devtools/generate_golden.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec import encode_multi_rung
from tests.golden_io import GOLDEN_DIR, read_multi_rung_golden_csv

# -- Golden CSV/BIN round-trip tests --

_MULTI_GOLDEN_CSVS = sorted(GOLDEN_DIR.glob("mr-*.csv"))


@pytest.mark.parametrize("csv_path", _MULTI_GOLDEN_CSVS, ids=[p.stem for p in _MULTI_GOLDEN_CSVS])
def test_golden_multi_rung(csv_path: Path) -> None:
    rung_items = read_multi_rung_golden_csv(csv_path)
    result = encode_multi_rung(
        [(lr, cr, af) for lr, cr, af, _ in rung_items],
        comments=[cmt for _, _, _, cmt in rung_items],
    )
    bin_path = csv_path.with_suffix(".bin")
    assert bin_path.exists(), f"Missing golden .bin: {bin_path.name}"
    expected = bin_path.read_bytes()
    assert result == expected, f"Golden file mismatch: {csv_path.stem}"


# -- Helpers --


def _empty(n: int = 31) -> list[str]:
    return [""] * n


def _wire(n: int = 31) -> list[str]:
    return ["-"] * n


# -- Wire topology tests --


def test_multi_rung_two_empty() -> None:
    result = encode_multi_rung([(1, [_empty()], [""]), (1, [_empty()], [""])])
    assert len(result) > 0


def test_multi_rung_wire_rung0() -> None:
    row = ["-"] + [""] * 30
    result = encode_multi_rung([(1, [row], [""]), (1, [_empty()], [""])])
    assert len(result) > 0


def test_multi_rung_fullwire_rung1() -> None:
    result = encode_multi_rung([(1, [_empty()], [""]), (1, [_wire()], [""])])
    assert len(result) > 0


def test_multi_rung_t_junction() -> None:
    row = ["-", "T"] + ["-"] * 29
    recv = ["", "-"] + [""] * 29
    result = encode_multi_rung(
        [
            (2, [row, recv], ["", ""]),
            (1, [_empty()], [""]),
        ]
    )
    assert len(result) > 0


def test_multi_rung_vertical_chain() -> None:
    row_t = ["-", "T"] + [""] * 29
    row_v = ["", "|"] + [""] * 29
    row_w = ["", "-"] + [""] * 29
    result = encode_multi_rung(
        [
            (3, [row_t, row_v, row_w], ["", "", ""]),
            (1, [_empty()], [""]),
        ]
    )
    assert len(result) > 0


def test_multi_rung_nop_each_rung() -> None:
    result = encode_multi_rung(
        [
            (1, [_empty()], ["NOP"]),
            (1, [_empty()], ["NOP"]),
        ]
    )
    assert len(result) > 0


def test_multi_rung_nop_non_first_row() -> None:
    """NOP on row 1 of a 2-row rung requires col0 +0x15 = 1."""
    result = encode_multi_rung(
        [
            (2, [_empty(), _empty()], ["", "NOP"]),
            (1, [_empty()], [""]),
        ]
    )
    assert len(result) > 0


def test_multi_rung_three_rungs() -> None:
    result = encode_multi_rung(
        [
            (1, [_empty()], [""]),
            (1, [_wire()], ["NOP"]),
            (1, [_empty()], [""]),
        ]
    )
    assert len(result) > 0


def test_multi_rung_mixed_row_counts() -> None:
    """Rungs with different row counts in the same buffer."""
    result = encode_multi_rung(
        [
            (1, [_wire()], [""]),
            (2, [_wire(), _empty()], ["", ""]),
            (1, [_empty()], ["NOP"]),
        ]
    )
    assert len(result) > 0


# -- Buffer size tests --


def test_multi_rung_buffer_size_two_1row() -> None:
    """Two 1-row rungs: 2 rung rows + 1 sep + 1 terminal = 4 grid rows."""
    result = encode_multi_rung([(1, [_empty()], [""]), (1, [_empty()], [""])])
    # 4 grid rows: raw = 0x0A60 + 4 * 0x800 = 0x2A60 -> next page = 0x3000
    assert len(result) == 0x3000


def test_multi_rung_buffer_size_three_1row() -> None:
    """Three 1-row rungs: 3 rung rows + 2 sep + 1 terminal = 6 grid rows."""
    result = encode_multi_rung(
        [
            (1, [_empty()], [""]),
            (1, [_empty()], [""]),
            (1, [_empty()], [""]),
        ]
    )
    # 6 grid rows: raw = 0x0A60 + 6 * 0x800 = 0x3A60 -> next page = 0x4000
    assert len(result) == 0x4000


# -- Validation tests --


def test_multi_rung_rejects_one_rung() -> None:
    with pytest.raises(ValueError, match="at least 2 rungs"):
        encode_multi_rung([(1, [_empty()], [""])])


def test_multi_rung_rejects_zero_rungs() -> None:
    with pytest.raises(ValueError, match="at least 2 rungs"):
        encode_multi_rung([])


def test_multi_rung_rejects_vertical_col_a() -> None:
    row = _empty()
    row[0] = "|"
    with pytest.raises(ValueError, match="column A"):
        encode_multi_rung(
            [
                (2, [row, _empty()], ["", ""]),
                (1, [_empty()], [""]),
            ]
        )


def test_multi_rung_rejects_vertical_last_row() -> None:
    row = _empty()
    row[1] = "|"
    with pytest.raises(ValueError, match="last row"):
        encode_multi_rung(
            [
                (1, [row], [""]),
                (1, [_empty()], [""]),
            ]
        )


def test_multi_rung_rejects_out_of_range_rows() -> None:
    with pytest.raises(ValueError, match="logical_rows"):
        encode_multi_rung(
            [
                (0, [], []),
                (1, [_empty()], [""]),
            ]
        )
    with pytest.raises(ValueError, match="logical_rows"):
        encode_multi_rung(
            [
                (33, [_empty() for _ in range(33)], [""] * 33),
                (1, [_empty()], [""]),
            ]
        )
