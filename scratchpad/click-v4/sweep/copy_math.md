# Copy / Math: CLICK v4.00 dialog DLLs vs laddercodec

Sources: `Inst_Copy.dll`, `InstCtl_Copy.dll`, `Inst_Math.dll`, `InstCtl_Math.dll` (v4.00), plus
`Inst_Copy.dll` v3.92 / v2.60 for history. Our side: `src/laddercodec/instructions/copy.py`, `math.py`.

Legend: **[D]** confirmed from disassembly, **[C]** confirmed from native captures in `tests/fixtures`,
**[I]** inferred.

Helper scripts written for this sweep (in this directory): `disasm_range.py` (address-range disasm
with string/import annotation), `member_xref.py` (refs to `[reg+disp]`), `dump_blobs.py` (tag dump of
every blob of a class in .bin files), `copy_survey.py` (value combos of native Copy blobs),
`dump_words.py`, `dump_doubles.py`, `vcl_fields.py` (C++Builder field-table names, for v3.92).
Raw outputs: `copy_*.asm`, `math_all.asm`, `copy_dialogs.txt`, `math_dialogs.txt`, `dfm392/`.

---------------------------------------------------------------------------------------------------

## 0. What actually reaches the clipboard: the InstCtl property tables  [D]

The dialog's get/set calls go to an in-memory object; the blob is written from a fixed per-class
tag table in `InstCtl_<Name>.dll` (index function bounds-checks the index, then
`movzx ecx, word [eax*2 + TABLE]`).

| Class | Table VA | Count | Tags in order |
|---|---|---|---|
| Copy | `InstCtl_Copy.dll` 0x10014000 | 12 (`cmp eax,0xc`) | 6074 6075 6076 6077 2206 11F8 2223 3218 2227 1221 3216 1201 |
| Math | `InstCtl_Math.dll` 0x10010000 | 11 (`cmp eax,0xb`) | 6065 11FE 11F8 61FF 6228 6229 61FD 3218 2224 6888 688C |

Both are exactly our `_COPY_TAGS` (copy.py:87-101, plus the 0000 terminator) and `_HEADER_TAGS` +
slots (math.py:75-85). **Serialization order MATCH.** The dialog's own set order differs (see below)
but is irrelevant, the table decides the blob order.

Value widths from the InstCtl getters [D]: Copy 11F8/1201/1221 dword, 2206/2223/2227 **byte**,
3216/3218 **signed int16** (`movsx word`), 6074-6077 string. Math 2224 byte, 3218 int16.
Bool-ish tags (0x1xxx) are written by the dialog as `BM_GETCHECK` (=1) yet appear as `-1` in
blobs, so the serializer normalizes bools to -1 [I, consistent with every capture].

Dialog-only tags (set by the v4 dialog, absent from the tables, never in any capture [C]):

| Tag | Set on save | Meaning |
|---|---|---|
| Copy 6078 | `""` always | v3.92 RTTI: bound to `edtErrorFlag` (hidden "Error Flag" address, `grpErrorFlag Visible=False`) [D v3.92] |
| Copy 1222 | 0 always | v3.92: `chkErrorFlag` (hidden Error Flag checkbox) [D v3.92] |
| Copy 292D[0..5] | 0 (indexed int set 0x7e8) | unknown, not serialized |
| Math 2280 | `""` | InstCtl_Math has a getter case for it but it is not in the table |
| Math 292D[0..1] | 0 | unknown, not serialized |

These need nothing from us: **WE DON'T EMIT, correctly.**

Func code 3218 is never touched by either dialog [D]; it is computed elsewhere (CLICK.exe). Our
tables (Copy 8960/62/76/78/80 +1 oneshot, Math 8451-8454) are capture-backed [C].

---------------------------------------------------------------------------------------------------

## 1. Copy (`Inst_Copy.dll`, dialog 1000)

### 1.1 Controls  [D, DDX at 0x10001b51..]

