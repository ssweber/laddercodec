# CLICK v4.00 dialog/renderer cross-check: Timer, Counter, Shift, Search, Call, Return, End, For, Next

Sources: `Inst_<Name>.dll` (edit dialog) and `InstCtl_<Name>.dll` (ladder renderer: owns the
func-code computation, the tag serialization order table, and the per-tag get/set dispatch).
Native-blob evidence: `sweep/scan_blobs.py` over native clipboard captures
(`tests/fixtures/tumbler/**/*.clipboard.bin`, `scr_captures/{coverage,counter_scr,shift_scr,...}.bin`,
`v4_captures/*.bin`). Note `ladder_captures/golden` and `coverage/golden` bins are encoder output.

Getter/setter codes seen in these DLLs: `0x7e1` string get, `0x7eb` string set, `0x7db` byte get,
`0x7e5` byte set, `0x7dd` int get, `0x7e7` int set.

Legend: **C** = confirmed from disassembly; **N** = confirmed from native capture bytes; **I** = inferred.

Helper scripts added in `scratchpad/click-v4/sweep/`: `disrange.py` (disassemble a VA range, annotate
imports/strings), `ptrstr.py` (string / string-pointer tables), `dlgstyle.py` (control styles:
READONLY etc.), `u16tab.py` (u16 table dump), `scan_blobs.py` (native blob field dump).

## Renderer serialization order (C, from InstCtl tag tables)

| Class | Table VA | Tag order | Our build order |
|---|---|---|---|
| Tmr | InstCtl_Tmr 0x10012000 | 6068 606a 6069 21f9 21fa 21fb 3a05 | same |
| Cnt | InstCtl_Cnt 0x10010000 | 606b 606a 606c 606d 21fc 3a05 | same |
| SR | InstCtl_SR 0x1000f000 | 6066 6067 3a05 | same |
| Search | InstCtl_Search 0x100130c0 | 6065 6066 6067 6079 607a 1277 3218 11f8 21f7 | same |
| Call | InstCtl_Call 0x1000e000 | 3219 6208 3218 | same |
| Return | InstCtl_Return 0x1000d000 | 3218 | same |
| End | InstCtl_End 0x1000e00c | 6065 (!) | none (terminator only) |
| For | InstCtl_For 0x1000e000 | 6065 3218 11f8 | same |
| Next | InstCtl_Next 0x1000d000 | 3218 6065 (!) | 3218 (Break/Continue), none (Next) |

End and Next renderers list a `0x6065` tag that never appears in native blobs (4 native End blobs:
terminator only; v4 Next/Break/Continue: 3218 only). UNSURE what it is; probably skipped when empty.
Our output matches the native blobs. Dialog save order differs from blob order for Search
(6066,6067,6065,...) and Call (6208, 3219), which doesn't matter: the blob order comes from the
renderer table above, and the native captures confirm it.

---

## Timer (`Inst_Timer.dll`, `InstCtl_Tmr.dll`) -> `timer.py`

Dialog 1000 "Timer".

| Tag | Get/Set | Dialog field | Control | Our handling | Verdict |
|---|---|---|---|---|---|
| 6068 | str | Timer Number: | Edit 0x1389 (+0x1e0) | `done_bit` | MATCH (C) |
| 606a | str | Set Point: | Edit 0x138c (+0x270) | `setpoint` | MATCH (C) |
| 6069 | str | Current Value: | Edit 0x138f (+0x300), **READONLY** | `current` | MATCH (C). Derived in the dialog, not user-editable (I: TD<n> from T<n>). We don't check it. |
| 21f9 | byte | Unit | ComboBox 0x138e droplist, CB_SETCURSEL index -> +0xc8 | `unit` via `TIMER_UNITS` | MATCH (C): 0=ms 1=sec 2=min 3=hour 4=day (strings at 0x100076c8.., combo filled from table 0x1000c534..0x1000c548). Our names Tms/Ts/Tm/Th/Td map 0..4. No other units. |
| 21fa | byte | Delay Setting radio | DDX_Radio 0x1390 -> +0xc0 | `timer_type` | MATCH (C): 0 = "ON Delay timer" (0x1390), 1 = "OFF Delay timer" (0x1391) |
| 21fb | byte | Current Value Option radio | DDX_Radio 0x1392 -> +0xc4 | `retained` | MATCH (C): 0 = "not retained", 1 = "retained (use reset input)" |
| 3a05[0..1] | n/a in dialog | func codes (enable, reset) | computed by InstCtl_Tmr 0x10003880 | `enable_func_code` / `reset_func_code` | MATCH for reachable combos, see below |

