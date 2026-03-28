# Encoding

`encode()` takes a `Rung` object (or a list of them) and produces a Click clipboard binary.

## Single rung

Every rung has four components:

```python
from laddercodec import encode, Rung

rung = Rung(
    logical_rows=1,       # int: 1..32
    conditions=[[""] * 31],  # list of lists: one row of 31 condition tokens each
    instructions=["NOP"], # list: one AF token per row
    comment=None,         # str | None: plain text, optional markdown formatting
)
binary = encode(rung)
```

### Wires

Condition columns accept four wire tokens as strings:

| Token | Meaning |
|---|---|
| `-` | Horizontal wire |
| `\|` | Vertical down |
| `T` | Branch junction (right + down) |
| `""` | Blank (no wire) |

```python
# Two-row rung with a branch
from laddercodec import encode, Rung

conds = [
    ["-", "T", "-", "-"] + [""] * 27,   # Row 0: wire into T, continue right
    ["",  "-", "-", "-"] + [""] * 27,    # Row 1: branch continues right
]
binary = encode(Rung(2, conds, ["NOP", "NOP"], None))
```

### Contacts and coils

Place instruction objects directly in the grid.

```python
from laddercodec import encode, Rung, Contact, Coil

conds = [[Contact("X001"), "-", Contact("X002", nc=True)] + [""] * 28]
binary = encode(Rung(1, conds, [Coil("Y001")], None))
```

Contact variants:

- `Contact("X001")` — normally open
- `Contact("X001", nc=True)` — normally closed
- `Contact("X001", edge="rise")` — rising edge
- `Contact("X001", edge="fall")` — falling edge
- `Contact("X001", immediate=True)` — immediate NO

Coil variants:

- `Coil("Y001")` — output
- `Coil("Y001", latch=True)` — latch
- `Coil("Y001", reset=True)` — reset
- `Coil("Y001", immediate=True)` — immediate output
- `Coil("C1", range_end="C8")` — range output

### Comparison contacts

```python
from laddercodec import encode, Rung, CompareContact, Coil

conds = [[CompareContact("DS1", "==", "DS2")] + [""] * 30]
binary = encode(Rung(1, conds, [Coil("Y001")], None))
```

Operators: `==`, `!=`, `>`, `<`, `>=`, `<=`

### Timers

```python
from laddercodec import encode, Rung, Contact, Timer

conds = [[Contact("X001")] + [""] * 30]
binary = encode(Rung(1, conds, [Timer("on_delay", "T1", "TD1", "1000", "Tms")], None))
```

Timer modes: `on_delay`, `off_delay`

Timer units: `Tms` (10ms), `Ts` (seconds), `Tm` (minutes), `Th` (hours), `Td` (days)

Timers occupy 2 grid rows. If you provide only 1 row, the encoder auto-pads with a blank continuation row.

### Comments

Plain text with optional markdown-style formatting:

```python
binary = encode(Rung(1, conds, afs, "Motor start circuit"))
binary = encode(Rung(1, conds, afs, "**Bold** and _italic_ and __underlined__"))
binary = encode(Rung(1, conds, afs, "Line one\nLine two"))
```

Max comment body size is 1400 bytes. For multi-row rungs the practical limit may be lower — see [binary format](../internals/binary-format.md#comment-sizing).

### NOP

A rung with no AF instruction uses the string `"NOP"`:

```python
binary = encode(Rung(1, conds, ["NOP"], None))
```

At most one NOP per rung.

## Multi-rung encoding

Pass a list of `Rung` objects to `encode()` to combine multiple rungs into a single clipboard buffer:

```python
from laddercodec import encode, Rung

rungs = [
    Rung(1, [[""] * 31], ["NOP"], None),
    Rung(1, [[""] * 31], ["NOP"], "Second rung"),
]
binary = encode(rungs)
```

## Known limitations

Not yet implemented:

- Counters, math blocks, shift registers, drum sequencers
- Copy/move/fill instructions
- Full AF instruction set beyond coils and timers
- Instruction cell encoding is limited to contacts, comparison contacts, coils, and timers
