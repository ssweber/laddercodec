"""Byte-exact golden-file tests and validation tests for encode_rungs().

Golden fixtures are multi-rung CSV/BIN pairs in tests/fixtures/ladder_captures/golden/
named mr-*.csv. Each CSV uses multiple R markers (one per rung). The BIN is the
expected encode_rungs() output, verified through Click paste round-trip.

Regenerate BIN files:  make golden
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from laddercodec import decode, encode, read_csv
from laddercodec.decode import _DATA, _walk_grid, _walk_row_cells
from laddercodec.encode_multi import encode_rungs
from laddercodec.topology import (
    CELL_SIZE,
    COLS_PER_ROW,
    GRID_FIRST_ROW_START,
    PROGRAM_HEADER_BASE,
)
from tests.golden_io import GOLDEN_DIR

# -- Golden CSV/BIN round-trip tests --

_MULTI_GOLDEN_CSVS = sorted(GOLDEN_DIR.glob("mr-*.csv"))


@pytest.mark.parametrize("csv_path", _MULTI_GOLDEN_CSVS, ids=[p.stem for p in _MULTI_GOLDEN_CSVS])
def test_golden_multi_rung(csv_path: Path) -> None:
    rung_items = read_csv(csv_path)
    result = encode(rung_items)
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
    result = encode_rungs([(1, [_empty()], [""]), (1, [_empty()], [""])])
    assert len(result) > 0


def test_multi_rung_wire_rung0() -> None:
    row = ["-"] + [""] * 30
    result = encode_rungs([(1, [row], [""]), (1, [_empty()], [""])])
    assert len(result) > 0


def test_multi_rung_fullwire_rung1() -> None:
    result = encode_rungs([(1, [_empty()], [""]), (1, [_wire()], [""])])
    assert len(result) > 0


def test_multi_rung_t_junction() -> None:
    row = ["-", "T"] + ["-"] * 29
    recv = ["", "-"] + [""] * 29
    result = encode_rungs(
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
    result = encode_rungs(
        [
            (3, [row_t, row_v, row_w], ["", "", ""]),
            (1, [_empty()], [""]),
        ]
    )
    assert len(result) > 0


def test_multi_rung_nop_each_rung() -> None:
    result = encode_rungs(
        [
            (1, [_empty()], ["NOP"]),
            (1, [_empty()], ["NOP"]),
        ]
    )
    assert len(result) > 0


def test_multi_rung_nop_non_first_row() -> None:
    """NOP on row 1 of a 2-row rung requires col0 +0x15 = 1."""
    result = encode_rungs(
        [
            (2, [_empty(), _empty()], ["", "NOP"]),
            (1, [_empty()], [""]),
        ]
    )
    assert len(result) > 0


def test_multi_rung_three_rungs() -> None:
    result = encode_rungs(
        [
            (1, [_empty()], [""]),
            (1, [_wire()], ["NOP"]),
            (1, [_empty()], [""]),
        ]
    )
    assert len(result) > 0


def test_multi_rung_mixed_row_counts() -> None:
    """Rungs with different row counts in the same buffer."""
    result = encode_rungs(
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
    result = encode_rungs([(1, [_empty()], [""]), (1, [_empty()], [""])])
    # 4 grid rows: raw = 0x0A60 + 4 * 0x800 = 0x2A60 -> next page = 0x3000
    assert len(result) == 0x3000


def test_multi_rung_buffer_size_three_1row() -> None:
    """Three 1-row rungs: 3 rung rows + 2 sep + 1 terminal = 6 grid rows."""
    result = encode_rungs(
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
        encode_rungs([(1, [_empty()], [""])])


def test_multi_rung_rejects_zero_rungs() -> None:
    with pytest.raises(ValueError, match="at least 2 rungs"):
        encode_rungs([])


def test_multi_rung_rejects_vertical_col_a() -> None:
    row = _empty()
    row[0] = "|"
    with pytest.raises(ValueError, match="column A"):
        encode_rungs(
            [
                (2, [row, _empty()], ["", ""]),
                (1, [_empty()], [""]),
            ]
        )


def test_multi_rung_rejects_vertical_last_row() -> None:
    row = _empty()
    row[1] = "|"
    with pytest.raises(ValueError, match="last row"):
        encode_rungs(
            [
                (1, [row], [""]),
                (1, [_empty()], [""]),
            ]
        )


def test_multi_rung_rejects_out_of_range_rows() -> None:
    with pytest.raises(ValueError, match="logical_rows"):
        encode_rungs(
            [
                (0, [], []),
                (1, [_empty()], [""]),
            ]
        )
    with pytest.raises(ValueError, match="logical_rows"):
        encode_rungs(
            [
                (33, [_empty() for _ in range(33)], [""] * 33),
                (1, [_empty()], [""]),
            ]
        )


# -- Past 256 rungs: CLICK's own copy of 266 rungs --

_NATIVE_266 = GOLDEN_DIR.parents[1] / "scr_captures" / "rungs_266"


def _row_fields(data: bytes) -> list[list[tuple[bytes, bytes]]]:
    """Each row's cells as (row number field, 16-byte tail)."""
    rows, _ = _walk_grid(data, GRID_FIRST_ROW_START, 600)
    fields = []
    for kind, cursor, _ in rows:
        if kind == _DATA:
            bounds = [(start, end) for start, end, _ in _walk_row_cells(data, cursor)]
        else:
            bounds = [
                (cursor + col * CELL_SIZE, cursor + (col + 1) * CELL_SIZE)
                for col in range(COLS_PER_ROW)
            ]
        fields.append([(data[a + 0x05 : a + 0x09], data[b - 0x10 : b]) for a, b in bounds])
    return fields


