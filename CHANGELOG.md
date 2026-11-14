# Changelog

<!-- Style guide: one sentence per entry. Describe the user-visible effect, not the
     implementation. Group related fixes/features into a single entry when they share
     a theme. Breaking changes and migration steps can be longer — users need the
     specifics. Detail belongs in commit messages and PR descriptions, not here.

     Review and condense before release — entries accumulate during development and
     should be edited into shape before moving from Unreleased to a version heading. -->

## Unreleased

This release writes rungs as CLICK writes them and refuses what CLICK refuses. Read "Behaviour changes" before upgrading.

### Added
- **`check(rungs)`**: returns a `Finding` for each rung shape CLICK's syntax check refuses, with CLICK's error code where a capture shows it (C0001, C0202, C0003, C000A, C0205, C0212). A finding with `captured=False` is a shape no capture shows, and CLICK may accept it. The rungs still encode and write as drawn.
- **CSV layout as CLICK draws it**: `read_csv` lays each rung out as CLICK's syntax check does, and `write_csv` writes that drawing with the logic unchanged.
- **`LegacyEncodingWarning`**: `decode()` and `decode_program()` warn (a `UserWarning`, exported from `laddercodec`) for a Math decimal constant outside -32768..32767 stored as 16-bit (`H70000`), which earlier versions wrote and CLICK runs as its low 16 bits (`RAND ( 70000 , 70002 )` ran as `RAND(4464, 4466)`). The rung still decodes; the warning has `instruction`, `token`, `detail`, `rung` and `program` attributes.
- **Raw box height and pins in CSV**: `raw(Email,0x2737,1,rows=3,sub=3,...)` holds the box's row span (`rows`, 1 to 32) and sub-rows (`sub`, 1 to 255), and a raw box of 2 or more parts adds its part rows as `pins=1/3/4`. `write_csv` always writes `rows` and `sub`, so a box that decodes as raw keeps its stored height and pins through CSV.
- **Written as CLICK writes it**: a one-phase `debounce` (`debounce(C1,off_acc=TD1,off_preset=100,unit=Tms)`) encodes and decodes instead of reading as `raw(Out,...)`; `function_code=N` keeps a Receive's FC02 or FC04 and a one-element Send's FC15 or FC16 through re-encoding; `write_csv` keeps a blank row inside a tall box when a later row of the box holds wires or contacts (it raised `WriterError`).

### Behaviour changes
- **Stricter validation**: a value CLICK refuses raises `FieldError`, or `AddressError` for an address (both `ValueError` subclasses), when the object is built or read from CSV, where it was stored or failed at encode with `KeyError`, `TypeError` or `IndexError`. A blob that holds such a value decodes as `raw(...)` (an unknown condition for a contact) and keeps its bytes.
  - Do: catch `FieldError` around `read_csv` and the constructors, and fix the rung. The refusals, by area:
  - Digits and text: only 0-9 count as digits; a `$` code is `$` and two hex digits in every field (`$D` is refused); text in Copy, Fill, Compare and Search is 1 to 128 printable ASCII characters (`""`, `é` and a quote inside the text are refused; write a quote as `$22`).
  - Bit instructions: contacts take X, Y, C, T, CT or SC, `out` and the Out variants take Y, C or SC, immediate takes X (contacts) or Y (coils); an address outside CLICK's banks (`Q1`, `C9999`, `X017`, `DS0`; X and Y take `X001`-`X016`, `X021`-`X036` and `X101`-`X116` up to `X801`-`X816`); an SC bit outside CLICK's 25 writable ones; `latch` or `reset` on X, T, CT or a data bank; a range that leaves its bank, runs backwards or ends where it starts (`C5..C5`); a flag that is not `True`, `False`, 1 or 0.
  - Compare: operands of one group (hex, numeric or text), a whole number within 32 bits, a hex constant up to `FFFFh`, and only `==` or `!=` on text.
  - Out variants: accumulators are TD, a preset is a DS register or a whole number up to 32767 (at least 0 for debounce, 1 for flasher and timed), one TD register is not used for both phases, a field the kind does not use must be empty, and a bad `unit` raises on construction.
  - Timer, Counter, Shift, Drum, For and Call: a number outside T1-T500 or CT1-CT250, a set point above 32767 (counter: outside 32 bits, over 12 characters, or not in DS or DD), an unknown unit or `counter_type`, `down_enabled` on `count_down`, `reset_enabled=False`, a drum with more than 16 steps or outputs (it dropped them without a message), a drum output used twice or as the completion flag, a For count above 2147483647 or in a bank other than DS, DD, TD, CTD or SD, a blank For limit, a shift outside C or with both ends equal, and a subroutine name CLICK refuses (blank, over 24 characters, one of `\ / : * ? " < > |`, a device name such as `CON`). `pin_rows` must be a tuple with one ascending row of 1 to 255 per input.
  - Copy, Block Copy, Fill, Pack, Unpack and Search: the operands, bank pairs, converters and ranges CLICK's dialogs refuse (`copy(X001,DS1)`, `fill(0,DS1..DD5)`, `pack_bits(X001..X016,DS1)`, a Block Copy destination not as long as its source), a range whose end equals or precedes its start, a Fill into TXT of more than one character, text past TXT1000, `pack_text` with a non-TXT source or `pack_words` with a TXT one, a pointer other than `BANK[DSn]` (`DD[DS1+2]`), a `termination_code` other than `$hh`, `0` or `none`, an X or Y range in a Pack source, Block Copy source or Unpack destination that crosses a 16-point slot, a Search value of the wrong kind for its register, a Search Result Flag that is not a C bit, and a `suppress_zero`, `exponential` or Search `comparison` outside its values.
  - Math: the formula grammar of CLICK's Math dialog (a sign after an operator, a misplaced operator, a function without parentheses, wrong arguments to `RAND`, shifts, rotates and `SUM`-type functions, a stray `,` or `:`, an address out of its bank's range, `1Eh`, a real above float32, text, a `<nickname>`, an unknown word, `DS1 + 1Fh` or `DH1 + 7` in the wrong mode, an empty formula, a formula over 270 characters as CLICK stores it, a hex constant of more than 4 digits); an X or Y range with an end in X021-X036 or Y021-Y036, which CLICK v4 stores wrongly. No Math CLICK wrote in the test captures is refused.
  - Send and Receive: a slave ID, port, IP, `register_type`, MODBUS 984 or hex remote address, count or status operand CLICK refuses, a `device_id` outside 0-255 (TCP) or 0-247 (RTU), a backwards or mixed-bank range, and the pairings CLICK's dialog refuses (a Receive into TD, CTD, SD or XD, an odd TXT count, a Word Swap CLICK turns off, one C bit in two status fields, X and Y counts past CLICK's slot runs, a bit count past the remote bank). An X or Y range counts the points that exist (`X001..X021` is 17 elements), and `X17` or `Y020` as an end raises `AddressError`.
  - Raw: `RawInstruction` needs a `part_count` from 0 to 65535, a bytes `blob` and a text `class_name`; a `raw(...)` token needs `rows` in 1 to 32, `sub` in 1 to 255 and pins that are one ascending row from 1 to 31 per later part; `Email`, `Home`, `Position` and `Velocity` take only `rows=3,sub=3`.
