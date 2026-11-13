# One layout pass, as CLICK's syntax check draws it (design, phase 1)

Status: design and prototype for the user to approve. Nothing here changes `read_csv`, `encode`,
`decode` or `write_csv` yet. The prototype is `src/laddercodec/_layout/` (private, not wired
in). The oracle and its tools are in this directory; `oracle.txt` holds every miss.

This lives in `scratchpad/` because it holds open questions and unapproved choices. Phase 2 moves
the settled rules to `docs/internals/layout.md`.

## 1. Pipeline

```
CSV rows ──parse──> literal grid ──nets──> network ──reduce──> SP tree per CLICK rung ──render──> grid
                    (tokens, AF,            (nets, contact      (series, Or legs,            (tokens, AF,
                     pin rows)               edges, box inputs)  output items, pins)          pin_rows)
```

- **Literal grid.** The CSV's cells read as flags: `-` right, `T` right and down, `|` down,
  a contact is an edge (and `T:` adds down). The AF column holds boxes, `NOP`, and pin tokens
  (`.reset()`), which mark an input of the box above. Hydration of `T`/`|` stays the CSV-syntax
  step it is today and runs first.
- **Network** (`_layout/network.py`). A grid point `(row, x)` is the left edge of column `x`;
  `x = 0` is the rail, `x = 31` the AF input. A wire flag joins two points; a contact is a
  directed edge from `(row, c)` to `(row, c + 1)`; a down flag joins `(row, c)` to
  `(row + 1, c)`; an AF cell's down flag joins `(row, 31)` to `(row + 1, 31)`. Every
  `(row, 0)` is the rail. Joined points are one net. A box input is the net at `(row, 31)` on
  each of its slot rows.
- **Tree** (`_layout/tree.py`). Structural series-parallel reduction, as pyrung's analyzer
  (`codegen/analyzer.py`, stage 2) does it, without Shannon expansion and without factoring:
  two edges with the same ends become a parallel block; a net with one edge in and one out joins
  them in series. Every main box input gets an edge to one shared sink, so the boxes hanging off
  one net become one parallel block of output items. Each pin input is reduced on its own, from
  the rail to its pin. The result per CLICK rung is `Branch(series, items)`, where an item is a
  box or a `Branch` starting from the end net of `series`.
- **Render** (`_layout/render.py`). Assigns a column to every net and a row to every contact
  and box, then paints tokens (the rules in section 2).

Where it runs: in the CSV converter (CSV to `Rung`), not in `encode`. `encode(Rung)` keeps
writing the grid it is given, so `decode(encode(x)) == x` keeps holding for any `Rung`, and a
hand-built or decoded `Rung` encodes as drawn.

## 2. Render rules

The rules are the layoutthy rules (a) to (h) with the rung 6 correction, made exact enough to
implement. The prototype implements every one of them.

### Columns

1. Each net is drawn as one vertical, on the left edge of column `col(net)`. The rail is column
   0 and draws no vertical. `col(dst) = max(col(src) + 1)` over the contacts into `dst`.
2. A contact sits in cell `col(src)` on its row; wire fills cells `col(src) + 1 .. col(dst) - 1`.
   So contacts pack left, a shorter Or leg gets wire to the merge, and a series contact after a
   merge sits in the merge's column carrying its vertical (`T:X002`, layoutthy rung 3).
3. A box input gets wire from `col(net)` to AE on its row.
4. A net's vertical runs from the topmost to the bottommost row that touches it (a contact
   starting or ending there, or a box input on it).
5. Two nets drawn onto one point, or a column past AE, is a layout failure. The SP structure
   and these rules never produced one on the oracle's 2130 rungs.

### Rows

6. Series terms all start on the same top row; a series block is as tall as its tallest term.
7. The legs of a parallel block stack downward from the block's top, in their original order
   (each leg's first contact's row, then column). Nested Ors whose legs share both ends are one
   block (an Or of Ors with one merge draws as one 4-leg Or: pyrung R13).
