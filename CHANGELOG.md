# Changelog

<!-- Style guide: one sentence per entry. Describe the user-visible effect, not the
     implementation. Group related fixes/features into a single entry when they share
     a theme. Breaking changes and migration steps can be longer — users need the
     specifics. Detail belongs in commit messages and PR descriptions, not here.

     Review and condense before release — entries accumulate during development and
     should be edited into shape before moving from Unreleased to a version heading. -->

## Unreleased

### Added
- **Undecoded marker rungs**: `decode()` and `decode_program()` return a rung they can't read as a one-row rung into an `Undecoded` marker, with an `UndecodedRungWarning`, and the rungs around it decode; the marker acts as `end()` in the main program and `return()` in a subroutine, since a program that ran past a rung it could not read would run wrong.
- **`Program.undecoded`**: lists a program's undecoded markers, empty when every rung decoded.
- **`undecoded(...)` CSV token**: `write_csv` writes a marker and `read_csv` reads it back; `encode()` refuses it, so it never reaches CLICK, and `check()` reports it as an `undecoded` finding.
- **Read errors say where**: an error `read_csv` raises for a bad CSV keeps its class and carries a `CsvLocation` (file, line, rung, row and column) as its `location`; a `ValueError` or `csv.Error` message ends with that location, a `UnicodeDecodeError` keeps its message and names the file only, and a `FieldError` refused while a box takes its pin rows still arrives as `ConvertError`, now with the refused field in `.field`.
- **Field errors say why**: a `FieldError` carries `reason` (a `Reason` such as `bank`, `range` or `conflict`), `click_id` (CLICK's own error id, such as `OBJ-005`, where it has one), `fields` (the one field, or both of a pair) and `errors` (every refusal of the construction, the raised one first). `Timer`, `Coil`, `Contact`, `CompareContact`, `OutVariant`, `Counter`, `Shift`, `Call`, `ForLoop`, `Drum`, `Search`, `Copy`, `BlockCopy`, `Fill`, `Pack`, `Unpack`, `Math`, `Send`, `Receive`, `ModbusRtuTarget`, `ModbusTcpTarget`, `ModbusAddress`, `RawInstruction` and `Undecoded` report every field they refuse, and a Math formula each address, constant, key or range it refuses; the other instructions report the first.
- **Read errors carry every refusal**: a `FieldError` from `read_csv` has a `location` on each refusal in `.errors`, not only the raised one, and the `ConvertError` of a refused pin row now carries `fields`, `reason`, `click_id` and `errors` as a `FieldError` does.
- **`RefusedFieldWarning`**: `decode()` and `decode_program()` emit one for each decoded instruction that holds a value CLICK's dialog refuses, with the instruction, its refusals, its rung and its program.
- **`read_csv(..., unchecked=True)`**: reads an instruction whose values its checks refuse as written, as the decoders read a stored one, with a `RefusedFieldWarning`, so the CSV `write_csv` writes for such an instruction reads back.
- **`constant_text()`**: writes a Python int, float or str as the constant text a `Math` or a `Copy` source takes, as building the instruction stores it (`constant_text(255, hex=True)` is `FFh`, `constant_text(1e3)` is `1000.0`, `constant_text("AB")` is `"AB"`).

### Fixed
- **Refusals read unchecked say where**: each refusal `read_csv(..., unchecked=True)` keeps carries the `CsvLocation` the default read raises it with (file, line, rung, row and column, a pin row's value at that pin's row), and the `RefusedFieldWarning` message ends with the first one's, where they carried no location.
- **Hex Math constant CLICK stores from `1e3`**: a hex `Math` holding `1E3h`, which CLICK stores for a constant typed `1e3`, decodes with no `RefusedFieldWarning` and reads back from CSV, where it was refused as a constant cut at its `E`.
- **Long MODBUS address and compare operator**: a Send or Receive `ModbusAddress` of more than 4300 digits is refused with a `FieldError` on `ModbusAddress.address`, where it crashed with `ValueError`, and a `CompareContact` operator outside `==`, `!=`, `<`, `>`, `<=` and `>=` is refused on `CompareContact.op`, where `build_blob` crashed with `KeyError`.
- **Unpack destination bank**: an Unpack destination whose bank the source can't unpack to, such as `DS1` into `DS1..DS2`, is refused with CLICK's `OBJ-004`, where it carried `OBJ-024`; the refusal itself is the same.
- **Copy, Pack and Unpack bank ids**: a bank the field does not take carries CLICK's id, where it had none: `OBJ-004` for a Pack destination and an Unpack source or destination, and for a single Copy into a bit bank it does not write, `OBJ-004` from a bit source and `OBJ-024` from any other; the refusal itself is the same.
- **Pack source module**: a Pack source range that spans two X or Y modules, such as `X001..X036`, is refused with CLICK's `OBJ-033`, where it had no id; the refusal itself is the same.
- **Copy termination code**: a `$` code that is no character code (`$ZZ`, `$D`) is refused with CLICK's `OBJ-036`, as a code with no `$` already was; the same values are accepted and refused.
- **SD or YD out of range as a hex Math result**: an SD register (SD1-SD1000), or a YD past YD8, is refused with CLICK's `OBJ-003` (outside the range) and a message that says so, and an SD past its bank's range (`SD0`, `SD1001`) with `OBJ-004`, where both had no id; the refusal itself is the same.
- **`check()` on a circuit that is not series-parallel**: such a rung gets its C0001 finding and no C000A finding or finding about a pin's contacts, as CLICK reports a bridge with an output above a retentive timer, where it also got C000A and C0205.
- **`check()` C000A on a pin's net**: another box's main input below a box's pin, on the pin's net, such as a timer fed from a counter's reset or a reset wire that also feeds an output, is a new `shared_input_net` finding, one per group of boxes that share nets, as CLICK reports it, where it got C0205 or a pin finding with no code; other boxes on a pin's net, a box below on a reset teed off the main input included, get it with `captured=False`, and so does `output_above_pinned_box` with a `NOP` or a box with a used pin above.
- **`check()` on an unwired reset**: a timer's or counter's reset whose row holds nothing is an `unwired_pin` finding, C0202 at its AF cell, as CLICK reports it, where `check()` reported nothing, and `read_csv` still lays such a rung out; another pin whose row holds nothing, or a pin row of wires that no rail or contact reaches, gets C0202 with `captured=False`.
- **Receive TXT count ids**: a Receive TXT count below 2 is refused with CLICK's `OBJ-010` and an odd one with `OBJ-029`, where both had no id; the refusals themselves are the same.
- **Long digit runs in Compare and Out variants**: a constant of more than 4300 digits, such as a long run of leading zeros, no longer raises a bare `ValueError`; it reads as its value, or is refused with `FieldError` where its pairing or limit refuses it.
- **For count of thousands of digits**: a For count of more than 4300 digits (leading zeros) no longer raises a bare `ValueError`; it reads as its value, or is refused with `FieldError`; the messages for an above-limit count and a pointer count are reworded.
- **Long digit runs in Timer and Drum**: a Timer set point or Drum preset of more than 4300 digits (leading zeros) no longer raises a bare `ValueError`; it reads as its value, or is refused with `FieldError` above its limit, and a Counter preset that long is refused with `FieldError`.
- **Long DS Slave ID**: a Modbus target whose `device_id` is `DS` followed by more than 4300 digits raises `FieldError`, where it raised a bare `ValueError`.

### Changed
- **Receive TXT count up to 250**: a Receive into TXT takes an even count of 2 to 250 characters, as CLICK does, where laddercodec refused a count over 124; a count past 250 is refused with `OBJ-010` and its message names characters.
- **Math constant and display-form messages**: up to 4 hex digits without `h` in a hex `Math` (`7`, `005`, `FF`, `1e3`) are refused with a message that names the `h` form CLICK reads (`write 7h`), but for a signed argument of `RAND`, `LSH`, `RSH`, `LRO` or `RRO`, which CLICK refuses with its `h` too; those that are not all digits (`FF`, `abc`, `E5`, `DF`) no longer carry `OBJ-1001`, since CLICK takes them; an integer with leading zeros outside int32 (`06000000000`) says its leading zeros are refused, where it said it was out of range; a name or address refused under `display_form_only()` for not being in display form names its field at the start of its message, as other refusals do; which values are refused is the same.
- **Reworded refusals**: the messages for Compare, Out variant, Timer set point, Counter preset, Drum preset, Modbus hex address, Copy, Fill and Search value fields are reworded, and a refusal that carries CLICK's error id ends with it, such as `(OBJ-004)` for a bank Out, Set, Reset, Timer, Counter, Drum, For, Math or Shift does not take and `(OBJ-003)` for an SC bit a coil can't write; the refusals themselves are the same.
- **Field errors name the field**: `FieldError.field` now names the field for a Compare pairing refusal, for Drum step counts, output counts and steps with neither a duration nor an event, for Send, Receive and Modbus target refusals, such as `Send.quantity` or `ModbusTcpTarget.port`, and for a bad Copy or BlockCopy format, Copy `exponential` or termination code, Pack or Unpack type, and `rows=` or `sub=` in a `raw(...)` token; `field` is always `Class.attr` of the instruction refused, so an event drum's event is `Drum.events_or_presets[i]`, where it was `Drum.events[i]`, a drum preset is `Drum.events_or_presets[i]`, where it was `Drum.presets[i]`, a refusal under `display_form_only()` names its field, and a refusal of `undecoded(...)` token syntax names none.
- **Undecoded comments keep their text**: a comment that doesn't decode now reads `UNDECODED comment: <error>` followed on the next line by the plain text that could be read from its bytes, cut and ended with `...` where it would be too long to encode, so `encode()` writes the text back into CLICK.
- **Docs site follows releases**: the published docs update when a release is published, not on every change to `main`.
- **Math X/Y option-slot range message**: the refusal of a `Math` X or Y range with an end in X021-X036 or Y021-Y036 now names the end or ends in the option slot and says CLICK sums the wrong bits for the range (`SUM ( X001 : X036 ) is refused: X036 is in the option slot (X021-X036), and CLICK sums the wrong bits for this range.`), where it listed the points CLICK would leave out or add; the same ranges are accepted and refused.

### Behaviour changes
- **A rung that doesn't decode no longer fails the call**: a down wire in the output column or wire flags no token has gives an undecoded marker for the rung, and a clipboard row the walk can't read or a program file record whose framing breaks gives one marker for that rung and every rung after it, where `decode()` and `decode_program()` raised `DecodeError` or `ValueError`.
  - Do: check `Program.undecoded`, or catch `UndecodedRungWarning`, where you caught those errors; a buffer whose magic, size or program header is wrong still raises.
- **Comments that don't decode**: the rung keeps its logic, its comment becomes `UNDECODED comment: <error>`, and `decode()` and `decode_program()` emit an `UndecodedCommentWarning`, where `decode()` raised `DecodeError` and `decode_program()` kept the rung with no comment.
- **`write_csv` writes a marker for a rung it can't write**: a rung holding an unknown condition or instruction is written as an undecoded marker, with an `UndecodedRungWarning`, where `write_csv` raised `WriterError`; its new `stop` argument gives the marker's `stop`.
  - Do: pass `stop="return"` when writing a subroutine.
- **Flags refuse a non-flag value**: the flags of `Copy`, `BlockCopy`, `Fill`, `Pack` (`allow_whitespace`, `oneshot`), `Unpack`, `Search` (`continuous`, `oneshot`), `Math`, `ForLoop`, `OutVariant` (`immediate`, `maintained`), `Send` and `Receive` (`word_swap`) now raise `FieldError` for a value other than True, False, 1 or 0, where they accepted it; `oneshot=2` was written as `oneshot=1`.
  - Do: pass True, False, 1 or 0.
- **A blank field is refused as `missing`**: an empty required field, in any instruction or Modbus target, has `FieldError.reason` `missing`, where it had the reason of a bad value (`address` for a blank address, `kind` for a blank Out variant or Counter preset, `choice` for a blank unit, type or mode, `form` or `conflict` for a blank Copy termination code, `form` for a blank Modbus target `ip`, `kind` for a blank `ModbusAddress.address`); a Copy `termination_code=""` no longer carries `OBJ-036`; which values are accepted, the field each refusal names and the other ids are unchanged.
  - Do: where you read `reason` to tell a blank from a bad value, test for `Reason.MISSING`; where you matched a blank on `address`, `kind`, `choice`, `form` or `conflict`, match `missing` instead.
- **A stored value CLICK's dialog refuses no longer makes a cell raw**: the instruction decodes with the value as stored and a `RefusedFieldWarning`, where it decoded as `raw(...)` or an unknown condition. Unchanged, it encodes as the raw cell did. Changed, it is checked again: `encode()` raises the `FieldError` building it raises, or encodes the fix as building it would. Read with `read_csv(..., unchecked=True)`, or a condition decoded by `decode_program()`, it has no bytes to write, and `encode()` raises that error. An address not in display form, a value outside a field's named values, refused pin rows, a value a check crashes on, a Math in nickname view and an instruction whose CSV would not read back as itself still decode as raw, and so does text that is no number in a numeric field, which decoded as the field's default. A Copy or Pack destination stored with an edge space decodes as the address without it, and encodes as stored while unchanged.
  - Do: nothing to decode and encode a rung unchanged. Catch `RefusedFieldWarning` to find these instructions; fix the field each names before you encode one you read from CSV.
- **Math and Copy constants are written as CLICK stores them**: a real in a `Math` or a single `Copy` source is the value CLICK prints back (`1.50` is `1.5`, `1e3` is `1000.0`, `.5` is `0.5`, `1E5` is `100000.0`), a `Copy` source drops an integer's leading zeros (`005` is `5`) and the `-` of zero (`-0` is `0`), drops a real's typed `+` (`+1.5` is `1.5`), writes a real typed in exponent form that 7 significant digits don't print exactly in 7 (`3.4028235E+38` is `3.402823E+38`, a slightly smaller value) and writes hex with uppercase digits and `h` (`0ffh` is `0FFh`), and a `Copy` of `$1` to TXT is accepted and written `$01`; `to_csv()`, `write_csv` and `encode()` write that form, where they kept the typed text, and the instruction built from either spelling is equal; `copy(EH,...)` and `copy(1Eh,...)` are refused, where they were read as hex 14 and 30, since CLICK stores them as the reals 0.0 and 1.0.
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
  - Do: write `3.402823466E+38` for float32's largest value, as `constant_text()` does.
- **A blank CSV token argument is `missing`**: in `read_csv`, a blank argument or keyword value, such as `out()`, `on_delay(T1,TD1,preset=,unit=Tms)` or `blockcopy(,DS10..DS13)` (`blockcopy(..,DS10..DS13)` as `write_csv` writes a blank range), is refused with a `FieldError` whose `reason` is `missing` and whose `field` is the blank one, as building the instruction with that field blank is. It was a token syntax error with no `field` (for `out(,oneshot=1)`, an `address` refusal of `oneshot=1`). `read_csv(..., unchecked=True)` keeps it as it keeps any refusal. A Timer or time drum `unit=`, a Math `mode=`, a drum list, a search expression and a blank flag in `out` or `for` are still syntax errors, and `out(,oneshot=)` is still an `address` refusal of `oneshot=`.
  - Do: where you told a syntax error from a field refusal by `field is None`, expect `field` and `Reason.MISSING` for a blank argument.

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
