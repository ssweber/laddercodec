# laddercodec Documentation — Agent Context

## What is laddercodec

laddercodec is a pure-Python binary codec for the AutomationDirect CLICK PLC ladder clipboard format. It encodes and decodes the native clipboard binary used by CLICK Programming Software. Tested against captures from v2.60 through v4. Zero runtime dependencies. Consumed by clicknick (GUI editor) and tested via pyrung (simulation).

## Tone and style decisions

Sentence style follows the Writing section of the root `AGENTS.md`. These are the decisions that are specific to the docs.

- **Code speaks first.** Lead with a working example, then explain it. If the code is clear, don't restate it in prose.
- **One concept per section.** Short paragraphs, minimal formatting. Don't pile concepts.
- **Simple to complex.** Every guide starts with the 80% use case and then adds nuance. Don't front-load edge cases.
- **Real scenarios, not API walkthroughs.** Write "Encode a rung with contacts", not "Step 1: call encode()."
- **Link, don't repeat.** If the internals explain wire flags, link to that page. Don't explain them again.
- **Don't front-load internals.** Guides say how to use the library. Internals hold the binary format details. The API Reference holds the exhaustive signatures. Keep the three separate.
- **Hex is a first-class citizen.** This is a binary codec, so use hex offsets, byte layouts and flag tables freely. The audience understands them.

## Audience

Developers who work with CLICK PLC ladder logic programmatically. They know ladder logic concepts (contacts, coils, rungs, branches). They do not know Click's clipboard binary format.

## Key technical details

- Zero runtime dependencies — stdlib only.
- CSV files use a 33-column canonical format (marker + A..AE + AF).
- Wire tokens are four characters: `T`, `-`, `|`, blank.
- You place instruction objects (Contact, Coil, etc.) directly in the condition and AF grids.
- Comments are plain text with optional markdown-style formatting (bold, italic, underline).
- The encoder writes bytes directly from verified formulas. It has no ORM or intermediate representation.
- Round-trip identity: `decode(encode(rungs)) == rungs` for all supported types.
- `read_csv(path, allow=[codes])` reads an instruction whose refusals all have a listed code, if laddercodec can write it and read it back the same. It emits no warning, and `encode()` writes it. `decode(encode(rungs)) == rungs` holds for those rungs too, except a Send or Receive target's name. The constructor of each instruction, Modbus target and `ModbusAddress` accepts the same `allow=` keyword, with the same limits.
