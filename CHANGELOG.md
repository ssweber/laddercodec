# Changelog

<!-- Style guide: one sentence per entry. Describe the user-visible effect, not the
     implementation. Group related fixes/features into a single entry when they share
     a theme. Breaking changes and migration steps can be longer — users need the
     specifics. Detail belongs in commit messages and PR descriptions, not here.

     Review and condense before release — entries accumulate during development and
     should be edited into shape before moving from Unreleased to a version heading. -->

## Unreleased

### Added
- **Legacy encoding warning**: `decode()` and `decode_program()` emit `LegacyEncodingWarning` (a `UserWarning`, exported from `laddercodec`) for a Math decimal constant outside -32768..32767 stored as 16-bit (`H70000`), which earlier versions wrote and CLICK runs as its low 16 bits (`RAND ( 70000 , 70002 )` ran as `RAND(4464, 4466)`). The rungs still decode; the warning has `instruction`, `token`, `detail`, `rung` and `program` attributes. Re-paste the rung to store the constant as 32-bit.

### Changed
- **Email, Home, Position and Velocity height**: an Email, Home, Position or Velocity box, decoded or read from CSV as `raw(Email,...)` and the like, spans CLICK's 3 rows and is written as a 3-row box; earlier versions wrote 1 row, which CLICK shows until the box's dialog is saved. A CSV with such a box and an output on the next row reads with blank rows under the box and the output moved below them, as for other tall boxes (2 CSV rows read as 4). A copied-back rung whose box CLICK still stores at 1 row decodes as `raw(...)`, re-encodes as stored, and `write_csv` raises `WriterError` for it; save the box's dialog in CLICK and copy the rung again.
- **Math hex constants**: a hex constant in a Math expression is written as CLICK shows it, uppercase digits without leading zeros (`0fH` is `Fh`, `00h` is `0h`); earlier versions kept the typed digits (`0fh`). A constant typed with more than 4 digits, zeros included (`0FFFEh`), is refused.
- **Math sign on a hex constant**: `DH1 + ( -Ah )` is stored as `( - Ah )`, the sign its own token, as CLICK writes it; earlier versions joined the sign (`-Ah`), which CLICK never writes. A stored `( -Ah )` still decodes, as `( - Ah )`; after an operator (`DH1 + -Ah`) it decodes as `raw(...)`. Re-encoding a stored lowercase or zero-padded hex constant (`0fh`) writes CLICK's form (`Fh`), so those bytes change though the value does not.
- **Math words**: a Math expression with a word that is no address, function name or constant (`DS1 + FOO`, `DS1 + DS1X`, `DH1 + 7H7`), accepted before as an unknown word, raises `FieldError`. A stored Math that laddercodec wrote earlier with such a word, with more than four typed hex digits, or with an empty template whose internal-form fallback no longer parses, now decodes as raw and keeps its bytes.
- **Math formula grammar**: a Math formula is read as CLICK's Math dialog reads it, and a formula it refuses raises `FieldError`. Accepted before and refused now:
  - a sign right after an operator (`DS1 * -5`, `DS1 - -5`; `DS1 * ( -5 )` is still accepted);
  - an operator or value out of place (`DS1 +`, `* DS1`, `DS1 DS2`, `2 PI`, `( DS1 ) ( DS2 )`, `( )`);
  - a function without parentheses (`SIN DF1`, `SUM DS1`);
  - `RAND`, `LSH`, `RSH`, `LRO` or `RRO` without exactly two one-token arguments (`RAND ( DS1 + 1 , 2 )`, `LSH ( RSH ( DH1 , 1h ) , 2h )`), or with a constant as the first argument of a shift or rotate (`LSH ( 1h , 2h )`);
  - `SUM`, `MAX`, `MIN`, `MDN` or `AVG` around anything but a range of two addresses (`SUM ( DS1 + DS2 )`, `SUM ( DS1 )`, `SUM ( DS1 : DS3 : DS5 )`, `SUM ( 1 : 5 )`);
  - a `,` outside those two-argument calls (`DS1 , DS2`, `MAX ( DS1 , DS2 )`, `DS1 + 1 , 5`) and a `:` outside those ranges (`DS1 : DS5`, `ABS ( DS1 : DS3 )`);
  - a `RAND`, shift or rotate call, or a range other than `SUM`, inside `SIN`, `COS`, `TAN`, `ASIN`, `ACOS`, `ATAN`, `LOG`, `LN`, `SQRT`, `RAD` or `DEG` (`SIN ( MAX ( DF1 : DF3 ) )`);
  - an address outside its bank's range (`DS1 + DS0`, `DS1 + DS4501`);
  - a hex constant whose digits run into an `E` (`1Eh`, `0Eh`, `2E5h`);
  - a real constant outside the float32 range (`1E39`);
  - a lone `.`, white space other than a space or a tab, and characters such as `=`, `#`, `@`, `;` and `&`.

  A stored Math whose formula is refused decodes as `raw(...)`; no Math CLICK wrote in the test captures is refused.
