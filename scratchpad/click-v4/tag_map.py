"""Map CLICK instruction blob tags to dialog controls for an MFC Inst_*.dll.

Join on `this` member offsets:
  load:  push <out ptr>; push TAG; push 0x7dd|0x7e1 (getter); ...; call
         out ptr is either `[this+off]` (int member) or a temp later passed to
         `lea ecx,[this+off]; call SetWindowText`.
  DDX:   lea r,[this+off] ... push CONTROL_ID (0x1388..0x13ff) ... call DDX_*

Usage: uv run --no-project --with pefile --with capstone python tag_map.py DLL
Prints tag -> member offset -> control id(s) -> nearest static label in RT_DIALOG.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import capstone
import pefile
from capstone import x86

sys.path.insert(0, str(Path(__file__).parent))
from dialog_dump import parse_dialog  # noqa: E402

GETTERS = {0x7DD: "int", 0x7E1: "str", 0x7DF: "?", 0x7E3: "?"}
ID_LO, ID_HI = 0x1388, 0x13FF


def mem_disp(op_str_ins, want_reg_not_ebp: bool = True) -> int | None:
    for op in op_str_ins.operands:
        if op.type == x86.X86_OP_MEM and op.mem.base not in (0, x86.X86_REG_EBP, x86.X86_REG_ESP):
            return op.mem.disp
    return None


def imm(ins) -> int | None:
    for op in ins.operands:
        if op.type == x86.X86_OP_IMM:
            return op.imm & 0xFFFFFFFF
    return None


def main() -> None:
    path = sys.argv[1]
    pe = pefile.PE(path)
    text = next(s for s in pe.sections if s.Name.rstrip(b"\0") == b".text")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    md.skipdata = True
    insns = list(md.disasm(text.get_data(), pe.OPTIONAL_HEADER.ImageBase + text.VirtualAddress))

    # --- tag -> offset (load path)
    tag_off: dict[int, list[tuple[str, int | None]]] = {}
    for k in range(1, len(insns) - 1):
        a, b = insns[k], insns[k + 1]
        if a.mnemonic != "push" or b.mnemonic != "push":
            continue
        tag, getter = imm(a), imm(b)
        if tag is None or getter not in GETTERS or not (0x1000 <= tag <= 0x6FFF):
            continue
        # out pointer pushed just before
        off = None
        for j in range(k - 1, max(k - 4, 0), -1):
            p = insns[j]
            if p.mnemonic == "lea":
                off = mem_disp(p)
                break
        if off is None:  # temp -> find lea ecx,[this+off] after the call
            for j in range(k + 2, min(k + 16, len(insns))):
                p = insns[j]
                if p.mnemonic == "lea" and p.op_str.startswith("ecx") and mem_disp(p) is not None:
                    off = mem_disp(p)
                    break
                if p.mnemonic == "push" and imm(p) in GETTERS:
                    break
        tag_off.setdefault(tag, []).append((GETTERS[getter], off))

    # --- control id -> offset (DDX)
    id_off: dict[int, set[int]] = {}
    for k, ins in enumerate(insns):
        if ins.mnemonic != "push":
            continue
        v = imm(ins)
        if v is None or not (ID_LO <= v <= ID_HI):
            continue
        for j in list(range(k - 1, max(k - 4, 0), -1)) + list(range(k + 1, min(k + 3, len(insns)))):
            p = insns[j]
            if p.mnemonic == "lea" and mem_disp(p) is not None:
                id_off.setdefault(v, set()).add(mem_disp(p))
                break
    off_ids: dict[int, set[int]] = {}
    for cid, offs in id_off.items():
        for o in offs:
            off_ids.setdefault(o, set()).add(cid)

    # --- labels from dialog
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    controls: dict[int, tuple[int, int, str, str]] = {}
    statics: list[tuple[int, int, str]] = []
    for typ in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if typ.id != pefile.RESOURCE_TYPE["RT_DIALOG"]:
            continue
        for ent in typ.directory.entries:
            for lang in ent.directory.entries:
                ds = lang.data.struct
                _t, items = parse_dialog(pe.get_data(ds.OffsetToData, ds.Size))
                for y, x, cid, cls, txt, _st in items:
                    controls[cid] = (y, x, cls, txt)
                    if cls in ("Static", "Button") and txt and txt != "...":
                        statics.append((y, x, txt))

    def label(cid: int) -> str:
        if cid not in controls:
            return "?"
        y, x, cls, txt = controls[cid]
        if txt and txt != "...":
            return f"{cls} {txt!r}"
        best = min(
            (s for s in statics if abs(s[0] - y) <= 6 and s[1] < x),
            key=lambda s: (x - s[1]),
            default=None,
        )
        return f"{cls} <- {best[2]!r}" if best else cls

    seen = set()
    for tag in sorted(tag_off, key=lambda t: list(tag_off).index(t)):
        for kind, off in tag_off[tag]:
            if (tag, off) in seen:
                continue
            seen.add((tag, off))
            ids = sorted(off_ids.get(off, ())) if off is not None else []
            desc = "; ".join(f"{c}={label(c)}" for c in ids) or "-"
            offs = f"+0x{off:x}" if off is not None else "?"
            print(f"{tag:04x} {kind:3} {offs:>7}  {desc}")


if __name__ == "__main__":
    main()
