# Changelog

<!-- Entries follow the CHANGELOG rule in the bob plugin's `writing` skill: say what
     changed for the user and what they must do, in two or three short sentences.
     Breaking changes may be longer. State each entry against the last release. -->

## Unreleased

`decode()` and `decode_program()` no longer raise at a rung that they can't read. They return a marker for that rung and decode the rest. A stored value that CLICK's dialog refuses now decodes as the instruction, with a warning. You can now build a rung from its circuit with `lay_out()`, read and write a whole project as a folder of CSV files, and list the addresses that a CLICK project must hold before you paste. Each refusal and each `check()` finding names its rule in `code`, and CLICK's own id in `click_id` when CLICK has one. An error from `read_csv` names the cell. This release breaks the API. Classes, fields and exceptions are renamed, instructions are frozen, and the field checks refuse more values that CLICK refuses. Read Breaking changes before you upgrade.

### Breaking changes

- **`decode()` always returns a list.** It now returns a `list[Rung]` even when the clipboard holds one rung. v0.4.0 returned the `Rung` itself in that case.
  - Unpack a single rung with `[rung] = decode(data)`, and remove any `isinstance(result, list)` check.
- **`Contact` and `Coil` are built by kind, with the operand first.** `Contact(operand, kind="no", immediate=False)` accepts the kinds `"no"`, `"nc"`, `"rise"` and `"fall"`. `Coil(operand, kind="out", range_end=None, immediate=False, oneshot=False)` accepts `"out"`, `"latch"` and `"reset"`. v0.4.0 took an `InstructionType` as `type`, first, and `edge_kind` for an edge contact.
  - `Contact(InstructionType.CONTACT_NC, "X001")` → `Contact("X001", kind="nc")`
  - `Contact(InstructionType.CONTACT_EDGE, "X001", edge_kind="rise")` → `Contact("X001", kind="rise")`
  - `Coil(InstructionType.COIL_LATCH, "Y001")` → `Coil("Y001", kind="latch")`
  - Pass `immediate`, `range_end` and `oneshot` by keyword. Read `.kind` where you read `.type` or `.edge_kind`. Errors name `Contact.kind` and `Coil.kind`.
- **Renamed classes, fields and values.** Instruction fields now have the names of their CSV keywords. The CSV text and the encoded bytes do not change, and `FieldError.field` names the new field. Rename each keyword, attribute and import below, and import the new names from `laddercodec`.
  - `laddercodec.instructions.Position` → `PositionMove`, and `Velocity` → `VelocityMove`. The token `raw(Position,...)` does not change.
  - `ConditionInstruction` → `Condition`, and `AfInstruction` → `Instruction`, in `laddercodec.model` and `laddercodec.instructions`.
  - The type alias `AfToken` → `InstructionToken`.
  - `laddercodec.csv.converter.ConvertError` → `CsvReadError`, and `laddercodec.csv.writer.WriterError` → `CsvWriteError`. Both are exported from `laddercodec`.
  - The alias `DecodedRung` → `Rung`.
  - `Timer.timer_type` and `Counter.counter_type` → `kind`, with the same values: `on_delay`, `off_delay`, `count_up` and `count_down`.
  - `Timer.done_bit` and `Counter.done_bit` → `done`. `Timer.current` and `Counter.current` → `accumulator`. `Timer.setpoint` → `preset`.
  - `Drum.drum_kind` → `kind`, and its values `event`, `time` and `time_event` → `event_drum`, `time_drum` and `time_event_drum`.
  - `Drum.events_or_presets` → `events` on an event drum and `presets` on a time drum. A time and event drum has both. A `Drum` given `presets` for an event drum, or `events` for a time drum, raises `FieldError` with reason `conflict`.
  - `Drum.jump_target` → `jump_step`.
  - `Drum.outputs`, `presets`, `events` and `pattern` are tuples. A list that you pass in is stored as a tuple, so compare them with tuples.
  - `Math.result` → `dest`.
  - `Search.comparison` → `op`, and `Search.source` → `value`.
  - `ForLoop.limit` → `count`.
  - `RawInstruction.visual_rows` → `rows`, and `RawInstruction.sub_rows` → `sub`.
  - `Copy.destination` and `Pack.destination` → `dest`.
  - `Copy.format` and `BlockCopy.format` → `convert`, and its values `"none"`, `"value"`, `"text"`, `"binary"` and `"ascii"` → `None`, `"to_value"`, `"to_text"`, `"to_binary"` and `"to_ascii"`.
  - `Pack.pack_type` and `Unpack.unpack_type` → `kind`, and its values `"bits"`, `"words"` and `"text"` → the CSV call names, such as `"pack_bits"` and `"unpack_to_words"`.
  - `Copy.suppress_zero` `"0"` or `"1"` → `True`, `False` or `None`, and `Copy.exponential` `"0"` or `"1"` → `True` or `False`. The strings now raise `FieldError` with reason `flag`.
  - For example: `Timer(kind="on_delay", done="T1", accumulator="TD1", preset="100", unit="Tms")`, `Drum(kind="event_drum", outputs=("C1",), events=("X1",), ...)`, `Math("DS1 + 1", dest="DS2")`, `RawInstruction(name, blob, 1, rows=2, sub=3)`, `Copy("DS1", "TXT1", convert="to_text", suppress_zero=True)` and `Pack("C1", "C16", "DS1", kind="pack_bits")`.
- **`check()` findings rename their fields.** `Finding.kind` → `code`, and `Finding.code` → `click_id`. A `check()` finding names its shape in `code` and CLICK's id, such as `C0202`, in `click_id`. Read `finding.code` where you read `finding.kind`, and `finding.click_id` where you read `finding.code`.
  - Each shape name has `-` where it had `_`, and four shapes are renamed:
    - `output_above_pinned_box` → `output-above-box-inputs`
    - `pin_without_contact` → `input-without-contact`
    - `pin_shares_main` → `input-shares-enable`
    - `pin_shares_pin` → `inputs-share-contacts`
  - `check()` reports shapes that v0.4.0 passed, so a test such as `assert check(rung) == []` can now fail. A finding with the code `shared-input-net` replaces the pin finding that v0.4.0 reported for an instruction fed from the net of another box's pin. The `check()` findings entry under Fixed lists each shape.
- **Instructions and `Rung` are frozen.** Assigning to a field of an instruction or a rung now raises `dataclasses.FrozenInstanceError`. Instructions and rungs are hashable, and a `Rung` stores its rows as tuples. In v0.4.0 you could assign any value to a field.
  - `inst.preset = "500"` → `inst = laddercodec.replace(inst, preset="500")`. `replace()` raises the `FieldError` that building the instruction raises. If you change no field, `encode()` writes the copy as the bytes that the instruction was decoded from.
  - `rung.instructions[0] = coil` → `rung = replace(rung, instructions=[coil, *rung.instructions[1:]])`
  - `Rung(1, rows, afs, None)` → `Rung(rows, afs, None)`. `rung.logical_rows` is a read-only property that returns `len(rung.conditions)`.
  - `Contact("X001", wire_down=True)` → `Tee(Contact("X001"))`. `Contact` and `CompareContact` have no `wire_down`. Where you read `wire_down`, test `isinstance(cell, Tee)` and read the contact from `cell.contact`. The CSV text `T:X001` does not change, and `Contact.from_csv_token("T:X001")` raises `CsvReadError`.
  - `decode()` and `decode_program()` return `Tee(UnknownCondition)` for a cell that they can't read and that has a wire down. v0.4.0 returned the `UnknownCondition` and dropped the wire. An `isinstance(cell, UnknownCondition)` test misses such a cell, so test `cell.contact` of a `Tee` as well.
  - Compare a rung's rows with tuples, or compare whole rungs. Two rungs that differ only in `comment_rtf` are equal.
  - `encode()` raises `EncodeError` for a `Tee` in column A or on the rung's last row, as it does for `"T"` and `"|"`. v0.4.0 encoded `Contact(wire_down=True)` there. `Rung()` raises `EncodeError` for a text where a row or the instructions list belongs. v0.4.0 encoded `"-" * 31` as a row of one-character tokens.
