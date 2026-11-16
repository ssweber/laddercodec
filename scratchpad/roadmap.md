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

1. Cruft sweep.
2. The undecoded marker (done).
3. The field-rule restructure (done in #43-#51).
4. Canonical constants, once CLICK has answered.

The stable public API and the SCR blob dataclass fit in wherever they are ready.

## 1. Cruft sweep (nothing)

- **Arc folders.** The closed arc folders under `laddercodec-wt/buildbot/jobs/` can all be deleted: the hold on
  `dllqa/`, `validation-arc/`, `validation/`, `rs2/` and `postrelease/` ended once the expected-diff entries
  were sorted.

## 2. The undecoded marker (done in #38; ClickNick and pyrung follow)

ClickNick drops its stand-in rung for `write_csv`'s marker; pyrung reads the `undecoded(...)` token. The
comment note and `encode()` is under "Later".

## 4. Canonical constants (CLICK)

Addresses are written canonical everywhere, and tested. Constants are written as typed:
- `copy(0ffh,DS1)`, `copy(005,DS1)`, `copy(+5,DS1)`, `fill(0ffh,...)`;
- `DS1==+5`, `DS1==005`, `DF1==1.50`;
- timer `preset=0050`, Search `005`.

Math constants and Modbus hex addresses are already canonical.

**Question for CLICK:** what does each dialog turn `005`, `+5`, `0ffh`, `0FFH`, `1.50` and `1.5E+3` into? Ask
in Copy, Fill, Compare, Search, Timer and Counter presets, OutVariant presets, drum durations and the For count.
This is a job for the sandbox runner (plan item 4), or for Sam.

Then make one behaviour-change branch: a test that every writer's output is canonical, the golden `.bin` files
that change, and Sam's paste checks of them.

## 5. Open CLICK questions (CLICK)

Each is a dialog check or a capture. Until answered, the code keeps the behaviour named.

- **Receive into Y101 or later from a CLICK C, T, CT or SC address.** The count room there may be 0 (every count
  refused). The code uses the slot run (Y101 from T1 gives 16) and, for C, the C room. Check Y101 from C1 with
  17 and with 102 elements, and Y101 from T1 with 1 element.
- **Which X point is the 17th element from X001** in a Send or Receive. CLICK stores only the start and the
  count, so this needs a PLC.
- **Block Copy into SD:** CLICK checks the destination against its list of writable SD addresses. The code
  doesn't, because the list isn't extracted. Ask which SD addresses the dialog refuses.
- **Compare with text in Data A:** the dialog offers = and !=. Which of the two does it save?
- **Coil range over SC:** does Compile refuse an SC range with read-only bits between its ends?
- **Math result into SD9, YD1 and YD0u:** paste each, copy back, and see what is stored.
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

## Waits on another repo

- **Parity test** for the private bank copy, with pyclickplc as a dev-only dependency. It waits for
  pyclickplc's `parse_address` change. It must convert units: XD here is 0-8 plus `u`, in pyclickplc 0-16
  Modbus units.
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

- **Email, Home, Position and Velocity readers:** each has a `from_csv_token` that no CSV token reaches, since
  their registry SPECs have no CSV names. Check whether these readers are dead code, and delete them or wire them.
- **Search's refusal message** says "is a integer value". Fix the article.
- **Hex message without an OBJ id (CLICK):** the refusal for a padded 32-bit constant ("a hex constant above
  FFFFh has at most 8 digits") carries no OBJ id. Find the id CLICK shows, if any.
- **`to_display` refusals** give `FieldError.field` None. They could take the caller's field.
- **Kind-mismatch refusal for junk input:** "<field> takes a decimal integer", for a blank or a stray character,
  states the rule but not what was wrong with the input.
- **Read-only description of each field's rule (Sam, another repo):** banks, constant kinds and limits, for
  callers such as pyrung. Under discussion in the ecosystem plan (`ssweber.github.io/plan/README.md`); not
  repeated here.
- **Copy termination encoding:** the `to_text_term` variant greys out the termination value in the UI, yet the
  blob stores it; the encoding may need revisiting.
- **SCR blob dataclass** (Sam's idea):
  - One frozen dataclass per instruction class: its ordered tags, defaults, array sizes and func code.
  - SCR decode lays the sparse tags it stores over that dataclass to build the full blob. An unknown class
    fails loudly.
  - Proof: the native SCR and clipboard pairs (793 AF blobs, 755 conditions). Today 120 of the 793 differ.
- **Output-column down wire:**
  - Decode would keep the flag and lift the refusal (the layout work left it out). Sam punted it: no one draws one.
  - Until it lands, such a rung becomes an undecoded marker (item 2).
- `layout_check._blank_rows` counts a first row holding only an unpowered NOP as content, so C0202 row numbers
  can be off by one.
- **Clipboard row count too low:** when the program header counts fewer rows than the grid holds, the clipboard
  walk stops at the header's count and the last rung loses its later rows, with no marker (`_walk_grid`'s bound
  and `_decode_single`'s slice).
- **Arguments on a pin that takes none:** `.reset(DS9)` reads as `.reset()`, and the argument is silently
  ignored. Under CSV-as-intent the reader should refuse it.
- **Comment note and encode():** a rung whose comment did not decode has the comment `UNDECODED comment: ...`
  and keeps the original bytes in `comment_rtf`, but encode() writes the note into CLICK. Decide whether
  encode() writes `comment_rtf` back while the comment is still the note, or refuses the rung.
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
- **A stored rung that breaks a dialog rule** (such as an older paste of `DH70 == DS3920`) decodes as raw or an
  unknown condition. If more users hit it, `decode` builds the object from the stored text and attaches a
  finding, and `read_csv` takes an opt-in flag for the writer's self-check. Construction, plain `read_csv` and
  `encode()` stay strict.
