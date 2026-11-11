"""Dump tagged fields of every <ClassName> blob found in clipboard .bin / scr files.

Usage: uv run python scratchpad/click-v4/sweep/dump_blobs.py ClassName FILE...
Prints tag=value for each header field (skips empty indexed slots of Math).
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from laddercodec.binary_helpers import _parse_tagged_fields_verbose

cls = sys.argv[1]
needle = (cls + "\0").encode("utf-16-le")
for f in sys.argv[2:]:
    raw = Path(f).read_bytes()
    pos = 0
    while True:
        i = raw.find(needle, pos)
        if i < 0:
            break
        pos = i + 2
        j = i + len(needle)
        if j + 10 > len(raw):
            break
        typ = struct.unpack_from("<I", raw, j)[0]
        parts = struct.unpack_from("<H", raw, j + 4)[0]
        count = struct.unpack_from("<I", raw, j + 6)[0]
        if count > 20000 or typ < 0x2700 or typ > 0x2800:
            continue
        fields, _end = _parse_tagged_fields_verbose(raw, j + 10, count)
        shown = []
        for tag, sent, val in fields:
            if sent != b"\xff\xff\xff\xff":
                if not val:
                    continue
                shown.append(f"{tag:04x}[{sent.hex()}]={val!r}")
            else:
                shown.append(f"{tag:04x}={val!r}")
        print(f"{Path(f).name} @0x{i:x} type=0x{typ:x} parts={parts} n={count}")
        print("   " + "  ".join(shown))
