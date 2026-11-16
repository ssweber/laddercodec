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
`read_csv`, a location on each). The next release, Sam's, carries it.

Sam's direction of 2026-11-16: pyrung's CLICK validation moves onto laddercodec first, ahead of its export and
import. pyrung builds laddercodec's objects and turns each refusal into a finding; its own bank tables go.

1. The field error's follow-ups. pyrung's validation waits only on a release with the error.
2. Decoding that does not depend on the checks.
3. Field rules tightened to the CLICK grids, as the grids arrive.
4. Canonical constants, once CLICK has answered (the runner is asking now). It can run beside 1-3.

The stable public API and the SCR blob dataclass fit in wherever they are ready. pyrung's export needs come
later (below).

laddercodec refuses what CLICK's editor refuses, plus what breaks the encoding or crashes CLICK on a paste. A
rule that rests on what a PLC does stays in pyrung.

## 1. The field error's follow-ups (nothing, except where marked Sam)

pyrung learns what a field takes by building the object and reading the error; that is on `main`. Not built: a
rule-description API (`field_rules(Copy)["source"]`), and a public way to build an instruction without its
checks (pyrung's conformance probes use `raw(...)`).

- **A blank is `missing`.** The shared checks give a blank field the reason of a bad value (a blank Out
  variant `on_acc` is `address`, a blank `on_preset` is `kind`), so pyrung can't tell a blank from a bad value.
  Changing it changes first-refusal reasons, so it is its own branch.
- **Where in a formula (Sam).** Two identical refusals in one formula (`DS0 + DS0`) can't be told apart. The
  proposal: `FieldError.span`, a half-open `(start, end)` character offset into the expression as typed; None
  where no single stretch is at fault (empty, the length, a `(` left open, the mode conflict); a range refusal
  spans its `A : B`, SUM's CT and X/Y refusals the range argument. It is new public API.
- **Math messages:** `06000000000` is refused as `form` (its leading zero) but its message says it is outside
  int32; a `to_display` refusal inside a formula has no `Math.expression:` prefix; `MAX ( DS1 , DS2 )` gets the
  range-shape refusal with no id while a comment records OBJ-037 for it. Fold these into item 4's Math work.
- **Copy termination code:** a non-`$` code gets OBJ-036; `$ZZ` and `$D`, refused by the shared check, get
  none.
- **A test of long digit text:** feed every constant field more than 4300 digits and expect a refusal, never a
  crash (Math's formula once crashed there).

## 2. Decoding that does not depend on the checks (nothing)

A stored instruction that breaks a dialog rule (such as an older paste of `DH70 == DS3920`) decodes as raw or an
unknown condition today. Before any rule is tightened, `decode` builds the object from what is stored and
attaches a finding; otherwise every tightened rule turns instructions in real projects into raw. `read_csv`
takes an opt-in flag for the writer's self-check. Construction, plain `read_csv` and `encode()` stay strict.

CLICK saves a single Copy's destination and a Pack's destination with an edge space kept (`DS1 `, ` DS1`);
decode reads that save as raw today, and must read it.

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
  (18) and the picker checks (28); `tests/test_editor_answers.py` compares them and lists each difference.
  Left: the full Math, Copy and Out grids, then Receive, Compare, Search, Fill, timers, counters
  and For. What the answers showed:
  - Hex Math `DH1 + 0`, `DH1 = 0` and `RAND(5,Ah)` are accepted, laddercodec refuses on purpose (item 4).
  - Hex Math `SUM(X001:X002)` and a DS in a hex formula (`DS1 + 1h`) are refused (OBJ-1002), laddercodec
    accepts: tighten.
  - An edge space is accepted in Math's result and formula, Copy's source and destination, a Block source, a
    Pack destination and an Unpack source, laddercodec refuses: decide the rule here (the saves trim it except
    a single Copy's and a Pack's destination; see item 2).
  - Unpack of a DS into DS is refused with OBJ-004, laddercodec says OBJ-024: align the id.
  - Receive TXT count: confirmed, in characters, 2 to 250 and even (OBJ-010 outside the range, 1 and 251
    included; OBJ-029 for an odd count inside it); the rules match, with both ids. The dialog holds 2 when
    the count is unset, which the rules accept. `receive.answers.json` (rx2) recorded no count, so its
    `03 -> TXT1` stays in the ratchet at count 1.
  - Open: is Send's TXT count in characters too, and what are its limits? Send has no TXT rule today.
- **The writable-SD list has arrived:** `sc_sd_writable.answers.json` (29 SD for a single Copy, a Block Copy
  and a decimal Math result, none for Out; 25 SC for Out, none elsewhere), and the 28 picker checks agree
  with it. laddercodec's `WRITABLE_SC` is the same 25; its rules accept all 1,000 SD in each of the three
  fields, so each tightens to the list (a Block Copy needs every address of its destination range listed).
  Then decide whether the sweep grids (`math_sd`, `copy_sd_single`, `copy_sd_block`, `out_sc`) stay.
- **Rows the editor refuses and the code accepts** (samples, to be confirmed by the grids): a DH in a decimal
  Math and a decimal register in a hex one; a RAND bound that is a real or a DF or DH, and equal bounds; SUM over
  TXT.
- **SC gaps (closed, 2026-11-16):** CLICK refuses an Out on an SC address outside `WRITABLE_SC` (SC49, SC163,
  SC310 and 12 more) with OBJ-003 and accepts SC50 and SC162. `WRITABLE_SC` stands; Out, Set and Reset give
  OBJ-003 for it.
- **Ids confirmed:** Out, Set and Reset share one validator: OBJ-004 for a bank, OBJ-008 for a range across
  banks, OBJ-009 for an end below the start, OBJ-012 for the same address at both ends.
- **Ids left None until CLICK answers.** `click_id` is set only where the code records the field's dialog; an
  id that can't be backed stays None. Open:
  - Fill: its pairing and range ends (Copy's OBJ-024, OBJ-008, OBJ-009, OBJ-012?), and a Fill into TXT of more
    than one character (OBJ-023?).
  - Pack and Block Copy, a source range spanning two X/Y modules: OBJ-033 or OBJ-035, which is whose?
  - Receive, one C bit for two status fields (Send's is OBJ-014). A Modbus remote address in hex past FFFEh,
    refused while the address is read (a hex start past FFFDh in a Send has OBJ-010). Whether OBJ-010 is
    also CLICK's id for a Send or Receive that runs past C2000, and for the room left in a DD hex start.
  - The Out variant's bank and not-writable SC refusals.
  - OBJ-002 and OBJ-003: which dialogs give them for an address that is not one and for a number outside its
    bank.
  - The Math formula's ids (OBJ-1001 to OBJ-1015, as the code sets them) and the result's OBJ-004 are read
    from CLICK's own code; the math grids are to confirm each.

## 4. Canonical constants (CLICK)

Addresses are written canonical everywhere, and tested. Constants are written as typed:
- `copy(0ffh,DS1)`, `copy(005,DS1)`, `copy(+5,DS1)`, `fill(0ffh,...)`;
- `DS1==+5`, `DS1==005`, `DF1==1.50`;
- timer `preset=0050`, Search `005`.

Modbus hex addresses are already canonical.

**click's answers for Math and Copy (2026-11-16):**
- Hex Math reads a constant without `h` as hex: `005` and `5` are stored `5h`, `FF` is `FFh`, `1e3` is `1E3h`
  (483), and `1Eh` is refused. laddercodec refuses `005` and `FF`.
- A real is stored as CLICK prints it back, in Math (display and internal) and in a Copy source: `1.50` is
  `1.5`, `1e3` is `1000.0`, `.5` is `0.5`; in a Copy, `1E5` is `100000.0`; in a Math, `1.5E+10` stays as typed
  (not asked in a Copy). laddercodec writes the typed text.
- A Copy source is stored as CLICK reads it: a decimal integer without leading zeros but with a typed `+`
  (`005` is `5`, `+5` stays `+5`); hex with its digits uppercased, leading zeros kept, then a lowercase `h`
  (`0ffh` is `0FFh`, `ffh` is `FFh`, `ABCH` is `ABCh`, `DH` is `Dh`).
- `EH` as a Copy source is stored as the real `0.0`; laddercodec reads it as hex 14.
- `$1` into TXT is accepted and stored `$01`; laddercodec refuses it.
- Decode: a hex Math holding `1E3h`, as CLICK itself stores it, decodes as `raw(Math, ...)`. Decode must read
  what CLICK writes.

**Ruling (Sam, 2026-11-16):**
- The encoder writes the form CLICK's dialog stores wherever its correction keeps the meaning: `1.50` is
  written `1.5`, `1e3` `1000.0`, `.5` `0.5`, `005` `5` in a Copy, `0ffh` `0FFh`, `$1` `$01`, and the rest of
  click's answers. The canonical form is what CLICK stores, not a stripped form: a typed `+` and the leading
  zeros of a hex Copy source are kept.
- Where the dialog's correction would change what the CSV text says, keep refusing and name the fix in the
  message:
  - a hex Math constant without `h` (`005`, `FF`, `1e3`): the settled ruling stands;
  - `EH` as a Copy source: refuse it, and say to write `0Eh` for hex or `0.0` for the real. Today the code
    reads it as hex 14; that changes on this item's branch.

**Question for CLICK:** what does each other dialog turn `005`, `+5`, `0ffh`, `0FFH`, `1.50` and `1.5E+3` into?
Ask in Fill, Compare, Search, Timer and Counter presets, OutVariant presets, drum durations and the For count.

Then make one behaviour-change branch: a test that every writer's output is canonical, the golden `.bin` files
that change, and Sam's paste checks of them.

The same branch writes a constant from a Python value (an int as hex, a float as a Real, a str as text) in
CLICK's canonical form, so pyrung stops spelling constants itself (its `click/ladder/translator.py` does today).
Approved by Sam 2026-11-16.

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
- **Math X/Y range members:** a span of more than two expansion slots, and a Y range that starts in the option
  slot. The fitted rule covers every capture so far.
- **Real constants:** where exactly is the float32 edge (about `3.4028235E+38`)? The Copy source refuses above
  it; Compare accepts `3.5E+38`.
- **Fill with hex above FFFFh:** does the Fill dialog take such a constant, and into which banks? A single
  Copy puts it into DD or CTD only; the code's Fill takes it into any numeric or TXT range.
- **Remote address `h`:** the Send and Receive dialogs let `h` and `1HH` through their span check. What do they
  store? The code refuses both.
- **Number constant into TXT:** a single Copy and a Fill take a decimal or hex constant into a TXT range. What
  does CLICK store in each TXT register? The code accepts it.
- **Text outside printable ASCII:** do the Copy and Fill dialogs take quoted text with a character outside
  space to `~` (an accented letter, a control character)? The code refuses it.
- **Quoted text with an `E`:** the Copy dialog reads such text as a number. Does lowercase `e` do the same, does
  Fill, and what does CLICK keep when such a Copy is pasted? The code accepts and encodes the text as typed.
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
- **`feat/productivity-codec`** stays as a branch for now.

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
  - C000A through a branch;
  - a NOP split;
  - C0206-C0214.
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
