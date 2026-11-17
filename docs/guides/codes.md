<!-- Written by docs/gen_codes.py from laddercodec.Code; edit codes.py, not this page. -->

# Error codes

Every refusal and every `check()` finding names its rule in `code`.
The tables below list every code.

```python
from laddercodec import Coil, FieldError

try:
    Coil("X001")
except FieldError as error:
    print(error.code, error.click_id, error.field)
    # bank-not-allowed OBJ-004 Coil.operand
```

`code` is a `Code`, a string enum. Each code compares equal to its name, so
`error.code == "bank-not-allowed"` is true, and `Code.BANK_NOT_ALLOWED` is the same code.
A `FieldError` lists every refusal of one construction in `errors`, and each refusal has
its own `code`. A `Finding` from `check()` also has a `code`.

`click_id` is CLICK's own id for the error, such as `OBJ-004` or `C0202`. It is `None`
when CLICK has no id for the error or when no id is known. One code can come with several
ids, and the tables list the ids that are known. A `blank-field` refusal has the id of the
check that refused the blank.

## Operand rules

These rules are the same in every instruction. `field` names the field.

| Code | Meaning | CLICK id |
|---|---|---|
| `blank-field` | A field that needs a value is blank. |  |
| `not-an-address` | Text that is no CLICK address, or names no bank. |  |
| `address-out-of-range` | A number outside its bank (`DS5000`, `X017`). | OBJ-003 |
| `bank-not-allowed` | An address in a bank the field doesn't take. | OBJ-003, OBJ-004 |
| `upper-byte-not-allowed` | `XD0u` or `YD0u` in a field that takes no upper byte. |  |
| `not-click-form` | A stored value in a form that CLICK never writes. It is an address, a Math keypad name or a Math hex constant that is not in display form (`x1`, `sqrt`), or a numeric tag that holds no number. A decoder keeps such a blob raw. |  |
| `not-writable` | An address the instruction can't write: a read-only SC bit, an SD outside the writable list, or a Send to a read-only Modbus type. | OBJ-003, OBJ-004, OBJ-018 |
| `pointer-outside-copy` | A pointer in any field but a single Copy's source or destination. |  |
| `pointer-bank-not-allowed` | A pointer to a bank the field's pointer can't address. | OBJ-004 |
| `pointer-not-ds` | A pointer whose index is no DS address. |  |
| `constant-kind-not-allowed` | A constant of a kind the field doesn't take, or a Python value of the wrong type, such as `2.5` for a Send or Receive `quantity`. |  |
| `not-a-constant` | Text read as neither an address nor a constant. |  |
| `constant-out-of-range` | A constant outside the field's limits (its value, hex digits, float32, text length or typed length), or a minus sign where the field's lowest value is 0 or more. | OBJ-005 |
| `invalid-constant` | A constant in a form the field refuses: a `+` where no sign is taken, a sign before hex, a space in a count, or a real with more significant digits than CLICK keeps. | OBJ-005 |
| `invalid-char-code` | A `$hh` or a termination code that is no character code. | OBJ-036 |
| `invalid-text-constant` | Quoted text holding a quote or a character CLICK doesn't keep. |  |
| `not-a-flag` | A flag that is not True, False, 1 or 0. |  |
| `invalid-choice` | Not one of the field's named values: a unit, type, op, format, kind, port, function code, stop or pattern cell. |  |

## Shared rules

These rules apply to several instructions.

