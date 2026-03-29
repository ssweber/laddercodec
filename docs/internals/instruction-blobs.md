# Instruction Blobs

This page documents the variable-length instruction data that follows the cell header in instruction cells. The blob starts at cell offset +0x25.

For field layouts, func code tables, and tag constants for each known instruction type, see the source in `src/laddercodec/instructions/` — each module (`contact.py`, `comparison.py`, `coil.py`, `timer.py`) is the authoritative reference.

## Generic blob structure

All instruction blobs follow the same pattern:

```
[UTF-16LE class name, null-terminated]
[type marker: uint32 LE, high byte always 0x27]
[part count: uint16 LE (0x01 for contacts/coils, 0x02 for timers)]
[extra bytes: (part_count - 1) bytes, if part_count > 1]
[field count: uint32 LE]
[tagged fields...]
```

### Tagged fields

Each field is:

```
[2-byte tag]
[FF FF FF FF sentinel]
[UTF-16LE null-terminated value]
```

Field values are string-encoded even for numeric data (e.g. `"1000"` for a timer preset). Timer fields 6–7 use a variant format with a 4-byte sub-marker instead of the `FF FF FF FF` sentinel.

## Known binary class names

| Class name | Type markers | Instruction | Source |
|---|---|---|---|
| `ContactNO` | 0x2711 (NO), 0x2712 (NC) | NO/NC contacts | `contact.py` |
| `Edge` | 0x2713 | Rising/falling edge contacts | `contact.py` |
| `Compare` | 0x2714 | Comparison contacts (==, !=, >, <, >=, <=) | `comparison.py` |
| `Out` | 0x2715, 0x2716, 0x2717 | All coil types (out, latch, reset) | `coil.py` |
| `Tmr` | 0x2718 | Timers (on_delay, off_delay) | `timer.py` |

The encoder uses `Out` as the class name for all coil types; the type marker and func code determine the variant. The decoder also recognizes `Latch` and `Reset` class names from native Click captures.

## Math nickname flag

Math blobs contain a `nickname_flag` field (tag `0x2224`). When set to `"1"`,
Click displays project-level tag names instead of raw addresses in the math
formula. The flag is purely a display hint — the expression itself always
stores concrete addresses.

The `encode()` API exposes this via `show_nicknames=True`, which sets the flag
on all math instructions in the buffer.

## AF summary block

In single-rung buffers, when a rung has 2+ AF instruction cells, the **last** AF instruction cell gets an extra block appended between the blob and tail:

1. 12 zero bytes (header padding)
2. `uint32 LE` total instruction count
3. `af_count * 8`-byte entries in a diagonal pattern:
   - `entry[af_idx] = left_value` (total_instr_count - instr_index for non-last; instrs_on_row for last)
   - `entry[af_idx + af_count] = 1` if row has a condition contact
4. Modified 16-byte tail: `tail[3]=1, tail[12]=1, tail[15]=1`

This block replaces the instruction count that would normally go on an AF data cell (`tail[12] = total_instr_count`) when no AF data cell exists (all rows have AF instructions).

## Blob boundary detection

For unknown instruction types, the blob boundary can be detected using the generic multi-part formula:

1. Read the class name (UTF-16LE, null-terminated)
2. Read the type marker (uint32 LE)
3. Read part count (uint16 LE), skip `(part_count - 1)` extra bytes
4. Read field count (uint32 LE)
5. Walk through tagged fields (each: 2B tag + 4B sentinel/marker + UTF-16LE value)
6. The blob ends after all fields are consumed

The `RawInstruction` fallback uses this formula to capture the complete blob as opaque bytes, enabling round-trip for unsupported instruction types via `raw(ClassName,hex)` CSV tokens.
