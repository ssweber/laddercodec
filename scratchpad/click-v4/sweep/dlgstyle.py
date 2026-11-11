"""Print control styles (readonly/disabled/hidden) for RT_DIALOG controls.

Usage: uv run --no-project --with pefile python dlgstyle.py DLL...
"""

from __future__ import annotations

import sys
from pathlib import Path

import pefile

sys.path.insert(0, str(Path(__file__).parent.parent))
from dialog_dump import parse_dialog  # noqa: E402

for arg in sys.argv[1:]:
    pe = pefile.PE(arg, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    print(f"######## {Path(arg).name}")
    for typ in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if typ.id != pefile.RESOURCE_TYPE["RT_DIALOG"]:
            continue
        for ent in typ.directory.entries:
            for lang in ent.directory.entries:
                ds = lang.data.struct
                title, items = parse_dialog(pe.get_data(ds.OffsetToData, ds.Size))
                print(f"--- dialog {ent.id} {title!r}")
                for y, x, cid, cls, text, st in sorted(items):
                    flags = []
                    if cls == "Edit" and st & 0x800:
                        flags.append("READONLY")
                    if cls == "Edit" and st & 0x2000:
                        flags.append("NUMBER")
                    if st & 0x08000000:
                        flags.append("DISABLED")
                    if not st & 0x10000000:
                        flags.append("HIDDEN")
                    if cls == "ComboBox":
                        flags.append({1: "simple", 2: "dropdown", 3: "droplist"}.get(st & 3, "?"))
                    print(f"  0x{cid & 0xffff:04x} {cls:10} style={st:08x} {' '.join(flags):24} {text!r}")
