# laddercodec

Binary codec for AutomationDirect CLICK PLC ladder clipboard format.

laddercodec encodes and decodes the native clipboard binary used by [CLICK Programming Software](https://www.automationdirect.com/clickplcs) (v2.60–v3.80). It's the codec layer that powers [clicknick](https://github.com/ssweber/clicknick).

## What it does

- **Encode** — CSV rung descriptions → clipboard binary, ready to paste into Click
- **Decode** — clipboard binary → structured data (contacts, coils, wires, comments)
- **Round-trip** — `decode(encode(data)) == data` for all supported instruction types

## Who it's for

- **clicknick developers** — this is the codec clicknick uses under the hood
- **Reverse engineers** — the [internals](internals/binary-format.md) section documents the binary format byte-by-byte
- **Tool builders** — anyone generating or consuming Click clipboard data programmatically

## Quick example

```python
from laddercodec import read_csv, encode, decode

# CSV → structured data → binary
rungs = read_csv("my_rung.csv")
binary = encode(rungs[0])

# Binary → structured data
decoded = decode(binary)
assert decoded.logical_rows == rungs[0].logical_rows
```

## Current status

Pre-alpha. Supports contacts (NO, NC, edge, immediate), comparison contacts, coils (out, latch, reset, immediate, range), and timers. See [known limitations](guides/encoding.md#known-limitations) for what's not yet implemented.

## Guide overview

| Section | What's in it |
|---|---|
| [Getting Started](getting-started/installation.md) | Install and encode your first rung |
| [Guides](guides/encoding.md) | Encoding, decoding, CSV format, adding new instruction types |
| [Internals](internals/binary-format.md) | Binary format spec, wire rendering rules, instruction blob structure |
| [API Reference](reference/index.md) | Auto-generated from docstrings |
