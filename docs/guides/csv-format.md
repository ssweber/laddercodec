# CSV Format (v1)

This document describes the canonical 33-column Click ladder CSV contract
used by `laddercodec` CSV tooling and by `pyrung.click.to_ladder()`.

Relevant entry points:

- `laddercodec.read_csv(path)`
- `laddercodec.write_csv(path, rungs, *, index=False)`
- `laddercodec.csv.bundle.parse_bundle(directory)`
- `pyrung.click.to_ladder(program, tag_map)`
- `pyrung.click.LadderBundle.write(directory)`

## Scope and guarantees

This is the canonical writer contract. `laddercodec` parsers may accept
additional conveniences, but producers and downstream tools should target
the format below.

- Deterministic output
- Fully expanded rows (no shorthand expansion required)
- Strict prevalidation before emit
- All-or-nothing export for `pyrung` bundle generation

## Bundle layout

A bundle directory contains:

1. `main.csv`
2. One file per subroutine: `sub_<slug>.csv`

Rules:

- Consumers discover subroutines in lexical filename order.
- `parse_bundle(directory)` requires `main.csv`.
- When `pyrung` writes a bundle, the output directory is auto-created
  (`parents=True, exist_ok=True`) and existing files are overwritten.
- `pyrung` slug generation:
  - Lowercase
  - Non-alphanumeric sequences become `_`
  - Leading/trailing `_` trimmed
  - Empty slug becomes `subroutine`
  - Collisions are suffixed (`_2`, `_3`, ...)

## CSV shape

- UTF-8 CSV (standard comma-separated, quoted as needed by CSV writer)
- Header is always present and exact:

```csv
marker,A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z,AA,AB,AC,AD,AE,AF
```

- Exactly 33 columns per row:
  - `marker` + `A..AE` (31 condition columns) + `AF` (output token)

## Row semantics

- `marker`:
  - `R` => first row of a rung
  - `R<n>` (e.g. `R1`, `R2`) => first row of a rung, with an optional 1-based
    index. `write_csv(path, rungs, index=True)` emits these; the index is
    decorative and ignored on read.
  - `""` (blank) => continuation row of current rung
  - `#` => comment row
- `AF`:
  - exactly one token or blank
  - blank means no output token on that row

Rung segmentation rule for consumers:

- A rung starts at each row whose `marker` is `R` optionally followed by digits
  (`R`, `R1`, `R2`, ...) and continues until the next such marker or EOF.

## Comment rows

Comment rows appear directly above the `R` row of the rung they annotate:

- `marker` = `#`
- Column `A` = comment text for that line
- No additional columns

Multi-line comments emit one `#` row per line. Example:

```csv
#,Initialize the light system.
#,Activates when Button is pressed.
R,X001,-,-,...,-,out(Y001)
```

Comment rows are metadata. Consumers may ignore them or display them as rung
annotations. Writers preserve comment text verbatim; some toolchains use
markdown-style markers inside the text (for example `**bold**`, `*italic*`,
`__underline__`) to represent styled Click comments.

## Condition grid cell vocabulary (`A..AE`)

Cells can contain:

- Contact/operand tokens (for example `X001`, `DS10`, `C1`)
- Negated contact: `~X001`
- Edge contacts: `rise(X001)`, `fall(X001)`
- Comparison terms (for example `DS1!=0`, `DS1==5`, `DS1<DS2`)
- Wire-down prefixed contacts: `T:X001`, `T:~X002`, `T:rise(C1)` - the contact
  token carries a `T:` prefix indicating the contact also has a vertical-down
  wire exit (used on non-final OR branches at mid-rung positions)
- Wiring symbols:
  - `-` horizontal-only wire
  - `T` horizontal + vertical-down wire (T-junction)
  - `|` vertical-only pass-through wire (OR output bus, middle rows)
- Blank (`""`) empty cell

No shorthand markers (`->`, `...`) are emitted.
No explicit `+` topology token is emitted.

## Vertical topology

OR conditions (`Or()`), multi-output stacking, and `branch()` conditions all
use continuation rows within a rung. These mechanisms share the same vertical
space - OR branch rows double as multi-output and branch rows.

### Bus patterns

Two column patterns control vertical connectivity:

