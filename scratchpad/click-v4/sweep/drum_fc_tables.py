"""Dump the InstCtl_Drum func-code byte-index table used at 0x10006bb0 (codes 8458..8494).

Usage: uv run --no-project --with pefile python drum_fc_tables.py DLL
"""

from __future__ import annotations

import struct
import sys

import pefile

pe = pefile.PE(sys.argv[1])
ib = pe.OPTIONAL_HEADER.ImageBase


def rd(va: int, n: int) -> bytes:
    return pe.get_data(va - ib, n)


ptrs = struct.unpack("<2I", rd(0x10006BE4, 8))
idx = rd(0x10006BEC, 0x25)
print("ptrs", [hex(p) for p in ptrs])
for i, k in enumerate(idx):
    print(8458 + i, k, "TRUE" if ptrs[k] == 0x10006BD5 else "false")
