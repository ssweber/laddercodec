# Arc: CLICK validation rules

Goal: laddercodec refuses what a CLICK v4.00 instruction dialog refuses, so an encoded rung
never pastes as something CLICK itself could not have written. pyrung gets the same list.

## Rules of the arc

- Field rules (a dialog refuses the value; OBJ-xxx errors in `SC_ErrorList.ini`) raise on
  construction or encode in laddercodec, with a message naming the field and the limit.
- Syntax Check rules (C-codes 40001-40069; CLICK still saves the project) do not raise in the
  codec. They are listed here and go to pyrung or a later optional `check()`.
- Rules that depend on the project (system configuration, nicknames, which CPU, whether a
  subroutine exists) are out of scope for the codec; listed only.
- Ground truth: CLICK v4.00 files under `C:/Program Files (x86)/AutomationDirect/CLICK Ver4.00`
  (`SC_ErrorList.ini`, `SC_InstructionSet.ini`, `Help/Content/*.htm` operand tables, the
  `Inst_*`/`InstCtl_*` DLLs), then a dialog check by the user where the files disagree or are
  silent. Do not commit copies of those files.

## Phase 1: catalogue (read-only)

One `bob-investigator` per family; each returns a table, folded in below:

| rule | source | laddercodec now | pyrung now | class | needs dialog check |

Families:
1. bits: contact, comparison, coil, out_variant
2. data: timer, counter, shift, drum
3. move: copy family (copy, block copy, fill, pack, unpack), search, math
4. comm: send, receive, email
5. flow + motion: call, return, end, forloop/next, home, velocity, position

## Phase 2: implement

One branch per family from the catalogue; dialog-check questions batched to the user first.

Order:
0. `operands` (first, alone): one bank-aware address check in `model.py` that replaces the
   `OPERAND_RE` regex. It checks the bank name, the number range per bank (Help 195) and X/Y
   module addressing (hundreds 0-8, points 01-16), and takes an allowed-bank set per field.
   It is called from `__post_init__`, so direct construction raises too, not only
   `from_csv_token`. Every existing `_validate_operand` site moves to it with today's
   bank-agnostic behaviour plus the bank-range check. Families then narrow the bank sets.
1. Family branches in parallel (bits, data, move, comm, flow), each on the settled rules
   below. A dialog answer that arrives later becomes a small follow-up commit on that family.
   Soundness bugs (S-list) ride on their family's branch.

## Catalogue (Phase 1, 2026-11-11)

Full tables, with file:line evidence for both projects, are in
`C:/Users/Sam/Documents/GitHub/laddercodec-wt/buildbot/jobs/catalogue-{bits,data,move,comm,flow}/REPORT.md`.
These are local and kept out of the repo, because they quote CLICK DLL addresses. The
investigators could not run scripts, so the DLL facts rest on the 2026-11-11 sweep dumps.
A rule seen only in the DLL ([I]) counts as unsettled until a dialog check confirms it.

### Cross-cutting findings

- laddercodec checks operands only in `from_csv_token`, and only with the regex
  `^[A-Z]{1,3}\d{1,5}$`: `Q1`, `C9999` and `X999` all pass. Direct construction checks
  nothing, and neither do Copy, Search, Math, Timer, Drum, Send/Receive or Email.
- Decoders did not fall back on a construction `ValueError`. The catch at
  `instructions/__init__.py:190,207` covers only `_decompose_blob`, so this bullet was wrong.
  Step 0 adds the catch to the `from_tags_condition` and `from_tags_af` dispatchers. A refused
  blob then decodes as raw or unknown, never as another instruction, and families need no
  catch of their own. The native fixtures (coverage, tumbler, v4_captures) are the net that
  catches a rule that is too strict.

### Settled field rules to enforce (no dialog check needed)

**bits**
- Contact NO/NC/edge: X, Y, C, T, CT, SC only. Immediate only on X. No pointers.
- Compare: Data A and Data B are data banks or constants; bit banks are refused.
  - Pairs follow the Help 202 groups: hex {XD, YD, DH, `h` constant}, numeric {TD, CTD, DS,
    DD, DF, SD, int/float constant}, text {TXT, `"text"` or `$HH`; see Q-B7}. Cross-group pairs
    are refused (OBJ-007, OBJ-024).
- Coil Out: Y, C or writable SC. X, T and CT are refused (OBJ-004). Immediate only on Y, and
  on a range both ends must be Y.
- Coil range: end must be greater than start (OBJ-009); both ends in the same bank (OBJ-008).
- Out variants: the target follows the Out rule. Presets are DS or a constant 0..32767, with
  floor 0 for debounce and 1 for flasher and timed. Accumulators are TD1-TD500.
  `maintained` is accepted only on timed.

**data**
- Timer: T1-T500. Current is TD<same n>. Set point is DS, or a digits-only constant that
  allows 0 (upper bound waits on Q-D1). Unit is checked on direct construction too.
- Counter: CT1-CT250. Current is CTD<same n>. Set point is DS or DD, or an integer constant
  (range waits on Q-D2).
- Shift: `.clock()` and `.reset()` pins are required. Start > end stays allowed (reverses
  direction, Help 172).
- Drum: 1-16 steps and 1-16 outputs. The pattern is steps x outputs with 0/1 cells, and the
  event, preset and pattern lengths agree.
  - Outputs Y or C. Current step DS. Accumulator TD, on the time drum too. Completion flag C.
    Jump target is a non-empty DS.
  - Every event-base step has an event (OBJ-021) and every time-base step a duration
    (OBJ-022). A time & event step needs one of the two (OBJ-1019).

**move**
- Copy single, block and fill bank pairs follow Help 173/185 (C1, C2, C4). Block Copy waits
  on Q-M1. A string constant goes to TXT only, and a constant never goes into Y or C.
- Converters: `to_text`/`to_binary` need a numeric source and a TXT destination;
  `to_value`/`to_ascii` need a TXT source and a numeric destination. Block Copy converts only
  with a TXT source.
- Termination code only on a single number → TXT copy, as settled in D1. A direct `Copy(...)`
  that carries one elsewhere raises.
- Range ends are in the same bank (OBJ-008) and inside the bank (TXT ≤ 1000).
  - Pack/Unpack X/Y ranges stay inside one 16-point module (OBJ-033, 035, 019).
  - Pack/Unpack counts: Pack ≤16 into DS/DH, ≤32 into DD/DF, or 2 words; Unpack likewise
    (OBJ-027/041/040, 032/039/042).
- Pointers (`DS[DSn]`) only in single Copy, the pointer itself a DS. Other copies refuse them.
- Search: range DS, DD, DH, DF, TD, CTD or TXT. Result DS. The source is a constant or data
  register, never a bit. Pyrung's editor checks from 2026-11-06 back the range and result
  rules.
- Math:
  - Result DS, DD, DF, TD or CTD, and DH in hex mode only.
  - No bit operand except in SUM over a bit range. Parentheses nest at most 8.
  - Mode-only functions stay in their mode (Help 170/203). Range aggregates run low:high
    inside one block, and MDN ≤ 1024 bytes.
  - Formula length cap (exact value waits on Q-M7; at least close S1).

**comm**
- Slave ID ranges: Send RTU 0-247, Send TCP 0-255, Receive RTU 1-247, Receive TCP 0-255. A DS
  address also passes (D3).
- TCP port 1-65535 and a four-octet IP. `register_type` is one of the four names, with a
  clear message otherwise.
- 984 start address inside its function code's bank, and hex 0h-FFFEh.
- Remote and local CLICK banks per function code follow Help 180/181.
- Counts:
  - Send: coils 1-1968, registers 1-123, 32-bit registers 1-61.
  - Receive: bits 1-2000, registers 1-125, 32-bit registers 1-62.
  - Both are capped by the room left in the local bank.
- CSV ranges must not run backwards or mix banks.
- Status bits are C bits; the Exception Response is DS or DD.

