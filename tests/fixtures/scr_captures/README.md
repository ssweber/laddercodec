# SCR fixture provenance

`coverage`, `counter_scr`, `or_topology`, and `shift_scr` pair native SCR files with clipboard captures. Their decoded geometry and wire mappings are comparison evidence.

`pins.scr` is CLICK's `Scr1.tmp` after pasting the `pins__v4` coverage golden (pins with OR legs). Its clipboard pair is that golden, which is synthetic: the SCR is evidence of how CLICK stores grown pin rows (each part's 1-based rung row, e.g. a drum's `01 02 04 05`), not of clipboard output. The native clipboard evidence is `v4_captures/pins.bin`.

`time_drums.scr` is a native SCR capture. **`time_drums.bin` is synthetic**: commit `be211ee` (v0.1.9 / PR #15, `test(scr): golden fixture for time drums`) says it was encoded from the verified canonical CSV, with a native clipboard capture left for future replacement. It is not independent evidence of CLICK's clipboard output.

The CSV/BIN keep their original canonical content. SCR rungs 13 and 14 contain additional wire rows that the decoder now preserves. Tests check these stored rows explicitly instead of deleting them to match the generated BIN. Tall-span NOP suppression remains a separate semantic convention shared with clipboard decoding.

The same-state native insertion and branch fixtures below distinguish covered NOPs from legitimate wire rows. The synthetic BIN remains useful as canonical input, but is not evidence of native normalization.

## Native drum insertion experiment

`time_drum_insert_rows.{scr,bin,csv,png}` are the user's `time_drum.*` captures. Unlike the older `time_drums.bin`, this BIN is a native CLICK clipboard capture. The screenshot and rung comments identify the construction:

1. Place a time drum normally on a fresh rung.
2. Insert one row above a NOP, then place the drum on the new top row.
3. Insert two rows above a NOP, then place the drum on the new top row.

Each rung stores four ordinary rows. The original row retains flag 1 and all 32 segment-1 wire entries at grid row 0, 1, or 2 respectively. In rungs 2/3, the unoccupied AF right-wire still decodes as a raw NOP underneath the drum span. Both public decoders suppress its NOP label while preserving the horizontal wires, matching the screenshot and CSV. All 384 compared cells agree between SCR and native clipboard; both decoded CSVs reproduce the supplied CSV byte-for-byte.

This establishes that the NOP's underlying wired row survives in these cases. The inserted rows are empty, so the removed heuristic's nonempty-row guard would also have kept these examples. The branch fixture below exercises that guard with a populated upper row.

## Native branch above the original wired row

`time_drum_b_column.{scr,bin,csv}` captures the one-inserted-row case after wiring B through AE on the upper row, leaving A blank, and adding a down connection at B to the original wired row. The SCR was snapshotted from the supplied CLICK `Scr1.tmp`; BIN/CSV were supplied through `clicknick-rung save time_drum_b_column`. Preserve the captured comment literally, including the question mark substituted for the dash by the originating application.

The upper row has flag 0, B segment 0, and C through AE segment 1. The lower original row has flag 1 and all 32 segment-1 entries, including the covered AF/NOP wire. The down list connects row 0 at column B. These four flag mappings agree at all 128 cells between SCR and native clipboard, and both decoders reproduce the supplied CSV byte-for-byte.

This is a native counterexample to the removed deletion rule: the upper row is nonempty and the following row has the all-segment-1 rail signature, yet CLICK's clipboard preserves both rows and the branch. Running the pre-change decoder (the version with `_resync_trailing_rung` and the row-0-signature deletion rule) deletes the branch and shifts the lower wire onto the drum's top row. The updated decoder preserves the branch and suppresses only the covered NOP token.

The condition-side geometry, row flags, and down list match the older time_drums rung 13; that older SCR additionally has a segment-0 AF wire entry on the upper row. Exact editing history of the older fixture is unnecessary to establish that the generic deletion rule was invalid.

## Past 256 rungs

`rungs_266.{scr,bin.gz,csv}` are one CLICK project of 266 rungs, all native: the `Scr1.tmp`, and the clipboard copy of the same rungs with its CSV. The BIN is gzipped because 266 rungs copy out to 1 MB. They settle how a rung index passes 255: 16 bits in the SCR (`RUNG`), and in the clipboard a little-endian value at tail `+0x09` that carries into `+0x0A`.

## Constants as CLICK stores them

`constants/*.scr` are CLICK v4's `Scr1.tmp`, each saved after one Math or Copy was typed in its dialog with a constant spelled another way than CLICK prints it back. Rung 1 holds the instruction. `tests/ladder/test_canonical_constants.py` decodes each and checks that the instruction built from the typed text is the one CLICK stored.

| File | Typed in the dialog | Stored |
|---|---|---|
| `math_hex_005` | hex Math `DH1 = 005` | `5h` |
| `math_hex_0ffh` | hex Math `DH1 = 0ffh` | `FFh` |
| `math_hex_1e3` | hex Math `DH1 = 1e3` | `1E3h` |
| `math_hex_dh2_plus_1e3` | hex Math `DH1 = DH2 + 1e3` | `DH2 + 1E3h` |
| `math_hex_0000h` | hex Math `DH1 = 0000h` | `0h` |
| `math_dec_1_50` | decimal Math `DF1 = 1.50` | `1.5` |
| `math_dec_1e3` | decimal Math `DF1 = 1e3` | `1000.0` |
| `math_dec_point_5` | decimal Math `DF1 = .5` | `0.5` |
| `math_dec_6000000000` | decimal Math `DF1 = 6000000000` | `6000000000` |
| `math_dec_1_5E10` | decimal Math `DF1 = 1.5E+10` | `1.5E+10` |
| `copy_005` | Copy `005` to DS1 | `5` |
| `copy_plus_5` | Copy `+5` to DS1 | `+5` |
| `copy_0ffh` | Copy `0ffh` to DS1 | `0FFh` |
| `copy_1_50` | Copy `1.50` to DS1 | `1.5` |
| `copy_1e3` | Copy `1e3` to DS1 | `1000.0` |
| `copy_point_5` | Copy `.5` to DS1 | `0.5` |
| `copy_1E5` | Copy `1E5` to DF1 | `100000.0` |
| `copy_ABCH` | Copy `ABCH` to DH1 | `ABCh` |
| `copy_DH` | Copy `DH` to DH1 | `Dh` |
| `copy_EH` | Copy `EH` to DH1 | `0.0` |
| `copy_dollar_1` | Copy `$1` to TXT1 | `$01` |

laddercodec refuses four of these typed forms, though CLICK takes them: a hex Math constant without `h` (`005`, `1e3`) reads as a decimal number everywhere else in a CSV, so the `h` form is asked for; `EH` reads as hex E, but CLICK stores the real 0.0. Their saves still decode as the stored instruction, with no refusal.
