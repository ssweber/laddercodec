# Layout check fixtures

Evidence for `laddercodec.check()`: rungs CLICK's syntax check accepted, and the two it refused.

- `layoutthy-pasted.bin`: CLICK v4 copy-back of a 24-rung stub right after paste, before the
  syntax check. The check refused rung 23 (index 22) with `error C0202: Row 3, Column D : Missing
  line connection` (listed twice) and `error C0001: Line connection error`; it accepted the other
  23 and redrew some of them.
- `layoutthy-checked.bin`: the same stub copied back after the syntax check, with rung 23 deleted.
- `windy-road.bin`: a hand-drawn rung whose path runs through the AF column's down flag on row 0;
  CLICK's check accepted it and redrew it as `windy-road-after-syntax.bin`. laddercodec's decode
  drops that flag, so the decoded rung has no path (the check's test for it is expected to fail).
- `wheatstone_bridge.csv`: pyrung's bridge rung (`tests/fixtures/wheatstone_bridge.csv` in
  pyrung). CLICK pastes and saves it; its check reports C0001.
- `pyrung_topology_pasted-2026-11-12.csv`, `pyrung_topology_pasted-2026-11-13.csv`: pyrung's
  topology rungs as pasted; `pyrung_topology_saved.csv`: the same rungs in the project CLICK saved
  after its check (pyrung `tests/click/ladder_topology_golden/`). The check accepted every rung.
