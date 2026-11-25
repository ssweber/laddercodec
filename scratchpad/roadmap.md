# laddercodec roadmap

This file is the only statement of what laddercodec still has to do. Work that crosses repos is written once,
in the ecosystem plan (`ssweber.github.io/plan/README.md`). Items here link to it and don't repeat it. When an
item lands, delete it.

Each item says what it needs. **nothing** means code only. **CLICK** means the CLICK software, through the
sandbox runner or Sam. **PLC** means a real PLC. **Sam** means his judgment. **another repo** means a change
in a sibling repo. Work that needs nothing is never queued behind work that needs Sam.


Written 2026-11-15, after 0.4.0, from the post-release plan and Sam's rulings on it. Updated 2026-11-25.

## How work runs here

- **Branches.** Feature and refactor branches go into an always-releasable `main`, only through PRs. There is no
  `dev` trunk. A session pushes its branch and opens the PR. It squash-merges the PR once CI is green on the
  head commit and a fresh reviewer has passed that commit. A PR that needs Sam, CLICK or a PLC (a golden paste
  check, say) waits for that. Every PR carries its CHANGELOG line, so `main` can be released at any commit.
- **Releases are Sam's.** Nobody tags, releases or publishes without him. Publishing a GitHub release sends the
  package to PyPI. Unless it is a pre-release, `publish.yml` then starts a docs deploy of that tag. You can
  redeploy by hand with `gh workflow run docs.yml --ref main` (the latest release, or `-f ref=<tag>`). That is
  a deploy, so it is Sam's call too.
- **Builds.** Multi-branch jobs run as BOB arcs. Each branch gets a worktree and a builder, a fresh reviewer
  checks it, and CI is the gate. BOB comes from the shared `bob` plugin (`ssweber/bob`). This repo's settings
  are in `.claude/bob/`.
- **Arc folders stay out of git** (`../laddercodec-wt/buildbot/jobs/`). When an arc closes, move its open items
  here. Then the folder can go.
- **No provenance.** Code, tests and user docs say what a rule is, never where it came from. CLICK's own error
  ids in messages, such as "(OBJ-023)", stay, because CLICK shows them to the user. Write what is still in
  doubt here as a question.
- **Less code first.** Deletion and consolidation come before new features. Line count is not a target. Do
  what is prudent.
- **Scope.** laddercodec refuses what CLICK's editor refuses. It also refuses what breaks the encoding or
  crashes CLICK on a paste. A rule that rests on what a PLC does stays in pyrung.

## Next steps

**Before the tag.** Nothing waits on Sam except the tag itself.
1. The laddercodec session merges the CHANGELOG and this roadmap, and hands Sam the release notes.
2. Sam tags 0.5.1. ClickNick 0.26.1 pins it, together with pyclickplc 0.11.3 and pyrung's next release.

**After 0.5.1, in this order.** Sam decided on 2026-11-25 that laddercodec builds what pyrung's export
needs first, so that laddercodec does not hold up the export. That work is done. The steps below are what
is left.
1. The whole-program check, which moves from pyrung once pyrung's export goes through laddercodec (see For
   pyrung's export).
2. The message wording that was deferred: the refusal's example from the partner field, the Math mode advice
   and `quantity=N` in Send and Receive messages (see Later). Then the other follow-ups in item 1 and in
   Later.

**Alongside these steps, and not steps of their own:**
- pyrung's reports from adopting the API.
- The field rules (item 2), tightened to each grid as ClickNick's runner returns it.

**After 0.5.1 (Sam).** Whether `read_csv` returns a rung of wires alone as drawn, or with CLICK's
`NOP` (see Later).

## 1. The field error's follow-ups (nothing, except where marked Sam)

pyrung learns what a field takes by building the object and reading the error. That is on `main`. A
rule-description API (`field_rules(Copy)["source"]`) is not built.

- **A strict numeric tag.** `tag_int` reads a tag through `int()`. It accepts `" 1"`, `"+1"`, `"1_0"` and
  non-ASCII digits, as it did before. If it read only ASCII digits, those blobs would stay raw.

- **The blanks a CSV token still reads as syntax.** A blank argument of an AF token reads as its field
  `missing`. That covers a blank `unit=`, Math `mode=`, drum list, Modbus `target=` and search expression. An
  absent keyword stays a `CsvReadError` (ruled). So does a Math `mode=` that is neither `decimal` nor `hex`
  (ruled). These blanks are still a syntax error with no field:
  - A token with blanks of two forms, a range and a single field (`pack_bits(,)`, `unpack_to_bits(,)`), because
    every blank in a token is tried in the same form (ruled).
  - A blank argument that the token has no field for (`toggle(C1,on_acc=)`).
  - A blank in a condition token. Condition tokens are not read for blanks, so `rise()`, `DS1==` and `~` are
    syntax errors.

  The coil parser drops a blank argument. It accepts `out(C1,)`. It reads `out(,oneshot=)` with `oneshot=` as
  the operand, which is an `address` refusal.
- **One parser per token.** Each family's `from_csv_token` parses with its own regex. Twice, one has disagreed
  with `read_csv` (`Copy.from_csv_token` refuses quoted `"A,B"`, `"A=B"`, `"(A"` and `"A\nB"`, and it raises
  for `copy("A",B",TXT1)`, which `read_csv` reads). Route every `from_csv_token` through
  `parse_af_token` and `parse_af_call`, and the condition tokens through their equivalent, so that one parser
  reads each token.
- **Token-syntax class split.** Some token-syntax errors are a `CsvReadError` and others are a `FieldError`
  with no field. Pick one class for a token that is not syntax.
- **Rung names.** A refusal that `encode()` raises does not name the rung it came from.
- **Falsy Send and Receive status fields.** A Send or Receive accepts a status field (`sending`, `receiving`,
  `success`, `error`, `exception_response`) that is falsy, such as `0`, `None` or `[]`, without a refusal. It
  checks the field only when the value is true. Choose whether a falsy value that is not `""` is refused as
  the wrong type.
- **Large raw array counts.** A `raw(...)` field spec with an array count, such as `2237[100000000]=0`, builds
  one field per entry, so a large count builds 10^8 tuples and can hang. Choose a limit for the count.
- **Three pointer readers.** `split_pointer` (`operands/address.py`), `_LOOSE_POINTER_RE` in
  `normalize_address` and the partition in `check_box_operand` (`copy.py`) each read a pointer. They disagree
  on a line break in the index, on nested brackets and on lower case. A Pack destination `DS[DS1\n]` is
  refused as `pointer-outside-copy` today, and `split_pointer` would make it `not-an-address`. Making them one
  reader is a rule change.