- **Math unary plus**: a `+` at the start, after `(` or after `,` joins the decimal constant after it, as CLICK does: `DS1 + ( + 5 )` is written `DS1 + ( +5 )` and stored `DS1#+#(#H+5#)`. Earlier versions kept the `+` apart and stored `(#+#H5#)`, so the bytes of such a Math change.
- **Math X and Y ranges**: an X or Y range in a Math stores only the addresses that exist, as CLICK does (`SUM ( X001 : X101 )` stores X002..X016 and X021..X036); earlier versions stored every number between the ends (X002..X100), so the bytes change for an X or Y range that spans more than one slot. A range stored with the earlier list still decodes as Math, and re-encoding it writes CLICK's list.
- **Math X and Y ranges into the option slot**: an X or Y range with an end in X021-X036 or Y021-Y036, accepted before, raises `FieldError`, because CLICK v4 stores the wrong addresses for it (for `SUM ( X001 : X036 )` it leaves out X032..X035); a range from the CPU slot to X021 and one with nothing between its ends are still accepted, and a stored Math with a refused range, CLICK's own included, decodes as `raw(...)`.
- **Math nickname**: a Math expression with a `<nickname>` (`math(DS1 + <FOO>,DS2)`), accepted before and copied into the formula CLICK keeps as addresses, raises `FieldError`.
- **Termination code**: a Copy termination code is `$` and two hex digits (`$0D`); `$D` and `$0` were accepted and stored as `$0D`, and now raise `FieldError`.
- **Fill into TXT**: a Fill into TXT takes one character, so `fill("AB",TXT1..TXT5)`, accepted before, raises `FieldError`.
- **Copy text past TXT1000**: a single Copy whose text would run past TXT1000 (`copy("AB",TXT1000)`), accepted before, raises `AddressError`.
- **Pack text**: `pack_text` needs a TXT source and a TXT source packs only as `pack_text`; `pack_text(DS1..DS2,DD1)` and `pack_words(TXT1..TXT2,DS1)`, accepted before, raise `FieldError`.
- **Math constants**: a hex constant in a decimal Math (`DS1 + 1Fh`) and text in any Math (`"A"`, `$41`), accepted before, raise `FieldError`.
- **Hex Math constants**: a decimal constant in a hex Math, integer or real (`DH1 + 7`, `DH1 + 70000`, `DH1 + 1.5`), accepted before, raises `FieldError`; hex constants (`7h`) are still accepted.
- **Uppercase `H` in a decimal Math**: a hex constant written with `H` in a decimal Math (`DS1 + 1FH`) raises `FieldError`, as `1Fh` does; before, it was accepted and stored as typed.
- **Uppercase `H` in a hex Math**: a Math keeps, writes to CSV and encodes a hex constant's suffix as `h`, as CLICK does (`DH1 + 7H` becomes `DH1 + 7h`), and checks it against `FFFFh`; the digits keep their case. Before, `7H` was stored as typed and not checked as a constant. A stored formula holding `7H`, which decoded as a Math before, now decodes as `raw(...)`.
- **Real range**: a real constant above the float32 range (`3.5E+38`), accepted before, raises `FieldError`; `3.5E+3` is still accepted.
- **Search value kind**: a Search number searches DS, DD, DF, TD or CTD, a hex value DH, and text or `$hh` TXT; other pairings, and a `$` value that is not `$hh`, accepted before, raise `FieldError`.
- **Character codes**: a `$` code is `$` and two hex digits (`$00` to `$FF`) in every field; `$1`, `$100` and `$4142` as a Copy source or a Fill value, accepted before, raise `FieldError`, and `$` and `$G1` as a Copy source, a Fill value or a Search value raise the same `FieldError` instead of an `AddressError`.
- **Copy and Fill text**: text in a single Copy or a Fill is 1 to 128 printable ASCII characters, as in Compare and Search; `copy("é",TXT1)`, accepted before, raises `FieldError` (`$E9` writes the code).
- Each of these refusals makes a blob that holds one decode as `raw(...)`.
- **Modbus target and hex address**: `ModbusTcpTarget` and `ModbusRtuTarget` refuse a numeric `device_id` outside 0-255 (TCP) or 0-247 (RTU) when built (`-1`, `65536`, RTU `248`), and a remote hex address is written as CLICK stores it: uppercase digits without leading zeros and a lowercase `h` (`0FFFEh` is `FFFEh`, `0000Fh` is `Fh`, `ffeh` is `FFEh`, `0H` is `0h`), up to `FFFEh`. A blob that stores another form decodes as `raw(...)`.
- **Address display form**: every instruction keeps, writes to CSV and encodes its addresses as CLICK displays them (`X1` becomes `X001`, `C001` becomes `C1`, `ds07` becomes `DS7`, `DS[ds01]` becomes `DS[DS1]`), accepts them in any letter case, and compares `C1` and `C001` as equal; constants are kept as written. A Math formula writes its function names in uppercase (`sum(x1:x16)` becomes `SUM ( X001 : X016 )`). A refusal of a field names the text as given beside its display form (`'x0' (X000) is outside X001-X016, ...`). Decoding does not rewrite: a blob whose address or function name is not in display form (`X1`, `c1`, `sum`) decodes as `raw(...)` or an unknown condition.
- **ASCII digits**: a constant, count, preset or address number written with a digit from another script (`copy(٣,DS1)`, `DS٣`) raises `FieldError`; only 0-9 are accepted.
- **Search text value**: a Search text value follows the Compare rule: 1 to 128 printable ASCII characters in quotes (`"AB"` matches a window of TXT registers, and `"$41"` is three characters of text) or an unquoted `$hh`; `""`, a longer or non-ASCII text and a quote inside the text raise `FieldError`, and such a blob decodes as `raw(...)`.
- **Address checks**: Contact, Coil, Counter, Shift, ForLoop and the Out variants raise `AddressError` (a `ValueError` subclass) naming the field for an address outside CLICK's banks or ranges (`Q1`, `C9999`, `X017`, `DS0`; X and Y take `X001`-`X016`, `X021`-`X036` (the dual option slot) and `X101`-`X116` to `X801`-`X816`), on direct construction as well as from CSV; such an AF blob decodes as `raw(...)` and such a contact blob as an unknown condition.
- **Bit instruction rules**: contacts take X, Y, C, T, CT or SC, `out` and the Out variants take Y, C or SC, immediate takes X (contacts) or Y (coils), an `out` range stays in one bank and ascends, and a compare takes data registers or constants of one group (hex, numeric or text); a refused value raises `FieldError`, and a refused blob decodes as `raw(...)` or an unknown condition.
- **Coil targets and ranges**: `latch` and `reset` refuse X, T, CT and data banks as `out` does; `out`, `latch`, `reset` and the Out variants refuse an SC bit outside CLICK's 25 writable ones (SC50, SC51, ... SC326); and a `latch` or `reset` range that leaves its bank or runs backwards, or any coil range whose end equals its start (`C5..C5`), raises `FieldError`. Such a blob decodes as `raw(...)`.
- **Out variants**: accumulators are TD, a preset is a DS register or a whole number (at least 0 for debounce, 1 for flasher and timed), and a field the kind does not use must be empty; a bad `unit` raises `FieldError` on construction instead of a `KeyError` at encode.
- **Compare tokens**: a quoted text constant that holds an operator character (`TXT1==">"`) now parses, in CSV files and in `CompareContact.from_csv_token`.
- **Compare constants**: a compare takes a text constant of 1 to 128 printable ASCII characters in quotes (`TXT1=="AB"` compares TXT1 and TXT2 against the characters) and raises `FieldError` for `""`, a longer or non-ASCII text, or a quote inside the text (write it as `$22`), for a whole number outside -2147483648..2147483647, for a hex constant above `FFFFh`, and for `>`, `<`, `>=` or `<=` on text; such a blob decodes as an unknown condition.
- **Out variant unused fields**: an Out variant blob that holds a value its kind does not use (an accumulator, preset or unit in a toggle, an `off_acc` or `off_preset` in a timed, a range end, an immediate flag in a timed, a maintained flag outside a timed) decodes as `raw(Out,...)` instead of dropping the value.
- **Out variant presets**: a preset above 32767, or one TD register for both phases of a `debounce` or `flasher`, raises `FieldError`, and such a blob decodes as `raw(Out,...)`.
- **Call and For**: `Call(subroutine="")` and a blank or whitespace-only `ForLoop` limit raise `FieldError`; a For blob with a blank limit decodes as `raw(...)`.
- **Timer, Counter and Drum fields**: these raise `FieldError` for a value CLICK's dialog refuses: a timer or counter number outside T1-T500 or CT1-CT250, a current value that does not match it, a non-numeric constant set point, an unknown timer unit, and a drum with more than 16 steps or outputs, a `jog_enabled` or `jump_enabled` that is not `True`, `False`, 1 or 0, a pattern that does not match them, or a blank event or duration. A Drum used to drop steps or outputs past 16 without a message. A native blob these rules refuse decodes as `raw(...)`.
- **Timer, Counter, Shift, Drum and For limits**: these raise `FieldError` for a value CLICK's dialog refuses: a timer set point above 32767, a drum duration above 32767 or with a sign, a counter set point outside the 32-bit range, longer than 12 characters, or in a register other than DS or DD, a shift outside C or with both ends at the same address, a drum event outside X, Y, C, T, CT and SC, a drum output used twice or as the completion flag, and a For count above 2147483647 or in a bank other than DS, DD, TD, CTD and SD; such a blob decodes as `raw(...)`.
- **Subroutine names**: `Call` refuses a name CLICK's Add New Subroutine dialog refuses: blank, over 24 characters, holding one of `\ / : * ? " < > |`, or a Windows device name such as `CON` before the last dot, each checked with outer spaces trimmed.
- **Send/Receive checks**: `Send` and `Receive` raise `FieldError` for a slave ID, TCP port or IP, `register_type`, MODBUS 984 or hex remote address, CLICK bank, count or status operand CLICK refuses, and a CSV range that runs backwards or mixes banks; such a blob decodes as `raw(...)`.
- **Send decode**: a Send keeps a status operand whose enable flag is 0, as Receive does, since CLICK v4 rederives the flags from the strings.
- **Send/Receive function codes**: `function_code=N` keeps a Receive's FC02 or FC04 from a CLICK address and a one-element Send written as FC15 or FC16, which used to re-encode as FC01/FC03 or FC05/FC06; a single DD, DF or CTD Send is now written as FC16 instead of FC06, and a blob whose code does not fit its addresses decodes as `raw(...)`.
- **Send/Receive dialog rules**: a Receive refuses a TD, CTD, SD or XD destination, a CLICK remote of another data type than its destination, more than one YD element or more than one DH element read from XD or YD, an odd TXT count, and a Word Swap CLICK turns off (including one DS or DH element); a Send refuses a hex start of FFFEh for a 32-bit or text source and two DD elements from FFFDh; either refuses one C bit in two status fields; X and Y counts stay in CLICK's slot runs (a Receive into `Y001` or a Send from `X001` to a CLICK address takes at most 32, as does a C count sent to a CLICK `Y001` or received from a CLICK `X001`); a bit count also fits the CLICK C, T, CT or SC bank on the remote side (a Receive of `C1` from `T490` takes at most 11), and such a blob decodes as `raw(...)`.
- **Send/Receive X and Y ranges**: an X or Y range in `source=` or `dest=` now counts the points that exist in the slots it covers, so `X001..X021` is 17 elements (`X001`-`X016`, then `X021`) where it used to be 21, and a range end such as `X17` or `Y020`, which earlier versions wrote for 17 or 20 elements from `X001`, raises `AddressError`.
- **Copy, Search and Math checks**: Copy, Block Copy, Fill, Pack, Unpack, Search and Math refuse the operands, bank pairs, converters, ranges and formulas CLICK's dialogs refuse (for example `copy(X001,DS1)`, `fill(0,DS1..DD5)`, `pack_bits(C1..C17,DS1)`, `math(SIN ( DH1 ),DH2,mode=hex)`) with a `FieldError` naming the field, and such a blob decodes as `raw(...)`; an X or Y range in a Pack source, a Block Copy source or an Unpack destination stays in one 16-point slot (`pack_bits(X015..X022,DH1)` is refused), and a Block Copy into Y whose run would cross a slot is refused until a capture shows what CLICK writes for it.
- **Copy bank pairs and constants**: Block Copy, Pack and Unpack take only the source and destination banks CLICK pairs (`pack_bits(X001..X016,DS1)` is refused, X packs to DH), a Block Copy destination end must be as far from its start as the source's (`blockcopy(DS1..DS4,DD1..DD2)` is refused), and a single Copy refuses an integer constant outside 32 bits and a hex constant above `FFFFh` into anything but DD or CTD; each raises `FieldError` and such a blob decodes as `raw(...)`.
- **Range order**: a Block Copy, Fill, Pack, Unpack or Search range whose end equals its start (`DS1..DS1`) or comes before it raises `FieldError`.
- **Search fields**: the Result Flag is a C bit, no field takes a pointer, a text search value (a text constant or a TXT register) takes only `==` or `!=`, and a hex search value is at most `FFFFh`; each raises `FieldError` and such a blob decodes as `raw(...)`.
- **Math fields**: a decimal Math writes to DS, DD, DF, TD, CTD or SD and a hex Math to DH or YD, a decimal integer constant must read back as typed (`3000000000`, `007` and `-0` are refused), a hex constant in a hex Math has at most 4 digits, and `SUM` takes no CT range; each raises `FieldError` and such a blob decodes as `raw(...)`.
- **Coil checks**: `Coil` raises `FieldError` for a one-shot on `latch` or `reset` (CLICK's Set/Reset dialog has no One Shot box), a type that is not a coil, and an `immediate` or `oneshot` that is not `True`, `False`, 1 or 0, instead of a `KeyError` or `ValueError` at encode.
- **Contact checks**: `Contact` raises `FieldError` for a type that is not a contact, an edge contact without `rise` or `fall`, an edge kind on a NO or NC contact, and an `immediate` or `wire_down`, and a `CompareContact.wire_down`, that is not `True`, `False`, 1 or 0, instead of a `KeyError` or `ValueError` at encode or `to_csv`.
- **Counter checks**: `Counter` raises `FieldError` for `down_enabled` on `count_down` (its own input is Down, with no `.down()` pin), an unknown `counter_type`, and a `down_enabled` or `reset_enabled` that is not `True`, `False`, 1 or 0, and `reset_enabled=False`, instead of a `ValueError` at encode; `reset_enabled` defaults to `True`, since every CLICK counter has a Reset input.
- **Timer checks**: `Timer(off_delay, retained=True)`, a `retained` that is not `True`, `False`, 1 or 0, and a value outside the unit list raise `FieldError` rather than a plain `ValueError` or a `TypeError`.
- **Pin rows**: Timer, Counter, Shift and Drum raise `FieldError` for `pin_rows` that are not a tuple with one ascending row of 1 to 255 per input, instead of an `IndexError` at encode. A pinned blob whose part bytes fail this decodes as `raw(...)`.
- **Raw instruction checks**: `RawInstruction` raises `FieldError` for a `part_count` that is not a whole number from 0 to 65535, a `blob` that is not bytes, or a `class_name` that is not text, instead of a `TypeError` at encode.
- **Copy, Fill, Search and Math constants**: a single Copy source, a Fill value and a Search value refuse a constant CLICK's shared input check refuses: a signed hex constant (`+1h`), hex above `FFFFh` longer than 8 digits (`0FFFFFFFFh`), an integer outside 32 bits (`fill(3000000000,DS1..DS4)`), a real that is not finite (`1E999`), and, in a Copy or Fill, text that is empty, over 128 characters or holds a quote (`""`, `"""`); a Copy `termination_code` is `$hh`, `0` or `none` (`abc` and `1` are refused), and `Math(expression="")` is refused. Each raises `FieldError` when built, so `""` in a Copy or Fill now fails in `read_csv()`, and such a blob decodes as `raw(...)`.
- **Copy pointers**: a pointer is `BANK[DSn]` in C, DS, DD, DH, DF, XD, YD, TD, CTD or TXT; the `BANK[pointer+offset]` and `BANK[pointer-offset]` forms (`copy(DD[DS1+2],DS1)`) and a pointer in any other bank raise `AddressError`.

### Fixed
- **Copy text into TXT**: a single Copy of two or more characters of text into TXT (`copy("TT",TXT1)`) stores the last TXT the text fills (TXT2) as its destination end, as CLICK does; it was stored empty, and CLICK's own blob decoded as `raw(Copy,...)`.
- **Math nicknames**: digits inside a `<nickname>` in a Math formula (`DS1 + <A 3000000000 B>`) are not checked as a constant; such a formula was refused.
- **Raw box height**: a `raw(...)` box keeps the row span and sub-rows of the cell it was decoded from, and one read from CSV takes its typed class's height (2 rows for the Copy family and Search, 3 for Send and Receive, an Out variant's height from its func code), where it used to encode as one row unless its blob had several parts.
- **One-phase debounce**: a `debounce` with only its on phase or only its off phase (`debounce(C1,off_acc=TD1,off_preset=100,unit=Tms)`), which CLICK v4 saves, encodes, decodes and round-trips through CSV instead of decoding as `raw(Out,...)`.
- **Pack/Unpack decode**: a pack of X, Y, T, CT or SC bits into DH now decodes as `pack_bits`, and an unpack of DH into Y bits as `unpack_to_bits`; a pack or unpack of CTD words, or an unpack into X, T, CT or SC, decodes as `raw(...)`, since CLICK's dialog refuses it.
- **Math formula length**: a formula longer than CLICK's limit of 270 characters as CLICK stores it (a sum of 68 addresses fits, 69 does not) raises `FieldError` instead of writing a blob whose field count disagrees with its header, and such a formula pasted into CLICK and copied back decodes as `raw(Math,...)`.
- **Search and Copy options**: an unknown `Search.comparison` raises `FieldError` on construction instead of a `KeyError` at encode, and a `Copy.suppress_zero` or `Copy.exponential` other than `"0"` or `"1"` raises `FieldError` instead of writing a conversion code CLICK doesn't have.

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
