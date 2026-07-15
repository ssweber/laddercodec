# Binary Format

This page documents the Click clipboard binary format as reverse-engineered from native captures. All offsets are hexadecimal.

## Buffer layout

The clipboard buffer has these regions:

```
0x0000 +-----------------------+
       | Global header         |  Fixed template data. Not modified by the encoder.
0x0254 +-----------------------+
       | Program header        |  Row count word at +0x00.
0x0260 +-----------------------+
       | Rung 0 preamble       |  Comment flag +0x30, length +0x34.
0x0298 +-----------------------+
       | Payload region        |  Comment RTF body (variable length, may be empty).
       |                       |  When empty, this region is zero-length and the
       |                       |  grid starts immediately at 0x0A60.
0x0A60 +-----------------------+  <-- grid start (in no-payload buffer)
       | Cell grid             |  32 cells/row. Wire-only rows: 0x800 bytes/row.
       |                       |  Instruction rows are larger (variable-length cells).
       |                       |  Pushed forward by payload_len when a comment exists.
       +-----------------------+
       | Page padding          |  Zero-filled to next 0x1000 (4096) boundary.
       +-----------------------+
```

## Global header (0x0000–0x0253)

Fixed template data loaded from the scaffold binary. Contains GUI state and format markers. The encoder does not modify this region.

## Program header (0x0254–0x025F)

A 12-byte structure immediately before the rung 0 preamble:

| Offset | Size | Field | Value |
|---|---|---|---|
| +0x00 | 2B | row_word | `total_grid_rows * 0x20` |
| +0x02 | ... | (other) | GUI state, not load-bearing for paste |

`total_grid_rows` includes data rows for all rungs, preamble rows for rungs 1+, and one terminal row. For a single N-row rung: `total_grid_rows = N + 1`.

## Rung preamble

Every rung has a 0x40-byte preamble that holds its comment data:

| Rung | Location |
|---|---|
| Rung 0 | Fixed at 0x0260 (between program header and cell grid) |
| Rung N>0 | Cell 0 of the preamble row preceding the rung's data rows |

Comment fields within the preamble:

| Offset | Size | Field |
|---|---|---|
| +0x30 | 1B | Comment flag (1 = has comment) |
| +0x34 | 4B | Comment body length (uint32 LE) |
| +0x38 | var | Comment body (RTF) |

## Payload region and the push model

When rung 0 has a comment, the RTF body is inserted at 0x0298 (preamble +0x38). This **pushes the cell grid forward** by `payload_len` bytes — everything after the insertion point shifts.

The encoder builds the grid as a byte blob (concatenated cell objects) appended to the header. The insertion at 0x0298 pushes the grid bytes forward by `payload_len`, so everything lands at the correct absolute addresses in the final buffer.

The final buffer is padded to the next 0x1000 boundary. For wire-only rungs, the pre-padding size is `GRID_FIRST_ROW_START + rows * GRID_ROW_STRIDE + payload_len`. Instruction cells are variable-length, so rows with instructions exceed the 0x800-byte baseline.

## Comment sizing

- Maximum comment body: 1400 bytes (enforced by the encoder)
- The practical limit per row count depends on where `minimal_end + payload_len` crosses a page boundary
- Example: 2-row rung — body up to 1324 bytes stays at 0x2000 total; 1325+ bumps to 0x3000

### RTF envelope

Comments are stored as RTF with a fixed prefix and suffix:

```
{\rtf1\ansi\ansicpg1252\deff0\deflang1033{\fonttbl{\f0\fnil\fcharset0 Arial;}}
\viewkind4\uc1\pard\fs20 <body>
\par }
```

Body encoding:

- Plain text: cp1252-encoded directly
- Bold: `{\b text}`
- Italic: `{\i text}`
- Underline: `{\ul text}`
- Multi-line: `\par ` between lines (not `\line`)

## Cell grid

