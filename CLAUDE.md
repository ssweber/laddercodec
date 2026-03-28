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
make test           # pytest (src + tests)
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
├── __init__.py           # Public API: encode_rung(), encode_multi_rung()
├── encode.py             # Single-rung encoder: encode_rung()
├── encode_multi.py       # Multi-rung encoder: encode_multi_rung()
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
- **topology.py** — Buffer structure constants: program header (0x0254), rung preamble layout (comment flag +0x30, length +0x34, body +0x38), cell offset math, wire flag constants (+0x19 left, +0x1D right, +0x21 down).
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

## Known Limitations (Not Yet Implemented)

- Contacts (NO, NC, edge, comparison, immediate variants)
- Coils / AF instructions (out, latch, reset)
- Instruction stream placement

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
