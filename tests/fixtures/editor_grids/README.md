# Editor grids

The grids are lists of cases for CLICK's instruction dialogs: an instruction, a mode and the
text to type in each field. ClickNick's runner (`click_runner.py try`) types each case into the
dialog, presses OK and records whether CLICK accepted it or refused it, with the error box's
code and message. The answers are what laddercodec's field rules are to be tightened to.

## Files

Each grid has a verdicts file beside it, `<grid>.verdicts.json`. The runner reads the grid only.

| Grid | What it holds |
| --- | --- |
| `preflight.json` | the first case of every row of the other grids: each field and state in one short run |
| `risky.json` | the spellings a dialog field may not take as typed: empty, a space at either end, a tab, a character outside ASCII, text over 40 characters (128- and 129-character quoted text) |
| `math_decimal.json`, `math_hex.json` | Math (without the risky spellings): each bank and pointer form as the result, as an operand (with a constant and alone), as a RAND bound and as a SUM range; every constant spelling as an operand and alone; RAND with equal and reversed bounds; the range functions |
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

The runner aborts the whole run when a field does not read back as typed, so **run `preflight.json`
and `risky.json` first**. Preflight tries one case in each row, so a field that cannot take text
(Out's range end, a constant or pointer in a range end) stops a short run. The risky spellings are
in their own file so that one stopping the run costs little. Preflight repeats cases of the other
files, with the same labels.

The runner takes about 4 seconds a case. The files are split by dialog and mode so none passes
about 2,000 cases, and the sweeps over SD and SC are files of their own. The generator prints the
number of cases and the time of each file.

## Regenerating

```bash
make editor-grids                         # write these files, then check them
uv run devtools/editor_grids.py --check   # exit 1 if they differ, messages included
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
case. `--check` compares the messages too; the test compares the verdict, error and field only.

## CLICK's answers

ClickNick's runner drove CLICK Programming Software v4.00's editor, on 2026-11-16, and wrote
`result.json` with one entry per case under `cases`: the case's own keys, then `outcome`
(`accepted`, `refused` or `other`), `code` and `message` (the error box's), `syntax_check`,
`seconds`, `read_back` (each field as the dialog showed it), `limits` (each field's text limit)
and, for an accepted case that was saved, `stored` (the saved rung as laddercodec CSV rows).
The answers sit beside the grids:

| File | What it holds |
| --- | --- |
| `preflight.answers.json`, `risky.answers.json` | the answers to the files of those names (92 and 67 cases) |
| `receive.answers.json` | 18 Receive cases: a master address in each bank, with function code 01 and 03 (the cases are in the file; the runner's own case file is not kept) |
| `pickcheck.answers.json` | 28 cases that check the Address Picker's lists against the dialog |
| `sc_sd_writable.answers.json` | the SC and SD addresses the Address Picker lists, per instruction, field and bank, with the bank tabs it leaves open |

They are CLICK's, and are never edited to fit the code: when a rule and an answer disagree, the
rule changes. Only the run metadata was changed when they were committed: the absolute paths in
`runs` became the run directories' names, and the PLC's IP address and name became "a PLC
connected to CLICK v4.00". Every case and every answer is as the runner wrote it.

`tests/test_editor_answers.py` compares them with laddercodec's rules: each case is rebuilt with
the generator's builders (Receive with its own) and its outcome compared with CLICK's, then the
refusal's `click_id` with CLICK's code (only where the rules give a `click_id`; most refusals have
none yet, and the test records how many codes it compared), then the saved rows of an accepted case with what
`read_csv` makes of them (a `raw(...)` is a difference), then the writable lists with the SC and
SD addresses the rules accept. A case with more text than its field's `limits` is skipped: the
runner sets text by WM_SETTEXT, which ignores the limit, so no user can type it. Each difference
is listed in the test with its reason and its roadmap item; the test fails on one that is not
listed and on a listed one that is gone.
