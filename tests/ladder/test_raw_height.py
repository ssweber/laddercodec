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
from laddercodec.csv.writer import (
    WriterError,
    _validate_roundtrip,
    decoded_rung_to_rows,
    write_csv,
)
from laddercodec.instructions import (
    AfInstruction,
    Coil,
    Email,
    Home,
    PinnedInstruction,
    Position,
    RawInstruction,
    Velocity,
)
from laddercodec.instructions.raw import find_blob_boundary
from laddercodec.model import FieldError, InstructionType
from laddercodec.topology import GRID_FIRST_ROW_START, PROGRAM_HEADER_BASE
from tests.fixtures_refused import is_refused

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


# ---------------------------------------------------------------------------
# A box stored at another span than its class's stays raw
# ---------------------------------------------------------------------------


def _short_email() -> RawInstruction:
    """An Email box stored at 1 row, as CLICK copies back a pasted 1-row box."""
    return RawInstruction("Email", Email().build_blob(), 1, visual_rows=1, sub_rows=1)


@pytest.mark.parametrize(
    "below", ["NOP", Coil(InstructionType.COIL_OUT, "Y001")], ids=["nop", "coil"]
)
def test_clipboard_short_box_stays_raw(below: object) -> None:
    rung = Rung(2, [["-"] * 31, ["-"] * 31], [_short_email(), below], None, None)
    data = encode(rung)
    assert _af_cells(data)[0] == ("Email", 1, 1)
    (back,) = _rungs(decode(data))
    assert back.logical_rows == 2
    assert isinstance(back.instructions[0], RawInstruction)
    assert back.instructions[0].cell_params() == {}
    assert back.instructions[1] == below
    assert _af_cells(encode(back)) == _af_cells(data)


@pytest.mark.parametrize(("cell_rows", "rows"), [(b"\x01\x01", 1), (b"\x03\x03", 3)])
def test_scr_box_takes_entry_span(cell_rows: bytes, rows: int) -> None:
    # The SCR entry header holds the clipboard cell's +0x09/+0x0A.
    args = ("Email", 0x2737, {}, b"\x01", None, None, cell_rows)
    box = _decode_program._scr_box(*args)
    assert isinstance(box, RawInstruction) == (rows == 1)
    assert _decode_program._infer_af_visual_rows(*args) == rows


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


def test_cell_rows_take_part_in_equality() -> None:
    # Two boxes are equal when they encode the same +0x09/+0x0A.
    blob = _raw_token_of(_typed(V4 / "sweep_search.bin", "Search")).blob
    native = RawInstruction("Search", blob, 1, visual_rows=2, sub_rows=3)
    class_rule = RawInstruction("Search", blob, 1)
    assert native != class_rule
    assert class_rule == RawInstruction("Search", blob, 1, visual_rows=2, sub_rows=2)
    assert class_rule == RawInstruction("Search", blob, 1, visual_rows=2)
    assert native.cell_params() == {"visual_rows": 2, "sub_rows": 3}
    assert class_rule.cell_params() == {"visual_rows": 2}


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


def test_csv_raw_pinned_box_ends_below_its_last_pin() -> None:
    # The span a typed pinned box has (last pin row + 1); the sub-rows it doesn't cover:
    # Tmr 02 03, Cnt 04 03, Drum 04 05, SR 03 02.
    pinned = [af for af in _typed_boxes() if isinstance(af, PinnedInstruction)]
    assert {type(af).__name__ for af in pinned} >= {"Timer", "Counter", "Shift", "Drum"}
    assert any(af.pin_rows[-1] + 1 > len(af.pin_rows) + 1 for af in pinned)
    for af in pinned:
        raw = _raw_token_of(af)
        assert raw.part_count > 1
        assert raw.cell_params() == {"visual_rows": af.pin_rows[-1] + 1}
        assert raw.cell_params()["visual_rows"] == af.cell_params()["visual_rows"]


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
    # A native Search with +0x0A = 3 writes ``rows=2,sub=3`` and reads back as stored.
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
    assert (tmp_path / "out.csv").read_text().count(",rows=2,sub=3,") == 8
    back = read_csv(tmp_path / "out.csv")
    assert [(r.logical_rows, r.conditions, r.instructions) for r in back] == [
        (r.logical_rows, r.conditions, r.instructions) for r in rungs
    ]
    assert all(
        rung.instructions[0].cell_params() == {"visual_rows": 2, "sub_rows": 3} for rung in back
    )
    assert _af_cells(encode(back)) == _af_cells(encode(rungs))


