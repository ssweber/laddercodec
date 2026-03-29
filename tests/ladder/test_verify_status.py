"""Ensure every golden CSV has been verified through Click paste round-trip.

Reads verify_progress.log and checks that every .csv stem in the golden
directory has a corresponding ": worked" entry. Fails with a clear list
of unverified fixtures if any are missing.

To verify fixtures:  clicknick-rung guided tests/fixtures/ladder_captures/golden
To regenerate bins:  make golden
"""

from __future__ import annotations

from tests.golden_io import GOLDEN_DIR

LOG = GOLDEN_DIR / "verify_progress.log"


def test_all_goldens_verified() -> None:
    csv_stems = sorted(p.stem for p in GOLDEN_DIR.glob("*.csv"))
    assert csv_stems, "No golden CSV files found"

    assert LOG.exists(), (
        f"verify_progress.log not found at {LOG}\nRun clicknick-rung guided to create it."
    )

    verified = set()
    for line in LOG.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, status = line.partition(":")
        if status.strip() == "worked":
            verified.add(name.strip())

    unverified = sorted(set(csv_stems) - verified)
    assert not unverified, (
        f"{len(unverified)} golden fixture(s) not yet verified in Click:\n"
        + "\n".join(f"  - {name}" for name in unverified)
        + "\n\nRun clicknick-rung guided to paste-verify, then re-run make test."
    )
