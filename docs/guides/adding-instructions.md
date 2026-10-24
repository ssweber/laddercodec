# Adding New Instruction Types

## Quick workflow

```
uv run devtools/inspect_bin.py <capture.bin>
```

This shows every instruction in the capture: known types display their model + `to_csv()` output, while `RawInstruction` and `UnknownInstruction` show a full tagged-field breakdown with tag IDs, sentinel types, and values.

From the inspect output you'll see one of two cases:

- **RawInstruction** — blob structure parsed, but no supported model matched yet. This can mean:
  - a new variant of an existing instruction class, or
  - an entirely new instruction class name
- **UnknownInstruction** — blob boundary could not be parsed cleanly (truncated/novel layout); inspect raw bytes before modeling

Tip: use the reported `class='...'` value. If the class name is already registered, you're likely adding a new variant; if it's new, you're likely adding a new instruction type.

Note: `Email`, `Home`, `Position`, and `Velocity` are currently known enough
to round-trip, but they still intentionally surface as `raw(...)` passthroughs
until dedicated typed DSL models are added.

## Base classes

All instruction dataclasses inherit from one of two base classes in `model.py`:

- **`ConditionInstruction`** — condition-side (Contact, CompareContact)
- **`AfInstruction`** — AF-side (Coil, Timer, Copy, BlockCopy, Fill, RawInstruction)

Both declare `to_csv()`, `build_blob()`, and `cell_params()` stubs. The pipeline uses these base classes for isinstance dispatch, so **new instruction types that inherit from the right base class are automatically recognized** by the encoder, decoder, grid builder, and CSV writer.

In addition, each instruction family module now exposes a small family spec in `src/laddercodec/instructions/family.py`. That spec is the shared source of truth for:

- binary class names
- CSV token names
- CSV call parsing
- supported pin names
- minimum CSV row count (`min_csv_rows`)

For most new instruction families, the main extension point is: **add the dataclass + codec logic in the family module, then register a `SPEC` for it.**

## Case 1: New variant of existing instruction

Example: adding oneshot to the Out coil (func code 8205, field[2] = "-1").

### 1. Read the field breakdown

```
[0][AF] RawInstruction class='Out'
      csv: raw(Out,4f00...)
      class: 'Out'
      type_marker: 0x2715
      field[0]: tag=0x6066 (std) value='Y001'     # operand
      field[1]: tag=0x6067 (std) value=''          # range_end
      field[2]: tag=0x11F8 (std) value='-1'        # oneshot ← new
      field[3]: tag=0x11F5 (std) value='0'         # immediate
      field[4]: tag=0x3218 (std) value='8205'      # func_code ← new
      field[5]: tag=0x0000 (std) value=''
```

Compare against existing field values (field[2] is normally "0", func code is normally "8193" for basic out). The diff tells you exactly what changed.

### 2. Update the instruction module

In `src/laddercodec/instructions/<module>.py`:

- Add the new func code to the lookup table
- Add any new fields to the dataclass (e.g. `oneshot: bool = False`)
- Update `build_blob()` to emit the new field value
- Update `to_csv()` to include the new parameter
- Update `from_tags()` to extract the new field from the func code table

If the new variant shares a class name with an existing family (CLICK v4's toggle,
debounce, flasher and timed are all class `Out`, type 0x2715), the existing family's
`from_tags()` must return `None` for func codes it doesn't know. Otherwise the variant
decodes silently as the old instruction. `from_tags()` dispatch tries every family in
turn, so the new family can set `binary_class_names=()` and leave the class name's
registry entry to the existing one (see `out_variant.py`).

### 3. Update the CSV-facing parse path

If the variant is covered by an existing family spec, update the family module's CSV parsing path rather than adding a new central converter branch. For example, extend `from_csv_token()` or the family's `parse_af_call()` hook so the new kwarg is understood:

```python
oneshot = call.kwargs.get("oneshot") == "1"
return Coil(..., oneshot=oneshot)
```

