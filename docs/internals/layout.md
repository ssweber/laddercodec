# Layout

`read_csv` lays every rung out as CLICK's syntax check draws it, and `write_csv` writes that
drawing. A CSV author writes contacts, wires and boxes; the reader decides the rows a box's
height takes, where OR legs and outputs sit, and where each pin of a pinned box goes. The
circuit never changes: only cells move, and a rung CLICK would split becomes several rungs.

`encode()` and `decode()` don't lay out. `encode(rung)` writes the grid it is given, and
`decode()` returns the grid the bytes hold, so `decode(encode(x)) == x` holds for any `Rung`.

The code is `laddercodec._layout`. Ground truth is CLICK v4's copy-back of pasted rungs before
and after its syntax check (`tests/fixtures/v4_captures/*_pasted.bin` and `*_checked.bin`);
`tests/test_layout.py` checks every checked capture and every pasted-to-checked pair.

## Pipeline

```
CSV rows ──read──> literal grid ──nets──> network ──reduce──> tree per CLICK rung ──render──> grid
```

- **Literal grid.** The CSV read as written (`csv.converter.convert_literal`): `T` and `|`
  hydrated, pin tokens on their rows, tall boxes padded.
- **Network.** A grid point `(row, x)` is the left edge of column `x`; `x = 0` is the rail and
  `x = 31` the AF input. A wire flag joins two points, a contact is a directed edge from
  `(row, c)` to `(row, c + 1)`, and a down flag joins `(row, c)` to `(row + 1, c)`. Joined
  points are one net. A box input is the net at `(row, 31)` on each of its slot rows.
- **Tree.** Series-parallel reduction: two edges with the same ends are a parallel block, and
  a net with one edge in and one out joins them in series. The boxes on one net are one block
  of output items. Each pin input is reduced on its own, from the rail to its pin.
- **Render.** Gives every net a column and every contact and box a row, by the rules below.

## Columns

1. Each net is one vertical, on the left edge of column `col(net)`; the rail is column 0.
   `col(dst) = max(col(src) + 1)` over the contacts into `dst`. Evidence: layoutq Q1a to Q1c
   (a merge at B and an output bus at C redrawn as one vertical at B); layoutq2, where every
   OR merge moved to the column after its last contact (P01, P02, P05, P06, P08, P10, P12,
   P17 to P20).
2. A contact sits in cell `col(src)` on its row, and wire fills the cells up to `col(dst)`.
   Contacts pack left: layoutq2 P20's contacts moved from B to A and the rail wire before them
   went. A series contact after a merge sits in the merge's column carrying its vertical
   (`T:X002`, layoutthy rung 3).
3. A box input gets wire from `col(net)` to AE on its row. A pin's legs longer than the main
   input keep the main input's wire out to the longest leg (layoutq2 P04, P06, P12).
4. A net's vertical runs from the topmost to the bottommost row that touches it.

## Rows

5. Series terms start on the same top row; a series block is as tall as its tallest term.
   Series contacts around an OR keep their order (layoutq2 P02, P04, P09, P17).
6. The legs of a parallel block stack down from the block's top, in their order in the
   source. Blank rows inside an OR are dropped (layoutq2 P01, P07, P09, P16, P19), and so is
   a blank row between two ORs (P03).
7. The output items of a net stack down in output order. A box goes on the later of its
   net's next row and the first AF row below the box above; boxes never overlap. A box spans its height
   (`cell_params()["visual_rows"]`: Copy 2, Send and Receive 3; a raw box its stored height),
   and the condition side packs up beside it. Evidence: `or_compact_checked.bin`,
   `r30_tallbox_checked.bin`; layoutq2 P18 (an out under a non-retentive on_delay moved up to
   row 2) and P19 (an out under a Send moved up to row 3). A branch after the output split
   starts on the row of its first box (layoutthy rung 6).
8. A rung is as tall as its lowest contact, box input or box span. Blank rows below, a blank
   first row and wire stubs that join nothing are dropped (layoutthy rungs 9, 19, 24).
