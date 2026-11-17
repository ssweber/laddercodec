"""The one capture that decodes to an undecoded marker, for the tests that decode every capture.

``v4_captures/windy_road_pasted.bin`` has a down wire in its output column, which ``decode``
refuses, so its rung decodes as a marker with an ``UndecodedRungWarning``
(``test_undecoded.test_windy_road_decodes_to_a_marker``).  pytest turns that warning into an
error, so a sweep either leaves the capture out (:func:`without_marker`) or decodes it
expecting the marker (:func:`decode_capture`).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from laddercodec import Rung, UndecodedRungWarning, decode

WINDY_ROAD = Path(__file__).parent / "fixtures" / "v4_captures" / "windy_road_pasted.bin"


def is_windy_road(path: Path) -> bool:
    """True when *path* is the capture that decodes to a marker."""
    return path.resolve() == WINDY_ROAD.resolve()


def without_marker(paths: Iterable[Path]) -> list[Path]:
    """*paths* less the capture that decodes to a marker: a marker rung has nothing to sweep."""
    return [path for path in paths if not is_windy_road(path)]


def decode_capture(path: Path) -> list[Rung]:
    """``decode`` of the capture at *path*, expecting the marker where it holds one."""
    data = path.read_bytes()
    if not is_windy_road(path):
        return decode(data)
    with pytest.warns(UndecodedRungWarning):
        return decode(data)
