"""Test ``Tee``, the cell of a contact with a wire down, and the frozen ``Rung``.

A ``Tee`` wraps one contact. The decoders put a contact with a wire down in a ``Tee``, the
CSV form writes it as ``T:`` before the contact, and ``encode()`` writes the wire down.
A ``Rung`` is frozen and stores its rows as tuples.
"""

from __future__ import annotations

import csv
import dataclasses
import importlib
import warnings
from pathlib import Path

import pytest

from laddercodec import (
    Coil,
    CompareContact,
    Contact,
    CsvReadError,
    CsvWriteError,
    EncodeError,
    FieldError,
    Rung,
    Tee,
    decode,
    decode_program,
    encode,
    read_csv,
    replace,
    write_csv,
)
from laddercodec.codes import Code
from laddercodec.csv.writer import _token_to_csv
from laddercodec.instructions import UnknownCondition

_DECODE = importlib.import_module("laddercodec.decode")
_DECODE_PROGRAM = importlib.import_module("laddercodec.decode_program")

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "ladder_captures" / "golden"
SCR = FIXTURES / "scr_captures"
V4 = FIXTURES / "v4_captures"

#: Every clipboard and program fixture that decodes.
DECODED = sorted(
    [*FIXTURES.rglob("*.bin"), *FIXTURES.rglob("*.scr")],
    key=lambda path: str(path),
)


def _row(*cells: object, fill: str = "-") -> list[object]:
    return [*cells, *[fill] * (31 - len(cells))]


def _tee_rung(tee: Tee | None = None) -> Rung:
    """Return a two-row rung with *tee* in column B of the first row, wired to a second
    contact in column A of the second row."""
    tee = tee if tee is not None else Tee(Contact("X002"))
    return Rung(
        [_row(Contact("X001"), tee), _row(Contact("X003"), "-", fill="")],
        [Coil("Y001"), ""],
        None,
    )


# -- Tee ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "inner",
    [
        Contact("X001"),
        Contact("X001", kind="rise"),
        CompareContact("==", "DS1", "1"),
        UnknownCondition(b"\x00\x01"),
    ],
    ids=repr,
)
def test_a_tee_holds_one_contact(inner: object) -> None:
    tee = Tee(inner)  # type: ignore[arg-type]
    assert tee.contact is inner
    assert tee == Tee(inner) and hash(tee) == hash(Tee(inner))  # type: ignore[arg-type]
    with pytest.raises(dataclasses.FrozenInstanceError):
        tee.contact = Contact("X002")  # type: ignore[misc]


@pytest.mark.parametrize(
    "inner",
    ["X001", "T", Tee(Contact("X001")), Coil("Y001"), None, 5],
    ids=repr,
)
def test_a_tee_refuses_anything_but_one_contact(inner: object) -> None:
    with pytest.raises(FieldError) as caught:
        Tee(inner)  # type: ignore[arg-type]
    assert caught.value.field == "Tee.contact"
    assert caught.value.code == Code.INVALID_TEE
    assert "Tee(Contact('X001'))" in str(caught.value)


@pytest.mark.parametrize(
    ("inner", "text"),
    [
        (Contact("X001"), "T:X001"),
        (Contact("X002", kind="rise"), "T:rise(X002)"),
        (Contact("X003", kind="nc", immediate=True), "T:~X003.immediate"),
        (CompareContact("==", "DS1", "1"), "T:DS1==1"),
    ],
    ids=repr,
)
def test_a_tee_writes_t_and_the_contact_token(inner: object, text: str) -> None:
    tee = Tee(inner)  # type: ignore[arg-type]
    assert tee.to_csv() == text
    assert _token_to_csv(tee) == text


def test_a_tee_around_an_unknown_contact_has_no_csv_text() -> None:
    tee = Tee(UnknownCondition(b"\x00\x01"))
    with pytest.raises(CsvWriteError, match=r"Tee holds an UnknownCondition \(2 bytes\)"):
        tee.to_csv()
    with pytest.raises(CsvWriteError):
        _token_to_csv(tee)


