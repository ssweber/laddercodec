"""Tests of undecoded markers.

When a decoder cannot read a rung, it returns one marker rung in its place and warns. It
does not raise. If the decoder cannot tell where that rung ends, decoding stops. One
marker then stands for that rung and every rung after it. A buffer that the decoders
cannot read at all still raises. Such a buffer has a bad magic, size or SCR header.

Most buffers here are golden fixtures that were encoded and then damaged, so most tests
need no capture of their own.
"""

from __future__ import annotations

import gzip
import importlib
import pickle
import warnings
from dataclasses import replace
from pathlib import Path

import pytest

from laddercodec import (
    EncodeError,
    FieldError,
    Program,
    Rung,
    Undecoded,
    UndecodedCommentWarning,
    UndecodedRungWarning,
    check,
    decode,
    decode_program,
    encode,
    read_csv,
    write_csv,
)
from laddercodec.csv.writer import CsvWriteError
from laddercodec.decode import DecodeError, decode_rung, decode_rungs, inspect_cells
from laddercodec.instructions import Shift, UnknownCondition, UnknownInstruction
from laddercodec.model import Condition
from laddercodec.undecoded import marker_rung
from tests.ladder.test_decode_program import _synthetic_scr
from tests.undecoded_captures import WINDY_ROAD

decode_program_module = importlib.import_module("laddercodec.decode_program")
writer_module = importlib.import_module("laddercodec.csv.writer")
FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "ladder_captures" / "golden"
COLUMNS = [*(chr(ord("A") + i) for i in range(26)), "AA", "AB", "AC", "AD", "AE", "AF"]


def _decoded(name: str) -> Rung:
    [rung] = decode((GOLDEN / name).read_bytes())
    assert isinstance(rung, Rung)
    return replace(rung, comment_rtf=None)


#: Three commented rungs: a 3-row branch, a series, then the branch again.
RUNGS = [
    replace(_decoded("instr-3row-branch.bin"), comment="first"),
    replace(_decoded("instr-series.bin"), comment="second"),
    replace(_decoded("instr-3row-branch.bin"), comment="third"),
]
DATA = encode(RUNGS)
#: The rungs as decode() returns them, each with the RTF of its comment.
DECODED = decode(DATA)


def _decode(data: bytes) -> tuple[list[Rung], list[Undecoded]]:
    """Decode a multi-rung buffer. Return its rungs and the marker of each UndecodedRungWarning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        rungs = decode(data)
    return rungs, [w.message.marker for w in caught if isinstance(w.message, UndecodedRungWarning)]


def _only_marker(rungs: list[Rung], index: int) -> Undecoded:
    """Check that rung *index* is a marker rung and that every other rung decodes as encoded.

    Return the marker.
    """
    assert len(rungs) == len(RUNGS)
    for i, rung in enumerate(rungs):
        if i != index:
            assert rung == DECODED[i]
    rung = rungs[index]
    (marker,) = rung.instructions
    assert isinstance(marker, Undecoded)
    assert rung.logical_rows == 1
    assert rung.conditions == (("-",) * 31,)
    assert marker.rung == index
    # decode() does not know whether the rungs come from a subroutine, so the marker acts as
    # end().
    assert marker.stop == "end"
    return marker


def _cell(rung: int, row: int, column: int) -> int:
    (dump,) = inspect_cells(DATA, [(rung, row, COLUMNS[column])])
    return dump.offset


def _patched(*changes: tuple[int, bytes]) -> bytes:
    data = bytearray(DATA)
    for offset, value in changes:
        data[offset : offset + len(value)] = value
    return bytes(data)


def test_the_buffer_decodes_as_encoded() -> None:
    rungs, markers = _decode(DATA)
    assert rungs == DECODED
    assert [replace(r, comment_rtf=None) for r in rungs] == RUNGS
    assert markers == []


@pytest.mark.parametrize("index", [0, 1, 2], ids=["first", "middle", "last"])
def test_down_wire_in_the_output_column(index: int) -> None:
    rungs, markers = _decode(_patched((_cell(index, 0, 31) + 0x21, b"\x01")))
    marker = _only_marker(rungs, index)
    assert markers == [marker]
    assert (marker.row, marker.column) == (0, 31)
    assert marker.error.startswith("the output column has a down wire")
    # The marker rung's comment is the marker's headline, then the rung's own comment.
    assert rungs[index].comment == f"{marker.headline}\n{RUNGS[index].comment}"


@pytest.mark.parametrize("index", [0, 1, 2], ids=["first", "middle", "last"])
def test_unknown_wire_flags_name_the_cell(index: int) -> None:
    row = RUNGS[index].logical_rows - 1
    column = next(c for c, t in enumerate(RUNGS[index].conditions[row]) if isinstance(t, str))
    rungs, markers = _decode(_patched((_cell(index, row, column) + 0x21, b"\x07")))
    marker = _only_marker(rungs, index)
    assert markers == [marker]
    assert (marker.row, marker.column) == (row, column)
    assert marker.error.startswith("unknown wire flags (segment, right, down) = ")


def _instruction_cell(rung: Rung) -> tuple[int, int]:
    """Return the (row, column) of the first condition instruction in *rung* that has a
    condition cell after it."""
    return next(
        (row, column)
        for row, tokens in enumerate(rung.conditions)
        for column, token in enumerate(tokens[:-1])
        if isinstance(token, Condition)
    )


def _rungs_and_markers(data: bytes) -> tuple[list[Rung], list[Undecoded]]:
    """Decode *data*, which holds one rung or several.

    Return its rungs and the marker of each UndecodedRungWarning.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        rungs = decode(data)
    return rungs, [w.message.marker for w in caught if isinstance(w.message, UndecodedRungWarning)]