**Convergent bus (OR merge)** - gathers parallel branches into a single
downstream path:

- `T` on the first row (right + down)
- `|` on middle rows (vertical pass-through - up + down only, no right exit)
- blank on the last row (bus terminates)

Middle and last rows reach downstream columns by routing up through `|` to the
`T`, then right. This ensures only the first row's horizontal path continues
directly.

**Divergent bus (output split)** - distributes one condition path to multiple
output rows:

- `T` on non-final rows (right + down)
- `-` on the final row (right only)

Every row has a right exit to its own AF output token.

**Contact input bus (`T:` prefix)** - an OR variant where the contacts
themselves carry the vertical bus instead of a separate wire column:

- `T:` prefix on non-final branch contacts (right + down)
- Bare contact on the final branch (right only)
- Contacts at column 0 (power rail) are always bare - the rail connects all
  rows.

The `T:` prefix applies to any contact token: `T:X002`, `T:~C1`, `T:rise(X001)`,
`T:DS1==5`.

### T-junction physical model

A `T` cell's vertical wire extends from the left edge of its cell downward. This
wire connects to either:

- A cell directly below in the same column, or
- The right edge of a contact in the column to the left (when the cell below is
  blank)

This diagonal adjacency is how contacts on continuation rows connect upward to
merge/split columns even when their own column has no marker below.

### Continuation row rules

- Only the first row (`marker = R`) carries the full condition path from power
  rail to output.
- Continuation rows carry only their OR-branch-local contacts and branch-local
  conditions. Shared AND-prefix contacts from earlier columns are not repeated.
- Each continuation row has at most one AF token or is blank in AF.

## `Or(...)` expansion

### Simple OR at power rail

`Or(X001, X002, X003)`:

```text
     A      B     ...   AF
R    X001   T     -...- out(Y001)
     X002   |
     X003
```

Contacts at col 0 are bare (power rail). Convergent bus at col B: `T` / `|` /
blank.

### Mid-rung OR

`X001, Or(X002, C1)`:

```text
     A      B       C     ...   AF
R    X001   T:X002  T     -...- out(Y001)
            C1
```

`T:` prefix on `X002` (non-final, mid-rung). Convergent bus at col C: `T` /
blank. Shared AND-prefix (`X001`) appears only on the first row.

### Series ORs

`Or(X001, X002), Or(C1, C2)`:

```text
     A      B     C      D     ...   AF
R    X001   T     T:C1   T     -...- out(Y001)
     X002   -     C2
```

First OR at power rail (bare contacts, convergent bus at col B). Second OR
mid-rung (`T:` prefix on `C1`, convergent bus at col D). Continuation rows
merge - `X002` and `C2` share the same row, connected by `-` wire at col B.

## Multi-output stacking

Multiple output instructions from the same condition path stack vertically using
a divergent bus:

`X001, X002` -> `out(Y001)`, `latch(Y002)`, `reset(Y003)`:

```text
     A      B      C     ...   AF
R    X001   X002   T     -...- out(Y001)
                   T     -...- latch(Y002)
                   -     -...- reset(Y003)
```

Divergent bus at col C: `T` / `T` / `-`. Each row continues right to its own
output.

## `branch(...)` conditions

Branch-local conditions are placed on continuation rows to the right of the
output split column. The branch contact carries a `T:` prefix when it is not on
the final row, maintaining the vertical bus for rows below it.

`X001, X002` -> `out(Y001)`, `branch(C1): out(Y002)`, `out(Y003)`:

```text
     A      B      C     D      ...   AF
R    X001   X002   T     T      -...- out(Y001)
                   T     T:C1   -...- out(Y002)
                   -     -      -...- out(Y003)
```

Divergent bus at col C: `T` / `T` / `-`. Col D: `T` on row 0, `T:C1` on row 1,
`-` on row 2. The `T:` prefix on `C1` ensures the down-wire continues to row 2
(dropping `C1` from conditions) so row 2 receives the parent condition without
`C1`.

Nested branches are not emitted (export error).

## Combined OR + multi-output + branch

When a rung has both OR conditions and multiple outputs/branches, they share the
same set of continuation rows. The OR branches provide the rows needed for the
outputs.

