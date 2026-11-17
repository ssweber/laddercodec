# Changelog

<!-- Entries follow the CHANGELOG rule in the bob plugin's `writing` skill: say what
     changed for the user and what they must do, in two or three short sentences.
     Breaking changes may be longer. State each entry against the last release. -->

## Unreleased

### Added
- **One error tree**: every error that `decode()`, `decode_program()`, `encode()`, `read_csv()`, `write_csv()` and `check()` raise for input they can't read or write is a `LaddercodecError`, and each is still a `ValueError`. The classes are `DecodeError`, the new `EncodeError`, `CsvError`, `WriterError`, and `FieldError` with its subclass `AddressError`. `except LaddercodecError` catches all of them.
- **More top-level exports**: `laddercodec` now exports `LaddercodecError`, `DecodeError`, `EncodeError`, `CsvError`, `WriterError`, `UnknownCondition`, `UnknownInstruction`, `Email`, `Home`, `Position`, `Velocity`, `ConditionInstruction`, `AfInstruction`, `ConditionToken` and `AfToken`.
- **Undecoded markers**: when `decode()` or `decode_program()` can't read a rung, they return an `Undecoded` marker for it, emit an `UndecodedRungWarning` and go on to decode the other rungs. The marker acts as `end()` in the main program and `return()` in a subroutine. `Program.undecoded` lists the markers. `write_csv` writes a marker as an `undecoded(...)` token and `read_csv` reads it back. `encode()` rejects a marker, and `check()` reports it as an `undecoded` finding.
- **Where a CSV error happened**: an error from `read_csv` has a `CsvLocation` (file, line, rung, row and column) as its `location`, and its message ends with it. A `FieldError` from a pin row now arrives as `CsvError` (`ConvertError` in v0.4.0) and has `.field`, `fields`, `reason`, `click_id` and `errors`. Each refusal in `.errors` has its own `location`.
- **Why a field was refused**: a `FieldError` now has `reason` (a `Reason` such as `bank`, `range` or `conflict`), `click_id` (CLICK's own id, such as `OBJ-005`, when CLICK has one), `fields` (the field, or both fields of a pair) and `errors` (every refusal for the construction, the raised one first). Most instructions report every field they refuse. The rest report the first.
- **`RefusedFieldWarning` and `read_csv(..., unchecked=True)`**: `decode()` and `decode_program()` emit a `RefusedFieldWarning` for each instruction that holds a value CLICK's dialog refuses. `read_csv(..., unchecked=True)` reads such an instruction as written, with the same warning, so the CSV that `write_csv` wrote for it reads back.
- **`constant_text()`**: returns the text that a `Math` or `Copy` source stores for a Python int, float or str. `constant_text(255, hex=True)` is `FFh`, and `constant_text(1e3)` is `1000.0`.

### Fixed
- **Copy conversions CLICK saves**: a single Copy between DF and CTD, between real and integer kinds, of a real constant into DD or CTD, or of an integer constant outside int16 into DF now encodes with conversion type 7, as CLICK saves it. `convert=to_binary` on these copies is accepted and encodes as conversion type 8. v0.4.0 wrote a plain copy and refused `to_binary`. CLICK's saves of these copies decode as the `Copy`, where v0.4.0 read them as `raw(Copy,...)`.
- **Copy into TXT**: a single Copy of an integer, hex or real constant into TXT now writes the last TXT its text fills, as CLICK does. A real constant or a DF pointer to text now writes real numbering (conversion type 3), or exponential numbering (type 4) with `exponential=1`. CLICK's saves of these copies, and of quoted text with no end, decode as the `Copy`. A Copy blob that CLICK never makes (conversion type 3 from `DS1`) decodes as `raw(Copy,...)`.
- **Copy and Search text**: a single Copy source or a Search value of quoted text can hold any character from U+0001 to U+FFFF except a surrogate, and `read_csv` reads a line break inside quotes. v0.4.0 refused both. NUL and characters above U+FFFF are still refused.
- **Copy past TXT1000**: a number constant copied to text that runs past TXT1000 (`-5` into TXT1000) is refused with an `AddressError` on the destination, with `OBJ-003`. v0.4.0 accepted it.
- **Termination codes**: a single Copy of TXT into TXT accepts `termination_code=$0D`, and a Block Copy of TXT into TXT keeps its code through `decode()`, `encode()` and `read_csv`. v0.4.0 refused the first and dropped the second.
- **Addresses CLICK saves as typed**: a Copy, Block Copy or Pack destination, an address in a Math formula or a hex Math result that CLICK saved as typed (`DS001`, `ds1`, `YD0U`) now decodes as the instruction, in display form. v0.4.0 decoded it as `raw(...)`.
- **Empty flag fields**: `decode()` now reads an empty flag field as set. v0.4.0 read it as clear, so a hex Math or a one-shot from `decode_program()` lost its flag when you encoded it and decoded it again.
- **`check()` findings**: a contact in parallel with a wire-only leg is now `C0002`, and a contact that feeds only a `NOP` is now `C0003` (the new kind `nop_only_contact`). A timer's or counter's reset with nothing wired is now an `unwired_pin` finding, `C0202`. Another box below a box's pin, on the pin's net, is now a `shared_input_net` finding. v0.4.0 reported none of these. A rung that is not series-parallel now gets only `C0001`.
- **Hex Math `1E3h`**: a hex `Math` holding `1E3h`, which CLICK stores for a constant typed `1e3`, now decodes without a `RefusedFieldWarning` and reads back from CSV.
- **Crashes on very long digit runs and bad values**: a constant, For count, Timer set point, Drum preset or DS Slave ID of more than 4300 digits no longer raises a bare `ValueError`. It reads as its value or is refused with `FieldError`. A `ModbusAddress` of more than 4300 digits and a `CompareContact` operator that is not `==`, `!=`, `<`, `>`, `<=` or `>=` are refused with `FieldError`, where v0.4.0 raised `ValueError` and `KeyError`.
- **CLICK's ids on refusals**: refusals that had no id now carry CLICK's. They include `OBJ-004` and `OBJ-024` for banks that Unpack, Pack and Copy do not take, `OBJ-1009` for a DH unpacked into a Y range across two slots, `OBJ-033` for a Pack source across two X or Y modules, `OBJ-036` for a termination code that is not a character code, `OBJ-004` for a Receive of function code 01 from a register, `OBJ-003` and `OBJ-004` for SD and YD out of range as a hex Math result, and `OBJ-010` and `OBJ-029` for a bad Receive TXT count. The same values are refused as before.

### Changed
- **Receive TXT count**: a Receive into TXT now accepts an even count of 2 to 250 characters, as CLICK does. v0.4.0 refused a count over 124.
- **Refusal order**: a single `Copy` whose constant source is refused for its own value now raises a `FieldError` on `Copy.source` before the destination is checked. v0.4.0 raised an `AddressError` on `Copy.destination` for `copy("",DS1)`. An Out, Set or Reset range whose end is in another bank now raises a `FieldError` with reason `conflict` and `OBJ-008` on both ends, where v0.4.0 raised an `AddressError` on `Coil.range_end`. The same values are refused.
- **Field errors name the field**: `FieldError.field` is now `Class.attr` of the instruction refused for more refusals, such as `Send.quantity`, `ModbusTcpTarget.port`, `Drum.events[i]` and `Drum.presets[i]`. A refusal under `display_form_only()` names its field too.
- **Reworded refusals**: the messages of many refusals changed, and a refusal that has a CLICK id ends with it, such as `(OBJ-004)`. Match on `reason`, `click_id` and `field`, not on message text.
- **Undecoded comments**: a comment that doesn't decode now reads `UNDECODED comment: <error>`, followed by the plain text that could be read. `encode()` writes that text back into CLICK.
- **Docs site follows releases**: the published docs update when a release is published, not on every change to `main`.

### Behaviour changes
- **`decode()` always returns a list**: `decode()` returns a `list[Rung]` for every buffer, a list of one for a single-rung clipboard. v0.4.0 returned the `Rung` itself for one rung. `encode()` is annotated as taking a `Rung` or an iterable of rungs and returning `bytes`.
  - Do: unpack a single rung with `[rung] = decode(data)`, and drop any `isinstance(result, list)` check.
- **Contact and Coil are built by kind, with the operand first**: `Contact(operand, kind="no", immediate=False, wire_down=False)` takes a `kind` of `"no"`, `"nc"`, `"rise"` or `"fall"`. `Coil(operand, kind="out", range_end=None, immediate=False, oneshot=False)` takes a `kind` of `"out"`, `"latch"` or `"reset"`. v0.4.0 took an `InstructionType` as `type`, first, and `edge_kind` for an edge contact. An edge contact with no edge, and an NO or NC contact with one, can no longer be built. Refusals name `Contact.kind` and `Coil.kind` where they named `Contact.type`, `Contact.edge_kind` and `Coil.type`.
  - Do: write `Contact("X001", kind="nc")` for `Contact(InstructionType.CONTACT_NC, "X001")`, `Contact("X001", kind="rise")` for `Contact(InstructionType.CONTACT_EDGE, "X001", edge_kind="rise")` and `Coil("Y001", kind="latch")` for `Coil(InstructionType.COIL_LATCH, "Y001")`. Pass `immediate`, `range_end` and `oneshot` by keyword, and read `.kind` where you read `.type` or `.edge_kind`.
- **Immediate edge contacts are refused**: `read_csv` of `rise(X001).immediate` or `immediate(fall(X001))`, and `Contact.from_csv_token`, now raise `FieldError` on `Contact.immediate` and `Contact.kind`, with reason `conflict`. v0.4.0 raised `ValueError`. With `unchecked=True` the contact is kept as written.
  - Do: catch `FieldError`, or `ValueError`, for these.
- **Error classes**: `encode()` raises `EncodeError` where it raised a bare `ValueError`, and for an `Undecoded` marker. `read_csv` raises `CsvError` where it raised a bare `ValueError`. `decode_program()` raises `DecodeError` for a file header it can't read and for a program name that is not UTF-16 text, where it raised `UnicodeDecodeError`. `ConvertError` is renamed `CsvError`, and `laddercodec.csv.converter.ConvertError` is gone. Each is a `ValueError`.
  - Do: catch `CsvError` where you caught `ConvertError`. `except ValueError` needs no change.
- **Errors that were not `ValueError`s**: `read_csv` raises `CsvError` for a file that isn't UTF-8, where it raised `UnicodeDecodeError`, and for a `csv.Error`, where it raised the `csv.Error`. The original is `__cause__`. A `send` or `receive` with no `target=` or `remote_start=` raises `CsvError`, where it raised `KeyError`. `encode()` raises `EncodeError` for a rung holding an `UnknownCondition` or `UnknownInstruction`, where it raised `TypeError` or `AttributeError`.
  - Do: catch `CsvError`, or `ValueError`, where you caught `UnicodeDecodeError`, `csv.Error` or `KeyError` around `read_csv`.
- **Empty text set after building**: `encode()` of a `Copy` or `Fill` whose text was set to `""` after it was built raises `FieldError`. v0.4.0 raised a bare `ValueError`.
- **A rung that doesn't decode no longer fails the call**: a down wire in the output column, or a wire flag that no token matches, gives an `Undecoded` marker for that rung. A clipboard row that can't be read, or a program record with broken framing, gives one marker for that rung and every rung after it. v0.4.0 raised `DecodeError` or `ValueError`. A buffer with a wrong magic, size or program header still raises `DecodeError`. A comment that doesn't decode keeps its rung, and `decode()` and `decode_program()` emit an `UndecodedCommentWarning`. v0.4.0 raised `DecodeError` in `decode()` and dropped the comment in `decode_program()`.
  - Do: check `Program.undecoded`, or catch `UndecodedRungWarning` and `UndecodedCommentWarning`, where you caught those errors.
- **`write_csv` writes a marker for a rung it can't write**: a rung holding an unknown condition or instruction is written as an undecoded marker with an `UndecodedRungWarning`. v0.4.0 raised `WriterError`. The new `stop` argument sets the marker's `stop`.
  - Do: pass `stop="return"` when you write a subroutine.
- **A stored value CLICK's dialog refuses no longer makes a cell raw**: `decode()` and `decode_program()` now decode the instruction with a `RefusedFieldWarning`. v0.4.0 decoded it as `raw(...)` or an unknown condition. Unchanged, it encodes as before. If you change it, `encode()` checks it again and raises the `FieldError` that building it raises. An instruction that `read_csv(..., unchecked=True)` read, or a condition from `decode_program()`, has no bytes to write, so `encode()` raises that error. Some values still decode as raw, such as an address not in display form outside the fields CLICK saves as typed.
  - Do: nothing to decode and encode a rung unchanged. Catch `RefusedFieldWarning` to find these instructions, and fix the field it names before you encode one you read from CSV.
- **Math and Copy constants are written as CLICK stores them**: a real in a `Math` or a single `Copy` source is the value CLICK prints back (`1.50` is `1.5`, `1e3` is `1000.0`, `+1.5` is `1.5`). A `Copy` source drops an integer's leading zeros and the `-` of zero, and writes hex with uppercase digits (`0ffh` is `0FFh`). `to_csv()`, `write_csv` and `encode()` write that form, where they kept the typed text. `copy(EH,...)` and `copy(1Eh,...)` are refused, where v0.4.0 read them as hex 14 and 30. CLICK stores them as the reals 0.0 and 1.0.
  - Do: compare constants in CLICK's form, or build both sides through the instruction. Write `0.0` or `14` where you wrote `EH`, and `1.0` or `30` where you wrote `1Eh`.
- **A Copy real keeps 7 significant digits, a Math real keeps 6**: a real constant in a single `Copy` typed with more than 7 significant digits (`copy(1.2345678,DF1)`), or in a decimal `Math` with more than 6 (`0.33333334`), raises `FieldError` with reason `form`. The message names the constant to write (`1.234568`, `0.333333`). v0.4.0 wrote it as typed, and CLICK saves it cut. A decimal `Math` real above float32's largest value, such as `3.4028235E+38`, raises `FieldError` with `OBJ-1009` and reason `range`. A decoded program that holds one decodes it with a `RefusedFieldWarning` and encodes it unchanged.
  - Do: write the constant the message names. For float32's largest value in a `Math`, write `3.40282E+38`. Use a Math where a Copy needs more digits.
- **`to_text` for a real constant or a DF pointer takes `exponential`**: a real constant or a DF pointer copied to text is written `to_text(exponential=0)` or `to_text(exponential=1)`, as a DF address is. `suppress_zero` on any of the three raises `FieldError` with reason `conflict`. v0.4.0 accepted it, and ignored it for a DF address. `Copy.suppress_zero` is now `None` by default for a DF or real source to text.
  - Do: write `exponential=0` where you wrote `suppress_zero` for a real constant or a DF pointer, and drop `suppress_zero` for a DF address.
- **A number into TXT needs a converter**: a single Copy of a number constant, register or pointer into TXT with no converter (`copy(5,TXT1)`, `copy(DS1,TXT1)`) raises `FieldError` with reason `conflict`. v0.4.0 accepted it and wrote a plain copy, which CLICK never saves. A decoded program that holds one decodes it with a `RefusedFieldWarning` and encodes it unchanged.
  - Do: write `convert=to_text(suppress_zero=1,termination_code=none)`, CLICK's default. For a real constant or a DF source, write `convert=to_text(exponential=0,termination_code=none)`.
- **TXT into a number**: a plain single Copy of TXT into DS, DD, DH, YD, TD, CTD or SD, and a plain Block Copy of TXT into DS, DD or DH, now raise `FieldError` with reason `conflict`. A single Copy of TXT into DF with `to_value` or `to_ascii`, a `Copy` from TXT with `suppress_zero=True`, and a Block Copy of TXT into TXT with `to_value` or `to_ascii` raise it too. v0.4.0 accepted all of these. A TXT register into DF stays a plain copy. A decoded program that holds one decodes it with a `RefusedFieldWarning` and encodes it unchanged.
  - Do: write `convert=to_value` for the character's value or `convert=to_ascii` for its ASCII code into a number other than DF. For the other cases, drop `suppress_zero` or the converter.
- **A termination code only where CLICK offers one**: `termination_code=$XX` on a `copy` or `blockcopy` other than TXT into TXT raises `FieldError` with reason `conflict`. v0.4.0 dropped it without a word. `termination_code=none` or `0` is still accepted.
  - Do: drop the code, or write it inside `to_text(...)` or `to_binary(...)` for a number copied to TXT.
- **Unknown Copy-family keywords raise**: a keyword that `copy`, `blockcopy`, `fill`, `pack_*` or `unpack_to_*` does not take, such as a misspelt `terminaton_code=` or `suppress_zero=1` outside `to_text(...)`, now raises `CsvError`. v0.4.0 dropped the keyword and its value. `allow_whitespace=1` in `pack_bits` or `pack_words` raises it too.
  - Do: spell the keyword as the docs do, and put `suppress_zero` and `exponential` inside `to_text(...)`.
- **A Pack of text into DH takes 4 characters**: `pack_text` of more than 4 TXT registers into DH, such as `pack_text(TXT1..TXT16,DH1)`, is refused with `OBJ-003` and reason `range`. v0.4.0 accepted it. A decoded program that holds one decodes it with a `RefusedFieldWarning` and encodes it unchanged.
  - Do: pack at most 4 TXT characters into a DH.
- **A Pack source is counted before its pairing**: a Pack source longer than any pairing takes now raises `FieldError` on `Pack.source_end` with CLICK's count id (`OBJ-041` for bits, `OBJ-040` for DH words). v0.4.0 raised `AddressError` on `Pack.destination` with no id. The same values are refused.
  - Do: catch `FieldError` where you caught `AddressError` for these, and read `.errors` for the pairing.
- **Flags refuse a non-flag value**: a flag of `Copy`, `BlockCopy`, `Fill`, `Pack`, `Unpack`, `Search`, `Math`, `ForLoop`, `OutVariant`, `Send`, `Receive` or `Coil` now raises `FieldError` for a value other than True, False, 1 or 0, with reason `flag`. In CSV text, a blank flag (`oneshot=`) raises it with reason `missing`. v0.4.0 read text such as `oneshot=yes` as off and wrote `oneshot=2` as `oneshot=1`. A `Pack` built with `allow_whitespace=True` for bits or words also raises `FieldError` with reason `conflict`, where v0.4.0 accepted it and did not encode it.
  - Do: pass True, False, 1 or 0, and drop `allow_whitespace` for `pack_bits` and `pack_words`. Catch `FieldError`, or `ValueError`, where you caught a `ValueError` message.
- **A blank field is refused as `missing`**: an empty required field now has `FieldError.reason` `missing`. In `read_csv`, a blank argument such as `out()` or `blockcopy(,DS10..DS13)` raises `FieldError` with that reason and the blank `field`. v0.4.0 gave the reason of a bad value (`address`, `kind`, `choice`, `form` or `conflict`), or a token syntax error with no `field`. A Copy `termination_code=""` no longer carries `OBJ-036`.
  - Do: test for `Reason.MISSING` where you read `reason` to tell a blank from a bad value. Expect `field` to be set where you told a syntax error from a field refusal by `field is None`.
- **Hex Math formula and SD writes follow CLICK**: a hex `Math` formula holding a DS register or a bit in a `SUM` is refused with `OBJ-1002`. An SD register that a program can't write is refused as a `Copy` destination, in a `BlockCopy` destination range and as a decimal `Math` result, with reason `not_writable`. v0.4.0 accepted all of these. A decoded program that holds one decodes it with a `RefusedFieldWarning` and encodes it unchanged.
  - Do: change such a value before you build or read the instruction.
- **Each Math mode takes its own banks**: a hex `Math` formula takes hex constants and the DH, XD and YD registers only. A decimal one takes decimal constants and the DS, DD, DF, TD, CTD and SD registers, with X, Y, C, T and SC bits only as the range of a `SUM`. Every other address is refused with `OBJ-1002` and reason `bank`. A `SUM` over CT is refused with `OBJ-1002` in both modes. A range with ends in two banks (`OBJ-1015`) or reversed (`OBJ-1014`) is refused with that id first. v0.4.0 accepted a DD, DF, TD, CTD, SD or TXT register in a hex formula, and a DH, XD, YD or TXT register in a decimal one.
  - Do: for a hex formula, copy the register into a DH first, pack the bits into a DH, or use a decimal `Math`. For a decimal formula, copy a DH, XD, YD or TXT register into a DS first, or use a hex `Math`.
- **RAND bounds follow CLICK**: a bound of a decimal `RAND` takes a DS or DD register or an integer constant. A hex `RAND` takes a DH register or a hex constant. The two bounds must differ. A bank that doesn't fit is refused with `OBJ-1002` and reason `bank`. A real bound (`RAND ( 1.5 , 10 )`) and equal bounds are refused with `OBJ-1001`. v0.4.0 accepted all of these. A decoded program that holds one decodes it with a `RefusedFieldWarning` and encodes it unchanged.
  - Do: copy the register into a DS, DD or DH first, write an integer bound, and write two different bounds.
- **`Timer` and `Counter` fields take their CSV names**: `Timer.timer_type` and `Counter.counter_type` are `kind`, valued with the CSV call name (`on_delay`, `off_delay`, `count_up`, `count_down`). `done_bit` is `done`, `current` is `accumulator`, and `Timer.setpoint` is `preset`. `FieldError.field` and the messages follow, so `Timer.setpoint` is `Timer.preset` and `Counter.current` is `Counter.accumulator`. A Timer `unit` that is not `Tms`, `Ts`, `Tm`, `Th` or `Td` raises `FieldError` with reason `choice` from `read_csv` and from building a `Timer`. v0.4.0 raised `ValueError` from `read_csv`. The CSV text and the encoded bytes do not change.
  - Do: rename the keywords and attributes (`Timer(kind="on_delay", done="T1", accumulator="TD1", preset="100", unit="Tms")`), match the new names in `.field`, and catch `ValueError` or `FieldError` for a bad unit.
- **`Drum` fields take their CSV names**: `jump_target` is `jump_step`, and `drum_kind` is `kind`, valued `event_drum`, `time_drum` or `time_event_drum` where v0.4.0 held `event`, `time` or `time_event`. `events_or_presets` is `events` on an event drum and `presets` on a time drum, and a time & event drum has both. A drum given the one its kind does not use is refused with `FieldError` (reason `conflict`). `outputs`, `presets`, `events` and `pattern` are tuples, and a list you pass in is stored as a tuple. `FieldError.field` follows (`Drum.drum_kind` is `Drum.kind`, `Drum.events_or_presets` is `Drum.events` or `Drum.presets`). `read_csv` now raises `FieldError` where it raised `ValueError` for a bad time drum `unit`, a time & event drum `accumulator` that is not `TD` or is blank, and a pattern cell that is not `0` or `1`. A time or time & event drum token with no `unit=` or `accumulator=` raises `CsvError`. The CSV text and the encoded bytes do not change.
  - Do: rename the keywords and attributes (`Drum(kind="event_drum", outputs=("C1",), events=("X1",), ...)`, `Drum(kind="time_drum", presets=("1000",), ...)`), compare `outputs`, `presets`, `events` and `pattern` with tuples, match `Drum.kind`, `Drum.events`, `Drum.presets` and `Drum.jump_step` in `.field`, and catch `ValueError` or `FieldError` where you caught `ValueError`.
- **`Math`, `Search`, `ForLoop` and `RawInstruction` fields take their CSV names**: `Math.result` is `dest`. `Search.comparison` is `op`, and `Search.source` is `value`. `ForLoop.limit` is `count`. `RawInstruction.visual_rows` and `sub_rows` are `rows` and `sub`. `FieldError.field` follows (`Math.result` is `Math.dest`, `Search.source` is `Search.value`, `Search.comparison` is `Search.op`, `ForLoop.limit` is `ForLoop.count`). The CSV text and the encoded bytes do not change.
  - Do: rename the keywords and attributes (`Math("DS1 + 1", dest="DS2")`, `Search(..., value="DS1", result="DS20", found="C1", op="==")`, `ForLoop(count="3")`, `RawInstruction(name, blob, 1, rows=2, sub=3)`), and match the new names in `.field`. pyrung's `raw()` reads `visual_rows` and `sub_rows` from a decoded `RawInstruction`, so read `rows` and `sub`.
- **`Copy`, `BlockCopy`, `Pack` and `Unpack` fields take their CSV names**: `destination` is `dest` (`Copy`, `Pack`). `format` is `convert` (`Copy`, `BlockCopy`), valued `None`, `"to_value"`, `"to_text"`, `"to_binary"` or `"to_ascii"` where v0.4.0 held `"none"`, `"value"`, `"text"`, `"binary"` or `"ascii"`. `pack_type` and `unpack_type` are `kind`, valued `"pack_bits"`, `"pack_words"`, `"pack_text"`, `"unpack_to_bits"` or `"unpack_to_words"` where v0.4.0 held `"bits"`, `"words"` or `"text"`. `Copy.suppress_zero` is `True`, `False` or `None`, and `Copy.exponential` is `True` or `False`, where v0.4.0 held `"0"` or `"1"`. The strings `"0"` and `"1"` are no longer accepted, and a bad value is refused with reason `flag`. `FieldError.field` follows (`Copy.destination` is `Copy.dest`, `Copy.format` is `Copy.convert`, `Pack.pack_type` is `Pack.kind`). The CSV text and the encoded bytes do not change.
  - Do: rename the keywords and attributes (`Copy("DS1", "TXT1", convert="to_text", suppress_zero=True)`, `Pack("C1", "C16", "DS1", kind="pack_bits")`), match the new names in `.field`, and pass `True` or `False` for `suppress_zero` and `exponential`.

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