def test_writer_sees_a_raw_height_loss() -> None:
    # The writer's round-trip check compares raw heights: a box that would read back at
    # another height than it encodes fails it.
    blob = _raw_token_of(_typed(V4 / "sweep_search.bin", "Search")).blob
    native = RawInstruction("Search", blob, 1, visual_rows=2, sub_rows=3)
    rows = decoded_rung_to_rows(_rung_of(native, 2))
    token = rows[0][-1]
    assert ",rows=2,sub=3," in token
    stripped = [*rows[0][:-1], token.replace(",rows=2,sub=3,", ",")]
    with pytest.raises(WriterError, match="AF mismatch"):
        _validate_roundtrip(_rung_of(native, 2), [stripped])


@pytest.mark.parametrize(
    ("fields", "visual_rows", "sub_rows"),
    [
        ("", None, None),
        ("rows=3,", 3, None),
        ("sub=2,", None, 2),
        ("rows=4,sub=1,", 4, 1),
        ("rows=32,sub=255,", 32, 255),
    ],
)
def test_raw_token_rows_fields_are_optional(
    fields: str, visual_rows: int | None, sub_rows: int | None
) -> None:
    raw = RawInstruction.from_csv_token(f"raw(Zzz,0x1234,1,{fields}0001=a,0000=)")
    assert (raw.visual_rows, raw.sub_rows) == (visual_rows, sub_rows)
    assert raw.to_csv().startswith("raw(Zzz,0x1234,1,rows=")
    assert RawInstruction.from_csv_token(raw.to_csv()) == raw


@pytest.mark.parametrize(
    ("fields", "match"),
    [
        ("rows=0,", "rows='0' is not a whole number from 1 to 32"),
        ("rows=33,", "rows='33' is not a whole number from 1 to 32"),
        ("sub=0,", "sub='0' is not a whole number from 1 to 255"),
        ("rows=3,sub=256,", "sub='256'"),
        ("rows=x,", "rows='x'"),
        ("rows=,", "rows=''"),
        ("sub=3,rows=3,", "goes right after the part count"),
        ("rows=3,rows=3,", "goes right after the part count"),
        ("0001=a,rows=3,", "goes right after the part count"),
    ],
)
def test_raw_token_rows_fields_refused(fields: str, match: str) -> None:
    with pytest.raises(FieldError, match=match):
        RawInstruction.from_csv_token(f"raw(Zzz,0x1234,1,{fields}0001=a,0000=)")


@pytest.mark.parametrize("cls", [Email, Home, Position, Velocity])
def test_typed_token_refuses_another_height(cls: type[AfInstruction]) -> None:
    token = cls().to_csv()
    assert ",1,rows=3,sub=3," in token
    for same in ("rows=3,sub=3,", "rows=3,", ""):
        cls.from_csv_token(token.replace("rows=3,sub=3,", same))
    for other in ("rows=1,sub=1,", "rows=1,", "sub=2,", "rows=3,sub=1,"):
        with pytest.raises(FieldError, match=rf"is not the {cls.__name__} box's height"):
            cls.from_csv_token(token.replace("rows=3,sub=3,", other))


def test_legacy_hex_token_takes_rows_fields() -> None:
    blob = Email().build_blob()
    legacy = RawInstruction.from_csv_token(f"raw(Email,{blob.hex()})")
    assert legacy.cell_params() == {"visual_rows": 3}
    stated = RawInstruction.from_csv_token(f"raw(Email,{blob.hex()},rows=1,sub=1)")
    assert stated.cell_params() == {}
    assert stated == RawInstruction("Email", blob, 1, visual_rows=1, sub_rows=1)


# ---------------------------------------------------------------------------
# The raw token holds a multi-part box's pin rows
# ---------------------------------------------------------------------------


def _native_files() -> list[Path]:
    """Native clipboard and SCR captures (not goldens, not synthetic ``time_drums.bin``)."""
    return sorted(
        path
        for path in FIXTURES.rglob("*")
        if path.name.endswith((".bin", ".bin.gz", ".scr"))
        and "golden" not in path.parts
        and path.name != "time_drums.bin"
        and not is_refused(path)
    )


def _forced_raw_rungs(path: Path) -> list[Rung]:
    if path.suffix == ".scr":
        return decode_program(path.read_bytes()).rungs
    return _rungs(decode(_load(path)))


