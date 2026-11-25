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
    conditions=[
        [Contact("X001"), "-", Contact("X002", kind="nc")] + [""] * 28,
    ],
    instructions=[Coil("Y001")],
    comment="Motor start circuit",
)

binary = encode(rung)
```

Every `Rung` has four fields:

| Field | Type | Notes |
|---|---|---|
| `conditions` | `tuple[tuple[object, ...], ...]` | One row per logical row, 1..32 rows, exactly 31 condition columns each |
| `instructions` | `tuple[object, ...]` | One AF token per logical row |
| `comment` | `str \| None` | Optional plain text with lightweight markdown styling |
| `comment_rtf` | `bytes \| None` | Raw RTF payload from a decode; leave it `None` when you build a rung |

You can pass lists, and the rung stores them as tuples. `rung.logical_rows` is the
number of rows, `len(rung.conditions)`. A `Rung` is frozen and can be hashed. Two
rungs that differ only in `comment_rtf` are equal.

## Build A Rung From Its Circuit

```python
from laddercodec import Box, Branch, Circuit, Coil, Contact, Parallel, check, encode, lay_out

circuit = Circuit(
    Branch(
        conditions=(Contact("X001"), Parallel((Contact("X002"), Contact("C1")))),
        outputs=(
            Box(Coil("Y001")),
            Branch(conditions=(Contact("C2"),), outputs=(Box(Coil("Y002")),)),
        ),
    ),
    comment="Start the pump",
)

rungs = lay_out(circuit)
assert check(rungs) == []
binary = encode(rungs)
```

`lay_out()` returns the rungs as CLICK's syntax check draws them, so you don't place
any cell yourself. In CSV, these rungs are:

```text
#,Start the pump
R,X001,T:X002,T,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,out(Y001)
,,C1,C2,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,out(Y002)
```

A circuit has no rows or columns. It is built from these parts:

| Part | Holds |
|---|---|
| `Series(terms)` | terms in series, from left to right |
| `Parallel(legs)` | two or more legs, drawn from the top down in the order given |
| `Box(instruction, pins=())` | an `Instruction` or `"NOP"`, and the term that feeds each pin it uses |
| `Branch(conditions=(), outputs=())` | conditions in series, then the boxes and branches that hang off their end |
| `Circuit(branch, comment=None)` | the branch from the rail, and the rung's comment |

A term is a `Contact`, a `CompareContact`, a `Series` or a `Parallel`. `Term` is a type
alias for these four classes. Use it in your type hints. The parts
are frozen and can be hashed. A part that a class doesn't take raises `FieldError`
with the code `invalid-circuit`.

A pinned box takes the term for each pin by the pin's name, such as
`Box(timer, {".reset": Contact("X002")})` for a retentive `Timer`. `lay_out()` puts
each pin on the row that CLICK gives it.

If outputs meet only at the rail, CLICK makes one rung of each. `lay_out()` does the
same and puts the comment on the first rung. So `len(lay_out(circuit))` is the
number of CLICK rungs.

An empty `Series(())` is a wire. You can use it only as a leg of a `Parallel`, as
in `Parallel((Contact("X001"), Series(())))`. CLICK holds such a leg, and its
syntax check refuses it. `lay_out()` draws this shape and other shapes that only
the syntax check refuses. To find them, call `check()` on the rungs.

`lay_out()` raises `LayoutError` for a circuit that CLICK can't hold, such as one
that needs more than 32 rows or more than the 31 condition columns. The error's
`code` says which. The rules of the drawing are in
[CSV layout](csv-format.md#layout).

`lay_out()` also raises `LayoutError` with `click_id` `C000A` for an output that
comes before or after a box whose pin is used, such as a retentive `Timer` with a
`.reset` term, when the output hangs off that box's input circuit. CLICK doesn't
allow an output there. Put the output in a `Circuit` of its own.

## Wire Tokens

Condition columns accept four wire tokens as strings:

| Token | Meaning |
|---|---|
| `"-"` | Horizontal wire |
| `"|"` | Vertical down |
| `"T"` | Branch junction (right + down) |
| `""` | Blank cell |

```python
from laddercodec import Contact, Rung, Tee, encode

conds = [
    ["-", "T", Tee(Contact("X001")), "-"] + [""] * 27,
    ["", "-", "-", "-"] + [""] * 27,
]

