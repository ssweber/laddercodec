# SCR fixture provenance

`coverage`, `counter_scr`, `or_topology`, and `shift_scr` pair native SCR files with clipboard captures. Their decoded geometry and wire mappings are comparison evidence.

`time_drums.scr` is a native SCR capture. **`time_drums.bin` is synthetic**: commit `be211ee` (v0.1.9 / PR #15, `test(scr): golden fixture for time drums`) says it was encoded from the verified canonical CSV, with a native clipboard capture left for future replacement. It is not independent evidence of CLICK's clipboard output.

The CSV/BIN keep their original canonical content. SCR rungs 13 and 14 contain additional wire rows that the decoder now preserves. Tests check these stored rows explicitly instead of deleting them to match the generated BIN. Tall-span NOP suppression remains a separate semantic convention shared with clipboard decoding.

The same-state native insertion and branch fixtures below distinguish covered NOPs from legitimate wire rows. The synthetic BIN remains useful as canonical input, but is not evidence of native normalization.

## Native drum insertion experiment (2026-09-10)

`time_drum_insert_rows.{scr,bin,csv,png}` are the user's `time_drum.*` captures. Unlike the older `time_drums.bin`, this BIN is a native CLICK clipboard capture. The screenshot and rung comments identify the construction:

1. Place a time drum normally on a fresh rung.
2. Insert one row above a NOP, then place the drum on the new top row.
3. Insert two rows above a NOP, then place the drum on the new top row.

Each rung stores four ordinary rows. The original row retains flag 1 and all 32 segment-1 wire entries at grid row 0, 1, or 2 respectively. In rungs 2/3, the unoccupied AF right-wire still decodes as a raw NOP underneath the drum span. Both public decoders suppress its NOP label while preserving the horizontal wires, matching the screenshot and CSV. All 384 compared cells agree between SCR and native clipboard; both decoded CSVs reproduce the supplied CSV byte-for-byte.

This establishes that the NOP's underlying wired row survives in these cases. The inserted rows are empty, so the removed heuristic's nonempty-row guard would also have kept these examples. The branch fixture below exercises that guard with a populated upper row.

## Native branch above the original wired row (2026-09-10)

`time_drum_b_column.{scr,bin,csv}` captures the one-inserted-row case after wiring B through AE on the upper row, leaving A blank, and adding a down connection at B to the original wired row. The SCR was snapshotted from the supplied CLICK `Scr1.tmp`; BIN/CSV were supplied through `clicknick-rung save time_drum_b_column`. Preserve the captured comment literally, including the question mark substituted for the dash by the originating application.

The upper row has flag 0, B segment 0, and C through AE segment 1. The lower original row has flag 1 and all 32 segment-1 entries, including the covered AF/NOP wire. The down list connects row 0 at column B. These four flag mappings agree at all 128 cells between SCR and native clipboard, and both decoders reproduce the supplied CSV byte-for-byte.

This is a native counterexample to the removed deletion rule: the upper row is nonempty and the following row has the all-segment-1 rail signature, yet CLICK's clipboard preserves both rows and the branch. Running the pre-change decoder (the version with `_resync_trailing_rung` and the row-0-signature deletion rule) deletes the branch and shifts the lower wire onto the drum's top row. The updated decoder preserves the branch and suppresses only the covered NOP token.

The condition-side geometry, row flags, and down list match the older time_drums rung 13; that older SCR additionally has a segment-0 AF wire entry on the upper row. Exact editing history of the older fixture is unnecessary to establish that the generic deletion rule was invalid.
