"""CLICK v4 captures: every labelled rung's comment says what it should decode to.

Each ``fixtures/v4_captures/<group>.bin`` is a multi-rung copy-back from CLICK v4.
The stubs are built with pyrung by ``scratchpad/click-v4/captures/v4_capture.py``;
a labelled rung's comment is

    line 1      the rung id
    line 2..n   every non-empty AF cell, in row order, as laddercodec should decode it

A rung whose AF still decodes to ``raw(...)`` is an expected failure (not supported yet).
Any other difference fails.  Rungs without a two-line comment (formulas typed straight
into CLICK, ``math_typed.bin``) are only used by the blob tests below.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from laddercodec import encode, read_csv
from laddercodec.binary_helpers import _parse_tagged_fields_verbose
from laddercodec.csv.writer import WriterError, decoded_rung_to_rows, write_csv
from laddercodec.decode import Rung, decode, inspect_cells
from laddercodec.instructions.counter import Counter
from laddercodec.instructions.drum import Drum
from laddercodec.instructions.forloop import Break, Continue
from laddercodec.instructions.math import Math
from laddercodec.instructions.out_variant import OutVariant
from laddercodec.instructions.raw import _decompose_blob
from laddercodec.instructions.shift import Shift

CAPTURE_DIR = Path(__file__).parent / "fixtures" / "v4_captures"
COVERAGE_GOLDEN = Path(__file__).parent / "fixtures" / "coverage" / "golden"


def _decode_file(path: Path) -> list[Rung]:
    decoded = decode(path.read_bytes())
    return decoded if isinstance(decoded, list) else [decoded]


def _load_labelled() -> list[tuple[str, Rung]]:
    cases: list[tuple[str, Rung]] = []
    for bin_path in sorted(CAPTURE_DIR.glob("*.bin")):
        for rung in _decode_file(bin_path):
            lines = (rung.comment or "").split("\n")
            if len(lines) > 1:
                cases.append((f"{bin_path.stem}:{lines[0]}", rung))
    return cases


_LABELLED = _load_labelled()


def _leg_on_unused_pin_row(rung: Rung) -> bool:
    """A pinned box whose unused pin's row holds a leg of the pin above.

    CLICK leaves that layout when a leg is drawn into the row an unused pin
    already has, instead of an inserted one.  CSV can't express it: on read,
    an unused pin's row goes below the legs.
    """
    af = rung.instructions[0]
    if not isinstance(af, Drum):
        return False
    used = (True, af.jump_enabled, af.jog_enabled)
    return any(
        not on and any(c != "" for c in rung.conditions[row])
        for row, on in zip(af.pin_rows, used, strict=True)
    )


@pytest.mark.parametrize("rung", [r for _, r in _LABELLED], ids=[cid for cid, _ in _LABELLED])
def test_rung_decodes_to_its_comment(rung: Rung) -> None:
    expected = (rung.comment or "").split("\n")[1:]
    if _leg_on_unused_pin_row(rung):
        with pytest.raises(WriterError):
            decoded_rung_to_rows(rung)
        return
    rows = decoded_rung_to_rows(rung)
    af_tokens = [row[-1] for row in rows if row[0] != "#" and row[-1]]
    if any(token.startswith("raw(") for token in af_tokens):
        pytest.xfail(f"not decoded yet: {af_tokens}")
    assert af_tokens == expected


@pytest.mark.parametrize("bin_path", sorted(CAPTURE_DIR.glob("*.bin")), ids=lambda p: p.stem)
def test_capture_writes_csv(bin_path: Path, tmp_path: Path) -> None:
    """write_csv's round-trip check passes, raw(...) rungs included (multi-part raw extras)."""
    rungs = [r for r in _decode_file(bin_path) if not _leg_on_unused_pin_row(r)]
    write_csv(tmp_path / f"{bin_path.stem}.csv", rungs)


# ---------------------------------------------------------------------------
# Math blobs CLICK wrote itself (typed or re-saved in the editor)
# ---------------------------------------------------------------------------

_SLOT_TAGS = (0x6888, 0x688C)

#: (file, rung index) of formulas whose blob CLICK's editor wrote.  The other rungs of
#: math.bin still carry the text laddercodec pasted.
_NATIVE_MATH = [
    *(("math.bin", i) for i in range(17, 23)),  # math__abs_ds .. math__rand_hex
    ("math_typed.bin", 0),  # RAND ( 1 , 10 ) + DS1
    ("math_typed.bin", 1),  # MAX ( DS1 : DS3 ) + SUM ( DS5 : DS8 )
    # Negative operands, all typed: ( -5 ) is stored H-5 and ( -2.5 ) F-2.5.  Rung 8,
    # DS401 * ( - DS402 ), fails CLICK's check even typed; its fields still match.
    # In retyped/ because retyping changed some results and comments, so the rung
    # comments no longer name the token.
    *(("retyped/math_neg.bin", i) for i in range(12)),
]


