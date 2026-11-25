"""Read and write the Markdown of a rung comment.

A comment is Markdown in a CSV file and in ``Rung.comment``, and RTF in the binary. The
Markdown has three styles: ``**bold**``, ``*italic*`` or ``_italic_``, and ``__underline__``.
A backslash before ``*``, ``_`` or ``\\`` makes that character text. A backslash before any
other character is a backslash.

A run of ``*`` or ``_`` can open a style only if a character that is not whitespace comes
after it. It can close a style only if a character that is not whitespace comes before it.
A run of ``_`` also opens only where no letter or digit comes before it, and closes only
where no letter or digit comes after it. So ``2 * 3 * 4`` and ``Pump_1_Run`` are text.

A run of ``*`` that can end a style pairs with the nearest run of ``*`` before it that can
start one. The same holds for ``_``. When both runs have at least two characters left, two
characters of each make bold for ``*`` or underline for ``_``. Otherwise one character of
each makes italic. A run that has characters left after it closes can then open. So
``*****WARNING*****`` is bold and italic.

If one of the two runs can both start and end a style, they don't pair when their lengths
add up to a multiple of 3, unless both lengths are multiples of 3. So in ``*a**b**c*``,
the ``**`` after ``a`` can't end the ``*`` before it, because 1 and 2 add up to 3. The
text is italic throughout, with a bold ``b``. The open runs between two runs that pair
become text.

Runs of ``*`` and runs of ``_`` pair apart from each other, so a bold stretch and an
underlined one can overlap. Two runs don't pair if only runs of the other character lie
between them, so ``**__**__`` is text. A run character that does not pair is text.

:func:`rtf_body` reads the Markdown and returns the RTF body that ``encode()`` writes.
:func:`write_runs` returns the Markdown for the styled text that ``decode()`` reads out of
the RTF. Each takes time in proportion to the length of the comment.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace

from ._rtf import cp1252_byte
from .errors import DecodeError


@dataclass(frozen=True)
class Style:
    """The bold, italic and underline state of some comment text."""

    bold: bool = False
    italic: bool = False
    underline: bool = False


PLAIN = Style()

#: A piece of comment text and its style.
Run = tuple[Style, str]

_ATTRS = ("bold", "italic", "underline")
_MARKER = {"bold": "**", "italic": "*", "underline": "__"}
_RTF_CONTROL = {"bold": "b", "italic": "i", "underline": "ul"}
# The style that two characters of a run pair as.
_DOUBLE = {"*": "bold", "_": "underline"}

# A backslash before one of these characters makes the character text.
_ESCAPABLE = "\\*_"


def _read_form(text: str) -> str:
    """Return *text* with ``\\n`` for each ``\\r\\n`` and for each lone ``\\r``."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _is_alnum(ch: str | None) -> bool:
    return ch is not None and ch.isalnum()


# ---------------------------------------------------------------------------
# Pairing, shared by the reader and the writer
# ---------------------------------------------------------------------------

_USED = ("used", 0, "")


@dataclass(eq=False)
class _Delim:
    """A run of ``*`` or ``_``, and the styles that its characters open and close."""

    char: str
    length: int
    can_open: bool
    can_close: bool
    at: int  # where the run starts in the characters of the text, without escapes
    # The writer's literal text, which must pair with nothing, and the units it holds.
    literal: bool = False
    units: list[int] = field(default_factory=list)
    escaped: bool = False  # the writer escaped this literal run, so the reader sees text
    left: int = 0  # characters that closed a style, counted from the left
    right: int = 0  # characters that opened a style, counted from the right
    tags: list[tuple[str, int, str] | None] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.tags = [None] * self.length

    @property
    def rem(self) -> int:
        return self.length - self.left - self.right


def _flanking(char: str, before: str | None, after: str | None) -> tuple[bool, bool]:
    """Return whether a run of *char* between *before* and *after* can open and can close."""
    can_open = after is not None and not after.isspace()
    can_close = before is not None and not before.isspace()
    if char == "_":
        can_open = can_open and not _is_alnum(before)
        can_close = can_close and not _is_alnum(after)
    return can_open, can_close


