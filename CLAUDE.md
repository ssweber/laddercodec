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
make docs-serve     # local docs dev server (auto-reload)
make docs-build     # build docs site (strict mode)
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
├── __init__.py           # Public API: encode(), decode(), read_csv(), write_csv(), Rung, ...
├── encode.py             # Encoder: encode() + internal encode_rung(), constants, RTF helpers
├── encode_multi.py       # Multi-rung encoder: internal encode_rungs()
├── _grid.py              # Shared grid-building: _validate_rung, _compute_rung_metadata, _build_rung_grid
├── binary_helpers.py     # Shared binary primitives: UTF-16LE encode/decode, tagged fields
├── decode.py             # Decoder: decode() + internal decode_rung(), decode_rungs()
├── cell.py               # Cell object builders: ClickCell, preamble, terminal, row
├── topology.py           # Program header, rung preamble, cell offset math, wire flags
├── empty_multirow.py     # Deterministic empty multi-row payload synthesis
├── model.py              # InstructionType enum, operand validation, base classes (ConditionInstruction, AfInstruction)
├── instructions/         # Instruction dataclasses + blob builders/parsers
│   ├── __init__.py       # Registry: INSTRUCTION_MODULES, parse_condition/af_blob()
│   ├── contact.py        # Contact (NO/NC/edge/immediate), build_blob(), cell_params(), parser
│   ├── comparison.py     # CompareContact (==, !=, >, <, >=, <=), build_blob(), cell_params(), parser
│   ├── coil.py           # Coil (out/latch/reset, range, immediate, oneshot), build_blob(), cell_params(), parser
│   ├── timer.py          # Timer (on_delay/off_delay, retentive), build_blob(), cell_params(), parser
│   ├── copy.py           # Copy (single/block/fill), BlockCopy, Fill — build_blob(), cell_params(), parser
│   └── raw.py            # RawInstruction (opaque blob passthrough), build_blob(), cell_params()
├── csv/                  # CSV parsing subpackage
│   ├── __init__.py       # read_csv, CSV_HEADER, CONDITION_COLUMNS
│   ├── ast.py            # Typed AST (CanonicalRow, condition/AF nodes, RungAst)
│   ├── contract.py       # Constants (CONDITION_COLUMNS, CSV_HEADER) + validators
│   ├── parser.py         # CSV file parser (canonical syntax)
│   ├── converter.py      # RungAst → Rung converter (pin rows, tall padding)
│   ├── writer.py         # CSV writer (Rung → CSV file)
│   ├── bundle.py         # Program bundle parser (main.csv + sub_*.csv)
│   └── token_parser.py   # Condition + AF token parsers
└── resources/
    └── empty_multirow_rule_minimal.scaffold.bin  # Template for multi-row synthesis
