# CLICK v4.00 dialog/InstCtl cross-check: contacts, compare, coils, Out variants

Scope: `Inst_ContactNO.dll`, `Inst_ContactNC.dll`, `Inst_Edge.dll`, `Inst_Compare.dll`,
`Inst_Out.dll`, `Inst_Set.dll`, `Inst_Reset.dll`, and their `InstCtl_*` model DLLs
(`InstCtl_ContactNO`, `InstCtl_Edge`, `InstCtl_Compare`, `InstCtl_Out`). There is no
`InstCtl_ContactNC/Set/Reset`: NC is handled by InstCtl_ContactNO, and Set/Reset by
InstCtl_Out (it draws `OUT`/`SET`/`RST` and picks the kind from the func code).

Our side: `src/laddercodec/instructions/contact.py`, `comparison.py`, `coil.py`, `out_variant.py`.

## Method and tools

- Accessor codes, read off the disassembly. The brief listed only the int/string codes.
  `0x7db` = u8 get, `0x7dd` = int get, `0x7e1` = string get; `0x7e5` = u8 set, `0x7e7` = int set,
  `0x7eb` = string set. Every flag and index tag in these DLLs uses the u8 pair (7db/7e5), so the
  shared `tag_map.py` (which only knows 7dd/7e1) reports only the string tags.
- `sweep/cc_accessors.py DLL`: lists every `push TAG ... push ACCESSOR` pair. It tolerates
  instructions between the two pushes, which Set/Reset need for `11f5`.
- `sweep/cc_tagtables.py DLL...`: dumps the InstCtl property tables
  (`movzx r, word [i*2+TABLE]`, bounded by `cmp i, N`). These tables are the instruction's
  serialized tag list, in order.
- `sweep/cc_dis.py DLL START END`: range disassembly with IAT names and string annotations.
- `sweep/cc_dwords.py`, `sweep/cc_strings.py`: jump-table and string dumps.
- Full dumps kept: `sweep/_out_full.asm` (Inst_Out), `sweep/_instctl_out.asm` (InstCtl_Out),
  `sweep/_compare_full.asm`, plus `sweep/cc_dialogs_small.txt` and `sweep/cc_dialogs_out.txt`.

### InstCtl property tables (serialization order) — confirmed

| DLL | table | tags |
|---|---|---|
| InstCtl_ContactNO | 1000e000 n=3 | 6065 11f5 3218 |
| InstCtl_Edge | 1000e000 n=3 | 6065 21f6 3218 |
| InstCtl_Compare | 1000f0c0 n=4 | 3218 6066 6067 21f7 |
| InstCtl_Out | 100141ec n=14 | 6066 6067 60b3 60b4 60b5 60b6 11f8 11f5 1246 1247 21f9 2248 3218 20ca |

Every one of these matches our `build_blob` order: `_CONTACT_NO_TAGS`, `_EDGE_TAGS`,
`_COMPARE_TAGS` and `_OUT_VARIANT_TAGS`. Our trailing `0x0000` field is not in any InstCtl table.
It comes from the common serializer, outside this scope. Plain `Coil` (`_COIL_TAGS`, coil.py:57)
emits the v3 subset `6066 6067 11f8 11f5 3218` in the same relative order. That is deliberate:
v4 accepts the v3 form (see memory note on cross-version compat).

---

## ContactNO / ContactNC (Inst_ContactNO.dll, Inst_ContactNC.dll)

Dialog 5000 is "Contact Normally Open" or "Contact Normally Closed". The two dialogs are identical
apart from the func-code base.

| Tag | Acc (load/save) | Control | Our handling | Verdict |
|---|---|---|---|---|
| 6065 | str 7e1/7eb | Edit 5001 "Bit Memory Address:" (member +0x148) | `operand` | MATCH |
| 11f5 | u8 7db/7e5 | Check 5003 "Immediate(Only for X Bit)" (hwnd +0x278). Saved as `BM_GETCHECK != 0` | `immediate` via `tag_flag` (contact.py:192) | MATCH |
| 3218 | int 7e7 (save only) | computed: NO `0x1001 + 2*imm`, NC `0x1002 + 2*imm` (NO @1000210d, NC @100020ed) | `CONTACT_FUNC_CODES` 4097/4099/4098/4100 | MATCH |