Func-code table (C, InstCtl_Tmr 0x10003880; members +0xd8 = 21f9 unit, +0xd9 = 21fa type,
+0xda = 21fb retain, confirmed via getters 0x10005cf0/0x10005ca0/0x10005c80). Jump table at
0x10003cd4: unit 0 -> 0x10003beb, 1 -> 0x10003897, 2 -> 0x10003963, 3 -> 0x10003a3b, 4 -> 0x10003b13.
Per unit, `base = 8717 + 6*unit`:

| type / retain | enable | reset | ours |
|---|---|---|---|
| ON, not retained | base+0 | 0 | same |
| OFF, not retained | base+1 | 0 | same |
| ON, retained | base+2 | base+3 | same |
| OFF, retained | **base+4** | **base+5** | we emit base+1 / base+3 |

Dialog behaviour (C, Inst_Timer 0x100024c0): when OFF Delay is selected, the retain radios
0x1392/0x1393/0x1394 are disabled and `+0xc4` (21fb) is forced to 0. So CLICK's editor never produces
OFF+retained, but the renderer has codes for it. **Gap:** `Timer.with_pins` (timer.py:141) sets
`retained=True` for any timer with a `.reset()` pin, so `off_delay(...)` with `.reset()` encodes
21fa=1, 21fb=1, enable base+1, reset base+3 (timer.py:113-125). Native would be base+4/base+5, and
the dialog doesn't allow the combination at all. Suggest rejecting off_delay + `.reset()`.
`from_tags` also accepts 21fa=1/21fb=1 without complaint.

Native evidence (N): units 0..3 seen (8717/8718/8719+8720, 8723/8724/8725+8726, 8729/8731+8732, 8735),
all consistent with the table.

Validation not modeled (I): a constant set point is limited to digits <= 0x7fff (32767) (Inst_Timer
0x10002ea0-0x10002f0e, error 0x2715). Address set points go through a memory-type list (DS/DD/DH/DF/
XD/YD/TD/CTD/SD/TXT branches). We do no set-point validation. **WE DON'T VALIDATE.**

Renderer-only tag `0x1007` (Tmr/Cnt/For renderers, double-valued set path) isn't in the serialization
table, so it isn't a blob field. Probably the online monitor value (I).

## Counter (`Inst_Counter.dll`, `InstCtl_Cnt.dll`) -> `counter.py`

Dialog 1000 "Counter".

| Tag | Get/Set | Dialog field | Control | Our handling | Verdict |
|---|---|---|---|---|---|
| 606b | str | Counter Number: | Edit 0x1389 (+0x1d8) | `done_bit` | MATCH (C) |
| 606a | str | Set Point: | Edit 0x138c (+0x268) | `preset` | MATCH (C) |
| 606c | str | Current Value: | Edit 0x138e (+0x3f8), **READONLY** | `current` | MATCH (C). Auto-filled on Counter Number change: CT<n> -> CTD<n> (0x10001850, inserts "D" at index 2). |
| 606d | str | Completion Bit: | Edit 0x138f (+0x488), **READONLY** | encoder writes `done_bit` (counter.py:166); decoder ignores it | MATCH (C+N): auto-filled = upper-cased Counter Number; native always 606d == 606b |
| 21fc | byte | Count Type radio | DDX_Radio 0x1391 -> +0xc0 | `counter_type` + `down_enabled` via `_MODE_TO_VARIANT` | MATCH (C): 0 = Count Up, 1 = Count Down, 2 = Count Up and Down. No other modes. |
| 3a05[0..2] | renderer | up/down/reset func codes | InstCtl_Cnt 0x100027d0 | `_VARIANT_TO_ENCODING` | MATCH (C+N): mode0 8710/0/8711, mode1 0/8747/8748, mode2 8713/8714/8715 |

