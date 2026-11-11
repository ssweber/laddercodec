"""Scan native clipboard .bin captures for instruction blobs of given classes.

Usage: uv run python scratchpad/click-v4/sweep/scan_blobs.py CLASS[,CLASS] FILE...
Prints each distinct (class, tag/sentinel/value list) once with the files it occurs in.
"""

from __future__ import annotations

import gzip
import struct
import sys
from collections import defaultdict
from pathlib import Path

from laddercodec.binary_helpers import _parse_tagged_fields_verbose

classes = sys.argv[1].split(",")
seen: dict[tuple, set[str]] = defaultdict(set)
for f in sys.argv[2:]:
    p = Path(f)
    data = p.read_bytes()
    if p.suffix == ".gz":
        data = gzip.decompress(data)
    for cls in classes:
        needle = (cls + "\0").encode("utf-16le")
        start = 0
        while True:
            i = data.find(needle, start)
            if i < 0:
                break
            start = i + 2
            # require preceding byte pair not to be a letter (avoid suffix matches)
            if i >= 2 and data[i - 2 : i] != b"\0\0" and 0x41 <= data[i - 2] <= 0x7A and data[i - 1] == 0:
                continue
            pos = i + len(needle)
            if pos + 10 > len(data):
                continue
            tm = struct.unpack_from("<I", data, pos)[0]
            if tm >> 8 != 0x27:
                continue
            pos += 4
            parts = struct.unpack_from("<H", data, pos)[0]
            pos += 2 + max(parts - 1, 0)
            extra = data[i + len(needle) + 6 : pos].hex()
            n = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            if n > 64:
                continue
            fields, _ = _parse_tagged_fields_verbose(data, pos, n)
            key = (
                cls,
                hex(tm),
                parts,
                tuple(
                    (f"{t:04x}", s.hex() if s != b"\xff\xff\xff\xff" else "", v) for t, s, v in fields
                ),
            )
            seen[key].add(p.name)

for key, files in sorted(seen.items(), key=lambda kv: kv[0][:2]):
    cls, tm, parts, fields = key
    fs = " ".join(f"{t}{'[' + s + ']' if s else ''}={v!r}" for t, s, v in fields)
    print(f"{cls} {tm} parts={parts}: {fs}")
    print(f"    in: {', '.join(sorted(files))[:200]}")
