"""Compare {slug}.csv against {slug}.clipboard.csv in a directory.

Reports which pairs are identical and which differ.

Usage:
    uv run devtools/compare_csv.py <directory>
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <directory>", file=sys.stderr)
        sys.exit(1)

    directory = Path(sys.argv[1])
    if not directory.is_dir():
        print(f"Not a directory: {directory}", file=sys.stderr)
        sys.exit(1)

    # Find all .clipboard.csv files and match to base CSVs
    clipboard_files = sorted(directory.rglob("*.clipboard.csv"))
    if not clipboard_files:
        print(f"No *.clipboard.csv files found in {directory}")
        sys.exit(1)

    identical = 0
    differ = 0
    missing = 0

    for clip_path in clipboard_files:
        # {slug}.clipboard.csv -> {slug}.csv (same directory)
        slug = clip_path.name.removesuffix(".clipboard.csv")
        base_path = clip_path.parent / f"{slug}.csv"

        if not base_path.exists():
            print(f"  MISSING  {slug}.csv")
            missing += 1
            continue

        if base_path.read_bytes() == clip_path.read_bytes():
            print(f"  IDENTICAL  {slug}")
            identical += 1
        else:
            print(f"  DIFFER     {slug}")
            differ += 1

    print()
    print(
        f"Total: {len(clipboard_files)} pairs — {identical} identical, {differ} differ, {missing} missing base"
    )
    sys.exit(1 if differ or missing else 0)


if __name__ == "__main__":
    main()
