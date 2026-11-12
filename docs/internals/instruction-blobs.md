# Instruction Blobs

This page documents the variable-length instruction data that follows the cell header in instruction cells. The blob starts at cell offset +0x25.

For field layouts, func code tables, and tag constants for each known instruction type, see the source in `src/laddercodec/instructions/` — each module (`contact.py`, `comparison.py`, `coil.py`, `timer.py`) is the authoritative reference.

## Generic blob structure

All instruction blobs follow the same pattern:

```
[UTF-16LE class name, null-terminated]
[type marker: uint32 LE, high byte always 0x27]
[part count: uint16 LE (0x01 for contacts/coils, 0x02 for timers)]
[extra bytes: (part_count - 1) bytes, if part_count > 1 — each later part's row]
[field count: uint32 LE]
[tagged fields...]
```

### Part rows

A tall instruction's extra bytes give the row, below the main row, of each later
part: `01` for a timer's reset, `01 02` for a counter (down, reset) or shift
(clock, reset), `01 02 03` for a drum (reset, jump, jog). OR legs under an
input (the main one included) push the later parts down, and CLICK grows the
box: a drum with one leg under reset is `01 03 04`. A count_down's main part is
its unused Up input, so its Down input is the first extra byte. The AF cell's `+0x09` becomes the last part's row + 1;
`+0x0A` keeps the base height (`tests/fixtures/v4_captures/pins.bin`, `count_down_or.bin`).

### Tagged fields

Each field is:

```
[2-byte tag]
[FF FF FF FF sentinel]
[UTF-16LE null-terminated value]
```

Field values are string-encoded even for numeric data (e.g. `"1000"` for a timer preset). Timer fields 6–7 use a variant format with a 4-byte sub-marker instead of the `FF FF FF FF` sentinel.

## Known binary class names

| Class name | Type markers | Instruction | Source |
|---|---|---|---|
| `ContactNO` | 0x2711 (NO), 0x2712 (NC) | NO/NC contacts | `contact.py` |
| `Edge` | 0x2713 | Rising/falling edge contacts | `contact.py` |
| `Compare` | 0x2714 | Comparison contacts (==, !=, >, <, >=, <=) | `comparison.py` |
| `Out` | 0x2715, 0x2716, 0x2717 | All coil types (out, latch, reset) | `coil.py` |
| `Tmr` | 0x2718 | Timers (on_delay, off_delay) | `timer.py` |

The encoder uses `Out` as the class name for all coil types; the type marker and func code determine the variant. The decoder also recognizes `Latch` and `Reset` class names from native Click captures.

## Out variants (CLICK v4)

CLICK v4's toggle, debounce, flasher and timed coils are `Out` blobs with type
marker 0x2715, the same as a plain `out`. They carry 15 fields, and only the
func code separates them from plain coils. An `Out` blob whose func code is in
neither table decodes as `raw(Out,...)`. Source: `out_variant.py`.

| Tag | Field |
|---|---|
| `0x6066` | target |
| `0x6067` | range end (always empty) |
| `0x60B3` / `0x60B4` | on preset / on accumulator (`TD`) |
| `0x60B5` / `0x60B6` | off preset / off accumulator (debounce, flasher) |
| `0x11F8` | oneshot (always `0`) |
| `0x11F5` | immediate (toggle) |
| `0x1246` | `1` for toggle |
| `0x1247` | maintained (timed) |
| `0x21F9` | time unit: 0 ms, 1 s, 2 min |
| `0x2248` | variant: 0 toggle, 1 debounce, 2 flasher, 3 timed |
| `0x3218` | func code |
| `0x20CA` | always `2` |

A debounce saved with one phase stores the empty phase's preset and accumulator
(`0x60B3`/`0x60B4` or `0x60B5`/`0x60B6`) as empty strings.

| Variant | Func codes | Units | Rows (`+0x09` / `+0x0A`) |
|---|---|---|---|
| toggle | 8224, immediate 8225 | — | 1 / 1 |
| debounce | 8226 ms, 8227 s | ms, s | 3 / 3 |
| flasher | 8228 ms, 8229 s | ms, s | 3 / 3 |
| timed | 8230–8232 ms/s/min, maintained 8233–8235 | ms, s, min | 2 / 3 |