def _stopped_at(rungs: list[Rung], markers: list[Undecoded], index: int) -> Undecoded:
    """Check that decoding stopped at rung *index*, and return the marker there.

    That marker must be the only one, and no rung may come after it.
    """
    assert len(rungs) == index + 1
    (marker,) = rungs[index].instructions
    assert isinstance(marker, Undecoded)
    assert markers == [marker]
    assert marker.rung == index
    assert marker.to_the_end is True
    assert "decoding stopped" not in marker.error
    return marker


@pytest.mark.parametrize("index", [0, 1, 2], ids=["first", "middle", "last"])
def test_a_row_the_walk_cannot_read_stops_decoding(index: int) -> None:
    """Decoding stops when the decoder cannot find the cell after an instruction.

    Without that cell, the decoder cannot tell where the next row starts. The rungs before
    that rung decode, and one marker stands for that rung and every rung after it.
    """
    row, column = _instruction_cell(RUNGS[index])
    rungs, markers = _rungs_and_markers(_patched((_cell(index, row, column + 1) + 0x01, b"\x7f")))
    assert rungs[:index] == DECODED[:index]
    marker = _stopped_at(rungs, markers, index)
    assert (marker.row, marker.column) == (row, None)
    assert marker.error.startswith(f"Cannot find cell boundary for col={column + 1}")


def test_a_lost_first_rung_is_one_marker_from_every_decoder() -> None:
    """decode, decode_rung and decode_rungs each return one marker rung for a lost first rung.

    The decoder's walk of the grid stops before it reaches any preamble row, so it cannot
    tell whether the buffer holds one rung or several.
    """
    row, column = _instruction_cell(RUNGS[0])
    data = _patched((_cell(0, row, column + 1) + 0x01, b"\x7f"))
    with pytest.warns(UndecodedRungWarning):
        [rung] = decode(data)
    with pytest.warns(UndecodedRungWarning):
        assert decode_rung(data) == rung
    with pytest.warns(UndecodedRungWarning):
        assert decode_rungs(data) == [rung]
    assert isinstance(rung, Rung)
    (marker,) = rung.instructions
    assert isinstance(marker, Undecoded)
    assert (marker.rung, marker.row) == (0, row)


#: Four one-row rungs that CLICK copied from the middle of a program. Their rows are numbered
#: from 0x24. The encoder numbers rows from 0x01.
LOOP_EXITS = FIXTURES / "v4_captures" / "loop_exits.bin"


def test_a_row_the_walk_cannot_read_in_a_native_copy_stops_decoding() -> None:
    """When rung 1 of 4 cannot be read, rung 0 decodes and one marker stands for rungs 1 to 3."""
    data = LOOP_EXITS.read_bytes()
    want = decode(data)
    assert len(want) == 4
    (cell,) = inspect_cells(data, [(1, 0, "B")])
    assert data[cell.offset + 0x05] == 0x26
    assert isinstance(want[1].conditions[0][0], Condition)
    damaged = bytearray(data)
    damaged[cell.offset + 0x01] = 0x7F
    rungs, markers = _rungs_and_markers(bytes(damaged))
    assert rungs[0] == want[0]
    marker = _stopped_at(rungs, markers, 1)
    assert (marker.row, marker.column) == (0, None)


