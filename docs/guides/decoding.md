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
| `instructions` | `list[str \| Coil \| Timer \| RawInstruction]` | One AF token per row |
| `comment` | `str \| None` | Plain text with markdown formatting |

### Instruction types

Known instruction types are decoded into domain objects:

- **Contacts** → `Contact` (NO, NC, edge, immediate)
- **Comparison contacts** → `CompareContact` (==, !=, >, <, >=, <=)
- **Coils** → `Coil` (out, latch, reset, immediate, range)
- **Timers** → `Timer` (on_delay, off_delay)

Unrecognised cells fall back to `RawInstruction` with the raw bytes preserved. This keeps the decoder forward-compatible — unknown instruction types don't crash the pipeline.

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