8. The output items of a net stack downward in output order (each item's first box row). A box
   goes on `max(next row of its net, first free AF row)`; boxes never overlap. A branch after
   the output split starts on the row of its own first box (layoutthy rung 6), so its contacts
   do not pack up beside a taller box above.
9. A rung is as tall as its lowest contact, box input or box span. Empty rows below are dropped.
10. A rung whose output items hang straight off the rail becomes one CLICK rung per item
    (layoutthy rung 21, or_compact stub rung 1). The comment goes on the first.

### Box heights

A box spans `cell_params()["visual_rows"]` rows (Copy 2, Send/Receive 3, out 1, NOP 1); a raw
box spans its stored height. The author never writes pad rows: rule 8 places the next box below
the span, and the condition side packs up beside it (rule 7), as CLICK draws it.

### Pinned boxes (Timer, Counter, Shift, Drum)

A pinned box's slots are: its lead slots (count_down's unused Up), the main input, then each pin.

11. The main input is an output item like any box (rule 8). The box's token sits `lead_rows`
    above it; with a lead slot the main row's AF holds `NOP`.
12. Each used pin's circuit is a separate circuit from the rail, drawn starting on its slot row.
    The first slot after the main input starts on the row after every contact placed so far, so
    OR legs under the main input push the pins down; each later slot starts on the row after the
    circuit above it. An unused pin between used ones takes a row of its own there.
13. Unused pins after the last used one sit directly under it, not below its legs (a
    non-retentive on_delay stays `pin_rows=(1,)` with legs under it: tumbler ProductionErrors,
    pyrung R20).
14. `pin_rows` is each slot's row minus the token row; the box ends on its last slot's row.
15. A used pin that nothing wires stays blank (CLICK saves such a box: `scr_captures/
    counter_scr.bin`).

Evidence: tumbler (38 pinned rungs), scr_captures (23 clipboard, 34 SCR), pyrung's CLICK-saved
`main.csv` (5 pinned, 3 with grown pins) and its 8 pinned pairs all hit. No checked capture yet
of legs under a drum's or count_down's main input, a pin fed from the main circuit, or legs
drawn on an unused pin's row (section 6).

### NOP, comments, multi-rung

- `NOP` is a 1-row box. A rung of wires and an unwired `NOP` (no contact, no wired box) is left
  as drawn: it has no circuit to lay out (the empty and wire-only ladder goldens).
- Comments are untouched; a split rung keeps its comment on the first part.
- Multi-rung buffers lay out rung by rung; a split inserts rungs in place.

## 3. What it replaces

In `csv/converter.py`: `_or_leg_layout` and `lays_out_or_legs` (orcompact), the tall-box
auto-padding loop, the row arithmetic in `_finalize_pinned_block` / `pinned_gap_height` (pin
rows come from rule 12), and the "rows inside a tall span push down" rule. The parsing of pin
tokens stays (it says which box a pin row feeds). Hydration stays.

In `csv/writer.py`: `_reads_back_compacted`, the `keep_padding` second pass, the
`pinned_gap_height` gap emission and the "an OR leg likely sits on an unused pin's row"
WriterError (with canonical writing, rule 12 decides that row).

Not touched: `encode`, `encode_multi`, `_grid.py` (segment flags), `decode`, `decode_program`.

## 4. Decode and `write_csv`

Today `write_csv` writes the decoded grid and checks that reading it back gives the same grid.
Once `read_csv` lays rungs out, that check fails for every decoded rung that is not in CLICK's
layout (a raw paste before the syntax check): the what-if run below fails 36 tests this way.

### (a) Write options

| option | what the CSV shows | `read_csv(write_csv(r))` | windy road |
|---|---|---|---|
| literal grid (today) | the bytes as drawn | `layout(r)`; the round-trip check must compare circuits | cannot be written (the AF down flag has no CSV token) |
| canonical always | CLICK's checked drawing | `layout(r)`, and the CSV reads back to itself | writes `X001,Y001,-...,out(Y001)` |
| literal unless inexpressible | as drawn, canonical only for an AF down flag | as the first row | as the second row |

Recommendation: **canonical whenever a layout exists, literal otherwise.** `read_csv` re-lays
the CSV out in every option, so the encoded bytes are the same in all three; the options differ
only in what the CSV text shows. Canonical text is what the user sees in CLICK after the check,
reads back to itself (the prototype is idempotent on all 2130 rungs), and makes the writer's
round-trip check a plain equality again. `decode()` keeps returning the literal grid: a `Rung`
stays what the bytes say, and the codec's round trip `decode(encode(x)) == x` is untouched.

