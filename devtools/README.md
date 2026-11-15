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
that tree. `convert_rung` returns a list of `Rung`, one per CLICK rung the CSV rung lays out
to; on a tree before the CSV layout it returns a `(logical_rows, conditions, instructions,
comment)` tuple, and `operand_probe.py` takes either.

### Two tiers and the expected-diff file

A change that moves a rule into a shared check may reword a message but must keep every
verdict. `identity_diff.py --tiers` compares two outputs of the same tool with that split:

```bash
uv run python -I devtools/identity_diff.py --tiers "$TEMP/probe_base.json" "$TEMP/probe_branch.json"
```

- **Must stay identical:** accept or refuse, the exception class, the CSV written, the bytes,
  the decode result, and the set of cases. The tools record an exception as
  `!Class: message`; the comparison cuts each one to `!Class`.
- **Listed apart, not a failure:** a case that differs only in a message's wording.

A case that differs in the first tier fails the run (exit 1) unless
[`expected_diff.txt`](expected_diff.txt) lists it. Each line of that file is
`<case key> | <reason>`: the key is a probe or snapshot case key, matched whole, with `*` for
any run of characters; the reason states the rule the new verdict follows. A case goes in only
when CLICK shows the old verdict was wrong. `--expected FILE` reads another file.

A family branch that wires in the shared checks:

1. runs the probe and the snapshot on its base and on the branch, as above;
2. runs `identity_diff.py --tiers` on each pair;
3. reads the message-only list, which needs no action;
4. fixes every first-tier difference, or, where CLICK shows the old verdict was wrong, adds the
   case to `expected_diff.txt` in the same commit as the change, with its reason.

The run also lists the entries that matched no difference. An entry describes a change against
the base it was made on; once its branch has landed, the next branch that touches the file
removes it.

## Shared field check dry run

`classify_dryrun.py` compares today's per-field checks with the shared field checks in
`laddercodec.operands.checks`, which no field calls yet. For each field that takes a constant,
and for the coil target, it tries a fixed value list two ways: building the instruction from a
known-good baseline (today), and the field's calls to `check_operand`, `check_constant` or
`check_out_target` with that field's parameters, plus the pairing the family keeps for itself (a
Compare group, a Copy destination, a Search table). Each rule's docstring states the field's
kinds and limits, and the order of calls that keeps today's exception class. It prints every
disagreement and the totals per family, exits 1 on any, and changes nothing:

```bash
uv run python -I devtools/classify_dryrun.py src
```

`DIFFERS` is a verdict that differs; `class` is a refusal with a different exception class.
Math is left out: its formula has its own grammar.