- Save order: 6065, 11f5, 3218. Same as ours.
- InstCtl_ContactNO treats the **func code** as the source of NO vs NC. Its immediate setter
  (@10001910) remaps 1001↔1003 and 1002↔1004, and its rendering checks for 1002/1004.
  Our decoder takes NO/NC from the **type code** (0x2711/0x2712) and ignores the func code on
  decode (contact.py:185-193). The two only disagree on a malformed blob whose type code and func
  code conflict. WE IGNORE (func code on decode). Low risk.
- The save path rejects some address types: the dialog checks against `CTD`, `SD`, `TXT` and
  others before saving.
- The dialog only enables Immediate for X addresses. Our `Contact` accepts `.immediate` on any
  operand. This is a validation-only gap.

## Edge (Inst_Edge.dll)

Dialog 3000 "Edge Contact": Edit 1003 "Bit Memory Address:", plus an "Edge Type" group of radios
1000 "Rising Edge(ON when the bit is turned on)" and 1001 "Falling Edge (ON when the bit is turned off)".

| Tag | Acc | Control | Our handling | Verdict |
|---|---|---|---|---|
| 6065 | str | Edit 1003 (+0x148) | `operand` | MATCH |
| 21f6 | u8 | `DDX_Radio(0x3e8)` → member +0xbc: 0 = Rising, 1 = Falling | `edge_kind`. Blob `"0"`/`"1"` (contact.py:153). Decode `!= 0` → fall (contact.py:201) | MATCH |
| 3218 | — (dialog never writes it) | InstCtl_Edge @10001850: 21f6==0 → 0x1005, 21f6==1 → 0x1006. Reverse @10001880: 21f6 = (3218 != 0x1005) | `CONTACT_EDGE_FUNC_CODES` 4101/4102 | MATCH |

- There is no Immediate control. We reject immediate edges. MATCH.
- On load, the dialog uses 21f6 only when its preset member is 0.

## Compare (Inst_Compare.dll)

Dialog 1000 "Compare (A with B)": Edit 5002 "Data A:", Edit 5003 "Data B:", and six bitmap radios
5006..5011 under "Symbol".

| Tag | Acc | Control | Our handling | Verdict |
|---|---|---|---|---|
| 6066 | str | Edit 5002 (+0x318) | `left` | MATCH |
| 6067 | str | Edit 5003 (+0x3a8) | `right` | MATCH |
| 21f7 | u8 | radio index (member +0x200). Click handler @100029b0: index = ctrlid − 0x138e | `COMPARE_OP_TO_TYPE_IDX` / `_TYPE_IDX_TO_OP` | MATCH |
| 3218 | — (dialog never writes it) | InstCtl_Compare @100019b0, jump table @10001a10: 0→0x1007, 1→0x1008, 2→0x1009, 3→0x100a, 4→0x100c, 5→0x100d, default 0x1007 | `COMPARE_FUNC_CODES` 4103..4106, 4108, 4109 | MATCH |

- Radio i gets bitmap i, in load order @10001022/@10001132: 0 `Sym_Equal`, 1 `Sym_NEqual`,
  2 `Sym_GT`, 3 `Sym_LT`, 4 `Sym_GTEqual`, 5 `Sym_LTEqual`. This confirms 21f7:
  0 `==`, 1 `!=`, 2 `>`, 3 `<`, 4 `>=`, 5 `<=`. The grid places `=` over `≠`, `>` over `<`
  and `≥` over `≤`, at x = 133/150/167.
- Reverse map @10001a30, table @10001a8c, for 0x1007..0x100d: 0,1,2,3,**0**,4,5.
  Func code 0x100b (4107) is never generated and reads back as `==`. Our decoder uses 21f7,
  so it is unaffected.
