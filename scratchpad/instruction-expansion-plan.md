# Instruction Expansion Plan

## Goal

Expand encode/decode coverage from 4 instruction classes (ContactNO, Edge, Compare, Out, Tmr) to all ~15+ Click instruction types. ~80 coverage fixtures already have CSVs; binaries need capturing.

## Phase 1: Discovery (current)

Capture one representative binary per instruction family to discover:
- UTF-16 class name (the binary discriminator)
- Type marker (0x2700 | N)
- Part count (0x01 vs 0x02 for multi-row)
- Field count, tag values, field layout
- Row span / visual rows

**Capture file:** `tests/fixtures/ladder_captures/golden/quick-instruction-names.bin`
**PDF reference:** `tests/fixtures/ladder_captures/golden/quick-instruction-names.pdf`

### Discovery results (2026-03-17)

**Multi-part formula (confirmed):** `marker(4) + part_count(2) + [01, 02, ..., part_count-1] + field_count(4) + tagged_fields`

Extra bytes before field_count = `part_count - 1` sequential bytes (0x01, 0x02, ...).

| Binary class | Type marker | Part count | Fields | CSV family | Notes |
|-------------|-------------|------------|--------|------------|-------|
| ContactNO | 0x2711-12 | 1 | 4 | cond__no/nc/immediate | KNOWN |
| Edge | 0x2713 | 1 | 4 | cond__rise/fall | KNOWN |
| Compare | 0x2714 | 1 | 5 | cond__eq/ne/gt/lt/ge/le | KNOWN |
| Out | 0x2715-17 | 1 | 6 | out/latch/reset + oneshot | KNOWN |
| Tmr | 0x2718 | 2 | 9 | on_delay/off_delay/rton | KNOWN |
| Cnt | 0x2719 | 3 | 9 | count_up/count_down | type_idx: 0=up, 1=down, 2=up+down |
| Math | 0x271A | 1 | 1010 | math__decimal/hex | Expression tree; 1010 pre-allocated field slots |
| Drum | 0x271B | 4 | 64 | time_drum/event_drum | type_idx field[4]: 0=time, 1=event |
| SR | 0x2720 | 3 | 6 | shift | start/end operands + 3 variant func codes |
| Copy | 0x2721 | 1 | 13 | copy/blockcopy/fill/pack/unpack | All copy variants share one class! field[6] discriminates: 0=single, 1=block, 2=fill, 3=pack |
| Search | 0x2722 | 1 | 10 | search | value, range, result, found operands |
| Call | 0x2723 | 1 | 4 | call | subroutine name in field[1] |
| (0x2724?) | - | - | - | (return? not captured) | |
| For | 0x2725 | 1 | 4 | forloop | iteration count in field[0] |
| Next | 0x2726 | 1 | 1 | (next) | |
| End | 0x2727 | 1 | 1 | (end) | |
| RD | 0x2728 | 1 | 169 | receive | Both RTU and TCP same class; 169 pre-allocated fields |
| SD | 0x2729 | 1 | 411 | send | MODBUS send; 411 pre-allocated fields |
| Email | 0x2737 | 1 | 522 | (email) | 522 pre-allocated fields |

**Key Copy field layout (field[6] = copy_type_idx):**
| Copy variant | field[6] val | func_code (field[7]) |
|-------------|-------------|---------------------|
| Single | "0" | "8960" |
| Block | "1" | "8962" |
| Fill | "2" | "8976" |
| Pack | "3" | "8978" |

**Counter field layout (9 fields, 3 parts):**
- [0] done_bit (CT1), [1] setpoint, [2] current (CTD1), [3] completion_bit
- [4] type_idx: "0"=up, "1"=down, "2"=up+down
- [5-8] variant func codes (3x 0x3A05 sub-markers + 1 empty)

**Shift Register field layout (6 fields, 3 parts):**
- [0] start (C1), [1] end (C2), [2-4] variant func codes, [5] empty

## Phase 2: Reorganize — `instructions/` package

Migrate existing instruction logic into per-class-name modules:

