# laddercodec Documentation — Context for Claude

## What is laddercodec

laddercodec is a pure-Python binary codec for the AutomationDirect CLICK PLC ladder clipboard format. It encodes and decodes the native clipboard binary used by CLICK Programming Software (v2.60–v3.80). Zero runtime dependencies. Consumed by clicknick (GUI editor) and tested via pyrung (simulation).

## Tone and style decisions

- **Direct, shows-don't-tells.** No marketing fluff, no "powerful" or "elegant." Say what it does.
- **Code speaks first.** Lead with a working example, explain after. If the code is clear, don't restate it in prose.
- **One concept per section.** Short paragraphs, minimal formatting. Don't pile concepts.
- **Simple to complex.** Every guide starts with the 80% use case, then adds nuance. Don't front-load edge cases.
- **Real scenarios, not API walkthroughs.** "Encode a rung with contacts" not "Step 1: call encode()."
- **Link, don't repeat.** If wire flags are explained in the internals, link to it. Don't re-explain.
- **Don't front-load internals.** Guides = how to use it. Internals = binary format details. API Reference = exhaustive signatures. Keep them separate.
- **Hex is a first-class citizen.** This is a binary codec — use hex offsets, byte layouts, and flag tables freely. The audience understands them.

## Audience

Developers who work with CLICK PLC ladder logic programmatically. Assume familiarity with ladder logic concepts (contacts, coils, rungs, branches) but not with Click's clipboard binary format.

## Key technical details

- Zero runtime dependencies — stdlib only.
- CSV files use a 33-column canonical format (marker + A..AE + AF).
- Wire tokens are four characters: `T`, `-`, `|`, blank.
- Instruction objects (Contact, Coil, etc.) placed directly in condition/AF grids.
- Comments are plain text with optional markdown-style formatting (bold, italic, underline).
- The encoder writes bytes directly from verified formulas — no ORM or intermediate representation.
- Round-trip identity: `decode(encode(data)) == data` for all supported types.
