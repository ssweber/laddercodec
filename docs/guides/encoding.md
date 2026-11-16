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

Every `Rung` has five fields:

| Field | Type | Notes |
|---|---|---|
| `logical_rows` | `int` | `1..32` |
| `conditions` | `list[list[object]]` | One row per logical row, exactly 31 condition columns each |
| `instructions` | `list[object]` | One AF token per logical row |
| `comment` | `str \| None` | Optional plain text with lightweight markdown styling |
| `comment_rtf` | `bytes \| None` | Raw RTF payload from a decode; leave it `None` when you build a rung |

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

binary = encode(Rung(logical_rows=2, conditions=conds, instructions=["NOP", ""], comment=None))
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
rows directly and writes them as given. When you come from canonical CSV,
`read_csv()` handles the padding and pin rows for you, and lays each rung out as
CLICK's syntax check draws it ([CSV layout](csv-format.md#layout)).

## Text Constants

Text constants are written with their double quotes (`Copy(source='"Q"', ...)`,
`CompareContact("==", "TXT1", '"T"')`), and an ASCII-code constant as `$hh`
(`"$00"`). CLICK writes one TXT register per character of a text constant, so an
empty `""` writes nothing. `Copy` and `Fill` take 1 to 128 characters in quotes
and raise `FieldError` for `""`, a longer text and a quote inside the text.
`CompareContact` and `Search` take 1 to 128 printable ASCII characters in quotes
(`"AB"` matches consecutive TXT registers) and raise `FieldError` for `""`, a
longer or non-ASCII text and a quote inside the text. Each refuses when built or
read from CSV. A quoted `"$41"` is text. Use `$00` for the blank (NUL) character.

## Refused Values

```python
from laddercodec import FieldError, Timer

try:
    Timer(timer_type="on_delay", done_bit="C1", current="TD1", setpoint="40000", unit="Tms")
except FieldError as exc:
    for error in exc.errors:
        print(error.field, error.reason, error.click_id)
# Timer.done_bit bank None
# Timer.setpoint range OBJ-005
```

A value CLICK's dialog refuses raises `FieldError` (`AddressError` for an
address) when the instruction is built. `errors` holds every refusal of that
instruction, the raised one first. `Timer`, `Coil`, `Contact`, `CompareContact`,
`OutVariant`, `Counter`, `Shift`, `Call`, `ForLoop`, `Drum`, `Search`, `Copy`,
`BlockCopy`, `Fill`, `Pack`, `Unpack`, `Math`, `Send`, `Receive`, the Modbus targets and address,
`RawInstruction` and `Undecoded` report every field they refuse;
the other instructions report the first. A Math formula gives one refusal for each
address, constant, key or range it refuses, each on `Math.expression`; an error in
its parentheses or in the order of its tokens ends the list. After a word that is
none of an address, a name or a constant, the order, bit and range checks are
skipped. A target refused when it is built names its own field (`ModbusTcpTarget.port`)
before any `Send` or `Receive` holds it. The one check a `Receive` makes of its target, a serial Slave ID of 0
(it starts at 1), names `Receive.target`. Each refusal has:

| Attribute  | Holds                                                                                  |
|------------|----------------------------------------------------------------------------------------|
| `field`    | the field refused, `Class.attr`, or `Class.attr[i]` for an item of a list              |
| `fields`   | `(field,)`, or both fields for a refused pair (`Timer.current`, `Timer.done_bit`)       |
| `reason`   | a `Reason`, listed below                                                               |
| `click_id` | CLICK's id for the error where it has one (`OBJ-005`), or `None`                       |
| `obj`      | the instruction being built                                                            |

`reason` is one of `address`, `bank`, `range`, `pointer`, `kind`, `form`,
`not_writable`, `flag`, `choice`, `conflict` and `missing` (each is described under
`Reason` in the [Codec API](../reference/api/codec.md)), or `None` for a refusal not
given one yet. A blank in a field that requires a value is `missing`, whatever
the field takes; a field that may be blank is accepted, and its blank is no refusal. A field that depends on a refused one is not checked:
a Timer whose done bit is refused is not checked for a current value that
matches it.

A decoded instruction can hold a refused value, with a `RefusedFieldWarning`
([Decoding](decoding.md#values-clicks-dialog-refuses)). Unchanged, it encodes as
the bytes it was decoded from; changed, it is checked again, and `encode()` raises
the `FieldError` building it raises. Read from CSV, it has no bytes to write, and
`encode()` raises that error.

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

## Nickname Display

Click can show project-level tag names (nicknames) instead of raw addresses
in math instruction blocks. Pass `show_nicknames=True` to `encode()`:

```python
binary = encode(rungs, show_nicknames=True)
```

This sets the nickname display flag on every math instruction in the buffer.
Click resolves the actual tag names from its own project nickname table — the
codec doesn't need to know the mappings.

The nicknames must already be loaded in the Click project before pasting.
If a referenced address has no nickname, Click falls back to showing the
raw address for that operand.

## Supported Instructions

All standard Click instruction families are supported from the root package:

- Condition side: `Contact`, `CompareContact`
- AF side: `Coil`, `OutVariant`, `Timer`, `Counter`, `Copy`, `BlockCopy`, `Fill`, `Pack`, `Unpack`, `Math`, `Shift`, `Search`, `Drum`, `Call`, `Return`, `End`, `ForLoop`, `Next`, `Break`, `Continue`, `Send`, `Receive`

Unknown AF blobs can still be preserved via `RawInstruction`, which keeps the
binary payload intact for lossless round-trip.

`encode()` raises `ValueError` for a rung that holds an `Undecoded` marker: the
marker stands in for a rung laddercodec could not decode, and CLICK has no
instruction for it ([Decoding](decoding.md#rungs-that-dont-decode)).

## If a paste fails

If CLICK crashes on a paste or draws the rung wrong, open an issue at
[github.com/ssweber/laddercodec/issues](https://github.com/ssweber/laddercodec/issues)
with the CSV or Python that built the rung, the `.bin` you pasted, your CLICK
version, and what CLICK showed.