**flow**
- `Call(subroutine="")` raises.
- For count: a DS, DD, TD, CTD or SD address, or a digits-only constant. Its upper bound
  waits on Q-F1, as does the bank list, which comes from the DLL only.
- Return and End take no operands (already enforced).
- ForLoop: the blank-limit check (`forloop.py:48`) should raise `FieldError`; then drop the
  local `try/except ValueError` at `forloop.py:209-212` (from the operands review, N5).

All families: new field rules raise `FieldError`, or `AddressError` for addresses. The
decode dispatchers catch only `FieldError`, so a plain `ValueError` raised in `from_tags`
crashes decode. XD/YD fields must pass `banks` naming XD or YD before `XD0u`/`YD0u` is
accepted.

### Soundness bugs reported (check each before fixing; they ride on their family's branch)

- S1 move: Math with more than 500 operands writes more 0x6888 fields than the header count
  (`math.py:404` vs `419-421`). This is a corrupt blob.
- S2 data: Drum with more than 16 steps or outputs is silently truncated (`drum.py:204,
  370-390`). A wide pattern row packs past 16 bits (`81-92`), and a short row raises
  IndexError (`86`).
- S3 move: Math with a descending range gives an empty interior list (`math.py:176-194`).
- S4 move: Pack/Unpack decode guesses bits or words from the first letter (`copy.py:846,
  862`), so X, Y, T, CT and SC bit sources decode as `pack_words`.
- S5 bits: Compare `from_csv_token` splits on the first operator it finds, so `TXT1=="="`
  mis-splits.
- S6 comm: an unknown `register_type` raises a bare KeyError (`send_receive.py:167`). On a
  Send it is silently read as holding (`179-190`). A bad 984 address is silently bucketed
  into FC03/FC04 (`140-154`).
- S7 comm: the SD decoder drops a status bit whose enable flag is 0 (`send_receive.py:718-721`);
  the RD decoder does not.
- S8 data: `Timer(unit="x")` built directly raises KeyError at encode (`timer.py:101`), and
  `OutVariant` does the same (`out_variant.py:167`).
- S9 comm: FC02 and FC04 are unreachable from a CLICK-addressed Receive (`send_receive.py:
  157-163`), so a native FC02/04 rung would re-encode as FC01/03. Waits on Q-C4.
- S10 bits: one-phase debounce is refused by both projects, but Help 348 allows it. Waits on
  Q-B4 and a capture. Q-B4 answered with a capture; laddercodec accepts it on bob/bits2.

### pyrung follow-ups (listed for the pyrung side, not built in this arc)

- **Send/Receive:**
  - `device_id` accepts 248-255 on RTU, and 0 on Receive RTU.
  - There are no `com_port` values for cpu3 or wlan (D2), and no DS slave ID (D3).
- **Compare:** `COMPARE_COMPATIBILITY` is never called.
- **Coils and timers:**
  - `coil_target` allows X, T and CT; only the write-target check catches them.
  - There is no floor on on/off-delay constants.
- **Drum and counter:** there is no 32767 cap on drum presets and no counter preset range.
- **Search:** `search()` accepts a DINT result while its hardware finding requires DS.
- **Shift:** there is no C-bank role for the shift register.
- **Math:**
  - SUM over X, Y, T and SC is allowed, and MAX over TD is not flagged (see Q-M8).
  - The destination table has no hex/decimal split.
- **Block Copy:** the pyrung table disagrees with Help 184 (Q-M1).
- **Fill into TXT:** `fill("AB", txt[1:5])` builds and passes Click validation. Only the
  simulator objects, with a `ValueError` at scan time (`_as_single_ascii_char`). It also takes
  codes 128-255, which CLICK's dialog does not. Single Copy is fine: a text literal into TXT
  fans out one character per register (`_instructions_basic.py:476`), as CLICK's
  `TXT1..2` rewrite does.
- **Math:** check that pyrung refuses text constants (`"A"`, `$41`) and hex constants in a
  decimal Math (Q-M13, Q-M20). Not looked at yet.
- **End:** an End inside a subroutine is not flagged.

### Syntax rules (C-codes; no raise in the codec; for pyrung or a later `check()`)

- **For/Next:**
  - Nesting ≤ 3 (C010D). One Shot only on the outermost loop (C0111).
  - For/Next pairing (C0101, C0102). Next alone on its rung (C0009).
  - No Return or End inside For/Next (C0115). A timer inside For/Next warns (C1004).
- **Break/Continue:** need a contact (C000B, C000C) and must sit inside For/Next (C010F,
  C0110).
- **Program structure:** a subroutine needs an unconditional Return (C0105); Main needs an
  unconditional End (C0201).
- **Timer, counter, shift, drum input contacts** (C0205-C0214, assigned to instructions by
  message order only).
- **Duplicate use:**
  - Duplicate Timer or Counter address (C010A, C010B).
  - OUT or DRUM on a timer address that is in use (C0112, C0113).
  - Unused timer or counter bit (C1002).
- **Math:** a function must be followed by an operator (C0114).
- **Motion:** the instruction refers to an axis that does not exist (C0215-C0217).

### Out of scope (project rules, listed only)

Out of scope: configured I/O, CPU model gates (C02xx, OBJ-049), port and protocol setup,
PTO axis setup, Email client setup, subroutine existence, duplicate coils, and
system-settings conflicts.

## Ground-truth questions (batched for CLICK v4)

Answer by opening the dialog in an empty project. "Refused" means OK shows an error or the
value cannot be typed. Ordered by how much Phase 2 work each one unblocks.

Open asks (checklist; details under each id below):
- Answered 2026-11-12 (user, dialog), to build: Q-M12, Q-M13, Q-M14, Q-M16, Q-M17, Q-M18,
  Q-M19, Q-M20, Q-M21, Q-B7 `DS1==1-2`, and the move (hmove) questions below.
- Built 2026-11-12 (bob/move6, dev 00124a1): Q-M13b, Q-B7 `$` codes, the `"TT"` → TXT1
  capture (fixture `v4_captures/text_tt.bin`). BOB rulings on that branch: a TXT pointer
  destination takes one character of text until a capture shows more; quoted text in a Copy
  or Fill into TXT is printable ASCII, as in Compare and Search (write others as `$hh`).
- ANSWERED 2026-11-12 (user, captures in `clicknick/`; laddercodec's Copy blob is
  byte-identical to each): `"ABC"` → TXT10 stores end TXT12 (`triple-txt-copy.bin`); a
  quoted `"$41"` → TXT2 is three characters of text, end TXT4
  (`triple-txt-copy-hex-quoted.bin`); 128 characters → TXT873 stores end TXT1000
  (`128-txt.bin`); `copy("AB",TXT[DS1])` is accepted and stores an empty end
  (`double-txt-copy-pointer.bin`), so the move6 pointer refusal is lifted. To build: add the
  four as fixtures, accept multi-character text into a TXT pointer with an empty end.
- New (user, dialog, 2026-11-12): the Copy dialog rewrites some quoted text as a number:
  `"ABCD"` stays text, `"ABCDE"` becomes `0.0` (Real numbering), and so does a quoted
  128-character text starting `0123…` or `ABC…`; `"FGHDSFG"` stays text. Likely a text made
  only of characters a number can hold (digits, A-F, E) is read as a number. laddercodec
  types `copy("ABCDE",TXT1)` as text. Needs: which quoted texts the dialog turns into
  numbers (`"ABCD"`, `"EEEE"`, `"1E5"`, `"12"`).
  - **ANSWERED 2026-11-12 (user, dialog):** `"12"` stays text; `"EEEE"`, `"1EF"` and
    `"ABCDEF"` become `0.0`, and so does `"HELLO"`. Every text that turns holds an `E`, none
    that stays does.
  - **Ruling 2026-11-12 (user):** a CLICK bug in the Copy dialog, not a field rule.
    laddercodec keeps accepting and encoding quoted text with an `E` (as with For's `1 0`,
    Q-F1). Unchecked: lowercase `e`, Fill, and what CLICK keeps when such a Copy is pasted.
