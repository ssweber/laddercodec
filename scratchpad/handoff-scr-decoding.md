# Handoff: SC-SCR Temp File Decoding

## Status

This note is now **historical context**, not the current source of truth.

Use these instead for the current state of SCR decoding:
- `src/laddercodec/decode_scr.py`
- `tests/ladder/test_decode_scr.py`
- `scratchpad/pickup-scr-decode-coverage.md`

The sections below are still useful for header / section / blob framing, but
parts of the topology discussion are outdated.

Known outdated areas:
- The multi-row / extra-row flag description is superseded by the newer
  continuation-row topology work.
- Continuation rows are **not** just the older made-up sparse flag map; SCR
  stores explicit right-wire column blocks that we now parse directly.
- Some "fully working" status claims reflect the decoder state at the time this
  handoff was written, not the current implementation.

## Goal

Decode Click Programming Software's internal temp files (`Scr1.tmp`, `Scr2.tmp`) into the same `Rung` objects that our clipboard decoder produces. These files live in e.g. `C:\Users\Sam\AppData\Local\Temp\CLICK (008B0E8C)\Scr*.tmp` — one per program (main, subs).

## Why

- SCR files are ~17x smaller than clipboard binaries (compact format, no cell grid)
- They represent the full program as stored on disk, not just a clipboard copy
- Decoding them enables reading `.ckp` project files directly (each program unpacks to a Scr*.tmp)

## Reference Files

