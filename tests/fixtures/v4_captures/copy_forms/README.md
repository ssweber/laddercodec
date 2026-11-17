# Single Copy forms, captured from CLICK v4

Cases `case01` to `case28` are one rung each, typed through CLICK Programming Software v4.00's
own dialogs: a Contact `X001`, then a single Copy with the fields below, confirmed with OK.
`caseNN.scr` is CLICK's `Scr1.tmp` after saving the project; `caseNN.bin` is the rung copied
with Edit > Copy (clipboard format 522). Both are as CLICK wrote them.

| Case | Source | Destination | Options picked | Saved |
|---|---|---|---|---|
| case01 | `CTD1` | `DF1` | Copy Binary | `0x2206`=1, `0x2227`=8 |
| case02 | `DF1` | `CTD1` | Copy Binary | `0x2206`=1, `0x2227`=8 |
| case03 | `1.5` | `DD1` | Copy Binary | `0x2206`=1, `0x2227`=8 |
| case04 | `1.5` | `CTD1` | Copy Binary | `0x2206`=1, `0x2227`=8 |
| case05 | `32768` | `DF1` | Copy Binary | `0x2206`=1, `0x2227`=8 |
| case06 | `65536` | `DF1` | Copy Binary | `0x2206`=1, `0x2227`=8 |
| case07 | `CTD1` | `DF1` | none | `0x2227`=7 |
| case08 | `1.5` | `DD1` | none | `0x2227`=7 |
| case09 | `DF[DS1]` | `DD1` | none | `0x2227`=7 |
| case10 | `DD[DS1]` | `DF1` | none | `0x2227`=7 |
| case11 | `CTD[DS1]` | `DF1` | none | `0x2227`=7 |
| case12 | `FFFFh` | `DF1` | none | the source as typed, no conversion type |
| case13 | `0FFFFh` | `DF1` | none | the source as typed, no conversion type |
| case14 | `123` | `TXT1` | Do not suppress zero | end `TXT3`, `0x2206`=1, `0x2227`=2 |
| case15 | `123` | `TXT1` | none (Suppress zero) | end `TXT3`, `0x2227`=1 |
| case16 | `5` | `TXT1` | none (Suppress zero) | no end, `0x2227`=1 |
| case17 | `3.4028235E+38` | `DF1` | none | the source as `3.402823E+38` |
| case18 | `3.4028235E+38` | `TXT1` | Real Numbering | the source as `3.402823E+38`, end `TXT12`, `0x2227`=3 |
| case19 | `"é"` | `TXT1` | none | the text as typed (U+00E9) |
| case20 | `"<tab>"` | `TXT1` | none | the text as typed (U+0009) |
| case21 | `"HALLO"` | `TXT1` | none | end `TXT5` |
| case22 | `"AB"` | `TXT999` | none | end `TXT1000` |
| case23 | `TXT1` | `DF1` | none offered | no conversion type |
| case24 | `DF[DS1]` | `CTD1` | Copy Binary | `0x2206`=1, `0x2227`=8 |
| case25 | `CTD1` | `DF[DS1]` | Copy Binary | `0x2206`=1, `0x2227`=8 |
| case26 | `DF1` | `CTD[DS1]` | none | `0x2227`=7 |
| case27 | `"€"` | `TXT1` | none | the text as typed (U+20AC) |
| case28 | `"<U+0001>"` | `TXT1` | none | the text as typed (U+0001) |

The dialog offers Copy Binary beside Copy Value for each pair that case07 to case11 and
case26 save as conversion type 7, a pointer on either side included (case24, case25), and saves Suppress zero (`0x2227`=1) for a number into TXT when no option
is touched. It refuses `3.4028236E+38` into DF1 (OBJ-005) and keeps 7 significant digits of a
real it takes. For TXT1 into DF1 it offers neither Copy Character Value nor Copy ASCII Code
Value.

`search01` and `math01` come from the same session, typed the same way after a Contact
`X001`: `search01` is a Search of `"é"` over `TXT1..TXT10` with result `DS1` and flag `C1`,
which CLICK keeps as typed; `math01` is a decimal Math of `0.33333334` into `DF1`, which
CLICK saves as `0.333333`, 6 significant digits. CLICK refuses `3.4028235E+38` in a Math
(OBJ-1009), and keeps a Compare constant as typed (`DF1 == 0.33333334`).

`paste01.scr` and `paste02.scr` are program files saved after a paste, not a dialog:
`paste01.scr` after pasting laddercodec's encode of `copy("HALLO",TXT1)`, the same bytes as
`case21.bin`, and `paste02.scr` after pasting laddercodec's encode of `copy("HELLO",TXT1)` and
`copy("HALLO",TXT1)` on two rungs. CLICK keeps the pasted text and saves no destination end
and no conversion type for it.
