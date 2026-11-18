"""A CLICK rung holds 1 to 32 rows, and every path that reads or writes a rung refuses more.

``read_csv`` and ``read_bundle`` raise ``CsvError``.  ``csv_rows``, ``write_csv`` and
``write_bundle`` raise ``WriterError``.  ``lay_out`` raises ``LayoutError``.  Each error has
the code ``layout-too-tall``.  ``check()`` reports the same code for a ``Rung`` that you
build.  Each case below is drawn at exactly 32 rows, which every path accepts, and at 33.
"""

from __future__ import annotations

import csv
import warnings
from collections.abc import Callable
from pathlib import Path

import pytest

import laddercodec._grid
import laddercodec.empty_multirow
from laddercodec import (
    CSV_HEADER,
    AfInstruction,
    Box,
    Branch,
    Circuit,
    Code,
    Coil,
    Contact,
    Copy,
    CsvError,
    CsvLocation,
    EncodeError,
    LayoutError,
    Parallel,
    Program,
    Project,
    Rung,
    Timer,
    WriterError,
    check,
    csv_rows,
    decode,
    encode,
    lay_out,
    read_bundle,
    read_csv,
    write_bundle,
    write_csv,
)
from laddercodec.csv.converter import convert_literal
from laddercodec.csv.parser import _parse_single_rung_rows

X1 = Contact("X001")
RETAINED = Timer("on_delay", "T1", "TD1", "100", "Tms", retained=True)
SEND = (
    'send(target=ModbusTcpTarget(name="tcp",ip="192.168.1.10",port=502,device_id=1),'
    'remote_start="C1",source=C11,sending=C1,success=C2,error=C3)'
)

#: The AF tokens of the boxes on one contact's net, for each case and row count.  A coil
#: spans 1 row, a Copy 2 and a Send 3.
BOXES: dict[str, Callable[[int], list[str]]] = {
    "coils": lambda rows: [f"out(C{n})" for n in range(1, rows + 1)],
    # 16 Copies fill 32 rows.  A coil after them makes 33.
    "copies": lambda rows: (
        [f"copy({n},DS{n})" for n in range(1, 17)] + [f"out(C{n})" for n in range(1, rows - 31)]
    ),
    # 10 Sends fill 30 rows.  Two coils make 32, and three make 33.
    "sends": lambda rows: [SEND] * 10 + [f"out(C{n})" for n in range(1, rows - 29)],
}
CASES = [*BOXES, "pin legs"]


def _row(marker: str, cells: list[str], af: str) -> list[str]:
    return [marker, *cells, *[""] * (31 - len(cells)), af]


def _box_rows(tokens: list[str]) -> list[list[str]]:
    """Return the CSV rows of one rung: ``X001`` feeds each box, one row per box.

    The reader pads each tall box to its height.
    """
    rows = []
    for index, token in enumerate(tokens):
        down = "T" if index < len(tokens) - 1 else "-"
        first = "X001" if index == 0 else ""
        rows.append(_row("R" if index == 0 else "", [first, down, *["-"] * 29], token))
    return rows


def _pin_rows(rows: int) -> list[list[str]]:
    """Return the CSV rows of a retentive timer whose reset has one OR leg per row below it."""
    legs = rows - 1
    out = [_row("R", ["X001", *["-"] * 30], RETAINED.to_csv())]
    for n in range(1, legs + 1):
        wire = "T" if n == 1 else ("|" if n < legs else "")
        right = ["-"] * 29 if n == 1 else []
        out.append(_row("", [f"C{n}", wire, *right], ".reset()" if n == 1 else ""))
    return out


def _rows(case: str, rows: int) -> list[list[str]]:
    return _pin_rows(rows) if case == "pin legs" else _box_rows(BOXES[case](rows))


def _drawn(case: str, rows: int) -> Rung:
    """Return the ``Rung`` of the case's rows as drawn, the way a caller can build it."""
    rung = convert_literal(_parse_single_rung_rows(_rows(case, rows)))
    assert rung.logical_rows == rows
    return rung