The dialog has no option to drop the reset input, so every counter has one. That matches our rule
that `.reset()` is required (counter.py `with_pins`).

The renderer derives the mode back from func code [0] (0x100028c0: 0x2206 -> 0, 0x2209 -> 2,
0x222b -> 1). count_down's slot 0 is 0, though, so that path presumably isn't what decides mode for
native count_down. Harmless for us because we read 21fc.

Validation not modeled (I): constant set point parsed with `_wtoll` and range-checked by adding
0x80000000 (signed 32-bit). **WE DON'T VALIDATE.**

## Shift Register (`Inst_ShiftRegister.dll`, `InstCtl_SR.dll`) -> `shift.py`

Dialog 1007 "Shift Register".

| Tag | Get/Set | Dialog field | Control | Ours | Verdict |
|---|---|---|---|---|---|
| 6066 | str | Starting Address: | Edit 0x138a (+0x1d0) | `start_bit` | MATCH (C) |
| 6067 | str | Ending Address: | Edit 0x138b (+0x260) | `end_bit` | MATCH (C) |
| 3a05[0..2] | renderer | data/clock/reset func codes | InstCtl_SR 0x10001fa3 | `_SHIFT_FUNC_CODES` 8448/8449/8450 | MATCH (C+N) |

No other options (direction is set by start > end address, not by a field).

## Search (`Inst_Search.dll`, `InstCtl_Search.dll`) -> `search.py`

Dialog 1000 "Search".

| Tag | Get/Set | Dialog field | Control | Ours | Verdict |
|---|---|---|---|---|---|
| 6065 | str | Search: (value) | Edit 0x138f | `source` | MATCH (C) |
| 6066 | str | Range Starting Address | Edit 0x1392 | `table_start` | MATCH (C) |
| 6067 | str | Range Ending Address | Edit 0x1395 | `table_end` | MATCH (C) |
| 6079 | str | Result (data register) | Edit 0x1398 | `result` | MATCH (C) |
| 607a | str | Result Flag | Edit 0x139b | `found` | MATCH (C) |
| 1277 | byte(bool) | "Continuous Search" | checkbox 0x139d | `continuous` "-1"/"0" | MATCH (C+N): renderer getter 0x10005fd0 sign-extends bit0 -> "-1" |
| 11f8 | byte(bool) | "One Shot (Execute one time)" | checkbox 0x139e | `oneshot` "-1"/"0" | MATCH for the tag value (N "-1") |
| 21f7 | byte | Condition (6 bitmap radios) | radio 0x1388+i, i = value | `comparison` via `_OP_TO_CMP_CODE` | MATCH (C): bitmaps 0x1388 Sym_Equal, 0x1389 Sym_NEqual, 0x138a Sym_GT, 0x138b Sym_LT, 0x138c Sym_GTEqual, 0x138d Sym_LTEqual -> 0 ==, 1 !=, 2 >, 3 <, 4 >=, 5 <= |
| 3218 | renderer | func code | InstCtl_Search 0x10003d60 | `func_code` | **MISMATCH**, see below |

**Func code (C, InstCtl_Search 0x10003d60 + jump table 0x10003e30, inverse at 0x10003e50).**
Inputs: `+0xc8` = 21f7 (setter 0x10006320) and bit 1 of `+0x158` = 11f8 **one-shot** (setter
0x100061a0; bit 0 = 1277 continuous, setter 0x100060f0):

| 21f7 | op | no one-shot | one-shot |
|---|---|---|---|
| 0 | == | 8964 | 8970 |
| 1 | != | 8965 | 8971 |
| 2 | > | 8966 | 8972 |
| 3 | < | 8968 | 8974 |
| 4 | >= | 8967 | 8973 |
| 5 | <= | 8969 | 8975 |

The inverse (0x10003e50, tables 0x10003ed4/0x10003f0c) maps func-8964 index 0..11 back to
cmp {0,1,2,4,3,5,0,1,2,4,3,5} and one-shot {0 x6, 1 x6}.

