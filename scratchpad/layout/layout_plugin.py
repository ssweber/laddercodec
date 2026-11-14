"""Pytest plugin for a what-if run: read_csv lays every rung out (LAYOUT_WRITE=1: write_csv too).

A rung the layout refuses keeps its written grid (Syntax Check rules do not raise).  A rung the
layout splits keeps its written grid too (convert_rung returns one rung) and is counted.

  PYTHONPATH=<job dir> uv run --no-sync pytest -q -p layout_plugin
"""

from __future__ import annotations

import os
from collections import Counter

import laddercodec.csv as lcsv
import laddercodec.csv.writer as writer
from laddercodec._layout import LayoutError, layout
from laddercodec.decode import Rung

STATS: Counter = Counter()
_orig_convert = lcsv.convert_rung
_orig_rows = writer.decoded_rung_to_rows


def _convert(rung_ast, *, strict: bool = True):
    logical_rows, conditions, instructions, comment = _orig_convert(rung_ast, strict=strict)
    rung = Rung(logical_rows, conditions, instructions, comment)
    try:
        got = layout(rung)
    except (LayoutError, ValueError):
        STATS["refused (kept literal)"] += 1
        return logical_rows, conditions, instructions, comment
    if len(got) != 1:
        STATS["split (kept literal)"] += 1
        return logical_rows, conditions, instructions, comment
    STATS["laid out"] += 1
    g = got[0]
    return g.logical_rows, g.conditions, g.instructions, comment


def _rows(rung):
    try:
        got = layout(rung)
    except (LayoutError, ValueError):
        return _orig_rows(rung)
    if len(got) != 1:
        return _orig_rows(rung)
    g = got[0]
    g.comment = rung.comment
    return _orig_rows(g)


def pytest_configure(config) -> None:
    lcsv.convert_rung = _convert
    writer.convert_rung = _convert
    if os.environ.get("LAYOUT_WRITE") == "1":
        writer.decoded_rung_to_rows = _rows


def pytest_terminal_summary(terminalreporter) -> None:
    terminalreporter.write_line(f"layout plugin: {dict(STATS)}")
