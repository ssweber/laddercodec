"""Find InstCtl property-tag tables: `cmp eax, N; jae ..; movzx ecx, word ptr [eax*2 + TABLE]`.

Usage: uv run --no-project --with pefile --with capstone python prop_table.py DLL
Prints each table (count, address) and the tag words in order.
"""

from __future__ import annotations

import re
import sys

import capstone
import pefile

pe = pefile.PE(sys.argv[1])
ib = pe.OPTIONAL_HEADER.ImageBase
text = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".text")
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.skipdata = True
insns = list(md.disasm(text.get_data(), ib + text.VirtualAddress))
pat = re.compile(r"word ptr \[(\w+)\*2 \+ (0x[0-9a-f]+)\]")
for k, ins in enumerate(insns):
    if ins.mnemonic != "movzx":
        continue
    m = pat.search(ins.op_str)
    if not m:
        continue
    table = int(m.group(2), 16)
    count = None
    for j in range(k - 1, max(k - 6, 0), -1):
        p = insns[j]
        if p.mnemonic == "cmp" and p.op_str.startswith(("eax", "ecx", "edx", "esi", "edi", "ebx")):
            try:
                count = int(p.op_str.split(",")[1], 0)
            except ValueError:
                pass
            break
    if not count or count > 2000:
        continue
    data = pe.get_data(table - ib, count * 2)
    words = [int.from_bytes(data[i : i + 2], "little") for i in range(0, len(data), 2)]
    print(f"table @{table:08x} count={count} (use @{ins.address:08x})")
    print("  " + " ".join(f"{w:04x}" for w in words))