def _write(path: Path, rows: list[list[str]]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        writer.writerows(rows)
    return path


def _assert_too_tall(error: Exception, rows: int) -> None:
    assert f"needs {rows} rows, and a CLICK rung holds at most 32" in str(error)
    assert "Split it into rungs of 32 rows or fewer" in str(error)


# ---------------------------------------------------------------------------
# read_csv and read_bundle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strict", [True, False])
@pytest.mark.parametrize("case", CASES)
def test_read_csv_takes_32_rows(tmp_path: Path, case: str, strict: bool) -> None:
    (rung,) = read_csv(_write(tmp_path / "r.csv", _rows(case, 32)), strict=strict)
    assert rung.logical_rows == 32
    assert check(rung) == []


@pytest.mark.parametrize("strict", [True, False])
@pytest.mark.parametrize("case", CASES)
def test_read_csv_refuses_33_rows(tmp_path: Path, case: str, strict: bool) -> None:
    path = _write(tmp_path / "r.csv", [["#", "a comment"], *_rows(case, 33)])
    with pytest.raises(CsvError) as caught:
        read_csv(path, strict=strict)
    error = caught.value
    assert error.code is Code.LAYOUT_TOO_TALL
    assert error.click_id is None
    assert error.errors == (error,)
    _assert_too_tall(error, 33)
    assert str(error).startswith("The rung needs 33 rows")
    # The header is line 1 and the comment line 2, so the R row is line 3.
    assert CsvLocation.of(error) == CsvLocation(file=path, rung_line=3)
    assert str(error).endswith(f"(at {path}, rung at line 3)")
    assert isinstance(error.__cause__, LayoutError)
    assert error.__cause__.code is Code.LAYOUT_TOO_TALL


@pytest.mark.parametrize("where", ["main", "subroutine"])
@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("rows", [32, 33])
def test_read_bundle(tmp_path: Path, case: str, rows: int, where: str) -> None:
    (tmp_path / "subroutines").mkdir()
    main = tmp_path / "main.csv"
    sub = tmp_path / "subroutines" / "Sub.csv"
    tall, short = (main, sub) if where == "main" else (sub, main)
    _write(tall, _rows(case, rows))
    _write(short, _rows("coils", 1))
    if rows == 32:
        project = read_bundle(tmp_path)
        program = project.main if where == "main" else project.subroutines[0]
        (rung,) = program.rungs
        assert rung.logical_rows == 32
        return
    with pytest.raises(CsvError) as caught:
        read_bundle(tmp_path)
    assert caught.value.code is Code.LAYOUT_TOO_TALL
    assert CsvLocation.of(caught.value) == CsvLocation(file=tall, rung_line=2)


def test_17_copies_need_34_rows(tmp_path: Path) -> None:
    tokens = [f"copy({n},DS{n})" for n in range(1, 18)]
    with pytest.raises(CsvError, match="needs 34 rows"):
        read_csv(_write(tmp_path / "r.csv", _box_rows(tokens)))


def test_a_rung_that_clicks_splits_may_be_taller_than_32_rows(tmp_path: Path) -> None:
    """33 outputs that meet only at the rail are 33 CLICK rungs of one row each."""
    rows = [
        _row("R" if n == 1 else "", [f"C{n}", *["-"] * 30], f"out(C{n + 100})")
        for n in range(1, 34)
    ]
    rungs = read_csv(_write(tmp_path / "r.csv", rows))
    assert [r.logical_rows for r in rungs] == [1] * 33
    drawn = convert_literal(_parse_single_rung_rows(rows))
    assert drawn.logical_rows == 33
    assert [f.code for f in check(drawn)] == [Code.LAYOUT_TOO_TALL]
    assert csv_rows([drawn]) == csv_rows(rungs)


@pytest.mark.parametrize("k", [1, 2])
def test_a_rung_that_click_splits_is_refused_for_one_rung_of_33_rows(
    tmp_path: Path, k: int
) -> None:
    """The message names the rung that CLICK would split it into, not the rung as drawn."""
    tall = _box_rows(BOXES["coils"](33))
    short = [_row("", ["C9", *["-"] * 30], "out(C200)")]
    rows = [*tall, *short] if k == 1 else [*short, *tall]
    rows = [["R" if n == 0 else "", *row[1:]] for n, row in enumerate(rows)]
    with pytest.raises(CsvError) as caught:
        read_csv(_write(tmp_path / "r.csv", rows))
    assert caught.value.code is Code.LAYOUT_TOO_TALL
    rest = (
        f"into 2 rungs. Rung {k} of them needs 33 rows, and a CLICK rung holds at most 32. "
        "Split it into rungs of 32 rows or fewer. For example, move some of its outputs, "
        "with the contacts that feed them, to a rung of their own."
    )
    assert str(caught.value).startswith(f"CLICK splits the rung {rest}")
    drawn = convert_literal(_parse_single_rung_rows(rows))
    assert drawn.logical_rows == 34
    with pytest.raises(WriterError) as written:
        csv_rows([drawn])
    assert str(written.value) == f"CLICK splits rungs[0] {rest}"
    assert written.value.code is Code.LAYOUT_TOO_TALL


# ---------------------------------------------------------------------------
# check() and encode() on a Rung you build
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES)
def test_check_passes_32_rows(case: str) -> None:
    assert check(_drawn(case, 32)) == []


@pytest.mark.parametrize("case", CASES)
def test_check_reports_33_rows(case: str) -> None:
    rung = _drawn(case, 33)
    (finding,) = check([_drawn("coils", 1), rung])
    assert finding.rung == 1
    assert finding.code is Code.LAYOUT_TOO_TALL
    assert finding.click_id is None
    assert finding.captured is False
    assert (finding.row, finding.column) == (None, None)
    assert finding.message.startswith("the rung needs 33 rows")
    _assert_too_tall(Exception(finding.message), 33)
    with pytest.raises(EncodeError, match="This one has 33"):
        encode(rung)


