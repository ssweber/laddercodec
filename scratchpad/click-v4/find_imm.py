"""Count 32-bit little-endian immediates (tag IDs) in PE files.

Usage: uv run --no-project python scratchpad/click-v4/find_imm.py HEXTAG[,HEXTAG...] FILE...
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

tags = [int(t, 16) for t in sys.argv[1].split(",")]
for f in sys.argv[2:]:
    data = Path(f).read_bytes()
    hits = {f"{t:04x}": data.count(struct.pack("<I", t)) for t in tags}
    if any(hits.values()):
        print(Path(f).name, hits)
