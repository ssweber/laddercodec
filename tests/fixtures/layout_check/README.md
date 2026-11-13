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