def test_a_rung_with_no_data_rows_stops_decoding() -> None:
    """Decoding stops at a rung that has no data rows.

    The test sets the preamble flag (+0x30) on cells 0 and 1 of rung 1's first data row,
    at the places where a preamble row with no comment holds it. That row then reads as a
    preamble row, so rung 1 has no data rows. One marker stands for rung 1 and every rung
    after it, and decode returns no rung after the marker.
    """
    row0 = _cell(1, 0, 0)
    rungs, markers = _rungs_and_markers(
        _patched((row0 + 0x30, b"\x01"), (row0 + 0x34, bytes(4)), (row0 + 0x70, b"\x01"))
    )
    assert rungs[0] == DECODED[0]
    marker = _stopped_at(rungs, markers, 1)
    assert (marker.row, marker.column) == (None, None)
    assert marker.error.startswith("the rung has no data rows")


@pytest.mark.parametrize("row", [0, 1, 2], ids=["first", "middle", "last"])
def test_a_preamble_flag_on_cell_0_only_stops_decoding(row: int) -> None:
    """A data row of rung 1 with the preamble flag on cell 0 only is not a preamble row.

    Its cell 1 has the flag clear, as cell 1 of every data row does. The decoder then cannot
    tell where the rows of rung 1 end. Rung 0 decodes, and one marker stands for rung 1 and
    every rung after it.
    """
    three = _decoded("nc-3row-t-junction.bin")
    data = encode([replace(three, comment=f"c{i}") for i in range(3)])
    want = decode(data)
    assert len(want) == 3
    (cell0,) = inspect_cells(data, [(1, row, "A")])
    (cell1,) = inspect_cells(data, [(1, row, "B")])
    assert data[cell0.offset + 0x30] == data[cell1.offset + 0x30] == 0
    damaged = bytearray(data)
    damaged[cell0.offset + 0x30] = 1
    rungs, markers = _rungs_and_markers(bytes(damaged))
    assert rungs[0] == want[0]
    marker = _stopped_at(rungs, markers, 1)
    assert (marker.row, marker.column) == (row, None)
    assert marker.error.startswith(f"grid row {3 + 1 + row} has the preamble flag on cell 0 only")


@pytest.mark.parametrize(("offset", "value"), [(0x01, 0x05), (0x05, 0x09)], ids=["column", "row"])
def test_a_preamble_row_with_no_cell_0_stops_decoding(offset: int, value: int) -> None:
    """Decoding stops at rung 0 when the cell 0 signature of rung 1's preamble row is damaged.

    The decoder cannot tell whether rung 0 has more rows.

    Rung 0's last row has no output, so its last cell is 0x40 bytes, and the walk steps
    straight to the preamble row.  After a row whose last cell holds an instruction, the
    walk would search for the next row's cell 0 instead.
    """
    first = _decoded("instr-3row-or.bin")
    assert first.instructions[-1] == ""
    data = encode([first, RUNGS[1]])
    (af,) = inspect_cells(data, [(0, first.logical_rows - 1, "AF")])
    preamble = af.offset + af.size
    assert data[preamble + 0x30] == 0x01
    assert data[preamble + offset] != value
    damaged = bytearray(data)
    damaged[preamble + offset] = value
    rungs, markers = _rungs_and_markers(bytes(damaged))
    marker = _stopped_at(rungs, markers, 0)
    assert (marker.row, marker.column) == (first.logical_rows, None)
    assert marker.error.startswith(
        f"grid row {first.logical_rows} is a preamble row with no cell 0"
    )


def _with_code_page(data: bytes, index: int, page: bytes = b"ansicpg1251") -> bytes:
    """Return *data* with the code page of comment *index*, counted from 0, changed to *page*."""
    at = -1
    for _ in range(index + 1):
        at = data.index(b"ansicpg1252", at + 1)
    return data[:at] + page + data[at + len(page) :]


