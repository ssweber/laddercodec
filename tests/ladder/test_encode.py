"""Byte-exact golden-file tests for encode_rung().

Each golden fixture is a CSV/BIN pair in tests/fixtures/ladder_captures/golden/.
The CSV defines the canonical rung layout (source of truth); the BIN is the
expected encode_rung() output, verified through Click paste round-trip.

Regenerate BIN files:  uv run python devtools/generate_golden.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec.encode import encode_rung
from tests.golden_io import GOLDEN_DIR, read_golden_csv

# -- Golden CSV/BIN round-trip tests --

_GOLDEN_CSVS = sorted(GOLDEN_DIR.glob("*.csv"))


@pytest.mark.parametrize("csv_path", _GOLDEN_CSVS, ids=[p.stem for p in _GOLDEN_CSVS])
def test_golden_encode(csv_path: Path) -> None:
    logical_rows, condition_rows, af_tokens, comment = read_golden_csv(csv_path)
    result = encode_rung(logical_rows, condition_rows, af_tokens, comment=comment)
    bin_path = csv_path.with_suffix(".bin")
    assert bin_path.exists(), f"Missing golden .bin: {bin_path.name}"
    expected = bin_path.read_bytes()
    assert result == expected, f"Golden file mismatch: {csv_path.stem}"


# -- Validation edge cases --


def _empty(n: int = 31) -> list[str]:
    return [""] * n


def test_encode_rung_rejects_multiple_nops() -> None:
    with pytest.raises(ValueError, match="Only one NOP"):
        encode_rung(2, [_empty(), _empty()], ["NOP", "NOP"])


def test_encode_rung_rejects_vertical_col_a() -> None:
    row = _empty()
    row[0] = "|"
    with pytest.raises(ValueError, match="column A"):
        encode_rung(2, [row, _empty()], ["", ""])


def test_encode_rung_rejects_vertical_last_row() -> None:
    row = _empty()
    row[1] = "|"
    with pytest.raises(ValueError, match="last row"):
        encode_rung(1, [row], [""])


def test_encode_rung_rejects_comment_overflow_2row() -> None:
    with pytest.raises(ValueError, match="too long"):
        encode_rung(2, [_empty(), _empty()], ["", ""], comment="X" * 1400)


def test_encode_rung_rejects_out_of_range_rows() -> None:
    with pytest.raises(ValueError, match="logical_rows"):
        encode_rung(0, [], [])
    with pytest.raises(ValueError, match="logical_rows"):
        encode_rung(33, [_empty() for _ in range(33)], [""] * 33)


def test_encode_rung_buffer_sizes() -> None:
    """Verify buffer sizing formula across key row counts."""
    cases = [
        (1, 0x2000),
        (2, 0x2000),
        (3, 0x3000),
        (4, 0x3000),
        (5, 0x4000),
        (9, 0x6000),
        (17, 0xA000),
        (32, 0x11000),
    ]
    for rows, expected_size in cases:
        result = encode_rung(rows, [_empty() for _ in range(rows)], [""] * rows)
        assert len(result) == expected_size, (
            f"rows={rows}: expected {expected_size}, got {len(result)}"
        )
