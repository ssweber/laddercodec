# CLICK v4 captures

`v4_capture.py` writes one paste CSV per group into `stubs/`, plus pyrung's own export into `expected/`.
Each rung's comment is its id, then every AF token it should decode to. laddercodec's
`tests/test_v4_captures.py` checks every captured rung against that comment.
The laddercodec side of the loop is in `docs/guides/adding-instructions.md`, "Capturing from CLICK v4".

The generator builds the rungs with pyrung, so it runs in pyrung's environment. From the laddercodec root:

```
uv run --project ../pyrung python scratchpad/click-v4/captures/v4_capture.py
```

Done so far: math, out, drum, pins (fixtures in `tests/fixtures/v4_captures/`, goldens `<group>__v4` in
`tests/fixtures/coverage/golden/`). loop: Break/Continue taken from a hand capture (`loop_exits.bin`); the
`loop__v4` golden (the whole group, real Break/Continue) is paste-verified, so `stubs/loop.csv` needs no copy-back.

## Per group

Run clicknick against the local checkouts (`make install-dev` in clicknick once, then `UV_NO_SYNC=1` and
`uv run --no-sync`). From the clicknick directory:

1. `clicknick-rung load ../laddercodec/scratchpad/click-v4/captures/stubs/<group>.csv`, then paste into CLICK v4.
2. Build each rung from its comment (see "What to do" below), then Syntax Check.
3. Select all the group's rungs and copy them, then
   `clicknick-rung save ../laddercodec/scratchpad/click-v4/captures/copyback/<group>`
   (this writes `<group>.bin` and `<group>.csv`; keep it out of `stubs/`, which the generator rewrites;
   `save` does not create `copyback/`).
   Once every rung matches its comment or decodes as `raw(...)`, copy the `.bin` to
   `tests/fixtures/v4_captures/` and delete the copy-back.
4. In laddercodec, `make test`: rungs still decoded as `raw(...)` are xfail, and any other mismatch fails.

What to do in CLICK:

| Group | Placeholder | What to do |
|---|---|---|
| out | NOP | Replace it with Out using the variant in the comment. `on_acc=TD5` means TD5 in the dialog. |
| drum | v3 Time drum | Change the base to Time & Event. Set each event; blank the preset where the comment says `None`, and enter `DS....` where it names a register. |
| drum `time_ds*` | real instruction | Nothing, unless the paste is rejected. |
| math | real instruction | Nothing, unless the paste is rejected. If it is, rebuild it from the comment. |
| loop | NOP on a contacted body rung | Replace it with Break or Continue, as the rung's comment says. The other rungs are real. |
| pins | real instruction, each pin fed by one contact | The id names the OR'd pin(s). Under each, insert a row per extra leg and OR in the next contact up (see `expected/pins.csv`): `drum_reset_or` +1 leg on Reset, `drum_reset_or3` +2 on Reset, `drum_jump_or` +1 on Jump, `drum_all_or` +1 on each pin, `count_up_down_or` +1 on Down, `shift_clock_or` +1 on Clock. Let the box grow. Don't route a leg back up past the next pin. |

Math comments use CLICK's spelling, `NAME ( a , b )` (`SUM ( ... : ... )` and `RAND ( DD111 , DD112 )` are seen
natively; `ABS ( x )` is inferred). The `math__rand_*` bodies are stand-ins (pyrung has no `randint` yet) with
the token written by hand. Whatever the copy-back decodes to is the answer; fix the expected line to match.

A loop case is several rungs (For, body rungs, Next), each labelled `<id>/<k>` with its own AF tokens. Copy
every rung of the group back, Next rungs included.

## Address map

| Group | Contacts | Targets / outputs | Timers | Data |
|---|---|---|---|---|
| out | C1001–C1020 | C1101–C1117, Y001–Y003 | T1–T24 / TD1–TD24 | DS1001–DS1006 (presets) |
| drum | C1201–C1207 | C1311–C1372 (C13n1.. for drum n) | TD101–TD107 (accumulators) | DS1201–DS1207 (step), DS1210 (jump step), DS1301–DS1304 (durations); done C1401–C1407; events C1501–C1509; reset/jog/jump C1601–C1609 |
| math | C1701–C1723 | DS1501–DS1508, DD201–DD205, DF201–DF205, DH201–DH205 | — | DS1401–DS1412, DD101–DD112, DF101–DF111, DH101–DH106, C1801–C1816 |
| loop | C1901–C1906 (For rungs), C1921–C1926 (body rungs) | C1941–C1942 | — | DS1601–DS1613 (counters, limits) |
| pins | C1050–C1097 (rung n: enable C(1042+8n), pin legs the next 7) | C1021–C1024 (drum outputs), C1031–C1034 (done), C1041–C1048 (shift bits) | TD111–TD114, CT1/CTD1 | DS1701–DS1704 (step), DS1710 (jump step) |

T1–T40 are reserved for the Out family (C0112: an Out coil claims its whole timer number).
