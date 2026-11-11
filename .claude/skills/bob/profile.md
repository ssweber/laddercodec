# BOB profile: laddercodec

Repo-specific rules for the /bob skill. Another repo replaces this file.

## Paths

- Main checkout `C:/Users/Sam/Documents/GitHub/laddercodec`, base branch `dev`. The user
  squash-merges dev into main and cuts releases; never touch main. Do not push any bob/*
  branch. Push dev after every landing (standing approval, user 2026-11-11: "You can push
  always on dev").
- Worktrees `../laddercodec-wt/<name>` on `bob/<name>`; mergeq home `../laddercodec-wt/buildbot`
  (queue, logs, results, `jobs/<id>/{BRIEF,HANDOFF,REVIEW,LEDGER}.md`).
- Current arc doc: `scratchpad/validation/arc.md`. One arc doc: fold rulings and leftovers into
  it, not side notes. Give builders the absolute main-checkout path when it is uncommitted.

## Correctness contract (put in every builder and reviewer brief)

- Match what CLICK Programming Software writes and accepts. Ground truth, in order: native
  captures (`tests/fixtures/`, `clicknick-rung save` copy-backs), paste checks recorded in
  `verify_progress.log`, then CLICK v4.00's own files under
  `C:/Program Files (x86)/AutomationDirect/CLICK Ver4.00` (DLLs, `SC_ErrorList.ini`,
  `SC_InstructionSet.ini`, `Help/Content/*.htm`). Never edit a recorded expectation to fit
  the code.
- Those AutomationDirect files are not ours: read them, quote short facts, never commit dumps
  of them (the repo is public; `scratchpad/click-v4/.gitignore` shows what stays out).
- No DLL addresses (`0x1000xxxx`, `@1000xxxx`, offsets into a CLICK DLL) in committed code,
  tests or docs (user ruling 2026-11-11). Committed citations name the evidence kind and a
  public reference: the OBJ-xxx error id, a Help topic (CLxxx), a capture file, an arc.md
  ruling, or `DLL: <name>.dll, <dialog/field>` without an address. Exact addresses go to the
  private map `../laddercodec-wt/buildbot/jobs/dllqa/ADDRESSES.md`, keyed by file and rule.
- The encoder writes bytes from verified formulas. A change to an encoded byte layout or a
  golden `.bin` needs a paste check in CLICK by the user; the builder names every changed
  golden and BOB batches them into one ground-truth request.
- Round trip holds: decode(encode(x)) == x, clipboard decode and SCR decode (`decode_program`)
  agree, and a blob we can't model decodes as `raw(...)`, never as a different instruction.
- Field rules (what a CLICK dialog refuses, the OBJ-xxx errors) raise on construction or
  encode. Syntax Check rules (C-codes; CLICK still saves the project) do not raise: they
  belong to a separate check or to pyrung, per the arc doc.
- Zero runtime dependencies. `make` commands only; shell hygiene per the root AGENTS.md (no
  multi-line content inlined in shell commands).
- CHANGELOG (Unreleased) moves with behaviour changes. Docs move only where a user's CSV or
  API use changes, in the tone docs/AGENTS.md sets.

## Train checks

None yet. Every gate stage is light (the whole suite takes about 20 s), so trains gate on
`train` (lint, test, docs).

## Models

- Builders: Opus at `effort: high` for encoder/decoder framing, `_grid.py`, `topology.py`,
  `decode_program.py`, or anything that moves a byte; Sonnet for one instruction family's
  validation, tests-only or docs-only.
- Reviewers: Opus for framing and byte-layout diffs; Sonnet for a single family, tests, docs.
- Cataloguing from CLICK's files (help pages, ini): `bob-investigator`, Sonnet. It cannot
  write outside $TEMP or run Python, so it returns its report as its final message and BOB
  saves it under `jobs/<id>/`. Anything that needs a DLL read (string tables, disassembly via
  `scratchpad/click-v4/*.py`) goes to `bob-reviewer` (bounded scripts under $TEMP) or a
  builder in a scratch worktree, not to an investigator.

## Machine budget

- Up to ~5 builders in parallel. One gate job at a time (the queue serializes it).
- Read a gate's exit code directly, never through a pipe without `pipefail`.

## Ground truth

The user captures rungs in CLICK (`clicknick-rung save`) and paste-checks goldens. Collect
the questions only CLICK can answer (a dialog that may refuse a value, a golden that changed)
and list them in milestone reports, batched.

## Gotcha

Agent `isolation: worktree` may fail here (cwd `documents` vs git `Documents` case mismatch,
as in pyrung): always use `mergeq worktree new` and brief the builder with the path.
