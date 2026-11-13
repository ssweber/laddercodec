"""Ensure every golden CSV has been verified through Click paste round-trip.

Covers both golden directories: the ladder captures and the coverage
fixtures. Each reads its own verify_progress.log and checks that every .csv
stem in the directory has a corresponding ": worked" entry. Fails with a
clear list of unverified fixtures if any are missing.

To verify fixtures:  clicknick-rung guided <golden dir>
To regenerate bins:  make golden / make coverage-golden
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden_io import GOLDEN_DIR

COVERAGE_GOLDEN_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "coverage" / "golden"

GOLDEN_DIRS = [
    pytest.param(GOLDEN_DIR, id="ladder_captures"),
    pytest.param(COVERAGE_GOLDEN_DIR, id="coverage"),
]


def _unverified(golden_dir: Path) -> list[str]:
    log = golden_dir / "verify_progress.log"
    csv_stems = sorted(p.stem for p in golden_dir.glob("*.csv"))
    assert csv_stems, f"No golden CSV files found in {golden_dir}"

    assert log.exists(), (
        f"verify_progress.log not found at {log}\nRun clicknick-rung guided to create it."
    )

    verified = set()
    for line in log.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, status = line.partition(":")
        if status.strip() == "worked":
            verified.add(name.strip())

    return sorted(set(csv_stems) - verified)


@pytest.mark.parametrize("golden_dir", GOLDEN_DIRS)
def test_all_goldens_verified(golden_dir: Path) -> None:
    unverified = _unverified(golden_dir)
    assert not unverified, (
        f"{len(unverified)} golden fixture(s) in {golden_dir} not yet verified in Click:\n"
        + "\n".join(f"  - {name}" for name in unverified)
        + f"\n\nRun clicknick-rung guided {golden_dir} to paste-verify, then re-run make test."
    )


def test_unverified_stem_is_reported(tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_text("")
    (tmp_path / "b.csv").write_text("")
    (tmp_path / "verify_progress.log").write_text("# note\n\na: worked\nb: failed\n")
    assert _unverified(tmp_path) == ["b"]