| Ctl id | Type | Caption / role | Member |
|---|---|---|---|
| 5000-5004 | radio (bitmap) | Copy Type: Single / Block / Fill / Pack / Unpack (index = 2223) | objects at 0x988 + type*0x7a8 |
| 0x138E / 0x1391 | edit | Source start / Source end | 0x328 / 0x3b8 |
| 0x1396 / 0x1399 | edit | Destination start / end | 0x448 / 0x4d8 |
| 0x139B / 0x139C | radio pair B0/B1 | Option radios, caption set per context (below) | 0x3410 / 0x3490, DDX_Radio -> 0xc0 |
| 0x13AC / 0x13AD | radio pair B2/B3 | "Suppress zero" / "Do not suppress zero" sub-option (int->TXT only) | 0x3510 / 0x3590, DDX_Radio -> 0xd0 |
| 0x139D | checkbox | Termination Code | DDX_Check -> 0xd4, CWnd 0x908 |
| 0x139F | edit | termination code "(ASCII HEX Code)" | 0x568, CString 0xf4 |
| 0x139E | button | ASCII Table | |
| 0x13AE | static | computed "TXTn" where the terminator lands | 0x5f8 |
| 0x13A0 | checkbox | One Shot (Execute one time) | 0x888 (hwnd 0x8a8) |

Edit limits [D, 0x10001db2]: source edit 130 chars (`EM_LIMITTEXT 0x82`, room for a quoted text
constant), the other three address edits 16 chars.

### 1.2 Load path (0x1000ea70) [D]

| Tag | Getter | Goes to |
|---|---|---|
| 2223 | int | 0xb8 copy type; checks radio `type`; `0x100021a0(type)` lays out the dialog |
| 2227 | int | 0xc8 conversion type; `0x10012600(conv)` checks the option radios from it |
| 6074-6077 | str | the four edits |
| 6078 | str | **read and discarded** |
| 2206 | int | **read and discarded** |
| 1222 | int | **read and discarded** |
| 1201 | int | **read and discarded** |
| 1221 | int | 0xd4 = (v != 0); enables 0x13A2/0x13AE/0x139F/0x139E |
| 3216 | int | low word formatted `"%X"` into the termination edit |
| 11F8 | int | One Shot `BM_SETCHECK` |

So the v4 dialog derives the whole option state from **2227 alone**; 2206 and 1201 are not inputs.

### 1.3 Save path (0x1000edc0) [D], dialog set order

6074, 6075, 6076, 6077, 6078="", 2206, 11F8 (BM_GETCHECK), 1222=0, 2223=[0xb8], 2227=[0xc8],
1221, 3216, **1201 = -1 unconditionally**, 292D[0..5]=0.

- 2206: if B2 (0x13AC) visible and enabled: B2 checked -> 0, else 1; if B2 visible but disabled -> 2;
  otherwise 2206 = [0xc0] (the B0/B1 radio index).
- 1221 = termination checkbox checked **and** enabled ? 1 : 0.
- 3216 = `wcstol(termination edit text, NULL, 16)`, written even when 1221 = 0.
- Validation (0x1000827e / 0x100134b0): the termination text must parse as hex <= 0xFF, else message
  0x2734 with range `"$00"`..`"$FF"`.

### 1.4 Conversion type 2227 / format option 2206 by context  [D]

Context function 0x10011b60(srcType&0xfff, srcType&0xf000, dstType&0xfff, dstType&0xf000) sets
context 0xc4 and the radio captions. Type codes inferred from the captions + captures:
0x02 = DS (incl. SD), 0x04 = DD, 0x08 = DF, 0x10 = DH, 0x40 = TXT [I, every pairing below agrees
with a capture where one exists]. Then 0x10012800 maps (context, radios) -> 2227 and [0xc0].

