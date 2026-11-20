# Changelog

<!-- Entries follow the CHANGELOG rule in the bob plugin's `writing` skill: say what
     changed for the user and what they must do, in two or three short sentences.
     Breaking changes may be longer. State each entry against the last release. -->

## Unreleased

### Added
- **One error tree.** Every error that `decode()`, `decode_program()`, `encode()`, `read_csv()`, `write_csv()` and `check()` raise for input they can't read or write is now a `LaddercodecError`. Each is still a `ValueError`. `read_csv` and `read_bundle` raise `CsvReadError`. `write_csv`, `csv_rows` and `write_bundle` raise `CsvWriteError`. The other classes are `DecodeError`, the new `EncodeError`, and `FieldError` with its subclass `AddressError`.
- **More top-level exports.** `laddercodec` now exports `LaddercodecError`, `DecodeError`, `EncodeError`, `CsvReadError`, `CsvWriteError`, `UnknownCondition`, `UnknownInstruction`, `Email`, `Home`, `PositionMove`, `VelocityMove`, `Condition`, `Instruction`, `ConditionToken`, `InstructionToken` and `replace`.
- **A `Literal` alias for each fixed set of field values.** `laddercodec` and `laddercodec.instructions` now export an alias that lists the values of each instruction field that accepts only a fixed set: `ContactKind`, `CompareOp`, `CoilKind`, `OutVariantKind`, `OutVariantUnit`, `TimerKind`, `TimeUnit`, `CounterKind`, `DrumKind`, `MathMode`, `CopyConvert`, `BlockCopyConvert`, `PackKind`, `UnpackKind`, `ModbusRtuPort`, `ModbusTcpPort`, `ModbusRegisterType`, `SendFunctionCode`, `ReceiveFunctionCode` and `UndecodedStop`. `typing.get_args(laddercodec.ContactKind)` returns `("no", "nc", "rise", "fall")`.
- **Undecoded markers.** When `decode()` or `decode_program()` can't read a rung, they now return an `Undecoded` marker for it and emit an `UndecodedRungWarning`. The other rungs still decode. The marker acts as `end()` in the main program and `return()` in a subroutine. `Program.undecoded` lists the markers. `write_csv` and `read_csv` round-trip a marker as an `undecoded(...)` token. `encode()` rejects a marker, and `check()` reports it as an `undecoded-rung` finding.
- **CSV errors say where.** An error from `read_csv` now has a `CsvLocation` (file, line, rung, row and column) as its `location`, and its message ends with it. Each refusal in `.errors` has its own `location`.
- **Field errors say why.** A `FieldError` now has `reason` (a `Reason` such as `bank`, `range` or `conflict`), `click_id` (CLICK's own id, such as `OBJ-005`, when CLICK has one), `fields` (one field, or both fields of a pair) and `errors` (every refusal for the construction, the raised one first).
- **`RefusedFieldWarning` and `read_csv(..., unchecked=True)`.** `decode()` and `decode_program()` emit a `RefusedFieldWarning` for each instruction that holds a value CLICK's dialog refuses. `read_csv(..., unchecked=True)` reads such an instruction as written, with the same warning.
- **`allow=` on `read_csv()` and `read_bundle()`.** `read_csv(path, allow=["bank-not-allowed"])` reads an instruction whose refusals all have a code that you list, and emits no warning for it. `encode()`, `write_csv()` and `write_bundle()` write such an instruction from its fields. A refusal raises as it does without `allow=` if you don't list its code, or if laddercodec can't write the instruction and read it back the same.
- **`constant_text()`.** It returns the text that a `Math` or `Copy` source stores for a Python int, float or str. `constant_text(255, hex=True)` is `FFh`.
- **`csv_rows()` and `CSV_HEADER`.** `csv_rows(rungs, *, index=False, stop="end")` returns the rows that `write_csv` writes after the header, each as a list of strings. You can use them without writing a file. `laddercodec` also exports `CSV_HEADER`, the header row, as a tuple of strings.
- **`write_bundle()` and `read_bundle()`.** `write_bundle(directory, project, *, index=False)` writes a `Project` as `main.csv` and one `subroutines/<name>.csv` for each subroutine. `read_bundle(directory, *, strict=True, unchecked=False, allow=())` reads that folder back into a `Project`. An error from any file has that file in its `CsvLocation`.
- **`lay_out()` and the circuit types.** `laddercodec` now exports `lay_out()`, the circuit types `Circuit`, `Branch`, `Box`, `Series`, `Parallel` and `Term`, and `LayoutError`. `lay_out(circuit)` returns the rungs that CLICK's syntax check draws for a circuit that you build from these types. For a circuit that CLICK can't hold, such as one of more than 32 rows, `lay_out()` raises `LayoutError`.
- **`CsvWriteError.code` and `CsvWriteError.click_id`.** `CsvWriteError` now has `code` and `click_id`, as `CsvReadError` has. When two subroutine names are equal with the case of A-Z ignored, such as `Pump` and `pump`, `write_bundle` raises a `CsvWriteError` and `read_bundle` raises a `CsvReadError`, and both have the code `duplicate-subroutine-name` and the `click_id` `GUI-036`. `é1` and `É1` are two names. `write_bundle` refuses them with a `CsvWriteError` that has no `code`, because their files would be one file on a file system that ignores case.
- **`message()`, `short()` and `detail()`.** `LaddercodecError` now has `message(names)`, `short(names)` and `detail(names)`. With `names={"C1": "Valve"}`, `message()` returns `Copy.dest: Valve (C1) can't take DS1; ...` for a Copy of DS1 into C1. `short()` and `detail()` split that text for you to show next to the field, so they say `this field` where `message()` names the field.
- **`addresses()`.** `addresses(payload)` returns every address that a `Rung`, a list of rungs or clipboard bytes uses, including the ends that CLICK works out, such as TXT5 for a Copy of `"HALLO"` into TXT1. CLICK drops each pasted operand whose address is not in the project, so add these addresses to the project first. See [Add The Addresses Before You Paste](https://pyrung.com/laddercodec/guides/encoding/#add-the-addresses-before-you-paste).
- **`Send.from_csv_token()` and `Receive.from_csv_token()`.** `Send.from_csv_token()` and `Receive.from_csv_token()` read a `send(...)` or `receive(...)` CSV token and return the instruction, as `Coil.from_csv_token()` does for `out(...)`. They raise the same `CsvReadError` or `FieldError` that `read_csv` raises for the same token.

### Fixed
- **Raw boxes from program files.** A `raw(...)` box that `decode_program()` reads, and its `raw(...)` token in `write_csv`, now hold the blob that CLICK writes to the clipboard for it: every tag in CLICK's order, with a set flag as `-1` in a Copy, Drum, Math or Search and `1` in any other class. A box that laddercodec can't read as an instruction of its class keeps only the tags that the program file stores, with each flag written the same way. v0.4.0 wrote only the stored tags for every such box, with a set flag as an empty value.
- **Fill of hex above `FFFFh`.** `Fill` and `fill(...)` now raise `FieldError` with `OBJ-005` for a hex constant above `FFFFh` into every bank. v0.4.0 accepted up to `FFFFFFFFh` in every bank. To fill a larger value, write it as an integer.
- **Fill of a number into TXT.** `Fill` and `fill(...)` now raise `FieldError` for an integer or hex constant of more than one character into TXT, such as `-5`, `123` or `10h`. v0.4.0 accepted them. A digit such as `5` and a real such as `1.5` are still accepted.
- **For count `-0`.** A For count of `-0` is now accepted and stored as `0`, from `ForLoop(count="-0")` and from `for(-0)`. v0.4.0 raised `AddressError`. A sign on any other count still raises.
- **Event drum `unit`.** `Drum(kind="event_drum", unit="Ts", ...)` and `event_drum(...,unit=Ts)` now raise `FieldError` with the code `option-not-offered`, because an event drum has no time unit. v0.4.0 accepted the unit and wrote nothing for it, and `read_csv` ignored it. To fix it, leave `unit` blank.
- **Copy conversions that CLICK saves.** A single Copy between DF and CTD, of a real constant into DD or CTD, or of an integer constant outside int16 into DF now encodes with conversion type 7, as CLICK saves it. `convert=to_binary` on these copies now works. v0.4.0 wrote a plain copy and rejected `to_binary`. CLICK's saves of these copies now decode as the `Copy`. v0.4.0 decoded them as `raw(Copy,...)`.
- **Copy into TXT.** A single Copy of a number constant into TXT now writes the last TXT its text fills, as CLICK does. The last TXT counts the real in the form that CLICK stores. `10000000000.0` into TXT1 is stored as `1E+10` and fills TXT1..TXT5. `1.0E+16` into TXT996 fills TXT996..TXT1000. A real constant or a DF pointer to text now writes real numbering, or exponential numbering with `exponential=1`. CLICK's saves of these copies decode as the `Copy`.
- **Copy, Compare and Search text.** A single Copy source, the right side of a `CompareContact` or a Search value of quoted text now accepts any character from U+0001 to U+FFFF except a surrogate. `read_csv` accepts a line break inside the quotes. v0.4.0 rejected both. All three still reject NUL and characters above U+FFFF.
- **A quote inside a Copy, Search or Compare text.** A single Copy source, a Search value and either side of a `CompareContact` now accept a quote inside quoted text. In CSV the text runs as typed from its first quote to its last: `copy("A"B",TXT1)` writes TXT1 to TXT3, `search(TXT1..TXT10 == "A",B",result=DS30,found=C1)` searches for the four characters `A",B`, and `TXT1=="A"B"` compares TXT1 to TXT3 with `A"B`. In v0.4.0, `Copy()`, `Search()`, `CompareContact()` and `read_csv` raised `FieldError` or `ValueError` for these, and `decode()` read CLICK's saves of them as raw instructions or unknown conditions.
- **One-digit character codes.** The right side of a `CompareContact` and a `Search` value now accept `$` and one hex digit, such as `TXT1==$1`, and keep it as typed. v0.4.0 rejected it. The left side of a `CompareContact` still rejects it.
- **Copy from an SD pointer.** A single Copy now accepts an SD pointer such as `SD[DS1]` as its source. It still refuses one as the destination. v0.4.0 raised `AddressError` for `copy(SD[DS1],DS1)`.
- **Copy past TXT1000.** A number constant copied to text that runs past TXT1000, such as `-5` into TXT1000, now raises `AddressError` with `OBJ-003`. v0.4.0 accepted it.
- **Termination codes into TXT.** A single Copy into TXT of a TXT register, quoted text, a decimal integer or a real now accepts `termination_code=$0D`, such as `copy("AB",TXT1,termination_code=$0D)` and `copy(5,TXT1,convert=to_text(suppress_zero=1,termination_code=$0D))`. A Block Copy of TXT into TXT keeps its code through `decode()`, `encode()` and `read_csv`, where v0.4.0 dropped it. v0.4.0's `Copy()` rejected these codes, and its `read_csv` rejected a code inside `to_text` and dropped a code outside `convert`, as in the first example.
- **Addresses that CLICK saves as typed.** An address such as `DS001`, `ds1` or `YD0U` in a Copy destination, a Math formula, a hex Math result, the right side of a Compare, or a Search's table start or result now decodes as the instruction, in display form. An address with a space at either end decodes the same way in the right side of a Compare or a Search's result. v0.4.0 decoded a Copy, Math or Search as `raw(...)` and a Compare as an unknown condition.
- **Empty flag fields.** `decode()` now emits a `LegacyEncodingWarning` for each flag field that is stored empty and that encoding the rung again writes set, such as `Coil.oneshot`. v0.4.0 gave no warning, and it decoded an empty one-shot or immediate flag as clear. Encode the rung again and paste it, so that CLICK runs the flag as `decode()` reads it.
- **`check()` findings.** A contact in parallel with a wire-only leg is now `C0002`. v0.4.0 reported it with no CLICK id. A contact that feeds only a `NOP` is now `C0003`, with the new code `contact-feeds-only-nop`. A timer's or counter's reset with nothing wired is now an `unwired-input` finding, `C0202`. v0.4.0 reported neither. An instruction fed from the net of another box's pin now has the new code `shared-input-net`, `C000A`. v0.4.0 reported a pin finding for it. An output above a box with a used pin is now `C000A` when it hangs off any net of the box's main input circuit, such as the net between `X001` and `X003` when they feed a timer in series. v0.4.0 reported it only on the box's main input net.
- **Hex Math `1E3h`.** A hex `Math` holding `1E3h`, which CLICK stores for a constant typed `1e3`, now decodes as the `Math`, and `read_csv` reads it. v0.4.0 decoded it as `raw(Math,...)` and `read_csv` rejected it.
- **Bare `TypeError`, `AttributeError`, `ValueError` and `KeyError` crashes.** An instruction now raises `FieldError` for a field of the wrong type, such as `Contact(5)` or `Coil(None)`, and for a `CompareContact` operator that is not `==`, `!=`, `<`, `>`, `<=` or `>=`. A number of more than 4300 digits in a constant, For count, Timer set point, Drum preset, Slave ID, `ModbusAddress`, Modbus target, Send or Receive range, `function_code=`, `raw(...)` token or `undecoded(...)` token now reads as its value or raises `FieldError`. v0.4.0 raised `TypeError` or `AttributeError` for the wrong type, `ValueError` for the digits and `KeyError` for the operator.
- **More rejections carry CLICK's id.** Many rejections that had no `click_id` now have one. For example, a Pack destination in a bank that Pack never writes, such as `X001`, now has `OBJ-004`. A Pack destination whose bank can't take the source, such as `C1..C16` into `TD1`, now has `OBJ-024`. laddercodec rejects the same values as before.
- **Rungs of more than 32 rows.** For a rung that needs more than 32 rows, `read_csv` raises `CsvReadError` and `write_csv` raises `CsvWriteError`, both with the code `layout-too-tall`. `read_bundle`, `csv_rows` and `write_bundle` raise the same errors, and `check()` reports a `layout-too-tall` finding. v0.4.0 read and wrote such a rung, and `check()` reported nothing.
- **Long strings in program files.** `decode_program()` now reads a Compare or Search text of 127 characters or more, such as one of 130 characters. v0.4.0 decoded the Compare as an `UnknownCondition` and the Search as `raw(Search,...)`.
- **No partial file from `write_csv`.** When `write_csv` raises `CsvWriteError` for a rung, it now creates no file and leaves a file already at the path unchanged. v0.4.0 left a file that held only the header and the rows before that rung, in place of any file that was there.
- **Comments in which one style follows another.** A comment such as `*a***b**` now encodes as an italic `a` and then a bold `b`. v0.4.0 encoded the `b` as italic, not bold.

### Changed
- **`parse_bundle` file order.** `laddercodec.csv.bundle.parse_bundle` now lists the subroutine files sorted by name with case ignored, the same on every OS. It now lists a file named `.csv`, and reads `subroutines/main.csv` as a subroutine. v0.4.0 sorted by path, which ignores case only on Windows, skipped `.csv`, and read `subroutines/main.csv` as the main program.
- **Receive TXT count.** A Receive into TXT now accepts an even count of 2 to 250 characters, as CLICK does. v0.4.0 rejected a count over 124.
- **Refusal order.** A single `Copy` whose constant source is invalid now raises `FieldError` on `Copy.source` before laddercodec checks the destination. v0.4.0 raised `AddressError` on `Copy.destination` for `copy("",DS1)`. An Out, Set or Reset range whose end is in another bank now raises `FieldError` with reason `conflict` and `OBJ-008`. v0.4.0 raised `AddressError` on `Coil.range_end`.
- **`FieldError.field` names more fields.** It is `Class.attr` of the instruction refused, such as `Send.quantity` or `ModbusTcpTarget.port`, for more refusals than in v0.4.0.
- **One refusal for a refused range.** When both ends of a range are in a bank that the field does not accept, such as `C1..C2` as a Fill destination, or both are out of their bank's range, laddercodec now raises one refusal for the range. Its message names the range once, `'C1..C2' is not allowed`, and its `fields` holds both ends. v0.4.0 named only the start, `'C1' is not allowed`.
- **Unpack names the banks of its kind.** When an `Unpack` destination can't take its source, the message now names the banks that this kind of unpack writes from that source, such as `an unpack to bits from DD goes to C`. v0.4.0 named the banks of both kinds, `an unpack from DD goes to C, DS, DH`.
- **Reworded messages.** Many error and warning messages now say what to do after they state the rule. When CLICK has an id for the refusal, such as `(OBJ-004)`, the id ends the sentence that states the rule. Match on `field`, `code`, `reason` or `click_id` instead of the message text, because the wording does not change them.
- **Undecoded comments.** A comment that doesn't decode now reads `UNDECODED comment: <error>`, followed by the plain text that could be read. `encode()` writes that text back into CLICK.
- **CSV format guide.** The guide no longer describes pyrung's exporter. Its sections "Subroutine tail guarantee" and "Strict validation and failure mode" are gone. Three sections have new names and anchors: "`Or(...)` expansion" is "OR legs", "Builder pin continuation rows" is "Pin continuation rows" and "For-loop lowering" is "For loops". Update any link to them.
- **Docs site follows releases.** The published docs now update when a release is published, not on every change to `main`.

### Behaviour changes
Several entries below say that laddercodec now rejects a value. That applies when you build an instruction or read one from CSV. A program that CLICK saved with such a value still decodes. `decode()` emits a `RefusedFieldWarning` for it, and the instruction encodes unchanged.

- **`decode()` always returns a list.** It now returns a `list[Rung]` even when the clipboard holds one rung. v0.4.0 returned the `Rung` itself in that case.
  - Do: Unpack a single rung with `[rung] = decode(data)`. Remove any `isinstance(result, list)` check.
- **`Contact` and `Coil` are built by kind, with the operand first.** `Contact(operand, kind="no", immediate=False)` takes `kind` `"no"`, `"nc"`, `"rise"` or `"fall"`. `Coil(operand, kind="out", range_end=None, immediate=False, oneshot=False)` takes `kind` `"out"`, `"latch"` or `"reset"`. v0.4.0 took an `InstructionType` as `type`, first, and `edge_kind` for an edge contact. Errors now name `Contact.kind` and `Coil.kind`.
  - `Contact(InstructionType.CONTACT_NC, "X001")` → `Contact("X001", kind="nc")`
  - `Contact(InstructionType.CONTACT_EDGE, "X001", edge_kind="rise")` → `Contact("X001", kind="rise")`
  - `Coil(InstructionType.COIL_LATCH, "Y001")` → `Coil("Y001", kind="latch")`
  - Do: Pass `immediate`, `range_end` and `oneshot` by keyword. Read `.kind` where you read `.type` or `.edge_kind`.
- **Immediate edge contacts raise `FieldError`.** `read_csv` of `rise(X001).immediate` and `Contact.from_csv_token` now raise `FieldError` with reason `conflict`. v0.4.0 raised `ValueError`. With `unchecked=True` the contact is kept as written.
  - Do: Catch `FieldError`, or `ValueError`, for these.
- **Errors use the new classes.** `encode()` raises `EncodeError` where v0.4.0 raised a bare `ValueError`, and it raises `EncodeError` for an `Undecoded` marker. `read_csv` raises `CsvReadError` where v0.4.0 raised a bare `ValueError`. `decode_program()` raises `DecodeError` for a file header or program name it can't read. v0.4.0 raised `ValueError` for the header and `UnicodeDecodeError` for the name. All of these are still `ValueError`.
  - `ConvertError` → `CsvReadError`. `laddercodec.csv.converter.ConvertError` is gone.
  - `WriterError` → `CsvWriteError`. `laddercodec.csv.writer.WriterError` is gone.
  - Do: Catch `CsvReadError` where you caught `ConvertError`, and `CsvWriteError` where you caught `WriterError`. `except ValueError` needs no change.
- **Five instruction names are new.** In `laddercodec.instructions`, `Position` is now `PositionMove`, `Velocity` is now `VelocityMove`, and the type alias `AfToken` is now `InstructionToken`. The base classes `ConditionInstruction` and `AfInstruction`, in `laddercodec.model` and `laddercodec.instructions`, are now `Condition` and `Instruction`. The CSV tokens, such as `raw(Position,...)`, do not change.
  - Do: Import the new names from `laddercodec`.
- **Some errors are now `ValueError`s.** `read_csv` raises `CsvReadError` for a file that isn't UTF-8 and for a `csv.Error`. v0.4.0 raised `UnicodeDecodeError` and `csv.Error`. A `send` or `receive` with no `target=` or `remote_start=` raises `CsvReadError`. v0.4.0 raised `KeyError`. `encode()` raises `EncodeError` for a rung holding an `UnknownCondition` or `UnknownInstruction`, or for an output cell that is neither a string nor an instruction, such as `None`. v0.4.0 raised `TypeError` or `AttributeError`.
  - Do: Catch `CsvReadError`, or `ValueError`, where you caught `UnicodeDecodeError`, `csv.Error` or `KeyError` around `read_csv`.
- **A rung that doesn't decode no longer fails the call.** A down wire in the output column, or a wire flag that no token matches, now gives an `Undecoded` marker for that rung. A clipboard row or program record that can't be read gives one marker for that rung and every rung after it. v0.4.0 raised `DecodeError` or `ValueError`. A wrong magic, size or program header still raises `DecodeError`. A comment that doesn't decode keeps its rung and emits an `UndecodedCommentWarning`. v0.4.0 raised `DecodeError` in `decode()`.
  - Do: Check `Program.undecoded` where you caught those errors. Catch `UndecodedRungWarning` and `UndecodedCommentWarning` if you need to know.
- **`write_csv` writes a marker for a rung it can't write.** A rung holding an unknown condition or instruction, or a compare whose cell reads two ways such as Data A `"A"=="B"` with Data B `"C"`, is now written as an undecoded marker, with an `UndecodedRungWarning`. v0.4.0 decoded that compare as an unknown condition and raised `WriterError` for both rungs.
  - Do: Pass `stop="return"` when you write a subroutine.
- **`read_csv` raises `CsvReadError` for a compare cell that reads two ways.** In a cell of two texts such as `"A"=="B"=="C"`, two operators each leave a text on both sides, so the cell reads as two compares. v0.4.0 raised `FieldError` or `ValueError` for it.
  - Do: Catch `CsvReadError`, and put a TXT register on one side, such as `TXT1=="C"`.
- **`read_csv` and `write_csv` drop a `NOP` fed from the rail.** When a rung has another output, they now drop a `NOP` that the rail feeds with no contact, and lay out the rest of the rung. CLICK's syntax check does the same. v0.4.0 kept such a rung as drawn, so a rung of `X001 -> out(Y003)`, `X002 -> out(Y004)` and a rail wire to `NOP` read as one rung, and it now reads as two.
  - Do: Expect no `NOP` in such a rung, and one rung for each output whose circuit meets the others only at the rail.
- **A stored value that CLICK's dialog refuses no longer makes a cell raw.** `decode()` and `decode_program()` now decode the instruction and emit a `RefusedFieldWarning`. v0.4.0 decoded it as `raw(...)` or an unknown condition. If you change such an instruction with `replace()`, `replace()` raises the `FieldError` that building it would raise.
  - Do: Nothing, to decode and encode a rung unchanged. Catch `RefusedFieldWarning` to find these instructions. Fix the field it names before you encode one that you read from CSV.
- **Math and Copy constants are written as CLICK stores them.** A real in a `Math` or a single `Copy` source is now the value CLICK prints back, so `1.50` is `1.5` and `1e3` is `1000.0`. Hex has uppercase digits (`0ffh` is `0FFh`), and a `Copy` drops leading zeros and a typed `+`. `to_csv()`, `write_csv` and `encode()` write that form. A `Math` real that CLICK cuts when it is typed in positional form, such as `0.00012345`, is written in its `E` form, `1.2345E-04`. A `Copy` real is written as CLICK prints its value with 7 significant digits, however you typed it. `1.0E+16` is `1E+16` and `1.0E+06` is `1000000.0`. v0.4.0 kept the typed text. `copy(EH,...)` and `copy(1Eh,...)` now raise `FieldError`. v0.4.0 read them as hex 14 and 30, but CLICK stores them as the reals 0.0 and 1.0.
  - Do: Compare constants in CLICK's form, or build both sides through the instruction.
  - Do: Write `0.0` or `14` where you wrote `EH`. Write `1.0` or `30` where you wrote `1Eh`.
- **Reals that CLICK saves cut.** A real constant with more than 7 significant digits in a single `Copy` (`copy(1.2345678,DF1)`) now raises `FieldError` with reason `form`. So does a real in a decimal `Math` that CLICK saves as another value (`0.33333334` is saved as `0.333333`), and the message names the text that CLICK saves and the constant to write. [Operand normalization notes](https://pyrung.com/laddercodec/guides/csv-format/#operand-normalization-notes) lists the forms that CLICK keeps. v0.4.0 wrote the constant as typed, and CLICK saves it cut. A decimal `Math` real above float32's largest value, such as `3.4028235E+38`, now raises `FieldError` with `OBJ-1009`. v0.4.0 accepted `3.4028235E+38` and rejected a larger real with no id.
  - Do: Write the constant that the message names. Write `3.402823E+38` for float32's largest value in a `Math`.
- **`to_text` for a real constant or a DF pointer takes `exponential`.** Write `to_text(exponential=0)` or `to_text(exponential=1)`, as for a DF address. `suppress_zero` on a real constant, a DF pointer or a DF address now raises `FieldError` with reason `conflict`. v0.4.0 accepted it. `Copy.suppress_zero` is now `None` by default for these sources.
  - Do: Write `exponential=0` where you wrote `suppress_zero` for a real constant or a DF pointer. Drop `suppress_zero` for a DF address.
- **A number into TXT needs a converter.** A single Copy of a number constant, register or pointer into TXT with no converter, such as `copy(5,TXT1)`, now raises `FieldError` with reason `conflict`. v0.4.0 accepted it and wrote a plain copy, which CLICK never saves.
  - Do: Write `convert=to_text(suppress_zero=1,termination_code=none)`, CLICK's default. For a real constant or a DF source, write `convert=to_text(exponential=0,termination_code=none)`.
- **TXT into a number needs `to_value` or `to_ascii`.** A plain single Copy of TXT into DS, DD, DH, YD, TD, CTD or SD, and a plain Block Copy of TXT into DS, DD or DH, now raise `FieldError` with reason `conflict`. So do a single Copy of TXT into DF with `to_value` or `to_ascii`, a `Copy` from TXT with `suppress_zero=True`, and a Block Copy of TXT into TXT with `to_value` or `to_ascii`. v0.4.0 accepted all of these. A TXT register into DF stays a plain copy.
  - Do: Write `convert=to_value` for the character's value, or `convert=to_ascii` for its ASCII code. Drop the converter or `suppress_zero` in the other cases.
- **A termination code only where CLICK offers one.** `read_csv` now raises `FieldError` with reason `conflict` for `termination_code=$XX` on a `copy` or `blockcopy` that is not into TXT, and on a single Copy of a `$hh` code into TXT, such as `copy($41,TXT1,termination_code=$0D)`. v0.4.0's `read_csv` dropped the code without a word. Its `Copy()` already rejected these codes.
  - Do: Drop the code, or write it inside `to_text(...)` or `to_binary(...)` for a number copied to TXT.
- **An unknown keyword raises `CsvReadError`.** A keyword that `copy`, `blockcopy`, `fill`, `pack_*` or `unpack_to_*` does not accept, such as a misspelt `terminaton_code=`, now raises `CsvReadError`. v0.4.0 dropped the keyword and its value.
  - Do: Spell the keyword as the docs do. Put `suppress_zero` and `exponential` inside `to_text(...)`.
- **`send` and `receive` refuse arguments they can't read.** `read_csv` now raises `CsvReadError` for an argument of a `send`, a `receive`, a target or a `ModbusAddress(...)` that has no keyword, is written twice, is not one of the call's keywords, is empty, or runs into the next argument because a comma is missing. v0.4.0 dropped these or read them into another field, and for a target that is neither a `ModbusTcpTarget(...)` nor a `ModbusRtuTarget(...)` it raised a plain `ValueError`.
  - Do: Write each argument once, as `keyword=value`, with a comma between arguments.
- **A quote in a Modbus target name is written twice.** `Send.to_csv()`, `Receive.to_csv()` and `write_csv` now write each `"` in a target's name as `""`. `read_csv` reads `name="a""b"` as the name `a"b`. v0.4.0 wrote the quote once and read `""` as two quotes, so a file that v0.4.0 wrote for such a name now raises `CsvReadError` or reads another name.
  - Do: Double each quote inside a name.
- **A Compare rejects a real outside float32.** A `CompareContact` with a real constant that float32 can't hold, such as `DF1==3.5E+38`, now raises `FieldError` with `OBJ-005`. v0.4.0 accepted it. A `Search` value of such a real raised `FieldError` in v0.4.0, and the error now has `OBJ-005` too.
  - Do: Write a real of at most `3.4028235E+38` in size.
- **A Search value address must be in the table's group.** A `Search` value address outside the table's compare group, such as `search(DS1..DS10 == TXT20,...)` or a DS table with an XD value, now raises `FieldError` with `OBJ-004` and code `search-value-bank`. v0.4.0 accepted it. A Search constant of the wrong kind for the table now has `OBJ-004` too.
  - Do: For a Search value, use an address in the table's group: XD, YD or DH for a DH table, TXT for a TXT table, and TD, CTD, DS, DD, DF or SD for the others.
- **The right side of a Compare rejects `DH`.** When the left side is hex, such as `DH1==DH`, the right side of a `CompareContact` now rejects `DH` in any letter case, with `FieldError` and code `invalid-constant`. v0.4.0 read it as the hex constant D.
  - Do: Write `0DH`.
- **A Pack of text into DH takes 4 characters.** `pack_text(TXT1..TXT16,DH1)` and any other `pack_text` of more than 4 TXT registers into DH now raises `FieldError` with `OBJ-003`. v0.4.0 accepted it.
  - Do: Pack at most 4 TXT characters into a DH.
- **A Pack source is counted before its pairing.** A Pack source that is longer than any pairing accepts now raises `FieldError` on `Pack.source_end` with CLICK's count id, such as `OBJ-041`. v0.4.0 raised `AddressError` on `Pack.destination` with no id.
  - Do: Catch `FieldError` where you caught `AddressError` for these. Read `.errors` for the pairing.
- **Flags reject a non-flag value.** A flag of `Copy`, `BlockCopy`, `Fill`, `Pack`, `Unpack`, `Search`, `Math`, `ForLoop`, `OutVariant`, `Send` or `Receive` now raises `FieldError` with reason `flag` for anything but True, False, 1 or 0. v0.4.0 accepted it and wrote `oneshot=2` as `oneshot=1`. In CSV, a flag such as `oneshot=yes` raises the same error. A blank flag, such as `oneshot=`, raises it with reason `missing`. v0.4.0 read both as off, and raised `ValueError` for them in `out`, `for` and `timed`. A `Pack` of bits or words with `allow_whitespace=True` now raises `FieldError` with reason `conflict`. v0.4.0 accepted it and did not encode it. In CSV, `allow_whitespace=` in `pack_bits` or `pack_words` raises `CsvReadError`.
  - Do: Pass True, False, 1 or 0. In CSV, write `1` or `0`.
  - Do: Drop `allow_whitespace` for `pack_bits` and `pack_words`.
- **A Send's slave register must match its source.** With CLICK addressing, a `Send` whose `remote_start` is of another data type than its `source`, such as `remote_start="DH1"` with `source=DS1`, now raises `FieldError` with reason `conflict` and `OBJ-004`. A `Send` to any SD register now raises `FieldError` with reason `not_writable` and `OBJ-004`. v0.4.0 accepted both.
  - Do: Write to DS or TD from DS, TD or SD, to DD or CTD from DD or CTD, to DF from DF, to DH or YD from DH, XD or YD, and to TXT from TXT.
- **A Send from TXT counts characters.** A `Send` from TXT with FC16 now accepts an even count of 2 to 246 characters, or fewer after a hex start, and raises `FieldError` with `OBJ-010` outside that range or `OBJ-029` for an odd count. v0.4.0 counted TXT in registers and accepted 1 to 123.
  - Do: Send an even number of TXT characters, such as `source=TXT1..TXT20`. Send one TXT register with FC06.
- **A Send to a hex address checks its count.** A `Send` to a hex `remote_start` now raises `FieldError` with `OBJ-010` when its count runs past `FFFDh` from DD, DF or CTD, or past `FFFEh` from any other register bank. Each element, and each TXT character, counts as one address. v0.4.0 checked this only for a DD source.
  - Do: Lower the count or the start address.
- **Word Swap only where a Send offers it.** `word_swap=True` on a `Send` now raises `FieldError` with reason `conflict` and code `option-not-offered` unless the Send uses FC16. It raises the same error for a TXT source, and for a count of 1 from DS, DH, TD or SD. v0.4.0 accepted it.
  - Do: Drop `word_swap=1`.
- **A blank CSV argument raises `FieldError`.** A blank argument now raises `FieldError` with reason `missing` and the blank `field`, as in `out()`, `unit=`, `mode=`, a drum's `outputs=`, a Modbus `target=` and `search(,result=DS1,found=C1)`. v0.4.0 raised a `ValueError` that named no field. An empty required field also raises `FieldError` with reason `missing`.
  - Do: Catch `FieldError`, or `ValueError`, for a blank argument. Read `reason` and `field` to tell a blank from a bad value.
- **Hex Math and SD writes follow CLICK.** A hex `Math` formula that holds a DS register, or a bit in a `SUM`, now raises `FieldError` with `OBJ-1002`. An SD register that a program can't write now raises `FieldError` with reason `not_writable` as a `Copy` destination, in a `BlockCopy` or `Fill` destination range and as a decimal `Math` result. A `Fill` into `SD29..SD38` raises it with `OBJ-004`, because SD30 is read-only. v0.4.0 accepted all of these.
  - Do: Change the value before you build or read the instruction.
- **Each Math mode accepts its own banks.** A hex `Math` formula accepts hex constants and the DH, XD and YD registers. A decimal one accepts decimal constants and the DS, DD, DF, TD, CTD and SD registers, and X, Y, C, T and SC bits as the range of a `SUM`. Any other address now raises `FieldError` with `OBJ-1002` and reason `bank`. v0.4.0 accepted some of them, such as a DD register in a hex formula and a DH register in a decimal one.
  - Do: For a hex formula, copy the register into a DH first, or use a decimal `Math`.
  - Do: For a decimal formula, copy a DH, XD, YD or TXT register into a DS first, or use a hex `Math`.
- **`RAND` bounds follow CLICK.** A decimal `RAND` accepts a DS or DD register or an integer constant as a bound. A hex `RAND` accepts a DH register or a hex constant. A bound of another bank now raises `FieldError` with `OBJ-1002`. A real bound and two equal bounds raise it with `OBJ-1001`. v0.4.0 accepted all of these.
  - Do: Copy the register into a DS, DD or DH first. Write an integer bound. Write two different bounds.
- **`Timer` and `Counter` fields now use their CSV names.** The CSV text and the encoded bytes do not change. `FieldError.field` uses the new names too.
  - `Timer.timer_type`, `Counter.counter_type` → `kind`. Its values are the CSV call names: `on_delay`, `off_delay`, `count_up`, `count_down`.
  - `done_bit` → `done`
  - `current` → `accumulator`
  - `Timer.setpoint` → `preset`
  - Do: Rename the keywords and attributes, for example `Timer(kind="on_delay", done="T1", accumulator="TD1", preset="100", unit="Tms")`.
- **A bad Timer `unit` raises `FieldError`.** A `unit` other than `Tms`, `Ts`, `Tm`, `Th` or `Td` now raises `FieldError` from `read_csv`. v0.4.0 raised `ValueError`. `FieldError` is a `ValueError`, so `except ValueError` still works.
- **`Drum` fields now use their CSV names.** The CSV text and the encoded bytes do not change. `FieldError.field` uses the new names too.
  - `jump_target` → `jump_step`
  - `drum_kind` → `kind`. Its values are now `event_drum`, `time_drum` and `time_event_drum`. v0.4.0 used `event`, `time` and `time_event`.
  - `events_or_presets` → `events` on an event drum, `presets` on a time drum. A time & event drum has both. A drum given the one its kind does not use raises `FieldError` with reason `conflict`.
  - `outputs`, `presets`, `events` and `pattern` are now tuples. A list that you pass in is stored as a tuple.
  - Do: Rename the keywords and attributes, for example `Drum(kind="event_drum", outputs=("C1",), events=("X1",), ...)`. Compare `outputs`, `presets`, `events` and `pattern` with tuples.
- **A bad Drum `unit`, `accumulator` or pattern cell raises `FieldError`.** `read_csv` now raises `FieldError` for a time drum `unit` that is not `Tms`, `Ts`, `Tm`, `Th` or `Td`, for a time & event drum `accumulator` that is blank or not `TD`, and for a pattern cell that is not `0` or `1`. v0.4.0 raised `ValueError`. A time or time & event drum token with no `unit=` raises `CsvReadError`. So does a time & event drum token with no `accumulator=`.
- **`Math`, `Search`, `ForLoop` and `RawInstruction` fields now use their CSV names.** The CSV text and the encoded bytes do not change. `FieldError.field` uses the new names too.
  - `Math.result` → `dest`
  - `Search.comparison` → `op`
  - `Search.source` → `value`
  - `ForLoop.limit` → `count`
  - `RawInstruction.visual_rows` → `rows`
  - `RawInstruction.sub_rows` → `sub`
  - Do: Rename the keywords and attributes, for example `Math("DS1 + 1", dest="DS2")` and `RawInstruction(name, blob, 1, rows=2, sub=3)`. pyrung's `raw()` reads `visual_rows` and `sub_rows` from a decoded `RawInstruction`. It must read `rows` and `sub`.
- **`Copy`, `BlockCopy`, `Pack` and `Unpack` fields now use their CSV names.** The CSV text and the encoded bytes do not change. `FieldError.field` uses the new names too.
  - `Copy.destination`, `Pack.destination` → `dest`
  - `format` → `convert`. Its values are now `None`, `"to_value"`, `"to_text"`, `"to_binary"` and `"to_ascii"`. v0.4.0 used `"none"`, `"value"`, `"text"`, `"binary"` and `"ascii"`.
  - `pack_type`, `unpack_type` → `kind`. Its values are the CSV call names, such as `"pack_bits"` and `"unpack_to_words"`. v0.4.0 used `"bits"`, `"words"` and `"text"`.
  - `Copy.suppress_zero` is now `True`, `False` or `None`, and `Copy.exponential` is `True` or `False`. v0.4.0 used `"0"` and `"1"`, which are no longer accepted. A bad value raises `FieldError` with reason `flag`.
  - Do: Rename the keywords and attributes, for example `Copy("DS1", "TXT1", convert="to_text", suppress_zero=True)` and `Pack("C1", "C16", "DS1", kind="pack_bits")`. Pass `True` or `False` for `suppress_zero` and `exponential`.
- **Every refusal and finding has a `code`.** `FieldError`, `AddressError`, each refusal in `errors` and a `check()` `Finding` now name their rule in `code`. The code is a `Code`, a new exported string enum of kebab-case names such as `bank-not-allowed`. CLICK's own id is in `click_id`. `CLICK_IDS` lists the CLICK ids that each code can come with. The Error codes page of the docs lists every code. Building a `FieldError` or `AddressError` now requires a keyword `code`.
  - Do: Match on `code`, such as `error.code == "bank-not-allowed"`, not on message text. Pass `code=` where you build a `FieldError` or `AddressError` yourself.
- **`Finding.kind` is now `code`, and `Finding.code` is now `click_id`.** A `check()` finding now names its shape in `code` and CLICK's id, such as `C0202`, in `click_id`. v0.4.0 held the shape in `kind` and CLICK's id in `code`. Each shape name now has `-` where it had `_`, and four shapes are renamed:
  - `output_above_pinned_box` → `output-above-box-inputs`
  - `pin_without_contact` → `input-without-contact`
  - `pin_shares_main` → `input-shares-enable`
  - `pin_shares_pin` → `inputs-share-contacts`
  - Do: Read `finding.code` where you read `finding.kind`, and `finding.click_id` where you read `finding.code`. Compare with the new names.
- **`Email`, `Home`, `PositionMove` and `VelocityMove` are provisional.** Their fields are named after CLICK's tag ids, such as `tag_3218`. A later release will rename them.
  - Do: Expect to rename these fields when you upgrade to that release.
- **Instructions are frozen, and `replace()` changes one.** Assigning to a field of an instruction now raises `dataclasses.FrozenInstanceError`, and every instruction is hashable. In v0.4.0 you could assign any value to a field.
  - Do: Write `inst = laddercodec.replace(inst, preset="500")` where you assigned to a field, and put the copy in the rung with `replace(rung, ...)`. `replace()` raises the `FieldError` that building the instruction raises. If you change no field, `encode()` writes the copy as the bytes that the instruction was decoded from.
- **`Rung` is now frozen and stores its rows as tuples, and a contact with a wire down is now `Tee(contact)`.** In v0.4.0 a `Rung` took `logical_rows` first and held lists, and a contact held its wire as `wire_down=True`. Encoded bytes and CSV text (`T:X001`) do not change.
  - `Rung(1, rows, afs, None)` → `Rung(rows, afs, None)`. `logical_rows` is a read-only property, `len(rung.conditions)`.
  - `Contact("X001", wire_down=True)` → `Tee(Contact("X001"))`. `Contact` and `CompareContact` have no `wire_down`, and `Contact.from_csv_token("T:X001")` raises `CsvReadError`.
  - `rung.instructions[0] = coil` → `rung = replace(rung, instructions=[coil, *rung.instructions[1:]])`. Assigning to a field or a cell raises, and a rung is hashable.
  - `decode()` and `decode_program()` return `Tee(UnknownCondition)` for a cell they can't read that has a wire down. v0.4.0 dropped the wire.
  - `encode()` raises `EncodeError` for a `Tee` in column A or on the rung's last row, as it does for `"T"` and `"|"`. v0.4.0 encoded `Contact(wire_down=True)` there.
  - `Rung()` raises `EncodeError` for a text where a row or the instructions list belongs. v0.4.0 encoded `"-" * 31` as a row of one-character tokens.
  - Two rungs that differ only in `comment_rtf` are equal.
  - The alias `DecodedRung` is gone. Use `Rung`.
  - Do: Where you read `wire_down`, test `isinstance(cell, Tee)` and read the contact from `cell.contact`.
  - Do: Compare a rung's rows with tuples, or compare whole rungs.
- **A field with a fixed set of values is annotated with its `Literal` alias.** v0.4.0 annotated the fields below `str` or `int`. A type checker now rejects a plain `str` or `int` in them.
  - `Timer.unit`, `Drum.unit` and `OutVariant.unit`
  - `Copy.convert` and `BlockCopy.convert` (v0.4.0's `format`)
  - `Pack.kind` and `Unpack.kind` (v0.4.0's `pack_type` and `unpack_type`)
  - `Search.op` (v0.4.0's `comparison`)
  - `ModbusRtuTarget.com_port`, `ModbusTcpTarget.com_port` and `ModbusAddress.register_type`
  - `Send.function_code` and `Receive.function_code`
  - Do: Narrow the value to the alias first, for example with `typing.cast(TimeUnit, unit)`.
- **Backslash escapes in comments.** In a comment, a backslash before `*`, `_` or `\` now makes that character text. `decode()` and `decode_program()` now write that backslash where a `*`, `_` or `\` would otherwise read as a style or an escape. v0.4.0 had no escape, so CLICK's text `_x_` decoded as `_x_` and encoded again as an italic `x`.
  - Do: Write `\\` for a backslash that comes before `*`, `_` or another backslash. An underscore inside a word, as in `Pump_1_Run`, and a backslash before any other character, as in `C:\temp`, need no change.
- **Underline inside a word in a decoded comment.** `decode()` and `decode_program()` now drop an underline that covers part of a word, such as `y` in `xyz`, and keep the text. v0.4.0 decoded it as `x__y__z`, which encodes as that text.
- **`*` and `_` next to whitespace in comments.** In a comment, a `*`, `**`, `_` or `__` with whitespace after it no longer starts a style, and one with whitespace before it no longer ends one. So `2 * 3 * 4` and `use _ or _` encode as that text, while `a *b* c` still has an italic `b`. v0.4.0 encoded `2 * 3 * 4` as `2 `, then an italic ` 3 `, then ` 4`, and `use _ or _` as `use ` and then an italic ` or `.
  - Do: To style text between spaced markers, put each marker next to the text, as in `*3*`.
- **Styled whitespace in a decoded comment.** `decode()` and `decode_program()` now leave whitespace unstyled at the edge of a bold, italic or underlined stretch, such as the space in a bold `a `. v0.4.0 decoded it as `**a **`.
- **How the `*` and `_` of a comment pair.** A run of `*` or `_` that can end a style now pairs with the nearest run of the same character before it that can start one, by the rules in [Comment styles and escapes](https://pyrung.com/laddercodec/guides/csv-format/#comment-styles-and-escapes). So `*****WARNING*****` encodes as a bold italic `WARNING`, `*1 see *Auto* mode` as `*1 see ` and then an italic `Auto`, and `*foo**bar*` as an italic `foo**bar`. v0.4.0 encoded the first as a bold `WARNING`, the second as an italic `1 see ` and then `Auto* mode`, and the third as an italic `foobar`.
  - Do: Read back a comment that has three or more `*` or `_` in a row, or one with no partner, and add a backslash where you meant the character as text.
- **Keyword values in quotes in `copy` and `search`.** `read_csv` now raises `CsvReadError` for a keyword value in quotes in a `copy` or `search` call, such as `copy("AB",TXT1,oneshot="1")`. In a `search`, a quoted keyword value before `result=` and `found=` now reads as part of the value's text, so `search(TXT1..TXT10 == "A",oneshot="1",result=DS30,found=C1)` searches for `A",oneshot="1`. v0.4.0 read a quoted keyword value in these calls as the value without its quotes.
  - Do: Write keyword values in `copy` and `search` without quotes.

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
