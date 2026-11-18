# Layout

`read_csv` lays every rung out as CLICK's syntax check draws it, and `write_csv` writes that
drawing. A CSV author writes contacts, wires and boxes. The reader decides the rows that a
box's height takes, where OR legs and outputs sit, and where each pin of a pinned box goes.
The circuit never changes. Only cells move, and a rung that CLICK would split becomes several
rungs.

`encode()` and `decode()` don't lay out. `encode(rung)` writes the grid it is given, and
`decode()` returns the grid that the bytes hold. So `decode(encode(x)) == [x]` holds for any
`Rung`.

The code is `laddercodec._layout`. Ground truth is CLICK v4's copy-back of pasted rungs before
and after its syntax check (`tests/fixtures/v4_captures/*_pasted.bin` and `*_checked.bin`).
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
   `col(dst) = max(col(src) + 1)` over the contacts into `dst`.
   An OR merge sits in the column after its last contact.
2. A contact sits in cell `col(src)` on its row, and wire fills the cells up to `col(dst)`.
   Contacts pack left, and no rail wire stands before them. A series contact after a merge
   sits in the merge's column carrying its vertical (`T:X002`).
3. A box input gets wire from `col(net)` to AE on its row. A pin's legs longer than the main
   input keep the main input's wire out to the longest leg.
4. A net's vertical runs from the topmost to the bottommost row that touches it.

## Rows

5. Series terms start on the same top row; a series block is as tall as its tallest term.
   Series contacts around an OR keep their order.
6. The legs of a parallel block stack down from the block's top, in their order in the
   source. Blank rows inside an OR are dropped, and so is
   a blank row between two ORs.
7. The output items of a net stack down in output order. A box goes on the later of its
   net's next row and the first AF row below the box above; boxes never overlap. A box spans its height
   (`cell_params()["visual_rows"]`: Copy 2, Send and Receive 3; a raw box its stored height),
   and the condition side packs up beside it. An out under a non-retentive on_delay moves up
   to row 2, and one under a Send to row 3. A branch after the output split starts on the row
   of its first box.
8. A rung is as tall as its lowest contact, box input or box span. The layout drops blank
   rows below, a blank first row and wire stubs that join nothing. It also drops a `NOP` that
   no rail or contact reaches, in a rung with a circuit. `check()` reports nothing for it.
   CLICK's check gives no error for it, and leaves a rung of `~X002` to `latch(Y002)` with
   stubs at A and C, an unwired `NOP` and a blank row as one row. `check()` reports any other
   box that no rail or contact reaches as `unpowered-box`, and its rung stays as drawn.
   CLICK's check on one is not known.
9. Outputs whose circuits meet only at the rail are one CLICK rung each, in order, the comment
   on the first. So `read_csv` can return more rungs than the CSV holds.

## Pinned boxes

A pinned box (Timer, Counter, Shift, Drum) has slots: count_down's unused Up, the main input,
then each pin in its fixed order.

10. The main input is an output item (rule 7); the box's token sits on the slot rows above it,
    and with a lead slot the main row's AF holds `NOP`. A count_down whose Down is drawn from
    the token row is redrawn onto the Down row.
11. Each used pin's circuit starts on its slot row. The first slot after the main input starts
    below every contact placed so far, so OR legs under the main input push the pins down.
    Each later slot starts below the circuit above it. An unused pin between used ones takes
    a row of its own there. A drum Reset leg on the unused Jump row is redrawn from
    `(1, 2, 3)` to `(1, 3, 4)`, and the same circuit at `(1, 3, 4)` is kept. A count_down
    `(1, 6)` becomes `(1, 5)`, and an event drum `(4, 6, 7)` becomes `(3, 5, 6)`.
12. Unused pins after the last used one sit directly under it, beside its legs. A drum at
    `(1, 2, 3)` with Jump and Jog unused is kept, and the same circuit at `(1, 5, 6)` is
    redrawn to `(1, 2, 3)`. A non-retentive on_delay stays at `pin_rows=(1,)` with legs
    below it.
13. `pin_rows` is each slot's row minus the token row; the box ends on its last slot's row.

## Rungs with no layout

A rung that `laddercodec.check()` reports has no layout. `read_csv` and `write_csv` handle it
as drawn. These are the shapes:

- a circuit that is not series-parallel (C0001)
- a contact that no rail reaches or that feeds no box (C0202 and C0003)
- a contact that a wire shorts (C0002)
- a box above a box with a used pin on its main input's circuit, or another box's input on a
  pin's net (C000A)
