# Instruction Blobs

This page documents the variable-length instruction data that follows the cell header in instruction cells. The blob starts at cell offset +0x25.

## Generic blob structure

All instruction blobs follow the same pattern:

```
[UTF-16LE class name, null-terminated]
[type marker: uint32 LE, high byte always 0x27]
[01 00]
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

Field values are string-encoded even for numeric data (e.g. `"1000"` for a timer preset).

## Known binary class names

| Class name | Type markers | Instruction |
|---|---|---|
| `ContactNO` | 0x2711 (NO), 0x2712 (NC) | NO/NC contacts |
| `Edge` | 0x2713 | Rising/falling edge contacts |
| `Compare` | 0x2714 | Comparison contacts (==, !=, >, <, >=, <=) |
| `Out` | 0x2715 | Output coils |
| `Latch` | 0x2716 | Latch coils |
| `Reset` | 0x2717 | Reset coils |
| `Tmr` | 0x2718 | Timers (on_delay, off_delay) |

## Contact fields (ContactNO)

Field count: 4

| Index | Field | Example values |
|---|---|---|
| 0 | Operand | `X001`, `C1`, `DS1` |
| 1 | Immediate flag | `0` or `1` |
| 2 | Func code | Discriminates NO vs NC |
| 3 | Terminal | Always `0` |

The type marker (0x2711 vs 0x2712) and func code together determine the contact variant (NO, NC, immediate NO, immediate NC).

### Contact func codes

| Func code | Variant |
|---|---|
| 4097 | NO |
| 4098 | NC |
| 4099 | Immediate NO |
| 4100 | Immediate NC |

## Edge contact fields (Edge)

Field count: 4

Same layout as ContactNO. Func code discriminates rising vs falling edge.

| Func code | Variant |
|---|---|
| 4101 | Rising edge |
| 4102 | Falling edge |

## Comparison contact fields (Compare)

Field count: 6

| Index | Field | Example values |
|---|---|---|
| 0 | Left operand | `DS1` |
| 1 | Right operand | `DS2`, `100` |
| 2 | Operator func code | Discriminates ==, !=, >, <, >=, <= |
| 3 | Type index | `0`–`5` (maps to operator, same order) |
| 4 | Terminal | Always `0` |
| 5 | Terminal | Always `0` |

### Compare func codes

| Func code | Operator |
|---|---|
| 4103 | == |
| 4104 | != |
| 4105 | > |
| 4106 | < |
| 4108 | >= |
| 4109 | <= |

Note: 4107 is not used.

## Coil fields (Out / Latch / Reset)

Field count: 6

| Index | Field | Example values |
|---|---|---|
| 0 | Operand | `Y001`, `C1` |
| 1 | Range end | `""` or `C8` (for range coils) |
| 2 | Oneshot | `0` |
| 3 | Immediate flag | `0` or `1` |
| 4 | Func code | Discriminates out/latch/reset variants |
| 5 | Terminal | Always `0` |

The binary class name (`Out`, `Latch`, `Reset`) determines the base type. Func code further discriminates variants (e.g. immediate output).

### Coil func codes

| Func code | Type | Range | Immediate |
|---|---|---|---|
| 8193 | Out | no | no |
| 8197 | Out | no | yes |
| 8207 | Out | yes | no |
| 8208 | Out | yes | yes |
| 8195 | Latch | no | no |
| 8199 | Latch | no | yes |
| 8213 | Latch | yes | no |
| 8214 | Latch | yes | yes |
| 8196 | Reset | no | no |
| 8200 | Reset | no | yes |
| 8219 | Reset | yes | no |
| 8220 | Reset | yes | yes |

## Timer fields (Tmr)

Timers are multi-part instructions:

- Part count: 2 (byte `0x02`, differs from contact/coil's `0x01`)
- Field count: 9 (6 standard tagged + 2 variant tagged + 1 sentinel)
- Type marker: 0x2718

Key fields include done bit (e.g. `T1`), accumulator register (e.g. `TD1`), preset value, unit, and mode (on_delay/off_delay). Timers occupy 2 grid rows in the cell grid.

### Timer units

| Unit index | Name | Resolution |
|---|---|---|
| 0 | Tms | 10 ms |
| 1 | Ts | 1 second |
| 2 | Tm | 1 minute |
| 3 | Th | 1 hour |
| 4 | Td | 1 day |

### Timer func codes

Enable func code formula: `base = 8717 + unit_index * 6`

| Variant | Func code |
|---|---|
| on_delay | `base` |
| on_delay (retentive) | `base + 2` |
| off_delay | `base + 1` |
| reset (retentive only) | `base + 3` |

## AF summary block

When a rung has 2+ AF instruction cells, the **last** AF instruction cell gets an extra block appended between the blob and tail:

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
3. Read `01 00` + field count
4. Walk through tagged fields (each: 2B tag + 4B sentinel + UTF-16LE value)
5. The blob ends after all fields are consumed

The `RawInstruction` fallback uses this formula to capture the complete blob as opaque bytes, enabling round-trip for unsupported instruction types via `raw(ClassName,hex)` CSV tokens.
