"""Dump N little-endian u16 values at a VA in a PE image.

Usage: uv run --no-project --with pefile python u16tab.py DLL VAHEX N
"""

from __future__ import annotations

import struct
import sys

import pefile

pe = pefile.PE(sys.argv[1])
ib = pe.OPTIONAL_HEADER.ImageBase
mm = pe.get_memory_mapped_image()
va = int(sys.argv[2], 16)
n = int(sys.argv[3])
vals = struct.unpack_from(f"<{n}H", mm, va - ib)
print(" ".join(f"{v:04x}" for v in vals))
