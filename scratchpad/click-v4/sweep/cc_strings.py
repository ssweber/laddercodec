"""List UTF-16LE (and optionally ASCII) strings in non-.text sections with their VAs.

Usage: uv run --no-project --with pefile python cc_strings.py DLL [MINLEN] [--ascii]
"""

from __future__ import annotations

import re
import sys

import pefile

pe = pefile.PE(sys.argv[1])
minlen = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 1
ib = pe.OPTIONAL_HEADER.ImageBase
for s in pe.sections:
    name = s.Name.rstrip(b"\0").decode()
    if name in (".text", ".rsrc", ".reloc"):
        continue
    data = s.get_data()
    for m in re.finditer(rb"(?:[\x20-\x7e]\x00){%d,}\x00\x00" % minlen, data):
        if m.start() % 2:
            continue
        txt = m.group()[:-2].decode("utf-16le")
        print(f"{ib + s.VirtualAddress + m.start():08x} {name} L{txt!r}")
    if "--ascii" in sys.argv:
        for m in re.finditer(rb"[\x20-\x7e]{%d,}\x00" % max(minlen, 3), data):
            print(f"{ib + s.VirtualAddress + m.start():08x} {name} A{m.group()[:-1].decode()!r}")
