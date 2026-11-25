# BOB profile: laddercodec

Repo-specific rules for the `bob` plugin's skill. The plugin's own rules (merge on green, the
release is the user's, PR text) apply as written. This file adds laddercodec's.

## Paths

- Main checkout `C:/Users/Sam/Documents/GitHub/laddercodec`, branch `main`, always releasable.
  No merge queue: this repo has no `[queue]` section in `config.toml`.
- Worktrees: `R worktree new <name> --branch <type>/<name>` (`feat/`, `fix/`, `chore/`,
  `refactor/`, `docs/`), which makes `../laddercodec-wt/<name>` from `origin/main`.
- `<jobs>` is `../laddercodec-wt/buildbot/jobs`: one folder per job (`BRIEF.md`, `HANDOFF.md`,
  `REVIEW.md`, `PR.md`) and the arc's `LEDGER.md`.
- Open work is in `scratchpad/roadmap.md`, the one roadmap. Fold rulings and leftovers into it,
  not into side notes. An item labelled **Sam** or **PLC** there waits on the user. An item
  labelled **CLICK** waits on the sandbox runner or the user.

## Correctness contract (put in every builder and reviewer brief)

- Match what CLICK Programming Software writes and accepts. Ground truth, in order of
  authority:
  1. Native captures (`tests/fixtures/`, `clicknick-rung save` copy-backs).
  2. Paste checks recorded in `verify_progress.log`.
  3. CLICK v4.00's own files under `C:/Program Files (x86)/AutomationDirect/CLICK Ver4.00`
     (DLLs, `SC_ErrorList.ini`, `SC_InstructionSet.ini`, `Help/Content/*.htm`).

  Nobody edits a recorded expectation to fit the code, and nobody edits CLICK's recorded
  answers.
- Those AutomationDirect files are not ours. Read them. Never commit dumps or excerpts of them,
  because the repo is public.
- Everything you write (code, tests, docs, comments, commit messages, PR text) says what a
  CLICK rule is. It never says where the rule came from. Leave out DLL names or addresses, Help
  page ids, question ids, dated dialog checks and private report names. CLICK's own error ids
  (OBJ-nnn, C0nnn) are fine. Put what is still in doubt in `scratchpad/roadmap.md`. The DLL
  verifier's brief lives outside git (`<jobs>/dllqa/VERIFY_BRIEF.md`), and its tooling is in
  `../laddercodec-wt/buildbot/tools/click-v4/`.
- The encoder writes bytes from verified formulas. A change to an encoded byte layout or to a
  golden `.bin` needs a paste check in CLICK by the user. The builder names every changed
  golden. BOB batches them into one ground-truth request. The PR stays open until the user has
  pasted them. `make test` fails on a golden with no `: worked` entry.
- The round trip holds: decode(encode(x)) == x. A blob that we can't model decodes as
  `raw(...)`, never as a different instruction.
- Paired implementations must agree. A reviewer checks each pair that a diff touches:
  - clipboard decode and SCR decode (`decode_program`);
  - each family's `from_tags` (blob parser) and its CSV parser (`parse_csv_call`);
  - the encoder and the CSV writer.

  When a rule changes, grep every family's parser, CSV writer and validator for anything that
  still models the old behaviour.
- A fine edge of the format (a byte, a boundary value, a refused form) gets a test.
- Field rules (what a CLICK dialog refuses, the OBJ-xxx errors) raise on construction or on
  encode. Syntax Check rules (C-codes) do not raise, because CLICK still saves the project.
  They belong to `check()` or to pyrung, as the roadmap says.
- A CSV states the circuit, not keypresses. Refuse a value whose meaning CLICK's dialog would
  change (hex Math `DH1 + 7`). Never rewrite it silently.
- Zero runtime dependencies. Use `make` commands only. Follow the shell hygiene in the root
  AGENTS.md: inline no multi-line content in shell commands.
- Every PR carries its CHANGELOG line (Unreleased) when users see a change. How to write it:
  - State the change against the last release, not against `main`. The last release is the
    newest tag, `v0.5.1` at the time of writing. Read its code or docs with
    `git show v0.5.1:<path>`.
  - When the change revises behaviour that an Unreleased entry already describes, rewrite that
    entry. Do not add one that contradicts it. A rename also rewrites every earlier Unreleased
    entry that names the old field.
  - Never write "where it was X" for an X that no release had.
  - Say when the error class that a caller catches changes.
  - Docs change only where a user's CSV or API use changes. Follow `docs/AGENTS.md`: guides say
    how to use the library, and `docs/internals/` holds the binary format.
  - Sentence style follows the Writing section of the root `AGENTS.md`.

## Gate

- Before every hand-back, run these locally in the builder's worktree: `make lint`, `make test`
  and `make docs-build`. `make lint` rewrites files, so commit them. The whole suite takes about
  20 s.
- CI runs on every PR into `main`. It runs `ci.yml` (read-only lint and `pytest` on Linux,
  Python 3.11 to 3.14, summed up by the `ci` check) and `docs.yml`'s `build`. `main` requires
  both, on a branch that is up to date. CI does not run on Windows, so the local gate is the
  only check of the Windows paths.

## Pre-PR checks

None yet.

## Models

- Builders: Opus at `effort: high` for encoder/decoder framing, `_grid.py`, `topology.py`,
  `decode_program.py`, or anything that moves a byte; Sonnet for one instruction family's
  validation, tests-only or docs-only.
- Reviewers: Opus for framing and byte-layout diffs; Sonnet for a single family, tests, docs,
  CI config.
- Cataloguing from CLICK's files (help pages, ini): `bob:bob-investigator`, Sonnet. It cannot
  write outside $TEMP or run Python. It returns its report as its final message, and BOB saves
  it under `<jobs>/<id>/`. Send anything that needs a DLL read (string tables, disassembly via
  `../laddercodec-wt/buildbot/tools/click-v4/*.py`) to `bob:bob-reviewer` (bounded scripts under
  $TEMP) or to a builder in a scratch worktree. Do not send it to an investigator.

## Machine budget

- Run up to about 5 builders in parallel. `targeted_slots = 3` bounds the test runs that all
  agents (builders and reviewers) start at once. Each run is capped at 8 GB.
- Read a command's exit code directly. Never read it through a pipe without `pipefail`.

## Ground truth

The user captures rungs in CLICK (`clicknick-rung save`) and paste-checks goldens. Collect the
questions that only CLICK can answer (a dialog that may refuse a value, a golden that changed)
and list them in milestone reports, batched.

## Gotcha

Agent `isolation: worktree` may fail here, because the cwd says `documents` and git says
`Documents`. Always cut the worktree with `R worktree new` or `git worktree add`, and give the
builder the path in its brief.