- ANSWERED 2026-11-12 (user, SCR `Scr1.tmp` of a project holding `"TT"` → TXT1): SCR
  decode gives `copy("TT",TXT1)`, so SCR stores the 0x6077 end too (decode refuses a
  mismatched end).
- ANSWERED 2026-11-12 (user, dialog): decimal `DS1 + 1FH` is refused, like `1Fh`.
  laddercodec accepts it (its Math hex pattern knows only lowercase `h`). Capture
  `clicknick/7h.bin` (hex `DH1 + 7H` copied back) is byte-identical to laddercodec's
  `DH1 + 7h` blob; laddercodec's `DH1 + 7H` blob differs. The user typed `7H` and the
  dialog lowercased it as typed. To build: Math reads `H` like `h` (refused in decimal,
  checked in hex), and normalizes the constant to lowercase `h` at construction, so `7H`
  encodes as `7h` does. Built in train8 (f77e06e); fixture
  `tests/fixtures/v4_captures/math_hex_upper_h.bin`. A stored `7H` blob decodes raw.
- Open from move8 (dialog), hex Math:
  - Are `DH1 + EH`, `DH1 + CH` and `DH1 + 0fH` read as hex constants? Does CLICK keep
    lowercase hex digits as typed (laddercodec keeps the digits' case, lowercases only the
    suffix)?
  - Is decimal `DS1 + EH` refused like `1FH`?
  - Is `( -Ah )` accepted in a hex Math, and what does it copy back as? laddercodec stores
    the literal `-Ah`, without evidence (`tests/ladder/test_address_display.py` no longer locks it).
  - ANSWERED 2026-11-12 (user, dialog): `DH1 + EH` → `DH1 + Eh`, `DH1 + CH` → `DH1 + Ch`,
    `DH1 + 0fH` → `DH1 + Fh` (digits uppercased, leading zero dropped, suffix `h`).
    laddercodec gives `0fh`. Capture `clicknick/minus-ah.bin` (typed `DH1 + ( -Ah )`): CLICK
    redisplays `DH1 + ( - Ah )`, stores the template `@ + ( - Ah )` and the internal formula
    `DH1#+#(#-#UH10#)`, so the sign on a hex constant is a separate token, as on an address.
    laddercodec writes `@ + ( -Ah )` and `DH1#+#(#-Ah#)`, a formula CLICK never writes.
    To build: a hex constant's display form is uppercase digits without leading zeros plus
    `h`; a sign before a hex constant stays spaced (`- Ah`), so the internal form is
    `-#UH10`.
  - ANSWERED 2026-11-12 (user, dialog): `0H` becomes `0h`. A padded `0FFFEh` is refused
    ("The entered value is outside the range"), although its value fits in FFFFh: the
    four-digit limit counts the digits as typed, leading zeros included.
  - Open from move9's review (dialog): is `DH1 + -Ah` (a sign right after an operator)
    accepted, and what does it redisplay as? laddercodec writes `DH1 + - Ah`. Is `00h`
    shown as `0h` (only `0H` was typed)?
  - ANSWERED 2026-11-12 (user, dialog): decimal `DS1 + EH` is refused (laddercodec agrees).
    `DS1 + FOO` is refused (laddercodec accepts it as an unknown word). In a hex Math,
    `DH1 + 7H7` is rewritten as `DH1 + 77h` (laddercodec stores `7H7` literally).
    BOB ruling: Math refuses any word that is not an address, a function name or a
    constant, and refuses `7H7` rather than copying CLICK's rewrite: an `H` inside a
    constant is a typo, and the rewrite's rule (drop every inner `H`?) is a guess from one
    case. Cost if wrong: `7H7` raises instead of encoding as `77h`. Built in train9
    (eb7b6f1). Update (grammar research): the code fixes the rewrite rule, delete the
    first `H` anywhere (`7H7` → `77h`, `H7` → `7h`, `7HH` refused), so the "guess" part
    of the ruling no longer holds; whether to refuse or rewrite is now the user's call.
