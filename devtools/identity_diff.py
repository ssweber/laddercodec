"""Compare two JSON outputs of ``fixture_snapshot.py`` or ``operand_probe.py``.

Both tools write ``{"tool": ..., "meta": {...}, "cases": {key: value}}``.  Only ``cases``
is compared: ``meta`` holds counts and summaries derived from it.

    uv run python -I devtools/identity_diff.py a.json b.json

Prints one line per difference and exits 1 if there is any, 0 if the cases are identical.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _short(value: Any, width: int = 400) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= width else text[: width - 3] + "..."


def _walk(path: str, a: Any, b: Any, out: list[str]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            sub = f"{path}.{key}"
            if key not in b:
                out.append(f"- {sub}: {_short(a[key])}")
            elif key not in a:
                out.append(f"+ {sub}: {_short(b[key])}")
            else:
                _walk(sub, a[key], b[key], out)
        return
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for index, (x, y) in enumerate(zip(a, b, strict=True)):
            _walk(f"{path}[{index}]", x, y, out)
        return
    if a != b:
        out.append(f"~ {path}: {_short(a)} -> {_short(b)}")


def diff_cases(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """Return one line per difference between two ``cases`` dicts."""
    out: list[str] = []
    for key in sorted(set(a) | set(b)):
        if key not in b:
            out.append(f"- {key}: {_short(a[key])}")
        elif key not in a:
            out.append(f"+ {key}: {_short(b[key])}")
        else:
            _walk(key, a[key], b[key], out)
    return out


def diff_files(path_a: str | Path, path_b: str | Path) -> int:
    """Print the differences between two tool outputs; return the exit status.

    0: identical cases; 1: differences; 2: an input could not be read.
    """
    docs = []
    for path in (path_a, path_b):
        try:
            with open(path, encoding="utf-8") as handle:
                docs.append(json.load(handle))
        except (OSError, ValueError) as exc:
            print(f"cannot read {path}: {exc}", file=sys.stderr)
            return 2
    a, b = docs
    if a.get("tool") != b.get("tool"):
        print(f"tool differs: {a.get('tool')!r} vs {b.get('tool')!r}")
        return 1
    lines = diff_cases(a["cases"], b["cases"])
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")  # ty: ignore[call-non-callable]
    for line in lines:
        print(line)
    print(f"{len(lines)} difference(s) in {len(a['cases'])} vs {len(b['cases'])} cases")
    return 1 if lines else 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: identity_diff.py A.json B.json", file=sys.stderr)
        return 2
    return diff_files(args[0], args[1])


if __name__ == "__main__":
    raise SystemExit(main())
