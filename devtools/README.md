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
  and float constants, spaces, ranges, digits beyond Python's 4300-digit `int()` limit). For
  each case it records the constructor's result (`ok` or the exception class), `to_csv()`, the
  blob hash, the CSV writer's result, `encode()` and `decode()` of a rung holding the instance,
  the case read back through the CSV path, and the blob parsed back by the decoder.

Both tools write a step that raises as `!Class` where its result would be, and list the
case's exceptions in order under `errors`, as `[class, message]`. No other value of a case
holds an exception message. Warnings are listed as `<WarningClass>: <message>`: the probe's
writer warnings under `write_warn`, its other warnings under `warn`, and the snapshot's under
`warnings`. A probe case is keyed `<Class>/<baseline>/<field>=<value>`, with the value's
repr; text over 1000 characters is written as its runs (`'0'*5000+'1'`). `--classes A,B` probes
only the classes named; like `--limit`, it is part of the output's scope, so both sides of a
diff need the same.

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
- Error messages in the probe's `errors` are recorded as raised; the snapshot writes the
  fixture root and the `src` path in them as `<fixtures>` and `<src>`.

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

- **Must stay identical (the first tier):** every value of a case (accept or refuse, the
  exception class, the CSV written, the bytes, the decode result), the class of each exception
  in `errors` and of each warning, each name ending in `Error`, `Exception` or `Warning` that
  an exception's message holds, and the set of cases.
- **Listed apart, not a failure:** a case that differs only in the text of a message or a
  warning.

A case whose first tier differs fails the run (exit 1) unless an entry of
[`expected_diff.txt`](expected_diff.txt) allows it. Each line of that file is one entry, its
parts separated by a bar with a space on each side:

```text
<case key> | family=<family> | kind=<a or b> [| keys=<k>,<k>] [| new=<verdict>] | <reason>
```

- The key is a probe, snapshot or dry-run case key, matched whole, with `*` for any run of
  characters other than `/`, `\*` for a star and `\\` for a backslash.
- `family=` names the family branch the entry belongs to: `bits`, `data`, `flow`, `move` or
  `comm`.
- `kind=` is `a` or `b`, below.
- `keys=` names the record keys (`new`, `csv`, `blob`, ...) whose first-tier difference the
  entry allows; without it the entry allows any, and a case added or removed.
- `new=` pins the verdict the entry allows, `ok` or `!<ExceptionClass>`, and binds the whole
  branch record, not only its `new`. For `ok`, the record has no `errors`, `read` and `dec`
  are `=`, and `tag`, when the record has one, does not end in ` None` or `!<Class>`. For
  `!X`, `new` and `read` are `!X`, every class in `errors` is X, `dec` is `None` and `tag`,
  when the record has one, ends in ` None`, since the blob decoder refuses the value. The dry
  run's records hold only the verdict, so there the pin binds that alone.
- The reason states the rule the new verdict follows. Neither the key nor the reason holds
  that separator, and the reason does not start with an option name.

A case goes in only when (a) CLICK shows the old verdict was wrong, or (b) the old code raised
something other than a `FieldError` or `AddressError` for the field value: a crash, not a
verdict. A kind (b) entry needs `new=`: the crash has no verdict to keep, so the entry states
the one that replaces it. `--expected FILE` reads another file. The dry run below reads the
same file.

An entry is judged only where it would be used: on a case whose key it matches and whose first
tier differs. There a kind (b) entry allows the case only when both sides have it, and the
base's `new` and every differing key the base holds record a crash; a key the base lacks is one
the crash left out. When both sides have the case and the base is not such a crash, the entry
is misused: `--tiers` and the dry run list the case and exit 2. An entry that allows no case
is listed as matching no difference, which is never an error: on a branch whose family's change
has not landed, or after it has merged, its entries match nothing.

A family branch that wires in the shared checks:

1. runs the probe and the snapshot on its base and on the branch, as above;
2. runs `identity_diff.py --tiers` on each pair;
3. reads the message-only list, which needs no action;
4. fixes every first-tier difference, or, for a case of kind (a) or (b), adds the case to
   `expected_diff.txt` with its family, in the same commit as the change, with its reason.

The run also lists the entries that matched no difference. An entry stays until its family's
branch has merged; after that, the next branch that touches the file removes it. Never remove
another family's entry because it matches no difference yet: that family's change has not
landed.

## Shared field check dry run

`classify_dryrun.py` compares today's per-field checks with the shared field checks in
`laddercodec.operands.checks`, which no field calls yet. For each field that takes a constant,
and for the coil target, it tries a fixed value list two ways: building the instruction from a
known-good baseline (today), and the field's calls to `check_operand`, `check_constant` or
`check_out_target` with that field's parameters, plus what the family keeps for itself (a
Compare group, a Copy destination, a Search table, a few refusals of its own). Each rule's
docstring states the field's kinds and limits, what the family keeps, and the order of calls
that keeps today's exception class. Cases are keyed as the probe keys them, from the probe's
baselines. It prints every disagreement and the totals per family, and changes nothing:

```bash
uv run python -I devtools/classify_dryrun.py src
```

`DIFFERS` is a verdict that differs; `class` is a refusal with a different exception class;
`expected` is either one that an entry of `expected_diff.txt` allows. The dry run judges an
entry as `--tiers` does, on a disagreeing case only, with today's verdict as the base's `new`
and the shared verdict as the branch's. The run exits 1 on any `DIFFERS` or `class`, and 2 when
an entry is misused on a disagreeing case. Math is left out: its formula
has its own grammar.