- Math grammar research, 2026-11-12: `scratchpad/validation/math-grammar/README.md` (editor
  model read from the Math dialog's code, EBNF, printers, fixture check, predictions) and
  `model.py`/`predict.py`. The model re-derives all 82 editor-written Math blobs in the
  fixtures. Open conflict: the code read accepts hex `DH1 + 7` (no `h`), the dialog refuses
  it (Q-M13b); the refusing check is unfound. Dialog checks it asks for, by how much they
  settle: hex `DH1 + 1Eh`, `0Eh`, `2E5h` (predicted refused: the tokenizer splits `1Eh` as a
  real); decimal `DS1 * -5` refused but `DS1 * ( -5 )` accepted; hex `DH1 + -Ah` refused;
  hex `DH1 + 7`: which message; hex `LSH ( 1h , 2h )` refused; `SIN ( MAX ( DF1 : DF3 ) )`
  refused but `SIN ( SUM ( DF1 : DF3 ) )` accepted. Next: move10, one parser from this
  grammar.
  - ANSWERED 2026-11-12 (user, dialog): every prediction held. Hex `DH1 + 1Eh`, `0Eh` and
    `2E5h` are refused. Decimal `DS1 * -5` is refused and `DS1 * ( -5 )` accepted (pyrung
    already exports the parenthesised form). Hex `DH1 + -Ah` is refused. Hex
    `LSH ( 1h , 2h )` is refused. `SIN ( MAX ( DF1 : DF3 ) )` is refused and
    `SIN ( SUM ( DF1 : DF3 ) )` accepted. Hex `DH1 + 7` is accepted as `DH1 + 7h`, so there
    is no missing check: the code read was right and the Q-M13b answer is corrected.
  - ANSWERED 2026-11-12 (user, dialog + capture `clicknick/stricter-math-questions.bin`),
    move10's open questions: `DS1 + ( +5 )` is accepted and stored `@ + ( +5 )` /
    `DS1#+#(#H+5#)`: a `+` merges into a decimal constant like `-` (laddercodec wrote
    `(#+#H5#)`). `PI ( 2 )` is accepted, stored `PI#(#H2#)`. Refused: `DS1 + .`, `SUM DS1`,
    `DS1 LSH 1h`, `RAND ( 1 , 10 ) DS1`, `MAX ( DS1 , DS2 )`, `SUM ( DS1 + DS2 )`,
    `DS1 + DS0` (Math operands take the full address check), and a stray comma
    `DS1 , DS2` ("Please use a period (.) as a decimal point.").
  - ANSWERED 2026-11-12 (user, typed; capture `clicknick/plus-2.5.bin`): `DS1 + ( +2.5 )`,
    result DF1, is stored `@ + ( +2.5 )` / `DS1#+#(#F+2.5#)`: a `+` merges into a real
    constant too, typed `F`. dev builds the same fields as CLICK. Not yet a fixture.
  - CORRECTED 2026-11-12 (user, typed in the editor, capture `clicknick/math-sums.bin`, cell
    bytes `01 03`): `SUM ( T1 : T5 )`, `MAX ( TD1 : TD5 )`, `SUM ( X001 : X036 )` and
    `SUM ( X001 : X101 )` are all accepted. The 2026-11-01 note that the editor refuses
    them was wrong; laddercodec keeps accepting them. T and TD interiors match
    laddercodec's. The X interiors do not: CLICK lists `X002..X016, X021..X031` for
    `X001 : X036` (26) and `X002..X016, X021..X036` for `X001 : X101` (31), where
    laddercodec lists every number (`X002..X035`, `X002..X100`). Open: CLICK's address
    stepping for X/Y ranges (which numbers are skipped, and whether it depends on the
    project's configured I/O; the capture's CPU is C2-03CPU). Needs its own move with the
    capture as fixture; not part of move10.
  - ANSWERED 2026-11-12 (user, no I/O modules configured; capture
    `clicknick/math-sums-slots.bin`, typed): `X001 : X116` lists X002..X016, X021..X036,
    X101..X115 (46); `X021 : X116` lists X021..X036, X101..X115 (31, the start included);
    `X001 : X032` lists X002..X016, X021..X027 (22); `X005 : X036` lists X006..X016,
    X021..X031 (22); `Y001 : Y036` is the same as X (26). Fitted rule (building in move11):
    an endpoint in the CPU option slot (21..36) counts as its number minus 4; the members
    are the valid X/Y addresses whose number lies strictly between the two bounds.
  - ANSWERED 2026-11-12 (user, typed; capture `clicknick/math-sums-slots-v2.bin`, now
    fixture `math_ranges_xy_slots2.bin`): `X001 : X021` lists X002..X016; `X025 : X026`
    lists nothing; `X025 : X027` lists X022 (wrong, X026 left out); `X101 : X201` lists
    X102..X116; `Y001 : Y116` lists all 46. All five fit the rule. User ruling: a range
    whose CLICK list differs from its true members is refused (decodes as raw). Landed in
    train11 (37e9980). Deferred to the next release by the user: SCR decode of such a
    refused range keeps only 6 of Math's 5510 fields (the "SCR raw drops tags" leftover).
    Not captured yet: a span of more than two expansion slots, a Y range starting in the
    option slot.
  - ANSWERED 2026-11-12 (user, typed; capture `clicknick/math-sum-x25-x101.bin`):
    `X025 : X101` lists X022..X036 (15), the rule's list (X025 counts as 21); true members
    X026..X036, so refused. dev (37e9980) decodes it as raw. Not yet a fixture.
- Dialog: comm: Receive into Y101+ from C/T/CT/SC; bits: Compile with an SC range over read-only bits.
- Move (hmove), ANSWERED 2026-11-12 (user, dialog):
  - Copy's Termination Code does not take one hex digit: the ASCII Table picker shows `$00`,
    two digits, one character. laddercodec accepts `$D` and stores `$0D`; refuse it.
  - A `"` in a Math formula: the user believes it is refused (see Q-M20).
  - OBJ-023: a Fill into TXT takes one character. A single Copy of `"TT"` into TXT1 is
    accepted, and the dialog changes the destination to `TXT1..2`. laddercodec accepts
    `fill("AB",TXT1..TXT5)`; refuse it. Capture wanted: what CLICK stores for `"TT"` →
    TXT1 (destination TXT1, or TXT1 with an end of TXT2), since laddercodec writes TXT1.
  - **ANSWERED 2026-11-12 (user, capture `clicknick/double-txt-copy.bin`):** CLICK stores
    destination TXT1 and destination end (tag 6077) TXT2. Every other tag matches
    laddercodec's `copy("TT",TXT1)` blob, which leaves 6077 empty, so the native rung
    decodes as raw today. To build: write 6077 as the last TXT the text fills, and decode it.
- Paste and copy back: Q-M15 Math into SD9, YD1, YD0u. Box height (rawheight review): native
  cells store Email/Home/Position/Velocity at `03 03` (cell +0x09/+0x0A), Math `01 03`, some
  Search `02 03`, Tmr `02 03`, Drum `04 05` and SR `03 02`. The typed encoder writes `01 01`,
  `01 01`, `02 02`, `02 02`, `04 04` and `03 03`, and those goldens paste. Does a pasted
  `raw_instructions__email` golden copy back as `03 03`, and should typed encode write the
  native height? A decoded raw Email-like box loses 2 rows through a CSV round trip (with a
  warning) until this is settled.
- Captures: Q-C7 remote address `0H` stored text, and the stored
  text of a padded `0FFFEh` (laddercodec writes `FFFEh`); the Captures
  wanted list at the end of this section.

**addresses (step 0)**
- Q-A1 In a CLICK PLUS project with an option slot, is `X021` (or `Y036`) accepted in a
  contact or coil? pyclickplc accepts X021-X036/Y021-Y036 as the option slot
  (`pyclickplc/src/pyclickplc/banks.py:57`), while laddercodec's `check_address` refuses any
  point past 16. The only native evidence is `SUM ( X001 : X036 )` as a Math range end.
  - **ANSWERED 2026-11-11 (user, dialog): accepted with a dual option slot.** The X/Y slot
    table is pyclickplc's: 1-16, 21-36, 101-116, ... 801-816 (ten 16-point slots).

**bits**
- Q-B1 Set and Reset:
  - Are X1, T1, CT1 and DS1 refused as the address?
  - Are `C9..C1` and `C5..Y5` refused? Out refuses both (OBJ-008/009); Set/Reset were not
    disassembled.
  - **ANSWERED 2026-11-11 (user, dialog): Set and Reset take Y, C and SC only.** X1, T1, CT1
    and DS1 are refused, and so are `C9..C1` and `C5..Y5`.
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/bits.md):** agrees. Inst_Set and Inst_Reset use the
    Out validator (Y, C, writable SC) and Out's range errors OBJ-008, OBJ-009 and OBJ-012
    (`C5..C5`); with Immediate checked the range end is checked as Y only.
- Q-B2 Out: which SC addresses are accepted? Is it exactly SC50, 51, 53, 55, 60, 61, 65, 66,
  67, 75, 76, 120, 121?
  - **ANSWERED 2026-11-11 (user, dialog): 25 SC bits, the read-write system bits in CLICK's
    address picker.** SC50, 51, 53, 55, 60, 61, 65, 66, 67, 75, 76, 120, 121, 162, 165, 168,
    171, 303, 304, 305, 306, 323, 324, 325, 326.
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/bits.md):** agrees: the 25 SC rows marked R/W in
    `PLCType.ini`; Set, Reset, Out and the Out variants share the check (OBJ-003).
- Q-B3 Out:
  - Is `C5..C5` refused?
  - Is `C1..C2000` accepted?
  - Is immediate `Y016..Y101`, which crosses a module, accepted?
  - Is an SC range accepted?
  - **ANSWERED 2026-11-11 (user, dialog):** `C5..C5` is refused; `C1..C2000` is accepted;
    immediate `Y001..Y101` is accepted; an SC range is accepted.
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/bits.md):** agrees: only the two ends of a range are
    checked. Whether Compile refuses an SC range with read-only bits between: needs dialog.
- Q-B4 Debounce: can it be saved with only the off phase filled? With only the on phase? If
  yes, a capture shows what CLICK writes.
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/bits.md):** yes to both; both phases empty is refused
    (OBJ-006). Flasher needs both phases.
  - **ANSWERED 2026-11-11 (user, capture `v4_captures/debounce_one_phase.bin`):** CLICK writes
    the empty phase's accumulator and preset as empty strings. Built on bob/bits2 (S10).
- Q-B5 Debounce and flasher: is the same TD for the on and off timer refused?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/bits.md):** refused, OBJ-012 (TD1 and TD001 are the same
    register). Timed has one TD.
- Q-B6 Debounce, flasher and timed: is a preset of 32768 refused? Does the Timed unit list
  include min? (Help 350 says no; a capture says yes.)
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/bits.md):** 32768 is refused for all three (OBJ-005),
    32767 accepted; a DS preset also passes. Timed offers ms, sec and min; debounce and
    flasher ms and sec.
