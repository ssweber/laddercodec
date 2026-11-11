# devtools

## Behaviour-identity checks

A change that must not alter behaviour (a refactor, a move of shared rules) is checked with two
tools. Each imports laddercodec from the `src` directory it is given, so one checkout runs both
the base and the branch:

- `fixture_snapshot.py` decodes every `.bin`, `.bin.gz`, `.scr` and `.tmp` under
  `tests/fixtures` to CSV token text per rung, with sha256 hashes of the CSV writer's rows, of
  the re-encoded bytes (plain and with `show_nicknames=True`) and the `find_v4_only()` result.
  It reads every `.csv` strictly and with `strict=False`, and records the same hashes.
- `operand_probe.py` builds every registered instruction class with one field varied over a
  fixed value list (bank edges, X/Y slots, pointers, padded forms, integer and hex limits, text
  and float constants, spaces, ranges). For each case it records the constructor's result
  (`ok` or the exception class and message), `to_csv()`, the blob hash, the CSV writer's
  result, `encode()` and `decode()` of a rung holding the instance, the case read back through
  the CSV path, and the blob parsed back by the decoder.

Check out the base `src` in a detached worktree outside the repository, run both tools on the
base and on the branch, writing outside the repository, then diff:

```bash
git worktree add --detach "$TEMP/base" <base-sha>

uv run python -I devtools/fixture_snapshot.py "$TEMP/base/src" "$TEMP/snap_base.json"
uv run python -I devtools/fixture_snapshot.py src "$TEMP/snap_branch.json"
uv run python -I devtools/fixture_snapshot.py --diff "$TEMP/snap_base.json" "$TEMP/snap_branch.json"

uv run python -I devtools/operand_probe.py "$TEMP/base/src" "$TEMP/probe_base.json"
uv run python -I devtools/operand_probe.py src "$TEMP/probe_branch.json"
uv run python -I devtools/operand_probe.py --diff "$TEMP/probe_base.json" "$TEMP/probe_branch.json"

git worktree remove "$TEMP/base"
```

The same `src` without a worktree:

```bash
mkdir -p "$TEMP/base"
git archive <base-sha> src | tar -x -C "$TEMP/base"
```

`--diff` prints one line per changed, added (`+`) or removed (`-`) case and exits 1 if there is
any, or if the two files come from different tools. A behaviour-identical change shows
`0 difference(s)` and exits 0. It exits 2 without comparing when the two runs have a different
scope (fixture root or `--limit`), when either lists a refused probe baseline, or when neither
has cases. Run the tools from the branch checkout so both
sides use the branch's fixtures and value lists.

`--limit N` runs at most N cases per class (or the first N fixture files). It is for trying the
tools out: only two full runs prove a change behaviour-identical.

The probe stops if a registered instruction class has no baseline in its `PROBES` table, or if
a class's fields differ from the table's: add the new class or field there first. A baseline the
tree under test refuses is printed and listed in `meta.refused_baselines`; the probe still
writes its output, for inspection, and exits 3, and `--diff` exits 2 on that file. Fix the
baseline in `PROBES` (or the tree) before comparing.

What the tools leave out:

- The CSV bundle path (`parse_bundle`, `parse_csv_file`) is not run.
- The opaque tag fields of `Email` and the motion boxes (`Home`, `Velocity`, `Position`) are
  probed over a short value list.
- Probe baselines are built by the tree under test from literal arguments: a change to a
  default or a derived field shows as a difference in every case of that baseline.
- Error messages in the probe are recorded as raised; the snapshot writes the fixture root and
  the `src` path in them as `<fixtures>` and `<src>`.

Besides the public API, the tools import the family registry in `laddercodec.instructions`
(with `UnknownCondition` and `UnknownInstruction`), `laddercodec.decode.Rung`,
`laddercodec.csv.parser._parse_single_rung_rows`, `laddercodec.csv.converter.convert_rung`,
`laddercodec.csv.writer.decoded_rung_to_rows`, `laddercodec.instructions.raw._decompose_blob`
and `_compose_blob`, and from `laddercodec.model` `AfInstruction`, `ConditionInstruction`,
`PinnedInstruction` and `InstructionType`. A step that renames one of them stops the tools on
that tree.

## Constant classifier dry run

`classify_dryrun.py` compares today's per-field constant checks with
`laddercodec.operands.constants.classify()`, which no field uses yet. For each field that takes
a constant it tries a fixed value list two ways: building the instruction (today), and
`classify()` plus that field's documented kinds and limits (each rule cites its arc.md
question, or the DLL reading it rests on). It prints every disagreement and the totals per
family, and changes nothing:

```bash
uv run python -I devtools/classify_dryrun.py src
```

`DIFFERS` is a disagreement; `DIFFERS?` is one whose rule rests on a DLL reading with no dialog
check; `open` is a value whose rule waits on a question. Addresses are skipped.
