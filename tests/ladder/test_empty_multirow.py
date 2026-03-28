"""Tests for deterministic empty multi-row synthesis."""

import pytest

from laddercodec.empty_multirow import (
    empty_multirow_payload_length,
    empty_multirow_row_word,
    synthesize_empty_multirow,
)
from laddercodec.topology import (
    COLS_PER_ROW,
    HEADER_ENTRY_BASE,
    HEADER_ENTRY_COUNT,
    HEADER_ENTRY_SIZE,
    cell_offset,
)


@pytest.mark.parametrize(
    ("rows", "expected_len", "expected_word"),
    [
        (1, 8192, 0x0040),
        (2, 8192, 0x0060),
        (3, 12288, 0x0080),
        (4, 12288, 0x00A0),
        (9, 24576, 0x0140),
        (17, 40960, 0x0240),
        (32, 69632, 0x0420),
    ],
)
def test_empty_multirow_length_and_row_word_formula(
    rows: int, expected_len: int, expected_word: int
) -> None:
    assert empty_multirow_payload_length(rows) == expected_len
    assert empty_multirow_row_word(rows) == expected_word


@pytest.mark.parametrize("rows", [0, 33])
def test_empty_multirow_rejects_out_of_range_rows(rows: int) -> None:
    with pytest.raises(ValueError, match="logical_rows must be in"):
        _ = empty_multirow_payload_length(rows)
    with pytest.raises(ValueError, match="logical_rows must be in"):
        _ = synthesize_empty_multirow(rows)


def _assert_active_cell_rules(data: bytes, *, logical_rows: int) -> None:
    for row in range(logical_rows):
        is_terminal = row == logical_rows - 1
        for col in range(COLS_PER_ROW):
            start = cell_offset(row, col)
            assert data[start + 0x01] == col
            assert data[start + 0x05] == row + 1
            assert data[start + 0x09] == 0x01
            assert data[start + 0x0A] == 0x01
            assert data[start + 0x0C] == 0x01
            assert data[start + 0x0D] == 0xFF
            assert data[start + 0x0E] == 0xFF
            assert data[start + 0x0F] == 0xFF
            assert data[start + 0x10] == 0xFF
            assert data[start + 0x11] == 0x01
            assert data[start + 0x38] == (0x00 if (is_terminal and col == 31) else 0x01)
            if is_terminal and col == 31:
                assert data[start + 0x3D] == 0x00
            elif col == 31:
                assert data[start + 0x3D] == row + 2
            else:
                assert data[start + 0x3D] == row + 1


@pytest.mark.parametrize("rows", [4, 9, 17, 32])
def test_synthesize_empty_multirow_writes_row_word_header_and_cell_formulas(rows: int) -> None:
    payload = synthesize_empty_multirow(rows)

    assert len(payload) == empty_multirow_payload_length(rows)

    # Verify header row word directly
    row_word = payload[HEADER_ENTRY_BASE] | (payload[HEADER_ENTRY_BASE + 1] << 8)
    assert row_word == empty_multirow_row_word(rows)

    for col in range(HEADER_ENTRY_COUNT):
        entry_start = HEADER_ENTRY_BASE + col * HEADER_ENTRY_SIZE
        assert payload[entry_start + 0x05] == 0x00
    assert payload[0x0A59] == 0x00

    _assert_active_cell_rules(payload, logical_rows=rows)