Each phase stores only its accumulator; Click claims the `T` of the same number
with it. Timed is the one AF instruction whose cell header has more visual
sub-rows (`+0x0A`) than rows spanned (`+0x09`).

## Time & Event drum (CLICK v4)

A drum's base is tag `0x2200`: `0` time, `1` event, `2` time & event. Any other
value decodes as `raw(Drum,...)`. Source: `drum.py`.

CLICK v4 copies every drum back with 82 fields: the 63 v3 fields, then 16 preset
slots (`0x6891`), `0x428A`, `0x6068` and the terminator. The encoder writes the
82-field layout for the v4-only drums: time & event, and a time drum with a
register preset. Other time drums and event drums keep the 64-field v3 layout,
which CLICK v4 still accepts.

| Tag | Time & event drum |
|---|---|
| `0x6872` ×16 | events (blank for a step without one) |
| `0x6891` ×16 | presets (blank for a step without one) |
| `0x6068` | done bit of the accumulator's timer (`TD101` → `T101`) |
| `0x428A` | constant-preset mask; see below |
| `0x3A05` ×4 | func codes; no-jog base Tms 10503, Ts 10510, Tm 10517, Th 10524, Td 10532 |

The func codes have the same block shape as the time drum: base, reset, jump,
then the jog group at +3..+6. Th's jog group is at +4..+7 (time 8480–8483,
time & event 10528–10531), so 8479 and 10527 are the unused codes and the Th
block is 8 codes long (`v4_captures/sweep_drum.bin`).

In every drum the codes run consecutively over the enabled pins. With Jump off,
Jog takes Jump's code: event `8494, 8495, 0, 8496`, not `8497`. CLICK v3
accepts the skipped code. CLICK v4 pastes it, then fails the syntax check with
C000A ("All inputs of the box instruction must originate from the same branch")
until the drum is reopened and OK'd (`v4_captures/drum_jog.bin`).

`0x428A` marks which presets are constants: bit *n* is cleared when step *n*'s
preset is a register, so all-constant is `-1` and `presets=[DS1,DS2]` is `-4`.
CLICK v4 computes it on OK (`InstCtl_Drum.dll`). A time drum with any register
preset then takes the func code series 1792 codes up (Tms 10247/10248, Th jog
10272…); time & event drums keep the 10503 series either way. A paste keeps the
field as written and treats a missing one as `-1`, so a 64-field time drum with
a register preset would paste as an 8455-series drum, a state the dialog never
writes; the encoder gives such drums the 82-field layout.

## Break and Continue (CLICK v4)

Break and Continue are class `Next` (type 0x2726), told apart by the func code in
tag `0x3218`. Source: `forloop.py`.

| `0x3218` | Instruction |
|---|---|
| absent | `next()`: v3 writes Next with the terminator field only |
| `9220` | `next()`: CLICK v4 writes the func code |
| `9232` | `continue()` |
| `9233` | `break()` |

Any other func code decodes as `raw(Next,...)`. Break and Continue are encoded
with the two fields Click writes; `next()` keeps the one-field v3 form. Each
version accepts either Next on paste and copies back its own: v3 drops `9220`,
v4 adds it.

## Math formulas

A Math blob (class `Math`, type 0x271A) has 1010 tagged fields: 9 header
fields, 500 operand slots (tag `0x6888`), 500 reserved slots (tag `0x688C`) and
a terminator. Source: `math.py`.

The formula appears four times in the header:

| Tag | Field | Example for `SUM ( DS1 : DS3 ) + 5` |
|---|---|---|
| `0x61FF` | template, display | `SUM ( @ : @ ) + 5` |
| `0x6228` | formula, display | `SUM ( DS1 : DS3 ) + 5` |
| `0x6229` | template, internal | `SUM#(#@#:#@#)#+#H5` |
| `0x61FD` | formula, internal | `SUM#(#DS1#:#DS3#)#+#H5` |

- **Display form** is spaced the way Click's formula editor spaces it: one space
  on each side of every operator, paren, comma and range colon (`ABS ( x )`,
  `RAND ( 1 , 100 )`). The encoder normalizes `ABS(x)*2` to this form. A sign
  stays on its constant (`( -5 )`) and is spaced from an address (`- DS401`).
