"""Tests for ``csv_rows``: the rows that ``write_csv`` writes after the header."""

from __future__ import annotations

import csv
import gzip
import re
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from laddercodec import (
    CSV_HEADER,
    Coil,
    Contact,
    CsvWriteError,
    Program,
    Project,
    Rung,
    UndecodedRungWarning,
    UnknownInstruction,
    csv_rows,
    decode,
    decode_program,
    read_csv,
    write_bundle,
    write_csv,
)
from laddercodec.instructions import Shift

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

#: One file from each fixture folder that the suite decodes, reads or writes back as CSV.
#: The golden CSV and the golden .bin each hold a comment of two or more lines.
#: ``windy_road_pasted.bin`` decodes to an ``undecoded(...)`` marker.
FIXTURE_FILES = (
    "ladder_captures/golden/cmt-1row-styled-mixed.csv",
    "ladder_captures/golden/instr-coil-timer-ret.bin",
    "coverage/golden/blockcopy__block.bin",
    "v4_captures/windy_road_pasted.bin",
    "tumbler/subroutines/AckAlarm.scr",
    "scr_captures/counter_scr.scr",
)


def _load(path: Path) -> list[Rung]:
    """Return the rungs of the fixture at *path*: decoded, decoded as a program, or read."""
    if path.suffix == ".csv":
        return read_csv(path)
    data = path.read_bytes()
    if path.name.endswith(".gz"):
        data = gzip.decompress(data)
    if path.suffix in (".scr", ".tmp"):
        return list(decode_program(data).rungs)
    return decode(data)


def _file_rows(path: Path) -> list[list[str]]:
    """Return the rows of the CSV file at *path*."""
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def _run(call: Callable[..., object], *args: Any, **kwargs: Any) -> tuple[object, list[str]]:
    """Call *call* with the arguments given.

    Return what it returns or the ``CsvWriteError`` it raises, and the warnings that it emits,
    as text.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            result: object = call(*args, **kwargs)
        except CsvWriteError as exc:
            result = exc
    return result, [f"{w.category.__name__}: {w.message}" for w in caught]


def _row(contact: str, coil: str) -> tuple[list[object], Coil]:
    """Return one row with a contact on *contact* wired to an out coil on *coil*."""
    return [Contact(contact), *["-"] * 30], Coil(coil)


def _split_rung() -> Rung:
    """Return a rung whose two outputs meet only at the rail, so CLICK splits it in two."""
    first, second = _row("C1", "Y1"), _row("C2", "Y2")
    return Rung(
        conditions=[first[0], second[0]],
        instructions=[first[1], second[1]],
        comment="two circuits",
    )


def _unknown_rung() -> Rung:
    """Return a rung whose output no CSV token can hold."""
    conditions, _ = _row("C1", "Y1")
    return Rung(
        conditions=[conditions], instructions=[UnknownInstruction(raw=b"\x01")], comment=None
    )


@pytest.mark.parametrize("name", FIXTURE_FILES)
def test_rows_match_the_file_that_write_csv_writes(name: str, tmp_path: Path) -> None:
    """For each fixture, the file has the rows ``[list(CSV_HEADER), *csv_rows(rungs)]``.

    Both functions emit the same warnings.
    """
    rungs, _ = _run(_load, FIXTURES / name)
    assert isinstance(rungs, list)
    for index in (False, True):
        out = tmp_path / f"index_{index}.csv"
        written, written_warnings = _run(write_csv, out, rungs, index=index)
        rows, rows_warnings = _run(csv_rows, rungs, index=index)
        assert written is None
        assert rows_warnings == written_warnings
        assert _file_rows(out) == [list(CSV_HEADER), *rows]


def test_the_fixtures_hold_a_long_comment_and_a_marker() -> None:
    """Some file in ``FIXTURE_FILES`` writes a comment of two or more lines, and some file
    writes an ``undecoded(...)`` token."""
    rows = [_quiet_rows(name) for name in FIXTURE_FILES]
    markers = [[row[0] for row in file_rows] for file_rows in rows]
    assert any(a == b == "#" for marks in markers for a, b in zip(marks, marks[1:], strict=False))
    assert any(row[-1].startswith("undecoded(") for file_rows in rows for row in file_rows)


def _quiet_rows(name: str) -> list[list[str]]:
    """Return ``csv_rows`` of the fixture *name*, ignoring the warnings that its decode emits."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return csv_rows(_load(FIXTURES / name))


def test_rows_of_a_marker_match_the_file_with_stop_return(tmp_path: Path) -> None:
    """With ``stop="return"``, the marker rung for an unknown token matches the file."""
    rungs = [_split_rung(), _unknown_rung()]
    with pytest.warns(UndecodedRungWarning):
        write_csv(tmp_path / "m.csv", rungs, index=True, stop="return")
    with pytest.warns(UndecodedRungWarning):
        rows = csv_rows(rungs, index=True, stop="return")
    assert _file_rows(tmp_path / "m.csv") == [list(CSV_HEADER), *rows]
    assert rows[-1][-1] == 'undecoded("no CSV token holds this unknown instruction (1 bytes)",' + (
        "rung=1,row=0,column=31,stop=return)"
    )


