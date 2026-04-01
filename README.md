# laddercodec

**Binary codec for AutomationDirect CLICK PLC ladder clipboard format.** Encodes and decodes the native clipboard binary used by CLICK Programming Software. Tested against v2.60-v3.9x captures. Zero runtime dependencies.

- Documentation: https://ssweber.github.io/laddercodec/
- LLM docs index: https://ssweber.github.io/laddercodec/llms.txt
- LLM full context: https://ssweber.github.io/laddercodec/llms-full.txt

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

**[Encoder](https://ssweber.github.io/laddercodec/guides/encoding/)** — `encode()` takes `Rung` objects or canonical CSV and produces clipboard binary ready to paste into Click. Supports all standard instruction types, wire topologies, and styled comments.

**[Decoder](https://ssweber.github.io/laddercodec/guides/decoding/)** — `decode()` reads clipboard binary back into structured Python objects (contacts, coils, timers, wires, comments). `decode_program()` reads Click's internal `Scr*.tmp` program files.

**[CSV I/O](https://ssweber.github.io/laddercodec/guides/csv-format/)** — `read_csv()` and `write_csv()` convert between the 33-column canonical CSV format and `Rung` objects. Multi-file program bundles supported.

**[Binary format docs](https://ssweber.github.io/laddercodec/internals/binary-format/)** — Byte-level reverse engineering of Click's clipboard and program file formats: buffer layout, cell grid, wire flags, instruction blobs, and multi-rung framing.

## Status

`laddercodec` is **beta** for clipboard encode/decode, CSV I/O, and `decode_program()`.

`Email`, `Home`, `Position`, and `Velocity` still intentionally surface as `raw(...)` passthroughs so binary and SCR round-trips stay lossless while those families remain opaque.

## Learn more

| | |
|---|---|
| [Quickstart](https://ssweber.github.io/laddercodec/getting-started/quickstart/) | Encode, decode, and round-trip your first rung |
| [Encoding guide](https://ssweber.github.io/laddercodec/guides/encoding/) | Build rungs, wire tokens, instruction types, comments |
| [Decoding guide](https://ssweber.github.io/laddercodec/guides/decoding/) | Structured decode, program files, round-trip identity |
| [CSV format](https://ssweber.github.io/laddercodec/guides/csv-format/) | 33-column canonical format, bundle layout, topology rules |
| [Adding instructions](https://ssweber.github.io/laddercodec/guides/adding-instructions/) | Extend the codec with new instruction types |
| [API reference](https://ssweber.github.io/laddercodec/reference/) | Auto-generated from docstrings |

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
