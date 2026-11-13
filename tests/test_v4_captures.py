"""CLICK v4 captures: every labelled rung's comment says what it should decode to.

Each ``fixtures/v4_captures/<group>.bin`` is a multi-rung copy-back from CLICK v4.
The stubs are built with pyrung by ``scratchpad/click-v4/captures/v4_capture.py``;
a labelled rung's comment is

    line 1      the rung id
    line 2..n   every non-empty AF cell, in row order, as laddercodec should decode it

A rung whose AF still decodes to ``raw(...)`` is an expected failure (not supported yet).
Any other difference fails.  Rungs without a two-line comment (formulas typed straight
into CLICK, ``math_typed.bin``, ``math_hex_upper_h.bin``, ``math_hex_signed.bin``,
``math_nickname_display.bin``, ``math_unary_plus_pi.bin``,
``math_unary_plus_real.bin``, ``math_ranges_x_t.bin``, ``math_ranges_xy_slots.bin``,
``math_ranges_xy_slots2.bin`` and ``math_ranges_x25_x101.bin``; text constants typed
in CLICK v4, ``text_blank.bin``, ``text_q.bin``, ``text_tt.bin``, ``text_abc.bin``,
``text_dollar_quoted.bin``, ``text_128.bin``, ``text_pointer.bin`` and
``text_compare.bin``; one-phase debounces saved in CLICK v4, ``debounce_one_phase.bin``;
Send and Receive hex addresses typed in CLICK v4, ``comm_hex_address.bin``;
a Call pasted from laddercodec, then saved by its dialog,
``call_index_pasted.bin`` and ``call_index_dialog_ok.bin``; fourteen coverage goldens
pasted from laddercodec, then saved by their dialogs, ``box_height_pasted.bin`` and
``box_height_dialog_ok.bin``; OR legs under a tall box pasted from laddercodec's
padded layout, then rewritten by CLICK's syntax check, ``or_compact_pasted.bin`` and
``or_compact_checked.bin`` (from ``or_compact_stub.csv``), ``r30_tallbox_pasted.bin``
and ``r30_tallbox_checked.bin`` (from pyrung's ``r30_tallbox.csv``)) are only used by
the blob and layout tests below.
"""

from __future__ import annotations

import re
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from laddercodec import FieldError, encode, read_csv
from laddercodec.binary_helpers import _parse_tagged_fields_verbose
from laddercodec.csv.writer import WriterError, decoded_rung_to_rows, write_csv
from laddercodec.decode import Rung, decode, inspect_cells
from laddercodec.instructions import from_tags_af
from laddercodec.instructions.comparison import CompareContact
from laddercodec.instructions.copy import Copy
from laddercodec.instructions.counter import Counter
from laddercodec.instructions.drum import Drum
from laddercodec.instructions.forloop import Break, Continue
from laddercodec.instructions.math import Math, range_interiors
from laddercodec.instructions.math import from_tags as from_tags_math
from laddercodec.instructions.out_variant import OutVariant
from laddercodec.instructions.raw import RawInstruction, _decompose_blob
from laddercodec.instructions.send_receive import ModbusAddress, Receive, Send
from laddercodec.instructions.shift import Shift

CAPTURE_DIR = Path(__file__).parent / "fixtures" / "v4_captures"
COVERAGE_GOLDEN = Path(__file__).parent / "fixtures" / "coverage" / "golden"


def _decode_file(path: Path | bytes) -> list[Rung]:
    """The rungs of a capture file, or of a buffer already read."""
    decoded = decode(path if isinstance(path, bytes) else path.read_bytes())
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
    slip = _BUILT_DIFFERENTLY.get((rung.comment or "").split("\n")[0])
    if slip:
        expected = [token.replace(*slip) for token in expected]
    assert af_tokens == [_current_spelling(token) for token in expected]


#: Build rungs CLICK was given other settings than their comment names: (comment text, built).
_BUILT_DIFFERENTLY: dict[str, tuple[str, str]] = {
    "send__slave_id_ds": ('com_port="cpu2"', 'com_port="cpu3"'),  # built on CPU Port 3
}


def _current_spelling(token: str) -> str:
    """A comment token as write_csv spells it now.

    Comments are baked into captures.  ``to_text`` used to carry both
    ``suppress_zero`` and ``exponential``; it now writes only the source's own.
    """
    if token.startswith("copy(") and "to_text(" in token:
        return Copy.from_csv_token(token).to_csv()
    return token


@pytest.mark.parametrize("bin_path", sorted(CAPTURE_DIR.glob("*.bin")), ids=lambda p: p.stem)
def test_capture_writes_csv(bin_path: Path, tmp_path: Path) -> None:
    """write_csv's round-trip check passes, raw(...) rungs included (multi-part raw extras)."""
    rungs = [r for r in _decode_file(bin_path) if not _leg_on_unused_pin_row(r)]
    write_csv(tmp_path / f"{bin_path.stem}.csv", rungs)