The cell grid starts at 0x0A60 (before any payload push). Each row has 32 cells. Wire-only rows are 0x800 bytes (32 x 0x40). Rows with instruction cells are larger because instruction cells are variable-length. Columns 0–30 are condition columns (A–AE); column 31 is the AF (output) column.

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
payload_len = 0x1000 * ((rows + 1) // 2 + 1)
```

This produces the correct buffer for any row count without needing 32 separate template files.

## Instruction blob tag wire types

Instruction blobs use tagged fields where each tag is a 2-byte LE value. The tag's **high byte** encodes the wire type — i.e. how many bytes follow the tag and how to interpret them:

| High byte | Wire type | Payload |
|---|---|---|
| 0x11, 0x12 | flag | No payload (tag presence is the signal) |
| 0x20, 0x21, 0x22 | byte | 1 byte |
| 0x32 | u16 | 2 bytes (uint16 LE) |
| 0x3A | variant_u16 | Sequence of `[uint16 index, uint16 value]` pairs, terminated by 0xFFFF |
| 0x60, 0x61, 0x62 | string | `[1B length][UTF-16LE value]` |
| 0x68 | variant_string | Sequence of `[uint16 index, 1B length, UTF-16LE value]` entries, terminated by 0xFFFF |

This rule applies identically to both clipboard and SCR instruction blobs — the tag IDs, wire types, and operand values are the same in both formats. Only the framing differs (see below).

## Clipboard vs SCR framing

The instruction blob content (tag IDs, operand values, wire types) is **identical** between clipboard and SCR formats. The difference is how blobs are framed:

**Clipboard:** blobs are embedded in the cell grid. Each instruction cell is a 0x25-byte cell header + blob + 16-byte cell tail. The blob boundary is found by scanning tagged fields (no explicit length). The 4-byte sentinel `FFFFFFFF` precedes each string value.

**SCR (Scr\*.tmp):** blobs are stored in instruction sections with explicit framing. Each blob has embedded cell-header fields and an `end_offset` pointer:

```
[1B class_name_len][UTF-16LE class_name][2B type_code]
[1B row_span][1B pad][2B structural][2B instr_index][1B visual_sub_rows]
[visual_sub_rows counting bytes][4B end_offset]
[tagged fields...]
```

The embedded fields at offsets +0 through +6 after the type code correspond to clipboard cell header offsets +0x09 through +0x10. The `end_offset` is an absolute file pointer to the blob boundary — the same boundary that clipboard's `find_blob_boundary()` derives by scanning tags. Tags use length-prefixed strings (no `FFFFFFFF` sentinel).

The byte at `end_offset` is a 1-byte trailer length (observed 0 or 1): the next structure starts at `end_offset + 2 + data[end_offset]`. Certain instruction encodings (`RD`/`SD` always; `Copy`/`Math`/`Out`/`Drum` sometimes) emit a 1-byte trailer whose value is opaque.

## SCR rung records

An SCR file is a header followed by one rung record per rung, in order, parseable with a single forward cursor:

```
RUNG = [2B rung_index]        -- 1-based ordinal; asserted sequential
       [4B rtf_len][rtf body] -- comment; rtf_len = 0 means none
       TOPOLOGY               -- row-topology block (below)
       [2B instr_count]       -- 0 = empty rung (nothing follows)
       [4B section_marker]    -- only when instr_count > 0
       instr_count x ENTRY    -- 8-byte header + blob (see framing above)
ENTRY  = [1B row_1based][1B col][1B b2][1B b3][1B entry_seq][3B 00] + blob
```

Rung 0 carries a 7-byte file prelude instead of `rung_index`: `[2B file_marker][0d][4B total_rung_records]`. `file_marker` equals the per-file `section_marker` constant (opaque; validation magic only), and `total_rung_records` counts every rung record in the file.

Programs end with 1–4 ordinary content-less rungs (the empty editor rungs below the last programmed rung; some carry a fully-wired row) — the decoder drops trailing records with no instructions and no comment. Files with `prog_idx == 1` (the main program) carry a 2-byte tail after the last record; subroutines end exactly at the last record.

## SCR row-topology blocks

SCR files store per-rung wire topology in structured blocks that precede each rung's instruction section. Each block encodes the right-wire and segment-flag data that clipboard stores per-cell in the grid.

```
[2B row_word][03 00 00]         -- 5-byte header; row_word = stored rows + 1
{ row block } x (row_word - 1)  -- one per grid row, in row order (row 0 first)
[20 00]                         -- end marker
[wire-down table]               -- exactly 32 column entries (see below)
```

Every row block — including row 0's — has the same uniform format:

```
[1B flag][1B count][00]  +  count x ([1B seg][1B col])
```

- `flag` — the +0x19 segment flag of the row's AF (col 31) cell. 1 for normal output/coil/NOP rows, 0 for tall segment-0 instructions (timer/counter/drum).
- `count` — number of right-wired cells on the row (condition cells plus AF when present). `count = 0` is an empty row: the 3-byte block `[flag][00][00]`.
- Each entry pairs a cell's +0x19 segment flag with its column index (0–31, 31 = AF). Entries are **placement-ordered** — the column sequence is usually ascending but not guaranteed (native captures include orders like `[6,1,0,3,2,4,5]`), so columns must be treated as a set.

A row block whose entries include col 0 with every condition-cell seg = 1 carries the grid-row-0 signature (row 0 is exempt from the per-row segment boundary). SCR can retain orphaned wire rows *above* the true row 0 — editor debris under a tall instruction box — which Click's own clipboard copy omits; the decoder drops non-empty stored rows preceding the first row with the row-0 signature.

The wire-down table after the `20 00` marker has exactly one entry per column 0–31:

```
no down wires: [00 00]
down wires:    [1B count][00][count x 1-based row index]
```

This table is the SCR serialization of the per-cell down flag (+0x21) that clipboard stores on each cell — it lists every down wire, including those carried by contact cells (rendered as a `T:` prefix, see [wire rendering](wire-rendering.md)). It is therefore a superset of the visible `T`/`|` wire tokens.
