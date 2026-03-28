"""Coverage test harness -- per-rung byte-exact comparison against Click golden binaries.

Workflow:
    1. Create golden/<rung_id>.csv by hand (33-column canonical format)
    2. Paste CSV into Click, copy each rung back -> golden/<rung_id>.bin
    3. make test -> this file runs, comparing encoded output to golden binaries

Pipeline: parse_csv_file() -> convert_rung() -> encode_rung() -> compare bytes.

Standalone report:  uv run python -m pytest tests/test_coverage.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec.csv.converter import ConvertError, convert_rung
from laddercodec.csv.parser import parse_csv_file
from laddercodec.csv.writer import write_csv
from laddercodec.decode import Rung, decode
from laddercodec.encode import encode_rung
from laddercodec.encode_multi import encode_rungs

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "coverage" / "golden"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_golden_pairs() -> list[tuple[str, Path, Path]]:
    """Scan golden dir for CSV files with matching .bin files.

    Returns list of (rung_id, csv_path, bin_path).
    """
    pairs = []
    for csv_path in sorted(GOLDEN_DIR.glob("*.csv")):
        bin_path = csv_path.with_suffix(".bin")
        if bin_path.exists():
            pairs.append((csv_path.stem, csv_path, bin_path))
    return pairs


def _convert_program(
    csv_path: Path,
) -> tuple[list[object], list[tuple[int, list[list[object]], list[object], str | None]]]:
    program = parse_csv_file(csv_path)
    rungs = list(program.rungs)
    converted: list[tuple[int, list[list[object]], list[object], str | None]] = []
    for idx, rung in enumerate(rungs):
        try:
            converted.append(convert_rung(rung))
        except (ConvertError, NotImplementedError, ValueError) as exc:
            raise ValueError(f"rung {idx}: {exc}") from exc
    return rungs, converted


def _encode_converted(
    converted: list[tuple[int, list[list[object]], list[object], str | None]],
) -> bytes:
    if len(converted) == 1:
        logical_rows, cond_rows, af_tokens, comment = converted[0]
        return encode_rung(
            logical_rows=logical_rows,
            condition_rows=cond_rows,
            af_tokens=af_tokens,
            comment=comment,
        )

    rung_inputs = [(lr, cond_rows, af_tokens) for lr, cond_rows, af_tokens, _ in converted]
    comments = [comment for _, _, _, comment in converted]
    return encode_rungs(rung_inputs, comments=comments)


_GOLDEN_PAIRS = _load_golden_pairs()
_IDS = [rid for rid, _, _ in _GOLDEN_PAIRS]


# ---------------------------------------------------------------------------
# Parametrized test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pair_index", range(len(_GOLDEN_PAIRS)), ids=_IDS)
def test_rung_byte_exact(pair_index):
    _rid, csv_path, bin_path = _GOLDEN_PAIRS[pair_index]
    try:
        rungs, converted = _convert_program(csv_path)
    except ValueError as exc:
        pytest.skip(f"not encodable: {exc}")
    if not rungs:
        pytest.skip(f"no rungs in {csv_path.name}")

    encoded = _encode_converted(converted)

    golden_bytes = bin_path.read_bytes()
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


@pytest.mark.parametrize("pair_index", range(len(_GOLDEN_PAIRS)), ids=_IDS)
def test_coverage_csv_roundtrip(pair_index, tmp_path: Path):
    """Ensure coverage CSV fixtures survive csv->encode->decode->csv semantically."""
    rid, csv_path, _ = _GOLDEN_PAIRS[pair_index]
    try:
        rungs, converted = _convert_program(csv_path)
    except ValueError as exc:
        pytest.skip(f"not encodable: {exc}")
    if not rungs:
        pytest.skip(f"no rungs in {csv_path.name}")

    encoded = _encode_converted(converted)

    decoded = decode(encoded)
    decoded_rungs = decoded if isinstance(decoded, list) else [decoded]
    if any(not isinstance(r, Rung) for r in decoded_rungs):
        pytest.fail(f"decode returned unexpected object type for {rid}")

    out_csv = tmp_path / f"{rid}.roundtrip.csv"
    write_csv(out_csv, list(decoded_rungs))

    # Compare normalized convert signatures (robust to equivalent token spellings
    # like immediate(X1) vs X1.immediate).
    out_program = parse_csv_file(out_csv)
    out_rungs = list(out_program.rungs)
    if len(out_rungs) != len(rungs):
        pytest.fail(
            f"roundtrip output rung count mismatch for {rid}: {len(out_rungs)} != {len(rungs)}"
        )

    out_converted: list[tuple[int, list[list[object]], list[object], str | None]] = []
    for idx, rung in enumerate(out_rungs):
        out_converted.append(convert_rung(rung))
        if idx >= len(converted):
            pytest.fail(f"unexpected extra rung {idx} in roundtrip output for {rid}")

    assert out_converted == converted


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
    pairs = _load_golden_pairs()
    csv_only = sorted(
        p.stem for p in GOLDEN_DIR.glob("*.csv") if not p.with_suffix(".bin").exists()
    )
    results: list[tuple[str, str, str]] = []

    for rid, csv_path, bin_path in pairs:
        try:
            rungs, converted = _convert_program(csv_path)
        except ValueError as exc:
            results.append((rid, "SKIP", str(exc)))
            continue
        except Exception as exc:
            results.append((rid, "ERR!", f"{type(exc).__name__}: {exc}"))
            continue

        if not rungs:
            results.append((rid, "SKIP", "no rungs in CSV"))
            continue

        try:
            encoded = _encode_converted(converted)
        except Exception as exc:
            results.append((rid, "ERR!", f"{type(exc).__name__}: {exc}"))
            continue

        golden_bytes = bin_path.read_bytes()
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

    for rid in csv_only:
        results.append((rid, "NBIN", ""))

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