`X001, Or(X002, X003, X004)` -> `out(Y001)`, `branch(C1): out(Y002)`,
`out(Y003)`:

```text
     A      B        C     D      ...   AF
R    X001   T:X002   T     T      -...- out(Y001)
            T:X003   |     T:C1   -...- out(Y002)
            X004           -      -...- out(Y003)
```

Col B: 3-way OR input bus (`T:` / `T:` / bare). Col C: convergent bus
(`T` / `|` / blank). Col D: divergent bus with branch condition
(`T` / `T:C1` / `-`).

The 3 OR branches provide the 3 rows needed for the 3 outputs. `C1` slots in as
a branch-local condition on the middle row. Middle OR rows reach the output
split by routing up through `|` to `T`, then right and back down through the
divergent bus.

## Builder pin continuation rows

Builder side conditions are emitted as continuation rows with dot tokens in `AF`:

- `.reset()`
- `.down()`
- `.clock()`
- `.jump(step)`
- `.jog()`

Pin rows are independent left-rail paths, not AND-chained through the parent
output row conditions.

Pins go in a fixed order (timers: reset; `count_up`: down, reset; `count_down`:
reset; `shift`: clock, reset; drums: reset, jump, jog). Rows without an AF token
between the instruction and a pin, or between two pins, are OR legs of the input
above, and they push the later pins down. CLICK grows the box to match:

```csv
R,C1,-,...,-,"time_drum(...)"
,C2,T,-,...,-,.reset()
,C3,,...,,
,C4,-,...,-,.jump(DS2)
```

Here `.jump()` is on row 3, not row 2. An unused pin still takes a row of its
own, below the legs of the pin above it: with Jump off, `.reset()` with one leg
then `.jog()` puts Jog on row 4, with a blank Jump row 3 (CLICK lays out a leg
added with Insert Row the same way). Blank rows just above the next pin are read
as the unused pins' rows, not legs. Legs under the last pin sit below the box.

The same holds for legs under the main input:

```csv
R,X1,T:X2,T,-,...,-,"count_down(CT1,CTD1,preset=3)"
,,T:X3,|,,...,,
,,X4,,,...,,
,X9,-,...,-,.reset()
```

`count_down`'s main input is its Down input, on box row 1 under the unused Up,
so this box is 5 rows with Reset on row 4. A `count_up` without `.down()` puts
the unused Down row under the main input's legs. A timer without `.reset()`
stays 2 rows, with its main input's legs beside and below it.

"OR leg" only says where a row sits. `read_csv` doesn't check wires, and it takes
`T` or `|` to join a leg to the row above. CLICK accepts a leg without them, but
that contact feeds nothing:

```csv
R,C31,-,...,-,"count_down(CT4,CTD4,preset=5)"
,C32,,...,,
,C39,-,...,-,.reset()
```

Here C31 drives Down and C32 goes nowhere. With `NOP` in the second row's AF, the
box is 3 rows and C32 drives Down, but C31 then sits on the unused top row, where
its wire stops at the box and it feeds nothing.

## Parsing conveniences

`laddercodec.read_csv()` accepts a few parsing conveniences beyond the canonical
writer contract:

- Timer instructions occupy 2 grid rows.
- If a timer rung is written with only 1 data row, the parser auto-pads a blank
  continuation row.
- Empty rows between rungs are ignored.

## For-loop lowering

`forloop(count, oneshot=...)` lowers to:

1. `for(count)` or `for(count,oneshot=1)` row (`marker=R`)
2. Body rungs (`marker=R` each): a bare body instruction is a wire-only rung; a
   body rung with contacts keeps them, and holds `break()` / `continue()`
   (CLICK v4). A nested loop is its own `for` .. `next()` run, up to three deep.
3. Closing `next()` row (`marker=R`)

## Subroutine tail guarantee

Each subroutine CSV emitted by `pyrung` is guaranteed to end with `return()`:

- If the last emitted instruction token is already `return()`, unchanged.
- Otherwise the exporter appends an `R` row with `return()`.

## AF token format (canonical)

All tokens are compact canonical function-style strings:

- `name(pos1,pos2,key=val,...)`
- Positional args come first, then keyword args as `key=value`
- no extra whitespace
- dot pins as `.name(...)`