For the windy road, `decode` has to keep the AF column's down flags (a new optional `Rung`
field, left out of equality, or a side table) so the writer can build the nets; today they are
dropped and bob/afdown refuses such a rung on decode. With the flag kept, the AF vertical is one
more net link and `windy_road_pasted.bin` writes as `windy_road_checked.bin` holds (the oracle
scores this pair: hit).

### (b) Non-SP rungs and unreachable contacts on decode

The correctness contract says Syntax Check rules (C-codes, which CLICK reports while still
saving the project) do not raise. CLICK pastes the bridge and saves it; only its check reports
C0001. So: no layout exists for these, and the writer writes them literal; `read_csv` reads them
literal (today's path); a separate check reports them. The same holds for the shapes whose CLICK
behaviour is unknown (a contact that feeds no box, a pin sharing contacts with its box's main
input): literal, reported, never silently redrawn.

### (c) What changes if `write_csv` writes canonical

`golden_impact.py` lays out every CSV fixture (`golden_impact.txt`):

| fixture CSVs | rungs | fixed | change | split | no layout |
|---|---|---|---|---|---|
| ladder_captures/golden (45 files) | 62 | 44 | 11 (8 files) | 4 of them | 7 |
| coverage/golden (111) + subroutines (1) | 217 | 217 | 0 | 0 | 0 |
| pinned_or (2) | 11 | 8 | 1 | 0 | 2 |
| v4_captures stubs (2) | 6 | 5 | 1 | 1 | 0 |
| scr_captures decoded CSVs (8) | 417 | 404 | 10 (5 files) | 1 | 3 |
| tumbler clipboard CSVs (34) | 497 | 495 | 2 (2 files) | 0 | 0 |
| tumbler SCR CSVs (34) | 497 | 495 | 2 (2 files) | 0 | 0 |

Decoded-CSV-vs-fixture-CSV mismatches under canonical writing: 14 rungs in 9 decoded-native
CSV files (scr_captures 10 in 5, tumbler 2+2 in 4), plus the ladder goldens below.

Goldens whose `.bin` changes once `read_csv` lays out (each needs a paste check), counting a
rung with no layout as literal:

- split kept as one rung: 6 goldens: `instr-2row-r0only`, `instr-3row-or`,
  `instr-compare-series`, `instr-count_down-row0-data`, `instr-series`, `mr-cmt-3rung-multirow`.
- split emitted as separate rungs: add `instr-copy-multirow-2af` and
  `mr-cmt-3rung-multirow-multiinstructions` (8).
- coverage goldens: none.

What-if runs of the whole suite (`layout_plugin.py`, results in `whatif_read.txt`,
`whatif_write.txt`; the plugin keeps a split or refused rung literal):

- `read_csv` lays out, writer unchanged: 36 failures. The 6 goldens above (encode and decode
  tests, 12), the writer's golden round trip (5), tumbler SCR-vs-clipboard CSV (2: the stored
  clipboard CSV is the literal one), `test_capture_writes_csv` (3), and tests that pin today's
  layout: the writer's dehydrate/hydrate and count_down tests, orcompact's pad-row tests, the
  pinned-OR forms, the forced-raw sweep and native pin-row round trips.
- plus canonical `write_csv`: 30 failures. The writer round trip and `test_capture_writes_csv`
  pass again; `pins__drum_reset_or3` (today a WriterError by design) now writes its canonical
  `(1, 3, 4)` form and `test_shift_requires_three_rows` changes.

### (d) Is the hit rate high enough to trust canonical writing?

On the sources known to be after CLICK's check, yes: 162 of 162 (section 5). Every layout kept
its circuit (2130 of 2130) and was idempotent. The misses on the other native sources are rungs
known to be drawn by hand or pasted and not checked, except two tumbler rungs whose shape is an
open question (section 6, Q1). Canonical writing never changes logic, so a wrong layout rule
costs a redraw by CLICK's check, not a different program. Recommendation: write canonical,
after the Q1 to Q3 captures.

## 5. Oracle

`oracle.py` scores render(tree(rung)) against native layouts: row count, contact label and
right/down flags in every cell, AF token with `pin_rows` on every row, and no AF down flag.

