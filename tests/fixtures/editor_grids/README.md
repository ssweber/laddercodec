# Editor grids

The grids are lists of cases for CLICK's instruction dialogs: an instruction, a mode and the
text to type in each field. ClickNick's runner (`click_runner.py try`) types each case into the
dialog, presses OK and records whether CLICK accepted it or refused it, with the error box's
code and message. The answers are what laddercodec's field rules are to be tightened to.

## Files

Each grid has a verdicts file beside it, `<grid>.verdicts.json`. The runner reads the grid only.

| Grid | What it holds |
| --- | --- |
| `preflight.json` | the first case of every row of the Math, Copy, Out and Search grids: each field and state in one short run |
| `risky.json` | the spellings a dialog field may not take as typed, for Math, Copy, Out and Search: empty, a space at either end, a tab, a character outside ASCII, text over 40 characters (128- and 129-character quoted text) |
| `preflight_compare.json`, `risky_compare.json` | the same for Compare |
| `preflight_fill.json`, `risky_fill.json` | the same for Fill |
| `preflight_<dialog>.json`, `risky_<dialog>.json` | the same for each of Timer, Counter, Shift, For and Drum (`preflight_timer.json`, `risky_timer.json` and so on) |
| `math_decimal.json`, `math_hex.json` | Math (without the risky spellings): each bank and pointer form as the result, as an operand (with a constant and alone), as a RAND bound and as a SUM range; every constant spelling as an operand and alone; RAND with equal and reversed bounds; the range functions |
| `copy_single.json` | Single Copy: each bank, pointer form and constant spelling as the source and the destination; each source bank against each destination bank; constants against each bank; text into TXT |
| `copy_block.json` | Block Copy: source ranges, destination banks, bank pairs |
| `copy_pack.json` | Pack: each bit bank against each register bank at 16 and 32 bits (and 1, 2, 17 and 33 for DS and DD); register sources |
| `copy_unpack.json` | Unpack: the same, in the other direction |
| `out.json` | Out: each bank, pointer form and constant as the target; ranges |
| `copy_fill.json` | Fill: each bank, pointer form and constant spelling as the value; each bank as the destination range, with a reversed range, one point and the bank's last address; each value bank against each destination bank; constants against each bank; text and numbers into TXT; hex above FFFFh into each register bank; reals of 7 significant digits and more; ranges in SD |
| `compare.json` | Compare: each bank and pointer form as A and as B; every constant spelling as B, and a constant of each kind as A; each register bank against each register bank and against constants; each operator on numbers, on hex, on two texts, and on hex against a number or a number against text |
| `search.json` | Search: each bank as the table, with its ends; each bank, pointer form and constant as the value; each bank as the result and as the found flag; each operator on numbers, hex and text; the Continuous and One Shot options |
| `timer.json` | Timer: each kind with each unit; Retentive on in each unit, and on an off-delay timer; the preset at 0, 32767, 32768 and -1 in each kind and unit; each constant spelling, bank and pointer form as the preset; each bank as the timer number; the current value typed |
| `counter.json` | Counter: each count type; the preset at 0, -1, 2147483647, 2147483648, -2147483648 and -2147483649 in each type, and at 12 and 13 characters; each constant spelling, bank and pointer form as the preset; each bank as the counter number, with the ends of CT; the current value typed |
| `shift.json` | Shift Register: C1..C8, X001..X008 and Y001..Y008; the ranges of C, X and Y, with a reversed range, one bit and an end past the bank, and one range of each other bank; each bank as the start and as the end |
| `for.json` | For: each constant spelling, bank and pointer form as the number of loops; One Shot on and off |
| `drum.json` | Drum, in Time Base and Event Base: each unit, and a unit on an event drum; a duration of 0, 32767, 32768, 39999, 40000 and -1 in each unit; each constant spelling, bank and pointer form as a duration; 0, 1, 16 and 17 steps and outputs; an output used twice, and the completion flag as an output; each bank as an output, the current step, the elapsed time, the completion flag and an event; jog, and the step number to jump to |

A case is `{"row", "case", "instruction", "mode", "fields"}`, as the runner reads it. A Search
case may add `options`, which maps an option's control id to 1 (on) or 0 (off): `5021` is
Continuous Search and `5022` is One Shot. A case without options leaves both buttons as the
dialog opens them. Both open unchecked. `case` is unique in its file and stable: it is built
from the fields' text. `row` groups the cases that ask one question (`copy.single.source.banks`).
Out has no `mode`. A Compare or Search case has the operator as its `mode`. Cases are in a fixed
order.

