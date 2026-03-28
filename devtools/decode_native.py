"""Decode a native capture and display structured results."""

import sys
from pathlib import Path

from laddercodec import decode
from laddercodec.decode import UnknownCondition, UnknownInstruction

path = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else Path("c:/Users/Sam/Documents/GitHub/clicknick/devtools/captures/instr-no-out.native.bin")
)
data = path.read_bytes()
r = decode(data)
assert not isinstance(r, list), "Expected single rung"

print(f"File: {path.name}")
print(f"Logical rows: {r.logical_rows}")
print(f"Comment: {r.comment}")
print()

for row_idx in range(r.logical_rows):
    conds = r.conditions[row_idx]
    af = r.instructions[row_idx]

    for col_idx, tok in enumerate(conds):
        col_letter = chr(ord("A") + col_idx) if col_idx < 26 else f"A{chr(ord('A') + col_idx - 26)}"
        if isinstance(tok, UnknownCondition):
            print(f"  Row {row_idx}, Col {col_letter}: UnknownCondition ({len(tok.raw)} bytes)")
            print(f"    hex: {tok.raw.hex(' ')}")
            null2 = tok.raw.find(b"\x00\x00")
            if null2 > 0 and null2 % 2 == 0:
                try:
                    name = tok.raw[:null2].decode("utf-16-le")
                    print(f"    class: {name!r}")
                except Exception:
                    pass
        elif tok not in ("",):
            print(f"  Row {row_idx}, Col {col_letter}: {tok!r}")

    if isinstance(af, UnknownInstruction):
        print(f"  Row {row_idx}, Col AF: UnknownInstruction ({len(af.raw)} bytes)")
        print(f"    hex: {af.raw.hex(' ')}")
        null2 = af.raw.find(b"\x00\x00")
        if null2 > 0 and null2 % 2 == 0:
            try:
                name = af.raw[:null2].decode("utf-16-le")
                print(f"    class: {name!r}")
            except Exception:
                pass
    elif af:
        print(f"  Row {row_idx}, Col AF: {af!r}")
