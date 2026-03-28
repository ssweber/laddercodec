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
├── __init__.py           # Public API: encode_rung()
├── encode.py             # Unified rung encoder: encode_rung()
├── topology.py           # Header table + wire-topology helpers + cell offset math
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
    ├── comment_phase_a.bin                       # Phase-A continuation stream (4040 bytes)
    └── empty_multirow_rule_minimal.scaffold.bin  # Template for multi-row synthesis
```

## Key Modules

- **encode.py** — Unified encoder. Public API is `encode_rung()`. Pipeline: allocate empty multi-row buffer → apply comment payload + phase-A → write wire flags → write AF column (NOP). Comment framing uses prefix/suffix literals + `comment_phase_a.bin`.
- **topology.py** — Cell offset math, wire flag constants (+0x19 left, +0x1D right, +0x21 down), header entry extraction/normalization.
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
│   ├── test_model.py        # Contact, Coil, RungGrid CSV round-trips
│   ├── test_topology.py     # Cell offsets, wire topology, header normalization
│   └── test_empty_multirow.py  # Payload synthesis for rows 1..32
├── csv/
│   ├── test_shorthand.py    # Shorthand normalization + macros
│   ├── test_parser.py       # CSV file parsing (canonical + shorthand)
│   ├── test_adapter.py      # RungGrid adaptation constraints
│   ├── test_contract.py     # Constants and validators
│   ├── test_bundle.py       # Program bundle parsing
│   └── test_token_parser.py # Condition + AF token parsing
└── fixtures/
    └── ladder_captures/golden/  # 20 byte-exact golden fixtures
```

Golden fixtures verified through Click paste round-trip.

## Current Encoder State

All tested shapes pass Click round-trip (verified via paste → copy-back):

**Non-comment:**
- Empty rungs (1/2/3/4/5/8/9/13/17/32 rows)
- Wire topologies (horizontal, vertical, T-junction, mixed, partial)
- NOP on AF column (row 0, multi-row with wires)
- Edge cases (all 31 cols dashed, vertical B-only, T at column AE)

**Comment (1-row):**
- Empty, full wire, partial wire, NOP, full wire + NOP
- Max 1400-byte comment with full wire + NOP

**Comment (2-row):**
- Empty, NOP on row 1, sparse wire (B+D) on both rows
- Wire at col A on both rows
- Max 1324-byte comment (exact buffer limit) with wire + NOP

**Comment (3+ rows):**
- 3-row: empty, NOP on row 2, wire on rows 1+2, same-col wire, mixed wire, max 1400
- 4-row: empty, full wire rows 0-2
- 5/9/13/32-row: partial wire (full row 0, B+D on middle rows)
- 5-row: max 1400-byte comment with wire

## Known Limitations (Not Yet Implemented)

- Styled comments (RTF bold/italic/underline)
- Contacts (NO, NC, edge, comparison, immediate variants)
- Coils / AF instructions (out, latch, reset)
- Instruction stream placement

## Known Parity Gaps (Non-blocking)

- **AF left-wire flag:** When NOP has horizontal wire from the left, native captures show phase-A slot 62 +0x21 = 1. Encoder writes only +0x25. Cosmetic only — Click accepts both.
- **Col-A left-wire in phase-A stride:** Native captures are inconsistent. Click ignores it. Encoder skips it (col_idx > 0 guard).

## Validation Rules

- T/| tokens rejected on the last row (vertical-down has nowhere to go)
- T/| tokens rejected on column A
- At most one NOP per rung (multiple NOPs render as tiny dots in Click)

## Important Patterns

- **Comment wire encoding uses phase-A stride, not cell grid.** For comment rungs row 0, wire data goes at phase-A-relative positions, NOT at cell grid offsets. The cell grid wire bytes are all zero in native comment captures.
- **Comment row 1+ wire/NOP uses continuation stream records.** 32 records per row after phase-A. Wire at +0x19/+0x1D. NOP encoding spans cont[0] and cont[31].
- **No payload padding.** Phase-A starts immediately after the RTF payload.
- **Comment flag varies by session (0x5A, 0x41, 0x67, 0x65).** Not grid-dependent. Encoder uses 0x5A; Click accepts all observed values.
- **Native captures are the ground truth.** When something doesn't work, capture a native rung with the same shape and diff against synthetic.
