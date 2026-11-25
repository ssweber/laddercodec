"""Tests that the decoders read each rung comment that CLICK writes outside ASCII.

The captures are in ``tests/fixtures/rung_comments``. Its README says what CLICK was
given for each one.
"""

from __future__ import annotations

import struct
import warnings
from pathlib import Path

import pytest

from laddercodec import Rung, UndecodedCommentWarning, decode, decode_program
from laddercodec.decode import _decode_rtf
from laddercodec.undecoded import recover_text

CAPTURES = Path(__file__).parent.parent / "fixtures" / "rung_comments"

#: The comment that CLICK shows for each capture.
SHOWN = {
    "temperature": "Température 50°C",
    "euro": "€ µ ß",
    "arrow": "a → b",
    "simsun": "中",
    "emoji": "\U0001f600",
    "cjk_u": "中",
    "emoji_signed": "\U0001f600",
}

#: CLICK's RTF before the body, with the space after \fs20 left out.
HEAD = (
    b"{\\rtf1\\ansi\\ansicpg1252\\deff0\\deflang1033"
    b"{\\fonttbl{\\f0\\fnil\\fcharset0 Arial;}}\r\n"
    b"\\viewkind4\\uc1\\pard\\fs20"
)
TAIL = b"\r\n\\par }\r\n\x00"


def _rtf(body: bytes, head: bytes = HEAD) -> bytes:
    return head + body + TAIL


def _fonts(table: bytes, header: bytes = b"\\fs20") -> bytes:
    """Return CLICK's RTF head with the font table *table* and *header* after ``\\pard``."""
    return (
        b"{\\rtf1\\ansi\\ansicpg1252\\deff0\\deflang1033{\\fonttbl" + table + b"}\r\n"
        b"\\viewkind4\\uc1\\pard" + header
    )


def _decoded(data: bytes) -> tuple[list[Rung], list[warnings.WarningMessage]]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        rungs = decode(data)
    return rungs, caught


def _with_rtf(data: bytes, rtf: bytes) -> bytes:
    """Return the one-rung clipboard *data* with rung 0's comment RTF replaced by *rtf*.

    The comment pushes the grid, so the bytes after it move. The buffer keeps its size.
    """
    old = struct.unpack_from("<I", data, 0x294)[0]
    out = data[:0x294] + struct.pack("<I", len(rtf)) + rtf + data[0x298 + old :]
    if len(out) > len(data):
        assert not out[len(data) :].strip(b"\x00")
        return out[: len(data)]
    return out + bytes(len(data) - len(out))


BASE = (CAPTURES / "temperature.bin").read_bytes()


# -- The captures --


@pytest.mark.parametrize("name", sorted(SHOWN))
def test_decode_reads_the_comment_that_click_shows(name: str) -> None:
    [rung], caught = _decoded((CAPTURES / f"{name}.bin").read_bytes())
    assert rung.comment == SHOWN[name]
    assert caught == []


@pytest.mark.parametrize("name", sorted(p.stem for p in CAPTURES.glob("*.scr")))
def test_decode_program_reads_the_comment_that_decode_reads(name: str) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        program = decode_program((CAPTURES / f"{name}.scr").read_bytes())
    [clipboard] = decode((CAPTURES / f"{name}.bin").read_bytes())
    [rung] = program.rungs
    assert rung.comment == SHOWN[name]
    assert rung.comment_rtf == clipboard.comment_rtf


@pytest.mark.parametrize("name", sorted(SHOWN))
def test_recover_text_reads_each_capture_as_decode_does(name: str) -> None:
    [rung] = decode((CAPTURES / f"{name}.bin").read_bytes())
    assert rung.comment_rtf is not None
    assert recover_text(rung.comment_rtf) == SHOWN[name]


# -- Where the body starts --


@pytest.mark.parametrize(
    ("body", "want"),
    [
        (b"\\'80 \\'b5 \\'df", "€ µ ß"),
        (b"\\u8594? b", "→ b"),
        (b"\\u20013?", "中"),
        (b"{\\b bold} plain", "**bold** plain"),
        (b" text", "text"),
        (b"  text", " text"),
        (b"text", "text"),
    ],
    ids=["hex", "unicode", "unicode-only", "group", "space", "two-spaces", "letter"],
)
def test_the_body_starts_where_the_font_size_control_word_ends(body: bytes, want: str) -> None:
    """A space after \\fs20 ends the control word and is not text. Any other byte is text."""
    assert _decode_rtf(_rtf(body)) == want


