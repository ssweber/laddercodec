## Context

We have two binary decoders for the same PLC programming tool: `decode.py` (clipboard format) and `decode_program.py` (SCR file format). Both produce the same `Rung` objects with the same instruction types. Analysis shows the instruction blob is the same internal structure in both formats — clipboard wraps it in a cell with header/tail, SCR stores it bare with a row/column prefix. Several "unknown" fields in the SCR decoder are already identified in the clipboard binary-format doc.

## Phase 1 — Name the known unknowns

**No behavioral changes. Renaming and documenting only.**

In `decode_program.py`:

- Rename `m1` → `visual_sub_rows` everywhere (parameter names, tuple positions, local variables, comments). It corresponds to clipboard cell offset `+0x0A` documented as "Visual sub-rows (0x01 for single-row, 0x02+ for timers)". The `part_count` alias in `RawInstruction` should get a docstring noting the equivalence.

- In `_parse_blob`, annotate the 6 bytes at `after_type` through `after_type + 5` as the embedded cell-header fields: `row_span` (1B), `visual_sub_rows` (1B), structural bytes (2B), `instruction_index` (4B) — matching clipboard offsets `+0x09` through `+0x10`. Add a comment block mapping these, but don't change parsing logic yet.

- In `_parse_blob`, document that `end_offset` (the uint32 at `eo_pos`) is the explicit blob boundary pointer — the same boundary that clipboard's `find_blob_boundary` derives by scanning. Add a comment noting this equivalence.

- Add a comment to `_parse_header` at the `cursor += 7` line identifying the known fields: 2-byte marker, 1 byte (still unidentified — log its observed values in test fixtures if convenient), 4-byte uint32.

Verify: all existing tests pass unchanged. This is pure annotation.

## Phase 2 — Extract the tag-type rule from the spec tables ✅

The tag ID high byte encodes its wire type. Every entry in `_SCR_TAG_PARSE_SPECS` follows this pattern:

- `0x11xx` → flag (presence-only, zero bytes)
- `0x20xx`–`0x22xx` → byte value (1 byte)
- `0x32xx` → u16 value (2 bytes)
- `0x3Axx` → variant u16 array (index/value pairs, `0xFFFF`-terminated)
- `0x60xx`–`0x62xx` → length-prefixed UTF-16LE string (the existing default path)
- `0x68xx` → variant string array (index/string pairs, `0xFFFF`-terminated)

Write a function `_tag_wire_type(tag: int) -> str` that returns `"flag"`, `"byte"`, `"u16"`, `"string"`, `"variant_u16"`, `"variant_string"`, or `"unknown"` based on the high byte.

Then verify: for every tag in every `_ScrTagParseSpec` entry, assert that `_tag_wire_type(tag)` agrees with which set it's in. Write this as an actual test. If any tag violates the rule, stop and report — don't proceed.

If the rule holds for all existing tags, refactor `_parse_scr_tags` to use `_tag_wire_type` as the primary dispatch, falling back to the spec tables only for `stop_tags` (which are a semantic override, not a type override). The per-family spec tables can then shrink to only `stop_tags` entries, or be removed entirely if no family uses stop tags exclusively.

Verify: all tests pass. Decoded output is identical.

## Phase 3 — Unify instruction construction

Both decoders build the same domain objects (`Contact`, `Coil`, `Timer`, `Counter`, `Copy`, etc.) from the same tag IDs. Currently this logic lives in:

- `decode.py` → delegates to `instructions/` package's `parse_condition_blob` and `parse_af_blob`, which parse clipboard blob bytes
- `decode_program.py` → `_scr_to_condition` and `_scr_to_af`, which read from a `tags: dict[int, str]` plus `tag_byte_lens`, `variant_u16_tags`, `variant_string_tags`

The SCR form (`tags` dict) is the more natural intermediate — it's already decoded from wire format. Refactor so both paths use it:

1. For each instruction module that `parse_af_blob`/`parse_condition_blob` handles, add a `from_tags(class_name, type_code, tags, tag_byte_lens, variant_u16_tags, variant_string_tags)` factory function (module-level, not a classmethod — matches existing style). Move the construction logic from `_scr_to_condition`/`_scr_to_af` into these factories.

2. Make the clipboard blob parser extract tags into the same dict shape, then call the same `from_tags`. This means `parse_af_blob` becomes: parse blob framing → extract tags → call `from_tags`. The blob-framing parsing stays in `instructions/raw.py`; the semantic construction moves to the per-family modules.

3. Delete `_scr_to_condition`, `_scr_to_af`, and the duplicate `_TYPE_CODE_TO_ITYPE` / `_COMPARE_IDX_TO_OP` tables from `decode_program.py`. These now live in the shared instruction modules.

4. Delete `_scr_to_raw_af` entirely. The Email/Home/Velocity/Position families that currently round-trip through `_compose_blob` should instead get their own `from_tags` in their instruction modules — no rehydration to clipboard format needed.

Do this one instruction family at a time. After each family: run full test suite, diff decoded output for both clipboard and SCR test fixtures against baselines.

Verify: `decode_program.py` no longer imports individual instruction classes for construction — only `from_tags` entry points and structural types. The file should shrink by roughly 500–600 lines.

## Phase 4 — Investigate blob structural equivalence

This is exploratory, not a refactor commitment.

Write a diagnostic script that, for each instruction in the test fixtures:
- Extracts the raw clipboard blob (from cell offset `+0x25` to cell boundary)
- Extracts the raw SCR blob (from `blob_start` to `end_offset`)
- Compares them byte-for-byte after stripping the clipboard cell header prefix and tail suffix

Report which instruction families have identical blob bodies, which differ, and where the differences are. If the blobs are structurally identical (likely), document this in `binary-format.md` as a finding: "The instruction blob is format-independent. Clipboard embeds it in a cell wrapper; SCR stores it bare." If there are differences, characterize them before deciding next steps.

---

**Do not combine phases.** Each one should be a separate branch/PR with its own verification. Phase 3 is the big payoff but Phase 2 de-risks it by proving the tag-type rule first, and Phase 1 makes Phase 3's diffs readable by getting the renames out of the way.