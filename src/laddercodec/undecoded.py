"""Marker rungs, which stand in for a rung that a decoder cannot decode or ``write_csv``
cannot write.

A marker always replaces a whole rung, because the rows of a rung share wires. If a rung
fails, the decoder puts one marker rung (:func:`marker_rung`) in its place and warns with
:class:`UndecodedRungWarning`. If only the comment fails and the rung's logic decodes, the
rung keeps its logic and is not a marker. Its comment becomes :func:`comment_note`,
followed by the text that :func:`recover_text` finds in the comment's bytes. The decoder
then warns with :class:`UndecodedCommentWarning`.
"""

from __future__ import annotations

import codecs
import re
import struct
import warnings
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from .instructions.undecoded import Stop, Undecoded
from .topology import CONDITION_COLUMNS

if TYPE_CHECKING:
    from .decode import Rung


class UndecodedRungWarning(UserWarning):
    """Issued when an undecoded marker rung stands in place of a rung.

    A decoder issues it for a rung that it cannot decode, and ``write_csv`` for a rung that
    it cannot write.

    Attributes
    ----------
    marker:
        The :class:`~laddercodec.instructions.Undecoded` marker. It says where the rung is
        and what went wrong.
    program:
        The name of the program when the warning comes from
        :func:`laddercodec.decode_program`, else ``None``.
    """

    def __reduce__(self):
        return (type(self), (self.marker, self.program))

    def __init__(self, marker: Undecoded, program: str | None = None) -> None:
        self.marker = marker
        self.program = program
        prefix = f"program {program!r}, " if program is not None else ""
        super().__init__(
            f"{prefix}{marker.where} is not decoded, and an undecoded marker stands in for it: "
            f"{marker.error}"
        )


class UndecodedCommentWarning(UserWarning):
    """Issued when a rung's comment cannot be decoded. The rung keeps its logic.

    The rung's comment becomes ``UNDECODED comment: <error>``. The next line holds the
    plain text that can be read out of the comment's bytes, if there is any. If that text
    would make the comment too long to encode, it is cut short and ends with ``...``. The
    rung's ``comment_rtf`` keeps the comment's bytes. The rung is not a marker, so
    ``Program.undecoded`` does not list it.

    Attributes
    ----------
    rung:
        Index of the rung, from 0.
    error:
        Why the comment could not be decoded, on one line.
    program:
        The name of the program when the warning comes from
        :func:`laddercodec.decode_program`, else ``None``.
    """

    def __reduce__(self):
        return (type(self), (self.rung, self.error, self.program))

    def __init__(self, rung: int, error: str, program: str | None = None) -> None:
        self.rung = rung
        self.error = error
        self.program = program
        prefix = f"program {program!r}, " if program is not None else ""
        super().__init__(
            f"{prefix}the comment of rung {rung} is not decoded, and the rung keeps its "
            f"logic: {error}"
        )


#: The exceptions that a decoder catches as a sign of bytes it cannot read, such as a
#: malformed value or a read past the end.
BAD_BYTES: tuple[type[Exception], ...] = (ValueError, IndexError, KeyError, struct.error)


def one_line(text: str) -> str:
    """Return *text* on one line, each run of white space as one space, for
    :attr:`Undecoded.error`."""
    return " ".join(text.split())


def reason(exc: BaseException) -> str:
    """Return the message of *exc* on one line, for :attr:`Undecoded.error`.

    If the message is empty, return the name of the exception's type."""
    return one_line(str(exc)) or type(exc).__name__


def to_the_end(error: str, rung: int) -> str:
    """Return *error* with a note that decoding stopped, for a marker that stands for rung
    *rung* and every rung after it."""
    return f"{error}; decoding stopped, so this marker stands for rung {rung} to the end"


def comment_note(error: str) -> str:
    """Return the note that starts the comment of a rung whose comment could not be decoded."""
    return f"UNDECODED comment: {error}"


#: RTF destinations whose group holds no comment text.
_RTF_DESTINATIONS = frozenset(
    {
        "fonttbl",
        "colortbl",
        "stylesheet",
        "info",
        "pict",
        "object",
        "header",
        "footer",
        "footnote",
        "fldinst",
        "listtable",
        "listoverridetable",
        "generator",
        "rsidtbl",
        "themedata",
        "datastore",
        "latentstyles",
    }
)