def test_short_box_round_trips_through_csv(tmp_path: Path) -> None:
    """A box stored at 1 row decodes raw, writes ``rows=1,sub=1`` and re-encodes as stored.

    CLICK copies back a 1-row Email, Home, Position or Velocity pasted from an earlier
    laddercodec at 1 row (``box_height_pasted.bin`` rungs 11-14).
    """
    data = (CAPTURE_DIR / "box_height_pasted.bin").read_bytes()
    rungs = _decode_file(data)
    short = rungs[10:14]
    boxes = [r.instructions[0] for r in short]
    assert all(isinstance(box, RawInstruction) for box in boxes)
    assert [getattr(box, "class_name", None) for box in boxes] == [
        "Email",
        "Home",
        "Position",
        "Velocity",
    ]
    write_csv(tmp_path / "pasted.csv", rungs)
    text = (tmp_path / "pasted.csv").read_text(encoding="utf-8")
    assert text.count(",rows=1,sub=1,") == 4
    back = read_csv(tmp_path / "pasted.csv")
    assert [r.logical_rows for r in back[10:14]] == [1, 1, 1, 1]
    assert [r.instructions for r in back[10:14]] == [r.instructions for r in short]
    again = encode(back)
    assert again == encode(rungs)
    for i, box in zip(range(10, 14), boxes, strict=True):
        assert _af_box(again, i) == _af_box(data, i) == (1, 1, 1)
        # Cell header and blob; the last cell's dump runs on into the capture's trailer.
        end = 0x25 + len(box.build_blob())
        (ours,) = inspect_cells(again, [(i, 0, "AF")])
        (native,) = inspect_cells(data, [(i, 0, "AF")])
        assert ours.raw[:end] == native.raw[:end], i + 1


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
    # Typed XD/YD operands: XD0, XD0u, YD1, then MAX ( XD0 : XD3 ).
    *(("retyped/math_xd.bin", i) for i in range(4)),
    # Copy-back of the math_operands stub; only these rungs were typed.  Past 500
    # interiors, up to the 5496 of SUM ( DS1 : DS4500 ) + SUM ( DD1 : DD1000 ).
    *(("retyped/math_wide.bin", i) for i in range(17, 21)),
    # Typed DS1 + ( +5 ) and PI ( 2 ); the rungs after them name formulas the dialog refused.
    ("math_unary_plus_pi.bin", 0),
    ("math_unary_plus_pi.bin", 1),
    ("math_unary_plus_real.bin", 0),  # DS1 + ( +2.5 ), result DF1: stored F+2.5
    # Typed T, TD, X and Y ranges, the X and Y ones across the slot gaps (C2-03CPU, no I/O
    # modules).
    # The other rungs of these files hold ranges laddercodec refuses (REFUSED_XY_RANGES).
    ("math_ranges_x_t.bin", 0),  # SUM ( T1 : T5 )
    ("math_ranges_x_t.bin", 1),  # MAX ( TD1 : TD5 )
    ("math_ranges_x_t.bin", 3),  # SUM ( X001 : X101 )
    ("math_ranges_xy_slots.bin", 0),  # SUM ( X001 : X116 )
    ("math_ranges_xy_slots2.bin", 0),  # SUM ( X001 : X021 )
    ("math_ranges_xy_slots2.bin", 1),  # SUM ( X025 : X026 )
    ("math_ranges_xy_slots2.bin", 3),  # SUM ( X101 : X201 )
    ("math_ranges_xy_slots2.bin", 4),  # SUM ( Y001 : Y116 )
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


def test_math_hex_upper_h_capture() -> None:
    """``math_hex_upper_h.bin``: hex ``DH1 + 7H`` typed in CLICK v4, which stores ``7h``.

    The capture decodes to ``7h``, and ``7H`` built by hand writes the native blob.
    """
    path = CAPTURE_DIR / "math_hex_upper_h.bin"
    (rung,) = _decode_file(path)
    rows = decoded_rung_to_rows(rung)
    assert [row[-1] for row in rows if row[0] != "#" and row[-1]] == ["math(DH1 + 7h,DH1,mode=hex)"]
    typed = Math("DH1 + 7H", "DH1", mode="hex")
    assert rung.instructions[0] == typed
    blob = typed.build_blob()
    assert _native_blob(path.read_bytes(), "Math", len(blob)) == blob


#: Remote address text (0x6085) and its type (0x320F), 1 for hex.
_HEX_ADDRESS_TAGS = (0x6085, 0x320F)


@pytest.mark.parametrize(
    ("index", "typed", "stored"),
    [
        (0, "0H", "0h"),
        (1, "0FFFEh", "FFFEh"),
        (2, "0000Fh", "Fh"),
        (3, "ffeh", "FFEh"),
        (4, "0H", "0h"),
        (5, "0FFFEh", "FFFEh"),
    ],
)
def test_comm_hex_address_capture(index: int, typed: str, stored: str) -> None:
    """``comm_hex_address.bin``: hex remote addresses typed in CLICK v4 for Send and Receive.

    CLICK stores uppercase digits without leading zeros and a lowercase ``h``.  The
    instruction built from the typed text writes the native address fields.  The rest of
    the blob is not compared: CLICK keeps a stale TCP IP in an RTU target and writes one
    0x6889 field per pin row, which the encoder does not (the box-height question, arc.md).
    """
    path = CAPTURE_DIR / "comm_hex_address.bin"
    rung = _decode_file(path)[index]
    native = rung.instructions[0]
    assert isinstance(native, Send if index < 4 else Receive)
    assert native.remote_start.address == stored
    built = replace(native, remote_start=ModbusAddress(typed, "holding"))
    assert built == native
    blob = built.build_blob()
    buf = path.read_bytes()
    starts = [m.start() for m in re.finditer(re.escape(blob[:40]), buf)]
    assert len(starts) == (4 if index < 4 else 2)  # four Sends, two Receives
    at = starts[index % 4]
    got = _decompose_blob(buf[at : at + len(blob)])
    want = _decompose_blob(blob)
    assert got[:3] == want[:3]
    for tag in _HEX_ADDRESS_TAGS:
        assert [f for f in got[4] if f[0] == tag] == [f for f in want[4] if f[0] == tag]


def test_math_unary_plus_and_pi_capture() -> None:
    """``math_unary_plus_pi.bin``: ``DS1 + ( +5 )`` and ``PI ( 2 )`` typed in CLICK v4.

    CLICK joins the ``+`` to its constant (``H+5``) and keeps ``PI ( 2 )`` in call form
    (``PI#(#H2#)``).  The later rungs are NOPs whose comments name formulas the dialog
    refused; ``tests/ladder/test_math_grammar.py`` refuses each.
    """
    rungs = _decode_file(CAPTURE_DIR / "math_unary_plus_pi.bin")
    afs = [
        row[-1]
        for rung in rungs[:2]
        for row in decoded_rung_to_rows(rung)
        if row[0] != "#" and row[-1]
    ]
    assert afs == ["math(DS1 + ( +5 ),DS1,mode=decimal)", "math(PI ( 2 ),DS1,mode=decimal)"]
    assert rungs[0].instructions[0] == Math("DS1 + ( + 5 )", "DS1")
    assert rungs[1].instructions[0] == Math("PI ( 2 )", "DS1")


