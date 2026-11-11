"""Dump Delphi/C++Builder DFM form resources (TPF0) from PE files as text.

Usage: uv run --with pefile python scratchpad/click-v4/dfm_dump.py OUT_DIR DLL [DLL ...]
Writes OUT_DIR/<dll stem>__<resource name>.txt per form.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pefile


class Reader:
    def __init__(self, data: bytes) -> None:
        self.d = data
        self.i = 0

    def u8(self) -> int:
        v = self.d[self.i]
        self.i += 1
        return v

    def take(self, n: int) -> bytes:
        v = self.d[self.i : self.i + n]
        self.i += n
        return v

    def i32(self) -> int:
        return struct.unpack("<i", self.take(4))[0]

    def sstr(self) -> str:
        n = self.u8()
        return self.take(n).decode("latin-1")


def read_value(r: Reader, t: int, indent: str) -> str:
    if t == 0:
        return "<null>"
    if t == 1:  # list
        items = []
        while True:
            t2 = r.u8()
            if t2 == 0:
                break
            items.append(read_value(r, t2, indent))
        return "(" + " ".join(items) + ")"
    if t == 2:
        return str(struct.unpack("<b", r.take(1))[0])
    if t == 3:
        return str(struct.unpack("<h", r.take(2))[0])
    if t == 4:
        return str(r.i32())
    if t == 5:
        r.take(10)
        return "<extended>"
    if t in (6, 7):
        s = r.sstr()
        return repr(s) if t == 6 else s
    if t == 8:
        return "False"
    if t == 9:
        return "True"
    if t == 10:
        n = r.i32()
        r.take(n)
        return f"<binary {n}>"
    if t == 11:
        items = []
        while True:
            s = r.sstr()
            if not s:
                break
            items.append(s)
        return "[" + ", ".join(items) + "]"
    if t in (12, 20):
        n = r.i32()
        return repr(r.take(n).decode("latin-1"))
    if t == 13:
        return "nil"
    if t == 14:  # collection
        out = ["<"]
        while True:
            t2 = r.u8()
            if t2 == 0:
                break
            if t2 in (2, 3, 4):
                read_value(r, t2, indent)
            else:
                r.i -= 1
            out.append(f"{indent}  item")
            out.extend(read_props(r, indent + "    "))
        out.append(f"{indent}>")
        return "\n".join(out)
    if t == 15:
        return str(struct.unpack("<f", r.take(4))[0])
    if t in (16, 17, 21):
        return str(struct.unpack("<d", r.take(8))[0])
    if t == 18:
        n = r.i32()
        return repr(r.take(2 * n).decode("utf-16-le"))
    if t == 19:
        return str(struct.unpack("<q", r.take(8))[0])
    raise ValueError(f"unknown value type {t} at {r.i - 1:#x}")


def read_props(r: Reader, indent: str) -> list[str]:
    lines = []
    while True:
        name = r.sstr()
        if not name:
            break
        t = r.u8()
        lines.append(f"{indent}{name} = {read_value(r, t, indent)}")
    return lines


def read_component(r: Reader, indent: str) -> list[str]:
    b = r.d[r.i]
    if b & 0xF0 == 0xF0:
        flags = r.u8() & 0x0F
        if flags & 0x02:
            t = r.u8()
            read_value(r, t, indent)
    cls = r.sstr()
    name = r.sstr()
    lines = [f"{indent}object {name}: {cls}"]
    lines.extend(read_props(r, indent + "  "))
    while r.d[r.i] != 0:
        lines.extend(read_component(r, indent + "  "))
    r.u8()
    lines.append(f"{indent}end")
    return lines


def dump(dll: Path, out_dir: Path) -> None:
    pe = pefile.PE(str(dll), fast_load=True)
    pe.parse_data_directories(
        directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
    )
    if not hasattr(pe, "DIRECTORY_ENTRY_RESOURCE"):
        return
    for typ in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if typ.id != pefile.RESOURCE_TYPE["RT_RCDATA"]:
            continue
        for ent in typ.directory.entries:
            rname = str(ent.name) if ent.name else str(ent.id)
            for lang in ent.directory.entries:
                ds = lang.data.struct
                data = pe.get_data(ds.OffsetToData, ds.Size)
                if not data.startswith(b"TPF0"):
                    continue
                r = Reader(data)
                r.i = 4
                try:
                    text = "\n".join(read_component(r, ""))
                except Exception as exc:  # noqa: BLE001
                    text = f"PARSE ERROR: {exc}"
                path = out_dir / f"{dll.stem}__{rname}.txt"
                path.write_text(text, encoding="utf-8")
                print(path)


def main() -> None:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    for arg in sys.argv[2:]:
        dump(Path(arg), out_dir)


if __name__ == "__main__":
    main()
