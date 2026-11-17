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
8. A rung is as tall as its lowest contact, box input or box span. Blank rows below, a blank
   first row and wire stubs that join nothing are dropped.
   So is a `NOP` that no rail or contact reaches, in a rung with a circuit; `check()` reports
   nothing for it: CLICK's check gives no error and leaves a rung of `~X002` to
   `latch(Y002)` with stubs at A and C, an unwired `NOP` and a blank row as one row. Any
   other box no rail or contact reaches is reported as `unpowered_box` and its rung stays as
   drawn: CLICK's check on one is not known.
9. Outputs whose circuits meet only at the rail are one CLICK rung each, in order, the comment
   on the first. So `read_csv` can return more rungs than the CSV holds.

## Pinned boxes

A pinned box (Timer, Counter, Shift, Drum) has slots: count_down's unused Up, the main input,
then each pin in its fixed order.

10. The main input is an output item (rule 7); the box's token sits on the slot rows above it,
    and with a lead slot the main row's AF holds `NOP`. A count_down whose Down is drawn from
    the token row is redrawn onto the Down row.
11. Each used pin's circuit starts on its slot row. The first slot after the main input starts
    below every contact placed so far, so OR legs under the main input push the pins down;
    each later slot starts below the circuit above it. An unused pin between used ones takes a
    row of its own there. A drum
    Reset leg on the unused Jump row is redrawn from `(1, 2, 3)` to `(1, 3, 4)`, and the same
    circuit at `(1, 3, 4)` is kept; a count_down `(1, 6)` becomes `(1, 5)` and an event drum
    `(4, 6, 7)` becomes `(3, 5, 6)`.
12. Unused pins after the last used one sit directly under it, beside its legs. A drum at
    `(1, 2, 3)` with Jump and Jog unused is kept, and the same circuit at `(1, 5, 6)` is
    redrawn to `(1, 2, 3)`; a non-retentive on_delay stays at `pin_rows=(1,)` with legs
    below it.
13. `pin_rows` is each slot's row minus the token row; the box ends on its last slot's row.

## Rungs with no layout

A rung `laddercodec.check()` reports has no layout and is read and written as drawn: a circuit
that is not series-parallel (C0001), a contact no rail reaches or that feeds no box (C0202 and
C0003), a contact a wire shorts (C0002), a box above a box with a used pin on its main
input's net or another box's input on a pin's net (C000A), and a pin with no contact of its
own (C0205, C0212). CLICK pastes and
saves these rungs and refuses them only at its check. A rung of wires alone, or with an
unwired `NOP`, has no circuit and is kept as drawn too.

Two findings keep the layout. A pin that no rail or contact reaches (C0202 at its AF cell): the
layout draws its row blank, dropping any wire in it, and CLICK saves such a rung as pasted
when the row holds nothing. A contact that feeds only a `NOP` (C0003): the rung is laid out as
before; CLICK keeps that layout when pasted, and its check on the rung as written is not
captured.

Three more shapes are kept as drawn, with no capture of CLICK's check on them:

- A contact on the circuits of two pins, or of a main input and a pin that has contacts of
  its own as well. Each pin's circuit is drawn on rows of its own, so a layout would draw the
  contact once per input. `check()` reports the later pin: `pin_without_contact` when all its
  contacts are the other pin's (a pin with no contact of its own), else `pin_shares_pin` or
  `pin_shares_main`.
- A rung that would split (rule 9) and holds a `NOP` that a rail or contact reaches. The
  splits known are of coils and Copy boxes.
- A rung the render cannot fit in 31 columns, or whose nets would cross.

Two rungs CLICK's check rewrites with no error are kept as drawn: a `NOP` on a row of its own
beside a coil's rung (`C1 -> out(Y1)`, `- -> NOP`), whose `NOP` CLICK drops, leaving one row;
and a rung of wires alone, which CLICK wires through AF, so that it decodes as wires into a
`NOP`.

## Check rules

`check()` reports the rungs CLICK's syntax check refuses by these rules. A shape no capture
shows is reported with `captured=False`.

