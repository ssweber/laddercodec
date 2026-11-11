# Arc: fixes from the CLICK v4.00 DLL sweep

CLICK v4.00's own instruction DLLs were read on 2026-11-11 (`Inst_*.dll` = MFC dialogs,
`InstCtl_*.dll` = blob tag order + func code computation). Our tag order matches CLICK for
every instruction; the gaps are func codes, enum values and a few fields we drop.
Per-family evidence: the v4 DLL sweep notes, kept outside the repo. Scripts: `scratchpad/click-v4/*.py`.

Goal: every instruction we encode produces the blob CLICK itself writes, field for field,
proven against native captures; the four raw instructions expose their status bits.

## Decisions (settled 2026-11-11: D2–D6 as recommended; the stub comments use them)

| # | Question | Decision |
|---|---|---|
| ~~D1~~ | ~~Termination code outside `to_text`~~ | **Dropped.** Checked in the v4 dialog: greyed for Single TXT→TXT and constant→TXT, Block TXT→TXT and Fill→TXT; Block DS→TXT isn't allowed at all. Termination is Single number→text only, which we already support. The sweep's reading of the enable logic was wrong. |
| D2 | Send/Receive over WLAN | `ModbusTcpTarget(...,com_port="wlan")`; omitted = Port1 (today's behaviour). |
| D3 | Slave ID given as an address | `device_id=DS2420` (int or address). |
| D4 | `latch`/`reset` with `oneshot=1` (CLICK's dialog has no One Shot) | Reject at parse time. |
| D5 | `off_delay` + retain (`.reset()` pin) (dialog forbids it) | Reject at parse time. |
| D6 | `to_text` options vs source type | Integer source: `suppress_zero` picks 1/2, `exponential=1` rejected. DF source: `exponential` picks 3/4, `suppress_zero` ignored (written as 1, as today). |

If a decision changes, I regenerate the stubs before you capture: a stub's comment is baked
into the capture and is what `tests/test_v4_captures.py` checks against.

## Phase 0 — captures (you, in CLICK v4)

Stubs: `scratchpad/click-v4/captures/stubs/sweep_<group>.csv`, written by
`uv run python scratchpad/click-v4/captures/sweep_stubs.py`. Paste each into an **empty program**.
From the clicknick directory:

```bash
UV_NO_SYNC=1 uv run --no-sync clicknick-rung load ../laddercodec/scratchpad/click-v4/captures/stubs/sweep_<group>.csv
# paste into CLICK. For groups with reopen rungs, first copy everything straight back:
UV_NO_SYNC=1 uv run --no-sync clicknick-rung save ../laddercodec/scratchpad/click-v4/captures/copyback/sweep_<group>_pasted
# then do the "In CLICK" column, Syntax Check, select all, copy, and:
UV_NO_SYNC=1 uv run --no-sync clicknick-rung save ../laddercodec/scratchpad/click-v4/captures/copyback/sweep_<group>
```

- **reopen**: our real instruction is pasted. Double-click it, change nothing, press OK.
  The `_pasted` copy tells us whether CLICK already corrects our bytes on paste (i.e. whether
  the bug ever mattered); the reopened copy is the ground truth.
- **build**: a NOP is pasted. Replace it with the instruction the comment describes.
- If CLICK refuses something (paste rejected, dialog won't accept a value), note it here and skip that rung.

| Group | Rungs | In CLICK | Needs |
|---|---|---|---|
| search | 6 | reopen all | — |
| coil | 3 | build: Out with One Shot + Immediate on Y001; Out range C611–C614 with One Shot; Out range Y002–Y004 with One Shot + Immediate | Y001–Y004 on the CPU |
| copy | 6 | reopen `copy__df_text_exp`, `blockcopy__to_ascii_v4`; build the rest: DF→TXT **Real Numbering**; DD→DF and DF→DD **Copy Value**; DD→DF **Copy Binary** | — |
| drum | 6 | reopen all (Th = hours) | DS presets need a CPU that allows them; if the dialog refuses, skip those two |
| comm | 3 | build: Send on **WLAN** to 192.168.1.20; Receive on **CPU Port 3** slave 2; Send on CPU Port 2 with Slave ID **DS2420**. Also try DD, DH, C as the Slave ID and note which the dialog refuses (for pyrung validation) | A CLICK PLUS CPU with WLAN and Port 3 (System Configuration) |
| math | 3 | **retype** all: OK keeps our formula bytes, so delete each Math and re-enter the same formula and result (literals 100000, 40000, 32767) | — |

Optional, any time: ASCII Send (static and dynamic) and ASCII Receive (fixed and variable)
rungs, and Home/Velocity/Position/Email with every status field filled with a distinct
address (needs a PTO axis in High Speed I/O Setup and Email Setup). These stay `raw(...)`
(xfail) but give us native blobs to model later. Save as `copyback/sweep_ascii`, `copyback/sweep_raw`.

When a group's copy-back decodes as expected, copy the reopened `.bin` (not `_pasted`) into
`tests/fixtures/v4_captures/` and record the `_pasted` result in the log below.

## Phase 1 — native-blob test

- [x] `tests/test_v4_captures.py::test_sweep_af_reencodes_like_native`: for every rung in `sweep_*.bin`,
      re-encode the decoded rung and compare each AF blob to CLICK's tag for tag (raw rungs xfail).
      Ignore list: Call `3219` (stale index). This catches func-code bugs: the decoder ignores `3218`,
      so decode-only checks pass. A new capture group is covered by dropping its `.bin` into `v4_captures/`.

## Phase 2 — encoder fixes (one commit each, each made green by its capture)

- [x] **Search** (`search.py`): func code `8964 + op + 6*oneshot`, op order `== != > >= < <=`; dropped `_TEXT_FUNC`.
      Confirmed by `sweep_search`. Not done: rejecting text search with an operator other than `==`/`!=`
      (agent claim, unverified — check in the dialog first; moved to Phase 5).
- [x] **Coil** (`coil.py`): added 8206 (out+oneshot+immediate), 8209/8210 (range+oneshot ±immediate); D4; one-shot flag written `1`. Confirmed by `sweep_coil`.
- [x] **Copy** (`copy.py`): conversion types 3 and 7; source-aware `to_text` (D6); DD↔DF value/binary with
      `2206` = 1 for binary; block `to_ascii` `2206` kept at v3's 0 (v4 dialog writes 1, ignores it on load).
      `1201` comment fixed (v4 writes -1 on every save; test ignores it). to_text CSV writes only the source's option. Confirmed by `sweep_copy`.
- [x] **Drum** (`drum.py`): Th jog group at block+4 (8480…, 10528…); `428a` bitmask of constant presets;
      10247-series codes for time drums with a register preset, which now get v4's 82-field blob (they're
      v4-only per `compat.py`, and a paste of the 64-field form keeps the 8455 series). Comments and
      `docs/internals/instruction-blobs.md` fixed. Confirmed by `sweep_drum`. **`drum__v4` coverage golden
      changed and is unverified — needs a paste check.**
- [x] **Send/Receive** (`send_receive.py`, 3071aea): port 1 = CPU Port3, 3 = WLAN (D2); DS slave ID via `60b2`/`223a` + 9749-9752 (D3);
      unknown port/func code -> raw. Confirmed by `sweep_comm`. Not done: SD status decoded like RD (DLL says v4 rederives
      enables; a v3 blob with an unchecked box may keep its string, so left alone). Padding sentinels: CLICK writes slot index,
      we write FFFFFFFF; fixing changes all 19 send/receive goldens (paste checks).
- [x] **Math** (`math.py`): integer literals outside -32768..32767 get `W`, not `H`. Confirmed by `sweep_math`.
      Not done (DLL only, uncaptured): reject hex constants over `FFFF` and integers outside int32 — check in the
      dialog first; moved to Phase 5.
- [x] **Timer** (`timer.py`, ea9d8a2): D5. **For** done in e94e50e (sweep_for.bin built in v4: 11F8 = 1). Was: **For** (`forloop.py:111`): one-shot written as `'1'`. No capture needed
      (For: `scr_captures/coverage.bin` already shows `'1'`).

## Later (after the fixes land) — raw instruction status bits

Deferred: the fixes come first.

## Phase 3 — raw instructions expose their status bits (laddercodec)

- [ ] `Home`, `Velocity`, `Position`, `Email`: read-only `outputs` → `{"busy", "complete", "success", "error", "error_code"}`
      (Email: `"sending"` instead of busy/complete). Tags: busy `60a3`, complete `60a4`, sending `607c`, success `607b`,
      error `607d`, error code `6083` — all confirmed from the dialog DLLs. The `raw(...)` token is unchanged.

## Phase 4 — pyrung (separate repo)

- [ ] `raw()` stays a no-op; its `outputs` tags count as `external` (written outside the ladder), so analysis and
      `recovers()` treat them correctly and tests drive them with `patch()`/`force()`. No state machine or mock API.
- [ ] Syntax from D2–D3: `ModbusTcpTarget.com_port`, `device_id` as a tag.

### Coordinate with Bobby (pyrung) before the comm capture

Checked against `../pyrung/src` on 2026-11-11. The CSV token syntax is shared: pyrung's ladder exporter writes
it (`click/ladder/instructions.py`, `translator.py`) and its codegen reads it back (`click/codegen/utils.py`).

| Decision | pyrung today | Impact |
|---|---|---|
| D2 `com_port="wlan"` / `"cpu3"` | `VALID_COM_PORTS` = cpu2, slot0_1..slot1_2 (`core/instruction/send_receive/types.py:148`); `ModbusTcpTarget` has no `com_port`; `_render_modbus_target` doesn't write one | **Needs agreement.** New field on the TCP target + two new RTU ports, in the DSL, exporter and codegen |
| D3 `device_id=DS2420` | `device_id: int` everywhere (types, exporter, Modbus backends) | **Needs agreement.** Tag-valued device ID in the DSL, exporter, codegen and the runtime backends |
| D4 reject latch/reset oneshot | `latch()`/`reset()` take no `oneshot` | None — pyrung already can't produce it |
| D5 reject off_delay + `.reset()` | `OffDelayBuilder` has no `.reset()` | None |
| D6 source-aware `to_text` | translator always writes both `suppress_zero` and `exponential`; runtime ignores `exponential` for integer sources | Small: `to_text(exponential=True)` from an integer source would now fail to export. pyrung should reject it (validation) or drop it. DF + `suppress_zero` keeps working (ignored, as at runtime) |
| Drum, Math, Search fixes | — | None: encoding only, the CSV tokens are unchanged |

**D2/D3 syntax agreed by Bobby 2026-11-11** — comm capture can go. Bobby's open questions: slave-ID memory types (capture), out-of-range slave ID at runtime (hardware only; pyrung assumes error bit + no send). D6: laddercodec's writer will omit `suppress_zero` for DF sources, matching pyrung's exporter. Timing of pyrung work vs its 0.16.0 cut: Sam to decide.
Old note: coil and copy captures could go first; the comm capture waited on D2/D3 since the
stub comments bake it in (`sweep_stubs.py` regenerates them if it changes).

## Phase 5 — optional validation (CLICK enforces, we don't)

Immediate only on X (contacts) / Y (coils); For limit operand only DS/DD/TD/CTD/SD; timer constant preset ≤ 32767;
Math functions per mode (hex vs decimal); Math formula ≤ 500 characters; text Search only `==`/`!=` (unverified);
Math hex constant > `FFFF` and integer outside int32 rejected (error 0x2B01 per the DLL, unverified).
Decide per item whether it's worth it.

## Log

- 2026-11-11: sweep done, stubs written. Waiting on Phase 0 captures.
- 2026-11-11: D1 dropped after a dialog check (termination only on Single number→text). Lesson: code-only
  `[D]` findings without a capture can be wrong; every Phase 2 fix waits for its capture.
- 2026-11-11: `sweep_search` captured (reopened copy → `v4_captures/sweep_search.bin`). CLICK's func codes:
  8964, 8965, 8971, 8970, 8975, 8966 — exactly the DLL formula. `_pasted` == reopened, so CLICK recomputes
  the func code on paste and our wrong codes (8970 ×3, 8964, 8969) never reached a program. No other field
  differed. Search fixed; Phase 1 test added and green (4057 passed).
- 2026-11-11: `sweep_drum` captured. Th jog codes were one low; CLICK fixes them on paste. Register-preset
  time drums: dialog writes `428a` -2 and 10247/10272 series; the `_pasted` copy kept 8455/8480 with `428a`
  -1, so a paste does **not** fix that one. Every reopened time drum also gets `6068` = T<n> and 82 fields
  (v4's own form; we keep v3's for constant presets, and the sweep test ignores the v4-added tags then).
- 2026-11-11: `sweep_math` captured (formulas retyped, since OK keeps the bytes). CLICK writes `W100000`,
  `W40000`, `H32767`; the `_pasted` copy kept our `H`, so this reached programs. v4 pads `688c` to 5000
  slots; the sweep test compares filled slots only. Drum + Math fixed; 4137 passed, lint clean.
- 2026-11-11: `sweep_coil` captured, but One Shot wasn't ticked on the two Immediate rungs — **recapture
  rungs 1 and 3**. The range rung confirmed 8209 (added) and showed CLICK writes the coil one-shot flag
  `11f8` as `1`, not our `-1` (also in `scr_captures/coverage.bin` `out__oneshot`) — fixed; `out__oneshot`
  coverage golden is now unverified. v4 copies every Out back in its OutVariant shape; the sweep test
  ignores those added fields for v3-form coils. Fixture held back until the recapture.
- 2026-11-11: coil recaptured: 8206 (One Shot + Immediate), 8209, 8210 — all match the DLL; added, plus D4
  (latch/reset oneshot rejected). `sweep_coil.bin` in fixtures; 4162 passed. Sent the pyrung list (D2, D3, D6 +
  deferred raw outputs) to the `bobby` session; waiting on its OK for D2/D3 syntax before the comm capture.
- 2026-11-11: Bobby agreed D2/D3/D6. to_text CSV (lands with the Copy fix, both exporters together): write only the flag the source uses — integer `to_text(suppress_zero=N,termination_code=…)`, DF `to_text(exponential=N,termination_code=…)`; read stays lenient except exponential=1 on an integer source. Tell Bobby when it lands.
- 2026-11-11: `sweep_copy` captured. CLICK: DF→TXT real = (3, 0), DD↔DF value = (7, 0), DD→DF binary = (8, 1), block to_ascii (6, 1) and `1201` = -1 on every OK'd Copy (pasted copies keep ours). Copy fixed; to_text writes only the source's option; 4211 passed. Told Bobby it landed.
- 2026-11-11: committed the five fixes on `click-v4-sweep-fixes` (35eed08..a1e3135). `drum__v4` and `out__oneshot` paste-verified in CLICK (worked): register-preset time drums in v4 form and coil one-shot flag 1 both accepted.
- 2026-11-11: `comms_sweep` captured (copyback/comms_sweep.bin). WLAN Send = 9736 (TCP code) with 220C=3; CPU Port 3 Receive = 9728 with 220C=1; address slave ID Send = 9751, 223A=1, 60B2=DS2420 (Sam put this rung on Port 3, 220C=1, not Port 2 — no Port 2 evidence). Decoder today maps unknown 220C to cpu2, so WLAN Send decodes as RTU cpu2 (lossy) — fix in send_receive.py once the src hold lifts. DD/DH/C in the slave-ID box still untested.
- 2026-11-11: Slave ID box accepts DS only (Sam: DD/DH/C refused). send_receive fix: device_id address must be DS. Told Bobby.
- 2026-11-11: Send/Receive fixed (3071aea); log lines committed (f25eab3); Timer D5 (ea9d8a2); For one-shot 1 (e94e50e) - forloop__oneshot and loop__v4 coverage goldens changed, need paste check. Phase 2 done.
- 2026-11-11: forloop__oneshot and loop__v4 paste-verified (worked); all 111 coverage goldens verified.