- **Errors are `LaddercodecError`s.** Each function below now raises a `LaddercodecError` subclass where v0.4.0 raised another class. Every `LaddercodecError` is a `ValueError`.
  - `encode()` raises `EncodeError` where v0.4.0 raised a bare `ValueError`. It also raises `EncodeError` for an `UnknownCondition`, an `UnknownInstruction`, or an output cell that is neither a string nor an instruction, such as `None`. v0.4.0 raised `TypeError` or `AttributeError` for these. `encode()` raises `EncodeError` for an `Undecoded` marker too.
  - `read_csv` raises `CsvReadError` where v0.4.0 raised a bare `ValueError` or a `csv.Error`. For a file that isn't UTF-8, v0.4.0 raised `UnicodeDecodeError`. For a `send` or `receive` with no `target=` or `remote_start=`, v0.4.0 raised `KeyError`.
  - `read_csv` raises `CsvReadError` for a compare cell that reads as two compares, such as `"A"=="B"=="C"`. v0.4.0 raised `FieldError` or `ValueError`. Put a TXT register on one side, such as `TXT1=="C"`.
  - `decode_program()` raises `DecodeError` for a file header or program name that it can't read. v0.4.0 raised `ValueError` for the header and `UnicodeDecodeError` for the name.
  - Catch `LaddercodecError`, or `ValueError`, where you caught `TypeError`, `AttributeError`, `KeyError`, `csv.Error` or `UnicodeDecodeError`. Catch `CsvReadError` where you caught `FieldError` for a compare cell.
- **More refusals raise `FieldError`, and some name another field.** Each refusal below raised another class or named another field in v0.4.0. `FieldError` is a `ValueError`, so `except ValueError` still catches it.
  - A field of the wrong type, such as `Contact(5)` or `Coil(None)`, raises `FieldError`. v0.4.0 raised `TypeError` or `AttributeError`.
  - A number of more than 4300 digits in a constant, For count, Timer preset, Drum preset, Slave ID, `ModbusAddress`, Modbus target, Send or Receive range, `function_code=`, `raw(...)` token or `undecoded(...)` token now reads as its value or raises `FieldError`. v0.4.0 raised `ValueError`.
  - A `CompareContact` operator that is not `==`, `!=`, `<`, `>`, `<=` or `>=` raises `FieldError`. v0.4.0 raised `KeyError`.
  - In `read_csv`, an immediate edge contact such as `rise(X001).immediate` raises `FieldError` on `Contact.immediate` with reason `conflict`, and so does `Contact.from_csv_token`. v0.4.0 raised `ValueError`. With `read_csv(..., unchecked=True)` the contact is kept as written.
  - In `read_csv`, a Timer `unit` other than `Tms`, `Ts`, `Tm`, `Th` or `Td` raises `FieldError`. So do a time drum `unit` of any other value, a time and event drum `accumulator` that is blank or not `TD`, and a drum pattern cell that is not `0` or `1`. v0.4.0 raised `ValueError`. A time drum or a time and event drum token with no `unit=` raises `CsvReadError`, and so does a time and event drum token with no `accumulator=`.
  - A blank CSV argument raises `FieldError` with reason `missing` and the blank `field`, as in `out()`, `unit=`, `mode=`, a drum's `outputs=`, a Modbus `target=` and `search(,result=DS1,found=C1)`. v0.4.0 raised a `ValueError` that named no field. An empty required field also raises `FieldError` with reason `missing`.
  - A single `Copy` whose constant source is refused raises `FieldError` on `Copy.source` before the destination is checked. v0.4.0 raised `AddressError` on `Copy.destination` for `copy("",DS1)`.
  - An Out, Set or Reset range whose end is in another bank, such as `out(C1..DS1)`, raises `FieldError` with reason `conflict` and `OBJ-008`. v0.4.0 raised `AddressError` on `Coil.range_end` when the field refuses the end's bank.
  - A Pack source that is longer than any pairing accepts raises `FieldError` on `Pack.source_end` with CLICK's count id, such as `OBJ-041`. v0.4.0 raised `AddressError` on `Pack.destination`. Read `.errors` for the pairing.
  - Catch `FieldError` where you caught `AddressError`, `TypeError`, `AttributeError` or `KeyError` for these.
  - `FieldError.field` is `Class.attr` of the refused field, such as `Send.quantity` or `ModbusTcpTarget.port`, for more refusals than in v0.4.0. A `FieldError` no longer reads its `field` from the message.
  - To build a `FieldError` or `AddressError` yourself, pass a keyword `code`, such as `code=Code.BANK_NOT_ALLOWED`. The keyword `source=` is gone.
  - Match on `field`, `code`, `reason` or `click_id`, such as `error.code == "bank-not-allowed"`, not on the message text.
- **Refusal messages are reworded.** Many error and warning messages now say what to do after they state the rule. When CLICK has an id for the refusal, such as `(OBJ-004)`, the id ends the sentence that states the rule. A `pytest.raises(match=...)` on v0.4.0's text can fail. The new wording leaves `field`, `code`, `reason` and `click_id` as they are.
  - When both ends of a range are in a bank that the field does not accept, such as `C1..C2` as a Fill destination, or both are out of their bank's range, laddercodec raises one refusal for the range. Its message names the range once, `'C1..C2' is not allowed`, and its `fields` holds both ends. v0.4.0 named only the start, `'C1' is not allowed`.
  - When an `Unpack` destination can't take its source, the message names the banks that this kind of unpack writes from that source, such as `an unpack to bits from DD goes to C`. v0.4.0 named the banks of both kinds, `an unpack from DD goes to C, DS, DH`.
  - Match on `field`, `code`, `reason` or `click_id` instead of the message text.
- **A rung that doesn't decode no longer fails the call.** `decode()` and `decode_program()` return an `Undecoded` marker for that rung and emit an `UndecodedRungWarning`. v0.4.0 raised `DecodeError` or `ValueError`.
  - A down wire in the output column, or a wire flag that no token matches, gives a marker for that rung. If a clipboard row or program record can't be read, one marker stands for that rung and every rung after it.
  - A comment that doesn't decode keeps its rung and emits an `UndecodedCommentWarning`. The comment reads `UNDECODED comment: <error>`, followed by the plain text that could be read, and `encode()` writes that text back into CLICK. v0.4.0's `decode()` raised `DecodeError`.
  - `write_csv` writes an undecoded marker, with an `UndecodedRungWarning`, for a rung that holds an unknown condition or instruction, or a compare whose cell reads two ways, such as Data A `"A"=="B"` with Data B `"C"`. v0.4.0's `write_csv` raised `WriterError` for such a rung, and v0.4.0's `decode()` read that compare as an unknown condition.
  - A wrong magic, size or program header still raises `DecodeError`.
  - Check `Program.undecoded` where you caught these errors. Catch `UndecodedRungWarning` and `UndecodedCommentWarning` if you need to know. When you write a subroutine, pass `stop="return"` to `write_csv`, so that a marker acts as `return()`.
- **`decode()` now reads two kinds of stored field differently, and warns for each.**
  - For a stored value that CLICK's dialog refuses, `decode()` and `decode_program()` return the instruction and emit a `RefusedFieldWarning`. v0.4.0 decoded it as `raw(...)` or an unknown condition. If you change such an instruction with `replace()`, `replace()` raises the `FieldError` that building it would raise. To decode and encode a rung unchanged, do nothing. To find these instructions, catch `RefusedFieldWarning`, and fix the field that it names before you encode one that you read from CSV.
  - `decode()` reads a flag field stored empty as set. It emits a `LegacyEncodingWarning` for each such flag that encoding the rung again writes set, such as `Coil.oneshot`. v0.4.0 read an empty flag as clear and gave no warning, and CLICK runs an empty flag as clear. v0.4.0 wrote a set flag as empty in a `raw(...)` box from a program file. Encode the rung again and paste it, so that CLICK runs the flag as `decode()` reads it.