- a pin with no contact of its own (C0205, C0212)

CLICK pastes and saves these rungs and refuses them only at its check. A rung of wires alone,
or with an unwired `NOP`, has no circuit and is kept as drawn too.

Two findings keep the layout:

- A pin that no rail or contact reaches (C0202 at its AF cell). The layout draws its row
  blank and drops any wire in it. CLICK saves such a rung as pasted when the row holds
  nothing.
- A contact that feeds only a `NOP` (C0003). The rung is laid out as before. CLICK keeps that
  layout when pasted. Its check on the rung as written is not captured.

Three more shapes are kept as drawn, with no capture of CLICK's check on them:

- A contact on the circuits of two pins, or of a main input and a pin that has contacts of
  its own as well. Each pin's circuit is drawn on rows of its own, so a layout would draw the
  contact once per input. `check()` reports the later pin. The finding is
  `input-without-contact` when all its contacts are the other pin's (a pin with no contact of
  its own). Otherwise it is `inputs-share-contacts` or `input-shares-enable`.
- A rung that would split (rule 9) and holds a `NOP` that a rail or contact reaches. The
  splits known are of coils and Copy boxes.
- A rung the render cannot fit in 31 columns, or whose nets would cross.

CLICK's check rewrites two more rungs with no error. Both are kept as drawn:

- a `NOP` on a row of its own beside a coil's rung (`C1 -> out(Y1)`, `- -> NOP`). CLICK
  drops the `NOP` and leaves one row.
- a rung of wires alone. CLICK wires it through AF, so that it decodes as wires into a
  `NOP`.

## Check rules

`check()` reports the rungs CLICK's syntax check refuses by these rules. A shape no capture
shows is reported with `captured=False`.

14. `check()` reports these contact shapes:
    - A contact whose input no line connects to the rail is C0202 at that contact, the
      first of each such group.
    - A path from the rail that reaches no box is C0202 at its last contact, and C0003
      once for the rung.
    - A contact that feeds a `NOP` and no other box, along any path, is
      `contact-feeds-only-nop`: C0003 once for the rung. This holds even when a coil sits on
      another wire of the rung or on another leg of the same split. A `NOP` on the rail
      alone, or on a net that a coil shares, does not count.
    - A contact whose two sides a wire joins (a contact in parallel with a wire-only
      leg) is C0002.
15. A pin whose row holds nothing (no contact, no wire, no vertical into it) is C0202 at
    its AF cell, with the row counted from 1. The captured pins are a timer's and a
    counter's reset in a rung whose rail reaches a box. A pin whose row holds a contact
    or a wire that no rail or contact reaches is also C0202 at its AF cell. That case is
    not captured.
16. A circuit into the main inputs that is not series-parallel is C0001, the rung's last
    finding. `check()` reports no C000A for the rung, and no finding about a pin's
    contacts. The rung captured has an output above a retentive timer on its net, whose
    reset has no contact of its own. For it, `check()` also drops C0212, C000A on a pin's
    net and the findings with no code.
17. Two boxes are paired on a net that the rail reaches through a contact, not on the rail
    itself, when one has a used pin (a retentive timer, a counter, a shift, a drum) and one
    of these holds:
    - the other box's main input is above the pinned box, on the pinned box's main
      input's net or on a net that the main input's circuit runs through from the rail
      (`output-above-box-inputs`)
    - an input of the other box is on the net of one of the pinned box's pins
      (`shared-input-net`)

    Each is C000A: CLICK's "All inputs of the box instruction must originate from the same
    branch". Paired boxes are one group, and each group is one finding. The finding is at
    the group's first pinned box with a captured pairing, or else at its first pinned box.
    The captured pairings are an output above the pinned box, and a box's main input below
    a pin on a net of the pin's own. These are not captured: a `NOP` as the other box, a
    pinned box above, a pin's net shared with a pin or with a main input above the pin, and
    a box below on a reset teed off the main input.
18. The boxes of a C000A group get no finding about their pins' contacts. The rung captured
    has a timer's reset on an output's net, a C0205 shape by rule 19. `check()` drops every
    other pin finding of the group too, including C0212 and the findings with no code.
19. A timer's or drum's reset whose contacts are all on a main input's circuit (a reset
    teed off the main input) is C0205 for a timer and C0212 for a drum. A box's own inputs
    on one net pair it with no box. A box below the pinned box on its main input's net is
    paired only through such a reset.

## Building from a circuit

`lay_out()` starts from a `Circuit` instead of a grid. `_layout/build.py` builds the network
straight from it, and `trees()` and `render()` draw it as they draw a grid's network.

