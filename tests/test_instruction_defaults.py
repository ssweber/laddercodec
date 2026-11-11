"""Defaults, checked over every instruction in the fixtures.

Binary side: Click's ``Scr*.tmp`` files leave out each tag at its default value
(see ``binary_helpers.tag_default``); the clipboard stores every tag.

* The defaults table must match what CLICK does: in every native SCR + clipboard
  pair, each tag SCR left out has its default value in the clipboard copy.
* Every instruction must decode without its default tags: each one's clipboard
  blob, with every tag at its default dropped the way SCR does, decodes to the
  same instruction rather than ``raw(...)``.

The func code (0x3218) is kept: SCR leaves it out only when it can be derived, and
each family derives it.

CSV side: a flag kwarg (a ``bool`` field such as ``oneshot``) is written only when
set, so ``for(3)`` rather than ``for(3,oneshot=0)``.  Value kwargs (``mode=``,
``unit=``, ``preset=``, the ``to_text(...)`` option the source has and its termination code) are always written.

The instructions come from the coverage goldens plus every native clipboard
capture (CLICK v4 copy-backs, the SCR pairs' clipboard side, the tumbler programs).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from laddercodec import decode
from laddercodec.binary_helpers import _STANDARD_SENTINEL, _tag_wire_type, tag_default
from laddercodec.csv import read_csv
from laddercodec.instructions import from_tags_af, from_tags_condition
from laddercodec.instructions.raw import RawInstruction, _decompose_blob, _fields_to_tag_dicts
from laddercodec.model import AfInstruction, ConditionInstruction
from tests.scr_defaults import fixture_pairs, mismatches, read_clipboard, survey

FIXTURES = Path(__file__).parent / "fixtures"

Instruction = AfInstruction | ConditionInstruction


def _native_captures() -> list[Path]:
    v4 = sorted((FIXTURES / "v4_captures").rglob("*.bin"))
    return v4 + [clip for _scr, clip in fixture_pairs()]


def _corpus() -> dict[str, Instruction]:
    rungs = [
        rung
        for path in sorted((FIXTURES / "coverage" / "golden").glob("*.csv"))
        for rung in read_csv(path)
    ]
    for path in _native_captures():
        decoded = decode(read_clipboard(path))
        rungs.extend(decoded if isinstance(decoded, list) else [decoded])

    found: dict[str, Instruction] = {}
    for rung in rungs:
        for token in [t for row in rung.conditions for t in row] + list(rung.instructions):
            if not isinstance(token, Instruction) or isinstance(token, RawInstruction):
                continue
            # The wire-down flag is grid topology, not blob content.
            if getattr(token, "wire_down", False):
                token = dataclasses.replace(token, wire_down=False)
            found.setdefault(token.to_csv(), token)
    return found


_CORPUS = _corpus()


def _scr_fields(class_name: str, fields: list[tuple[int, bytes, str]]):
    """Drop the fields Click's SCR leaves out: every tag at its default."""
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
    decode_tags = from_tags_condition if isinstance(token, ConditionInstruction) else from_tags_af
    parsed = decode_tags(class_name, type_marker, *tag_dicts)
    assert parsed is not None, f"{token_csv} fell back to raw without its default tags"
    assert parsed.to_csv() == token_csv


@pytest.mark.parametrize("token_csv", sorted(_CORPUS))
def test_unset_flag_kwarg_is_not_written(token_csv: str) -> None:
    token = _CORPUS[token_csv]
    for field in dataclasses.fields(token):
        value = getattr(token, field.name)
        if isinstance(value, bool) and not value:
            for written in (f"{field.name}=0", f"{field.name}=False"):
                assert written not in token_csv, f"{type(token).__name__} writes {written}"