def test_native_pin_rows_round_trip_through_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_decode, "parse_af_blob", lambda raw: None)
    monkeypatch.setattr(_decode_program, "_scr_af", lambda *args: None)
    boxes = moved = 0
    for path in _native_files():
        rungs = [
            rung
            for rung in _forced_raw_rungs(path)
            if any(isinstance(af, RawInstruction) and af.part_count > 1 for af in rung.instructions)
        ]
        if not rungs:
            continue
        for af in (af for rung in rungs for af in rung.instructions):
            if not (isinstance(af, RawInstruction) and af.part_count > 1):
                continue
            boxes += 1
            pins = _decode_blob_pins(af.blob)
            moved += pins != bytes(range(1, af.part_count))
            assert f",pins={'/'.join(map(str, pins))}," in af.to_csv()
            back = RawInstruction.from_csv_token(af.to_csv())
            assert back.blob == af.blob
            assert back == af
        out = tmp_path / f"{path.name}.csv"
        write_csv(out, rungs)
        again = read_csv(out)
        assert [r.instructions for r in again] == [r.instructions for r in rungs], path.name
        assert [r.conditions for r in again] == [r.conditions for r in rungs], path.name
    # count_down_or.bin and pins.bin (12 boxes), scr_captures/pins.scr (6), the layoutq
    # captures (5) and the layoutq2 captures (27) move a pin.
    assert moved == 50
    assert boxes > moved


def _decode_blob_pins(blob: bytes) -> bytes:
    from laddercodec.instructions.raw import _decompose_blob

    return _decompose_blob(blob)[3]


def test_raw_token_pins_default_and_height() -> None:
    plain = RawInstruction.from_csv_token("raw(Zzz,0x1234,3,0001=a,0000=)")
    assert _decode_blob_pins(plain.blob) == b"\x01\x02"
    assert plain.cell_params() == {"visual_rows": 3}
    moved = RawInstruction.from_csv_token("raw(Zzz,0x1234,3,pins=1/3,0001=a,0000=)")
    assert _decode_blob_pins(moved.blob) == b"\x01\x03"
    assert moved.cell_params() == {"visual_rows": 4}
    assert moved.to_csv() == "raw(Zzz,0x1234,3,rows=4,sub=4,pins=1/3,0001=a,0000=)"
    assert moved != plain
    one = RawInstruction.from_csv_token("raw(Zzz,0x1234,1,0001=a,0000=)")
    assert "pins=" not in one.to_csv()


@pytest.mark.parametrize(
    ("token", "match"),
    [
        ("raw(Zzz,0x1234,3,pins=1,0000=)", "must hold 2 rows"),
        ("raw(Zzz,0x1234,3,pins=1/2/3,0000=)", "must hold 2 rows"),
        ("raw(Zzz,0x1234,3,pins=0/2,0000=)", "not a whole number from 1 to 31"),
        ("raw(Zzz,0x1234,3,pins=1/32,0000=)", "not a whole number from 1 to 31"),
        ("raw(Zzz,0x1234,3,pins=1/x,0000=)", "not a whole number from 1 to 31"),
        ("raw(Zzz,0x1234,3,pins=1/,0000=)", "not a whole number from 1 to 31"),
        ("raw(Zzz,0x1234,3,pins=3/3,0000=)", "must ascend"),
        ("raw(Zzz,0x1234,3,pins=3/1,0000=)", "must ascend"),
        ("raw(Zzz,0x1234,1,pins=1,0000=)", "only for a box of 2 or more parts"),
        ("raw(Zzz,0x1234,3,pins=1/2,rows=3,0000=)", "goes right after the part count"),
        ("raw(Zzz,0x1234,3,0001=a,pins=1/2,0000=)", "goes right after the part count"),
        ("raw(Zzz,0x1234,3,rows=3,sub=3,pins=1/3,0000=)", r"rows=3 does not fit pins=1/3"),
        ("raw(Zzz,0x1234,3,rows=4,0000=)", r"rows=4 does not fit no pins="),
        ("raw(Email,4142,pins=1)", "can't follow the hex"),
    ],
)
def test_raw_token_pins_refused(token: str, match: str) -> None:
    with pytest.raises(FieldError, match=match):
        RawInstruction.from_csv_token(token)


def test_typed_token_refuses_pins() -> None:
    token = Email().to_csv().replace("rows=3,sub=3,", "rows=3,sub=3,pins=1,")
    with pytest.raises(FieldError, match="only for a box of 2 or more parts"):
        Email.from_csv_token(token)


def test_raw_token_pins_need_their_rows_in_the_rung() -> None:
    # The reader pads the rung to the box's span, one row below its last pin.
    rung = _csv_rung("raw(Zzz,0x1234,3,pins=1/5,0001=a,0000=)")
    assert rung.logical_rows == 6