_OTHER = {"*": "_", "_": "*"}


def _other_counts(chars: str) -> dict[str, list[int]]:
    """Return, for ``*`` and for ``_``, how many of the first k *chars* are not the other.

    A run of ``*`` and a later one don't pair if every character between them is an
    unescaped ``_``, and the same holds the other way round. So ``**__**__`` is text, and
    ``**\\_**`` is a bold ``_``. In *chars*, an escaped character is not ``*`` or ``_``.
    """
    counts: dict[str, list[int]] = {}
    for char, other in _OTHER.items():
        prefix = [0]
        for ch in chars:
            prefix.append(prefix[-1] + (ch != other))
        counts[char] = prefix
    return counts


def _three(opener: _Delim, closer: _Delim) -> bool:
    """Return whether the rule of 3 keeps *opener* and *closer* from pairing.

    If either run can both open and close, their lengths may not add up to a multiple of 3,
    unless both lengths are multiples of 3. So in ``*a**b**c*``, the ``**`` after ``a``
    can't end the ``*`` before it, because 1 and 2 add up to 3. The text is italic
    throughout, with a bold ``b``.
    """
    return _three_of((opener.length % 3, opener.can_close, 0, 0), closer.length, closer.can_open)


def _pair(
    delims: Iterable[_Delim],
    counts: dict[str, list[int]],
    escape: Callable[[_Delim], None] | None = None,
    unblock: Callable[[_Delim, _Delim], bool] | None = None,
) -> None:
    """Pair the runs in *delims*, in order, and tag each character that opens or closes.

    A closing run pairs with the nearest open run of its character that the rule of 3
    allows, and the open runs between them become text. *counts* comes from
    :func:`_other_counts`. Two runs don't pair if only the other character lies between
    them.

    The writer passes *escape* and *unblock*. It calls *escape* for each literal run that
    the reader could pair, and the pairing goes on as if that run were text. A literal run
    that could close is escaped, and so is a literal run that it would close. A literal run
    that a marker would close is escaped. When only the other character lies between two
    markers, *unblock* escapes the literal characters there, so that the markers pair. It
    returns False if there are none.

    Each closing run looks down its stack only as far as the last run with the same
    length modulo 3, and the same ability to open, found nothing. So the pairing takes time
    in proportion to the number of runs.
    """

    def allowed(opener: _Delim, closer: _Delim) -> bool:
        prefix = counts[closer.char]
        return prefix[closer.at] > prefix[opener.at + opener.length]

    stacks: dict[str, list[_Delim]] = {"*": [], "_": []}
    # For each character, length modulo 3 and ability to open: how far down a search goes.
    bottoms: dict[tuple[str, int, bool], int] = {}

    def cut(char: str, size: int) -> None:
        del stacks[char][size:]
        for key, bottom in bottoms.items():
            if key[0] == char and bottom > size:
                bottoms[key] = size

    def nearest(d: _Delim, start: int) -> int | None:
        """Return where the open run that *d* would close is in its stack, at *start* or
        below, if there is one."""
        stack = stacks[d.char]
        key = (d.char, d.length % 3, d.can_open)
        i = start
        while i >= bottoms.get(key, 0):
            if not stack[i].escaped and not _three(stack[i], d):
                return i
            i -= 1
        bottoms[key] = len(stack)
        return None

    pair = 0
    for d in delims:
        stack = stacks[d.char]
        if d.literal:
            if escape is not None and d.can_close and stack:
                escape(d)
                if stack[-1].literal:
                    escape(stack[-1])
                    cut(d.char, len(stack) - 1)
            elif d.can_open:
                stack.append(d)
            continue
        if d.can_close:
            start = len(stack) - 1
            while d.rem:
                i = nearest(d, start)
                if i is None:
                    break
                opener = stack[i]
                if escape is not None and opener.literal:
                    # The runs above it don't pair with d, so the search goes on below it.
                    escape(opener)
                    opener.escaped = True
                    start = i - 1
                    continue
                if not allowed(opener, d) and (unblock is None or not unblock(opener, d)):
                    break
                cut(d.char, i + 1)
                used = 2 if opener.rem >= 2 and d.rem >= 2 else 1
                attr = _DOUBLE[d.char] if used == 2 else "italic"
                pair += 1
                opener.right += used
                at = opener.length - opener.right
                opener.tags[at : at + used] = [("open", pair, attr)] + [_USED] * (used - 1)
                d.tags[d.left : d.left + used] = [("close", pair, attr)] + [_USED] * (used - 1)
                d.left += used
                if not opener.rem:
                    cut(d.char, i)
                start = len(stack) - 1
        if d.rem and d.can_open:
            stack.append(d)


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


