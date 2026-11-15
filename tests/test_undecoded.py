"""Undecoded markers: a rung the decoders can't read becomes one marker rung, not an error.

The buffers here are encoded from goldens and then corrupted, so no test needs a capture of
its own.  A buffer the decoders can't read at all (its magic, size or SCR header) still
raises.
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
from laddercodec.decode import DecodeError, inspect_cells
from laddercodec.csv.writer import WriterError
from laddercodec.instructions import Shift, UnknownCondition, UnknownInstruction
from laddercodec.model import ConditionInstruction
from laddercodec.undecoded import marker_rung
from tests.fixtures_refused import is_refused
from tests.ladder.test_decode_program import _synthetic_scr

decode_program_module = importlib.import_module("laddercodec.decode_program")
writer_module = importlib.import_module("laddercodec.csv.writer")
FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "ladder_captures" / "golden"
COLUMNS = [*(chr(ord("A") + i) for i in range(26)), "AA", "AB", "AC", "AD", "AE", "AF"]


def _decoded(name: str) -> Rung:
    rung = decode((GOLDEN / name).read_bytes())
    assert isinstance(rung, Rung)
    return replace(rung, comment_rtf=None)


#: Three commented rungs: a 3-row branch, a series, then the branch again.
RUNGS = [
    replace(_decoded("instr-3row-branch.bin"), comment="first"),
    replace(_decoded("instr-series.bin"), comment="second"),
    replace(_decoded("instr-3row-branch.bin"), comment="third"),
]
DATA = encode(RUNGS)
#: The rungs as decode() gives them back: with each comment's RTF.
DECODED = decode(DATA)


def _decode(data: bytes) -> tuple[list[Rung], list[Undecoded]]:
    """Decode a multi-rung buffer; return its rungs and the markers its warnings carry."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        rungs = decode(data)
    assert isinstance(rungs, list)
    return rungs, [w.message.marker for w in caught if isinstance(w.message, UndecodedRungWarning)]


def _only_marker(rungs: list[Rung], index: int) -> Undecoded:
    """The marker at rung *index*, after checking every other rung decodes as encoded."""
    assert len(rungs) == len(RUNGS)
    for i, rung in enumerate(rungs):
        if i != index:
            assert rung == DECODED[i]
    rung = rungs[index]
    (marker,) = rung.instructions
    assert isinstance(marker, Undecoded)
    assert rung.logical_rows == 1
    assert rung.conditions == [["-"] * 31]
    assert marker.rung == index
    assert marker.stop == "end"  # decode() has no program: the marker acts as end()
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
    # The marker's comment leads with its headline, then the rung's own comment.
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
    """The first condition instruction in *rung* that has a condition cell after it."""
    return next(
        (row, column)
        for row, tokens in enumerate(rung.conditions)
        for column, token in enumerate(tokens[:-1])
        if isinstance(token, ConditionInstruction)
    )


@pytest.mark.parametrize("index", [0, 1, 2], ids=["first", "middle", "last"])
def test_a_row_the_walk_cannot_read_is_skipped_to_the_next_row(index: int) -> None:
    """With the cell after an instruction unfindable, the walk resumes at the next row."""
    row, column = _instruction_cell(RUNGS[index])
    rungs, markers = _decode(_patched((_cell(index, row, column + 1) + 0x01, b"\x7f")))
    marker = _only_marker(rungs, index)
    assert markers == [marker]
    assert (marker.row, marker.column) == (row, None)
    assert marker.error.startswith(f"Cannot find cell boundary for col={column + 1}")
    assert not marker.error.endswith("to the end")


def _fake_cell0(number: int) -> bytes:
    """The bytes of a cell 0 of the row numbered *number*, holding an instruction (+0x25)."""
    fake = bytearray(0x26)
    fake[0x05:0x07] = number.to_bytes(2, "little")
    fake[0x09] = fake[0x0A] = 0x01
    fake[0x25] = 0x01
    return bytes(fake)


def _right_or_marker(rungs: list[Rung]) -> None:
    """Each rung is the one encoded at its index, or a marker for that index: never another."""
    for i, rung in enumerate(rungs):
        if isinstance(rung.instructions[0], Undecoded):
            assert rung.instructions[0].rung == i
        else:
            assert rung == DECODED[i]