### 4. Update the coverage CSV

The coverage fixture at `tests/fixtures/coverage/golden/<rung_id>.csv` should already exist for the variant. Verify the CSV token matches what your `to_csv()` produces (e.g. `out(C47,oneshot=1)`). Boolean flags use kwargs style: `oneshot=1`, not wrapper style.

### 5. Verify

```bash
make test && make lint
```

## Case 2: Entirely new instruction type

### 1. Read the field breakdown

Same as above. For new types, inspect will often show `RawInstruction` with a new class name (for example `class='End'`). `UnknownInstruction` is less common and usually means the blob format itself wasn't parsed cleanly. The inspect output shows the blob structure — class name, type marker, part count, field count, all tagged fields.

### 2. Create instruction module

In `src/laddercodec/instructions/`:

- New `@dataclass` inheriting from `AfInstruction` (or `ConditionInstruction`)
- Implement `to_csv()`, `build_blob()`, `cell_params()`, and a module-level `from_tags()`
- Follow existing modules (coil.py, timer.py, copy.py) as templates
- Add `InstructionType` enum value in `model.py` if it uses a new type marker

**Tall instructions:** if the new instruction occupies more than 1 grid row in the binary/editor shape, return `{"visual_rows": N}` from `cell_params()`.

If the instruction also needs auto-padding in CSV, set `min_csv_rows=N` on the family `SPEC`. These are related but not always identical:

- `visual_rows` = binary/editor cell height
- `min_csv_rows` = minimum CSV/logical rows to synthesize on read

Example: timers currently use `visual_rows=2` and `min_csv_rows=2`, while counter/shift/drum families use explicit higher CSV row counts because their lower rows have pin semantics.

`visual_rows` sets both cell header bytes, `+0x09` (rows spanned) and `+0x0A`
(sub-rows). When a native capture shows them differing, add `"sub_rows"` for
`+0x0A`: CLICK v4's timed coil spans 2 rows but writes 3 (`{"visual_rows": 2, "sub_rows": 3}`).

**Reading tags in `from_tags()`:** flag tags (`0x11xx`/`0x12xx`) are present in
`tags` with an empty value when set, and absent when `0`. Test them with
`0x1201 in tags`, not by value.

Also add a family `SPEC` in the module:

- `binary_class_names`
- `csv_names`
- `from_tags`
- `parse_csv_call` (for AF families)
- `pin_names` if the family uses dot-prefixed continuation rows
- `min_csv_rows` if the family should auto-pad in CSV

### 3. Register and export

| File | What to update |
|------|---------------|
| `instructions/__init__.py` | Register the family `SPEC` in `AF_FAMILY_SPECS` or `CONDITION_FAMILY_SPECS`, and re-export the new class |
| `__init__.py` | Re-export the new class in the public API |
| `tests/test_public_api.py` | Add the class to `EXPECTED_ROOT_EXPORTS`, which pins the root `__all__` |
| `docs/gen_reference.py` | Add the class to the Instructions API page; `make docs-build` fails on an unlisted export |

`KNOWN_AF_NAMES` is now derived from the registered family specs, so `csv/ast.py` does not need manual token updates.

Thanks to the base classes and family specs, `encode.py`, `_grid.py`, `devtools/inspect_bin.py`, and most of the CSV token dispatch need no changes.

### 4. Update family CSV parsing if needed

For AF instructions, make sure the family `SPEC` can parse the CSV call:

- add the CSV token name to `csv_names`
- implement or extend `parse_csv_call`
- handle positional args and kwargs there

### 5. Update CSV writer

If the instruction has only generic blank padding, the existing tall-instruction stripping usually works automatically.

If the instruction has semantic lower rows or pins (like timers, counters, shifts, or drums), update `csv/writer.py` and possibly `csv/converter.py` to handle the reverse row-shaping explicitly.

### 6. Update coverage CSV and verify

Add `tests/fixtures/coverage/golden/<rung_id>.csv` files covering all variants.

