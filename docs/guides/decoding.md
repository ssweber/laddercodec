# Decoding

`decode()` reads a Click clipboard binary and returns structured data: a `list[Rung]`, one `Rung` per rung on the clipboard, a list of one for a single rung.

## Single rung

```python
from laddercodec import decode

with open("capture.bin", "rb") as f:
    data = f.read()

[rung] = decode(data)
```

Each `Rung` has the same fields that feed `encode()`:

| Field | Type | Description |
|---|---|---|
| `conditions` | `tuple[tuple[str \| Contact \| CompareContact \| Tee, ...], ...]` | 31-column grid of wire tokens and instruction objects, 1..32 rows |
| `instructions` | `tuple[str \| Coil \| Timer \| Counter \| ..., ...]` | One AF token per row |
| `comment` | `str \| None` | Plain text with markdown formatting |

`rung.logical_rows` is the number of rows, `len(rung.conditions)`. A contact with a
wire down from its cell's left edge decodes as a `Tee` around the contact, such as
`Tee(Contact("X001"))`.

### Instruction types

All standard Click instruction types are decoded into domain objects:

- **Contacts** → `Contact` (NO, NC, edge, immediate)
- **Comparison contacts** → `CompareContact` (==, !=, >, <, >=, <=)
- **Coils** → `Coil` (out, latch, reset, immediate, range, oneshot)
- **CLICK v4 Out variants** → `OutVariant` (toggle, debounce, flasher, timed)
- **Timers** → `Timer` (on_delay, off_delay, retentive)
- **Counters** → `Counter` (count_up, count_down)
- **Copy family** → `Copy`, `BlockCopy`, `Fill`, `Pack`, `Unpack`
- **Math** → `Math` (decimal/hex expressions)
- **Shift registers** → `Shift`
- **Drum sequencers** → `Drum` (event, time, and CLICK v4 time & event)
- **Table search** → `Search`
- **Flow control** → `Call`, `Return`, `End`, `ForLoop`, `Next`, `Break`, `Continue` (CLICK v4)
- **Modbus** → `Send`, `Receive`