14. A contact whose input no line connects to the rail is C0202 at that contact, the first of
    each such group. A path from the rail that reaches no box is C0202 at its last contact,
    and C0003 once for the rung. A contact that feeds a `NOP` and no other box, along
    any path, is `nop_only_contact`, C0003 once for the rung, even when a coil sits on another
    wire of the rung or on another leg of the same split; a `NOP` on the rail alone, or on a
    net a coil shares, is not. A contact whose two sides a wire joins (a contact in parallel
    with a wire-only leg) is C0002.
15. A pin whose row holds nothing (no contact, no wire, no vertical into it) is C0202 at its
    AF cell, the row counted from 1. The captured pins are a timer's and a counter's reset in
    a rung whose rail reaches a box. A pin whose row holds a contact or a wire that no rail
    or contact reaches is C0202 at its AF cell too, not captured.
16. A circuit into the main inputs that is not series-parallel is C0001, the rung's last
    finding: `check()` reports no C000A for the rung, and no finding about a pin's contacts.
    The rung captured has an output above a retentive timer on its net, whose reset has no
    contact of its own; `check()` drops C0212, C000A on a pin's net and the findings with no
    code as well.
17. Two boxes are paired on a net that the rail reaches through a contact, not on the rail
    itself, when one has a used pin (a retentive timer, a counter, a shift, a drum) and:
    the other box's main input is on the pinned box's main input's net, above it
    (`output_above_pinned_box`); or an input of the other box is on one of its pins' nets
    (`shared_input_net`). Each is C000A: CLICK's "All inputs of the box instruction must
    originate from the same branch". Paired boxes are one group, and each group is one
    finding, at its first pinned box with a captured pairing, else at its first pinned box.
    The captured pairings are an output above the pinned box, and a box's main input below
    a pin on a net of the pin's own. A `NOP` as the other box, a pinned box above, a pin's
    net shared with a pin or with a main input above the pin, and a box below on a reset
    teed off the main input are not captured.
18. The boxes of a C000A group get no finding about their pins' contacts. The rung captured
    has a timer's reset on an output's net, a C0205 shape by rule 19; `check()` drops every
    other pin finding of the group too, C0212 and the findings with no code included.
19. A timer's or drum's reset whose contacts are all on a main input's circuit (a reset teed
    off the main input) is C0205 for a timer and C0212 for a drum. A box's own inputs on
    one net pair it with no box, and a box below the pinned box on its main input's net is
    paired only through such a reset.

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
  above a retentive on_delay on C1's net, Reset C3): the shape of C000A with the output
  behind a contact of its own. The box inputs share no net, so rule 17 does not report it,
  and `read_csv` lays it out.
- A box on the net of a reset with no contact of its own (a drum's Reset teed off its main
  input, `copy(...)` below on that net): `check()` reports C000A alone, by rules 17 and 18,
  with `captured=False`; CLICK may accept the rung, or report C0212 or C0205 as well.
- A bridge whose timer reset tees off its own main input: whether CLICK reports C0205 with
  C0001 (rule 16).
- A pin other than a timer's or counter's reset with nothing wired to it (a shift's clock, a
  drum's jog, a counter's down): C0202 by rule 15, not captured. Nor is a pin row that holds
  a wire no rail or contact reaches.
- A rung with two groups of boxes that share nets: whether CLICK prints C000A once or once
  per group.
- A rung with a `NOP` no rail or contact reaches and outputs that meet only at the rail
  (`C1 -> out(Y1)`, an unwired `NOP` row, `C2 -> out(Y2)`): `read_csv` drops the `NOP`, then
  splits the rung in two. No capture shows CLICK's check doing both on one rung.
- A contact two pins share: CLICK's code for it, if it refuses it.
- A `NOP` reached only by contacts that also reach a coil: `check()` reports nothing, as for a
  `NOP` on a coil's net. Probed, not captured: C1 splits with a wire to the `NOP` and C2 to a
  coil; a shorted contact into a `NOP` (C0002 only); an unrailed contact into a `NOP`; a rail
  wire to a coil plus a contact off the rail into a `NOP`.
