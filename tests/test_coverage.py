"""Coverage test harness -- per-rung byte-exact comparison against Click golden binaries.

Workflow:
    1. pyrung devtools/coverage_program.py -> fixtures/coverage/main.csv
    2. Paste CSV into Click, copy each rung back -> golden/<rung_id>.bin
    3. make test -> this file runs, comparing encoded output to golden binaries

Pipeline: parse_csv_file() -> convert_rung() -> encode_rung() -> compare bytes.

Standalone report:  uv run python -m pytest tests/test_coverage.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from laddercodec.csv.converter import ConvertError, convert_rung
from laddercodec.csv.parser import parse_csv_file
from laddercodec.encode import encode_rung

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "coverage"
CSV_PATH = FIXTURES_DIR / "main.csv"
GOLDEN_DIR = FIXTURES_DIR / "golden"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rung_id(rung):
    """Extract rung ID from comment rows (e.g. 'cond__no', 'out__tag')."""
    if rung.comment_rows:
        return rung.comment_rows[0].canonical.conditions[0].strip()
    return "unknown"


def _golden_path(rung_id: str) -> Path:
    """Map rung ID to golden binary path: 'cond__no' -> cond__no.bin."""
    return GOLDEN_DIR / f"{rung_id}.bin"


# ---------------------------------------------------------------------------
# Load rungs at import time for parametrize (empty list if no CSV)
# ---------------------------------------------------------------------------

_RUNGS = list(parse_csv_file(CSV_PATH).rungs) if CSV_PATH.exists() else []
_IDS = [_rung_id(r) for r in _RUNGS]


# ---------------------------------------------------------------------------
# Parametrized test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rung_index", range(len(_RUNGS)), ids=_IDS)
def test_rung_byte_exact(rung_index):
    rung = _RUNGS[rung_index]
    rid = _rung_id(rung)
    golden = _golden_path(rid)

    if not golden.exists():
        pytest.skip(f"no golden binary: {golden.name}")

    try:
        logical_rows, cond_rows, af_tokens, comment = convert_rung(rung)
    except (ConvertError, NotImplementedError, ValueError) as exc:
        pytest.skip(f"not encodable: {exc}")

    encoded = encode_rung(
        logical_rows=logical_rows,
        condition_rows=cond_rows,
        af_tokens=af_tokens,
        comment=comment,
    )

    golden_bytes = golden.read_bytes()
    if encoded != golden_bytes:
        offset = next(
            (
                i
                for i in range(min(len(golden_bytes), len(encoded)))
                if golden_bytes[i] != encoded[i]
            ),
            min(len(golden_bytes), len(encoded)),
        )
        pytest.fail(
            f"byte mismatch at 0x{offset:04X} (golden={len(golden_bytes)}B, got={len(encoded)}B)"
        )


# ---------------------------------------------------------------------------
# Standalone progress report
# ---------------------------------------------------------------------------

_COLORS = {
    "PASS": "\033[32m",
    "FAIL": "\033[31m",
    "SKIP": "\033[33m",
    "NBIN": "\033[36m",
    "ERR!": "\033[31m",
}
_RST = "\033[0m"


def _run_report():
    if not CSV_PATH.exists():
        print(f"No CSV at {CSV_PATH} -- run pyrung coverage_program.py first")
        sys.exit(1)

    rungs = list(parse_csv_file(CSV_PATH).rungs)
    results: list[tuple[str, str, str]] = []

    for rung in rungs:
        rid = _rung_id(rung)
        golden = _golden_path(rid)

        if not golden.exists():
            results.append((rid, "NBIN", ""))
            continue

        try:
            logical_rows, cond_rows, af_tokens, comment = convert_rung(rung)
        except (ConvertError, NotImplementedError, ValueError) as exc:
            results.append((rid, "SKIP", str(exc)))
            continue
        except Exception as exc:
            results.append((rid, "ERR!", f"{type(exc).__name__}: {exc}"))
            continue

        try:
            encoded = encode_rung(
                logical_rows=logical_rows,
                condition_rows=cond_rows,
                af_tokens=af_tokens,
                comment=comment,
            )
        except Exception as exc:
            results.append((rid, "ERR!", f"{type(exc).__name__}: {exc}"))
            continue

        golden_bytes = golden.read_bytes()
        if encoded == golden_bytes:
            results.append((rid, "PASS", ""))
        else:
            offset = next(
                (
                    i
                    for i in range(min(len(golden_bytes), len(encoded)))
                    if golden_bytes[i] != encoded[i]
                ),
                min(len(golden_bytes), len(encoded)),
            )
            results.append(
                (
                    rid,
                    "FAIL",
                    f"diff at 0x{offset:04X} (golden={len(golden_bytes)}B, got={len(encoded)}B)",
                )
            )

    # -- Print report --
    passed = sum(1 for _, s, _ in results if s == "PASS")
    testable = sum(1 for _, s, _ in results if s != "NBIN")
    pct = (passed / testable * 100) if testable else 0

    print(f"\n{'=' * 68}")
    print(f"  Ladder Codec Coverage: {passed}/{testable} byte-exact ({pct:.0f}%)")
    print(f"{'=' * 68}\n")

    for rid, status, detail in results:
        col = _COLORS.get(status, "")
        line = f"  {col}{status}{_RST}  {rid}"
        if detail:
            line += f"  ({detail})"
        print(line)

    counts: dict[str, int] = {}
    for _, s, _ in results:
        counts[s] = counts.get(s, 0) + 1
    parts = []
    if counts.get("PASS"):
        parts.append(f"{counts['PASS']} passed")
    if counts.get("FAIL"):
        parts.append(f"{counts['FAIL']} FAILED")
    if counts.get("SKIP"):
        parts.append(f"{counts['SKIP']} not implemented")
    if counts.get("NBIN"):
        parts.append(f"{counts['NBIN']} need capture")
    if counts.get("ERR!"):
        parts.append(f"{counts['ERR!']} errors")
    print(f"\n  {', '.join(parts)}\n")


if __name__ == "__main__":
    _run_report()