- Q-B7 Compare:
  - Is `DS1>40000` refused? `DS1==3000000000`? `DH1==10000h`?
  - Is a constant accepted on the left (`100<DS1`), or on both sides (`1==1`)?
  - With TXT1 as Data A, are `>`, `<`, `>=` and `<=` disabled?
  - Are `DH1==FFFFH` (uppercase H) and `TXT1=="$41"` (quoted) accepted?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/bits.md):** `DS1>40000` accepted; `DS1==3000000000`
    and `DH1==10000h` refused (OBJ-005: a whole number is int32, a hex constant at most
    FFFFh); `100<DS1` and `1==1` accepted; with text as Data A, `>`, `<`, `>=` and `<=` are
    hidden; `DH1==FFFFH` accepted; `TXT1=="$41"` accepted as three characters of text. The
    dialog takes 1 to 128 characters between the quotes; `""` is refused (OBJ-005).
  - **Ruling 2026-11-11 (user), superseded by the revised ruling below:** laddercodec refuses multi-character text, `"$41"`
    included, though the dialog accepts it. Help CL196 says a compare text constant is a
    single ASCII character, and a TXT register holds one; the dialog's limit is baseEx's
    generic check, a gap in CLICK's validation. The quote character `"""` is refused too
    (the CSV token can't hold it; `$22` spells it).
  - **Ruling 2026-11-11 (user, revised):** a compare text constant is 1 to 128 printable
    ASCII characters between quotes, as the dialog accepts (`""` stays refused, OBJ-005).
    On hardware CLICK compares the literal against consecutive TXT registers starting at the
    named one (pyrung conformance compare/char_two_char_literal: TXT771="A", TXT772="B"
    makes `TXT771=="AB"` true; "A","C" and "B","A" false), and pyrung's `TXT771=="AB"`
    rungs pasted into CLICK and copied back unchanged. Still refused: any `"` inside the
    text (the CSV token can't split it; `$22` spells it), a quoted `"$41"` (write `$41`
    unquoted), and `>`, `<`, `>=`, `<=` on text.
  - **ANSWERED 2026-11-11 (user, dialog):** typing TXT1 into Data A leaves only = and != to
    choose; a text compare takes == or != only. Which of the two is saved (bits.md N8) is
    still open.
  - **Ruling 2026-11-11 (user, revised again):** a quoted "$hh" is literal text, as the dialogs accept it (Compare bits.md N4; Search Inst_Search 0x2040 class).
  - Needs a capture: the `$` character-code forms other than `$hh` (`$1`, `$100`, `$4142`).
    The DLL classifies `$` up to FF as one type and above it as another; laddercodec
    refuses them. Search refuses them too since 2026-11-12, following the Compare rule; Fill
    and single Copy still accept them.
  - **ANSWERED 2026-11-12 (user, Help `ascii table2.gif`):** a `$` code is one character
    picked from CLICK's Embed ASCII Code table, 00h-FFh (80h-FFh on its second page), so it
    is exactly `$` and two hex digits. `$1`, `$100` and `$4142` are refused in every field,
    Fill and single Copy included.
  - Needs a dialog check: is `DS1==1-2` refused? The shared check lets a sign stand among
    the digits; the Counter dialog refuses `1-2` with its own parse (Q-D2), and the
    constant classifier (`operands/constants.py`) refuses it in every field.
  - **ANSWERED 2026-11-12 (user, dialog):** `DS1==1-2` is refused.

**data**
- Q-D1 Timer set point: is 32767 accepted? Are 32768 and -1 refused? Is it the same for every
  unit?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/data.md):** 0-32767 for every unit, digits only
    (a sign is refused), OBJ-005; an address set point is DS only, OBJ-004.
- Q-D2 Counter set point:
  - Are 2147483647 and -2147483648 accepted, and 2147483648 refused?
  - Are `1.5` and `abc` refused?
  - Are DS and DD the only registers (DH, DF, TD and CTD refused)?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/data.md):** yes to all three. The constant fits
    32 bits and its text is under 13 characters, else OBJ-005; registers DS and DD only,
    OBJ-004.
  - **ANSWERED 2026-11-11 (user, dialog):** `1-2` is refused, so a `-` only leads (the
    report's "'-' anywhere" quirk does not happen).
- Q-D3 Shift register:
  - Are Y1..Y8, T1..T8 and SC1..SC8 accepted, or only C?
  - Is `C1..X8` refused?
  - Are `C1..C1` and `C1..C2000` accepted?
  - Is `C106..C99` accepted?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/data.md):** only C, OBJ-004; `C1..X8` refused
    with OBJ-004; `C1..C1` refused, OBJ-012 (not accepted); `C1..C2000` and `C106..C99`
    accepted. laddercodec compares the ends as addresses, since CLICK normalizes C001 to
    C1 as it is typed (user, dialog, 2026-11-11; see Q-D5).
- Q-D4 Drum time base:
  - Is a duration of 32767 accepted and 32768 refused? Is 0 accepted?
  - Does the unit change the cap?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/data.md):** 0-32767 accepted, 32768 and any
    sign refused, OBJ-005; the unit does not change the cap. A DS duration depends on the
    CPU (project rule, not checked); another register bank is OBJ-004.
- Q-D5 Drum:
  - Is the same output in two columns accepted?
  - Are SC, T and CT accepted in the event column?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/data.md):** the same output twice, or an output
    equal to the completion flag, is refused, OBJ-014. Events take X, Y, C, T, CT and SC,
    else OBJ-004. Checking outputs against coils in other rungs is a project rule.
  - **ANSWERED 2026-11-11 (user, dialog):** CLICK normalizes an address as it is typed:
    C001 becomes C1, and only X and Y go the other way (X1 becomes X001). So C1 and C001
    are the same output, and so are X1 and X001; laddercodec compares parsed addresses.
  - **ANSWERED 2026-11-11 (user decision; native captures):** laddercodec writes every
    address in pyclickplc's display form (X/Y padded to 3 digits, other banks unpadded,
    bank uppercase, XD0u), normalized at construction by `model.normalize_address`. The
    18,117 address strings in the native .bin/.scr fixtures (v4_captures, tumbler,
    scr_captures) are all in this form, so decoding native data is unchanged.
  - **ANSWERED 2026-11-11 (user, dialog):** lowercase is accepted and normalized as typed:
    `ds1` becomes DS1. laddercodec accepting `ds01`/`x1` on construction and CSV matches the
    dialog (FABLE_REVIEW decision 4).

**move**
- Q-M1 Block Copy DS1..DS3:
  - Are a YD destination and an SD destination accepted?
  - Are TD, CTD and YD sources accepted?
  - Is TXT → DF refused?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/move.md):** YD destinations and TD, CTD and
    YD sources are refused; an SD destination is accepted from a word source, then checked
    against CLICK's read-only SD list (OBJ-018, not applied: the writable-SD table is not
    extracted); TXT → DF, TD, CTD and SD are refused. The pairs: bits → Y, C; DS, DD, DH,
    DF, SD → DS, DD, DH, DF, TD, CTD, SD; TXT → DS, DD, DH, TXT.
- Q-M2 Pack:
  - Is X001..X016 → DS accepted?
  - Are DH words → DF accepted?
  - Is TXT → SD accepted?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/move.md):** all three are refused. X, Y, T, CT
    and SC pack to DH only; C to DS, DD, DH, DF; DS to DD, DF; DH to DD; TXT to DS, DD,
    DH, DF, TD, CTD.
- Q-M2b Unpack: are DS5 → Y001..Y016 and DD → DF accepted?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/move.md):** both are refused. DS unpacks to C;
    DD and DF to C, DS, DH; DH to Y, C.
- Q-M3 Equal range ends: is Block DS1..DS1 refused? Pack and Unpack with start == end?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/move.md):** all are refused (OBJ-012); an end
    before the start is OBJ-009.
  - **ANSWERED 2026-11-11 (DLL, verifier):** Fill's OnOK runs the same range check on its
    destination (Inst_Copy), so `fill(0,DS1..DS1)` and `fill(0,DS5..DS1)` are
    refused too.
- Q-M4 Block DS1..DS4 → DD1: does CLICK compute the end as DD2 or DD4? And DD1..DD4 → DS1?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/move.md):** by element count: DD4, and DS4.
- Q-M5 Single Copy:
  - Is `"AB"` → DS1 refused?
  - Are 40000 → DS1, 3.5 → DS1, 5000000000 → DD1 and 100h → DH1 refused?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/move.md):** `"AB"` → DS1 and 5000000000 → DD1
    are refused; 40000 → DS1, 3.5 → DS1 and 100h → DH1 are accepted. A hex constant above
    FFFFh copies to DD or CTD only (10000h → DH1 is refused).