- **Drum wording.** A time-event drum with events only is refused as `Drum.presets: 0 steps`. The guide does
  not say that a time drum's blank `accumulator=` is a `FieldError`.

## 2. Field rules tightened to the CLICK grids (CLICK)

The runner tries whole grids, not samples: every bank and constant kind in each dialog field. Its answers are
committed as test data. That makes these tests the one place where CLICK's field rules are recorded. No rule is
written from the 17 sampled rows in `ssweber.github.io/plan/rule-decisions.md`.

- **Grids (Sam, 2026-11-16):** laddercodec writes the case lists, because it knows how each field is modelled
  (banks, constant kinds, modes). They take the shape of ClickNick's `devtools/editor_cases.json`. click's
  runner runs them and returns the answers. `make editor-grids` writes the cases to
  `tests/fixtures/editor_grids/`, with laddercodec's verdict beside each. The runner has answered every grid
  there. Some answers are in another grid's file. The `preflight_<dialog>` cases are in the answers of the
  full grid for that dialog, such as `counter.answers.json`. The `receive_click_count1` cases are in
  `receive_click.answers.json`, and the `drum_events_padded2` cases are in `drum_events_padded.answers.json`.
  The next grids are the ones that laddercodec writes for the open questions in this item.
  `tests/test_editor_answers.py` compares the answers with the rules and lists each difference in
  `DISAGREEMENTS`, grouped by what is to be done. A new grid is new work for the runner. Tighten a field's rule
  when its answers arrive.
- **CLICK's saves of 25 Fill, Math and Copy cases (nothing).** ClickNick's runner has recorded CLICK v4.00's
  saves of 25 cases, which ClickNick's runner results call J4. CLICK accepted all 25. Commit the cases and
  the saves under `tests/fixtures/editor_grids/`, with no local paths, and add them to
  `tests/test_editor_answers.py`. Fix the one Fill save that differs from what laddercodec writes.
  `fill(1234567.8,TXT1..TXT2)` is saved as `1234568.0`, and laddercodec writes `1234567.8`. Refuse it and
  name the saved text, as a single Copy does. One Math save differs too. It is a CLICK question in "Math
  real stored type", and it is not part of this item.

  Then update the items that the saves settle: "Fill text and a bare number", "Reals in exponent form in a
  Math", "A typed + on a real", "Math real form", "A pointer on both sides of a single Copy" and "Pointer on
  both sides of a Copy". CLICK saves Copy type 7 for every plain case, the four in "A pointer on both sides
  of a single Copy" among them. It saves type 8 with 0x2206 `1` for Copy Binary. laddercodec writes the
  same, except that it writes 0x2206 `0` in a plain copy, which CLICK leaves out. Decode reads both forms.
  The saves also answer the open Fill question in "Quoted text with an E". CLICK saves
  `fill("HELLO",TXT1..TXT2)` as `0.0`.
- **Open order of checks in a Math range (CLICK).** The rules check every range's banks and order before any
  address's bank, then a median's size and the X/Y option-slot ends. No answer covers these cases:
  - A reversed or two-bank `MAX`, `MIN`, `MDN` or `AVG` range over a refused bank (`MAX ( DH2 : DH1 )` in
    decimal). The rules report OBJ-1014 or OBJ-1015 first, as for a `SUM`.
  - A formula with a refused address beside a refused range (`DH1 + SUM ( DS5 : DS2 )` in decimal). The rules
    report the range's OBJ-1014 first, whatever stands before it.
  - A median over a refused bank that is also past 1024 bytes. The rules report OBJ-1002 before OBJ-1013.
- **Copy-family ids that no answer covers (CLICK).** A bank that no row of a field lists gets an id by the rules
  that the answers fit. These cases have no answer:
  - Single Copy, XD as the destination: CLICK answers OBJ-004 from a DS, TXT1 or 5, and OBJ-024 from a bit or
    `"A"`. The rules report no id there yet.
  - A bit source into an X, T, CT or SC address outside its bank (`C1 -> X017`). The rules report OBJ-004.
  - A single Copy whose destination is a bit bank address and whose source is a refused constant. Does CLICK
    report `99999999999`, `1e99`, `FFFFFFFFFh`, `"é"` or text of 200 characters into X001 for the constant or
    for the destination, and with which id? The rules refuse the destination's bank first, with no id, and
    refuse the constant after it.
  - DS2 or 5 into `X[DS1]`, `Y[DS1]`, `T[DS1]`, `CT[DS1]` or `SC[DS1]` (CLICK reports OBJ-005), and into
    `XD[DS1]` or `SD[DS1]` (OBJ-004). The rules refuse each as a pointer with no id. CLICK reports OBJ-005 for
    `-$41` into DS1. The rules refuse it as no address, with no id.
  - SD43 as the destination of a bit, quoted text or `10000h`. It is not answered.
  - The shared constant check, which Math and Fill use too, gives no id to an empty text, a signed hex constant,
    or a hex constant of more than 8 digits. The single Copy reports these as OBJ-005, as CLICK does.
- **The writable-SD list (CLICK).** The picker's list of 29 writable SD (`WRITABLE_SD`) answers a single Copy, a
  Block Copy and a decimal Math result, and the 25 writable SC answer Out. A Block Copy from `DS1..DS2` gets
  OBJ-018 ("read only addresses between") from CLICK into SD42 and SD147, and OBJ-004 into SD215. The rule
  fitted to these three answers is OBJ-018 for an unlisted SD before SD215, OBJ-004 for one past it, no id for
  a range with both, and no id for an unlisted start. Open questions:
  - the last nine `copy.block.destination.banks` cases: a writable start whose range reaches read-only SD,
    controls inside the list, and a read-only start that ends writable;
  - a Block Copy whose start is not listed;
  - an unlisted SD below SD29 in each field.
- **Hex Math words shaped like an address (nothing).** The rules refuse a word such as `C0`, `DD0`, `DF0`, `DH0`
  or `DH501` (alone, beside `+ 1h` or as a RAND bound) as outside its bank's range. The message is to name the
  `h` form (`C0h`, `D0h`), as the message for `5` or `abc` does. This is one group in `DISAGREEMENTS`. Fix the
  rule, then drop the group's entries.