@pytest.mark.parametrize(
    "plant",
    ["before the next row", "in a later blob", "in a later blob, next row lost"],
)
def test_the_walk_never_resumes_at_a_row_start_inside_a_blob(plant: str) -> None:
    """After a row fails, a cell 0 signature in instruction bytes never starts a row.

    Rung 1's one row fails, and the next row is rung 2's preamble.  A fake cell 0 for that
    preamble's row number is planted just before it (inside rung 1's failed row, where a
    walk from it would borrow the preamble's cells 1..31), or in the tail of rung 2's
    instruction cell.  Each rung decodes as itself or as a marker, never as another rung.
    """
    assert RUNGS[1].logical_rows == 1
    row, column = _instruction_cell(RUNGS[1])
    failed = _cell(1, row, 0)
    (af,) = inspect_cells(DATA, [(1, row, "AF")])
    preamble = af.offset + af.size  # rung 1's one row ends where rung 2's preamble starts
    number = int.from_bytes(DATA[failed + 0x05 : failed + 0x07], "little") + 1
    assert DATA[preamble + 0x30] == 0x01
    assert int.from_bytes(DATA[preamble + 0x05 : preamble + 0x07], "little") == number
    changes = [(_cell(1, row, column + 1) + 0x01, b"\x7f")]
    if plant == "before the next row":
        changes.append((preamble - 0x30, _fake_cell0(number)))
    else:
        r2, c2 = _instruction_cell(RUNGS[2])
        (dump,) = inspect_cells(DATA, [(2, r2, COLUMNS[c2])])
        changes.append((dump.offset + dump.size - 0x10, _fake_cell0(number)[:0x0B]))
        if plant.endswith("lost"):
            changes.append((preamble + 0x09, b"\x00"))
    rungs, markers = _decode(_patched(*changes))
    _right_or_marker(rungs)
    assert markers[0].rung == 1
    if not plant.endswith("lost"):
        assert len(rungs) == 3
        assert rungs[2] == DECODED[2]


def _with_code_page(data: bytes, index: int, page: bytes = b"ansicpg1251") -> bytes:
    """*data* with the code page of its comment number *index* (from 0) changed to *page*."""
    at = -1
    for _ in range(index + 1):
        at = data.index(b"ansicpg1252", at + 1)
    return data[:at] + page + data[at + len(page) :]


@pytest.mark.parametrize("index", [0, 1, 2], ids=["first", "middle", "last"])
def test_a_comment_that_does_not_decode_keeps_the_rung(index: int) -> None:
    """A comment in a code page other than 1252 is noted, and the rung keeps its logic."""
    with pytest.warns(UndecodedCommentWarning) as caught:
        rungs = decode(_with_code_page(DATA, index))
    assert isinstance(rungs, list)
    (warning,) = [w.message for w in caught]
    assert isinstance(warning, UndecodedCommentWarning)
    assert (warning.rung, warning.program) == (index, None)
    assert str(warning).startswith(f"the comment of rung {index} is not decoded")
    note = f"UNDECODED comment: {warning.error}"
    for i, rung in enumerate(rungs):
        want = DECODED[i]
        if i == index:
            want = replace(want, comment=note, comment_rtf=rung.comment_rtf)
            assert rung.comment_rtf is not None and b"ansicpg1251" in rung.comment_rtf
        assert rung == want


def test_a_comment_that_does_not_decode_on_a_marker_rung() -> None:
    """A rung whose cells and comment both fail is a marker whose comment holds the note."""
    data = _with_code_page(_patched((_cell(1, 0, 31) + 0x21, b"\x01")), 1)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        rungs = decode(data)
    assert isinstance(rungs, list)
    kinds = [type(w.message) for w in caught]
    assert kinds == [UndecodedCommentWarning, UndecodedRungWarning]
    (marker,) = rungs[1].instructions
    assert isinstance(marker, Undecoded)
    error = caught[0].message.error  # type: ignore[union-attr]
    assert rungs[1].comment == f"{marker.headline}\nUNDECODED comment: {error}"


@pytest.mark.parametrize("cut", [False, True], ids=["zeroed", "cut"])
@pytest.mark.parametrize(("index", "row"), [(1, 0), (2, 1)])
def test_rows_lost_to_the_end_make_one_marker(index: int, row: int, cut: bool) -> None:
    """A row with no cell 0, or past the buffer's end, ends the walk.

    One marker stands for that rung and every later one.
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
    assert marker.error.endswith(f"so this marker stands for rung {index} to the end")
    assert marker.error.startswith("the buffer ends before" if cut else "grid row")


def test_two_bad_rungs_make_two_markers() -> None:
    rungs, markers = _decode(
        _patched((_cell(0, 0, 31) + 0x21, b"\x01"), (_cell(2, 0, 31) + 0x21, b"\x01"))
    )
    assert [m.rung for m in markers] == [0, 2]
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
        f"UNDECODED comment: {warning.error}",
        "third",
    ]
    assert [(r.conditions, r.instructions) for r in program.rungs] == [
        (r.conditions, r.instructions) for r in want.rungs
    ]


SCR_MAIN = FIXTURES / "scr_captures" / "coverage.scr"


def _scr_with(monkeypatch: pytest.MonkeyPatch, change) -> tuple[Program, Program]:
    """coverage.scr decoded as is, then with *change* applied to its first record that has
    an instruction (the instruction list is passed in, and the list returned replaces it)."""
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
    """The one marker in *got*; every other rung is as in *want*."""
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
    """A rung whose record frames but whose cells don't build is a marker, with its comment."""

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
    with pytest.raises(ValueError):
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
    ],
)
def test_marker_fields_are_checked(kwargs: dict, message: str) -> None:
    fields = {"error": "why", "rung": 0, **kwargs}
    with pytest.raises(FieldError, match=message):
        Undecoded(**fields)