def _tokens(text: str) -> tuple[list[str | _Delim], str]:
    """Split Markdown *text* into text characters and runs of ``*`` or ``_``.

    Also return the characters for :func:`_other_counts`.
    """
    tokens: list[str | _Delim] = []
    chars: list[str] = []
    at = 0
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in _ESCAPABLE:
            tokens.append(text[i + 1])
            chars.append(ch)
            at += 1
            i += 2
            continue
        if ch not in "*_":
            tokens.append(ch)
            chars.append(ch)
            at += 1
            i += 1
            continue
        j = i
        while j < n and text[j] == ch:
            j += 1
        can_open, can_close = _flanking(ch, text[i - 1] if i else None, text[j] if j < n else None)
        tokens.append(_Delim(ch, j - i, can_open, can_close, at))
        chars.append(text[i:j])
        at += j - i
        i = j
    return tokens, "".join(chars)


class _Open:
    """The pairs that are open at a point in the text, and the outermost one of each style."""

    def __init__(self) -> None:
        self._pairs: dict[str, list[int]] = {attr: [] for attr in _ATTRS}
        self._first = dict.fromkeys(_ATTRS, 0)
        self._closed: set[int] = set()
        self.order: dict[int, int] = {}

    def open(self, pair: int, attr: str) -> None:
        self.order[pair] = len(self.order)
        self._pairs[attr].append(pair)

    def close(self, pair: int) -> None:
        self._closed.add(pair)

    def outermost(self, attr: str) -> int | None:
        pairs, i = self._pairs[attr], self._first[attr]
        while i < len(pairs) and pairs[i] in self._closed:
            i += 1
        self._first[attr] = i
        return pairs[i] if i < len(pairs) else None


def _events(text: str) -> Iterator[tuple[str, int, str]]:
    """Yield ``("open", pair, attr)``, ``("close", pair, attr)`` and ``("text", 0, text)``.

    A run character that does not pair is yielded as text.
    """
    tokens, chars = _tokens(text)
    _pair((t for t in tokens if isinstance(t, _Delim)), _other_counts(chars))
    for t in tokens:
        if isinstance(t, str):
            yield "text", 0, t
            continue
        for tag in t.tags:
            if tag is None:
                yield "text", 0, t.char
            elif tag is not _USED:
                yield tag


def parse(text: str) -> list[Run]:
    """Return the styled runs of Markdown *text*, with adjacent equal styles merged."""
    runs: list[Run] = []
    state = _Open()
    for kind, pair, value in _events(text):
        if kind == "open":
            state.open(pair, value)
        elif kind == "close":
            state.close(pair)
        else:
            style = Style(*(state.outermost(attr) is not None for attr in _ATTRS))
            runs.append((style, value))
    return _merged(runs)


# The RTF for each ASCII character that is not written as itself.
_RTF_ASCII = {"\\": "\\\\", "{": "\\{", "}": "\\}", "\n": "\\par "}


def _unicode_escape(char: str) -> str:
    """Return the ``\\uN?`` escape that CLICK writes for *char*, which code page 1252 lacks.

    N is unsigned. A character above U+FFFF is written as its UTF-16 surrogate pair, one
    escape for each surrogate: U+1F600 is ``\\u55357?\\u56832?``.
    """
    code = ord(char)
    if code > 0xFFFF:
        code -= 0x10000
        return f"\\u{0xD800 + (code >> 10)}?\\u{0xDC00 + (code & 0x3FF)}?"
    return f"\\u{code}?"


