# Drum / Send / Receive vs CLICK v4.00 dialog + InstCtl DLLs

Source: `C:\Program Files (x86)\AutomationDirect\CLICK Ver4.00\{Inst,InstCtl}_{Drum,SD,RD}.dll`,
disassembled with the scripts in this directory (`disasm.py`, `prop_table.py`, `jt.py`,
`drum_fc_tables.py`, `find_fc_table.py`, `dump_u32.py`, `wstr.py`, `drum_fieldcounts.py`).
Listings: `SD.asm`, `RD.asm`, `Drum.asm` (dialogs), `ctl_SD.asm`, `ctl_RD.asm`, `ctl_Drum.asm`
(InstCtl), `ctl_SD_setters.asm`, `ctl_SD_getters.asm`, `ctl_RD_setters.asm`; dialog templates
`dlg_SD.txt`, `dlg_RD.txt`, `dlg_Drum.txt`.

Legend: **CONFIRMED** = read directly from code/data; **INFERRED** = consistent reading of the
code plus a capture, not executed.

Our code: `src/laddercodec/instructions/send_receive.py`, `src/laddercodec/instructions/drum.py`.

---

## 1. Serialized tag order (CONFIRMED, all MATCH)

The InstCtl property-tag tables (the order the blob is serialized in) match our tag tuples exactly.

| Class | Table | Count | Tags |
|---|---|---|---|
| SD | `InstCtl_SD @100223f8` | 34 | 3218 220c 2225 120a 607c 1209 607b 120b 607d 121a 6083 320e 60b2 223a 2211 320f 6085 607e 3210 221c 220d 6217 6081 6082 1220 2214 1221 2215 3216 622a 6889 622b 322c 688f |
| RD | `InstCtl_RD @100213f8` | 41 | 3218 220c 2225 220d 120a 607c 1209 607b 120b 607d 121a 6083 121b 6084 320e 60b2 223a 2211 320f 6085 607e 3210 221c 221d 607f 6080 2212 121e 6086 2213 121f 6087 1220 2214 2215 3216 622b 322c 608d 608e 688f |
| Drum | `InstCtl_Drum @1001d410` | 18 | 3a05 2200 21f9 3203 3204 606e 606f 6070 1201 1202 6071 6872 3a26 6873 20ca 6891 428a 6068 |

Array bounds: SD `6889` index 0..249 (getter `cmp ecx,0xf9`) = 250 slots; `688f` 0..127 = 128
slots. Matches `Send.build_blob` (send_receive.py:445-504) and `Receive.build_blob` (347-405).

---

## 2. Send (SD)

### 2.1 Port / protocol (tag 0x220C) — MISMATCH (gap)

Dialog port combo strings (2011-2018): CPU Port1, CPU Port2, CPU Port3, WLAN Port, Slot0 Port1,
Slot0 Port2, Slot1 Port1, Slot1 Port2. Load maps stored value -> combo index:

| 0x220C | Port | Kind |
|---|---|---|
| 2 | CPU Port1 (Ethernet) | TCP (IP/port fields shown) |
| 0 | CPU Port2 | serial |
| 1 | CPU Port3 | serial |
| 3 | WLAN Port | TCP (IP/port fields shown, IP saved) |
| 4..7 | Slot0 P1, Slot0 P2, Slot1 P1, Slot1 P2 | serial |

CONFIRMED. Our `_COM_PORT_MODE` (send_receive.py:62-69) has no entry for 1 (CPU Port3) or 3
(WLAN). `_build_target` (566-577) treats only "2" as TCP and maps unknown values to `cpu2` via
`_COM_PORT_MODE_INV.get(protocol_mode, "cpu2")` (575): a WLAN Send/Receive decodes as an RTU
target on CPU Port2 (IP lost), and a CPU Port3 one decodes as CPU Port2. Both silently re-encode
to a different port. The same mapping applies to RD.

### 2.2 Func code 0x3218 — CONFIRMED (recomputed by InstCtl_SD @0x1000a230)

| Case | Code |
|---|---|
| Port 2/3 (TCP: Ethernet, WLAN), Modbus | 9736 |
| TCP, indirect slave ID | 9752 |
| Serial Modbus | 9731 |
| Serial Modbus, indirect slave ID | 9751 |
| ASCII static message (220d=0) | 9733 |
| ASCII dynamic message (220d=1) | 9732 |

Constructor default 9731. Our constants `_SD_FC_RTU`/`_SD_FC_TCP` (300-303) cover only 9731/9736.
`_from_tags_sd` (631-654) never reads 0x3218, so 9751/9752/9732/9733 blobs decode as plain Modbus
and lose the variant. ASCII Sends have an empty 0x6085, so `_build_remote_start` returns None and
the blob falls back to RawInstruction — acceptable.