Unrecognised cells fall back to `RawInstruction` with the raw bytes preserved. This keeps the decoder forward-compatible — unknown instruction types don't crash the pipeline. A cell whose stored value CLICK's dialog refuses is not raw. It decodes as its instruction ([Values CLICK's dialog refuses](#values-clicks-dialog-refuses)).

CLICK's Email, Home, Position and Velocity instructions decode as `Email`, `Home`,
`PositionMove` and `VelocityMove`. Each field holds the text that its tag stores, and
`write_csv` writes each instruction as a `raw(...)` token.

### Legacy encodings

A rung that an older laddercodec saved can hold bytes that decode to the same text
as today's bytes, but that CLICK runs differently. `decode()` and
`decode_program()` still return the rungs, and they emit a `LegacyEncodingWarning`.
There are two cases:

- A Math decimal constant outside -32768..32767 that was stored as 16-bit
  (`H70000`). CLICK runs it as its low 16 bits, so `70000` runs as 4464.
- A flag field that was stored empty and that encoding the rung again writes set,
  such as a Coil's one-shot or a Math's hex mode. laddercodec reads the flag as
  set, and CLICK runs it as clear. Only `decode()` warns for it. A program file
  writes a flag as a tag with no value. That is CLICK's own form, so
  `decode_program()` does not warn for it.

To store the rung as CLICK does, encode it again with this laddercodec and paste it.
A Math that holds such a constant encodes in laddercodec's form, even if you leave it
unchanged and it holds an address or a real that was saved as typed.

The warning carries `instruction`, `token`, `detail`, `rung` (0-based index, or
`None`) and `program` (for `decode_program()`). For a flag field that was stored
empty, `instruction` names the field, such as `"Coil.oneshot"`, and `token` is
`""`. If no field can be named, `instruction` is the class and `token` names the
tag, such as `"1246="`. To collect the warnings:

```python
import warnings
from laddercodec import LegacyEncodingWarning, decode

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always", LegacyEncodingWarning)
    rungs = decode(data)
legacy = [w.message for w in caught if issubclass(w.category, LegacyEncodingWarning)]
```

### Values CLICK's dialog refuses

A stored instruction can hold a value that CLICK's dialog refuses. CLICK keeps
whatever a paste holds. CLICK v4 and older laddercodec versions also store values
that today's checks refuse. `decode()` and `decode_program()` build such an
instruction with every value as stored, and they emit a `RefusedFieldWarning` for
it:

```python
import warnings
from laddercodec import RefusedFieldWarning, decode

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always", RefusedFieldWarning)
    rungs = decode(data)
for w in caught:
    if issubclass(w.category, RefusedFieldWarning):
        print(w.message.rung, w.message.instruction.to_csv())
        print(w.message.error)
# 2 math(SUM ( X001 : X036 ),DS1,mode=decimal)
# Math.expression: SUM ( X001 : X036 ) is refused: X036 is in the option slot (X021-X036). In the option slot, write a range of one point or of two points next to each other, such as SUM ( X025 : X026 ).
```

The warning carries `instruction`, `error` (the `FieldError` that building the
instruction raises), `errors` (every refusal, with `error` first), `rung` (0-based
index, or `None`) and `program` (for `decode_program()`). The refusals are the
ones that construction raises ([Refused values](encoding.md#refused-values)).

If you encode the instruction unchanged, it encodes as it did when it decoded as
`RawInstruction`, so `encode(decode(data))` writes the rung back as before:

- If it was decoded from a clipboard, you get the blob and cell rows that CLICK
  stored.
- If `decode_program()` decoded it, you get the blob that CLICK writes to the
  clipboard for the instruction, with the values that the program file stores. Some
  arrays differ: an RD or SD blob leaves out their empty entries, and a Math blob holds
  fewer reserved slots than CLICK v4 writes
  ([From a program file to the clipboard](../internals/binary-format.md#from-a-program-file-to-the-clipboard)).

To fix a refusal, call `replace()` with a new value for the field that the error
names. A `Rung` is frozen, so call `replace()` on the rung too, to put the copy in it:

```python
from laddercodec import replace

math = rungs[2].instructions[0]
fixed = replace(math, expression="SUM ( X001 : X016 )")
rungs[2] = replace(rungs[2], instructions=[fixed, *rungs[2].instructions[1:]])
```

If a value that you pass differs from the instruction's, `replace()` checks the copy
as if you built it new. If a value is still refused, `replace()` raises the
`FieldError` that building the instruction raises. If every value passes, the copy
encodes as building it from its fields would (`ds2` is written `DS2`). If every
value that you pass is equal to the field's current value, the copy has the same
blob and refusals as the original. A value that the constructor writes in another
form is a change. For example, `"ds2"` is a change to a field that holds `"DS2"`
([Change An Instruction](encoding.md#change-an-instruction)).

`write_csv()` writes the instruction as it is held. `read_csv(path, unchecked=True)`
reads it back with the same warning and locates each refusal in the CSV
([Where a read error is](csv-format.md#where-a-read-error-is)). By default
`read_csv` refuses it. A CSV file holds no blob, so the instruction that it reads
compares equal to the decoded one, but `encode()` raises its `error`.

A value that no stored instruction holds still decodes as `RawInstruction` (or an
unknown condition), with its bytes kept. These cases do that:

- an address not in CLICK's display form, outside the fields CLICK saves as typed
  (`C001` in an Out)
- a value outside a field's named values (a timer unit, a compare operator)
- text that is not a number, in a numeric field
- pin rows that the box can't take
- a value that makes a check crash
- a Math stored in nickname view
- an instruction whose CSV would not read back as the same instruction

If a Copy or Pack destination, the right side of a Compare or a Search's result is
stored with a space at either end, it decodes as the address without the space. If
you encode it unchanged, you get back the bytes that CLICK saved, space and all.

CLICK saves some addresses as you typed them, not in display form. These are a
Copy, Block Copy or Pack destination, each address in a Math formula, a hex Math's
result, the right side of a Compare, and a Search's table start and result (`DS001`,
`ds1`, `YD0U`, `DS[ds1]`). They decode in display form
(`DS1`, `YD0u`, `DS[DS1]`), as CLICK's editor shows them, and the CSV holds that
form. When you encode such an instruction:

- If you leave it unchanged, you get back the bytes CLICK saved.
- If you change it, it encodes in display form.
- If you read it back from the CSV that `write_csv` wrote, it encodes in display
  form. A CSV file holds no blob.

An address typed with fewer digits than its display form (`Y1`) is left raw. So is
a typed address in any other field.

CLICK saves some reals in a decimal Math formula as you typed them, such as
`3.0E+38` or `1.50`. Such a Math decodes with the real in laddercodec's form
(`3E+38`, `1.5`). `write_csv` writes that form. CLICK reads both forms as the same
value. If you encode the Math unchanged, you get back the bytes CLICK saved. If you
change it, or read it back from the CSV, it encodes in laddercodec's form. An older
laddercodec also wrote some reals as typed, and a Math that it wrote decodes and
encodes in the same way.

### Wire tokens

Wire cells are decoded into string tokens: `"-"`, `"|"`, `"T"`, or `""` (blank). The segment flag is ignored during decoding — only the right and down flags determine the token.

### Comments

RTF comment bodies are decoded to plain text with markdown formatting:

- `{\b text}` → `**text**`
- `{\i text}` → `*text*`
- `{\ul text}` → `__text__`
- `\par` → newline

`decode()` puts a backslash before a `*`, `_` or `\` in the text where
`encode()` would otherwise read it as a style or an escape. So CLICK's comment
text `_init_` decodes as `\_init\_`. See
[Comment styles and escapes](csv-format.md#comment-styles-and-escapes).

## Multi-rung buffers

A buffer of several rungs decodes the same way, to a longer list:

```python
from laddercodec import decode

for rung in decode(data):
    print(f"Rows: {rung.logical_rows}, Comment: {rung.comment}")
```

## Binary to CSV

Write decoded data directly to a CSV file:

```python
from laddercodec import decode, write_csv

write_csv("output.csv", decode(data))
```

`write_csv` writes each rung the way CLICK's syntax check draws it. If you copied a
rung before the check, the CSV can hold it redrawn. It can also split the rung
where its outputs' circuits meet only at the rail. The logic stays the same
([CSV layout](csv-format.md#layout)).

To get the rows without writing a file, call `csv_rows`:

```python
from laddercodec import CSV_HEADER, csv_rows, decode

rows = [list(CSV_HEADER), *csv_rows(decode(data))]
```

`csv_rows` returns the rows that `write_csv` writes after the header, each as a list of
strings. It accepts the same `index` and `stop` arguments as `write_csv`. `CSV_HEADER` is
the header row, as a tuple.

## Decode a program file

`decode_program()` reads a Click program file (`Scr*.tmp`) and returns a `Program` containing all rungs. These are the internal temp files Click Programming Software writes to disk — much more compact than clipboard format (~17x smaller).

```python
from laddercodec import decode_program

with open("Scr1.tmp", "rb") as f:
    data = f.read()

program = decode_program(data)
print(f"Program: {program.name}, index: {program.prog_idx}")
for i, rung in enumerate(program.rungs):
    print(f"  Rung {i}: {rung.logical_rows} rows")
```

The returned `Program` dataclass has:

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Program name from the file header |
| `prog_idx` | `int` | Program index (1 = main, 2+ = subroutines) |
| `rungs` | `list[Rung]` | Decoded rungs — same `Rung` objects as `decode()` returns |
| `undecoded` | `list[Undecoded]` | The undecoded markers in `rungs`, in order; empty when every rung decoded |

Each `Rung` in `program.rungs` has the same structure as clipboard-decoded rungs, so you can pass them to `encode()` (all but a marker rung), `write_csv()`, or any other API that accepts `Rung` objects.

## Rungs that don't decode

If laddercodec can't read a rung, it decodes that rung as an undecoded marker
rung. The rungs around it decode as usual. Each marker emits an
`UndecodedRungWarning`:

```python
import warnings
from laddercodec import UndecodedRungWarning, decode_program

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always", UndecodedRungWarning)
    program = decode_program(data)
for marker in program.undecoded:
    print(marker.headline)
# UNDECODED: CLICK rung 5, row 1: the output column has a down wire, which isn't supported. CLICK's syntax check removes it.
```

The marker rung is one row, wired from the rail into an `Undecoded` output. Its
comment starts with the marker's headline, `UNDECODED: CLICK rung N, row R: <error>`.
The headline counts the rung and the row from 1. CLICK counts them the same way.
The headline leaves out `, row R` when the failure is not at one row. The rung's
own comment follows, if that decoded.

`Undecoded` has `error`, `rung`, `row`, `column`, `stop` and `to_the_end`.
`rung`, `row` and `column` count from 0 (column 31 is AF). `row` and `column` are
`None` when the failure is not at one row or cell. `to_the_end` is True when the
marker stands for its rung and every rung after it. The warning carries the
`marker`, and the `program` name for `decode_program()`.

You can build a marker rung yourself:

```python
from laddercodec import Undecoded, marker_rung

rung = marker_rung(Undecoded("why", 3, 0), "the rung's own comment")
print(rung.comment)
# UNDECODED: CLICK rung 4, row 1: why
# the rung's own comment
```

`marker_rung()` returns the one-row rung that holds the marker. The second
argument is optional. Pass the rung's own comment there if you have it.

The marker stops the program where the rung was. Its `stop` is `"end"` in the
main program and `"return"` in a subroutine. A consumer that runs the program
runs the marker as that instruction. A program that ran past a rung it could not
read would run wrong. The missing rung may set a bit that a later rung reads, or
it may hold the `end()` or `return()` itself. `decode()` reads a clipboard with no
program, so its markers have `stop="end"`.

A rung decodes as a marker in two cases:

- a cell's bytes don't decode (wire flags that no token has)
- its output column has a down wire

Each such rung gets its own marker.

Sometimes the decoder can't find where the rest of the rungs start. This happens
when a clipboard row has cells that can't be walked or is cut off, and when a
program file record has broken framing. The rungs before that point decode. One
marker stands for the first rung not known to be whole and for every rung after
it. If this happens in a clipboard's first rung, `decode()` returns a list of the
marker rung alone, because it can't tell one rung from several.

That marker has `to_the_end` set to True, and its headline ends with a note:

```text
UNDECODED: CLICK rung 2: the rung has no data rows; decoding stopped, so this marker stands for CLICK rung 2 to the end
```

The decoder still raises `DecodeError` for a buffer it can't read at all. That
means a clipboard whose magic or size is wrong, or a program file whose header
doesn't parse.

A comment that doesn't decode does not make a marker. The rung keeps its logic.
Its comment becomes `UNDECODED comment: <error>`, and its `comment_rtf` keeps the
comment's bytes. The decoder emits an `UndecodedCommentWarning` with the `rung`,
the `error` and the `program` name. `Program.undecoded` does not list the rung.

The line after the note holds the plain text that can be read from the comment's
bytes. Styling is dropped. Paragraph breaks become line breaks. Non-ASCII
characters are kept, as in a comment that decodes. If the text would make the
comment too long to encode, it is cut and ends with `...`. An error message too
long to leave room for the text is cut the same way. If no text can be read, the
comment is the note alone.

`encode()` writes the note and the text like any comment. A `*` or `_` pair in the
text reads as styling when you encode it, as it does in any comment.

The decoder reads text in a font of charset 0 (Windows code page 1252) or 134
(GBK). In a font of any other charset, the decoder reads each non-ASCII byte as
U+FFFD and each ASCII byte as ASCII. Some charsets write one character as two
bytes, and the second byte can be ASCII. So where CLICK shows one character, the
comment may show U+FFFD and then a stray ASCII letter. If the text in such a font is
all ASCII, the decoder emits no warning. In a GBK font, the decoder reads each byte
that GBK cannot read as U+FFFD.

In both cases the decoder reads the rest of the comment as usual and puts no note
in it. Then it emits an `UndecodedCommentWarning` with `partial` set to True. If
you get this warning, compare the comment with what CLICK shows, and correct it
before you encode the rung.

A marker never reaches CLICK. `encode()` refuses it, and `check()` reports it as an
`undecoded-rung` finding. `write_csv()` writes it as an `undecoded(...)` token, and
`read_csv()` reads that token back ([CSV format](csv-format.md#supported-instruction-tokens-canonical-producer-set)).

## Check for CLICK v4 instructions

A pre-v4 CLICK pastes v4 rungs without complaint and then changes them. Break and
Continue come back as plain Next, which closes the loop early. Check before
pasting into a pre-v4 CLICK:

```python
from laddercodec import find_v4_only

for index, instruction in find_v4_only(rungs):
    print(f"rung {index}: {instruction.to_csv()} needs CLICK v4")
```

`find_v4_only` reports these as v4-only:

- `Break`, `Continue` and `OutVariant`
- a time & event `Drum`
- a time `Drum` with a duration from a register
- `Math` using MAX, MIN, MDN, AVG, ABS, RAND, SUM over a bit range, or ranges past
  500 interior addresses

`is_v4_only()` checks a single instruction.

<a id="check-for-line-connection-errors"></a>

## Check for rungs CLICK's syntax check rejects or redraws

CLICK pastes and saves a rung even if its syntax check refuses the lines. It
reports the problem only when you run that check. laddercodec encodes and writes
such a rung as you drew it. `check()` reports it. It accepts decoded rungs and
rungs read from CSV:

```python
from laddercodec import check, read_csv

for finding in check(read_csv("main.csv")):
    print(f"rung {finding.rung}: {finding.message}")
# rung 0: the circuit is not series-parallel (CLICK: C0001)
```

Each `Finding` has `rung`, `code`, `click_id`, `captured`, `row`, `column`,
`message` and `program` ([Check a program or a project](#check-a-program-or-a-project)).
The `rung`, `row` and `column` fields count from 0 (column 0 is A, 31
is AF). `row` and `column` are `None` for a finding about the whole rung.

A captured C0202 message names the cell as CLICK prints it, with rows counted from
1. `row=2, column=3` reads "row 3, column D in CLICK's numbering". If the rung's
first row is blank, the count starts on the second row. That rests on one capture,
and CLICK may count otherwise. Every other message gives the cell counted from 0.

`captured` is `True` where a CLICK capture shows its syntax check reporting the
shape with that CLICK id. [Error codes](codes.md) lists every code.

| `code` | shape | `click_id` |
|---|---|---|
| `not-series-parallel` | the circuit into a main box input is not series-parallel (a bridge) | `C0001` |
| `no-rail` | a contact whose input no line connects to the rail, at the first contact of each such group | `C0202` |
| `feeds-no-box` | a path from the rail that reaches no box input, at its last contact (the cell CLICK named in three captured rungs) | `C0202` |
| `no-coil` | a path from the rail that reaches no box, once per rung; CLICK's text is "There is no Coil instruction in the rung" | `C0003` |
| `contact-feeds-only-nop` | a contact the rail reaches that feeds a `NOP` and no other box, even when a coil is on another wire or leg of the rung; CLICK's text is "There is no Coil instruction in the rung" | `C0003` |
| `shorted-contact` | a contact whose two sides a wire joins (in parallel with a wire-only leg); CLICK's text is "Short circuit error" | `C0002` |
| `unwired-input` | a timer's or counter's reset whose row holds nothing (no contact, no wire, no vertical into it), at its AF cell | `C0202` |
| `output-above-box-inputs` | a box above a box with a used pin row (a `.reset()` row and the like), off the pinned box's main input's net or off a net that the main input's circuit runs through, such as the net between `X001` and `X003` when the two feed a timer in series, once per group of boxes that share nets | `C000A` |
| `shared-input-net` | another box's main input below a pin, on the pin's net, where that net is the pin's own (not its box's main input's net), once per group of boxes that share nets | `C000A` |
| `input-without-contact` | a timer's or drum's reset whose contacts are all on the main input's circuit | `C0205` (timer), `C0212` (drum) |
| `undecoded-rung` | an undecoded marker, at its AF cell ([Rungs that don't decode](#rungs-that-dont-decode)); CLICK never sees one | none |
| `layout-too-tall` | a rung that needs more than 32 rows, with every row that a box spans counted; CLICK can't hold one | none |
| `comment-too-long` | a rung comment that `encode()` refuses, because its RTF body is longer than 1400 bytes ([Comments](encoding.md#comments)) | none |

The net of a C000A finding is one that the rail reaches through a contact, not the
rail itself. A rung whose rail reaches no box gets no `not-series-parallel`
finding, as in CLICK.

A rung whose circuit is not series-parallel gets no C000A finding and no finding
about a pin's contacts. The boxes of a C000A finding also get no finding about
their pins' contacts. CLICK does the same on the two shapes captured: a bridge
with an output above a retentive timer on its net, and a timer's reset on an
output's net. Whether CLICK does so on other shapes is not captured. One example
is a reset teed off its box's main input, with another box below on that net.

C000A has `captured=False` in these cases:

- a `NOP` is the other box
- a box with a used pin is the box above
- a pin's net is shared with another pin, or with a main input above the pin
- a box is below the pinned box, on a reset teed off its main input

`unwired-input` has `C0202` with `captured=False` in these cases:

- the pin is not a timer's or counter's reset (a shift's clock, a
  drum's jog, a counter's down)
- the rung's rail reaches no box
- the pin's row holds a wire or a contact, but no rail or contact reaches it

A rung that holds an undecoded marker gets an `undecoded-rung` finding for each marker,
then its other findings. A marker rung as the decoders make it (one row of wires
into the marker) gets only its `undecoded-rung` finding.

A rung that needs more than 32 rows gets one `layout-too-tall` finding for the whole
rung, after its `undecoded-rung` findings. `encode()` refuses a rung of more than 32
rows. `read_csv()` and `write_csv()` refuse one too, unless CLICK's layout of it is
rungs of 32 rows or fewer. That happens when CLICK splits the rung, or when the layout
packs its rows.

A rung whose comment `encode()` refuses as too long gets one `comment-too-long`
finding for the whole rung. It comes after the rung's `undecoded-rung` and
`layout-too-tall` findings, and before its other findings. The message says how
many bytes CLICK would store and how many to cut. `check()` counts the bytes the
same way that `encode()` does.

`input-without-contact` on other pins (a counter's reset, a drum's jog) has no CLICK id.
On a reset wired straight from the rail, or a reset whose contacts are all another
pin's, it has the box's CLICK id with `captured=False`. A contact that two pins share
counts as the earlier pin's. A `no-rail` or `feeds-no-box` finding on a loop of
contacts is also `captured=False`.

These shapes are also reported with `captured=False`:

- an unpowered box
- a pin circuit that shares contacts with a main input (`input-shares-enable`) or
  another pin (`inputs-share-contacts`) but has some of its own
- a pin circuit that is not series-parallel

Those codes are provisional. They may be renamed or dropped once CLICK's response
to them is captured. A finding with `captured=False` may be a shape CLICK accepts.

CLICK's check drops a `NOP` that no rail or contact reaches. `check()` does not
report it, and `read_csv` drops it from a rung with a circuit. CLICK's check also
drops a `NOP` that the rail feeds through wires alone, when the rung has another
output. `check()` does not report that `NOP` either, and `read_csv` drops it. A
`NOP` that is the rung's only output stays, and so does a `NOP` on a coil's net.

### Check a program or a project

Pass `check()` a `Program` or a `Project`, and it also reports the rules that span
rungs: For/Next loops, Break and Continue, and Calls.

```python
from laddercodec import check, read_bundle

for finding in check(read_bundle("my_program")):
    print(f"{finding.program}, rung {finding.rung}: {finding.message}")
# Sub1, rung 0: row 0 from 0, column AF: this For would start a 4th loop, counting the
# loops around the Call: Main Program calls Sub1 on rung 3 from 0 inside 3 loops
# (CLICK: C010D). Loops nest at most 3 deep, counting the loops around a Call. Move Main
# Program's Call on rung 3 from 0 out of the loop that starts on rung 2 from 0.
```

Each finding's `program` is the `Program.name` of the program that holds the rung.
It is `None` when you pass rungs. On rungs alone, `check()` reports none of these
rules, because a list of rungs can be part of a program.

| `code` | shape | `click_id` |
|---|---|---|
| `for-without-next` | a loop that is still open at the last End or Return of its program | `C0102` |
| `next-without-for` | a Next with no open For before it | `C0101` |
| `for-nesting-depth` | a For that would nest loops more than 3 deep | `C010D` |
| `oneshot-inside-loop` | a For with One Shot on, inside another loop | `C0111` |
| `return-inside-loop` | a Return or End inside a loop of its own program | `C0115` |
| `nested-call` | a Call in a subroutine, which a paste into CLICK drops | none |
| `call-without-subroutine` | a Call in the main program that names no subroutine of the project | `C010C` |
| `break-outside-loop` | a Break that is not inside a loop | `C010F` |
| `continue-outside-loop` | a Continue that is not inside a loop | `C0110` |

Every finding of these rules is at the instruction's AF cell. Its message ends with
what to change.

- **Pairs.** A Next closes the nearest open For. A For past the depth limit opens no
  loop. The Next that would close it gets `next-without-for`.
- **Open loops.** A loop with no Next gets its finding at the last End or Return of
  its program, not at the For. That rung gets two findings: `return-inside-loop`,
  then `for-without-next`. Every End or Return after the For gets
  `return-inside-loop`. When no End or Return comes after the For, the For gets
  `for-without-next`.
- **Calls.** In a `Project`, the loops around a Call in the main program count in the
  subroutine that the Call names. A For in that subroutine gets `for-nesting-depth`
  when those loops and its own nest more than 3 deep. It gets
  `oneshot-inside-loop` when it has One Shot on and a loop is around the Call. In
  that subroutine, a Next with no open For of its own closes one of the loops around
  the Call, and gets no finding. A Break or Continue there is inside the loops around
  the Call. A Return or End there gets `return-inside-loop` only inside a loop of the
  subroutine itself.
- **Call names.** A Call names the first subroutine whose name matches
  `Call.subroutine` without regard to case. In a `Project`, a Call in the main program
  that names no subroutine gets `call-without-subroutine`. A `Program` alone has no
  list of subroutines. So a main `Program` alone gets no `call-without-subroutine`,
  even in the shape of a project that CLICK checked. A Call in a subroutine gets only
  `nested-call`. When main calls a subroutine from loops of different depths,
  `check()` counts the deepest.
- **Main.** In a `Project`, the main program is `project.main`. For a `Program`
  alone, it is the program with `prog_idx` 1. `check()` reads any other `Program`
  alone as a subroutine that main calls outside any loop.
- **Order.** A `Project` is checked main first, then each subroutine in
  `project.subroutines`. In each program, a rung's own findings come first, then its
  program findings.
- **Undecoded markers.** `check()` reads no For, Next, Return, End, Call, Break or
  Continue after a program's first undecoded marker, because the rung that the marker
  stands for may hold a For or a Next. A `RawInstruction` of class For, Next, Return,
  End or Call stops the reading in the same way. A For that is open where the
  reading stops gets no `for-without-next` finding. When the reading of the main
  program stops, the loops around a later Call are not known. In that project, a
  Next, a Break or a Continue in a subroutine gets no finding when the subroutine has
  no open For of its own.

A program finding has `captured=True` and its `click_id` only on the exact shapes
that CLICK answered. The whole project must have the shape of a project that CLICK
checked, and CLICK must have reported that finding there. A larger project that
contains an answered shape is not captured.

The shape is the project's exact CSV: each program's name, a `#` row for each line of
each rung's comment, and each row of the rung as it is, with each cell's CSV text.
`check()` does not lay the rung out first. Every cell counts: each wire, each contact
with its address, each instruction with its fields. The subroutines may come in any
order. A main program alone has the shape of a project with no subroutines. A
subroutine alone, and a rung with a cell that the CSV can't hold, are never captured.
`nested-call` has no CLICK id.

## Round-trip identity

For all supported instruction types:

```python
from laddercodec import encode, decode, Rung

rung = Rung(conds, afs, cmt)
[decoded] = decode(encode(rung))
assert decoded == rung
```

A rung stores its rows as tuples, so a rung that you build from lists equals the
decoded one.
