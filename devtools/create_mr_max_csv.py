"""One-time script to create mr-cmt-2rung-r1-max1400 golden CSV."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from golden_io import GOLDEN_DIR, Rung, write_multi_rung_golden_csv

from laddercodec.instructions import ConditionToken

# 1400-byte comment body: "ABCDEFGHIJ" x 140
comment_text = "ABCDEFGHIJ" * 140
assert len(comment_text.encode("cp1252")) == 1400
blank_row = cast(list[ConditionToken], [""] * 31)

# 2 rungs, each 1 row, empty cells, no AF
rungs: list[Rung] = [
    Rung(1, [blank_row.copy()], [""], None),  # rung 0: 1 row, no comment
    Rung(1, [blank_row.copy()], [""], comment_text),  # rung 1: 1 row, max comment
]

csv_path = GOLDEN_DIR / "mr-cmt-2rung-r1-max1400.csv"
write_multi_rung_golden_csv(csv_path, rungs)
print(f"Created {csv_path.name} ({csv_path.stat().st_size} bytes)")
