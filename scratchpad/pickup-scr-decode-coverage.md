**Project: `laddercodec` — `decode_scr()` coverage status**

## What's Done

`src/laddercodec/decode_scr.py` decodes SCR temp files into `Rung` objects. The core pipeline works:
- SCR structure parsing (headers, sections, row headers, flag blocks, wire_down)
- Direct SCR tag parsing → instruction objects (bypasses CLIP blob conversion)
- Row 0 topology comes from the SCR row-header flag block
- Continuation-row topology is now parsed from explicit SCR right-wire column blocks instead of the old made-up sparse flag map
- Horizontal dash fill on extra rows is now only a narrow fallback for the remaining count=0 modifier rows that still appear to be omitted in SCR (currently counter pin rows in the fixture)
- **8/8 `or_topology` rungs match CLIP decoder exactly**
- **114/114 `coverage` rungs match CLIP decoder exactly**

## What Was Fixed This Session

1. **Boolean flags → presence-based**: Changed `tags.get(TAG, "0") == "1"` to `TAG in tags` for edge kind (0x21F6), immediate (0x11F5), oneshot (0x11F8), off_delay (0x21FA), retained (0x21FB).

2. **Compare contacts → byte-length encoding**: Tag 0x21F7 encodes the compare operator as its `str_len` byte (absent=0/==, 1/!=, 2/>, 3/<, 4/>=, 5/<=). Added `tag_byte_lens` return value to `_parse_scr_tags` to support this.

3. **Timer defaults**: Missing unit tag (0x21F9) defaults to "0" (Tms).

4. **Copy family parser**: Added a Copy-specific mixed-tag SCR parser and mapped SCR blobs to `Copy`, `BlockCopy`, `Fill`, `Pack`, and `Unpack`. All copy-family coverage rungs now match, including conversion/text termination/oneshot cases.

5. **Additional AF decoders**: Added SCR decoding for `Counter`, `Search`, `Shift`, `For`, `Next`, `Call`, `End`, and `Return`.

6. **Row/header inference**: Relaxed row-header lookup and inferred logical row count from instruction placement / AF visual height so multi-row counter, shift, and drum rungs stop collapsing to 1 row when the section header is farther back than expected.

7. **Implied horizontal wires on tall AF rows**: Extra rows under multi-row AF instructions now inherit the AF-side dash run even when the row itself has no AF token. This fixed the timer/counter/shift/drum extra-row dash mismatches.

8. **Counter layout quirks**: Added the native `count_down` bridge-row `NOP` and blank top-row rendering.

9. **Math parser**: Added a Math-specific SCR parser that stops before the operand table and correctly handles the `hex` / `oneshot` presence tags. All math coverage rungs now match.

10. **Structural parser cleanup**: Replaced the one-off family parsers with a declarative SCR tag parse spec (`_ScrTagParseSpec`) plus one shared parser that understands standard strings, presence-only flags, byte-valued tags, u16-valued tags, and early-stop tags. Also removed the separate SCR-only visual-row lookup table and now infer AF height from parsed instruction `cell_params()` or instruction-family metadata (`min_csv_rows`).

11. **Behavior check after cleanup**: The structural cleanup did not change the then-current results; the fixture still sat at **76/113** matching rungs.

12. **Drum parser**: Extended the declarative SCR tag parser with compact variant-tag support (u16 arrays + string arrays) and mapped SCR `Drum` blobs to native `Drum` instructions. Event drums and time drums now match, including jump/jog flags, compact pattern bitmasks, default `Tms`, and sparse output/event tables.

13. **Send / Receive parser**: Added compact SCR decoding for `RD` / `SD`, including sparse default handling for protocol mode, device id, address type, quantity, TCP target fields, and the mixed enable-bit conventions (`RD` status bits are presence-based; `SD` still uses explicit enable flags). All send/receive coverage rungs now match.

14. **Regression tests**: Added `tests/ladder/test_decode_scr.py` to lock in `or_topology` parity and the current `coverage` matched prefix through rung 108.

15. **Continuation-row topology parser**: Replaced the fake `_parse_extra_row_flags()` decoder with a structural parser for SCR continuation-row blocks:

   `00 [count] 00 00 [col next_seg]... [final_col]`

   The decoder now uses those explicit stored columns to place right-wire cells on continuation rows. `or_topology.scr` is no longer relying on the broad implied-dash heuristic to recover branch wiring.

16. **Marker anchoring cleanup**: `_parse_wiredown()` now consumes the `0x0020` marker position returned by the continuation-row parser instead of searching the whole gap region again.

17. **Topology regression**: Added a parser-level test that checks the extracted continuation-row right-wire columns from `or_topology.scr` against the clipboard fixture, not just the final rung decode.

