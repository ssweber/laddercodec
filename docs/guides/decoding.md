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
| `logical_rows` | `int` | Number of rows (1..32) |
| `conditions` | `list[list[str \| Contact \| CompareContact]]` | 31-column grid of wire tokens and instruction objects |
| `instructions` | `list[str \| Coil \| Timer \| Counter \| ...]` | One AF token per row |
| `comment` | `str \| None` | Plain text with markdown formatting |

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

At the moment, Click `Email`, `Home`, `Position`, and `Velocity` instructions
also surface this way. They are supported for binary/SCR round-trip, but they
are not yet modeled as dedicated DSL classes, so they currently emit
`raw(...)` tokens.

### Legacy encodings

A rung that an older laddercodec saved can hold bytes that decode to the same text
as today's bytes, but that CLICK runs differently. `decode()` and
`decode_program()` still return the rungs, and they emit a `LegacyEncodingWarning`.
The only case today is a Math decimal constant outside -32768..32767 that was
stored as 16-bit (`H70000`). CLICK runs it as its low 16 bits, so `70000` runs as
4464. Re-paste the rung to store it as 32-bit.

The warning carries `instruction`, `token`, `detail`, `rung` (0-based index, or
`None`) and `program` (for `decode_program()`). To collect them:

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
# Math.expression: SUM ( X001 : X036 ) is refused: X036 is in the option slot (X021-X036), and CLICK sums the wrong bits for this range.
```

The warning carries `instruction`, `error` (the `FieldError` that building the
instruction raises), `errors` (every refusal, with `error` first), `rung` (0-based
index, or `None`) and `program` (for `decode_program()`). The refusals are the
ones that construction raises ([Refused values](encoding.md#refused-values)).

If you encode the instruction unchanged, it encodes as it did when it decoded as
`RawInstruction`, so `encode(decode(data))` writes the rung back as before:

- If it was decoded from a clipboard, you get the blob and cell rows that CLICK
  stored.
- If it is an output box that `decode_program()` decoded, you get the blob that its
  tags make.
- If it is a condition that `decode_program()` decoded, it has no such blob, and
  `encode()` raises its `error`.

If you change a field that the blob holds, the instruction is checked again. Any
field counts except a contact's `wire_down`. If the instruction is still refused,
`encode()` raises the refusal that it holds now. If your change fixed it, `encode()`
encodes it as building it from its fields would (`ds2` is written `DS2`). To fix
a refusal, change the field that the error names, then encode.

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

If a Copy or Pack destination is stored with a space at either edge, it decodes as
the address without the space. If you encode it unchanged, it encodes as it did
when it decoded as `RawInstruction`, space and all.

CLICK saves some addresses as you typed them, not in display form. These are a
Copy, Block Copy or Pack destination, each address in a Math formula, and a hex
Math's result (`DS001`, `ds1`, `YD0U`, `DS[ds1]`). They decode in display form
(`DS1`, `YD0u`, `DS[DS1]`), as CLICK's editor shows them, and the CSV holds that
form. When you encode such an instruction:

- If you leave it unchanged, you get back the bytes CLICK saved.
- If you change it, it encodes in display form.
- If you read it back from the CSV that `write_csv` wrote, it encodes in display
  form. A CSV file holds no blob.

An address typed with fewer digits than its display form (`Y1`) is left raw. So is
a typed address in any other field.

### Wire tokens

Wire cells are decoded into string tokens: `"-"`, `"|"`, `"T"`, or `""` (blank). The segment flag is ignored during decoding — only the right and down flags determine the token.

### Comments

RTF comment bodies are decoded to plain text with markdown formatting:

- `{\b text}` → `**text**`
- `{\i text}` → `*text*`
- `{\ul text}` → `__text__`
- `\par` → newline

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
# UNDECODED: rung 4, row 0: the output column has a down wire, which isn't supported. CLICK's syntax check removes it.
```

The marker rung is one row, wired from the rail into an `Undecoded` output. Its
comment starts with the marker's headline, `UNDECODED: rung N, row R: <error>`.
The rung's own comment follows, if that decoded.

`Undecoded` has `error`, `rung`, `row`, `column` and `stop`. `rung`, `row` and
`column` count from 0 (column 31 is AF). `row` and `column` are `None` when the
failure is not at one row or cell. The warning carries the `marker`, and the
`program` name for `decode_program()`.

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

