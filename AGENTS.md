# laddercodec Agent Guidance

**IMPORTANT: Don't use `cd` before commands. The working directory is already set to the project root.**
**IMPORTANT: Always use `make` commands, not direct `uv run` commands.**

This file provides guidance to coding agents working in this repository.

## Project Overview

**laddercodec** is a pure-Python binary codec for AutomationDirect CLICK PLC ladder clipboard format. It encodes and decodes the native clipboard binary used by CLICK Programming Software (v2.60–v4), reads and writes the CSV form of a rung, and checks a rung against CLICK's syntax check. Zero runtime dependencies. Licensed MPL-2.0.

Extracted from [clicknick](https://github.com/ssweber/clicknick) as a standalone library.

## Build & Development Commands

```bash
make                # install + lint + test (default)
make install        # uv sync --locked --all-extras --dev
make lint           # devtools/lint.py: ruff (check + format) + ty
make test           # pytest (src + tests) — fails if any ladder or coverage golden is unverified
make golden         # regenerate ladder .bin from .csv + prune verify log + clean debris
make coverage-golden  # the same for the coverage goldens
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
├── __init__.py           # Public API: encode(), decode(), decode_program(), read_csv(), write_csv(), check(), Rung, ...
├── encode.py             # encode() + internal encode_rung(), constants, RTF helpers
├── encode_multi.py       # Internal encode_rungs(): N rungs in one buffer
├── _grid.py              # Shared grid building: _validate_rung, _compute_rung_metadata, _build_rung_grid
├── binary_helpers.py     # UTF-16LE, tagged-field read/write primitives
├── decode.py             # decode() + internal decode_rung(), decode_rungs(); DecodeError
├── decode_program.py     # decode_program(): Scr*.tmp to Program
├── legacy.py             # LegacyEncodingWarning: saved forms an older laddercodec wrote that CLICK runs differently
├── undecoded.py          # UndecodedRungWarning, marker_rung(): the rung decoders and write_csv put in place of one they can't read
├── refused.py            # RefusedFieldWarning, warn_refused(): a decoded instruction that holds a value its checks refuse
├── compat.py             # find_v4_only() / is_v4_only(): instructions an older CLICK would mangle
├── layout_check.py       # check(): Finding per shape CLICK's syntax check cannot lay out (C0001, C0202, ...)
├── _layout/              # Lays a rung out as CLICK's syntax check draws it: network.py (nets, contact edges),
│                         #   tree.py (series-parallel tree), render.py (packed layout). Used by csv/ and layout_check.py
├── cell.py               # ClickCell, preamble, terminal and row builders
├── topology.py           # Program header, rung preamble, cell offset math, wire flags
├── empty_multirow.py     # Deterministic empty multi-row payload synthesis
├── model.py              # InstructionType enum, ConditionInstruction / AfInstruction bases; re-exports operands/
├── operands/             # Shared operand rules (private; model.py re-exports the public names)
│   ├── address.py        # ADDRESS_BANKS, Address, check_address, normalize_address, normalize_fields,
│   │                     #   normalize_items, display form, X/Y slots
│   ├── banks.py          # Bank flags in CLICK's type order (bit 0 = X), banks(mask), mask(*names)
│   ├── checks.py         # Shared field checks: check_operand, check_constant,
│   │                     #   check_out_target with per-field Constants; check_quoted_text (Compare, Search);
│   │                     #   check_flag (re-exported by model.py); BIT_BANKS, REGISTER_BANKS;
│   │                     #   Refusals: collects every refusal of one construction (Timer, Coil)
│   ├── constants.py      # classify(): constant kinds as CLICK's shared input check reads them (not wired in yet);
│   │                     #   fits_float32() (Math), hex_display() (Math, Send/Receive)
│   ├── errors.py         # FieldError (ValueError), AddressError; .errors, .field(s), .reason (Reason), .click_id, .obj
│   └── unchecked.py      # unchecked(): build an instruction from what is stored, keeping its refusals; refusals(), rebuilt(); the stored blob an unchanged decoded instruction writes; checked()
├── instructions/         # Instruction dataclasses: build_blob(), cell_params(), blob parser, CSV token parser
│   ├── __init__.py       # Registry: INSTRUCTION_MODULES, parse_condition/af_blob()
│   ├── family.py         # Family SPEC (csv names, parse_csv_call) used by the registry and CSV dispatch
│   ├── contact.py, comparison.py, coil.py, out_variant.py
│   ├── timer.py, counter.py, shift.py, drum.py, forloop.py
│   ├── copy.py           # Copy, BlockCopy, Fill, Pack, Unpack
│   ├── search.py, math.py, math_formula.py   # math_formula.parse(): the formula as CLICK's Math dialog reads it
│   ├── call.py, return_.py, end.py
│   ├── send_receive.py, email.py, home.py, position.py, velocity.py
│   ├── raw.py            # RawInstruction: opaque blob passthrough with row span, sub-rows and pin rows
│   └── undecoded.py      # Undecoded: the marker for a rung that did not decode; no blob, encode() refuses it
├── csv/                  # ast.py, contract.py, parser.py, token_parser.py, converter.py (RungAst to Rung, uses _layout),
│                         #   writer.py (Rung to CSV), bundle.py (main.csv + subroutines/*.csv),
│                         #   location.py (CsvLocation: the file, line, rung, row and column a read error names)
└── resources/
    └── empty_multirow_rule_minimal.scaffold.bin  # Template for multi-row synthesis
```

## Key Modules

- **Encoding.** `encode()` accepts a `Rung` or `list[Rung]`. `encode_rung()` runs: validate → compute metadata → build grid → insert comment → pad to page. `encode()` writes the grid it is given; it does not lay out.
- **Decoding.** `decode()` auto-detects single vs multi-rung, walks the variable-length cell grid, parses instruction blobs into domain objects, and decodes RTF comments to markdown. A blob that no parser accepts (unknown type, or a value no stored instruction holds, such as an address not in display form) becomes `RawInstruction` (AF) or an unknown condition, with its bytes kept; a stored value the field checks refuse decodes as the instruction, holding the refusal, with a `RefusedFieldWarning`; unchanged, it encodes as the blob it was decoded from (CLICK's, or one composed from SCR tags) and the cell rows; changed, it is checked again, and `encode()` refuses one read from CSV. A rung that can't be decoded (a down wire in the AF column, a cell that doesn't decode, a row the walk can't read, broken framing) becomes one undecoded marker rung with an `UndecodedRungWarning`; a comment that doesn't decode keeps the rung's logic, with an `UndecodedCommentWarning`; only a bad envelope (magic, size, SCR header) raises. `decode_program()` reads Click's `Scr*.tmp` program files (~17x smaller than the clipboard form) with the same instruction parsing and different framing.
- **Instructions.** Each dataclass knows how to serialize itself: the grid loop calls `token.build_blob()` and `token.cell_params()`. `ConditionInstruction` and `AfInstruction` subclasses are recognized by isinstance dispatch.
- **Operand rules.** A refused field raises `FieldError` (`AddressError` for an address) at construction; a decoder builds the instruction anyway and keeps the refusal (`operands/unchecked.py`). `tests/test_operand_guards.py` counts, in `instructions/`, each `re` function call, each set, tuple, list or dict literal of bank names, and each raise of `ValueError` outside blob parsing, against an allowlist; a new one fails the test, and an entry the code no longer has must be removed. `devtools/classify_dryrun.py` reports where the shared checks in `operands/checks.py`, called with each field's parameters, disagree with today's checks.
- **Layout.** `read_csv` and `write_csv` lay a rung out as CLICK's syntax check draws it; a rung CLICK would split reads as several rungs. `check()` reports the shapes CLICK refuses. See [`docs/internals/layout.md`](docs/internals/layout.md).
- **csv/.** `read_csv` takes a canonical CSV (33 columns: marker + A..AE + AF; wire tokens `T`, `-`, `|`, blank). `converter.py` handles pin rows (`.reset()` → retentive timers) and tall-instruction padding.
- **Devtools.** `devtools/inspect_bin.py <file.bin>` shows instructions with `to_csv()` and the tagged-field breakdown of raw blobs; `devtools/compare_csv.py <dir>` compares an scr decode with its clipboard CSV. `make editor-grids` writes `tests/fixtures/editor_grids/` (the cases ClickNick's runner types into CLICK's dialogs, with laddercodec's verdict on each) and checks the files. `make field-sweep` records, for a golden instruction new to `tests/fixtures/field_sweep/`, what odd field values do to it; `tests/test_field_sweep.py` lets a crash there become a refusal and nothing else. Agent tooling (BOB, the test-run guard) comes from the `bob` plugin; this repo's settings are in `.claude/bob/`.

## Tests

Under `tests/`: `test_*.py` for the cross-cutting checks (public API, v4 captures, coverage goldens, layout and `check()`, operand rules, operand-guard ratchet, compat, legacy warning, refusals kept by decode), `ladder/` for encode, decode, instruction and operand rules, `csv/` for the CSV pipeline, `operands/` for `classify()`. `tests/golden_io.py` reads and writes golden CSV/BIN files; `tests/kept_refusals.py` checks the refusals a decoded instruction keeps.

Fixtures are in `tests/fixtures/`:

- `ladder_captures/golden/` and `coverage/golden/`: `.csv` is the source of truth, `.bin` is generated from it.
- `scr_captures/`: Scr program files and clipboard bins for `decode_program`; `time_drums.bin` is synthetic (see that directory's README), so do not use its differences from SCR as evidence of native cleanup.
- `tumbler/`: 34 real programs, each a `.scr` paired with a clipboard capture of the same program.
- `v4_captures/`: CLICK v4 copy-backs of pyrung capture stubs, and pasted/checked pairs the layout tests use.
- `layout_check/`, `pinned_or/`: inputs for `check()` and pinned-box tests.

## Golden Fixtures

Ladder goldens are verified through a CLICK paste round-trip. Ground truth (native captures, `verify_progress.log` paste checks, CLICK's own DLLs and help files) is authoritative: never edit a ground-truth expectation to fit the code.

- Edit the golden `.csv`, then `make golden` (or `make coverage-golden`) regenerates the `.bin` and prunes the `verify_progress.log` entries of changed goldens.
- `make test` fails if any golden lacks a `: worked` entry in `verify_progress.log`. A golden whose `.bin` changed needs a paste check in CLICK.
- Coverage goldens use kwargs style for boolean flags (`oneshot=1`).

## Binary Format

Full spec: [`docs/internals/binary-format.md`](docs/internals/binary-format.md) — buffer layout, program header, rung preamble, payload push model, cell grid, multi-rung format, SCR row-topology blocks.

Quick reference: three regions — program header (0x0254), payload region (0x0298, comment RTF), cell grid (0x0A60+, 32 cells/row × 0x40 bytes/cell). Comment payloads push the grid forward.

Other specs: [wire rendering](docs/internals/wire-rendering.md) (flag bytes, left-edge rendering, segment flag boundaries), [instruction blobs](docs/internals/instruction-blobs.md) (blob structure, class names, field layouts), [layout](docs/internals/layout.md).

## Validation Rules

- T/| tokens rejected on the last row (vertical-down has nowhere to go)
- T/| tokens rejected on column A
- At most one NOP per rung (multiple NOPs render as tiny dots in Click)
- Wire tokens are classified by (right, down) only; the segment flag is ignored on decode, and the encoder treats row 0 as exempt from segment-flag computation.

## Important Patterns

- **Rung preamble model.** Every rung has a 0x40-byte preamble at a fixed offset. Rung 0's is at 0x0260; rung N>0's is cell 0 of the preamble row preceding its data rows. Comment flag (+0x30), length (+0x34), and body (+0x38) live at the same offsets in every preamble.
- **Payload push model.** The cell grid always lives at 0x0A60 in a no-payload buffer. A comment payload inserted into a preamble pushes everything after it forward. Wire flags written to cell grid positions before insertion land at the right absolute addresses after insertion — no special stride encoding needed.
- **Buffer sizing for comments.** Truncate the base buffer to `GRID_FIRST_ROW_START + rows * GRID_ROW_STRIDE` before inserting the payload. This keeps the page-aligned final size consistent: `pad_to_page(minimal_end + payload_len)`.
- **Comment max depends on row count.** Inserting > 1400-byte body is rejected outright. The practical per-row limit is determined by where `minimal_end + payload_len` crosses the next page boundary (e.g. 2-row: body ≤ 1324 bytes stays at 0x2000; 1325+ bumps to 0x3000).
- **Empty multi-row payload length** is `0x1000 * (ceil((rows+1)/2) + 1)` for 1–32 rows.
- **Native captures are the ground truth.** When something doesn't work, capture a native rung with the same shape and diff against synthetic.
- **RE-first.** Understand the format through native captures and byte-level diffing before building a decode layer. The encoder writes bytes directly from verified formulas, with no abstraction over structure that is not understood.
- **Cross-version CLICK.** Each CLICK version accepts the other's blob form and copies back its own; keep the v3 encoding for instructions both versions share.

## Adding Instruction Support

When the user provides a `.bin` + `.csv` from a Click capture:

1. **Inspect the capture:** `uv run devtools/inspect_bin.py <file.bin>`. A RawInstruction means the class name is recognized but the func code or a field value is not; the breakdown shows what differs.
2. **Update the code:** add func codes, fields or instruction modules; CSV parsing goes through the family `SPEC`'s `parse_csv_call`.
3. **Update the coverage CSV:** `tests/fixtures/coverage/golden/<name>.csv`.
4. **Verify:** `make test` + `make lint`.

For CLICK v4 instructions captured from pyrung stubs (`tests/fixtures/v4_captures/`, `tests/test_v4_captures.py`), see "Capturing from CLICK v4" in the guide.

Full guide: [`docs/contributing/adding-instructions.md`](docs/contributing/adding-instructions.md). Encode failures that crash CLICK on paste: [`docs/contributing/troubleshooting.md`](docs/contributing/troubleshooting.md).