### 2.3 Slave ID: 0x320E / 0x60B2 / 0x223A — MISMATCH (gap)

- 0x60B2 is the slave-ID text the dialog shows; 0x320E is its numeric value.
- 0x223A = 1 when the slave-ID text is an address (`IsAddress`, e.g. `DS1`); then 0x320E = 1.
  Otherwise 0x223A = 0 and 0x320E = `_wtoi(text)`. Func code switches to 9751/9752.
- SD default 0x320E = 0 / 0x60B2 `"0"` (string @`InstCtl_SD 0x10019e40`); RD default 1 / `"1"`
  (@`InstCtl_RD 0x10018f34`). This matches the SCR-elision comments at 607-609 / 633-635.

Our decoders read 0x320E (610, 636), so an indirect slave ID (`DS1`) decodes as device_id 1.
Our encoders write 0x223A = "0" (send_receive.py:476 SD [13], 381 RD [16]).

### 2.4 Status enables (0x120A/0x1209/0x120B/0x121A) — INFERRED: redundant gating

- The dialog never reads or writes the enable tags.
- InstCtl_SD `0x1000fae0` sets each enable to (status string non-empty). It is tail-called from
  the draw/layout routine (`jmp 0x1000fae0` at `0x1000b03f`).
- InstCtl_RD has the same function at `0x1000f740`, covering all 7 RD enables. It is called from
  two draw paths (`0x1000f4c2`, `0x1000f5b6`, both after `SetDrawParam`).
- Rendering draws a status row only when its enable is non-zero.

So CLICK v4 rederives every enable from its string whenever the instruction is drawn. Our SD
decoder drops a status bit whose enable is 0 (send_receive.py:649-652), but the RD decoder
ignores enables (617-627). That asymmetry is harmless for v4-written blobs, where enable ==
non-empty. It loses data only for a blob whose string is set while its enable is 0, which v4
would display. Suggest decoding SD like RD (ignore the enables). Encoder behaviour (enable =
"1" iff string) matches what v4 derives.

### 2.5 Other SD tags (CONFIRMED)

| Tag | Member | Meaning | Ours |
|---|---|---|---|
| 2225 | +0x51 | port protocol: 0 MODBUS, else ASCII (copied from project port setup) | "0" reserved [2]: OK for Modbus |
| 2211 | +0x7e | FC combo 0..3 = 05/06/15/16 | MATCH `_sd_fc_subtype` |
| 320f | +0x80 | address type 0 = 984, 1 = Hex, 2 = CLICK | MATCH |
| 6085 / 607e / 3210 | +0x84/+0x88/+0x8c | remote start / source / quantity (default 1) | MATCH |
| 221c | +0x8e | Word Swap combo 0 = ON, 1 = OFF (default 1) | MATCH (`word_swap_off`) |
| 220d | +0x8f | ASCII radio 0 = Static, 1 = Dynamic Text Message | reserved [20] |
| 6217 | +0x90 | encoded static message list | reserved [21] |
| 6081 | +0x94 | dynamic message start address; setter fills 688f[128] = TXTn..n+127 | reserved [22] |
| 6082 | +0x98 | number of bytes | reserved [23] |
| 1220 | +0x9c | Byte Swap checkbox | reserved [24] |
| 2214 | +0xa0 | 0 All / 1 All but null | reserved [25] |
| 1221 | +0xa4 | Termination Code checkbox | reserved [26] |
| 2215 | +0xa8 | 0 = 1 character, 1 = 2 characters | reserved [27] |
| 3216 | +0xaa | termination code, hex (wcstol base 16) | reserved [28] |
| 622a | +0xb4 | static message text | reserved [29] |
| 6889[250] | +0xb8.. | static-message embedded-address list | 250 x "" |
| 622b / 322c | +0xac/+0xb0 | IP (saved only for ports 2/3) / TCP port (default 502) | MATCH |

All of the "reserved" SD slots are ASCII-mode fields, so our Modbus-only defaults are correct.

---

## 3. Receive (RD)

Same port table, slave-ID logic and enable rederivation as SD (see 2.1, 2.3, 2.4).

### 3.1 Func code 0x3218 (InstCtl_RD @0x1000ad50) — CONFIRMED

| Case | Code |
|---|---|
| TCP (port 2/3) | 9735 |
| TCP, indirect slave ID | 9750 |
| Serial Modbus | 9728 |
| Serial Modbus, indirect | 9749 |
| ASCII fixed length (220d=0) | 9730 |
| ASCII variable length (220d=1) | 9729 |

