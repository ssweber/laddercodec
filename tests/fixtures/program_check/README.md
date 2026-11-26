# Program check fixtures

`tests/test_program_check.py` runs `check()` on these fixtures as a `Project`.

## click/: CLICK's answers

ClickNick's runner pasted each case into a new CLICK v4.00 project, with a C2-03CPU and no PLC, and ran
Syntax Check. Each case folder holds these files, as the runner recorded them:

- `program/`: the bundle that was pasted, as `read_bundle()` reads it.
- `pasted/`, `info/`, `checked/`: CLICK's `Scr*.tmp` files from three saves, and the CSVs that laddercodec
  0.5.0 decoded from them. `pasted` is the save after the paste. `info` comes after Local Program
  Information, and `checked` after Syntax Check. Case q8c runs Syntax Check before Local Program Information.
- `<case>_errors.txt`: the Syntax Check output, as CLICK printed it.
- `program_size.txt`: the step count in CLICK's status bar at each save.

`Scr1.tmp` is Main Program. `Scr2.tmp` is the first subroutine that was added, and so on. In q5a, Sub2 was
added before Sub1.

The `.gitattributes` in `click/` keeps every file byte for byte, line ends included. Do not edit these
files. They are CLICK's answers.

`make program-answers` reads these cases and writes `src/laddercodec/resources/program_answers.json`.
That table gives a program finding its CLICK id. Run it after you add a case.

| Case | Program |
|---|---|
| q1a | A For with no Next in Main |
| q1b | A Next with no For in Main |
| q1c | A For in Main around a Call to Sub1, and a Next in Sub1 |
| q1d | Two Fors and one Next in Main |
| q2a | Four nested loops in Main |
| q2b | Three nested loops in Main around a Call to Sub1, which holds one loop |
| q2c | Two nested loops in Main around a Call to Sub1, which holds one loop |
| q2d | Main calls Sub1 outside any loop. Sub1 holds four nested loops |
| q3a | One Shot on the inner For of two |
| q3b | One Shot on the outer For of two |
| q3c | A loop in Main around a Call to Sub1, whose own For has One Shot on |
| q4a | A Return inside a loop in Sub1 |
| q4b | An End inside a loop in Main |
| q4c | A For with no Next in Sub1, and two Returns after it |
| q5a | Sub1 calls Sub2. CLICK drops the Call at the paste |
| q5b | Sub1 calls Sub1. CLICK drops the Call at the paste |
| q6a | A Call to a name that no subroutine has |
| q6b | A Call to `sub1`, in a project whose subroutine is `Sub1` |
| q7 | A Break and a Continue outside a loop |
| q8 | A Call to Sub1, which holds a Math |
| q8c | q8, with Syntax Check run before Local Program Information |

`check()` does not report a Call to a missing subroutine (q6a), or a Break or a Continue outside a loop
(q7). The test leaves those errors out.

The runner also ran the 8,000-step cases. They are not here, because `check()` does not count steps.

## own/: laddercodec's own reading

Each folder is a bundle that `read_bundle()` reads. CLICK did not check these bundles. `OWN` in the test
holds the findings that laddercodec's rules give for them.

- `depth_3`: three nested loops in Main. No finding.
- `return_after_loop`: a Return in Sub1 after its loop's Next. No finding.
- `call_other_case`: three nested loops in Main around a Call to `sub1`, in a project whose subroutine `Sub1`
  holds one loop. The Call names Sub1, because the names match without regard to case (q6b). Sub1's For gets
  `for-nesting-depth`, as in q2b. The finding has no CLICK id, because CLICK did not check this shape.