A Fill case has the mode `fill`. Its fields have the names that the runner gives the Copy
dialog's fields: `source` is the value, and `destination` to `destination_end` is the range.
The runner does not drive Fill yet, so it refuses to load `copy_fill.json`,
`preflight_fill.json` and `risky_fill.json`.

The runner does not drive Timer, Counter, Shift, For or Drum yet either, so it refuses to load
their files. Until it drives them, a case names everything except a list's item by
laddercodec's names:

- `instruction` is `timer`, `counter`, `shift`, `for` or `drum`.
- `mode` is the kind: `on_delay` or `off_delay` for Timer, `count_up`, `count_down` or
  `count_up_down` for Counter, and `time_drum` or `event_drum` for Drum. Shift and For have no
  mode.
- `fields` are the fields of the laddercodec class: `done`, `accumulator` and `preset` for
  Timer and Counter, `start_bit` and `end_bit` for Shift, and `count` for For. A drum's
  `num_steps` and `num_outputs` are the numbers typed in Number of Steps and Number of
  Outputs. A drum's list fields are named by their index, one for each step or output:
  `outputs[0]` to `outputs[15]`, `presets[0]` to `presets[15]` for each step's duration, and
  `events[0]` to `events[15]` for each step's event. Its other fields are `current_step`,
  `accumulator` (the elapsed time in the step), `completion_flag` and `jump_step`.
- `choices` picks the item of a list by the text that the list shows. The only list is `unit`
  (`ms`, `sec`, `min`, `hour` or `day`), for Timer and Drum.
- `options` sets a check box or radio button by the name of the flag: `retained` for Timer,
  `oneshot` for For, and `jog_enabled` and `jump_enabled` for Drum. Before the first run, the
  ClickNick session maps each option name to the id of its button.

CLICK fills in a timer's or counter's current value when you type its number: TD1 for T1,
and CTD1 for CT1. So a case leaves `accumulator` out. The one case in each of the rows
`timer.accumulator` and `counter.accumulator` types it, to find out whether the dialog takes
it.

Each drum case starts from a drum that laddercodec accepts and changes one field, list or
option. A refusal then names the field that the case changed. A refusal of `num_steps` names
`presets` or `events`, and a refusal of `num_outputs` names `outputs`. When a case changes the
number of steps or outputs, it also fills each step or output that the new number adds.

Compare is a contact, so the runner runs its cases only with `--wire`. Compare's preflight and
risky cases are in `preflight_compare.json` and `risky_compare.json`. Run those with `--wire`
too.

When a field does not read back as typed, the runner records the case as `not_taken` and closes
the dialog with Cancel. Then it goes on to the next case. **Run the preflight and risky files
first.** Preflight tries one case in each row. A field that cannot take text (Out's range end, a
constant or pointer in a range end) then shows up in a short run. The risky spellings are in
files of their own. The other files hold only spellings that the generator expects a field to
read back as typed. Preflight repeats cases of the other files, with the same labels.

The runner takes about 4 seconds a case. The files are split by dialog and mode so none passes
about 2,000 cases. The generator prints the number of cases and the time of each file.

## Regenerating

```bash
make editor-grids                         # write these files, then check them
uv run devtools/editor_grids.py --check   # exit 1 if they differ, messages included
```

The generator builds the lists from laddercodec's own bank ranges, X/Y slots, pointer banks and
constant kinds, so a new bank or kind changes the grids. `tests/test_editor_grids.py` fails when
the committed files differ from what the generator writes. The Fill, Compare, Search, Timer,
Counter, For and Drum grids use the constant spellings of the other grids. They add `0ffh` to
the hex spellings. The Timer, Counter, For and Drum grids also try values of their own, such as
-1 for a timer preset and 39999 for a drum duration.

CLICK has answered the Math, Copy and Out grids. If you change a list that they use, their cases
change, and `tests/test_editor_answers.py` fails because the answers no longer match the grid.
The generator adds the Search cases to `preflight.json` and `risky.json` after the answered
ones. The test compares only the answered dialogs' cases in those two files.

## Verdicts

`<grid>.verdicts.json` maps each case's label to what laddercodec's rules say today:
`{"verdict": "accepted"}`, or `{"verdict": "refused", "error", "field", "message"}`. A case is
built as the instruction laddercodec would make from it: Block Copy's destination end is the
start plus the source's length, which CLICK works out itself; a Copy or Block Copy of TXT
into a number register other than DF takes Copy Character Value (`to_value`), the dialog's
default, since a plain copy is refused; a single Copy of a number constant or a number
register into TXT takes the dialog's default too, Copy Value as text with Suppress zero for
an integer and Real Numbering for a real; Pack and Unpack take the bits or
words form of the bank typed. A Fill case is built as `Fill`, with `source` as the value,
`destination` to `destination_end` as the range and no option set. A Compare case is built as
`CompareContact` with A as `left` and B as `right`. A Search case sets `continuous` when its
options set 5021 to 1, and `oneshot` when they set 5022 to 1.