Ours: 9728/9735 only (send_receive.py:300-301). There is no func-code check in `_from_tags_rd`.

### 3.2 Reserved RD fields resolved (CONFIRMED)

| Our idx | Tag | Meaning |
|---|---|---|
| [2] | 2225 | port protocol (0 MODBUS) |
| [3] | 220d | ASCII data length type: 0 Fixed, 1 Variable |
| [12]/[13] | 121b/6084 | Overflow status enable / bit (ASCII) |
| [16] | 223a | indirect slave ID flag |
| [23] | 221d | ASCII character order combo: 0 'Char1, Char2', 1 'Char2, Char1' |
| [24] | 607f | ASCII data destination; setter fills 688f[128] = TXTn.. |
| [25] | 6080 | ASCII data length |
| [26] | 2212 | Character Interval time-out combo (0 None, 1..5 = 100..500 ms) |
| [27]/[28] | 121e/6086 | Character Interval Time-out status enable/bit (pairing INFERRED from layout) |
| [29] | 2213 | First Character time-out combo (0 None, 1..5 = 100..500 ms) |
| [30]/[31] | 121f/6087 | First Character Time-out status enable/bit (pairing INFERRED) |
| [32] | 1220 | Byte Swap checkbox |
| [33] | 2214 | All / All but null |
| [34] | 2215 | termination 1 / 2 characters |
| [35] | 3216 | termination code (hex) |
| [38]/[39] | 608d/608e | no setter; constant `"SD50"`/`"SD60"` (Received Data Length registers of CPU Port2/Port3) — MATCH |

The RD constructor defaults all 7 enables to 1; we write "0" for 121b/121e/121f
(send_receive.py:377, `_RD_RESERVED_DEFAULTS` 267-281). This doesn't matter in practice because
v4 rederives the enables from the (empty) strings when it draws the instruction (2.4).

Other RD tags MATCH:

- 2211 FC combo: 0 = FC01, 1 = FC02, 2 = FC03, 3 = FC04. The `_build_remote_start` hex
  register-type mapping matches for both RD and SD.
- 320f, 6085, 607e, 3210 (default 1), 221c (default 1 = OFF), 622b, 322c (default 502).

---

## 4. Drum

### 4.1 Func code table — CONFIRMED; MISMATCH for Th + jog

`InstCtl_Drum` has a complete table at `.data 0x1001d010..0x1001d40f`. Each entry is 4 u32
codes [base, reset, jump, jog]. Each block of 4 entries is indexed by
`pins = (jog ? 1 : 0) | (jump ? 2 : 0)` (`0x10006b80`), in the order: none, jog, jump, jog+jump.

| Unit | Time drum (0x2200 = 0) | Time drum, register preset (0x2200 = 0, 428a != 0xFFFF) | Time & event (0x2200 = 2) |
|---|---|---|---|
| Tms | 8455/8456 · jog 8458.. | 10247/10248 · jog 10250.. | 10503/10504 · jog 10506.. |
| Ts | 8462 · jog 8465 | 10254 · jog 10257 | 10510 · jog 10513 |
| Tm | 8469 · jog 8472 | 10261 · jog 10264 | 10517 · jog 10520 |
| **Th** | 8476 · jog **8480** | 10268 · jog **10272** | 10524 · jog **10528** |
| Td | 8484 · jog 8487 | 10276 · jog 10279 | 10532 · jog 10535 |
| Event | 8491 · jog 8494 | | |

Full rows (base, reset, jump, jog):

- Th time: `8476 8477 0 0`, `8480 8481 0 8482`, `8476 8477 8478 0`, `8480 8481 8482 8483`.
- Th time & event: `10524 10525 0 0`, `10528 10529 0 10530`, `10524 10525 10526 0`,
  `10528 10529 10530 10531`.

Two independent tables confirm the Th offset:

- The "is jog group" check (`0x10006bb0`, byte table `0x10006bec`) is true exactly for
  {8458, 8465, 8472, **8480**, 8487, 8494}.
- The "has jump" check (`0x10006c20`) lists 8457, 8460, 8464, 8467, 8471, 8474, 8478,
  **8482**, 8486, 8489, 8493, 8496.

In every unit the no-jog group is at block+0 and the jog group at block+3, **except Th, where
the jog group is at block+4**. Code 8479 (10271, 10527) is the unused one, not 8483.

