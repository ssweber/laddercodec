"""Dump a VA range of a DLL as rows of four u32 values.

Usage: uv run --no-project --with pefile python dump_u32.py DLL START END
"""

from __future__ import annotations

import struct
import sys

import pefile

pe = pefile.PE(sys.argv[1])
ib = pe.OPTIONAL_HEADER.ImageBase
start, end = (int(x, 16) for x in sys.argv[2:4])
data = pe.get_data(start - ib, end - start)
for off in range(0, len(data), 16):
    vals = struct.unpack("<4I", data[off : off + 16].ljust(16, b"\0"))
    print(f"{start + off:08x}: " + " ".join(f"{v:6d}" if v < 100000 else f"{v:08x}" for v in vals))
