# Copy of a TXT source, captured from CLICK v4

Each case is one rung typed through CLICK Programming Software v4.00's own dialogs: a
Contact `X001`, then a single Copy or a Block Copy with the fields below, confirmed with OK.
`caseNN.scr` is CLICK's `Scr1.tmp` after saving the project; `caseNN.bin` is the rung copied
with Edit > Copy (clipboard format 522). Both are as CLICK wrote them.

| Case | Mode | Source | Destination | Options picked |
|---|---|---|---|---|
| case01 | single | `TXT1` | `YD0` | Copy Character Value (the default) |
| case02 | single | `TXT1` | `YD0` | Copy ASCII Code Value |
| case03 | single | `TXT1` | `TXT21` | none |
| case04 | single | `TXT1` | `TXT21` | Termination Code, left at its default `$00` |
| case05 | single | `TXT1` | `TXT21` | Termination Code `$0D` |
| case06 | block | `TXT1..TXT2` | `TXT11` | none |
| case07 | block | `TXT1..TXT2` | `TXT11` | Termination Code, left at its default `$00` |
| case08 | block | `TXT1..TXT2` | `TXT11` | Termination Code `$0D` |

For a TXT register into YD, the dialog offers Copy Character Value and Copy ASCII Code
Value, and greys Suppress zero and Termination Code. For a TXT register or range into TXT, it
offers Termination Code, whose code is typed as text, and greys Suppress zero. CLICK sets a
Block Copy's destination end itself (`TXT12`).

The termination flag (`0x1221`) is set with a code, and `0x3216` holds the code in decimal
(13 for `$0D`); the program file leaves `0x3216` out for `$00`, and the clipboard holds 0.
