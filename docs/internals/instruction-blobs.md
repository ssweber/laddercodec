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

## Math formulas

A Math blob (class `Math`, type 0x271A) always has 1010 tagged fields: 9 header
fields, 500 operand slots (tag `0x6888`), 500 reserved slots (tag `0x688C`) and
a terminator. Source: `math.py`.

The formula appears four times in the header:

| Tag | Field | Example for `SUM ( DS1 : DS3 ) + 5` |
|---|---|---|
| `0x61FF` | template, display | `SUM ( @ : @ ) + 5` |
| `0x6228` | formula, display | `SUM ( DS1 : DS3 ) + 5` |
| `0x6229` | template, internal | `SUM#(#@#:#@#)#+#H5` |
| `0x61FD` | formula, internal | `SUM#(#DS1#:#DS3#)#+#H5` |

- **Display form** is spaced the way Click's formula editor spaces it: one space
  on each side of every operator, paren, comma and range colon (`ABS ( x )`,
  `RAND ( 1 , 100 )`). The encoder normalizes `ABS(x)` to this form.
- **Internal form** is the display form with spaces replaced by `#` and each
  bare decimal literal prefixed with `H`. Click splits it on `#`, so an
  unspaced `ABS(` becomes a single unknown token. In CLICK v4 that pastes but
  raises a Math instruction error.
- **RAND** is stored infix in the internal form: `RAND ( a , b )` becomes
  `a#RAND#b`, followed by a trailing `#` when RAND ends the formula
  (`H1#RAND#H100#`, `H1#RAND#H10#+#DS1`). The display form keeps the function
  call.

### Operand and reserved slots

Each slot is `[2B tag][4B index LE][UTF-16LE value]`, and an empty slot is just
a null terminator. Operand slots hold every address in the formula, in order,
duplicates included. Reserved slots hold the interior addresses of each
`A : B` range, ranges in order. The endpoints are ordinary operands, so
`SUM ( DS201 : DS300 )` stores DS201 and DS300 as operands and DS202..DS299 in
the reserved slots.

CLICK v4 copies Math back with 5000 reserved slots, not 500. A 500-slot blob
still pastes into both v3 and v4, so the encoder keeps 500.

## Math nickname flag

Math blobs contain a `nickname_flag` field (tag `0x2224`). When set to `"1"`,
Click displays project-level tag names instead of raw addresses in the math
formula. The flag is purely a display hint — the expression itself always
stores concrete addresses.

The `encode()` API exposes this via `show_nicknames=True`, which sets the flag
on all math instructions in the buffer.

## Blob boundary detection

For unknown instruction types, the blob boundary can be detected using the generic multi-part formula:

1. Read the class name (UTF-16LE, null-terminated)
2. Read the type marker (uint32 LE)
3. Read part count (uint16 LE), skip `(part_count - 1)` extra bytes
4. Read field count (uint32 LE)
5. Walk through tagged fields (each: 2B tag + 4B sentinel/marker + UTF-16LE value)
6. The blob ends after all fields are consumed

The `RawInstruction` fallback uses this formula to capture the complete blob as opaque bytes, enabling round-trip for unsupported instruction types via `raw(ClassName,hex)` CSV tokens.

At the moment, `Email`, `Home`, `Position`, and `Velocity` still deliberately
travel through this raw path. They round-trip correctly, but they are not yet
modeled as dedicated DSL instruction classes.
