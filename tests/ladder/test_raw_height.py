"""A raw AF box has the height of the native cell it came from, or of its typed class.

The cell header holds a box's row span at +0x09 and its sub-rows at +0x0A.  A box the
decoders leave raw keeps the native bytes (the SCR entry header holds the same two
bytes); a raw box read from CSV takes its typed class's height.
"""

from __future__ import annotations

import gzip
import importlib
import struct
from pathlib import Path

import pytest

from laddercodec import Rung, decode, decode_program, encode, read_csv
from laddercodec.csv.converter import convert_rung
from laddercodec.csv.parser import _parse_single_rung_rows
from laddercodec.csv.writer import decoded_rung_to_rows, write_csv
from laddercodec.instructions import AfInstruction, PinnedInstruction, RawInstruction
from laddercodec.instructions.raw import find_blob_boundary
from laddercodec.model import FieldError
from laddercodec.topology import GRID_FIRST_ROW_START, PROGRAM_HEADER_BASE

_decode = importlib.import_module("laddercodec.decode")
_decode_program = importlib.import_module("laddercodec.decode_program")

FIXTURES = Path(__file__).parents[1] / "fixtures"
V4 = FIXTURES / "v4_captures"

#: Native clipboard captures holding every tall fixed-height class: the Copy family,
#: Search, Send, Receive and the Out variants (v4 sweeps), plus SCR's coverage pair.
CAPTURES = [
    V4 / "sweep_copy.bin",
    V4 / "sweep_search.bin",
    V4 / "sweep_comm.bin",
    V4 / "sweep_coil.bin",
    V4 / "out.bin",
    V4 / "math.bin",
    V4 / "pins.bin",
    FIXTURES / "scr_captures" / "coverage.bin",
    FIXTURES / "tumbler" / "main.clipboard.bin",
]

#: Native SCR files and their clipboard copies (``time_drums.bin`` is synthetic).
SCR_PAIRS = [
    ("coverage.scr", "coverage.bin"),
    ("counter_scr.scr", "counter_scr.bin"),
    ("shift_scr.scr", "shift_scr.bin"),
    ("time_drum_insert_rows.scr", "time_drum_insert_rows.bin"),
    ("rungs_266.scr", "rungs_266.bin.gz"),
]


def _load(path: Path) -> bytes:
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