- Q-M6 Pointers: does Block Copy refuse `DS[DS1]`? Does Search accept a pointer?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/move.md):** both refuse a pointer. The exact
    error id is not settled (most likely OBJ-005).
- Q-M7 Math: what is the longest formula, and what is the message? Today DS1..DS68 is
  accepted and DS69 is refused; the edit limit reads as 500 characters.
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/move.md):** 270 characters of the formula as
    CLICK stores it (OBJ-1008 "The Formula is too long"): a sum of 68 addresses fits, 69
    does not. Constants, function names and parentheses count; the 500-character edit
    limit is a looser, separate cap.
- Q-M8 Math: which of these are refused?
  - `SUM(X001:X008)`, `SUM(Y001:Y008)`, `SUM(T1:T3)`, `SUM(SC1:SC3)`
  - `SUM(CT1:CT3)`, `SUM(TD1:TD3)`, `MAX(TD1:TD3)`, `MAX(DS1:DS3)`
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/move.md):** on a current CPU only
    `SUM(CT1:CT3)` is refused (OBJ-1002); MAX, MIN and AVG refuse a bit range. An older CPU
    refuses SUM over any bit bank and MAX, MIN, MDN, AVG, RAND and ABS outright
    (OBJ-1016); laddercodec applies the current-CPU rule.
- Q-M9 Math:
  - Is a hex result into DS1 or DD1 accepted?
  - Are 3000000000 (decimal), and 10000h and 1FFFFh (hex), refused?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/move.md):** a hex result into DS1 or DD1 is
    refused: a decimal Math stores to DS, DD, DF, TD, CTD or SD, a hex Math to DH or YD.
    3000000000, 10000h and 1FFFFh are refused (OBJ-1009).
  - **ANSWERED 2026-11-11 (DLL, verifier):** a decimal integer is refused when its low 32
    bits, printed with `%d`, differ in length from the typed token (Inst_Math),
    so `007` and `-0` are refused and `6000000000` passes. Hex constants are checked only
    in a hex Math.
- Q-M11 Copy pointer offset: is `DS[DS1+5]` (or `DS[DS1-5]`) refused in the Single Copy
  dialog? laddercodec now refuses it (Help CL238 shows no offset). pyrung's translator writes
  this form for a mapped block with an offset (`pyrung/src/pyrung/click/ladder/translator.py:725-728`).
  - **ANSWERED 2026-11-11 (user, dialog): refused.** laddercodec is right; pyrung's
    translator must stop writing it.
- Q-M10 Search:
  - Which banks does the Result Flag accept?
  - With a TXT range and source "A", are the order operators disabled?
  - Are DS10..DS1, DS1..DD5 and a one-register range refused?
  - Is DS1..DS10 > 40000 accepted?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/move.md):** the Result Flag is a C bit; the
    order operators are hidden for a text constant, leaving == and !=; DS10..DS1, DS1..DD5
    and DS1..DS1 are refused (OBJ-009, OBJ-008, OBJ-012).
  - **ANSWERED 2026-11-11 (DLL, verifier):** a TXT register value reaches the same text test
    as a text constant (Inst_Search), so the order operators are hidden for it too. A hex
    value is 32-bit, and refused (OBJ-005), only above FFFFh: baseEx decides by value, so
    `0FFFFh` is accepted.
  - **ANSWERED 2026-11-11 (user, dialog):** `DS1..DS10 > 40000` is accepted.
  - **Ruling 2026-11-11 (user, then orchestrator):** a Search text value follows the Compare
    rule: a quoted text of 1 to 128 printable ASCII characters, or `$hh` unquoted. `""`, an
    inner `"` (spell `$22`), a quoted `"$hh"` (write `$41`), over 128 characters and
    non-ASCII raise `FieldError` naming `Search.source`; a native blob holding one decodes as
    raw. The empty-text refusal is the user's; the rest applies the Compare ruling (Q-B7) to
    Search as an orchestrator ruling. DLL: Inst_Search value field runs baseEx
    CheckInputData, mask 0x6fff, as Compare does; a 0x82 text limit (EM_LIMITTEXT) in the
    Inst_Search value field and a length check in baseEx; `""` gives OBJ-005 at Inst_Search.
    Hardware: CLICK matches multi-character text as a window over consecutive TXT registers
    (pyrung case search/text_windows).
  - **Ruling 2026-11-11 (user, revised again):** a quoted "$hh" is literal text, as the dialogs accept it (Compare bits.md N4; Search Inst_Search 0x2040 class).
- Q-M12 Pack text: is `pack_text(DS1..DS2,DD1)` refused? laddercodec accepts it; no DLL
  trace ties the whitespace options to a TXT source.
  - **ANSWERED 2026-11-12 (user):** CLICK has no separate text pack. pyrung's `pack_text` is
    CLICK's Copy → Pack with a TXT source, which is where the whitespace options appear. So
    `pack_text` needs a TXT source (conv type 9/10), and a TXT source packs only as
    `pack_text`. laddercodec accepts `pack_text(DS1..DS2,DD1)` and `pack_words(TXT1..TXT2,DS1)`;
    refuse both. The native fixtures agree: every `pack_text` source is TXT and every
    `pack_words` source is DS.
- Q-M13 Decimal Math with a hex constant: are `DS1 + 10000h` and `DS1 + 1Fh` accepted in a
  decimal Math? The hex tests run only in hex mode, and laddercodec accepts both.
  - **ANSWERED 2026-11-12 (user, dialog):** no, both are refused. laddercodec accepts them;
    refuse a hex constant in a decimal Math.
- Q-M13b Hex Math with a decimal integer: does a hex-mode Math refuse `DH1 + 70000` or
  `DH1 + 007`? laddercodec checks only hex constants in hex mode and accepts both.
  - **ANSWERED 2026-11-12 (user, dialog):** `DH1 + 70000` and `DH1 + 7` are both refused: a
    hex Math takes no decimal constant. laddercodec accepts them; refuse them.
  - **CORRECTED 2026-11-12 (user, dialog, rechecked after the grammar research):** hex
    `DH1 + 7` is accepted and rewritten as `DH1 + 7h`, as the Math dialog's code predicts
    (a bare digit run in hex mode is read as hex: `10` would mean 10h = 16). `70000` is
    refused (more than four digits). laddercodec refuses both since move6; whether to keep
    refusing a bare `7` or to rewrite it as CLICK does is the user's call (with `7H7`).
- Q-M14 Block Copy into Y across a slot: what does `X001..X008 → Y010` give? CLICK's
  GetNextAddress steps on into the next Y slot; laddercodec refuses the run until a capture
  shows the stored destination.
  - **ANSWERED 2026-11-12 (user, dialog):** `X001..X008 → Y010` is refused; `→ Y001` works.
    laddercodec already refuses it; keep that.
- Q-M15 Math result banks newly accepted: paste a decimal Math into SD9 and a hex Math into
  YD1 and YD0u, and copy them back.
- Q-M16 Comma float: is `1,5` accepted as a Copy source into DF1? The shared check sends a
  comma to its float test, which was not read; the constant classifier refuses it.
  - **ANSWERED 2026-11-12 (user, dialog):** refused. laddercodec already refuses it.
- Q-M17 Float range: is `3.5E+38` (above float32) accepted as a Copy source into DF1? No range
  is known for the shared check's float path; the classifier refuses only non-finite values.
  - **ANSWERED 2026-11-12 (user, dialog):** `3.5E+38` is refused. `3.5E+3` is accepted, and
    the dialog rewrites it as `3500.0`. laddercodec accepts both; refuse a real above the
    float32 range (the exact edge, about 3.4028235E+38, is not checked). Open: does a pasted
    `3.5E+3` copy back as `3500.0`? If so, CLICK normalizes a real the way it does an
    address, and laddercodec may want to write the normalized form.
  - **ANSWERED 2026-11-12 (user):** the rewrite to `3500.0` is the dialog's, done as it is
    typed. laddercodec keeps writing a real as given; no normalization.
