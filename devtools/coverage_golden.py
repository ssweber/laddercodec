"""Manage coverage CSV/BIN fixtures based on verify_progress.log.

Behavior:
    - Parse tests/fixtures/coverage/golden/verify_progress.log
    - Select only fixture stems marked as ``worked``
    - Generate ``.bin`` files for those stems from their ``.csv``
    - Remove any existing ``.bin`` whose stem is not marked ``worked``

Usage:
    uv run devtools/coverage_golden.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from laddercodec.csv.converter import ConvertError, convert_rung
from laddercodec.csv.parser import parse_csv_file
from laddercodec.encode import AfToken, ConditionToken, encode_rung
from laddercodec.encode_multi import encode_rungs

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "coverage" / "golden"
VERIFY_LOG = GOLDEN_DIR / "verify_progress.log"

_WORKED_RE = re.compile(r"^([A-Za-z0-9_]+):\s*worked\s*$")


def _worked_stems_from_log(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Missing verify log: {path}")

    stems: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _WORKED_RE.match(line.strip())
        if m:
            stems.append(m.group(1))
    return sorted(set(stems))


def _encode_csv(csv_path: Path) -> bytes:
    program = parse_csv_file(csv_path)
    if not program.rungs:
        raise ValueError(f"No rungs found in {csv_path.name}")

    converted: list[tuple[int, list[list[ConditionToken]], list[AfToken], str | None]] = []
    for idx, rung in enumerate(program.rungs):
        try:
            logical_rows, cond_rows, af_tokens, comment = convert_rung(rung)
        except (ConvertError, NotImplementedError, ValueError) as exc:
            raise ValueError(f"Cannot encode {csv_path.name} rung {idx}: {exc}") from exc
        converted.append((logical_rows, cond_rows, af_tokens, comment))

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


def sync() -> int:
    worked_stems = _worked_stems_from_log(VERIFY_LOG)
    if not worked_stems:
        print(f"No 'worked' fixtures found in {VERIFY_LOG}")
        return 1

    print(f"Generating coverage bins for {len(worked_stems)} worked fixture(s):")

    missing_csv: list[str] = []
    generated = 0
    for stem in worked_stems:
        csv_path = GOLDEN_DIR / f"{stem}.csv"
        if not csv_path.exists():
            missing_csv.append(stem)
            continue

        encoded = _encode_csv(csv_path)
        bin_path = GOLDEN_DIR / f"{stem}.bin"
        bin_path.write_bytes(encoded)
        generated += 1
        print(f"  {csv_path.name} -> {bin_path.name} ({len(encoded):,} bytes)")

    if missing_csv:
        print("\nMissing CSV files for worked fixtures:")
        for stem in missing_csv:
            print(f"  {stem}.csv")
        return 1

    worked_set = set(worked_stems)
    stale_bins = sorted(p for p in GOLDEN_DIR.glob("*.bin") if p.stem not in worked_set)
    if stale_bins:
        print(f"\nRemoving {len(stale_bins)} non-worked .bin fixture(s):")
        for p in stale_bins:
            print(f"  {p.name}")
            p.unlink()

    print(f"\nDone. Generated {generated} coverage bin fixture(s).")
    return 0


def main() -> None:
    if len(sys.argv) > 1:
        print("Usage: uv run devtools/coverage_golden.py")
        raise SystemExit(2)
    raise SystemExit(sync())


if __name__ == "__main__":
    main()
