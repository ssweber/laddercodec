"""Dump a table of string pointers (or a single string) from a 32-bit PE.

Usage: uv run --no-project --with pefile python ptrstr.py DLL VAHEX COUNT [str]
  default: treat VA as table of COUNT dword pointers and print UTF-16 string at each.
  'str' mode: print COUNT UTF-16 strings laid out consecutively starting at VA.
"""

from __future__ import annotations

import struct
import sys

import pefile

pe = pefile.PE(sys.argv[1])
ib = pe.OPTIONAL_HEADER.ImageBase
mm = pe.get_memory_mapped_image()
va = int(sys.argv[2], 16)
n = int(sys.argv[3])


def ustr(a: int) -> str:
    off = a - ib
    if not 0 <= off < len(mm):
        return f"<out of image {a:08x}>"
    end = off
    while end + 1 < len(mm) and mm[end : end + 2] != b"\0\0":
        end += 2
    return mm[off:end].decode("utf-16le", errors="replace")


if len(sys.argv) > 4 and sys.argv[4] == "str":
    a = va
    for _ in range(n):
        s = ustr(a)
        print(f"{a:08x} {s!r}")
        a += (len(s) + 1) * 2
else:
    for i in range(n):
        p = struct.unpack_from("<I", mm, va - ib + 4 * i)[0]
        print(f"[{i}] {va + 4 * i:08x} -> {p:08x} {ustr(p)!r}")
