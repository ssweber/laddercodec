# Adding New Instruction Types — Workflow

## 1. Capture

User builds test rungs in Click Programming Software covering all variants of the new instruction type (e.g. all six comparison operators, all timer units). Print to PDF and export the clipboard binary via `clicknick-rung save <name>`.

## 2. Decode & compare to PDF

Convert PDF to PNGs, then run `decode_multi_rung()` on the binary. Compare the output to the PDF — every rung should appear, and unknown blobs tell you what needs parsing.

## 3. Fix grid walking first

If the decoder finds fewer rungs than expected, the grid walker is losing track. Multi-row AF instructions (like timers) add extra grid rows and may use different cell-0 signature bytes. Check `_find_row_end` and `_walk_grid` against the actual bytes at the missing row positions.

## 4. Analyze the instruction blob

Write a scratchpad script that reads the `UnknownCondition`/`UnknownInstruction` raw bytes and parses them field-by-field:
- UTF-16LE class name (e.g. "Compare", "Tmr")
- Type marker (uint32 LE, high byte always 0x27)
- Part count or `01 00` prefix
- Tagged fields: `[2B tag][FFFFFFFF sentinel][UTF-16LE value]`
- Some instructions use variant tag formats (sub-marker bytes instead of sentinel)

Cross-reference each field against the PDF to understand what it means. Diff across variants (e.g. EQ vs GT, ms vs sec) to isolate which field controls what.

## 5. Check naming conventions

Before naming new types or CSV tokens:
- `src/laddercodec/csv/ast.py` — existing AF names (`KNOWN_AF_NAMES`), condition node types
- `src/laddercodec/csv/token_parser.py` — how conditions/AF tokens parse
- `../pyrung/src/pyrung/core/` — instruction and condition class names
- `../pyrung/src/pyrung/click/ladder.py` — `to_ladder()` for CSV rendering format

Match pyrung's naming: `on_delay`/`off_delay` not `TON`/`TOF`, `==`/`!=` not `EQ`/`NE`, `Tms`/`Ts` not `ms`/`sec`.

## 6. Add model classes

In `model.py`:
- New `InstructionType` enum values
- New dataclass(es) with `to_csv()` matching pyrung's format
- Func code lookup tables if needed

Export from `__init__.py`.

## 7. Add decoder parsing

In `decode.py`:
- Import new types and lookup tables
- Add `_parse_<name>()` function following existing `_parse_contact`/`_parse_coil` pattern
- Wire into `_decode_data_row`: condition column → try contact, then compare, then unknown; AF column → try coil, then timer, then unknown
- Update `ConditionToken`/`AfToken` type aliases

## 8. Verify

- Run decoder on the capture — all rungs should produce proper domain objects, zero `Unknown*`
- Cross-check every decoded field against the PDF
- `make test` + `make lint` — all existing tests must pass
