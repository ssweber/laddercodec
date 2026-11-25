"""Tests of the Markdown in a rung comment: the reader, the writer and their round trip.

``rtf_body`` reads the Markdown that ``encode()`` writes as RTF. ``_decode_rtf`` reads the
RTF and writes it as Markdown with ``write_runs``. Any text and styles that the writer
writes read back the same, with two exceptions, which read back without the style:

- a style on whitespace at the edge of a styled stretch, and
- an underline whose ``__`` would touch a letter or a digit outside it.
"""

from __future__ import annotations

import itertools
import random
import time
from pathlib import Path

import pytest

import laddercodec._comment
from laddercodec import (
    Rung,
    UndecodedCommentWarning,
    decode,
    decode_program,
    encode,
    read_csv,
    write_csv,
)
from laddercodec._comment import (
    PLAIN,
    Style,
    _merged,
    _pieces,
    _read_form,
    _writable,
    parse,
    rtf_body,
    write_runs,
    write_text,
)
from laddercodec.decode import _decode_rtf
from laddercodec.encode import _PREFIX, _SUFFIX, encode_rung
from tests.ladder.test_decode_program import _synthetic_scr
from tests.test_undecoded import DECODED

_STYLES = tuple(Style(b, i, u) for b in (False, True) for i in (False, True) for u in (False, True))


def _rtf(body: str | bytes) -> bytes:
    if isinstance(body, str):
        body = body.encode("cp1252")
    return _PREFIX + body + _SUFFIX


def _rtf_of_runs(runs: list[tuple[Style, str]]) -> bytes:
    """Return an RTF payload that holds *runs*, each in a group of its own."""
    parts = []
    for style, text in runs:
        text = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
        text = text.replace("\n", "\\par ")
        text = "".join(ch if ch.encode("cp1252", "ignore") else f"\\u{ord(ch)}?" for ch in text)
        controls = "".join(
            code
            for on, code in ((style.bold, "\\b"), (style.italic, "\\i"), (style.underline, "\\ul"))
            if on
        )
        parts.append(f"{{{controls} {text}}}" if controls else text)
    return _rtf("".join(parts))


def _chars(runs: list[tuple[Style, str]]) -> list[tuple[str, Style]]:
    return [(ch, style) for style, text in runs for ch in text]


# -- The reader --


@pytest.mark.parametrize(
    ("markdown", "body"),
    [
        ("Pump_1_Run", "Pump_1_Run"),
        ("X_1 and Y_2", "X_1 and Y_2"),
        ("count_up__reset", "count_up__reset"),
        ("set _init to 1", "set _init to 1"),
        ("_x_", r"{\i x}"),
        (r"\_x\_", "_x_"),
        (r"\*x\*", "*x*"),
        (r"a\\b", r"a\\b"),
        (r"C:\temp", r"C:\\temp"),
        (r"end\\", r"end\\"),
        ("DS401 * ( -5 )", "DS401 * ( -5 )"),
        ("2 * 3 * 4", "2 * 3 * 4"),
        ("DS401 * ( -5 ) * 2", "DS401 * ( -5 ) * 2"),
        ("a *b* c", r"a {\i b} c"),
        ("2*3*4", r"2{\i 3}4"),
        ("** x**", "** x**"),
        ("*a *b*", r"*a {\i b}"),
        ("*1 see *Auto* mode", r"*1 see {\i Auto} mode"),
        ("*****WARNING*****", r"{\i {\b WARNING}}"),
        ("*a**b**c*", r"{\i a{\b b}c}"),
        ("**a*b*c**", r"{\b a{\i b}c}"),
        ("*foo**bar*", r"{\i foo**bar}"),
        ("**a **b** c**", r"{\b a b c}"),
        ("****a****", r"{\b a}"),
        ("a******a", "a******a"),
        ("use _ or _", "use _ or _"),
        ("**__**__", "**__**__"),
        (r"**\_**", r"{\b _}"),
        (r"__\*__", r"{\ul *}"),
        ("\uff0ax\uff0a", r"\u65290?x\u65290?"),
        ("caf\u00e9_1_", r"caf\'e9_1_"),
        (
            "**Bold** and *italic* and __underline__",
            r"{\b Bold} and {\i italic} and {\ul underline}",
        ),
        ("**a *b* c**", r"{\b a {\i b} c}"),
        ("***x***", r"{\i {\b x}}"),
        ("*a***b**", r"{\i a}{\b b}"),
        ("__x **y__**", r"{\ul x {\b y}}"),
        ("**a\nb**", r"{\b a\par b}"),
        ("{x}", r"\{x\}"),
    ],
)
def test_reader_writes_the_rtf_body(markdown: str, body: str) -> None:
    assert rtf_body(markdown) == body