**Bug:** `_compute_func_codes` (drum.py:236-271) uses `block_base + 3..+6` for every unit, so a Th
time drum or Th time & event drum with jog enabled encodes 8479/8480/(8481)/8482
(10527/10528/...) instead of 8480/8481/(8482)/8483 (10528/...). The comment at drum.py:34-36
("Td (+8; code 8483 is skipped/reserved)") and docs/internals/instruction-blobs.md:105-106
("same Td skip") place the gap in the wrong block. The Td base codes themselves are right.
No fixture covers a Th drum with jog, which is why tests pass. Fix: give Th a jog-group offset of
+4 (or tabulate all four rows per unit from the table above).

The decoder ignores 0x3A05, so decoding is unaffected.

### 4.2 Tag 0x428A — CONFIRMED meaning: "preset is a constant" bitmask

- InstCtl member +0xE0, constructor default -1 (`0x100061ab`). The setter (`0x10009300`) is only
  reached through the property path.
- The dialog (`Inst_Drum`) loads it into +0x3fa0. On OK it resets it to -1 and validates each step
  preset: the 0x6872 edit for a time drum, the 0x6891 edit for time & event. For a non-empty
  preset that `MemoryAddress::CheckInputData` classes as an address, on CPUs whose capability
  query 0x97 returns 2 or 3, it does `btr eax, step` (`0x100080ba..c3`), clearing bit `step`.
  Constants and blank steps keep their bit.
- Func-code selection (`0x10007af0` etc.): for a time drum, if `word [+0xE0] == 0xFFFF` use the
  8455 series, else the 10247 series. Time & event always uses the 10503 series. Event drums use
  their own table.

This explains both observations:

- drum__te_ds has `presets=[DS1301,None]`, so bit 0 is cleared and the value is **-2**
  (tests/test_v4_captures.py:193).
- "A time drum switched to Time & Event and back came out -4 with Tms 10247/10248"
  (docs/internals/instruction-blobs.md:114-116): bits 0-1 were cleared, so the drum moved to the
  register-preset series.

**Gaps:**

1. drum.py:347-349 always writes `-1`. A time & event drum with a register preset (e.g.
   drum__te_ds) therefore encodes a state CLICK wouldn't write. Compute
   `428a = -1 & ~sum(1 << i for i, p in enumerate(presets) if p is an address)`, as a signed
   32-bit value. Whether CLICK misbehaves at compile/run time with the stale -1 is INFERRED risk,
   not observed. CLICK only recomputes the value when the dialog is OK'd; a paste keeps the blob
   value.
2. Time drums with register presets use the 10247 series in v4, but we always encode 8455-series
   (`_TIME_FC`) and emit the 64-field blob without 428a. On paste v4 defaults 428a to -1, giving
   an 8455-series drum with register presets — a state the v4 dialog never produces.
   INFERRED; no capture.
3. The decoder ignores 428a and 0x3A05, so time drums with 10247-series codes decode fine. The
   re-encode writes 8455-series codes (see 2).

The `drum.py` docs/comments call 428a "unexplained"; it can now be documented.

### 4.3 Other Drum tags (CONFIRMED)

- 0x2200 base: dialog radios Time Base / Event Base / Time && Event, stored 0/1/2. MATCH
  (drum.py `_BASE_*`).
- 0x21F9 unit (combo 5003): index 0..4 = ms/s/min/h/day. MATCH.
- 0x1201 jog / 0x1202 jump: stored as flags (getters `0x10005a40`/`0x10005a50`). MATCH.
- 0x20CA: byte member +0x50, constructor 2, never written by the dialog. MATCH: constant "2".
- 0x6068 getter (`0x10008a50`): returns the timer done bit for base 0 and 2, and "" for event
  drums.
- v4 writes the 82-field blob for every drum kind, time and event included (all 14 drums in
  v4_captures drum.bin / drum_jog.bin / pins.bin have field count 82). Our 64-field form for
  time and event drums is the v3 shape, which v4 accepts per existing captures.

---

## 5. Unresolved / not checked

- Which CPU models make capability 0x97 return 2/3 (the gate for register-preset bit clearing).
- Whether a pasted time & event drum with register presets and 428a = -1 compiles or runs
  differently from the dialog-written -2.
- ASCII Send/Receive end-to-end (we fall back to raw; not decoded).
- SD save writes fields in a different order than the property table. Serialization follows the
  table, so this is irrelevant to the blob.
- 6087/6086 label pairing (First Character vs Character Interval) comes from dialog layout plus
  member grouping. tag_map.py's labels were wrong.
- No v4 Send/Receive capture exists in tests/fixtures/v4_captures. Recommended captures:
  - WLAN-port Send
  - CPU Port3 Receive
  - indirect slave ID (DS) Send
  - Th time drum with jog
  - time drum with a DS preset