def test_write_csv_writes_the_text_of_each_tee(tmp_path: Path) -> None:
    """The cell text in the file is ``to_csv()`` of the ``Tee`` the rung holds there."""
    rungs = decode((V4 / "or_compact_checked.bin").read_bytes())
    out = tmp_path / "rungs.csv"
    write_csv(out, rungs)
    with out.open(newline="", encoding="utf-8") as file:
        rows = [row for row in csv.reader(file) if row and row[0] != "marker"]
    grid = [row[1:32] for row in rows]
    cells = [cell for rung in rungs for row in rung.conditions for cell in row]
    tees = [cell for cell in cells if isinstance(cell, Tee)]
    assert tees
    written = [text for row in grid for text in row if text.startswith("T:")]
    assert written == [tee.to_csv() for tee in tees]


@pytest.mark.parametrize("path", DECODED, ids=lambda path: path.relative_to(FIXTURES).as_posix())
def test_every_decoded_cell_token_has_csv_text(path: Path) -> None:
    """``to_csv()`` works on each cell token that is not a string, and a ``Tee`` keeps its
    ``T:``. A caller that walks the cells and calls ``to_csv()`` loses no wire down."""
    data = path.read_bytes()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        rungs = decode(data) if path.suffix == ".bin" else decode_program(data).rungs
    for rung in rungs:
        for row in rung.conditions:
            for cell in row:
                if isinstance(cell, str):
                    continue
                text = cell.to_csv()  # type: ignore[union-attr]
                assert text.startswith("T:") == isinstance(cell, Tee), (cell, text)


@pytest.mark.parametrize(
    ("cls", "token"),
    [(Contact, "T:X001"), (Contact, "|:rise(X001)"), (CompareContact, "T:DS1==1")],
)
def test_a_contact_token_with_a_wire_down_is_refused(cls: type, token: str) -> None:
    """A contact class reads only the contact. The ``T:`` form is a ``Tee``."""
    with pytest.raises(CsvReadError, match=r"Wrap the contact in a Tee"):
        cls.from_csv_token(token)


def test_a_native_contact_with_a_wire_down_decodes_as_a_tee() -> None:
    """CLICK saved C1 and C2 in column B of the first rung, each with a wire down."""
    rungs = decode((V4 / "or_compact_checked.bin").read_bytes())
    assert rungs[0].conditions[0][1] == Tee(Contact("C1"))
    assert rungs[0].conditions[1][1] == Tee(Contact("C2"))
    assert decode(encode(rungs)) == rungs


def test_a_tee_in_column_a_is_refused() -> None:
    rung = Rung(
        [_row(Tee(Contact("X001"))), _row(Contact("X002"), fill="")],
        [Coil("Y001"), ""],
        None,
    )
    with pytest.raises(EncodeError, match=r"column A: T:X001 has a wire down, and column A"):
        encode(rung)


def test_a_tee_on_the_last_row_is_refused() -> None:
    rung = Rung([_row(Contact("X001"), Tee(Contact("X002")))], [Coil("Y001")], None)
    with pytest.raises(EncodeError, match=r"column B: T:X002 has a wire down on the rung's last"):
        encode(rung)


def test_an_unknown_contact_with_a_wire_down_decodes_as_a_tee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A condition cell that no parser reads keeps its wire down. ``encode()`` refuses the
    unknown contact inside a ``Tee`` as it refuses one on its own, and the rung encodes once
    the contact inside is replaced."""
    native = decode((V4 / "or_compact_checked.bin").read_bytes())[0]
    monkeypatch.setattr(_DECODE, "parse_condition_blob", lambda raw: None)
    [rung] = decode(encode(native))
    tee = rung.conditions[0][1]
    assert isinstance(tee, Tee) and isinstance(tee.contact, UnknownCondition)
    assert isinstance(rung.conditions[0][0], UnknownCondition)
    rows = [list(row) for row in rung.conditions]
    rows[0][0] = native.conditions[0][0]
    with pytest.raises(EncodeError, match=r"Unknown condition at row=0, col=1"):
        encode(replace(rung, conditions=rows))
    fixed = [list(row) for row in native.conditions]
    assert encode(replace(rung, conditions=fixed)) == encode(native)


def test_an_unknown_contact_with_a_wire_down_in_a_program_decodes_as_a_tee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``or_topology.scr`` holds ``T:X002`` in column B of its first rung."""
    data = (SCR / "or_topology.scr").read_bytes()
    monkeypatch.setattr(_DECODE_PROGRAM, "from_tags_condition", lambda *args: None)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        program = decode_program(data)
    tee = program.rungs[0].conditions[0][1]
    assert isinstance(tee, Tee) and isinstance(tee.contact, UnknownCondition)


