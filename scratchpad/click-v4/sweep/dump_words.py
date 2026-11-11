"""Dump u16 words at a VA in a PE (hex), e.g. an InstCtl tag table.

Usage: python dump_words.py DLL HEXVA COUNT
"""

from __future__ import annotations

import struct
import sys

import pefile

pe = pefile.PE(sys.argv[1])
va, n = int(sys.argv[2], 16), int(sys.argv[3])
data = pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n * 2)
print(" ".join(f"{w:04x}" for w in struct.unpack(f"<{n}H", data)))
