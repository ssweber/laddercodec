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
- **Timers** → `Timer` (on_delay, off_delay, retentive)
- **Counters** → `Counter` (count_up, count_down)
- **Copy family** → `Copy`, `BlockCopy`, `Fill`, `Pack`, `Unpack`
- **Math** → `Math` (decimal/hex expressions)
- **Shift registers** → `Shift`
- **Drum sequencers** → `Drum` (event/time)
- **Table search** → `Search`
- **Flow control** → `Call`, `Return`, `End`, `ForLoop`, `Next`
- **Modbus** → `Send`, `Receive`

Unrecognised cells fall back to `RawInstruction` with the raw bytes preserved. This keeps the decoder forward-compatible — unknown instruction types don't crash the pipeline.

At the moment, Click `Email`, `Home`, `Position`, and `Velocity` instructions
also surface this way. They are supported for binary/SCR round-trip, but they
are not yet modeled as dedicated DSL classes, so they currently emit
`raw(...)` tokens.

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