```

## Key Modules

- **encode.py** — Encoder. Public API is `encode()` (accepts `Rung` or `list[Rung]`). Internal `encode_rung()` orchestrates: validate → compute metadata → build grid → insert comment → pad to page. Constants, RTF helpers, type aliases (`ConditionToken`, `AfToken`), and `_af_segment()` / `_compute_seg_boundaries()` live here.
- **encode_multi.py** — Multi-rung encoder. Internal `encode_rungs()`. Combines N rungs into one buffer with per-rung preambles and data rows. Delegates grid building to `_grid.py`.
- **_grid.py** — Shared grid-building functions used by both encoders. `_validate_rung()` validates dimensions/tokens, `_compute_rung_metadata()` returns a `RungMetadata` dataclass (instruction indices, AF summary, segment boundaries), `_build_rung_grid()` builds the cell grid for one rung.
- **binary_helpers.py** — Shared binary serialization primitives. Encoding: `_utf16le_null()`, `_tagged_field()`, `_variant_tagged_field()`. Decoding: `_read_utf16le()`, `_parse_tagged_fields()`, `_parse_tagged_fields_verbose()` (returns tag IDs + handles variant sentinels). Used by all instruction modules and `devtools/inspect_bin.py`.
- **decode.py** — Decoder. Public API is `decode()` (auto-detects single vs multi-rung). Returns `Rung` or `list[Rung]`. Walks the variable-length cell grid, parses instruction blobs into Contact/Coil/Timer domain objects, decodes RTF comments to markdown. Falls back to `RawInstruction` for unrecognised cell types.
- **cell.py** — Cell object builders. `ClickCell` dataclass builds 0x25-byte header + blob + 16-byte tail. Also: `build_preamble_cell()`, `build_terminal_cell()`, `build_row()`.
- **topology.py** — Buffer structure constants: program header (0x0254), rung preamble layout (comment flag +0x30, length +0x34, body +0x38), cell offset math, cell flag constants (+0x19 segment, +0x1D right, +0x21 down).
- **empty_multirow.py** — Deterministic empty payload synthesis for 1–32 rows. Key formula: payload length = `0x1000 * (ceil((rows+1)/2) + 1)`.
- **model.py** — `InstructionType` enum (0x2711–0x2718), operand validation, `ConditionInstruction` and `AfInstruction` base classes. All instruction dataclasses inherit from one of these; the pipeline uses them for isinstance dispatch so new types are recognized automatically.
- **instructions/** — Instruction dataclasses with `build_blob()` and `cell_params()` methods, func code tables, and blob parsers. Each dataclass knows how to serialize itself — the grid loop just calls `token.build_blob()` and `token.cell_params()`. Registry in `__init__.py` dispatches class name → module.
- **csv/contract.py** — Constants (CONDITION_COLUMNS, CSV_HEADER) used by golden fixture IO and clicknick.
- **csv/converter.py** — RungAst → Rung converter. Handles pin rows (`.reset()` → retentive timers) and tall instruction auto-padding.
- **csv/parser.py, writer.py, bundle.py, token_parser.py** — CSV parsing and writing. `parser.py` reads canonical CSV into AST; `writer.py` serializes Rung to CSV; `bundle.py` handles multi-file programs; `token_parser.py` parses condition/AF tokens.

## Tests

```
tests/
├── test_smoke.py            # Basic sanity check
├── test_coverage.py         # Coverage golden fixture tests (instruction variants)
├── golden_io.py             # Golden CSV/BIN read/write helpers
├── ladder/
│   ├── test_encode.py       # encode() pipeline, multi-row, comments, wires, NOP
│   ├── test_encode_multi.py # encode() multi-rung golden fixture tests
│   ├── test_decode.py       # decode() tests
│   ├── test_decode_multi.py # decode() multi-rung tests
│   ├── test_verify_status.py # Golden verification status check
│   ├── test_model.py        # InstructionType, operand validation
│   └── test_empty_multirow.py  # Payload synthesis for rows 1..32
├── csv/
│   ├── test_parser.py       # CSV file parsing (canonical)
│   ├── test_converter.py    # RungAst → Rung conversion
│   ├── test_contract.py     # Constants and validators
│   ├── test_bundle.py       # Program bundle parsing
│   ├── test_token_parser.py # Condition + AF token parsing
│   └── test_writer.py       # CSV writer tests
└── fixtures/
    └── ladder_captures/golden/  # Golden CSV/BIN fixtures
```

Golden fixtures verified through Click paste round-trip.

## Binary Format

Full spec: [`docs/internals/binary-format.md`](docs/internals/binary-format.md) — buffer layout, program header, rung preamble, payload push model, cell grid, multi-rung format.

Quick reference: three regions — program header (0x0254), payload region (0x0298, comment RTF), cell grid (0x0A60+, 32 cells/row × 0x40 bytes/cell). Comment payloads push the grid forward.

## Wire Rendering

Full spec: [`docs/internals/wire-rendering.md`](docs/internals/wire-rendering.md) — flag bytes, left-edge rendering, segment flag boundary rules.

Quick reference: three flag bytes per cell — segment (+0x19), right (+0x1D), down (+0x21). Wire tokens classified by (right, down) only. Segment flag boundary computed per-row. Row 0 exempt.

## Instruction Blobs

Full spec: [`docs/internals/instruction-blobs.md`](docs/internals/instruction-blobs.md) — blob structure, class names, field layouts, AF summary block.

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
- Comparison contacts: GT, GE, LT, LE, EQ, NE
- Coils: out, latch, reset, immediate, range (e.g. `out(C1..C2)`), oneshot
- Timers: on_delay, off_delay
- Wire tokens: classified by (right, down) only — segment flag ignored (T, -, |, blank)
- Comments: RTF → markdown round-trip
- Multi-rung buffers with interleaved preambles
- Unknown types: `RawInstruction` fallback with raw bytes preserved

See [instruction blobs](docs/internals/instruction-blobs.md) for the binary blob structure.

## Known Limitations (Not Yet Implemented)

- Counters, math blocks, shift registers, drum sequencers
- Full AF instruction set beyond coils, timers, and copy family

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

## Adding Instruction Support

When the user provides a `.bin` + `.csv` from a Click capture:

1. **Inspect the capture:** `uv run devtools/inspect_bin.py <file.bin>` — shows known instructions with `to_csv()` output, and RawInstruction/Unknown blobs with full tagged-field breakdown (tag IDs, sentinel types, values).
2. **Identify what's new:** RawInstruction means the class name is recognized but the func code isn't. The field breakdown shows exactly which func code / field values differ from existing support.
3. **Update the code:** add func codes, fields, or new instruction modules as needed. Update `csv/converter.py` to pass new kwargs through.
4. **Update coverage CSV:** `tests/fixtures/coverage/main.csv` and `golden/<name>.csv` — use kwargs style for boolean flags (e.g. `oneshot=1`).
5. **Verify:** `make test` + `make lint`.

See [`docs/guides/adding-instructions.md`](docs/guides/adding-instructions.md) for the full guide.
