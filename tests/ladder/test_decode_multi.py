"""Golden round-trip tests and validation tests for decode_rungs().

For each multi-rung golden .bin fixture (mr-*.csv), decodes the binary and
compares the result against the CSV-derived data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec import decode, read_csv
from laddercodec.decode import DecodeError, decode_rungs
from laddercodec.encode import encode_rung
from laddercodec.encode_multi import encode_rungs
from tests.golden_io import GOLDEN_DIR

# -- Golden CSV/BIN decode round-trip tests --

_MULTI_GOLDEN_CSVS = sorted(GOLDEN_DIR.glob("mr-*.csv"))


@pytest.mark.parametrize("csv_path", _MULTI_GOLDEN_CSVS, ids=[p.stem for p in _MULTI_GOLDEN_CSVS])
def test_golden_decode_multi(csv_path: Path) -> None:
    rung_items = read_csv(csv_path)
    bin_path = csv_path.with_suffix(".bin")
    assert bin_path.exists(), f"Missing golden .bin: {bin_path.name}"
    data = bin_path.read_bytes()

    result = decode(data)

    assert len(result) == len(rung_items)
    for decoded, expected in zip(result, rung_items, strict=True):
        assert decoded.logical_rows == expected.logical_rows
        assert decoded.conditions == expected.conditions
        assert decoded.instructions == expected.instructions
        assert decoded.comment == expected.comment


# -- Encode -> decode round-trip tests --


def test_encode_decode_multi_roundtrip_empty() -> None:
    rungs = [(1, [[""] * 31], [""]), (1, [[""] * 31], [""])]
    data = encode_rungs(rungs)
    result = decode(data)
    assert len(result) == 2
    for d in result:
        assert d.logical_rows == 1
        assert d.conditions == [[""] * 31]
        assert d.instructions == [""]
        assert d.comment is None


def test_encode_decode_multi_roundtrip_comments() -> None:
    rungs = [(1, [[""] * 31], [""]), (1, [[""] * 31], [""])]
    comments = ["First", "**Second**"]
    data = encode_rungs(rungs, comments=comments)
    result = decode(data)
    assert result[0].comment == "First"
    assert result[1].comment == "**Second**"


def test_encode_decode_multi_roundtrip_mixed() -> None:
    rungs = [
        (1, [["-"] * 31], ["NOP"]),
        (2, [["-"] * 31, [""] * 31], ["", ""]),
    ]
    comments = ["Rung 0", None]
    data = encode_rungs(rungs, comments=comments)
    result = decode(data)
    assert len(result) == 2
    assert result[0].logical_rows == 1
    assert result[0].instructions == ["NOP"]
    assert result[0].comment == "Rung 0"
    assert result[1].logical_rows == 2
    assert result[1].comment is None


# -- Validation / error tests --


def test_decode_multi_rejects_single_rung() -> None:
    single_bin = encode_rung(1, [[""] * 31], [""])
    with pytest.raises(DecodeError, match="single rung"):
        decode_rungs(single_bin)
