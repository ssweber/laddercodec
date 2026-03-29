"""Tests for laddercodec.csv.bundle."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from laddercodec.csv.bundle import parse_bundle
from laddercodec.csv.contract import CONDITION_COLUMNS, CSV_HEADER


def _write_one_row_file(path: Path, marker: str = "R", af: str = "out(Y001)") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conditions = [""] * len(CONDITION_COLUMNS)
    conditions[0] = "X001"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        writer.writerow([marker, *conditions, af])


def test_main_csv_required(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing required main.csv"):
        parse_bundle(tmp_path)


def test_subroutines_in_subfolder(tmp_path: Path) -> None:
    _write_one_row_file(tmp_path / "main.csv")
    _write_one_row_file(tmp_path / "subroutines" / "zeta.csv", af="return()")
    _write_one_row_file(tmp_path / "subroutines" / "alpha.csv", af="return()")

    bundle = parse_bundle(tmp_path)
    assert bundle.main.path.name == "main.csv"
    assert [sub.path.name for sub in bundle.subroutines] == ["alpha.csv", "zeta.csv"]
    assert [sub.subroutine_slug for sub in bundle.subroutines] == ["alpha", "zeta"]


def test_no_subroutines_without_folder(tmp_path: Path) -> None:
    _write_one_row_file(tmp_path / "main.csv")

    bundle = parse_bundle(tmp_path)
    assert bundle.main.path.name == "main.csv"
    assert bundle.subroutines == ()
