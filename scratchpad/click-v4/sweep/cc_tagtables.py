"""Find u16 tag tables in InstCtl_*.dll: `movzx r, word ptr [reg*2 + TABLE]` preceded by `cmp reg, N`.

Usage: uv run --no-project --with pefile --with capstone python cc_tagtables.py DLL...
Prints each table address, the bound N from the nearest preceding cmp, and the u16 entries.
"""

from __future__ import annotations

import struct
import sys

import capstone
import pefile
from capstone import x86

for path in sys.argv[1:]:
    pe = pefile.PE(path)
    ib = pe.OPTIONAL_HEADER.ImageBase
    text = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".text")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    md.skipdata = True
    insns = list(md.disasm(text.get_data(), ib + text.VirtualAddress))
    print(f"######## {path.rsplit('/', 1)[-1]}")
    seen: set[int] = set()
    for k, ins in enumerate(insns):
        if ins.id == 0 or ins.mnemonic not in ("movzx", "mov"):
            continue
        for op in ins.operands:
            if op.type == x86.X86_OP_MEM and op.mem.scale == 2 and op.mem.base == 0 and op.size == 2:
                tbl = op.mem.disp & 0xFFFFFFFF
                n = None
                for j in range(k - 1, max(0, k - 8), -1):
                    p = insns[j]
                    if p.id and p.mnemonic == "cmp" and len(p.operands) == 2 and p.operands[1].type == x86.X86_OP_IMM:
                        n = p.operands[1].imm
                        break
                key = tbl
                if key in seen:
                    continue
                seen.add(key)
                cnt = n if n and n < 64 else 16
                data = pe.get_data(tbl - ib, cnt * 2)
                vals = struct.unpack(f"<{cnt}H", data)
                print(f"  table {tbl:08x} n={n} @ {ins.address:08x}: " + " ".join(f"{v:04x}" for v in vals))
