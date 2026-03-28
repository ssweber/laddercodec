# Adding New Instruction Types

This guide covers the full workflow for adding support for a new Click instruction type, from binary capture through decoder integration.

## Capture workflow

### 1. Build test rungs

Build test rungs in Click Programming Software covering all variants of the instruction type (e.g. all six comparison operators, all timer units). Combine into a single multi-rung program for efficient capture.

### 2. Export

Print to PDF from Click and export the clipboard binary via `clicknick-rung save <name>`.

### 3. Decode and compare

Convert the PDF to PNGs, then run `decode()` on the binary. Compare output to the PDF — every rung should appear. `UnknownCondition` / `UnknownInstruction` fallbacks tell you what needs parsing.

### 4. Fix grid walking

If the decoder finds fewer rungs than expected, the grid walker is losing track. Multi-row AF instructions (like timers) add extra grid rows and may use different cell-0 signature bytes. Check `_find_row_end` and `_walk_grid` against the actual bytes at the missing row positions.

### 5. Analyze the instruction blob

Write a scratchpad script that reads the `UnknownCondition` / `UnknownInstruction` raw bytes and parses them field-by-field:

- UTF-16LE class name (e.g. "Compare", "Tmr")
- Type marker (uint32 LE, high byte always 0x27)
- Part count or `01 00` prefix
- Tagged fields: `[2B tag][FFFFFFFF sentinel][UTF-16LE value]`

Cross-reference each field against the PDF. Diff across variants to isolate which field controls what. See [instruction blobs](../internals/instruction-blobs.md) for the generic structure.

### 6. Check naming conventions

Before naming new types or CSV tokens, check existing conventions:

- `src/laddercodec/csv/ast.py` — existing AF names, condition node types
- `src/laddercodec/csv/token_parser.py` — condition/AF token parsing
- `../pyrung/src/pyrung/core/` — instruction and condition class names
- `../pyrung/src/pyrung/click/ladder.py` — `to_ladder()` CSV rendering

Match pyrung's naming: `on_delay`/`off_delay` not `TON`/`TOF`, `==`/`!=` not `EQ`/`NE`.

### 7. Add model classes

In `instructions/`:

- New module with dataclass, func code tables, blob builder, and blob parser
- New `InstructionType` enum values in `model.py`
- Register in `instructions/__init__.py` INSTRUCTION_MODULES dict
- Export from `__init__.py`

### 8. Add decoder parsing

In `decode.py`:

- Import new types and lookup tables
- Wire into `_decode_data_row`: condition column dispatches through `parse_condition_blob`, AF column through `parse_af_blob`

### 9. Verify

- Decode the capture — all rungs should produce proper domain objects, zero `Unknown*`
- Cross-check every decoded field against the PDF
- `make test` + `make lint`

## Coverage loop

For systematic coverage testing across all instruction variants, there's a three-repo pipeline:

```
pyrung                        laddercodec                    clicknick
------                        -----------                    ---------
coverage_program.py           split_coverage_csv.py          clicknick-rung
  | to_ladder()                 | split main.csv               | guided FOLDER
  v                             v                              v
fixtures/coverage/main.csv -> tests/fixtures/coverage/    paste -> copy-back
                               +-- main.csv                    |
                               +-- golden/                     v
                                    +-- cond__no.csv       cond__no.bin
                                    +-- cond__no.bin       out__tag.bin
                                    +-- out__tag.csv       ...
                                                     <-- test_coverage.py
```

### Step 1: Generate CSV (pyrung)

```bash
cd ~/documents/github/pyrung
uv run python devtools/coverage_program.py
```

Writes `fixtures/coverage/main.csv` — one rung per instruction variant, ~70 rungs total. Add new variants by adding entries to the relevant variant table in `coverage_program.py`.

### Step 2: Copy and split (laddercodec)

```bash
cp ~/documents/github/pyrung/fixtures/coverage/main.csv tests/fixtures/coverage/main.csv
uv run devtools/split_coverage_csv.py
```

Produces `tests/fixtures/coverage/golden/<rung_id>.csv` per rung.

### Step 3: Capture golden binaries (Click + clicknick)

```bash
cd ~/documents/github/clicknick
uv run clicknick-rung guided --folder ~/documents/github/laddercodec/tests/fixtures/coverage/golden
```

The tool iterates through each CSV, pastes into Click, and captures the copy-back binary. Responses at the prompt:

- **Enter / w** — worked: saves `.bin`
- **c** — crashed: logs crash
- **n** — not as expected: saves notes
- **s** — skip
- **q** — quit (resume later with same command)

### Step 4: Run tests

```bash
make test
```

Each `.bin` gets a parametrized test comparing encoded CSV against captured bytes. Results: PASS (byte-exact), SKIP (no `.bin` yet), FAIL (bytes differ).
