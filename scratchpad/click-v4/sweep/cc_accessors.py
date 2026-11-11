"""List every `push TAG; push ACCESSOR` pair (ACCESSOR in 0x7d0..0x7ff) in a 32-bit PE.

Usage: uv run --no-project --with pefile --with capstone python cc_accessors.py DLL [BEFORE] [AFTER]
Prints tag, accessor, address, then BEFORE/AFTER instructions of context.
"""

from __future__ import annotations

import sys

import capstone
import pefile
from capstone import x86

path = sys.argv[1]
before = int(sys.argv[2]) if len(sys.argv) > 2 else 0
after = int(sys.argv[3]) if len(sys.argv) > 3 else 0

pe = pefile.PE(path)
text = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".text")
base = pe.OPTIONAL_HEADER.ImageBase + text.VirtualAddress
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = True
md.skipdata = True
insns = list(md.disasm(text.get_data(), base))


def imm(ins) -> int | None:
    if ins.id == 0:
        return None
    for op in ins.operands:
        if op.type == x86.X86_OP_IMM:
            return op.imm & 0xFFFFFFFF
    return None


for k in range(1, len(insns)):
    b = insns[k]
    if b.mnemonic != "push":
        continue
    acc = imm(b)
    if acc is None or not (0x7D0 <= acc <= 0x7FF):
        continue
    # previous push (skipping up to 3 non-push instructions) carries the tag
    tag = None
    a = None
    for j in range(k - 1, max(0, k - 5), -1):
        if insns[j].mnemonic == "push":
            a = insns[j]
            tag = imm(a)
            break
    if tag is None or a is None:
        print(f"TAG ???? ACC {acc:03x} @ {b.address:08x} (tag not immediate)")
        continue
    print(f"TAG {tag:04x} ACC {acc:03x} @ {a.address:08x}")
    if before or after:
        for j in range(max(0, k - 1 - before), min(len(insns), k + 1 + after)):
            i = insns[j]
            mark = ">>" if j in (k - 1, k) else "  "
            print(f"  {mark} {i.address:08x} {i.mnemonic} {i.op_str}")