def test_reader_keeps_a_comment_without_styling_unchanged() -> None:
    text = "Pump_1_Run starts when X_1 is on and DS1 * 2 > 5"
    assert rtf_body(text) == text


# -- The writer --


@pytest.mark.parametrize(
    ("body", "markdown"),
    [
        ("Pump_1_Run", "Pump_1_Run"),
        ("X_1 and Y_2", "X_1 and Y_2"),
        ("_x_", r"\_x\_"),
        ("*x*", r"\*x\*"),
        ("set _init to 1", "set _init to 1"),
        ("DS401 * ( -5 )", "DS401 * ( -5 )"),
        ("one * two * three", "one * two * three"),
        ("2 * 3 * 4", "2 * 3 * 4"),
        ("DS401 * ( -5 ) * 2", "DS401 * ( -5 ) * 2"),
        ("2*3*4", r"2\*3\*4"),
        (r"a {\i b} c", "a *b* c"),
        (r"{\b a }b", "**a** b"),
        (r"{\b a}{\i  b}", "**a** *b*"),
        (r"{\i  x}", " *x*"),
        (r"C:\\temp", r"C:\temp"),
        (r"Pump_1_Run waits for _init_ in C:\\temp", r"Pump_1_Run waits for \_init\_ in C:\temp"),
        (r"a\\\\b", r"a\\\b"),
        (r"a\\*b", r"a\\*b"),
        (r"x\\{\b y}", r"x\\**y**"),
        (r"{\b a}*", r"**a**\*"),
        (r"{\ul a}_", r"__a__\_"),
        (r"x{\ul y}z", "xyz"),
        (r"x {\ul y} z", "x __y__ z"),
        (r"x{\b\ul y}z", "x**__y__**z"),
        (r"{\b a {\i b}} {\i c}", "**a *b*** *c*"),
        (r"a\\\u769?{\i b}", "a\\\u0301*b*"),
        (r"{\i \u769?}", "*\u0301*"),
    ],
)
def test_writer_escapes_only_what_would_read_as_styling(body: str, markdown: str) -> None:
    assert _decode_rtf(_rtf(body)) == markdown


_I, _B, _BI = Style(italic=True), Style(bold=True), Style(bold=True, italic=True)


@pytest.mark.parametrize(
    ("runs", "markdown"),
    [
        ([(_I, "a"), (_BI, "b"), (_I, "c")], "*a**b**c*"),
        ([(_B, "a"), (_BI, "b"), (_B, "c")], "**a*b*c**"),
        ([(_I, "a"), (_B, "b")], "*a***b**"),
        # The rule of 3 keeps the nested runs from pairing, so a style opens twice.
        ([(_I, "a"), (_BI, "b"), (_B, "c")], "*a****b*******c****"),
        ([(_B, "a"), (_BI, "b"), (_I, "c")], "**a******b***c*"),
    ],
)
def test_writer_picks_star_runs_that_read_back(
    runs: list[tuple[Style, str]], markdown: str
) -> None:
    assert _decode_rtf(_rtf_of_runs(runs)) == markdown
    _check_round_trip(runs)


def test_a_comment_with_no_star_runs_that_read_back_is_undecoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The nested runs of *a****b*******c**** don't read back, so the writer searches.
    monkeypatch.setattr(laddercodec._comment, "_searched_stars", lambda bounds: None)
    first = DECODED[0]
    rung = Rung(
        conditions=first.conditions, instructions=first.instructions, comment="*a****b*******c****"
    )
    with pytest.warns(UndecodedCommentWarning, match="'abc'"):
        [back] = decode(encode(rung))
    assert isinstance(back, Rung)
    assert (back.conditions, back.instructions) == (rung.conditions, rung.instructions)
    assert back.comment is not None and back.comment.endswith("\nabc")


def test_writer_of_plain_text() -> None:
    """The writer escapes a ``*`` or ``_`` only if the reader would pair it."""
    assert write_text("_init and *x*") == r"_init and \*x\*"
    assert write_text("a * b and _x_") == r"a * b and \_x\_"
    assert write_text("_a _b_") == r"_a \_b\_"
    assert write_text("\uff0ax\uff0a") == "\uff0ax\uff0a"
    assert write_text("caf\u00e9_1_") == "caf\u00e9_1_"
    assert write_text("Pump_1_Run") == "Pump_1_Run"