- **RAND bounds (CLICK).** Open:
  - Are bounds equal by their text or by their value? The rules use the narrowest reading, the same text in
    display form. So they refuse `RAND(1h,01h)` and `RAND(DS1,ds1)`, and accept `RAND(1,+1)`. They refuse
    `RAND(1,01)` anyway (leading zeros, OBJ-1009) and `RAND(DS1,DS 1)` by its shape.
  - Which id comes first where one RAND has two refusals: `RAND(DF1,DF1)`, `RAND(DF1,1.5)`? The rules report
    the real bound and equal bounds (OBJ-1001) before a bound's bank (OBJ-1002).
  - A hex `RAND(-5,Ah)` is OBJ-1001. The rules refuse `-5` with no id for its missing `h` (Settled), and then
    report OBJ-1001 for the shape.
  - Do the shift and rotate arguments (`LSH ( XD0 , 1h )`) accept XD and YD, as the rules do? No answer covers
    them.
- **Pack and Unpack neighbours that no answer covers (CLICK).**
  - A Pack of text into DS, DD, DF, TD or CTD. CLICK's own code reads limits of 6 characters for DS and TD, 11
    for DD and CTD, and 14 for DF (OBJ-003). The rules accept any length there. Into DH, the rules refuse 5 to
    15 characters (`TXT1..TXT5`), as CLICK's code does. Ask CLICK next for `TXT1..TXT4` and `TXT1..TXT5` into
    DH1, the edge of the limit.
  - A count where the pairing is refused and no answer shows it: `DH1..DH3` into DS1, DF1, TD1 or CTD1,
    `C1..C33` into TD1 or CTD1, and 33 or more T, CT or SC bits into DF1, TD1 or CTD1 (answered only into DS
    and DD). The rules report the count first (OBJ-040, OBJ-041).
  - A DH into a Y range across two slots with 16 points or fewer (`Y016..Y021`), and a DH into the option slot
    alone (`Y021..Y036`). The rules report OBJ-1009 for the first and accept the second.
- **Addresses saved as typed (CLICK).** CLICK saves some fields as typed (`DS001`, `ds1`, `YD0U`). Decode reads
  them in display form, and writes the saved blob back while the instruction is unchanged. Not answered:
  - a typed form in those fields that no answer shows, read in display form by the code's own rule. Examples
    are a DH as a hex Math result (`dh1`, `DH01`), an X or Y number with extra zeros (`X0001`), a lowercase bit
    (`y021`), a word register with a leading zero (`XD01`, `ctd01`, `txt01`), a pointer of another bank
    (`SD[sd1]`), a Pack destination with leading zeros (`dd001`) and a lowercase X or T in a `SUM`;
  - these stay raw: an X or Y number typed short (`Y1` as a Copy destination, `X1` in a Math `SUM`), a typed
    Fill destination, a typed Unpack destination that CLICK accepts (it refused every answered one), and what a
    clipboard copy of a typed Math holds in its operand slots.
- **A set flag in a program file (CLICK).** A decoded program box writes each flag as CLICK's clipboard does
  (`-1` or `1` when set, `0` when clear). CLICK reads an empty flag on the clipboard as clear, so an entry that
  no family reads writes a set flag as `1`, or `-1` in a Copy, Drum, Math or Search. For a class that no
  capture shows, `1` is a guess. Does CLICK read `1` and `-1` alike for every class?
- **A pointer on both sides of a single Copy (CLICK).** The encoder writes type 7 for `DF1` into `DD[DS1]`,
  `DD1` into `DF[DS1]`, `DF[DS1]` into `CTD1` and `CTD1` into `DF[DS1]` as a plain copy. CLICK has not answered
  for these. It saves type 7 for `DF[DS1]` into DD1, for `DD[DS1]` and `CTD[DS1]` into DF1, and for DF1 into
  `CTD[DS1]`.
