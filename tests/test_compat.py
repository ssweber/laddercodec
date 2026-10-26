"""find_v4_only(): flags exactly the instructions an older CLICK would mangle."""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec import Break, Continue, Math, find_v4_only, is_v4_only
from laddercodec.decode import Rung, decode

FIXTURES = Path(__file__).parent / "fixtures"
V3_BINS = sorted(
    p for p in (FIXTURES / "coverage" / "golden").glob("*.bin") if not p.stem.endswith("__v4")
) + sorted((FIXTURES / "tumbler").rglob("*.clipboard.bin"))


def _rungs(path: Path) -> list[Rung]:
    decoded = decode(path.read_bytes())
    return decoded if isinstance(decoded, list) else [decoded]


def _flagged_ids(path: Path) -> set[str]:
    rungs = _rungs(path)
    return {(rungs[i].comment or "").split("\n")[0] for i, _ in find_v4_only(rungs)}


@pytest.mark.parametrize("path", V3_BINS, ids=lambda p: p.relative_to(FIXTURES).as_posix())
def test_v3_fixtures_need_nothing_from_v4(path: Path) -> None:
    assert find_v4_only(_rungs(path)) == []


def test_v4_captures_are_flagged() -> None:
    captures = FIXTURES / "v4_captures"
    out_ids = {(r.comment or "").split("\n")[0] for r in _rungs(captures / "out.bin")}
    math_ids = {(r.comment or "").split("\n")[0] for r in _rungs(captures / "math.bin")}
    assert _flagged_ids(captures / "out.bin") == out_ids
    assert _flagged_ids(captures / "math.bin") == math_ids
    assert _flagged_ids(captures / "drum.bin") == {
        "drum__te_mixed",
        "drum__te_ds",
        "drum__te_jog_jump",
        "drum__te_hour",
        "drum__te_day",
    }
    assert _flagged_ids(captures / "loop_exits.bin") == {"break", "continue"}


@pytest.mark.parametrize(
    ("expression", "v4_only"),
    [
        ("SUM ( DS1 : DS10 )", False),
        ("SUM ( TD1 : TD5 )", False),
        ("SUM ( CTD1 : CTD5 )", False),
        ("SUM ( C1 : C16 )", True),
        ("SUM ( X001 : X008 ) + 1", True),
        ("SUM ( CT1 : CT4 )", True),
        ("MAX ( DS1 : DS3 )", True),
        ("ABS ( DS1 )", True),
        ("RAND ( 1 , 100 )", True),
        ("DS1 + SQRT ( DS2 )", False),
    ],
)
def test_math_v4_functions(expression: str, v4_only: bool) -> None:
    assert is_v4_only(Math(expression=expression, result="DS100")) is v4_only


def test_single_rung_and_loop_exits() -> None:
    rung = Rung(logical_rows=1, conditions=[["-"] * 31], instructions=[Break()], comment=None)
    assert find_v4_only(rung) == [(0, Break())]
    assert is_v4_only(Continue())