| Copy type | Source -> Dest | Context | B0 caption -> (2227, 2206) | B1 caption -> (2227, 2206) | Captured |
|---|---|---|---|---|---|
| Single | DS/DD/DH -> TXT | 3 | "Copy Value" + B2 "Suppress zero" -> (1, 0); + B3 "Do not suppress zero" -> (2, 1) | "Copy Binary" -> (8, 2) | 1/0, 2/1, 8/2 [C] |
| Single | DF -> TXT | 1 | "Real Numbering" -> (3, 0) | "Exponential Numbering" -> (4, 1) | 4/1 only [C] |
| Single | TXT -> DS/DD/DH | 2 | "Copy Character Value" -> (5, 0) | "Copy ASCII Code Value" -> (6, 1) | 5/0, 6/1 [C] |
| Single | DD -> DF, DF -> DD | 4 | "Copy Value" -> (7, 0) | "Copy Binary" -> (8, 1) | none |
| Block | TXT -> DS/DD (DH*) | 2 | "Copy Character Value" -> (5, 0) | "Copy ASCII Code Value" -> (6, 1) | 5/0, **6/0** [C, pre-v4] |
| Pack | TXT -> DS/DD/DH/DF, feature-gated** | 5 | "Disallow whitespace" -> (9, 0) | "Allow whitespace" -> (10, 1) | 9/0, 10/1 [C] |
| any other combination (constants, same-type, DF->DS, fill, unpack, pack bits/words) | | -1 | options disabled -> 2227 = 0 | | 0 [C] |

\* Block TXT->DH only when the dest's type string is "DH". Single TXT->SD keeps context 2 but shows
the radios disabled with suppress-zero captions.
\** Pack text and the termination code both sit behind the same SCFS call
`[0x10022e74](0, 0x97, cpuWord)`: when it returns 0 or 1 the options are skipped. Math gates its
v4 function buttons on the same 0x97 query (section 2.3). Probably a CPU/firmware capability [I].

Full 2227 range written by v4: **0-10**. Context 0 (conv 1/2 from B0 alone) is never set by the
context function and is unreachable [D].

### 1.5 Termination code availability (0x10012c00) [D]

Enabled only when the feature-0x97 gate passes and **dest is TXT**, for copy type **Single, Block or
Fill** (`b8` 0, 1, 2). Disabled (and 1221 forced 0) when the computed terminator address falls outside
TXT1..TXT1000. Source type doesn't matter: DS->TXT in any option, TXT->TXT, constant->TXT all allow it.

### 1.6 Tag-by-tag verdicts, Copy family

| Tag | DLL meaning | Ours | Verdict |
|---|---|---|---|
| 6074 | Source (start) | source / source_start / value | MATCH |
| 6075 | Source end | source_end ("" single/fill/unpack) | MATCH |
| 6076 | Destination (start) | destination / dest_start | MATCH |
| 6077 | Destination end | dest_end ("" single/pack) | MATCH |
| 2206 | option radio index (0/1, 2 = int->TXT binary) | copy.py:332-337 single; 446 block "0"; 597-603 pack | Single: MATCH for 1/2/4/5/6/8. **Block to_ascii: v4 dialog writes 1, we write 0** (copy.py:446); the pre-v4 native capture also has 0, and v4's load ignores 2206, so MINOR/UNSURE. Decode ignores 2206: WE IGNORE (harmless, v4 does too) |
| 11F8 | One Shot | oneshot, -1 | MATCH |
| 2223 | copy type 0-4 | `[6]` per class, from_tags dispatch | MATCH |
| 3218 | func code (not dialog) | COPY_FUNC_CODES | MATCH [C] |
| 2227 | conversion type 0-10 (table 1.4) | `_CONVTYPE_TO_OPTS` copy.py:57-65 | **MISMATCH / GAP**, see 1.7 |
| 1221 | termination checked and enabled | term_flag | MATCH for single copy. **Block/Fill: WE IGNORE** (decode drops it, encode writes 0) |
| 3216 | termination char, hex text -> int, $00-$FF | term_char decimal | MATCH (range matches `_ascii_code` 0..0xFF). v4 may store a nonzero 3216 with 1221=0; we decode that as no termination, which is the right meaning |
| 1201 | v4: **always -1** on save, ignored on load. v3.92: bound to hidden `chkDummy`, set from the termination checkbox (`[0x3f4]` vmt+0x50 -> `[0x408]`, 0x407194) | text_flag = -1 for termination or text-constant source (copy.py:346-348) | Encoder matches every capture (pre-v4: 0 unless termination; v4 text-constant copies: -1). The "text constant" rule is really "saved by the v4 dialog": a v4 copy-back of *any* Copy edited in v4 will carry -1. Decode ignores it: WE IGNORE (correct, v4 ignores it too) |

### 1.7 Discrepancies and gaps (Copy)

