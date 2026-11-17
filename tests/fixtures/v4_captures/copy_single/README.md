# Single Copy captures from CLICK v4

Each case is one rung typed through CLICK Programming Software v4.00's own dialogs: a
Contact `X001`, then a single Copy with the source and destination below, confirmed with OK
and checked with Syntax Check. `caseNN.scr` is CLICK's `Scr1.tmp` after saving the project;
`caseNN.bin` is the rung copied with Edit > Copy (clipboard format 522). The TXT cases kept
the dialog's defaults (Copy Value, Suppress zero, no Termination Code); case21 chose Real
Numbering and case22 Exponential Numbering.

| Case | Source | Destination |
|---|---|---|
| case01 | `CTD1` | `DF1` |
| case02 | `DF1` | `CTD1` |
| case03 | `1.5` | `DD1` |
| case04 | `1.5` | `CTD1` |
| case05 | `1.5` | `CTD[DS1]` |
| case06 | `-5` | `TXT1` |
| case07 | `1h` | `TXT1` |
| case08 | `10h` | `TXT1` |
| case09 | `0FFh` | `TXT1` |
| case10 | `FFFFh` | `TXT1` |
| case11 | `+5` | `TXT1` |
| case12 | `32767` | `DF1` |
| case13 | `32768` | `DF1` |
| case14 | `-32768` | `DF1` |
| case15 | `-32769` | `DF1` |
| case16 | `65535` | `DF1` |
| case17 | `65536` | `DF1` |
| case19 | `2147483647` | `DF[DS1]` |
| case21 | `1.5` | `TXT1` (real numbering) |
| case22 | `1.5` | `TXT1` (exponential numbering) |
| case23 | `DF[DS1]` | `TXT1` (real numbering) |
| case24 | `DF[DS1]` | `TXT1` (exponential numbering) |
| case25 | `DF[DS1]` | `TXT1` (Suppress zero asked for; the dialog does not offer it, so real numbering) |
| case26 | `DD[DS1]` | `TXT1` (defaults) |
| case27 | `DS[DS1]` | `TXT1` (defaults) |

CLICK refused the two cases left out: `10000h` into `DF1` (case18, OBJ-024) and `-5` into
`TXT1000` (case20, OBJ-003, the end TXT1001).

Cases 23 to 27 were made the same way in a later run, each confirmed with OK and saved,
with no Syntax Check recorded. For a `DF[DS1]` source the dialog offers Real or
Exponential Numbering and Termination Code, and no Suppress zero; for `DD[DS1]` and
`DS[DS1]` it offers what a DS or DD address does.