| Code | Meaning | CLICK id |
|---|---|---|
| `option-not-offered` | A field or option CLICK's dialog greys out for the other fields' values. |  |
| `range-mixed-banks` | A range whose two ends are in two banks. | OBJ-008 |
| `range-not-ascending` | A range that ends at or before its start. | OBJ-009, OBJ-012 |
| `range-crosses-slot` | An X or Y range that crosses a 16-point slot. | OBJ-033, OBJ-1009 |
| `duplicate-address` | Two fields that must differ name one address. | OBJ-012, OBJ-014 |
| `timer-pair-mismatch` | A timer's or counter's done bit and accumulator with different numbers, such as `T1` with `TD2`. |  |
| `immediate-contact-not-x` | An immediate contact outside X. |  |
| `immediate-coil-not-y` | An immediate coil outside Y. |  |
| `immediate-edge-contact` | Immediate on a rise or fall contact. |  |
| `immediate-not-allowed` | Immediate on an instruction with no immediate form. |  |
| `text-order-compare` | `<` or `>` on text, in a Compare or a Search. |  |
| `invalid-subroutine-name` | A subroutine name over 24 characters, with a forbidden character, or a device name. | GUI-040 |
| `invalid-input-rows` | `pin_rows` that is not one ascending row (1 to 255) per box input. |  |

## Copy family

Copy, Block Copy, Fill, Pack and Unpack.

| Code | Meaning | CLICK id |
|---|---|---|
| `copy-bank-incompatible` | A source bank or kind that can't copy into this destination bank. | OBJ-004, OBJ-024 |
| `constant-into-bit` | A single Copy of a constant into a bit address. | OBJ-004, OBJ-024 |
| `copy-converter-bank` | A converter the source and destination kinds don't offer. |  |
| `copy-txt-needs-convert` | A single Copy between TXT and a number, or a Block Copy from TXT into numbers, with no converter. |  |
| `copy-hex-reads-as-real` | A Copy source `EH` or `1EH`. CLICK reads either one as a real. |  |
| `text-past-bank` | Text a Copy writes that runs past TXT1000. | OBJ-003 |
| `block-copy-end-mismatch` | A Block Copy `dest_end` that is not where the copy ends. |  |
| `pack-kind-mismatch` | A Pack or Unpack kind (bits, words or text) that doesn't match the bank. |  |
| `pack-too-many` | A Pack source or Unpack destination past its count limit. | OBJ-003, OBJ-027, OBJ-032, OBJ-039, OBJ-040, OBJ-041, OBJ-042 |

## Math

These rules apply to the formula of a Math instruction.

| Code | Meaning | CLICK id |
|---|---|---|
| `math-nickname` | A formula that holds a `<nickname>`. |  |
| `math-invalid-token` | A word or character that is no formula part. | OBJ-1001 |
| `math-constant-kind` | A hex constant in a decimal Math, a constant without an `h` in a hex Math, or a text constant in any Math. | OBJ-1001 |
| `math-constant-out-of-range` | Hex over 4 digits, a real past float32 or with more significant digits than CLICK keeps, an integer past int32, or leading zeros. | OBJ-1009 |
| `math-nesting-depth` | Parentheses more than 8 deep. | OBJ-1010 |
| `math-unbalanced-parens` | A `)` with no `(`, or a `(` with no `)`. | OBJ-1004, OBJ-1005 |
| `math-function-mode` | A function, an operator or `PI` that only the other mode's keypad has, such as `SIN` in a hex Math or `XOR` in a decimal Math. | OBJ-1006 |
| `math-syntax-error` | A formula with tokens out of order, a comma outside a call, `:` outside a range function, or a wrong first or last token. | OBJ-1001, OBJ-037 |
| `math-arg-expression` | A function argument that is not one address or constant. | OBJ-1001 |
| `random-bound-type` | A RAND bound that is a real, or in a bank RAND doesn't take. | OBJ-1001, OBJ-1002 |
| `random-equal-bounds` | RAND with equal bounds. | OBJ-1001 |
| `math-operand-bank` | An address outside a `SUM` range, in a bank that the Math mode doesn't take. A decimal Math takes bit addresses only in a `SUM` range. | OBJ-1002 |
| `sum-bank-unavailable` | SUM over a bank SUM doesn't read. | OBJ-1002 |
| `math-range-mixed-banks` | An `a : b` range in two banks. | OBJ-1015 |
| `math-range-not-ascending` | An `a : b` range that runs high to low. | OBJ-1014 |
| `median-range-too-large` | MDN over more than 1024 bytes. | OBJ-1013 |
| `sum-option-slot` | An X or Y SUM range with an end in the option slot. |  |
| `math-formula-too-long` | A formula longer than 270 characters in the internal form that CLICK stores. | OBJ-1008 |

