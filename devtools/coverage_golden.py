"""Manage coverage golden CSV/BIN fixtures.

Regenerates all .bin files from .csv sources and prunes the verify log
for changed/deleted fixtures.

Usage:
    uv run devtools/coverage_golden.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from laddercodec.csv.converter import ConvertError, convert_rung
from laddercodec.csv.parser import parse_csv_file
from laddercodec.encode import AfToken, ConditionToken, encode_rung
from laddercodec.encode_multi import encode_rungs

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "coverage" / "golden"
VERIFY_LOG = GOLDEN_DIR / "verify_progress.log"


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


def generate() -> None:
    csv_files = sorted(GOLDEN_DIR.glob("*.csv"))
    if not csv_files:
        print(f"No CSV files found in {GOLDEN_DIR}")
        sys.exit(1)

    print(f"Generating coverage bins from {len(csv_files)} CSV files:")
    for csv_path in csv_files:
        encoded = _encode_csv(csv_path)
        bin_path = csv_path.with_suffix(".bin")
        bin_path.write_bytes(encoded)
        print(f"  {csv_path.name} -> {bin_path.name} ({len(encoded):,} bytes)")

    print(f"\nDone. {len(csv_files)} fixtures generated.")


def prune() -> None:
    csv_stems = {p.stem for p in GOLDEN_DIR.glob("*.csv")}

    # --- Delete orphaned .bin (no matching .csv) ---
    orphaned = sorted(p for p in GOLDEN_DIR.glob("*.bin") if p.stem not in csv_stems)
    if orphaned:
        print(f"Deleting {len(orphaned)} orphaned .bin files:")
        for p in orphaned:
            print(f"  {p.name}")
            p.unlink()

    # --- Prune verify_progress.log ---
    if not VERIFY_LOG.exists():
        print("No verify_progress.log found — nothing to prune.")
        return

    # Find .bin files with uncommitted changes
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", "tests/fixtures/coverage/golden/*.bin"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    changed_stems = {
        Path(line.strip()).stem for line in result.stdout.strip().split("\n") if line.strip()
    }

    lines = VERIFY_LOG.read_text().splitlines(keepends=True)
    kept: list[str] = []
    removed: list[str] = []

    for line in lines:
        if line.startswith("#") or not line.strip():
            continue
        name = line.split(":")[0].strip()
        if name in changed_stems or name not in csv_stems:
            removed.append(name)
        else:
            kept.append(line)

    with open(VERIFY_LOG, "w", encoding="utf-8") as f:
        f.write("# verify_progress.log — tracks Click paste verification status\n")
        for line in kept:
            f.write(line if line.endswith("\n") else line + "\n")

    verified = sum(1 for ln in kept if ln.strip())
    total = len(csv_stems)
    unverified = total - verified

    if removed:
        print(f"Pruned {len(removed)} entries from verify_progress.log:")
        for name in sorted(removed):
            print(f"  {name}")

    print(f"\nVerification status: {verified}/{total} verified, {unverified} unverified")
    if unverified:
        verified_names = {ln.split(":")[0].strip() for ln in kept if ln.strip()}
        for name in sorted(csv_stems - verified_names):
            print(f"  UNVERIFIED: {name}")


def main() -> None:
    if len(sys.argv) > 1:
        print("Usage: uv run devtools/coverage_golden.py")
        raise SystemExit(2)
    generate()
    print()
    prune()


if __name__ == "__main__":
    main()
