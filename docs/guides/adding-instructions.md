# Adding New Instruction Types

## Quick workflow

```
uv run devtools/inspect_bin.py <capture.bin>
```

This shows every instruction in the capture: known types display their model + `to_csv()` output, while `RawInstruction` and `UnknownInstruction` show a full tagged-field breakdown with tag IDs, sentinel types, and values.

From the inspect output you'll see one of two cases:

- **RawInstruction** — class name recognized, func code not → new variant of an existing instruction
- **UnknownInstruction** — class name not in registry → entirely new instruction type

## Base classes

All instruction dataclasses inherit from one of two base classes in `model.py`:

- **`ConditionInstruction`** — condition-side (Contact, CompareContact)
- **`AfInstruction`** — AF-side (Coil, Timer, Copy, BlockCopy, Fill, RawInstruction)

Both declare `to_csv()`, `build_blob()`, and `cell_params()` stubs. The pipeline uses these base classes for isinstance dispatch, so **new instruction types that inherit from the right base class are automatically recognized** by the encoder, decoder, grid builder, and CSV writer — no isinstance updates needed in those files.

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

### 3. Update the CSV converter

In `src/laddercodec/csv/converter.py`, pass the new kwarg through when constructing the instruction:

```python
oneshot = call.kwargs.get("oneshot") == "1"
return Coil(..., oneshot=oneshot)
```

### 4. Update the coverage CSV

The coverage fixture at `tests/fixtures/coverage/main.csv` should already have a row for the variant. Verify the CSV token matches what your `to_csv()` produces (e.g. `out(C47,oneshot=1)`). Boolean flags use kwargs style: `oneshot=1`, not wrapper style.

### 5. Verify

```bash
make test && make lint
```

## Case 2: Entirely new instruction type

### 1. Read the field breakdown

Same as above, but the class name won't be in the registry. The inspect output shows the full blob structure — class name, type marker, part count, field count, all tagged fields.

### 2. Create instruction module

In `src/laddercodec/instructions/`:

- New `@dataclass` inheriting from `AfInstruction` (or `ConditionInstruction`)
- Implement `to_csv()`, `build_blob()`, `cell_params()`, and `parse_blob()`
- Follow existing modules (coil.py, timer.py, copy.py) as templates
- Add `InstructionType` enum value in `model.py` if it uses a new type marker

**Tall instructions:** if the new instruction occupies more than 1 grid row (like Timer and Copy at 2 rows), return `{"visual_rows": N}` from `cell_params()`. The pipeline detects tall instructions automatically via `cell_params()` — no isinstance updates needed. Also add the token name to the `_TALL_AF` dict in `csv/converter.py` so the CSV auto-padding works.

### 3. Register and export

| File | What to update |
|------|---------------|
| `instructions/__init__.py` | `INSTRUCTION_MODULES` registry (binary class name → module), re-export the new class |
| `__init__.py` | Re-export the new class in the public API |
| `csv/ast.py` | Add the token name to `KNOWN_AF_NAMES` |

Thanks to the base classes, `encode.py`, `_grid.py`, `csv/writer.py`, and `devtools/inspect_bin.py` need no changes — they dispatch on `AfInstruction`/`ConditionInstruction`.

### 4. Update CSV converter

In `csv/converter.py`:

- Add a branch in `_af_call_to_token()` for the new instruction name
- Handle positional args and kwargs

### 5. Update CSV writer

If the instruction has pin rows or padding (like timers), update `csv/writer.py` to handle the reverse direction.

### 6. Update coverage CSV and verify

Add rows to `tests/fixtures/coverage/main.csv` covering all variants.

```bash
make test && make lint
```

## Coverage testing

Coverage golden fixtures live in `tests/fixtures/coverage/golden/`. Each fixture is a hand-written CSV (`<rung_id>.csv`) paired with a Click-captured binary (`<rung_id>.bin`).

### Adding a fixture

1. Create `tests/fixtures/coverage/golden/<rung_id>.csv` by hand — one rung per file, 33-column canonical format.
2. Add the rung to `tests/fixtures/coverage/main.csv` (the combined file that `test_coverage.py` reads).
3. Capture the golden binary via Click paste round-trip using `clicknick-rung guided`.
4. `make test` — each `.bin` gets a parametrized test comparing encoded CSV against captured bytes.

## Clicknick compatibility

The `clicknick-rung guided` tool extracts operand addresses from CSV tokens for MDB provisioning. It uses `to_csv()` + regex to find address patterns, so **new instruction types work automatically** — no clicknick changes needed.
