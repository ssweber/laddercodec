# laddercodec

**Binary codec for AutomationDirect CLICK PLC ladder clipboard format.** Encodes and decodes the native clipboard binary used by [CLICK Programming Software](https://www.automationdirect.com/clickplcs). Tested against v2.60-v3.9x captures. Zero runtime dependencies.

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

**[Decoder](guides/decoding.md)** — `decode()` reads clipboard binary back into structured Python objects (contacts, coils, timers, wires, comments). `decode_program()` reads Click's internal `Scr*.tmp` program files.

**[CSV I/O](guides/csv-format.md)** — `read_csv()` and `write_csv()` convert between the 33-column canonical CSV format and `Rung` objects. Multi-file program bundles supported.

**[Binary format docs](internals/binary-format.md)** — Byte-level reverse engineering of Click's clipboard and program file formats: buffer layout, cell grid, wire flags, instruction blobs, and multi-rung framing.

## Status

`laddercodec` is **beta** for clipboard encode/decode, CSV I/O, and `decode_program()`.

`Email`, `Home`, `Position`, and `Velocity` still intentionally surface as `raw(...)` passthroughs so binary and SCR round-trips stay lossless while those families remain opaque.

## Guide overview

| Section | What's in it |
|---|---|
| [Getting Started](getting-started/installation.md) | Install and encode your first rung |
| [Guides](guides/encoding.md) | Encoding, decoding, CSV format, adding new instruction types |
| [Internals](internals/binary-format.md) | Binary format spec, wire rendering rules, instruction blob structure |
| [API Reference](reference/index.md) | Auto-generated from docstrings |