@pytest.mark.parametrize("index", [0, 1, 2], ids=["first", "middle", "last"])
def test_a_comment_that_does_not_decode_keeps_the_rung(index: int) -> None:
    """A comment in a code page other than 1252 is not decoded, and the rung keeps its logic.

    decode warns, and puts a note at the start of the rung's comment.
    """
    with pytest.warns(UndecodedCommentWarning) as caught:
        rungs = decode(_with_code_page(DATA, index))
    (warning,) = [w.message for w in caught]
    assert isinstance(warning, UndecodedCommentWarning)
    assert (warning.rung, warning.program) == (index, None)
    assert str(warning).startswith(f"the comment of rung {index} is not decoded")
    note = f"UNDECODED comment: {warning.error}\n{DECODED[index].comment}"
    for i, rung in enumerate(rungs):
        want = DECODED[i]
        if i == index:
            want = replace(want, comment=note, comment_rtf=rung.comment_rtf)
            assert rung.comment_rtf is not None and b"ansicpg1251" in rung.comment_rtf
        assert rung == want


def test_a_comment_that_does_not_decode_on_a_marker_rung() -> None:
    """When neither the cells nor the comment of a rung decode, the rung becomes a marker rung.

    The marker rung's comment holds the marker's headline and then the comment's note.
    """
    data = _with_code_page(_patched((_cell(1, 0, 31) + 0x21, b"\x01")), 1)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        rungs = decode(data)
    kinds = [type(w.message) for w in caught]
    assert kinds == [UndecodedCommentWarning, UndecodedRungWarning]
    (marker,) = rungs[1].instructions
    assert isinstance(marker, Undecoded)
    error = caught[0].message.error  # type: ignore[union-attr]
    assert rungs[1].comment == f"{marker.headline}\nUNDECODED comment: {error}\nsecond"


@pytest.mark.parametrize("cut", [False, True], ids=["zeroed", "cut"])
@pytest.mark.parametrize(("index", "row"), [(1, 0), (2, 1)])
def test_rows_lost_to_the_end_make_one_marker(index: int, row: int, cut: bool) -> None:
    """A row that has no cell 0, or that starts past the end of the buffer, ends the walk of
    the grid.

    One marker stands for that row's rung and every later rung.
    """
    start = _cell(index, row, 0)
    data = DATA[:start] if cut else DATA[:start] + bytes(len(DATA) - start)
    rungs, markers = _decode(data)
    *decoded, last = rungs
    assert decoded == DECODED[:index]
    (marker,) = last.instructions
    assert isinstance(marker, Undecoded)
    assert markers == [marker]
    assert (marker.rung, marker.row, marker.column) == (index, row, None)
    assert marker.to_the_end is True
    assert "decoding stopped" not in marker.error
    assert marker.error.startswith("the buffer ends before" if cut else "grid row")


def test_two_bad_rungs_make_two_markers() -> None:
    rungs, markers = _decode(
        _patched((_cell(0, 0, 31) + 0x21, b"\x01"), (_cell(2, 0, 31) + 0x21, b"\x01"))
    )
    assert [(m.rung, m.to_the_end) for m in markers] == [(0, False), (2, False)]
    assert rungs[1] == DECODED[1]


def test_envelope_errors_still_raise() -> None:
    with pytest.raises(DecodeError, match="Invalid magic"):
        decode(b"\x00" * len(DATA))
    with pytest.raises(DecodeError, match="Buffer too short"):
        decode(DATA[:0x100])


# ---------------------------------------------------------------------------
# decode_program: subroutines stop with return(), and the warning names the program
# ---------------------------------------------------------------------------


def test_scr_comment_that_does_not_decode_keeps_the_rung() -> None:
    """The rung keeps its logic and is not listed in Program.undecoded."""
    data = _synthetic_scr(["first", "second", "third"])
    want = decode_program(data)
    with pytest.warns(
        UndecodedCommentWarning, match="^program 'Synth', the comment of rung 1 is not decoded"
    ) as caught:
        program = decode_program(_with_code_page(data, 1))
    (warning,) = [w.message for w in caught]
    assert isinstance(warning, UndecodedCommentWarning)
    assert (warning.rung, warning.program) == (1, "Synth")
    assert program.undecoded == []
    assert [r.comment for r in program.rungs] == [
        "first",
        f"UNDECODED comment: {warning.error}\nsecond",
        "third",
    ]
    assert [(r.conditions, r.instructions) for r in program.rungs] == [
        (r.conditions, r.instructions) for r in want.rungs
    ]


SCR_MAIN = FIXTURES / "scr_captures" / "coverage.scr"


