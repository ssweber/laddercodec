"""CLICK v4 captures: every labelled rung's comment says what it should decode to.

Each ``fixtures/v4_captures/<group>.bin`` is a multi-rung copy-back from CLICK v4.
The stubs come from pyrung (``pyrung/scratchpad/click-v4/captures/v4_capture.py``);
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

from laddercodec.binary_helpers import _parse_tagged_fields_verbose
from laddercodec.csv.writer import decoded_rung_to_rows
from laddercodec.decode import Rung, decode
from laddercodec.instructions.math import Math
from laddercodec.instructions.raw import RawInstruction

CAPTURE_DIR = Path(__file__).parent / "fixtures" / "v4_captures"


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


@pytest.mark.parametrize("rung", [r for _, r in _LABELLED], ids=[cid for cid, _ in _LABELLED])
def test_rung_decodes_to_its_comment(rung: Rung) -> None:
    expected = (rung.comment or "").split("\n")[1:]
    rows = decoded_rung_to_rows(rung)
    af_tokens = [row[-1] for row in rows if row[0] != "#" and row[-1]]
    if any(token.startswith("raw(") for token in af_tokens):
        pytest.xfail(f"not decoded yet: {af_tokens}")
    assert af_tokens == expected


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


def test_out_variant_is_not_a_plain_coil() -> None:
    """A debounce (class ``Out``, func code 8226) must not decode as ``out(C1)``."""
    rung = _decode_file(CAPTURE_DIR / "out_debounce_example.bin")[0]
    af = next(token for token in rung.instructions if token not in ("", "NOP"))
    assert isinstance(af, RawInstruction)
    assert af.to_csv().startswith("raw(Out,")
