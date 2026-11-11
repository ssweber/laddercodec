"""Print doubles (and float) at VAs in a PE.

Usage: python dump_doubles.py DLL HEXVA[,HEXVA...] [f]   (f = read as float32)
"""

from __future__ import annotations

import struct
import sys

import pefile

pe = pefile.PE(sys.argv[1])
as_float = len(sys.argv) > 3 and sys.argv[3] == "f"
for v in sys.argv[2].split(","):
    va = int(v, 16)
    n = 4 if as_float else 8
    data = pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)
    val = struct.unpack("<f" if as_float else "<d", data)[0]
    print(f"{va:08x} {val!r}")
