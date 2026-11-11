"""Disassemble an address range of a 32-bit PE, annotating imports and string refs.

Usage: uv run --no-project --with pefile --with capstone python dis.py DLL STARTHEX ENDHEX
"""

from __future__ import annotations

import sys

import capstone
import pefile
from capstone import x86

path = sys.argv[1]
start = int(sys.argv[2], 16)
end = int(sys.argv[3], 16)

pe = pefile.PE(path)
ib = pe.OPTIONAL_HEADER.ImageBase
imports: dict[int, str] = {}
for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
    for imp in entry.imports:
        name = imp.name.decode() if imp.name else f"ord{imp.ordinal}"
        imports[imp.address] = f"{entry.dll.decode()}!{name}"

mm = pe.get_memory_mapped_image()


def read_str(va: int) -> str | None:
    off = va - ib
    if not (0 <= off < len(mm) - 2):
        return None
    # try UTF-16LE
    raw = mm[off : off + 200]
    try:
        u = raw.decode("utf-16le", errors="strict")
        u = u.split("\0", 1)[0]
        if len(u) >= 2 and all(32 <= ord(c) < 0x3000 for c in u):
            return "L" + repr(u)
    except UnicodeDecodeError:
        pass
    a = raw.split(b"\0", 1)[0]
    if len(a) >= 3 and all(32 <= c < 127 for c in a):
        return repr(a.decode())
    return None


text = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".text")
tbase = ib + text.VirtualAddress
code = text.get_data()
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = True
md.skipdata = True
for ins in md.disasm(code[start - tbase : end - tbase], start):
    note = ""
    if ins.id != 0:
        for op in ins.operands:
            if op.type == x86.X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
                a = op.mem.disp & 0xFFFFFFFF
                if a in imports:
                    note = "  ; " + imports[a]
            elif op.type == x86.X86_OP_IMM:
                a = op.imm & 0xFFFFFFFF
                if a in imports:
                    note = "  ; " + imports[a]
                elif ib <= a < ib + 0x200000:
                    s = read_str(a)
                    if s:
                        note = "  ; " + s
    print(f"{ins.address:08x} {ins.mnemonic} {ins.op_str}{note}")