18. **Continuation-row `next_seg` semantics**: Verified against `or_topology.bin` that each stored `next_seg` byte is the clipboard segment flag (`+0x19`) of the *next serialized right-wire cell* in the SCR continuation-row block. The serialized column order is not guaranteed to be ascending, so the decoder still only trusts the explicit column set for reconstruction.

19. **Alternate row-header variant**: Found a second native row-header form:

   `[u16 row_word] [03 00 00 01 1F 00]`

   Those headers carry **31** row-0 flag entries instead of 32, so the continuation-row blocks start 2 bytes earlier than the old parser expected. This was the real reason `coverage.scr` `shift` / `drum` / `time_drum` modifier rows had looked "missing" before; we were anchoring to the previous rung's standard `...20 00` header instead of this rung's own `...1F 00` header.

20. **Alternate section marker**: Relaxed section scanning to treat the 4-byte field after section count as an opaque marker rather than hardcoding `0x00000090`. New capture `shift_scr.scr` uses `0x000000E2` and now decodes correctly.

21. **New shift fixture + regressions**: Added `tests/fixtures/scr_captures/shift_scr.{scr,bin,csv}` (two-rung connected vs disconnected shift capture), plus tests that lock in both `shift_scr` parity and the `0x1F` row-header parsing on the existing `coverage.scr` shift/drum/time-drum cases.

## Test Fixtures

`tests/fixtures/scr_captures/` has three capture sets:
- `or_topology.{scr,bin,csv}` — 8 rungs, contacts + coils only (all match)
- `coverage.{scr,bin,csv}` — 114 SCR rungs / 114 CLIP rungs, all instruction types (**all match**)
- `shift_scr.{scr,bin,csv}` — 2 rungs, same `shift()` with pin rows disconnected vs connected (**all match**)

Run comparison: `PYTHONIOENCODING=utf-8 uv run python devtools/test_decode_scr.py tests/fixtures/scr_captures/coverage.scr tests/fixtures/scr_captures/coverage.bin`

Dump SCR tags: `PYTHONIOENCODING=utf-8 uv run python devtools/dump_scr_tags.py tests/fixtures/scr_captures/coverage.scr`

## Key Discovery: SCR Copy Blobs Use Mixed Tag Format

The generic tag parser (`_parse_scr_tags`) works for Contact/Coil/Timer/Compare blobs (all tags use `[u16 tag] [u8 slen] [slen bytes]`). But **Copy blobs use a mixed format**:

- **Operand tags** (0x60xx): standard `[u16 tag] [u8 slen] [slen bytes UTF-16LE]` — these parse correctly
- **Short value tags** (0x2223 copy_type, 0x2227 conversion_type, 0x2206 format_option, 0x3216 term_char): `[u16 tag] [u8 value]` — 3 bytes, value byte IS the index directly
- **Flag tags** (0x11F8 oneshot, 0x1221/0x1201 termination flags): `[u16 tag]` — 2 bytes, no slen, presence only
- **Terminator**: `[u16 0x0000]` or zero padding — 2 bytes

When the generic parser encounters a flag tag (e.g., 0x11F8), it reads the next byte as slen — which is actually the first byte of the next tag (e.g., 0x23 from 0x2223). This causes the parser to consume subsequent tags as "data", garbling everything after.

