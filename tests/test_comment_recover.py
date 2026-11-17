"""An undecoded comment keeps the plain text that can be recovered from its bytes."""

from __future__ import annotations

import pytest

from laddercodec import Rung, UndecodedCommentWarning, decode, decode_program, encode
from laddercodec.encode import COMMENT_MAX_BYTES, _build_rtf_body
from laddercodec.undecoded import comment_note, recover_text, recovered_comment
from tests.ladder.test_decode_program import _synthetic_scr

PREFIX = (
    b"{\\rtf1\\ansi\\ansicpg1252\\deff0\\deflang1033"
    b"{\\fonttbl{\\f0\\fnil\\fcharset0 Arial;}}\r\n"
    b"\\viewkind4\\uc1\\pard\\fs20 "
)
SUFFIX = b"\r\n\\par }\r\n\x00"


def _rtf(body: bytes) -> bytes:
    return PREFIX + body + SUFFIX


@pytest.mark.parametrize(
    ("payload", "want"),
    [
        (_rtf(b"hello"), "hello"),
        (_rtf(b"one\\par two"), "one\ntwo"),
        (_rtf(b"{\\b bold} and {\\i\\ul more}"), "bold and more"),
        # truncated: no closing brace, no suffix
        (PREFIX + b"cut {\\b off", "cut off"),
        (b"{\\rtf1\\ansi{\\fonttbl{\\f0 Arial;", ""),
        # unknown destination groups are dropped, with their nested groups
        (_rtf(b"a{\\*\\generator Foo {bar}; 1}b"), "ab"),
        (_rtf(b"{\\colortbl ;\\red255;}x"), "x"),
        # escapes
        (_rtf(b"caf\\'e9"), "caf\u00e9"),
        (_rtf(b"A\\'4"), "A4"),
        (_rtf(b"A\\'zzB"), "Azz" + "B"),
        (_rtf(b"\\u8364?x"), "\u20acx"),
        (_rtf(b"\\uc0\\u65 x"), "Ax"),
        (_rtf(b"\\u65\\'41B"), "AB"),
        (_rtf(b"\\u"), ""),
        (_rtf(b"\\u-3913\\u-8704?"), "\uf0b7"),
        (_rtf(b"lone \\u-10179?end"), "lone end"),
        (_rtf(b"a\\\\b\\{c\\}"), "a\\b{c}"),
        (_rtf(b"a\\~b\\_c"), "a b-c"),
        # a closer that closes the outermost group while text follows is stray: reading goes on
        (_rtf(b"a}}b"), "ab"),
        (_rtf(b"{\\b one}} two"), "one two"),
        (_rtf(b"one } two\\par three"), "one  two\nthree"),
        # the end is the closer with only whitespace or NULs after it
        (_rtf(b"hi") + b"\r\n \x00", "hi"),
        # bytes after the end are text too, since the record is length-bounded
        (_rtf(b"hi") + b"garbage after", "hi\ngarbage after"),
        # a lone backslash at the end
        (_rtf(b"ab\\"), "ab"),
        # numbers too long to read are skipped, and the text goes on
        (_rtf(b"\\u" + b"9" * 5000 + b" abc \\uc" + b"9" * 5000 + b" hello"), "abc hello"),
        # a value outside the 16-bit range is dropped
        (_rtf(b"a\\u70000?b\\u-40000?c"), "abc"),
        # nothing usable
        (_rtf(b""), ""),
        (_rtf(b"{\\b }\\par \\par "), ""),
        (b"", ""),
        (b"\x00\x01{\\", ""),
    ],
)
def test_recover_text(payload: bytes, want: str) -> None:
    assert recover_text(payload) == want


def test_recover_text_follows_the_declared_code_page() -> None:
    payload = _rtf(b"caf\xe9").replace(b"ansicpg1252", b"ansicpg1250")
    assert recover_text(payload) == "café"
    # a code page Python does not know is read as 1252
    assert recover_text(_rtf(b"ok").replace(b"ansicpg1252", b"ansicpg99999")) == "ok"


def test_recovered_comment_with_no_text_is_the_note() -> None:
    assert recovered_comment("why", _rtf(b"")) == comment_note("why")


def test_recovered_comment_puts_the_text_on_its_own_line() -> None:
    comment = recovered_comment("why", _rtf(b"one\\par two"))
    assert comment == "UNDECODED comment: why\none\ntwo"


