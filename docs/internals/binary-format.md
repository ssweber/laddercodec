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
| +0x15 | 4B | Row-start flag: stored row bit 0 at column A, zero elsewhere (uint32 LE) |
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

## SCR header

After the `SC-SCR  ` magic and opaque header bytes, offset `0x40` holds the u16 program index. Offset `0x42` is the byte length of the following UTF-16LE name. Immediately after the name:

```
[u16 column_count]
column_count x [u16 numeric column_width]  -- includes AF
[u8 display_flags]
[u16 rung_count]
rung_count x RUNG
```

Widths resembling UTF-16 letters are numeric widths, not condition-family codes. The final width belongs to AF; it is not a file marker. The display byte contains independent settings:

| Mask | Setting |
|---|---|
| `0x01` | Nicknames |
| `0x02` | Address Comments |
| `0x04` | Rung Comments |
| `0x08` | Freeze Pane Coil Area |

The common value `0x0D` enables nicknames, rung comments, and the frozen coil area. It is not a delimiter. Header parsing retains the byte internally without requiring a particular setting; the public `Program` model exposes the name, index, and semantic rungs, not editor display settings.

## SCR rung records

Every rung, including rung zero, has the same framing:

```
RUNG = [u16 rung_index]       -- zero-based ordinal, asserted sequential
       [u32 rtf_len][rtf body]
       TOPOLOGY
       [u16 instr_count]     -- 0 = no instruction section
       [u32 section_marker]  -- only when instr_count > 0; opaque
       instr_count x ENTRY
ENTRY = [u8 stored_row][u8 col][u8 b2][u8 b3][u8 entry_seq][3B opaque] + blob
```

Instruction rows start at one because stored row zero is the special comment/preamble row. Blob pointers and trailer lengths determine the next entry position (see above). The apparent old u32 rung count was the u16 count followed by rung zero's u16 index.

Files with `prog_idx == 1` have a two-byte tail after the last rung; subroutines end at the last record. The parser enforces the declared count, sequential indices, and final cursor. Malformed framing raises an offset-bearing error; it never searches for a later rung to resume decoding.

CLICK keeps trailing content-less editor rungs, sometimes fully wired. The decoder parses them and then omits trailing records with neither instructions nor a raw comment. This existing semantic-output policy is separate from structural parsing.

## SCR row-topology blocks

```
[u16 stored_row_count]       -- includes the special first row
stored_row_count x ROW
[u16 down_column_count]     -- normally 32; a count, not an end marker
down_column_count x DOWN_LIST

ROW = [u8 row_flags][u16 entry_count]
      entry_count x [u8 segment][u8 column]

DOWN_LIST = [u16 count][count x u8 stored_row_index]
```

The first stored row is the comment/preamble row. CLICK initializes it with flags 3 and the next ordinary row with flags 1. `03 00 00` means flags 3 and zero entries; `03 20 00` means flags 3 and 32 entries. Both are ordinary instances of the counted grammar. The latter occurs in `tumbler/subroutines/Rotate.scr`, where the former decoder incorrectly invoked recovery.

Rows retain their flags and placement-ordered entries in the internal parser. Native column orders include `[6,1,0,3,2,4,5]`; order must not be required to ascend. The semantic rung builder uses the column set for wire presence.

| SCR data | Clipboard field | Meaning established by native writer |
|---|---|---|
| Ordinary row flags bit 0 | `+0x15` | Set only in column A when the row bit is set |
| Entry segment bit 0 | `+0x19` | Copy the persisted bit for that column |
| Column occurs in row entries | `+0x1D` | Right wire is present |
| Row occurs in column's down list | `+0x21` | Down wire is present |

The row flag is **not** the AF segment flag. Row flags bit 1 is also serialized; the special first row has this bit set, but its complete editing semantics remain uncharacterized. The parser accepts both low row bits. Entry flags currently support bit 0.

Down lists refer to stored row indices starting at one. The decoder subtracts one to obtain ordinary grid coordinates, and rejects zero or out-of-range references. These lists include down wires carried by contact cells, so they cover more than visible `T`/`|` wire tokens.

### Stored rows and canonical output

Ordinary stored rows map directly to grid rows. The decoder preserves their positions and horizontal and vertical connections. Row and segment flags do not determine whether a row exists.

Instruction placement is separate from stored wire entries: an instruction can occupy a cell without a right-wire entry. An AF right-wire becomes a `NOP` only when no instruction occupies or covers that cell. Covered NOPs are omitted from the decoded instructions; the surrounding wiring remains.

The public `Rung` model retains instructions and wire geometry, but does not retain raw row or segment flags. Re-encoding constructs flags using the conventions in [wire rendering](wire-rendering.md), so it does not preserve every byte of native editor state. Trailing records without instructions or comments are omitted from the decoded program.

### Native evidence

These corrections were checked against CLICK Ver3.92's native x86 `CLICK.exe` on 2026-09-10 (SHA-256 `E31A8130BC6D6261BAC841AF3062DAB70DD68B4307A1B3B58DA37F994C6FE13A`). Addresses are preferred-image virtual addresses, image base `0x400000`:

- Program writer `0x5A77F0`: numeric widths at `0x5A791C` with scaling at `0x5A794B`; display bits at `0x5A79D5`; u16 rung count backpatch at `0x5A7B9B`; u16 rung indices at `0x5A7AD0`.
- Display toggle handlers `0x5BF360/0x5BF430/0x5BF500/0x5B1A00` toggle the four serialized fields. MFC command IDs `0x8036/0x802D/0x8095/0x8090` and executable string resources supply the setting names above.
- Rung serializer `0x61C540`: stored row count at `0x61C637`, row flags at `0x61C66F`, u16 entry counts at `0x61C6DD`, pair bytes at `0x61C754/0x61C795`, down-column count at `0x61C7F7`.
- Clipboard writer `0x5BC2F0`: row-bit/column-A tests at `0x5BC4DB/0x5BC4E1`, entry bit at `0x5BC54B`, right presence at `0x5BC552`, down-list matching from `0x5BC5B4`. Native record origins are eight bytes before this document's clipboard cell origins.

The investigation walked 39 SCR files / 704 records without resynchronization. Comparing four flag mappings at 46,208 cell positions found no mismatches outside the synthetic time_drums pair. These are static-binary and fixture results, not a new live paste/reopen validation. `InstCtl_Drum.dll` confirms a four-row instruction footprint; it does not establish the disputed row-removal behavior.
