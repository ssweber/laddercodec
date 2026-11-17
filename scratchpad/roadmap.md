# laddercodec roadmap

This file is the only statement of what laddercodec still has to do. Work that crosses repos is written once,
in the ecosystem plan (`ssweber.github.io/plan/README.md`); items here link to it and don't repeat it. When an
item lands, delete it.

Each item says what it needs: **nothing** (code only), **CLICK** (the CLICK software, through the sandbox
runner or Sam), **PLC** (a real PLC), **Sam** (his judgment), or **another repo**. Work that needs nothing is
never queued behind work that needs Sam.

Written 2026-11-15, after 0.4.0, from the post-release plan and Sam's rulings on it.

## How work runs here

- **Branches.** Feature and refactor branches go into an always-releasable `main`, only through PRs. There is no
  `dev` trunk. A session pushes its branch, opens the PR and squash-merges it once CI is green on the head commit
  and a fresh reviewer has passed that commit. A PR that needs Sam, CLICK or a PLC (a golden paste check, say)
  waits for that. Every PR carries its CHANGELOG line, so `main` can be released at any commit.
- **Releases are Sam's.** Nothing is tagged, released or published without him. Publishing a GitHub release
  sends the package to PyPI, then, unless it is a pre-release, `publish.yml` starts a docs deploy of that tag. A
  redeploy by hand is
  `gh workflow run docs.yml --ref main` (the latest release, or `-f ref=<tag>`); it is a deploy, so it is Sam's
  call too.
- **Builds.** Multi-branch jobs run as BOB arcs: a worktree and a builder per branch, a fresh reviewer, CI as the
  gate. BOB comes from the shared `bob` plugin (`ssweber/bob`); this repo's settings are in `.claude/bob/`.
- **Arc folders stay out of git** (`../laddercodec-wt/buildbot/jobs/`). When an arc closes, its open items move
  here and the folder can go.
- **No provenance.** Code, tests and user docs say what a rule is, not where it came from. CLICK's own error ids
  in messages, such as "(OBJ-023)", stay: that is what CLICK shows the user. What is still in doubt is written
  here as a question.
- **Less code first.** Deletion and consolidation come before new features. Line count is not a target; do what
  is prudent.

## Order