String rendering:

- Strings are double-quoted.
- Internal `"` is escaped as `""` (doubled quote). No backslash escaping.

Boolean rendering:

- `1` / `0`

`None` rendering:

- `none`

Collections:

- List/tuple-like values render as bracket lists, for example `[A,B]`,
  `[[1,0],[0,1]]`.

## Supported instruction tokens (canonical producer set)

Positional args stay positional. Keyword-only args use `key=value` syntax.
Conditional kwargs (marked with "if !=0") are omitted when the value is the
default (`0`).

Producer may emit:

- `out(target)` or `out(target,oneshot=1)`
- `latch(target)`
- `reset(target)`
- `copy(source,target)` or `copy(source,target,oneshot=1)`
- `blockcopy(source,dest)` or `blockcopy(source,dest,oneshot=1)`
- `fill(value,dest)` or `fill(value,dest,oneshot=1)`
- `math(expression,dest,mode=decimal)` or `math(...,mode=hex,oneshot=1)`
- `search(range cond value,result,found)` or `search(...,continuous=1,oneshot=1)`
- `pack_bits(bit_block,dest)` or `pack_bits(bit_block,dest,oneshot=1)`
- `pack_words(word_block,dest)` or `pack_words(word_block,dest,oneshot=1)`
- `pack_text(source_range,dest)` or
  `pack_text(...,allow_whitespace=1,oneshot=1)`
- `unpack_to_bits(source,bit_block)` or
  `unpack_to_bits(source,bit_block,oneshot=1)`
- `unpack_to_words(source,word_block)` or
  `unpack_to_words(source,word_block,oneshot=1)`
- `on_delay(done,acc,preset=N,unit=Tms)`
- `off_delay(done,acc,preset=N,unit=Tms)`
- `count_up(done,acc,preset=N)`
- `count_down(done,acc,preset=N)`
- `shift(bit_range)`
- `event_drum(outputs=[...],events=[...],pattern=[[...],...],current_step=X,completion_flag=X)`
- `time_drum(outputs=[...],presets=[...],unit=Tms,pattern=[[...],...],current_step=X,accumulator=X,completion_flag=X)`
- `send(target=X,remote_start="addr",source=X,sending=X,success=X,error=X,exception_response=X,function_code=N)`
- `receive(target=X,remote_start="addr",dest=X,receiving=X,success=X,error=X,exception_response=X,function_code=N)`
  - `target` is `ModbusRtuTarget(name="rtu",com_port="cpu2",device_id=1)` (ports `cpu2`,
    `cpu3`, `slot0_1`, `slot0_2`, `slot1_1`, `slot1_2`) or
    `ModbusTcpTarget(name="tcp",ip="192.168.1.20",port=502,device_id=1)`, with
    `com_port="wlan"` for the WLAN port (omitted = Ethernet)
  - `device_id` is a number or a DS address (`device_id=DS2420`), as CLICK's Slave ID box allows
  - Slave ID numbers: Send RTU 0-247, Receive RTU 1-247, TCP 0-255. TCP `port` is 1-65535.
  - Hex `remote_start` runs `0h`-`FFFEh` (`0h`-`FFFDh` for a DD, DF, CTD or TXT source); a
    Send takes `register_type` `coil` or `holding`.
  - `function_code=N` picks the Modbus code when the address leaves a choice. Receive from a
    CLICK address reads with FC01 (bits) or FC03 (registers) unless `function_code=2` or `4`.
    Send writes one element with FC05/FC06 and a block with FC15/FC16; `function_code=15` or
    `16` writes one element as a block. One DD, DF or CTD element is always FC16, and XD and
    YD go out only as FC06.
  - A Receive into registers takes DS, DD, DH, DF, YD or TXT. A CLICK `remote_start` matches
    the destination's type: DS from DS, TD or SD; DD from DD or CTD; DF from DF; DH or YD
    from DH, XD or YD; TXT from TXT. A YD destination, or DH read from XD or YD, takes one
    element; TXT takes an even count of at least 2.
  - `word_swap=1` is refused where CLICK turns Word Swap off: a bit Receive, a YD or TXT
    destination, one DS or DH element, DH read from XD or YD, and DD or DF read from a CLICK
    address.
  - A range (`source=DS1..DS5`) runs forward inside one bank. Counts: Send 1-1968 bits or
    1-123 registers (1-61 for DD, DF, CTD); Receive 1-2000 bits or 1-125 registers (1-62 for
    DD, DF).
  - An X or Y range counts the points that exist in the slots it covers: `X001..X021` is 17
    elements (`X001`-`X016`, then `X021`). `X017`-`X020` are not addresses, so a range can't
    end on one.
  - X and Y counts stay inside a slot run. `X001`-`X016` and `X021`-`X036` are one run
    (`X001` gives 32); from `X101` on, a count stays in the start's slot (`X101` gives 16).
    This holds for a Receive into Y, for a Send of X or Y to a CLICK address (from the
    higher of the two start numbers when the remote is X or Y too), and for a C count to or
    from a CLICK X or Y address. A Send of X or Y to a MODBUS 984 or hex address, and a
    Receive into `Y101` or later from a CLICK C address, count through `Y816` (`X001` gives
    160, `Y101` gives 128).
  - A count also stays inside the remote bank where CLICK checks it: a C, T, CT or SC remote
    of a Receive into Y or C (`T490` gives 11), a MODBUS 984 coil remote of a Receive into Y
    (`65530` gives 6), and a C remote of a Send from X, Y or C.
  - `sending`, `receiving`, `success` and `error` are C bits, and no C bit serves two of
    them; `exception_response` is DS or DD.