def test_recovered_comment_is_cut_to_fit_encode() -> None:
    body = b"word " * 400
    comment = recovered_comment("why", _rtf(body))
    assert comment.startswith("UNDECODED comment: why\nword word ")
    assert comment.endswith("word...")
    assert len(_build_rtf_body(comment).encode("cp1252")) <= COMMENT_MAX_BYTES
    # one more character would not fit
    longer = comment[:-3] + " w..."
    assert len(_build_rtf_body(longer).encode("cp1252")) > COMMENT_MAX_BYTES - 5


def test_recovered_comment_is_cut_where_line_breaks_and_braces_cost_more() -> None:
    comment = recovered_comment("why", _rtf(b"{\\\\}\\par " * 400))
    assert comment.endswith("...")
    assert len(_build_rtf_body(comment).encode("cp1252")) <= COMMENT_MAX_BYTES


def test_recovered_comment_cuts_an_error_too_long_to_encode() -> None:
    error = "x" * (2 * COMMENT_MAX_BYTES)
    comment = recovered_comment(error, _rtf(b"text"))
    assert comment.startswith("UNDECODED comment: xxx")
    assert comment.endswith("...")
    assert len(_build_rtf_body(comment).encode("cp1252")) <= COMMENT_MAX_BYTES


@pytest.mark.parametrize(
    "body",
    [
        b"a\\par " * 800,
        b"{\\\\}\\par " * 5000,
        b"\\u8230?\\'e9\\u8364?" * 3000,
        b"*a*_b_**c**__d__ " * 300,
    ],
    ids=["newlines", "braces", "non-ascii", "styling"],
)
def test_recovered_comment_keeps_the_longest_text_that_fits(body: bytes) -> None:
    comment = recovered_comment("why", _rtf(body))
    size = len(_build_rtf_body(comment).encode("cp1252"))
    assert COMMENT_MAX_BYTES - 12 <= size <= COMMENT_MAX_BYTES
    assert comment.endswith("...")


def _wrong_code_page(data: bytes, index: int = 0) -> bytes:
    """*data* with the code page of its comment number *index* (from 0) changed to 1251."""
    at = -1
    for _ in range(index + 1):
        at = data.index(b"ansicpg1252", at + 1)
    return data[:at] + b"ansicpg1251" + data[at + 11 :]


def _rung(comment: str) -> Rung:
    from tests.test_undecoded import DECODED

    first = DECODED[0]
    return Rung(
        logical_rows=first.logical_rows,
        conditions=first.conditions,
        instructions=first.instructions,
        comment=comment,
    )


@pytest.mark.parametrize(
    "raw",
    [
        "plain text",
        "a * b and snake_case",
        "one * two * three",
        r"brace \{x\} back\\slash",
        r"caf\'e9 \u233?",
    ],
)
def test_a_recovered_comment_survives_encode_and_decode(raw: str) -> None:
    """The recovered text comes back as the same text after an encode and a decode."""
    placeholder = "A" * len(raw)
    data = encode(_rung(placeholder)).replace(placeholder.encode(), raw.encode())
    with pytest.warns(UndecodedCommentWarning) as caught:
        [broken] = decode(_wrong_code_page(data))
    assert isinstance(broken, Rung)
    assert broken.comment_rtf is not None and b"ansicpg1251" in broken.comment_rtf
    (warning,) = [w.message for w in caught]
    assert isinstance(warning, UndecodedCommentWarning)
    note = comment_note(warning.error)
    assert broken.comment is not None and broken.comment.startswith(note + "\n")
    assert broken.comment[len(note) + 1 :] == recover_text(broken.comment_rtf)

    [again] = decode(encode(broken))
    assert isinstance(again, Rung)
    # the text after the note is what a normal comment with the same characters gives
    text = broken.comment[len(note) + 1 :]
    [plain] = decode(encode(_rung(text)))
    assert isinstance(plain, Rung)
    assert again.comment == f"{note}\n{plain.comment}"


def test_scr_comment_text_is_recovered() -> None:
    data = _synthetic_scr(["first", "second line", "third"])
    with pytest.warns(UndecodedCommentWarning) as caught:
        program = decode_program(_wrong_code_page(data, 1))
    (warning,) = [w.message for w in caught]
    assert isinstance(warning, UndecodedCommentWarning)
    assert program.rungs[1].comment == f"UNDECODED comment: {warning.error}\nsecond line"


def test_recovered_comment_of_zero_byte_characters_fits_whole() -> None:
    """Combining marks cost no bytes once encoded, so none of them is cut."""
    comment = recovered_comment("why", _rtf(b"\\u768 " * 100000))
    assert not comment.endswith("...")
    assert len(_build_rtf_body(comment).encode("cp1252")) <= COMMENT_MAX_BYTES
