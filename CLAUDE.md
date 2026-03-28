# CLAUDE.md

**IMPORTANT: Don't use `cd` before commands. The working directory is already set to the project root.**
**IMPORTANT: Always use `make` commands, not direct `uv run` commands.**

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

**laddercodec** is a pure-Python binary codec for AutomationDirect CLICK PLC ladder clipboard format. It encodes and decodes the native clipboard binary used by CLICK Programming Software (v2.60–v3.80). Zero runtime dependencies. Licensed MPL-2.0.

Extracted from [clicknick](https://github.com/ssweber/clicknick) as a standalone library.

## Build & Development Commands

```bash
make                # install + lint + test (default)
make install        # uv sync --all-extras --dev
make lint           # ruff (check + format) + ty
make test           # pytest (src + tests) — fails if any golden is unverified
make golden         # regenerate .bin from .csv + prune verify log + clean debris
make build          # uv build
```

## Shell Hygiene

Never inline multi-line content in bash commands (echo, printf, python -c, cat <<EOF).
This triggers Claude Code's quoted-newline security check and stalls the workflow.
Instead:
- Use the Write/Edit tool to create .py scripts, then run them with `uv run`.
- For quick Python one-liners, keep them truly single-line.

## Package Structure

```
src/laddercodec/
├── __init__.py           # Public API: encode_rung(), decode_rung(), Contact, Coil, ...
├── encode.py             # Single-rung encoder: encode_rung()
├── encode_multi.py       # Multi-rung encoder: encode_multi_rung()
├── decode.py             # Decoder: decode_rung(), decode_multi_rung()
├── topology.py           # Program header, rung preamble, cell offset math, wire flags
├── empty_multirow.py     # Deterministic empty multi-row payload synthesis
├── model.py              # Domain objects: Contact, Coil, InstructionType, RungGrid
├── csv/                  # CSV parsing subpackage
│   ├── __init__.py
│   ├── ast.py            # Typed AST (CanonicalRow, condition/AF nodes, RungAst)
│   ├── contract.py       # Constants (CONDITION_COLUMNS, CSV_HEADER) + validators
│   ├── shorthand.py      # Shorthand row normalization + rendering
│   ├── parser.py         # CSV file parser (canonical + shorthand syntax)
│   ├── adapter.py        # RungAst → RungGrid adapter (simple rungs only)
│   ├── bundle.py         # Program bundle parser (main.csv + sub_*.csv)
│   └── token_parser.py   # Condition + AF token parsers
└── resources/
    └── empty_multirow_rule_minimal.scaffold.bin  # Template for multi-row synthesis
```

## Key Modules

- **encode.py** — Single-rung encoder. Public API is `encode_rung()`. Pipeline: allocate base buffer → write wire flags into cell grid → write NOP → insert comment payload into rung 0 preamble at 0x0298 (grid pushes forward) → pad to page.
- **encode_multi.py** — Multi-rung encoder. Public API is `encode_multi_rung()`. Combines N rungs into one buffer with per-rung preambles and data rows.
- **decode.py** — Decoder. Public API is `decode_rung()` / `decode_multi_rung()`. Walks the variable-length cell grid, parses instruction blobs into Contact/Coil domain objects, decodes RTF comments to markdown. Falls back to UnknownCondition/UnknownInstruction for unrecognised cell types.
- **topology.py** — Buffer structure constants: program header (0x0254), rung preamble layout (comment flag +0x30, length +0x34, body +0x38), cell offset math, cell flag constants (+0x19 segment, +0x1D right, +0x21 down).
- **empty_multirow.py** — Deterministic empty payload synthesis for 1–32 rows. Key formula: payload length = `0x1000 * (ceil((rows+1)/2) + 1)`.
- **model.py** — Domain objects: `Contact` (NO/NC/edge), `Coil` (out/latch/reset), `InstructionType` enum, `RungGrid` (single-row rung model with CSV parse/serialize). Currently used only by csv/ subpackage; will become active when instruction encoding is added.
- **csv/contract.py** — Constants (CONDITION_COLUMNS, CSV_HEADER) used by golden fixture IO and clicknick.
- **csv/shorthand.py** — Shorthand syntax: `R` marker, condition tokens, macros (`->` fill wires, `...` fill blanks), separator `:`, AF token.
- **csv/parser.py, adapter.py, bundle.py, token_parser.py** — Forward-looking modules for future CSV program import. Tested but not yet wired into any encode path.

## Tests

```
tests/
├── test_smoke.py            # Basic sanity check
├── golden_io.py             # Golden CSV/BIN read/write helpers
├── ladder/
│   ├── test_encode.py       # encode_rung() pipeline, multi-row, comments, wires, NOP
│   ├── test_encode_multi.py # encode_multi_rung() golden fixture tests
│   ├── test_model.py        # Contact, Coil, RungGrid CSV round-trips
│   └── test_empty_multirow.py  # Payload synthesis for rows 1..32
├── csv/
│   ├── test_shorthand.py    # Shorthand normalization + macros
│   ├── test_parser.py       # CSV file parsing (canonical + shorthand)
│   ├── test_adapter.py      # RungGrid adaptation constraints
│   ├── test_contract.py     # Constants and validators
│   ├── test_bundle.py       # Program bundle parsing
│   └── test_token_parser.py # Condition + AF token parsing
└── fixtures/
    └── ladder_captures/golden/  # 39 byte-exact golden fixtures
```

Golden fixtures verified through Click paste round-trip.

## Binary Format Model

The clipboard buffer has three regions:

1. **Program header** (0x0254–0x025F) — row_word at +0x00 (total_grid_rows × 0x20).
2. **Rung preamble** — each rung has a 0x40-byte preamble holding its comment data:
   - Rung 0: at 0x0260, immediately after the program header (from template, not in grid).
   - Rung N>0: cell 0 of the rung's preamble row in the grid.
   - Comment layout: flag at +0x30, length (4B LE) at +0x34, body (RTF) at +0x38.
3. **Cell grid** (0x0A60+) — 32 cells per row × 0x40 bytes each. Comment payloads inserted at +0x38 push everything after them forward (payload push model).

Multi-rung grid rows: `[rung 0 data] [rung 1 preamble] [rung 1 data] [rung 2 preamble] ... [terminal]`.

## Wire Flags, Segment Flag, and Left-Edge Rendering

Each cell has three flag bytes at fixed offsets: segment (+0x19), right (+0x1D), down (+0x21). The **segment flag** is load-bearing — getting it wrong causes contacts/wires to shift down to their own row. The encoder computes segment flags per-row using a branch-zone boundary (best-effort match of native Click behavior). Wire tokens are classified by (right, down) only, ignoring segment:

- `(*, 1, 0)` → `-` horizontal wire
- `(*, 0, 1)` → `|` vertical down
- `(*, 1, 1)` → `T` branch junction
- `(*, 0, 0)` → blank

The CSV vocabulary is four tokens: `T`, `-`, `|`, blank. No Unicode corners needed.

**Left-edge rendering.** Click renders the T's DOWN wire at the **left edge** of the cell, not the center. This means two cells can connect to a single T's down-wire — one from each side of that edge:

1. **Same-column (DOWN):** A `-` directly below a T connects via the standard vertical edge.
2. **Diagonal (UP/RIGHT):** A `-` one column to the LEFT and one row BELOW connects UP one row and ONE COLUMN TO THE RIGHT to the T. The `-`'s right-wire meets the T's down-wire at the shared cell boundary.

```
Connected:                          Not connected:
R, -, T, T, -, -, out(Y1)          R, -, T, T, -, -, out(Y1)
 , -, -, -, -, -, out(Y2)           , -,  , -, -, -, out(Y2)
      ^                                   ^
      B has "-" = bridge                  B is blank = gap
```

In the not-connected case: A row 1 connects UP/RIGHT to T@B (rule 2), C row 1 connects UP to T@C (rule 1), and the blank at B is the gap that keeps the two branches independent.

**Segment flag boundary rules** (verified against native captures):

1. Find the per-row boundary column. For row R (R > 0): boundary = max of T col+2 / | col+1 from row R-1 only (does not propagate further), plus Contact/CompareContact col+2 from rows 0..R-1. Non-blank cells at col < boundary get seg=0; at col >= boundary get seg=1. Blank/| cells are always seg=0.
2. Row 0 is exempt (boundary=0, all non-blank cells get seg=1). Note: Click's native seg flags track editor creation order — "insert row above" keeps the original row exempt rather than row 0. Our encoder always treats row 0 as exempt, matching top-down construction. Native captures built via "insert row above" will show a different exempt row; don't use those for seg validation. Verified 2026-03-19.
3. AF column: Coil seg=1 on row 0, seg=0 on row 1+. Timer=seg=1. NOP data cell=seg=1.

**Instruction index ordering:** Click stores a per-cell instruction index at +0x0D but the value reflects **editor creation order**, not a structural rule. Native captures show different orderings depending on how the user built the rung. Click accepts any ordering on paste. The encoder uses a deterministic conditions-first-then-AF scheme (all condition-side instructions numbered across rows in row-major column-major order, then AF-side instructions in row order). Verified via native captures with different creation orders (2026-03-18).

**AF summary block:** When a rung has 2+ AF instruction cells, the LAST AF instruction cell gets an extra block appended between the blob and tail. Structure (verified against native instr-3row-branch capture):

1. 12 zero bytes (header padding)
2. uint32 LE total_instr_count
3. af_count × 8-byte entries (diagonal pattern):
   - `entry[af_idx] = left_value` (total_instr_count - instr_index for non-last; instrs_on_row for last)
   - `entry[af_idx + af_count] = 1` if row has a condition contact
4. Modified 16-byte tail: `tail[3]=1, tail[12]=1, tail[15]=1` (replaces the regular instruction tail)

This block replaces the instruction count that would normally go on an AF data cell (tail[12] = total_instr_count) when no AF data cell exists (all rows have AF instructions).

## Current Encoder State

All tested shapes pass Click round-trip (verified via paste → copy-back):

**Single-rung, no comment:**
- Empty rungs (1/2/3/4/5/8/9/13/17/32 rows)
- Wire topologies (horizontal, vertical, T-junction, mixed, partial)
- NOP on AF column (row 0, multi-row with wires)
- Edge cases (all 31 cols dashed, vertical B-only, T at column AE)

**Single-rung, with comment:**
- 1-row: empty, full wire, partial wire, NOP, full wire + NOP, max 1400-byte
- 2-row: empty, NOP, sparse wire, wire at col A, max 1324-byte
- 3-row: empty, NOP, wires, same-col wire, mixed wire, max 1400-byte
- 4/5/9/13/32-row: empty, partial wire, max 1400-byte
- Styled comments: bold, italic, underline, mixed styles, multiline

**Multi-rung:**
- 2-rung: empty, NOP, wire, 2-row
- 3-rung: empty, wire + NOP
- Comments on rung 0 only, rung 1 only, both rungs, all 3 rungs
- Comments with wires + NOP, 2-row rungs, styled text

## Current Decoder State

The decoder (`decode.py`) reads Click clipboard binaries back into structured data. Validated against a 37-rung native capture covering all basic instruction types.

**Decoded instruction types:**
- Contacts: NO, NC, edge (rise/fall), immediate (NO/NC)
- Coils: out, latch, reset, immediate, range (e.g. `out(C1..C2)`)
- Wire tokens: classified by (right, down) only — segment flag ignored (T, -, |, blank)
- Comments: RTF → markdown round-trip
- Multi-rung buffers with interleaved preambles

**Instruction cell blob structure** (from +0x25):
- UTF-16LE null-terminated class name: "ContactNO" (NO+NC), "Edge", "Out", "Latch", "Reset"
- Type marker (uint32 LE): 0x2711=NO, 0x2712=NC, 0x2713=Edge, 0x2715=Out, 0x2716=Latch, 0x2717=Reset
- `01 00` + field count (uint32 LE)
- Tagged fields: `[2B tag][FFFFFFFF sentinel][UTF-16LE null-terminated value]`
- Contact fields (count=4): operand, immediate_flag, func_code, terminal
- Coil fields (count=6): operand, range_end, oneshot, immediate_flag, func_code, terminal
- Func code is the key discriminator — reverse-lookup determines all type/immediate/edge/range attributes

**Cell boundary detection:**
- Cell signature: `+0x00==0x00`, `+0x01==col`, `+0x05==row_byte`, `+0x09==0x01`, `+0x0A==0x01`
- Do NOT use `+0x0D` — varies between 0x00, 0x01, and 0xFF across cell types

## Known Limitations (Not Yet Implemented)

- Comparison contacts (GT, GE, LT, LE, EQ, NE)
- Full AF instruction set (timers, counters, math, etc.)
- Instruction cell encoding (encode.py still writes wire/NOP cells only)

## Development Approach

RE-first: understand the binary format thoroughly through native captures and byte-level diffing before building any byte→model decode layer. The encoder writes bytes directly from verified formulas — no premature abstractions over incompletely-understood structure.

## Validation Rules

- T/| tokens rejected on the last row (vertical-down has nowhere to go)
- T/| tokens rejected on column A
- At most one NOP per rung (multiple NOPs render as tiny dots in Click)

## Important Patterns

- **Rung preamble model.** Every rung has a 0x40-byte preamble at a fixed offset. Rung 0's is at 0x0260; rung N>0's is cell 0 of the preamble row preceding its data rows. Comment flag (+0x30), length (+0x34), and body (+0x38) live at the same offsets in every preamble.
- **Payload push model.** The cell grid always lives at 0x0A60 in a no-payload buffer. A comment payload inserted into a preamble pushes everything after it forward. Wire flags written to cell grid positions before insertion land at the right absolute addresses after insertion — no special stride encoding needed.
- **Buffer sizing for comments.** Truncate the base buffer to `GRID_FIRST_ROW_START + rows * GRID_ROW_STRIDE` before inserting the payload. This keeps the page-aligned final size consistent: `pad_to_page(minimal_end + payload_len)`.
- **Comment max depends on row count.** Inserting > 1400-byte body is rejected outright. The practical per-row limit is determined by where `minimal_end + payload_len` crosses the next page boundary (e.g. 2-row: body ≤ 1324 bytes stays at 0x2000; 1325+ bumps to 0x3000).
- **Native captures are the ground truth.** When something doesn't work, capture a native rung with the same shape and diff against synthetic.

## Native Capture Workflow

When adding support for new instruction types:

1. **User builds test rungs** in Click Programming Software — one rung per instruction variant, combined into a single multi-rung program for efficient capture.
2. **User prints to PDF** from Click and exports the clipboard binary using `clicknick-rung guided` or clipboard capture tooling.
3. **Claude converts the PDF** using `uv run devtools/pdf_to_png.py <path>` to get page images, reads them to understand the rung layout.
4. **Claude decodes the binary** using a scratchpad script (`uv run python scratchpad/<name>.py`) — write scripts to `scratchpad/` for iterative debugging, not inline bash.
5. **Fix decoder issues** — new wire flags, class names, field layouts — until all rungs decode cleanly.
6. **Native captures live in** `clicknick/devtools/captures/` (not in the laddercodec repo).
7. **devtools/ scripts** (inspect, scan, debug) are committed to laddercodec for reuse.
