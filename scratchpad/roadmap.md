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

Done: the cruft sweep, the undecoded marker (#38) and the field-rule restructure (#43-#51).

Sam's direction of 2026-11-16: pyrung's CLICK validation moves onto laddercodec first, ahead of its export and
import. pyrung builds laddercodec's objects and turns each refusal into a finding; its own bank tables go.

1. The field error pyrung reads. pyrung's validation waits on it and on a release with it.
2. Decoding that does not depend on the checks.
3. Field rules tightened to the CLICK grids, as the grids arrive.
4. Canonical constants, once CLICK has answered (the runner is asking now). It can run beside 1-3.

The stable public API and the SCR blob dataclass fit in wherever they are ready. pyrung's export needs come
later (below).

laddercodec refuses what CLICK's editor refuses, plus what breaks the encoding or crashes CLICK on a paste. A
rule that rests on what a PLC does stays in pyrung.

## 1. The field error pyrung reads (nothing; Sam releases, then pyrung follows)

pyrung learns what a field takes by building the object and reading the error. Accepted by Sam 2026-11-16.
Not built: a rule-description API (`field_rules(Copy)["source"]`), and a public way to build an instruction
without its checks (pyrung's conformance probes use `raw(...)`).

- **Every refusal.** The constructor raises one `FieldError` whose `.errors` holds every refusal, itself first,
  so `except FieldError` in the decoders is unchanged. A check that depends on an earlier field
  (`Timer.current`'s number against `Timer.done_bit`) is skipped when that field was refused. A Timer with a
  wrong done bit and a preset of 40000 gives two.
- **The Math formula parser** stops at its first error; collecting more there is the costly part. If a first
  version leaves it out, tell Sam what that loses (pyrung reports up to six findings on one Math) and let him
  choose.
- **Uniform `.field`.** Always `Class.attr`, with `[i]` for an element. Today the shared checks take one `name`
  for both the message and `.field`, which gives `Receive dest`, `Copy.source pointer` and `Math.expression`
  for every formula error: split the label from the field. A refusal about a pair (bare `CompareContact`)
  names both in `.fields`. `to_display`'s refusals, whose field is None today, take the caller's field.
- **A stable `.reason`** from a small fixed set the shared checks own (`bank`, `pointer`, `kind`, `range`,
  `not_writable`, `flag`, ...), plus `.click_id` (`OBJ-005`) where CLICK has one. pyrung's finding codes
  separate reasons on one field (`Timer.setpoint`: wrong bank, too large, a pointer). Messages stay free text
  and are not API.
- **Every class.** Then tell Sam it is on `main`. The next release waits for it and carries it with everything
  since v0.4.0, the undecoded marker included; the release is Sam's. pyrung's validation follows straight
  after its `Rung` to `rung` rename.

## 2. Decoding that does not depend on the checks (nothing)

A stored instruction that breaks a dialog rule (such as an older paste of `DH70 == DS3920`) decodes as raw or an
unknown condition today. Before any rule is tightened, `decode` builds the object from what is stored and
attaches a finding; otherwise every tightened rule turns instructions in real projects into raw. `read_csv`
takes an opt-in flag for the writer's self-check. Construction, plain `read_csv` and `encode()` stay strict.

## 3. Field rules tightened to the CLICK grids (CLICK)

The runner tries whole grids, not samples: every bank and constant kind in each dialog field. Its answers are
committed here as test data, which makes these tests the one place CLICK's field rules are recorded. No rule is
written from the 17 sampled rows in `ssweber.github.io/plan/rule-decisions.md`.

- **Case lists (Sam, 2026-11-16):** laddercodec writes them, since it knows how each field is modelled (banks,
  constant kinds, modes), in the shape of ClickNick's `devtools/editor_cases.json`. click's runner runs them
  and returns the answers; cases and answers are committed as test data. The runner's `try` drives Math, Copy
  (single, block, pack, unpack) and Out today, about 4 seconds a case, so those grids run first. click is
  adding a run that resumes and more dialogs, Receive first.
- **A writable-SD list,** taken once from CLICK's DLLs, help or a grid, not copied from pyrung or pyclickplc.
  The sampled rows: the editor refuses a single Copy into SD1, a Math result into SD1, and a Block Copy into
  SD1 or into SD29..SD30 (every address in the destination range must be writable); it accepts SD29 and
  SD31..SD32.
- **Rows the editor refuses and the code accepts** (samples, to be confirmed by the grids): a DH in a decimal
  Math and a decimal register in a hex one; a RAND bound that is a real or a DF or DH, and equal bounds; SUM over
  TXT.
- **SC gaps:** check a point in a gap of `WRITABLE_SC` (SC163, SC310); click has been asked.

## 4. Canonical constants (CLICK)

Addresses are written canonical everywhere, and tested. Constants are written as typed:
- `copy(0ffh,DS1)`, `copy(005,DS1)`, `copy(+5,DS1)`, `fill(0ffh,...)`;
- `DS1==+5`, `DS1==005`, `DF1==1.50`;
- timer `preset=0050`, Search `005`.

Math constants and Modbus hex addresses are already canonical.

**Question for CLICK:** what does each dialog turn `005`, `+5`, `0ffh`, `0FFH`, `1.50` and `1.5E+3` into? Ask
in Copy, Fill, Compare, Search, Timer and Counter presets, OutVariant presets, drum durations and the For count.
click's runner (job B) is saving and decoding what CLICK stores for `005`, `+5`, `-5`, `0ffh`, `1.50`, `1e3` and
`.5` in Math and Copy; the other dialogs still need asking.

Then make one behaviour-change branch: a test that every writer's output is canonical, the golden `.bin` files
that change, and Sam's paste checks of them.

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
  accepts them is item 3's grid; this is what a paste stores.)
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
- A writer for `main.csv` plus `subroutines/` (`csv/bundle.py` only reads).
- Later, a whole-program check: loop nesting, nested calls, the 8,000-step limit and a step estimate. See the
  Syntax Check rules item in Later.

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
