"""Tests that ``encode()`` writes a rung comment outside ASCII as CLICK stores it.

The captures are in ``tests/fixtures/rung_comments``. Its README says what CLICK was
given for each one.
"""

from __future__ import annotations

import warnings

import pytest

import laddercodec._comment
from laddercodec import EncodeError, Rung, decode, encode
from laddercodec._comment import rtf_body
from laddercodec._rtf import cp1252_byte, decode_cp1252
from laddercodec.encode import _PREFIX, _SUFFIX, COMMENT_MAX_BYTES
from tests.ladder.test_comment_charsets import CAPTURES, SHOWN

_ROW = [""] * 31

E_ACUTE = "\N{LATIN SMALL LETTER E WITH ACUTE}"
ARROW = "\N{RIGHTWARDS ARROW}"
EURO = "\N{EURO SIGN}"
ZHONG = "\N{CJK UNIFIED IDEOGRAPH-4E2D}"
EMOJI = "\U0001f600"


def _u(*codes: int) -> str:
    """Return the ``\\uN?`` escape of each of *codes*."""
    return "".join(f"\\u{code}?" for code in codes)


def _round_trip(comment: str) -> Rung:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        [back] = decode(encode(Rung([_ROW], ["NOP"], comment)))
    return back


# -- CLICK's form of each character --

#: The captures whose comment CLICK wrote in the form that encode() writes.
WRITTEN = ["temperature", "euro", "arrow", "emoji", "cjk_u"]


@pytest.mark.parametrize("name", WRITTEN)
def test_encode_writes_the_comment_rtf_that_click_holds(name: str) -> None:
    """CLICK writes no space after ``\\fs20`` when the body starts with a control word.

    ``encode()`` always writes one, and CLICK keeps either form.
    """
    [capture] = decode((CAPTURES / f"{name}.bin").read_bytes())
    [rung] = decode(encode(Rung(capture.conditions, capture.instructions, SHOWN[name])))
    assert capture.comment_rtf is not None and rung.comment_rtf is not None
    if capture.comment_rtf.startswith(_PREFIX):
        assert rung.comment_rtf == capture.comment_rtf
    else:
        assert rung.comment_rtf.replace(b"\\fs20 ", b"\\fs20", 1) == capture.comment_rtf


@pytest.mark.parametrize(
    ("comment", "body"),
    [
        (f"Temp{E_ACUTE}rature 50\N{DEGREE SIGN}C", r"Temp\'e9rature 50\'b0C"),
        (f"a {ARROW} b", f"a {_u(8594)} b"),
        (f"{EURO} \N{MICRO SIGN} \N{LATIN SMALL LETTER SHARP S}", r"\'80 \'b5 \'df"),
        (ZHONG, _u(20013)),
        (EMOJI, _u(55357, 56832)),
        ("\U0000ffff", _u(65535)),
        ("\U0010ffff", _u(56319, 57343)),
        ("\x80", _u(128)),
        ("\x81\x8d\x8f\x90\x9d", r"\'81\'8d\'8f\'90\'9d"),
        (f"**{E_ACUTE}** {{{ARROW}}}\n\\", r"{\b \'e9} \{" + _u(8594) + r"\}\par \\"),
    ],
    ids=[
        "temperature",
        "arrow",
        "euro",
        "cjk",
        "emoji",
        "last-bmp",
        "last-code-point",
        "u0080",
        "c1-controls",
        "styled",
    ],
)
def test_rtf_body_writes_each_character_in_clicks_form(comment: str, body: str) -> None:
    assert rtf_body(comment) == body


def test_the_cp1252_bytes_that_encode_writes_are_the_bytes_that_decode_reads() -> None:
    for byte in range(0x80, 0x100):
        assert cp1252_byte(decode_cp1252(bytes([byte]))) == byte
    assert cp1252_byte("a") is None
    assert cp1252_byte(ARROW) is None


def test_a_character_that_cp1252_lacks_goes_through_one_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    escape = laddercodec._comment._unicode_escape

    def spy(char: str) -> str:
        calls.append(char)
        return escape(char)

    monkeypatch.setattr(laddercodec._comment, "_unicode_escape", spy)
    body = rtf_body(f"caf{E_ACUTE} {ARROW} {EURO} {ZHONG}")
    assert body == rf"caf\'e9 {_u(8594)} \'80 {_u(20013)}"
    assert calls == [ARROW, ZHONG]