- `call("subroutine_name")`
  - Subroutine names follow CLICK's naming rules (see "Operand normalization notes")
- `return()`
- `for(count)` or `for(count,oneshot=1)`
- `next()`
- `break()`, `continue()` (CLICK v4) - on a contacted rung inside a loop
- `raw(ClassName,hex)` - opaque instruction passthrough for binary round-trip
  fidelity. `ClassName` is the Click binary class name (unquoted) and `hex` is
  the raw blob as a hex string. Runtime no-op; preserved so CSV -> DSL -> CSV
  round-trips losslessly for unrecognized instruction types.
  `Email`, `Home`, `Position`, and `Velocity` currently use this raw passthrough
  path because they are not yet modeled as dedicated DSL instruction classes.

Pin tokens:

- `.reset()`
- `.down()`
- `.clock()`
- `.jump(step)`
- `.jog()`

Click supports additional instruction placeholders that canonical writers do not
currently emit:

- Empty instruction placeholder: `,:,...`
- NOP instruction placeholder: `,:,NOP`

## Operand normalization notes

- Tags render as mapped Click addresses (for example `X001`, `DS10`).
- An address must name a CLICK bank and lie inside its range (CLICK help topic
  CL195, Memory Addresses). X and Y number by 16-point slot: `X001`-`X016` on the
  CPU, `X021`-`X036` on its dual option slot, and `X101`-`X116` through `X801`-`X816`
  on expansion modules 1-8. `X017`, `C2001` and `DS0` raise `AddressError`.
- Each instruction narrows the banks it takes:
  - Contacts take X, Y, C, T, CT or SC; `.immediate` only on X.
  - `out(...)`, `latch(...)`, `reset(...)` and the Out variants (`toggle`, `debounce`,
    `flasher`, `timed`) take Y, C or SC; `immediate(...)` only on Y, and both ends of
    an immediate range.
  - The SC bits a coil writes are SC50, SC51, SC53, SC55, SC60, SC61, SC65, SC66, SC67,
    SC75, SC76, SC120, SC121, SC162, SC165, SC168, SC171, SC303, SC304, SC305, SC306,
    SC323, SC324, SC325 and SC326. An SC range needs both ends on this list.
  - A coil range stays in one bank and its end is above its start: `out(C1..C2000)`
    and `out(immediate(Y001..Y101))` are accepted, `out(C9..C1)`, `out(C5..C5)` and
    `out(C5..Y5)` are refused.
  - Variant accumulators are TD, and the on and off phases of `debounce` and
    `flasher` use two different TD registers. A preset is a DS register or a whole
    number up to 32767, at least 0 for `debounce` and at least 1 for `flasher` and
    `timed`.
  - A `debounce` may leave out one phase's keywords
    (`debounce(C1,on_acc=TD1,on_preset=100,unit=Tms)`); it needs at least one phase.
    `flasher` needs both.
  - A compare takes data registers or constants, never bits, on either side. Both
    sides come from one group: hex (XD, YD, DH, `0h`-`FFFFh`), numeric (TD, CTD, DS,
    DD, DF, SD, numbers; a whole number lies in -2147483648 to 2147483647) or text
    (TXT, 1 to 128 printable ASCII characters in quotes such as `"A"` or `"AB"`, or `$41`; a quote
    is `$22`, and `"$41"` is text). A text compare takes `==` or `!=` only.