- Q-M18 32-bit hex digits: is `000000001h` (nine digits, leading zeros) accepted as a Copy
  source into DD1? The classifier counts typed digits (at most 8).
  - **ANSWERED 2026-11-12 (user, dialog):** accepted; the dialog calls it an "H Value". So the
    check goes by value, not by typed digits, as in Search (Q-M10). laddercodec already
    accepts it; check that `classify()` does too.
- Q-M19 Number into TXT: are `5` and `0Fh` accepted as a Copy source into TXT1, and as a Fill
  value into TXT1..TXT5? Is `10000h` accepted as a Fill value into DD1..DD5?
  - **ANSWERED 2026-11-12 (user, dialog):** yes to all. laddercodec already accepts them.
- Q-M20 Text in Math: are `DS1 + "A"` and `DS1 + $41` accepted in a decimal Math? Q-M9 covers
  numbers only.
  - **ANSWERED 2026-11-12 (user, dialog):** no, both are refused. laddercodec accepts them;
    refuse text in a Math formula.
- Q-M21 Search value kind against the table: are a hex value against a DS table
  (`DS1..DS10 == 0FFFFh`), a decimal against a DH table, and a number against a TXT table
  refused? The DLL reading pairs the value's class with the table banks, with no dialog
  check; 114 dry-run rows (devtools/classify_dryrun.py, `DIFFERS?`) wait on this.
  - **ANSWERED 2026-11-12 (user, dialog):** the value's kind ties to the table: a hex value
    (`0h`) to DH, a decimal (`1`) to the integer banks ("INT"), and text (`"T"`) to TXT.
    This confirms the DLL pairing, so the 114 `DIFFERS?` rows follow it. Settled (user,
    2026-11-12): a decimal integer or a real searches DS, DD, DF, TD or CTD; a 16-bit hex
    value DH; text or `$hh` TXT. Built in `Search`, with `SEARCH_TABLE_BANKS` in
    `operands/constants.py`.

**comm**
- Q-C1 Slave ID: are DD1 and C1 refused?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/comm.md):** both refused (OBJ-004); an indirect
    slave ID is a DS address. laddercodec already matched.
- Q-C2 TCP target:
  - Are IP 0.0.0.0 and a blank octet refused?
  - Are ports 0 and 65536 refused, or only labelled?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/comm.md):** 0.0.0.0 accepted, a blank octet
    refused (OBJ-005), ports 0 and 65536 refused (GUI-101). laddercodec already matched.
- Q-C3 Receive: which local types enable Word Swap on each of the four dialogs? Which
  combination limits the count to "(1 to 1)"?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/comm.md):** Word Swap is forced off for bit
    Receives, YD and TXT destinations, DD/DF under CLICK addressing and DH read from XD/YD;
    DS/DH enable it above 1 element. "(1 to 1)" is a YD destination, or DH from a CLICK XD
    or YD. TXT takes an even count of at least 2. laddercodec now refuses the rest.
  - **ANSWERED 2026-11-11 (DLL: Inst_RD.dll):** at one DS or DH element the
    disabled Word Swap is forced off; laddercodec now refuses `word_swap=1` there.
- Q-C4 CLICK-addressed Receive of X1 with the combo set to FC02: does CLICK write FC02? A
  register with FC04: does it write FC04? A capture settles S9.
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/comm.md):** CLICK writes FC02 and FC04 as picked,
    as the native `scr_captures/coverage` rungs 88-89 show. S9 fixed: `function_code=2`/`4`.
- Q-C5 Send: is the same C bit in two status fields refused? Is a 32-bit source at hex FFFEh
  refused with 1 element, and with 2?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/comm.md):** both refused (OBJ-014; OBJ-010, the
    highest hex start is FFFDh for DD, DF, CTD and TXT); a DD source at FFFDh takes 1
    element. laddercodec now refuses them.
  - **ANSWERED 2026-11-11 (DLL: Inst_RD.dll):** a Receive refuses one C bit
    in two status fields too (0x271e); laddercodec now refuses it.
- Q-C6 Counts across banks with gaps:
  - Does Send X001 with 17 elements read X001..X016 and then X101, or is it refused?
  - Is X815 with 3 elements refused?
  - Is YD8 with 5 elements refused? Where does YD0u fall in a count?
  - Today a CSV range `X001..X101` encodes as 101 elements (end minus start, plus 1), and no
    room check is made for X, Y, XD or YD.
  - **PARTLY ANSWERED 2026-11-11 (user, dialog):** the count's upper bound adjusts to the
    start: X 1-32, C 1-1968, T 1-500. C and T match "min(cap, room left in the bank)". X 32
    from X001 equals the first two slots (X001-X016 + X021-X036), so CLICK seems to count X
    points along the slot table rather than by number. Open: is 32 the project's configured
    I/O (CPU + dual option slot only) or a fixed limit? Does it grow with an expansion module,
    or from a later start such as X101?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/comm.md):** a fixed slot table, not configured
    I/O. CLICK addressing: 33-n from X001-X016, 37-n from X021-X036, 17-(n%100) from X101
    (X001 gives 32, X101 16, X815 2); 984/hex counts through slot 8 (X001 gives 160). X815
    with 3 is refused in both modes; a YD count over 1 can't be entered. laddercodec now
    checks that room and counts an X/Y CSV range along the slots (`X001..X021` is 17).
    Still open (firmware): which point the 17th element from X001 is. CLICK stores only the
    start and the count.
  - **ANSWERED 2026-11-11 (DLL: Inst_RD.dll and Inst_SD.dll quantity limits):** a Receive
    into Y uses the slot run in every mode (Y001 gives 32, not 160), capped by a remote C, T,
    CT or SC bank and by a MODBUS 984 coil start (65536 minus the start). A C count to or
    from a CLICK X/Y address stays in that address's slot run, and a C count to or from a
    CLICK C, T, CT or SC address stays in that bank (the Inst_RD.dll and Inst_SD.dll local C
    cases). laddercodec now checks all of these.
  - **NEEDS DIALOG:** a Receive into Y101 or later from a CLICK C, T, CT or SC address. The
    remote C case (Inst_RD.dll) skips its slot formula from Y101 on, so its room is the C
    room capped by the higher of the two start numbers. laddercodec applies only the C room
    and the points through Y816 (Y101 from C1 gives 128). The T, CT and SC cases
    (Inst_RD.dll) give a room of 0 from Y101 on, so CLICK seems to refuse every count.
    laddercodec uses the slot run there (Y101 from T1 gives 16). Check in the dialog: Y101
    from C1 with 17 and with 102 elements; Y101 from T1 with 1 element.
- Q-C7 Remote hex address: does the dialog accept `0H` (uppercase)? Does it accept a Send of
  one DD/DF/CTD element as FC16? (The codec writes FC06 for any single element.)
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/comm.md):** `0H` is accepted (laddercodec keeps
    refusing it until a capture shows the stored text). One DD/DF/CTD element must be FC16
    (FC06 refuses them), and XD/YD FC06 only; laddercodec now writes FC16 for them.

**flow**
- Q-F1 For:
  - Are a constant 0, a negative and 2147483648 refused?
  - Which banks are refused (DF, DH, X, C, T, CT, TXT)?
  - Is a pointer accepted?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/data.md):** a constant 0 is accepted (no floor);
    a negative and 2147483648 are refused, OBJ-005. Banks DS, DD, TD, CTD and SD only; DF,
    DH, X, C, T, CT and TXT are refused, OBJ-004.
  - **ANSWERED 2026-11-11 (user, dialog):** a pointer (`DS[DS1]`) is refused.
  - **ANSWERED 2026-11-11 (user, dialog):** `1 0` (inner space) passes the dialog, a gap in
    its check; the user's decision is to refuse it, since it is not a number. Leading and
    trailing whitespace keeps today's handling (stripped).
