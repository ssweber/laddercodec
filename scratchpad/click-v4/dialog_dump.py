"""Dump Win32 RT_DIALOG (DLGTEMPLATEEX) controls and RT_STRING tables from PE files.

Usage: uv run --no-project --with pefile python scratchpad/click-v4/dialog_dump.py DLL [DLL ...]
Controls are listed in layout order (top-to-bottom, left-to-right).
"""

from __future__ import annotations

import struct
import sys

import pefile

CLASS_ORD = {0x80: "Button", 0x81: "Edit", 0x82: "Static", 0x83: "ListBox", 0x84: "ScrollBar", 0x85: "ComboBox"}


def sz_or_ord(d: bytes, i: int) -> tuple[str, int]:
    w = struct.unpack_from("<H", d, i)[0]
    if w == 0:
        return "", i + 2
    if w == 0xFFFF:
        o = struct.unpack_from("<H", d, i + 2)[0]
        return CLASS_ORD.get(o, f"#{o}"), i + 4
    end = i
    while struct.unpack_from("<H", d, end)[0] != 0:
        end += 2
    return d[i:end].decode("utf-16-le"), end + 2


def align4(i: int) -> int:
    return (i + 3) & ~3


def button_kind(style: int) -> str:
    bs = style & 0xF
    return {0: "push", 1: "defpush", 2: "check", 3: "autocheck", 4: "radio", 7: "group", 9: "autoradio"}.get(bs, f"bs{bs}")


def parse_dialog(d: bytes) -> tuple[str, list[tuple[int, int, int, str, str, int]]]:
    ver, sig = struct.unpack_from("<HH", d, 0)
    if sig != 0xFFFF:
        raise ValueError("not DLGTEMPLATEEX")
    _help, _ex, style = struct.unpack_from("<III", d, 4)
    count = struct.unpack_from("<H", d, 16)[0]
    i = 26
    _menu, i = sz_or_ord(d, i)
    _cls, i = sz_or_ord(d, i)
    title, i = sz_or_ord(d, i)
    if style & 0x40:
        i += 6
        _font, i = sz_or_ord(d, i)
    items = []
    for _ in range(count):
        i = align4(i)
        _h, _e, st = struct.unpack_from("<III", d, i)
        x, y, _cx, _cy = struct.unpack_from("<hhhh", d, i + 12)
        cid = struct.unpack_from("<I", d, i + 20)[0]
        i += 24
        cls, i = sz_or_ord(d, i)
        text, i = sz_or_ord(d, i)
        extra = struct.unpack_from("<H", d, i)[0]
        i += 2 + extra
        items.append((y, x, cid, cls, text, st))
    return title, items


def main() -> None:
    for arg in sys.argv[1:]:
        pe = pefile.PE(arg, fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        print(f"######## {arg.rsplit('/', 1)[-1]}")
        res = getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None)
        for typ in res.entries if res else []:
            if typ.id == pefile.RESOURCE_TYPE["RT_DIALOG"]:
                for ent in typ.directory.entries:
                    for lang in ent.directory.entries:
                        ds = lang.data.struct
                        title, items = parse_dialog(pe.get_data(ds.OffsetToData, ds.Size))
                        print(f"--- dialog {ent.id or ent.name} {title!r}")
                        for y, x, cid, cls, text, st in sorted(items):
                            kind = button_kind(st) if cls == "Button" else ""
                            print(f"  y={y:4} x={x:4} id={cid:5} (0x{cid:04x}) {cls:18} {kind:9} {text!r}")
            elif typ.id == pefile.RESOURCE_TYPE["RT_STRING"]:
                for ent in typ.directory.entries:
                    for lang in ent.directory.entries:
                        ds = lang.data.struct
                        d = pe.get_data(ds.OffsetToData, ds.Size)
                        i = 0
                        base = (ent.id - 1) * 16
                        for k in range(16):
                            n = struct.unpack_from("<H", d, i)[0]
                            s = d[i + 2 : i + 2 + 2 * n].decode("utf-16-le")
                            i += 2 + 2 * n
                            if s:
                                print(f"  string {base + k}: {s!r}")


if __name__ == "__main__":
    main()
