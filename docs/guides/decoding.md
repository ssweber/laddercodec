# Decoding

`decode()` reads a Click clipboard binary and returns structured data. It returns a `Rung` for a single-rung buffer and a `list[Rung]` for a multi-rung buffer.

## Single rung

```python
from laddercodec import decode

with open("capture.bin", "rb") as f:
    data = f.read()

decoded = decode(data)
```

The returned `Rung` has the same fields that feed `encode()`:

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

Unrecognised cells fall back to `RawInstruction` with the raw bytes preserved. This keeps the decoder forward-compatible — unknown instruction types don't crash the pipeline. A stored value CLICK's dialog refuses does not make a cell raw: the cell decodes as its instruction ([Values CLICK's dialog refuses](#values-clicks-dialog-refuses)).

At the moment, Click `Email`, `Home`, `Position`, and `Velocity` instructions
also surface this way. They are supported for binary/SCR round-trip, but they
are not yet modeled as dedicated DSL classes, so they currently emit
`raw(...)` tokens.

### Legacy encodings

A rung saved from an older laddercodec can hold bytes that decode to the same text as today's but that CLICK runs differently. `decode()` and `decode_program()` still return the rungs and emit a `LegacyEncodingWarning`. At present the only case is a Math decimal constant outside -32768..32767 stored as 16-bit (`H70000`); CLICK runs it as its low 16 bits, so `70000` runs as 4464. Re-paste the rung to store it as 32-bit.

The warning carries `instruction`, `token`, `detail`, `rung` (0-based index, or `None`) and `program` (for `decode_program()`). To collect them:

```python
import warnings
from laddercodec import LegacyEncodingWarning, decode

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always", LegacyEncodingWarning)
    rungs = decode(data)
legacy = [w.message for w in caught if issubclass(w.category, LegacyEncodingWarning)]
```

### Values CLICK's dialog refuses

A stored instruction can hold a value CLICK's dialog refuses: CLICK keeps what a
paste holds, and CLICK v4 and older laddercodec versions store values that
today's checks refuse. `decode()` and `decode_program()` build such an
instruction with every value as stored and emit a `RefusedFieldWarning` for it:

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
# Math.expression: SUM ( X001 : X036 ) is refused; CLICK v4 stores a wrong member list ...
```

The warning carries `instruction`, `error` (the `FieldError` building the
instruction raises), `errors` (every refusal, `error` first), `rung` (0-based
index, or `None`) and `program` (for `decode_program()`). The refusals are the
ones construction raises ([Refused values](encoding.md#refused-values)).

Left unchanged, the instruction encodes as it did when it decoded as
`RawInstruction`, so `encode(decode(data))` writes the rung back as before:
decoded from a clipboard, as the blob and cell rows CLICK stored; an output box
decoded by `decode_program()`, as the blob its tags make. A condition decoded by
`decode_program()` has no such blob, and `encode()` raises its `error`.

Change a field the blob holds (any field but a contact's `wire_down`), and the
instruction is checked again: `encode()` raises the refusal it holds now, or, if
the change fixed it, encodes it as building it from its fields would (`ds2` is
written `DS2`). Fix the field the error names, then encode.

`write_csv()` writes the instruction as it is held, and
`read_csv(path, unchecked=True)` reads it back with the same warning, each refusal
located in the CSV ([Where a read error is](csv-format.md#where-a-read-error-is)); by
default `read_csv` refuses it. A CSV holds no blob, so the instruction it reads compares
equal to the decoded one but `encode()` raises its `error`.

A value no stored instruction holds still decodes as `RawInstruction` (or an
unknown condition) with its bytes kept: an address not in CLICK's display form
(`C001`), a value outside a field's named values (a timer unit, a compare
operator), text that is no number in a numeric field, pin rows the box can't
take, a value a check crashes on, a Math stored in nickname view, and an
instruction whose CSV would not read back as the same instruction. A Copy or Pack
destination stored with a space at either edge decodes as the address without the
space; left unchanged, it encodes as it did when it decoded as `RawInstruction`,
space and all.

### Wire tokens

Wire cells are decoded into string tokens: `"-"`, `"|"`, `"T"`, or `""` (blank). The segment flag is ignored during decoding — only the right and down flags determine the token.

### Comments

RTF comment bodies are decoded to plain text with markdown formatting:

- `{\b text}` → `**text**`
- `{\i text}` → `*text*`
- `{\ul text}` → `__text__`
- `\par` → newline

## Multi-rung buffers

`decode()` detects multi-rung buffers automatically and returns a list:

```python
from laddercodec import decode

decoded_list = decode(data)
for rung in decoded_list:
    print(f"Rows: {rung.logical_rows}, Comment: {rung.comment}")
```

## Binary to CSV

Write decoded data directly to a CSV file:

```python
from laddercodec import decode, write_csv

result = decode(data)
rungs = result if isinstance(result, list) else [result]
write_csv("output.csv", rungs)
```

`write_csv` writes each rung as CLICK's syntax check draws it. A rung copied
before the check can come out redrawn, or split where its outputs' circuits
meet only at the rail; the logic is the same ([CSV layout](csv-format.md#layout)).

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

A rung laddercodec can't read decodes as an undecoded marker rung, and the rungs
around it decode as usual. Each marker emits an `UndecodedRungWarning`:

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
comment is the marker's headline, `UNDECODED: rung N, row R: <error>`, then the
rung's own comment when that decoded. `Undecoded` has `error`, `rung`, `row`,
`column` and `stop`; `rung`, `row` and `column` count from 0 (column 31 is AF),
and `row` and `column` are `None` when the failure is not at one row or cell. The
warning carries the `marker`, and the `program` name for `decode_program()`.

The marker stops the program where the rung was. Its `stop` is `"end"` in the
main program and `"return"` in a subroutine, and a consumer that runs the program
runs the marker as that instruction. A program that ran past a rung it could not
read would run wrong: the missing rung may set a bit a later rung reads, or hold the
`end()` or `return()` itself. `decode()` reads a clipboard with no program, so its
markers have `stop="end"`.

A rung decodes as a marker when a cell's bytes don't decode (wire flags no token
has) or its output column has a down wire. Each such rung has its own marker.
When the decoder can't find where the rest of the rungs start (a clipboard row
whose cells can't be walked or that is cut off, or a program file record whose
framing is broken), the rungs before it decode, and one marker stands for the
first rung not known to be whole and every rung after it. When that happens in a
clipboard's first rung, `decode()` returns the marker rung alone, since it can't
tell one rung from several. A buffer the decoder can't read at all still raises:
`DecodeError` for a clipboard whose magic or size is wrong, `ValueError` for a
program file whose header doesn't parse.

A comment that doesn't decode does not make a marker: the rung keeps its logic,
its comment becomes `UNDECODED comment: <error>`, its `comment_rtf` keeps the
comment's bytes, and the decoder emits an `UndecodedCommentWarning` with the
`rung`, the `error` and the `program` name. `Program.undecoded` does not list
the rung.

The note is followed on the next line by the plain text that can be read from the
comment's bytes: styling is dropped, paragraph breaks become line breaks, and
non-ASCII characters are kept, as in a comment that decodes. Text that would
make the comment too long to encode is cut and ends with `...`; so is an error
message too long to leave room for it. When no text can be read, the comment is
the note alone.
`encode()` writes the note and the text like any comment. A `*` or `_` pair in
the text reads as styling when it is encoded, as it does in any comment.

A marker never reaches CLICK: `encode()` refuses it, and `check()` reports it as an
`undecoded` finding. `write_csv()` writes it as an `undecoded(...)` token that
`read_csv()` reads back ([CSV format](csv-format.md#supported-instruction-tokens-canonical-producer-set)).

## Check for CLICK v4 instructions

An older CLICK pastes v4 rungs without complaint and changes them: Break and
Continue come back as plain Next, which closes the loop early. Check before
pasting into a pre-v4 CLICK:

```python
from laddercodec import find_v4_only

for index, instruction in find_v4_only(rungs):
    print(f"rung {index}: {instruction.to_csv()} needs CLICK v4")
```

v4-only: `Break`, `Continue`, `OutVariant`, a time & event `Drum`, a time `Drum`
with a duration from a register, and `Math` using MAX, MIN, MDN, AVG, ABS, RAND,
SUM over a bit range, or ranges past 500 interior addresses. `is_v4_only()` checks
a single instruction.

<a id="check-for-line-connection-errors"></a>

## Check for rungs CLICK's syntax check rejects or redraws

CLICK pastes and saves a rung whose lines its syntax check refuses, and reports
it only at that check. laddercodec encodes and writes such a rung as drawn;
`check()` reports it, on decoded rungs or rungs read from CSV:

```python
from laddercodec import check, read_csv

for finding in check(read_csv("main.csv")):
    print(f"rung {finding.rung}: {finding.message}")
# rung 0: the circuit is not series-parallel (CLICK: C0001)
```

Each `Finding` has `rung`, `kind`, `code`, `captured`, `row`, `column` and
`message`. The `rung`, `row` and `column` fields count from 0 (column 0 is A, 31
is AF); `row` and `column` are `None` for a finding about the whole rung. A
captured C0202 message names the cell as CLICK prints it, rows from 1:
`row=2, column=3` reads "row 3, column D in CLICK's numbering". When the rung's
first row is blank, the count starts on the second row; that rests on one capture,
and CLICK may count otherwise. Every other message gives the cell counted from 0.
`captured` is `True` where a CLICK capture shows its syntax check reporting the
shape with that code:

| `kind` | shape | `code` |
|---|---|---|
| `not_series_parallel` | the circuit into a main box input is not series-parallel (a bridge) | `C0001` |
| `no_rail` | a contact whose input no line connects to the rail, at the first contact of each such group | `C0202` |
| `feeds_no_box` | a path from the rail that reaches no box input, at its last contact (the cell CLICK named in three captured rungs) | `C0202` |
| `no_coil` | a path from the rail that reaches no box, once per rung; CLICK's text is "There is no Coil instruction in the rung" | `C0003` |
| `unwired_pin` | a timer's or counter's reset whose row holds nothing (no contact, no wire, no vertical into it), at its AF cell | `C0202` |
| `output_above_pinned_box` | a box above a box with a used pin row (a `.reset()` row and the like), both off the pinned box's main input's net, once per group of boxes that share nets | `C000A` |
| `shared_input_net` | another box's main input below a pin, on the pin's net, where that net is the pin's own (not its box's main input's net), once per group of boxes that share nets | `C000A` |
| `pin_without_contact` | a timer's or drum's reset whose contacts are all on the main input's circuit | `C0205` (timer), `C0212` (drum) |
| `undecoded` | an undecoded marker, at its AF cell ([Rungs that don't decode](#rungs-that-dont-decode)); CLICK never sees one | none |

The net of a C000A finding is one the rail reaches through a contact, not the rail.
A rung whose rail reaches no box gets no `not_series_parallel` finding, as in CLICK.
A rung whose circuit is not series-parallel gets no C000A finding and no finding
about a pin's contacts, and the boxes of a C000A finding get no finding about their
pins' contacts. CLICK does the same on the two shapes captured: a bridge with an
output above a retentive timer on its net, and a timer's reset on an output's net.
Whether CLICK does so on other shapes, such as a reset teed off its box's main input
with another box below on that net, is not captured.
C000A has `captured=False` for a `NOP` as the other box, for a box with a used pin
as the box above, for a pin's net shared with another pin or with a main input
above the pin, and for a box below the pinned box on a reset teed off its main input.
`unwired_pin` on other pins (a shift's clock, a drum's jog, a counter's down), or in
a rung whose rail reaches no box, has `C0202` with `captured=False`, and so does a pin
whose row holds a wire or a contact but that no rail or contact reaches.
A rung that holds an undecoded marker gets an `undecoded` finding for each marker,
then its other findings; a marker rung as the decoders make it (one row of wires
into the marker) gets only its `undecoded` finding.
`pin_without_contact` on other pins (a counter's reset, a drum's jog) has no code,
and on a reset wired straight from the rail, or whose contacts are all another
pin's (a contact two pins share counts as the earlier pin's), it has the box's code
with `captured=False`. A `no_rail` or `feeds_no_box` finding on a loop of contacts is
also `captured=False`. Other shapes (an unpowered box, a shorted contact, a pin circuit
that shares contacts with a main input (`pin_shares_main`) or another pin
(`pin_shares_pin`) but has some of its own, and a pin circuit that is not
series-parallel) are reported with `captured=False`; those kinds are
provisional and may be renamed or dropped once CLICK's response to them is
captured. A finding with `captured=False` may be a shape CLICK accepts. A `NOP` that
no rail or contact reaches is not reported: CLICK's check drops it, and `read_csv`
drops it from a rung with a circuit.

## Round-trip identity

For all supported instruction types:

```python
from laddercodec import encode, decode, Rung

rung = Rung(lr, conds, afs, cmt)
decoded = decode(encode(rung))
assert decoded.logical_rows == lr
assert decoded.conditions == conds
assert decoded.instructions == afs
assert decoded.comment == cmt
```
