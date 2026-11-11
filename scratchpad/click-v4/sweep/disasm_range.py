"""Disassemble an address range of a 32-bit PE (.text), annotating string refs.

Usage: python disasm_range.py DLL HEXSTART HEXEND
Pushes/movs of addresses inside .rdata/.data that point to UTF-16 or ASCII strings get the
string printed alongside.  Calls through the IAT get the imported name.
"""

from __future__ import annotations

import sys

import capstone
import pefile
from capstone import x86

path, start, end = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3], 16)
pe = pefile.PE(path)
base = pe.OPTIONAL_HEADER.ImageBase

imports: dict[int, str] = {}
if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
    for entry in pe.DIRECTORY_ENTRY_IMPORT:
        for imp in entry.imports:
            name = imp.name.decode() if imp.name else f"{entry.dll.decode()}#{imp.ordinal}"
            imports[imp.address] = name


def read_str(va: int) -> str | None:
    try:
        rva = va - base
        data = pe.get_data(rva, 200)
    except Exception:
        return None
    # utf-16
    if len(data) >= 4 and data[1] == 0 and 32 <= data[0] < 127:
        s = []
        for i in range(0, len(data) - 1, 2):
            c = data[i] | (data[i + 1] << 8)
            if c == 0:
                break
            if c < 32 or c > 0x7E:
                return None
            s.append(chr(c))
        if len(s) >= 1:
            return 'L"' + "".join(s) + '"'
    s2 = []
    for b in data:
        if b == 0:
            break
        if b < 32 or b > 126:
            return None
        s2.append(chr(b))
    if len(s2) >= 2:
        return '"' + "".join(s2) + '"'
    return None


text = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".text")
tbase = base + text.VirtualAddress
code = text.get_data()
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = True
md.skipdata = True
off = start - tbase
for ins in md.disasm(code[off : end - tbase], start):
    note = ""
    if ins.id != 0:
        for op in ins.operands:
            if op.type == x86.X86_OP_IMM:
                v = op.imm & 0xFFFFFFFF
                if v > base:
                    s = read_str(v)
                    if s:
                        note = f"   ; {s}"
            elif op.type == x86.X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
                v = op.mem.disp & 0xFFFFFFFF
                if v in imports:
                    note = f"   ; {imports[v]}"
                else:
                    s = read_str(v)
                    if s:
                        note = f"   ; {s}"
    print(f"{ins.address:08x} {ins.mnemonic} {ins.op_str}{note}")
