"""Inspect raw instruction blobs from native captures.

Parses the tagged-field structure inside UnknownCondition/UnknownInstruction
raw blobs to confirm the byte layout before building the real parser.
"""

from pathlib import Path

from laddercodec.decode import UnknownCondition, UnknownInstruction, decode

CAPTURES = Path(r"c:\Users\Sam\Documents\GitHub\clicknick\devtools\captures")


def read_utf16le_string(raw: bytes, offset: int) -> tuple[str, int]:
    """Read a null-terminated UTF-16LE string. Returns (string, end_offset)."""
    i = offset
    while i < len(raw) - 1:
        if raw[i] == 0 and raw[i + 1] == 0:
            s = raw[offset:i].decode("utf-16-le")
            return s, i + 2  # skip null terminator
        i += 2
    return raw[offset:].decode("utf-16-le", errors="replace"), len(raw)


def parse_instruction_blob(raw: bytes) -> dict:
    """Parse the raw instruction blob into structured fields."""
    result = {}

    # 1. Class name (UTF-16LE null-terminated)
    class_name, pos = read_utf16le_string(raw, 0)
    result["class_name"] = class_name

    # 2. Type marker (uint32 LE)
    type_marker = int.from_bytes(raw[pos : pos + 4], "little")
    result["type_marker"] = f"0x{type_marker:04X}"
    pos += 4

    # 3. Unknown 2 bytes + field count (uint32 LE)
    unknown = int.from_bytes(raw[pos : pos + 2], "little")
    result["unknown_01"] = f"0x{unknown:04X}"
    pos += 2

    field_count = int.from_bytes(raw[pos : pos + 4], "little")
    result["field_count"] = field_count
    pos += 4

    # 4. Tagged fields: [2B tag][4B FFFFFFFF sentinel][value UTF-16LE null-terminated]
    fields = []
    for i in range(field_count):
        if pos + 6 > len(raw):
            fields.append({"error": f"ran out of data at field {i}, pos={pos}"})
            break

        tag = int.from_bytes(raw[pos : pos + 2], "little")
        pos += 2

        sentinel = raw[pos : pos + 4]
        pos += 4

        if sentinel != b"\xff\xff\xff\xff":
            # Not a sentinel — might be a different structure
            fields.append(
                {"tag": f"0x{tag:04X}", "sentinel": sentinel.hex(), "note": "unexpected sentinel"}
            )
            break

        value, pos = read_utf16le_string(raw, pos)
        fields.append({"tag": f"0x{tag:04X}", "value": value})

    result["fields"] = fields

    if pos < len(raw):
        result["trailing"] = raw[pos:].hex(" ")
        result["trailing_len"] = len(raw) - pos

    return result


for name in ["instr-no-out.native.bin", "instr-nc-out.native.bin"]:
    path = CAPTURES / name
    if not path.exists():
        print(f"--- {name}: NOT FOUND ---")
        continue

    print(f"\n{'=' * 60}")
    print(f"  {name}")
    print(f"{'=' * 60}")

    data = path.read_bytes()
    rung = decode(data)
    assert not isinstance(rung, list), "Expected single rung"

    for row_idx, (conds, af) in enumerate(zip(rung.conditions, rung.instructions, strict=True)):
        for col_idx, cell in enumerate(conds):
            if isinstance(cell, UnknownCondition):
                print(f"\n  Row {row_idx}, Col {col_idx} — CONDITION ({len(cell.raw)} bytes)")
                parsed = parse_instruction_blob(cell.raw)
                for k, v in parsed.items():
                    if k == "fields":
                        for j, f in enumerate(v):
                            print(f"    field[{j}]: {f}")
                    else:
                        print(f"    {k}: {v}")

        if isinstance(af, UnknownInstruction):
            print(f"\n  Row {row_idx}, AF — INSTRUCTION ({len(af.raw)} bytes)")
            parsed = parse_instruction_blob(af.raw)
            for k, v in parsed.items():
                if k == "fields":
                    for j, f in enumerate(v):
                        print(f"    field[{j}]: {f}")
                else:
                    print(f"    {k}: {v}")
