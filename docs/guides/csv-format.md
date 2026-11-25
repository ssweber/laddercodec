# CSV Format (v1)

This page defines laddercodec's 33-column CSV format. `read_csv` reads it and
`write_csv` writes it. If you write a CSV by hand, start at [Layout](#layout).

Relevant entry points:

- `laddercodec.read_csv(path, *, strict=True, unchecked=False, allow=())`
- `laddercodec.write_csv(path, rungs, *, index=False, stop="end")`
- `laddercodec.csv_rows(rungs, *, index=False, stop="end")`
- `laddercodec.write_bundle(directory, project, *, index=False)`
- `laddercodec.read_bundle(directory, *, strict=True, unchecked=False, allow=())`
- `laddercodec.csv.bundle.parse_bundle(directory)`

## Scope and guarantees

This is the canonical writer contract. `laddercodec` parsers may accept
additional conveniences, but producers and downstream tools should target
the format below.

- Deterministic output
- Fully expanded rows (no shorthand expansion required)
- `write_csv` builds every row before it opens the file. If it raises
  `CsvWriteError`, the file is unchanged.

## Bundle layout

A bundle directory contains:

```text
<bundle>/
  main.csv
  subroutines/
    <name>.csv      one file per subroutine
```

`write_bundle` writes a `Project` as a bundle, and `read_bundle` reads it back:

```python
from laddercodec import read_bundle, write_bundle

write_bundle("my_program", project)
project = read_bundle("my_program")
```

`write_bundle(directory, project, *, index=False)`:

- writes `main.csv` with `stop="end"` and `subroutines/<name>.csv` with
  `stop="return"`, as `write_csv` writes each file. `<name>` is the
  subroutine's name with the whitespace stripped from both ends. It does not
  write `project.main.name`;
- creates the directory and `subroutines/` if they are missing, and replaces
  a file of the same name. It does not delete or change any other file. A
  subroutine file left from an earlier write stays, and `read_bundle` reads it;
- raises `FieldError` for a subroutine name that CLICK refuses. It raises
  `CsvWriteError` for two names that are equal when the case of A-Z is ignored
  (`Pump` and `pump`, but not `é1` and `É1`). It raises `CsvWriteError` with no
  `code` for two names whose files would be one file on a file system that
  ignores case, such as NTFS (`é1` and `É1`, but not `Straße` and `STRASSE`). It
  raises `CsvWriteError` for a name that holds a control character (U+0000 to
  U+001F, or U+007F) anywhere, including at either end. It also raises
  `CsvWriteError` when a path that it would write exists and is of the wrong
  kind, such as a directory named `main.csv`;
- checks every name and path and builds every file's rows before it writes any
  file. A `FieldError` or `CsvWriteError` leaves the directory as it was. An
  `OSError` while it writes, such as a full disk, can leave some files written
  and others not;
- with `index=True`, numbers the rungs of each file from `R1`.

`read_bundle(directory, *, strict=True, unchecked=False, allow=())`:

- reads each file as `read_csv` reads it, with the same `strict`, `unchecked`
  and `allow`. An error from a file has the location of that file;
- returns the main program as `"Main Program"`, `prog_idx` 1, and then the
  subroutines in the order described next, with `prog_idx` 2, 3, 4 and so on;
- raises `CsvReadError` for a missing `main.csv`. It also raises `CsvReadError` for a
  subroutine name that CLICK refuses, for a name that starts or ends with
  whitespace, and for two subroutine names that are equal when case is
  ignored. It checks the names before it reads any file.

The files have no order. A round trip returns the subroutines sorted by name,
not in the order of `project.subroutines`.

Both readers, `read_bundle` and `parse_bundle(directory)`, list the same files:

- `main.csv` is required.
- The subroutines are the files directly in `subroutines/` whose names end in
  `.csv`, in any case. A subroutine's name is its file's name without the last
  four characters. `..csv` holds the subroutine `.`, and
  `subroutines/main.csv` holds the subroutine `main`.
- The subroutines are sorted by name with case ignored. Two names that differ
  only in case are sorted by their exact text. The order is the same on every
  operating system.
- A bundle with no `subroutines/` folder has no subroutines.
- Other files are ignored.

`parse_bundle` returns a `ParsedCsvFileAst` for each subroutine file. Its
`subroutine_slug` is the subroutine's name.

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
annotations.

### Comment styles and escapes

```csv
#,**Bold** and *italic* and __underline__
#,Pump_1_Run waits for \_init\_ in C:\temp
#,DS1 is 2 * 3 * 4 and *only* then
#,*****WARNING*****
```

A comment is Markdown with three styles: `**bold**`, `*italic*` or `_italic_`,
and `__underline__`. An underscore inside a word, as in `Pump_1_Run`, is text.
A `*`, `**`, `_` or `__` with whitespace after it can't start a style, and one
with whitespace before it can't end one. So in the third line above,
`2 * 3 * 4` is text and `only` is italic. A `*` or `_` that has no partner is
text, as in `DS1*2`.

A run of `*` that can end a style pairs with the nearest run of `*` before it
that can start one. The same holds for `_`. When both runs have at least two
characters left, two characters of each make bold for `*` or underline for `_`.
Otherwise one character of each makes italic. So the last line above is a bold
italic `WARNING`, and in `*1 see *Auto* mode` only `Auto` is italic.

If one of the two runs can both start and end a style, they don't pair when
their lengths add up to a multiple of 3, unless both lengths are multiples of 3.
So in `*a**b**c*`, the `**` after `a` can't end the `*` before it, because 1
and 2 add up to 3. The text is italic throughout, with a bold `b`. A run doesn't
pair with itself, so `a******a` is text. Two runs don't pair if only runs of the
other character lie between them, so `**__**__` is text.

To write a `*` or `_` as text where it would otherwise start or end a style,
put a backslash before it. To write a backslash before `*`, `_` or another
backslash, write `\\`. The second line above reads as
`Pump_1_Run waits for _init_ in C:\temp`, with no styling. A backslash before
any other character is a backslash, so `C:\temp` reads as it is written.

`decode()` and `decode_program()` return each comment as Markdown. The Markdown
has a backslash before a `*`, `_` or `\` only where `read_csv` would otherwise
read a style or an escape. `write_csv` writes the comment as it is, so the
comment reads back with the same text and styles. CLICK can style two kinds of
text that this Markdown can't. The decoders keep the text of each and drop the
style:

- an underline on part of a word, such as `y` in `xyz`;
- a style on whitespace at the edge of a styled stretch, such as the space in a
  bold `a `.

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

## Layout

Write the circuit: contacts, wires and boxes. `read_csv` lays each rung out as
CLICK's syntax check draws it. So a CSV doesn't need pad rows under a tall box,
rows for unused pins, or a merge in any particular column. If you write a wire
between two series contacts like this:

```text
     A      B      C      ...   AF
R    X001   -      X002   -...- out(Y001)
```

`read_csv` reads it as:

```text
     A      B      C      ...   AF
R    X001   X002   -      -...- out(Y001)
```

- Contacts pack left, and each OR merges in the column after its last contact.
- Each box goes on the first free output row below the box above it, and the
  conditions pack up beside it.
- Blank rows inside an OR, blank rows at the top or bottom, and wire stubs that
  join nothing are dropped.
- A pinned box's pins go on the rows CLICK gives them
  ([Pin continuation rows](#pin-continuation-rows)).
- A `NOP` that the rail feeds through wires alone, with no contact, is dropped when
  the rung has another output. A `NOP` that no rail or contact reaches is dropped too, in a rung
  with a circuit.

The logic never changes. If the circuits of several outputs meet only at the rail,
`read_csv` makes one rung of each, in order, with the comment on the first. CLICK
splits them the same way. So `read_csv` can return more rungs than the CSV holds.

If a rung needs more than 32 rows, `read_csv` raises `CsvReadError` with the code
`layout-too-tall`, and `write_csv` raises `CsvWriteError` with the same code. Both accept
the rung if each rung of its layout has 32 rows or fewer. That happens when CLICK splits
the rung, or when the layout drops its blank rows.

`write_csv` writes the same layout, so a CSV that it wrote reads back unchanged. A
rung that `laddercodec.check()` reports
([Decoding](decoding.md#check-for-line-connection-errors)) has no layout.
`read_csv` and `write_csv` handle it as drawn. The rules are in
[Layout](../internals/layout.md).

To lay a rung out from Python without a grid, build its circuit and call
`lay_out()` ([Build a rung from its circuit](encoding.md#build-a-rung-from-its-circuit)).

## Vertical topology

OR conditions, multi-output stacking, and branch conditions all use
continuation rows within a rung. These mechanisms share the same vertical
space - OR branch rows double as multi-output and branch rows.

In a circuit ([Build a rung from its circuit](encoding.md#build-a-rung-from-its-circuit)),
an OR is a `Parallel`. The outputs that one condition path feeds are the
`outputs` of its `Branch`. A branch condition is the `conditions` of a `Branch`
inside those `outputs`.

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

## OR legs

### Simple OR at power rail

An OR of X001, X002 and X003:

```text
     A      B     ...   AF
R    X001   T     -...- out(Y001)
     X002   |
     X003
```

Contacts at col 0 are bare (power rail). Convergent bus at col B: `T` / `|` /
blank.

### Mid-rung OR

X001 in series with an OR of X002 and C1:

```text
     A      B       C     ...   AF
R    X001   T:X002  T     -...- out(Y001)
            C1
```

`T:` prefix on `X002` (non-final, mid-rung). Convergent bus at col C: `T` /
blank. Shared AND-prefix (`X001`) appears only on the first row.

### Series ORs

An OR of X001 and X002, in series with an OR of C1 and C2:

```text
     A      B      C     ...   AF
R    X001   T:C1   T     -...- out(Y001)
     X002   C2
```

The first OR is at the power rail, so `X001` and `X002` are bare. The `T:`
prefix on `C1` draws one vertical at the left edge of col B. That vertical joins
the outputs of `X001` and `X002`, and it feeds both `C1` and `C2`. The
convergent bus at col C (`T` / blank) merges the second OR. `X002` and `C2`
share the same continuation row.

## Multi-output stacking

Multiple output instructions from the same condition path stack vertically using
a divergent bus:

X001 and X002 in series feed `out(Y001)`, `latch(Y002)` and `reset(Y003)`:

```text
     A      B      C     ...   AF
R    X001   X002   T     -...- out(Y001)
                   T     -...- latch(Y002)
                   -     -...- reset(Y003)
```

Divergent bus at col C: `T` / `T` / `-`. Each row continues right to its own
output.

## Branch conditions

Branch-local conditions are placed on continuation rows. The first one sits in
the output split column. The rest follow it to the right. The branch contact
carries a `T:` prefix when it is not on the final row, maintaining the vertical
bus for rows below it.

X001 and X002 in series feed `out(Y001)`, a branch with the condition C1 that
feeds `out(Y002)`, and `out(Y003)`:

```text
     A      B      C      ...   AF
R    X001   X002   T      -...- out(Y001)
                   T:C1   -...- out(Y002)
                   -      -...- out(Y003)
```

Divergent bus at col C: `T` / `T:C1` / `-`. `C1` sits in the bus on row 1. The
`T:` prefix on `C1` continues the down-wire at the left edge of col C to row 2,
so row 2 receives the parent condition without `C1`.

## Combined OR + multi-output + branch

When a rung has both OR conditions and multiple outputs/branches, they share the
same set of continuation rows. The OR branches provide the rows needed for the
outputs.

The conditions are X001 in series with an OR of X002, X003 and X004. They feed
`out(Y001)`, a branch with the condition C1 that feeds `out(Y002)`, and
`out(Y003)`:

```text
     A      B        C      ...   AF
R    X001   T:X002   T      -...- out(Y001)
            T:X003   T:C1   -...- out(Y002)
            X004     -      -...- out(Y003)
```

Col B: 3-way OR input bus (`T:` / `T:` / bare). Col C holds both the OR merge
and the output split. Its vertical joins the outputs of `X002`, `X003` and
`X004`. The same vertical is the divergent bus with the branch condition
(`T` / `T:C1` / `-`).

The 3 OR branches provide the 3 rows needed for the 3 outputs. `C1` slots in as
a branch-local condition on the middle row.

### Outputs under a tall box

A box taller than one row (Copy is 2) needs its rows to itself in AF. Write each
output on the row after the one above. `read_csv` moves an output down when the
box above still covers its row. The conditions stay beside the box. For example:

```text
     A      B      C     ...   AF
R    X001   T:C1   T     -...- copy(1,DS1)
            T:C2   T     -...- copy(2,DS2)
            C3
```

`read_csv` reads that CSV so that the legs keep their rows. The second Copy moves
down to C3's row, and the vertical at C reaches it. The rung is 4 rows, and the
last is the second Copy's lower row:

```text
     A      B      C     ...   AF
R    X001   T:C1   T     -...- copy(1,DS1)
            T:C2   |
            C3     -     -...- copy(2,DS2)
```

The logic is the same. This is the layout that CLICK's syntax check leaves. A
box with nothing beside it keeps blank rows under it for its height, with its
verticals carried through. Every row below moves down with the output.

## Pin continuation rows

A box's pin conditions go on continuation rows, with a dot token in `AF`. In a
circuit, they are the terms in the `Box`'s `pins`. The tokens are:

- `.reset()`
- `.down()`
- `.clock()`
- `.jump(step)`
- `.jog()`

Pin rows are independent left-rail paths, not AND-chained through the parent
output row conditions.

Pins go in a fixed order (timers: reset; `count_up`: down, reset; `count_down`:
reset; `shift`: clock, reset; drums: reset, jump, jog). A row with no AF token
between the instruction and a pin, or between two pins, is an OR leg of the input
above. It pushes the later pins down, and CLICK grows the box to match:

```csv
R,C1,-,...,-,"time_drum(...)"
,C2,T,-,...,-,.reset()
,C3,,...,,
,C4,-,...,-,.jump(DS2)
```

Here `.jump()` is on row 3, not row 2. An unused pin still takes a row of its
own, below the legs of the pin above it. For example, with Jump off, `.reset()`
with one leg and then `.jog()` puts Jog on row 4, with a blank Jump row 3 (CLICK
lays out a leg added with Insert Row the same way, and its check moves a leg drawn
on the unused Jump row there). Unused pins after the last used one sit directly
under it, beside its legs. The CSV doesn't place an unused pin. `read_csv` drops
blank rows, and these rules give the row. Legs under the last pin sit below the
box.

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

A leg needs `T` or `|` to join the row above. Without one, the contact feeds
nothing. CLICK's syntax check refuses that (C0202, C0003). `laddercodec.check()`
reports it, and `read_csv` keeps the rung as drawn:

```csv
R,C31,-,...,-,"count_down(CT4,CTD4,preset=5)"
,C32,,...,,
,C39,-,...,-,.reset()
```

Here C31 drives Down and C32 goes nowhere. Now put `NOP` in the second row's AF.
The box is 3 rows and C32 drives Down. C31 then sits on the unused top row, where
its wire stops at the box. CLICK refuses that the same way.

## Parsing conveniences

`laddercodec.read_csv()` accepts a few parsing conveniences beyond the canonical
writer contract:

- Timer instructions occupy 2 grid rows.
- If a timer rung is written with only 1 data row, the parser auto-pads a blank
  continuation row.
- Empty rows between rungs are ignored.

## For loops

A for loop is a run of rungs, in this order:

1. A `for(count)` or `for(count,oneshot=1)` row (`marker=R`).
2. The body rungs (`marker=R` each). A body rung with no contacts is a wire from
   the rail to its output (`R,-,...,-,out(C1)`). A nested loop is its own
   `for` .. `next()` run inside the body.
3. A closing `next()` row (`marker=R`).

CLICK v4 adds `break()` and `continue()` for a body rung. CLICK's syntax check
refuses these shapes:

- a `break()` or `continue()` with no contact before it (C000B, C000C)
- a `break()` or `continue()` outside a loop (C010F, C0110)
- loops nested more than three deep (C010D)

`read_csv` and `check()` check none of these rules.

## AF token format (canonical)

All tokens are compact canonical function-style strings:

- `name(pos1,pos2,key=val,...)`
- Positional args come first, then keyword args as `key=value`
- no extra whitespace
- dot pins as `.name(...)`

String rendering:

- A text constant, such as a Copy source or a compare side, is written as typed:
  its outer quotes and every character between them, with no escaping.
  `copy("A""B",TXT1)` copies the four characters `A""B`.
- In `copy` and `search`, write keyword values without quotes. The text runs from
  the first quote to the last, and each comma, bracket and quote between them is
  part of it, so `copy("A",B",TXT1)` copies the four characters `A",B`.
  `read_csv` raises `CsvReadError` for `copy("AB",TXT1,oneshot="1")`.
- In a keyword value in quotes in any other call, and in the error text of an
  `undecoded(...)` marker, a `"` is written as `""`. No backslash escaping.
- The CSV file then quotes the whole cell, as any CSV writer does.

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

A blank argument is its field left blank. `out()`, `on_delay(T1,TD1,preset=,unit=Tms)`
and `blockcopy(,DS10..DS13)` are refused with a `FieldError`. Its `reason` is
`missing`, and its `field` is the blank one (`Coil.operand`, `Timer.preset`; both
ends of a range). Building the instruction with that field blank gives the same
error.

A range with a blank end reads the same way. `write_csv` writes a range with both
ends blank as `..`, and a range with one end blank as `..DS4` or `DS1..`.
Elsewhere `..` is the value written (`copy(..,DS1)` is refused as an address).

A blank list, target or search expression reads the same way:

- `event_drum(outputs=,...)` leaves `Drum.outputs` blank. An empty list,
  `outputs=[]`, is a different value, and it is refused for its size.
- `send(target=,...)` leaves `Send.target` blank.
- `search(,result=DS1,found=C1)` leaves `Search.table_start`,
  `Search.table_end`, `Search.op` and `Search.value` blank. The `FieldError`
  holds a refusal of each of the four.

A blank argument that the token has no field for, such as `on_acc=` in
`toggle(C1,on_acc=)`, is still a syntax error, with no `field`.

A token that is broken in another way is also a syntax error. A blank flag
(`oneshot=`, `maintained=`) is `missing` in every instruction.

Producer may emit:

- `out(target)` or `out(target,oneshot=1)`
- `latch(target)`
- `reset(target)`
- `copy(source,target)` or `copy(source,target,oneshot=1)`
- `blockcopy(source,dest)` or `blockcopy(source,dest,oneshot=1)`
- `fill(value,dest)` or `fill(value,dest,oneshot=1)`
- `math(expression,dest,mode=decimal)` or `math(...,mode=hex,oneshot=1)`; the expression takes addresses, and a `<nickname>` is refused
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
- `send(target=X,remote_start="addr",source=X,sending=X,success=X,error=X,exception_response=X,function_code=N,word_swap=1)`
- `receive(target=X,remote_start="addr",dest=X,receiving=X,success=X,error=X,exception_response=X,function_code=N,word_swap=1)`
  - Write each argument once, with its keyword. The same rule applies inside
    `ModbusTcpTarget(...)`, `ModbusRtuTarget(...)` and `ModbusAddress(...)`. `read_csv`
    raises `CsvReadError` for an argument with no keyword, a keyword that the call doesn't
    accept, a keyword written twice, an empty argument, or a missing comma.
  - `target` is `ModbusRtuTarget(name="rtu",com_port="cpu2",device_id=1)` (ports `cpu2`,
    `cpu3`, `slot0_1`, `slot0_2`, `slot1_1`, `slot1_2`) or
    `ModbusTcpTarget(name="tcp",ip="192.168.1.20",port=502,device_id=1)`, with
    `com_port="wlan"` for the WLAN port (omitted = Ethernet)
  - Each part of a TCP `ip` is a decimal number. `read_csv` accepts leading zeros and
    `write_csv` leaves them out (`010.002.003.004` is `10.2.3.4`, `000.0.0.0` is `0.0.0.0`).
  - Write a quote inside a name twice: `name="a""b"` names the target `a"b`.
  - `device_id` is a number or a DS address (`device_id=DS2420`), as CLICK's Slave ID box allows
  - Slave ID numbers: Send RTU 0-247, Receive RTU 1-247, TCP 0-255. TCP `port` is 1-65535.
  - Hex `remote_start` runs `0h`-`FFFEh` (`0h`-`FFFDh` for a DD, DF, CTD or TXT source); a
    Send takes `register_type` `coil` or `holding`. It may be typed with `H`, zero padding or
    lowercase digits and is written in CLICK's form (`0H` is `0h`, `000Fh` is `Fh`, `ffeh` is
    `FFEh`).
  - A Send count from a hex `remote_start` ends at `FFFDh` from a DD, DF or CTD source, and
    at `FFFEh` from any other register source. Each element, and each TXT character, counts
    as one address. From `FFFCh`, a TXT source sends 2 characters.
  - `function_code=N` picks the Modbus code when the address leaves a choice. Receive from a
    CLICK address reads with FC01 (bits) or FC03 (registers) unless `function_code=2` or `4`.
    Send writes one element with FC05/FC06 and a block with FC15/FC16; `function_code=15` or
    `16` writes one element as a block. One DD, DF or CTD element is always FC16, and XD and
    YD go out only as FC06.
  - A Receive into registers takes DS, DD, DH, DF, YD or TXT. A CLICK `remote_start` matches
    the destination's type: DS from DS, TD or SD; DD from DD or CTD; DF from DF; DH or YD
    from DH, XD or YD; TXT from TXT. A YD destination, or DH read from XD or YD, takes one
    element; TXT takes an even count of 2 to 250 characters.
  - A Send to a CLICK `remote_start` writes a register of the source's type: DS or TD from
    DS, TD or SD; DD or CTD from DD or CTD; DF from DF; DH or YD from DH, XD or YD; TXT from
    TXT. A Send can't write an SD register.
  - A Send from TXT with FC16 takes an even count of 2 to 246 characters. With FC06 it
    sends one TXT register.
  - `word_swap=1` is refused where CLICK turns Word Swap off: a bit Receive, a YD or TXT
    destination, one DS or DH element, DH read from XD or YD, and DD or DF read from a CLICK
    address.
  - A Send offers `word_swap=1` only with FC16. It doesn't offer it for a TXT source, or for
    one register of DS, DH, TD or SD.
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
- `break()`, `continue()` (CLICK v4). See [For loops](#for-loops).
- `raw(ClassName,0xTTTT,N,rows=R,sub=S,pins=P,fields...)` - opaque instruction
  passthrough for binary round-trip fidelity. `ClassName` is the Click binary
  class name (unquoted), `0xTTTT` the type marker, `N` the part count, and the
  fields are the blob's tagged fields (`60a5=1`, `68b1[250]=`). The older form
  `raw(ClassName,hex)` holds the whole blob as a hex string, and may be followed
  by `rows=R,sub=S`.
  - `rows` is the box's row span, 1 to 32, and `sub` is its sub-rows, 1 to 255.
    The writer always writes both. Both go right after the part count (or the
    hex), `rows` first. On read each is optional:
    - a box with neither takes its class's height (2 rows for a Copy, 3 for a Send)
    - a box with `rows` and no `sub` has sub-rows equal to `rows`
    - a box with `sub` and no `rows` has its class's row span
  - `pins` gives the row of each later part of a box with 2 or more parts. Rows
    count below the main row, and `/` joins them: `pins=1/3/4` for a drum with an
    OR leg under its reset. The writer writes it after `sub` for every such box.
    A 1-part box and the older hex form have none. The rows are 1 to 31 and
    ascend, one per part after the first. On read it is optional. Without it the
    parts sit on rows 1, 2, ... A box ends one row below its last pin, so in this
    form `rows` must be the last pin + 1. The reader pads the rung to that height,
    as it does for other tall boxes. The hex form does not check this, and the
    writer uses it for a box stored at any other span.
  - `write_csv` writes an `Email`, `Home`, `PositionMove` or `VelocityMove` as a
    `raw(...)` token. Its box spans 3 rows, as CLICK draws it. The reader pads
    the rung with blank rows, as it does for other tall boxes. CLICK stores some
    boxes at 1 row: one pasted from an earlier version and not yet saved by its
    dialog. Such a box writes `rows=1,sub=1` and reads back at 1 row.
- `undecoded("<error>",rung=N,row=R,column=C,stop=end,to_the_end=1)` - the marker that stands in
  for a rung laddercodec could not decode ([Decoding](decoding.md#rungs-that-dont-decode)).
  `rung`, `row` and `column` count from 0 (column 31 is AF). `row` and `column` are
  omitted when the failure is not at one row or cell. `stop` is `end` in the main
  program and `return` in a subroutine. `to_the_end=1` comes last. It says that the
  marker stands for its rung and every rung after it, and it is omitted when the
  marker stands for its rung alone. A consumer runs the marker as that
  instruction, so the program stops where the rung was. `encode()` refuses the
  marker, so it never reaches CLICK. `write_csv()` also writes a marker, with an
  `UndecodedRungWarning`, for a rung it can't write, such as one holding an
  instruction that no token holds or a compare whose cell reads two ways. The
  `stop` argument of `write_csv()` sets the marker's `stop`.

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

- You can write an address in any letter case, with or without leading zeros.
  laddercodec keeps and writes it in CLICK's display form. X and Y pad to 3 digits
  (`x1` is `X001`). Every other bank is unpadded (`C001` is `C1`, `ds07` is `DS7`,
  `DS[ds01]` is `DS[DS1]`), and `xd0U` is `XD0u`. Constants are kept as written. A
  Math formula's function names are uppercase (`sum(x1:x16)` is
  `SUM ( X001 : X016 )`).
- An address must name a CLICK bank and lie inside its range. X and Y number by
  16-point slot: `X001`-`X016` on the CPU, `X021`-`X036` on its dual option slot,
  and `X101`-`X116` through `X801`-`X816` on expansion modules 1-8. `X017`,
  `C2001` and `DS0` raise `AddressError`.
- Each instruction narrows the banks it takes:
  - Contacts take X, Y, C, T, CT or SC. `.immediate` is only on X.
  - `out(...)`, `latch(...)`, `reset(...)` and the Out variants (`toggle`, `debounce`,
    `flasher`, `timed`) take Y, C or SC. `immediate(...)` is only on Y, and so are both
    ends of an immediate range.
  - The SC bits a coil writes are SC50, SC51, SC53, SC55, SC60, SC61, SC65, SC66, SC67,
    SC75, SC76, SC120, SC121, SC162, SC165, SC168, SC171, SC303, SC304, SC305, SC306,
    SC323, SC324, SC325 and SC326. An SC range needs both ends on this list.
  - A coil range stays in one bank, and its end is above its start. `out(C1..C2000)`
    and `out(immediate(Y001..Y101))` are accepted. `out(C9..C1)`, `out(C5..C5)` and
    `out(C5..Y5)` are rejected.
  - Variant accumulators are TD, and the on and off phases of `debounce` and
    `flasher` use two different TD registers. A preset is a DS register or a whole
    number up to 32767. The lowest number is 0 for `debounce` and 1 for `flasher`
    and `timed`.
  - A `debounce` may leave out one phase's keywords
    (`debounce(C1,on_acc=TD1,on_preset=100,unit=Tms)`). It needs at least one phase.
    `flasher` needs both.
  - A compare takes data registers or constants on either side, never bits. Both
    sides come from one group:
    - hex: XD, YD, DH, `0h`-`FFFFh`. The right side rejects `DH` in any letter
      case. CLICK saves it as an empty field. Write `0DH` for the hex constant D.
    - numeric: TD, CTD, DS, DD, DF, SD, or a number. A whole number lies in
      -2147483648 to 2147483647. A real is at most `3.4028235E+38` in size, and a
      larger one raises `FieldError` with `OBJ-005`.
    - text: TXT, or 1 to 128 characters in quotes such as `"A"` or `"AB"`, or
      `$41`. `$22` is a lone quote, and a quote inside quoted text is one
      character of it. `"$41"` is text. The left side takes printable ASCII only.

    A text compare takes `==` or `!=` only.
- Timer, counter, shift and drum fields take CLICK's banks:
  - Timer: done `T1`-`T500` with accumulator `TD` of the same number, and a
    preset that is a `DS` address or digits only, `0`-`32767` for every unit.
  - Counter: done `CT1`-`CT250` with accumulator `CTD` of the same number,
    and a preset that is a `DS` or `DD` address or an integer from
    `-2147483648` to `2147483647` (a `-` only in front, at most 12 characters).
  - Shift: both ends are `C` bits and differ. `shift(C1..C1)` and `shift(C1..C001)`
    are rejected. `shift(C106..C99)` runs backwards.
  - Drum:
    - 1-16 steps and 1-16 outputs (`Y` or `C`)
    - a pattern of 0/1 cells, with one row per step
    - current step `DS`, accumulator `TD`, completion flag `C`
    - a `.jump()` target that is a `DS` address
    - for each step, an event (event drum) or a duration (time drum). A time and
      event step needs a duration or an event.
  - Drum errors:
    - A time drum or a time and event drum without a `unit=` is a syntax error. A
      blank `unit=` on them is a `FieldError` (`missing`).
    - A time and event drum without an `accumulator=` is a syntax error. A blank
      `accumulator=` on a time and event drum is a `FieldError` (`missing`).
    - A `unit=` that is not `Tms`, `Ts`, `Tm`, `Th` or `Td` raises `FieldError`. So
      does an accumulator that is not `TD`, and a pattern cell that is not `0` or `1`.
    - An event drum has no time unit. `event_drum(...,unit=Ts)` and
      `Drum(kind="event_drum", unit="Ts", ...)` raise `FieldError` with the code
      `option-not-offered`. A blank `unit=` is accepted.
  - Drum events are X, Y, C, T, CT or SC. A duration is `0`-`32767` (no sign) or a
    `DS` address. No output appears twice or equals the completion flag, compared as
    addresses (`C1` and `C001` are the same bit).
- `for(count)`: a `DS`, `DD`, `TD`, `CTD` or `SD` address, or digits only from `0` to
  `2147483647`. A pointer (`DS[DS1]`) and a space inside the number are rejected. `-0` is
  accepted and read as `0`. Any other sign is rejected.
- `call("name")` names a subroutine as CLICK's Add New Subroutine dialog allows.
  After outer spaces are trimmed, the name:
  - is not blank
  - has at most 24 characters
  - has none of `\ / : * ? " < > |`
  - has a part before its last dot that is not a Windows device name (`CON`, `NUL`,
    `COM1`, ...)
- Block ranges render either:
  - contiguous compact form `BANKstart..BANKend` (same bank, +1 sequence), or
  - explicit list form `[A,B,C]`.
- Indirect refs render as `BANK[pointer]`. The pointer is a DS address, and `BANK` is
  one of C, DS, DD, DH, DF, XD, YD, TD, CTD or TXT (`copy(DD[DS100],DS1)`). A
  `copy` source may also be an SD pointer (`copy(SD[DS1],DS1)`). Only a
  single `copy` takes one. `blockcopy`, `fill`, `pack_*`, `unpack_to_*` and `search`
  raise `AddressError`.
- Copy, Block Copy, Fill, Pack, Unpack, Search and Math operands follow CLICK's
  dialogs and raise `AddressError` or `FieldError` naming the field:
  - a bit copies to Y or C
  - a text constant copies to TXT
  - both ends of a range sit in one bank, and the end comes after the start
    (`DS1..DS1` is rejected)
  - an X or Y range in a Pack source, a Block Copy source or an Unpack destination
    stays in one 16-point slot
  - a pack or unpack range fits its register (`pack_bits` takes bits, `pack_words`
    registers)
  - a Math result is DS, DD, DF, TD, CTD or SD in decimal mode, and DH or YD in hex
    mode
- A single `copy` destination, every address a `blockcopy` or `fill` fills and a
  decimal `math` result accept only the SD registers a program writes: SD29, SD31,
  SD32, SD34-SD36, SD40-SD42, SD50, SD51, SD60, SD61, SD106-SD108, SD112-SD114,
  SD140-SD147, SD214 and SD215. Any other SD raises `AddressError`
  (`copy(DS1,SD43)`, `blockcopy(DS1..DS2,SD42..SD43)`, `fill(5,SD29..SD38)`).
- Block Copy, Pack and Unpack pair banks as CLICK's dialog does:
  - `blockcopy`: bits go to Y or C; DS, DD, DH, DF and SD to DS, DD, DH, DF,
    TD, CTD or SD; TXT to DS, DD, DH or TXT. The destination end is the start
    plus the source's length, whatever the banks (`blockcopy(DS1..DS4,DD1..DD4)`).
    A run into Y that would cross a slot (`blockcopy(C1..C16,Y010..Y025)`) is
    rejected. What CLICK writes for it is not captured yet.
  - `pack_*`: X, Y, T, CT and SC bits pack into DH; C bits into DS, DD, DH or
    DF; DS words into DD or DF; DH words into DD; TXT into DS, DD, DH, DF, TD
    or CTD, and at most 4 characters into DH (`pack_text(TXT1..TXT4,DH1)`).
  - `unpack_to_*`: DS unpacks to C; DD and DF to C, DS or DH; DH to Y or C. An
    `unpack_to_bits` goes to the bit banks of that list (Y, C), and an
    `unpack_to_words` to its registers (DS, DH).
- Constants:
  - A single `copy` takes a 32-bit integer constant. A hex constant above `FFFFh`
    copies only to DD or CTD.
  - A `copy` source takes a 32-bit integer and unsigned hex up to `FFFFFFFFh`, with at
    most 8 digits above `FFFFh`. A `fill` value takes a 32-bit integer and unsigned hex
    up to `FFFFh`. A `fill` into TXT takes an integer or hex constant of one character
    (`5`) and a real (`1.5`). It rejects `-5`, `123` and `10h`.
  - A `search` value takes a 32-bit integer and unsigned hex up to `FFFFh` (`+1h` is
    rejected).
- A single `copy` source and a `math` constant are written as CLICK stores them,
  in `to_csv()`, `write_csv` and the encoded rung alike:
  - a real as CLICK saves it: `1.50` is `1.5`, `1e3` is `1000.0`, `.5` is
    `0.5`, and in a `math` a typed `+2.5` stays. A `math` real is written as
    CLICK's Math saves it (`0.000015` is `1.5E-05`, `20000000.0` is `2E+07`,
    `1234.000001` stays), except an integral one, which keeps a `.0` (`1E5` is
    `100000.0`). In a `math`, `write_csv` writes each real in a form that CLICK
    saves as the same value when you type it. CLICK cuts `0.00012345` typed so
    to `0.000123`, and saves `1.2345E-04` as `0.00012345`. So `write_csv` writes
    `math(1.2345E-04,DF1,mode=decimal)`, and the encoded rung holds
    `0.00012345`. CLICK saves a `copy` real as its value printed with 7
    significant digits, whatever form you typed it in. From `1E-04` to below
    `1E+07` the print is positional (`1.0E+06` is `1000000.0`). Otherwise it is
    in exponent form, with trailing zeros cut from the mantissa (`1.0E+16` is
    `1E+16`, `1.50E+16` is `1.5E+16`);
  - in a `copy`, a real without a typed `+` (`+1.5` is `1.5`), as CLICK's Copy
    stores it. CLICK's Copy keeps 7 significant digits, leading and trailing
    zeros aside. It saves a real typed with more cut to 7 (`3.4028235E+38` as
    `3.402823E+38`). So a `copy` rejects one, and the message names the constant
    of 7 digits to write (`copy(1.2345678,DF1)` names `1.234568`). A `math`
    rejects a real that CLICK would save as another value, and the message
    names the constant to write (`0.33333334` names `0.333333`);
  - in a `copy`, a decimal integer without leading zeros (`005` is `5`, `+5`
    and `+0` stay, `-0` is `0`), and a hex constant with uppercase digits, its
    leading zeros and a lowercase `h` (`0ffh` is `0FFh`, `ABCH` is `ABCh`);
  - in a `math`, a hex constant with uppercase digits and no leading zeros
    (`0ffh` is `FFh`, `0000h` is `0h`);
  - in a `copy` to TXT, `$` and one hex digit as the code with two (`$1` is
    `$01`). A compare's right side and a `search` value keep `$1` as typed. A
    `fill` and a compare's left side reject it.

  `copy(EH,DH1)` and `copy(1Eh,DH1)` are rejected. CLICK's Copy stores `EH` as
  the real `0.0` and `1Eh` as `1.0`, not as hex. Write the real, or write the hex
  value as a decimal integer (`14` for `Eh`, `30` for `1Eh`).

  `constant_text()` writes a Python int, float or str as text that builds a `math`
  or a `copy` holding that value (`constant_text(255, hex=True)` is `FFh`). A `copy`
  rejects a real of more than 7 significant digits, and a `math` rejects one that
  CLICK would save as another value (`constant_text(1/3)` is `0.33333334`). The
  largest float32 value is `3.402823466E+38`. Write it as `3.402823E+38` in a
  `copy` and in a `math`.
- Constants, counts and address numbers use the digits 0-9 only. A digit from
  another script (`٣`) is rejected.
- `search` takes a C bit as its found flag, `==` or `!=` for a text value (a
  text constant or a TXT register), and a hex value of at most `FFFFh`. A value
  address comes from the table's compare group: XD, YD or DH for a DH table, TXT
  for a TXT table, and TD, CTD, DS, DD, DF or SD for the others.
  `search(DS1..DS10 == TXT20,result=DS30,found=C1)` is rejected with `OBJ-004`.
  A text value may hold a quote, and each quote between the outer quotes is one
  character: `search(TXT1..TXT10 == "A""B",result=DS30,found=C1)` searches for
  the four characters `A""B`. `$22` searches for a lone quote character.
- In a decimal `math`, an integer constant must read back as typed. CLICK keeps
  its low 32 bits and refuses it when they print at a different length
  (`3000000000`, `007` and `-0` are rejected).
  - A decimal `math` takes no hex constant (`1Fh` or `1FH`), and a hex `math` takes
    no decimal one (`1.5`).
  - A hex `math` rejects hex digits without `h` (`7`, `005`, `FF`, `1e3`), though
    CLICK reads them as hex. Where CLICK takes the `h` form, the message names it
    (`7h`, `5h`, `FFh`, `1E3h`).
  - A hex constant has at most 4 digits, and an `H` suffix is written `h`, as CLICK
    writes it (`7H` becomes `7h`).
- Each `math` mode takes its own registers, and any other address is rejected, in
  a `SUM` too:
  - A hex formula takes only hex values: hex constants and the DH, XD and YD
    registers. It rejects any other register (`DS1 + 1h`, `DD1 + 1h`) and any bit
    (`SUM ( X001 : X002 )`). Copy a register into a DH first, or pack bits into a
    DH. Or use a decimal `math` for a DS, DD, DF, TD, CTD or SD value.
  - A decimal formula takes decimal constants and the DS, DD, DF, TD, CTD and SD
    registers. An X, Y, C, T or SC bit stands only as the range of a `SUM`
    (`SUM ( X001 : X016 )`, not `X001 + 1`). It rejects a DH, XD, YD or TXT register
    and a CT bit (`DS1 + DH1`, `SUM ( CT1 : CT5 )`). Copy a DH, XD, YD or TXT
    register into a DS first, or use a hex `math` for a DH, XD or YD value. Pack CT
    bits into a DH, then copy the DH into a DS or use it in a hex `math`.
- A bound of `RAND ( a , b )` takes fewer values than the rest of the formula:
  - In a decimal formula, a bound is a DS or DD register or an integer constant
    (`RAND ( -5 , DD1 )`). A DF, TD, CTD or SD register is rejected
    (`RAND ( DF1 , 10 )`), and so is a real constant (`RAND ( 1.5 , 10 )`). Copy the
    register into a DS or DD first.
  - In a hex formula, a bound is a DH register or a hex constant
    (`RAND ( DH1 , FFh )`). An XD or YD register is rejected (`RAND ( XD0 , Ah )`).
    Copy it into a DH first.
  - The two bounds differ: `RAND ( 1 , 1 )` and `RAND ( DH1 , DH1 )` are
    rejected. Bounds are equal when they read the same as CLICK shows them
    (`01h` is `1h`, `ds1` is `DS1`), so `RAND ( 1h , 01h )` is rejected and
    `RAND ( 1 , +1 )` is accepted. Reversed bounds are accepted (`RAND ( 10 , 1 )`).
- A `math` formula is at most 270 characters as CLICK stores it. A sum of 68
  addresses fits, and 69 does not. Constants, functions and parentheses count too.
- A `math` formula is read as CLICK's Math dialog reads it. A formula that CLICK
  would refuse raises `FieldError` (`AddressError` for an address):
  - It holds addresses, constants, function names, operators and parentheses,
    separated by spaces or tabs. It rejects:
    - any other word or character (`DS1 = DS2`, `FOO`, `NAN`, `0x1A`, a lone `.`, a
      pointer, a line break)
    - a real constant above float32's largest value, 3.402823466E+38, in size
      (`1E39`, and `3.4028235E+38`, which float32 rounds to that value)
    - a real that CLICK would save as another value. The message names the text
      that CLICK saves and the constant to write. From `1E-04` to below `1E+07`
      CLICK saves a real in positional form, and otherwise in exponent form.
      What it keeps depends on how the real is typed:
      - without an `E`, 6 digits after the point (`0.33333334` is saved as
        `0.333333`, `0.00012345` as `0.000123`, `12345678.9` as
        `1.234568E+07`; `1234567.0` is accepted);
      - with an `E`, 7 significant digits (`1.2345678E+15` is saved as
        `1.234568E+15`, `3.402823466E+38` as `3.402823E+38`; `1.2345E-04` and
        `1.234567E+10` are accepted);
      - with a lowercase `e`, a `math` rejects a real that either rule would
        change (`1.2345e-04` names `1.2345E-04`).
  - Each address lies inside its bank's range: `DS1 + DS0` is rejected.
  - A sign goes at the start, after `(` or after `,`. A decimal `math` joins it to
    the constant after it (`( + 5 )` is written `( +5 )`). After an operator, put
    the signed value in parentheses: `DS1 * ( -5 )`, not `DS1 * -5` or `DS1 - -5`.
  - Each operator stands between two values, and two values never stand side by
    side. `DS1 +`, `* DS1`, `DS1 DS2`, `2 PI` and `( DS1 ) ( DS2 )` are rejected.
  - A function takes its argument in parentheses (`SIN ( DF1 )`, not `SIN DF1`).
    `PI` stands alone or before parentheses (`PI ( 2 )`).
  - `RAND`, `LSH`, `RSH`, `LRO` and `RRO` take `( a , b )`, one token each
    (`RAND ( DS1 + 1 , 2 )` is rejected). The first argument of a shift or
    rotate is an address (`LSH ( 1h , 2h )` is rejected). A `,` anywhere else is
    rejected (`DS1 , DS2`, `MAX ( DS1 , DS2 )`). CLICK reads it as a decimal
    comma (OBJ-037 for `DS1 , DS2`; `MAX ( DS1 , DS2 )` carries no id).
  - `SUM`, `MAX`, `MIN`, `MDN` and `AVG` take `( a : b )`, a range of two
    addresses (`SUM ( DS1 + DS2 )`, `SUM ( DS1 )` and `SUM ( 1 : 5 )` are
    rejected). A `:` anywhere else is rejected (`DS1 : DS5`, `ABS ( DS1 : DS3 )`).
  - `SIN`, `COS`, `TAN`, `ASIN`, `ACOS`, `ATAN`, `LOG`, `LN`, `SQRT`, `RAD` and
    `DEG` hold no `RAND`, shift or rotate call, and no range but a `SUM`.
    `SIN ( SUM ( DF1 : DF3 ) )` is accepted, and `SIN ( MAX ( DF1 : DF3 ) )` is
    rejected.
  - In a hex `math`, a constant whose digits run into an `E` (`1Eh`, `0Eh`,
    `2E5Ah`, `001Eh`) is rejected, because CLICK reads the digits before the `E` as
    a real number. `E1h` and `1Fh` are accepted. So are digits, `E` and digits
    then `h` (`1E3h`, `2E5h`): CLICK stores a hex constant typed `1e3` as `1E3h`.
- A `math` range over X or Y with an end in the CPU's option slot, X021-X036 or
  Y021-Y036, is rejected although CLICK accepts it. On a CPU with no I/O modules,
  CLICK stores the wrong points for it (`SUM ( X001 : X036 )` leaves out
  X032..X035). Three kinds of such range are accepted, because CLICK stores them
  right:
  - a range from the CPU slot to X021 or Y021 (`SUM ( X001 : X021 )`)
  - a range of one point (`SUM ( X025 : X025 )`)
  - a range of two points numbered one apart (`SUM ( X025 : X026 )`;
    `SUM ( X036 : X101 )` is rejected)

  A range with no end in the option slot is accepted (`SUM ( X001 : X101 )`). The
  points CLICK stores are in [operand and reserved slots](../internals/instruction-blobs.md#operand-and-reserved-slots).
- Text constants are double-quoted (`copy("Q",TXT1)`, `TXT1=="T"`).
  - An ASCII-code constant is `$hh` (`copy($00,TXT1)`, `TXT1==$00`): `$` and
    exactly two hex digits from `$00` to `$FF`. `$`, `$100` and `$4142` raise
    `FieldError` in every field. So does `$1`, except as a `copy` source, a
    compare's right side or a `search` value.
  - CLICK writes one TXT register per character of a text constant, so `""`
    writes nothing and `copy("TT",TXT1)` writes TXT1 and TXT2. A `copy` whose
    text would run past TXT1000 raises `AddressError`.
  - A `copy` of text into a pointer (`TXT[DS1]`) takes 1 to 128 characters.
    CLICK stores no end for it.
  - A Fill value takes 1 to 128 printable ASCII characters in quotes. When the
    CSV is read or the instruction is built, it refuses `""`, a longer or
    non-ASCII text and a quote inside the text. Spell any other character as its
    `$hh` code, and a quote as `$22`.
  - A compare's left side takes 1 to 128 printable ASCII characters in quotes,
    and its right side takes 1 to 128 characters. Both refuse `""` and a longer
    text. A compare of text matches consecutive TXT registers (`TXT771=="AB"`
    compares TXT771 and TXT772).
  - Either side of a compare may hold a quote, and each quote between the outer
    quotes is one character: `TXT1=="A""B"` matches the four characters `A""B`.
    `$22` is a lone quote character. The text runs from its first quote to its
    last, and the operator is read outside it, so `"A==B"==TXT1` matches the
    characters `A==B`. When both sides are text, the operator is the one that
    leaves a text of at least one character on each side. A cell with two such
    operators reads two ways, such as `"A"=="B"=="C"`. `read_csv` raises
    `CsvReadError` for such a cell. CLICK accepts `"A"=="B"` compared with `"C"`,
    so a decoded program can hold that compare. `write_csv` writes the rung that
    holds it as an `undecoded(...)` marker, with an `UndecodedRungWarning`.
  - A Copy source, a compare's right side and a search value take any character
    from U+0001 to U+FFFF except a surrogate (`copy("é",TXT1)`, `"€"`, a tab, a
    line break). CLICK keeps these as typed. They refuse NUL and a character
    above U+FFFF. `write_csv` writes them inside the quotes, and `read_csv` reads
    them back. A line break elsewhere in a token raises `CsvReadError`.
  - A search matches the window the text fills.
  - A quoted `"$41"` is three characters of text, not the code `$41`. Use `$00`
    for the blank (NUL) character.
- Copy converters are emitted as a `convert=` kwarg on the instruction:
  - `convert=to_value` or `convert=to_ascii` for TXT copied to a number register.
    They give the character's value or its ASCII code.
    - CLICK's dialog asks for one of the two. So a plain copy of TXT into any
      number register but DF raises `FieldError` (`copy(TXT1,DS1)`,
      `blockcopy(TXT1..TXT2,DD1..DD2)`).
    - A TXT register copied to DF is a plain copy (`copy(TXT1,DF1)`), as CLICK
      saves it. `to_value` or `to_ascii` there raises `FieldError`, because CLICK's
      dialog offers neither.
  - A number constant, register or pointer copied to TXT needs `convert=to_text(...)`
    or `convert=to_binary`. CLICK's dialog saves one of them. It saves Copy Value as
    text by default, with suppress zero, or with real numbering for a real or DF
    source. So `copy(5,TXT1)` and `copy(DS1,TXT1)` raise `FieldError`, and the
    message names `convert=to_text(suppress_zero=1,termination_code=none)`.
  - `convert=to_binary` for a value converted between a real and a 32-bit integer,
    where a plain copy converts it:
    - DF to DD or CTD, and back (`copy(CTD1,DF1,convert=to_binary)`)
    - a real constant into DD or CTD
    - an integer constant outside int16 into DF
    - a pointer on either side of any of these (`copy(DF[DS1],CTD1,convert=to_binary)`)
  - `convert=to_binary`, or `convert=to_binary(termination_code=$XX)`, for a number
    register copied to TXT with a termination code. `none` is accepted and writes
    plain `to_binary`. Any other keyword raises `FieldError`.
  - A termination code is `none`, `0`, or `$` and two hex digits (`$0D`). Anything
    else, `$D` included, raises `FieldError`.
  - `convert=to_text(exponential=<0|1>,termination_code=<none|$XX>)` for a DF address
    or pointer (`DF[DS1]`) or a real constant (`1.5`). It picks real (`0`) or
    exponential (`1`) numbering.
  - `convert=to_text(suppress_zero=<0|1>,termination_code=<none|$XX>)` for any other
    source, including an integer or hex constant and a DD or DS pointer.
  - laddercodec writes and reads only the option that CLICK's dialog offers for the
    source. `suppress_zero` for a DF or real source raises `FieldError`. So does
    `exponential=1` for any other source. `exponential=0` for any other source is
    accepted and not written.
- A TXT register or pointer copied to TXT takes a termination code with no converter:
  `copy(TXT1,TXT21,termination_code=$0D)`, and for a range
  `blockcopy(TXT1..TXT2,TXT11..TXT12,termination_code=$0D)`.
  - Quoted text copied to TXT takes one the same way: `copy("AB",TXT1,termination_code=$0D)`.
    A decimal integer or a real copied to TXT takes one inside `to_text(...)`:
    `copy(5,TXT1,convert=to_text(suppress_zero=1,termination_code=$0D))`. The code adds
    no TXT register to the end that the constant fills. A hex constant or a `$hh` code
    with a code raises `FieldError`.
  - `none`, `0` or no keyword means no code, and any copy takes that.
  - A code for any other copy raises `FieldError`. So does a code beside a
    `convert=` kwarg. Inside `to_binary(...)` or `to_text(...)`, it is the converter's
    code.
  - A `blockcopy` of TXT into TXT takes no converter.
- Keywords by instruction:
  - `copy` and `blockcopy` take `convert`, `oneshot` and `termination_code`.
  - `fill`, `pack_bits`, `pack_words`, `unpack_to_bits` and `unpack_to_words` take
    `oneshot`.
  - `pack_text` takes `oneshot` and `allow_whitespace`.
  - Any other keyword (`terminaton_code=`) raises `CsvReadError`.
  - A flag is `1` or `0`. Any other value (`oneshot=yes`) raises `FieldError` with
    reason `flag`, and a blank `oneshot=` raises it with reason `missing`.
  - `allow_whitespace` is a `pack_text` option. A `Pack` of bits or words built with
    it raises `FieldError` with reason `conflict`.

## Immediate handling

Immediate operands are supported only in strict, explicit contexts.

Allowed condition-cell forms:

- `X001.immediate`
- `~X001.immediate`
- `immediate(X001)`
- `~immediate(X001)`

Allowed AF token forms:

- `out(immediate(Y001))`
- `latch(immediate(Y001))`
- `reset(immediate(Y001))`
- `out(immediate(Y001..Y004))`

Rules:

- A contact takes the `.immediate` suffix or the `immediate(...)` wrapper.
  `write_csv` writes the suffix. A coil target takes only the wrapper.
- Immediate is allowed only for:
  - direct rung contacts (normal and negated), and
  - `out(...)`, `latch(...)`, `reset(...)` target operands.
- Immediate is not allowed in:
  - edge contacts (`rise(...)`, `fall(...)`),
  - non-coil instruction operands (`copy`, `math`, `search`, etc.).
- Immediate coil targets must resolve to `Y` bank addresses.
- An immediate range is any ascending `Y` range, including one that crosses a
  module (`out(immediate(Y001..Y101))`).

## Values CLICK's dialog refuses

`write_csv` writes a decoded instruction that holds a value CLICK's dialog refuses
as it is held ([Decoding](decoding.md#values-clicks-dialog-refuses)). `read_csv`
refuses such a token, as it refuses any. `read_csv(path, unchecked=True)` reads it
as written and emits a `RefusedFieldWarning` for it. The warning's `rung` counts
the rungs that `read_csv` returns, from 0. Each refusal in the warning's `errors`
carries the `location` that the default read raises it with
([Where a read error is](#where-a-read-error-is)). The warning's message ends with
the first refusal's location.

A value that no stored instruction holds still raises. Examples are a timer unit
that is none of CLICK's, a flag that is not 0 or 1, and pin rows the box can't
take. A CSV holds no stored bytes, so `encode()` refuses the instruction.

To accept some refusals and write the instruction anyway, list their codes in
`allow=`:

```python
from laddercodec import encode, read_csv

rungs = read_csv("main.csv", allow=["bank-not-allowed"])
data = encode(rungs)
```

`read_csv` reads an instruction that CLICK's dialog refuses only if you list the
code of every error in the refusal ([Error codes](codes.md)). Any other refusal
raises, as it does by default. The values that `unchecked=True` can't keep raise
whatever you list. `read_csv` emits no warning for an instruction that it reads
this way. `encode()`, `write_csv` and `write_bundle` write it.

`read_csv` keeps a refusal that you list only when laddercodec can write the
instruction and read it back the same. Otherwise the refusal raises, as it does by
default. A check that depends on a refused field does not run, so `allow=` can let
through a value that such a check would refuse.

If you change a field with `replace`, the copy is checked again. A refused value
that the copy still holds then raises, even if you listed its code.

If you list a name that is not a code, or pass both `allow=` and `unchecked=True`,
`read_csv` raises `CsvReadError` before it reads the file.

### Build one in Python

```python
from laddercodec import Coil, ModbusTcpTarget, Send, replace

coil = Coil("X001", allow=["bank-not-allowed"])
target = ModbusTcpTarget("plc", "192.168.1.10", 502, 256, allow=["invalid-modbus-target"])
send = Send(target, "DS1", "DS1", 1, "C1", "C2", "C3", "", allow=["invalid-modbus-target"])
moved = replace(coil, operand="X002", allow=["bank-not-allowed"])
```

Each instruction class, Modbus target and `ModbusAddress` takes `allow=` as a
keyword. The constructor keeps the refusals that you list, as `read_csv(path,
allow=...)` keeps them, with the same limits. A refusal that you don't list raises,
as it does without `allow=`. `encode()`, `write_csv`, `lay_out()` and `check()` take
the instruction as they take one that `read_csv` read with `allow=`.

The instruction does not store `allow`. Equality, hashing and `repr` ignore it. A
class that has no checks, such as `End`, accepts `allow=` and ignores it.
`allow=None` and `allow=()` change nothing.

A Modbus target that holds a refused value needs `allow=` too, because building it
raises before the `Send` exists. A `Send` or `Receive` built with `allow=` builds its
target and its `ModbusAddress` again with its own list. A refusal there that the list
leaves out raises.

`replace()` checks a changed copy again, as it does for an instruction that
`read_csv` read. To keep a refusal in the copy, pass `allow=` to `replace()` too.

A bad `allow=` raises `LaddercodecError` when you build the instruction. For the
same value, `read_csv` raises `CsvReadError`, which is a subclass of
`LaddercodecError`.

## Where a read error is

```python
from laddercodec import CsvLocation, LaddercodecError, read_csv

try:
    rungs = read_csv("main.csv")
except LaddercodecError as exc:
    where = CsvLocation.of(exc)
    print(where.line, where.column_name)  # 5 D
```

`read_csv` raises `CsvReadError` for a file that isn't UTF-8 text, and for a row, token
or rung that it can't read. It raises `FieldError` (`AddressError` for an address)
for a value that CLICK's dialog refuses. Each is a `LaddercodecError`
([Errors](#errors)). Each carries a `CsvLocation` as its `location` attribute.
`CsvLocation.of(exc)` returns it, or `None` for an exception that has none. A
`FieldError` still names its field in `.field`. Each part is `None` where it is
not known:

| Attribute   | Holds                                                                                        |
|-------------|----------------------------------------------------------------------------------------------|
| `file`      | the CSV file                                                                                 |
| `line`      | the line the bad row starts on, from 1, blank lines counted; `None` for the whole file       |
| `rung_line` | the line of the `R` row that starts the row's rung; `None` for a row in no rung              |
| `row`       | the row within that rung, from 0: the `R` row is 0, comment rows are not counted             |
| `column`    | from 0: 0 is `A`, 30 is `AE`, 31 is `AF`; `None` for a whole row or its marker               |

The header is line 1 only when no blank line comes before it. A row is in no rung
when it is the header, a comment row, or a row with no `R` row between it and the
comment row or header above it. `column_name` gives the column's letters.

`read_csv` counts rows and columns as the CSV holds them, before layout. `column`
counts as `Finding.column` does. A refusal of what a pin row holds (a `.jump()`
target, a `.reset()` on a timer that can't be retentive) is at that pin row. A
missing pin row is at the box's row. The message ends with the location:

```text
Coil.operand: 'C9999' is outside C1-C2000 (at main.csv, line 5, rung at line 4, row 1 from 0, column AF)
```

Three cases differ:

- If a refusal comes while a box takes its pin rows, `read_csv` raises a `CsvReadError`,
  not a `FieldError`. The `CsvReadError` carries the refusal's `field`, `fields`,
  `code`, `reason`, `click_id` and `errors`, as `FieldError` has them (`Drum.jump_step`).
- Every refusal in a `FieldError`'s `errors` has its own `location`, not only the one
  raised. A refusal that a pin row's value causes is at that pin's row. The rest
  take the cell that raised them. Only the raised error's message ends with the
  location.
- A file that isn't UTF-8 raises a `CsvReadError` with the `UnicodeDecodeError`'s
  message and the `UnicodeDecodeError` as its `__cause__`. Its location holds
  `file` only. A `csv.Error` (such as a cell longer than `csv.field_size_limit()`)
  arrives the same way, at the line its row starts on.

`read_bundle` and `parse_bundle` give the location the same way. `file` names the file at fault,
or `main.csv` when it is missing.

## Errors

`decode()`, `decode_program()`, `encode()`, `read_csv()`, `write_csv()`, `csv_rows()`, `read_bundle()`, `write_bundle()` and `check()`
raise a `LaddercodecError` for input they can't read or write, and every
`LaddercodecError` is a `ValueError`:

| Class           | Raised by                                                                    |
|-----------------|------------------------------------------------------------------------------|
| `DecodeError`   | `decode()` for a bad envelope (magic or size), `decode_program()` for a bad file header |
| `EncodeError`   | `encode()` for a rung it can't write: a grid of the wrong size, a wire CLICK can't draw, two `NOP`s, an `Undecoded` marker, a comment too long |
| `CsvReadError`  | `read_csv` and `read_bundle` for a file that isn't UTF-8, or a row, token or rung they can't read; `read_bundle` for a missing `main.csv`, a subroutine file name that CLICK refuses or that starts or ends with whitespace, or two subroutine file names that are equal when the case of A-Z is ignored |
| `CsvWriteError` | `write_csv`, `csv_rows` and `write_bundle` for a rung the CSV can't hold; `write_bundle` for two subroutine names that are equal when the case of A-Z is ignored or whose files would be one file on a file system that ignores case, a name that holds a control character, or a path it would write that exists and is of the wrong kind |
| `FieldError`    | building an instruction, `read_csv`, `read_bundle` or `encode()`, for a value CLICK's dialog refuses; `AddressError` for an address. `write_bundle` for a subroutine name that CLICK refuses |

## Consumer recommendations

1. Validate exact header and column count (33).
2. Parse in row order and preserve ordering semantics.
3. Treat `AF` as an opaque canonical token string unless your decoder
   intentionally parses token grammar.
4. Treat unknown future token names as extension points (fail closed if strict).
5. Segment rungs by a `marker` of `R` optionally followed by digits (`R`, `R1`, `R2`, ...).
