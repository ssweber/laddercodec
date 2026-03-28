# Binary Format

This page documents the Click clipboard binary format as reverse-engineered from native captures. All offsets are hexadecimal.

## Buffer layout

The clipboard buffer has three regions:

```
0x0000 +-----------------------+
       | Global header         |  Fixed template data. Not modified by the encoder.
0x0254 +-----------------------+
       | Program header        |  Single 0x40-byte struct. Row count at +0x00.
0x0294 +-----------------------+
       | Payload region        |  Comment RTF body (variable length, may be empty).
       |                       |  When empty, this region is zero-length and the
       |                       |  grid starts immediately at 0x0A60.
0x0A60 +-----------------------+  <-- grid start (in no-payload buffer)
       | Cell grid             |  32 cells/row x 0x40 bytes/cell = 0x800 bytes/row.
       |                       |  Pushed forward by payload_len when a comment exists.
       +-----------------------+
       | Page padding          |  Zero-filled to next 0x1000 (4096) boundary.
       +-----------------------+
```

## Global header (0x0000–0x0253)

Fixed template data loaded from the scaffold binary. Contains GUI state and format markers. The encoder does not modify this region.

## Program header (0x0254–0x0293)

A single 0x40-byte structure:

| Offset | Size | Field | Value |
|---|---|---|---|
| +0x00 | 2B | row_word | `total_grid_rows * 0x20` |
| +0x02 | ... | (other) | GUI state, not load-bearing for paste |

`total_grid_rows` includes data rows for all rungs, preamble rows for rungs 1+, and one terminal row. For a single N-row rung: `total_grid_rows = N + 1`.

## Rung preamble

Every rung has a 0x40-byte preamble that holds its comment data:

| Rung | Location |
|---|---|
| Rung 0 | Fixed at 0x0260 (inside program header region, not in cell grid) |
| Rung N>0 | Cell 0 of the preamble row preceding the rung's data rows |

Comment fields within the preamble:

| Offset | Size | Field |
|---|---|---|
| +0x30 | 1B | Comment flag (1 = has comment) |
| +0x34 | 4B | Comment body length (uint32 LE) |
| +0x38 | var | Comment body (RTF) |

## Payload region and the push model

When rung 0 has a comment, the RTF body is inserted at 0x0298 (preamble +0x38). This **pushes the cell grid forward** by `payload_len` bytes — everything after the insertion point shifts.

The encoder writes wire flags to cell grid positions computed from the no-payload base offset (0x0A60). Because the insertion happens after flag writing, the flags land at the correct absolute addresses in the final buffer.

Buffer size formula: `pad_to_page(GRID_FIRST_ROW_START + rows * GRID_ROW_STRIDE + payload_len)`, rounded up to the next 0x1000 boundary.

## Comment sizing

- Maximum comment body: 1400 bytes (enforced by the encoder)
- The practical limit per row count depends on where `minimal_end + payload_len` crosses a page boundary
- Example: 2-row rung — body up to 1324 bytes stays at 0x2000 total; 1325+ bumps to 0x3000

### RTF envelope

Comments are stored as RTF with a fixed prefix and suffix:

```
{\rtf1\ansi\deff0{\fonttbl{\f0 Tahoma;}}
{\colortbl ;\red0\green0\blue0;}
\f0\fs16\cf1 <body> }
```

Body encoding:

- Plain text: cp1252-encoded directly
- Bold: `{\b text}`
- Italic: `{\i text}`
- Underline: `{\ul text}`
- Multi-line: `\par ` between lines (not `\line`)

## Cell grid

The cell grid starts at 0x0A60 (before any payload push). Each row is 0x800 bytes (32 cells x 0x40 bytes per cell). Columns 0–30 are condition columns (A–AE); column 31 is the AF (output) column.

### Cell structure (wire/blank cells)

Wire and blank cells are exactly 0x40 bytes: a 0x25-byte header, 0x0B bytes of padding, and a 16-byte tail.

**Header (0x25 bytes):**

| Offset | Size | Field |
|---|---|---|
| +0x00 | 1B | Always 0x00 |
| +0x01 | 4B | Column index (uint32 LE) |
| +0x05 | 4B | Row byte (uint32 LE, `global_row + 1`) |
| +0x09 | 1B | Row span (0x01 for single-row, 0x02+ for multi-row AF) |
| +0x0A | 1B | Visual sub-rows (0x01 for single-row, 0x02+ for timers) |
| +0x0B–0x0C | 2B | Structural: +0x0C = 0x01 in wire-only rungs, 0x00 in instruction-bearing rungs |
| +0x0D | 4B | Instruction index (int32 LE; 0xFFFFFFFF for data cells) |
| +0x11 | 4B | Structural flag (always 0x00000001) |
| +0x15 | 4B | Enable/contact flag (uint32 LE) |
| +0x19 | 4B | Segment flag (uint32 LE) |
| +0x1D | 4B | Right flag (uint32 LE) |
| +0x21 | 4B | Down flag (uint32 LE) |

**Tail (16 bytes, at +0x30):**

| Offset | Field |
|---|---|
| +0x08 | Marker (0x01 for condition cells and non-last-row AF data cells) |
| +0x09 | Rung index |
| +0x0C | Instruction count (AF data cell, last row of last rung only) |
| +0x0D | Row hint (condition: `local_row + 1`; AF last rung: `local_row + 2`) |

### Cell structure (instruction cells)

Instruction cells are **composite**: they carry wire flags (right=1 for contacts, right+down for T-junction contacts) with instruction data layered on top. The cell is variable-length: 0x25-byte header + instruction blob + 16-byte tail. See [instruction blobs](instruction-blobs.md) for the blob format.

### Cell boundary detection

To walk a variable-length grid, detect cell boundaries by signature:

- `+0x00 == 0x00`
- `+0x01 == col` (expected column index)
- `+0x05 == row_byte` (expected row)
- `+0x09 == 0x01`
- `+0x0A == 0x01`

Do **not** use `+0x0D` for detection — it varies between 0x00, 0x01, and 0xFF across cell types.

## Multi-rung format

Multi-rung buffers are **not** concatenated single-rung buffers. They share a single global header and program header, with interleaved data and preamble rows in one cell grid:

```
[rung 0 data rows] [rung 1 preamble row] [rung 1 data rows] [rung 2 preamble row] ... [terminal row]
```

The program header's row_word reflects the total grid row count across all rungs.

Only rung 0's comment payload lives in the payload region (pushed at 0x0298). Rung N>0 comments are stored inline in their preamble row's cell 0, at the same +0x30/+0x34/+0x38 offsets.

## Page alignment

All buffers are padded with zero bytes to the next 0x1000 (4096 byte) boundary. The minimum buffer size for a 1-row rung with no comment is 0x2000 (8192 bytes).

## Empty multi-row synthesis

Empty rung buffers for N rows (1..32) are synthesized deterministically from a minimal scaffold binary. Payload length formula:

```
payload_len = 0x1000 * (ceil((rows + 1) / 2) + 1)
```

This produces the correct buffer for any row count without needing 32 separate template files.