def test_check_counts_the_rows_of_a_box_past_the_last_row() -> None:
    """A Copy on the last row of a 32-row rung spans a 33rd row."""
    conditions = [
        [X1, "T", *[""] * 29],
        *[["", "|", *[""] * 29]] * 30,
        ["", "-", *["-"] * 29],
    ]
    rung = Rung(conditions, [""] * 31 + [Copy("1", "DS1")], None)
    assert [f.code for f in check(rung)] == [Code.LAYOUT_TOO_TALL]
    assert "needs 33 rows" in check(rung)[0].message


# ---------------------------------------------------------------------------
# csv_rows, write_csv and write_bundle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES)
def test_writers_take_32_rows(tmp_path: Path, case: str) -> None:
    rung = _drawn(case, 32)
    rows = csv_rows([rung])
    write_csv(tmp_path / "r.csv", [rung])
    write_bundle(tmp_path / "b", Project(Program("Main Program", 1, [rung]), []))
    (back,) = read_csv(tmp_path / "r.csv")
    assert back.logical_rows == 32
    assert csv_rows([back]) == rows
    assert read_bundle(tmp_path / "b").main.rungs == [back]


def _writer_error(write: Callable[[], object]) -> WriterError:
    with pytest.raises(WriterError) as caught:
        write()
    error = caught.value
    assert error.code is Code.LAYOUT_TOO_TALL
    assert error.click_id is None
    assert isinstance(error.__cause__, LayoutError)
    assert error.__cause__.code is Code.LAYOUT_TOO_TALL
    _assert_too_tall(error, 33)
    return error


@pytest.mark.parametrize("case", CASES)
def test_writers_refuse_33_rows(tmp_path: Path, case: str) -> None:
    rungs = [_drawn("coils", 1), _drawn(case, 33)]
    error = _writer_error(lambda: csv_rows(rungs))
    assert str(error).startswith("rungs[1] needs 33 rows")

    path = tmp_path / "r.csv"
    error = _writer_error(lambda: write_csv(path, rungs))
    assert str(error).startswith("rungs[1] needs 33 rows")
    assert not path.exists()

    folder = tmp_path / "b"
    sub = Program("Pump", 2, rungs)
    project = Project(Program("Main Program", 1, [_drawn("coils", 1)]), [sub])
    error = _writer_error(lambda: write_bundle(folder, project))
    assert str(error).startswith("Subroutine 'Pump': rungs[1] needs 33 rows")
    assert not folder.exists()


# ---------------------------------------------------------------------------
# lay_out
# ---------------------------------------------------------------------------


def _boxes(case: str, rows: int) -> tuple[Box, ...]:
    if case == "pin legs":
        legs = tuple(Contact(f"C{n}") for n in range(1, rows))
        return (Box(RETAINED, {".reset": Parallel(legs)}),)
    out = []
    for token in BOXES[case](rows):
        name, args = token.split("(", 1)
        if name == "out":
            out.append(Box(Coil(args[:-1])))
        elif name == "copy":
            source, destination = args[:-1].split(",")
            out.append(Box(Copy(source, destination)))
        else:
            out.append(Box(_af_token(token)))
    return tuple(out)


def _af_token(token: str) -> AfInstruction:
    """Return the AF instruction that the CSV *token* reads to."""
    rung = convert_literal(_parse_single_rung_rows([_row("R", ["X001", *["-"] * 30], token)]))
    (instruction, *_) = rung.instructions
    assert isinstance(instruction, AfInstruction)
    return instruction


@pytest.mark.parametrize("case", CASES)
def test_lay_out(case: str) -> None:
    (rung,) = lay_out(Circuit(Branch((X1,), _boxes(case, 32))))
    assert rung.logical_rows == 32
    with pytest.raises(LayoutError) as caught:
        lay_out(Circuit(Branch((X1,), _boxes(case, 33))))
    assert caught.value.code is Code.LAYOUT_TOO_TALL
    assert str(caught.value).startswith("The circuit needs 33 rows, and a CLICK rung holds")


# ---------------------------------------------------------------------------
# decode
# ---------------------------------------------------------------------------


def test_decode_reads_a_rung_of_33_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """``decode()`` reads such a rung without a warning, and the writers refuse it.

    CLICK can't hold a rung of 33 rows, so no capture has one.  The buffer is made by
    ``encode()`` with its 32-row limit raised for this test.
    """
    rung = _drawn("coils", 33)
    with monkeypatch.context() as patch:
        patch.setattr(laddercodec._grid, "MAX_ROWS", 33)
        patch.setattr(laddercodec.empty_multirow, "EMPTY_MULTIROW_MAX_ROWS", 33)
        data = encode(rung)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert decode(data) == [rung]
    assert [f.code for f in check(rung)] == [Code.LAYOUT_TOO_TALL]
    _writer_error(lambda: csv_rows([rung]))
