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
- Update `parse_blob()` to extract the new field from the func code table

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
- Implement `to_csv()`, `build_blob()`, `cell_params()`, and `parse_blob()`
- Follow existing modules (coil.py, timer.py, copy.py) as templates
- Add `InstructionType` enum value in `model.py` if it uses a new type marker

**Tall instructions:** if the new instruction occupies more than 1 grid row in the binary/editor shape, return `{"visual_rows": N}` from `cell_params()`.

If the instruction also needs auto-padding in CSV, set `min_csv_rows=N` on the family `SPEC`. These are related but not always identical:

- `visual_rows` = binary/editor cell height
- `min_csv_rows` = minimum CSV/logical rows to synthesize on read

Example: timers currently use `visual_rows=2` and `min_csv_rows=2`, while counter/shift/drum families use explicit higher CSV row counts because their lower rows have pin semantics.

Also add a family `SPEC` in the module:

- `binary_class_names`
- `csv_names`
- `parse_blob`
- `parse_csv_call` (for AF families)
- `pin_names` if the family uses dot-prefixed continuation rows
- `min_csv_rows` if the family should auto-pad in CSV

### 3. Register and export

| File | What to update |
|------|---------------|
| `instructions/__init__.py` | Register the family `SPEC` in `AF_FAMILY_SPECS` or `CONDITION_FAMILY_SPECS`, and re-export the new class |
| `__init__.py` | Re-export the new class in the public API |

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

Coverage golden fixtures live in `tests/fixtures/coverage/golden/`. Each fixture is a hand-written CSV (`<rung_id>.csv`) paired with a Click-captured binary (`<rung_id>.bin`).

### Adding a fixture

1. Create `tests/fixtures/coverage/golden/<rung_id>.csv` by hand — one rung per file, 33-column canonical format.
2. Capture the golden binary via Click paste round-trip using `clicknick-rung guided`.
3. `make test` — each `.csv` with a matching `.bin` gets a parametrized test comparing encoded CSV against captured bytes.

### Regenerating coverage bins from verified fixtures

When you want to refresh coverage bins from the current encoder, use:

```bash
make coverage-golden
```

This command reads `tests/fixtures/coverage/golden/verify_progress.log`, selects only fixture IDs marked `: worked`, regenerates those `.bin` files, and removes non-worked coverage `.bin` files.

Use this for bulk refresh/sync. For native Click fidelity checks, keep using capture round-trips for the specific fixture.

## Clicknick compatibility

The `clicknick-rung guided` tool extracts operand addresses from CSV tokens for MDB provisioning. It uses `to_csv()` + regex to find address patterns, so **new instruction types work automatically** — no clicknick changes needed.
