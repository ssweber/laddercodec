"""List instructions in a PE's .text that reference [reg+DISP] for the given displacements.

Usage: python member_xref.py DLL HEXDISP[,HEXDISP...] [write]
With 'write', only show instructions whose first operand is the memory reference (stores).
Also prints the enclosing function start (nearest preceding 'push ebp; mov ebp, esp').
"""

from __future__ import annotations

import sys

import capstone
import pefile
from capstone import x86

path = sys.argv[1]
disps = {int(d, 16) for d in sys.argv[2].split(",")}
only_write = len(sys.argv) > 3 and sys.argv[3] == "write"
pe = pefile.PE(path)
text = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".text")
base = pe.OPTIONAL_HEADER.ImageBase + text.VirtualAddress
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = True
md.skipdata = True
insns = list(md.disasm(text.get_data(), base))
func = 0
for k, ins in enumerate(insns):
    if ins.id == 0:
        continue
    if ins.mnemonic == "push" and ins.op_str == "ebp" and k + 1 < len(insns) and insns[k + 1].op_str == "ebp, esp":
        func = ins.address
    for n, op in enumerate(ins.operands):
        if op.type == x86.X86_OP_MEM and op.mem.base not in (0, x86.X86_REG_EBP, x86.X86_REG_ESP):
            if (op.mem.disp & 0xFFFFFFFF) in disps:
                if only_write and n != 0:
                    continue
                if only_write and ins.mnemonic in ("cmp", "test", "push"):
                    continue
                print(f"fn {func:08x}  {ins.address:08x} {ins.mnemonic} {ins.op_str}")
                break