Done: the cruft sweep, the undecoded marker (#38), the field-rule restructure (#43-#51) and the field error
pyrung reads (#55-#60: every instruction reports every refusal, with its fields, reason, CLICK id and, through
`read_csv`, a location on each). The next release, Sam's, carries it. Item 2, decoding that does not depend on
the checks, is done too: a stored instruction that breaks a dialog rule decodes as that instruction with a
`RefusedFieldWarning`, and `read_csv(..., unchecked=True)` reads what `write_csv` writes for it.

Sam's direction of 2026-11-16: pyrung's CLICK validation moves onto laddercodec first, ahead of its export and
import. pyrung builds laddercodec's objects and turns each refusal into a finding; its own bank tables go.

1. The field error's follow-ups. pyrung's validation waits only on a release with the error.
3. Field rules tightened to the CLICK grids, as the grids arrive.
4. Canonical constants, once CLICK has answered (the runner is asking now). It can run beside 1-3.

The stable public API and the SCR blob dataclass fit in wherever they are ready. pyrung's export needs come
later (below).

laddercodec refuses what CLICK's editor refuses, plus what breaks the encoding or crashes CLICK on a paste. A
rule that rests on what a PLC does stays in pyrung.

## 1. The field error's follow-ups (nothing, except where marked Sam)

pyrung learns what a field takes by building the object and reading the error; that is on `main`. Not built: a
rule-description API (`field_rules(Copy)["source"]`), and a public way to build an instruction without its
checks (pyrung's conformance probes use `raw(...)`; the decoders use the private
`laddercodec.operands.unchecked.unchecked()`, which a public API could expose).

- **A strict numeric tag.** `tag_int` reads a tag through `int()`, so it accepts `" 1"`, `"+1"`, `"1_0"` and
  non-ASCII digits, as it did before. Reading only ASCII digits would leave those blobs raw.
- **A held condition from a program file.** A contact `decode_program()` builds with a refusal has no blob to
  write, so `encode()` raises its error (the unknown condition it decoded as before did not encode either). An
  output box writes the blob composed from its tags, as its raw box did. Decide whether a condition should too.

- **Where in a formula (Sam).** Two identical refusals in one formula (`DS0 + DS0`) can't be told apart. The
  proposal: `FieldError.span`, a half-open `(start, end)` character offset into the expression as typed; None
  where no single stretch is at fault (empty, the length, a `(` left open, the mode conflict); a range refusal
  spans its `A : B`, SUM's CT and X/Y refusals the range argument. It is new public API.
- **The blanks a CSV token still reads as syntax:** a blank argument is now its field `missing` where it fills
  one text field or a range (a range with a blank end, `..DS4`, too). The family parsers check these before
  construction, so a blank is a syntax error with no field, where Python says `missing`: a Timer or time drum
  `unit=` (an Out variant's reads as `missing`, an event drum's is accepted), a Math `mode=`, a time-event drum
  `accumulator=`, a drum list (`outputs=`, `presets=`, `events=`, `pattern=`), a whole Modbus `target=` and a
  search expression (`search(,result=DS1,found=C1)`). Reading them as `missing` means changing `timer.py`,
  `drum.py`, `math.py`, `search.py` and `send_receive.py`.
  - A token with blanks of two forms, a range and a single field (`pack_bits(,)`, `unpack_to_bits(,)`), stays a
    syntax error: every blank in a token is tried in the same form.
  - Condition tokens are not read for blanks: `rise()`, `DS1==` and `~` are syntax errors.
  - `oneshot=` is the default in Copy, Pack, Unpack, Fill, Search and Math but a syntax error in `out` and
    `for` (as is `maintained=` in `timed`).
  - The coil parser drops a blank argument: `out(C1,)` is accepted, and `out(,oneshot=)` reads `oneshot=` as
    the operand, an `address` refusal.

## 3. Field rules tightened to the CLICK grids (CLICK)

The runner tries whole grids, not samples: every bank and constant kind in each dialog field. Its answers are
committed here as test data, which makes these tests the one place CLICK's field rules are recorded. No rule is
written from the 17 sampled rows in `ssweber.github.io/plan/rule-decisions.md`.

- **Case lists (Sam, 2026-11-16):** laddercodec writes them, since it knows how each field is modelled (banks,
  constant kinds, modes), in the shape of ClickNick's `devtools/editor_cases.json`. click's runner runs them
  and returns the answers; cases and answers are committed as test data. The runner's `try` drives Math, Copy
  (single, block, pack, unpack) and Out today, about 4 seconds a case, so those grids run first. click is
  adding a run that resumes and more dialogs, Receive first.
- **Math, Copy and Out grids are written** (#54): `tests/fixtures/editor_grids/`, made by `make editor-grids`,
  with laddercodec's verdict beside each case. CLICK answered `preflight` and `risky` (159 cases), Receive
  (18), the picker checks (28) and the full Out, Copy (single, block, pack, unpack) and Math (decimal, hex)
  grids (5,210); `tests/test_editor_answers.py` compares them and lists each difference, grouped by what
  is to be done. Left: Receive, Compare, Search, Fill, timers, counters and For. What the answers showed:
  - Hex Math reads a word typed without `h` as a hex constant (`DH1 + 0`, `5`, `abc`, `DH0` as `D0h`);
    laddercodec refuses it on purpose (Settled, below).
  - Math formula banks (ruled, Sam, 2026-11-16), one table per mode in `math_formula._OPERANDS`:
    - Hex: hex constants and the DH, XD and YD registers only. Every other register (DS, DD, DF, TD, CTD,
      SD, TXT) and every bit is refused, in a `SUM` too. The answers hold DH accepted, and DS and X refused
      (X in a `SUM` too); the rest is the ruling ahead of CLICK.
    - Decimal: decimal constants and the DS, DD, DF, TD, CTD and SD registers; X, Y, C, T and SC bits only
      as the range of `SUM ( a : b )`. DH, XD, YD, TXT and CT are refused anywhere, a `SUM` included. The
      Address Picker for a decimal `SUM` enables exactly X, Y, C, T, SC, DS, DD, DF, TD, CTD and SD.
    - Every bank refusal is OBJ-1002, reason `bank`: one for each address outside a `SUM`, one for each
      `SUM`.
    - The `math_hex` and `math_decimal` answers confirm both tables in every position (alone, beside a
      constant, a range end, a `SUM`), XD and YD in hex and DH, XD, YD, TXT and CT in decimal included,
      except a RAND bound, which takes fewer banks (RAND bounds, below).
    - A `SUM` whose ends are reversed is OBJ-1014, and one whose ends are in two banks OBJ-1015, ahead of
      OBJ-1002 for a refused bank (`SUM ( DH2 : DH1 )`, `SUM ( X001 : TXT2 )`). Closed: the rules check
      every range's banks and order before any address's bank, then a median's size and the X/Y
      option-slot ends. Open (CLICK), the rules' order where no answer covers it:
      - A reversed or two-bank `MAX`, `MIN`, `MDN` or `AVG` range over a refused bank
        (`MAX ( DH2 : DH1 )` in decimal): the rules give OBJ-1014 or OBJ-1015 first, as for a `SUM`.
      - A formula with a refused address beside a refused range (`DH1 + SUM ( DS5 : DS2 )` in
        decimal): the rules give the range's OBJ-1014 first, whatever stands before it.
      - A median over a refused bank that is also past 1024 bytes: the rules give OBJ-1002 before
        OBJ-1013.
  - An edge space is accepted in Math's result and formula, Copy's source and destination, a Block source, a
    Pack destination and an Unpack source, laddercodec refuses. Ruled (closed): the refusal stays, since an
    instruction holds the address in display form; decode reads CLICK's edge-space saves (a single Copy's and
    a Pack's destination keep the space, and decode as the address without it). The ratchet keeps these
    entries with that reason. Both `dec  DS1 = ...` and `dec DS1  = ...` put the space in the Math result.
  - Unpack of a DS into DS is refused with OBJ-004, laddercodec said OBJ-024. Closed: every Unpack
    destination bank its source can't unpack to now carries OBJ-004. CLICK confirms it for a DH source into
    DS and for every source into T, DD and TXT, and gives OBJ-004 for a source from Y, C, T, CT, SC, XD, YD,
    TD, CTD, SD or TXT. A DS, DD or DF into Y is OBJ-024 (Pack and Unpack order, below).
  - Copy-family bank ids (closed for the answered rows): a bank no row of the field holds is OBJ-004 for a
    Pack destination (answered for X001, SD29 and SD31), an Unpack source (X001) and an Unpack destination
    (X, SC and SD); a single Copy into a bit bank it does not write is OBJ-004 from a bit source (X001 into
    X001, C1 into SC50 and SC303) and OBJ-024 from any other (DS2 and 5 into X001). The rules give these ids
    to every bank of each check. What the full grids answered:
    - Single Copy: T and CT as the destination are OBJ-004 from a bit (C1, X001) and OBJ-024 from a DS; a
      DS or a number into SC is OBJ-024; a TXT register or a text constant into X, C, T, CT or SC is
      OBJ-024. The rules give each of these. An XD destination is OBJ-004 from a DS, TXT1 or 5 and OBJ-024
      from a bit or `"A"`; the rules give no id there yet.
    - Pack into Y, C, T, CT or SC (in range or past it) is OBJ-004, and into XD, YD or TXT OBJ-004 (OBJ-033
      for 32 X or Y bits), as the rules give.
    - A bit (C1, X001, T1, CT1, SC1), quoted text or `10000h` into SD1, which a Copy does not write, is
      OBJ-024: the pairing comes first (`$41` into SD1 is OBJ-004). A follow-up, below. SD43 is not
      answered.
    - A DS into an X, T, CT or SC address outside its bank (`DS2 -> X017`, `T501`, `SC1001`) is OBJ-004,
      not OBJ-005. A follow-up, below. A bit source there (`C1 -> X017`) is not answered.
    - Still open: does CLICK report a refused constant source (`99999999999`, `1e99`, `FFFFFFFFFh`, `"é"`,
      text of 200 characters) before the destination, and with which id, when the destination is a bit
      bank (X001)? The rules give the destination's bank refusal no id then, and refuse the constant after
      it.
  - Receive TXT count: confirmed, in characters, 2 to 250 and even (OBJ-010 outside the range, 1 and 251
    included; OBJ-029 for an odd count inside it); the rules match, with both ids. The dialog holds 2 when
    the count is unset, which the rules accept. `receive.answers.json` (rx2) recorded no count, so its
    `03 -> TXT1` stays in the ratchet at count 1.
  - Open: is Send's TXT count in characters too, and what are its limits? Send has no TXT rule today.
- **The writable-SD list (closed):** `sc_sd_writable.answers.json` lists 29 SD for a single Copy, a Block Copy
  and a decimal Math result, none for Out, and 25 SC for Out, none elsewhere. `WRITABLE_SD` holds the 29, and
  the three fields refuse any other SD with reason `not_writable`: a single Copy with OBJ-004 (answered for
  SD43, SD105, SD216 and SD1000), a decimal Math result with OBJ-003 (SD62, SD148 and SD999), and a Block
  Copy when any address of its destination range is not listed. A Block Copy from `DS1..DS2` gives OBJ-018
  ("read only addresses between") into SD42 and SD147, and OBJ-004 into SD215; the rule fitted to these three
  is OBJ-018 for an unlisted SD before SD215 and OBJ-004 for one past it, no id for a range with both, and no
  id for an unlisted start. The sweep grids (`math_sd`, `copy_sd_single`, `copy_sd_block`, `out_sc`) are
  removed: the picker list answers them. Open: CLICK's answer to the last nine `copy.block.destination.banks` cases (a writable start whose range reaches read-only SD, controls inside the list, and a read-only start that ends writable); a Block Copy whose start is not listed, and an unlisted SD
  below SD29 in each field; a Fill into SD still takes every SD (no answer covers it).
- **The picker's lists for 8 more fields are in:** Pack's destination (with nothing, an X source and a C
  source filled first), Unpack's destination and destination end (with nothing, a DH source and a DS source),
  and a hex Math result. None lists an SC or SD address, and the rules accept none. The 15 `try` cases from
  those lists (`picker_lists.answers.json`) and CLICK's two rule-table rows (`rule_rows.answers.json`: a
  block Copy of TXT into TXT and a hex Math into YD) agree with the rules, except one id: CLICK refuses an
  SD as a hex Math result with OBJ-003 (outside the range), answered for SD29 and SD31 and applied to all of
  SD1-SD1000 (the full grid answers SD0 and SD1001 with OBJ-004); YD9 is answered the same way, applied to a YD past YD8. The rules now say so, where they said OBJ-004 or
  gave no id.
  A bank a hex result does not take (DS1) stays OBJ-004.
- **Follow-ups from the full grids (waiting on nothing).** Each is one group in `DISAGREEMENTS`; fix the
  rule, then drop the group's entries:
  - Hex Math words without `h` stay refused (Settled), but a word shaped like an address (`C0`, `DD0`,
    `DF0`, `DH0`, `DH501`, alone, beside `+ 1h` or as a RAND bound) is refused as outside its bank's range.
    That message is to name the `h` form (`C0h`, `D0h`), as the message for `5` or `abc` does.
  - RAND bounds (closed): one table per mode in `math_formula._OPERANDS`. A decimal bound is a DS or DD
    register or an integer constant, a hex bound a DH register or a hex constant; any other bank is
    OBJ-1002, a real bound and equal bounds OBJ-1001, as the answers give. Open (CLICK):
    - Are bounds equal by their text or their value? The rules take the narrowest reading: the same text
      in display form, so `RAND(1h,01h)` and `RAND(DS1,ds1)` are refused and `RAND(1,+1)` is taken.
      `RAND(1,01)` is refused anyway (leading zeros, OBJ-1009) and `RAND(DS1,DS 1)` by its shape.
    - Which id comes first where one RAND has two refusals: `RAND(DF1,DF1)`, `RAND(DF1,1.5)`? The rules
      give the real bound and equal bounds (OBJ-1001) before a bound's bank (OBJ-1002).
    - A hex `RAND(-5,Ah)` is OBJ-1001; the rules refuse `-5` with no id for its missing `h` (Settled), then
      give OBJ-1001 for the shape.
    - Do the shift and rotate arguments (`LSH ( XD0 , 1h )`) take XD and YD, as the rules do? No answer
      covers them.
  - The float32 edge in a decimal Math (closed): `3.4028235E+38`, alone or as an operand, is OBJ-1009,
    though float32 rounds it to its largest value; the largest real answered as taken is `1E5`.
    The rules refuse a real whose value, read as a double, is above float32's largest, 3.402823466E+38, in size:
    of the bounds the answers allow, the only one with a reason, and the one that refuses least. A Copy
    source takes it (`3.4028236E+38` is OBJ-005 there). Open (CLICK), neighbours no answer covers:
    `-3.4028235E+38` (the rules refuse it, as `-3.5E+38` is refused), `3.40282347E+38` (refused, above
    the largest as a double), and `3.402823466E+38`, `3.4028234E+38` and any real from 1E5 up to them
    (taken).
  - A `SUM`'s OBJ-1014 and OBJ-1015 come before OBJ-1002 (closed, above).
  - A hex Math result past SD's range (SD0, SD1001) is OBJ-004 (closed): the OBJ-003 for an SD as a hex
    result covers SD1-SD1000 only, and an SD past them is refused as a bank the result does not take.
  - Copy `DS 1` (a space inside) is accepted as a single Copy's source (saved `DS1`) and destination (saved
    `DS 1`, which `read_csv` refuses) and as a decimal Math result; the rules refuse it. Decide whether it
    is refused on purpose, as the edge space is.
  - An SD pointer (`SD[DS1]`) is accepted as a single Copy's source, and saved as typed; the rules refuse it.
  - Pack and Unpack order (closed): the rules give CLICK's id first in every answered case.
    - A Pack counts its source before the pairing. Where the source packs into the destination, the
      limit is the destination's room (16 or 32 bits, 2 words: OBJ-027, OBJ-041, OBJ-040). Where it does
      not, bits are held to 32 (OBJ-041, then OBJ-024, as the answers' `boxes` show) and a DH source to
      2 words (OBJ-040); a DS source is not counted (`DS1..DS4500` into DH1 is OBJ-024).
    - For a DH source CLICK stops after OBJ-040 (`DH1..DH16` and `DH1..DH500` into DH1 show no
      `boxes`). The OBJ-024 that follows in `.errors` is laddercodec's own; CLICK's first id matches.
    - A Pack of text into DH takes at most 4 characters (OBJ-003, reason `range`): `TXT1..TXT2` and
      `TXT999..TXT1000` are accepted, `TXT1..TXT16` and `TXT1..TXT1000` refused.
    - An Unpack pairs its destination's start with the source (OBJ-004; OBJ-024 for Y from DS, DD or DF)
      before it reads the end, so the end's fit with a refused start (OBJ-008, OBJ-009, OBJ-012) is not
      checked. A DH into a Y range across two slots is OBJ-1009, where the rules said OBJ-019.
  - Pack and Unpack neighbours no answer covers (CLICK):
    - A Pack of text into DS, DD, DF, TD or CTD: CLICK's own code reads limits of 6 characters for DS
      and TD, 11 for DD and CTD and 14 for DF (OBJ-003); the rules take any length there. Into DH, 5 to
      15 characters (`TXT1..TXT5`): the rules refuse them, as CLICK's code does. Ask CLICK next for
      `TXT1..TXT4` and `TXT1..TXT5` into DH1, the edge of the limit.
    - A count where the pairing is refused and no answer shows it: `DH1..DH3` into DS1, DF1, TD1 or
      CTD1, `C1..C33` into TD1 or CTD1, and 33 or more T, CT or SC bits into DF1, TD1 or CTD1 (answered
      only into DS and DD). The rules give the count first (OBJ-040, OBJ-041).
    - A DH into a Y range across two slots with 16 points or fewer (`Y016..Y021`), and into the option
      slot alone (`Y021..Y036`): the rules give OBJ-1009 for the first and accept the second.
  - Copy ids: a `$` code source (`$41`, `$1`) into any bank but TXT is OBJ-004; `""` and a hex source of
    more than 8 digits into DS1 are OBJ-005; a bit, quoted text or `10000h` into SD1 is OBJ-024 (above); a
    DS into an X, T, CT or SC address outside its bank (`X000`, `X017`, `T501`, `SC1001`) is OBJ-004
    (above). The rules give OBJ-024, OBJ-024, OBJ-004 and OBJ-024.
  - Out: a range whose end is in another bank is OBJ-008 even where that bank is refused (`C1..DS1`); the
    rules give OBJ-004.
  - Saves that decode as `raw(...)`: CLICK saves an address as typed (`DS001`, `DS01`, `ds1`, `XD00`,
    `YD0U`, `DS[ds1]`) in Copy, Block Copy, Pack and Math.
  - Saves that decode as `raw(...)`: conversion type 7. A single Copy saves it for exactly these answered
    cases: `1.5` into DD1, `DD[DS1]`, CTD1 or `CTD[DS1]`; CTD1 into DF1 and DF1 into CTD1; `2147483647` into
    DF1. DD1 into DF1 and back, and `1.5`, `5` or `-5` into DF1, keep the usual type.
  - Saves that decode as `raw(...)`: a number whose text fills more than one TXT, into TXT1. The save holds
    the constant as typed, the TXT its text ends in and a conversion type: `-5` ends in TXT2 (type 1), `1.5`
    in TXT3 (type 3), `FFh` in TXT3 (type 1), `2147483647` in TXT10 (type 1). `5` into TXT1 reads back.
  - Quoted text with an E into TXT: item 4 owns it.
- **SC gaps (closed, 2026-11-16):** CLICK refuses an Out on an SC address outside `WRITABLE_SC` (SC49, SC163,
  SC310 and 12 more) with OBJ-003 and accepts SC50 and SC162. `WRITABLE_SC` stands; Out, Set and Reset give
  OBJ-003 for it.
- **Ids confirmed:** Out, Set and Reset share one validator: OBJ-004 for a bank, OBJ-008 for a range across
  banks, OBJ-009 for an end below the start, OBJ-012 for the same address at both ends.
- **Ids left None until CLICK answers.** `click_id` is set only where the code records the field's dialog; an
  id that can't be backed stays None. Open:
  - Fill: its pairing and range ends (Copy's OBJ-024, OBJ-008, OBJ-009, OBJ-012?), and a Fill into TXT of more
    than one character (OBJ-023?).
  - Block Copy, a source range spanning two X/Y modules: CLICK's answer for Pack is OBJ-033 (set); no recorded
    answer covers Block Copy's, so it stays None. What OBJ-035 is for is still unknown.
  - Receive, one C bit for two status fields (Send's is OBJ-014). A Modbus remote address in hex past FFFEh,
    refused while the address is read (a hex start past FFFDh in a Send has OBJ-010). Whether OBJ-010 is
    also CLICK's id for a Send or Receive that runs past C2000, and for the room left in a DD hex start.
  - The Out variant's bank and not-writable SC refusals.
  - A blank field's refusal carries no id yet. CLICK's recorded answers give OBJ-001 for a blank address,
    OBJ-006 for a blank Copy source and OBJ-1001 for a blank Math formula; each field needs its own answer
    before it carries one.
  - OBJ-002 and OBJ-003: which dialogs give them for an address that is not one and for a number outside its
    bank.
  - The Math formula's ids (OBJ-1001 to OBJ-1015, as the code sets them) and the result's OBJ-004 are read
    from CLICK's own code; the math grids confirm every one the rules give.

## 4. Canonical constants (CLICK)

Addresses are written canonical everywhere, and tested. Math and a single Copy source are written as CLICK
stores them (`feat/canon-math-copy`): a real as CLICK prints it back, a Copy integer without leading zeros, hex
in CLICK's case, `$1` as `$01`; hex Math digits without `h` and a Copy `EH` or `1Eh` stay refused, naming the
form to write. A Copy source also follows CLICK's save of `-0` (`0`), a real's `+` (dropped) and a real typed
in exponent form that 7 significant digits don't print exactly (written in 7: `3.4028235E+38` is `3.402823E+38`,
a slightly smaller value), `fix/copy-constants`. `constant_text()` writes a Python value in that form, but for
such a real, which it writes in the fewest digits that hold its float32 value. The other constants are written as typed:
- `fill(0ffh,...)`, `fill(005,...)`;
- `DS1==+5`, `DS1==005`, `DF1==1.50`;
- timer `preset=0050`, Search `005`.

Modbus hex addresses are already canonical.

Open: does a clipboard copy-back of a dialog-made Copy carry tag 0x1201 as "0"? The clipboard form natively
writes "0" (tumbler), and the SCR form keeps it empty or leaves it out; a pasted block Copy was saved without
it. The encoder writes "0" in every Copy-family blob; no change until CLICK answers.

**Question for CLICK:** what does each other dialog turn `005`, `+5`, `0ffh`, `0FFH`, `1.50` and `1.5E+3` into?
Ask in Fill, Compare, Search, Timer and Counter presets, OutVariant presets, drum durations and the For count.
Then one behaviour-change branch per answer set, as for Math and Copy.

**Questions for CLICK on Math and Copy** (until answered, the code keeps the behaviour named):
- **Reals in exponent form.** Typed `1e6`, `9999999`, `1e7` to `1e9`, `1.5e10`, `1e-5` and `1.0E-10` in a Math
  and a Copy: is the switch to exponent form between 1E6 and 1E7 (the code's 1E+07), and does CLICK write
  `1E+07`, `1.0E+07` or `1E7`? The code writes a real positionally below 1E+07 and from 1E-04 up, and keeps any
  other as typed, but for a Copy real typed in exponent form that 7 digits don't print exactly (below).
- **More than 7 significant digits.** A Copy stores `3.4028235E+38` as `3.402823E+38`, so the code writes a Copy
  real typed in exponent form in 7 digits where they don't print it exactly; `constant_text()` keeps the digits
  that hold the value, which a Math keeps and a Copy rounds. Open: typed `1234567.89`, `0.123456789` and `0.30000001` in a Math and a Copy,
  and an exponent-form real with more than 7 digits in a Math. The code keeps the first two as typed (7 digits
  are another float32 value), writes the third `0.3` (the same float32 value), and keeps the last as typed.
- **A typed `+` on a real with digits CLICK drops:** typed `+2.50` in a Math. The code writes `+2.5`. A Copy drops
  a real's `+` (`+1.5` is `1.5`), and the code writes `2.5` there.
- **Integer `-00` in a Copy:** CLICK stores `-0` as `0`; the code writes `-00` as `0` too, not answered.
- **`$0d` as a Copy source:** stored `$0d` or `$0D`? The code keeps the case typed, as for `$0d` everywhere.
- **Other hex Copy sources with `E`:** `0EH`, `01EH`, `E0H`, `EEH`, `1E3H` in a Copy: hex or real? CLICK stores
  `EH` as `0.0` and `1Eh` as `1.0`, as if it read any text with an `E` as a real, so these may be reals too. The
  code refuses only `EH` and `1EH`, and reads the rest as hex; the refusal names the real and the hex value as a
  decimal integer, not a hex spelling, since none with an `E` is known to be read as hex.
- **Typed `1E3h` in a hex Math:** does the dialog take it, as CLICK stores `1e3` that way? The code takes it, so
  that a stored `1E3h` decodes and reads back.
- **`MAX ( DS1 , DS2 )`:** which id does the dialog give? The code refuses it with no id.

**Answered by the full Copy and Math grids**, where CLICK stores another form than the code writes now (each
case is in the `copy_single` and `math_decimal` answers; the code is unchanged until a branch takes them):
- A decimal Math `1E5` is stored `100000`, and `1.5E+3` and `1.5E3` are stored `1500` (alone and as `DS1 + ...`);
  the code writes `100000.0` and `1500.0`. A lowercase `1e5` in a decimal Math, alone and as `DS1 + 1e5`,
  is stored `100000.0`, as the code writes. A Copy stores both `1E5` and `1e5` as `100000.0`, as the code
  writes.
- Quoted text with an E into TXT is stored as its float value, a follow-up this item owns (the ratchet
  lists it): a Copy `"HELLO"` into TXT1 saves the source `0.0`, ends in TXT3 and has conversion type 3,
  which decode reads as `raw(...)`; into `TXT[DS1]` it is stored `0.0`. The rules accept it as text.
- As the code writes: `1E-45` and `1E-50` are kept as typed in a Copy (and `1E-45` in a Math); `1.5e-3` is
  `0.0015`; `1.` is `1.0`; `1.50` is `1.5`.

## Open CLICK questions (CLICK)

Each is a dialog check or a capture. Until answered, the code keeps the behaviour named.

- **Receive into Y101 or later from a CLICK C, T, CT or SC address.** The count room there may be 0 (every count
  refused). The code uses the slot run (Y101 from T1 gives 16) and, for C, the C room. Check Y101 from C1 with
  17 and with 102 elements, and Y101 from T1 with 1 element.
- **Which X point is the 17th element from X001** in a Send or Receive. CLICK stores only the start and the
  count, so this needs a PLC.
- **Compare with text in Data A:** the dialog offers = and !=. Which of the two does it save?
- **Coil range over SC:** does Compile refuse an SC range with read-only bits between its ends?
- **Math result into SD9, YD1 and YD0u:** paste each, copy back, and see what is stored. (Whether the dialog
  accepts them is item 3's grids; this is what a paste stores.)
- **Math X/Y range members:** the refusal is one rule, not the fitted member list: an X or Y range with an end
  in 021-036 is refused, except one from the CPU slot to 021, one of one point, and one of two points numbered
  one apart (X025 : X026; X036 : X101 is refused).
  The fitted list (`_xy_bound`) now only writes the reserved slots. Open: a span of more than two expansion slots,
  a Y range that starts in the option slot, and the lists CLICK stores on a CPU with I/O modules, where the rule
  may refuse ranges CLICK stores right or accept ones it stores wrong.
- **Real constants:** a Copy source takes `3.4028235E+38` and refuses `3.4028236E+38` (OBJ-005); a decimal
  Math refuses both (OBJ-1009), the first a follow-up in item 3. Where exactly is a Math's edge? Compare
  accepts `3.5E+38`.
- **Fill with hex above FFFFh:** does the Fill dialog take such a constant, and into which banks? A single
  Copy puts it into DD or CTD only; the code's Fill takes it into any numeric or TXT range.
- **Remote address `h`:** the Send and Receive dialogs let `h` and `1HH` through their span check. What do they
  store? The code refuses both.
- **Number constant into TXT:** a single Copy of a number whose text fills more than one TXT saves the
  constant as typed, the TXT its text ends in and a conversion type (`-5` ends in TXT2, `1.5` and `FFh` in
  TXT3, `2147483647` in TXT10); decode reads that save as `raw(...)` (item 3). `5` into TXT1 reads back.
  What does a Fill store? The code accepts it.
- **Text outside printable ASCII:** do the Copy and Fill dialogs take quoted text with a character outside
  space to `~` (an accented letter, a control character)? The code refuses it.
- **Quoted text with an `E`:** the Copy dialog reads such text as a number: `"HELLO"`, `"E"`, `"e"` and
  `"1E5"` into DS1 are stored 0.0 (refused on purpose, Settled), and `"HELLO"` into TXT1 is stored 0.0 too,
  filling TXT1..TXT3 (item 4). Does Fill do the same, and what does CLICK keep when such a Copy is pasted? The
  code accepts and encodes the text as typed into TXT.
- **Captures for motion and Email:** native Home, Velocity and Position, one per mode, and an Email with To,
  Cc, Bcc, Subject and both body modes filled, each field a distinct value. Their field maps are inferred and
  stay `raw(...)`.
- **ASCII Send and Receive** (static, dynamic, fixed, variable) and Home, Velocity, Position and Email with every
  status field set to a distinct address: native blobs to model later.
- **Other non-pinned boxes in a compact OR layout:** `read_csv` lays them out as it does stacked 2-row Copies,
  which CLICK's post-check layout confirmed. Capture one more shape (Math, Search or a timer under an OR).

## For pyrung's export (later; another repo first)

From the ecosystem plan's item 2; each waits until pyrung's export reaches it, after items 1-3.

- An entry that takes a series-parallel tree and returns rows. The private `_layout.render.render` does this,
  but takes a `Network` beside the `RungTree`.
- The rows in memory, with the number of CLICK rungs each source rung became (`write_csv` only writes a file).
- A writer for `main.csv` plus `subroutines/`, and a reader that builds their rungs: `csv/bundle.py` only
  parses them, so a refusal in a subroutine file reaches no one yet.
- A check on a whole program, approved by Sam 2026-11-16, moving from pyrung: for-loop nesting depth, a One Shot
  or a Return inside a loop, nested calls, the 8,000-step limit, and pyrung's estimate of program steps (its
  `click/ladder/steps.py`). It comes after pyrung's export goes through laddercodec, since only then does pyrung
  hold a laddercodec program to pass in. See the Syntax Check rules item in Later.

## Waits on another repo

- **`docs/guides/csv-format.md`:** delete the pyrung-specific sections after pyrung has its copy.

**For pyrung** (one line each; unchecked against pyrung's current source):
- Send/Receive: `device_id` accepts 248-255 on RTU and 0 on Receive RTU; no `com_port` for CPU Port 3 or WLAN; a
  slave ID given as a DS address is not in the DSL, exporter, codegen or backends.
- `raw()` stays a no-op, and its status tags (once laddercodec exposes them) count as written outside the
  ladder.
- `to_text(exponential=True)` from an integer source: refuse it or drop it.
- The translator writes a pointer with an offset (`DS[DS1+5]`) for a mapped block; CLICK refuses it.
- `COMPARE_COMPATIBILITY` is never called.
- `coil_target` allows X, T and CT; on/off-delay constants have no floor; drum presets have no 32767 cap; counter
  presets have no range.
- `search()` accepts a DINT result; CLICK needs DS.
- The shift register has no C-bank role.
- Math: the destination table has no hex/decimal split; text constants and hex constants in a decimal Math are
  not refused.
- Block Copy's bank table disagrees with CLICK's rules.
- `fill("AB", txt[1:5])` builds, and only the simulator objects; it also takes codes 128-255, which CLICK's
  dialog does not.
- An End inside a subroutine is not flagged.
- A slave ID out of range at run time: pyrung assumes an error bit and no send. Only a PLC shows what happens.

## Stable public API (nothing; ClickNick follows)

- **Approved by Sam.**
  - `laddercodec.__all__`, plus the names ClickNick reaches past it for, moved to the top level:
    - `UnknownCondition` and `UnknownInstruction`;
    - `DecodeError`, `WriterError`, `ConvertError`;
    - `Email`, `Home`, `Position` and `Velocity`, which exist but aren't exported.
  - ClickNick also imports `laddercodec.model.Program`, `encode.AfToken`/`ConditionToken`,
    `csv.contract.CONDITION_COLUMNS` and `csv.writer.decoded_rung_to_rows`. Either these move to the top level
    or ClickNick stops using them.
  - Everything else is internal. A test pins `__all__`. Message text is not part of the API.
  - This fits the plan's "named imports" direction.

## Settled (don't reopen)

- **Hex Math constants:** keep refusing `DH1 + 7` and `DH1 + 7H7`; never rewrite them as CLICK's dialog does
  (`7h`, `77h`). The error names the fix.
- **Canonical constants (Sam, 2026-11-16):** the encoder writes the form CLICK's dialog stores wherever its
  correction keeps the meaning, a typed `+` and a hex Copy source's leading zeros included; where it would change
  what the CSV says (hex Math digits without `h`, a Copy `EH` or `1Eh`), the text is refused and the message names
  the fix.
- **Hex Math words without `h` (Sam):** CLICK reads a word of hex digits typed without `h` as a hex constant:
  `abc`, `5`, `-5`, `005`, `C0`, `DD0`, `DF0`, `1E5`, `1-2`, `RAND(5,Ah)`, and `DH0` as `D0h`. laddercodec
  keeps refusing them: a CSV says what it means, and `DH0` meaning `D0h`, or `10` meaning 16, is what to
  refuse. `DISAGREEMENTS` keeps them as kept differences.
- **Copy into DS of text that isn't a number (Sam):** CLICK takes `1E`, `E5`, `"HELLO"`, `"E"`, `"e"` and
  `"1E5"` as a Copy source into DS1 and stores the real it parses them to (0.0, or 1.0 for `1E`).
  laddercodec keeps refusing these six: DS is an integer, so a real such as 0.0 or 1.0 is no source for a
  Copy into DS1, and typing a valid constant can't make that rung, since 0.0 into DS becomes 0.
  `DISAGREEMENTS` keeps them as kept differences.
- **`feat/productivity-codec`** stays as a branch for now.
- **A last rung of only wires in an SCR save:** it can't be told from CLICK's own trailing empty rungs (both are
  records with no instruction and no comment, byte-identical; CLICK keeps 1 to 4 trailing empties), so
  `decode_program` drops it. Nothing to do unless CLICK's save differs somewhere not yet seen.

## Later (nothing unless marked)

- **Parity test** for the private bank copy, with pyclickplc (0.6.0 or later, which has the `parse_address`
  change) as a dev-only dependency. It must convert units: XD here is 0-8 plus `u`, in pyclickplc 0-16 Modbus
  units. Don't compare `WRITABLE_SC`: pyclickplc's means writable in Data View, a different fact from the
  ladder-writable list here.

- **Email, Home, Position and Velocity readers:** each has a `from_csv_token` that no CSV token reaches, since
  their registry SPECs have no CSV names. Check whether these readers are dead code, and delete them or wire them.
- **Search's refusal message** says "is a integer value". Fix the article.
- **Hex message without an OBJ id (CLICK):** the refusal for a padded 32-bit constant ("a hex constant above
  FFFFh has at most 8 digits") carries no OBJ id. Find the id CLICK shows, if any.
- **Kind-mismatch refusal for junk input:** "<field> takes a decimal integer", for a blank or a stray character,
  states the rule but not what was wrong with the input.
- **Operand probe recheck:** recheck, against the operand probe, every operand field it finds surprising, and fix
  or delete.
- **Comment styling characters (Sam):** comment text with a literal `_x_` pair (or other styling characters)
  comes back as `*x*`, because neither the comment writer nor the reader escapes styling characters; decide on
  an escape such as `\*` and `\_`.
- **Copy termination encoding:** the `to_text_term` variant greys out the termination value in the UI, yet the
  blob stores it; the encoding may need revisiting.
- **SCR blob dataclass** (Sam's idea):
  - One frozen dataclass per instruction class: its ordered tags, defaults, array sizes and func code.
  - SCR decode lays the sparse tags it stores over that dataclass to build the full blob. An unknown class
    fails loudly.
  - Proof: the native SCR and clipboard pairs (793 AF blobs, 755 conditions). Today 120 of the 793 differ.
- **Output-column down wire:**
  - Decode would keep the flag and lift the refusal (the layout work left it out). Sam punted it: no one draws one.
  - Until it lands, such a rung becomes an undecoded marker.
- `layout_check._blank_rows` counts a first row holding only an unpowered NOP as content, so C0202 row numbers
  can be off by one.
- **Clipboard row count too low:** when the program header counts fewer rows than the grid holds, the clipboard
  walk stops at the header's count and the last rung loses its later rows, with no marker (`_walk_grid`'s bound
  and `_decode_single`'s slice).
- **Arguments on a pin that takes none:** `.reset(DS9)` reads as `.reset()`, and the argument is silently
  ignored. Under CSV-as-intent the reader should refuse it.
- **Captures (CLICK):**
  - an unpowered real box (coil, timer);
  - a reset wired from the rail;
  - shared pins;
  - C000A through a branch (an output behind a contact of its own above a pinned box on one net);
  - a box on the net of a reset with no contact of its own (`instr-copy-multirow-2af-T`): C000A alone, as
    `check()` reports with `captured=False`, C0212 too, or accepted;
  - a bridge whose timer reset tees off its own main input: C0001 alone, as `check()` reports, or C0205 too;
  - a `NOP`, or a box with a used pin, above a pinned box on its main input's net: C000A, as for an output;
  - a pin's net shared with another pin, or with a main input above the pin: C000A, as `check()` reports;
  - an unwired shift clock, drum jog or counter down: C0202, as for a reset;
  - a pin row of wires that no rail or contact reaches: C0202 at AF, as for an empty row, or elsewhere;
  - two groups of boxes that share nets in one rung: one C000A line or two;
  - C0206-C0214.
- **`read_csv` and CLICK's check rewrites (Sam):** CLICK's check drops a `NOP` on a row of its own beside a
  coil's rung (`C1 -> out(Y1)`, `- -> NOP`; one row left), and wires a rung of only wires through AF, which
  decodes as wires into a `NOP` (`tests/test_check_shapes.py`, rungs 13 and 14). `read_csv` keeps both as
  drawn. Should it give the post-check form? Dropping that `NOP` is like the unpowered `NOP` it drops already;
  a `NOP` in a rung of wires is a token the CSV does not hold.
- The Home `11f5` flag doesn't round-trip.
- RawInstruction's hex fallback breaks when the hex holds `,` or `)`.
- A guard that a REFUSED entry has gone stale.
- A Hypothesis property test.
- **Home, Velocity, Position and Email status bits:** read-only `outputs` with busy, complete, success,
  error and error code (Email: sending, success, error, error code). The `raw(...)` token stays as it is.
- **Syntax Check rules `check()` doesn't report.** It reports C0001, C0003, C000A, C0202, C0205 and C0212. Not
  reported: For/Next nesting, pairing, One Shot and Return/End inside a loop; Next alone on its rung
  (C0009); a timer inside For/Next (C1004); Break/Continue without a contact or outside a loop; a subroutine without an unconditional Return and Main without an unconditional End; the other
  timer, counter, shift and drum input-contact rules; duplicate Timer or Counter addresses and Out or Drum on a
  used timer address; an unused timer or counter bit; a Math function not followed by an operator; a motion
  instruction naming an axis that does not exist. Decide which are worth a Finding.
- **SCR decode of a Math whose range is refused** keeps only 6 of Math's 5510 fields. The SCR blob dataclass above
  fixes it.
- **ASCII Send and Receive** are not modelled (they stay `raw`).
- **Send/Receive padding slots:** CLICK writes the slot index; the encoder writes another form. Changing it
  changes all 19 Send/Receive goldens and needs paste checks. Check against the current encoder before
  starting.