def test_marker_text() -> None:
    marker = Undecoded("why", 4, 2, 31, "return")
    assert marker.where == "rung 4, row 2"
    assert marker.headline == "UNDECODED: rung 4, row 2: why"
    assert marker.to_csv() == 'undecoded("why",rung=4,row=2,column=31,stop=return)'
    assert Undecoded("why", 4).to_csv() == 'undecoded("why",rung=4,stop=end)'
    assert Undecoded("why", 4).headline == "UNDECODED: rung 4: why"


def test_warnings_pickle() -> None:
    warning = UndecodedRungWarning(Undecoded("why", 1, 0), "Sub")
    back = pickle.loads(pickle.dumps(warning))
    assert (back.marker, back.program, str(back)) == (warning.marker, "Sub", str(warning))
    comment = UndecodedCommentWarning(2, "why", "Sub")
    back_comment = pickle.loads(pickle.dumps(comment))
    assert (back_comment.rung, back_comment.error, back_comment.program) == (2, "why", "Sub")
    assert str(back_comment) == str(comment)


@pytest.mark.parametrize(
    "marker",
    [
        Undecoded("why", 0),
        Undecoded('a "quoted", comma-held error', 7, 3, 12, "return"),
        Undecoded("the output column has a down wire", 2, 0, 31),
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


def test_write_csv_still_raises_for_a_shape_it_cannot_write(tmp_path: Path) -> None:
    """Only a cell with no token makes a marker; a rung of known tokens CSV can't hold raises."""
    blank = [""] * 31
    rung = Rung(
        logical_rows=2,
        conditions=[blank, blank],
        instructions=[Shift("C99", "C106"), ""],
        comment=None,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", UndecodedRungWarning)
        with pytest.raises(WriterError, match="shift requires 3 decoded rows"):
            write_csv(tmp_path / "m.csv", [RUNGS[0], rung])


def test_write_csv_still_raises_when_the_round_trip_check_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(rung, rows, *, exact=False):
        raise WriterError("round-trip validation failed")

    monkeypatch.setattr(writer_module, "_validate_roundtrip", fail)
    with pytest.raises(WriterError, match="round-trip validation failed"):
        write_csv(tmp_path / "m.csv", [RUNGS[1]])


def test_encode_refuses_a_marker() -> None:
    marker = marker_rung(Undecoded("why", 3, 0, 31))
    with pytest.raises(ValueError, match=r"Row 0, AF: an undecoded marker .* can't be pasted"):
        encode(marker)
    with pytest.raises(ValueError, match=r"^Rung 1: Row 0, AF: an undecoded marker"):
        encode([RUNGS[0], marker])


def test_check_reports_the_marker_and_nothing_else() -> None:
    marker = Undecoded("why", 3, 1)
    findings = check([RUNGS[1], marker_rung(marker)])
    assert [(f.rung, f.kind, f.code, f.captured, f.row, f.column) for f in findings] == [
        (1, "undecoded", None, False, 0, 31)
    ]
    assert findings[0].message == (
        "row 0 from 0, column AF: an undecoded marker for rung 3, row 1, "
        "which encode() refuses: why"
    )


def test_check_runs_the_layout_checks_on_a_rung_with_more_than_a_marker() -> None:
    """A hand-built rung that holds a marker and other content gets every finding."""
    marker = Undecoded("why", 3, 1)
    contacts = ["", *RUNGS[1].conditions[0][1:]]  # the contacts with no line from the rail
    rung = Rung(
        logical_rows=2,
        conditions=[["-"] * 31, contacts],
        instructions=[marker, RUNGS[1].instructions[0]],
        comment=None,
    )
    kinds = [(f.kind, f.row, f.column) for f in check(rung)]
    assert kinds[0] == ("undecoded", 0, 31)
    assert ("no_rail", 1, 1) in kinds
    unwired = Rung(logical_rows=1, conditions=[["", *["-"] * 30]], instructions=[marker], comment=None)
    assert [(f.kind, f.row, f.column) for f in check(unwired)] == [
        ("undecoded", 0, 31),
        ("unpowered_box", 0, 31),
    ]


def test_no_fixture_decodes_to_a_marker() -> None:
    """Every clipboard and SCR fixture decodes with no marker, but the one decode refuses."""
    clipboard = [
        path
        for folder in ("ladder_captures", "coverage", "scr_captures", "tumbler", "v4_captures")
        for path in sorted((FIXTURES / folder).rglob("*.bin"))
        if not is_refused(path)
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


def test_a_truncated_scr_record_stops_decoding_at_a_marker() -> None:
    """A record cut off mid-comment is a framing error: the rungs before it decode."""
    data = _synthetic_scr(["first", "second"])
    cut = data.index(b"second") - 4
    with pytest.warns(UndecodedRungWarning, match="rung 1 to the end"):
        program = decode_program(data[:cut])
    assert program.rungs[0].comment == "first"
