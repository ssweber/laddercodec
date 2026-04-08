# Troubleshooting Encode Failures

When an encoded binary crashes Click on paste (or renders incorrectly), the problem is usually a structural byte difference in the cell grid — not the instruction blob content. This guide covers how to find it.

## Tools

| Tool | What it does |
|---|---|
| `devtools/inspect_bin.py` | Decodes a `.bin` and prints all instructions with `to_csv()` output. Good for checking logical correctness, but doesn't show structural bytes. |
| `inspect_cells()` | Dumps raw cell bytes, header fields, flags, and decoded tokens for specific cells. This is the primary debugging tool for encode failures. |

`inspect_cells` lives in `laddercodec.decode` (not yet in the public API — import it directly):

```python
from laddercodec.decode import inspect_cells

data = open("capture.bin", "rb").read()
dumps = inspect_cells(data, [(0, 0, "AF"), (0, 1, "AF"), (0, 2, "AF")])
for d in dumps:
    print(d)
```

The second argument is a list of `(rung_index, visual_row, column_letter)` tuples. Column is `"A"` through `"AE"` for conditions, `"AF"` for the output column.

Each `CellDump` has:

- `offset` — absolute byte position in the buffer
- `size` — cell size (0x40 for wire cells, larger for instruction cells)
- `flags` — `(segment, right, down)` from `+0x19/+0x1D/+0x21`
- `token` — decoded instruction or wire token
- `raw` — full cell bytes
- `hex()` — formatted hex dump

## Workflow

### 1. Get a native capture

Paste the same rung shape manually in Click, then copy it back to get a native `.bin`. This is your ground truth. The native capture can come from `clicknick-rung guided` or by manually copying from Click's clipboard (format 522).

### 2. Compare with inspect_cells

Run `inspect_cells` on both the native capture and your encoded output. Focus on the AF column and any instruction cells:

```python
from laddercodec.decode import inspect_cells

native = open("native.bin", "rb").read()
ours = open("encoded.bin", "rb").read()

cells = [(0, r, "AF") for r in range(3)]

for label, data in [("NATIVE", native), ("OURS", ours)]:
    print(f"\n=== {label} ===")
    for d in inspect_cells(data, cells):
        hdr = d.raw[:0x25]
        print(f"[{d.row}][{d.col}] size={d.size} flags={d.flags}")
        print(f"  row_span={hdr[0x09]} vis_rows={hdr[0x0A]}")
        print(f"  instr_idx={int.from_bytes(hdr[0x0D:0x11], 'little', signed=True)}")
        print(f"  tail: {d.raw[-16:].hex(' ')}")
```

### 3. What to look for

The cell header is 0x25 (37) bytes. Key fields:

| Offset | Field | Notes |
|---|---|---|
| +0x01 | column | 4-byte LE, should match the column index |
| +0x05 | global_row | 4-byte LE, `row + 1` (varies by rung position — ok to differ) |
| +0x09 | row_span | How many grid rows this cell occupies |
| +0x0A | visual_rows | Visual sub-row count (1 = normal, 2 = timer, 3 = retained timer) |
| +0x0D | instr_index | 4-byte LE signed. `-1` (0xFFFFFFFF) for data cells |
| +0x15 | contact_flag | 4-byte LE |
| +0x19 | segment | 4-byte LE — load-bearing flag |
| +0x1D | wire_right | 4-byte LE |
| +0x21 | wire_down | 4-byte LE |

After the header: instruction blob (variable length), then a 16-byte tail.

**Size differences** are the most important signal. If a cell has unexpected extra bytes, the blob length formula is probably wrong for that instruction type.

**Flag differences** (segment, wire_right, wire_down) can cause visual corruption but usually don't crash Click.

**Tail differences** are usually cosmetic (rung index encoding, row hints).

### 4. Don't bother with hex diffs

Raw `xxd` / hex diffs of the two binaries are nearly useless because:

- The global header (0x0000–0x0253) contains file paths, font tables, and MDB data that differ between every capture.
- Instruction cells are variable-length, so a single size difference shifts every subsequent byte.
- Comment RTF formatting varies slightly (e.g. `\par ` vs `\r\n\par `), shifting the entire grid region.

`inspect_cells` handles all of this — it walks the variable-length grid correctly and gives you per-cell structural data.

## Known pitfalls

### Tall instruction visual_rows

The byte at cell offset +0x0A (`visual_rows`) is not always the same as the instruction's `cell_params()["visual_rows"]`. For instructions with pin rows (retained timers, counters, shifts, drums), the native binary may use a different value that accounts for the pin rows.

If your instruction cell is the right size but Click still renders it wrong, compare +0x09 and +0x0A against the native capture.

### Payload space slots

The 31 slots between the rung preamble (0x0260) and the cell grid (0x0A60) contain structural bytes that differ between our encoder and native Click. These differences are tolerated — Click reads them but doesn't crash on mismatches. Don't chase these.