- **Nets.** Net 0 is the rail. Each term of a series ends on a new net, and the next term
  starts on that net. The last term ends on the net where the series ends. All legs of a
  `Parallel` start on the same net and end on the same net.
- **Order.** The builder numbers contacts and box inputs depth-first in source order and
  gives each that number as its row. The tree orders OR legs and output items by row, so
  they keep the order the caller wrote. The builder doesn't factor or sort anything.
- **Boxes.** A box takes a slot for each of its rows. A pinned box marks the slots of the
  pins it uses, and each pin term starts on the rail. A used pin with no term gets a net
  that nothing reaches, so it is drawn blank and `check()` reports it (C0202).
- **Wire legs.** For each `Series(())` leg of a `Parallel`, the builder adds an edge whose
  contact is the marker `WIRE_LEG`. `render()` draws that edge as `-` on a row of its own.
  A network read from a grid has no such edge. In a grid, a wire beside a contact joins the
  contact's two nets into one net, and the network lists the contact in `bypassed`.
- **Errors.** `lay_out()` raises `LayoutError` for a rung of more than 32 rows
  (`layout-too-tall`), more than 31 condition columns (`layout-too-wide`), nets that cross
  (`layout-cannot-draw`), and a split rung that holds a `NOP` (`layout-nop-split`). It also
  raises `C000A` for a box before or after a box with a used pin, where the other box hangs
  off the pinned box's main input circuit. The code is `output-above-box-inputs` for a box
  before the pinned box, as `check()` reports it. It is `shared-input-net` for a box after
  it, because the pin rows would cross the wire down to that box. It does not raise for any
  other `check()` finding.

`tests/test_circuit_round_trip.py` reads every laid-out rung of the fixtures back to a
circuit and checks that `lay_out()` gives the same bytes.

## Writing CSV

`write_csv` writes each rung's layout and checks that the rows read back to it exactly. If a
decoded rung is not in CLICK's layout (for example a paste copied back before the syntax
check), `write_csv` writes it in the layout, which may be several rungs. The writer checks
that their circuit is the decoded rung's, with each contact in it exactly once. `write_csv`
writes a rung with no layout as stored, and it reads back as stored. The exception is blank
rows at its end. They can read back as a tall box's own rows and be dropped, and the writer
warns when they are.

`read_csv` and `write_csv` refuse a rung of more than 32 rows (`layout-too-tall`).
`_layout.drawn()` checks the height of each rung that they keep. Those are the rungs of the
layout, or the rung as drawn when it has no layout. `render()` never sees a rung with no
layout, so the check is not in `render()`. The count includes every row that a box spans
(`visual_rows`). A rung of more than 32 rows still reads and writes when its layout is rungs
of 32 rows or fewer.

## Open questions

For the next capture round:

- An output above a pinned box on one net reached through a branch (`C1,T:C2 -> out(Y1)`
  above a retentive on_delay on C1's net, Reset C3). This is the shape of C000A with the
  output behind a contact of its own. The box inputs share no net, so rule 17 does not
  report it, and `read_csv` lays it out.
- A box on the net of a reset with no contact of its own (a drum's Reset teed off its main
  input, `copy(...)` below on that net). `check()` reports C000A alone, by rules 17 and 18,
  with `captured=False`. CLICK may accept the rung, or report C0212 or C0205 as well.
- A bridge whose timer reset tees off its own main input. Does CLICK report C0205 with
  C0001 (rule 16)?
- A pin other than a timer's or counter's reset with nothing wired to it (a shift's clock,
  a drum's jog, a counter's down). `check()` reports C0202 by rule 15, not captured. A pin
  row that holds a wire no rail or contact reaches is not captured either.
- A rung with two groups of boxes that share nets. Does CLICK print C000A once, or once per
  group?
- A rung with a `NOP` no rail or contact reaches and outputs that meet only at the rail
  (`C1 -> out(Y1)`, an unwired `NOP` row, `C2 -> out(Y2)`). `read_csv` drops the `NOP`, then
  splits the rung in two. No capture shows CLICK's check doing both on one rung.
- A contact that two pins share. What code does CLICK give it, if it refuses it?
- A `NOP` reached only by contacts that also reach a coil. `check()` reports nothing, as
  for a `NOP` on a coil's net. These were probed and not captured:
  - C1 splits with a wire to the `NOP` and C2 to a coil
  - a shorted contact into a `NOP` (C0002 only)
  - an unrailed contact into a `NOP`
  - a rail wire to a coil plus a contact off the rail into a `NOP`