- **Internal form** is the display form with spaces replaced by `#` and each
  bare decimal literal prefixed with `H`. Click splits it on `#`, so an
  unspaced `ABS(` becomes a single unknown token. In CLICK v4 that pastes but
  raises a Math instruction error.
- **Comma functions** (`RAND`, `LSH`, `RSH`, `LRO`, `RRO`) are stored infix in
  the internal form: `F ( a , b )` becomes `a#F#b`, followed by a trailing `#`
  when the call ends the formula (`H1#RAND#H100#`, `H1#RAND#H10#+#DS1`,
  `DH5#LSH#UH1#`). The display form keeps the function call. Range functions
  (`SUM`, `MAX`, `MIN`, `MDN`, `AVG`) and one-argument functions keep the call
  form (`SUM#(#DS1#:#DS3#)`).
- Each argument of a comma function must be one operand or constant. CLICK's
  editor refuses `LSH ( DH401 + 1h , 2h )`, `RAND ( ABS ( DD616 ) , 20 )` and
  any other expression or call as an argument. The encoder
  writes such a call in its call form (`LSH#(#DH401#+#UH1#,#UH2#)`), which
  passes Check Program when pasted; written infix, it fails with C0114.
- Cell header byte `+0x0A` is `03` on a Math that went through CLICK's editor.
  A pasted Math keeps the encoder's `01`, even in a copy-back, so only `03`
  blobs show CLICK's own internal form.

### Operand and reserved slots

Each slot is `[2B tag][4B index LE][UTF-16LE value]`, and an empty slot is just
a null terminator. Operand slots hold every address in the formula, in order,
duplicates included. Reserved slots hold the interior addresses of each
`A : B` range, ranges in order. The endpoints are ordinary operands, so
`SUM ( DS201 : DS300 )` stores DS201 and DS300 as operands and DS202..DS299 in
the reserved slots.

An `XD` or `YD` range also lists the upper half of address 0:
`MAX ( XD0 : XD3 )` stores XD0u, XD1 and XD2.

CLICK v4 copies Math back with 5000 reserved slots, not 500, for 5510 fields.
A 500-slot blob still pastes into both v3 and v4, so the encoder writes 500
unless the ranges have more than 500 interiors. CLICK's editor stops listing
at 5000 without an error, even though the formula keeps the full range, and the
encoder does the same.

## Math nickname flag

Math blobs contain a `nickname_flag` field (tag `0x2224`). When set to `"1"`,
Click displays project-level tag names instead of raw addresses in the math
formula. The flag is purely a display hint — the expression itself always
stores concrete addresses.

The `encode()` API exposes this via `show_nicknames=True`, which sets the flag
on all math instructions in the buffer.

## Blob boundary detection

For unknown instruction types, the blob boundary can be detected using the generic multi-part formula:

1. Read the class name (UTF-16LE, null-terminated)
2. Read the type marker (uint32 LE)
3. Read part count (uint16 LE), skip `(part_count - 1)` extra bytes
4. Read field count (uint32 LE)
5. Walk through tagged fields (each: 2B tag + 4B sentinel/marker + UTF-16LE value)
6. The blob ends after all fields are consumed

The `RawInstruction` fallback uses this formula to capture the complete blob as opaque bytes, enabling round-trip for unsupported instruction types via `raw(ClassName,hex)` CSV tokens.

The blob does not hold the box's height: the cell header does (+0x09 row span, +0x0A sub-rows). A decoded `RawInstruction` keeps the native cell's two bytes as `visual_rows` and `sub_rows`. One read from CSV takes them from its class: the typed family's height when the blob alone gives it (Copy family 2 rows, Search 2, Send/Receive 3, an Out variant by its func code), otherwise `part_count` rows.

Native cells of some classes differ from both the typed height and this rule, which is an open capture question: Email, Home, Position and Velocity `03 03` (typed and raw rule `01 01`), Math `01 03`, some Search `02 03`, Tmr `02 03`, Drum `04 05` and SR `03 02`.

At the moment, `Email`, `Home`, `Position`, and `Velocity` still deliberately
travel through this raw path. They round-trip correctly, but they are not yet
modeled as dedicated DSL instruction classes.
