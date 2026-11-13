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

Unrecognised cells fall back to `RawInstruction` with the raw bytes preserved. This keeps the decoder forward-compatible — unknown instruction types don't crash the pipeline.

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
| `prog_idx` | `int` | Program index (0 = main, 1+ = subroutines) |
| `rungs` | `list[Rung]` | Decoded rungs — same `Rung` objects as `decode()` returns |

Each `Rung` in `program.rungs` has the same structure as clipboard-decoded rungs, so you can pass them to `encode()`, `write_csv()`, or any other API that accepts `Rung` objects.

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

## Check for line connection errors

CLICK pastes and saves a rung whose circuit it cannot lay out, and reports it
only at its syntax check. laddercodec encodes and writes such a rung as drawn;
`check()` reports it, on decoded rungs or rungs read from CSV:

```python
from laddercodec import check, read_csv

for finding in check(read_csv("main.csv")):
    print(f"rung {finding.rung}: {finding.message}")
# rung 0: the circuit is not series-parallel (CLICK: C0001)
```

Each `Finding` has `rung`, `kind`, `code`, `row`, `column` and `message`. Rows and
columns count from 0 (column 0 is A, 31 is AF); `row` and `column` are `None` for a
finding about the whole circuit.

| `kind` | shape | `code` |
|---|---|---|
| `not_series_parallel` | a circuit into a box input is not series-parallel (a bridge) | `C0001` |
| `no_rail` | a contact whose input no wire or contact connects to the rail | `C0202` |
| `unpowered_box` | a box input that neither the rail nor a contact reaches | `None` |
| `feeds_no_box` | a contact on a path from the rail that ends at no box | `None` |
| `pin_shares_main` | a reset, jog or other pin input fed through contacts of a main input | `None` |
| `shorted_contact` | a contact whose two sides a wire joins | `None` |

`code` is `None` where CLICK's response to the shape has not been captured.

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