- Timer, counter, shift and drum fields take CLICK's banks:
  - Timer: done bit `T1`-`T500` with current value `TD` of the same number, and a
    set point that is a `DS` address or digits only, `0`-`32767` for every unit.
  - Counter: done bit `CT1`-`CT250` with current value `CTD` of the same number,
    and a set point that is a `DS` or `DD` address or an integer from
    `-2147483648` to `2147483647` (a `-` only in front, at most 12 characters).
  - Shift: both ends are `C` bits and differ (`shift(C1..C1)` and `shift(C1..C001)`
    are refused); `shift(C106..C99)` runs backwards.
  - Drum: 1-16 steps and 1-16 outputs (`Y` or `C`), a pattern of 0/1 cells with
    one row per step, current step `DS`, accumulator `TD`, completion flag `C`,
    and a `.jump()` target that is a `DS` address. Each step has an event (event
    drum) or a duration (time drum); a time and event step needs a duration or an event.
  - Drum events are X, Y, C, T, CT or SC; a duration is `0`-`32767` (no sign) or a
    `DS` address. No output appears twice or equals the completion flag, compared as
    addresses (`C1` and `C001` are the same bit).
- `for(count)`: a `DS`, `DD`, `TD`, `CTD` or `SD` address, or digits only from `0` to
  `2147483647`. A pointer (`DS[DS1]`) and a space inside the number are refused.
- `call("name")` names a subroutine as CLICK's Add New Subroutine dialog allows. With
  outer spaces trimmed, the name is not blank, has at most 24 characters and none of
  `\ / : * ? " < > |`, and the part before its last dot is not a Windows device name
  (`CON`, `NUL`, `COM1`, ...).
- Block ranges render either:
  - contiguous compact form `BANKstart..BANKend` (same bank, +1 sequence), or
  - explicit list form `[A,B,C]`.
- Indirect refs render as `BANK[pointer]`, the pointer a DS address and `BANK`
  one of C, DS, DD, DH, DF, XD, YD, TD, CTD or TXT (`copy(DD[DS100],DS1)`,
  CLICK help topic CL238). Only a single `copy` takes one; `blockcopy`,
  `fill`, `pack_*`, `unpack_to_*` and `search` raise `AddressError`.
- Copy, Block Copy, Fill, Pack, Unpack, Search and Math operands follow CLICK's
  dialogs and raise `AddressError` or `FieldError` naming the field: a bit
  copies to Y or C, a text constant to TXT, both ends of a range sit in one bank
  and the end comes after the start (`DS1..DS1` is refused), an X or Y range in
  a Pack source, a Block Copy source or an Unpack destination stays in one
  16-point slot, a pack or unpack range fits its register (`pack_bits` takes
  bits, `pack_words` registers), and a Math result is DS, DD, DF, TD, CTD or SD
  in decimal mode, DH or YD in hex mode.
- Block Copy, Pack and Unpack pair banks as CLICK's dialog does:
  - `blockcopy`: bits go to Y or C; DS, DD, DH, DF and SD to DS, DD, DH, DF,
    TD, CTD or SD; TXT to DS, DD, DH or TXT. The destination end is the start
    plus the source's length, whatever the banks (`blockcopy(DS1..DS4,DD1..DD4)`).
    A run into Y that would cross a slot (`blockcopy(C1..C16,Y010..Y025)`) is
    refused: what CLICK writes for it is not captured yet.
  - `pack_*`: X, Y, T, CT and SC bits pack into DH; C bits into DS, DD, DH or
    DF; DS words into DD or DF; DH words into DD; TXT into DS, DD, DH, DF, TD
    or CTD.
  - `unpack_to_*`: DS unpacks to C; DD and DF to C, DS or DH; DH to Y or C.