**Critical**: despite the garbling, **operand tags are always correct** (they come first), and **0x11F8 presence is detectable** (it's in the tag dict even with garbled value). The copy type can be determined from operand presence:
- Has 0x6075 AND 0x6077 → block copy
- Has 0x6077 only → fill or unpack (use `tag_byte_lens[0x2223]`: 2=fill, 4=unpack)
- Has 0x6075 only → pack
- Neither → single copy

### Verified Copy Tag Encodings (from `devtools/dump_copy_raw.py`)

**Tag 0x2223 (copy_type_idx) — short value:**
- absent → 0 (single copy)
- value=0x01 → block copy
- value=0x02 → fill
- value=0x03 → pack
- value=0x04 → unpack

**Tag 0x2227 (conversion_type) — short value:**
- absent → 0 (none)
- value=0x01 → text (default: suppress_zero=1, exponential=0)
- value=0x02 → text (suppress_zero=0)
- value=0x04 → text (exponential=1)
- value=0x05 → value
- value=0x06 → ascii
- value=0x08 → binary

**Tag 0x2206 (format_option) — short value:**
- value=0x01 → text modified / ascii
- value=0x02 → binary

**Text termination tags:**
- 0x1221 (termination_flag): flag tag (2 bytes)
- 0x3216 (termination_char): short value, value = decimal ASCII code (e.g., 0x13 = $13)
- 0x1201 (termination_flag2): flag tag (2 bytes)

## Key Discovery: Continuation-Row Blocks Are Serialized Right-Wire Lists

For continuation rows with explicit topology, SCR is storing more than just
"these columns have dashes". The block shape is:

`00 [count] 00 00 [col next_seg]... [final_col]`

What we can now say confidently from the `or_topology` fixture:

- `count` = number of right-wired cells on that row, including the AF cell when present
- `|` cells are **not** part of this list because they have no right wire
- The stored column order is a native serialized order, **not** always ascending
- For every non-final entry, `next_seg` equals the clipboard segment flag (`+0x19`) of the **next serialized** right-wire cell
- This is why rows like rung 5's continuation rows can wrap instead of staying sorted:
  - row 1 order: `[3, 4, 5, ..., 31, 1]`
  - row 2 order: `[4, 5, 6, ..., 30, 3, 31, 1]`

That means the remaining unexplained part is narrower than before:

- We now understand what the extra byte means
- We do **not** yet fully understand why Click chooses a particular serialized starting point / wrap order for some rows
- For decoding into our `Rung` model, we only need the column **set**, so the current parser is structurally correct even without replaying native serialized order

## Key Discovery: Some Rungs Use `...1F 00` Row Headers

The new `shift_scr` capture plus targeted inspection of `coverage.scr` showed that
some multi-row AF rungs use a second row-header flavor:

`[u16 row_word] [03 00 00 01 1F 00]`

instead of:

`[u16 row_word] [03 00 00 01 20 00]`

What changes with the `1F` form:

- Row 0 stores **31** flag entries (condition columns A..AE only), not 32
- The continuation-row topology blocks therefore begin **2 bytes earlier**
- If the decoder only searches for the `...20 00` form, it can back up to the
  previous rung's header and make perfectly explicit continuation-row topology
  look "missing"

This directly explained the old `coverage.scr` anomalies:

- `shift__basic`
- `event_drum__basic`
- `event_drum__jump`
- `event_drum__jog`
- `time_drum__basic`
- `time_drum__basic_td`

Those rows were not actually omitted from SCR; we were reading from the wrong header.

## Key Discovery: Section Marker Is Not Always `0x90`

The compact two-rung `shift_scr.scr` fixture decodes into the same `Rung` objects
as its clipboard pair, but its instruction sections use a different 4-byte marker
after the instruction count:

- `coverage.scr` / `or_topology.scr`: `0x00000090`
- `shift_scr.scr`: `0x000000E2`

The row/col + blob layout after that marker is still valid, so the decoder now
treats this field as opaque and validates sections structurally instead of
hardcoding `0x90`.

## Remaining Questions

### 1. Continuation-row serialized ordering
We now know what the `next_seg` byte means, but we still do not know why Click chooses a particular serialized starting point / wrap order for some rows.

- `or_topology` shows wrapped examples (`[3, 4, ..., 31, 1]`, `[4, 5, ..., 30, 3, 31, 1]`) instead of a plain ascending column list
- This does not block `Rung` reconstruction, but it matters if we ever want byte-for-byte replay of native continuation-row topology blocks

### 2. Count=0 / omitted continuation blocks under AF modifier rows
After the `0x1F` row-header discovery, the old shift/drum/time-drum examples are no longer unexplained. The remaining rows that still look genuinely omitted are narrower.

- The current decoder still needs fallback dash fill for some rows
- On the current fixture, the clearest remaining examples are **counter pin rows** (`count_up__down` and `count_down`)
- A connected-vs-disconnected counter capture should make the remaining difference much easier to isolate than the earlier mixed coverage fixture did

### 3. Remaining heuristics worth revisiting later
The decoder is structurally sound on the current fixtures, but a few tactical behaviors are still explicit:

- Headerless section detection is still heuristic
- `count_down` still has special-case layout normalization (blank top row + bridge `NOP`)
- Some Copy-family subtype recovery still falls back to operand-shape inference if the short-value discriminator is absent/garbled
- Continuation-row block **ordering** is still not fully explained; we now know `next_seg` is the successor cell's segment flag, but we do not yet know why some rows serialize as wrapped / rotated column orders
- Count=0 continuation-row blocks under some AF modifier rows still fall back to implied horizontal dash fill, but this now appears to be mostly a **counter** question rather than a shift/drum question

## Key Files
- `src/laddercodec/decode_scr.py` — the decoder
- `devtools/test_decode_scr.py` — comparison tool (SCR vs CLIP decode)
- `devtools/dump_scr_tags.py` — dumps parsed SCR tags per instruction
- `devtools/dump_copy_tags.py` — dumps raw bytes of Copy-specific tags
- `devtools/dump_copy_raw.py` — hex dump of Copy blob tag regions
- `tests/fixtures/scr_captures/` — test fixtures

## Suggested Next Steps

1. **Explain the continuation-row start/wrap rule** — compare more native captures where branch edit order changes but visible topology does not.
2. **Chase the remaining counter pin rows** — capture connected vs disconnected counter variants and see whether their middle-row wiring is stored structurally or still genuinely implied.
3. **Decide how much native-order fidelity we want** — current decode parity is done, so the remaining work is about explanation / byte-for-byte topology replay, not fixture correctness.
