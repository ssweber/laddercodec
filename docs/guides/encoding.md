# Encoding

`laddercodec.encode()` is the stable root entry point for producing Click
clipboard binary.

It accepts either:

- a single `Rung`
- a sequence of `Rung` objects for a multi-rung clipboard buffer

If you already have canonical Click CSV, the shortest path is:

```python
from laddercodec import encode, read_csv

binary = encode(read_csv("main.csv"))
```

Low-level helpers such as `encode_rung()` and `encode_rungs()` are still
available in submodules for advanced use, but the root `encode()` API is the
preferred public surface.

## Build A Single Rung In Code

```python
from laddercodec import Coil, Contact, Rung, encode

rung = Rung(
    logical_rows=1,
    conditions=[
        [Contact.from_csv_token("X001"), "-", Contact.from_csv_token("~X002")] + [""] * 28,
    ],
    instructions=[Coil.from_csv_token("out(Y001)")],
    comment="Motor start circuit",
)

binary = encode(rung)
```

Every `Rung` has four fields:

| Field | Type | Notes |
|---|---|---|
| `logical_rows` | `int` | `1..32` |
| `conditions` | `list[list[object]]` | One row per logical row, exactly 31 condition columns each |
| `instructions` | `list[object]` | One AF token per logical row |
| `comment` | `str \| None` | Optional plain text with lightweight markdown styling |

## Wire Tokens

Condition columns accept four wire tokens as strings:

| Token | Meaning |
|---|---|
| `"-"` | Horizontal wire |
| `"|"` | Vertical down |
| `"T"` | Branch junction (right + down) |
| `""` | Blank cell |

```python
from laddercodec import Rung, encode

conds = [
    ["-", "T", "-", "-"] + [""] * 27,
    ["", "-", "-", "-"] + [""] * 27,
]

binary = encode(Rung(logical_rows=2, conditions=conds, instructions=["NOP", "NOP"], comment=None))
```

## Condition-Side Instructions

The most convenient public helpers are the instruction token parsers:

```python
from laddercodec import CompareContact, Contact

Contact.from_csv_token("X001")
Contact.from_csv_token("~X001")
Contact.from_csv_token("rise(X001)")
Contact.from_csv_token("fall(X001)")
Contact.from_csv_token("immediate(X001)")

CompareContact.from_csv_token("DS1==DS2")
```

You can also construct comparison contacts directly:

```python
from laddercodec import CompareContact

compare = CompareContact(op=">=", left="DS1", right="100")
```

## AF-Side Instructions

Coils have a CSV-token helper as well:

```python
from laddercodec import Coil

Coil.from_csv_token("out(Y001)")
Coil.from_csv_token("latch(Y001)")
Coil.from_csv_token("reset(Y001)")
Coil.from_csv_token("out(immediate(Y001))")
Coil.from_csv_token("out(C1..C8)")
```

Timers are typically easiest to build directly:

```python
from laddercodec import Contact, Rung, Timer, encode

rung = Rung(
    logical_rows=2,
    conditions=[
        [Contact.from_csv_token("X001")] + [""] * 30,
        [""] * 31,
    ],
    instructions=[
        Timer(
            timer_type="on_delay",
            done_bit="T1",
            current="TD1",
            setpoint="1000",
            unit="Tms",
        ),
        "",
    ],
    comment=None,
)

binary = encode(rung)
```

Tall instructions such as timers, copy-family instructions, shift, drum, and
some counters occupy multiple visual rows. `encode()` accepts the fully expanded
rows directly. When you come from canonical CSV, `read_csv()` handles the
padding and pin-row shaping for you.

## Comments

Comments are plain text with optional markdown-style inline formatting:

```python
rung.comment = "Motor start circuit"
rung.comment = "**Bold** and _italic_ and __underlined__"
rung.comment = "Line one\nLine two"
```

The comment body limit is 1400 bytes after RTF encoding. For multi-row rungs
the practical limit can be lower; see
[binary format](../internals/binary-format.md#comment-sizing).

## Multi-Rung Encoding

Pass a list of `Rung` objects to `encode()`:

```python
from laddercodec import Rung, encode

rungs = [
    Rung(logical_rows=1, conditions=[[""] * 31], instructions=["NOP"], comment=None),
    Rung(logical_rows=1, conditions=[[""] * 31], instructions=["NOP"], comment="Second rung"),
]

binary = encode(rungs)
```

## Supported Instructions

All standard Click instruction families are supported from the root package:

- Condition side: `Contact`, `CompareContact`
- AF side: `Coil`, `Timer`, `Counter`, `Copy`, `BlockCopy`, `Fill`, `Pack`, `Unpack`, `Math`, `Shift`, `Search`, `Drum`, `Call`, `Return`, `End`, `ForLoop`, `Next`, `Send`, `Receive`

Unknown AF blobs can still be preserved via `RawInstruction`, which keeps the
binary payload intact for lossless round-trip.
