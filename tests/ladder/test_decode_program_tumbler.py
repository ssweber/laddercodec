"""Tumbler fixture: 34 real Click programs, SCR decode vs clipboard ground truth.

Each ``<name>.scr`` (Click's internal Scr*.tmp program file) is paired with
``<name>.clipboard.csv`` — the same program copied out of Click via the
clipboard and decoded with the verified clipboard decoder.  Decoding the SCR
file must reproduce the clipboard CSV byte-for-byte.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec import decode_program, write_csv

_TUMBLER_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "tumbler"
_SCR_PATHS = sorted(_TUMBLER_DIR.rglob("*.scr"), key=lambda p: p.name.lower())


@pytest.mark.parametrize("scr_path", _SCR_PATHS, ids=lambda p: p.stem)
def test_tumbler_scr_decodes_to_clipboard_csv(scr_path: Path, tmp_path: Path):
    clipboard_csv = scr_path.with_name(f"{scr_path.stem}.clipboard.csv")
    assert clipboard_csv.exists(), f"missing ground truth: {clipboard_csv.name}"

    program = decode_program(scr_path.read_bytes())
    if scr_path.parent.name == "subroutines":
        assert program.name == scr_path.stem

    out_path = tmp_path / "decoded.csv"
    write_csv(out_path, program.rungs, index=True)

    assert out_path.read_text(encoding="utf-8") == clipboard_csv.read_text(encoding="utf-8")