- **Ids left None until CLICK answers.** `click_id` is set only where the code records the field's dialog. An id
  that can't be backed stays None. Open:
  - Fill: its pairing (Copy's OBJ-024) and a range in two banks. Open:
    - A Fill into SD from a writable start SD that does not end above it, such as `SD31..SD31` or
      `SD32..SD31`, has no answer and no id.
    - CLICK answers OBJ-008 for a range in two banks (`DS1..TXT1`) and for an end in a bank that Fill refuses
      (`DS1..C1`). It answers OBJ-004 when the range starts in SD and OBJ-024 when it starts in TXT. The rules
      give a range in two banks no id.
  - Fill into TXT of a number of more than one character: a `+`, a leading zero, `-0` and a one-digit hex
    constant have no answer, and get no id. Quoted text of several characters is answered OBJ-023 and has no
    id.
  - A Receive into TXT that starts at an even address. A Send refuses such a start with OBJ-028. No answer
    covers Receive, so the rules accept it.
  - Block Copy, a source range spanning two X/Y modules. CLICK's answer for Pack is OBJ-033 (set). No recorded
    answer covers Block Copy's, so it stays None. What OBJ-035 is for is still unknown.
  - Receive, one C bit for two status fields (Send's is OBJ-014).
  - A Modbus remote address in hex past FFFEh, which is refused while the address is read. A hex start past
    FFFDh in a Send has OBJ-010.
  - Whether OBJ-010 is also CLICK's id for a Send or Receive that runs past C2000, and for the room left in a
    DD hex start.
  - The Out variant's bank and not-writable SC refusals.
  - A blank field's refusal carries no id yet. CLICK's recorded answers give OBJ-001 for a blank address,
    OBJ-006 for a blank Copy source and OBJ-1001 for a blank Math formula. Each field needs its own answer
    before it carries one.
  - OBJ-002 and OBJ-003: which dialogs report them for an address that is not one, and for a number outside its
    bank.
  - Out, Set and Reset, where the rules now report OBJ-008 before the end's own refusal and no answer covers
    it: an SC bit that a coil can't write (`C1..SC1`), an immediate range whose end is in another bank
    (`immediate(Y001..C2)`), and an end outside its bank in another bank (`C1..DS0`, where the rules report the
    end's bank refusal, OBJ-004). `Y001..X[DS1]` is OBJ-005, and the rules give it no id.
- **A unit on an instruction that has none (nothing).** An event drum and a toggle accept a falsy `unit` other
  than `""`, such as `None` or `0`. Both should refuse it with `OPTION_NOT_OFFERED`. The annotations
  `TimeUnit | Literal[""]` on `Drum.unit` and `OutVariantUnit | Literal[""]` on `OutVariant.unit` state that
  contract.

## 3. Canonical constants (CLICK)

Addresses are written canonical everywhere, and tested. Math and a single Copy source are written as CLICK
stores them. A Math real that CLICK would save as another value is refused, and the refusal names CLICK's form
(Settled).

Follow-ups (nothing):
- `constant_text()` can return a form that a Math or a Copy refuses (`0.33333334`). A public helper would
  return CLICK's form for a value.

**Open (CLICK v3.92):** CLICK v4's dialog sets tag 0x1201 of a Copy in every single Copy and Block Copy. Its
clipboard copy holds -1. A clipboard copy from CLICK before v4 holds 0, or -1 with a termination code. The
encoder keeps the older form and writes 0, except -1 for a termination code and for a single Copy's text
constant source. Paste a single Copy from v4 that has a numeric source and no termination code, so that it holds
0x1201 = -1. Does v3.92 read it as it reads the same Copy with 0? If it does, the encoder could write -1 in
every single Copy and Block Copy. That would change 19 golden `.bin` files, and each would need a paste check
(CLICK). No capture shows a Fill, Pack or Unpack that v4's dialog saved.

**Question for CLICK:** what does each other dialog turn `005`, `+5`, `0ffh`, `0FFH`, `1.50` and `1.5E+3` into?
Ask in Fill, Compare, Search, Timer and Counter presets, OutVariant presets, drum durations and the For count.
Then make one behaviour-change branch per answer set, as for Math and Copy. Until CLICK answers, the code writes
these as typed:
- `fill(0ffh,...)`, `fill(005,...)`;
- `DS1==+5`, `DS1==005`, `DF1==1.50`;
- timer `preset=0050`, Search `005`.

Modbus hex addresses are already canonical.

**Questions for CLICK on Math and Copy** (until CLICK answers, the code keeps the behaviour named):
- **Reals in exponent form in a Math.** Typed `1e6`, `9999999`, `1e7` to `1e9`, `1.5e10`, `1e-5` and `1.0E-10`.
  A Copy follows CLICK's answers (7 significant digits, `1E+07`, `1E-05`, `1.5E-45` as typed). For a Math, does
  CLICK switch to exponent form between 1E6 and 1E7 (the code's 1E+07)? The code writes a real positionally
  below 1E+07 and from 1E-04 up. It keeps any other as typed.
- **A typed `+` on a real with digits CLICK drops:** typed `+2.50` in a Math. The code writes `+2.5`. A Copy
  drops a real's `+` (`+1.5` is `1.5`), and the code writes `2.5` there.
- **Integer `-00` in a Copy:** CLICK stores `-0` as `0`. The code writes `-00` as `0` too. CLICK has not
  answered for `-00`.
- **`$0d` as a Copy source:** does CLICK store `$0d` or `$0D`? The code keeps the case as typed, as for `$0d`
  everywhere.
- **Other hex Copy sources with `E`:** `0EH`, `01EH`, `E0H`, `EEH` and `1E3H` in a Copy. Are they hex or
  real? CLICK stores `EH` as `0.0` and `1Eh` as `1.0`, as if it read any text with an `E` as a real. So these
  may be reals too. The code refuses only `EH` and `1EH`, and reads the rest as hex. The refusal names the
  real, and names the hex value as a decimal integer, not a hex spelling, because no text with an `E` is
  known to be read as hex.
- **Typed `1E3h` in a hex Math:** does the dialog accept it, as CLICK stores `1e3` that way? The code accepts
  it, so that a stored `1E3h` decodes and reads back.
- **`MAX ( DS1 , DS2 )`:** which id does the dialog report? The code refuses it with no id.

**Answered by the full Copy and Math grids.** In these cases CLICK stores another form than the code writes
now. Each case is in the `copy_single` and `math_decimal` answers. The code is unchanged until a branch
adopts them.
- A decimal Math `1E5` is stored `100000`. `1.5E+3` and `1.5E3` are stored `1500` (alone and as `DS1 + ...`).
  The code writes `100000.0` and `1500.0`.
- A lowercase `1e5` in a decimal Math, alone and as `DS1 + 1e5`, is stored `100000.0`, as the code writes.
- A Copy stores both `1E5` and `1e5` as `100000.0`, as the code writes.
- As the code writes: `1E-45` and `1E-50` are kept as typed in a Copy (and `1E-45` in a Math). `1.5e-3` is
  `0.0015`. `1.` is `1.0`. `1.50` is `1.5`.

## Open CLICK questions (CLICK)

Each is a dialog check or a capture. Until CLICK answers, the code keeps the behaviour named.

- **Receive into Y101 or later from a CLICK C, T, CT or SC address.** The count room there may be 0, which
  would refuse every count. The code uses the slot run (Y101 from T1 allows 16) and, for C, the C room. Check
  Y101 from C1 with 17 and with 102 elements, and Y101 from T1 with 1 element.
- **Which X point is the 17th element from X001** in a Send or Receive. CLICK stores only the start and the
  count, so this needs a PLC.
- **Compare with text in Data A:** the dialog offers = and !=. Which of the two does it save?
- **A one-digit `$` code in Compare's Data A:** does the dialog accept `compare $1 == TXT1`, and how does it
  save it? Data B and a Search value keep `$1` as typed. The code still refuses it in Data A.
- **Text outside printable ASCII in Compare's Data A:** does the dialog accept `compare "é" == TXT1` and a tab,
  and are they saved as typed? Data B keeps them. The code still refuses them in Data A.
- **`DH` as a hex constant elsewhere:** CLICK saves Compare's Data B empty when you type `DH`, and the code
  refuses it there opposite a hex Data A. Does CLICK blank a `DH` constant in a Search value, Compare's Data A,
  a Copy, a Fill or a Math, or as the hex remote address of a Send or Receive? The code accepts it in each of
  them as the hex constant D. Does Compare's Data B accept `DH1 == 0DH` and `DH1 == dh`, and save them as
  typed? The code accepts `0DH` and refuses `dh`.
- **Search value pairs and Compare's real bound.** The group rule decides these, and no answer shows them:
  - a DS table with a DH or YD value;
  - a DH table with a DS or TXT value;
  - a TXT table with a DS or XD value;
  - a DD, DF, TD or CTD table with any value address.

  The code accepts a value in the table's group and refuses any other with OBJ-004. In Compare's Data A, does
  CLICK refuse a real outside float32 (`3.5E+38 == DF1`) with OBJ-005, as it does in Data B? The code does.
- **Coil range over SC:** does Compile refuse an SC range with read-only bits between its ends?
- **Math result into SD9, YD1 and YD0u:** paste each, copy back, and see what is stored. (The Field rules grids
  answer whether the dialog accepts them. This question is about what a paste stores.)
- **Math X/Y range members.** The refusal is one rule, not the fitted member list. The rule refuses an X or Y
  range with an end in 021-036, except one from the CPU slot to 021, one of one point, and one of two points
  numbered one apart (X025 : X026; X036 : X101 is refused). The fitted list (`_xy_bound`) now only writes the
  reserved slots. Open: a span of more than two expansion slots, a Y range that starts in the option slot, and
  the lists CLICK stores on a CPU with I/O modules. There the rule may refuse ranges that CLICK stores
  correctly, or accept ones that CLICK stores wrongly.
- **Math real form:** CLICK's Math saves a real in positional form for an exponent from -4 to 6, and in
  exponent form otherwise. Typed without an `E`, a real keeps 6 digits after the point (`0.00012345` is saved
  as `0.000123`, `12345678.9` as `1.234568E+07`). Typed with an `E`, it keeps 7 significant digits
  (`1.2345E-04` as `0.00012345`, `1.2345678E+15` as `1.234568E+15`). The rules refuse each real that CLICK
  saves as another value and name the saved text. Open:
  - A lowercase `e` with more digits than CLICK keeps (`1.2345e-04`, `1.2345678e15`). The rules refuse one
    that either form would change.
  - A short real is only normalized: `1e5` and `1.` are saved as `100000.0` and `1.0`, and `0.0015` as typed.
    Which typed forms CLICK cuts and which it only normalizes is not settled.
- **Math real stored type:** CLICK's Math dialog stores some reals as integers. The encoder writes them as
  reals:

  | typed | CLICK stores (0x6229) | laddercodec writes |
  |---|---|---|
  | `1E5` | `W100000` | `F100000.0` |
  | `1.5E+3`, `1.5E3` | `H1500` | `F1500.0` |
  | `1234567.0` | `W1234567` (shown `1234567`) | `F1234567.0` |
  | `1e6` (into DF1) | `W1000000` | `F1000000.0` |

  An integral real typed with an `E`, and `1234567.0`, are stored as integers (H in int16, else W). `1e5`
  (`F100000.0`) and `1.` (`F1.0`) are stored as laddercodec writes them. Every other real is stored as CLICK
  saves it (`3.0E+38` as `F3E+38`). Open: whether the integer type changes what the Math computes, and which
  other positional reals CLICK stores as integers.

  **A lowercase `e` (CLICK).** CLICK v4.00 stored `1e5` as the real `F100000.0` and `1e6` as the integer
  `W1000000`. Two saves do not give a rule, so laddercodec fits none yet. ClickNick's runner answers a grid of
  lowercase-`e` reals from about 1e5 to 1e7 first, such as `1e5`, `5e5`, `1e6`, `2.5e6` and `1e7`. The grid
  also holds `1.5e3`, because CLICK stores it as `H1500` when it is typed with an uppercase `E`.
  laddercodec writes that grid. The encoder changes after CLICK answers.
- **Send Word Swap after a change of function code.** With FC16 and Word Swap on, switch the Send to FC06.
  Does CLICK keep Word Swap stored, or clear it? A runner case types `send fc16 984 400001 <- DS1 x2
  word_swap=ON`, then picks FC06 and saves. The code refuses Word Swap with any code but FC16, so a stored
  FC06 Send with Word Swap decodes with a `RefusedFieldWarning`.
- **Remote address `h`:** the Send and Receive dialogs let `h` and `1HH` through their span check. What do
  they store? The code refuses both.
- **Number constant into TXT:** a single Copy of a number whose text fills more than one TXT saves the TXT
  where its text ends. CLICK refuses a Fill of such an integer or hex number, and the rules do too. What CLICK
  stores for a Fill of a real into TXT is not known.
- **Termination code with other options.** The code accepts a termination code on a single Copy of a constant
  into TXT with `suppress_zero=0`, such as `copy(5,TXT1,convert=to_text(suppress_zero=0,termination_code=$0D))`,
  and with `exponential=1`, such as `copy(1.5,TXT1,convert=to_text(exponential=1,termination_code=$0D))`.
  CLICK has saved neither. The ClickNick runner types both into the Copy dialog, and laddercodec compares
  CLICK's saves with the blobs that the encoder writes.
- **Fill text and a bare number.** For `fill(5,TXT1..TXT2)` with no option touched, what does the dialog
  default to and save? CLICK accepts `"é"` and a tab as a Fill into TXT; what a PLC writes for them is not
  known. The code accepts the bare number and refuses both characters. It also accepts a real with more than 7
  significant digits as typed (`fill(1234567.8,DF1..DF2)`), where a Copy refuses it.
- **Quoted text with an `E`.** The Copy dialog reads such text as a number. `"HELLO"`, `"E"`, `"e"` and
  `"1E5"` into DS1 are stored 0.0 (refused on purpose, Settled). `"HELLO"` into TXT1 is stored 0.0 too, and
  fills TXT1..TXT3. The code accepts the text as typed into TXT and encodes it, as ruled (Sam,
  2026-11-17). Open: does Fill do the same?
- **A line break inside a text constant:** does CLICK accept LF and CR inside the quotes of a Compare Data B,
  a Copy source or a Search value? The code accepts them, and `read_csv` reads them into the text. CLICK
  accepts a tab in a Compare Data B and in a Fill into TXT.
- **A Fill into SD from a read-only start SD, with the end at or below it** (`SD28..SD1`, `SD148..SD147`):
  does CLICK refuse the start with OBJ-004 here too? The code does. CLICK refuses `SD1..SD1` and `SD2..SD1`
  with OBJ-004.
- **Characters above U+FFFF:** a source `"😀"` (U+1F600) into TXT1. Does CLICK accept it, how does it save it,
  and which TXT is the end? The code refuses it.
- **Pointer on both sides of a Copy:** `DF[DS1]` into `DD[DS1]`, plain and with Copy Binary. Does the dialog
  offer it? What does it save in 0x2227 and 0x2206? The code writes type 7 or type 8 by the bank pair.
- **Captures for motion and Email:** native Home, Velocity and Position, one per mode, and an Email with To,
  Cc, Bcc, Subject and both body modes filled, each field a distinct value. Their field maps are inferred and
  stay `raw(...)`.
- **ASCII Send and Receive** (static, dynamic, fixed, variable), and Home, Velocity, Position and Email with
  every status field set to a distinct address: native blobs to model later.
- **Other non-pinned boxes in a compact OR layout.** `read_csv` lays them out as it does stacked 2-row
  Copies, and CLICK's post-check layout confirmed that. Capture one more shape (Math, Search or a timer under
  an OR).
- **A box past the last row.** `encode()` writes a box that runs past the rung's last row, such as a Copy on
  row 32 of a 32-row rung. `check()` reports it as `layout-too-tall`. `read_csv` refuses the rung, so you can
  pass such a rung to `encode()` only as a `Rung` that you build in Python. Nobody has tested what CLICK does
  with it. That needs a capture before `encode()` refuses it.
- **An address number of six or more digits.** laddercodec reads at most five digits in an address, so it
  refuses `C000001`. Does CLICK's editor accept it?
- **The length form of a long string in a program file.** CLICK saves a string of up to 63 characters with a
  one-byte count, and one of 130 characters as `ff`, then a u16 count. `decode_program()` reads a one-byte
  count up to 0xFE. If CLICK saves 64 to 126 characters in another form, `decode_program()` reads them wrong.
  Save a Compare whose text is 64, 126 and 127 characters long, and a Math formula of 500 characters to see
  that Math uses the same form.
- **Comment text that no capture shows.** The decoder reads cp1252's five holes (0x81, 0x8D, 0x8F, 0x90 and
  0x9D) as the C1 controls of the same numbers. In a font whose charset is not 0 or 134, it reads each ASCII
  byte as ASCII and each other byte as U+FFFD. No capture shows a comment with either. Set `a`, U+0081, `b` in
  CLICK's comment editor, and type a Japanese comment with an IME. Copy each rung back, and compare what
  `decode()` reads with what the editor shows. Typing `中` with an IME is not tested either. CLICK wrote it
  under a SimSun font when it was set as UTF-16.

## For pyrung's export (another repo first)

This comes from the ecosystem plan's item 2. It waits until pyrung's export goes through laddercodec.

- A check on a whole program, approved by Sam 2026-11-16, moving from pyrung. It covers for-loop nesting
  depth, a One Shot or a Return inside a loop, nested calls, the 8,000-step limit, and pyrung's estimate of
  program steps (its `click/ladder/steps.py`). It comes after pyrung's export goes through laddercodec,
  because only then does pyrung hold a laddercodec program to pass in. See the Syntax Check rules item in
  Later.

## Waits on another repo

**For pyrung** (one line each; unchecked against pyrung's current source):
- Send/Receive: `device_id` accepts 248-255 on RTU and 0 on Receive RTU. There is no `com_port` for CPU Port 3
  or WLAN. A slave ID given as a DS address is not in the DSL, exporter, codegen or backends.
- `raw()` stays a no-op, and its status tags (once laddercodec exposes them) count as written outside the
  ladder.
- `to_text(exponential=True)` from an integer source: refuse it or drop it.
- The translator writes both `to_text` keys (`suppress_zero` and `exponential`). It should write only
  `exponential` for a DF address, a DF pointer or a real constant source, which refuse `suppress_zero` now. It
  should write only `suppress_zero` for any other source.
- The translator writes a pointer with an offset (`DS[DS1+5]`) for a mapped block. CLICK refuses it.
- `COMPARE_COMPATIBILITY` is never called.
- `coil_target` allows X, T and CT. On/off-delay constants have no floor. Drum presets have no 32767 cap.
  Counter presets have no range.
- `search()` accepts a DINT result. CLICK needs DS.
- The shift register has no C-bank role.
- Math: the destination table has no hex/decimal split. It does not refuse text constants, or hex constants in
  a decimal Math.
- Block Copy's bank table disagrees with CLICK's rules.
- `fill("AB", txt[1:5])` builds, and only the simulator objects. It also accepts codes 128-255, which CLICK's
  dialog does not.
- An End inside a subroutine is not flagged.
- A slave ID out of range at run time: pyrung assumes an error bit and no send. Only a PLC shows what
  happens.

## Stable public API (nothing; ClickNick follows)

- ClickNick also imports `csv.contract.CONDITION_COLUMNS` and `csv.writer.decoded_rung_to_rows`. Either these
  move to the top level or ClickNick stops using them.
- The tag-id fields of `Email`, `Home`, `PositionMove` and `VelocityMove` (`tag_60a5`, and so on) are still to
  be renamed.
- Everything else is internal. A test pins `__all__`. Message text is not part of the API.

## Settled (don't reopen)

- **A box after a box with pins (CLICK v4.00, 2026-11-25):** CLICK can't hold the two in one rung. A pin
  row runs from the rail to its pin, and a `T` or `|` can't go in column A. So any wire down to a later
  output crosses every pin row. CLICK joins the wires where they cross, and its Syntax Check refuses the
  rung: C0208 for a Counter's Reset, C0210 for a Shift Register's Clock, C0205 for a Timer's Reset.
  `lay_out` keeps refusing the shape. pyrung refuses the shape when a program is built. The user writes the
  next output as a rung of its own with `.continued()`.
- **Email, Home, Position and Velocity have no pin rows (CLICK v4.00, 2026-11-25):** Each box is three rows
  tall. A contact wired to row 2 or 3 is C0202 "Missing line connection". Their inputs, such as Home's limit
  switches, are dialog fields. pyrung wires nothing to them, so `lay_out` needs nothing for them.
- **Refusal strings (Sam, 2026-11-19):** the `.code` names and the `.field` and `.fields` strings
  (`Copy.src`, `Send.ip`, `Class.field[i]`) are frozen for the release. pyrung is the consumer, so a later
  change goes to both repos together.
- **Same address at both ends (Sam, 2026-11-19):** a range with the same address at both ends (`C1..C1`) is
  `duplicate-address` in every field, with OBJ-012 where CLICK answered it. `range-not-ascending` means only
  an end below the start (`C5..C1`).
- **OBJ-028 and OBJ-023 (Sam, 2026-11-19):** a Send of TXT that starts at an even address, such as TXT1000, is
  refused with the new code `txt-start-not-odd` and OBJ-028. A Fill into TXT of a number of more than one
  character keeps its code and reports OBJ-023 for the shapes CLICK answered.
- **An empty flag field (Sam, 2026-11-19):** `decode()` reads it as set, and issues a `LegacyEncodingWarning`.
- **Command limit (Sam, 2026-11-19):** a `make` or `pytest` command run through the bob wrapper stops after
  900 s.
- **Public class names (Sam, 2026-11-18):** `Instruction`, `InstructionToken`, `Condition`, `CsvReadError`,
  `CsvWriteError`, `PositionMove` and `VelocityMove` are the names, with no alias for the names that they
  replaced. The CSV tokens, the binary class names and the `Code` names do not change. `laddercodec` exports
  `Term`. Every other public name stays.
  `addresses()` is a public name too (Sam, 2026-11-20).

- **Hex Math constants:** keep refusing `DH1 + 7` and `DH1 + 7H7`. Never rewrite them as CLICK's dialog does
  (`7h`, `77h`). The error names the fix.
- **Canonical constants (Sam, 2026-11-16):** the encoder writes the form that CLICK's dialog stores, wherever
  that correction keeps the meaning. That includes a typed `+` and a hex Copy source's leading zeros. Where the
  correction would change what the CSV says (hex Math digits without `h`, a Copy `EH` or `1Eh`), the encoder
  refuses the text, and the message names the fix.
- **Hex Math words without `h` (Sam):** CLICK reads a word of hex digits typed without `h` as a hex constant:
  `abc`, `5`, `-5`, `005`, `C0`, `DD0`, `DF0`, `1E5`, `1-2`, `RAND(5,Ah)`, and `DH0` as `D0h`. laddercodec
  keeps refusing them. A CSV says what it means, so laddercodec refuses `DH0` meaning `D0h` and `10` meaning
  16. `DISAGREEMENTS` keeps them as kept differences.
- **Copy into DS of text that isn't a number (Sam):** CLICK accepts `1E`, `E5`, `"HELLO"`, `"E"`, `"e"` and
  `"1E5"` as a Copy source into DS1. It stores the real that it parses them to (0.0, or 1.0 for `1E`).
  laddercodec keeps refusing these six. DS is an integer, so a real such as 0.0 or 1.0 is no source for a
  Copy into DS1. Typing a valid constant can't make that rung either, because 0.0 into DS becomes 0.
  `DISAGREEMENTS` keeps them as kept differences.
- **A bare number copied into TXT (Sam):** `copy(5,TXT1)` is refused. It needs `to_text`.
- **Rule codes (Sam):** the codes are kebab-case names in `.code`, with CLICK's id in `.click_id`, and `allow=`
  takes the name, never the id.
- **A real constant that CLICK saves as another value** (more than 7 significant digits in a Copy; in a Math,
  the rule in **Math real form**) is refused, and the refusal names CLICK's form. It is never rewritten.
- **Text past TXT1000** stays refused (OBJ-003), though CLICK accepts a pasted one.
- **Search keeps `op` and Call keeps `subroutine`** as field names.
- **`feat/productivity-codec`** stays as a branch for now.
- **A last rung of only wires in an SCR save.** It can't be told from CLICK's own trailing empty rungs. Both
  are records with no instruction and no comment, byte-identical, and CLICK keeps 1 to 4 trailing empties. So
  `decode_program` drops it. Nothing to do unless CLICK's save differs somewhere not yet seen.
- **A padded TCP address (Sam, 2026-11-20):** laddercodec accepts `010.2.3.4` and writes `10.2.3.4`. Each
  part is read as decimal.
- **A space in an address (Sam, 2026-11-17):** an edge space, or a space inside an address (`DS 1`), stays
  refused on purpose, though CLICK's dialog accepts it. An instruction holds the address in display form. Decode
  reads CLICK's saves of such an address, and a decoded Compare whose Data B holds `DS 1` keeps the refusal.
- **Quoted text with an E into TXT (Sam, 2026-11-17):** the rules keep accepting it, and the encoder keeps
  writing it as text, though CLICK stores it as its float value. A Copy `"HELLO"` into TXT1 saves the source
  `0.0`, ends in TXT3 and has conversion type 3. Decode reads that save as
  `copy(0.0,TXT1,convert=to_text(...))`.

## Later (nothing unless marked)

- **A refusal's example from the partner field (builder).** A caller who follows the example in some
  refusals gets another refusal, because the example is chosen from the field alone:
  - the other end of a range: `Coil("Y001", range_end="$41")` suggests Y001;
  - the other operand of a Copy, Block Copy, Pack, Unpack, Compare or Search;
  - a Send's function code: FC06 suggests DD1 or DF1, which FC06 refuses.

  The `_IGNORES_PARTNER` entries in `tests/test_refusal_details.py` list them. The branch `fix/msg-examples`
  (not pushed, in the main checkout) adds an optional preferred example to `example_address`. Nothing calls
  it yet.
- **Math mode advice (builder).** "Set mode to hex" ignores the formula's constants, so the advised formula
  can still be refused (`DH1 AND 3`). The same holds for "Set mode to decimal" with `SIN ( 2h )`. A SUM range
  of bits (`C1 : C8`) is told to write "its registers as DH, XD or YD"; the message should say bits.
- **`quantity=N` in Send and Receive messages (builder).** Some refusals advise `quantity=N`, which a CSV
  token refuses. The message should name the source range instead.
- **The `$hh` hint in Fill and Compare (nothing).** A Fill into TXT and Compare's Data A share one text
  check. Each refuses a character outside ASCII, such as `"é"`, with `invalid-text-constant`, and the message
  says to write the character as its `$hh` code. The bare `$E9` is accepted in both. The quoted form `"$E9"`
  is not what the hint means:
  - In a Fill it is refused again, with `constant-out-of-range`.
  - In Compare's Data A it is accepted as the 3-character text `$E9`, so the compare matches other text.

  The hint should show the bare form.
- **CLICK ids for Compare and Search refusals.** CLICK shows an id for these refusals, and the code gives
  none or another. Add the ids, with no new codes:
  - mixed Compare groups: OBJ-007 (`compare-mixed-types` has no id);
  - `$100`, `$G1`, `$` and `$ 41` in Compare's Data B and in a Search value: OBJ-005;
  - a Search table in a bank that Search doesn't take: OBJ-004, and OBJ-005 for an XD0u or YD0u start;
  - a Search table whose end is in another bank than its start (`DH1..DS1`, `DH1..TXT1`, `TXT1..DS1`) and a
    one-register TXT table (`TXT1..TXT1`): OBJ-004, where the code says OBJ-008 or OBJ-012. The code for
    the same address at both ends is ruled (Settled); the id here follows CLICK's answer.
- **A formula refusal's place in the CSV cell (nothing).** When `read_csv` refuses a Math formula,
  `FieldError.span` gives the place within the formula argument, without the spaces at its ends. It does not
  give a character offset within the CSV cell. The token parser strips the cell and its arguments, and it can
  rewrite a token that has blank arguments, so it does not know where the formula sits in the cell. Also,
  `CsvLocation` has no field for an offset. Adding one is new public API, and Sam approves it.
- **Unicode line separators.** U+2028, U+0085, VT, FF and x1C-x1E outside quotes read as whitespace in a CSV
  token.
- **Copy Binary decode.** A type 8 Copy decodes without comparing tag 0x2206.
- **An RTU Send or Receive (nothing).** The encoder writes `...` in tag 0x622B of an RTU Send or Receive. A
  decoded one whose 0x622B holds anything else does not keep its stored blob, so `encode()` writes `...`
  there.
- **Three RTF forms that the comment readers disagree on.** `_decode_rtf` and `undecoded.recover_text` read
  three RTF forms differently. CLICK writes none of them, so nothing waits on this. `_decode_rtf` ignores a
  `\ucN` in the header, before `\fsN`, and `recover_text` reads it. A `\uN` above 0xFFFF reads as that
  character in `_decode_rtf` and as nothing in `recover_text`. A brace as the fallback character of a `\uN`
  opens or closes a group in `recover_text`, and `_decode_rtf` drops it.
- **Code page 936 text that Python's `gbk` codec cannot read.** Windows code page 936 reads the
  byte 0x80 as `€`. It also reads 2,149 user-defined two-byte codes, as U+E000 to U+E864. Python's `gbk`
  codec has no character for any of them. The decoder reads each as U+FFFD and warns with `partial`. No
  capture shows CLICK writing them. A table like the code page 1252 one in `_rtf.py` would let the decoder
  read them.
- **The comment fuzz check (nothing).** `tests/ladder/test_comment_markdown.py` decides whether an underline
  touches a word by calling the code's own `_is_alnum`. Write the rule in the test instead
  (`ch.isalnum() or unicodedata.category(ch).startswith("M")`), so that the test does not depend on the code
  that it checks.
- **The `.python-version` pin.** It sets Python 3.13 for a fresh venv, because pyyaml has no wheel for
  3.15 and `make docs-build` fails without it. Delete the file when pyyaml ships a 3.15 wheel.
- **Small cleanups.** `tests/csv/test_flag_keywords.py` has no `read_csv(unchecked=True)` case with a
  location. `devtools/classify_dryrun.py` keeps the internal `for_limit_*` names.
- **Email, Home, Position and Velocity readers:** each has a `from_csv_token` that no CSV token reaches,
  because their registry SPECs have no CSV names. Check whether these readers are dead code, and delete them
  or wire them.
- **Hex message without an OBJ id (CLICK):** in Math, the refusal for a padded 32-bit constant ("a hex
  constant above FFFFh has at most 8 digits") carries no OBJ id. Find the id that CLICK shows there, if any. A
  single Copy source reports OBJ-005 for it, as CLICK does.
- **Kind-mismatch refusal for junk input:** the message "<field> takes a decimal integer", for a blank or a
  stray character, states the rule but not what was wrong with the input.
- **Operand probe recheck:** recheck, against the operand probe, every operand field that it finds surprising,
  and fix or delete.
- **SCR blob dataclass** (Sam's idea):
  - One frozen dataclass per instruction class: its ordered tags, defaults, array sizes and func code.
  - SCR decode lays the sparse tags that it stores over that dataclass to build the full blob. An unknown
    class fails loudly.
  - Proof: the native SCR and clipboard pairs (793 AF blobs, 755 conditions). Today 120 of the 793 differ.
- **Output-column down wire:**
  - Decode would keep the flag and lift the refusal (the layout work left it out). Sam punted it, because no
    one draws one.
  - Until it lands, such a rung becomes an undecoded marker.
- `layout_check._blank_rows` counts a first row that holds only an unpowered NOP as content. So C0202 row
  numbers can be off by one.
- **Clipboard row count too low.** When the program header counts fewer rows than the grid holds, the
  clipboard walk stops at the header's count. The last rung loses its later rows, with no marker
  (`_walk_grid`'s bound and `_decode_single`'s slice).
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
- **`read_csv` and CLICK's check rewrite of a wires-only rung (Sam; after 0.5.1).** CLICK's
  check wires a rung of only wires through AF, and the rung then decodes as wires into a `NOP`
  (`tests/test_check_shapes.py`, rung 14). `read_csv` keeps the rung as drawn, with no `NOP`. Should it
  return the post-check form? A `NOP` in a rung of wires is a token that the CSV does not hold.

  **CLICK question.** CLICK's answers are known only for a rail-fed `NOP` beside coils. The layout drops it
  beside every kind of box. What does CLICK's check do with a rail-fed `NOP` beside a counter with
  `.reset()`, beside a Copy, and beside `end()`? The sandbox runner or Sam answers it.
- The Home `11f5` flag doesn't round-trip.
- RawInstruction's hex fallback breaks when the hex contains `,` or `)`.
- A guard that a REFUSED entry has gone stale.
- A Hypothesis property test.
- **Home, Velocity, Position and Email status bits:** read-only `outputs` with busy, complete, success,
  error and error code (Email: sending, success, error, error code). The `raw(...)` token stays as it is.
- **Syntax Check rules `check()` doesn't report.** It reports C0001, C0002, C0003, C000A, C0202, C0205 and
  C0212. It does not report these:
  - For/Next nesting, pairing, One Shot and Return/End inside a loop;
  - Next alone on its rung (C0009);
  - a timer inside For/Next (C1004);
  - Break/Continue without a contact or outside a loop;
  - a subroutine without an unconditional Return, and Main without an unconditional End;
  - the other timer, counter, shift and drum input-contact rules;
  - duplicate Timer or Counter addresses, and Out or Drum on a used timer address;
  - an unused timer or counter bit;
  - a Math function not followed by an operator;
  - a motion instruction that names an axis that does not exist.

  Decide which are worth a Finding.
- **SCR decode of a Math whose range is refused** keeps only 6 of Math's 5510 fields. The SCR blob dataclass
  above fixes it.
- **ASCII Send and Receive** are not modelled (they stay `raw`).
- **Send/Receive padding slots.** CLICK writes the slot index, and the encoder writes another form. Changing
  it changes all 19 Send/Receive goldens and needs paste checks. Check against the current encoder before
  starting.
