# laddercodec

**The compatibility layer for CLICK ladder data.** laddercodec reads and writes CLICK's native representations and enables reliable round-tripping between CLICK and the pyrung/ClickNick toolchain. Tested against v2.60 to v3.9x captures. Zero runtime dependencies.

It's the layer [ClickNick](https://pyrung.com/clicknick/) pastes through, and it's useful on its own to convert between CLICK ladder data, Python objects, and CSV.

## Install

```bash
uv add laddercodec
# or
pip install laddercodec
```

Requires Python 3.11+.

## Quick example

```python
from laddercodec import read_csv, encode, decode

# CSV → binary (ready to paste into Click)
rungs = read_csv("my_rung.csv")
binary = encode(rungs[0])

# Binary → structured data
rung = decode(binary)
print(rung.logical_rows)
print(rung.instructions)
```

## What's included

**[Encoder](guides/encoding.md)** — `encode()` takes `Rung` objects or canonical CSV and produces clipboard binary ready to paste into Click. Supports all standard instruction types, wire topologies, and styled comments.

**[Decoder](guides/decoding.md)** — `decode()` reads clipboard binary back into structured Python objects (contacts, coils, timers, wires, comments). `decode_program()` reads ladder data from native CLICK program files.

**[CSV I/O](guides/csv-format.md)** — `read_csv()` and `write_csv()` convert between the 33-column canonical CSV format and `Rung` objects. Multi-file program bundles supported.

**[CLICK format reference](internals/binary-format.md)** — Technical reference for CLICK's native clipboard and program representations, including binary layouts and instruction records.

## Status

`laddercodec` is **beta** for clipboard encode/decode, CSV I/O, and `decode_program()`.

`Email`, `Home`, `Position`, and `Velocity` still intentionally surface as `raw(...)` passthroughs so clipboard and program data round-trips stay lossless while those families remain opaque.

## Guide overview

| Section | What's in it |
|---|---|
| [Guides](guides/encoding.md) | Encoding, decoding, CSV format, adding new instruction types |
| [Internals](internals/binary-format.md) | Binary format spec, wire rendering rules, instruction blob structure |
| [API Reference](reference/index.md) | Auto-generated from docstrings |
