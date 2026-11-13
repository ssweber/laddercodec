"""Find native rungs whose Or merge net also feeds rows below its last leg (one vertical or two).

Run from the layout worktree: uv run --no-sync python ../buildbot/jobs/layout/merge_extent.py
"""

from __future__ import annotations

import gzip
from collections import defaultdict
from pathlib import Path

import laddercodec
from laddercodec import decode, read_csv
from laddercodec._layout import network_of_rung

JOB = Path(__file__).parent
FIX = Path(laddercodec.__file__).resolve().parents[2] / "tests" / "fixtures"  # the checkout it runs in
LT = Path("C:/Users/Sam/Documents/GitHub/laddercodec-wt/buildbot/jobs/layoutthy")  # layoutthy captures
PY = Path("C:/Users/Sam/Documents/GitHub/pyrung/tests/click/ladder_topology_golden")


def as_list(x):
    return x if isinstance(x, list) else [x]


def report(name: str, rungs: list) -> None:
    for i, r in enumerate(rungs):
        try:
            net = network_of_rung(r)
        except Exception:
            continue
        ins = defaultdict(list)
        outs = defaultdict(list)
        for e in net.edges:
            ins[e.dst].append(e.row)
            outs[e.src].append(e.row)
        for s in net.sinks:
            outs[s.net].append(s.row)
        for n, rows in ins.items():
            if len(rows) < 2 or len(outs[n]) < 2:
                continue
            if max(outs[n]) > max(rows):
                # count verticals: columns with a down flag on this net
                print(f"{name} rung {i}: merge legs rows {sorted(rows)}, fed rows {sorted(outs[n])}, from rail={n == net.rail}")


srcs = {
    "tumbler": [FIX / "tumbler" / "main.clipboard.bin", *sorted((FIX / "tumbler" / "subroutines").glob("*.clipboard.bin"))],
}
for p in srcs["tumbler"]:
    report(p.name, as_list(decode(p.read_bytes())))
for stem in ("coverage", "counter_scr", "or_topology", "shift_scr"):
    report(stem, as_list(decode((FIX / "scr_captures" / f"{stem}.bin").read_bytes())))
report("rungs_266", as_list(decode(gzip.decompress((FIX / "scr_captures" / "rungs_266.bin.gz").read_bytes()))))
report("layoutthy-checked", as_list(decode((LT / "layoutthy-checked.bin").read_bytes())))
report("pyrung main", read_csv(PY / "main.csv"))
