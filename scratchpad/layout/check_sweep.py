"""Run laddercodec.check over every fixture CSV and capture; print each finding.

Run from the worktree: uv run --no-sync python scratchpad/layout/check_sweep.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import laddercodec
from laddercodec import decode, read_csv
from laddercodec.layout_check import check

FIX = Path(laddercodec.__file__).resolve().parents[2] / "tests" / "fixtures"
EXTRA = [Path(p) for p in sys.argv[1:]]


def rungs_of(path: Path) -> list:
    if path.suffix == ".csv":
        return read_csv(path)
    got = decode(path.read_bytes())
    return got if isinstance(got, list) else [got]


paths = sorted(FIX.rglob("*.csv")) + sorted(FIX.rglob("*.bin")) + EXTRA
total = 0
for path in paths:
    try:
        rungs = rungs_of(path)
    except Exception as exc:  # noqa: BLE001
        print(f"SKIP {path.relative_to(FIX) if path.is_relative_to(FIX) else path}: {type(exc).__name__}")
        continue
    found = check(rungs)
    total += len(rungs)
    for f in found:
        name = path.relative_to(FIX) if path.is_relative_to(FIX) else path
        print(f"{name} rung {f.rung}: {f.kind} {f.code}: {f.message}")
print(f"{total} rungs checked")
