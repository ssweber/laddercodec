"""Print the UTF-16LE string at each VA in a DLL.

Usage: uv run --no-project --with pefile python wstr.py DLL VA [VA...]
"""

from __future__ import annotations

import sys

import pefile

pe = pefile.PE(sys.argv[1])
ib = pe.OPTIONAL_HEADER.ImageBase
for arg in sys.argv[2:]:
    va = int(arg, 16)
    data = pe.get_data(va - ib, 128)
    end = next((k for k in range(0, len(data) - 1, 2) if data[k : k + 2] == b"\0\0"), len(data))
    print(f"{va:08x}: {data[:end].decode('utf-16-le', 'replace')!r}")
