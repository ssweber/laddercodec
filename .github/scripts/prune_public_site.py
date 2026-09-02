#!/usr/bin/env python3
"""Remove explicitly private source files copied by Zensical 0.0.57."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


PRIVATE_ROOT_NAMES = {
    "__pycache__",
    "agents",
    "agents.md",
    "claude",
    "claude.md",
    "gen_llms.py",
    "gen_reference.py",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune private public-site paths.")
    parser.add_argument("site", type=Path, help="Generated site directory to prune")
    args = parser.parse_args()

    site = args.site.resolve()
    if not site.is_dir():
        raise RuntimeError(f"Public site directory does not exist: {site}")

    for path in site.iterdir():
        if path.name.lower() not in PRIVATE_ROOT_NAMES:
            continue
        resolved = path.resolve()
        if resolved.parent != site:
            raise RuntimeError(f"Refusing to prune path outside public site: {resolved}")
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