- Q-F2 Add New Subroutine:
  - What happens at 25 characters?
  - Are spaces, `-`, `.`, a leading digit, a case-only duplicate and "Main" refused?
  - **ANSWERED 2026-11-11 (DLL, jobs/dllqa/data.md):** the edit takes 24 characters, so a
    25th cannot be typed. The name is trimmed. `\ / : * ? " < > |` and a Windows device
    name (AUX, CON, NUL, PRN, CLOCK$, COM1-9, LPT1-9) before the last dot are refused,
    GUI-040. A case-only duplicate is refused, GUI-036. Inner spaces, `-` and a leading
    digit are accepted. The checks live in CLICK.exe; Add Interrupt has the same ones.
  - **ANSWERED 2026-11-11 (user, dialog):** `main` and `.` are accepted. An empty or
    all-space name is refused.
  - laddercodec: `Call.subroutine` takes the name rules, checked on the trimmed name.
    The case-only duplicate (GUI-036) is a cross-program rule and is not checked (BOB
    ruling); the 986-subroutine Call list limit is a project rule.

**Captures wanted (one-time, when convenient)**
- Native Home, Velocity and Position, one per mode, with distinct values in every field.
  Their tag maps are inferred only, and they stay `raw` tag strings until captured.
- Native Email with To, Cc, Bcc, Subject and both body modes filled. Its tag map is unknown.

## Rulings

- **Ruling 2026-11-11 (user):** constants, counts, presets and address numbers accept only
  the ASCII digits 0-9. Python's `\d` and `int()` take any Unicode decimal digit
  (`٣`), which CLICK's validators do not; every regex and digit test in the codec is
  ASCII.
- Field rules raise in `__post_init__`, so construction, CSV and encode all go through them.
  Decoders keep the existing ValueError → raw fallback. Cost if wrong: a rule that is too
  strict turns a native blob into raw. The native fixtures in `make test` catch that.
- A rule supported only by a DLL inference ([I]) or by a single source that disagrees with
  another waits for its dialog answer, and does not raise yet. Cost if wrong: a gap stays
  open for one more round.
- Bank number ranges (Help 195) count as field rules. Limits from the configured I/O count as
  project rules. Cost if wrong: an expansion-I/O address beyond the CPU's real modules still
  encodes.
- Motion (Home, Velocity, Position) and Email stay as opaque tag strings in Phase 2, and get
  field rules only after the captures above. Cost if wrong: their gaps stay open longer.
- Syntax rules stay out of the codec, per the arc. Cost: none.
- Pin rows, such as Shift `.clock()`/`.reset()`, follow two different rules:
  - Their structure is a field rule. The blob always has the rows, and the converter's
    autofill of blank rows already guarantees that.
  - The contacts on those rows are a syntax rule (C0205-C0214). A bare `shift(...)` in CSV
    keeps converting.
  - The brief for bob/data said "pins required" and the builder refused the bare form; that
    was reverted.
  - Cost if wrong: none for CLICK, which still saves these rungs.

## Leftovers

- Process: `bob-investigator` cannot write outside $TEMP or run Python, so Phase 1 re-read no
  DLLs. A later DLL pass goes to `bob-reviewer`, which runs bounded scripts under $TEMP; see
  profile.md.
- The SCR fallback is lossy and disagrees with clipboard decode. Both cases predate step 0,
  which makes them reachable through bad addresses:
  - `decode_program.py:658` keeps only the class name in `UnknownCondition`, not the blob.
  - `decode_program.py:674-680` builds the raw AF blob from the tags SCR stores. Correction
    (scrraw, 2026-11-11): SCR stores only the tags that differ from the defaults (Shift keeps
    `{6066,6067,0000}` and no 3a05 tags; Out, Drum, Math and RD flags are sparse the same way),
    so nothing is dropped and passing the variant tags through recovers nothing. The earlier
    note here, which said the clock and reset func codes were lost, was wrong.
  - Plan (after the release, the user's idea): one frozen blob dataclass per instruction
    class, holding the ordered tags, defaults, array sizes and func code. SCR decode lays its
    sparse tags over it to build the full clipboard blob, and an unknown class fails loudly.
    Proof: the native SCR and clipboard pairs (793 AF blobs, 755 conditions).
  - Typed SCR decode is lossy today. SCR decode followed by build_blob differs from the
    native clipboard blob in 120 of 793 AF blobs: the RD/SD array sentinel form, Call tag
    3219 (48 cases, e.g. 9 written as 0) and Math 2224 with nickname 6228 (46 cases). Is
    Call 3219 data that matters?
- Bits family: OutVariant's unused `on_acc`/`off_acc` is refused at construction (24740f3),
  and decode leaves a blob raw if any tag differs from what the kind would write (train2).
- Done in train4 (2ae8501): a raw tall box keeps its native height (clipboard +0x09/+0x0A, SCR
  entry header bytes 2/3), and a CSV-read raw takes its class's height. `Counter` defaults to
  `reset_enabled=True` and refuses False, since a CLICK counter always has a Reset. The five
  unchecked flag fields below go through `check_flag`.
- Open from rawheight's review: the writer's `_af_tokens_match` can't see a raw box height
  loss, because a raw's height is left out of equality (the CSV token can't hold it).
- `dll_address` refuses a short mask written right after a DLL name and a colon, as if it
  were an address. No case of this exists today.
- Flag fields without `check_flag` (hcrash review): `Timer.retained`, `Contact.wire_down`,
  `CompareContact.wire_down`, `Drum.jog_enabled`, `Drum.jump_enabled` accept any truthy value
  (`retained=2`, `"x"`). None crashes; route them through `check_flag` after the release.
- Ground truth: does a CLICK dialog accept `X1` and `DS0001`, or only `X001` and `DS1`? Help
  195 lists only the zero-padded X/Y form. Step 0 accepts both forms, as before.
  ANSWERED 2026-11-12 (user, dialog): both are accepted and rewritten, `X1` → `X001` and
  `DS0001` → `DS1`, which is what laddercodec's display form already does. Nothing to build.
- Parked 2026-11-12 (user ruling): a stored rung that breaks a dialog rule, such as a
  pre-rule paste of `DH70 == DS3920`, decodes as before: an AF falls back to raw() and a
  condition to UnknownCondition, which `write_csv` can't write. ClickNick handles it (the
  simulator error names the rung and says "Paste it again"; Guided Paste shows "re-paste").
  The parked design, if more users hit it: on a FieldError, decode builds the object from
  the stored text and attaches a LegacyFinding, and `read_csv(legacy=True)` does the same
  for the writer's self-check (`csv/writer.py:347`). Construction, plain `read_csv` and
  `encode()` stay strict.
- Math, from move8's review (predates move8, on dev):
  - A nickname containing spaces leaks into `_make_internal`: `<my 7H >` becomes
    `<my#UH7#>` and `<my 200 >` becomes `H200`, so the stored nickname text changes.
    ANSWERED 2026-11-12 (user, capture `clicknick/test_nickname_with_space_math.bin`,
    `DS3` nicknamed "Test Nickname", typed as `<Test Nickname> + 1`): CLICK stores the
    template `@ + 1`, the display `<Test Nickname> + 1` and the internal formula `DS3#+#H1`.
    The internal form always holds the address, never the nickname; the clipboard also
    carries the nickname in a table near its end. laddercodec has no nickname table, so any
    `<nickname>` in a Math expression (spaces or not) writes a formula CLICK never writes.
    To build: refuse `<...>` in `Math.expression`; `test_math_nickname_keeps_its_digits`
    changes to expect the refusal.
  - `DS1 + FOO` and `DH1 + 7H7` are accepted as unknown words. Answered 2026-11-12, see
    the hex-Math answers: both are refused (building on move9).
- ASCII Send/Receive is not modelled (raw). Its rules are in the comm report, for a later
  arc.
