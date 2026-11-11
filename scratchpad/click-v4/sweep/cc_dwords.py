"""Dump N little-endian dwords (or u16 with --u16) at a VA of a PE.

Usage: uv run --no-project --with pefile python cc_dwords.py DLL VAHEX N [--u16]
"""

from __future__ import annotations

import struct
import sys

import pefile

pe = pefile.PE(sys.argv[1])
va = int(sys.argv[2], 16)
n = int(sys.argv[3])
u16 = "--u16" in sys.argv
size = 2 if u16 else 4
data = pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n * size)
vals = struct.unpack(f"<{n}{'H' if u16 else 'I'}", data)
print(" ".join(f"{v:0{size * 2}x}" for v in vals))