def _scr_with(monkeypatch: pytest.MonkeyPatch, change) -> tuple[Program, Program]:
    """Return coverage.scr decoded as it is, and decoded again with *change* applied.

    *change* receives the instruction list of the first record that has instructions. The
    list that *change* returns replaces it.
    """
    data = SCR_MAIN.read_bytes()
    want = decode_program(data)
    real = decode_program_module._walk_until_framing_error

    def walk(data, header):
        records, error = real(data, header)
        index = next(i for i, r in enumerate(records) if r.instructions)
        records[index] = replace(records[index], instructions=change(records[index].instructions))
        return records, error

    monkeypatch.setattr(decode_program_module, "_walk_until_framing_error", walk)
    with pytest.warns(UndecodedRungWarning, match="^program 'Main Program', rung "):
        got = decode_program(data)
    return want, got


def _first_marker(want: Program, got: Program) -> Undecoded:
    """Check that *got* has one marker and that every other rung matches *want*.

    Return the marker.
    """
    (marker,) = got.undecoded
    assert marker.stop == "end"  # coverage.scr is the main program
    assert len(got.rungs) == len(want.rungs)
    index = marker.rung
    assert (
        got.rungs[:index] + got.rungs[index + 1 :] == want.rungs[:index] + want.rungs[index + 1 :]
    )
    return marker


def test_scr_instruction_on_the_comment_row(monkeypatch: pytest.MonkeyPatch) -> None:
    def change(instructions):
        row, col, *rest = instructions[0]
        return [(-1, col, *rest), *instructions[1:]]

    marker = _first_marker(*_scr_with(monkeypatch, change))
    assert marker.row is None
    assert marker.error == "an instruction is stored on the comment row"


def test_scr_instruction_past_the_output_column(monkeypatch: pytest.MonkeyPatch) -> None:
    def change(instructions):
        row, col, *rest = instructions[0]
        return [(row, 40, *rest), *instructions[1:]]

    marker = _first_marker(*_scr_with(monkeypatch, change))
    assert marker.column is None
    assert marker.error == "an instruction is stored in column 40, past AF"


