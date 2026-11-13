"""What canonical layout would do to every CSV fixture: rungs that are fixed points, rungs
whose layout changes (their .bin would change in phase 2, and a canonical write_csv would
write a different CSV), and rungs the layout refuses.

Run from the layout worktree: uv run --no-sync python ../buildbot/jobs/layout/golden_impact.py
Writes golden_impact.txt beside this script.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import laddercodec
from laddercodec import read_csv  # noqa: E402
from laddercodec._layout import LayoutError, layout  # noqa: E402

from oracle_show import show, sig  # noqa: E402

JOB = Path(__file__).parent
FIX = Path(laddercodec.__file__).resolve().parents[2] / "tests" / "fixtures"  # the checkout it runs in

groups = {
    "ladder_captures/golden": sorted((FIX / "ladder_captures" / "golden").glob("*.csv")),
    "coverage/golden": sorted((FIX / "coverage" / "golden").glob("*.csv")),
    "coverage/subroutines": sorted((FIX / "coverage" / "subroutines").glob("*.csv")),
    "pinned_or": sorted((FIX / "pinned_or").glob("*.csv")),
    "v4_captures stubs": sorted((FIX / "v4_captures").glob("*.csv")),
    "scr_captures csv (decoded native)": sorted((FIX / "scr_captures").glob("*.csv")),
    "tumbler clipboard csv (decoded native)": sorted(
        [FIX / "tumbler" / "main.clipboard.csv", *(FIX / "tumbler" / "subroutines").glob("*.clipboard.csv")]
    ),
    "tumbler scr csv (decoded native)": sorted(
        [FIX / "tumbler" / "main.csv", *(p for p in (FIX / "tumbler" / "subroutines").glob("*.csv") if ".clipboard" not in p.name)]
    ),
}

lines: list[str] = []
summary: list[str] = []
for group, paths in groups.items():
    c: Counter = Counter()
    detail: list[str] = []
    for path in paths:
        try:
            rungs = read_csv(path)
        except Exception as exc:  # noqa: BLE001
            c["unreadable files"] += 1
            detail.append(f"--- {path.name}: read_csv failed: {exc}")
            continue
        c["files"] += 1
        file_changed = False
        for i, rung in enumerate(rungs):
            c["rungs"] += 1
            try:
                got = layout(rung)
            except (LayoutError, ValueError) as exc:
                c["refused"] += 1
                file_changed = True
                detail.append(f"--- {path.name} rung {i}: REFUSED ({getattr(exc, 'code', None)}): {exc}")
                detail.extend(show(rung))
                continue
            if [sig(g) for g in got] == [sig(rung)]:
                c["fixed"] += 1
                continue
            c["changed"] += 1
            if len(got) > 1:
                c["split"] += 1
            file_changed = True
            detail.append(f"--- {path.name} rung {i}: CHANGED ({len(got)} rung(s))")
            detail.extend(show(rung))
            detail.append("  ->")
            for g in got:
                detail.extend(show(g))
        c["files changed"] += int(file_changed)
    summary.append(
        f"{group}: {c['files']} files, {c['rungs']} rungs: {c['fixed']} fixed, {c['changed']} changed "
        f"({c['split']} split), {c['refused']} refused; {c['files changed']} files change"
        + (f"; {c['unreadable files']} unreadable" if c["unreadable files"] else "")
    )
    lines.append(f"===== {group}")
    lines.extend(detail)
(JOB / "golden_impact.txt").write_text("\n".join(["# Golden impact", "", *summary, "", *lines]) + "\n", encoding="utf-8")
print("\n".join(summary))