```bash
make test && make lint
```

## Coverage testing

Coverage golden fixtures live in `tests/fixtures/coverage/golden/`. Each fixture is a hand-written CSV (`<rung_id>.csv`) paired with a generated binary (`<rung_id>.bin`).

### Adding a fixture

1. Create `tests/fixtures/coverage/golden/<rung_id>.csv` by hand in the 33-column canonical format. Usually one rung per file; a file can hold several rungs (`math__v4.csv` holds 23) and is verified as one paste.
2. Run `make coverage-golden` to generate the `.bin` from the CSV.
3. Paste-verify in Click using `clicknick-rung guided`.
4. `make test` — each `.csv` with a matching `.bin` gets a parametrized test comparing encoded output to golden binaries.

### Regenerating coverage bins

```bash
make coverage-golden
```

Regenerates all `.bin` files from `.csv` sources and prunes the verify log for changed/deleted fixtures. Same workflow as `make golden` for ladder fixtures.

### Smoke-testing combined fixtures

To quickly test multiple instruction types together in a single rung:

```bash
uv run devtools/combine_coverage.py          # 4 random fixtures
uv run devtools/combine_coverage.py -n 6     # 6 random fixtures
uv run devtools/combine_coverage.py --seed 42 # reproducible pick
```

This picks N random coverage CSVs, stacks their data rows into one multi-row rung, and writes `devtools/combined.csv` + `devtools/combined.bin` for paste-testing.

## Capturing from CLICK v4

New CLICK v4 instructions are captured in groups. The paste CSVs are built with
pyrung by `scratchpad/click-v4/captures/v4_capture.py`, whose README has the
CLICK-side steps and address map per group. Each rung's comment is its id, then
every AF token it should decode to, in row order:

```
#,drum__te_ds
#,"time_event_drum(outputs=[C1321,C1322],presets=[DS1301,None],...)"
#,.reset()
```

Run clicknick against the local checkouts, so `load` encodes with the laddercodec
you are changing. From the clicknick directory:

```bash
make install-dev          # editable ../pyclickplc, ../pyrung, ../laddercodec
UV_NO_SYNC=1 uv run --no-sync clicknick-rung load ../laddercodec/scratchpad/click-v4/captures/stubs/<group>.csv
# build each rung in CLICK as its comment says, copy them all back, then:
UV_NO_SYNC=1 uv run --no-sync clicknick-rung save ../laddercodec/scratchpad/click-v4/captures/copyback/<group>
```

A rung whose instruction laddercodec can't encode yet is pasted as a placeholder
(NOP, or a v3 instruction with `1` standing in for a blank or register preset);
its comment still names the target.

In laddercodec:

1. Copy `scratchpad/click-v4/captures/copyback/<group>.bin` to `tests/fixtures/v4_captures/`. `tests/test_v4_captures.py`
   checks every labelled rung: one still decoding as `raw(...)` is xfail, any other
   mismatch fails, and every capture must survive `write_csv`.
2. Map the fields of the raw blobs (`devtools/inspect_bin.py`, or the `raw(...)`
   tokens in the saved CSV) and model the instruction until its rungs pass.
3. Add a test that re-encoding matches the blobs Click wrote, field for field
   (see `test_out_variant_blobs_match_native` and `test_time_event_drum_blobs_match_native`).
4. For the encode side, copy `scratchpad/click-v4/captures/expected/<group>.csv` (real tokens in the
   AF column) to a coverage golden `<family>__v4.csv`, run `make coverage-golden`,
   and paste-verify it with `clicknick-rung guided`.

A typo made while building rungs in CLICK shows up as a failing rung, not an
xfail. Fix the rung in CLICK and save again.

## Clicknick compatibility

The `clicknick-rung guided` tool extracts operand addresses from CSV tokens for MDB provisioning. It uses `to_csv()` + regex to find address patterns, so **new instruction types work automatically** — no clicknick changes needed.
