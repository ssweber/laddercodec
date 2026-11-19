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

## Writing

Prose in this repo follows the `writing` skill in the bob plugin (`/bob:writing`, or `skills/writing/SKILL.md` in https://github.com/ssweber/bob). Read it before you write a commit message, a changelog entry, docs, a docstring, a comment or a message. The rules below are only the ones specific to this repo.

- Everything you write says what a CLICK rule is. It never says where the rule came from.
- A CHANGELOG entry is stated against the last release, v0.4.0. It never describes a state that no release had.
- When a change revises behaviour that an Unreleased entry already describes, rewrite that entry. Do not add one that contradicts it.
- An entry says when the exception class that a caller catches changes.
- Docs follow `docs/AGENTS.md`.

## Shell Hygiene

Never inline multi-line content in bash commands (echo, printf, python -c, cat <<EOF).
This triggers Claude Code's quoted-newline security check and stalls the workflow.
Instead:
- Use the Write/Edit tool to create .py scripts, then run them with `uv run`.
- For quick Python one-liners, keep them truly single-line.

## Package Structure

```
src/laddercodec/
├── __init__.py           # Public API: encode(), decode(), decode_program(), read_csv(), write_csv(), read_bundle(), write_bundle(), check(), Rung, ...
├── encode.py             # encode() + internal encode_rung(), constants, RTF helpers
├── _comment.py           # Comment Markdown: rtf_body() reads it for encode, write_runs() writes it for decode; backslash escapes
├── encode_multi.py       # Internal encode_rungs(): N rungs in one buffer
├── _grid.py              # Shared grid building: _validate_rung, _compute_rung_metadata, _build_rung_grid
├── binary_helpers.py     # UTF-16LE, tagged-field read/write primitives
├── errors.py             # LaddercodecError(ValueError) and the tree under it: DecodeError, EncodeError, CsvReadError, CsvWriteError, LayoutError
├── codes.py              # Code: the kebab-case name of each refusal, finding and layout error rule; CLICK_IDS
├── decode.py             # decode() (always a list[Rung]) + internal decode_rung(), decode_rungs()
├── decode_program.py     # decode_program(): Scr*.tmp to Program
├── legacy.py             # LegacyEncodingWarning: saved forms an older laddercodec wrote that CLICK runs differently
├── undecoded.py          # UndecodedRungWarning, marker_rung(): the rung decoders and write_csv put in place of one they can't read
├── refused.py            # RefusedFieldWarning, warn_refused(): a decoded instruction that holds a value its checks refuse
├── compat.py             # find_v4_only() / is_v4_only(): instructions an older CLICK would mangle
├── paste.py              # addresses(): the addresses that a CLICK project must hold before a paste
├── layout_check.py       # check(): a Finding (.code, .click_id such as C0001) per shape CLICK's syntax check cannot lay out
├── circuit.py            # lay_out() and the circuit types: Series, Parallel, Box, Branch, Circuit
├── _layout/              # Lays a rung out as CLICK's syntax check draws it: network.py (nets, contact edges),
│                         #   tree.py (series-parallel tree), render.py (packed layout), build.py (network
│                         #   from a Circuit, for lay_out). Used by csv/, layout_check.py and circuit.py
├── cell.py               # ClickCell, preamble, terminal and row builders
├── topology.py           # Program header, rung preamble, cell offset math, wire flags
├── empty_multirow.py     # Deterministic empty multi-row payload synthesis
├── model.py              # InstructionType enum, Condition / Instruction bases; re-exports operands/
├── operands/             # Shared operand rules (private; model.py re-exports the public names)
│   ├── address.py        # ADDRESS_BANKS, Address, check_address, require_text (refuses a value that is
│   │                     #   not text), normalize_address, normalize_fields, normalize_items, display form,
│   │                     #   read_as_typed, X/Y slots, xy_points, xy_room;
│   │                     #   readers that never raise: parse_address, split_pointer, is_pointer, bank_prefix, address_shape;
│   │                     #   too_long and digits_value (read a number that int() can't convert)
│   ├── banks.py          # Bank flags in CLICK's type order (bit 0 = X), banks(mask), mask(*names);
│   │                     #   BIT_BANKS, REGISTER_BANKS, XY_BANKS, WORD_IO_BANKS, bits_per_register
│   ├── checks.py         # Shared field checks: check_operand, check_constant,
│   │                     #   check_out_target with per-field Constants; check_quoted_text (Compare, Search);
│   │                     #   check_flag (re-exported by model.py); check_csv_flag (a CSV 0/1 keyword:
│   │                     #   Coil, Copy family); bank_of (the bank that check_operand accepts, or None);
│   │                     #   is_choice (whether a value, hashable or not, is one of a set) and
│   │                     #   choice_operand (the value as a refusal of a choice names it);
│   │                     #   Refusals: collects every refusal of one construction (Timer, Coil)
│   ├── constants.py      # classify(): constant kinds as CLICK's shared input check reads them;
│   │                     #   FLOAT32_MAX (Math), hex_display() (Math, Send/Receive)
│   ├── errors.py         # FieldError (LaddercodecError), AddressError; .errors, .field(s), .code (Code), .reason (Reason), .click_id, .obj
│   ├── math_real.py      # MathReal: a real in a decimal Math formula. CLICK's save rule is stated once, in .saves.
│   │                     #   .in_range states the range rule. .stored states the text written for an integral real.
│   │                     #   The other forms (refusal, stored type, held text) are derived from these three
│   ├── message.py        # Parts of a refusal message: Op, says(), make_refusal(), parts_of(), with_click_id();
│   │                     #   shown(): a short repr of a caller's value that never raises;
│   │                     #   wrong_type(): the rule for a value of the wrong type, such as "5 is an int, not text";
│   │                     #   str(err) and LaddercodecError.message()/short()/detail() render them
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
│                         #   writer.py (Rung to CSV), reader.py (one file to rungs, for read_csv and read_bundle),
│                         #   bundle.py (read_bundle, write_bundle: main.csv + subroutines/*.csv),
│                         #   location.py (CsvLocation: the file, line, rung, row and column a read error names)
└── resources/
    └── empty_multirow_rule_minimal.scaffold.bin  # Template for multi-row synthesis
```

## Key Modules

- **Encoding.** `encode()` accepts a `Rung` or `list[Rung]`. `encode_rung()` runs these steps: validate, compute metadata, build the grid, insert the comment, pad to a page. `encode()` writes the grid it is given. It does not lay out.
- **Decoding.** `decode()` returns a `list[Rung]`, a list of one for a single-rung buffer. It walks the variable-length cell grid, parses instruction blobs into domain objects, and decodes RTF comments to markdown.
  - A blob that no parser accepts becomes `RawInstruction` (AF) or an unknown condition, and its bytes are kept. That covers an unknown type, and a value that no stored instruction holds, such as an address that is not in display form.
  - A stored value that the field checks refuse decodes as the instruction, which holds the refusal, with a `RefusedFieldWarning`. While you leave it unchanged, it encodes as the blob it was decoded from and the cell rows. For an instruction from a program file, that blob is CLICK's clipboard form of the entry's tags. If you change it, it is checked again. If it was read from CSV, `encode()` refuses it.
  - CLICK saves some fields as typed: a Copy, Block Copy or Pack destination, the addresses in a Math formula, a hex Math result, Compare's Data B, and a Search's table start and result (`DS001`, `ds1`, `YD0U`). `read_as_typed` reads these in display form, except an X or Y number typed short (`Y1`). The instruction keeps the blob it was decoded from in the same way. Typed text in any other field stays raw.
  - A rung that can't be decoded becomes one undecoded marker rung with an `UndecodedRungWarning`. That covers a down wire in the AF column, a cell that doesn't decode, a row the walk can't read, and broken framing.
  - A comment that doesn't decode keeps the rung's logic and gives an `UndecodedCommentWarning`.
  - Only a bad envelope (magic, size, SCR header) raises.
  - `decode_program()` reads Click's `Scr*.tmp` program files, which are about 17x smaller than the clipboard form. It parses instructions the same way and uses different framing.
- **Instructions.** Each dataclass knows how to serialize itself. The grid loop calls `token.build_blob()` and `token.cell_params()`. Isinstance dispatch recognizes `Condition` and `Instruction` subclasses.
- **Operand rules.**
  - A refused field raises `FieldError` at construction (`AddressError` for an address).
  - A decoder builds the instruction anyway and keeps the refusal (`operands/unchecked.py`).
  - Each refusal site passes `code=Code.<MEMBER>` (`codes.py`). `tests/test_code_guard.py` fails on a call without one.
  - `docs/gen_codes.py` writes the error codes page (`docs/guides/codes.md`) from `Code`. `tests/test_codes.py` fails when the page is out of date.
  - `tests/test_operand_guards.py` counts three things in `instructions/` and compares the counts with an allowlist. They are each `re` function call, each set, tuple, list or dict literal of bank names, and each raise of `ValueError` or a `laddercodec.errors` class outside blob parsing.
  - A new one fails the test. Remove an allowlist entry when the code no longer has it.
  - `devtools/classify_dryrun.py` calls the shared checks in `operands/checks.py` with each field's parameters. It reports where they disagree with today's checks.
- **Layout.** `read_csv` and `write_csv` lay a rung out as CLICK's syntax check draws it. A rung that CLICK would split reads as several rungs. `check()` reports the shapes CLICK refuses. `lay_out()` lays a rung out from a `Circuit` instead of a grid. See [`docs/internals/layout.md`](docs/internals/layout.md).
- **csv/.** `read_csv` takes a canonical CSV (33 columns: marker + A..AE + AF; wire tokens `T`, `-`, `|`, blank). `converter.py` handles pin rows (`.reset()` → retentive timers) and tall-instruction padding.
- **Devtools.**
  - `devtools/inspect_bin.py <file.bin>` shows instructions with `to_csv()` and the tagged-field breakdown of raw blobs.
  - `devtools/compare_csv.py <dir>` compares an scr decode with its clipboard CSV.
  - `make editor-grids` writes `tests/fixtures/editor_grids/` and checks the files. They hold the cases that ClickNick's runner types into CLICK's dialogs, with laddercodec's verdict on each.
  - `make field-sweep` records what odd field values do to a golden instruction that is new to `tests/fixtures/field_sweep/` (keyed by class name and CSV text). `tests/test_field_sweep.py` lets a crash there become a refusal and nothing else.
  - Agent tooling (BOB, the test-run guard) comes from the `bob` plugin. This repo's settings are in `.claude/bob/`.

## Tests

Under `tests/`: `test_*.py` for the cross-cutting checks (public API, v4 captures, coverage goldens, layout and `check()`, operand rules, operand-guard ratchet, compat, legacy warning, refusals kept by decode), `ladder/` for encode, decode, instruction and operand rules, `csv/` for the CSV pipeline, `operands/` for `classify()`. `tests/golden_io.py` reads and writes golden CSV/BIN files; `tests/kept_refusals.py` checks the refusals a decoded instruction keeps.

`tests/test_pyclickplc_parity.py` fails when laddercodec's bank facts disagree with pyclickplc. Most of the facts are in `operands/address.py` and `operands/banks.py`. Some modules in `instructions/` keep their own copies, such as the bank sets that follow from a bank's data type or register width. pyclickplc is in the dev group. The test skips when pyclickplc is not installed or is older than 0.9.1. The test lists each kind of address text that the two libraries read differently by design.

Fixtures are in `tests/fixtures/`:

- `ladder_captures/golden/` and `coverage/golden/`: `.csv` is the source of truth, `.bin` is generated from it.
- `scr_captures/`: Scr program files and clipboard bins for `decode_program`; `time_drums.bin` is synthetic (see that directory's README), so do not use its differences from SCR as evidence of native cleanup.
- `tumbler/`: 34 real programs, each a `.scr` paired with a clipboard capture of the same program.
- `v4_captures/`: CLICK v4 copy-backs of pyrung capture stubs, and pasted/checked pairs the layout tests use.
- `layout_check/`, `pinned_or/`: inputs for `check()` and pinned-box tests.

## Golden Fixtures

Ladder goldens are verified through a CLICK paste round-trip. Ground truth is authoritative. It is the native captures, the `verify_progress.log` paste checks, and CLICK's own DLLs and help files. Nobody edits a ground-truth expectation to fit the code, and nobody edits CLICK's recorded answers.

- Edit the golden `.csv`, then `make golden` (or `make coverage-golden`) regenerates the `.bin` and prunes the `verify_progress.log` entries of changed goldens.
- `make test` fails if any golden lacks a `: worked` entry in `verify_progress.log`. A golden whose `.bin` changed needs a paste check in CLICK.
- Coverage goldens use kwargs style for boolean flags (`oneshot=1`).

## Binary Format

Full spec: [`docs/internals/binary-format.md`](docs/internals/binary-format.md) — buffer layout, program header, rung preamble, payload push model, cell grid, multi-rung format, SCR row-topology blocks.

Quick reference: three regions — program header (0x0254), payload region (0x0298, comment RTF), cell grid (0x0A60+, 32 cells/row × 0x40 bytes/cell). Comment payloads push the grid forward.

Other specs: [wire rendering](docs/internals/wire-rendering.md) (flag bytes, left-edge rendering, segment flag boundaries), [instruction blobs](docs/internals/instruction-blobs.md) (blob structure, class names, field layouts), [layout](docs/internals/layout.md).

## Validation Rules

- T/| tokens are rejected on the last row, because a vertical-down wire has nowhere to go.
- T/| tokens are rejected on column A.
- A rung has at most one NOP. Several NOPs render as tiny dots in Click.
- Wire tokens are classified by (right, down) only. Decode ignores the segment flag. The encoder exempts row 0 from segment-flag computation.

## Important Patterns

- **Rung preamble model.** Every rung has a 0x40-byte preamble at a fixed offset. Rung 0's is at 0x0260. For rung N>0, the preamble is cell 0 of the preamble row before its data rows. The comment flag (+0x30), length (+0x34) and body (+0x38) are at the same offsets in every preamble.
- **Payload push model.** In a no-payload buffer the cell grid always lives at 0x0A60. A comment payload that you insert into a preamble pushes everything after it forward. Wire flags that you write to cell grid positions before the insertion land at the right absolute addresses after it. No special stride encoding is needed.
- **Buffer sizing for comments.** Truncate the base buffer to `GRID_FIRST_ROW_START + rows * GRID_ROW_STRIDE` before you insert the payload. That keeps the page-aligned final size consistent: `pad_to_page(minimal_end + payload_len)`.
- **Comment max depends on row count.** Inserting a body of more than 1400 bytes is rejected outright. The practical limit for each row count is where `minimal_end + payload_len` crosses the next page boundary. For 2 rows, a body of up to 1324 bytes stays at 0x2000, and 1325 bytes or more bumps it to 0x3000.
- **Empty multi-row payload length** is `0x1000 * (ceil((rows+1)/2) + 1)` for 1–32 rows.
- **Native captures are the ground truth.** When something doesn't work, capture a native rung with the same shape and diff it against the synthetic one.
- **RE-first.** Understand the format through native captures and byte-level diffing before you build a decode layer. The encoder writes bytes directly from verified formulas. It puts no abstraction over structure that is not understood.
- **Cross-version CLICK.** Each CLICK version accepts the other's blob form and copies back its own. Keep the v3 encoding for instructions that both versions share.

## Adding Instruction Support

When the user provides a `.bin` + `.csv` from a Click capture:

1. **Inspect the capture:** `uv run devtools/inspect_bin.py <file.bin>`. A RawInstruction means the class name is recognized but the func code or a field value is not; the breakdown shows what differs.
2. **Update the code:** add func codes, fields or instruction modules; CSV parsing goes through the family `SPEC`'s `parse_csv_call`.
3. **Update the coverage CSV:** `tests/fixtures/coverage/golden/<name>.csv`.
4. **Verify:** `make test` + `make lint`.

For CLICK v4 instructions captured from pyrung stubs (`tests/fixtures/v4_captures/`, `tests/test_v4_captures.py`), see "Capturing from CLICK v4" in the guide.

Full guide: [`docs/contributing/adding-instructions.md`](docs/contributing/adding-instructions.md). Encode failures that crash CLICK on paste: [`docs/contributing/troubleshooting.md`](docs/contributing/troubleshooting.md).
