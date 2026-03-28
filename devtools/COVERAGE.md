# Coverage Loop Workflow

End-to-end guide for generating, capturing, and testing per-rung golden binaries.

## Overview

```
pyrung                        laddercodec                    clicknick
──────                        ───────────                    ─────────
coverage_program.py           split_coverage_csv.py          clicknick-rung
  │ to_ladder()                 │ split main.csv               │ guided FOLDER
  ▼                             ▼                              ▼
fixtures/coverage/main.csv → tests/fixtures/coverage/    paste → copy-back
                               ├── main.csv                    │
                               └── golden/                     ▼
                                    ├── cond__no.csv       cond__no.bin
                                    ├── cond__no.bin       out__tag.bin
                                    ├── out__tag.csv       ...
                                    └── ...
                                                     ◄── test_coverage.py
```

## Step 1: Generate the CSV (pyrung)

```bash
cd ~/documents/github/pyrung
uv run python devtools/coverage_program.py
```

This writes `fixtures/coverage/main.csv` — one rung per instruction variant, ~70 rungs total. Rungs are generated programmatically from variant tables. Each rung has a comment encoding a stable semantic ID (e.g. `cond__no`, `out__tag`, `copy__as_text`).

To add new instruction variants, add an entry to the relevant variant table in `devtools/coverage_program.py` and re-run. The allocator handles tag creation and address wiring automatically.

## Step 2: Copy to laddercodec and split

```bash
cd ~/documents/github/laddercodec

# Copy the multi-rung CSV
cp ~/documents/github/pyrung/fixtures/coverage/main.csv tests/fixtures/coverage/main.csv

# Split into individual rung CSVs
uv run devtools/split_coverage_csv.py
```

This produces `tests/fixtures/coverage/golden/<rung_id>.csv` — one file per rung, named by its semantic label (e.g. `cond__no.csv`, `out__tag.csv`).

## Step 3: Capture golden binaries (Click + clicknick)

Prerequisites:
- Click Programming Software running with a project open
- Addresses provisioned in SC_.mdb (the tool handles this automatically)

```bash
cd ~/documents/github/clicknick
uv run clicknick-rung guided --folder ~/documents/github/laddercodec/tests/fixtures/coverage/golden
```

The tool iterates through each CSV:
1. Encodes the CSV and copies binary to clipboard
2. Provisions any missing addresses in SC_.mdb
3. Prompts you to paste in Click (Ctrl+V on a rung)
4. You confirm it rendered correctly, then select the rung and copy (Ctrl+C)
5. Tool reads clipboard back and saves as `rung_NN.bin`

Responses at the prompt:
- **Enter / w** — worked: saves copy-back as `.bin`
- **c** — crashed: logs crash, moves on
- **n** — not as expected: saves notes, optionally saves `.bin`
- **s** — skip: skip this rung
- **q** — quit: stop, resume later

Progress is tracked in `verify_progress.log`. Re-run the same command to resume where you left off. Use `--restart` to start fresh.

## Step 4: Run the tests

```bash
cd ~/documents/github/laddercodec
make test
```

Each `<rung_id>.bin` in `golden/` gets a parametrized test that encodes the CSV through the pipeline and compares bytes. Results:
- **PASS** — byte-exact match
- **SKIP** — no `.bin` (not yet captured) or instruction not yet encodable
- **FAIL** — bytes differ (with offset and size info)

For the standalone progress report with color output:

```bash
uv run python tests/test_coverage.py
```

## Adding new rungs

1. Add an entry to the relevant variant table in `pyrung/devtools/coverage_program.py`
2. Re-run steps 1-3 above
3. The new `.bin` is picked up automatically by `test_coverage.py`

## File inventory

| File | Repo | Purpose |
|---|---|---|
| `devtools/coverage_program.py` | pyrung | Generates the master CSV |
| `tests/fixtures/coverage/main.csv` | laddercodec | Multi-rung source CSV |
| `devtools/split_coverage_csv.py` | laddercodec | Splits main.csv into per-rung CSVs |
| `tests/fixtures/coverage/golden/<rung_id>.csv` | laddercodec | Individual rung CSVs |
| `tests/fixtures/coverage/golden/<rung_id>.bin` | laddercodec | Golden binaries from Click |
| `tests/test_coverage.py` | laddercodec | Parametrized byte-exact tests |
