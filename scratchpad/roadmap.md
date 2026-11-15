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
- **Less code first.** Deletion and consolidation come before new features. A shared mechanism stays only if it
  removes more lines than it adds.

## Order

1. Cruft sweep.
2. The undecoded marker.
3. The field-rule restructure.
4. Canonical constants, once CLICK has answered.

The stable public API and the SCR blob dataclass fit in wherever they are ready.

## 1. Cruft sweep (nothing)

- **Arc folders.** Delete the closed ones under `laddercodec-wt/buildbot/jobs/`, except `dllqa/`,
  `validation-arc/`, `validation/`, `rs2/` and `postrelease/`. Those hold until the expected-diff entries (item
  3) are sorted.

## 2. The undecoded marker (nothing; ClickNick and pyrung follow)

Ruled in the plan, "Who owns what", last bullet. Sam accepted the form proposed after 0.4.0.

- **The unit is the rung.** A rung that fails becomes one marker rung:
  - comment `UNDECODED: rung N, row R: <error>`, then the rung's own comment if that decoded;
  - one row, wired from the rail, ending in a new `Undecoded(error, rung, row, column, stop)` instruction.
    `stop` is `end` in the main program and `return` in a subroutine, and the row is unconditional.
- **Behaviour.**
  - CSV token `undecoded("...")`: `write_csv` writes it and `read_csv` reads it back.
  - `check()` reports it as a Finding.
  - `encode()` refuses it, so it is never pasted into CLICK.
  - `decode` and `decode_program` warn, and `Program` lists the undecoded rungs.
- **A framing error in the SCR walk** (a truncated record, or a topology or section it can't parse): the rungs
  before it decode, one marker stands for "rung N to the end", and decoding stops.
- **Clipboard `decode()`:** the same per-rung marker; the grid's fixed stride lets the later rungs read.
- **`write_csv` of a rung it cannot write** (an `UnknownCondition`, which has no token) writes the marker.
  That replaces ClickNick's stand-in rung.
- **Producers today:** the output-column down wire (the punted fix, below) and framing errors. Also check
  whether the SCR AF down wire past `logical_rows`, which is ignored silently today, should be a marker.
- **Docs and CHANGELOG** say what the marker is and why it stops execution.

## 3. Field-rule restructure (nothing)

Ruled in the plan, "Who owns what". Steps 0-2 landed before 0.4.0: the identity tools, `operands/` with the
guard ratchet, and the unwired `classify()` with its dry run. There is no engine pilot; the end state is plain
shared functions.

- **Identity has two tiers.**
  - These stay identical: accept or refuse, exception class, CSV written, bytes, decode result.
  - Message wording may change; the changes are listed for review.
  - Give `devtools/identity_diff.py` a mode that compares class and verdict, and lists message changes apart.
- **Expected-diff file.** Rerun `devtools/classify_dryrun.py` on main (it last gave 7
  disagreements and 251 open) and sort the entries, then free the held folders.
  - Fill into TXT takes one character of text, while `classify()` takes 1-128. This is a real dialog
    difference, so it becomes a parameter of the shared check.
  - Compare `3.5E+38` is accepted beyond float32. Where CLICK's exact edge lies has not been checked, so keep
    today's behaviour as a parameter until it is.
  - Copy termination code `none` is a keyword, not a constant. That is an error in the dry run; fix the dry
    run.
  - The 154 Math cases stay out: Math has its own grammar.
- **Provenance out of src.**
  - Delete `operands/sources.py` and `FieldError.source`. `dll_address()` moves into
    `tests/test_no_dll_addresses.py`.
  - Delete the citation comments: 142 lines in 16 files.
  - The OBJ ids in messages stay.
- **Per family** (bits, data, flow, move, comm):
  - Replace the private regexes and bank sets with the shared functions (`check_operand`, `check_constant`,
    `check_address`, `check_flag`, `check_out_target`), and shrink the guard allowlists.
  - Each family must delete more lines than it adds.
- **`FieldError.field` explicit everywhere.**
  - Pass `field=` at every raise site (198 today; only 5 pass it, and about 45 come out None). Then drop the
    parsing of `.field` from the message text, and add a guard test.
  - A refusal across two fields names the instruction (`field="CompareContact"`).
  - `.obj` is not promised.
  - `csv/converter.py:365` drops `.field` when it re-raises as `ConvertError`.
- **Locations for pyrung.** `read_csv` errors carry no rung, row or column. pyrung's export check (plan,
  "pyrung takes laddercodec") needs one.
- **One rule for flag fields.**
  - Every `bool` field on an instruction carries an `Annotated[bool, FLAG]` marker.
  - One base-class `__post_init__` loop checks every marked field.
  - A guard test fails on an unmarked `bool`.
  - Keep it only if it stays plain data plus one function.
- **Recheck on main**, each against the operand probe, and fix or delete:
  - every operand field the probe finds surprising;
  - the move family's double `check_constant` call.

## 4. Canonical constants (CLICK; after item 3)

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
  it; Compare accepts `3.5E+38` (item 3).
- **Quoted text with an `E`:** the Copy dialog reads such text as a number. Does lowercase `e` do the same, does
  Fill, and what does CLICK keep when such a Copy is pasted? The code accepts and encodes the text as typed.
- **Captures for motion and Email:** native Home, Velocity and Position, one per mode, and an Email with To,
  Cc, Bcc, Subject and both body modes filled, each field a distinct value. Their field maps are inferred and
  stay `raw(...)`.
- **ASCII Send and Receive** (static, dynamic, fixed, variable) and Home, Velocity, Position and Email with every
  status field set to a distinct address: native blobs to model later.
- **Other non-pinned boxes in a compact OR layout:** `read_csv` lays them out as it does stacked 2-row Copies,
  which CLICK's post-check layout confirmed. Capture one more shape (Math, Search or a timer under an OR).

## Required checks (Sam)

Switch `main`'s ruleset to require only `ci` and the docs `build`. Until then the test matrix's Python versions
stay as they are: each is a required check by name.

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