All in `C:\Users\Sam\Documents\GitHub\clicknick\`:
- `scr1.csv` / `scr1.bin` — Main Program, 114 rungs, every instruction type (872KB clipboard, 51KB SCR)
- `scr2.csv` / `scr2.bin` — coverage_sub subroutine, 3 rungs (16KB clipboard, 1.2KB SCR)

The SCR tmp files are at:
- `C:\Users\Sam\AppData\Local\Temp\CLICK (008B0E8C)\Scr1.tmp` (51394 bytes)
- `C:\Users\Sam\AppData\Local\Temp\CLICK (008B0E8C)\Scr2.tmp` (1200 bytes)

**Validation**: `devtools/validate_scr.py` decodes the clipboard .bin, writes CSV, diffs against reference CSV. Both scr1 and scr2 produce **PERFECT MATCH** (114 rungs / 250 lines, 3 rungs / 6 lines).

## Current Walker Status — FULLY WORKING

`walk_scr.py` now correctly parses both files:

- **Scr2.tmp**: 4 entries (3 rungs + sentinel), 4 instructions
- **Scr1.tmp**: 114 rungs (113 + sentinel), **237 instructions** — all found, all comments correct

### Architecture: Anchor-Based (not sequential)

The walker uses a two-phase approach:

1. **Phase 1 (pre-validation)**: Scan the entire file for `[u16 count] [90 00 00 00]` instruction section headers. For each candidate, validate by parsing ALL `count` blobs using `parse_blob()`. Only sections where every blob parses successfully are kept. This eliminates false positives completely.

2. **Phase 2 (anchor matching)**: For each validated section, scan backwards to find:
   - Its **row header** (`[u16 row_word] [03 00 00 01 20 00]` signature) — gives row count
   - Its **RTF comment** (`{\rtf1` signature) — gives rung comment text

This avoids sequential walking entirely, which was fragile due to:
- Variable-length gaps between row headers and instruction sections (multi-row rungs)
- Off-by-one in blob `end_offset` terminators (some blobs have `01 00` instead of `00 00`)
- False-positive row header signatures in instruction blob data

### Key Numbers

- 113 valid instruction sections found in Scr1.tmp
- 7 headerless sections (rungs with no row header, like `next()` after `for()`, shift register, drum sequencer)
- 107 sections matched to row headers
- 1 terminal sentinel (row header with no section)

## Existing Analysis Scripts

In `laddercodec/devtools/`:
- **`walk_scr.py`** — anchor-based structural walker, fully working
- `inspect_scr.py` — annotated hex dump of SCR file, finds RTF comments and instruction blobs
- `compare_blobs.py` — side-by-side SCR vs CLIP instruction blob comparison
- `diag_blob.py` — diagnostic for multi-row gap analysis and section boundary tracing
- `validate_scr.py` — clipboard decode → CSV → diff against reference
- `analyze_scr.py` — earlier analysis script

## SCR File Format (Reverse-Engineered)

### Magic & Header

```
0x0000: "SC-SCR  " (8 bytes)
0x000A: u16le version (0x035A)
0x0040: u16le program_index (1=Main, 2+=subs)
0x0042: u8 name_byte_count
0x0043: UTF-16LE program name (byte_count bytes, single null terminator)
```

After name:
```
u16le cols_per_row (always 32)
[optional extra u16le fields — Main has one extra (0xCC=204, possibly rung count)]
[N × u16le 0x0041 column type entries ('A' in UTF-16LE)]
```

### Initial 0x90 Prefix (before rung 0)

```
u16le 0x0090 (marker)
u8    mystery_byte (0x0D observed)
u32le unknown_value
```

Then falls into the per-rung data.

### Per-Rung Structure

Each rung contains (in file order):

```
1. [u32le rtf_len] [RTF body bytes...]                         ← optional comment (rung 0 has no u16 rung_idx prefix; rungs 1+ have [u16 rung_idx] before the u32)
2. [u16le row_word] [03 00 00 01 20 00]                        ← row header (row_word = logical_rows + 1)
3. [variable per-row flag data]                                 ← column wire flags, multiple blocks for multi-row
4. [u16le instr_count] [90 00 00 00]                            ← instruction section header
5. Per instruction:
     [8 or 9 byte position header] [instruction blob]
```

### Rung Boundary Marker

Between rungs (after instruction section, before next rung's comment):
```
[u16le rung_idx] [u32le rtf_len] [RTF body if rtf_len > 0]
```

**Important**: Some blobs have `01 00` at their `end_offset` position instead of the expected `00 00`. This makes the boundary marker start 1 byte later than `end_offset + 2`. The anchor-based walker avoids this issue entirely by scanning backwards from sections rather than forward from boundaries.

### Headerless Rungs

Some rungs (notably `next()` after `for()`, and some drum/shift register rungs) have **no row header** — just a bare instruction section. These are single-row rungs that are implicitly all-wired. The walker finds 7 of these in Scr1.tmp.

### Multi-Row Rung Flag Data

Multi-row rungs (row_word > 2) have variable-length flag data between the row header and instruction section. The structure depends on whether extra rows have wires:

**Standard case (no wires on extra rows):**
- 64-byte column flag block (row 0 flags)
- 2-byte trailing marker
- 64-byte zero spacer
- `3 * (rows - 1)` bytes of zeros
- Then instruction section

**Wired extra rows:**
Each wired extra row adds a ~67-byte block containing:
```
[u8 col_count (0x1F=31)] [col_count × (u8 col_idx, u8 flag)] [padding] [u16 0x0020 marker] [64 zero bytes]
```

The gap formula: `base + 62 * k` where base = `130 + 3*(rows-1)` and k = number of wired extra rows.

Observed gaps:
| rows | no-wire gap | per wired row | examples |
|------|------------|---------------|----------|
| 2    | 133        | +62           | 133, 195 |
| 3    | 136        | +62           | 136, 198, 260 |
| 4    | 139        | +62           | 139, 325 (=139+186=3×62) |

## Instruction Blob Format (SCR)

Each blob:
```
[u8 byte_len] [UTF-16LE class_name + single \0]     ← length-prefixed class name
[u16le instruction_type]                              ← same codes as clipboard (0x2711, 0x2715, etc.)
[6 zero bytes] [u8 m1 (row_height)]                   ← m1 bytes follow: 01 02 ... m1
[u32le end_offset]                                    ← file-absolute: blob data extends to here
[tagged fields...]                                    ← tag ID + length-prefixed operand strings
```

**Critical**: `end_offset` is file-absolute. The data between the m1 sequence and end_offset contains tagged fields. The next structure starts at `end_offset + 2` (usually `00 00` bytes, but sometimes `01 00`).

### Position Header (before each blob)

Each instruction has an 8-byte or 9-byte header before the blob:
```
8-byte: [u8 flag] [u8 col_idx] [01 01] [u32le ???]
9-byte: [u8 extra] [u8 flag] [u8 col_idx] [01 01] [u32le ???]
```
Column index gives the grid position (0=A, 1=B, ..., 30=AE, 31=AF).

### SCR vs CLIP Blob Differences

| Feature | SCR (tmp) | CLIP (clipboard) |
|---|---|---|
| Class name | `[u8 len] UTF-16LE + 1×\0` | `UTF-16LE + \0\0` (double null) |
| After type marker | 6 zeros + m1 + m1 bytes + `u32 end_offset` | Variable metadata bytes |
| Tagged field values | `[u16 tag] [u8 str_len] UTF-16LE string` | `[u16 tag] [FFFFFFFF sentinel] UTF-16LE string` |
| Tag IDs | Same (`0x6065`, `0x6066`, etc.) | Same |
| Operand content | Same (`C233`, `C234`, `DS7`, etc.) | Same (but CLIP has extra system fields) |

### Known Class Names (from Scr1.tmp)

ContactNO(113), Copy(29), Out(23), RD(13), SD(13), Search(8), Drum(7), Compare(6), Edge(5), Math(3), Tmr(3), Cnt(3), For(2), Next(2), SR(1), Call(1), End(1), Email(1), Home(1), Velocity(1), Position(1), Return(3) — **237+3=240 total blobs across both files**

## Next Steps

### 1. Build `decode_scr()` function

New module `src/laddercodec/decode_scr.py` returning `list[Rung]`. The walker's anchor-based architecture translates directly:

```python
def decode_scr(data: bytes) -> list[Rung]:
    sections = find_valid_sections(data)
    rungs = []
    for sec_off, count, sec_end in sections:
        rh = find_row_header_before(data, sec_off)
        comment = find_rtf_before(data, rh or sec_off)
        instructions = parse_section_blobs(data, sec_off, count)
        # Build Rung from instructions + wire flags + comment
        rungs.append(...)
    return rungs
```

### 2. SCR tagged field parser

New helper in `binary_helpers.py`: `_parse_scr_tagged_fields()` that reads `[u16 tag] [u8 len] [UTF-16LE string]` instead of sentinel-terminated.

### 3. Wire reconstruction

SCR column flags give the wire pattern per row (01=dash, 00=empty). Combined with instruction column positions, this reconstructs the full condition grid.

### 4. Validate round-trip

`decode_scr(scr_data)` should produce identical `Rung` objects to `decode(clipboard_data)` for the same program. Compare against the validated CSV from `validate_scr.py`.

## Key Observations

- The SCR format is essentially **our CSV format in binary** — wire flags per column (= dashes), instruction blobs only for non-empty cells, RTF comments per rung
- The CLIP clipboard format **expands** this into a full 32×0x40 cell grid with page alignment
- Instruction TYPE codes and TAG IDs are shared between formats — the knowledge in `instructions/` modules applies to both
- The `end_offset` field in each blob is the key to reliable parsing — it's a file-absolute pointer
- The anchor-based approach (find sections first, then match structure backwards) is fundamentally more robust than sequential walking — it tolerates variable gaps, off-by-one terminators, and false-positive signatures