# -- Rung --------------------------------------------------------------------


def test_assigning_to_a_rung_field_raises() -> None:
    rung = _tee_rung()
    for name in ("conditions", "instructions", "comment", "comment_rtf"):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(rung, name, None)
    with pytest.raises(TypeError):
        rung.conditions[0][0] = "-"  # type: ignore[index]
    with pytest.raises(AttributeError):
        rung.logical_rows = 3  # type: ignore[misc]


@pytest.mark.parametrize(
    "conditions",
    [["-"] * 31, "-" * 31, [["-"] * 31, "-" * 31]],
    ids=["flat row", "text", "text row"],
)
def test_a_text_where_a_row_belongs_is_refused(conditions: object) -> None:
    with pytest.raises(EncodeError, match=r"where a row belongs\. Pass conditions as one list"):
        Rung(conditions, [""], None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("conditions", "instructions", "message"),
    [
        ([], [], r"A rung has 1 to 32 rows\. This one has 0\. Pass conditions"),
        ([["-"] * 31] * 33, [""] * 33, r"This one has 33\. Split it into rungs"),
        ([["-"] * 31], ["", ""], r"The rung has 1 row, and instructions has 2 tokens\."),
        ([["-"] * 31] * 2, [""], r"The rung has 2 rows, and instructions has 1 token\."),
    ],
    ids=["no rows", "33 rows", "two tokens", "one token"],
)
def test_a_rung_with_the_wrong_row_count_names_the_counts(
    conditions: list[list[str]], instructions: list[str], message: str
) -> None:
    with pytest.raises(EncodeError, match=message):
        encode(Rung(conditions, instructions, None))


def test_a_text_where_the_instructions_list_belongs_is_refused() -> None:
    with pytest.raises(EncodeError, match=r"instructions holds the text 'NOP' where a list"):
        Rung([["-"] * 31], "NOP", None)


def test_a_rung_built_from_generators_keeps_every_row() -> None:
    rung = Rung(
        (row for row in [["-"] * 31, [""] * 31]),
        (token for token in [Coil("Y001"), ""]),
        None,
    )
    assert rung.conditions == (("-",) * 31, ("",) * 31)
    assert rung.instructions == (Coil("Y001"), "")


def test_a_rung_built_from_lists_equals_the_rung_built_from_tuples() -> None:
    from_lists = _tee_rung()
    from_tuples = Rung(
        tuple(tuple(row) for row in from_lists.conditions),
        tuple(from_lists.instructions),
        None,
    )
    assert from_lists == from_tuples
    assert hash(from_lists) == hash(from_tuples)
    assert from_lists.logical_rows == 2
    assert isinstance(from_lists.conditions, tuple)
    assert all(isinstance(row, tuple) for row in from_lists.conditions)
    assert isinstance(from_lists.instructions, tuple)


def test_rungs_that_differ_only_in_comment_rtf_are_equal() -> None:
    rung = _tee_rung()
    other = replace(rung, comment_rtf=b"{\\rtf1 x}")
    assert other == rung and hash(other) == hash(rung)


def test_replace_builds_a_rung_with_the_fields_given() -> None:
    rung = _tee_rung()
    changed = replace(rung, instructions=[Coil("Y002"), ""])
    assert changed.instructions == (Coil("Y002"), "")
    assert changed.conditions == rung.conditions
    assert rung.instructions == (Coil("Y001"), "")
    assert encode(changed) == encode(_tee_rung()).replace(
        "Y001".encode("utf-16-le"), "Y002".encode("utf-16-le")
    )


@pytest.mark.parametrize(
    "path",
    [
        V4 / "or_compact_checked.bin",
        V4 / "r30_tallbox_checked.bin",
        GOLDEN / "instr-3row-or.bin",
    ],
    ids=lambda path: path.name,
)
def test_a_decoded_rung_equals_its_csv_round_trip(tmp_path: Path, path: Path) -> None:
    rungs = decode(path.read_bytes())
    out = tmp_path / "rung.csv"
    write_csv(out, rungs)
    assert read_csv(out) == rungs
