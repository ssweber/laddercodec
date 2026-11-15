"""Fixtures the decoders refuse, so a test that decodes every fixture skips them.

A refused rung decodes as an undecoded marker, which ``encode()`` refuses and no capture
holds.  Each entry is a path under ``tests/fixtures`` and has a test of its own that checks
the refusal.
"""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

#: A down wire in the output column: ``decode`` gives a marker for the rung.
REFUSED = frozenset({"v4_captures/windy_road_pasted.bin"})


def is_refused(path: Path) -> bool:
    """True when *path* is a fixture the decoders refuse."""
    try:
        return path.resolve().relative_to(FIXTURES.resolve()).as_posix() in REFUSED
    except ValueError:
        return False