#: RTF control words that stand for one character.
_RTF_CHARS = {
    "par": "\n",
    "line": "\n",
    "tab": " ",
    "emdash": "-",
    "endash": "-",
    "lquote": "'",
    "rquote": "'",
    "ldblquote": '"',
    "rdblquote": '"',
    "bullet": "*",
}

_RTF_CODE_PAGE = re.compile(rb"\\ansicpg(\d+)")
_RTF_WORD = re.compile(r"\\([A-Za-z]+)(-?\d+)? ?")
#: A control word's number longer than this is not read.
_MAX_ARG_DIGITS = 6
_HEX_PAIR = re.compile(r"[0-9A-Fa-f]{2}")


def _rtf_text(payload: bytes) -> str:
    """Return the text of RTF *payload*, with no styling."""
    encoding = "cp1252"
    match = _RTF_CODE_PAGE.search(payload)
    if match is not None:
        try:
            encoding = codecs.lookup(f"cp{match.group(1).decode('ascii')}").name
        except LookupError:
            pass
    body = payload.decode(encoding, errors="replace")

    out: list[str] = []
    stack: list[tuple[bool, int]] = []  # per open group: skipping it, and its \uc count
    skip, uc = False, 1
    first = False  # just after an opening brace
    fallback = 0  # characters left to drop after a \u
    i, n = 0, len(body)
    while i < n:
        ch = body[i]
        if ch == "{":
            stack.append((skip, uc))
            first = True
            i += 1
            continue
        if ch == "}":
            if not stack or (len(stack) == 1 and body[i + 1 :].strip(" \t\r\n\x00")):
                i += 1  # stray, or closing the outermost group with text still to come
                continue
            skip, uc = stack.pop()
            if not stack:
                break  # the outermost group is closed, with only whitespace after it
            first = False
            i += 1
            continue
        was_first, first = first, False
        if ch != "\\":
            if fallback:
                fallback -= 1
            elif not skip and ch >= " " and ch != "\x7f":
                out.append(ch)
            i += 1
            continue
        nxt = body[i + 1] if i + 1 < n else ""
        if nxt == "'":
            digits = body[i + 2 : i + 4]
            if _HEX_PAIR.fullmatch(digits):
                if fallback:
                    fallback -= 1
                elif not skip:
                    out.append(bytes([int(digits, 16)]).decode(encoding, errors="replace"))
                i += 4
            else:
                i += 2
        elif nxt.isalpha():
            word = _RTF_WORD.match(body, i)
            assert word is not None
            name, arg = word.group(1), word.group(2)
            i = word.end()
            if name in _RTF_DESTINATIONS and was_first:
                skip = True
            elif name == "uc" and arg is not None:
                if len(arg) <= _MAX_ARG_DIGITS:
                    uc = max(int(arg), 0)
            elif name == "u" and arg is not None and len(arg) <= _MAX_ARG_DIGITS:
                value = int(arg)
                if not skip and -0x8000 <= value <= 0xFFFF:
                    out.append(chr(value % 0x10000))
                fallback = uc
            elif name in _RTF_CHARS and not skip:
                out.append(_RTF_CHARS[name])
        else:
            if nxt == "*":
                skip = skip or was_first
            elif skip or not nxt:
                pass
            elif nxt in "\\{}":
                out.append(nxt)
            elif nxt in "\r\n":
                out.append("\n")
            elif nxt == "~":
                out.append(" ")
            elif nxt == "_":
                out.append("-")
            i += 2
    # Join \u surrogate pairs; a lone half is dropped.
    text = "".join(out).encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
    return text.replace("\ufffd", "")


def recover_text(payload: bytes) -> str:
    """Return the plain text that can be read out of the comment bytes *payload*.

    The function makes a best effort and never raises. It drops control words, control
    symbols and destination groups (the font and colour tables, ``\\*`` groups). It keeps
    the text, turns paragraph breaks into line breaks, and reads well-formed ``\\'hh`` and
    ``\\uN`` escapes. It keeps non-ASCII characters, as the decoder does for a comment that
    decodes. ``encode()`` reduces them to ASCII when it writes. If no text is left, the
    function returns ``""``.
    """
    try:
        text = _rtf_text(payload)
    except Exception:  # whatever went wrong, return no text rather than raise
        return ""
    return "\n".join(line.rstrip() for line in text.strip().split("\n"))


