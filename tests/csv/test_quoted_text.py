"""Test that every text of a single Copy, a Search and a Compare reads back from its CSV
token.

In a Copy or a Search, the text runs from the first quote in the call's arguments to the
last. Each comma, bracket, parenthesis and quote between them is a character of the text.
In a Compare, a side that is text runs from its first quote to its last, and the operator
is outside it. The tests try every text of 1 to 4 characters over a set of characters that
a CSV token reads as syntax, and every text of 1 to 3 characters with line breaks added to
the set.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from pathlib import Path

import pytest

from laddercodec import decode, encode, read_csv, write_csv
from laddercodec.csv.ast import ComparisonCondition
from laddercodec.csv.converter import af_node_to_token, condition_node_to_token
from laddercodec.csv.token_parser import parse_af_token, parse_condition_token
from laddercodec.errors import CsvReadError
from laddercodec.instructions import parse_af_blob, parse_condition_blob
from laddercodec.instructions.comparison import CompareContact
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
        ('copy("A"B",TXT1,oneshot="1")', 'copy: oneshot="1" is in quotes; write oneshot=1.'),
        (
            'search(TXT1..TXT10 == "A"B",result=DS30,found=C1,oneshot="1")',
            'search: oneshot="1" is in quotes; write oneshot=1.',
        ),
        (
            'search(TXT1..TXT10 == TXT20,oneshot="1",result=DS30,found=C1)',
            'search: oneshot="1" is in quotes; write oneshot=1.',
        ),
        (
            'search(DS1..DS10 == 5,oneshot="1",result=DS30,found=C1)',
            'search: oneshot="1" is in quotes; write oneshot=1.',
        ),
    ],
)
def test_a_keyword_value_in_quotes_is_refused(token: str, says: str) -> None:
    """A keyword value in quotes is refused where it leaves a Copy without its destination or
    a Search without its result and found, and in a call with no text.  If the quotes of
    the text do not pair up, the refusal names the last quoted keyword value."""
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


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

#: Characters that a compare token reads as syntax, and two that it doesn't.
_CMP_CHARS = '"=!<> A'
#: ``_CMP_CHARS`` and the line breaks.
_CMP_BREAK_CHARS = _CMP_CHARS + "\n\r"
#: Every text of 1 to 3 characters over ``_CMP_BREAK_CHARS`` and of 4 characters over
#: ``_CMP_CHARS``, with its outer quotes.
_CMP_TEXTS = [
    '"' + "".join(chars) + '"'
    for count in range(1, 5)
    for chars in itertools.product(_CMP_BREAK_CHARS if count < 4 else _CMP_CHARS, repeat=count)
]
_OPS = ("==", "!=", ">", "<", ">=", "<=")


def _sides(text: str) -> list[tuple[str, str]]:
    """Return *text* as the left side and as the right side, opposite TXT1."""
    return [(text, "TXT1"), ("TXT1", text)]


def _compares(text: str) -> list[CompareContact]:
    """Return the compares of *text* with == and !=, on each side that takes it. The left
    side takes printable ASCII only."""
    sides = _sides(text) if text.isprintable() else [("TXT1", text)]
    return [CompareContact(op, left, right) for left, right in sides for op in ("==", "!=")]


def test_the_compare_texts_are_every_text_up_to_four_characters() -> None:
    n = len(_CMP_BREAK_CHARS)
    assert len(_CMP_TEXTS) == n + n**2 + n**3 + len(_CMP_CHARS) ** 4


def test_every_operator_is_found_outside_the_text() -> None:
    """read_csv reads each condition cell with ``parse_condition_token``. With a text on
    either side, it reads every operator, and the text as written."""
    wrong = []
    for text in _CMP_TEXTS:
        for left, right in _sides(text):
            for op in _OPS:
                node = parse_condition_token(f"{left}{op}{right}")
                if not isinstance(node, ComparisonCondition) or (
                    node.left,
                    node.op,
                    node.right,
                ) != (left, op, right):
                    wrong.append((left, op, right))
    assert wrong == []


def test_every_compare_text_reads_back_and_decodes() -> None:
    """The token of each compare reads back equal to it, and decode() reads the blob that
    encode() writes as the same compare."""
    compares = [c for text in _CMP_TEXTS for c in _compares(text)]
    assert [
        c for c in compares if condition_node_to_token(parse_condition_token(c.to_csv())) != c
    ] == []
    assert [c for c in compares if parse_condition_blob(c.build_blob()) != c] == []


#: Every text of 1 to 3 characters over ``"= !A`` and of 4 characters over ``"=A``, with its
#: outer quotes. A pair of the 4-character texts can read two ways, such as ``"A"=="`` with
#: ``"B"``.
_TWO_TEXTS = sorted(
    {
        '"' + "".join(chars) + '"'
        for count in range(1, 5)
        for chars in itertools.product('"= !A' if count < 4 else '"=A', repeat=count)
    }
)


def _text_readings(token: str) -> list[tuple[str, str, str]]:
    """Return each split of *token* at an operator that leaves a text of at least one
    character, in quotes, on each side."""
    readings = []
    for i in range(1, len(token)):
        for op in _OPS:
            if token.startswith(op, i):
                left, right = token[:i], token[i + len(op) :]
                if all(len(t) >= 3 and t[0] == t[-1] == '"' for t in (left, right)):
                    readings.append((left, op, right))
    return readings


def test_every_two_text_compare_with_one_reading_reads_back() -> None:
    """A cell of two texts reads back as its compare when one operator leaves a text on each
    side. When two operators do, read_csv refuses the cell."""
    wrong = []
    two_way = 0
    for left, right in itertools.product(_TWO_TEXTS, repeat=2):
        for op in ("==", "!="):
            compare = CompareContact(op, left, right)
            token = compare.to_csv()
            if len(_text_readings(token)) == 1:
                if CompareContact.from_csv_token(token) != compare:
                    wrong.append(token)
                continue
            two_way += 1
            with pytest.raises(CsvReadError, match="reads as a compare two ways"):
                CompareContact.from_csv_token(token)
    assert wrong == []
    assert two_way > 0


@pytest.mark.parametrize("count", [1, 2])
def test_short_compare_texts_round_trip_through_files(tmp_path: Path, count: int) -> None:
    """write_csv writes every compare text of ``count`` characters, read_csv reads each
    back, and decode() reads what encode() writes."""
    capture = Path(__file__).resolve().parents[1] / "fixtures" / "v4_captures" / "copy_forms"
    [rung] = decode((capture / "case21.bin").read_bytes())
    first, *rest = rung.conditions
    texts = [t for t in _CMP_TEXTS if len(t) == count + 2]
    rungs = [
        replace(rung, conditions=((compare, *first[1:]), *rest))
        for t in texts
        for compare in _compares(t)
    ]
    path = tmp_path / "compares.csv"
    write_csv(path, rungs)
    assert read_csv(path) == rungs
    assert decode(encode(rungs)) == rungs