```
src/laddercodec/instructions/
├── __init__.py          # Registry: class_name → module dispatch
├── contact.py           # "ContactNO" (0x2711-12) + "Edge" (0x2713) — all contacts
├── comparison.py        # "Compare" (0x2714) — comparison contacts
├── coil.py              # "Out" (0x2715-17) — all coil types + oneshot
├── timer.py             # "Tmr" (0x2718) — timers
├── raw.py               # RawInstruction — opaque blob passthrough
├── counter.py           # "Cnt" (0x2719) — counters (up/down/up+down)
├── math.py              # "Math" (0x271A) — decimal/hex math expressions
├── drum.py              # "Drum" (0x271B) — time/event sequencer drums
├── shift_register.py    # "SR" (0x2720) — shift register
├── copy.py              # "Copy" (0x2721) — single/block/fill/pack/unpack
├── search.py            # "Search" (0x2722) — array search
├── call.py              # "Call" (0x2723) — subroutine call
├── for_loop.py          # "For" (0x2725) — for loop
├── next_end.py          # "Next" (0x2726) + "End" (0x2727) — trivial 1-field
├── rd.py                # "RD" (0x2728) — MODBUS receive (RTU/TCP)
├── sd.py                # "SD" (0x2729) — MODBUS send
└── email.py             # "Email" (0x2737) — email send
```

Naming convention: files use Python domain names (contact, coil, timer), not Click
binary class names (ContactNO, Out, Tmr).  New modules follow this pattern.

Each module contains:
- **Model dataclass** (fields, from_csv_token, to_csv)
- **Func code tables** (forward + reverse lookups)
- **`build_blob()`** — encoder blob builder (from cell.py)
- **`parse_blob()`** — decoder blob parser (from decode.py)

What stays where:
- **cell.py** — ClickCell, preamble/terminal builders, build_row (structural)
- **encode.py** — pipeline orchestration (grid, segment flags, comments)
- **decode.py** — grid walking, row classification, comment extraction; dispatches to instructions/
- **model.py** — thin re-exports + shared types (InstructionType, operand validation)

## Phase 3: Implement batches

Work through in order of complexity. Each batch: model + blob builder + parser → golden test passes.

| Batch | Class(es) | Parts | Fields | Complexity | clickplc_reference |
|-------|-----------|-------|--------|------------|-------------------|
| 1 | Copy (0x2721) | 1 | 13 | All copy variants share one class — just field[6] discriminates | copy_single.md, copy_block.md, copy_fill.md, copy_pack.md, copy_unpack.md |
| 2 | Out oneshot | 1 | 6 | Confirm oneshot=field[2]="1" | coil_out.md |
| 3 | Cnt (0x2719) | 3 | 9 | Multi-row, variant func codes like Timer | counters.md |
| 4 | Search (0x2722) | 1 | 10 | Multi-row visually, single-part blob | search.md |
| 5 | SR (0x2720) | 3 | 6 | Multi-row, 3 variant func codes | shift_register.md |
| 6 | Math (0x271A) | 1 | 1010 | Expression encoding — many empty fields | math_decimal.md, math_hex.md |
| 7 | Call/For/Next/End | 1 | 1-4 | Simple control flow | call.md, for.md |
| 8 | Drum (0x271B) | 4 | 64 | Complex: 4-part, pattern matrix | drum_event.md, drum_time.md |
| 9 | RD (0x2728) | 1 | 169 | Comms: 169 pre-allocated fields | comm_receive_modbus_rtu.md, comm_receive_modbus_tcp.md |
| 10 | SD (0x2729) + Email (0x2737) | 1 | 411/522 | Comms: very large field counts | comm_send_modbus_rtu.md, comm_email.md |

### clickplc_reference integration

Each batch cross-references the corresponding reference doc for:
1. **Operand validation** — source/destination compatibility matrices
2. **Completeness** — all setup fields and option variants covered
3. **Field semantics** — correct naming, understanding what each field means

The reference does NOT tell us byte layouts, class names, or func codes — those come only from captures.

## Validation

- Each instruction module gets unit tests for CSV round-trip and blob round-trip
- Coverage golden tests (`test_coverage.py`) verify byte-exact match against Click captures
- `clicknick-rung guided FOLDER` does live paste verification for new fixtures
