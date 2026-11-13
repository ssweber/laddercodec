"""Tumbler fixture: 34 real Click programs, SCR decode vs clipboard ground truth.

Each ``<name>.scr`` (Click's internal Scr*.tmp program file) is paired with
``<name>.clipboard.bin``, the same program copied out of Click via the
clipboard, and ``<name>.clipboard.csv``, that copy decoded with the verified
clipboard decoder and written with ``write_csv``.  Decoding the SCR file must
give the clipboard decode's rungs cell for cell (rows, conditions,
instructions, comment), and write the same CSV text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec import decode, decode_program, write_csv

_TUMBLER_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "tumbler"
_SCR_PATHS = sorted(_TUMBLER_DIR.rglob("*.scr"), key=lambda p: p.name.lower())


def _cells(rungs) -> list[tuple[object, ...]]:
    return [(r.logical_rows, r.conditions, r.instructions, r.comment) for r in rungs]


@pytest.mark.parametrize("scr_path", _SCR_PATHS, ids=lambda p: p.stem)
def test_tumbler_scr_decodes_to_clipboard_rungs(scr_path: Path) -> None:
    clipboard_bin = scr_path.with_name(f"{scr_path.stem}.clipboard.bin")
    assert clipboard_bin.exists(), f"missing ground truth: {clipboard_bin.name}"

    program = decode_program(scr_path.read_bytes())
    if scr_path.parent.name == "subroutines":
        assert program.name == scr_path.stem

    clipboard = decode(clipboard_bin.read_bytes())
    expected = clipboard if isinstance(clipboard, list) else [clipboard]
    assert _cells(program.rungs) == _cells(expected)


@pytest.mark.parametrize("scr_path", _SCR_PATHS, ids=lambda p: p.stem)
def test_tumbler_scr_decodes_to_clipboard_csv(scr_path: Path, tmp_path: Path) -> None:
    clipboard_csv = scr_path.with_name(f"{scr_path.stem}.clipboard.csv")
    assert clipboard_csv.exists(), f"missing ground truth: {clipboard_csv.name}"

    out_path = tmp_path / "decoded.csv"
    write_csv(out_path, decode_program(scr_path.read_bytes()).rungs, index=True)

    assert out_path.read_text(encoding="utf-8") == clipboard_csv.read_text(encoding="utf-8")