def test_math_nickname_display_capture() -> None:
    """``math_nickname_display.bin``: ``<Test Nickname> + 1`` typed in CLICK v4 for DS3.

    CLICK keeps the nickname in the display text only; the formula holds ``DS3``, so the
    capture decodes to the address form.
    """
    (rung,) = _decode_file(CAPTURE_DIR / "math_nickname_display.bin")
    rows = decoded_rung_to_rows(rung)
    assert [row[-1] for row in rows if row[0] != "#" and row[-1]] == [
        "math(DS3 + 1,DS1,mode=decimal)"
    ]


def test_math_hex_signed_capture() -> None:
    """``math_hex_signed.bin``: ``DH1 + ( -Ah )`` typed in a hex Math in CLICK v4.

    CLICK redisplays ``( - Ah )`` and stores ``DH1#+#(#-#UH10#)``: the sign is its own token.
    """
    path = CAPTURE_DIR / "math_hex_signed.bin"
    (rung,) = _decode_file(path)
    rows = decoded_rung_to_rows(rung)
    assert [row[-1] for row in rows if row[0] != "#" and row[-1]] == [
        "math(DH1 + ( - Ah ),DH1,mode=hex)"
    ]
    typed = Math("DH1 + ( -Ah )", "DH1", "hex")
    assert rung.instructions[0] == typed
    # CLICK v4 copies back 5000 reserved slots; the fields are what must match.
    native_header, native_slots = _blob_fields(_native_math_blobs(path)[0])
    header, slots = _blob_fields(typed.build_blob())
    assert header == native_header
    assert slots == native_slots


@pytest.mark.parametrize(("typed", "display"), [("0fH", "Fh"), ("EH", "Eh"), ("fh", "Fh")])
def test_math_hex_constant_display_form(typed: str, display: str) -> None:
    assert Math(f"DH1 + {typed}", "DH1", "hex").expression == f"DH1 + {display}"


def test_math_with_nickname_display_text_decodes_as_raw() -> None:
    """Empty template and internal formula leave only the display text, which holds a nickname."""
    tags = {0x6065: "DS1", 0x61FF: "", 0x61FD: "", 0x6228: "<Test Nickname> + 1", 0x3218: "8451"}
    assert from_tags_math("Math", 0x271A, tags) is None
    assert from_tags_af("Math", 0x271A, tags) is None


@pytest.mark.parametrize("expression", ["<Test Nickname> + 1", "DS1 + <FOO>", "<my 7H >"])
def test_math_refuses_a_nickname(expression: str) -> None:
    with pytest.raises(FieldError, match="Math.expression.*nickname"):
        Math(expression, "DS1")


def _points(bank: str, *runs: tuple[int, int]) -> list[str]:
    return [f"{bank}{n:03d}" for first, last in runs for n in range(first, last + 1)]


#: Each X and Y range of the three range captures (typed in CLICK v4, C2-03CPU, no I/O
#: modules, each into DS1): (file, rung, formula, the reserved slots (tag 0x688C) CLICK
#: wrote).  The slots are filled from index 0 with no empty slot between, and the slots
#: after them are empty.  None lists X017..X020 or X037..X100.  An end in the option slot
#: (21-36) stops the list early (X001 : X036 ends at X031), a start at X021 lists
#: X021 itself, and X025 : X027 lists X022.
_NATIVE_XY_LISTS = [
    ("math_ranges_x_t.bin", 2, "SUM ( X001 : X036 )", _points("X", (2, 16), (21, 31))),
    ("math_ranges_x_t.bin", 3, "SUM ( X001 : X101 )", _points("X", (2, 16), (21, 36))),
    (
        "math_ranges_xy_slots.bin",
        0,
        "SUM ( X001 : X116 )",
        _points("X", (2, 16), (21, 36), (101, 115)),
    ),
    (
        "math_ranges_xy_slots.bin",
        1,
        "SUM ( X021 : X116 )",
        _points("X", (21, 36), (101, 115)),
    ),
    ("math_ranges_xy_slots.bin", 2, "SUM ( X001 : X032 )", _points("X", (2, 16), (21, 27))),
    ("math_ranges_xy_slots.bin", 3, "SUM ( X005 : X036 )", _points("X", (6, 16), (21, 31))),
    ("math_ranges_xy_slots.bin", 4, "SUM ( Y001 : Y036 )", _points("Y", (2, 16), (21, 31))),
    ("math_ranges_xy_slots2.bin", 0, "SUM ( X001 : X021 )", _points("X", (2, 16))),
    ("math_ranges_xy_slots2.bin", 1, "SUM ( X025 : X026 )", []),
    ("math_ranges_xy_slots2.bin", 2, "SUM ( X025 : X027 )", ["X022"]),
    ("math_ranges_xy_slots2.bin", 3, "SUM ( X101 : X201 )", _points("X", (102, 116))),
    (
        "math_ranges_xy_slots2.bin",
        4,
        "SUM ( Y001 : Y116 )",
        _points("Y", (2, 16), (21, 36), (101, 115)),
    ),
    ("math_ranges_x25_x101.bin", 0, "SUM ( X025 : X101 )", _points("X", (22, 36))),
]
_XY_IDS = [f"{f}:{i}" for f, i, _, _ in _NATIVE_XY_LISTS]