- Our 8964-8969 operator table (search.py `_OP_TO_FUNC`) is correct for no one-shot.
- **Our `_TEXT_FUNC = "8970"` (search.py:51, used at search.py:132-134, docstring search.py:8) is a
  misattribution.** 8970 means "== with one-shot", not "text search". The only native 8970 capture
  (`scr_captures/coverage.bin`: `TXT1..TXT10 == "T"`, oneshot) is both text and one-shot, which
  explains the confusion. Wrong encodings:
  - text search without one-shot: we emit 8970, native emits 8964 (== ) / 8965 (!=)
  - data search with one-shot: we emit 8964-8969, native emits 8970-8975
  - text search with != and one-shot: we emit 8970, native emits 8971
  - Correct rule: `8964 + {==:0, !=:1, >:2, >=:3, <:4, <=:5}[op] + (6 if oneshot else 0)`. Text vs
    data doesn't change the func code.
  - Probably harmless on paste (I): the renderer applies tags in blob order, so 3218 is set first and
    then 11f8 and 21f7 recompute it when they differ (setters 0x100061a0 / 0x10006320 call
    0x10003d60). CLICK would likely fix the code itself. Still not byte-identical, and anything that
    trusts 3218 would read our blob wrong. Our decoder ignores 3218, so decoding is unaffected.
- Text search limits the condition to == / != (I, Inst_Search 0x10002c77-0x10002e75): with a text
  source, a selected condition other than index 0/1 is forced back to 0, and radios 2..5 are
  hidden/disabled. **WE DON'T VALIDATE**: we accept `TXT.. > "A"`.

## Call (`Inst_Call.dll`, `InstCtl_Call.dll`) -> `call.py`

Dialog 1000 "Call": ComboBox 0x1389 "Subroutine Program Name:" (droplist, CBS_SORT) and the
"Add New Subroutine..." button.

| Tag | Get/Set | Dialog field | Ours | Verdict |
|---|---|---|---|---|
| 6208 | str | Subroutine Program Name (combo text) | `subroutine` | MATCH (C) |
| 3219 | byte | combo **CB_GETCURSEL index** of the chosen subroutine (save 0x10001893-0x100018bf) | always "0" (call.py:51), ignored on decode | **WE EMIT CONSTANT** (C+N) |
| 3218 | renderer | func code 0x2405 = 9221 (InstCtl_Call 0x100015f3) | `CALL_FUNC_CODE` 9221 | MATCH (C+N) |

3219 is stale UI state. On load the dialog first does CB_SETCURSEL(3219) (0x1000172e), then refills
the list and reselects by name: get 6208 -> CB_FINDSTRINGEXACT -> CB_SETCURSEL (0x10001ad0-0x10001b96).
So the name is what counts (C). Native values vary per program and go stale (e.g. AlmHistorian seen
as 0 and 2, WarnTimestamp as 23 and 26). Writing "0" is fine. The "Add New Subroutine..." button is
disabled once 0x3da (986) subroutines exist (I).

## Return (`Inst_Return.dll`, `InstCtl_Return.dll`) -> `return_.py`

The dialog has no parameters ("No setup parameter is required"), and the Inst DLL touches no tags.
The renderer constructor sets func 0x2407 = 9223 (InstCtl_Return 0x10001b74), and its tag table is
[3218]. Ours emits 3218=9223: MATCH (C+N, all tumbler subroutine Return blobs are `3218='9223'`).

## End (`Inst_End.dll`, `InstCtl_End.dll`) -> `end.py`

The dialog has no parameters and the Inst DLL touches no tags. The renderer constructor sets a
func code of 0x2606 = 9734 internally (InstCtl_End 0x10002674), and its tag table lists [6065]. But
all native End blobs (coverage.bin, tumbler main.clipboard.bin, v4 math_wide.bin, rungs_266) contain
only the terminator (field count 1). Ours emits terminator only: MATCH (N). Why neither 3218=9734
nor 6065 is serialized is UNSURE.

## For (`Inst_For.dll`, `InstCtl_For.dll`) -> `forloop.py` `ForLoop`

Dialog 1000 "For".

