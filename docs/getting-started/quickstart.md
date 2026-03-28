# Quickstart

## Encode a rung from CSV

The simplest path: write a CSV file describing a rung, then encode it to clipboard binary.

```python
from laddercodec import read_csv, encode

rungs = read_csv("my_rung.csv")
binary = encode(rungs[0])

# `binary` is ready to write to the clipboard or save to a .bin file
with open("my_rung.bin", "wb") as f:
    f.write(binary)
```

## Encode a rung from code

Build the rung data directly — no CSV needed.

```python
from laddercodec import encode, Rung, Contact, Coil

# A simple rung: NO contact on column A, output coil on AF
conds = [[""] * 31]  # 31 condition columns, all blank
conds[0][0] = Contact.from_csv_token("X001")

binary = encode(Rung(1, conds, [Coil.from_csv_token("out(Y001)")], None))
```

## Decode a binary

Read a clipboard binary back into structured data.

```python
from laddercodec import decode

with open("my_rung.bin", "rb") as f:
    data = f.read()

decoded = decode(data)
print(f"Rows: {decoded.logical_rows}")
print(f"Comment: {decoded.comment}")
print(f"Instructions: {decoded.instructions}")
```

## Decode a program file

Read a Click program file (`Scr*.tmp`) — the internal format Click writes to disk.

```python
from laddercodec import decode_program

with open("Scr1.tmp", "rb") as f:
    program = decode_program(f.read())

print(f"Program: {program.name} ({len(program.rungs)} rungs)")
for rung in program.rungs:
    print(f"  {rung.logical_rows} rows, comment: {rung.comment}")
```

## Round-trip

Encode and decode are inverses for all supported instruction types.

```python
from laddercodec import encode, decode, Rung, Contact, Coil

binary = encode(Rung(
    1,
    [[Contact.from_csv_token("X001")] + [""] * 30],
    [Coil.from_csv_token("out(Y001)")],
    "My comment",
))

decoded = decode(binary)
assert decoded.logical_rows == 1
assert decoded.comment == "My comment"
```

## Multi-rung encoding

Combine multiple rungs into a single clipboard buffer.

```python
from laddercodec import read_csv, encode

rungs = read_csv("multi_rung.csv")
binary = encode(rungs)
```

## Full binary-to-CSV pipeline

Decode a binary and write it out as a CSV file.

```python
from laddercodec import decode, write_csv

data = open("capture.bin", "rb").read()
result = decode(data)
rungs = result if isinstance(result, list) else [result]
write_csv("output.csv", rungs)
```