binary = encode(Rung(conditions=conds, instructions=["NOP", ""], comment=None))
```

A contact can have a wire down from its cell's left edge, as `"T"` does. Wrap the
contact in a `Tee`, such as `Tee(Contact("X001"))`. Its CSV token is `T:X001`.

Column A and the rung's last row can't hold a `Tee`, a `"T"` or a `"|"`. `encode()`
raises `EncodeError` for one there.

## Condition-Side Instructions

`Contact` takes an operand, then an optional `kind`: `"no"` (the default), `"nc"`,
`"rise"` or `"fall"`. The alias [`ContactKind`](../reference/api/instructions.md#laddercodec.ContactKind)
lists these values. The comment on each line below is its CSV token:

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
or `"reset"`. The alias [`CoilKind`](../reference/api/instructions.md#laddercodec.CoilKind)
lists these values. They are also the names of the coil's CSV calls:

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
`""` and for a longer text.

- `Fill` takes printable ASCII, and raises `FieldError` for a quote inside the text.
- `Copy` takes any character from U+0001 to U+FFFF except a surrogate (`"é"`,
  `"€"`, a tab). CLICK keeps these as typed. `Copy` refuses NUL and a character
  above U+FFFF.
- A quote inside a `Copy` text is one character of the text, so
  `Copy('"A"B"', "TXT1")` writes TXT1 to TXT3.
- `Search` takes the characters that `Copy` takes, a quote inside the text
  included. `Search("TXT1", "TXT10", '"A"B"', "DS30", "C1", "==")` searches for
  the three characters `A"B`.
- The right side of `CompareContact` takes the characters that `Copy` takes, a
  quote inside the text included.
- The left side of `CompareContact` takes printable ASCII, a quote inside the
  text included. `CompareContact("==", '"A"B"', "TXT1")` matches the three
  characters `A"B`.

`Search` and `CompareContact` match consecutive TXT registers (`"AB"`). They raise
`FieldError` for `""` and for a longer text.

Each check runs when you build the instruction and when you read it from CSV. A
quoted `"$41"` is text. Use `$00` for the blank (NUL) character.

## Refused Values

```python
from laddercodec import FieldError, Timer

try:
    Timer(kind="on_delay", done="C1", accumulator="TD1", preset="40000", unit="Tms")
except FieldError as exc:
    for error in exc.errors:
        print(error.field, error.code, error.click_id)
# Timer.done bank-not-allowed None
# Timer.preset constant-out-of-range OBJ-005
```

If you build an instruction with a value that CLICK's dialog refuses, it raises
`FieldError`, or `AddressError` for an address. `errors` holds every refusal of
that instruction, with the raised one first.

These report every field they refuse: `Timer`, `Coil`, `Contact`, `CompareContact`,
`OutVariant`, `Counter`, `Shift`, `Call`, `ForLoop`, `Drum`, `Search`, `Copy`,
`BlockCopy`, `Fill`, `Pack`, `Unpack`, `Math`, `Send`, `Receive`, the Modbus targets
and address, `RawInstruction` and `Undecoded`. The other instructions report the
first refusal only.

A Math formula gives one refusal for each address, constant, key or range that it
refuses, each on `Math.expression`. A key here is a keypad key that the mode does
not take. Three things cut the list short:

- An error in the formula's parentheses ends the list.
- An error in the order of its tokens ends the list.
- If the formula holds a word that is none of an address, a name or a constant, the
  order, bit and range checks are skipped.

If a target is refused when you build it, the refusal names the target's own field
(`ModbusTcpTarget.port`). That happens before any `Send` or `Receive` holds the
target. `Receive` makes one check of its target: it refuses a serial Slave ID of 0,
because Slave IDs start at 1. That refusal names `Receive.target`. Each refusal
has these attributes:

| Attribute  | Holds                                                                                  |
|------------|----------------------------------------------------------------------------------------|
| `field`    | the field refused, `Class.attr`, or `Class.attr[i]` for an item of a list              |
| `fields`   | `(field,)`, or both fields for a refused pair (`Timer.accumulator`, `Timer.done`)       |
| `code`     | the rule refused, a `Code` (see [Error codes](codes.md))                               |
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
unchanged, you get the blob that Decoding describes for it. If you change it with
`replace()`, the copy is checked again, and `replace()` raises the `FieldError` that
building it raises. If you read it from CSV, it has no bytes to write, and
`encode()` raises that error.

### Show Your Names In A Refusal