| Tag | Get/Set | Dialog field | Control | Ours | Verdict |
|---|---|---|---|---|---|
| 6065 | str | Number of loops: | Edit 0x1389 (+0x148) | `limit` | MATCH (C) |
| 11f8 | byte | "One Shot (Execute one time)" | checkbox 0x138b | `oneshot`; encoder writes "-1"/"0" (forloop.py:111) | **MISMATCH (byte form only)**: native writes "1" |
| 3218 | renderer | func code | InstCtl_For | `_FOR_FUNC_CODES` 9218/9219 | MATCH (C+N) |

The renderer stores no separate one-shot flag (C). The 11f8 getter (0x10002640) returns
`func != 0x2402` via `setne`, which gives 1, not -1, so native For writes `11f8='1'`
(N: `scr_captures/coverage.bin` `For DS1 3218='9219' 11f8='1'`). The 11f8 setter (0x100026d0)
sets `func = 0x2402 + (v != 0)`, so CLICK accepts our "-1". The difference is cosmetic (byte
mismatch vs native, not functional). Search's 11f8 really is "-1" natively because its getter
sign-extends a bitfield; the two instructions differ. Our decoder accepts both ("-1" or "1" -> set,
raw.py:170).

Validation not modeled (I, Inst_For 0x10001876-0x10002251): a constant limit must be digits
<= 0x7fffffff. Address limits are restricted to DS / DD / TD / CTD / SD. `_validate_for_limit` accepts
any valid operand (e.g. X1). **WE DON'T VALIDATE.**

## Next / Break / Continue (`Inst_Next.dll`, `InstCtl_Next.dll`) -> `forloop.py` `Next`/`Break`/`Continue`

Dialog 1007 "Next - Break - Continue": radios Next 0x4a38, Break 0x4a3a, Continue 0x4a39 (index
member +0x240: 0/1/2).

| Tag | Get/Set | Meaning | Ours | Verdict |
|---|---|---|---|---|
| 3218 | int (0x7dd / 0x7e7) | 0x2404 = 9220 Next, 0x2411 = 9233 Break, 0x2410 = 9232 Continue | `_NEXT_FUNC_CODE` / `_BREAK_FUNC_CODE` / `_CONTINUE_FUNC_CODE` | MATCH (C+N) |

The dialog seeds the value with 0x2404 before reading 3218 (Inst_Next 0x10001dac), so a missing 3218
reads as Next (C). Our v3-form `Next.build_blob` (no 3218) is therefore read correctly by v4. Native
v4 Next writes `3218='9220'` (N, loop_exits.bin), which our decoder also handles.

---

## Summary of discrepancies and gaps

1. **Search func code (MISMATCH, C+N):** 8970-8975 are the one-shot variants of 8964-8969, not
   "text search". Affects search.py:8, :51, :128-135. Fix: `8964 + idx + 6*oneshot`, with idx
   {==0, !=1, >2, >=3, <4, <=5}. Paste probably self-corrects (I).
2. **For one-shot byte (MISMATCH, cosmetic, C+N):** native `11f8='1'`, we write `'-1'` (forloop.py:111).
3. **Timer off_delay + retained (GAP, C):** the CLICK dialog forbids it. The renderer codes are
   base+4/base+5, but we would emit base+1/base+3 (timer.py:113-125) when `.reset()` is attached to
   `off_delay` (timer.py:141).
4. **Call 3219 (WE EMIT CONSTANT, C+N):** it is the combobox index, and CLICK ignores it on load
   (reselects by name). "0" is fine.
5. **Unvalidated input ranges (I):** timer constant set point <= 32767; counter set point 32-bit
   signed; For limit <= 2^31-1 and DS/DD/TD/CTD/SD only; Search text source only == / !=;
   Timer/Counter current value (and Counter completion bit) are derived read-only fields.
6. **No missing enum values:** timer units 0..4, counter modes 0..2 and search conditions 0..5 are all
   fully covered by our tables.
7. **Unresolved:** End/Next renderer tag tables list a 0x6065 tag that never appears in native blobs,
   and End's internal func code 9734 isn't serialized. Renderer tag 0x1007 (monitor value?) is outside
   the serialization tables.
