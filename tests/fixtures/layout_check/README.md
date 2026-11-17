# Layout check fixtures

Evidence for `laddercodec.check()`: rungs CLICK's syntax check accepted, and those it refused.
The CLICK captures are in `v4_captures/`; the pyrung CSVs are here.

- `v4_captures/layoutthy_pasted.bin`: CLICK v4 copy-back of a 24-rung stub right after paste,
  before the syntax check. The check refused rung 23 (index 22) with `error C0202: Row 3, Column
  D : Missing line connection` (listed twice) and `error C0001: Line connection error`. The
  check reads the cell as the contact X010, zero-based (3, D), with CLICK counting rows from 1
  after the rung's blank first row. This rung is the only evidence for that reading; CLICK may
  instead name the blank cell (2, D). CLICK accepted the other 23 and redrew some of them.
- `v4_captures/layoutthy_checked.bin`: the same stub copied back after the syntax check, with
  rung 23 deleted.
- `v4_captures/layoutq_pasted.bin`, `v4_captures/layoutq_checked.bin`: the 21-rung stub
  `v4_captures/layoutq_stub.csv` copied back before and after CLICK v4's syntax check, each
  followed by the subroutine's own `return()` rung. CLICK's error list is in
  `tests/test_layout_check.py` (`_LAYOUTQ_ERRORS`); the refused rungs were deleted from the
  checked copy.
- `v4_captures/layoutq2_pasted.bin`, `v4_captures/layoutq2_checked.bin`: 20 rungs of pinned
  boxes, then the subroutine's `return()`, before and after a syntax check that accepted all.
- `v4_captures/windy_road_checked.bin`: CLICK's check redrawing `windy_road_pasted.bin`, whose
  path runs down the AF column (decode refuses the pasted one).
- `wheatstone_bridge.csv`: pyrung's bridge rung (`tests/fixtures/wheatstone_bridge.csv` in
  pyrung). CLICK pastes and saves it; its check reports C0001.
- `pyrung_topology_pasted-2026-11-12.csv`, `pyrung_topology_pasted-2026-11-13.csv`: pyrung's
  topology rungs as pasted; `pyrung_topology_saved.csv`: the same rungs in the project CLICK saved
  after its check (pyrung `tests/click/ladder_topology_golden/`). The check accepted every rung.
- `accepted_shapes.csv`: four rungs pasted into CLICK v4.00 as one main program: a contact in
  parallel with a wire-only leg, a contact feeding only a `NOP`, two contacts in parallel
  feeding only a `NOP`, and `end()`. CLICK pasted all four and its check rewrote none.
  `accepted_shapes_errors.txt` is CLICK's Syntax Check output as printed (rungs from 1):
  C0002 on rung 1, C0003 on rungs 2 and 3. `accepted_shapes_checked.scr` is the `Scr1.tmp`
  CLICK saved after the check, and `accepted_shapes_pasted.clip.bin` the clipboard payload
  that was pasted. `tests/test_accepted_shapes.py` compares `check()` with the answer,
  `read_csv` with the saved rungs, and `encode()` with the payload.
- `two_wires.csv`: a contact feeding only a `NOP` on one wire, and a contact feeding a coil on
  another, in both row orders, pasted as one main program with `end()`. CLICK kept all three
  rungs; its check answered C0003 on rungs 1 and 2 and rewrote nothing.
  `two_wires_errors.txt`, `two_wires_checked.scr` and `two_wires_pasted.clip.bin` are as for
  `accepted_shapes`; `tests/test_accepted_shapes.py` covers them.
- `nop_leg.csv`: a contact into a `NOP` on one leg of a split and a coil on the other, in both
  orders, pasted with `end()`. CLICK kept all three rungs; its check answered C0003 on rungs 1
  and 2 and rewrote nothing. The payload pasted holds rung 2 with C2 on the branch cell
  (`T:C2`), where the CSV has `T,C2`; `read_csv` lays it out as `T:C2`.
  `nop_leg_errors.txt`, `nop_leg_checked.scr` and `nop_leg_pasted.clip.bin` are as for
  `accepted_shapes`; `tests/test_accepted_shapes.py` covers all three.
- `check_shapes.csv`: 16 rungs pasted into CLICK v4.00 as one main program, and
  `check_shapes_errors.txt`: CLICK v4.00's Syntax Check answer on those pasted rungs, its
  lines as CLICK printed them (rungs and rows from 1; the last line, C0201, is the program's
  missing `end()`). The rungs are bridges, pinned boxes whose inputs share or do not share a
  branch, comments, wires and `NOP`s, and a timer and a counter with an unwired reset; the
  4-row rung of a counter and a timer reads as two rungs, 3 and 4. The shapes come from
  pyrung's `tests/fixtures/user_shapes/` and its bridge. `check_shapes_checked.scr` is the
  `Scr1.tmp` CLICK saved after that check. `tests/test_check_shapes.py` compares `check()`
  with the answer and `read_csv` with the saved rungs.
