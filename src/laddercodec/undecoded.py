"""Marker rungs: what the decoders and ``write_csv`` put in place of a rung they can't read.

The unit is the rung, because its rows share wires.  A rung that fails becomes one marker
rung (:func:`marker_rung`), and the decoder warns with :class:`UndecodedRungWarning`.  A
comment that fails, on a rung whose logic decodes, is not a marker: the rung keeps its
logic, its comment becomes :func:`comment_note` followed by the text
:func:`recover_text` finds in the comment's bytes, and the decoder warns with
:class:`UndecodedCommentWarning`.
"""

from __future__ import annotations

import codecs
import re
import struct
import warnings
from collections.abc import Iterable
from typing import TYPE_CHECKING

from .instructions.undecoded import Stop, Undecoded
from .topology import CONDITION_COLUMNS

if TYPE_CHECKING:
    from .decode import Rung


class UndecodedRungWarning(UserWarning):
    """A rung could not be decoded, and an undecoded marker stands in its place.

    Attributes
    ----------
    marker:
        The :class:`~laddercodec.instructions.Undecoded` marker: why, and where.
    program:
        Program name for :func:`laddercodec.decode_program`, else ``None``.
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
    """A rung's comment could not be decoded; the rung keeps its logic.

    The rung's comment is ``UNDECODED comment: <error>``, then on a new line the plain text
    that can be read out of the comment's bytes (nothing, when none can be; cut short and
    ended with ``...`` when it would make the comment too long to encode).  Its
    ``comment_rtf`` keeps the comment's bytes.  The rung is not a marker, so
    ``Program.undecoded`` does not list it.

    Attributes
    ----------
    rung:
        Index of the rung, from 0.
    error:
        Why the comment could not be decoded, on one line.
    program:
        Program name for :func:`laddercodec.decode_program`, else ``None``.
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


#: What a decoder catches as bytes it can't read: a malformed value, or a read past the end.
BAD_BYTES: tuple[type[Exception], ...] = (ValueError, IndexError, KeyError, struct.error)


def one_line(text: str) -> str:
    """*text* with its line breaks as spaces, for :attr:`Undecoded.error`."""
    return " ".join(text.split())


def reason(exc: BaseException) -> str:
    """The error an exception gives, on one line, for :attr:`Undecoded.error`."""
    return one_line(str(exc)) or type(exc).__name__


def to_the_end(error: str, rung: int) -> str:
    """*error* for a marker that stands for rung *rung* and every rung after it."""
    return f"{error}; decoding stopped, so this marker stands for rung {rung} to the end"


def comment_note(error: str) -> str:
    """The comment a rung gets in place of one that could not be decoded."""
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
_HEX_PAIR = re.compile(r"[0-9A-Fa-f]{2}")


def _rtf_text(payload: bytes) -> str:
    """The text runs of RTF *payload*, with no styling."""
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
            if stack:
                skip, uc = stack.pop()
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
                uc = int(arg) if int(arg) > 0 else 0
            elif name == "u" and arg is not None:
                if not skip:
                    out.append(chr(int(arg) % 0x10000))
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
    """The plain text that can be read out of the comment bytes *payload*.

    Best effort, and it never raises.  Control words, control symbols and destination
    groups (the font and colour tables, ``\\*`` groups) are dropped; text runs are kept,
    paragraph breaks become line breaks, and well-formed ``\\'hh`` and ``\\uN`` escapes are
    read.  Non-ASCII characters are kept, as in a comment that decodes; ``encode()`` reduces
    them to ASCII when it writes.  It is ``""`` when nothing is left.
    """
    try:
        text = _rtf_text(payload)
    except Exception:  # best effort: whatever went wrong, there is no text to give
        return ""
    return "\n".join(line.rstrip() for line in text.strip().split("\n"))


def recovered_comment(error: str, payload: bytes) -> str:
    """:func:`comment_note` for *error*, then the text :func:`recover_text` finds in *payload*.

    The text starts on its own line, so the note's error does not run into it.  It is cut,
    and ended with ``...``, where the whole comment would be too long for ``encode()``,
    which refuses an RTF body over ``COMMENT_MAX_BYTES`` bytes whatever the rung's rows.
    The styling characters ``*`` and ``_`` in the text are not escaped, since the encoder
    has no escape for them.
    """
    from .encode import COMMENT_MAX_BYTES, _build_rtf_body

    note = comment_note(error)
    text = recover_text(payload)
    if not text:
        return note

    def size(comment: str) -> int:
        return len(_build_rtf_body(comment).encode("cp1252"))

    comment = f"{note}\n{text}"
    cut = len(text)
    while size(comment) > COMMENT_MAX_BYTES:
        if cut == 0:
            return note
        cut = max(min(cut - 1, cut - (size(comment) - COMMENT_MAX_BYTES)), 0)
        comment = f"{note}\n{text[:cut].rstrip()}..."
    return comment


def read_comment(rtf: bytes | None, rung: int, failed: list[tuple[int, str]]) -> str | None:
    """Rung *rung*'s comment from *rtf*, or :func:`recovered_comment` when it can't be decoded.

    A failure is added to *failed* as ``(rung, error)`` for :func:`warn_comments`.
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
    """The one-row rung that stands for a rung that could not be decoded.

    Its comment is the marker's headline, then *comment* (the rung's own, when that
    decoded).  Its one row is wired from the rail, unconditional, into the marker.
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
    """Every undecoded marker in *rungs*, in rung order."""
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
