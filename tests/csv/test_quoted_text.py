"""Test that every text of a single Copy and of a Search reads back from its CSV token.

The text runs from the first quote in the call's arguments to the last. Each comma,
bracket, parenthesis and quote between them is a character of the text. The test
tries every text of 1 to 4 characters over a set of characters that a CSV token reads as
syntax, and every text of 1 to 3 characters with line breaks added to the set.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from pathlib import Path

import pytest

from laddercodec import decode, encode, read_csv, write_csv
from laddercodec.csv.converter import af_node_to_token
from laddercodec.csv.token_parser import parse_af_token
from laddercodec.errors import CsvReadError
from laddercodec.instructions import parse_af_blob
from laddercodec.instructions.copy import Copy
from laddercodec.instructions.search import Search

#: Characters that a call's arguments read as syntax, and two that they don't.
_CHARS = '",[]() A='
#: ``_CHARS`` and the line breaks, which a text may hold and the arguments outside it may not.
_BREAK_CHARS = _CHARS + "\n\r"
#: Every text of 1 to 3 characters over ``_BREAK_CHARS`` and of 4 characters over
#: ``_CHARS``, with its outer quotes.
_TEXTS = [
    '"' + "".join(chars) + '"'
    for count in range(1, 5)
    for chars in itertools.product(_BREAK_CHARS if count < 4 else _CHARS, repeat=count)
]


def _boxes(text: str) -> list[Copy | Search]:
    return [Copy(text, "TXT1"), Search("TXT1", "TXT10", text, "DS30", "C1", "==")]


@pytest.fixture(scope="module")
def boxes() -> list[Copy | Search]:
    return [box for text in _TEXTS for box in _boxes(text)]


def test_the_texts_are_every_text_up_to_four_characters() -> None:
    n = len(_BREAK_CHARS)
    assert len(_TEXTS) == n + n**2 + n**3 + len(_CHARS) ** 4


def test_every_text_reads_back_from_its_token(boxes: list[Copy | Search]) -> None:
    """read_csv reads each AF cell with ``parse_af_token``. The token of each Copy and each
    Search reads back equal to it."""
    wrong = [box for box in boxes if af_node_to_token(parse_af_token(box.to_csv())) != box]
    assert wrong == []


def test_every_text_decodes_from_its_blob(boxes: list[Copy | Search]) -> None:
    """decode() reads the blob that encode() writes as the same instruction."""
    assert [box for box in boxes if parse_af_blob(box.build_blob()) != box] == []


@pytest.mark.parametrize("token", ['copy(",TXT1)', 'search(TXT1..TXT10 == ",result=DS30,found=C1)'])
def test_a_lone_quote_in_the_arguments_is_refused(token: str) -> None:
    with pytest.raises(CsvReadError, match="unmatched quote"):
        parse_af_token(token)


@pytest.mark.parametrize(
    ("token", "says"),
    [
        ('copy("AB",TXT1,oneshot="1")', 'copy: oneshot="1" is in quotes; write oneshot=1.'),
        (
            'copy("A",TXT2,termination_code="$0D")',
            'copy: termination_code="$0D" is in quotes; write termination_code=$0D.',
        ),
        (
            'copy(TXT1,DS1,convert="to_value",oneshot="1")',
            'copy: convert="to_value" is in quotes; write convert=to_value.',
        ),
        (
            'search(TXT1..TXT10 == "A",result="DS30",found="C1")',
            'search: result="DS30" is in quotes; write result=DS30.',
        ),
        (
            'search(DS1..DS10 == 5,result="DS30",found="C1")',
            'search: result="DS30" is in quotes; write result=DS30.',
        ),
    ],
)
def test_a_keyword_value_in_quotes_is_refused(token: str, says: str) -> None:
    """A keyword value in quotes is refused where it leaves a Copy without its destination or
    a Search without its result and found, and in a call with no text."""
    with pytest.raises(CsvReadError) as info:
        parse_af_token(token)
    assert str(info.value) == says


@pytest.mark.parametrize(
    ("token", "value"),
    [
        ('search(TXT1..TXT10 == "A",oneshot="1",result=DS30,found=C1)', '"A",oneshot="1"'),
        (
            'search(TXT1..TXT10 == "A",continuous="1",result=DS30,found=C1)',
            '"A",continuous="1"',
        ),
        ('search(TXT1..TXT10 == "A",found="C2",result=DS30,found=C1)', '"A",found="C2"'),
    ],
)
def test_a_quoted_keyword_before_result_and_found_is_text(token: str, value: str) -> None:
    """The text runs from the first quote to the last, so it holds a quoted keyword that
    comes before result= and found=. write_csv writes such a text in the same form."""
    search = Search("TXT1", "TXT10", value, "DS30", "C1", "==")
    assert af_node_to_token(parse_af_token(token)) == search
    assert search.to_csv() == token


@pytest.mark.parametrize(
    "box",
    [
        Copy('"A",oneshot="1"', "TXT1"),
        Copy('"A",TXT2,convert="to_value"', "TXT1"),
        Search("TXT1", "TXT10", '"A",result="DS1",found="C2"', "DS30", "C1", "=="),
    ],
    ids=["copy-keyword", "copy-argument", "search-keywords"],
)
def test_a_text_that_holds_arguments_reads_back_whole(tmp_path: Path, box: object) -> None:
    """write_csv writes the text from its first quote to its last, and read_csv reads it so."""
    assert af_node_to_token(parse_af_token(box.to_csv())) == box  # type: ignore[attr-defined]
    capture = Path(__file__).resolve().parents[1] / "fixtures" / "v4_captures" / "copy_forms"
    [rung] = decode((capture / "case21.bin").read_bytes())
    rungs = [replace(rung, instructions=[box, ""])]
    write_csv(tmp_path / "text.csv", rungs)
    assert read_csv(tmp_path / "text.csv") == rungs


def test_extra_positional_arguments_are_counted() -> None:
    with pytest.raises(CsvReadError, match="got 3"):
        af_node_to_token(parse_af_token('copy("A",TXT1,"x")'))


@pytest.mark.parametrize("count", [1, 2])
def test_short_texts_round_trip_through_files(tmp_path: Path, count: int) -> None:
    """write_csv writes every text of ``count`` characters, read_csv reads each back, and
    decode() reads what encode() writes."""
    capture = Path(__file__).resolve().parents[1] / "fixtures" / "v4_captures" / "copy_forms"
    [rung] = decode((capture / "case21.bin").read_bytes())
    texts = [t for t in _TEXTS if len(t) == count + 2]
    rungs = [replace(rung, instructions=[box, ""]) for t in texts for box in _boxes(t)]
    path = tmp_path / "texts.csv"
    write_csv(path, rungs)
    assert read_csv(path) == rungs
    assert decode(encode(rungs)) == rungs
