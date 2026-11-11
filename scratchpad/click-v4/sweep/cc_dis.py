"""Disassemble an address range of a 32-bit PE, annotating string refs in .rdata.

Usage: uv run --no-project --with pefile --with capstone python cc_dis.py DLL STARTHEX ENDHEX
Immediates/displacements that point at a printable ASCII or UTF-16LE string get a ; "..." comment.
Calls through IAT slots get the imported name.
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
        nm = imp.name.decode() if imp.name else f"ord{imp.ordinal}"
        imports[imp.address] = f"{entry.dll.decode()}!{nm}"


def read_str(va: int) -> str | None:
    try:
        rva = va - ib
        data = pe.get_data(rva, 200)
    except Exception:
        return None
    # utf-16le
    if len(data) >= 4 and data[1] == 0 and 32 <= data[0] < 127:
        out = []
        for i in range(0, len(data) - 1, 2):
            c = data[i] | (data[i + 1] << 8)
            if c == 0:
                break
            if c < 32 or c > 0x7E:
                return None
            out.append(chr(c))
        if len(out) >= 1:
            return 'L"' + "".join(out) + '"'
    out = []
    for b in data:
        if b == 0:
            break
        if b < 32 or b > 0x7E:
            return None
        out.append(chr(b))
    if len(out) >= 2:
        return '"' + "".join(out) + '"'
    return None


text = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".text")
tbase = ib + text.VirtualAddress
code = text.get_data()
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = True
md.skipdata = True
off = start - tbase
for ins in md.disasm(code[off : end - tbase], start):
    note = ""
    if ins.id != 0:
        for op in ins.operands:
            v = None
            if op.type == x86.X86_OP_IMM:
                v = op.imm & 0xFFFFFFFF
            elif op.type == x86.X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
                v = op.mem.disp & 0xFFFFFFFF
                if v in imports:
                    note += f" ; {imports[v]}"
                    continue
            if v is not None and v > ib:
                s = read_str(v)
                if s:
                    note += f" ; {s}"
    print(f"{ins.address:08x} {ins.mnemonic} {ins.op_str}{note}")