9. Outputs whose circuits meet only at the rail are one CLICK rung each, in order, the comment
   on the first (layoutthy rung 21, `or_compact_stub.csv` rung 2, layoutq Q5a to Q5c). So
   `read_csv` can return more rungs than the CSV holds.

## Pinned boxes

A pinned box (Timer, Counter, Shift, Drum) has slots: count_down's unused Up, the main input,
then each pin in its fixed order.

10. The main input is an output item (rule 7); the box's token sits on the slot rows above it,
    and with a lead slot the main row's AF holds `NOP`. A count_down whose Down is drawn from
    the token row is redrawn onto the Down row (layoutq Q2c).
11. Each used pin's circuit starts on its slot row. The first slot after the main input starts
    below every contact placed so far, so OR legs under the main input push the pins down;
    each later slot starts below the circuit above it. An unused pin between used ones takes a
    row of its own there (layoutq2 P06's Down, P10's Jump). Evidence: layoutq Q3a, a drum
    Reset leg on the unused Jump row redrawn from `(1, 2, 3)` to `(1, 3, 4)`, and Q3b
    (layoutq2 P11), the same circuit at `(1, 3, 4)`, kept; layoutq2 P07 (count_down `(1, 6)` to
    `(1, 5)`) and P16 (event drum `(4, 6, 7)` to `(3, 5, 6)`).
12. Unused pins after the last used one sit directly under it, beside its legs. Evidence:
    layoutq2 P13 (a drum at `(1, 2, 3)`, Jump and Jog unused, kept), P14 (the same circuit at
    `(1, 5, 6)`, redrawn to `(1, 2, 3)`); tumbler ProductionErrors (a non-retentive
    on_delay stays at `pin_rows=(1,)` with legs below it).
13. `pin_rows` is each slot's row minus the token row; the box ends on its last slot's row.

## Rungs with no layout

A rung `laddercodec.check()` reports has no layout and is read and written as drawn: a circuit
that is not series-parallel (C0001), a contact no rail reaches or that feeds no box (C0202 and
C0003), an output above a pinned box on its net (C000A, layoutq Q7a and Q7c), and a pin with no
contact of its own (C0205, C0212, layoutq Q4a and Q4b). CLICK pastes and saves these rungs and
refuses them only at its check. A rung of wires alone, or with an unwired `NOP`, has no circuit
and is kept as drawn too.

Three more shapes are kept as drawn, with no capture of CLICK's check on them:

- A contact on the circuits of a pin and of another box input. Each pin's circuit is drawn
  on rows of its own, so a layout would draw the contact once per input. `check()` reports a
  pin whose contacts are all another input's as `pin_without_contact` (the shape of Q4a and
  Q4b), and one with some of its own as `pin_shares_main` or `pin_shares_pin`.
- A rung that would split (rule 9) and holds a `NOP`. The captured splits are of coils and
  Copy boxes.
- A rung the render cannot fit in 31 columns, or whose nets would cross.

## Writing CSV

`write_csv` writes each rung's layout and checks that the rows read back to it exactly. A
decoded rung that is not in CLICK's layout, such as a paste copied back before the syntax
check, is written in the layout, which may be several rungs; the writer checks that their
circuit is the decoded rung's, each contact in it exactly once. A rung with no layout is
written as stored and reads back as stored, except that blank rows at its end can read back
as a tall box's own rows and be dropped; the writer warns when they are.

## Open questions

For the next capture round:

- An output above a pinned box on one net reached through a branch (`C1,T:C2 -> out(Y1)`
  above a retentive on_delay on C1's net, Reset C3): Q7a's shape (C000A) with the output
  behind a contact of its own. `check()` does not report it, and `read_csv` lays it out.
- A `NOP` on a net of its own beside a coil (`C1 -> out(Y1)`, `- -> NOP`): whether CLICK
  splits it into a rung of its own. Kept as drawn until a capture shows it.
- A contact two pins share: CLICK's code for it, if it refuses it.
