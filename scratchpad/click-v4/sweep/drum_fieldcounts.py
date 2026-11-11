"""Print field count, base (0x2200) and func codes of every Drum blob in capture files.

Usage: uv run --no-project python drum_fieldcounts.py FILE.bin [...]
Scans for the UTF-16LE "Drum" class name; reads type marker, part count, pin bytes, field count.
"""

from __future__ import annotations

import struct
import sys

NEEDLE = "Drum".encode("utf-16-le") + b"\x00\x00"

for path in sys.argv[1:]:
    buf = open(path, "rb").read()
    i = -1
    while (i := buf.find(NEEDLE, i + 1)) != -1:
        p = i + len(NEEDLE)
        marker = struct.unpack_from("<I", buf, p)[0]
        parts = struct.unpack_from("<H", buf, p + 4)[0]
        pins = buf[p + 6 : p + 6 + parts - 1]
        count = struct.unpack_from("<I", buf, p + 6 + parts - 1)[0]
        window = buf[p : p + 6000]
        has_428a = struct.pack("<H", 0x428A) in window
        print(f"{path} @{i:#x} marker={marker:#x} parts={parts} pins={list(pins)} fields={count} 428a_tag_bytes_present={has_428a}")