def _blob_fields(blob: bytes) -> tuple[list[tuple[int, str]], dict[tuple[int, int], str]]:
    """Header fields in order, and filled indexed slots, of a Math blob."""
    start = blob.index("Math".encode("utf-16-le") + b"\x00\x00") + 10
    count = struct.unpack_from("<I", blob, start + 6)[0]
    fields, _ = _parse_tagged_fields_verbose(blob, start + 10, count)
    header = [(tag, value) for tag, _, value in fields if tag not in _SLOT_TAGS]
    slots = {
        (tag, struct.unpack("<I", sentinel)[0]): value
        for tag, sentinel, value in fields
        if tag in _SLOT_TAGS and value
    }
    return header, slots


def _native_math_blobs(path: Path) -> list[bytes]:
    buf = path.read_bytes()
    needle = "Math".encode("utf-16-le") + b"\x00\x00"
    starts = []
    i = -1
    while (i := buf.find(needle, i + 1)) != -1:
        starts.append(i)
    return [
        buf[s : (starts[k + 1] if k + 1 < len(starts) else len(buf))] for k, s in enumerate(starts)
    ]


@pytest.mark.parametrize(("file", "index"), _NATIVE_MATH, ids=[f"{f}:{i}" for f, i in _NATIVE_MATH])
def test_math_blob_fields_match_native(file: str, index: int) -> None:
    """Every field Click writes matches, slot capacity aside (v4 copies back 5000 reserved)."""
    path = CAPTURE_DIR / file
    rung = _decode_file(path)[index]
    math = next(token for token in rung.instructions if isinstance(token, Math))
    native_header, native_slots = _blob_fields(_native_math_blobs(path)[index])
    header, slots = _blob_fields(math.build_blob())
    assert header == native_header
    assert slots == native_slots


def test_out_variant_blobs_match_native() -> None:
    """Every toggle/debounce/flasher/timed CLICK wrote re-encodes to the same blob bytes."""
    buf = (CAPTURE_DIR / "out.bin").read_bytes()
    variants = [
        token
        for rung in _decode_file(CAPTURE_DIR / "out.bin")
        for token in rung.instructions
        if isinstance(token, OutVariant)
    ]
    needle = "Out".encode("utf-16-le") + b"\x00\x00"
    starts = []
    i = -1
    while (i := buf.find(needle, i + 1)) != -1:
        starts.append(i)
    assert len(variants) == len(starts) == 18
    for variant, start in zip(variants, starts, strict=True):
        blob = variant.build_blob()
        assert buf[start : start + len(blob)] == blob, variant.to_csv()


def test_time_event_drum_blobs_match_native() -> None:
    """Every time & event drum CLICK wrote re-encodes field for field, 0x428A aside.

    0x428A is unexplained: Click wrote -1 for four drums and -2 for drum__te_ds;
    the encoder writes -1, which Click also fills in for a pasted drum lacking it.
    """
    buf = (CAPTURE_DIR / "drum.bin").read_bytes()
    drums = [
        token
        for rung in _decode_file(CAPTURE_DIR / "drum.bin")
        for token in rung.instructions
        if isinstance(token, Drum)
    ]
    needle = "Drum".encode("utf-16-le") + b"\x00\x00"
    starts = []
    i = -1
    while (i := buf.find(needle, i + 1)) != -1:
        starts.append(i)
    checked = 0
    for drum, start in zip(drums, starts, strict=True):
        if drum.drum_kind != "time_event":
            continue
        blob = drum.build_blob()
        *head, native_fields = _decompose_blob(buf[start : start + len(blob)])
        *encoded_head, fields = _decompose_blob(blob)
        assert encoded_head == head
        assert [f for f in fields if f[0] != 0x428A] == [
            f for f in native_fields if f[0] != 0x428A
        ], drum.to_csv()
        checked += 1
    assert checked == 5


def test_drum_func_codes_match_native() -> None:
    """Drum func codes run consecutively over the enabled pins.

    ``drum_jog.bin``: event Reset + Jog, time (ms) Reset + Jog, event Reset + Jump, each
    reopened and OK'd in CLICK v4.  With Jump off, Jog takes Jump's code (8496, 8460);
    the next code up passes a paste but fails v4's check with C000A.
    """
    buf = (CAPTURE_DIR / "drum_jog.bin").read_bytes()
    drums = [r.instructions[0] for r in _decode_file(CAPTURE_DIR / "drum_jog.bin")]
    needle = "Drum".encode("utf-16-le") + b"\x00\x00"
    starts = []
    i = -1
    while (i := buf.find(needle, i + 1)) != -1:
        starts.append(i)
    codes = []
    for drum, start in zip(drums, starts, strict=True):
        assert isinstance(drum, Drum)
        *_, native_fields = _decompose_blob(buf[start:])
        *_, fields = _decompose_blob(drum.build_blob())
        native = [f for f in native_fields if f[0] == 0x3A05]
        assert [f for f in fields if f[0] == 0x3A05] == native, drum.to_csv()
        codes.append([f[2] for f in native])
    assert codes == [
        ["8494", "8495", "0", "8496"],
        ["8458", "8459", "0", "8460"],
        ["8491", "8492", "8493", "0"],
    ]


