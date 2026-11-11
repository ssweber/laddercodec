"""Survey native Copy blobs: (copy_type, src kind, dst kind, 2206, 2227, 1221, 3216, 1201) counts.

Usage: uv run python scratchpad/click-v4/sweep/copy_survey.py FILE...
"""

from __future__ import annotations

import re
import struct
import sys
from collections import Counter
from pathlib import Path

from laddercodec.binary_helpers import _parse_tagged_fields_verbose

needle = "Copy\0".encode("utf-16-le")


def kind(s: str) -> str:
    if not s:
        return "-"
    if s.startswith('"'):
        return "str"
    if s.startswith("$"):
        return "$hh"
    m = re.match(r"[A-Z]+", s)
    if m:
        return m.group(0)
    return "num"


c: Counter = Counter()
ex: dict = {}
for f in sys.argv[1:]:
    raw = Path(f).read_bytes()
    pos = 0
    while (i := raw.find(needle, pos)) >= 0:
        pos = i + 2
        j = i + len(needle)
        if j + 10 > len(raw):
            break
        typ, = struct.unpack_from("<I", raw, j)
        count, = struct.unpack_from("<I", raw, j + 6)
        if typ != 0x2721 or count > 100:
            continue
        fields, _ = _parse_tagged_fields_verbose(raw, j + 10, count)
        t = {tag: v for tag, _s, v in fields}
        key = (
            t.get(0x2223), kind(t.get(0x6074, "")), kind(t.get(0x6076, "")),
            t.get(0x2206), t.get(0x2227), t.get(0x1221), t.get(0x3216), t.get(0x1201),
        )
        c[key] += 1
        ex.setdefault(key, f"{Path(f).parent.name}/{Path(f).name}: {t.get(0x6074)}->{t.get(0x6076)}")
print("type src dst 2206 2227 1221 3216 1201 : count  example")
for k, n in sorted(c.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
    print(" ".join(str(x) for x in k), ":", n, " ", ex[k])