1. **2227 = 3 missing (DF -> TXT "Real Numbering").** It is the first radio for DF->TXT, so a
   default DF->TXT copy written by CLICK carries 3. `_CONVTYPE_TO_OPTS` (copy.py:57-65) has no "3",
   so `from_tags` returns None (copy.py:739-741) and the instruction falls back to `raw()`. [D]
2. **2227 = 7 missing (DD <-> DF "Copy Value").** Same fallback to raw. [D] No capture.
3. **Encoder conv formula is wrong outside the captured points** (copy.py:332):
   `1 + (1 - sz) + 3*exp` gives
   - DF source with `to_text(suppress_zero=1, exponential=0)` -> 1, CLICK writes 3;
   - `to_text(suppress_zero=0, exponential=1)` -> **5, which is "Copy Character Value" (to_value)**;
     decode then reads it back as `to_value`. Silent corruption.
   - The DLL has no suppress-zero choice for DF->TXT and no real/exponential choice for
     DS/DD/DH->TXT. The two knobs belong to different source types, so the model is per source type:
     int->TXT {suppress (1), no suppress (2), binary (8)}, DF->TXT {real (3), exponential (4)}.
     Our label for 4, `("text", "1", "1")`, is a naming convention only. The CSV for the
     `copy__to_text_exp` capture says `suppress_zero=1,exponential=1`, but suppress zero isn't
     an option there.
4. **"binary" 2206 depends on context**: int->TXT binary = (8, 2) [C]; DD<->DF binary = (8, 1) [D].
   We always write 2 (`_FORMAT_TO_FIELD4`, copy.py:76-81). Minor, since v4 load ignores 2206.
5. **Termination codes are wider than `to_text`**: available for any Single/Block/Fill copy whose
   dest is TXT. `Copy.to_csv` only prints `termination_code` inside `to_text(...)` (copy.py:304-310)
   and the parser only reads it from there (copy.py:277-281, 843-847). So `copy("ABC",TXT1)` or
   `copy(TXT1,TXT5)` or `to_binary` with a terminator decodes with `termination_code` set but
   **writes CSV without it** (lossy). `BlockCopy`/`Fill` have no termination field at all: the
   decoder drops 1221/3216 (copy.py:761-784) and the encoder writes 0 (copy.py:451-452, 520-521).
6. Pack/Unpack bits vs words is guessed from `source.startswith("C")` / `destination.startswith("C")`
   (copy.py:796, 812). The DLL has no bits/words flag (both conv 0), so the bytes are fine, but the
   CSV name is wrong for X/Y/T/CT/SC bit sources (-> `pack_words`) and for CTD words (-> `pack_bits`).
   Not DLL-derived; it's a logic note.
7. Dialog options we don't model: hidden Error Flag (6078/1222, never serialized); the 0x97 feature
   gate on pack-text and termination (CPU dependent); the TXT1..TXT1000 terminator bound.

---------------------------------------------------------------------------------------------------

## 2. Math (`Inst_Math.dll`, dialog 1000)

### 2.1 Controls  [D, dialog_dump]

Result edit 2001 (limit 26 chars, `EM_LIMITTEXT 0x1a`); Formula RichEdit 2006 (**limit 500 chars**,
`EM_EXLIMITTEXT 0x1f4`); Type radios Decimal 2003 / Hex 2004; One Shot 2005; display radios
Address 2007 / Nickname 2008; formula pad buttons 2010-2060.

### 2.2 Load (0x10003d04) / save (0x10002a30) [D]