```python
from laddercodec import Copy, FieldError

names = {"C1": "Valve", "DS1": "Count"}
try:
    Copy(source="DS1", dest="C1")
except FieldError as exc:
    print(exc)
    print(exc.message(names))
    print(exc.short(names))
    print(exc.detail(names))
# Copy.dest: 'C1' can't take 'DS1'; a numeric register copies to DS, DD, DH, DF, YD, TD, CTD, SD, TXT (OBJ-024)
# Copy.dest: Valve (C1) can't take Count (DS1); a numeric register copies to DS, DD, DH, DF, YD, TD, CTD, SD, TXT (OBJ-024)
# Valve (C1) can't take Count (DS1)
# a numeric register copies to DS, DD, DH, DF, YD, TD, CTD, SD, TXT
```

`names` maps an address to your name for it. `message(names)` returns the text of
`str(exc)` with each named address replaced by its name. CLICK's form of the value
follows in parentheses. `short(names)` returns only the refused value and its rule.
`detail(names)` returns the explanation and what to write, as in
`Write an address, such as DS1.` It is empty when the refusal has neither.
A number constant is shown without quotes:
`Copy.source: 5000000000 is outside -2147483648 to 2147483647 (OBJ-005)`.

`short()` and `detail()` are for text that you show next to the field, so they do not
name the field. Where `str(exc)` says `Fill.value takes one character`, `detail()`
says `this field takes one character`.

A range or a pointer is shown in the same way:

| Value     | Names                              | Shown as                  |
|-----------|------------------------------------|---------------------------|
| `C1..C2`  | `{"C1": "Valve1", "C2": "Valve2"}` | `Valve1..Valve2 (C1..C2)` |
| `C1..C2`  | `{"C1": "Valve1"}`                 | `Valve1..C2 (C1..C2)`     |
| `DS[DD1]` | `{"DD1": "Ptr"}`                   | `DS[Ptr] (DS[DD1])`       |
| `x1`      | `{"X001": "Start"}`                | `Start (X001)`            |
| `X001`    | `{"X001": "X1"}`                   | `X1`                      |

When you pass names, a value that holds an address is shown without quotes. This
holds even if none of your keys is a CLICK address. The parentheses are left out
when the value as shown is CLICK's form. They are also left out when your name is
another form of the same address, such as `X1` for `X001`. A constant, a bank list
and a limit are never replaced. You can write a key in any form that CLICK reads,
such as `ds1` or `DS001`. A key that is not a CLICK address is ignored. With no
names, `message()` returns `str(exc)`. If `read_csv` raised the refusal, `message()`
keeps the CSV location at the end, and `short()` and `detail()` leave it out.

A `FieldError` from any instruction, Modbus target or `ModbusAddress` shows your
name for each address it names. When a `Math` refusal quotes the whole formula, names do not
replace the addresses in it. The refusals of `Call`, `Tee`, `RawInstruction`,
`Undecoded`, `Series`, `Parallel`, `Box`, `Branch` and `Circuit` name no address, so
names change nothing in them, and `short()` and `detail()` still split them. A
`CsvReadError` about the shape of a token shows no names. For example, `read_csv`
refuses `blockcopy(DS1,DS10..DS20)` with `'DS1' is not a range`, and `message()`
returns that text with no name in it. For an error that keeps no parts, `message()`
returns `str(exc)`.
`short()` returns that text without its `Class.field:` prefix, and `detail()`
returns an empty string.

## Change An Instruction

```python
from laddercodec import Timer, replace

timer = Timer(kind="on_delay", done="T1", accumulator="TD1", preset="100", unit="Tms")
slower = replace(timer, preset="500")
print(timer.preset, slower.preset)
# 100 500
```

An instruction is frozen. If you assign to a field, Python raises
`dataclasses.FrozenInstanceError`. To change an instruction, call `replace()` with
the new field values. It returns a copy and leaves the instruction you passed
unchanged.

A `Rung` is frozen too, and `replace()` works on it. To put the copy in a rung, call
`replace()` on the rung with its new `instructions`:

```python
rung = replace(rung, instructions=[slower, ""])
```

`replace()` checks the copy as if you built it new. A refused value raises the
`FieldError` that building the instruction raises. A name that is not a field
raises `TypeError`.