A marker never reaches CLICK. `encode()` refuses it, and `check()` reports it as an
`undecoded` finding. `write_csv()` writes it as an `undecoded(...)` token, and
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

Each `Finding` has `rung`, `kind`, `code`, `captured`, `row`, `column` and
`message`. The `rung`, `row` and `column` fields count from 0 (column 0 is A, 31
is AF). `row` and `column` are `None` for a finding about the whole rung.

A captured C0202 message names the cell as CLICK prints it, with rows counted from
1. `row=2, column=3` reads "row 3, column D in CLICK's numbering". If the rung's
first row is blank, the count starts on the second row. That rests on one capture,
and CLICK may count otherwise. Every other message gives the cell counted from 0.

`captured` is `True` where a CLICK capture shows its syntax check reporting the
shape with that code:
| `kind` | shape | `code` |
|---|---|---|
| `not_series_parallel` | the circuit into a main box input is not series-parallel (a bridge) | `C0001` |
| `no_rail` | a contact whose input no line connects to the rail, at the first contact of each such group | `C0202` |
| `feeds_no_box` | a path from the rail that reaches no box input, at its last contact (the cell CLICK named in three captured rungs) | `C0202` |
| `no_coil` | a path from the rail that reaches no box, once per rung; CLICK's text is "There is no Coil instruction in the rung" | `C0003` |
| `nop_only_contact` | a contact the rail reaches that feeds a `NOP` and no other box, even when a coil is on another wire or leg of the rung; CLICK's text is "There is no Coil instruction in the rung" | `C0003` |
| `shorted_contact` | a contact whose two sides a wire joins (in parallel with a wire-only leg); CLICK's text is "Short circuit error" | `C0002` |
| `unwired_pin` | a timer's or counter's reset whose row holds nothing (no contact, no wire, no vertical into it), at its AF cell | `C0202` |
| `output_above_pinned_box` | a box above a box with a used pin row (a `.reset()` row and the like), both off the pinned box's main input's net, once per group of boxes that share nets | `C000A` |
| `shared_input_net` | another box's main input below a pin, on the pin's net, where that net is the pin's own (not its box's main input's net), once per group of boxes that share nets | `C000A` |
| `pin_without_contact` | a timer's or drum's reset whose contacts are all on the main input's circuit | `C0205` (timer), `C0212` (drum) |
| `undecoded` | an undecoded marker, at its AF cell ([Rungs that don't decode](#rungs-that-dont-decode)); CLICK never sees one | none |

The net of a C000A finding is one that the rail reaches through a contact, not the
rail itself. A rung whose rail reaches no box gets no `not_series_parallel`
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

`unwired_pin` has `C0202` with `captured=False` in these cases:

- the pin is not a timer's or counter's reset (a shift's clock, a
  drum's jog, a counter's down)
- the rung's rail reaches no box
- the pin's row holds a wire or a contact, but no rail or contact reaches it

A rung that holds an undecoded marker gets an `undecoded` finding for each marker,
then its other findings. A marker rung as the decoders make it (one row of wires
into the marker) gets only its `undecoded` finding.

`pin_without_contact` on other pins (a counter's reset, a drum's jog) has no code.
On a reset wired straight from the rail, or a reset whose contacts are all another
pin's, it has the box's code with `captured=False`. A contact that two pins share
counts as the earlier pin's. A `no_rail` or `feeds_no_box` finding on a loop of
contacts is also `captured=False`.

These shapes are also reported with `captured=False`:

- an unpowered box
- a pin circuit that shares contacts with a main input (`pin_shares_main`) or
  another pin (`pin_shares_pin`) but has some of its own
- a pin circuit that is not series-parallel

Those kinds are provisional. They may be renamed or dropped once CLICK's response
to them is captured. A finding with `captured=False` may be a shape CLICK accepts.

CLICK's check drops a `NOP` that no rail or contact reaches. `check()` does not
report it, and `read_csv` drops it from a rung with a circuit. Neither happens to
a `NOP` on the rail alone, or to one on a coil's net.

## Round-trip identity

For all supported instruction types:

```python
from laddercodec import encode, decode, Rung

rung = Rung(lr, conds, afs, cmt)
[decoded] = decode(encode(rung))
assert decoded.logical_rows == lr
assert decoded.conditions == conds
assert decoded.instructions == afs
assert decoded.comment == cmt
```
