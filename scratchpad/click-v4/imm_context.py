"""Disassemble a 32-bit PE and print context around immediates (tag IDs / control IDs).

Usage: uv run --no-project --with pefile --with capstone python imm_context.py DLL LO-HI[,LO-HI] [BEFORE] [AFTER]
Ranges are hex, inclusive.  Prints each instruction whose immediate falls in a range,
with BEFORE/AFTER instructions of context.
"""

from __future__ import annotations

import sys

import capstone
import pefile
from capstone import x86

path = sys.argv[1]
ranges = []
for r in sys.argv[2].split(","):
    lo, _, hi = r.partition("-")
    ranges.append((int(lo, 16), int(hi or lo, 16)))
before = int(sys.argv[3]) if len(sys.argv) > 3 else 3
after = int(sys.argv[4]) if len(sys.argv) > 4 else 3

pe = pefile.PE(path)
text = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".text")
base = pe.OPTIONAL_HEADER.ImageBase + text.VirtualAddress
code = text.get_data()

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = True
md.skipdata = True
insns = list(md.disasm(code, base))


def hit(ins) -> int | None:
    if ins.id == 0:  # skipdata pseudo-instruction
        return None
    for op in ins.operands:
        if op.type == x86.X86_OP_IMM:
            v = op.imm & 0xFFFFFFFF
            if any(lo <= v <= hi for lo, hi in ranges):
                return v
    return None


last = -1
for k, ins in enumerate(insns):
    v = hit(ins)
    if v is None:
        continue
    lo = max(k - before, last + 1)
    if lo > last + 1:
        print("  ...")
    for j in range(lo, min(k + after + 1, len(insns))):
        m = insns[j]
        mark = ">>" if j == k else "  "
        print(f"{mark} {m.address:08x} {m.mnemonic} {m.op_str}")
    last = min(k + after, len(insns) - 1)
