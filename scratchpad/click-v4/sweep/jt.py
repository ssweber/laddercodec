"""Resolve a tag-switch jump table to per-tag call targets.

Usage: uv run --no-project --with pefile --with capstone python jt.py DLL BASE_TAG COUNT PTR_TABLE [IDX_TABLE]
(all hex).  With IDX_TABLE: target = ptrs[idx[tag-BASE]]; else ptrs[tag-BASE].
Prints tag -> case block -> first call target in the block (or the block's first instrs).
"""

from __future__ import annotations

import struct
import sys

import capstone
import pefile

pe = pefile.PE(sys.argv[1])
ib = pe.OPTIONAL_HEADER.ImageBase
base, count, ptrs = (int(x, 16) for x in sys.argv[2:5])
idx = int(sys.argv[5], 16) if len(sys.argv) > 5 else None
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)


def rd(va: int, n: int) -> bytes:
    return pe.get_data(va - ib, n)


default = None
if idx is not None:
    idxs = list(rd(idx, count))
    default = max(idxs)
for i in range(count):
    k = idxs[i] if idx is not None else i
    if idx is not None and k == default and idxs.count(k) > 3:
        continue
    blk = struct.unpack("<I", rd(ptrs + 4 * k, 4))[0]
    code = rd(blk, 48)
    desc = []
    for ins in md.disasm(code, blk):
        desc.append(f"{ins.mnemonic} {ins.op_str}")
        if ins.mnemonic in ("call", "jmp", "ret"):
            break
    print(f"{base + i:04x} -> {blk:08x}: " + "; ".join(desc[-3:]))