_FULL_STAR, _FULL_LOW_LINE, _FULL_BACKSLASH, _ACUTE = "\uff0a", "\uff3f", "\uff3c", "\u0301"
_U = Style(underline=True)


@pytest.mark.parametrize(
    ("runs", "markdown"),
    [
        ([(PLAIN, f"{_FULL_STAR}x{_FULL_STAR}")], f"{_FULL_STAR}x{_FULL_STAR}"),
        ([(PLAIN, f"{_FULL_LOW_LINE}x{_FULL_LOW_LINE}")], f"{_FULL_LOW_LINE}x{_FULL_LOW_LINE}"),
        ([(PLAIN, f"a{_FULL_BACKSLASH}"), (Style(italic=True), "b")], f"a{_FULL_BACKSLASH}*b*"),
        ([(PLAIN, f"a\\{_ACUTE}"), (Style(italic=True), "b")], f"a\\{_ACUTE}*b*"),
        ([(Style(italic=True), _ACUTE)], f"*{_ACUTE}*"),
        ([(PLAIN, "x "), (_U, _ACUTE), (PLAIN, " y")], f"x __{_ACUTE}__ y"),
        ([(PLAIN, "a"), (Style(bold=True), f"b{_ACUTE}"), (PLAIN, "c")], f"a**b{_ACUTE}**c"),
    ],
)
def test_writer_writes_a_lookalike_or_a_combining_mark_as_text(
    runs: list[tuple[Style, str]], markdown: str
) -> None:
    """``\uff0a``, ``\uff3f`` and ``\uff3c`` are text, not ``*``, ``_`` or ``\\``. A
    combining mark is a character of its own."""
    assert _decode_rtf(_rtf_of_runs(runs)) == markdown
    _check_round_trip(runs)


def test_an_underscore_beside_a_letter_outside_ascii_is_text() -> None:
    """``é`` is a letter, so a ``__`` beside it is text, as it is beside ``e``."""
    assert rtf_body("caf\u00e9__y__") == r"caf\'e9__y__"
    markdown = write_runs([(PLAIN, "x caf\u00e9"), (_U, "y"), (PLAIN, " _z_")])
    assert markdown == "x caf\u00e9y \\_z\\_"


# -- The round trip --


def _check_round_trip(runs: list[tuple[Style, str]]) -> None:
    """Check that the Markdown for *runs* reads back as the same text and styles.

    It also checks that the Markdown is written again unchanged after an encode and a
    decode. Text is compared as the reader sees it, with ``\\n`` for each line break. Each
    character reads back with the style that the writer means to write. That style never
    adds a style. It keeps bold and italic on any character that is not
    whitespace, and it keeps underline unless a ``__`` would touch a letter or a digit.
    """
    markdown = _decode_rtf(_rtf_of_runs(runs))
    assert markdown == write_runs(runs)
    again = _decode_rtf(_rtf(rtf_body(markdown)))
    assert rtf_body(again) == rtf_body(markdown), (runs, markdown)
    assert _decode_rtf(_rtf(rtf_body(again))) == again, (runs, markdown)
    assert again == markdown, (runs, markdown)

    want = _seen(runs)
    got = _chars(parse(_read_form(markdown)))
    assert [ch for ch, _ in got] == [ch for ch, _ in want], (runs, markdown)
    _, meant = _writable(_pieces(_merged(runs)))
    assert [style for _, style in got] == meant, (runs, markdown)
    for (ch, g), (_, w) in zip(got, want, strict=True):
        for attr in ("bold", "italic", "underline"):
            assert getattr(w, attr) or not getattr(g, attr), (runs, markdown)
        if not ch.isspace():
            assert (g.bold, g.italic) == (w.bold, w.italic), (runs, markdown)
    underline = [w.underline for _, w in want]
    touches_word = any(
        underline[k] != underline[k + 1]
        and (want[k][0].isalnum() if underline[k + 1] else want[k + 1][0].isalnum())
        for k in range(len(want) - 1)
    )
    if not touches_word:
        for (ch, g), (_, w) in zip(got, want, strict=True):
            assert ch.isspace() or g.underline == w.underline, (runs, markdown)


def _seen(runs: list[tuple[Style, str]]) -> list[tuple[str, Style]]:
    """Return each character of *runs* as the reader sees it, with its style."""
    return [(unit, style) for style, text in runs for ch in text for unit in _read_form(ch)]