def test_a_font_family_that_starts_with_fs_is_not_the_font_size() -> None:
    head = _fonts(b"{\\f0\\fswiss\\fcharset0 Arial;}")
    assert _decode_rtf(_rtf(b"\\'80 x", head)) == "€ x"


# -- Surrogate pairs --


@pytest.mark.parametrize(
    "pair",
    [b"\\u-10179?\\u-8704?", b"\\u55357?\\u56832?", b"\\u-10179?\\u56832?"],
    ids=["signed", "unsigned", "mixed"],
)
def test_a_surrogate_pair_reads_as_one_character(pair: bytes) -> None:
    assert _decode_rtf(_rtf(b" a" + pair + b"b")) == "a\U0001f600b"


@pytest.mark.parametrize(
    ("body", "want"),
    [
        (b" a\\u55357?b", "a\ufffdb"),
        (b" a\\u56832?b", "a\ufffdb"),
        (b"\\u56832?\\u55357?", "\ufffd\ufffd"),
        (b"\\u55357?\\u55357?\\u56832?", "\ufffd\U0001f600"),
        (b"\\u55357?", "\ufffd"),
    ],
    ids=["high", "low", "low-then-high", "two-highs", "high-at-end"],
)
def test_a_surrogate_outside_a_pair_reads_as_the_replacement_character(
    body: bytes, want: str
) -> None:
    comment = _decode_rtf(_rtf(body))
    assert comment == want
    comment.encode("utf-8")  # no surrogate is left


def test_a_lone_surrogate_from_a_capture_writes_as_utf8() -> None:
    [rung], caught = _decoded(_with_rtf(BASE, _rtf(b"\\u-10179?")))
    assert rung.comment == "\ufffd"
    assert caught == []


# -- Font charsets --

SIMSUN = b"{\\f0\\fmodern\\fprq6\\fcharset134 SimSun;}{\\f1\\fnil\\fcharset0 Arial;}"


def test_hex_bytes_read_in_the_charset_of_the_current_font() -> None:
    head = _fonts(SIMSUN, b"\\f1\\fs20")
    body = b" caf\\'e9 \\f0\\'d6\\'d0\\'b9\\'fa\\f1  \\'e9"
    assert _decode_rtf(_rtf(body, head)) == "café 中国 é"


def test_the_default_font_sets_the_charset_when_the_header_names_no_font() -> None:
    head = _fonts(SIMSUN)
    assert _decode_rtf(_rtf(b"\\'d6\\'d0", head)) == "中"
    assert _decode_rtf(_rtf(b"\\'e9", head.replace(b"\\deff0", b"\\deff1"))) == "é"


def test_a_group_restores_the_font() -> None:
    head = _fonts(SIMSUN, b"\\f1\\fs20")
    assert _decode_rtf(_rtf(b" {\\f0\\'d6\\'d0}\\'e9", head)) == "中é"


def test_a_gbk_character_may_end_in_an_ascii_byte() -> None:
    """In GBK, the second byte of a character can be from 0x40 to 0x7E."""
    head = _fonts(SIMSUN, b"\\f0\\fs20")
    assert _decode_rtf(_rtf(b"\\'81@", head)) == b"\x81@".decode("gbk")


@pytest.mark.parametrize(
    ("body", "want"),
    [
        (b"\\'d6\\f1  ok", "\ufffd ok"),
        (b"\\'ff\\'ff\\f1  ok", "\ufffd\ufffd ok"),
        (b"\\'d6\\'d0\\'d6\\f1  ok\\f0\\'d6", "\u4e2d\ufffd ok\ufffd"),
    ],
    ids=["lead-byte-alone", "not-gbk", "twice-in-one-font"],
)
def test_bytes_that_gbk_cannot_read_give_a_warning_and_keep_the_rest(
    body: bytes, want: str
) -> None:
    rtf = _rtf(body, _fonts(SIMSUN, b"\\f0\\fs20"))
    [rung], caught = _decoded(_with_rtf(BASE, rtf))
    assert rung.comment == want
    [warning] = [w.message for w in caught]
    assert isinstance(warning, UndecodedCommentWarning)
    assert warning.partial
    assert "font 0 has \\fcharset134" in warning.error
    assert recover_text(rtf) == want


UNKNOWN = b"{\\f0\\fnil\\fcharset0 Arial;}{\\f1\\fnil\\fcharset128 MS Gothic;}"


