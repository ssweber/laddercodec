"""Print rungs of a bin or CSV compactly.  Usage: show.py <file> <index> [<index> ...]"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from laddercodec import decode, read_csv  # noqa: E402

import oracle_show  # noqa: E402

path = Path(sys.argv[1])
rungs = read_csv(path) if path.suffix == ".csv" else decode(path.read_bytes())
rungs = rungs if isinstance(rungs, list) else [rungs]
for i in map(int, sys.argv[2:]):
    print(f"--- {path.name} rung {i}: {rungs[i].comment!r}"[:120])
    print("\n".join(oracle_show.show(rungs[i])))