def test_a_split_rung_gets_one_numbered_r_row_per_part() -> None:
    """A rung that CLICK splits gives one ``R`` row per part, numbered across the call."""
    rows = csv_rows([_split_rung(), _split_rung()], index=True)
    assert [row[0] for row in rows] == ["#", "R1", "R2", "#", "R3", "R4"]
    assert [row[-1] for row in rows if row[0] != "#"] == ["out(Y001)", "out(Y002)"] * 2
    assert [row[0] for row in csv_rows([_split_rung()])] == ["#", "R", "R"]


def test_rows_are_lists_of_str() -> None:
    """A data row has 33 cells and a comment row has two, all of them str."""
    rows = csv_rows([_split_rung()])
    assert rows[0] == ["#", "two circuits"]
    assert all(len(row) == len(CSV_HEADER) for row in rows[1:])
    assert all(type(cell) is str for row in rows for cell in row)


def test_csv_header_is_a_tuple_of_str() -> None:
    assert isinstance(CSV_HEADER, tuple)
    assert CSV_HEADER[0] == "marker"
    assert CSV_HEADER[-1] == "AF"
    assert len(CSV_HEADER) == 33
    assert all(type(name) is str for name in CSV_HEADER)


def test_both_accept_any_iterable(tmp_path: Path) -> None:
    rungs = [_split_rung(), _split_rung()]
    assert csv_rows(iter(rungs)) == csv_rows(rungs)
    write_csv(tmp_path / "m.csv", (rung for rung in rungs))
    assert _file_rows(tmp_path / "m.csv") == [list(CSV_HEADER), *csv_rows(rungs)]


@pytest.mark.parametrize("name", ["csv_rows", "write_csv"])
def test_a_bad_stop_raises_writer_error(name: str, tmp_path: Path) -> None:
    """Each function names itself in the message, and ``write_csv`` makes no file."""
    path = tmp_path / "m.csv"
    calls = {
        "csv_rows": lambda: csv_rows([_split_rung()], stop="halt"),  # type: ignore[arg-type]
        "write_csv": lambda: write_csv(path, [_split_rung()], stop="halt"),  # type: ignore[arg-type]
    }
    with pytest.raises(
        CsvWriteError, match=rf"^{name}: stop='halt' must be 'end' or 'return'$"
    ) as e:
        calls[name]()
    assert e.value.code is None
    assert e.value.click_id is None
    assert not path.exists()


def _unwritable_rung() -> Rung:
    """Return a rung that the CSV can't hold: a three-row Shift in a two-row rung."""
    blank = [""] * 31
    return Rung(conditions=[blank, blank], instructions=[Shift("C99", "C106"), ""], comment=None)


def test_a_writer_error_leaves_no_file(tmp_path: Path) -> None:
    """The rung that fails comes after one that can be written, and no file is made."""
    path = tmp_path / "m.csv"
    with pytest.raises(CsvWriteError, match="is 3 rows tall, but the rung has only 2 rows") as e:
        write_csv(path, [_split_rung(), _unwritable_rung()])
    assert e.value.code is None
    assert e.value.click_id is None
    assert not path.exists()
    with pytest.raises(CsvWriteError, match="is 3 rows tall, but the rung has only 2 rows"):
        csv_rows([_split_rung(), _unwritable_rung()])


def test_a_writer_error_leaves_an_existing_file_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "m.csv"
    path.write_bytes(b"kept\r\n")
    with pytest.raises(CsvWriteError):
        write_csv(path, [_split_rung(), _unwritable_rung()])
    assert path.read_bytes() == b"kept\r\n"


@pytest.mark.parametrize("name", ["csv_rows", "write_csv"])
def test_the_undecoded_warning_points_at_the_caller(name: str, tmp_path: Path) -> None:
    calls = {
        "csv_rows": lambda: csv_rows([_unknown_rung()]),
        "write_csv": lambda: write_csv(tmp_path / "m.csv", [_unknown_rung()]),
    }
    with pytest.warns(UndecodedRungWarning) as caught:
        calls[name]()
    (warning,) = caught
    assert Path(warning.filename) == Path(__file__)


@pytest.mark.parametrize("width", [3, 40])
@pytest.mark.parametrize("name", ["csv_rows", "write_csv", "write_bundle"])
def test_a_row_of_the_wrong_width_raises_writer_error(
    name: str, width: int, tmp_path: Path
) -> None:
    """The message names the rung, the row and its number of cells, and no file is made."""
    bad = Rung([["-"] * 31, ["-"] * width], [Coil("Y1"), Coil("Y2")], None)
    rungs = [_split_rung(), bad]
    path = tmp_path / ("bundle" if name == "write_bundle" else "m.csv")
    calls = {
        "csv_rows": lambda: csv_rows(rungs),
        "write_csv": lambda: write_csv(path, rungs),
        "write_bundle": lambda: write_bundle(path, Project(Program("Main Program", 1, rungs))),
    }
    start = "Main program: " if name == "write_bundle" else ""
    want = f"{start}rungs[1]: Row 1: expected 31 columns, got {width}. "
    with pytest.raises(CsvWriteError, match=f"^{re.escape(want)}"):
        calls[name]()
    assert not path.exists()