| source | how it is known | hit |
|---|---|---|
| layoutthy-checked.bin, fixed points | after the check | 24/24 |
| or_compact_checked, r30_tallbox_checked, windy-road-after-syntax | after the check | 8/8 |
| pyrung `main.csv` (CLICK saved), fixed points | after the check | 42/42 |
| layoutthy pasted -> checked (rung 23 refused as predicted) | pairs | 24/24 |
| or_compact / r30 / windy pasted -> checked | pairs | 7/7 |
| pyrung pasted -> CLICK saved | pairs | 57/57 |
| tumbler clipboard / tumbler SCR | native, check state unknown | 495/497, 495/497 |
| scr_captures clipboard / SCR | native, hand-drawn experiments, check state unknown | 390/402, 401/417 |
| v4 captures pasted from laddercodec, not checked (informational) | layout is the paster's | 158/162 |

How sources were told apart: a file name or test docstring that says "checked" or "after the
syntax check", or pyrung's `main.csv` (its test docstring: CLICK's saved project after the check)
are checked. `*_pasted.bin` and the v4 pyrung-stub copy-backs (`tests/test_v4_captures.py`
docstring: copy-backs of pasted stubs) are pasted, not checked: paste changes no flag
(layoutthy), so they score laddercodec's layout. Skipped as synthetic: every laddercodec-encoded
golden `.bin`, `scr_captures/time_drums.bin` (README), `scr_captures/pins.scr` (pasted from a
synthetic golden). `ladder_captures/drum_weird_branch.bin` is scored informational only.

Hits cover 81 multi-output and 241 tall-box rungs in tumbler, 13 multi-output and 12 tall-box
rungs in layoutthy, and 46 multi-output pyrung pairs.

### Every miss