- Save order: 6066, 6067, 21f7. InstCtl then serializes 3218 first. Ours matches the InstCtl order.

## Set / Reset (Inst_Set.dll, Inst_Reset.dll)

Dialog 1000 is "Set" or "Reset". Controls: Edit 5002 "Bit Memory Address1:", Edit 5003
"Bit Memory Address2 (Optional):" (preceded by "to"), and Check 5006 "Immediate(Only for Y Bit)".
There is no One Shot control.

| Tag | Acc | Control | Our handling | Verdict |
|---|---|---|---|---|
| 6066 | str | Edit 5002 (+0x1d0) | `operand` | MATCH |
| 6067 | str | Edit 5003 (+0x260) | `range_end` | MATCH |
| 11f5 | u8 | Check 5006 (hwnd +0x410): raw check state | `immediate` | MATCH |
| 3218 | int 7e7 | Set: range ? `0x2015+imm` : `0x2003+4*imm`. Reset: range ? `0x201b+imm` : `0x2004+4*imm` (@10003739..5b) | latch 8195/8199/8213/8214, reset 8196/8200/8219/8220 | MATCH |

- In the func code, "imm" means the box is checked **and** the window is enabled
  (`ord8345` on +0x3f0). 11f5 itself is written from the raw check state. The two can only
  differ if a stale, disabled check is saved.
- Save order: 6066, 6067, 11f5, 3218. The dialog does not touch 11f8/60b3–60b6 or the other
  tags; InstCtl_Out fills them with defaults.

## Out, including the CLICK v4 variants (Inst_Out.dll + InstCtl_Out.dll)

Dialog 1000 "Out". DDX map @10001c61..10001e5d. Labels and captions come from RT_DIALOG and .rdata.

| Tag | Acc | Control (member) | Dialog semantics | Our handling | Verdict |
|---|---|---|---|---|---|
| 6066 | str | Edit 5002 (+0x3f8) "Bit Memory Address1:" | target | `Coil.operand` / `OutVariant.operand` | MATCH |
| 6067 | str | Edit 5003 (+0x488) "Bit Memory Address2 (Optional):" | Forced `""` when variant ≠ 0 or Toggle is checked (@10005b2c) | `range_end`. OutVariant always writes `""` | MATCH |
| 60b3 | str | Edit 5015 (+0x518) | "On Debounce Time" / "On Flash Time" / "Minimum On Time". Forced `""` when variant = 0 | `on_preset` | MATCH |
| 60b4 | str | Edit 5018 (+0x5a8) | "On … Timer Number" (TD). Forced `""` when variant = 0 | `on_acc` | MATCH |
| 60b7 | str (save only) | derived | 60b4 with char 1 deleted (`TD5` → `T5`, `ord3846(1,1)`) | not emitted | WE DON'T EMIT (correct; see below) |
| 60b5 | str | Edit 5033 (+0x638) | "Off Debounce Time" / "Off Flash Time". Forced `""` when variant is 0 or 3 | `off_preset` | MATCH |
| 60b6 | str | Edit 5036 (+0x6c8) | "Off … Timer Number". Forced `""` when variant is 0 or 3 | `off_acc` | MATCH |
| 60b8 | str (save only) | derived | 60b6 with the D deleted | not emitted | WE DON'T EMIT (correct) |
| 11f5 | u8 | Check 5006 "Immediate(Only for Y Bit)" (hwnd +0xa78). Enabled only for address type 2 (Y), @10002484 | immediate | `Coil.immediate`; `OutVariant.immediate` (toggle only) | MATCH |
| 11f8 | u8 | AutoCheck 5007 "One Shot (Turn on the bit(s) for one scan)" (hwnd +0xaf8) | oneshot | `Coil.oneshot`. OutVariant always `"0"` | MATCH (but see func-code gaps) |
| 1246 | u8 | AutoCheck 5008 "Toggle Output" (hwnd +0x1020) | toggle | OutVariant `"1"` iff toggle | MATCH |
| 1247 | u8 | AutoCheck 5038 "Output Maintained" (hwnd +0x10a0) | timed maintained | `maintained` | MATCH |
| 21f9 | u8 | ComboBox 5013 "Unit", `DDX_CBIndex` → +0x2fa0. Options from .rdata `ms`, `sec`, `min` | 0 ms, 1 sec, 2 min. Only the first **2** options for debounce/flasher (@10005982: count = 3 + (−1 when variant is 1 or 2)) | `TIMER_UNIT_TO_INDEX` (Tms/Ts/Tm) | MATCH |
| 2248 | u8 | AutoRadios 5009..5012 (objects +0x1100 + i·0x7a8, `DDX_Radio(0x1391)`) | 0 "Out/Toggle", 1 "Debounce", 2 "Flasher", 3 "Timed" | `_KIND_INDEX` (toggle 0, debounce 1, flasher 2, timed 3) | MATCH |
| 3218 | — (dialog never writes it) | InstCtl_Out @10004300 (see table below) | | `COIL_FUNC_CODES`, `OUT_VARIANT_FUNC_CODES` | MATCH for the codes we have, gaps below |
| 20ca | — | not in the dialog. InstCtl_Out constructor sets it to `2` (@10003e28). The setter stores it without recomputing. The variant box is drawn only if `20ca == 2 && 2248 != 0` (@10004ffe, @100069bc) | layout/format version | OutVariant always `"2"`. Coil omits it (v3 form) | MATCH / by design |