A decoded instruction can hold the blob that it was decoded from
([Decoding](decoding.md#values-clicks-dialog-refuses)). If every value that you
pass is equal to the field's current value, the copy has that blob and the same
refusals. A value that the constructor writes in another form is a change. For
example, `"ds1"` is a change to a field that holds `"DS1"`.

## Comments

Comments are plain text with optional markdown-style inline formatting:

```python
rung = replace(rung, comment="Motor start circuit")
rung = replace(rung, comment="**Bold** and _italic_ and __underlined__")
rung = replace(rung, comment="Line one\nLine two")
rung = replace(rung, comment=r"Pump_1_Run waits for \_init\_")
```

To write a `*` or `_` as text where it would otherwise start or end a style,
put a backslash before it. To write a backslash before `*`, `_` or another
backslash, write `\\`. The last comment above encodes as
`Pump_1_Run waits for _init_`, with no styling. See
[Comment styles and escapes](csv-format.md#comment-styles-and-escapes).

A comment can hold any Unicode text, such as `é`, `°`, `→`, `中` or an emoji.
`encode()` writes each character of the comment's RTF body in the form that
CLICK stores:

- An ASCII character is written as itself, in 1 byte. `\`, `{` and `}` take
  2 bytes each (`\\`, `\{`, `\}`), and a line break takes 5 (`\par `).
- A character in Windows code page 1252, such as `é`, `°` or `€`, is written
  as its byte in hex, such as `\'e9`. It takes 4 bytes.
- Any other character, such as `→` or `中`, is written as its code, such as
  `\u8594?`. It takes 6 to 8 bytes. A character above U+FFFF, such as an
  emoji, is written as two codes and takes 16 bytes.

The limit is 1400 bytes of the RTF body. The limit counts each character in
the form above. It also counts the group around each styled stretch, such as
`{\b ` and `}`. If a comment is longer, `encode()` raises `EncodeError`, and the
message says how many bytes to cut. For multi-row rungs
the practical limit can be lower; see
[binary format](../internals/binary-format.md#comment-sizing).

## Multi-Rung Encoding

Pass a list of `Rung` objects to `encode()`:

```python
from laddercodec import Rung, encode

rungs = [
    Rung(conditions=[[""] * 31], instructions=["NOP"], comment=None),
    Rung(conditions=[[""] * 31], instructions=["NOP"], comment="Second rung"),
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

## Add The Addresses Before You Paste

```python
from laddercodec import Contact, Copy, Rung, addresses, encode

rung = Rung([[Contact("X001")] + ["-"] * 30], [Copy('"HALLO"', "TXT1")], None)
binary = encode(rung)

addresses(binary)  # ['X001', 'TXT1', 'TXT5']
```

`addresses()` returns every address that the rungs store, and the ends that they imply.

When CLICK pastes rungs, it drops each operand whose address is not in the project's
address database, `SC_.mdb`. It keeps the operand if the address is there. Add each address
that `addresses()` returns to the project before you paste.

The list holds every address that the payload stores, whether or not the paste needs it. An
extra address costs you one row in `SC_.mdb`, and a missing one loses an operand. Each
address appears once, in display form and in the order that the payload first uses it. You
can pass a `Rung`, a list of rungs, or clipboard bytes from `encode()` or from CLICK.
`addresses()` returns the same list for a rung and for its encoded bytes.

The list holds these addresses too:

- the end that a Copy of text stores, such as TXT5 for `"HALLO"` into TXT1
- the end of a Send's source or a Receive's destination, such as DS5 for 5 registers from
  DS1
- a Send's or a Receive's remote start, which is an address in the other PLC
- a time drum's done bit, such as T4 for the accumulator TD4
- the index of a pointer, such as DS1 in `TXT[DS1]`
- each address in a Math formula
- the addresses in an Email's indexed arrays
- the addresses in a `RawInstruction` and in an `UnknownCondition`

For a range, CLICK needs only its two ends in the project. The list holds both ends of
each range, such as TXT1 and TXT10 for a Search of TXT1..TXT10. It leaves out the
addresses between them.

For a pointer, the list holds the index. A Copy of `DS[DS2]` into DS10 lists DS2 and DS10.
The address that the pointer reaches is known only when the PLC runs, so the list can't
hold it.

A time drum's done bit is the T address with the number of its accumulator. The list holds
it whether or not the drum's bytes store it.

The list leaves out text in quotes. A Copy of `"DS1"` into TXT1 lists TXT1 and TXT3, and no
DS1.

An Email's To, Cc and Bcc name an entry in the project's address book by its number. The
entry's name and address are not in the payload, so `addresses()` can't list them. Paste
into a project whose address book holds the same entries.

If `addresses()` can't read a row of the bytes, it issues an `UndecodedRungWarning` that
names the row. The list then lacks the addresses in that row and every row after it. If it
can't read the fields of a cell, it issues an `UndecodedRungWarning` that names the cell,
and the list lacks the addresses in that cell.

## If a paste fails

If CLICK crashes on a paste or draws the rung wrong, open an issue at
[github.com/ssweber/laddercodec/issues](https://github.com/ssweber/laddercodec/issues)
with the CSV or Python that built the rung, the `.bin` you pasted, your CLICK
version, and what CLICK showed.
