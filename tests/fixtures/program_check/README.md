# Program check fixtures

Each folder is a bundle that `read_bundle()` reads: `main.csv` and `subroutines/*.csv`.
`tests/test_program_check.py` runs `check()` on each bundle as a `Project` and compares the
findings with `EXPECTED` in that file. Those findings are what laddercodec's rules give.
CLICK's Syntax Check answer is not recorded for any of these bundles.

A bundle with an expected finding:

- `for_without_next`: a For with no Next in Main.
- `next_without_for`: a Next with no For in Main.
- `for_and_next_split`: a For in Main and its Next in Sub1.
- `two_fors_one_next`: two Fors and one Next in Main. The Next closes the second For.
- `depth_4`: four nested loops in Main.
- `depth_4_through_call`: three nested loops in Main around a Call to Sub1, which holds one
  loop.
- `depth_4_in_subroutine`: Main calls Sub1 outside any loop. Sub1 holds four nested loops.
- `oneshot_inner`: One Shot on the inner For of two.
- `return_inside_loop`: a Return inside a loop in Sub1.
- `return_in_unclosed_loop`: a For with no Next in Sub1, with two Returns after it. The For
  gets `for-without-next`, and neither Return gets a finding.
- `end_inside_loop`: an End inside a loop in Main.
- `nested_call`: Sub1 calls Sub2.
- `self_call`: Sub1 calls Sub1.

A bundle with no finding:

- `depth_3`: three nested loops in Main.
- `depth_3_through_call`: two nested loops in Main around a Call to Sub1, which holds one
  loop.
- `oneshot_outer`: One Shot on the outer For of two.
- `oneshot_through_call`: a loop in Main around a Call to Sub1, whose own For has One Shot
  on. `check()` looks for an inner One Shot within one program only.
- `return_after_loop`: a Return in Sub1 after its loop's Next.
- `call_other_case`: three nested loops in Main around a Call to `sub1`, in a project whose
  subroutine `Sub1` holds one loop. The Call names no subroutine, because the name differs in
  case, so it adds no loops. If the Call named `Sub1`, the loops would nest 4 deep.

A bundle for CLICK only:

- `call_unknown`: a Call to a name that no subroutine has. `check()` reports nothing for it,
  whatever subroutine the Call names. The bundle is here for CLICK's answer.
