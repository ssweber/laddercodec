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
    DD, DF, SD, int/float constant}, text {TXT, one-char `"x"` or `$HH`}. Cross-group pairs
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
  Q-B4 and a capture.

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
- Q-B2 Out: which SC addresses are accepted? Is it exactly SC50, 51, 53, 55, 60, 61, 65, 66,
  67, 75, 76, 120, 121?
  - **ANSWERED 2026-11-11 (user, dialog): 25 SC bits, the read-write system bits in CLICK's
    address picker.** SC50, 51, 53, 55, 60, 61, 65, 66, 67, 75, 76, 120, 121, 162, 165, 168,
    171, 303, 304, 305, 306, 323, 324, 325, 326.
- Q-B3 Out:
  - Is `C5..C5` refused?
  - Is `C1..C2000` accepted?
  - Is immediate `Y016..Y101`, which crosses a module, accepted?
  - Is an SC range accepted?
  - **ANSWERED 2026-11-11 (user, dialog):** `C5..C5` is refused; `C1..C2000` is accepted;
    immediate `Y001..Y101` is accepted; an SC range is accepted.
- Q-B4 Debounce: can it be saved with only the off phase filled? With only the on phase? If
  yes, a capture shows what CLICK writes.
- Q-B5 Debounce and flasher: is the same TD for the on and off timer refused?
- Q-B6 Debounce, flasher and timed: is a preset of 32768 refused? Does the Timed unit list
  include min? (Help 350 says no; a capture says yes.)
- Q-B7 Compare:
  - Is `DS1>40000` refused? `DS1==3000000000`? `DH1==10000h`?
  - Is a constant accepted on the left (`100<DS1`), or on both sides (`1==1`)?
  - With TXT1 as Data A, are `>`, `<`, `>=` and `<=` disabled?
  - Are `DH1==FFFFH` (uppercase H) and `TXT1=="$41"` (quoted) accepted?

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
    How laddercodec writes the operand text is a separate open question.

**move**
- Q-M1 Block Copy DS1..DS3:
  - Are a YD destination and an SD destination accepted?
  - Are TD, CTD and YD sources accepted?
  - Is TXT → DF refused?
- Q-M2 Pack:
  - Is X001..X016 → DS accepted?
  - Are DH words → DF accepted?
  - Is TXT → SD accepted?
- Q-M2b Unpack: are DS5 → Y001..Y016 and DD → DF accepted?
- Q-M3 Equal range ends: is Block DS1..DS1 refused? Pack and Unpack with start == end?
- Q-M4 Block DS1..DS4 → DD1: does CLICK compute the end as DD2 or DD4? And DD1..DD4 → DS1?
- Q-M5 Single Copy:
  - Is `"AB"` → DS1 refused?
  - Are 40000 → DS1, 3.5 → DS1, 5000000000 → DD1 and 100h → DH1 refused?
- Q-M6 Pointers: does Block Copy refuse `DS[DS1]`? Does Search accept a pointer?
- Q-M7 Math: what is the longest formula, and what is the message? Today DS1..DS68 is
  accepted and DS69 is refused; the edit limit reads as 500 characters.
- Q-M8 Math: which of these are refused?
  - `SUM(X001:X008)`, `SUM(Y001:Y008)`, `SUM(T1:T3)`, `SUM(SC1:SC3)`
  - `SUM(CT1:CT3)`, `SUM(TD1:TD3)`, `MAX(TD1:TD3)`, `MAX(DS1:DS3)`
- Q-M9 Math:
  - Is a hex result into DS1 or DD1 accepted?
  - Are 3000000000 (decimal), and 10000h and 1FFFFh (hex), refused?
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

**comm**
- Q-C1 Slave ID: are DD1 and C1 refused?
- Q-C2 TCP target:
  - Are IP 0.0.0.0 and a blank octet refused?
  - Are ports 0 and 65536 refused, or only labelled?
- Q-C3 Receive: which local types enable Word Swap on each of the four dialogs? Which
  combination limits the count to "(1 to 1)"?
- Q-C4 CLICK-addressed Receive of X1 with the combo set to FC02: does CLICK write FC02? A
  register with FC04: does it write FC04? A capture settles S9.
- Q-C5 Send: is the same C bit in two status fields refused? Is a 32-bit source at hex FFFEh
  refused with 1 element, and with 2?
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
- Q-C7 Remote hex address: does the dialog accept `0H` (uppercase)? Does it accept a Send of
  one DD/DF/CTD element as FC16? (The codec writes FC06 for any single element.)

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
  - `decode_program.py:674-680` builds the raw AF blob from the standard tags only and drops
    the variant u16/string tags. A refused Shift decodes from SCR as
    `raw(SR,...,6066=C1,6067=C0)`, without the clock and reset func codes that clipboard
    decode keeps.
  - One fix covers both: pass the SCR variant tags into `_compose_blob` and keep the
    condition bytes. This is an Opus job (decode_program).
- Bits family: OutVariant writes the `on_acc`/`off_acc` that a kind doesn't use, without
  checking them (`out_variant.py:105-110`, `201-221`), so `toggle` with `on_acc="Q77"`
  encodes Q77 and the decode drops it. Refuse a non-empty unused field (review N3 on
  operands).
- Ground truth: does a CLICK dialog accept `X1` and `DS0001`, or only `X001` and `DS1`? Help
  195 lists only the zero-padded X/Y form. Step 0 accepts both forms, as before.
- ASCII Send/Receive is not modelled (raw). Its rules are in the comm report, for a later
  arc.
