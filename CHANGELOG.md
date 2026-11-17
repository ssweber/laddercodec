# Changelog

<!-- Style guide: one sentence per entry. Describe the user-visible effect, not the
     implementation. Group related fixes/features into a single entry when they share
     a theme. Breaking changes and migration steps can be longer — users need the
     specifics. Detail belongs in commit messages and PR descriptions, not here.

     Review and condense before release — entries accumulate during development and
     should be edited into shape before moving from Unreleased to a version heading. -->

## Unreleased

### Added
- **One error tree**: `decode()`, `decode_program()`, `encode()`, `read_csv()`, `write_csv()` and `check()` raise a `LaddercodecError` for input they can't read or write, and each `LaddercodecError` is a `ValueError`, so `except ValueError` still catches each one: `DecodeError` (`decode()`, `decode_program()`), the new `EncodeError` (`encode()`), `CsvError` (`read_csv`), `WriterError` (`write_csv`) and `FieldError` with `AddressError` (a value CLICK's dialog refuses); `except LaddercodecError` catches them all.
- **More top-level exports**: `laddercodec` exports `LaddercodecError`, `DecodeError`, `EncodeError`, `CsvError`, `WriterError`, `UnknownCondition`, `UnknownInstruction`, `Email`, `Home`, `Position` and `Velocity`, the instruction bases `ConditionInstruction` and `AfInstruction`, and the cell types `ConditionToken` and `AfToken`, so none needs a submodule import.
- **Undecoded marker rungs**: `decode()` and `decode_program()` return a rung they can't read as a one-row rung into an `Undecoded` marker, with an `UndecodedRungWarning`, and the rungs around it decode; the marker acts as `end()` in the main program and `return()` in a subroutine, since a program that ran past a rung it could not read would run wrong.
- **`Program.undecoded`**: lists a program's undecoded markers, empty when every rung decoded.
- **`undecoded(...)` CSV token**: `write_csv` writes a marker and `read_csv` reads it back; `encode()` refuses it, so it never reaches CLICK, and `check()` reports it as an `undecoded` finding.
- **Read errors say where**: an error `read_csv` raises for a bad CSV carries a `CsvLocation` (file, line, rung, row and column) as its `location`, and its message ends with that location; for a file that isn't UTF-8 the location names the file only, and a `FieldError` refused while a box takes its pin rows still arrives as `CsvError` (`ConvertError` in v0.4.0), now with the refused field in `.field`.
- **Field errors say why**: a `FieldError` carries `reason` (a `Reason` such as `bank`, `range` or `conflict`), `click_id` (CLICK's own error id, such as `OBJ-005`, where it has one), `fields` (the one field, or both of a pair) and `errors` (every refusal of the construction, the raised one first). `Timer`, `Coil`, `Contact`, `CompareContact`, `OutVariant`, `Counter`, `Shift`, `Call`, `ForLoop`, `Drum`, `Search`, `Copy`, `BlockCopy`, `Fill`, `Pack`, `Unpack`, `Math`, `Send`, `Receive`, `ModbusRtuTarget`, `ModbusTcpTarget`, `ModbusAddress`, `RawInstruction` and `Undecoded` report every field they refuse, and a Math formula each address, constant, key or range it refuses; the other instructions report the first.
- **Read errors carry every refusal**: a `FieldError` from `read_csv` has a `location` on each refusal in `.errors`, not only the raised one, and the `CsvError` of a refused pin row now carries `fields`, `reason`, `click_id` and `errors` as a `FieldError` does.
- **`RefusedFieldWarning`**: `decode()` and `decode_program()` emit one for each decoded instruction that holds a value CLICK's dialog refuses, with the instruction, its refusals, its rung and its program.
- **`read_csv(..., unchecked=True)`**: reads an instruction whose values its checks refuse as written, as the decoders read a stored one, with a `RefusedFieldWarning`, so the CSV `write_csv` writes for such an instruction reads back.
- **`constant_text()`**: writes a Python int, float or str as the constant text a `Math` or a `Copy` source takes, as building the instruction stores it (`constant_text(255, hex=True)` is `FFh`, `constant_text(1e3)` is `1000.0`, `constant_text("AB")` is `"AB"`); a `Math` refuses a real of more than 6 significant digits and a `Copy` one of more than 7 (`constant_text(1/3)` is `0.33333334`, which both refuse).

### Fixed
- **Copy conversion type 7**: a single Copy between DF and CTD, of a DF, DD or CTD address or pointer into a DD, CTD or DF address or pointer across the real and integer kinds (`copy(DF[DS1],DD1)`, `copy(DD[DS1],DF1)`, `copy(DF1,CTD[DS1])`), of a real constant into DD or CTD (`copy(1.5,DD1)`, `copy(1.5,CTD[DS1])`), or of an integer constant outside int16 into DF (`copy(65536,DF1)`, `copy(2147483647,DF[DS1])`) encodes with conversion type 7, as CLICK saves it and as a DD to DF copy already did, where it was written as a plain copy.
- **Copy Binary between a real and a 32-bit integer**: `convert=to_binary` on a copy CLICK saves as conversion type 7 (`copy(CTD1,DF1,convert=to_binary)`, `copy(1.5,DD1,convert=to_binary)`, `copy(65536,DF1,convert=to_binary)`) is accepted and encodes as CLICK saves it, conversion type 8, as a DD to DF copy already did, a pointer on either side included (`copy(DF[DS1],CTD1,convert=to_binary)`), where it was refused.
- **Copy and Search text of any 16-bit character**: a single Copy source or a Search value of quoted text holding any character U+0001 to U+FFFF but a surrogate (`copy("é",TXT1)`, `"€"`, a tab, U+0001, a line break) is accepted, and encodes and reads back from CSV as typed, as CLICK keeps it, where it was refused; NUL (write `$00`) and a character above U+FFFF are still refused, and so is text outside printable ASCII in a Fill and a compare. A line break inside a quoted CSV argument reads back, where `read_csv` refused the token; one outside the quotes is still refused.
- **Copy of an integer into TXT**: a single Copy of an integer or hex constant into TXT with `to_text` writes the last TXT its text fills, counting the constant as written (`-5` and `+5` into TXT1 end in TXT2, `0FFh` in TXT4), as CLICK saves it, where it wrote no end.
- **Copy of a real or a DF pointer into TXT, encode**: a single Copy of a real constant or a DF pointer to text writes real numbering (conversion type 3) or, with `exponential=1`, exponential numbering (type 4), and a real constant also the last TXT its text fills (`1.5` into TXT1 ends in TXT3), as CLICK saves them, where both wrote type 1 or 2 (zeros suppressed or not), `exponential=1` was refused for them, and a real constant had no end.
- **Copy of a real or a DF pointer into TXT, decode**: CLICK's saves of a real constant or a DF pointer copied to text decode as the Copy, where type 3 from a DF pointer read as `suppress_zero=1` and type 4 as `raw(Copy,...)`.
- **Copy past TXT1000**: a single Copy of a number constant to text whose text runs past TXT1000 (`-5` into TXT1000) is refused with an `AddressError` on the destination carrying CLICK's `OBJ-003`, where it was accepted, and quoted text that runs past it (`"AB"` into TXT1000), refused before, now carries `OBJ-003` too.
- **Copy save CLICK never makes**: a single Copy blob of a source that is not a real or DF with real numbering (conversion type 3, such as `DS1` into TXT) decodes as `raw(Copy,...)`, where it read as a Copy to text with suppress zero.
- **Copy saves that read as raw**: CLICK's single Copy saves of conversion type 7 or Copy Binary (DF to or from CTD, a DF, DD or CTD pointer across the real and integer kinds, a real constant into DD or CTD, an integer outside int16 into a DF address or pointer), of a number constant into TXT with the end its text fills (`FFh` or `1.5` into TXT1, or `"HELLO"`, which CLICK stores as `0.0`), and of quoted text with no end, which CLICK's paste saves (`copy("HALLO",TXT1)`), decode as the Copy, where they read as `raw(Copy,...)`, and unchanged write the bytes they were decoded from; quoted text with no end past TXT1000 keeps the `OBJ-003` refusal.
- **`check()` codes for two accepted shapes**: a contact in parallel with a wire-only leg is `C0002` (it had no code), and a contact that feeds only a `NOP` is `C0003`, even beside a coil on another wire or leg (it reported nothing), as CLICK's syntax check answers; `read_csv`, `write_csv` and `encode()` handle both shapes as v0.4.0 did; the C0003 finding is the new kind `nop_only_contact`.
- **Refusals read unchecked say where**: each refusal `read_csv(..., unchecked=True)` keeps carries the `CsvLocation` the default read raises it with (file, line, rung, row and column, a pin row's value at that pin's row), and the `RefusedFieldWarning` message ends with the first one's, where they carried no location.
- **Hex Math constant CLICK stores from `1e3`**: a hex `Math` holding `1E3h`, which CLICK stores for a constant typed `1e3`, decodes with no `RefusedFieldWarning` and reads back from CSV, where it was refused as a constant cut at its `E`.
- **Long MODBUS address and compare operator**: a Send or Receive `ModbusAddress` of more than 4300 digits is refused with a `FieldError` on `ModbusAddress.address`, where it crashed with `ValueError`, and a `CompareContact` operator outside `==`, `!=`, `<`, `>`, `<=` and `>=` is refused on `CompareContact.op`, where `build_blob` crashed with `KeyError`.
- **Unpack ids and order**: an Unpack refusal carries CLICK's id, where it had none: `OBJ-004` for a source or destination bank the instruction does not take and for a destination bank the source can't unpack to (`DS1` into `DS1..DS2`), but `OBJ-024` for Y from DS, DD or DF, and `OBJ-1009` for a DH into a Y range across two slots (`Y001..Y032`). The destination's start is checked against the source before its end, so an end that does not fit a start refused for its pairing is no longer reported; the same values are accepted and refused.
- **Copy and Pack bank ids**: a bank the field does not take carries CLICK's id, where it had none: `OBJ-004` for a Pack destination, and for a single Copy into a bit bank it does not write, `OBJ-004` from a bit source or at an address outside the bank (`X017`, `T501`) and `OBJ-024` from any other; a single Copy of a `$` code (`$41`) into any bank but TXT, a pointer of another bank included (`X[DS1]`, `SD[DS1]`), carries `OBJ-004`, and a single Copy source of empty text (`""`), of text over 128 characters, of a signed hex constant (`-FFh`) or of a hex constant with more than 8 digits (`0FFFFFFFFh`) carries `OBJ-005`, as one above FFFFFFFFh does; which values are refused is the same.
- **Pack source module**: a Pack source range that spans two X or Y modules, such as `X001..X036`, is refused with CLICK's `OBJ-033`, where it had no id; the refusal itself is the same.
- **Copy termination code**: a `$` code that is no character code (`$ZZ`, `$D`) is refused with CLICK's `OBJ-036`, as a code with no `$` already was; the same values are accepted and refused.
- **Termination code on a TXT copy into TXT**: a single Copy of a TXT register or pointer into TXT takes a termination code (`copy(TXT1,TXT21,termination_code=$0D)`), as CLICK's dialog offers, where building one refused it and `read_csv` dropped the keyword without a word, and CLICK's save of one decodes as the Copy, where it read as `raw(Copy,...)`; CLICK's program file saves no code tag for `$00`, and decode reads it as `$00`.
- **Block Copy termination code**: a Block Copy of TXT into TXT keeps its termination code (`blockcopy(TXT1..TXT2,TXT11..TXT12,termination_code=$0D)`), on decode, on encode and in `read_csv`, where decode and `read_csv` dropped it and encode wrote none.
- **Receive FC01 id**: a Receive with function code 01 from a register slave address (`DS1` into `C1`) carries CLICK's `OBJ-004`, where it had none; the refusal itself is the same.
- **SD or YD out of range as a hex Math result**: an SD register (SD1-SD1000), or a YD past YD8, is refused with CLICK's `OBJ-003` (outside the range) and a message that says so, and an SD past its bank's range (`SD0`, `SD1001`) with `OBJ-004`, where both had no id; the refusal itself is the same.
- **`check()` on a circuit that is not series-parallel**: such a rung gets its C0001 finding and no C000A finding or finding about a pin's contacts, as CLICK reports a bridge with an output above a retentive timer, where it also got C000A and C0205.
- **`check()` C000A on a pin's net**: another box's main input below a box's pin, on the pin's net, such as a timer fed from a counter's reset or a reset wire that also feeds an output, is a new `shared_input_net` finding, one per group of boxes that share nets, as CLICK reports it, where it got C0205 or a pin finding with no code; other boxes on a pin's net, a box below on a reset teed off the main input included, get it with `captured=False`, and so does `output_above_pinned_box` with a `NOP` or a box with a used pin above.
- **`check()` on an unwired reset**: a timer's or counter's reset whose row holds nothing is an `unwired_pin` finding, C0202 at its AF cell, as CLICK reports it, where `check()` reported nothing, and `read_csv` still lays such a rung out; another pin whose row holds nothing, or a pin row of wires that no rail or contact reaches, gets C0202 with `captured=False`.
- **Receive TXT count ids**: a Receive TXT count below 2 is refused with CLICK's `OBJ-010` and an odd one with `OBJ-029`, where both had no id; the refusals themselves are the same.
- **Long digit runs in Compare and Out variants**: a constant of more than 4300 digits, such as a long run of leading zeros, no longer raises a bare `ValueError`; it reads as its value, or is refused with `FieldError` where its pairing or limit refuses it.
- **For count of thousands of digits**: a For count of more than 4300 digits (leading zeros) no longer raises a bare `ValueError`; it reads as its value, or is refused with `FieldError`; the messages for an above-limit count and a pointer count are reworded.
- **Long digit runs in Timer and Drum**: a Timer set point or Drum preset of more than 4300 digits (leading zeros) no longer raises a bare `ValueError`; it reads as its value, or is refused with `FieldError` above its limit, and a Counter preset that long is refused with `FieldError`.
- **Long DS Slave ID**: a Modbus target whose `device_id` is `DS` followed by more than 4300 digits raises `FieldError`, where it raised a bare `ValueError`.
- **Addresses CLICK saves as typed decode**: an address CLICK saves as it was typed (a Copy, Block Copy or Pack destination, an address in a Math formula and a hex Math result, such as `DS001`, `ds1`, `YD0U` or `DS[ds1]`) decodes as the instruction, in display form (`DS1`, `YD0u`, `DS[DS1]`), where it decoded as `raw(...)`; unchanged, it encodes as stored, and an X or Y number typed short (`Y1`) or typed text in any other field still decodes as `raw(...)`.
- **Empty flag fields read as set**: `decode()` reads a flag field that holds nothing as set, where it read it as clear; a box `decode_program()` reads writes a flag the program file sets that way, so encoded and decoded again it keeps the flag (a hex Math stays hex, a oneshot stays oneshot), and CLICK's own clipboard holds `-1`, `1` or `0`.

### Changed
- **Copy and Out refusal order**: a single `Copy` whose constant source is refused for its own value (an empty or too long text, a quote inside the text, a signed hex constant, an integer outside 32 bits, a real outside float32, a hex constant of more than 8 digits or above FFFFFFFFh) raises a `FieldError` on `Copy.source` before its pairing with the destination and before the format and termination code refusals, where a destination that can't take the constant (`copy("",DS1)`, `copy(-1h,Y001)`, `copy(100000000h,Y001)`) raised an `AddressError` on `Copy.destination`, and a termination code the format does not take a `FieldError` on `Copy.termination_code`; text with a character the Copy refuses still raises the pairing first. An Out, Set or Reset range whose end is in another bank raises a `FieldError` with reason `conflict` on both ends, carrying `OBJ-008`, before the end's own checks: where the field does not take that bank (`out(C1..DS1)`), where the end is a pointer (`out(Y001..DS[DS1])`) and where the end is an SC bit a coil can't write (`out(C1..SC1)`), it raised an `AddressError` on `Coil.range_end`, and an immediate range whose end is in another bank (`out(immediate(Y001..C2))`) is refused for the bank, where it was refused as not immediate. The same values are accepted and refused.
- **Receive TXT count up to 250**: a Receive into TXT takes an even count of 2 to 250 characters, as CLICK does, where laddercodec refused a count over 124; a count past 250 is refused with `OBJ-010` and its message names characters.
- **Math constant and display-form messages**: up to 4 hex digits without `h` in a hex `Math` (`7`, `005`, `FF`, `1e3`) are refused with a message that names the `h` form CLICK reads (`write 7h`), but for a signed argument of `RAND`, `LSH`, `RSH`, `LRO` or `RRO`, which CLICK refuses with its `h` too; those that are not all digits (`FF`, `abc`, `E5`, `DF`) no longer carry `OBJ-1001`, since CLICK takes them; an integer with leading zeros outside int32 (`06000000000`) says its leading zeros are refused, where it said it was out of range; a name or address refused under `display_form_only()` for not being in display form names its field at the start of its message, as other refusals do; which values are refused is the same.
- **Reworded refusals**: the messages for Compare, Out variant, Timer set point, Counter preset, Drum preset, Modbus hex address, Copy, Fill and Search value fields are reworded, and a refusal that carries CLICK's error id ends with it, such as `(OBJ-004)` for a bank Out, Set, Reset, Timer, Counter, Drum, For, Math or Shift does not take and `(OBJ-003)` for an SC bit a coil can't write; the refusals themselves are the same.
- **Field errors name the field**: `FieldError.field` now names the field for a Compare pairing refusal, for Drum step counts, output counts and steps with neither a duration nor an event, for Send, Receive and Modbus target refusals, such as `Send.quantity` or `ModbusTcpTarget.port`, and for a bad Copy or BlockCopy format, Copy `exponential` or termination code, Pack or Unpack type, and `rows=` or `sub=` in a `raw(...)` token; `field` is always `Class.attr` of the instruction refused, so an event drum's event is `Drum.events_or_presets[i]`, where it was `Drum.events[i]`, a drum preset is `Drum.events_or_presets[i]`, where it was `Drum.presets[i]`, a refusal under `display_form_only()` names its field, and a refusal of `undecoded(...)` token syntax names none.
- **Undecoded comments keep their text**: a comment that doesn't decode now reads `UNDECODED comment: <error>` followed on the next line by the plain text that could be read from its bytes, cut and ended with `...` where it would be too long to encode, so `encode()` writes the text back into CLICK.
- **Docs site follows releases**: the published docs update when a release is published, not on every change to `main`.
- **Math X/Y option-slot range message**: the refusal of a `Math` X or Y range with an end in X021-X036 or Y021-Y036 now names the end or ends in the option slot and says CLICK sums the wrong bits for the range (`SUM ( X001 : X036 ) is refused: X036 is in the option slot (X021-X036), and CLICK sums the wrong bits for this range.`), where it listed the points CLICK would leave out or add; the same ranges are accepted and refused.

### Behaviour changes
- **`decode()` always returns a list**: `decode()` returns a `list[Rung]` for every buffer, a list of one for a single-rung clipboard, where it returned the `Rung` itself for one rung and a list for several; `encode()` is annotated as taking a `Rung` or an iterable of rungs and returning `bytes`.
  - Do: unpack a single rung with `[rung] = decode(data)`, and drop any `isinstance(result, list)` check.
- **Contact and Coil are built by kind, with the operand first**: `Contact(operand, kind="no", immediate=False, wire_down=False)` takes a `kind` of `"no"`, `"nc"`, `"rise"` or `"fall"`, where it took an `InstructionType` (which `laddercodec` does not export) as `type`, first, and `edge_kind` for an edge contact; `Coil(operand, kind="out", range_end=None, immediate=False, oneshot=False)` takes a `kind` of `"out"`, `"latch"` or `"reset"`, the names of its CSV calls, where it took an `InstructionType` as `type`, first. An edge contact with no edge, and an NO or NC contact with one, can no longer be built. A refusal names `Contact.kind` where it named `Contact.type` or `Contact.edge_kind`, and `Coil.kind` where it named `Coil.type`, so a set or reset with a one-shot names `Coil.oneshot` and `Coil.kind`; a kind refused reads `Contact.kind: 'up' is not a contact kind (no, nc, rise or fall)` or `Coil.kind: 'set' is not a coil (out, latch or reset)`.
  - Do: write `Contact("X001", kind="nc")` for `Contact(InstructionType.CONTACT_NC, "X001")`, `Contact("X001", kind="rise")` for `Contact(InstructionType.CONTACT_EDGE, "X001", edge_kind="rise")` and `Coil("Y001", kind="latch")` for `Coil(InstructionType.COIL_LATCH, "Y001")`; pass `immediate`, `range_end` and `oneshot` by keyword; read `.kind` where you read `.type` or `.edge_kind`.
- **Immediate edge contacts and coil one-shot text are field refusals**: `read_csv` given `rise(X001).immediate` or `immediate(fall(X001))` raises `FieldError` `Contact.immediate: an edge contact has no immediate form`, reason `conflict` on `Contact.immediate` and `Contact.kind`, where it raised `ValueError` `Cannot convert generic condition to encode token: ...`, and `Contact.from_csv_token` raises the same, where it raised `ValueError` `Immediate edge contacts are unsupported`; read with `unchecked=True`, such a contact is kept as written, with a `RefusedFieldWarning`. A coil `oneshot=` other than `0` or `1` (`out(Y001,oneshot=2)`) raises `FieldError` `Coil.oneshot: '2' is not 1 or 0`, reason `flag`, and a blank one (`out(Y001,oneshot=)`) `Coil.oneshot: is blank; it needs a value, 1 or 0`, reason `missing`, as a Copy-family flag does, where both raised `ValueError` `coil oneshot must be 0 or 1`. Each is still a `ValueError`.
  - Do: catch `FieldError`, or `ValueError`, for these.
- **Error classes**: `encode()` raises `EncodeError` where it raised a bare `ValueError` (a grid of the wrong size, a wire token CLICK can't draw, more than one `NOP`, a comment too long), and raises it for an `Undecoded` marker; `read_csv` raises `CsvError` where it raised a bare `ValueError` for a row, token or rung it can't read; `decode_program()` raises `DecodeError` where it raised `ValueError` for a file header it can't read, and for a program name that is not UTF-16 text, where it raised `UnicodeDecodeError`; `ConvertError` is renamed `CsvError`, and `laddercodec.csv.converter.ConvertError` is gone. Each is a `ValueError`, and each message is unchanged, except the program name's, which is new.
  - Do: catch `CsvError` where you caught `ConvertError`; `except ValueError` needs no change.
- **Errors that were not `ValueError`s**: `read_csv` raises `CsvError` for a file that isn't UTF-8, where it raised `UnicodeDecodeError`, and for a `csv.Error` (such as a cell longer than `csv.field_size_limit()`), where it raised the `csv.Error`; each keeps the original's message, ends it with the location, and holds the original as `__cause__`. A `send` or `receive` with no `target=` or no `remote_start=` raises `CsvError`, where it raised `KeyError`. `encode()` raises `EncodeError` for a rung holding an `UnknownCondition` or `UnknownInstruction` (a cell `decode()` couldn't read), where it raised `TypeError` or `AttributeError`.
  - Do: catch `CsvError`, or `ValueError`, where you caught `UnicodeDecodeError` or `csv.Error` around `read_csv`.
- **Empty text set after building**: `encode()` given a `Copy` or `Fill` whose text was set to `""` after it was built raises the `FieldError` building it with `""` raises (`Copy.source: '""' is refused; ...`), where it raised a `ValueError` (`Empty text constant "" in ...`).
- **`to_text` for a real constant or a DF pointer takes `exponential`**: a real constant (`1.5`) or a DF pointer (`DF[DS1]`) copied to text is written `to_text(exponential=0)` or `to_text(exponential=1)`, as a DF address is, and `suppress_zero` for any of the three, either value, raises `FieldError` with reason `conflict` on `Copy.suppress_zero` and `Copy.source`, where it was accepted, chose zeros suppressed or not for a real constant or DF pointer, and was ignored for a DF address; a DD or DS pointer keeps `suppress_zero`; `Copy.suppress_zero` is `None` by default for a DF or real source to text, where a DF address had `"1"`.
  - Do: write `exponential=0` where you wrote `suppress_zero` for a real constant or a DF pointer, and drop `suppress_zero` for a DF address.
- **TXT into a number takes `to_value` or `to_ascii`**: a plain single Copy of a TXT register or pointer into DS, DD, DH, YD, TD, CTD or SD (`copy(TXT1,DS1)`) raises `FieldError` with reason `conflict` on `Copy.format`, `Copy.source` and `Copy.destination`, and a plain Block Copy of TXT into DS, DD or DH (`blockcopy(TXT1..TXT2,DS1..DS2)`) on `BlockCopy.format`, `BlockCopy.source_start` and `BlockCopy.dest_start`, where both were accepted and written as a plain copy, which CLICK never saves: its dialog asks for the character's value or its ASCII code. A TXT register into DF stays a plain copy, as CLICK saves it. A decoded program that holds a plain one decodes it with a `RefusedFieldWarning` and encodes it unchanged.
  - Do: write `convert=to_value` for the character's value or `convert=to_ascii` for its ASCII code.
- **A termination code only where CLICK offers one**: `termination_code=$XX` beside the operands of a `copy` or `blockcopy` other than TXT into TXT raises `FieldError` with reason `conflict` (`copy(TXT1,DS1,convert=to_value,termination_code=$0D)`, `blockcopy(DS1..DS2,DS11..DS12,termination_code=$0D)`), where `read_csv` dropped it without a word; `termination_code=none` or `0` is no code, which any copy takes.
  - Do: drop the code, or write it inside `to_text(...)` or `to_binary(...)` for a number copied to TXT.
- **Copy-family keywords and flags**: a keyword `copy` or `blockcopy` does not take (anything but `convert`, `oneshot` and `termination_code`, such as a misspelt `terminaton_code=` or `suppress_zero=1` outside `to_text(...)`), or `fill`, `pack_*` or `unpack_to_*` does not take (anything but `oneshot`, and `allow_whitespace` for `pack_text`), raises `CsvError`, where `read_csv` dropped it and its value; `allow_whitespace=1` in `pack_bits` or `pack_words`, which `read_csv` kept and `write_csv` wrote back, raises it too. A blank flag keyword of these (`oneshot=`) raises `FieldError` with reason `missing`, and any value but `1` or `0` (`oneshot=yes`) with reason `flag`, where both read as off.
  - Do: spell the keyword as written here, put `suppress_zero` and `exponential` inside `to_text(...)`, and write a flag as `1` or `0`.
- **A number into TXT needs a converter**: a single Copy of a number constant, register or pointer into TXT with no converter (`copy(5,TXT1)`, `copy(DS1,TXT1)`) raises `FieldError` with reason `conflict` on `Copy.format`, `Copy.source` and `Copy.destination`, where it was accepted and written as a plain copy, which CLICK never saves: its dialog saves the number as text, by default with suppress zero or, for a real or DF source, real numbering, or as binary. A decoded program that holds a plain one decodes it with a `RefusedFieldWarning` and encodes it unchanged.
  - Do: write `convert=to_text(suppress_zero=1,termination_code=none)`, CLICK's default, or `convert=to_text(exponential=0,termination_code=none)` for a real constant or a DF source.
- **A Copy real keeps 7 significant digits**: a single Copy of a real constant typed with more than 7 significant digits, leading and trailing zeros aside (`copy(3.4028235E+38,DF1)`, `copy(1.2345678,DF1)`), raises `FieldError` with reason `form` on `Copy.source`, and the message names the constant of 7 digits to write (`3.402823E+38`, `1.234568`), where it was written as typed: CLICK keeps 7 significant digits and saves a real of more cut to 7. A decoded program that holds one decodes it with a `RefusedFieldWarning` and encodes it unchanged.
  - Do: write the value the message names, or a Math where the value needs more digits.
- **TXT into DF takes no converter**: a single Copy of a TXT register or pointer into DF with `convert=to_value` or `convert=to_ascii` raises `FieldError` with reason `conflict` on `Copy.format`, `Copy.source` and `Copy.destination`, where it was accepted, since CLICK's dialog offers neither for DF and saves a plain copy. A decoded program that holds one decodes it with a `RefusedFieldWarning` and encodes it unchanged.
  - Do: drop the converter: `copy(TXT1,DF1)`.
- **No suppress zero or converter where CLICK offers none for TXT**: a `Copy` from a TXT source built with `suppress_zero="1"` raises `FieldError` with reason `conflict` on `Copy.suppress_zero` and `Copy.source`, where it was accepted and not written; a Block Copy of TXT into TXT with `to_value` or `to_ascii` raises `FieldError` with reason `conflict` on `BlockCopy.format` and `BlockCopy.dest_start`, where it was accepted.
  - Do: drop `suppress_zero` for a TXT source, and the converter from a Block Copy of TXT into TXT.
- **A Pack of text into DH takes 4 characters**: `pack_text` of more than 4 TXT registers into DH, such as `pack_text(TXT1..TXT16,DH1)`, is refused with `OBJ-003` and reason `range`, as CLICK refuses it, where it was accepted; a decoded program that holds one decodes it with a `RefusedFieldWarning` and encodes it unchanged.
  - Do: pack at most 4 TXT characters, 4 hex digits, into a DH.
- **A Pack source is counted before its pairing**: a Pack source longer than any pairing takes raises `FieldError` on `Pack.source_end` with CLICK's count id, then the pairing's `OBJ-024`, where it raised `AddressError` on `Pack.destination` with no id: 33 or more T, CT or SC bits into DS, DD, DF, TD or CTD and 33 or more C bits into TD or CTD give `OBJ-041`, and 3 or more DH into DS, DH, DF, TD or CTD give `OBJ-040` (`pack_words(DH1..DH16,DH1)`); the same values are accepted and refused.
  - Do: catch `FieldError` where you caught `AddressError` for these, and read `.errors` for the pairing.
- **A rung that doesn't decode no longer fails the call**: a down wire in the output column or wire flags no token has gives an undecoded marker for the rung, and a clipboard row the walk can't read or a program file record whose framing breaks gives one marker for that rung and every rung after it, where `decode()` and `decode_program()` raised `DecodeError` or `ValueError`.
  - Do: check `Program.undecoded`, or catch `UndecodedRungWarning`, where you caught those errors; a buffer whose magic, size or program header is wrong still raises `DecodeError`.
- **Comments that don't decode**: the rung keeps its logic, its comment becomes `UNDECODED comment: <error>`, and `decode()` and `decode_program()` emit an `UndecodedCommentWarning`, where `decode()` raised `DecodeError` and `decode_program()` kept the rung with no comment.
- **`write_csv` writes a marker for a rung it can't write**: a rung holding an unknown condition or instruction is written as an undecoded marker, with an `UndecodedRungWarning`, where `write_csv` raised `WriterError`; its new `stop` argument gives the marker's `stop`.
  - Do: pass `stop="return"` when writing a subroutine.
- **A Math real keeps 6 significant digits**: a real constant in a decimal `Math` typed with more than 6 significant digits, leading and trailing zeros aside (`0.33333334`, `3.402823466E+38`), raises `FieldError` with reason `form`, and the message names the constant of 6 digits to write (`0.333333`, `3.40282E+38`), where it was written as typed: CLICK keeps 6 significant digits in a Math and saves a real of more cut to 6. A decoded program that holds one decodes it with a `RefusedFieldWarning` and encodes it unchanged.
  - Do: write the constant the message names.
- **`allow_whitespace` is a `pack_text` option**: a `Pack` of bits or words built with `allow_whitespace=True` raises `FieldError` with reason `conflict` on `Pack.allow_whitespace` and `Pack.pack_type`, where it was accepted, written to CSV and not encoded.
  - Do: drop `allow_whitespace` for `pack_bits` and `pack_words`.
- **Flags refuse a non-flag value**: the flags of `Copy`, `BlockCopy`, `Fill`, `Pack` (`allow_whitespace`, `oneshot`), `Unpack`, `Search` (`continuous`, `oneshot`), `Math`, `ForLoop`, `OutVariant` (`immediate`, `maintained`), `Send` and `Receive` (`word_swap`) now raise `FieldError` for a value other than True, False, 1 or 0, where they accepted it; `oneshot=2` was written as `oneshot=1`.
  - Do: pass True, False, 1 or 0.
- **A blank field is refused as `missing`**: an empty required field, in any instruction or Modbus target, has `FieldError.reason` `missing`, where it had the reason of a bad value (`address` for a blank address, `kind` for a blank Out variant or Counter preset, `choice` for a blank unit, type or mode, `form` or `conflict` for a blank Copy termination code, `form` for a blank Modbus target `ip`, `kind` for a blank `ModbusAddress.address`); a Copy `termination_code=""` no longer carries `OBJ-036`; which values are accepted, the field each refusal names and the other ids are unchanged.
  - Do: where you read `reason` to tell a blank from a bad value, test for `Reason.MISSING`; where you matched a blank on `address`, `kind`, `choice`, `form` or `conflict`, match `missing` instead.
- **A stored value CLICK's dialog refuses no longer makes a cell raw**: the instruction decodes with the value as stored and a `RefusedFieldWarning`, where it decoded as `raw(...)` or an unknown condition. Unchanged, it encodes as the raw cell did. Changed, it is checked again: `encode()` raises the `FieldError` building it raises, or encodes the fix as building it would. Read with `read_csv(..., unchecked=True)`, or a condition decoded by `decode_program()`, it has no bytes to write, and `encode()` raises that error. An address not in display form outside the fields CLICK saves as typed, a value outside a field's named values, refused pin rows, a value a check crashes on, a Math in nickname view and an instruction whose CSV would not read back as itself still decode as raw, and so does text that is no number in a numeric field, which decoded as the field's default. A Copy or Pack destination stored with an edge space decodes as the address without it, and encodes as stored while unchanged.
  - Do: nothing to decode and encode a rung unchanged. Catch `RefusedFieldWarning` to find these instructions; fix the field each names before you encode one you read from CSV.
- **Math and Copy constants are written as CLICK stores them**: a real in a `Math` or a single `Copy` source is the value CLICK prints back (`1.50` is `1.5`, `1e3` is `1000.0`, `.5` is `0.5`, `1E5` is `100000.0`), a `Copy` source drops an integer's leading zeros (`005` is `5`) and the `-` of zero (`-0` is `0`), drops a real's typed `+` (`+1.5` is `1.5`), writes hex with uppercase digits and `h` (`0ffh` is `0FFh`), and a `Copy` of `$1` to TXT is accepted and written `$01`; `to_csv()`, `write_csv` and `encode()` write that form, where they kept the typed text, and the instruction built from either spelling is equal; `copy(EH,...)` and `copy(1Eh,...)` are refused, where they were read as hex 14 and 30, since CLICK stores them as the reals 0.0 and 1.0.
  - Do: compare constants in CLICK's form, or build both sides through the instruction; write the real or the hex value as a decimal integer where you wrote `EH` (`0.0` or `14`) or `1Eh` (`1.0` or `30`).
- **Hex Math formula and SD writes follow CLICK**: a hex `Math` formula holding a DS register (`DS1 + 1h`) or a bit in a `SUM` (`SUM ( X001 : X002 )`) is refused with `OBJ-1002`, where both were accepted; an SD register other than the 29 a program writes (SD29, SD31, SD32, SD34-SD36, SD40-SD42, SD50, SD51, SD60, SD61, SD106-SD108, SD112-SD114, SD140-SD147, SD214, SD215) is refused as a `Copy` destination (`OBJ-004`), anywhere in a `BlockCopy` destination range (`OBJ-018` for a read-only SD after a writable start, `OBJ-004` past SD215) and as a decimal `Math` result (`OBJ-003`), each with reason `not_writable`, where it was accepted.
  - Do: change such a value before you build or read the instruction; a decoded program that holds one decodes it with a `RefusedFieldWarning` and encodes it unchanged.
- **Each Math mode takes its own banks**: a hex `Math` formula takes hex constants and the DH, XD and YD registers only, and a decimal one decimal constants, the DS, DD, DF, TD, CTD and SD registers, and X, Y, C, T and SC bits only as the range of a `SUM`. Every other address, in a `SUM` too, is refused with `OBJ-1002` and reason `bank`, and each refusal states its mode's rule.
  - A DD, DF, TD, CTD, SD or TXT register in a hex formula, and a DH, XD, YD or TXT register in a decimal one, is now refused, where it was accepted.
  - A `SUM` over CT, in either mode, now carries `OBJ-1002`, where it had no id.
  - A range whose ends are in two banks (`OBJ-1015`) or reversed (`OBJ-1014`, where a reversed range had no id) is refused with that id first, ahead of `OBJ-1002`, as CLICK refuses `SUM ( DH2 : DH1 )` and `SUM ( X001 : TXT2 )` in a decimal Math.
  - Do: for a hex formula, copy a register into a DH first or pack bits into a DH, or use a decimal `Math` for a DS, DD, DF, TD, CTD or SD value; for a decimal formula, copy a DH, XD, YD or TXT register into a DS first, or use a hex `Math` for a DH, XD or YD value, and pack CT bits into a DH, then copy the DH into a DS or use it in a hex `Math`.
- **RAND bounds follow CLICK**: a bound of a decimal `RAND` takes a DS or DD register or an integer constant, and of a hex `RAND` a DH register or a hex constant, and the two bounds differ. A DF, TD, CTD or SD register in a decimal `RAND`, or an XD or YD register in a hex one, is refused with `OBJ-1002` and reason `bank`; a real bound (`RAND ( 1.5 , 10 )`) and equal bounds (`RAND ( 1 , 1 )`, `RAND ( DH1 , DH1 )`) are refused with `OBJ-1001`, where all were accepted. A bound refused for its bank states RAND's rule, where it stated the formula's. A decoded program that holds such a `RAND` decodes it with a `RefusedFieldWarning` and encodes it unchanged.
  - Do: copy the register into a DS or DD (decimal) or a DH (hex) first and use that as the bound, write an integer bound, and write two different bounds.
- **A Math real is at most float32's largest value**: a real constant in a decimal `Math` whose value, read as a double, is above float32's largest value, 3.402823466E+38, in size, such as `3.4028235E+38`, is refused with `OBJ-1009` and reason `range`, as CLICK refuses it, where one that float32 rounds to that largest value was accepted; the message names the largest value. A decoded program that holds one decodes it with a `RefusedFieldWarning` and encodes it unchanged.
  - Do: write `3.40282E+38`, float32's largest value cut to the 6 significant digits a Math keeps.
- **A blank CSV token argument is `missing`**: in `read_csv`, a blank argument or keyword value, such as `out()`, `on_delay(T1,TD1,preset=,unit=Tms)` or `blockcopy(,DS10..DS13)` (`blockcopy(..,DS10..DS13)` as `write_csv` writes a blank range), is refused with a `FieldError` whose `reason` is `missing` and whose `field` is the blank one, as building the instruction with that field blank is. It was a token syntax error with no `field` (for `out(,oneshot=1)`, an `address` refusal of `oneshot=1`). `read_csv(..., unchecked=True)` keeps it as it keeps any refusal. A Timer or time drum `unit=`, a Math `mode=`, a drum list, a search expression and a blank flag in `out` or `for` are still syntax errors, and `out(,oneshot=)` is still an `address` refusal of `oneshot=`.
  - Do: where you told a syntax error from a field refusal by `field is None`, expect `field` and `Reason.MISSING` for a blank argument.
- **`Timer` and `Counter` fields take their CSV names**: `timer_type` and `counter_type` are `kind`, valued with the CSV call name (`on_delay`, `off_delay`, `count_up`, `count_down`, as before); `done_bit` is `done`; `current` is `accumulator`; `Timer.setpoint` is `preset`, as `Counter.preset` was. Each `.field` of a `FieldError` and each name in its message follows (`Timer.setpoint` is `Timer.preset`, `Counter.current` is `Counter.accumulator`), the arity messages of `Timer` and `Counter` say `(done, accumulator)` where they said `(done, acc)` and `(done, current)`, and a Timer `unit` that is not `Tms`, `Ts`, `Tm`, `Th` or `Td` raises `FieldError` (`Timer.unit: 'Bad' is not one of Tms, Ts, Tm, Th, Td`, reason `choice`) from `read_csv` and from building a `Timer`, where `read_csv` raised a `ValueError` (`Unknown timer unit: 'Bad'`). The CSV text and the encoded bytes do not change.
  - Do: rename the keywords and attributes (`Timer(kind="on_delay", done="T1", accumulator="TD1", preset="100", unit="Tms")`), match `Timer.preset`, `Timer.done`, `Timer.accumulator`, `Counter.done` and `Counter.accumulator` in `.field`, and catch `ValueError` or `FieldError` for a bad unit.
- **`Drum` fields take their CSV names**: `jump_target` is `jump_step`, as the CSV pin `.jump(step)` names it (`Drum.jump_target` is `Drum.jump_step` in `.field`); `drum_kind` is `kind`, valued with the CSV call name (`event_drum`, `time_drum`, `time_event_drum`, where it held `event`, `time`, `time_event`); `events_or_presets` is `events` on an event drum and `presets` on a time drum, and a time & event drum keeps both, as the CSV keywords do, so a drum given the one its kind does not use (`presets` on an event drum, `events` on a time drum) is refused with `FieldError` (reason `conflict`); the fields come in the order `kind`, `outputs`, `presets`, `events`, `pattern`. `outputs`, `presets`, `events` and `pattern` (a tuple of tuples) are tuples, and a list given in is stored as a tuple, so `Drum(outputs=["C1"]).outputs == ("C1",)`. Each `.field` of a `FieldError` follows (`Drum.drum_kind` is `Drum.kind`; `Drum.events_or_presets` is `Drum.events` or `Drum.presets`), and so does the message of a bad kind (`Drum.kind: 'x' is not one of event_drum, time_drum, time_event_drum`). `read_csv` raises a `FieldError` where it raised a `ValueError`: for a time or time & event drum `unit` that is not `Tms`, `Ts`, `Tm`, `Th` or `Td` (`Drum.unit: 'Bad' is not one of Tms, Ts, Tm, Th, Td`, where `Unsupported time drum unit: 'Bad'` for a time drum and `Unsupported time_event_drum unit: 'Bad'` for a time & event drum), for a time & event drum `accumulator` that is not `TD` (`Drum.accumulator: 'DS1' is not allowed; Drum.accumulator takes TD`, where `time_event_drum accumulator must be a TD address: 'DS1'`), for a blank `accumulator=` on a time & event drum (reason `missing`), and for a pattern cell that is not `0` or `1` (`Drum.pattern: 'x' is not allowed, cells are 0 or 1`, where `A pattern cell is 0 or 1: '[1,x]'`). A time or time & event drum token with no `unit=`, or a time & event drum token with no `accumulator=`, raises `CsvError` (`time_drum needs unit=`, `time_event_drum needs accumulator=`). `encode()` of a drum whose unit was changed after it was built to one with no func code says `Unsupported time_event_drum unit: ''` (`EncodeError`), where it said `Unsupported time_event drum unit: ''`. The CSV text and the encoded bytes do not change.
  - Do: rename the keywords and attributes (`Drum(kind="event_drum", outputs=("C1",), events=("X1",), ...)`, `Drum(kind="time_drum", presets=("1000",), ...)`), put an event drum's steps in `events` and a time drum's in `presets`, compare `outputs`, `presets`, `events` and `pattern` with tuples, match `Drum.kind`, `Drum.events`, `Drum.presets` and `Drum.jump_step` in `.field`, and catch `ValueError` or `FieldError` where you caught `ValueError` for a bad unit, accumulator or pattern cell.

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