#: Each pin's row in pins.bin, built in CLICK from ``stubs/pins.csv``.  drum_reset_or3 was
#: built as C1059 OR (C1060 AND C1061): its one leg row sits on the unused jump pin's row.
_PIN_ROWS = {
    "pins__drum_reset_or": (1, 3, 4),
    "pins__drum_reset_or3": (1, 2, 3),
    "pins__drum_jump_or": (1, 2, 4),
    "pins__drum_all_or": (1, 3, 5),
    "pins__count_up_down_or": (1, 3),
    "pins__shift_clock_or": (1, 3),
}


def _af_cell_shape(data: bytes, rung: int) -> tuple[int, int, bytes]:
    """Row 0 AF cell of a rung: ``(+0x09 rows spanned, +0x0A sub-rows, part bytes)``."""
    cell = inspect_cells(data, [(rung, 0, "AF")])[0]
    _, _, _, extra, _ = _decompose_blob(cell.raw[0x25:-0x10])
    return cell.raw[0x09], cell.raw[0x0A], extra


def test_pin_rows_reencode_like_native() -> None:
    """OR legs under a pin push the later pins down: the part bytes hold each pin's row,
    +0x09 grows to the last pin's row + 1, and +0x0A keeps the base height."""
    native = (CAPTURE_DIR / "pins.bin").read_bytes()
    rungs = _decode_file(CAPTURE_DIR / "pins.bin")
    assert len(rungs) == len(_PIN_ROWS)
    encoded = encode(rungs)
    for index, rung in enumerate(rungs):
        rung_id = (rung.comment or "").split("\n")[0]
        af = rung.instructions[0]
        assert isinstance(af, (Counter, Drum, Shift))
        assert af.pin_rows == _PIN_ROWS[rung_id], rung_id
        assert _af_cell_shape(encoded, index) == _af_cell_shape(native, index), rung_id


def test_pin_rows_from_pyrung_csv() -> None:
    """pyrung's export (pin under its legs) reads back to the rows CLICK gave them."""
    rungs = read_csv(COVERAGE_GOLDEN / "pins__v4.csv")
    for rung in rungs:
        rung_id = (rung.comment or "").split("\n")[0]
        if rung_id == "pins__drum_reset_or3":  # two leg rows in pyrung's form
            continue
        af = rung.instructions[0]
        assert isinstance(af, (Counter, Drum, Shift))
        assert af.pin_rows == _PIN_ROWS[rung_id], rung_id


def test_loop_exit_blobs_match_native() -> None:
    """Break and Continue are class ``Next`` with func codes 9233 / 9232 (a v4 Next is 9220).

    ``loop_exits.bin`` was typed in CLICK v4: for(1), C1 Break, C2 Continue, Next.
    """
    path = CAPTURE_DIR / "loop_exits.bin"
    buf = path.read_bytes()
    rows = [row for rung in _decode_file(path) for row in decoded_rung_to_rows(rung)]
    assert [(row[1], row[-1]) for row in rows if row[0] != "#"] == [
        ("-", "for(1,oneshot=0)"),
        ("C1", "break()"),
        ("C2", "continue()"),
        ("-", "next()"),
    ]
    needle = "Next".encode("utf-16-le") + b"\x00\x00"
    starts = []
    i = -1
    while (i := buf.find(needle, i + 1)) != -1:
        starts.append(i)
    for exit_token, start in zip((Break(), Continue()), starts[:2], strict=True):
        blob = exit_token.build_blob()
        assert buf[start : start + len(blob)] == blob, exit_token.to_csv()


def test_out_variant_is_not_a_plain_coil() -> None:
    """A debounce (class ``Out``, func code 8226) must not decode as ``out(C1)``."""
    rung = _decode_file(CAPTURE_DIR / "out_debounce_example.bin")[0]
    af = next(token for token in rung.instructions if token not in ("", "NOP"))
    assert isinstance(af, OutVariant)
    assert (
        af.to_csv() == "debounce(C1,on_acc=TD1,on_preset=100,off_acc=TD2,off_preset=100,unit=Tms)"
    )