- **Comment Markdown has escapes, and its markers pair as the docs say.** These changes affect the text that `decode()` writes and the styles that `encode()` writes. [Comment styles and escapes](https://pyrung.com/laddercodec/guides/csv-format/#comment-styles-and-escapes) gives the rules.
  - A backslash before `*`, `_` or `\` makes that character text. `decode()` and `decode_program()` write that backslash where a `*`, `_` or `\` would otherwise read as a style or an escape. v0.4.0 had no escape, so CLICK's text `_x_` decoded as `_x_` and encoded again as an italic `x`. Write `\\` for a backslash that comes before `*`, `_` or another backslash. An underscore inside a word, as in `Pump_1_Run`, and a backslash before any other character, as in `C:\temp`, need no change.
  - A `*`, `**`, `_` or `__` with whitespace after it no longer starts a style, and one with whitespace before it no longer ends one. `2 * 3 * 4` and `use _ or _` encode as that text, and `a *b* c` still has an italic `b`. v0.4.0 encoded `2 * 3 * 4` as `2 `, then an italic ` 3 `, then ` 4`. To style text between spaced markers, put each marker next to the text, as in `*3*`.
  - A run of `*` or `_` that can end a style pairs with the nearest run of the same character before it that can start one. `*****WARNING*****` encodes as a bold italic `WARNING`, `*1 see *Auto* mode` as `*1 see ` and then an italic `Auto`, and `*foo**bar*` as an italic `foo**bar`. v0.4.0 encoded the first as a bold `WARNING`, the second as an italic `1 see ` and then `Auto* mode`, and the third as an italic `foobar`. Read back a comment that has three or more `*` or `_` in a row, or one with no partner, and add a backslash where you meant the character as text.
  - `*a***b**` encodes as an italic `a` and then a bold `b`. v0.4.0 encoded the `b` as italic.
  - `decode()` and `decode_program()` drop an underline that covers part of a word, such as the `y` in `xyz`, and keep the text. v0.4.0 decoded it as `x__y__z`, which encodes as that text.
  - `decode()` and `decode_program()` leave whitespace unstyled at the edge of a bold, italic or underlined stretch, such as the space in a bold `a `. v0.4.0 decoded it as `**a **`.
- **Math and Copy constants are written as CLICK stores them.** `to_csv()`, `write_csv` and `encode()` write a real in a `Math` or a single `Copy` source as the value that CLICK prints back, so `1.50` is `1.5` and `1e3` is `1000.0`. v0.4.0 kept the typed text.
  - Hex has uppercase digits: `0ffh` is `0FFh`.
  - A `Copy` drops leading zeros (`007` is `7`) and the `+` of a real (`+1.5` is `1.5`).
  - A `Copy` real is written as CLICK prints its value with 7 significant digits, however you typed it. `1.0E+16` is `1E+16`, and `1.0E+06` is `1000000.0`.
  - Compare constants in CLICK's form, or build both sides through the instruction.
- **A TCP address is written without leading zeros.** `ModbusTcpTarget(ip="010.002.003.004", ...)`, a target that `read_csv` reads, and one that `decode()` or `decode_program()` reads now hold `ip="10.2.3.4"`, and `to_csv()`, `write_csv` and `encode()` write that form. v0.4.0 held and wrote a padded address as given. While you leave a decoded instruction unchanged, `encode()` writes the bytes that CLICK saved.
  - Compare `ip` with the address written without leading zeros, such as `10.2.3.4`.
- **The field checks refuse more values in `Copy`, `BlockCopy`, `Fill` and `Pack`.** Each value below raises `FieldError` when you build the instruction or read it from CSV. v0.4.0 accepted it. A program that CLICK saved with such a value still decodes, with a `RefusedFieldWarning`, and the instruction encodes unchanged.
  - `Copy` of a number constant, register or pointer into TXT with no converter, such as `copy(5,TXT1)`, has reason `conflict`. v0.4.0 wrote a plain copy, which CLICK never saves. Write `convert=to_text(suppress_zero=1,termination_code=none)`, CLICK's default. For a real constant or a DF source, write `convert=to_text(exponential=0,termination_code=none)`.
  - A plain `Copy` of TXT into DS, DD, DH, YD, TD, CTD or SD, and a plain `BlockCopy` of TXT into DS, DD or DH, have reason `conflict`. Write `convert=to_value` for the character's value, or `convert=to_ascii` for its ASCII code. A TXT register into DF stays a plain copy.
  - `Copy` of TXT into DF with `to_value` or `to_ascii`, a `Copy` from TXT with `suppress_zero=True`, and a `BlockCopy` of TXT into TXT with `to_value` or `to_ascii` have reason `conflict`. Drop the converter or `suppress_zero`.
  - `suppress_zero` on a real constant, a DF pointer or a DF address has reason `conflict`. For a real constant or a DF pointer, write `to_text(exponential=0)` where you wrote `suppress_zero`. For a DF address, drop `suppress_zero`. A `Copy` of these sources with `convert="to_text"` has `suppress_zero` `None` by default.
  - `Copy` of a number constant into text that runs past TXT1000, such as `-5` into TXT1000, raises `AddressError` with `OBJ-003`. Start the text at a lower TXT.
  - `copy(EH,...)` and `copy(1Eh,...)` are refused. v0.4.0 read them as hex 14 and 30, but CLICK stores them as the reals 0.0 and 1.0. Write `0.0` or `14` where you wrote `EH`, and `1.0` or `30` where you wrote `1Eh`.
  - A real constant with more than 7 significant digits in a single `Copy`, such as `copy(1.2345678,DF1)`, has reason `form`. v0.4.0 wrote it as typed, and CLICK saves it cut. Write the constant that the message names, such as `1.234568`.
  - `Fill` of a hex constant above `FFFFh` into any bank has `OBJ-005`. v0.4.0 accepted up to `FFFFFFFFh`. To fill a larger value, write it as an integer.
  - `Fill` of an integer or hex constant of more than one character into TXT, such as `-5`, `123` or `10h`. Write one character, such as `5`, or a real, such as `1.5`.
  - An SD register that a program can't write, as a `Copy` destination or in a `BlockCopy` or `Fill` destination range, has reason `not_writable`. A `Fill` into `SD29..SD38` has `OBJ-004`, because SD30 is read-only. Use a writable SD register.
  - `pack_text` of more than 4 TXT registers into DH, such as `pack_text(TXT1..TXT16,DH1)`, has `OBJ-003`. Pack at most 4 TXT characters into a DH.
  - A `Pack` of bits or words with `allow_whitespace=True` has reason `conflict`. v0.4.0 accepted it and did not encode it. Drop `allow_whitespace`.
- **The field checks refuse more values in `Math`, `CompareContact`, `Search`, `Send`, `Drum` and flags.** Each value below raises `FieldError` when you build the instruction or read it from CSV. v0.4.0 accepted it, unless the item says otherwise. A program that CLICK saved with such a value still decodes, with a `RefusedFieldWarning`, and the instruction encodes unchanged.
  - A `Math` address outside its mode's banks has `OBJ-1002` and reason `bank`. A hex formula accepts hex constants and the DH, XD and YD registers. A decimal formula accepts decimal constants, the DS, DD, DF, TD, CTD and SD registers, and X, Y, C, T and SC bits as the range of a `SUM`. For a hex formula, copy the register into a DH first. For a decimal formula, copy a DH, XD, YD or TXT register into a DS first. Or use the other mode.
  - A `Math` result in an SD register that a program can't write has reason `not_writable`.
  - A `RAND` bound outside its mode has `OBJ-1002`. A decimal `RAND` accepts a DS or DD register or an integer constant, and a hex `RAND` accepts a DH register or a hex constant. A real bound and two equal bounds have `OBJ-1001`. Copy the register into a DS, DD or DH first, and write two different integer bounds.
  - A real in a decimal `Math` that CLICK saves as another value has reason `form`. CLICK saves `0.33333334` as `0.333333`, for example. A real that CLICK cuts when it is typed in positional form, such as `0.00012345`, has reason `form` too. v0.4.0 wrote the constant as typed. Write the constant that the message names, such as `1.2345E-04`. [Operand normalization notes](https://pyrung.com/laddercodec/guides/csv-format/#operand-normalization-notes) lists the forms that CLICK keeps.
  - A real in a decimal `Math` above float32's largest value, such as `3.4028235E+38`, has `OBJ-1009`. v0.4.0 accepted `3.4028235E+38` and refused a larger real with no id. Write `3.402823E+38` for float32's largest value.
  - A `CompareContact` with a real constant that float32 can't hold, such as `DF1==3.5E+38`, has `OBJ-005`. Write a real of at most `3.4028235E+38` in size. v0.4.0 already refused such a real as a `Search` value, and that refusal now has `OBJ-005` too.
  - The right side of a `CompareContact` with a hex left side, such as `DH1==DH`, refuses `DH` in any letter case with code `invalid-constant`. v0.4.0 read it as the hex constant D. Write `0DH`.
  - A `Search` value address outside the table's compare group, such as `search(DS1..DS10 == TXT20,...)` or a DS table with an XD value, has `OBJ-004` and code `search-value-bank`. Use an address in the table's group: XD, YD or DH for a DH table, TXT for a TXT table, and TD, CTD, DS, DD, DF or SD for the others.
  - With CLICK addressing, a `Send` whose `remote_start` has another data type than its `source`, such as `remote_start="DH1"` with `source=DS1`, has reason `conflict` and `OBJ-004`. A `Send` to any SD register has reason `not_writable` and `OBJ-004`. Write to DS or TD from DS, TD or SD, to DD or CTD from DD or CTD, to DF from DF, to DH or YD from DH, XD or YD, and to TXT from TXT.
  - A `Send` from TXT with FC16 counts characters. It accepts an even count of 2 to 246 characters, or fewer after a hex start, and refuses other counts with `OBJ-010`, or `OBJ-029` for an odd count. v0.4.0 counted TXT in registers and accepted 1 to 123. Send an even number of TXT characters, such as `source=TXT1..TXT20`, or send one TXT register with FC06.
  - A `Send` from an even TXT address, such as `source=TXT1000`, has code `txt-start-not-odd` and `OBJ-028`. Start at an odd address, such as `TXT999`.
  - A `Send` to a hex `remote_start` has `OBJ-010` when its count runs past `FFFDh` from DD, DF or CTD, or past `FFFEh` from any other register bank. Each element, and each TXT character, counts as one address. v0.4.0 checked this only for a DD source. Lower the count or the start address.
  - `word_swap=True` on a `Send` has reason `conflict` and code `option-not-offered` unless the Send uses FC16. The same holds for a TXT source, and for a count of 1 from DS, DH, TD or SD. Drop `word_swap=1`.
  - `Drum(kind="event_drum", unit="Ts", ...)` and `event_drum(...,unit=Ts)` have code `option-not-offered`, because an event drum has no time unit. v0.4.0 wrote nothing for the unit, and `read_csv` ignored it. Leave `unit` blank.
  - A flag of `Copy`, `BlockCopy`, `Fill`, `Pack`, `Unpack`, `Search`, `Math`, `ForLoop`, `OutVariant`, `Send` or `Receive` that is not True, False, 1 or 0 has reason `flag`. v0.4.0 wrote `oneshot=2` as `oneshot=1`. In CSV, a flag such as `oneshot=yes` has reason `flag`, and a blank flag such as `oneshot=` has reason `missing`. v0.4.0 read both as off, and it raised `ValueError` for them in `out`, `for` and `timed`. Pass True, False, 1 or 0, and write `1` or `0` in CSV.
- **`read_csv` refuses token arguments that v0.4.0 dropped, and reads quotes as written.** v0.4.0 dropped each argument below, read it into another field, or read it as another value.
  - A keyword that `copy`, `blockcopy`, `fill`, `pack_*` or `unpack_to_*` does not accept, such as a misspelt `terminaton_code=`, raises `CsvReadError`. So does `allow_whitespace=` in `pack_bits` or `pack_words`. Spell the keyword as the docs do, and put `suppress_zero` and `exponential` inside `to_text(...)`.
  - `termination_code=$XX` on a `copy` or `blockcopy` that is not into TXT, or on a single Copy of a `$hh` code into TXT such as `copy($41,TXT1,termination_code=$0D)`, raises `FieldError` with reason `conflict`. v0.4.0's `Copy()` already refused these codes. Drop the code, or write it inside `to_text(...)` or `to_binary(...)` for a number copied to TXT.
  - An argument of a `send`, a `receive`, a target or a `ModbusAddress(...)` raises `CsvReadError` if it has no keyword, is written twice, is not one of the call's keywords, is empty, or runs into the next argument because a comma is missing. A target that is neither a `ModbusTcpTarget(...)` nor a `ModbusRtuTarget(...)` also raises `CsvReadError`, where v0.4.0 raised a plain `ValueError`. Write each argument once, as `keyword=value`, with a comma between arguments.
  - A keyword value in quotes in a `copy` or `search` call, such as `copy("AB",TXT1,oneshot="1")`, raises `CsvReadError`. In a `search` of quoted text, a quoted keyword value before `result=` and `found=` reads as part of the text, so `search(TXT1..TXT10 == "A",oneshot="1",result=DS30,found=C1)` searches for `A",oneshot="1`. v0.4.0 read the value without its quotes. Write keyword values in `copy` and `search` without quotes.
  - A `"` in a Modbus target's name is written twice. `Send.to_csv()`, `Receive.to_csv()` and `write_csv` write it as `""`, and `read_csv` reads `name="a""b"` as the name `a"b`. v0.4.0 wrote the quote once and read `""` as two quotes, so a file that v0.4.0 wrote for such a name now raises `CsvReadError` or reads another name. Double each quote inside a name.
- **`read_csv` and `write_csv` drop a rail-fed `NOP` and refuse a rung of more than 32 rows.**
  - When a rung has another output, they drop a `NOP` that the rail feeds with no contact, and lay out the rest of the rung. CLICK's syntax check does the same. v0.4.0 kept such a rung as drawn. A rung of `X001 -> out(Y003)`, `X002 -> out(Y004)` and a rail wire to `NOP` read as one rung in v0.4.0, and it now reads as two. Expect no `NOP` in such a rung, and one rung for each output whose circuit meets the others only at the rail.
  - For a rung that needs more than 32 rows, `read_csv` raises `CsvReadError` and `write_csv` raises `CsvWriteError`, both with the code `layout-too-tall`. `read_bundle`, `csv_rows` and `write_bundle` raise the same errors, and `check()` reports a `layout-too-tall` finding. v0.4.0 read and wrote such a rung, and `check()` reported nothing. Split the rung.
- **`parse_bundle` lists files in another order.** `laddercodec.csv.bundle.parse_bundle` lists the subroutine files sorted by name with case ignored, the same on every OS. It lists a file named `.csv`, and it reads `subroutines/main.csv` as a subroutine. v0.4.0 sorted by path, which ignores case only on Windows, skipped `.csv`, and read `subroutines/main.csv` as the main program.
  - Look a subroutine up by its name, not by its position.
- **A field with a fixed set of values is annotated with its `Literal` alias.** v0.4.0 annotated the fields below `str` or `int`, and a type checker now refuses a plain `str` or `int` in them.
  - `Timer.unit`, `Drum.unit` and `OutVariant.unit`
  - `Copy.convert` and `BlockCopy.convert`
  - `Pack.kind` and `Unpack.kind`
  - `Search.op`
  - `ModbusRtuTarget.com_port`, `ModbusTcpTarget.com_port` and `ModbusAddress.register_type`
  - `Send.function_code` and `Receive.function_code`
  - Narrow the value to the alias first, for example with `typing.cast(TimeUnit, unit)`.

### Added

- **Error classes.** Every error that `decode()`, `decode_program()`, `encode()`, `read_csv()`, `write_csv()` and `check()` raise for input that they can't read or write is a `LaddercodecError`, and each is a `ValueError`. `read_csv` and `read_bundle` raise `CsvReadError`. `write_csv`, `csv_rows` and `write_bundle` raise `CsvWriteError`. The other classes are `DecodeError`, `EncodeError`, `LayoutError`, and `FieldError` with its subclass `AddressError`.
- **What an error says.** Each refusal and each `check()` finding names its rule in `code`, a `Code`. `Code` is a string enum of kebab-case names such as `bank-not-allowed`, and `CLICK_IDS` lists the CLICK ids that each code can come with. The [Error codes](https://pyrung.com/laddercodec/guides/codes/) page lists every code.
  - A `FieldError` has `reason`, a `Reason` such as `bank`, `range` or `conflict`. It has `click_id`, CLICK's own id such as `OBJ-005` when CLICK has one, and `fields`, one field or both fields of a pair. Its `errors` lists every refusal of the construction, the raised one first.
  - An error from `read_csv` has a `CsvLocation` (file, line, rung, row and column) as its `location`, and its message ends with it. Each refusal in `.errors` has its own `location`.
  - `CsvWriteError` has `code` and `click_id`, as `CsvReadError` has. When two subroutine names are equal with the case of A-Z ignored, such as `Pump` and `pump`, `write_bundle` raises a `CsvWriteError` and `read_bundle` raises a `CsvReadError`. Both have the code `duplicate-subroutine-name` and the `click_id` `GUI-036`. `é1` and `É1` are two names, and `write_bundle` refuses them with a `CsvWriteError` that has no `code`, because their files would be one file on a file system that ignores case.
  - `LaddercodecError` has `message(names)`, `short(names)` and `detail(names)`. With `names={"C1": "Valve"}`, `message()` returns `Copy.dest: Valve (C1) can't take DS1; ...` for a Copy of DS1 into C1. `short()` and `detail()` split that text for you to show next to the field, so they say `this field` where `message()` names the field.
- **Undecoded markers.** When `decode()` or `decode_program()` can't read a rung, it returns an `Undecoded` marker for that rung and decodes the other rungs. The marker acts as `end()` in the main program and `return()` in a subroutine. `Program.undecoded` lists the markers. `write_csv` and `read_csv` round-trip a marker as an `undecoded(...)` token. `encode()` refuses a marker, and `check()` reports it as an `undecoded-rung` finding.
- **Instructions that hold a refused value.** `decode()` and `decode_program()` emit a `RefusedFieldWarning` for each instruction that holds a value CLICK's dialog refuses. `read_csv(..., unchecked=True)` reads such an instruction as written, with the same warning. `read_csv(path, allow=["bank-not-allowed"])` reads an instruction whose refusals all have a code that you list, with no warning, and `read_bundle()` accepts the same `allow=`. `encode()`, `write_csv()` and `write_bundle()` write such an instruction from its fields. A refusal raises as it does without `allow=` if you don't list its code, or if laddercodec can't write the instruction and read it back the same.
- **CSV helpers.** These functions read and write CSV as a folder, as rows or as one token.
  - `write_bundle(directory, project, *, index=False)` writes a `Project` as `main.csv` and one `subroutines/<name>.csv` for each subroutine. `read_bundle(directory, *, strict=True, unchecked=False, allow=())` reads that folder back into a `Project`. An error from any file has that file in its `CsvLocation`.
  - `csv_rows(rungs, *, index=False, stop="end")` returns the rows that `write_csv` writes after the header, each as a list of strings, so you can use them without writing a file. `CSV_HEADER` is the header row, as a tuple of strings.
  - `Send.from_csv_token()` and `Receive.from_csv_token()` read a `send(...)` or `receive(...)` token and return the instruction, as `Coil.from_csv_token()` does for `out(...)`. They raise the same `CsvReadError` or `FieldError` that `read_csv` raises for the same token.
- **`lay_out()` and the circuit types.** `lay_out(circuit)` returns the rungs that CLICK's syntax check draws for a circuit that you build from `Circuit`, `Branch`, `Box`, `Series`, `Parallel` and `Term`. For a circuit that CLICK can't hold, such as one of more than 32 rows, `lay_out()` raises `LayoutError`.
- **`addresses()`.** `addresses(payload)` returns every address that a `Rung`, a list of rungs or clipboard bytes uses. That includes the ends that CLICK works out, such as TXT5 for a Copy of `"HALLO"` into TXT1. CLICK drops each pasted operand whose address is not in the project, so add these addresses to the project first. See [Add The Addresses Before You Paste](https://pyrung.com/laddercodec/guides/encoding/#add-the-addresses-before-you-paste).
- **`constant_text()`.** It returns the text that a `Math` or `Copy` source stores for a Python int, float or str. `constant_text(255, hex=True)` is `FFh`.
- **More top-level names.** `laddercodec` exports each name above, and also `UnknownCondition`, `UnknownInstruction`, `Email`, `Home`, `PositionMove`, `VelocityMove`, `Tee`, `Condition`, `Instruction`, `ConditionToken`, `InstructionToken` and `replace`.
  - `laddercodec` and `laddercodec.instructions` export a `Literal` alias that lists the values of each instruction field that accepts only a fixed set: `ContactKind`, `CompareOp`, `CoilKind`, `OutVariantKind`, `OutVariantUnit`, `TimerKind`, `TimeUnit`, `CounterKind`, `DrumKind`, `MathMode`, `CopyConvert`, `BlockCopyConvert`, `PackKind`, `UnpackKind`, `ModbusRtuPort`, `ModbusTcpPort`, `ModbusRegisterType`, `SendFunctionCode`, `ReceiveFunctionCode` and `UndecodedStop`. `typing.get_args(laddercodec.ContactKind)` returns `("no", "nc", "rise", "fall")`.
  - The fields of `Email`, `Home`, `PositionMove` and `VelocityMove` are named after CLICK's tag ids, such as `tag_3218`. A later release will rename them.

### Changed

- **More refusals have CLICK's id.** Many refusals that had no `click_id` now have one. A Pack destination in a bank that Pack never writes, such as `X001`, has `OBJ-004`. A Pack destination whose bank can't take the source, such as `C1..C16` into `TD1`, has `OBJ-024`. laddercodec refuses the same values as before.
- **CSV format guide.** The guide no longer describes pyrung's exporter, and its sections "Subroutine tail guarantee" and "Strict validation and failure mode" are gone. Three sections have new names and anchors: "`Or(...)` expansion" is "OR legs", "Builder pin continuation rows" is "Pin continuation rows" and "For-loop lowering" is "For loops". Update any link to them.
- **Docs site follows releases.** The published docs now update when a release is published, not on every change to `main`.

### Fixed

- **Raw boxes from program files.** A `raw(...)` box that `decode_program()` reads, and its `raw(...)` token in `write_csv`, now hold the blob that CLICK writes to the clipboard for it. That blob has every tag in CLICK's order, with a set flag as `-1` in a Copy, Drum, Math or Search and `1` in any other class. A box that laddercodec can't read as an instruction of its class keeps only the tags that the program file stores, with each flag written the same way. v0.4.0 wrote only the stored tags for every such box, with a set flag as an empty value.
- **Copy conversions that CLICK saves.** A single Copy between DF and CTD, of a real constant into DD or CTD, or of an integer constant outside int16 into DF now encodes as CLICK saves it, and `convert=to_binary` works on these copies. v0.4.0 wrote a plain copy and refused `to_binary`. CLICK's saves of these copies now decode as the `Copy`, where v0.4.0 decoded them as `raw(Copy,...)`.
- **Copy into TXT.** A single Copy of a number constant into TXT now writes the last TXT that its text fills, as CLICK does. The last TXT counts the real in the form that CLICK stores. `10000000000.0` into TXT1 is stored as `1E+10` and fills TXT1..TXT5, and `1.0E+16` into TXT996 fills TXT996..TXT1000. A real constant or a DF pointer copied to TXT with `to_text` now converts as a DF address does: with CLICK's real numbering, or with exponential numbering when `exponential=1`. v0.4.0 converted it as an integer and refused `exponential=1`. CLICK's saves of a real constant copied to TXT now decode as the `Copy`, where v0.4.0 decoded them as `raw(Copy,...)`.
- **Values that CLICK accepts.** v0.4.0 refused each value below, and laddercodec now accepts it.
  - A single Copy source, the right side of a `CompareContact` or a Search value of quoted text accepts any character from U+0001 to U+FFFF except a surrogate, and `read_csv` accepts a line break inside the quotes. All three still refuse NUL and characters above U+FFFF.
  - A single Copy source, a Search value and either side of a `CompareContact` accept a quote inside quoted text. In CSV the text runs as typed from its first quote to its last. `copy("A"B",TXT1)` writes TXT1 to TXT3, `search(TXT1..TXT10 == "A",B",result=DS30,found=C1)` searches for the four characters `A",B`, and `TXT1=="A"B"` compares TXT1 to TXT3 with `A"B`. v0.4.0's `decode()` read CLICK's saves of these as raw instructions or unknown conditions.
  - The right side of a `CompareContact` and a `Search` value accept `$` and one hex digit, such as `TXT1==$1`, and keep it as typed. The left side of a `CompareContact` still refuses it.
  - A single Copy accepts an SD pointer such as `SD[DS1]` as its source, as in `copy(SD[DS1],DS1)`. It still refuses one as the destination.
  - A single Copy into TXT of a TXT register, quoted text, a decimal integer or a real accepts `termination_code=$0D`, such as `copy("AB",TXT1,termination_code=$0D)` and `copy(5,TXT1,convert=to_text(suppress_zero=1,termination_code=$0D))`. v0.4.0's `read_csv` refused a code inside `to_text` and dropped a code outside `convert`, as in the first example. A Block Copy of TXT into TXT keeps its code through `decode()`, `encode()` and `read_csv`, where v0.4.0 dropped it.
  - A Receive into TXT accepts an even count of 2 to 250 characters, as CLICK does. v0.4.0 refused a count over 124.
  - A For count of `-0` is stored as `0`, from `ForLoop(count="-0")` and from `for(-0)`. v0.4.0 raised `AddressError`. A sign on any other count still raises.
- **CLICK's saves that decoded as raw.** Each form below now decodes as the instruction.
  - An address that CLICK saves as typed, such as `DS001`, `ds1` or `YD0U`, in a Copy destination, a Math formula, a hex Math result, the right side of a Compare, or a Search's table start or result decodes in display form. An address with a space at either end decodes the same way in the right side of a Compare or a Search's result. v0.4.0 decoded a Copy, Math or Search as `raw(...)` and a Compare as an unknown condition.
  - A hex `Math` holding `1E3h`, which CLICK stores for a constant typed `1e3`, decodes as the `Math`, and `read_csv` reads it. v0.4.0 decoded it as `raw(Math,...)`, and its `read_csv` refused it.
  - `decode_program()` reads a Compare or Search text of 127 characters or more. v0.4.0 decoded the Compare as an `UnknownCondition` and the Search as `raw(Search,...)`.
- **`check()` findings.** `check()` reports these shapes with CLICK's codes.
  - A contact in parallel with a wire-only leg is `C0002`. v0.4.0 reported it with no CLICK id.
  - A contact that feeds only a `NOP` is `C0003`, with the code `contact-feeds-only-nop`. A timer's or counter's reset with nothing wired is an `unwired-input` finding, `C0202`. v0.4.0 reported neither.
  - An instruction fed from the net of another box's pin has the code `shared-input-net`, `C000A`. v0.4.0 reported a pin finding for it.
  - An output above a box with a used pin is `C000A` when it hangs off any net of the box's main input circuit, such as the net between `X001` and `X003` when they feed a timer in series. v0.4.0 reported it only on the box's main input net.
- **No partial file from `write_csv`.** When `write_csv` raises `CsvWriteError` for a rung, it now creates no file and leaves a file already at the path unchanged. v0.4.0 left a file that held only the header and the rows before that rung, in place of any file that was there.

## 0.4.0 (2026-11-14)

This release writes rungs as CLICK writes them and refuses what CLICK refuses. Read "Behaviour changes" before upgrading.

### Added
- **`check(rungs)`**: returns a `Finding` for each rung shape CLICK's syntax check refuses, with CLICK's error code where a capture shows it.
- **CSV layout as CLICK draws it**: `read_csv` lays each rung out as CLICK's syntax check does, and `write_csv` writes that drawing.
- **`LegacyEncodingWarning`**: `decode()` and `decode_program()` warn on a Math decimal constant outside -32768..32767 stored as 16-bit, which CLICK runs as its low 16 bits; re-paste the rung to fix it.
- **Raw box height and pins in CSV**: `raw(Email,0x2737,1,rows=3,sub=3,pins=...)` keeps a box's row span, sub-rows and part rows through CSV.
- **One-phase `debounce`**: a debounce with only its on or only its off phase encodes and decodes instead of reading as `raw(Out,...)`.
- **Send/Receive `function_code=N`**: keeps a Receive's FC02 or FC04 and a one-element Send's FC15 or FC16 through re-encoding.
- **Tall boxes in CSV**: `write_csv` keeps a blank row inside a tall box when a later row holds wires or contacts, where it raised `WriterError`.

### Behaviour changes
- **Stricter validation**: a value CLICK refuses raises `FieldError` (`AddressError` for an address, both `ValueError` subclasses) on construction or `read_csv`, where it was stored or failed at encode; a blob holding one decodes as `raw(...)` or an unknown condition and keeps its bytes. What each instruction accepts is in [Operand normalization notes](https://pyrung.com/laddercodec/guides/csv-format/#operand-normalization-notes).
  - Do: catch `ValueError` around `read_csv` and the constructors (`FieldError`, `AddressError` and `ConvertError` are subclasses), and fix the rung.
- **Display form of addresses**: addresses are kept, written and encoded as CLICK shows them (`X1` becomes `X001`, `C001` becomes `C1`, `ds07` becomes `DS7`), and a blob not in that form decodes as `raw(...)`.
  - Do: expect the display form when you read addresses back or compare them with your own text.
- **Re-encoded bytes change**: Math hex constants and signs, Math unary plus, Math X and Y ranges, single-register Send FC16, Copy text into TXT, 3-row Email, Home, Position and Velocity, and raw box heights.
  - Do: re-record stored `.bin` files and paste-check them in CLICK.
- **Decoding**: a bit Pack or Unpack decodes as `pack_bits` or `unpack_to_bits` (it decoded as words), and a Send keeps a status operand whose enable flag is 0.
  - Do: check code that expected `pack_words` or `unpack_to_words` for a bit pack.
- **`read_csv` returns more rungs than the CSV holds**: a rung whose circuits meet only at the rail reads as one rung per circuit, each laid out as CLICK's syntax check draws it.
  - Do: use the rungs `read_csv` returns; do not match them to CSV rows by index.
- **Down wire in the output column**: `decode()` and `decode_program()` raise `DecodeError` naming the rung and row, where the wire was dropped without a word; one such rung fails the whole call, so `decode_program()` returns no rungs for that program.
  - Do: catch `DecodeError`, or let CLICK's syntax check remove the wire before you copy the rung.
- **Raw tokens from CSV**: a `raw(...)` token without `rows`, `sub` or `pins` takes its class's height.
  - Do: rewrite old CSV with `write_csv` to keep a decoded box's height and pins.

### Fixed
- **Raw box field values**: a raw box whose field value holds a comma, quote, newline, tab or trailing space reads back; it wrote a token that failed to read or read other bytes.
- **Copy text into TXT**: a single Copy of 2 or more characters into TXT stores the last TXT it fills as its destination end, as CLICK does.
- **Math formula length**: a formula over CLICK's limit raises `FieldError` instead of writing a blob whose field count disagrees with its header.

## 0.3.3 (2026-11-11)

### Added
- **Binary copy termination code**: a Copy from a number register to TXT with `convert=to_binary(termination_code=$0D)` keeps its termination code through CSV.
- **Send/Receive ports and slave IDs**: `ModbusTcpTarget(...,com_port="wlan")` for the WLAN port, `ModbusRtuTarget(com_port="cpu3")` for CPU Port 3, and a slave ID read from a register (`device_id=DS2420`; CLICK accepts only DS). Each gets the protocol mode and func code CLICK writes.

### Changed
- **Copy to text**: `to_text(...)` is written with only the option the source has, `suppress_zero` for an integer source and `exponential` for a DF source, matching pyrung's exporter; the other is still accepted on read, except that `exponential=1` from an integer source now raises `ValueError` instead of encoding as a character-value copy.
- **Coil One Shot**: `latch(...,oneshot=1)` and `reset(...,oneshot=1)` raise `ValueError`, since CLICK's Set/Reset dialog has no One Shot.
- **Retentive Off Delay**: an `off_delay(...)` with a `.reset()` row raises `ValueError`, since CLICK's Timer dialog offers Retentive only for On Delay; such a blob decodes as `raw(Tmr,...)`.

### Fixed
- **Search encode**: each comparison and one-shot combination gets the func code CLICK writes (`8964` + operator + 6 for one-shot), where before most were written as `8970`; CLICK corrected it on paste, so pasted rungs already behaved.
- **Drum encode**: a Th drum with Jog gets CLICK's func codes (8480–8483, time & event 10528–10531), and a time drum with a register preset is written in CLICK v4's form, with the preset mask and func codes CLICK's dialog writes, instead of the constant-preset form that a paste keeps as is; time & event drums write the same mask.
- **Coil**: One Shot now works with a range and with Immediate (`out(C1..C4,oneshot=1)`, `out(immediate(Y1),oneshot=1)`) instead of failing to encode and decoding as `raw(Out,...)`, and the One Shot flag is written as `1`, as CLICK writes it, not `-1`.
- **Copy conversions**: a DF to text copy with real numbering, and a copy between DD and DF, encode with the conversion CLICK writes and decode instead of reading as `raw(Copy,...)`.
- **Math encode**: an integer literal outside -32768..32767 is stored as a 32-bit constant (`W100000`), as CLICK writes it, instead of a 16-bit one (`H100000`), which a paste kept as is.
- **For One Shot**: the One Shot flag of `for(...,oneshot=1)` is written as `1`, as CLICK writes it, not `-1`.
- **Send/Receive decode**: a WLAN or CPU Port 3 Send/Receive decoded as an RTU target on CPU Port 2 (dropping a WLAN target's IP), and a register slave ID as slave ID 1; a port or func code we don't model, such as an ASCII Send, now decodes as `raw(...)`.

## 0.3.2 (2026-11-10)

### Changed
- **Copy termination codes**: a `$` termination code is stored as two hex digits (`$D` and `$0d` become `$0D`), as CLICK and pyrung write it, and a code that isn't hex in `$00`–`$FF` raises `ValueError`.

### Fixed
- **SCR decode**: tags CLICK leaves out of a program file read as their defaults, so a `timed`, `debounce` or `flasher` coil at `Tms` no longer decodes from SCR as `raw(Out,...)`, and a set `0x11F5` flag on Home, Position and Velocity no longer reads as `"0"`.
- **Copy decode**: a Copy to text with a termination code below `$10` decodes as `$0D`, not `$D`, and a single Copy carrying end addresses, which CLICK doesn't write, round-trips as `raw(Copy,...)` instead of losing them.
- **CSV writer**: a loop is written `for(N)`, not `for(N,oneshot=0)`, matching pyrung's exporter.

## 0.3.1 (2026-11-06)

### Changed
- **Empty text constants**: `encode()` raises `ValueError` for `""` in a Copy or Fill source, a Search value or a compare contact, since CLICK cannot store an empty text constant; use `$00` for the NUL character.

### Fixed
- **Large pastes**: encoding more than 256 rungs no longer raises `byte must be in range(0, 256)`, and buffers past 2047 grid rows encode and decode without dropping rungs.
- **Copy text constants**: a Copy from a text constant (`"Q"`, `$00`) encodes with the flag CLICK sets and decodes without a spurious `termination_code`, so `write_csv` round-trips it.
- **Math encode**: `LSH`, `RSH`, `LRO` and `RRO` are written in the editor's infix form, like `RAND`.

## 0.3.0 (2026-11-01)

### Added
- **CLICK v4 Out variants**: `toggle(C1)`, `debounce(...)`, `flasher(...)` and `timed(...)` decode and encode as `OutVariant`, exported from the root package, matching Click-written blobs byte for byte.
- **CLICK v4 Time & Event drum**: `time_event_drum(outputs=[...],presets=[1000,None,DS1],events=[None,C1,C2],unit=Tms,...)` decodes and encodes as `Drum(drum_kind="time_event")`, with `None` marking a step without a preset or event.
- **CLICK v4 Break and Continue**: `break()` and `continue()` decode and encode as `Break` and `Continue`, exported from the root package; both used to decode as `next()`.
- **CLICK v4 Math**: wide ranges encode up to CLICK's limit of 5000 interior addresses, where more than 500 used to raise `ValueError`, and `XD`/`YD` registers are recognized as operands, including `XD0u` and its place inside a range.
- **CLICK v4 check**: `find_v4_only(rungs)` lists the instructions an older CLICK would silently change or may not hold (Break/Continue, Out variants, Time & Event drums, time drums with a duration from a register, v4 math functions, SUM over bits, Math ranges past 500 interior addresses), and `is_v4_only()` checks one.
- **Pin OR legs**: OR legs under a counter, shift or drum pin push the later pins down and grow the box as CLICK does, in clipboard and SCR, exposed as `pin_rows`.

### Changed
- **CSV read**: a blank-AF row directly under `count_down` now counts toward its Down input and grows the box by a row; it used to leave the token row's contacts on the box's unused top row, where they fed nothing.
- **CSV errors**: pins out of order or repeated raise `ConvertError` instead of being dropped, a pin a timer does not have (e.g. `.down()`) raises `ConvertError` instead of reading as a blank row, and `write_csv` refuses a leg drawn onto an unused pin's row, which CSV cannot express.

### Fixed
- **Math encode**: formulas and constants are written the way Click's editor writes them (`ABS(x)*2` → `ABS ( x ) * 2`, `RAND` in its infix form, range interiors listed, `Ah` → `UH10`, `-5` → `H-5`, `-2.5` → `F-2.5`), so pasted formulas no longer raise Math instruction errors or fail CLICK v4's syntax check.
- **Math encode**: `show_nicknames=True` wraps each operand once, where repeated or overlapping addresses (`DS10 + DS1 + DS1`) came out corrupted.
- **Math decode**: `XD`/`YD` formulas keep their display constants, instead of `XD0 AND 1h` reading back as `XD0 AND UH1`.
- **Drum encode**: with Jump off, Jog takes the func code Jump would have, so CLICK v4 no longer rejects a pasted drum with C000A ("all inputs of the box instruction must originate from the same branch").
- **Unknown coils and drums**: an Out coil with an unknown func code or a drum with an unknown base decodes as `raw(...)`, instead of silently decoding as a plain `out(...)` or `time_drum`.
- **Raw multi-part instructions**: a `raw(...)` token with part count 2+ rebuilds Click's part bytes, so `write_csv` no longer fails its round-trip check on raw drums and SCR raw blobs carry the right bytes.
- **CSV read, OR inputs on boxes**: OR legs under any timer, counter, shift or drum input push its later pins down, so a `count_down` fed by a 3+ row OR no longer raises and a retentive timer fed by a 2+ row OR keeps its `.reset()`.
- **CSV writer**: a box's empty pin rows and a `count_down`'s empty top row stay in place when a blank-AF row or a `count_down` follows, where `write_csv` used to fail its round-trip check.

## 0.2.2 (2026-09-10)

### Fixed
- **SCR decode**: parse counted column widths, independent display flags, and all stored rows so valid populated special rows no longer trigger recovery, and malformed records fail without silently skipping a rung.
- **SCR decode**: preserve branch wiring above a later rail-connected row instead of deleting the branch and shifting the lower wire upward.

### Added
- **Native drum regression fixtures**: preserve the original NOP's wire row and a branch above it after row insertion and drum placement, with native SCR/clipboard and CSV comparisons.

### Documentation
- Correct SCR flag meanings and fixture provenance, and distinguish native persisted flags from the encoder's construction conventions.

## 0.2.1 (2026-08-25)

### Fixed
- **SCR decode**: a Modbus `Send` at `device_id=0` no longer decodes as `device_id=1` — SCR blobs elide fields at their class default, and Send's device_id default (0) differs from Receive's (1).
- **CSV writer**: a `count_up` with `.reset()` wired but `.down()` unused always dehydrates the empty `.down()` row, so the `.reset()` pin row directly follows the counter row even when the reset branch has a floating OR-leg below it.
- **CSV read**: rows after a counter/shift `.reset()` pin row stay below the instruction's span instead of being absorbed into it, which misplaced a floating OR-leg onto the unused `.down()` row.

### Added
- **Tests**: synthetic regression coverage for default-elided Send/Receive fields and for floating OR-leg rows below every pinned instruction span (timer, count_up, count_down, shift).

## 0.2.0

### Fixed
- **SCR decode**: correct the row-topology block framing — every row (including row 0) uses one uniform block format, fixing branch rungs whose wires (`T`/`|`/`-`) were silently dropped whenever a continuation row's first right-wired cell carried segment flag 1.
- **SCR decode**: accept placement-ordered flag-table entries — native captures store columns out of order (e.g. `[6,1,0,3,2,4,5]`), which the old sorted-order validation rejected.
- **SCR decode**: introduced deletion of presumed orphan wire rows above a later rail-connected row; the claimed native clipboard agreement was based on a synthetic fixture, and this behavior is reversed in 0.2.2.

### Changed
- **SCR decode**: replace the heuristic topology parser (leading-row guessing, count_down special cases, end-marker scanning) with a deterministic parser derived from the verified format — see `docs/internals/binary-format.md` §"SCR row-topology blocks" for the spec.
- **SCR decode**: `decode_program()` now parses rung records with a single forward cursor — comments, topology, and instructions are read from explicit lengths and counts instead of scanning for signatures, so comments attach to their own rung by construction and malformed files fail loudly with the byte offset (see §"SCR rung records" in the binary format doc).

### Added
- **Tumbler fixture**: 34 real Click programs (`tests/fixtures/tumbler/`), each pairing the internal `.scr` program file with a clipboard capture of the same program; `decode_program()` output is regression-tested byte-identical against the clipboard CSVs.
- **Devtools**: `compare_csv.py` normalizes `R` vs `R1`/`R2` rung markers before comparing, so scr-derived and clipboard-saved CSVs diff cleanly.

## 0.1.9

### Added
- **Time drums**: encode and decode all five time bases (`Tms`/`Ts`/`Tm`/`Th`/`Td`), plus jog and jump, matching event drums.
- **CSV writer**: `write_csv(path, rungs, index=True)` emits 1-based sequential rung markers (`R1`, `R2`, `R3`, …) instead of plain `R`; readers accept `R` optionally followed by digits, so indexed files still round-trip.

### Fixed
- **Drum decode**: single-step event and time drums now decode from `Scr*.tmp` files instead of falling back to `RawInstruction`.
- **Drum decode**: a stray NOP stranded on a drum's pin row is dropped instead of surfacing as a spurious `NOP` that broke `write_csv`.
- **CSV writer**: a tall instruction (drum, timer, counter, …) with a wire branch or content running below its body keeps its rows positional instead of collapsing the following rows up, fixing `WriterError`/lost geometry on those rungs.

### Performance
- `decode_program()` is ~48% faster — topology block scanning uses `bytes.find()` instead of byte-by-byte iteration, and hot loops cache `len(data)` and precomputed constants.
- `encode()` is ~35% faster — cell headers use a single pre-compiled `struct.Struct.pack` instead of 8 separate calls, and Math blobs use pre-computed empty slot bytes instead of 1000 per-instruction loop iterations.

## 0.1.8

### Fixed
- **CSV writer**: downgrade trailing blank row mismatch from error to warning
  when a tall instruction's stripped continuation absorbs extra blank rows on
  read-back — fixes `WriterError` on rungs with blank rows beyond an
  instruction's visual height

## 0.1.7

### Fixed
- **SCR decode**: skip pure vertical pass-through rows in implied modifier
  row fallback, preventing `|` → `T` and blank → `-` corruption on
  continuation rows
- **CSV converter**: recognize `Contact`/`CompareContact` objects with
  `wire_down=True` during wire hydration, not just bare string tokens

### Changed
- **SCR decode**: remove `_implied_modifier_row_offsets` fallback — SCR
  continuation row topology already encodes per-row horizontal connectivity
  explicitly, verified across 883 rungs in 47 SCR files

## 0.1.6

### Fixed
- **SCR decode**: replace backward/brute-force topology block scanning with a
  single forward pass, fixing false positive matches from flag-table tail bytes
  that caused spurious empty rungs with inflated row counts

## 0.1.5

### Changed
- **Encode**: remove AF summary block — Click accepts multi-AF rungs without
  it, eliminating complex gating logic
- **CSV**: consolidate tall-instruction padding into shared hydrate/dehydrate
  helpers in converter and writer

### Added
- **Devtools**: `combine_coverage.py` — combine random coverage fixtures into
  a single multi-row rung for paste smoke-testing
- **Devtools**: `coverage_golden.py` now regenerates all bins unconditionally

## 0.1.4

### Fixed
- **CSV**: preserve multi-row AF round-trips, including pinned/tall AF blocks
  away from row 0, multiple tall blocks in one rung, and generic tall
  continuation rows
- **SCR decode**: restore omitted wiring for generic tall AF continuation rows
- **CSV writer**: fail loudly when emitted CSV rows lose decoded rung
  semantics by reparsing writer output and checking for row, condition, or AF
  mismatches before writing to disk

## 0.1.3

### Fixed
- **RTF decode**: parse RTF comments structurally instead of regex-based
  stripping, handling nested groups, font/color tables, and style toggles
  correctly
- **RTF decode**: handle `\uN` unicode escape sequences (signed 16-bit) and
  validate `ansicpg1252` before decoding
- **CSV**: preserve quoted string literals in AF token positional args — e.g.
  `copy("d",TXT1)` no longer loses its quotes during parse
- **Search instruction**: store text-search operands with quotes end-to-end,
  removing the strip-on-decode/re-add-on-encode anti-pattern

### Added
- **Encode**: auto-sanitize non-ASCII characters (curly quotes, em-dashes,
  arrows, etc.) in rung comments before RTF conversion via NFKD normalization


## 0.1.2

### Fixed
- **Math**: preserve duplicate operands and normalize parenthesis spacing

## 0.1.1

### Fixed
- **Encode**: correct `row_span` for tall AF instructions and single-rung list
  routing

## 0.1.0

Initial release. Originally prototyped in
[clicknick](https://github.com/ssweber/clicknick), then developed into a
standalone library here.

- Encode `Rung` objects or CSV into Click clipboard binary
- Decode clipboard binary back into structured Python objects
- Decode `Scr*.tmp` program files into `Program` objects
- All standard Click instruction types supported natively
- `RawInstruction` passthrough for unknown blob types
- Zero runtime dependencies
