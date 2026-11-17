"""Helpers for the tests that decode every capture. One capture decodes to a marker.

``v4_captures/windy_road_pasted.bin`` has a down wire in its output column, and ``decode``
refuses that wire. So ``decode`` returns its rung with an ``Undecoded`` marker as the only
instruction, and warns with ``UndecodedRungWarning``.
``test_undecoded.test_windy_road_decodes_to_a_marker`` tests this.

pytest turns that warning into an error. So a test that decodes every capture either leaves
this capture out with :func:`without_marker`, or decodes it with :func:`decode_capture`, which
expects the warning.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from laddercodec import Rung, UndecodedRungWarning, decode

WINDY_ROAD = Path(__file__).parent / "fixtures" / "v4_captures" / "windy_road_pasted.bin"


def is_windy_road(path: Path) -> bool:
    """Return whether *path* is the capture that decodes to a marker."""
    return path.resolve() == WINDY_ROAD.resolve()


def without_marker(paths: Iterable[Path]) -> list[Path]:
    """Return *paths* without the capture that decodes to a marker.

    A rung whose only instruction is a marker has nothing for these tests to check.
    """
    return [path for path in paths if not is_windy_road(path)]


def decode_capture(path: Path) -> list[Rung]:
    """Decode the capture at *path* and return its rungs.

    If *path* is the capture that decodes to a marker, expect its ``UndecodedRungWarning``.
    """
    data = path.read_bytes()
    if not is_windy_road(path):
        return decode(data)
    with pytest.warns(UndecodedRungWarning):
        return decode(data)
