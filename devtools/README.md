# devtools

## Behaviour-identity checks

A change that must not alter behaviour (a refactor, a move of shared rules) is checked with two
tools. Each imports laddercodec from the `src` directory it is given, so one checkout runs both
the base and the branch:

- `fixture_snapshot.py` decodes every `.bin`, `.bin.gz`, `.scr` and `.tmp` under
  `tests/fixtures` to CSV token text per rung, with sha256 hashes of the CSV writer's rows and
  of the re-encoded bytes. It reads every `.csv` and records a sha256 of its encoded bytes.
- `operand_probe.py` builds every registered instruction class with one field varied over a
  fixed value list (bank edges, X/Y slots, pointers, padded forms, integer and hex limits, text
  and float constants, spaces, ranges). For each case it records the constructor's result
  (`ok` or the exception class and message), `to_csv()`, the blob hash, the CSV writer's
  result, the case read back through the CSV path, and the blob parsed back by the decoder.

Run both on the base and on the branch, writing outside the repository, then diff:

```bash
uv run python -I devtools/fixture_snapshot.py ../laddercodec/src "$TEMP/snap_base.json"
uv run python -I devtools/fixture_snapshot.py src "$TEMP/snap_branch.json"
uv run python -I devtools/fixture_snapshot.py --diff "$TEMP/snap_base.json" "$TEMP/snap_branch.json"

uv run python -I devtools/operand_probe.py ../laddercodec/src "$TEMP/probe_base.json"
uv run python -I devtools/operand_probe.py src "$TEMP/probe_branch.json"
uv run python -I devtools/operand_probe.py --diff "$TEMP/probe_base.json" "$TEMP/probe_branch.json"
```

`--diff` prints one line per changed, added (`+`) or removed (`-`) case and exits 1 if there is
any. A behaviour-identical change shows `0 difference(s)`. Run the tools from the branch
checkout so both sides use the branch's fixtures and value lists.

The probe stops if a registered instruction class has no baseline in its `PROBES` table, or if
a class's fields differ from the table's: add the new class or field there first. `--limit N`
runs at most N cases per class (or N fixture files).
