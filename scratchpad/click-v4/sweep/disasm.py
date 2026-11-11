"""Full annotated disassembly of a 32-bit PE .text (imports, ordinal MFC names, strings).

Usage: uv run --no-project --with pefile --with capstone python disasm.py DLL OUT.asm
Annotates: call [IAT] -> import name; push imm pointing at .rdata/.data UTF-16/ASCII string.
Also prints a tag-call index: (addr, TAG, CODE) for push TAG; push CODE pairs.
"""

from __future__ import annotations

import sys

import capstone
import pefile
from capstone import x86

path, out = sys.argv[1], sys.argv[2]
pe = pefile.PE(path)
ib = pe.OPTIONAL_HEADER.ImageBase
imports: dict[int, str] = {}
for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
    for i in e.imports:
        nm = i.name.decode() if i.name else f"ord{i.ordinal}"
        imports[i.address] = f"{e.dll.decode()}!{nm}"


def read_str(va: int) -> str | None:
    try:
        rva = va - ib
        data = pe.get_data(rva, 200)
    except Exception:
        return None
    # utf-16
    if len(data) > 4 and data[1] == 0 and 32 <= data[0] < 127:
        s = []
        for k in range(0, len(data) - 1, 2):
            c = data[k] | (data[k + 1] << 8)
            if c == 0:
                break
            if c < 32 or c > 0xFFFF:
                return None
            s.append(chr(c))
        if len(s) >= 2:
            return "L" + repr("".join(s))
    s = []
    for b in data:
        if b == 0:
            break
        if b < 32 or b > 126:
            return None
        s.append(chr(b))
    if len(s) >= 3:
        return repr("".join(s))
    return None


text = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".text")
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = True
md.skipdata = True
insns = list(md.disasm(text.get_data(), ib + text.VirtualAddress))
lo_s, hi_s = ib + text.VirtualAddress, ib + text.VirtualAddress + text.Misc_VirtualSize
with open(out, "w", encoding="utf-8") as f:
    for ins in insns:
        note = ""
        if ins.id:
            for op in ins.operands:
                if op.type == x86.X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
                    if op.mem.disp & 0xFFFFFFFF in imports:
                        note = imports[op.mem.disp & 0xFFFFFFFF]
                elif op.type == x86.X86_OP_IMM:
                    v = op.imm & 0xFFFFFFFF
                    if ib <= v < ib + pe.OPTIONAL_HEADER.SizeOfImage and not (lo_s <= v < hi_s):
                        s = read_str(v)
                        if s:
                            note = s
        if ins.mnemonic in ("ret", "retn") or ins.mnemonic.startswith("ret"):
            note = (note + " ---------").strip()
        f.write(f"{ins.address:08x} {ins.mnemonic} {ins.op_str}{'   ; ' + note if note else ''}\n")
