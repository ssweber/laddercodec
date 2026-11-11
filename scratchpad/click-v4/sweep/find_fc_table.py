"""Search DLL images for u16/u32 occurrences of drum func codes (8455.., 10503..).

Usage: uv run --no-project --with pefile python find_fc_table.py DLL [DLL...]
"""

from __future__ import annotations

import struct
import sys

import pefile

CODES = [8455, 8458, 8476, 8479, 8480, 8484, 8491, 8494, 10503, 10506, 10524, 10527, 10528, 10532]

for path in sys.argv[1:]:
    pe = pefile.PE(path)
    ib = pe.OPTIONAL_HEADER.ImageBase
    print("==", path)
    for s in pe.sections:
        name = s.Name.rstrip(b"\0").decode()
        data = s.get_data()
        base = ib + s.VirtualAddress
        for code in CODES:
            for fmt, width in (("<H", 2), ("<I", 4)):
                needle = struct.pack(fmt, code)
                i = data.find(needle)
                hits = []
                while i != -1 and len(hits) < 8:
                    hits.append(base + i)
                    i = data.find(needle, i + 1)
                if hits and name != ".text":
                    print(f"  {name} {code} u{width * 8}: " + " ".join(f"{h:08x}" for h in hits))