A Timer or Counter case without `accumulator` is built with the current value that CLICK
assigns: the TD or CTD register with the number of the timer or counter. If that number is
not a T or CT address, the case is built with TD1 or CTD1, so that only the number is
refused. A `count_up_down` case is built as `count_up` with a down input. A Drum case is built
with the number of steps and outputs that `num_steps` and `num_outputs` hold. A field that the
case leaves out is blank. No cell of the pattern is set. A case's `unit` item is built as the
laddercodec unit that it names: `ms` as `Tms`, `sec` as `Ts`, `min` as `Tm`, `hour` as `Th`
and `day` as `Td`. An option that a case sets to 1 is on, and any other option is off.

The verdicts exist to be compared with CLICK's answers case by case. `--check` compares the
messages too; the test compares the verdict, error and field only.

## CLICK's answers

ClickNick's runner drove CLICK Programming Software v4.00's editor, on 2026-11-16, and wrote
`result.json` with one entry per case under `cases`: the case's own keys, then `outcome`
(`accepted`, `refused` or `other`), `code` and `message` (the error box's), `syntax_check`,
`seconds`, `read_back` (each field as the dialog showed it), `limits` (each field's text limit)
and, for an accepted case that was saved, `stored` (the saved rung as laddercodec CSV rows).
Where one OK raised a chain of error boxes, `boxes` lists each box's code and message, and
`code` and `message` are the first box's. The answers sit beside the grids:

| File | What it holds |
| --- | --- |
| `preflight.answers.json`, `risky.answers.json` | the answers to the files of those names (92 and 67 cases) |
| `out.answers.json`, `copy_single.answers.json`, `copy_block.answers.json`, `copy_pack.answers.json`, `copy_unpack.answers.json`, `math_decimal.answers.json`, `math_hex.answers.json` | the answers to the files of those names (477, 900, 661, 615, 603, 1,071 and 883 cases); six Pack cases (33 T, CT or SC bits into DS or DD) hold `boxes`: OBJ-041, then OBJ-024 |
| `receive.answers.json` | 18 Receive cases: a master address in each bank, with function code 01 and 03 (the cases are in the file; the runner's own case file is not kept) |
| `receive_count.answers.json` | 10 Receive cases that set the count (function code 03): a TXT master at count unset, 1, 2, 3, 4, 126, 250 and 252, and a DS master at 1 and 2 (two runs, `rxc1` and `rxc2`). `read_back` holds every field, the count and Slave ID too; for the unset case the count is the 2 the dialog held |
| `pickcheck.answers.json` | 28 cases that check the Address Picker's lists against the dialog |
| `picker_lists.answers.json` | 15 cases from the Address Picker's lists for a hex Math result, Pack's destination and Unpack's destination: an address the list holds is accepted, an SC or SD (or another bank) it leaves out is refused (run `pc1`, with its saves kept) |
| `rule_rows.answers.json` | 3 cases CLICK accepts: a Block Copy of TXT1..TXT2 into TXT11, and a hex Math into YD0 and YD1 (`DH1 + DH2`); run `k1`, with its saves kept |
| `sc_sd_writable.answers.json` | the SC and SD addresses the Address Picker lists, per instruction, field and bank, with the bank tabs it leaves open; 12 fields, 8 of them for a field the picker lists only after another field is filled (`filled`: the source of a Pack or Unpack), and a bank with no list is null |

They are CLICK's, and are never edited to fit the code: when a rule and an answer disagree, the
rule changes. Only the run metadata was changed when they were committed: the absolute paths in
`runs` became the run directories' names, and the PLC's IP address and name became "a PLC
connected to CLICK v4.00". Every case and every answer is as the runner wrote it.

`tests/test_editor_answers.py` compares them with laddercodec's rules: each case is rebuilt with
the generator's builders (Receive with its own, at the count the dialog held where an answer
records one, else 1) and its outcome compared with CLICK's, then the
refusal's `click_id` with CLICK's code (only where the rules give a `click_id`; most refusals have
none yet, and the test records how many codes it compared), then the saved rows of an accepted case
with what `read_csv` makes of them (a `raw(...)` is a difference), then the writable lists with the SC and
SD addresses the rules accept (a field's list holds with the other fields as `filled` gives them; a bank with
no list means the rules accept no address of it). A case with more text than its field's `limits` is skipped: the
runner sets text by WM_SETTEXT, which ignores the limit, so no user can type it. Each difference
is listed in the test with its reason and its roadmap item; the test fails on one that is not
listed and on a listed one that is gone.