@pytest.mark.parametrize(("extra", "rows"), [(b"\x02\x01", None), (b"\x01\x02", 5)])
def test_raw_box_the_fields_form_refuses_writes_hex(extra: bytes, rows: int | None) -> None:
    from laddercodec.binary_helpers import _STANDARD_SENTINEL
    from laddercodec.instructions.raw import _compose_blob

    blob = _compose_blob("Zzz", 0x1234, 3, extra, [(0x0001, _STANDARD_SENTINEL, "a")])
    raw = RawInstruction("Zzz", blob, 3, visual_rows=rows)
    token = raw.to_csv()
    assert token.startswith(f"raw(Zzz,{blob.hex()},rows=")
    assert RawInstruction.from_csv_token(token) == raw


# ---------------------------------------------------------------------------
# A raw box whose field values the token can't carry is written as hex
# ---------------------------------------------------------------------------

_VALUES_TOKEN_CANT_CARRY = [
    "MAX ( DS1 , 100 )",  # the Math form of the native captures; a comma splits the token
    "a,b",
    'a,"',
    '"',
    '"a',
    'a"',
    ' "',
    'a"b',
    "trail ",
    " ",
    "\t",
    "a\nb",
    "a\r\nb",
]
_VALUES_TOKEN_CARRIES = ["", "100 )", "(a", "a=b", " lead", "é", "rows=3", "x:y", '"a,b"']


def _field_box(value: str, last: bool = False) -> RawInstruction:
    """A Math box with *value* in its first field, or in its last when *last*."""
    from laddercodec.binary_helpers import _STANDARD_SENTINEL
    from laddercodec.instructions.raw import _compose_blob

    fields = [(0x6065, _STANDARD_SENTINEL, value), (0x11FE, _STANDARD_SENTINEL, "0")]
    if last:
        fields.reverse()
    return RawInstruction("Math", _compose_blob("Math", 0x271A, 1, b"", fields), 1)


@pytest.mark.parametrize("last", [False, True])
@pytest.mark.parametrize("value", _VALUES_TOKEN_CANT_CARRY)
def test_raw_field_value_the_token_cant_carry_is_written_as_hex(
    tmp_path: Path, value: str, last: bool
) -> None:
    box = _field_box(value, last)
    assert box.to_csv() == f"raw(Math,{box.blob.hex()},rows=1,sub=1)"
    assert RawInstruction.from_csv_token(box.to_csv()) == box
    out = tmp_path / "x.csv"
    write_csv(out, [Rung(1, [["-"] * 31], [box], None, None)])
    (back,) = read_csv(out)
    assert back.instructions == [box]
    assert back.instructions[0].blob == box.blob


@pytest.mark.parametrize("last", [False, True])
@pytest.mark.parametrize("value", _VALUES_TOKEN_CARRIES)
def test_raw_field_value_the_token_carries_stays_in_the_fields_form(
    tmp_path: Path, value: str, last: bool
) -> None:
    box = _field_box(value, last)
    assert box.to_csv().startswith("raw(Math,0x271a,1,rows=1,sub=1,")
    out = tmp_path / "x.csv"
    write_csv(out, [Rung(1, [["-"] * 31], [box], None, None)])
    (back,) = read_csv(out)
    assert back.instructions[0].blob == box.blob


def test_native_raw_math_with_a_comma_in_a_field_round_trips_through_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_decode, "parse_af_blob", lambda raw: None)
    cases = [(V4 / "math.bin", (21, 22, 23)), (V4 / "math_typed.bin", (1,))]
    for path, numbers in cases:
        rungs = _rungs(decode(_load(path)))
        for number in numbers:
            rung = rungs[number - 1]
            out = tmp_path / f"{path.stem}_{number}.csv"
            write_csv(out, [rung])
            (back,) = read_csv(out)
            assert back.instructions == rung.instructions


def test_forced_raw_sweep_round_trips_every_native_rung(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_decode, "parse_af_blob", lambda raw: None)
    monkeypatch.setattr(_decode_program, "_scr_af", lambda *args: None)
    failures = []
    for path in _native_files():
        rungs = _forced_raw_rungs(path)
        out = tmp_path / f"{path.name}.csv"
        for number, rung in enumerate(rungs, 1):
            try:
                write_csv(out, [rung])
                back = read_csv(out)
            except Exception as err:  # noqa: BLE001 - report every failing rung
                failures.append(f"{path.name} #{number}: {err}"[:150])
                continue
            if [r.instructions for r in back] != [rung.instructions]:
                failures.append(f"{path.name} #{number}: instructions differ")
    assert failures == []
