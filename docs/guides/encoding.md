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
        [Contact("X001"), "-", Contact("X002", kind="nc")] + [""] * 28,
    ],
    instructions=[Coil("Y001")],
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

`Contact` takes an operand, then an optional `kind`: `"no"` (the default), `"nc"`,
`"rise"` or `"fall"`. The comment on each line below is its CSV token:

```python
from laddercodec import CompareContact, Contact

Contact("X001")                                # X001
Contact("X001", kind="nc")                     # ~X001
Contact("X001", kind="rise")                   # rise(X001)
Contact("X001", kind="fall")                   # fall(X001)
Contact("X001", immediate=True)                # X001.immediate
Contact("X001", kind="nc", immediate=True)     # ~X001.immediate

CompareContact(op=">=", left="DS1", right="100")  # DS1>=100
```

Only an NO or NC contact on X has an immediate form. If you ask for an immediate
form of an edge contact, or of a contact on another bank, `Contact` raises
`FieldError`.

## AF-Side Instructions

`Coil` takes an operand, then an optional `kind`: `"out"` (the default), `"latch"`
or `"reset"`. These are the names of its CSV calls:

```python
from laddercodec import Coil

Coil("Y001")                                   # out(Y001)
Coil("Y001", kind="latch")                     # latch(Y001)
Coil("Y001", kind="reset")                     # reset(Y001)
Coil("Y001", immediate=True)                   # out(immediate(Y001))
Coil("C1", range_end="C8")                     # out(C1..C8)
Coil("C1", oneshot=True)                       # out(C1,oneshot=1)
```

Each instruction's `to_csv()` writes its CSV token, and `from_csv_token()` reads
one back.

Timers are typically easiest to build directly:

```python
from laddercodec import Contact, Rung, Timer, encode

rung = Rung(
    logical_rows=2,
    conditions=[
        [Contact("X001")] + [""] * 30,
        [""] * 31,
    ],
    instructions=[
        Timer(
            kind="on_delay",
            done="T1",
            accumulator="TD1",
            preset="1000",
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
`read_csv()` handles the padding and pin rows for you. It also lays each rung out
as CLICK's syntax check draws it ([CSV layout](csv-format.md#layout)).

## Text Constants

Text constants are written with their double quotes (`Copy(source='"Q"', ...)`,
`CompareContact("==", "TXT1", '"T"')`), and an ASCII-code constant as `$hh`
(`"$00"`). CLICK writes one TXT register per character of a text constant, so an
empty `""` writes nothing.

`Copy` and `Fill` take 1 to 128 characters in quotes. They raise `FieldError` for
`""`, for a longer text and for a quote inside the text.

- `Fill` takes printable ASCII.
- `Copy` takes any character from U+0001 to U+FFFF except a surrogate (`"é"`,
  `"€"`, a tab). CLICK keeps these as typed. `Copy` refuses NUL and a character
  above U+FFFF.
- `Search` takes the characters that `Copy` takes.
- `CompareContact` takes 1 to 128 printable ASCII characters in quotes.

`Search` and `CompareContact` match consecutive TXT registers (`"AB"`). They raise
`FieldError` for `""`, for a longer text and for a quote inside the text.
`CompareContact` also raises it for non-ASCII text.

Each check runs when you build the instruction and when you read it from CSV. A
quoted `"$41"` is text. Use `$00` for the blank (NUL) character.

## Refused Values

```python
from laddercodec import FieldError, Timer

try:
    Timer(kind="on_delay", done="C1", accumulator="TD1", preset="40000", unit="Tms")
except FieldError as exc:
    for error in exc.errors:
        print(error.field, error.reason, error.click_id)
# Timer.done bank None
# Timer.preset range OBJ-005
```

If you build an instruction with a value that CLICK's dialog refuses, it raises
`FieldError`, or `AddressError` for an address. `errors` holds every refusal of
that instruction, with the raised one first.

These report every field they refuse: `Timer`, `Coil`, `Contact`, `CompareContact`,
`OutVariant`, `Counter`, `Shift`, `Call`, `ForLoop`, `Drum`, `Search`, `Copy`,
`BlockCopy`, `Fill`, `Pack`, `Unpack`, `Math`, `Send`, `Receive`, the Modbus targets
and address, `RawInstruction` and `Undecoded`. The other instructions report the
first refusal only.

A Math formula gives one refusal for each address, constant, key or range it
refuses, each on `Math.expression`. An error in its parentheses or in the order of
its tokens ends the list. After a word that is none of an address, a name or a
constant, the order, bit and range checks are skipped.

If a target is refused when you build it, the refusal names the target's own field
(`ModbusTcpTarget.port`). That happens before any `Send` or `Receive` holds the
target. `Receive` makes one check of its target: it refuses a serial Slave ID of 0,
because Slave IDs start at 1. That refusal names `Receive.target`. Each refusal
has these attributes:

| Attribute  | Holds                                                                                  |
|------------|----------------------------------------------------------------------------------------|
| `field`    | the field refused, `Class.attr`, or `Class.attr[i]` for an item of a list              |
| `fields`   | `(field,)`, or both fields for a refused pair (`Timer.accumulator`, `Timer.done`)       |
| `reason`   | a `Reason`, listed below                                                               |
| `click_id` | CLICK's id for the error where it has one (`OBJ-005`), or `None`                       |
| `obj`      | the instruction being built                                                            |

`reason` is one of `address`, `bank`, `range`, `pointer`, `kind`, `form`,
`not_writable`, `flag`, `choice`, `conflict` and `missing` (each is described under
`Reason` in the [Codec API](../reference/api/codec.md)), or `None` for a refusal not
given one yet. A blank in a field that requires a value is `missing`, whatever
the field takes. A field that may be blank accepts a blank, and that is no refusal.

A field that depends on a refused one is not checked. For example, if a Timer's
done is refused, the Timer is not checked for an accumulator that matches it.

A decoded instruction can hold a refused value, with a `RefusedFieldWarning`
([Decoding](decoding.md#values-clicks-dialog-refuses)). If you encode it
unchanged, you get the bytes it was decoded from. If you change it, it is checked
again, and `encode()` raises the `FieldError` that building it raises. If you read
it from CSV, it has no bytes to write, and `encode()` raises that error.

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

`encode()` raises `EncodeError` for a rung that holds an `Undecoded` marker. The
marker stands in for a rung that laddercodec could not decode, and CLICK has no
instruction for it ([Decoding](decoding.md#rungs-that-dont-decode)).

## If a paste fails

If CLICK crashes on a paste or draws the rung wrong, open an issue at
[github.com/ssweber/laddercodec/issues](https://github.com/ssweber/laddercodec/issues)
with the CSV or Python that built the rung, the `.bin` you pasted, your CLICK
version, and what CLICK showed.