def _rtf_char(char: str) -> str:
    """Return the RTF that CLICK writes for the character *char* of a comment.

    An ASCII character is written as itself, except that ``\\``, ``{`` and ``}`` are
    escaped and ``\\n`` is ``\\par``. A character that code page 1252 holds is ``\\'hh``,
    with lowercase hex: ``é`` is ``\\'e9``. Any other character is a ``\\uN?`` escape.
    """
    if char.isascii():
        return _RTF_ASCII.get(char, char)
    byte = cp1252_byte(char)
    if byte is not None:
        return f"\\'{byte:02x}"
    return _unicode_escape(char)


def rtf_body(text: str) -> str:
    """Return the Markdown comment *text* as the body of an RTF string.

    The function first turns ``\\r\\n`` and a lone ``\\r`` into ``\\n``. Each styled
    stretch of text becomes an RTF group: ``{\\b text}`` for bold, ``{\\i text}`` for italic
    and ``{\\ul text}`` for underline. A style inside the same style adds no group. Each
    character of the text is written as :func:`_rtf_char` says, so the body is ASCII.
    """
    out: list[str] = []
    state = _Open()
    groups: list[tuple[int, str]] = []
    for kind, pair, value in _events(_read_form(text)):
        if kind == "open":
            state.open(pair, value)
            continue
        if kind == "close":
            state.close(pair)
            continue
        # Each style is the group of its outermost open pair. Close every group from the
        # outermost one that has ended, then open the others in the order they opened.
        outer = [(state.outermost(attr), attr) for attr in _ATTRS]
        wanted = sorted(
            ((p, a) for p, a in outer if p is not None), key=lambda g: state.order[g[0]]
        )
        ended = [i for i, group in enumerate(groups) if group not in wanted]
        if ended:
            out.append("}" * (len(groups) - ended[0]))
            del groups[ended[0] :]
        for group in wanted:
            if group not in groups:
                out.append(f"{{\\{_RTF_CONTROL[group[1]]} ")
                groups.append(group)
        out.append("".join(map(_rtf_char, value)))
    out.append("}" * len(groups))
    return "".join(out)


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def _merged(runs: Iterable[Run]) -> list[Run]:
    """Return *runs* without empty text, with each pair of adjacent equal styles joined."""
    pieces: list[tuple[Style, list[str]]] = []
    for style, text in runs:
        if not text:
            continue
        if pieces and pieces[-1][0] == style:
            pieces[-1][1].append(text)
        else:
            pieces.append((style, [text]))
    return [(style, "".join(texts)) for style, texts in pieces]


@dataclass
class _Piece:
    """A character of comment text, or ``\\r\\n``, the character that the reader sees in it,
    and its style."""

    text: str
    unit: str
    style: Style


def _pieces(runs: Iterable[Run]) -> list[_Piece]:
    """Split the text of *runs* into pieces that the reader sees as one character each.

    A piece is one character, or ``\\r\\n``. The reader sees ``\\n`` for ``\\r\\n`` and
    for a lone ``\\r``.
    """
    chars = [(style, ch) for style, text in runs for ch in text]
    pieces: list[_Piece] = []
    i = 0
    while i < len(chars):
        style, ch = chars[i]
        if ch == "\r" and i + 1 < len(chars) and chars[i + 1][1] == "\n":
            pieces.append(_Piece("\r\n", "\n", style))
            i += 2
        else:
            pieces.append(_Piece(ch, _read_form(ch), style))
            i += 1
    return pieces


def _stars(style: Style | None) -> set[str]:
    if style is None:
        return set()
    return {attr for attr in ("bold", "italic") if getattr(style, attr)}