- **Dialog save order:** 6066, 6067, 60b3, 60b4, 60b7, 60b5, 60b6, 60b8, 11f5, 11f8, 1246,
  1247, 21f9, 2248. The blob order comes from the InstCtl table, which matches ours.
- **60b7/60b8 are virtual. Confirmed:** InstCtl_Out's string-setter tag table (@10003968,
  0x6066..0x60b6) has no slot for them, so the model drops them, and they are not in the
  serialization table. CLICK.exe @005f3d2b..005f4200 (type 0x2715) maps 60b7↔60b4 and
  60b8↔60b6. That looks like an address-usage or replace hook (purpose inferred). It confirms the
  doc note that "Click claims the T of the same number".
- **InstCtl setters clamp values:** 2248 ≥ 4 → 0 (@10007590), and 21f9 ≥ 3 → 0 (@100075c0).
  Every flag/unit/variant setter recomputes 3218 (@10004300). The 3218 setter rewrites the flags
  from the func code (@10004620). Because 3218 comes near the end of the table, **Click treats the
  func code as authoritative when it loads a blob**.
- Dialog defaults, inferred from string refs: debounce presets `100`, flasher `500`, timed
  `1000`. Presets accept a DS address or a numeric constant (range check `≤ 0x7fff` @10007b1c,
  inferred to be the preset). Accumulators are checked against `TD`.
- Variants are gated by CPU capability: a lookup by model string, then `SCLIB(0x97, model)`.
  A result of 0 or 1 disables radios 1–3 and the Toggle checkbox. There is also a version-word
  check against `0x3c8`. This is inferred and not modeled; it is not blob-relevant.

### InstCtl_Out func-code computation (@10004300). Confirmed from disassembly.

kind = Out / Set / Reset, taken from the func code via table @10004af0. "R" = range end (6067)
non-empty, "O" = oneshot (11f8), "I" = immediate (11f5).

| kind | R | O | I=0 | I=1 |
|---|---|---|---|---|
| Out | – | – | 8193 | 8197 |
| Out | – | O | 8205 | **8206** |
| Out | R | – | 8207 | 8208 |
| Out | R | O | **8209** | **8210** |
| Set | – | – | 8195 | 8199 |
| Set | – | O | **8211** | **8212** |
| Set | R | – | 8213 | 8214 |
| Set | R | O | **8215** | **8216** |
| Reset | – | – | 8196 | 8200 |
| Reset | – | O | **8217** | **8218** |
| Reset | R | – | 8219 | 8220 |
| Reset | R | O | **8221** | **8222** |