def _af_cells(data: bytes) -> list[tuple[str, int, int]]:
    """``(class_name, +0x09, +0x0A)`` of every AF instruction cell, in grid order."""
    row_word = struct.unpack_from("<I", data, PROGRAM_HEADER_BASE)[0]
    _rtf, payload_len = _decode._read_rung0_comment(data)
    infos, _ = _decode._walk_grid(data, GRID_FIRST_ROW_START + payload_len, row_word // 0x20)
    cells = []
    for tag, cursor, _ in infos:
        if tag != _decode._DATA:
            continue
        pos, end, has_instr = _decode._walk_row_cells(data, cursor)[31]
        if has_instr:
            class_name, _, _ = find_blob_boundary(bytes(data[pos + 0x25 : end]))
            cells.append((class_name, data[pos + 0x09], data[pos + 0x0A]))
    return cells


def _rungs(decoded: Rung | list[Rung]) -> list[Rung]:
    return decoded if isinstance(decoded, list) else [decoded]


def _all_raw(rungs: list[Rung]) -> bool:
    return all(
        isinstance(af, RawInstruction)
        for rung in rungs
        for af in rung.instructions
        if isinstance(af, AfInstruction)
    )


def _csv_rung(token: str) -> Rung:
    """The rung a CSV row of ``A..AE`` wires and *token* in AF reads back as."""
    logical_rows, conditions, instructions, comment = convert_rung(
        _parse_single_rung_rows([["R", *["-"] * 31, token]])
    )
    return Rung(logical_rows, conditions, instructions, comment, None)


def _raw_token_of(af: AfInstruction) -> RawInstruction:
    """The raw box a CSV file holds for *af*'s blob."""
    blob = af.build_blob()
    class_name, _, part_count = find_blob_boundary(blob + bytes(16))
    raw = _csv_rung(RawInstruction(class_name, blob, part_count).to_csv()).instructions[0]
    assert isinstance(raw, RawInstruction)
    return raw


# ---------------------------------------------------------------------------
# Decoded raw boxes keep the native bytes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", CAPTURES, ids=lambda p: p.name)
def test_clipboard_raw_reencodes_native_row_bytes(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    native = _load(path)
    monkeypatch.setattr(_decode, "parse_af_blob", lambda raw: None)
    rungs = _rungs(decode(native))
    assert _all_raw(rungs)
    assert _af_cells(encode(rungs)) == _af_cells(native)


@pytest.mark.parametrize(("scr", "clipboard"), SCR_PAIRS, ids=[s for s, _ in SCR_PAIRS])
def test_scr_raw_takes_entry_row_bytes(
    scr: str, clipboard: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    native = _load(FIXTURES / "scr_captures" / clipboard)
    monkeypatch.setattr(_decode_program, "_scr_af", lambda *args: None)
    rungs = decode_program((FIXTURES / "scr_captures" / scr).read_bytes()).rungs
    assert _all_raw(rungs)
    assert _af_cells(encode(rungs)) == _af_cells(native)


def test_tall_classes_are_in_the_captures() -> None:
    seen = {cell for path in CAPTURES for cell in _af_cells(_load(path))}
    for cell in [
        ("Copy", 2, 2),
        ("Search", 2, 2),
        ("Search", 2, 3),
        ("SD", 3, 3),
        ("RD", 3, 3),
        ("Out", 3, 3),
        ("Out", 2, 3),
        ("Math", 1, 3),
        *((name, 3, 3) for name in ("Email", "Home", "Position", "Velocity")),
    ]:
        assert cell in seen


def test_cell_rows_take_no_part_in_equality() -> None:
    blob = _raw_token_of(_typed(V4 / "sweep_search.bin", "Search")).blob
    native = RawInstruction("Search", blob, 1, visual_rows=2, sub_rows=3)
    from_csv = RawInstruction("Search", blob, 1)
    assert native == from_csv
    assert native.cell_params() == {"visual_rows": 2, "sub_rows": 3}
    assert from_csv.cell_params() == {"visual_rows": 2}


@pytest.mark.parametrize("bad", [0, 256, -1, True, "2", 2.0])
def test_cell_rows_refused(bad: object) -> None:
    with pytest.raises(FieldError, match="RawInstruction.visual_rows"):
        RawInstruction("Zzz", b"", visual_rows=bad)  # type: ignore[arg-type]
    with pytest.raises(FieldError, match="RawInstruction.sub_rows"):
        RawInstruction("Zzz", b"", sub_rows=bad)  # type: ignore[arg-type]


def test_sub_rows_default_to_the_given_span() -> None:
    assert RawInstruction("Zzz", b"", visual_rows=3).cell_params() == {"visual_rows": 3}
    assert RawInstruction("Zzz", b"", visual_rows=1, sub_rows=1).cell_params() == {}


# ---------------------------------------------------------------------------
# Raw boxes read from CSV take the typed class's height
# ---------------------------------------------------------------------------


def _typed_boxes() -> list[AfInstruction]:
    boxes = []
    for path in CAPTURES:
        for rung in _rungs(decode(_load(path))):
            boxes += [
                af
                for af in rung.instructions
                if isinstance(af, AfInstruction) and not isinstance(af, RawInstruction)
            ]
    return boxes


def _typed(path: Path, class_name: str) -> AfInstruction:
    for rung in _rungs(decode(_load(path))):
        for af in rung.instructions:
            if isinstance(af, AfInstruction) and not isinstance(af, RawInstruction):
                if find_blob_boundary(af.build_blob() + bytes(16))[0] == class_name:
                    return af
    raise AssertionError(f"no {class_name} in {path.name}")


def test_csv_raw_takes_typed_height() -> None:
    # A regression lock on the class rule (raw matches typed), not native ground truth.
    # Native cells it does not cover: Math 01 03 and some Search 02 03 (typed 02 02).
    kinds: set[str] = set()
    for af in _typed_boxes():
        if isinstance(af, PinnedInstruction):
            continue
        try:
            raw = _raw_token_of(af)
        except ValueError:
            # A raw token of a formula with a comma in it does not read back.
            assert type(af).__name__ == "Math"
            continue
        assert raw.cell_params() == af.cell_params(), af.to_csv()
        if af.cell_params():
            kinds.add(f"{type(af).__name__}:{getattr(af, 'kind', '')}")
    assert kinds >= {
        "Copy:",
        "BlockCopy:",
        "Search:",
        "Send:",
        "Receive:",
        "OutVariant:debounce",
        "OutVariant:flasher",
        "OutVariant:timed",
        "Email:",
        "Home:",
        "Position:",
        "Velocity:",
    }


def test_csv_raw_pinned_box_spans_its_part_count() -> None:
    # A regression lock on the part-count rule, not native ground truth.  Native cells it
    # does not cover: Tmr 02 03, Drum 04 05, SR 03 02, and pinned boxes whose OR legs
    # grow the box (Cnt 04 03 to 0A 03, Drum 05 04, SR 04 03).
    pinned = [af for af in _typed_boxes() if isinstance(af, PinnedInstruction)]
    assert {type(af).__name__ for af in pinned} >= {"Timer", "Counter", "Shift", "Drum"}
    for af in pinned:
        raw = _raw_token_of(af)
        assert raw.part_count > 1
        assert raw.cell_params() == {"visual_rows": raw.part_count}


def test_raw_out_with_unknown_func_code_is_one_row() -> None:
    out = _raw_token_of(_typed(V4 / "out.bin", "Out"))
    token = out.to_csv()
    func = next(spec for spec in token[4:-1].split(",") if spec.startswith("3218="))
    unknown = RawInstruction.from_csv_token(token.replace(func, "3218=9999"))
    assert unknown.cell_params() == {}


@pytest.mark.parametrize(
    "class_name", ["Copy", "Search", "SD", "RD", "Email", "Home", "Position", "Velocity"]
)
def test_csv_raw_pads_rung_as_typed(class_name: str) -> None:
    # A regression lock on the class rule (raw pads as typed), not native ground truth.
    # Native cells it does not cover: some Search 02 03 (typed and raw rule 02 02).
    path = {
        "Copy": V4 / "sweep_copy.bin",
        "Search": V4 / "sweep_search.bin",
        "SD": V4 / "sweep_comm.bin",
        "RD": V4 / "sweep_comm.bin",
    }.get(class_name, FIXTURES / "scr_captures" / "coverage.bin")
    typed = _typed(path, class_name)
    raw_rung = _csv_rung(_raw_token_of(typed).to_csv())
    typed_rung = _csv_rung(typed.to_csv())
    assert raw_rung.logical_rows == typed_rung.logical_rows > 1
    span = typed.cell_params()["visual_rows"]
    assert _af_cells(encode(raw_rung)) == [(class_name, span, span)]


# ---------------------------------------------------------------------------
# The CSV writer lays out a raw tall box as the typed one
# ---------------------------------------------------------------------------


def _rung_of(af: AfInstruction, rows: int) -> Rung:
    return Rung(
        logical_rows=rows,
        conditions=[["-"] * 31, *[[""] * 31 for _ in range(rows - 1)]],
        instructions=[af, *[""] * (rows - 1)],
        comment=None,
        comment_rtf=None,
    )


@pytest.mark.parametrize("class_name", ["Copy", "Search", "SD", "Out"])
def test_writer_lays_out_raw_as_typed(class_name: str) -> None:
    path = {"Copy": "sweep_copy.bin", "Search": "sweep_search.bin", "SD": "sweep_comm.bin"}
    typed = (
        next(af for af in _typed_boxes() if getattr(af, "kind", "") == "debounce")
        if class_name == "Out"
        else _typed(V4 / path[class_name], class_name)
    )
    rows = typed.cell_params()["visual_rows"]
    typed_rows = decoded_rung_to_rows(_rung_of(typed, rows))
    raw_rows = decoded_rung_to_rows(_rung_of(_raw_token_of(typed), rows))
    assert len(raw_rows) == len(typed_rows) == 1
    assert [row[:-1] for row in raw_rows] == [row[:-1] for row in typed_rows]


def test_writer_keeps_native_sub_rows_raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A native Search with +0x0A = 3 writes and reads back; the CSV holds no sub-rows.
    native = _load(FIXTURES / "scr_captures" / "coverage.bin")
    monkeypatch.setattr(_decode, "parse_af_blob", lambda raw: None)
    rungs = [
        rung
        for rung in _rungs(decode(native))
        if any(getattr(af, "class_name", "") == "Search" for af in rung.instructions)
    ]
    assert len(rungs) == 8
    assert all(
        rung.instructions[0].cell_params() == {"visual_rows": 2, "sub_rows": 3} for rung in rungs
    )
    write_csv(tmp_path / "out.csv", rungs)
    back = read_csv(tmp_path / "out.csv")
    assert [(r.logical_rows, r.conditions, r.instructions) for r in back] == [
        (r.logical_rows, r.conditions, r.instructions) for r in rungs
    ]
    assert all(rung.instructions[0].cell_params() == {"visual_rows": 2} for rung in back)
