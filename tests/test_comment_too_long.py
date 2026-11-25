"""``check()`` reports a rung comment that ``encode()`` refuses as too long.

The limit is 1400 bytes of the comment's RTF body. An ASCII letter counts as 1 byte, ``é`` as
4 (``\\'e9``), ``中`` as 8 (``\\u20013?``) and an emoji as 16 (two ``\\uN?`` escapes). Each
case checks that ``check()`` and ``encode()`` agree at the limit and one byte either side.
"""

from __future__ import annotations

import pytest

from laddercodec import Code, Coil, Contact, EncodeError, Rung, check, encode, marker_rung
from laddercodec.encode import COMMENT_MAX_BYTES
from laddercodec.instructions import Undecoded

E_ACUTE = "\N{LATIN SMALL LETTER E WITH ACUTE}"
ZHONG = "\N{CJK UNIFIED IDEOGRAPH-4E2D}"
EMOJI = "\U0001f600"

#: Each character and the bytes that it counts toward the limit.
UNITS = [("a", 1), (E_ACUTE, 4), (ZHONG, 8), (EMOJI, 16)]
IDS = ["ascii", "cp1252", "unicode", "surrogate-pair"]


def _rung(comment: str | None) -> Rung:
    """Return a rung with no other finding: X001 wired to a coil."""
    return Rung([[Contact("X001"), *["-"] * 30]], [Coil("Y001")], comment)


def _comment(unit: str, size: int, total: int) -> str:
    """Return a comment of as many *unit* as fit in *total* bytes, padded with ``a``."""
    count, rest = divmod(total, size)
    return unit * count + "a" * rest


def _too_long(size: int) -> str:
    cut = size - COMMENT_MAX_BYTES
    return (
        f"the comment is too long: CLICK would store {size} bytes, and the limit is 1400. "
        f"Shorten the comment by at least {cut} byte{'' if cut == 1 else 's'}."
    )


@pytest.mark.parametrize(("unit", "size"), UNITS, ids=IDS)
def test_a_comment_up_to_the_limit_has_no_finding(unit: str, size: int) -> None:
    for total in (COMMENT_MAX_BYTES - 1, COMMENT_MAX_BYTES):
        rung = _rung(_comment(unit, size, total))
        assert check(rung) == []
        encode(rung)


@pytest.mark.parametrize(("unit", "size"), UNITS, ids=IDS)
def test_a_comment_one_byte_over_the_limit_is_too_long(unit: str, size: int) -> None:
    rung = _rung(_comment(unit, size, COMMENT_MAX_BYTES) + "a")
    (finding,) = check(rung)
    assert finding.code is Code.COMMENT_TOO_LONG
    assert (finding.rung, finding.click_id, finding.captured) == (0, None, False)
    assert (finding.row, finding.column) == (None, None)
    assert finding.message == _too_long(COMMENT_MAX_BYTES + 1)
    with pytest.raises(EncodeError, match=f"would store {COMMENT_MAX_BYTES + 1} bytes"):
        encode(rung)


@pytest.mark.parametrize(("unit", "size"), UNITS, ids=IDS)
def test_one_more_character_counts_its_bytes(unit: str, size: int) -> None:
    count, rest = divmod(COMMENT_MAX_BYTES, size)
    rung = _rung(unit * (count + 1) + "a" * rest)
    (finding,) = check(rung)
    assert finding.message == _too_long(COMMENT_MAX_BYTES + size)
    with pytest.raises(EncodeError, match=f"would store {COMMENT_MAX_BYTES + size} bytes"):
        encode(rung)


def test_the_size_counts_each_style_group() -> None:
    """``**bold**`` is written as ``{\\b bold}``, so the group adds 5 bytes."""
    at_limit = "**" + "a" * (COMMENT_MAX_BYTES - 5) + "**"
    assert check(_rung(at_limit)) == []
    over = "**" + "a" * (COMMENT_MAX_BYTES - 4) + "**"
    assert [f.message for f in check(_rung(over))] == [_too_long(COMMENT_MAX_BYTES + 1)]


@pytest.mark.parametrize("comment", [None, ""])
def test_no_comment_has_no_finding(comment: str | None) -> None:
    assert check(_rung(comment)) == []


def test_only_the_rung_with_the_long_comment_has_a_finding() -> None:
    rungs = [_rung("ok"), _rung(E_ACUTE * 350 + "ab"), _rung(E_ACUTE * 350)]
    (finding,) = check(rungs)
    assert finding.rung == 1
    assert finding.message == (
        "the comment is too long: CLICK would store 1402 bytes, and the limit is 1400. "
        "Shorten the comment by at least 2 bytes."
    )
    # encode() counts the rungs from 0 too.
    with pytest.raises(EncodeError, match="^The comment of rung 1 is too long"):
        encode(rungs)


def test_the_finding_comes_before_the_findings_at_a_cell() -> None:
    """A contact that no rail reaches gives ``no-rail`` at its cell, after the comment."""
    rung = Rung([["", Contact("X001"), *["-"] * 29]], [Coil("Y001")], "a" * 1401)
    findings = [(f.code, f.row, f.column) for f in check(rung)]
    assert findings[0] == (Code.COMMENT_TOO_LONG, None, None)
    assert (Code.NO_RAIL, 0, 1) in findings[1:]


def test_the_finding_comes_after_layout_too_tall() -> None:
    conditions = [[Contact("X001"), "T", *["-"] * 29]]
    conditions += [["", "T", *["-"] * 29]] * 31 + [["", "-", *["-"] * 29]]
    rung = Rung(conditions, [Coil(f"C{i}") for i in range(1, 34)], "a" * 1401)
    assert [f.code for f in check(rung)] == [Code.LAYOUT_TOO_TALL, Code.COMMENT_TOO_LONG]


def test_the_finding_comes_after_an_undecoded_marker() -> None:
    """A rung that you build around a marker is not a marker rung, so its comment counts."""
    rung = Rung(
        [["-"] * 31, [Contact("X001"), *["-"] * 30]],
        [Undecoded("why", 3), Coil("Y001")],
        "a" * 1401,
    )
    assert [f.code for f in check(rung)] == [Code.UNDECODED_RUNG, Code.COMMENT_TOO_LONG]


@pytest.mark.parametrize(
    ("error", "own"),
    [("x" * 2000, None), ("why", "a" * COMMENT_MAX_BYTES)],
    ids=["long-error", "long-own-comment"],
)
def test_a_marker_rung_gets_no_comment_finding(error: str, own: str | None) -> None:
    """The decoder writes a marker rung's comment, so you could not act on the finding."""
    rung = marker_rung(Undecoded(error, 3), own)
    assert rung.comment is not None and len(rung.comment) > COMMENT_MAX_BYTES
    assert [f.code for f in check(rung)] == [Code.UNDECODED_RUNG]