# -- The round trip --

ROUND_TRIP = {
    "e-acute": f"caf{E_ACUTE}",
    "degree": "50\N{DEGREE SIGN}C",
    "euro": f"{EURO} 5",
    "arrow": f"a {ARROW} b",
    "cjk": f"{ZHONG}\N{CJK UNIFIED IDEOGRAPH-6587}",
    "emoji": f"ok {EMOJI}",
    **{f"c1-{byte:#04x}": f"a{chr(byte)}b" for byte in (0x81, 0x8D, 0x8F, 0x90, 0x9D)},
    "u0080": "a\x80b",
    "starts-with-hex": f"{E_ACUTE}t{E_ACUTE}",
    "starts-with-unicode": f"{ARROW} next",
    "starts-with-surrogate-pair": f"{EMOJI} x",
    "starts-with-backslash": "\\x",
    "starts-with-brace": "{x}",
    "starts-with-closing-brace": "} x",
    "starts-with-line-break": "\nline two",
    "starts-with-style": f"**{E_ACUTE}** x",
}


@pytest.mark.parametrize("comment", ROUND_TRIP.values(), ids=ROUND_TRIP.keys())
def test_decode_reads_back_the_comment_that_encode_writes(comment: str) -> None:
    assert _round_trip(comment).comment == comment


# -- The length limit --


@pytest.mark.parametrize(
    ("unit", "size"),
    [("a", 1), (E_ACUTE, 4), (ARROW, 7), (EMOJI, 16)],
    ids=["ascii", "hex", "unicode", "surrogate-pair"],
)
def test_the_length_limit_counts_the_bytes_of_each_escape(unit: str, size: int) -> None:
    count, rest = divmod(COMMENT_MAX_BYTES, size)
    comment = unit * count + "a" * rest
    assert len(rtf_body(comment)) == COMMENT_MAX_BYTES
    assert _round_trip(comment).comment == comment
    longer = unit * (count + 1) + "a" * rest
    with pytest.raises(EncodeError, match=f"would store {COMMENT_MAX_BYTES + size} bytes"):
        encode(Rung([_ROW], ["NOP"], longer))


def test_a_comment_too_long_says_how_many_bytes_to_cut() -> None:
    with pytest.raises(EncodeError) as exc:
        encode(Rung([_ROW], ["NOP"], E_ACUTE * 350 + "ab"))
    assert str(exc.value) == (
        "The comment is too long: CLICK would store 1402 bytes, and the limit is 1400. "
        f"A character outside ASCII takes more than one byte: {E_ACUTE} takes 4 (\\'e9), "
        "and a character that code page 1252 lacks takes 6 or more. Shorten the comment by "
        "at least 2 bytes."
    )
    # A log file in code page 1252 can hold the message.
    str(exc.value).encode("cp1252")


def test_a_lone_surrogate_decodes_as_the_replacement_character() -> None:
    """A surrogate outside a pair is not text. encode() writes it, and decode() reads U+FFFD."""
    lone = chr(0xD800)
    assert rtf_body(f"a{lone}b") == f"a{_u(55296)}b"
    assert _round_trip(f"a{lone}b").comment == "a\N{REPLACEMENT CHARACTER}b"


def test_a_comment_too_long_names_its_rung_among_several() -> None:
    rungs = [Rung([_ROW], ["NOP"], "ok"), Rung([_ROW], ["NOP"], ARROW * 201)]
    with pytest.raises(
        EncodeError, match="^The comment of rung 1 is too long: CLICK would store 1407"
    ):
        encode(rungs)


def test_a_comment_at_the_limit_encodes_among_several() -> None:
    comment = ARROW * 200
    rungs = [Rung([_ROW], ["NOP"], "ok"), Rung([_ROW], ["NOP"], comment)]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        back = decode(encode(rungs))
    assert [r.comment for r in back] == ["ok", comment]
    assert back[1].comment_rtf == _PREFIX + rtf_body(comment).encode("ascii") + _SUFFIX
