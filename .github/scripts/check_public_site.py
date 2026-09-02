#!/usr/bin/env python3
"""Reject private sources and incomplete generated docs in the public site."""

from __future__ import annotations

import argparse
from pathlib import Path


BLOCKED_FILENAMES = {
    "agents",
    "agents.html",
    "agents.md",
    "claude",
    "claude.html",
    "claude.md",
    "gen_llms.py",
    "gen_reference.py",
    "llms-full.txt",
}
BLOCKED_PATH_PARTS = {"__pycache__", "agents", "claude"}
EXPECTED_FILES = {
    "index.html",
    "llms.txt",
    "reference/index.html",
    "reference/api/codec/index.html",
    "reference/api/csv/index.html",
    "reference/api/instructions/index.html",
}


def ascii_text(value: object) -> str:
    return str(value).encode("ascii", errors="backslashreplace").decode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check generated public-site paths.")
    parser.add_argument("site", type=Path, help="Generated site directory to inspect")
    args = parser.parse_args()

    site = args.site
    if not site.is_dir():
        print(f"ERROR: public site directory does not exist: {ascii_text(site)}")
        return 2

    violations: list[str] = []
    actual_files = {
        path.relative_to(site).as_posix()
        for path in site.rglob("*")
        if path.is_file()
    }
    for relative_path in actual_files:
        path = Path(relative_path)
        if path.name.lower() in BLOCKED_FILENAMES or any(
            part.lower() in BLOCKED_PATH_PARTS for part in path.parts
        ):
            violations.append(f"blocked public-site path: {relative_path}")

    for missing in sorted(EXPECTED_FILES - actual_files):
        violations.append(f"missing expected public-site path: {missing}")

    for path in site.rglob("*"):
        if path.suffix.lower() not in {".html", ".md", ".txt"} or not path.is_file():
            continue
        if "::: laddercodec." in path.read_text(encoding="utf-8", errors="replace"):
            relative_path = path.relative_to(site).as_posix()
            violations.append(f"unrendered API directive: {relative_path}")

    if violations:
        for violation in sorted(violations):
            print(f"ERROR: {ascii_text(violation)}")
        print(f"ERROR: public-site guard found {len(violations)} violation(s).")
        return 1

    print(f"OK: public-site guard passed: {ascii_text(site)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