def _drop_style_on_edge_whitespace(units: list[str], styles: list[Style]) -> None:
    """Remove each style from whitespace where its marker would open or close beside it.

    A marker can't open before whitespace or close after it. So a stretch of whitespace
    keeps a style only if the text on each side of it has the style, and so does every
    character in the stretch. Whitespace at the start or the end of the comment keeps none.
    """
    n = len(units)
    i = 0
    while i < n:
        if not units[i].isspace():
            i += 1
            continue
        j = i
        while j < n and units[j].isspace():
            j += 1
        inside = 0 < i and j < n
        keep = {
            attr: inside
            and getattr(styles[i - 1], attr)
            and getattr(styles[j], attr)
            and all(getattr(styles[k], attr) for k in range(i, j))
            for attr in _ATTRS
        }
        for k in range(i, j):
            styles[k] = Style(**keep)
        i = j


def _drop_crossing_on_whitespace(units: list[str], styles: list[Style]) -> None:
    """Remove bold or italic from whitespace where the two would cross at whitespace.

    Bold and italic nest. Where one opens inside the other, and the outer one ends first,
    the outer one closes and opens again around the new one. It can't close after
    whitespace, so the whitespace before the new style loses the outer style instead.
    """
    n = len(units)
    end: dict[str, list[int]] = {}
    for attr in ("bold", "italic"):
        ends = [0] * n
        for k in range(n - 1, -1, -1):
            if getattr(styles[k], attr):
                on_next = k + 1 < n and getattr(styles[k + 1], attr)
                ends[k] = ends[k + 1] if on_next else k
        end[attr] = ends
    for k in range(1, n):
        if not units[k - 1].isspace():
            continue
        for new, outer in (("bold", "italic"), ("italic", "bold")):
            opens = getattr(styles[k], new) and not getattr(styles[k - 1], new)
            crosses = (
                getattr(styles[k - 1], outer)
                and getattr(styles[k], outer)
                and end[outer][k] < end[new][k]
            )
            if opens and crosses:
                s = k - 1
                while s >= 0 and units[s].isspace():
                    styles[s] = replace(styles[s], **{outer: False})
                    s -= 1


def _drop_underline_beside_word(units: list[str], styles: list[Style]) -> None:
    """Remove underline where its ``__`` would touch a letter or a digit outside it.

    An ``__`` with a letter or a digit outside it, as in ``x__y__z``, is text to the reader.
    A ``*`` marker between them keeps them apart, so that case keeps its underline.
    """
    n = len(units)
    k = 0
    while k < n:
        if not styles[k].underline:
            k += 1
            continue
        a = k
        while k < n and styles[k].underline:
            k += 1
        before = a > 0 and _is_alnum(units[a - 1]) and _stars(styles[a - 1]) == _stars(styles[a])
        after = k < n and _is_alnum(units[k]) and _stars(styles[k - 1]) == _stars(styles[k])
        if before or after:
            for m in range(a, k):
                styles[m] = replace(styles[m], underline=False)


@dataclass(frozen=True)
class _Boundary:
    """The place before a unit, or after the last one, and the bold and italic on each side."""

    old: frozenset[str]
    new: frozenset[str]
    u_close: bool
    u_open: bool
    can_open: bool  # whether a run of ``*`` here can open a style
    can_close: bool  # whether it can close one


def _boundaries(units: list[str], styles: list[Style]) -> list[_Boundary]:
    n = len(units)
    out = []
    for k in range(n + 1):
        prev = styles[k - 1] if k else None
        nxt = styles[k] if k < n else None
        u_close = prev is not None and prev.underline and not (nxt is not None and nxt.underline)
        u_open = nxt is not None and nxt.underline and not (prev is not None and prev.underline)
        before = "_" if u_close else (units[k - 1] if k else None)
        after = "_" if u_open else (units[k] if k < n else None)
        can_open, can_close = _flanking("*", before, after)
        out.append(
            _Boundary(
                frozenset(_stars(prev)),
                frozenset(_stars(nxt)),
                u_close,
                u_open,
                can_open,
                can_close,
            )
        )
    return out


