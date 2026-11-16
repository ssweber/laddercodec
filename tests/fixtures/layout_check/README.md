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
- `check_shapes.csv`: 16 rungs pasted into CLICK v4.00 as one main program, and
  `check_shapes_errors.txt`: CLICK v4.00's Syntax Check answer on those pasted rungs, its
  lines as CLICK printed them (rungs and rows from 1; the last line, C0201, is the program's
  missing `end()`). The rungs are bridges, pinned boxes whose inputs share or do not share a
  branch, comments, wires and `NOP`s, and a timer and a counter with an unwired reset; the
  4-row rung of a counter and a timer reads as two rungs, 3 and 4. The shapes come from
  pyrung's `tests/fixtures/user_shapes/` and its bridge. `check_shapes_checked.scr` is the
  `Scr1.tmp` CLICK saved after that check. `tests/test_check_shapes.py` compares `check()`
  with the answer and `read_csv` with the saved rungs.
