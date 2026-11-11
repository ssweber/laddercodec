"""Committed files carry no CLICK DLL addresses.

A citation names its evidence (an OBJ-xxx id, a Help topic, a capture, an arc.md ruling or
``DLL: <name>.dll, <dialog/field>``), never a location inside a CLICK DLL.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# A location in a DLL's image: 0x100xxxxx, a bare 100xxxxx, or @xxxxxxxx.
ADDRESS = re.compile(
    r"(?<![0-9A-Za-z_.])(?:0x)?100[0-9A-Fa-f]{5}(?![0-9A-Za-z_])|@[0-9A-Fa-f]{8}\b"
)

# path -> reason.  Keep empty.
ALLOWED: dict[str, str] = {}


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def test_pattern_matches_the_forms_in_use() -> None:
    tail = "0aabb"  # built here so this file holds no address itself
    for text in ("0x100" + tail, "@100" + tail, "Inst_Search 100" + tail, "at 100" + tail):
        assert ADDRESS.search(text), text
    for text in ("0x8bc0", "0x271e", "0x0A60", "0x6fff", "0x10e", "0x1201", "+0x19", "x1000"):
        assert not ADDRESS.search(text), text


def test_no_dll_addresses_in_tracked_files() -> None:
    hits = []
    for rel in _tracked_files():
        if rel in ALLOWED:
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if ADDRESS.search(line):
                hits.append(f"{rel}:{number}: {line.strip()[:100]}")
    assert not hits, "DLL addresses in committed files:\n" + "\n".join(hits)