| rungs | shape | reading |
|---|---|---|
| tumbler AlmHistorian 0, WarnTimestamp 0 (clipboard and SCR) | Or of two compares at the rail; its merge feeds outputs below the legs; drawn with the merge at B (legs' rows only) and the output bus at C | open (Q1). tumbler `main` rungs 50 to 65 have the same circuit shape with rise/fall legs and are drawn with one vertical, as the layout does |
| or_topology 1, 2, 3, 4, 6, 7 (clipboard and SCR) | one net drawn as two verticals joined by a wire | not checked: pyrung's pasted R29 and R34 were exactly these drawings and CLICK's check collapsed them (`main.csv` R29, R34) |
| coverage 101 (clipboard and SCR) | a 3-row Send in a 4-row rung, last row blank | not checked: the check drops trailing blank rows (layoutthy 9, 19, 24) |
| counter_scr 6, 7 (clipboard and SCR) | count_down's main input drawn from a contact on the token (lead) row, down a vertical at H into the NOP row | open (Q2): hand-built; no checked count_down exists |
| time_drum_b_column 0, time_drums.scr 11 to 14, time_drum_insert_rows 1, 2 | insert-row and branch experiments (README); main input not wired on its row | not checked (the README describes the editing that made them) |
| v4 pins.bin 1 (informational) | a drum reset leg on the unused Jump row, `(1, 2, 3)` | open (Q3): the layout gives `(1, 3, 4)`, which CLICK also writes after Insert Row |
| v4 count_down_or 2 to 4 (informational) | laddercodec's own count_down forms: a contact into the unused Up slot, a blank row between the main input and Reset | laddercodec's paste; open with Q2 |
| drum_weird_branch (informational) | a drum pin teed off the main input's circuit | open (Q4) |

## 6. Consequences to put to the user

1. **Non-SP rungs (C0001) and contacts no rail reaches (C0202).** No layout exists. The brief
   says refuse; the correctness contract says Syntax Check rules do not raise (CLICK saves these
   rungs). Recommendation: encode and write them literal, as today, and report them through a
   separate check (`laddercodec.check(rung)` returning findings), not an exception. Evidence:
   CLICK pasted and saved the bridge and rung 23 and refused them only at check.
2. **Dead wire stubs disappear** (layoutthy 24). Logic is unchanged. Recommendation: accept.
3. **A rung CLICK would split** (circuits that meet only at the rail). Options: refuse, or emit
   two rungs. Recommendation: emit them, comment on the first: it is what CLICK does
   (layoutthy 21, or_compact stub 1), the logic is unchanged, and the author's intent is kept.
   Cost: `read_csv` can return more rungs than the CSV holds, which shifts rung indexes for
   callers (pyrung already exports split rungs, clicknick pastes them in order). Unconditional
   outputs off the rail (`mr-cmt-3rung-multirow-multiinstructions`: `-` then `T` from the rail
   to four coils) would split into four 1-row rungs; no capture shows that yet (Q5).
4. **A decoded raw paste re-encodes logic-identical, not byte-identical.** In the native
   fixtures that is 2 of 497 tumbler rungs and 12 of 402 scr_captures rungs; every checked
   rung re-encodes byte-identical. `decode(encode(x)) == x` itself is unchanged (encode is
   literal).
5. **Goldens that change bytes:** 6 (8 if splits are emitted), listed in section 4(c); 0
   coverage goldens. Each needs a paste check. Seven ladder goldens have no layout (two dead
   contacts on row 1, two unpowered outputs, two pins fed from the main circuit, one spread
   dead contact) and stay literal under recommendation 1.
6. **Contacts that feed no box, and pins sharing the main circuit.** CLICK's behaviour is
   unknown. Recommendation: literal and reported, until Q4 and Q6 are captured.
7. **The CSV can no longer place an unused pin's row or a pad row.** Rule 12 decides it. The
   `drum_reset_or3` shape (a leg on the unused Jump row) becomes `(1, 3, 4)`. Recommendation:
   accept, pending Q3.

## 7. Open questions that need captures

Each is a rung to paste, run the syntax check on, and copy back (one stub can hold them all):

- Q1. AlmHistorian rung 0 and WarnTimestamp rung 0 as they are: does the check join the merge
  at B and the bus at C into one vertical at B? (The layout says yes.)
- Q2. count_down: a contact into its main input, OR legs under the main input, and the same
  drawn from the token row as in `counter_scr.bin` rung 6: where does the check put the input?
- Q3. Drum with Reset OR legs and Jump unused, Jog used: `(1, 2, 3)` with the leg on the Jump
  row, or `(1, 3, 4)`?
- Q4. A pin teed off the main circuit (`drum_weird_branch.bin`, `instr-copy-multirow-2af-T`):
  accepted, redrawn, or an error (C000A, "all inputs of the box instruction must originate from
  the same branch", may be this)?
- Q5. Unconditional outputs off the rail (`- T` to several coils): one rung or one per coil?
- Q6. A contact whose output reaches no box (`instr-2row-cond__and` row 1): an error, or
  dropped?
- Q7. A box with other outputs after it on the same net when it is pinned (a retentive timer
  then `out(Y001)`): the vertical would cross the pin row, so CLICK must draw it some other way
  or refuse it. No capture exists.
- Q8. Rung 23's "Row 3, Column D": 0-based or 1-based (one rung with a known bad cell settles
  it). Needed only for the check's messages.

## 8. Proposed phase 2

1. **layout-check** (no byte change): the separate check API (C0001, C0202, dead contact, pin
   sharing) over a `Rung`, built on `_layout.tree`; tests from the bridge, rung 23 and the seven
   literal goldens.
2. **layout-read**: wire `_layout` into `convert_rung`: pin tokens become slot sinks; no pad
   rows; split rungs emitted (if the user agrees); literal fallback for rungs with no layout.
   Delete `_or_leg_layout`, auto-padding and the pinned gap arithmetic. Regenerate the 6 or 8
   goldens (paste check), update the tests in `whatif_read.txt` that pin today's layout, keep
   the ones that pin CLICK captures.
3. **layout-write**: `write_csv` writes `layout(rung)` when one exists, literal otherwise;
   remove `_reads_back_compacted`, `keep_padding` and the unused-pin WriterError; regenerate the
   9 decoded-native CSV fixtures (tumbler 4, scr_captures 5).
4. **layout-afdown**: `decode` keeps the AF column's down flag; nets use it; windy road writes
   canonical (merge with bob/afdown's refusal).
5. **Captures** Q1 to Q7 in one stub; fold the answers into rules 8 and 11 to 13.
6. **Docs**: `docs/internals/layout.md` from this file; the CSV guide says authors draw wires
   and boxes, not pad rows; CHANGELOG.
