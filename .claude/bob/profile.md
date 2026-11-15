# BOB profile: laddercodec

Repo-specific rules for the `bob` plugin's skill. The plugin's own rules (merge on green, the
release is the user's, PR text) apply as written; this file adds laddercodec's.

## Paths

- Main checkout `C:/Users/Sam/Documents/GitHub/laddercodec`, branch `main`, always releasable.
  No merge queue: this repo has no `[queue]` section in `config.toml`.
- Worktrees: `R worktree new <name> --branch <type>/<name>` (`feat/`, `fix/`, `chore/`,
  `refactor/`, `docs/`), which makes `../laddercodec-wt/<name>` from `origin/main`.
- `<jobs>` is `../laddercodec-wt/buildbot/jobs`: one folder per job (`BRIEF.md`, `HANDOFF.md`,
  `REVIEW.md`, `PR.md`) and the arc's `LEDGER.md`.
- Open work: `scratchpad/roadmap.md`, the one roadmap. Fold rulings and leftovers into it, not
  side notes. An item labelled **Sam**, **CLICK** or **PLC** there waits on the user.

## Correctness contract (put in every builder and reviewer brief)

- Match what CLICK Programming Software writes and accepts. Ground truth, in order: native
  captures (`tests/fixtures/`, `clicknick-rung save` copy-backs), paste checks recorded in
  `verify_progress.log`, then CLICK v4.00's own files under
  `C:/Program Files (x86)/AutomationDirect/CLICK Ver4.00` (DLLs, `SC_ErrorList.ini`,
  `SC_InstructionSet.ini`, `Help/Content/*.htm`). Never edit a recorded expectation to fit
  the code.
- Those AutomationDirect files are not ours: read them, never commit dumps or excerpts of them
  (the repo is public).
- Everything written (code, tests, docs, comments, commit messages, PR text) says what a CLICK
  rule is, never where it came from: no DLL names or addresses, Help page ids, question ids,
  dated dialog checks or private report names. CLICK's own error ids (OBJ-nnn, C0nnn) are fine.
  What is still in doubt goes in `scratchpad/roadmap.md`. Still on main and not to be copied:
  `laddercodec/operands/sources.py` (`Src`, `SrcKind`), `FieldError.source`, and the AGENTS.md
  line on `Src`; roadmap item 3 removes them. The DLL verifier's brief lives outside git
  (`<jobs>/dllqa/VERIFY_BRIEF.md`), its tooling in `../laddercodec-wt/buildbot/tools/click-v4/`.
- The encoder writes bytes from verified formulas. A change to an encoded byte layout or a
  golden `.bin` needs a paste check in CLICK by the user: the builder names every changed
  golden, BOB batches them into one ground-truth request, and the PR stays open until the user
  has pasted them (`make test` fails on a golden with no `: worked` entry).
- Round trip holds: decode(encode(x)) == x, clipboard decode and SCR decode (`decode_program`)
  agree, and a blob we can't model decodes as `raw(...)`, never as a different instruction.
- Field rules (what a CLICK dialog refuses, the OBJ-xxx errors) raise on construction or
  encode. Syntax Check rules (C-codes; CLICK still saves the project) do not raise: they
  belong to `check()` or to pyrung, per the roadmap.
- A CSV states the circuit, not keypresses: refuse a value whose meaning CLICK's dialog would
  change (hex Math `DH1 + 7`), never rewrite it silently.
- Zero runtime dependencies. `make` commands only; shell hygiene per the root AGENTS.md (no
  multi-line content inlined in shell commands).
- Every PR carries its CHANGELOG line (Unreleased) when users see a change. Docs move only
  where a user's CSV or API use changes, in the tone docs/AGENTS.md sets.

## Gate

- Local, in the builder's worktree, before every hand-back: `make lint` (it rewrites files:
  commit them), `make test`, `make docs-build`. The whole suite takes about 20 s.
- CI on every PR into `main`: `ci.yml` (read-only lint and `pytest` on Linux, Python 3.11 to
  3.14, summed up by the `ci` check) and `docs.yml`'s `build`. `main` requires them, on a
  branch that is up to date. CI does not run on Windows, so the local gate is the only check
  of the Windows paths.
- Don't change the Python versions in the test matrix until the ruleset requires only `ci`:
  each version is a required check by name.

## Pre-PR checks

None yet.

## Models

- Builders: Opus at `effort: high` for encoder/decoder framing, `_grid.py`, `topology.py`,
  `decode_program.py`, or anything that moves a byte; Sonnet for one instruction family's
  validation, tests-only or docs-only.
- Reviewers: Opus for framing and byte-layout diffs; Sonnet for a single family, tests, docs,
  CI config.
- Cataloguing from CLICK's files (help pages, ini): `bob:bob-investigator`, Sonnet. It cannot
  write outside $TEMP or run Python, so it returns its report as its final message and BOB
  saves it under `<jobs>/<id>/`. Anything that needs a DLL read (string tables, disassembly via
  `../laddercodec-wt/buildbot/tools/click-v4/*.py`) goes to `bob:bob-reviewer` (bounded
  scripts under $TEMP) or a builder in a scratch worktree, not to an investigator.

## Machine budget

- Up to ~5 builders in parallel (`targeted_slots = 5`).
- Read a command's exit code directly, never through a pipe without `pipefail`.

## Ground truth

The user captures rungs in CLICK (`clicknick-rung save`) and paste-checks goldens. Collect
the questions only CLICK can answer (a dialog that may refuse a value, a golden that changed)
and list them in milestone reports, batched.

## Gotcha

Agent `isolation: worktree` may fail here (cwd `documents` vs git `Documents` case mismatch):
always cut the worktree with `R worktree new` or `git worktree add`, and brief the builder with
the path.
