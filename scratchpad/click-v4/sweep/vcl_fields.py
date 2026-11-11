"""Print Delphi/C++Builder published-field tables (offset -> field name) from a PE.

A VCL field table entry is: [u32 offset][u16 class index][shortstring name].
We scan for each DFM component name (as a shortstring) and read the 6 bytes before it.

Usage: python vcl_fields.py DLL NAME [NAME...]   (or NAME list from a dfm dump with --dfm FILE)
"""

from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

path = sys.argv[1]
args = sys.argv[2:]
names: list[str] = []
if args and args[0] == "--dfm":
    txt = Path(args[1]).read_text(encoding="utf-8", errors="replace")
    names = re.findall(r"^\s*object (\w+):", txt, re.M)
else:
    names = args
data = Path(path).read_bytes()
rows = []
for n in names:
    pat = bytes([len(n)]) + n.encode()
    for m in re.finditer(re.escape(pat), data):
        i = m.start()
        if i < 6:
            continue
        off, idx = struct.unpack_from("<IH", data, i - 6)
        if off < 0x10000:
            rows.append((off, idx, n))
for off, idx, n in sorted(set(rows)):
    print(f"+0x{off:03x}  cls#{idx:<3} {n}")