#: The ranges among them whose stored list is not the points between the ends, refused
#: (user ruling 2026-11-12), and what the refusal says CLICK's list gets wrong.
#: test_math_grammar.py reads it for the stored formulas it expects refused.
REFUSED_XY_RANGES = {
    "SUM ( X001 : X036 )": "leave out X032..X035",
    "SUM ( X021 : X116 )": "add X021",
    "SUM ( X001 : X032 )": "leave out X028..X031",
    "SUM ( X005 : X036 )": "leave out X032..X035",
    "SUM ( Y001 : Y036 )": "leave out Y032..Y035",
    "SUM ( X025 : X027 )": "leave out X026 and add X022",
    "SUM ( X025 : X101 )": "add X022..X025",
}


@pytest.mark.parametrize(("file", "index", "formula", "expected"), _NATIVE_XY_LISTS, ids=_XY_IDS)
def test_math_xy_range_lists_in_capture(
    file: str, index: int, formula: str, expected: list[str]
) -> None:
    """The stored list is as recorded, and the encoder's rule for X/Y ranges gives it."""
    header, slots = _blob_fields(_native_math_blobs(CAPTURE_DIR / file)[index])
    assert dict(header)[0x6228] == formula
    listed = [value for (tag, _), value in sorted(slots.items()) if tag == 0x688C]
    assert listed == expected
    assert {key for key in slots if key[0] == 0x688C} == {(0x688C, i) for i in range(len(expected))}
    assert range_interiors(formula) == expected


@pytest.mark.parametrize(
    ("file", "index", "formula"), [x[:3] for x in _NATIVE_XY_LISTS], ids=_XY_IDS
)
def test_math_xy_range_refused_unless_its_list_holds_the_points_between(
    file: str, index: int, formula: str
) -> None:
    """A refused range's rung decodes as raw and keeps CLICK's bytes; the others are Math."""
    path = CAPTURE_DIR / file
    rung = _decode_file(path)[index]
    af = rung.instructions[0]
    if formula not in REFUSED_XY_RANGES:
        assert af == Math(formula, "DS1")
        return
    with pytest.raises(FieldError, match=f"wrong member list.*{REFUSED_XY_RANGES[formula]}"):
        Math(formula, "DS1")
    assert isinstance(af, RawInstruction)
    native = _native_math_blobs(path)[index]
    # The whole blob: 5510 fields, terminator included.
    assert af.blob == native[: len(af.blob)]
    assert _blob_fields(af.blob) == _blob_fields(native)
    assert af.blob in encode(rung)


@pytest.mark.parametrize("index", range(17, 21))
def test_math_wider_than_500_interiors_uses_clicks_capacity(index: int) -> None:
    """Past 500 interiors the whole blob matches, capacity included; CLICK stops at 5000."""
    path = CAPTURE_DIR / "retyped" / "math_wide.bin"
    math = next(t for t in _decode_file(path)[index].instructions if isinstance(t, Math))
    blob = math.build_blob()
    assert _native_math_blobs(path)[index].startswith(blob)
    assert struct.unpack_from("<I", blob, 16)[0] == 5510


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
    """Every time & event drum CLICK wrote re-encodes field for field.

    0x428A is the constant-preset mask: -1, except -2 for drum__te_ds (step 0 is DS1301).
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
        assert fields == native_fields, drum.to_csv()
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


#: ``(rows, pin_rows)`` of each rung in count_down_or.bin, CLICK 4.00's copy-back of
#: ``pinned_or/count_down_or.csv``.  Only nop_control_3row has anything on the box's
#: unused top row; CLICK draws C21's wire stopping at the box.
_COUNT_DOWN_SHAPES = {
    "or2_wired": (4, (1, 3)),
    "or3_wired": (5, (1, 4)),
    "nop_control_3row": (3, (1, 2)),
    "unwired_contact": (4, (1, 3)),
    "empty_row": (4, (1, 3)),
    "counters/count_down_negative": (5, (1, 4)),
    "counters/acc_clamps_at_dint_range": (6, (1, 5)),
    "counters/count_down_done_at_preset": (10, (1, 9)),
}


def test_count_down_or_layouts_survive_click() -> None:
    """CLICK keeps the layout read_csv gives count_down: legs under Down push Reset down."""
    native = (CAPTURE_DIR / "count_down_or.bin").read_bytes()
    rungs = _decode_file(CAPTURE_DIR / "count_down_or.bin")
    sent = read_csv(Path(__file__).parent / "fixtures" / "pinned_or" / "count_down_or.csv")
    assert [r.comment for r in rungs] == list(_COUNT_DOWN_SHAPES)
    encoded = encode(rungs)
    for index, (rung, ours) in enumerate(zip(rungs, sent, strict=True)):
        rung_id = rung.comment or ""
        af = rung.instructions[0]
        assert isinstance(af, Counter)
        assert (rung.logical_rows, af.pin_rows) == _COUNT_DOWN_SHAPES[rung_id], rung_id
        assert rung.conditions == ours.conditions, rung_id
        assert rung.instructions == ours.instructions, rung_id
        assert _af_cell_shape(encoded, index) == _af_cell_shape(native, index), rung_id


def test_loop_exit_blobs_match_native() -> None:
    """Break and Continue are class ``Next`` with func codes 9233 / 9232 (a v4 Next is 9220).

    ``loop_exits.bin`` was typed in CLICK v4: for(1), C1 Break, C2 Continue, Next.
    """
    path = CAPTURE_DIR / "loop_exits.bin"
    buf = path.read_bytes()
    rows = [row for rung in _decode_file(path) for row in decoded_rung_to_rows(rung)]
    assert [(row[1], row[-1]) for row in rows if row[0] != "#"] == [
        ("-", "for(1)"),
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


#: ``debounce_one_phase.bin``: debounces saved in CLICK v4 with one phase left empty
#: (rung 0 off phase only, rung 1 on phase only).  CLICK writes the empty phase's
#: accumulator and preset as empty strings.
_ONE_PHASE_DEBOUNCES = [
    "debounce(C1,off_acc=TD1,off_preset=100,unit=Tms)",
    "debounce(C1,on_acc=TD1,on_preset=100,unit=Tms)",
]


def test_one_phase_debounce_capture(tmp_path: Path) -> None:
    """Each one-phase debounce decodes, re-encodes to CLICK's blob and survives CSV."""
    path = CAPTURE_DIR / "debounce_one_phase.bin"
    buf = path.read_bytes()
    rungs = _decode_file(path)
    variants = [rung.instructions[0] for rung in rungs]
    assert [v.to_csv() for v in variants if isinstance(v, OutVariant)] == _ONE_PHASE_DEBOUNCES
    needle = "Out".encode("utf-16-le") + b"\x00\x00"
    starts = []
    i = -1
    while (i := buf.find(needle, i + 1)) != -1:
        starts.append(i)
    assert len(starts) == len(variants)
    for variant, start in zip(variants, starts, strict=True):
        assert isinstance(variant, OutVariant)
        blob = variant.build_blob()
        assert buf[start : start + len(blob)] == blob, variant.to_csv()
    write_csv(tmp_path / "rungs.csv", rungs)
    assert [r.instructions[0] for r in read_csv(tmp_path / "rungs.csv")] == variants


