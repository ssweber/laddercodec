# Layout check fixtures

Evidence for `laddercodec.check()`: rungs CLICK's syntax check accepted, and the two it refused.
The CLICK captures are in `v4_captures/`; the pyrung CSVs are here.

- `v4_captures/layoutthy_pasted.bin`: CLICK v4 copy-back of a 24-rung stub right after paste,
  before the syntax check. The check refused rung 23 (index 22) with `error C0202: Row 3, Column
  D : Missing line connection` (listed twice) and `error C0001: Line connection error`. CLICK
  counts rows from 1 (layoutq Q8a, Q8b), so its cell is zero-based (2, D); `check()` reports
  (3, D), the contact X010, and which cell CLICK names for C0202 is open. CLICK
  accepted the other 23 and redrew some of them.
- `v4_captures/layoutthy_checked.bin`: the same stub copied back after the syntax check, with
  rung 23 deleted.
- `v4_captures/windy_road_checked.bin`: CLICK's check redrawing `windy_road_pasted.bin`, whose
  path runs down the AF column (decode refuses the pasted one).
- `wheatstone_bridge.csv`: pyrung's bridge rung (`tests/fixtures/wheatstone_bridge.csv` in
  pyrung). CLICK pastes and saves it; its check reports C0001.
- `pyrung_topology_pasted-2026-11-12.csv`, `pyrung_topology_pasted-2026-11-13.csv`: pyrung's
  topology rungs as pasted; `pyrung_topology_saved.csv`: the same rungs in the project CLICK saved
  after its check (pyrung `tests/click/ladder_topology_golden/`). The check accepted every rung.