| Tag | Load | Save | Ours | Verdict |
|---|---|---|---|---|
| 6065 | Result edit; also per-mode result slot `[0x15c + mode*4]` | `[0x15c + mode*4]` | result | MATCH |
| 11FE | mode = (v != 0), 0 Decimal / 1 Hex | `[0x148]` | mode, "-1"/"0" | MATCH |
| 11F8 | One Shot | BM_GETCHECK | oneshot | MATCH |
| 2224 | per-mode Address/Nickname radio `[0x154 + mode*4]` | same, 0/1 | `"1" if show_nicknames else "0"` | MATCH encode (native `2224='1'` [C]). Decode ignores: WE IGNORE (harmless) |
| 6228 | formula display, shown in the RichEdit (nickname form when 2224=1) | `[0x14c]` | formula_display | MATCH. Decode prefers 61FF+61FD and falls back to 6228, which is right because 6228 may hold `<nicknames>` |
| 61FF | **read and discarded** | arg (template) | template_display | MATCH (v4 regenerates it) |
| 61FD | `[0x150]` internal formula | `[0x150]` | formula_internal | MATCH, literal prefixes aside (2.4) |
| 6229 | **read and discarded** | arg (template internal) | template_internal | MATCH |
| 6888[i] | (none) | first all 500 cleared, then one per token of type 0x25 (address) | operands | MATCH (well covered by `test_v4_captures`) |
| 688C[j] | (none) | `[0x1ac][j]` for j < `[0x1b0]`; index argument continues the operand counter | interiors from 0 | MATCH on bytes: captures start at index 0 [C]. The dialog passes `n_ops + j` [D], so the setter must append or compact [I] |
| 2280, 292D | (none) | "" / 0 | not emitted | correct (not serialized) |

0x10001740 returns 5000 [D]; that is v4's reserved-slot capacity (matches `_V4_RESERVED_SLOTS`).

### 2.3 Function availability [D, 0x10003f40]

- Hex only: A-F, AND, OR, XOR, LSH, RSH, LRO, RRO.
- Decimal only: SIN ASIN LOG RAD COS ACOS SQRT DEG TAN ATAN LN PI, `^`, `.`, **ABS**.
- Both: ( ) SUM, digits, / * - +, MOD, MAX MIN MDN AVG RAND.
- MAX MIN MDN AVG RAND ABS are disabled when the SCFS 0x97 query returns 0 or 1 (same gate as the
  Copy features).
- Parser names [D, strings]: exactly the button set plus `name(` forms. No hidden functions.

We don't validate function vs mode (e.g. SIN in hex, AND in decimal) or the 500-char limit:
**WE DON'T MODEL** (encode-side validation only). `RESERVED_NAMES` (math.py:112-136) lacks MAX MIN MDN
AVG RAND ABS, but it only filters `_ADDR_RE` matches, so this is harmless.

### 2.4 Internal literal prefixes (formula 61FD / 6229) [D, 0x1000ead1-0x1000ee46 encode, 0x1000aaba decode]

| Literal | CLICK writes | Ours (math.py:280-287) | Verdict |
|---|---|---|---|
| integer -32768..32767 | `H` + decimal | `H` | MATCH |
| integer -2147483648..2147483647 outside int16 | **`W` + decimal** | `H` | **MISMATCH**: e.g. `100000` -> CLICK `W100000`, we write `H100000`. No capture has a literal over 32767; the largest is `H10000` [C] |
| integer outside int32 | error 0x2B01 | `H` | we don't reject it |
| real, abs <= FLT_MAX, finite | `F` + text | `F` | MATCH |
| hex constant <= 4 digits and <= FFFFh | `UH` + decimal | `UH` | MATCH |
| hex constant of 5+ digits or > FFFFh | error 0x2B01 (no `UW` emitted by the editor) | `UH` + value | we don't reject it |
| (decode side) prefixes recognized | UH, UW, H, W, F; UH/UW are redisplayed `%Xh` | n/a: decode takes literals from 61FF | `UW` exists only on the decode side. It may come from other writers or older data [I] |

---------------------------------------------------------------------------------------------------

## 3. Unresolved / not done

- The meaning of the address type codes (0x02/0x04/0x08/0x10/0x40 and the 0x1000/0x8000 high bits)
  is inferred from captions and captures, not from `cool::base::MemoryAddress::CheckInputData`.
- No capture yet for DF->TXT real (3), DD<->DF value/binary (7/8), Block/Fill with a termination
  code, or a v4-saved block copy to_ascii (to settle 2206 = 1 vs 0).
- What the SCFS 0x97 capability is (CPU model or firmware) wasn't traced (it lives in SCFS.dll).
- Whether v4's compiler (CLICK.exe) reads 2206/1201 wasn't checked; both dialogs ignore them on load.
- v3.92 chkDummy: vmt+0x50 on the termination checkbox is read as GetChecked (fits the capture where
  DS->TXT has no terminator and 1201=0); GetEnabled would contradict that capture.