def test_rung_and_row_fields_match_native_past_256_rungs() -> None:
    native = gzip.decompress(_NATIVE_266.with_suffix(".bin.gz").read_bytes())
    rungs = read_csv(_NATIVE_266.with_suffix(".csv"))
    assert len(rungs) == 266

    ours, theirs = _row_fields(encode(rungs)), _row_fields(native)
    assert len(ours) == len(theirs) == 532
    # The last AF cell's end is not comparable: CLICK follows it with a table of its own.
    ours[-1].pop()
    theirs[-1].pop()
    assert ours == theirs


def test_native_past_256_rungs_decodes_to_its_csv() -> None:
    native = decode(gzip.decompress(_NATIVE_266.with_suffix(".bin.gz").read_bytes()))
    rungs = read_csv(_NATIVE_266.with_suffix(".csv"))
    assert isinstance(native, list)
    assert [(r.conditions, r.instructions) for r in native] == [
        (r.conditions, r.instructions) for r in rungs
    ]


@pytest.mark.parametrize("count", [255, 256, 257, 258])
def test_rung_counts_around_256_round_trip(count: int) -> None:
    rungs = [(1, [["-"] * 31], ["NOP"])] * count
    result = decode(encode_rungs(rungs))
    assert isinstance(result, list)
    assert len(result) == count
    assert all(r.instructions == ["NOP"] for r in result)


def test_comment_past_256_rungs_round_trips() -> None:
    rungs = [(1, [_empty()], [""])] * 260
    comments = [f"rung {i}" if i in (255, 256, 259) else None for i in range(260)]
    result = decode(encode_rungs(rungs, comments=comments))
    assert isinstance(result, list)
    assert [(i, r.comment) for i, r in enumerate(result) if r.comment] == [
        (255, "rung 255"),
        (256, "rung 256"),
        (259, "rung 259"),
    ]


def test_row_word_carries_past_16_bits() -> None:
    # CLICK's copy of 1049 rungs and 2938 grid rows reads 40 6F 01 00 here.
    count = 1100
    data = encode_rungs([(1, [_empty()], [""])] * count)
    assert data[PROGRAM_HEADER_BASE : PROGRAM_HEADER_BASE + 4] == (count * 2 * 0x20).to_bytes(
        4, "little"
    )
    result = decode(data)
    assert isinstance(result, list)
    assert len(result) == count
