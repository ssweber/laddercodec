# laddercodec

**The codec for CLICK's clipboard format.** When you copy a rung in CLICK Programming Software, the clipboard holds an undocumented binary. laddercodec decodes it into Python objects and encodes them back, byte for byte. Tested against v2.60 to v3.9x captures. Zero runtime dependencies.

It's the layer [ClickNick](https://pyrung.com/clicknick/) pastes through, and it's useful on its own if you want to generate CLICK clipboard payloads, inspect captured binaries, or decode `Scr*.tmp` program files.

- Documentation: https://pyrung.com/laddercodec/
- LLM docs index: https://pyrung.com/laddercodec/llms.txt
- LLM full context: https://pyrung.com/laddercodec/llms-full.txt

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

**[Encoder](https://pyrung.com/laddercodec/guides/encoding/)** — `encode()` takes `Rung` objects or canonical CSV and produces clipboard binary ready to paste into Click. Supports all standard instruction types, wire topologies, and styled comments.

**[Decoder](https://pyrung.com/laddercodec/guides/decoding/)** — `decode()` reads clipboard binary back into structured Python objects (contacts, coils, timers, wires, comments). `decode_program()` reads Click's internal `Scr*.tmp` program files.

**[CSV I/O](https://pyrung.com/laddercodec/guides/csv-format/)** — `read_csv()` and `write_csv()` convert between the 33-column canonical CSV format and `Rung` objects. Multi-file program bundles supported.

**[Binary format docs](https://pyrung.com/laddercodec/internals/binary-format/)** — Byte-level reverse engineering of Click's clipboard and program file formats: buffer layout, cell grid, wire flags, instruction blobs, and multi-rung framing.

## Status

`laddercodec` is **beta** for clipboard encode/decode, CSV I/O, and `decode_program()`.

`Email`, `Home`, `Position`, and `Velocity` still intentionally surface as `raw(...)` passthroughs so binary and SCR round-trips stay lossless while those families remain opaque.

## Learn more

| | |
|---|---|
| [Encoding guide](https://pyrung.com/laddercodec/guides/encoding/) | Encode, decode, and round-trip your first rung |
| [Decoding guide](https://pyrung.com/laddercodec/guides/decoding/) | Structured decode, program files, round-trip identity |
| [CSV format](https://pyrung.com/laddercodec/guides/csv-format/) | 33-column canonical format, bundle layout, topology rules |
| [Adding instructions](https://pyrung.com/laddercodec/guides/adding-instructions/) | Extend the codec with new instruction types |
| [API reference](https://pyrung.com/laddercodec/reference/) | Auto-generated from docstrings |

## Development

```bash
make install        # uv sync --all-extras --dev
make test           # pytest
make lint           # ruff + ty
make golden         # regenerate .bin from .csv fixtures
make docs-serve     # local docs dev server
make                # all of the above
```

## License

[MPL-2.0](LICENSE)
