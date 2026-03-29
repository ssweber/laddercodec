"""Manage golden CSV/BIN fixtures.

Subcommands:
    generate  — Regenerate all .bin files from .csv sources.
    prune     — Remove verify_progress.log entries for changed/deleted goldens,
                delete debris (.note.txt, .png) and orphaned .bin (no .csv).
    sync      — generate + prune (default when no subcommand given).

Usage:
    uv run devtools/golden.py           # sync (generate + prune)
    uv run devtools/golden.py generate
    uv run devtools/golden.py prune
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

GOLDEN_DIR = ROOT / "tests" / "fixtures" / "ladder_captures" / "golden"
LOG = GOLDEN_DIR / "verify_progress.log"


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


def generate() -> None:
    from laddercodec import encode, read_csv

    csv_files = sorted(GOLDEN_DIR.glob("*.csv"))
    if not csv_files:
        print(f"No CSV files found in {GOLDEN_DIR}")
        sys.exit(1)

    print(f"Generating .bin fixtures from {len(csv_files)} CSV files:")
    for csv_path in csv_files:
        rungs = read_csv(csv_path)
        if len(rungs) > 1:
            result = encode(rungs)
        else:
            result = encode(rungs[0])
        bin_path = csv_path.with_suffix(".bin")
        bin_path.write_bytes(result)
        print(f"  {csv_path.name} -> {bin_path.name} ({len(result):,} bytes)")

    print(f"\nDone. {len(csv_files)} fixtures generated.")


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------


def prune() -> None:
    csv_stems = {p.stem for p in GOLDEN_DIR.glob("*.csv")}

    # --- Delete orphaned .bin (no matching .csv) ---
    orphaned = sorted(p for p in GOLDEN_DIR.glob("*.bin") if p.stem not in csv_stems)
    if orphaned:
        print(f"Deleting {len(orphaned)} orphaned .bin files:")
        for p in orphaned:
            print(f"  {p.name}")
            p.unlink()

    # --- Delete debris (.note.txt, .png) ---
    debris = sorted(GOLDEN_DIR.glob("*.note.txt")) + sorted(GOLDEN_DIR.glob("*.png"))
    if debris:
        print(f"Deleting {len(debris)} debris files:")
        for p in debris:
            print(f"  {p.name}")
            p.unlink()

    # --- Prune verify_progress.log ---
    if not LOG.exists():
        print("No verify_progress.log found — nothing to prune.")
        return

    # Find .bin files with uncommitted changes
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", "tests/fixtures/ladder_captures/golden/*.bin"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    changed_stems = {
        Path(line.strip()).stem for line in result.stdout.strip().split("\n") if line.strip()
    }

    # Stems in log that no longer have a .csv
    lines = LOG.read_text().splitlines(keepends=True)
    kept: list[str] = []
    removed: list[str] = []

    for line in lines:
        # Preserve header / blank lines
        if line.startswith("#") or not line.strip():
            # Drop old header lines — we'll write a fresh one
            continue
        name = line.split(":")[0].strip()
        if name in changed_stems or name not in csv_stems:
            removed.append(name)
        else:
            kept.append(line)

    # Write back with a single clean header
    with open(LOG, "w", encoding="utf-8") as f:
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


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sync"

    if cmd == "generate":
        generate()
    elif cmd == "prune":
        prune()
    elif cmd == "sync":
        generate()
        print()
        prune()
    else:
        print(f"Unknown subcommand: {cmd}")
        print("Usage: uv run devtools/golden.py [generate|prune|sync]")
        sys.exit(1)


if __name__ == "__main__":
    main()