## Other instructions

Compare, Search, Out variants, Drum, Send and Receive, For, and laddercodec's own types.

| Code | Meaning | CLICK id |
|---|---|---|
| `compare-mixed-types` | Compare operands in different groups (hex, numeric, text). |  |
| `search-value-bank` | A Search constant whose kind doesn't search the table's bank. |  |
| `coil-time-unit` | An Out variant with a time unit its kind lacks. |  |
| `debounce-needs-phase` | A debounce with neither phase filled. | OBJ-006 |
| `drum-size-out-of-range` | Drum steps or outputs outside 1 to 16. |  |
| `drum-pattern-shape` | A drum pattern or event list that doesn't match its steps and outputs. |  |
| `drum-step-empty` | A drum step with no event or duration. | OBJ-021, OBJ-022, OBJ-1019 |
| `function-code-mismatch` | A Modbus function code that doesn't fit the remote type or the count. | OBJ-004 |
| `count-out-of-range` | A Send or Receive count past its cap or room, or an odd TXT count. | OBJ-010, OBJ-029 |
| `remote-address-out-of-range` | A remote start outside the MODBUS 984 ranges, or past FFFDh. | OBJ-010 |
| `invalid-modbus-target` | A Modbus target with a bad device_id, IP or port. |  |
| `for-count-bank` | A For loop count in a bank the count doesn't take. | OBJ-004 |
| `invalid-token` | A CSV token that doesn't follow its instruction's syntax. |  |
| `invalid-raw` | A `RawInstruction` field with a value of the wrong type or out of range, or a `raw(...)` token whose `rows=` does not fit its `pins=`. |  |
| `invalid-undecoded` | An `Undecoded` field refused. |  |

## check() findings

`check()` reports these.

| Code | Meaning | CLICK id |
|---|---|---|
| `not-series-parallel` | A circuit that is not series-parallel. | C0001 |
| `no-rail` | A contact whose input no rail reaches. | C0202 |
| `feeds-no-box` | A contact that feeds no box. | C0202 |
| `no-coil` | A path from the rail that reaches no box. | C0003 |
| `contact-feeds-only-nop` | A contact that feeds a NOP and no other box. | C0003 |
| `unwired-input` | A box input (a Reset input, a Down input, ...) that no rail or contact reaches. | C0202 |
| `output-above-box-inputs` | A box whose main input is on the same net as the main input of a lower box that uses an input row, such as a `.reset()` row. The rail reaches that net through a contact. | C000A |
| `shared-input-net` | A box input whose net another input shares. | C000A |
| `input-without-contact` | A box input with no contact of its own. | C0205, C0212 |
| `input-shares-enable` | A box input whose circuit shares contacts with an enable. |  |
| `inputs-share-contacts` | A box input whose circuit shares contacts with another box input. |  |
| `unpowered-box` | A box that no rail or contact reaches. | C0202 |
| `shorted-contact` | A wire that joins a contact's two sides. | C0002 |
| `undecoded-rung` | A rung that holds an `Undecoded` marker. The marker stands in for a rung that a decoder could not decode or that `write_csv` could not write. |  |

## Layout only

These codes come only from laying a rung out. `check()` never reports them. If `write_csv` can't lay a rung out without changing its circuit, it raises a `WriterError`, and the `__cause__` of that error has one of these codes.

| Code | Meaning | CLICK id |
|---|---|---|
| `layout-too-wide` | A layout that needs more than 31 condition columns. |  |
| `layout-nop-split` | A rung that holds a NOP and that CLICK would split into several rungs. laddercodec does not know how CLICK splits such a rung. |  |
| `layout-cannot-draw` | Nets that collide, cells that overlap, a contact that can't take a down wire, or a contact drawn twice. |  |