# ---------------------------------------------------------------------------
# Call index
# ---------------------------------------------------------------------------


def _call_blob_fields(buf: bytes, length: int) -> tuple[bytes, dict[int, str]]:
    """The one Call blob of a capture, and its tag -> value map."""
    needle = "Call".encode("utf-16-le") + bytes(2)
    assert buf.count(needle) == 1
    blob = _native_blob(buf, "Call", length)
    start = buf.index(needle) + 10
    count = struct.unpack_from("<I", buf, start + 6)[0]
    fields, _ = _parse_tagged_fields_verbose(buf, start + 10, count)
    return blob, {tag: value for tag, _, value in fields}


def test_call_index_captures() -> None:
    """Tag 0x3219 is the dialog's drop-down index: a pasted 0 stays, the dialog saves its own (3)."""
    from laddercodec.instructions.call import Call

    expected = Call("Conf_RtcSet").build_blob()
    blobs = {}
    for name, index in (("call_index_pasted.bin", "0"), ("call_index_dialog_ok.bin", "3")):
        buf = (CAPTURE_DIR / name).read_bytes()
        calls = [t for r in _decode_file(CAPTURE_DIR / name) for t in r.instructions]
        assert [t for t in calls if isinstance(t, Call)] == [Call("Conf_RtcSet")], name
        blob, fields = _call_blob_fields(buf, len(expected))
        assert fields[0x3219] == index, name
        assert fields[0x6208] == "Conf_RtcSet", name
        blobs[name] = blob
    assert blobs["call_index_pasted.bin"] == expected
    diff = [
        i
        for i, (a, b) in enumerate(zip(expected, blobs["call_index_dialog_ok.bin"], strict=True))
        if a != b
    ]
    assert len(diff) == 1
    assert expected[diff[0]] == ord("0") and blobs["call_index_dialog_ok.bin"][diff[0]] == ord("3")


# ---------------------------------------------------------------------------
# Box height: coverage goldens pasted, then saved by their dialogs
# ---------------------------------------------------------------------------

#: The coverage goldens pasted into ``box_height_pasted.bin`` and
#: ``box_height_dialog_ok.bin``, one rung each, in order.  The dialog capture adds an
#: ``end()`` rung 15, and its Email, Home, Position and Velocity have the status fields
#: filled in so their dialogs save.
_BOX_HEIGHT_GOLDENS = (
    "math__decimal",
    "math__hex",
    "search__eq",
    "search__continuous",
    "on_delay__ton",
    "on_delay__rton",
    "off_delay__tof",
    "shift__basic",
    "event_drum__basic",
    "time_drum__basic",
    "raw_instructions__email",
    "raw_instructions__home",
    "raw_instructions__position",
    "raw_instructions__velocity",
)
_RAW_BOX_GOLDENS = _BOX_HEIGHT_GOLDENS[10:]


def _af_box(data: bytes, rung: int) -> tuple[int, int, int]:
    """``(rung rows, +0x09, +0x0A)`` of the AF box on *rung*'s first row."""
    rows = len(_decode_file(data)[rung].conditions)
    (dump,) = inspect_cells(data, [(rung, 0, "AF")])
    assert dump.size > 0x40, f"rung {rung + 1}: no AF box on its first row"
    return rows, dump.raw[0x09], dump.raw[0x0A]


def test_box_height_captures() -> None:
    """CLICK keeps a typed box's height through paste and dialog OK; it grows the raw four.

    A pasted 1-row Email, Home, Position or Velocity copies back as ``01 01``; saving its
    dialog rewrites +0x09 to 3 and grows the rung to 3 rows (``03 01``).  CLICK v4 rewrites
    a pasted Math or Drum blob in its own form, so the boxes compare decoded.
    """
    pasted = (CAPTURE_DIR / "box_height_pasted.bin").read_bytes()
    dialog = (CAPTURE_DIR / "box_height_dialog_ok.bin").read_bytes()
    pasted_rungs = _decode_file(pasted)
    dialog_rungs = _decode_file(dialog)
    assert len(pasted_rungs) == len(_BOX_HEIGHT_GOLDENS)
    assert len(dialog_rungs) == len(_BOX_HEIGHT_GOLDENS) + 1
    assert [type(t).__name__ for t in dialog_rungs[-1].instructions] == ["End"]
    for i, name in enumerate(_BOX_HEIGHT_GOLDENS):
        for rungs in (pasted_rungs, dialog_rungs):
            assert (rungs[i].comment or "").startswith(f"{i + 1} {name}:"), rungs[i].comment
        (golden,) = read_csv(COVERAGE_GOLDEN / f"{name}.csv")
        ours = _af_box(encode(golden), 0)
        box = golden.instructions[0]
        if name in _RAW_BOX_GOLDENS:
            assert ours == (3, 3, 3), name
            assert pasted_rungs[i].instructions[0].build_blob() == box.build_blob(), name
            assert _af_box(pasted, i) == (1, 1, 1), name
            assert _af_box(dialog, i) == (3, 3, 1), name
        else:
            assert pasted_rungs[i].instructions[0] == box, name
            assert dialog_rungs[i].instructions[0] == box, name
            assert _af_box(pasted, i) == ours, name
            assert _af_box(dialog, i) == ours, name


