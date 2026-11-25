"""Read the text bytes of a rung comment's RTF.

A byte of comment text, raw or written as ``\\'hh``, is read in the code page of the font
that is current where the byte stands. The RTF starts with a font table, and each font in
the table names its charset with ``\\fcharsetN``. laddercodec reads two charsets:

- 0, as Windows code page 1252;
- 134, as GBK, where one character can take two bytes.

In a font of any other charset, a byte below 0x80 reads as ASCII and each other byte reads
as U+FFFD. In a GBK font, each byte that GBK cannot read reads as U+FFFD. The decoder warns
in both cases.

Both readers of comment RTF use this module: ``decode._decode_rtf`` and
``undecoded.recover_text``.
"""

from __future__ import annotations

import codecs
import re
from collections.abc import Iterable
from typing import TypeVar

#: The charset that is read as Windows code page 1252.
ANSI_CHARSET = 0
#: The charset that is read as GBK.
GBK_CHARSET = 134
#: The charsets that laddercodec reads.
READ_CHARSETS = frozenset({ANSI_CHARSET, GBK_CHARSET})

# Python's cp1252 codec has no character for 0x81, 0x8D, 0x8F, 0x90 and 0x9D. Windows reads
# each of these bytes as the control character of the same number, and so does this table.
_CP1252_TABLE = "".join(
    bytes([byte]).decode("cp1252", errors="ignore") or chr(byte) for byte in range(256)
)

_FONT_TABLE = b"{\\fonttbl"
# A font number, or the charset of the font named before it. A number longer than six
# digits is not read.
_FONT_WORD = re.compile(rb"\\f(\d{1,6})(?!\d)|\\fcharset(\d{1,6})(?!\d)")
_FONT = re.compile(rb"\\f(\d{1,6})(?!\d)")
_DEFAULT_FONT = re.compile(rb"\\deff(\d{1,6})(?!\d)")

_T = TypeVar("_T")


def decode_cp1252(data: bytes) -> str:
    """Return *data* read as Windows code page 1252.

    The bytes 0x81, 0x8D, 0x8F, 0x90 and 0x9D read as U+0081, U+008D, U+008F, U+0090 and
    U+009D. Every other byte reads as in Python's cp1252 codec.
    """
    return codecs.charmap_decode(data, "strict", _CP1252_TABLE)[0]


def read_bytes(data: bytes, charset: int, *, ansi: str = "cp1252", errors: str = "strict") -> str:
    """Return the text of *data*, the bytes of a font whose charset is *charset*.

    Charset 0 is read with the codec *ansi*. A charset that is not in
    :data:`READ_CHARSETS` gives ASCII for each byte below 0x80 and U+FFFD for each other
    byte. *errors* applies to a byte that the codec cannot read. With ``"strict"``, such a
    byte raises :class:`UnicodeDecodeError`.
    """
    if charset == ANSI_CHARSET:
        if codecs.lookup(ansi).name == "cp1252":
            return decode_cp1252(data)
        return data.decode(ansi, errors=errors)
    if charset == GBK_CHARSET:
        return data.decode("gbk", errors=errors)
    return "".join(chr(byte) if byte < 0x80 else "\ufffd" for byte in data)


def _group_end(rtf: bytes, start: int) -> int:
    """Return the index after the brace that closes the group that opens at ``rtf[start]``.

    Return ``len(rtf)`` if the group is not closed.
    """
    depth = 0
    i = start
    while i < len(rtf):
        byte = rtf[i]
        if byte == 0x5C:  # a backslash, which makes the next byte part of a control
            i += 2
            continue
        if byte == 0x7B:
            depth += 1
        elif byte == 0x7D:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(rtf)


def font_table(rtf: bytes) -> tuple[dict[int, int], int]:
    """Return the charset of each font in the font table of *rtf*, and the end of the table.

    A font with no ``\\fcharset`` has charset 0. If *rtf* has no font table, return an
    empty dict and 0.
    """
    start = rtf.find(_FONT_TABLE)
    if start == -1:
        return {}, 0
    end = _group_end(rtf, start)
    charsets: dict[int, int] = {}
    font: int | None = None
    for match in _FONT_WORD.finditer(rtf, start, end):
        if match.group(1) is not None:
            font = int(match.group(1))
            charsets.setdefault(font, ANSI_CHARSET)
        elif font is not None:
            charsets[font] = int(match.group(2))
    return charsets, end


def default_font(rtf: bytes) -> int:
    """Return the font that ``\\deffN`` in *rtf* names, or 0 if *rtf* has no ``\\deffN``."""
    default = _DEFAULT_FONT.search(rtf)
    return int(default.group(1)) if default else 0


def header_font(header: bytes, table_end: int) -> int:
    """Return the font that is current at the end of *header*, the RTF before the body.

    That is the last ``\\fN`` after the font table, which ends at *table_end*. With no
    ``\\fN`` there, it is the :func:`default_font`.
    """
    fonts = _FONT.findall(header, table_end)
    if fonts:
        return int(fonts[-1])
    return default_font(header)


def join_surrogates(units: Iterable[tuple[_T, str]]) -> list[tuple[_T, str]]:
    """Return *units* with each surrogate pair joined into one character.

    Each unit is a tag, such as a style, and one character. A high surrogate followed by a
    low surrogate becomes the character that the pair stands for, with the tag of the high
    surrogate. A surrogate that is not part of such a pair becomes U+FFFD.
    """
    units = list(units)
    out: list[tuple[_T, str]] = []
    i = 0
    while i < len(units):
        tag, char = units[i]
        if "\ud800" <= char <= "\udbff" and i + 1 < len(units):
            low = units[i + 1][1]
            if "\udc00" <= low <= "\udfff":
                code = 0x10000 + ((ord(char) - 0xD800) << 10) + (ord(low) - 0xDC00)
                out.append((tag, chr(code)))
                i += 2
                continue
        if "\ud800" <= char <= "\udfff":
            char = "\ufffd"
        out.append((tag, char))
        i += 1
    return out