def recovered_comment(error: str, payload: bytes) -> str:
    """Return :func:`comment_note` for *error*, then the text that :func:`recover_text` finds
    in *payload*.

    The text starts on its own line, so that the note's error does not run into it.
    ``encode()`` refuses an RTF body over ``COMMENT_MAX_BYTES`` bytes, however many rows the
    rung has. If the whole comment would be longer than that, the text is cut and ends with
    ``...``. If the note alone is too long, its error is cut in the same way. The styling
    characters ``*`` and ``_`` in the text are not escaped, because the encoder has no
    escape for them.
    """
    from .encode import COMMENT_MAX_BYTES, _build_rtf_body

    def size(comment: str) -> int:
        return len(_build_rtf_body(comment).encode("cp1252"))

    def longest(fits: Callable[[int], bool], high: int) -> int:
        """Return the largest k in 0..high for which *fits* is true, found by bisection.

        Return 0 if there is none."""
        low = 0
        while low < high:
            mid = (low + high + 1) // 2
            if fits(mid):
                low = mid
            else:
                high = mid - 1
        return low

    note = comment_note(error)
    if size(note) > COMMENT_MAX_BYTES:
        keep = longest(
            lambda k: size(comment_note(error[:k].rstrip() + "...")) <= COMMENT_MAX_BYTES,
            len(error),
        )
        note = comment_note(error[:keep].rstrip() + "...")
    text = recover_text(payload)
    if not text:
        return note
    comment = f"{note}\n{text}"
    if size(comment) <= COMMENT_MAX_BYTES:
        return comment

    def cut(k: int) -> str:
        return f"{note}\n{text[:k].rstrip()}..."

    keep = longest(lambda k: size(cut(k)) <= COMMENT_MAX_BYTES, len(text))
    return cut(keep) if keep else note


def read_comment(rtf: bytes | None, rung: int, failed: list[tuple[int, str]]) -> str | None:
    """Return the comment of rung *rung*, decoded from *rtf*.

    Return None if *rtf* is None. If *rtf* cannot be decoded, return
    :func:`recovered_comment` and add ``(rung, error)`` to *failed* for
    :func:`warn_comments`.
    """
    if rtf is None:
        return None
    from .decode import _decode_rtf  # decode imports this module

    try:
        return _decode_rtf(rtf)
    except BAD_BYTES as exc:
        error = reason(exc)
        failed.append((rung, error))
        return recovered_comment(error, rtf)


def warn_comments(failed: Iterable[tuple[int, str]], *, program: str | None = None) -> None:
    """Emit one :class:`UndecodedCommentWarning` per ``(rung, error)`` in *failed*."""
    for rung, error in failed:
        warnings.warn(UndecodedCommentWarning(rung, error, program), stacklevel=3)


def marker_rung(marker: Undecoded, comment: str | None = None) -> Rung:
    """Return the one-row rung that stands for a rung that could not be decoded.

    Its comment is the marker's headline, followed by *comment* if one is given. A caller
    passes the rung's own comment when that comment decoded. The one row is a wire from
    the rail straight into the marker, with no conditions.
    """
    from .decode import Rung

    lines = [marker.headline, comment] if comment else [marker.headline]
    return Rung(
        logical_rows=1,
        conditions=[["-"] * CONDITION_COLUMNS],
        instructions=[marker],
        comment="\n".join(lines),
    )


def markers(rungs: Iterable[Rung]) -> list[Undecoded]:
    """Return every undecoded marker in *rungs*, in rung order."""
    return [af for rung in rungs for af in rung.instructions if isinstance(af, Undecoded)]


def warn_undecoded(rungs: Iterable[Rung], *, program: str | None = None) -> None:
    """Emit one :class:`UndecodedRungWarning` per marker in *rungs*."""
    for marker in markers(rungs):
        warnings.warn(UndecodedRungWarning(marker, program), stacklevel=3)


__all__ = [
    "BAD_BYTES",
    "Stop",
    "Undecoded",
    "UndecodedCommentWarning",
    "UndecodedRungWarning",
    "comment_note",
    "marker_rung",
    "markers",
    "one_line",
    "read_comment",
    "reason",
    "recover_text",
    "recovered_comment",
    "to_the_end",
    "warn_comments",
    "warn_undecoded",
]