- A single `copy` takes a 32-bit integer constant, and a hex constant above
  `FFFFh` copies only to DD or CTD.
- Constants, counts and address numbers use the digits 0-9 only; a digit from
  another script (`٣`) is refused.
- `search` takes a C bit as its found flag, `==` or `!=` for a text value (a
  text constant or a TXT register), and a hex value of at most `FFFFh`.
- In a decimal `math`, an integer constant must read back as typed: CLICK keeps
  its low 32 bits and refuses it when they print at a different length
  (`3000000000`, `007` and `-0` are refused). In a hex `math`, a hex constant
  has at most 4 digits. `SUM` takes no CT range, and the formula is at most 270
  characters as CLICK stores it: a sum of 68 addresses fits, 69 does not;
  constants, functions and parentheses count too.
- Text constants are double-quoted (`copy("Q",TXT1)`, `TXT1=="T"`); an
  ASCII-code constant is `$hh` (`copy($00,TXT1)`, `TXT1==$00`). CLICK writes
  one TXT register per character of a text constant, so `""` writes nothing:
  `encode()` refuses an empty `""` in a Copy or Fill source, and `read_csv()` and
  `decode()` still accept it there. A compare or a search takes 1 to 128
  printable ASCII characters in quotes (`TXT771=="AB"` compares TXT771 and
  TXT772; a search matches the same window) and refuses `""`, a longer or
  non-ASCII text and a quote inside the text when it is read or built; spell a
  quote as `$22`. A quoted `"$41"` is three characters of text, not the code
  `$41`. Use `$00` for the blank (NUL) character.
- Copy converters are emitted as a `convert=` kwarg on the instruction:
  - `convert=to_value`
  - `convert=to_ascii`
  - `convert=to_binary`, or `convert=to_binary(termination_code=$XX)` for a number register copied to TXT with a termination code (`none` is accepted and writes plain `to_binary`; any other keyword raises `FieldError`)
  - `convert=to_text(suppress_zero=<0|1>,termination_code=<none|$XX>)` for an integer source, `convert=to_text(exponential=<0|1>,termination_code=<none|$XX>)` for a DF source: only the option CLICK offers for that source is written. The other is accepted on read and ignored (DF), except `exponential=1` from an integer source, which raises `ValueError`.

## Immediate handling

Immediate operands are supported only in strict, explicit contexts.

Allowed condition-cell forms:

- `immediate(X001)`
- `~immediate(X001)`

Allowed AF token forms:

- `out(immediate(Y001))`
- `latch(immediate(Y001))`
- `reset(immediate(Y001))`
- `out(immediate(Y001..Y004))`

Rules:

- `Tag.immediate` and `immediate(...)` wrapper style are both supported.
- Immediate is allowed only for:
  - direct rung contacts (normal and negated), and
  - `out(...)`, `latch(...)`, `reset(...)` target operands.
- Immediate is not allowed in:
  - edge contacts (`rise(...)`, `fall(...)`),
  - non-coil instruction operands (`copy`, `math`, `search`, etc.).
- Immediate coil targets must resolve to `Y` bank addresses.
- An immediate range is any ascending `Y` range, including one that crosses a
  module (`out(immediate(Y001..Y101))`).
- pyrung's exporter writes an immediate range in `BANKstart..BANKend` form only when
  its tags map to one contiguous address span; a mapping that does not fails
  pyrung's export check with a diagnostic.

## Strict validation and failure mode

Before rendering, `pyrung` runs strict Click validation and extra export checks.

On any issue:

- `LadderExportError` is raised
- includes structured `issues` entries (`path`, `message`, `source_file`,
  `source_line`)
- no CSV bundle is returned/written

## Consumer recommendations

1. Validate exact header and column count (33).
2. Parse in row order and preserve ordering semantics.
3. Treat `AF` as an opaque canonical token string unless your decoder
   intentionally parses token grammar.
4. Treat unknown future token names as extension points (fail closed if strict).
5. Segment rungs by a `marker` of `R` optionally followed by digits (`R`, `R1`, `R2`, ...).