@pytest.mark.parametrize("name", _RAW_BOX_GOLDENS)
def test_csv_raw_box_is_3_rows(name: str) -> None:
    """A raw Email, Home, Position or Velocity read from CSV is written as a 3-row box."""
    (rung,) = read_csv(COVERAGE_GOLDEN / f"{name}.csv")
    assert isinstance(rung.instructions[0], RawInstruction)
    assert rung.logical_rows == 3
    assert _af_box(encode(rung), 0) == (3, 3, 3)


def test_dialog_saved_box_reencodes_at_3_rows() -> None:
    """The dialog-saved boxes decode typed and re-encode as ``03 03`` over their 3 rows."""
    rungs = _decode_file(CAPTURE_DIR / "box_height_dialog_ok.bin")[10:14]
    assert [type(r.instructions[0]).__name__ for r in rungs] == [
        "Email",
        "Home",
        "Position",
        "Velocity",
    ]
    again = encode(rungs)
    for i, rung in enumerate(rungs):
        assert rung.instructions[0].cell_params() == {"visual_rows": 3}
        assert _af_box(again, i) == (3, 3, 3)


# ---------------------------------------------------------------------------
# Text constants typed in CLICK v4
# ---------------------------------------------------------------------------

_TEXT_128 = "GHIJKLMNOPQRSTUVWXYZ" * 6 + "ghijklmn"

#: ``text_blank.bin``: ``TXT1 == $00`` (ASCII-code constant) -> Copy ``$00`` to TXT1.
#: ``text_q.bin``: Copy ``"Q"`` (typed with its quotes) to TXT2.
#: ``text_tt.bin``: Copy ``"TT"`` to TXT1; the dialog shows the destination as TXT1..2.
#: ``text_abc.bin``: ``"ABC"`` to TXT10.  ``text_dollar_quoted.bin``: ``"$41"`` (quoted, so
#: three characters) to TXT2.  ``text_128.bin``: 128 characters to TXT873.
#: ``text_pointer.bin``: ``"AB"`` to ``TXT[DS1]``, which stores no end.
_TEXT_CAPTURES = {
    "text_blank.bin": ("TXT1==$00", "copy($00,TXT1)"),
    "text_q.bin": ("-", 'copy("Q",TXT2)'),
    "text_tt.bin": ("-", 'copy("TT",TXT1)'),
    "text_abc.bin": ("-", 'copy("ABC",TXT10)'),
    "text_dollar_quoted.bin": ("-", 'copy("$41",TXT2)'),
    "text_128.bin": ("-", f'copy("{_TEXT_128}",TXT873)'),
    "text_pointer.bin": ("-", 'copy("AB",TXT[DS1])'),
}

#: What CLICK stores as the destination end (0x6077) of each capture's Copy: the last TXT a
#: text of two or more characters fills, and nothing for one character or a ``$hh`` code.
_TEXT_DESTINATION_ENDS = {
    "text_blank.bin": (Copy("$00", "TXT1"), ""),
    "text_q.bin": (Copy('"Q"', "TXT2"), ""),
    "text_tt.bin": (Copy('"TT"', "TXT1"), "TXT2"),
    "text_abc.bin": (Copy('"ABC"', "TXT10"), "TXT12"),
    "text_dollar_quoted.bin": (Copy('"$41"', "TXT2"), "TXT4"),
    "text_128.bin": (Copy(f'"{_TEXT_128}"', "TXT873"), "TXT1000"),
    "text_pointer.bin": (Copy('"AB"', "TXT[DS1]"), ""),
}


@pytest.mark.parametrize("file", list(_TEXT_DESTINATION_ENDS))
def test_text_copy_destination_end_matches_native(file: str) -> None:
    """A Copy built by hand writes CLICK's blob, destination end included."""
    copy, end = _TEXT_DESTINATION_ENDS[file]
    native = _af_blob((CAPTURE_DIR / file).read_bytes(), 0)
    assert {tag: value for tag, _, value in native[4]}[0x6077] == end
    blob = copy.build_blob()
    assert _decompose_blob(blob) == native
    assert _native_blob((CAPTURE_DIR / file).read_bytes(), "Copy", len(blob)) == blob


def _native_blob(buf: bytes, class_name: str, length: int) -> bytes:
    start = buf.index(class_name.encode("utf-16-le") + b"\x00\x00")
    return buf[start : start + length]


@pytest.mark.parametrize("file", list(_TEXT_CAPTURES))
def test_text_constant_capture_decodes(file: str, tmp_path: Path) -> None:
    """Decodes to the typed rung, with no termination code, and the CSV round-trips."""
    rung = _decode_file(CAPTURE_DIR / file)[0]
    rows = decoded_rung_to_rows(rung)
    assert [(row[1], row[-1]) for row in rows if row[0] != "#" and row[-1]] == [
        _TEXT_CAPTURES[file]
    ]
    copy = rung.instructions[0]
    assert isinstance(copy, Copy) and copy.termination_code == "0"
    write_csv(tmp_path / "rung.csv", [rung])
    assert read_csv(tmp_path / "rung.csv")[0].instructions[0] == copy