Out with no range has these further cases:

- Toggle (1246) → 8224 / 8225 (imm). Oneshot is ignored.
- Variant 1 → 8227 if unit = 1, else 8226.
- Variant 2 → 8229 if unit = 1, else 8228.
- Variant 3 → 8230/8231/8232 (unit 0/1/2), or 8233/8234/8235 when maintained.

The variant and toggle paths ignore range, oneshot and (except for toggle) immediate. Bold codes
are **missing from `COIL_FUNC_CODES`** (coil.py:23-37).

The reverse map (@10004620, tables @100047fc/@100047b8) agrees with every row above. It also
assigns 8194, 8198, 8201–8204 and 8223 to "all flags clear". Those are unused codes.

---

## Discrepancies and gaps

1. **Missing coil func codes** (coil.py:23-37). InstCtl_Out models these combinations and
   computes their codes. Our encoder raises `KeyError` in `Coil.func_code` (coil.py:141-143),
   and our decoder sends them to `raw(Out,...)` (coil.py:206).
   - `out(immediate(Y..), oneshot=1)` → 8206. Reachable from the dialog: One Shot is never
     disabled, and Immediate is enabled for Y. Verified locally that
     `Coil.from_csv_token('out(immediate(Y1),oneshot=1)')` parses and then `func_code` raises
     KeyError.
   - `out(A..B, oneshot=1)` → 8209, or 8210 with immediate. The dialog writes range + One Shot
     freely. Reachability is inferred from the dialog code, not observed in a capture.
   - Set/Reset with oneshot → 8211/8212/8215/8216 and 8217/8218/8221/8222. These are model-only:
     the Set/Reset dialogs have no One Shot control and never write 11f8. Our CSV parser accepts
     `latch(...,oneshot=1)` / `reset(...,oneshot=1)` and then fails in `func_code`. Either add the
     codes or reject oneshot for latch/reset at parse time.
2. **Which field is authoritative on decode** (coil.py:212-214, contact.py:185-193). Click
   rebuilds immediate/oneshot/toggle/unit/variant from 3218 when loading. We read the flag tags
   (Coil) or the type code (Contact NO/NC). This only matters for inconsistent blobs. UNSURE
   whether such blobs ever occur in practice.
3. **Validation only.** Immediate is allowed only for X on contacts and only for Y on
   coils/Set/Reset/toggle (dialog labels; Out enables it for address type 2). We do not check this.
4. **60b7/60b8:** written by the dialog but never serialized. No action needed; it is consistent
   with our 15-field OutVariant blob.
5. **4107 (0x100b)** is not a generated compare func code; Click reads it as `==`. Our table
   lacks it, which is harmless because we decode the operator from 21f7.

## Options or modes we don't model

- Out dialog: none beyond item 1. All four radios, the Toggle/One Shot/Immediate/Maintained
  checkboxes, the 3-option unit combo (2 options for debounce/flasher) and the on/off time and
  number edits are covered.
- Out variant combinations that Click accepts but cannot produce: debounce or flasher with
  unit `min` would get the ms code. We already return Raw when the unit and func code disagree.
- The contact dialog constructor checks a mode parameter (0x2711 vs 0x2730); 0x2730 defaults the
  address to `X`. This looks like a "new instruction" entry mode, not a blob field (inferred).

## Unresolved

- Whether 11f8 is ever written as `1` alongside a toggle or variant func code by the real dialog.
  It is harmless: the reverse map clears oneshot, so a Click copy-back writes `0`, matching our
  always-`"0"`.
- The exact preset validation range (the `0x7fff` check is inferred to apply to presets).
- Our coil decoder also accepts class names "Latch"/"Reset" (coil.py:193). Nothing in these DLLs
  confirms or refutes those names; InstCtl_Out handles all three kinds under one object.
