# Editor grids

The grids are lists of cases for CLICK's instruction dialogs: an instruction, a mode and the
text to type in each field. ClickNick's runner (`click_runner.py try`) types each case into the
dialog, presses OK and records whether CLICK accepted it or refused it, with the error box's
code and message. The answers are what laddercodec's field rules are to be tightened to.

## Files

Each grid has a verdicts file beside it, `<grid>.verdicts.json`. The runner reads the grid only.

| Grid | What it holds |
| --- | --- |
| `math_decimal.json`, `math_hex.json` | Math: each bank and pointer form as the result, as an operand (with a constant and alone), as a RAND bound and as a SUM range; every constant spelling as an operand and alone; RAND with equal and reversed bounds; the range functions |
| `copy_single.json` | Single Copy: each bank, pointer form and constant spelling as the source and the destination; each source bank against each destination bank; constants against each bank; text into TXT |
| `copy_block.json` | Block Copy: source ranges, destination banks, bank pairs |
| `copy_pack.json` | Pack: each bit bank against each register bank at 16 and 32 bits (and 1, 2, 17 and 33 for DS and DD); register sources |
| `copy_unpack.json` | Unpack: the same, in the other direction |
| `out.json` | Out: each bank, pointer form and constant as the target; ranges |
| `math_sd.json` | every SD address as the result of a decimal Math |
| `copy_sd_single.json` | every SD address as a single Copy destination |
| `copy_sd_block.json` | every SD address as the start of a Block Copy destination range of two (`DS1..DS2` copied there) |
| `out_sc.json` | every SC address as an Out target |

A case is `{"row", "case", "instruction", "mode", "fields"}`, as the runner reads it. `case` is
unique in its file and stable: it is built from the fields' text. `row` groups the cases that ask
one question (`copy.single.source.banks`). Out has no `mode`. Cases are in a fixed order.

A file takes the runner about 4 seconds a case (see the counts below). The files are split by
dialog and mode so none passes about 2,000 cases, and the sweeps over SD and SC are files of
their own.

| File | Cases | Runner time |
| --- | ---: | ---: |
| `math_decimal.json` | 1,089 | 1.2 h |
| `math_hex.json` | 901 | 1.0 h |
| `math_sd.json` | 1,000 | 1.1 h |
| `copy_single.json` | 911 | 1.0 h |
| `copy_block.json` | 593 | 0.7 h |
| `copy_pack.json` | 598 | 0.7 h |
| `copy_unpack.json` | 586 | 0.7 h |
| `copy_sd_single.json` | 1,000 | 1.1 h |
| `copy_sd_block.json` | 1,000 | 1.1 h |
| `out.json` | 488 | 0.5 h |
| `out_sc.json` | 1,000 | 1.1 h |

## Regenerating

```bash
uv run devtools/editor_grids.py           # write these files
uv run devtools/editor_grids.py --check   # exit 1 if they differ
```

The generator builds the lists from laddercodec's own bank ranges, X/Y slots, pointer banks and
constant kinds, so a new bank or kind changes the grids. `tests/test_editor_grids.py` fails when
the committed files differ from what the generator writes.

## Verdicts

`<grid>.verdicts.json` maps each case's label to what laddercodec's rules say today:
`{"verdict": "accepted"}`, or `{"verdict": "refused", "error", "field", "message"}`. A case is
built as the instruction laddercodec would make from it: Block Copy's destination end is the
start plus the source's length, which CLICK works out itself; Pack and Unpack take the bits or
words form of the bank typed. The verdicts exist to be compared with CLICK's answers case by
case. The test compares the verdict, error and field, not the message.

## CLICK's answers

The runner writes `result.json` with one entry per case under `cases`: the case's own keys, then
`outcome` (`accepted`, `refused` or `other`), `code` and `message` (the error box's), `syntax_check`
and `seconds`. Commit each run's answers beside its grid, as test data. They are CLICK's, and are
never edited to fit the code: when a rule and an answer disagree, the rule changes.