def _nested_stars(bounds: list[_Boundary]) -> list[tuple[int, int, int]]:
    """Return, for each boundary, the ``*`` count and the bold and italic pairs it opens.

    Bold and italic nest. Where one of them opens while the other stays open, and the run
    can close, the run closes the open one and then opens both. So does a run that closes a
    style under one that stays open.
    """
    out = []
    entries: list[list[str]] = []  # the bold and italic that each open run holds, in order
    for b in bounds:
        to_close, to_open, stay = b.old - b.new, b.new - b.old, b.old & b.new
        crossing = False
        stays_above = False
        for entry in reversed(entries):
            if stays_above and any(attr in to_close for attr in entry):
                crossing = True
            if any(attr in stay for attr in entry):
                stays_above = True
        count = 0
        if (to_open and stay and b.can_close) or crossing:
            count = sum(len(_MARKER[attr]) for entry in entries for attr in entry)
            entries.clear()
            to_open = b.new
        else:
            for entry in entries:
                count += sum(len(_MARKER[attr]) for attr in entry if attr in to_close)
                entry[:] = [attr for attr in entry if attr not in to_close]
            entries[:] = [entry for entry in entries if entry]
        bold, italic = int("bold" in to_open), int("italic" in to_open)
        if to_open:
            entries.append([attr for attr in ("italic", "bold") if attr in to_open])
        out.append((count + 2 * bold + italic, bold, italic))
    return out


# An open run of ``*`` as the reader holds it: its length modulo 3, whether it can close as
# well as open, and how many bold and italic pairs its characters are meant to open.
_StarRun = tuple[int, bool, int, int]


def _star_step(
    runs: tuple[_StarRun, ...], length: int, b: _Boundary
) -> tuple[tuple[_StarRun, ...], int] | None:
    """Return the open runs after a run of *length* ``*`` at *b*, and the characters it
    leaves open, as :func:`_pair` reads it.

    Return None if it closes a pair as another style than the one meant, or if it leaves
    an open character as text.
    """
    stack = list(runs)
    left = length
    if b.can_close:
        while left and stack:
            i = len(stack) - 1
            while i >= 0 and _three_of(stack[i], length, b.can_open):
                i -= 1
            if i < 0:
                break
            if i != len(stack) - 1:
                return None  # the open runs above it would become text
            mod, both, bold, italic = stack[-1]
            if 2 * bold + italic >= 2 and left >= 2:
                if not bold:
                    return None
                bold, left = bold - 1, left - 2
            else:
                if not italic:
                    return None
                italic, left = italic - 1, left - 1
            if bold or italic:
                stack[-1] = (mod, both, bold, italic)
            else:
                stack.pop()
    if left and not b.can_open:
        return None
    return tuple(stack), left


def _three_of(run: _StarRun, length: int, can_open: bool) -> bool:
    """Return whether the rule of 3 keeps the open *run* from pairing with a run of *length*
    that can close, and that can open too if *can_open* is true."""
    mod, both = run[0], run[1]
    if not (both or can_open):
        return False
    return (mod + length) % 3 == 0 and bool(mod or length % 3)


def _pushed(
    step: tuple[tuple[_StarRun, ...], int], length: int, bold: int, italic: int, b: _Boundary
) -> tuple[_StarRun, ...] | None:
    """Return the open runs after a run of *length* at *b*, whose open characters are
    meant as *bold* and *italic* pairs. Return None if the text after it would not have the
    bold and italic meant."""
    stack, left = step
    if left != 2 * bold + italic:
        return None
    if left:
        stack = (*stack, (length % 3, b.can_close, bold, italic))
    held = {"bold" for run in stack if run[2]} | {"italic" for run in stack if run[3]}
    return stack if held == b.new else None


_MAX_STARS = 8  # the longest run of ``*`` that the search tries at a boundary
_MAX_OPEN = 3  # the most open runs that the search lets the reader hold

_Move = tuple[tuple[int, int, int], tuple[_StarRun, ...]]