def test_scr_two_instructions_in_one_cell(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = _first_marker(
        *_scr_with(monkeypatch, lambda instructions: [*instructions, instructions[0]])
    )
    assert marker.error == "two instructions are stored in one cell"
    assert marker.row is not None and marker.column is not None


def test_scr_bytes_a_rung_cannot_be_built_from(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rung whose SCR record reads whole but whose cells cannot be built becomes a marker.

    The marker rung keeps the rung's comment after the marker's headline.
    """

    def build(**kwargs):
        raise ValueError("no such row")

    monkeypatch.setattr(decode_program_module, "_build_topology_backed_rung", build)
    with pytest.warns(UndecodedRungWarning, match="no such row"):
        program = decode_program(_synthetic_scr(["first"]))
    (marker,) = program.undecoded
    assert (marker.rung, marker.row, marker.error, marker.stop) == (
        0,
        None,
        "no such row",
        "return",
    )
    assert program.rungs[0].comment == marker.headline + "\nfirst"


def test_scr_header_errors_still_raise() -> None:
    with pytest.raises(DecodeError):
        decode_program(b"not an SCR file")


def test_program_lists_no_markers_when_every_rung_decodes() -> None:
    program = decode_program(_synthetic_scr(["first"]))
    assert program.undecoded == []
    marker = Undecoded("x", 1)
    built = Program("Main", 1, [RUNGS[0], marker_rung(marker), RUNGS[1]])
    assert built.undecoded == [marker]


# ---------------------------------------------------------------------------
# The marker: fields, CSV, encode, check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"error": ""}, "must be text that says why"),
        ({"error": "   "}, "must be text that says why"),
        ({"error": "a\nb"}, "must be one line"),
        ({"rung": -1}, r"Undecoded\.rung"),
        ({"rung": True}, r"Undecoded\.rung"),
        ({"row": -1}, r"Undecoded\.row"),
        ({"column": 32}, r"Undecoded\.column"),
        ({"stop": "halt"}, r"Undecoded\.stop"),
        ({"to_the_end": 2}, r"Undecoded\.to_the_end: 2 is not True, False, 1 or 0"),
        ({"to_the_end": "yes"}, r"Undecoded\.to_the_end: 'yes' is not True, False, 1 or 0"),
        ({"to_the_end": None}, r"Undecoded\.to_the_end: None is not True, False, 1 or 0"),
    ],
)
def test_marker_fields_are_checked(kwargs: dict, message: str) -> None:
    fields = {"error": "why", "rung": 0, **kwargs}
    with pytest.raises(FieldError, match=message):
        Undecoded(**fields)


def test_to_the_end_is_stored_as_a_bool() -> None:
    """``to_the_end`` accepts 1 and 0 as every flag field does, and stores a bool."""
    assert Undecoded("why", 0, to_the_end=1).to_the_end is True
    assert Undecoded("why", 0, to_the_end=0).to_the_end is False
    assert Undecoded("why", 0, to_the_end=1) == Undecoded("why", 0, to_the_end=True)


def test_marker_text() -> None:
    """The headline counts the rung and the row from 1, as CLICK shows them.

    ``where`` and the CSV token count them from 0.
    """
    marker = Undecoded("why", 4, 2, 31, "return")
    assert marker.where == "rung 4, row 2"
    assert marker.headline == "UNDECODED: CLICK rung 5, row 3: why"
    assert marker.to_csv() == 'undecoded("why",rung=4,row=2,column=31,stop=return)'
    assert Undecoded("why", 4).to_csv() == 'undecoded("why",rung=4,stop=end)'
    assert Undecoded("why", 4).headline == "UNDECODED: CLICK rung 5: why"
    assert Undecoded("why", 0, 0).headline == "UNDECODED: CLICK rung 1, row 1: why"


def test_marker_text_to_the_end() -> None:
    """A marker that stands for its rung and every rung after it says so after the error."""
    stopped = Undecoded("why", 4, stop="end", to_the_end=True)
    assert stopped.headline == (
        "UNDECODED: CLICK rung 5: why; decoding stopped, so this marker stands for "
        "CLICK rung 5 to the end"
    )
    assert stopped.to_csv() == 'undecoded("why",rung=4,stop=end,to_the_end=1)'
    at_row = Undecoded("why", 1, 0, to_the_end=True)
    assert at_row.headline == (
        "UNDECODED: CLICK rung 2, row 1: why; decoding stopped, so this marker stands for "
        "CLICK rung 2 to the end"
    )
    assert at_row.where == "rung 1, row 0"
    assert str(UndecodedRungWarning(at_row)) == (
        "rung 1, row 0 is not decoded, and an undecoded marker stands in for it: why; "
        "decoding stopped, so this marker stands for rung 1 to the end"
    )
    assert str(UndecodedRungWarning(Undecoded("why", 1, 0))) == (
        "rung 1, row 0 is not decoded, and an undecoded marker stands in for it: why"
    )
    with pytest.raises(
        EncodeError, match=r"\(UNDECODED: CLICK rung 2, row 1: why; decoding stopped"
    ):
        encode(marker_rung(at_row))


def test_warnings_pickle() -> None:
    warning = UndecodedRungWarning(Undecoded("why", 1, 0), "Sub")
    back = pickle.loads(pickle.dumps(warning))
    assert (back.marker, back.program, str(back)) == (warning.marker, "Sub", str(warning))
    texted = UndecodedRungWarning(Undecoded("why", 1, 0), text="rung 1, row 0 can't be read")
    back_texted = pickle.loads(pickle.dumps(texted))
    assert (back_texted.text, str(back_texted)) == (texted.text, "rung 1, row 0 can't be read")
    comment = UndecodedCommentWarning(2, "why", "Sub")
    back_comment = pickle.loads(pickle.dumps(comment))
    assert (back_comment.rung, back_comment.error, back_comment.program) == (2, "why", "Sub")
    assert str(back_comment) == str(comment)
    assert back_comment.partial is False
    partial = UndecodedCommentWarning(2, "why", "Sub", partial=True)
    back_partial = pickle.loads(pickle.dumps(partial))
    assert (back_partial.rung, back_partial.error, back_partial.program) == (2, "why", "Sub")
    assert back_partial.partial is True
    assert str(back_partial) == str(partial)


@pytest.mark.parametrize(
    "marker",
    [
        Undecoded("why", 0),
        Undecoded('a "quoted", comma-held error', 7, 3, 12, "return"),
        Undecoded("the output column has a down wire", 2, 0, 31),
        Undecoded("the buffer ends", 3, 1, stop="return", to_the_end=True),
        Undecoded("the rung has no data rows", 5, to_the_end=True),
    ],
)
def test_csv_round_trip(marker: Undecoded, tmp_path: Path) -> None:
    rungs = [RUNGS[1], marker_rung(marker, "its own comment"), RUNGS[1]]
    write_csv(tmp_path / "m.csv", rungs)
    assert read_csv(tmp_path / "m.csv") == rungs


@pytest.mark.parametrize(
    ("token", "message"),
    [
        ("undecoded(rung=1,stop=end)", "must be undecoded"),
        ('undecoded("x",rung=1,bogus=2,stop=end)', "must be undecoded"),
        ('undecoded("x",stop=end)', "has no rung="),
        ('undecoded("x",rung=1)', "has no stop="),
        ('undecoded("x",rung=1,stop=halt)', "must be 'end' or 'return'"),
        ('undecoded("x",rung=-1,stop=end)', "must be a whole number from 0"),
        ('undecoded("x",rung=1,column=32,stop=end)', "must be None or 0 to 31"),
        ('undecoded("x",rung=1,stop=end,to_the_end=2)', "to_the_end: 2 is not 1 or 0"),
        ('undecoded("x",rung=1,stop=end,to_the_end=yes)', "'yes' is not 1 or 0"),
    ],
)
def test_csv_token_errors(token: str, message: str, tmp_path: Path) -> None:
    write_csv(tmp_path / "m.csv", [marker_rung(Undecoded("x", 1))])
    text = (tmp_path / "m.csv").read_text(encoding="utf-8")
    bad = text.replace('"undecoded(""x"",rung=1,stop=end)"', '"' + token.replace('"', '""') + '"')
    assert bad != text
    (tmp_path / "m.csv").write_text(bad, encoding="utf-8")
    with pytest.raises(FieldError, match=message):
        read_csv(tmp_path / "m.csv")


@pytest.mark.parametrize(
    ("rung", "row", "column"),
    [
        (
            replace(
                RUNGS[1], conditions=[[UnknownCondition(raw=b"\x01"), *RUNGS[1].conditions[0][1:]]]
            ),
            0,
            0,
        ),
        (replace(RUNGS[1], instructions=[UnknownInstruction(raw=b"\x01")]), 0, 31),
    ],
    ids=["condition", "instruction"],
)
def test_write_csv_writes_a_marker_for_an_unwritable_rung(
    rung: Rung, row: int, column: int, tmp_path: Path
) -> None:
    with pytest.warns(UndecodedRungWarning, match="^rung 1, row 0 is not decoded") as caught:
        write_csv(tmp_path / "m.csv", [RUNGS[0], rung], stop="return")
    (warning,) = [w.message for w in caught if isinstance(w.message, UndecodedRungWarning)]
    marker = warning.marker
    assert (marker.rung, marker.row, marker.column, marker.stop) == (1, row, column, "return")
    kind = "condition" if column < 31 else "instruction"
    assert marker.error == f"no CSV token holds this unknown {kind} (1 bytes)"
    back = read_csv(tmp_path / "m.csv")
    assert back == [RUNGS[0], marker_rung(marker, "second")]


def test_write_csv_refuses_an_unknown_stop_before_writing(tmp_path: Path) -> None:
    """``stop`` is checked even when no rung needs a marker, and no file is made."""
    with pytest.raises(CsvWriteError, match=r"write_csv: stop='halt' must be 'end' or 'return'"):
        write_csv(tmp_path / "m.csv", RUNGS, stop="halt")  # type: ignore[arg-type]
    assert not (tmp_path / "m.csv").exists()


def test_write_csv_still_raises_for_a_shape_it_cannot_write(tmp_path: Path) -> None:
    """write_csv writes a marker only for a cell that has no CSV token.

    A rung whose tokens are all known, but in a shape that CSV cannot hold, still raises.
    """
    blank = [""] * 31
    rung = Rung(
        conditions=[blank, blank],
        instructions=[Shift("C99", "C106"), ""],
        comment=None,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", UndecodedRungWarning)
        with pytest.raises(
            CsvWriteError,
            match="shift on row 0 from 0 is 3 rows tall, but the rung has only 2 rows",
        ):
            write_csv(tmp_path / "m.csv", [RUNGS[0], rung])


def test_write_csv_still_raises_when_the_round_trip_check_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(rung, rows, *, exact=False):
        raise CsvWriteError("round-trip validation failed")

    monkeypatch.setattr(writer_module, "_validate_roundtrip", fail)
    with pytest.raises(CsvWriteError, match="round-trip validation failed"):
        write_csv(tmp_path / "m.csv", [RUNGS[1]])


def test_encode_refuses_a_marker() -> None:
    marker = marker_rung(Undecoded("why", 3, 0, 31))
    with pytest.raises(EncodeError, match=r"Row 0, AF: an undecoded marker .* can't be pasted"):
        encode(marker)
    with pytest.raises(EncodeError, match=r"^Rung 1: Row 0, AF: an undecoded marker"):
        encode([RUNGS[0], marker])


def test_check_reports_the_marker_and_nothing_else() -> None:
    marker = Undecoded("why", 3, 1)
    findings = check([RUNGS[1], marker_rung(marker)])
    assert [(f.rung, f.code, f.click_id, f.captured, f.row, f.column) for f in findings] == [
        (1, "undecoded-rung", None, False, 0, 31)
    ]
    assert findings[0].message == (
        "row 0 from 0, column AF: an undecoded marker for rung 3, row 1, "
        "which encode() refuses: why"
    )


def test_check_runs_the_layout_checks_on_a_rung_with_more_than_a_marker() -> None:
    """check() runs every layout check on a hand-built rung that holds a marker and more."""
    marker = Undecoded("why", 3, 1)
    contacts = ["", *RUNGS[1].conditions[0][1:]]  # the contacts with no line from the rail
    rung = Rung(
        conditions=[["-"] * 31, contacts],
        instructions=[marker, RUNGS[1].instructions[0]],
        comment=None,
    )
    codes = [(f.code, f.row, f.column) for f in check(rung)]
    assert codes[0] == ("undecoded-rung", 0, 31)
    assert ("no-rail", 1, 1) in codes
    unwired = Rung(conditions=[["", *["-"] * 30]], instructions=[marker], comment=None)
    assert [(f.code, f.row, f.column) for f in check(unwired)] == [
        ("undecoded-rung", 0, 31),
        ("unpowered-box", 0, 31),
    ]


def test_no_fixture_decodes_to_a_marker() -> None:
    """Every clipboard and SCR fixture decodes with no marker, except WINDY_ROAD.

    decode refuses the down wire in WINDY_ROAD's output column.
    """
    clipboard = [
        path
        for folder in ("ladder_captures", "coverage", "scr_captures", "tumbler", "v4_captures")
        for path in sorted((FIXTURES / folder).rglob("*.bin"))
        if path != WINDY_ROAD
    ]
    rungs_266 = gzip.decompress((FIXTURES / "scr_captures" / "rungs_266.bin.gz").read_bytes())
    scr = sorted(FIXTURES.rglob("*.scr"))
    assert len(clipboard) > 100 and len(scr) > 30
    with warnings.catch_warnings():
        warnings.simplefilter("error", UndecodedRungWarning)
        for path in clipboard:
            decode(path.read_bytes())
        decode(rungs_266)
        for path in scr:
            decode_program(path.read_bytes())


def test_windy_road_decodes_to_a_marker() -> None:
    with pytest.warns(UndecodedRungWarning) as caught:
        [rung] = decode(WINDY_ROAD.read_bytes())
    assert len(caught) == 1
    assert isinstance(rung, Rung)
    (marker,) = rung.instructions
    assert isinstance(marker, Undecoded)
    assert (marker.rung, marker.column) == (0, 31)


def test_a_truncated_scr_record_stops_decoding_at_a_marker() -> None:
    """An SCR record cut off in the middle of its comment is a framing error.

    Decoding stops at a marker there, and the rungs before it decode.
    """
    data = _synthetic_scr(["first", "second"])
    cut = data.index(b"second") - 4
    with pytest.warns(UndecodedRungWarning, match="rung 1 to the end"):
        program = decode_program(data[:cut])
    assert program.rungs[0].comment == "first"
    (marker,) = program.undecoded
    assert (marker.rung, marker.row, marker.to_the_end) == (1, None, True)
    assert "decoding stopped" not in marker.error
    assert program.rungs[1].comment == marker.headline
    assert marker.headline.startswith("UNDECODED: CLICK rung 2: ")
    assert marker.headline.endswith(
        "; decoding stopped, so this marker stands for CLICK rung 2 to the end"
    )