- **Display form of addresses**: every instruction keeps, writes and encodes its addresses as CLICK displays them (`X1` becomes `X001`, `C001` becomes `C1`, `ds07` becomes `DS7`, `DS[ds01]` becomes `DS[DS1]`), accepts any letter case, and compares `C1` and `C001` as equal; a Math formula writes function names in uppercase and a hex constant as `Fh` (uppercase digits, no leading zeros, lowercase `h`), as does a Modbus hex remote address (`FFFEh`). Constants are kept as written. Decoding does not rewrite: a blob with an address or function name not in display form (`X1`, `c1`, `sum`) decodes as `raw(...)` or an unknown condition.
  - Do: expect the display form when you read addresses back or compare them with your own text.
- **Re-encoded bytes change**: re-encoding a decoded rung can write other bytes for the same meaning.
  - Do: re-record any stored `.bin` and paste-check it in CLICK. The cases: a Math hex constant such as `0fh` (now `Fh`) or a signed one (`( -Ah )` is stored `( - Ah )`); a Math unary plus (`DS1 + ( + 5 )` is stored `DS1#+#(#H+5#)`); a Math X or Y range (only the addresses that exist: `SUM ( X001 : X101 )` stores X002..X016 and X021..X036, not X002..X100); a single DD, DF or CTD Send (FC16, not FC06); a Copy of text into TXT (the destination end is the last TXT the text fills); an Email, Home, Position or Velocity box (3 rows, not 1, so a CSV with such a box and an output on the next row reads with blank rows under the box and the output below them); a `raw(...)` box (it keeps its decoded height, or takes its class's from CSV: 2 rows for the Copy family and Search, 3 for Send and Receive, an Out variant's from its func code; it was 1 row unless the blob had several parts).
- **Decoding**: a Pack of X, Y, T, CT or SC bits into DH decodes as `pack_bits`, and an Unpack of DH into Y bits as `unpack_to_bits`; a Pack or Unpack of CTD words, or an Unpack into X, T, CT or SC, decodes as `raw(...)`. A Send keeps a status operand whose enable flag is 0, as Receive does.
  - Do: check code that expected `pack_words` or `unpack_to_words` for a bit pack.
- **`read_csv` returns more rungs than the CSV holds**: a rung whose circuits meet only at the rail reads as one rung per circuit, the comment on the first, and each rung is laid out as CLICK's syntax check draws it; `write_csv` writes that drawing, and a rung `check()` reports keeps its drawing.
  - Do: do not match rungs to CSV rows by index; use the rungs `read_csv` returns.
- **`decode()` and `decode_program()` raise on a down wire in the output column (AF)**: a `DecodeError` (a `ValueError`) names the rung and row; earlier versions dropped the wire without a word, which changed the rung's path. CLICK keeps such a path until its syntax check removes it, and the CSV has no syntax for it.
  - Do: catch `DecodeError`, or let CLICK's syntax check remove the wire before you copy the rung.
- **Warning on a 16-bit Math constant**: `decode()` and `decode_program()` emit `LegacyEncodingWarning` (see Added).
  - Do: re-paste the rung in CLICK to store the constant as 32-bit, or filter the warning.
- **Raw tokens from CSV**: a `raw(...)` token without `rows`, `sub` or `pins`, such as one from an earlier version, takes its class's height and puts its parts on rows 1, 2, ...
  - Do: write old CSV again with `write_csv` to keep a decoded box's height and pins.

### Fixed
- **Raw box with an unreadable field value**: a raw box whose field value holds a comma, quote, newline, tab or trailing space is written in the hex form and reads back; earlier versions wrote a token that failed to read or read other bytes.
- **Math formula length**: a formula over CLICK's 270-character limit no longer writes a blob whose field count disagrees with its header; it raises `FieldError`.

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
