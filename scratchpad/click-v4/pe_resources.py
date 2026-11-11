"""List PE resource types/names/sizes. Usage: uv run --no-project --with pefile python pe_resources.py DLL..."""

from __future__ import annotations

import sys

import pefile

for arg in sys.argv[1:]:
    pe = pefile.PE(arg, fast_load=True)
    pe.parse_data_directories(
        directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
    )
    print(f"== {arg}")
    imports = []
    pe.parse_data_directories(
        directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]]
    )
    for imp in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        imports.append(imp.dll.decode())
    print("  imports:", ", ".join(imports))
    res = getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None)
    for typ in res.entries if res else []:
        tname = str(typ.name) if typ.name else pefile.RESOURCE_TYPE.get(typ.id, typ.id)
        names = []
        for ent in typ.directory.entries:
            rname = str(ent.name) if ent.name else str(ent.id)
            size = sum(lang.data.struct.Size for lang in ent.directory.entries)
            names.append(f"{rname}({size})")
        print(f"  {tname}: {' '.join(names[:40])}")
