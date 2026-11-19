# laddercodec roadmap

This file is the only statement of what laddercodec still has to do. Work that crosses repos is written once,
in the ecosystem plan (`ssweber.github.io/plan/README.md`). Items here link to it and don't repeat it. When an
item lands, delete it.

Each item says what it needs. **nothing** means code only. **CLICK** means the CLICK software, through the
sandbox runner or Sam. **PLC** means a real PLC. **Sam** means his judgment. **another repo** means a change
in a sibling repo. Work that needs nothing is never queued behind work that needs Sam.

Written 2026-11-15, after 0.4.0, from the post-release plan and Sam's rulings on it. Updated 2026-11-17.

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

## Order

Done:
- the cruft sweep;
- the undecoded marker (#38);
- the field-rule restructure (#43-#51);
- the field error that pyrung reads (#55-#60). Every instruction reports every refusal, with its fields,
  reason and CLICK id. Through `read_csv`, each refusal also has a location.
- decoding that does not depend on the checks. A stored instruction that breaks a dialog rule decodes as that
  instruction with a `RefusedFieldWarning`. `read_csv(..., unchecked=True)` reads what `write_csv` writes for
  it.

The next release, Sam's, carries all of this.

Sam's direction of 2026-11-16: pyrung's CLICK validation moves onto laddercodec first, ahead of its export and
import. pyrung builds laddercodec's objects and turns each refusal into a finding. Its own bank tables go.

1. The field error's follow-ups. pyrung's validation waits only on a release that has the error.
2. API cleanup, in the order below. It is provisional until laddercodec and pyrung release together.
3. Field rules tightened to the CLICK grids, as the grids arrive.
4. Canonical constants, once CLICK has answered (the runner is asking now). It can run beside 1-3.

The SCR blob dataclass fits in wherever it is ready. pyrung's export needs come after the API cleanup (below).

laddercodec refuses what CLICK's editor refuses. It also refuses what breaks the encoding or crashes CLICK on a
paste. A rule that rests on what a PLC does stays in pyrung.

## 1. The field error's follow-ups (nothing, except where marked Sam)

pyrung learns what a field takes by building the object and reading the error. That is on `main`. Two things
are not built. One is a rule-description API (`field_rules(Copy)["source"]`). The other is a public way to build
an instruction without its checks. pyrung's conformance probes use `raw(...)`. The decoders use the private
`laddercodec.operands.unchecked.unchecked()`, which a public API could expose.

- **A strict numeric tag.** `tag_int` reads a tag through `int()`. It accepts `" 1"`, `"+1"`, `"1_0"` and
  non-ASCII digits, as it did before. If it read only ASCII digits, those blobs would stay raw.
- **A held condition from a program file.** When `decode_program()` builds a contact that has a refusal, the
  contact has no blob to write. `encode()` raises the refusal's error. The unknown condition that it decoded as
  before did not encode either. A Compare whose Data B CLICK saved as typed (`ds1`, ` DS1`) has no blob
  either, so it encodes in display form. An output box writes the blob composed from its tags, as its raw
  box did. Decide whether a condition should do the same.

- **Where in a formula (Sam).** Two identical refusals in one formula (`DS0 + DS0`) can't be told apart. The
  proposal is `FieldError.span`, a half-open `(start, end)` character offset into the expression as typed. It
  is new public API.
  - It is None where no single stretch is at fault: an empty formula, the length, a `(` left open, the mode
    conflict.
  - A range refusal spans its `A : B`.
  - SUM's CT refusals and X/Y refusals span the range argument.
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
  with `read_csv` (`Copy.from_csv_token` refuses quoted `"A,B"`, `"A=B"`, `"(A"` and `"A\nB"`). Route every
  `from_csv_token` through `parse_af_token` and `parse_af_call`, and the condition tokens through their
  equivalent, so that one parser reads each token.
- **Token-syntax class split.** Some token-syntax errors are a `CsvReadError` and others are a `FieldError` with no
  field. Pick one class for a token that is not syntax.
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

## 2. API cleanup (nothing; provisional until the joint release)

Sam's rule (2026-11-17): the API stays open to change from pyrung's feedback, as pyrung's validation branch
adopts it, until laddercodec and pyrung release together. Every change merged here is provisional until then.

- **Done:**
  - the error tree, and `decode()` returning a list (#94);
  - the CSV names for Timer and Counter (#95), Contact and Coil (#97), Drum (#98), and Math, Search, ForLoop
    and `raw` (#99);
  - one CSV flag rule for every family (`check_csv_flag`).
- **In flight:** the Copy-family names (Copy, BlockCopy, Pack, Unpack).
- **Next, in order:**
  1. Ids. Every refusal gets a `.code`, which is one of the kebab-case names Sam approved in the code-names
     list. CLICK's id goes in `.click_id`. `allow=` takes the name. On `Finding`, `kind` becomes `code` and
     `code` becomes `click_id`. A `LayoutError` gets both. Email, Home, Position and Velocity are marked
     provisional here.
  2. Frozen instructions. Instructions get `frozen=True`. A public `laddercodec.replace(inst, **changes)`
     keeps the held blob and refusals when nothing changes, and checks again when something does. Drum's lists
     are tuples already, so only the `wire_down` writes in the decoders go through `rebuilt()`.
  3. The rung grid. `Rung` becomes frozen with a tuple grid, and `wire_down` moves into the grid. This comes
     before the export pieces.
  4. Then pyrung's export needs (below).
- **Before release (Sam):** review the code-names list as a user would. For each name, check three things: the
  name, one plain sentence in CLICK's words, and one example.

## 3. Field rules tightened to the CLICK grids (CLICK)

The runner tries whole grids, not samples: every bank and constant kind in each dialog field. Its answers are
committed here as test data. That makes these tests the one place where CLICK's field rules are recorded. No
rule is written from the 17 sampled rows in `ssweber.github.io/plan/rule-decisions.md`.

- **Case lists (Sam, 2026-11-16):** laddercodec writes them, because it knows how each field is modelled
  (banks, constant kinds, modes). They take the shape of ClickNick's `devtools/editor_cases.json`. click's
  runner runs them and returns the answers. The cases and the answers are committed as test data. Today the
  runner's `try` drives Math, Copy (single, block, pack, unpack) and Out, at about 4 seconds a case, so those
  grids run first. click is adding a run that resumes, and more dialogs, Receive first.
- **Math, Copy and Out grids are written** (#54). `make editor-grids` makes them in
  `tests/fixtures/editor_grids/`, with laddercodec's verdict beside each case. CLICK has answered:
  - `preflight` and `risky` (159 cases);
  - Receive (18);
  - the picker checks (28);
  - the full Out, Copy (single, block, pack, unpack) and Math (decimal, hex) grids (5,210).

  `tests/test_editor_answers.py` compares the answers with the rules. It lists each difference, grouped by what
  is to be done. Left to answer: Receive, Compare, Search, Fill, timers, counters and For. What the answers
  showed:
  - Hex Math reads a word typed without `h` as a hex constant (`DH1 + 0`, `5`, `abc`, `DH0` as `D0h`).
    laddercodec refuses it on purpose (Settled, below).
  - Math formula banks (ruled, Sam, 2026-11-16). There is one table per mode in `math_formula._OPERANDS`:
    - Hex accepts hex constants and the DH, XD and YD registers only. It refuses every other register (DS, DD,
      DF, TD, CTD, SD, TXT) and every bit, in a `SUM` too. The answers show DH accepted, and DS and X refused
      (X in a `SUM` too). The rest is the ruling, made ahead of CLICK's answer.
    - Decimal accepts decimal constants and the DS, DD, DF, TD, CTD and SD registers. It accepts X, Y, C, T and
      SC bits only as the range of `SUM ( a : b )`. It refuses DH, XD, YD, TXT and CT anywhere, a `SUM`
      included. The Address Picker for a decimal `SUM` enables exactly X, Y, C, T, SC, DS, DD, DF, TD, CTD and
      SD.
    - Every bank refusal is OBJ-1002, reason `bank`. The formula gets one refusal for each address outside a
      `SUM` and one for each `SUM`.
    - The `math_hex` and `math_decimal` answers confirm both tables in every position: alone, beside a
      constant, as a range end, and in a `SUM`. That includes XD and YD in hex, and DH, XD, YD, TXT and CT in
      decimal. The exception is a RAND bound, which accepts fewer banks (RAND bounds, below).
    - A `SUM` whose ends are reversed is OBJ-1014. A `SUM` whose ends are in two banks is OBJ-1015. Both come
      before OBJ-1002 for a refused bank (`SUM ( DH2 : DH1 )`, `SUM ( X001 : TXT2 )`). Closed: the rules check
      every range's banks and order before any address's bank. Then they check a median's size and the X/Y
      option-slot ends. Open (CLICK): the rules' order where no answer covers it:
      - A reversed or two-bank `MAX`, `MIN`, `MDN` or `AVG` range over a refused bank (`MAX ( DH2 : DH1 )` in
        decimal). The rules report OBJ-1014 or OBJ-1015 first, as for a `SUM`.
      - A formula with a refused address beside a refused range (`DH1 + SUM ( DS5 : DS2 )` in decimal). The
        rules report the range's OBJ-1014 first, whatever stands before it.
      - A median over a refused bank that is also past 1024 bytes. The rules report OBJ-1002 before OBJ-1013.
  - CLICK accepts an edge space in Math's result and formula, Copy's source and destination, a Block source, a
    Pack destination, an Unpack source, Compare's Data A and Data B, and a Search's value and result.
    laddercodec refuses it. Ruled (closed): the refusal stays, because an instruction holds the address in
    display form. Decode reads CLICK's edge-space saves. A single Copy's destination, a Pack's destination,
    Compare's Data B and a Search's result keep the space, and decode as the address without it. The ratchet
    keeps these entries with that reason. Both `dec  DS1 = ...` and `dec DS1  = ...` put the space in the Math
    result.
  - CLICK refuses an Unpack of a DS into DS with OBJ-004. laddercodec said OBJ-024. Closed: every Unpack
    destination bank that its source can't unpack to now carries OBJ-004. CLICK confirms it for a DH source
    into DS and for every source into T, DD and TXT. CLICK reports OBJ-004 for a source from Y, C, T, CT, SC,
    XD, YD, TD, CTD, SD or TXT. A DS, DD or DF into Y is OBJ-024 (Pack and Unpack order, below).
  - Copy-family bank ids (closed for the answered rows). A bank that no row of the field lists gets these ids:
    - OBJ-004 for a Pack destination (answered for X001, SD29 and SD31), an Unpack source (X001) and an Unpack
      destination (X, SC and SD).
    - For a single Copy into a bit bank that the Copy does not write, OBJ-004 from a bit source (X001 into
      X001, C1 into SC50 and SC303) and OBJ-024 from any other source (DS2 and 5 into X001).

    The rules apply these ids to every bank of each check. What the full grids answered:
    - Single Copy, T and CT as the destination: OBJ-004 from a bit (C1, X001), and OBJ-024 from a DS.
    - Single Copy into SC: OBJ-024 from a DS or a number.
    - Single Copy of a TXT register or a text constant into X, C, T, CT or SC: OBJ-024.
    - The rules match each of these.
    - Single Copy, XD as the destination: OBJ-004 from a DS, TXT1 or 5, and OBJ-024 from a bit or `"A"`. The
      rules report no id there yet.
    - Pack into Y, C, T, CT or SC (in range or past it) is OBJ-004. Pack into XD, YD or TXT is OBJ-004, and
      OBJ-033 for 32 X or Y bits. The rules match.
    - A bit (C1, X001, T1, CT1, SC1), quoted text or `10000h` into SD1, which a Copy does not write, is
      OBJ-024, because the pairing comes first (`$41` into SD1 is OBJ-004). The rules match. SD43 is not
      answered.
    - A DS into an X, T, CT or SC address outside its bank (`DS2 -> X017`, `T501`, `SC1001`) is OBJ-004, not
      OBJ-005. The rules report OBJ-004 there from any source. A bit source (`C1 -> X017`) is not answered.
    - A `$` code source (`$41`, `$1`) into any bank but TXT is OBJ-004. Into a pointer of another bank
      (`X[DS1]`, `XD[DS1]`, `SD[DS1]`) it is OBJ-004 too, where quoted text is OBJ-024. The rules match.
    - A single Copy's checks run in the order that the answers support:
      1. the source's address;
      2. the destination's address (OBJ-004 for an address outside its bank in X, T, CT or SC);
      3. the source constant's value (`""`, `0FFFFFFFFh`, `100000000h`, `+FFh` and 129 characters of text
         into DS1 are OBJ-005);
      4. the pairing (OBJ-024, or OBJ-004 for a `$` code);
      5. an SD that the Copy does not write (OBJ-004).

      Text outside printable ASCII is refused last. CLICK reports OBJ-024, the pairing, for `"é"` and a tab
      into DS1, whether or not it also refuses the characters.
    - The answers support this order where the destination is refused for its address (DS2 into X017, T501,
      SC1001: OBJ-004 before any pairing). It is still open where the destination is a bit bank address and
      the source is a refused constant. Does CLICK report `99999999999`, `1e99`, `FFFFFFFFFh`, `"é"` or text of
      200 characters into X001 for the constant or for the destination, and with which id? The rules refuse
      the destination's bank first, with no id, and refuse the constant after it.
    - The single Copy reports its source value refusals as OBJ-005, as CLICK does. The shared constant check,
      which Math and Fill use too, gives no id to an empty text, a signed hex constant, or a hex constant of
      more than 8 digits. A quote inside the text (`"a"b"`) has no answer and no id.
    - Not answered, rules None. CLICK reports OBJ-005 for DS2 or 5 into `X[DS1]`, `Y[DS1]`, `T[DS1]`,
      `CT[DS1]` or `SC[DS1]`, and OBJ-004 into `XD[DS1]` or `SD[DS1]`. The rules refuse each as a pointer
      with no id. CLICK reports OBJ-005 for `-$41` into DS1. The rules refuse it as no address, with no id.
  - Receive TXT count: confirmed. The count is in characters, from 2 to 250, and even. CLICK reports OBJ-010
    outside the range (1 and 251 included) and OBJ-029 for an odd count inside it. The rules match, with both
    ids. The dialog holds 2 when the count is unset, and the rules accept that. `receive.answers.json` (rx2)
    recorded no count, so its `03 -> TXT1` stays in the ratchet at count 1.
  - Open (CLICK): is Send's TXT count in characters too, and what are its limits? Send has no TXT rule today.
- **The writable-SD list (closed):** `sc_sd_writable.answers.json` lists 29 SD for a single Copy, a Block Copy
  and a decimal Math result. It lists none for Out. It lists 25 SC for Out and none elsewhere. `WRITABLE_SD`
  holds the 29. The three fields refuse any other SD with reason `not_writable`:
  - a single Copy reports OBJ-004 (answered for SD43, SD105, SD216 and SD1000);
  - a decimal Math result reports OBJ-003 (SD62, SD148 and SD999);
  - a Block Copy refuses when any address of its destination range is not listed.

  A Block Copy from `DS1..DS2` gets OBJ-018 ("read only addresses between") from CLICK into SD42 and SD147,
  and OBJ-004 into SD215. The rule fitted to these three answers is:
  - OBJ-018 for an unlisted SD before SD215;
  - OBJ-004 for one past it;
  - no id for a range with both;
  - no id for an unlisted start.

  The sweep grids (`math_sd`, `copy_sd_single`, `copy_sd_block`, `out_sc`) are removed, because the picker
  list answers them. Open questions for CLICK:
  - the last nine `copy.block.destination.banks` cases: a writable start whose range reaches read-only SD,
    controls inside the list, and a read-only start that ends writable;
  - a Block Copy whose start is not listed;
  - an unlisted SD below SD29 in each field.

  A Fill into SD needs every SD in its range to be writable. CLICK refuses any other SD range with OBJ-004, and
  so does the code.
- **The picker's lists for 8 more fields are in.** They are Pack's destination (with nothing filled first,
  with an X source, and with a C source), Unpack's destination and destination end (with nothing, a DH source
  and a DS source), and a hex Math result. None of them lists an SC or SD address, and the rules accept none.
  Two sets of answers agree with the rules, with one exception on an id:
  - the 15 `try` cases from those lists (`picker_lists.answers.json`);
  - CLICK's two rule-table rows (`rule_rows.answers.json`): a block Copy of TXT into TXT and a hex Math into
    YD.

  The exception: CLICK refuses an SD as a hex Math result with OBJ-003 (outside the range). It answered for
  SD29 and SD31, and the rules apply it to all of SD1-SD1000. The full grid answers SD0 and SD1001 with
  OBJ-004. YD9 is answered the same way, and the rules apply it to a YD past YD8. The rules now say so. Before,
  they said OBJ-004 or gave no id. A bank that a hex result does not accept (DS1) stays OBJ-004.
- **Follow-ups from the full grids (waiting on nothing).** Each is one group in `DISAGREEMENTS`. Fix the
  rule, then drop the group's entries:
  - Hex Math words without `h` stay refused (Settled). But the rules refuse a word shaped like an address
    (`C0`, `DD0`, `DF0`, `DH0`, `DH501`, alone, beside `+ 1h` or as a RAND bound) as outside its bank's range.
    That message is to name the `h` form (`C0h`, `D0h`), as the message for `5` or `abc` does.
  - RAND bounds (closed). There is one table per mode in `math_formula._OPERANDS`. A decimal bound is a DS or
    DD register or an integer constant. A hex bound is a DH register or a hex constant. Any other bank is
    OBJ-1002. A real bound and equal bounds are OBJ-1001. The answers show all of this. Open (CLICK):
    - Are bounds equal by their text or by their value? The rules use the narrowest reading, the same text in
      display form. So they refuse `RAND(1h,01h)` and `RAND(DS1,ds1)`, and accept `RAND(1,+1)`. They refuse
      `RAND(1,01)` anyway (leading zeros, OBJ-1009) and `RAND(DS1,DS 1)` by its shape.
    - Which id comes first where one RAND has two refusals: `RAND(DF1,DF1)`, `RAND(DF1,1.5)`? The rules
      report the real bound and equal bounds (OBJ-1001) before a bound's bank (OBJ-1002).
    - A hex `RAND(-5,Ah)` is OBJ-1001. The rules refuse `-5` with no id for its missing `h` (Settled), and
      then report OBJ-1001 for the shape.
    - Do the shift and rotate arguments (`LSH ( XD0 , 1h )`) accept XD and YD, as the rules do? No answer
      covers them.
  - The float32 edge in a decimal Math (closed). `3.4028235E+38`, alone or as an operand, is OBJ-1009, though
    float32 rounds it to its largest value. Into DF1, `3.40282E+38` and `-3.40282E+38` are saved as typed, and
    `3.40283E+38` is OBJ-1009. So OBJ-1009 starts between `3.40282E+38` and `3.40283E+38`. The rules refuse a
    real whose value, read as a double, is above float32's largest, 3.402823466E+38, in size. A Copy source
    accepts it (`3.4028236E+38` is OBJ-005 there). CLICK saves `3.402823E+38`, `-3.402823E+38` and
    `3.402821E+38` as typed, and `3.4028234E+38` and `3.402823466E+38` as `3.402823E+38`.
    `-3.4028235E+38` is OBJ-1009. The rules agree with each.
  - A `SUM`'s OBJ-1014 and OBJ-1015 come before OBJ-1002 (closed, above).
  - A hex Math result past SD's range (SD0, SD1001) is OBJ-004 (closed). The OBJ-003 for an SD as a hex
    result covers SD1-SD1000 only. The rules refuse an SD past them as a bank that the result does not accept.
  - `DS 1` (a space inside) (closed). CLICK accepts it as a single Copy's source (saved `DS1`), as a single
    Copy's destination (saved `DS 1`, which `read_csv` refuses), as a decimal Math result, as Compare's Data A
    (saved `DS1`) and Data B (saved `DS 1`), and as a Search value (saved `DS1`). The rules refuse it. Sam
    ruled on 2026-11-17 that it stays refused on purpose, as the edge space is. A decoded Compare whose Data B
    holds `DS 1` keeps the refusal.
  - Pack and Unpack order (closed): in every answered case, the rules report CLICK's id first.
    - A Pack counts its source before the pairing. Where the source packs into the destination, the limit is
      the destination's room (16 or 32 bits, 2 words: OBJ-027, OBJ-041, OBJ-040). Where it does not, bits are
      held to 32 (OBJ-041, then OBJ-024, as the answers' `boxes` show) and a DH source to 2 words (OBJ-040).
      A DS source is not counted (`DS1..DS4500` into DH1 is OBJ-024).
    - For a DH source, CLICK stops after OBJ-040 (`DH1..DH16` and `DH1..DH500` into DH1 show no `boxes`). The
      OBJ-024 that follows in `.errors` is laddercodec's own. CLICK's first id matches.
    - A Pack of text into DH accepts at most 4 characters (OBJ-003, reason `range`). `TXT1..TXT2` and
      `TXT999..TXT1000` are accepted. `TXT1..TXT16` and `TXT1..TXT1000` are refused.
    - An Unpack pairs its destination's start with the source (OBJ-004, or OBJ-024 for Y from DS, DD or DF)
      before it reads the end. So it does not check the end's fit with a refused start (OBJ-008, OBJ-009,
      OBJ-012). A DH into a Y range across two slots is OBJ-1009. The rules said OBJ-019.
  - Pack and Unpack neighbours that no answer covers (CLICK):
    - A Pack of text into DS, DD, DF, TD or CTD. CLICK's own code reads limits of 6 characters for DS and TD,
      11 for DD and CTD, and 14 for DF (OBJ-003). The rules accept any length there. Into DH, the rules refuse
      5 to 15 characters (`TXT1..TXT5`), as CLICK's code does. Ask CLICK next for `TXT1..TXT4` and
      `TXT1..TXT5` into DH1, the edge of the limit.
    - A count where the pairing is refused and no answer shows it: `DH1..DH3` into DS1, DF1, TD1 or CTD1,
      `C1..C33` into TD1 or CTD1, and 33 or more T, CT or SC bits into DF1, TD1 or CTD1 (answered only into DS
      and DD). The rules report the count first (OBJ-040, OBJ-041).
    - A DH into a Y range across two slots with 16 points or fewer (`Y016..Y021`), and a DH into the option
      slot alone (`Y021..Y036`). The rules report OBJ-1009 for the first and accept the second.
  - Addresses saved as typed (closed). CLICK saves these as typed (`DS001`, `DS01`, `ds1`, `XD00`, `YD0U`,
    `xd0U`, `DS[ds1]`):
    - a single Copy's, a Block Copy's and a Pack's destination;
    - each address of a Math formula;
    - a hex Math's result;
    - Compare's Data B, with a space at its ends (` DS1`, `DS1 `);
    - a Search's table start, and its result with a space at its ends.

    Decode reads them in display form. If the instruction is unchanged, decode writes the saved blob. A
    Compare from a program file keeps no blob (item 1, "A held condition from a program file"), so it
    encodes in display form. CLICK saves a Copy, Block Copy or Unpack source, a decimal Math result, an Out
    address, Compare's Data A, and a Search's value, table end and Result Flag in display form, so typed text
    there stays raw.
    - Not answered (CLICK), read in display form by the code's own rule: in those fields, a typed form that no
      answer shows. Examples are a DH as a hex Math result (`dh1`, `DH01`), an X or Y number with extra zeros
      (`X0001`), a lowercase bit (`y021`), a word register with a leading zero (`XD01`, `ctd01`, `txt01`), a
      pointer of another bank (`SD[sd1]`), a Pack destination with leading zeros (`dd001`) and a lowercase X
      or T in a `SUM`.
    - Not answered (CLICK), left raw:
      - an X or Y number typed short (`Y1` as a Copy destination, `X1` in a Math `SUM`);
      - a typed Fill destination;
      - a typed Unpack destination that CLICK accepts (it refused every answered one);
      - what a clipboard copy of a typed Math holds in its operand slots.
    - A program file holds a set flag as an empty value, and the blob that a decoded program box writes keeps
      it that way. The clipboard decoder reads an empty flag as set. No CLICK clipboard capture holds one.
      Open (CLICK): does CLICK read such a pasted box's flag as set?
  - A single Copy's conversion type 7 and a number's TXT end (closed, 2026-11-17). CLICK v4 typed each case
    through its dialogs. The captures are in `tests/fixtures/v4_captures/copy_single/`. Decode reads every
    answered save as the Copy. The encoder now does this:
    - It writes type 7 for DF to and from DD or CTD, for a real constant into DD or CTD, and for an integer
      constant outside int16 into a DF address or pointer (`32768`, `-32769`, `65535`, `65536`, `2147483647`;
      `32767` and `-32768` stay type 0).
    - For an integer or hex constant, it writes a number's end. The end is the constant's length as stored,
      with `h` and `+` counted (`0FFh` into TXT1 ends in TXT4).
    - It refuses an end past TXT1000 with OBJ-003 (`-5` into TXT1000), as it does for quoted text (`"AB"` into
      TXT1000).
    - `10000h` into DF1 is OBJ-024, as before (`docs/internals/instruction-blobs.md`).

    A decoded Copy keeps its stored blob while it is unchanged, if the encoder would write its type or end
    differently. If the encoder writes it as CLICK saved it (a plain copy, a pointer's text), the encoder
    writes `0x1201` = 0 where CLICK v4 sets it. That is the narrow keep rule (2026-11-17).

    A real constant or a DF pointer into TXT accepts what CLICK's dialog offers a DF address (closed, Sam,
    2026-11-17):
    - `to_text(exponential=0|1)`, type 3 or 4 (`0x2206` = 1);
    - a real constant's end at its saved length (`1.5` into TXT1 ends in TXT3, and `1.50`, saved as `1.5`,
      ends in TXT3 too);
    - `suppress_zero` refused.

    A DD or DS pointer keeps suppress zero (type 1, no end). The coverage golden `copy__conversion` holds one
    rung of each new encoding. It waits on a paste check (CLICK).

    Not answered (CLICK): `DF1` into `DD[DS1]`, `DD1` into `DF[DS1]`, and `DF[DS1]` into `CTD1` and `CTD1`
    into `DF[DS1]` as a plain copy. The encoder writes type 7 for each of them. CLICK saves type 7 for
    `DF[DS1]` into DD1, for `DD[DS1]` and `CTD[DS1]` into DF1, and for DF1 into `CTD[DS1]`.
  - Quoted text with an E into TXT: accepted and encoded as text (Sam, 2026-11-17; item 4).
- **SC gaps (closed, 2026-11-16):** CLICK refuses an Out on an SC address outside `WRITABLE_SC` (SC49, SC163,
  SC310 and 12 more) with OBJ-003. It accepts SC50 and SC162. `WRITABLE_SC` stands. Out, Set and Reset report
  OBJ-003 for it.
- **Ids confirmed:** Out, Set and Reset share one validator. It reports these ids:
  - OBJ-004 for a bank;
  - OBJ-008 for a range across banks;
  - OBJ-009 for an end below the start;
  - OBJ-012 for the same address at both ends.

  An end in another bank is OBJ-008, and that comes before the end's own checks. It holds where the field
  refuses that bank (`C1..DS1`) and where the end is a pointer that CLICK reads (`Y001..DS[DS1]`).
  `Y001..X[DS1]` is OBJ-005, and the rules give it no id.

  Not answered, where the rules now report OBJ-008 before the end's own refusal:
  - an SC bit that a coil can't write (`C1..SC1`, which gave OBJ-003 for the end before);
  - an immediate range whose end is in another bank (`immediate(Y001..C2)`, which was refused as not
    immediate).

  Not answered either: an end outside its bank, in another bank (`C1..DS0`). The rules report the end's bank
  refusal (OBJ-004).
- **Ids left None until CLICK answers.** `click_id` is set only where the code records the field's dialog. An
  id that can't be backed stays None. Open:
  - Fill: its pairing and range ends (Copy's OBJ-024, OBJ-008, OBJ-009, OBJ-012?). For a Fill into TXT of an
    integer or hex constant of more than one character, CLICK shows OBJ-023. The rules refuse it with no id.
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
  - OBJ-002 and OBJ-003: which dialogs report them for an address that is not one, and for a number outside
    its bank.
  - The Math formula's ids (OBJ-1001 to OBJ-1015, as the code sets them) and the result's OBJ-004 are read
    from CLICK's own code. The math grids confirm every one that the rules report.
- **A unit on an instruction that has none.** An event drum accepts any `unit`, and `to_csv()` and `encode()`
  drop it. A toggle accepts any falsy `unit`, such as `None` or `0`. Both should refuse a `unit` other than `""`
  with `OPTION_NOT_OFFERED`. The annotations `TimeUnit | Literal[""]` on `Drum.unit` and
  `OutVariantUnit | Literal[""]` on `OutVariant.unit` state that contract.

## 4. Canonical constants (CLICK)

Addresses are written canonical everywhere, and tested. Math and a single Copy source are written as CLICK
stores them (`feat/canon-math-copy`):
- a real as CLICK prints it back;
- a Copy integer without leading zeros;
- hex in CLICK's case;
- `$1` as `$01`.

Hex Math digits without `h` and a Copy `EH` or `1Eh` stay refused, and the refusal names the form to write. A
Copy source also follows CLICK's save of `-0` (`0`) and of a real's `+` (dropped). A Copy real is
written as CLICK prints its value with 7 significant digits, however it was typed (`10000000000.0` as `1E+10`,
`1.0E+16` as `1E+16`, `1.0E+06` as `1000000.0`, `1.0E-05` as `1E-05`). A real that CLICK saves as
another value (more than 7 significant digits in a Copy; in a Math, the rule in **Math real form**) is
refused, and the refusal names CLICK's form. It is not rewritten (Settled). `constant_text()` writes a Python value in the form that the instruction stores. For such a real,
it writes the fewest digits that hold its float32 value. The other constants are written as typed:
- `fill(0ffh,...)`, `fill(005,...)`;
- `DS1==+5`, `DS1==005`, `DF1==1.50`;
- timer `preset=0050`, Search `005`.

Modbus hex addresses are already canonical.

Follow-ups (nothing):
- `constant_text()` can return a form that a Math or a Copy refuses (`0.33333334`). A public helper would
  return CLICK's form for a value.

Closed (2026-11-18, by the rule that the encoder keeps the pre-v4 form of an instruction that both versions
share): tag 0x1201 of a Copy. CLICK v4's dialog sets the tag in every single Copy and Block Copy. Its clipboard
copy holds -1, and its program file holds the tag empty. A clipboard copy from CLICK before v4 holds 0, or -1
with a termination code. When you paste a Copy that holds 0 into v4, v4's copy-back keeps the 0. The encoder
writes 0, except -1 for a termination code and for a single Copy's text constant source. The encoder and the
goldens stay as they are. No capture shows a Fill, Pack or Unpack that v4's dialog saved.

**Open (CLICK v3.92):** paste a single Copy from v4 that has a numeric source and no termination code, so that
it holds 0x1201 = -1. Does v3.92 read it as it reads the same Copy with 0? If it does, the encoder could write
-1 in every single Copy and Block Copy. That would change 19 golden `.bin` files, and each would need a paste
check (CLICK).

**Question for CLICK:** what does each other dialog turn `005`, `+5`, `0ffh`, `0FFH`, `1.50` and `1.5E+3` into?
Ask in Fill, Compare, Search, Timer and Counter presets, OutVariant presets, drum durations and the For count.
Then make one behaviour-change branch per answer set, as for Math and Copy.

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
- Quoted text with an E into TXT is stored as its float value. A Copy `"HELLO"` into TXT1 saves the source
  `0.0`, ends in TXT3 and has conversion type 3. Decode reads that as `copy(0.0,TXT1,convert=to_text(...))`.
  Into `TXT[DS1]` it is stored `0.0`. Ruled (Sam, 2026-11-17): the rules keep accepting it, and the encoder
  keeps writing it as text. The ratchet does not list it, because both CLICK and the rules accept the case
  and its save reads back.
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
- **A doubled quote in a Search text value:** CLICK accepts `search TXT1..TXT10 == "A""B"` and saves the
  value as `"A""B"`. On the PLC, does it match `A"B` or `A""B`? This needs a PLC. The code refuses the value,
  since no form of a Search text value holds a quote.
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
- **Math result into SD9, YD1 and YD0u:** paste each, copy back, and see what is stored. (Item 3's grids
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

  An integral real typed with an `E`, and `1234567.0`, are stored as integers (H in int16, else W). `1e5`
  (`F100000.0`) and `1.` (`F1.0`) are stored as laddercodec writes them. Every other real is stored as CLICK
  saves it (`3.0E+38` as `F3E+38`). Open: whether the integer type
  changes what the Math computes, and which other positional reals CLICK stores as integers.
- **Send Word Swap after a change of function code.** With FC16 and Word Swap on, switch the Send to FC06.
  Does CLICK keep Word Swap stored, or clear it? A runner case types `send fc16 984 400001 <- DS1 x2
  word_swap=ON`, then picks FC06 and saves. The code refuses Word Swap with any code but FC16, so a stored
  FC06 Send with Word Swap decodes with a `RefusedFieldWarning`.
- **Remote address `h`:** the Send and Receive dialogs let `h` and `1HH` through their span check. What do
  they store? The code refuses both.
- **Number constant into TXT:** a single Copy of a number whose text fills more than one TXT saves the TXT
  where its text ends (item 3 has the open cases). CLICK refuses a Fill of such an integer or hex number,
  and the rules do too. What CLICK stores for a Fill of a real into TXT is not known.
- **Termination code with other options.** The code accepts a termination code on a single Copy of a constant
  into TXT with `suppress_zero=0`, such as `copy(5,TXT1,convert=to_text(suppress_zero=0,termination_code=$0D))`,
  and with `exponential=1`, such as `copy(1.5,TXT1,convert=to_text(exponential=1,termination_code=$0D))`.
  CLICK has saved neither. The ClickNick runner types both into the Copy dialog, and laddercodec compares
  CLICK's saves with the blobs that the encoder writes.
- **Fill text and a bare number.** For `fill(5,TXT1..TXT2)` with no option touched, what does the dialog
  default to and save? Does Fill accept quoted text with a character outside space to `~` (`"é"`, a tab)? The
  code accepts the bare number and refuses both characters. It also accepts a real with more than 7
  significant digits as typed (`fill(1234567.8,DF1..DF2)`), where a Copy refuses it.
- **Quoted text with an `E`.** The Copy dialog reads such text as a number. `"HELLO"`, `"E"`, `"e"` and
  `"1E5"` into DS1 are stored 0.0 (refused on purpose, Settled). `"HELLO"` into TXT1 is stored 0.0 too, and
  fills TXT1..TXT3 (item 4). The code accepts the text as typed into TXT and encodes it, as ruled (Sam,
  2026-11-17). Open: does Fill do the same?
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

## For pyrung's export (later; another repo first)

These come from the ecosystem plan's item 2. Each waits until pyrung's export reaches it, after items 1-3 and
the API cleanup.

- An entry that accepts a series-parallel tree and returns rows. The private `_layout.render.render` does
  this, but it needs a `Network` beside the `RungTree`.
- The rows in memory, with the number of CLICK rungs that each source rung became (`write_csv` only writes a
  file).
- A writer for `main.csv` plus `subroutines/`, and a reader that builds their rungs. `csv/bundle.py` only
  parses them, so a refusal in a subroutine file reaches no one yet.
- A check on a whole program, approved by Sam 2026-11-16, moving from pyrung. It covers for-loop nesting
  depth, a One Shot or a Return inside a loop, nested calls, the 8,000-step limit, and pyrung's estimate of
  program steps (its `click/ladder/steps.py`). It comes after pyrung's export goes through laddercodec,
  because only then does pyrung hold a laddercodec program to pass in. See the Syntax Check rules item in
  Later.

## Waits on another repo

- **`docs/guides/csv-format.md`:** delete the pyrung-specific sections after pyrung has its copy.

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

The top level now exports `Program`, `UnknownCondition`, `UnknownInstruction`, `CsvReadError` (was `ConvertError`),
`DecodeError`, `CsvWriteError` (was `WriterError`), `InstructionToken`, `ConditionToken`, `Email`, `Home`, `PositionMove`, `VelocityMove` and `Term`. Still open:
- ClickNick also imports `csv.contract.CONDITION_COLUMNS` and `csv.writer.decoded_rung_to_rows`. Either these
  move to the top level or ClickNick stops using them.
- The tag-id fields of `Email`, `Home`, `PositionMove` and `VelocityMove` are still to be renamed (API cleanup, ids).
- Everything else is internal. A test pins `__all__`. Message text is not part of the API.

## Settled (don't reopen)

- **Public class names (Sam, 2026-11-18):** `Instruction`, `InstructionToken`, `Condition`, `CsvReadError`,
  `CsvWriteError`, `PositionMove` and `VelocityMove` are the names, with no alias for the names that they
  replaced. The CSV tokens, the binary class names and the `Code` names do not change. `laddercodec` exports
  `Term`. Every other public name stays.

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

## Later (nothing unless marked)

- **CLICK ids for Compare and Search refusals.** CLICK shows an id for these refusals, and the code gives
  none or another. Add the ids, with no new codes:
  - mixed Compare groups: OBJ-007 (`compare-mixed-types` has no id);
  - `$100`, `$G1`, `$` and `$ 41` in Compare's Data B and in a Search value: OBJ-005;
  - a Search table in a bank that Search doesn't take: OBJ-004, and OBJ-005 for an XD0u or YD0u start;
  - a Search table whose end is in another bank than its start (`DH1..DS1`, `DH1..TXT1`, `TXT1..DS1`) and a
    one-register TXT table (`TXT1..TXT1`): OBJ-004, where the code says OBJ-008 or OBJ-012.
- **A quote inside Copy text (CLICK).** Does a single Copy's source accept `"A""B"`, and what does CLICK
  save? laddercodec refuses it and says to write the text without the quote.
- **Unicode line separators.** U+2028, U+0085, VT, FF and x1C-x1E outside quotes read as whitespace in a CSV
  token.
- **Copy Binary decode.** A type 8 Copy decodes without comparing tag 0x2206.
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
- **`read_csv` and CLICK's check rewrite of a wires-only rung (Sam).** CLICK's check wires a rung of only
  wires through AF, and the rung then decodes as wires into a `NOP` (`tests/test_check_shapes.py`, rung 14).
  `read_csv` keeps the rung as drawn, with no `NOP`. Should it return the post-check form? A `NOP` in a rung
  of wires is a token that the CSV does not hold.

  CLICK's other rewrite is built. When a rung has another output, the layout drops a `NOP` that the rail
  feeds with no contact, then lays out and splits the rest (`docs/internals/layout.md`, rule 8).
  `read_csv`, `write_csv` and `lay_out()` all use that layout. A `NOP` behind a contact stays, and so does a
  `NOP` that is the rung's only output.

  **CLICK question.** CLICK's answers are known only for a rail-fed `NOP` beside coils. The layout drops it
  beside every kind of box. What does CLICK's check do with a rail-fed `NOP` beside a counter with
  `.reset()`, beside a Copy, and beside `end()`? The sandbox runner or Sam answers it.
- The Home `11f5` flag doesn't round-trip.
- RawInstruction's hex fallback breaks when the hex contains `,` or `)`.
- A guard that a REFUSED entry has gone stale.
- A Hypothesis property test.
- **Home, Velocity, Position and Email status bits:** read-only `outputs` with busy, complete, success,
  error and error code (Email: sending, success, error, error code). The `raw(...)` token stays as it is.
- **Syntax Check rules `check()` doesn't report.** It reports C0001, C0003, C000A, C0202, C0205 and C0212. It
  does not report these:
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