@pytest.mark.parametrize("file", list(_TEXT_CAPTURES))
def test_text_constant_blobs_match_native(file: str) -> None:
    """A text-constant Copy source sets 0x1201 = -1, as CLICK writes; the blobs match."""
    path = CAPTURE_DIR / file
    buf = path.read_bytes()
    rung = _decode_file(path)[0]
    copy = rung.instructions[0]
    assert isinstance(copy, Copy)
    blob = copy.build_blob()
    assert _native_blob(buf, "Copy", len(blob)) == blob
    *_, fields = _decompose_blob(blob)
    flags = {tag: value for tag, _, value in fields if tag in (0x1221, 0x3216, 0x1201)}
    assert flags == {0x1221: "0", 0x3216: "0", 0x1201: "-1"}
    compare = rung.conditions[0][0]
    if isinstance(compare, CompareContact):
        blob = compare.build_blob()
        assert _native_blob(buf, "Compare", len(blob)) == blob


#: ``text_compare.bin``: TXT1 compared, as typed, against an ASCII-code constant and a
#: quoted text constant.  CLICK stores each operand as its text ($0D two digits, "A"
#: with its quotes), and laddercodec passes it through: nothing is formatted.
_TEXT_COMPARES = [("TXT1", "$0D"), ("TXT1", '"A"')]


def test_text_compare_capture_decodes() -> None:
    rung = _decode_file(CAPTURE_DIR / "text_compare.bin")[0]
    operands = []
    for compare in rung.conditions[0][: len(_TEXT_COMPARES)]:
        assert isinstance(compare, CompareContact) and compare.op == "=="
        operands.append((compare.left, compare.right))
    assert operands == _TEXT_COMPARES
    rows = decoded_rung_to_rows(rung)
    assert rows[0][1:3] == ["TXT1==$0D", 'TXT1=="A"']


def test_text_compare_blobs_match_native(tmp_path: Path) -> None:
    """Each Compare re-encodes to CLICK's bytes, and survives a CSV round-trip."""
    path = CAPTURE_DIR / "text_compare.bin"
    buf = path.read_bytes()
    rung = _decode_file(path)[0]
    compares = rung.conditions[0][: len(_TEXT_COMPARES)]
    offsets = []
    for compare in compares:
        assert isinstance(compare, CompareContact)
        offset = buf.find(compare.build_blob())
        assert offset >= 0, f"{compare.to_csv()} blob not in the native buffer"
        offsets.append(offset)
    assert len(set(offsets)) == len(compares)
    write_csv(tmp_path / "rung.csv", [rung])
    assert read_csv(tmp_path / "rung.csv")[0].conditions[0][:2] == compares


# ---------------------------------------------------------------------------
# DLL-sweep captures (arc.md): re-encoding gives CLICK's own AF blob
# ---------------------------------------------------------------------------

#: Tags CLICK writes but doesn't read back, per class name.
_SWEEP_IGNORED_TAGS: dict[str, frozenset[int]] = {
    # Drop-down position; the dialog reselects the subroutine by name and saves its own index
    # (call_index_pasted.bin keeps the pasted 0, call_index_dialog_ok.bin has 3).
    "Call": frozenset({0x3219}),
    # v4's dialog writes -1 on every save and ignores it on load (InstCtl_Copy.dll);
    # the encoder keeps the pre-v4 rule that native v3 captures match.
    "Copy": frozenset({0x1201}),
}

#: Per rung: fields where CLICK v4's dialog and the pre-v4 native capture we match
#: disagree, and v4 ignores the field on load.  The encoder keeps the v3 value.
_SWEEP_V3_VALUES: dict[str, frozenset[int]] = {
    "blockcopy__to_ascii_v4": frozenset({0x2206}),  # v4 dialog 1, coverage.bin 0
    # IP of a serial target: v4 '' (saved only for Ethernet/WLAN), coverage.bin '...'
    "receive__cpu3": frozenset({0x622B}),
    "send__slave_id_ds": frozenset({0x622B}),
}

#: Fields v4 adds to a blob we keep in v3's form (v4 takes both on paste).
_V4_ADDED_TAGS: dict[str, frozenset[int]] = {
    "Drum": frozenset({0x6891, 0x428A, 0x6068}),
    # v4 writes every Out in its OutVariant shape: pulse/timer fields, all blank or 0.
    "Out": frozenset({0x60B3, 0x60B4, 0x60B5, 0x60B6, 0x1246, 0x1247, 0x21F9, 0x2248, 0x20CA}),
}

#: Slot tables v4 pads further than v3 (Math: 5000 range-interior slots, not 500);
#: only the filled slots are compared.
_PADDED_TAGS: dict[str, frozenset[int]] = {
    "Math": frozenset({0x688C}),
}

#: Array slots whose sentinel CLICK writes as the slot index (0, 1, ...) and we write as
#: FFFFFFFF.  CLICK accepts both (every send/receive coverage golden is paste-verified),
#: so only the slot values are compared.
_INDEX_SENTINEL_TAGS: dict[str, frozenset[int]] = {
    "SD": frozenset({0x6889, 0x688F}),
    "RD": frozenset({0x688F}),
}

_SWEEP = [
    (path, index, rung)
    for path in sorted(CAPTURE_DIR.glob("sweep_*.bin"))
    for index, rung in enumerate(_decode_file(path))
]


def _af_blob(
    data: bytes, rung_index: int
) -> tuple[str, int, int, bytes, list[tuple[int, bytes, str]]]:
    cell = inspect_cells(data, [(rung_index, 0, "AF")])[0]
    return _decompose_blob(cell.raw[0x25:-0x10])


