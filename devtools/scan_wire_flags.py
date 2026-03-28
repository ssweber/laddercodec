"""Scan a native capture for all unique wire flag combinations."""

import struct
import sys
from pathlib import Path

from laddercodec.topology import (
    CELL_SIZE,
    COLS_PER_ROW,
    GRID_FIRST_ROW_START,
    GRID_ROW_STRIDE,
    PROGRAM_HEADER_BASE,
)

path = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else Path(r"c:\Users\Sam\Documents\GitHub\clicknick\devtools\captures\variety.native.bin")
)
data = path.read_bytes()

# Read payload length to find grid start.
payload_len = struct.unpack_from("<I", data, 0x0294)[0]
grid_start = GRID_FIRST_ROW_START + payload_len

row_word = struct.unpack_from("<H", data, PROGRAM_HEADER_BASE)[0]
total_grid_rows = row_word // 0x20

print(f"File: {path.name} ({len(data)} bytes)")
print(f"Grid start: {grid_start:#x}, total grid rows: {total_grid_rows}")

flags_seen: dict[tuple[int, int, int], list[str]] = {}

cursor = grid_start
for row in range(total_grid_rows):
    if cursor + CELL_SIZE > len(data):
        break

    marker_05 = data[cursor + 0x05]
    marker_30 = data[cursor + 0x30]

    if marker_05 == 0xFF:
        print(f"  Row {row}: TERMINAL at {cursor:#x}")
        break

    if marker_30 == 0x01:
        cmt_len = int.from_bytes(data[cursor + 0x34 : cursor + 0x38], "little")
        print(f"  Row {row}: PREAMBLE at {cursor:#x} (comment={cmt_len})")
        cursor += GRID_ROW_STRIDE + cmt_len
        continue

    print(f"  Row {row}: DATA at {cursor:#x}")
    pos = cursor
    for col in range(COLS_PER_ROW):
        if pos + CELL_SIZE > len(data):
            break
        has_instr = data[pos + 0x25] != 0
        if has_instr:
            # Just note the instruction, skip wire flags
            # Try to read class name
            raw = data[pos + 0x25 :]
            i = 0
            while i < min(40, len(raw) - 1):
                if raw[i] == 0 and raw[i + 1] == 0:
                    try:
                        cn = raw[:i].decode("utf-16-le")
                    except Exception:
                        cn = "?"
                    print(
                        f"    Col {col}: INSTRUCTION class={cn.encode('ascii', errors='replace')!r}"
                    )
                    break
                i += 2
            # Find next cell to advance pos
            if col < COLS_PER_ROW - 1:
                row_byte = data[cursor + 0x05]
                for scan in range(pos + CELL_SIZE, pos + 0x200):
                    if (
                        scan + CELL_SIZE <= len(data)
                        and data[scan] == 0x00
                        and data[scan + 0x01] == col + 1
                        and data[scan + 0x05] == row_byte
                        and data[scan + 0x09] == 0x01
                    ):
                        pos = scan
                        break
                else:
                    pos += CELL_SIZE
            else:
                pos += CELL_SIZE
        else:
            wl = data[pos + 0x19]
            wr = data[pos + 0x1D]
            wd = data[pos + 0x21]
            key = (wl, wr, wd)
            loc = f"row={row},col={col}"
            flags_seen.setdefault(key, []).append(loc)
            pos += CELL_SIZE

    cursor = pos

print(f"\nUnique wire flags ({len(flags_seen)}):")
for key, locs in sorted(flags_seen.items()):
    known = {(0, 0, 0): '""', (1, 1, 0): '"-"', (0, 0, 1): '"|"', (1, 1, 1): '"T"'}
    label = known.get(key, "NEW")
    print(f"  {key} ({label}): {len(locs)} cells, first: {locs[0]}")
