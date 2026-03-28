# laddercodec

`laddercodec` encodes and decodes the native ladder clipboard binary used by
[AutomationDirect CLICK Programming Software](https://www.automationdirect.com/clickplcs)
(v2.60-v3.80).

It is the binary codec layer behind
[clicknick](https://github.com/ssweber/clicknick), and it is useful on its own
if you want to generate Click clipboard payloads, inspect captured binaries, or
decode `Scr*.tmp` program files.

## What It Does

- Encode `Rung` objects or canonical Click CSV into clipboard binary ready to paste into Click
- Decode clipboard binary back into structured Python objects
- Decode `Scr*.tmp` program files into `Program` objects with all rungs
- Round-trip supported instruction families losslessly, with `RawInstruction` passthrough for unknown AF blobs
- Ship with no runtime dependencies

## Install

```bash
pip install laddercodec
```

Or with `uv`:

```bash
uv add laddercodec
```

## Quickstart

The simplest path is CSV -> binary:

```python
from laddercodec import encode, read_csv

rungs = read_csv("main.csv")
binary = encode(rungs)

with open("main.bin", "wb") as f:
    f.write(binary)
```

You can also build rungs directly in code:

```python
from laddercodec import Coil, Contact, Rung, encode

rung = Rung(
    logical_rows=1,
    conditions=[
        [Contact.from_csv_token("X001")] + [""] * 30,
    ],
    instructions=[Coil.from_csv_token("out(Y001)")],
    comment="Motor start circuit",
)

binary = encode(rung)
```

And decode captured binary back into structured data:

```python
from laddercodec import decode

with open("capture.bin", "rb") as f:
    decoded = decode(f.read())

rungs = decoded if isinstance(decoded, list) else [decoded]
print(rungs[0].logical_rows)
print(rungs[0].comment)
```

## Public API

The root package is the stable release surface:

- Core functions: `encode`, `decode`, `decode_program`, `read_csv`, `write_csv`
- Model types: `Rung`, `Program`, `Project`
- Instruction types: `Contact`, `CompareContact`, `Coil`, `Timer`, `Counter`, `Copy`, `BlockCopy`, `Fill`, `Pack`, `Unpack`, `Math`, `Shift`, `Search`, `Drum`, `Call`, `Return`, `End`, `ForLoop`, `Next`, `Send`, `Receive`, `RawInstruction`

Advanced helpers stay module-scoped on purpose:

- `laddercodec.decode.decode_rung`
- `laddercodec.decode.decode_rungs`
- `laddercodec.decode.inspect_cells`
- `laddercodec.csv.bundle.parse_bundle`

## Status

Clipboard encoding/decoding, CSV I/O, and the root instruction models are
**beta**.

`decode_program()` is **alpha**: it is already useful, but it is backed by fewer
fixtures than the clipboard path and should be treated as a faster-moving API.

## Documentation

Full docs: <https://ssweber.github.io/laddercodec/>

- Getting started: <https://ssweber.github.io/laddercodec/getting-started/installation/>
- Encoding guide: <https://ssweber.github.io/laddercodec/guides/encoding/>
- Decoding guide: <https://ssweber.github.io/laddercodec/guides/decoding/>
- Binary format internals: <https://ssweber.github.io/laddercodec/internals/binary-format/>
- API reference: <https://ssweber.github.io/laddercodec/reference/>

## License

[MPL-2.0](LICENSE)