@functools.lru_cache(maxsize=4096)
def _moves(state: tuple[_StarRun, ...], b: _Boundary) -> tuple[_Move, ...]:
    """Return each ``*`` count and the pairs it opens at *b*, with the open runs after it.

    The moves depend only on the open runs and on *b*, of which there are few kinds, so the
    results are kept.
    """
    moves = []
    for length in range(_MAX_STARS + 1):
        step = _star_step(state, length, b)
        if step is None:
            continue
        for bold in range(step[1] // 2, -1, -1):
            nxt = _pushed(step, length, bold, step[1] - 2 * bold, b)
            if nxt is not None and len(nxt) <= _MAX_OPEN:
                moves.append(((length, bold, step[1] - 2 * bold), nxt))
    return tuple(moves)


def _searched_stars(bounds: list[_Boundary]) -> list[tuple[int, int, int]] | None:
    """Return a ``*`` count and the pairs it opens for each boundary, such that the reader
    gives each unit its bold and italic, or None if there is none.

    The search goes boundary by boundary over the open runs that the reader can hold. There
    are few of them, and few kinds of boundary, so each step is kept and the search takes
    time in proportion to the number of boundaries.
    """
    changes = [k for k, b in enumerate(bounds) if b.old != b.new]
    layers: list[dict[tuple[_StarRun, ...], tuple[_Move, ...]]] = []
    forward: dict[tuple[frozenset, _Boundary], tuple[dict, frozenset]] = {}
    states: frozenset[tuple[_StarRun, ...]] = frozenset({()})
    for k in changes:
        b = replace(bounds[k], u_close=False, u_open=False)
        if (states, b) not in forward:
            layer = {state: _moves(state, b) for state in states}
            forward[states, b] = layer, frozenset(n for moves in layer.values() for _, n in moves)
        layer, states = forward[states, b]
        layers.append(layer)
    # ok[i] holds the open runs after change i from which the rest can be written.
    ok: list[frozenset[tuple[_StarRun, ...]]] = [frozenset() for _ in layers]
    if layers:
        ok[-1] = frozenset({()})
    backward: dict[tuple[int, frozenset], frozenset] = {}
    for i in range(len(layers) - 1, 0, -1):
        key = (id(layers[i]), ok[i])
        if key not in backward:
            backward[key] = frozenset(
                s for s, moves in layers[i].items() if any(n in ok[i] for _, n in moves)
            )
        ok[i - 1] = backward[key]
    out = [(0, 0, 0)] * len(bounds)
    state: tuple[_StarRun, ...] = ()
    for k, layer, after in zip(changes, layers, ok, strict=True):
        move = next(((m, n) for m, n in layer[state] if n in after), None)
        if move is None:
            return None
        out[k], state = move
    return out


def _reads_back(bounds: list[_Boundary], stars: list[tuple[int, int, int]]) -> bool:
    """Return whether the reader gives each unit its bold and italic for these *stars*."""
    runs: tuple[_StarRun, ...] | None = ()
    for b, (length, bold, italic) in zip(bounds, stars, strict=True):
        if b.old != b.new or length:
            step = _star_step(runs, length, b)
            runs = None if step is None else _pushed(step, length, bold, italic, b)
            if runs is None:
                return False
    return runs == ()


def _boundary_markers(units: list[str], styles: list[Style]) -> list[str]:
    """Return the markers that go before each unit, and the ones after the last unit.

    At each boundary the writer closes underline, then writes a run of ``*`` for bold and
    italic, then opens underline. The run nests bold and italic where the reader reads that
    back. Otherwise the writer searches for the ``*`` counts that the reader reads back,
    which can open a style twice, as in ``*a****b*******c****``.
    """
    bounds = _boundaries(units, styles)
    stars = _nested_stars(bounds)
    if not _reads_back(bounds, stars):
        searched = _searched_stars(bounds)
        if searched is None:
            msg = f"no run of * writes the bold and italic of the comment {''.join(units)!r}"
            raise DecodeError(msg)
        stars = searched
    return [
        ("__" if b.u_close else "") + "*" * length + ("__" if b.u_open else "")
        for b, (length, _, _) in zip(bounds, stars, strict=True)
    ]


def _escapes(units: list[str], markers: list[str]) -> list[bool]:
    """Return, for each unit, whether a backslash goes before it.

    A literal ``*`` or ``_`` gets one where it touches a marker of the same character, and
    where the reader would pair it. A literal ``\\`` gets one before ``\\``, ``*`` or ``_``.
    """
    # Each item is a character of the Markdown, with its unit, or -1 for a marker.
    items: list[tuple[str, int]] = []
    for k in range(len(units) + 1):
        items.extend((ch, -1) for ch in markers[k])
        if k < len(units):
            items.append((units[k], k))
    escaped = [False] * len(units)

    delims: list[_Delim] = []
    i = 0
    while i < len(items):
        ch, unit = items[i]
        if ch not in "*_":
            i += 1
            continue
        j = i
        while j < len(items) and items[j][0] == ch and (items[j][1] < 0) == (unit < 0):
            j += 1
        before = items[i - 1][0] if i else None
        after = items[j][0] if j < len(items) else None
        touches = (i and items[i - 1] == (ch, -1)) or (j < len(items) and items[j] == (ch, -1))
        if unit >= 0 and touches:
            for _, k in items[i:j]:
                escaped[k] = True
        else:
            can_open, can_close = _flanking(ch, before, after)
            delim = _Delim(ch, j - i, can_open, can_close, i, literal=unit >= 0)
            delim.units = [k for _, k in items[i:j]]
            delims.append(delim)
        i = j

    def escape(delim: _Delim) -> None:
        for k in delim.units:
            escaped[k] = True

    def unblock(opener: _Delim, closer: _Delim) -> bool:
        # Only the other character lies between, so no marker of this character does,
        # and the stretches that this scans don't overlap.
        between = [k for _, k in items[opener.at + opener.length : closer.at] if k >= 0]
        for k in between:
            escaped[k] = True
        return bool(between)

    _pair(delims, _other_counts("".join(ch for ch, _ in items)), escape, unblock)
    for i, (ch, unit) in enumerate(items):
        if ch == "\\" and unit >= 0 and i + 1 < len(items) and items[i + 1][0] in _ESCAPABLE:
            escaped[unit] = True
    return escaped


def _writable(pieces: list[_Piece]) -> tuple[list[str], list[Style]]:
    """Return the unit of each of *pieces*, and the style of each that Markdown can write."""
    units = [piece.unit for piece in pieces]
    styles = [piece.style for piece in pieces]
    _drop_style_on_edge_whitespace(units, styles)
    _drop_crossing_on_whitespace(units, styles)
    _drop_underline_beside_word(units, styles)
    return units, styles


def write_runs(runs: Iterable[Run]) -> str:
    """Return the Markdown for the styled *runs* of a comment.

    The function writes ``**`` for bold, ``*`` for italic and ``__`` for underline. A
    literal ``*``, ``_`` or ``\\`` gets a backslash before it where the reader would
    otherwise read it as a marker or an escape. The function finds those places in one
    pass, with the same pairing as the reader.

    So a comment that is read back has the same text and the same styles, with two
    exceptions. The function writes the text of each without the style:

    - a style on whitespace where its marker would have whitespace on the side that it
      opens or closes, as in a bold ``"a "``;
    - an underline whose ``__`` would touch a letter or a digit outside it.
    """
    pieces = _pieces(_merged(runs))
    if not pieces:
        return ""
    units, styles = _writable(pieces)
    markers = _boundary_markers(units, styles)
    escaped = _escapes(units, markers)

    out: list[str] = []
    for k, piece in enumerate(pieces):
        out.append(markers[k])
        out.append("\\" + piece.text if escaped[k] else piece.text)
    out.append(markers[len(units)])
    return "".join(out)


def write_text(text: str) -> str:
    """Return plain *text* as comment Markdown, so that the reader reads it back unstyled."""
    return write_runs([(PLAIN, text)])