def test_a_charset_that_laddercodec_does_not_read_gives_a_warning_and_keeps_the_rest() -> None:
    rtf = _rtf(b" a \\f1\\'82\\'a0 ok\\f0  caf\\'e9", _fonts(UNKNOWN))
    [rung], caught = _decoded(_with_rtf(BASE, rtf))
    # The bytes 0x82 and 0xA0 in font 1 read as U+FFFD. Its ASCII and font 0 read as text.
    assert rung.comment == "a \ufffd\ufffd ok café"
    [warning] = [w.message for w in caught]
    assert isinstance(warning, UndecodedCommentWarning)
    assert warning.partial
    assert warning.rung == 0
    assert "\\fcharset128" in warning.error
    assert str(warning).startswith("part of the comment of rung 0 is not decoded: font 1 ")
    assert recover_text(rtf) == "a \ufffd\ufffd ok café"


def test_a_charset_that_laddercodec_does_not_read_warns_in_decode_program() -> None:
    data = (CAPTURES / "simsun.scr").read_bytes()
    old = (CAPTURES / "simsun.bin").read_bytes()
    [rung] = decode(old)
    assert rung.comment_rtf is not None and rung.comment_rtf in data
    rtf = rung.comment_rtf.replace(b"\\fcharset134", b"\\fcharset136")
    at = data.index(rung.comment_rtf)
    data = data[: at - 4] + struct.pack("<I", len(rtf)) + rtf + data[at + len(rung.comment_rtf) :]
    with pytest.warns(UndecodedCommentWarning) as caught:
        program = decode_program(data)
    [warning] = [w.message for w in caught]
    assert isinstance(warning, UndecodedCommentWarning)
    assert warning.partial and warning.program == "Main Program"
    assert "\\fcharset136" in warning.error
    assert program.rungs[0].comment == "\ufffd\ufffd"


def test_ascii_in_a_charset_that_laddercodec_does_not_read_gives_no_warning() -> None:
    rtf = _rtf(b" \\f1 ok", _fonts(UNKNOWN))
    [rung], caught = _decoded(_with_rtf(BASE, rtf))
    assert rung.comment == "ok"
    assert caught == []


# -- The five bytes that Python's cp1252 has no character for --

HOLES = [0x81, 0x8D, 0x8F, 0x90, 0x9D]


@pytest.mark.parametrize("byte", HOLES, ids=[f"{b:#04x}" for b in HOLES])
def test_a_cp1252_hole_as_hex_reads_as_the_control_character(byte: int) -> None:
    rtf = _rtf(b" a\\'" + f"{byte:02x}".encode() + b"b")
    [rung], caught = _decoded(_with_rtf(BASE, rtf))
    assert rung.comment == f"a{chr(byte)}b"
    assert caught == []
    assert recover_text(rtf) == f"a{chr(byte)}b"


@pytest.mark.parametrize("byte", HOLES, ids=[f"{b:#04x}" for b in HOLES])
def test_a_cp1252_hole_as_a_raw_byte_reads_as_the_control_character(byte: int) -> None:
    rtf = _rtf(b" a" + bytes([byte]) + b"b")
    [rung], caught = _decoded(_with_rtf(BASE, rtf))
    assert rung.comment == f"a{chr(byte)}b"
    assert caught == []
    assert recover_text(rtf) == f"a{chr(byte)}b"


# -- decode and recover_text read the same RTF the same way --


@pytest.mark.parametrize(
    "rtf",
    [
        _rtf(b"\\'80 \\'b5 \\'df"),
        _rtf(b" a\\u-10179?\\u-8704?b\\u55357?c"),
        _rtf(b"\\'d6\\'d0\\f1  x", _fonts(SIMSUN, b"\\f0\\fs20")),
        _rtf(b" a \\f1\\'82\\'a0 ok", _fonts(UNKNOWN)),
        _rtf(b" \\'81\x8d\\'8f\x90\\'9d"),
        _rtf(b" \\u-3913\\u-8704?"),
        _rtf(b" \\uc2\\u8217\\'92\\'92x"),
    ],
    ids=["hex", "surrogates", "gbk", "unknown-charset", "holes", "control-as-fallback", "uc2"],
)
def test_recover_text_reads_the_text_that_decode_reads(rtf: bytes) -> None:
    assert recover_text(rtf) == _decode_rtf(rtf)