# Characters that look like ``*``, ``_`` or ``\``, and a combining mark. Each is text.
_LOOKALIKES = ("\uff0a", "\ufe61", "\uff3f", "\ufe4d", "\uff3c", "\ufe68", "\u0301")
# Characters that encode() writes as ``\'hh`` and as ``\uN?``.
_OUTSIDE_ASCII = ("\u00e9", "\u20ac", "\u0081", "\u4e2d", "\u2192")
_ALPHABET = (
    *("a", "Z", "1", " ", "*", "_", "\\", "{", "}", "-", "\n", "\t"),
    *_LOOKALIKES,
    *_OUTSIDE_ASCII,
)


def _generated_runs(seed: int, count: int) -> list[list[tuple[Style, str]]]:
    rng = random.Random(seed)
    cases = []
    for _ in range(count):
        runs = []
        for _ in range(rng.randint(1, 6)):
            text = "".join(rng.choice(_ALPHABET) for _ in range(rng.randint(1, 4)))
            runs.append((rng.choice(_STYLES), text))
        cases.append(runs)
    return cases


@pytest.mark.parametrize("seed", range(20))
def test_generated_comments_read_back_the_same(seed: int) -> None:
    for runs in _generated_runs(seed, 250):
        _check_round_trip(runs)


def test_every_short_text_in_each_style_reads_back_the_same() -> None:
    chars = ("a", " ", "*", "_", "\\")
    for length in range(1, 5):
        for text in map("".join, itertools.product(chars, repeat=length)):
            for style in _STYLES:
                _check_round_trip([(style, text)])
                _check_round_trip([(PLAIN, "x"), (style, text), (PLAIN, "y")])


_LONG = 5600
# Each case takes about a tenth of a second. A writer or reader that took time in proportion
# to the square of the length took several seconds.
_BOUND = 1.0


@pytest.mark.parametrize(
    ("convert", "text"),
    [
        (rtf_body, "*_" * (_LONG // 2)),
        (rtf_body, "**a*" * (_LONG // 4)),
        (rtf_body, "a" + "*" * _LONG + "a"),
        (rtf_body, "*a " * (_LONG // 6) + "a* " * (_LONG // 6)),
        (write_text, "*_" * (_LONG // 2)),
        (write_text, "a" + "*" * _LONG + "a"),
        (write_text, "*a " * (_LONG // 6) + "a* " * (_LONG // 6)),
        (write_text, "_a " * (_LONG // 6) + "a_ " * (_LONG // 6)),
        (write_text, "*a _b " * (_LONG // 12) + "b_ a* " * (_LONG // 12)),
    ],
    ids=lambda value: getattr(value, "__name__", None) or repr(value[:8]),
)
def test_a_long_comment_takes_time_in_proportion_to_its_length(convert, text: str) -> None:
    start = time.perf_counter()
    convert(text)
    assert time.perf_counter() - start < _BOUND


@pytest.mark.parametrize(
    "runs",
    [
        [(Style(bold=bool(i % 2), underline=i % 3 == 0), "a_*") for i in range(_LONG // 3)],
        # The nested runs don't read back here, so the writer searches.
        [(s, t) for _ in range(_LONG // 3) for s, t in ((_I, "a"), (_BI, "b"), (_B, "c"))],
    ],
    ids=["alternating", "searched"],
)
def test_a_long_comment_of_styled_runs_takes_time_in_proportion_to_its_length(
    runs: list[tuple[Style, str]],
) -> None:
    start = time.perf_counter()
    markdown = write_runs(runs)
    assert time.perf_counter() - start < _BOUND
    assert _chars(parse(_read_form(markdown))) == _chars(runs)


# -- The paths that read and write a comment --


def test_csv_keeps_an_escaped_comment(tmp_path: Path) -> None:
    [rung] = decode(encode_rung(1, [[""] * 31], [""], comment=r"\_x\_ and Pump_1_Run"))
    assert rung.comment_rtf == _rtf("_x_ and Pump_1_Run")
    assert rung.comment == r"\_x\_ and Pump_1_Run"

    path = tmp_path / "rung.csv"
    write_csv(path, [rung])
    assert r"#,\_x\_ and Pump_1_Run" in path.read_text(encoding="utf-8")
    [again] = read_csv(path)
    assert again.comment == rung.comment
    assert encode(again) == encode(rung)


def test_decode_program_escapes_a_comment() -> None:
    program = decode_program(_synthetic_scr(["_x_ and Pump_1_Run"]))
    assert [r.comment for r in program.rungs] == [r"\_x\_ and Pump_1_Run"]
