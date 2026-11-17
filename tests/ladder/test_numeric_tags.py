"""Text that is no number in a numeric tag leaves the blob raw.

A numeric tag read as its default would build another variant of the instruction (a Pack
of text read as a Pack of words) and hold the refusals of that one.  Each case takes a
coverage golden's blob, stores ``C1`` in one numeric tag, and parses the tags again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec import RawInstruction, decode, read_csv
from laddercodec.binary_helpers import NotANumber, tag_int
from laddercodec.instructions import (
    ConditionInstruction,
    from_tags_af,
    from_tags_condition,
    parse_af_blob,
)
from laddercodec.instructions.raw import _decompose_blob, _fields_to_tag_dicts

GOLDEN = Path(__file__).parents[1] / "fixtures" / "coverage" / "golden"

#: (golden, class read from it, numeric tag).
CASES = [
    ("cond__eq", "CompareContact", 0x21F7),
    ("cond__rise", "Contact", 0x21F6),
    ("copy__tag", "Copy", 0x2223),
    ("pack_text", "Pack", 0x2227),
    ("count_down", "Counter", 0x21FC),
    ("event_drum__basic", "Drum", 0x3203),
    ("event_drum__basic", "Drum", 0x3204),
    ("search__continuous", "Search", 0x21F7),
    ("send__tcp_click_coil", "Send", 0x320E),
    ("send__tcp_click_coil", "Send", 0x322C),
    ("send__tcp_click_coil", "Send", 0x3210),
    ("receive__rtu_click_block", "Receive", 0x3210),
    ("off_delay__tof", "Timer", 0x21FA),
    ("off_delay__tof", "Timer", 0x21FB),
]


def _token(golden: str, cls: str) -> object:
    [rung] = read_csv(GOLDEN / f"{golden}.csv")
    tokens = [*(t for row in rung.conditions for t in row), *rung.instructions]
    [token] = [t for t in tokens if type(t).__name__ == cls]
    return token


@pytest.mark.parametrize(("golden", "cls", "tag"), CASES, ids=[f"{c[1]}-{c[2]:04X}" for c in CASES])
def test_no_number_in_a_numeric_tag_leaves_the_blob_raw(golden, cls, tag) -> None:
    token = _token(golden, cls)
    class_name, type_code, _parts, _extra, fields = _decompose_blob(token.build_blob())
    tags, variant_u16, variant_string = _fields_to_tag_dicts(fields)
    parse = from_tags_condition if isinstance(token, ConditionInstruction) else from_tags_af
    assert (
        type(parse(class_name, type_code, dict(tags), variant_u16, variant_string)).__name__ == cls
    )
    assert parse(class_name, type_code, tags | {tag: "C1"}, variant_u16, variant_string) is None


def test_home_variant_tag_with_no_number_leaves_the_blob_raw() -> None:
    [rung] = read_csv(GOLDEN / "raw_instructions__home.csv")
    [raw] = [t for t in rung.instructions if isinstance(t, RawInstruction)]
    class_name, type_code, _parts, _extra, fields = _decompose_blob(raw.blob)
    tags, variant_u16, variant_string = _fields_to_tag_dicts(fields)
    assert from_tags_af(class_name, type_code, tags, variant_u16, variant_string) is not None
    edited = tags | {0x222E: "C1"}
    assert from_tags_af(class_name, type_code, edited, variant_u16, variant_string) is None


def test_pack_text_with_no_number_conversion_decodes_raw() -> None:
    """The stored blob is not read as a Pack of words, which it isn't."""
    data = (GOLDEN / "pack_text__allow_whitespace.bin").read_bytes()
    stored = b"\x27\x22\xff\xff\xff\xff" + "10".encode("utf-16-le") + b"\x00\x00"
    assert data.count(stored) == 1
    edited = data.replace(
        stored, b"\x27\x22\xff\xff\xff\xff" + "C1".encode("utf-16-le") + b"\x00\x00"
    )
    [token] = [t for t in decode(edited)[0].instructions if t]
    assert isinstance(token, RawInstruction)
    assert parse_af_blob(token.blob) is None


def test_tag_int_reads_a_blank_as_the_default_and_refuses_text() -> None:
    assert tag_int({}, 0x2223) == 0
    assert tag_int({0x2223: ""}, 0x2223) == 0
    assert tag_int({0x2223: "3"}, 0x2223) == 3
    with pytest.raises(NotANumber, match="0x2223"):
        tag_int({0x2223: "C1"}, 0x2223)