@pytest.mark.parametrize(
    ("path", "index", "rung"),
    _SWEEP,
    ids=[f"{p.stem}:{(r.comment or '').split(chr(10))[0]}" for p, _, r in _SWEEP],
)
def test_sweep_af_reencodes_like_native(path: Path, index: int, rung: Rung) -> None:
    """Every field CLICK wrote, in order, comes back from encode(decode(...)).

    The decode check above can't see func codes: the decoder ignores 0x3218.
    """
    if any(isinstance(token, str) and token.startswith("raw(") for token in rung.instructions):
        pytest.xfail("not decoded yet")
    native = _af_blob(path.read_bytes(), index)
    ours = _af_blob(encode(rung), 0)
    rung_id = (rung.comment or "").split("\n")[0]
    ignored = _SWEEP_IGNORED_TAGS.get(native[0], frozenset()) | _SWEEP_V3_VALUES.get(
        rung_id, frozenset()
    )
    v4_added = _V4_ADDED_TAGS.get(native[0], frozenset())
    if not any(f[0] in v4_added for f in ours[4]):
        ignored |= v4_added
    padded = _PADDED_TAGS.get(native[0], frozenset())
    indexed = _INDEX_SENTINEL_TAGS.get(native[0], frozenset())

    def compared(fields: list[tuple[int, bytes, str]]) -> list[tuple[int, bytes, str]]:
        return [
            (f[0], b"" if f[0] in indexed else f[1], f[2])
            for f in fields
            if f[0] not in ignored and not (f[0] in padded and not f[2])
        ]

    assert ours[:4] == native[:4]
    assert compared(ours[4]) == compared(native[4])


# ---------------------------------------------------------------------------
# OR legs under a tall box: pasted, then after CLICK's syntax check
# ---------------------------------------------------------------------------

_GRID_COLUMNS = [*(chr(ord("A") + i) for i in range(26)), "AA", "AB", "AC", "AD", "AE", "AF"]

#: ``(csv, checked capture, {csv rung: checked rung})``.  CLICK's check splits stub
#: rung 2 (two branches from the rail) into checked rungs 2 and 3.
_OR_COMPACT = [
    ("or_compact_stub.csv", "or_compact_checked.bin", {0: 0, 2: 3, 3: 4, 4: 5}),
    ("r30_tallbox.csv", "r30_tallbox_checked.bin", {0: 0}),
]


def _wire_flags(data: bytes, rung: int) -> list[list[tuple[int, int]]]:
    """The (right, down) flags of every cell of *rung*; segment flags keep editing history."""
    rows = len(_decode_file(data)[rung].conditions)
    return [
        [d.flags[1:] for d in inspect_cells(data, [(rung, r, c) for c in _GRID_COLUMNS])]
        for r in range(rows)
    ]


def _assert_same_layout(ours: bytes, ours_rung: int, native: bytes, native_rung: int) -> None:
    mine, theirs = _decode_file(ours)[ours_rung], _decode_file(native)[native_rung]
    assert mine.logical_rows == theirs.logical_rows
    assert mine.conditions == theirs.conditions
    assert mine.instructions == theirs.instructions
    assert _wire_flags(ours, ours_rung) == _wire_flags(native, native_rung)


@pytest.mark.parametrize(("csv_name", "bin_name", "pairs"), _OR_COMPACT, ids=["stub", "r30"])
def test_or_legs_encode_as_checked(csv_name: str, bin_name: str, pairs: dict[int, int]) -> None:
    """OR legs under a tall box encode as CLICK's syntax check leaves them.

    The legs keep their rows, each Copy takes the first row below the box above it,
    and the right vertical reaches both.  Stub rung 3 (C2 hangs off X1's vertical,
    not an OR leg) keeps its padding, as CLICK does.
    """
    rungs = read_csv(CAPTURE_DIR / csv_name)
    native = (CAPTURE_DIR / bin_name).read_bytes()
    for csv_index, native_index in pairs.items():
        _assert_same_layout(encode(rungs[csv_index]), 0, native, native_index)


def test_or_legs_layout_moves_only_what_check_moves() -> None:
    """Against the pasted padded layout: stub rungs 1, 4 and 5 move, 2 and 3 don't."""
    rungs = read_csv(CAPTURE_DIR / "or_compact_stub.csv")
    pasted = _decode_file(CAPTURE_DIR / "or_compact_pasted.bin")
    ours = [_decode_file(encode(rung))[0] for rung in rungs]
    moved = [a.conditions != b.conditions for a, b in zip(ours, pasted, strict=True)]
    assert moved == [True, False, False, True, True]
    assert [r.logical_rows for r in ours] == [4, 4, 4, 4, 6]
    assert [r.logical_rows for r in pasted] == [4, 4, 4, 5, 6]


@pytest.mark.parametrize("bin_name", ["or_compact_checked.bin", "r30_tallbox_checked.bin"])
def test_checked_or_legs_round_trip_through_csv(bin_name: str, tmp_path: Path) -> None:
    """CLICK's compact layout writes to CSV, reads back and encodes to the same layout."""
    native = (CAPTURE_DIR / bin_name).read_bytes()
    rungs = _decode_file(native)
    write_csv(tmp_path / "checked.csv", rungs)
    again = encode(read_csv(tmp_path / "checked.csv"))
    for i in range(len(rungs)):
        _assert_same_layout(again, i, native, i)


@pytest.mark.parametrize("bin_name", ["or_compact_pasted.bin", "r30_tallbox_pasted.bin"])
def test_pasted_or_legs_keep_their_pad_rows_through_csv(bin_name: str, tmp_path: Path) -> None:
    """The padded layout writes its pad rows, so it reads back padded, not compacted."""
    native = (CAPTURE_DIR / bin_name).read_bytes()
    rungs = _decode_file(native)
    pad_row = ["", "", "|", "|", *[""] * 28, ""]
    assert pad_row in decoded_rung_to_rows(rungs[0])
    write_csv(tmp_path / "pasted.csv", rungs)
    again = encode(read_csv(tmp_path / "pasted.csv"))
    for i in range(len(rungs)):
        _assert_same_layout(again, i, native, i)
