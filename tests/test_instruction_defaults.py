"""Tests of how default values are stored and written, over every instruction in the fixtures.

In the binary, CLICK's ``Scr*.tmp`` files leave out each tag that is at its default value
(see ``binary_helpers.tag_default``).  The clipboard stores every tag.

* The defaults table must match what CLICK does.  In every native pair of an SCR file
  and a clipboard capture, each tag that the SCR file left out has its default value in
  the clipboard capture.
* Every instruction must decode without its default tags.  Take the clipboard blob of
  each instruction and drop every tag that is at its default, as SCR does.  The result
  decodes to the same instruction, not to ``raw(...)``.

Neither check treats the func code (0x3218) as a default.  The first does not compare it,
and the second keeps it.  An SCR file leaves the func code out only when the class and
the other fields determine it.  Each instruction family works it out itself, and the
defaults table has no entry for it.

In CSV, a flag kwarg (a ``bool`` field such as ``oneshot``) is written only when it is
set: ``for(3)``, not ``for(3,oneshot=0)``.  Value kwargs are always written.  They are
``mode=``, ``unit=``, ``preset=``, and in a ``to_text(...)`` copy the text option that
the source has and the termination code.

The instructions come from the coverage golden files and from every native clipboard
capture: the CLICK v4 copy-backs, the clipboard side of the SCR pairs, and the tumbler
programs.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from laddercodec import decode
from laddercodec.binary_helpers import _STANDARD_SENTINEL, _tag_wire_type, tag_default
from laddercodec.csv import read_csv
from laddercodec.instructions import Tee, from_tags_af, from_tags_condition
from laddercodec.instructions.raw import RawInstruction, _decompose_blob, _fields_to_tag_dicts
from laddercodec.model import Condition, Instruction
from laddercodec.operands.unchecked import refusals
from tests.scr_defaults import fixture_pairs, mismatches, read_clipboard, survey
from tests.undecoded_captures import without_marker

FIXTURES = Path(__file__).parent / "fixtures"

Instruction = Instruction | Condition


def _native_captures() -> list[Path]:
    v4 = without_marker(sorted((FIXTURES / "v4_captures").rglob("*.bin")))
    return v4 + [clip for _scr, clip in fixture_pairs()]


def _corpus() -> dict[str, Instruction]:
    rungs = [
        rung
        for path in sorted((FIXTURES / "coverage" / "golden").glob("*.csv"))
        for rung in read_csv(path)
    ]
    for path in _native_captures():
        decoded = decode(read_clipboard(path))
        rungs.extend(decoded)

    found: dict[str, Instruction] = {}
    for rung in rungs:
        for token in [t for row in rung.conditions for t in row] + list(rung.instructions):
            # The wire down of a Tee describes the grid, and the contact's blob does not
            # hold it.
            if isinstance(token, Tee):
                token = token.contact
            if not isinstance(token, Instruction) or isinstance(token, RawInstruction):
                continue
            if refusals(token):
                continue  # its checks refuse a stored value, so it builds no blob to compare
            found.setdefault(token.to_csv(), token)
    return found


_CORPUS = _corpus()


def _scr_fields(class_name: str, fields: list[tuple[int, bytes, str]]):
    """Return *fields* without the tags that CLICK's SCR files leave out, which are the tags
    at their default.  Tags 0x0000 and 0x3218 are always kept."""
    kept = []
    for tag, sentinel, value in fields:
        if tag in (0x0000, 0x3218):
            kept.append((tag, sentinel, value))
            continue
        if sentinel == _STANDARD_SENTINEL:
            wire = _tag_wire_type(tag)
            if wire == "flag":
                if value in ("", "0"):
                    continue
            elif value == tag_default(tag, class_name) or (not value and wire != "string"):
                continue
        elif value in ("", "0"):  # variant slot at zero
            continue
        kept.append((tag, sentinel, value))
    return kept


def test_tag_defaults_match_native_scr_captures() -> None:
    result = survey(fixture_pairs())
    assert result.pairs > 30
    assert result.unpaired == 0
    assert mismatches(result) == [], "SCR left these tags out at a non-default value"


def test_corpus_covers_every_family() -> None:
    families = {type(token).__name__ for token in _CORPUS.values()}
    assert len(_CORPUS) > 300
    assert {"OutVariant", "Timer", "Drum", "Copy", "Send", "Receive", "ForLoop"} <= families


@pytest.mark.parametrize("token_csv", sorted(_CORPUS))
def test_instruction_decodes_without_default_tags(token_csv: str) -> None:
    token = _CORPUS[token_csv]
    class_name, type_marker, _parts, _extra, fields = _decompose_blob(token.build_blob())
    tag_dicts = _fields_to_tag_dicts(_scr_fields(class_name, fields))
    decode_tags = from_tags_condition if isinstance(token, Condition) else from_tags_af
    parsed = decode_tags(class_name, type_marker, *tag_dicts)
    assert parsed is not None, f"{token_csv} fell back to raw without its default tags"
    assert parsed.to_csv() == token_csv


#: A Copy to text always writes the text option its source has, off or on.
_WRITTEN_WHEN_OFF = {("Copy", "suppress_zero"), ("Copy", "exponential")}


@pytest.mark.parametrize("token_csv", sorted(_CORPUS))
def test_unset_flag_kwarg_is_not_written(token_csv: str) -> None:
    token = _CORPUS[token_csv]
    for field in dataclasses.fields(token):
        value = getattr(token, field.name)
        if (type(token).__name__, field.name) in _WRITTEN_WHEN_OFF:
            continue
        if isinstance(value, bool) and not value:
            for written in (f"{field.name}=0", f"{field.name}=False"):
                assert written not in token_csv, f"{type(token).__name__} writes {written}"
