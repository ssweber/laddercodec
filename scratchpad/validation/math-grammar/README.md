# CLICK v4 Math formula: grammar and editor model

Source: CLICK v4.00 `Inst_Math.dll` (Unicode MFC, read from disassembly), `baseEx.dll` string
checks, `SC_ErrorList.ini`, Help CL170/CL187/CL203, the 191 Math blobs in the repo's fixtures,
and the dialog answers in `scratchpad/validation/arc.md`. Nothing in the repo was changed.
Scripts are in `%TEMP%\mathgram\`. The executable model is `model.py`, the fixture check is
`model.py fixtures.json`, and the probes are `predict.py`.

Tags used below: **[code]** read from the DLL; **[obs]** observed in a capture, fixture or
dialog answer (cited); **[inf]** inferred, not read or seen.

Error names: OBJ-1001 "The Formula has an error.", 1002 "The Address cannot be used.",
1004/1005 unmatched `)`/`(`, 1006 "...cannot be calculated", 1008 "The Formula is too long.",
1009 "The entered value is outside the range.", 1010 nesting deeper than 8, 1013 median over
1024 bytes, 1014 range must run Low:High, 1015 range must stay in one block, 1016 CPU lacks
SUM(BIT)/MAX/MIN/MDN/AVG/RAND/ABS, OBJ-037 "Please use a period (.) as decimal point."

---

## 1. Implementation model

### 1.1 Pipeline (OK path) [code]

The OK handler calls one driver with these inputs: the typed text, a hex flag (Decimal/Hex
radio), a nickname-view flag, and an error slot. The driver runs these passes in order and
stops at the first error. Each pass works on one array of up to 500 tokens, each with a type
and a running position, which is used to point at the error.

1. **Tokenizer.** Runs five passes; passes 2 to 4 were only partly read.
   - Pass 1 splits on `+ - * / ^`, on `[` and `]`, and on runs of space/tab. A whitespace
     run becomes its own token. It does not split on `( ) , :`. A `<...>` stays whole up to
     the `>`.
   - Number rule: if the token so far is all ASCII digits and the next character is `.`,
     `E` or `e`, the tokenizer runs `wcstod` from the token's start. The longest prefix
     that parses as a real becomes the token. So `1.5E+10` stays whole, but `1Eh` becomes
     `1` and `Eh`, and `3E8h` becomes `3E8` and `h`.
   - Later passes split out `( ) , :` and keyword names. The keyword finder dispatches on
     the first letter (S A L R C D T P M X O); its inner matching was not fully read.
2. **Classification.** Each token is looked up uppercased in the keyword map: `(`3 `)`4 `[`5
   `]`6 SUM7 SIN8 ASIN9 LOG10 RAD11 COS12 ACOS13 SQRT14 DEG15 TAN16 ATAN17 LN18 PI19 `/`20
   `*`21 `-`22 `+`23 `^`24 MOD25 AND26 OR27 XOR28 LSH29 RSH30 LRO31 RRO32 `,`33 `:`34
   `.`35 MAX39 MIN40 MDN41 AVG42 RAND43 ABS44. A token of only spaces or tabs gets type 2.
   Two other paths follow:
   - With nickname view off, any token that passes baseEx `IsAddress` becomes an address
     (type 37). This happens in **both** modes, so in a hex Math `C1` is the address C1,
     not the constant C1h.
   - With nickname view on, only `<name>` tokens are looked up, through the project's tag
     database and then its nickname list. `<?ADDR>`, the form for an address without a
     nickname, is left as a word that a later pass lets through.
   - Everything else stays type 0, a "word".
3. **Parenthesis check.** More than 8 open → OBJ-1010. A `)` with no `(` → OBJ-1004. A `(`
   left open → OBJ-1005.
4. **Exponent rejoin (decimal only).** Every word is uppercased in place. A word ending in
   `E`, followed by `+`/`-` and another word, is joined into one token (`.5E` `+` `3` →
   `.5E+3`).
5. **Unary sign merge (decimal only).** At the start of the formula, after `(` and after `,`:
   take a `-` or `+`, then the next word with one trailing `H` removed. If that word passes
   `IsFloat`, the sign, any whitespace and the number merge into one word (`( - 5 )` →
   `-5`). Nowhere else, and never in hex mode.
6. **Literal converter.** Runs on each word, with the spaces and tabs inside it removed.
   - **Decimal:**
     - If the word holds only `0-9+-` (`IsNumeric2`): take v = `_wtoi64`. The check
       string is `"+"` if the word starts with `+`, then `"%d"` of v's low 32 bits. If the
       lengths differ → OBJ-1009. Otherwise prefix `H` when v fits in int16, `W` when not,
       and keep the typed text (`+5` → `H+5`).
     - Else if `IsFloat` (strtod parses the whole string; one leading `-` is stripped
       first; ERANGE refused) and `_wtof` fits a float32 → `F` + typed text. Else →
       OBJ-1009.
     - Otherwise the word is left as a word.
   - **Hex:**
     - A word followed by `[` is left alone (pointer bank).
     - Otherwise uppercase it and delete the first `H` anywhere in it. If what is left
       passes `IsHex` (non-empty, `0-9A-F` only): 5 or more digits as typed → OBJ-1009;
       value over FFFF → OBJ-1009; otherwise the token becomes `UH` + decimal value.
   - Words that fail every branch stay words.
7. **Bracket/word check.**
   - Any `[` or `]` still typed as a bracket → OBJ-1001.
   - Any word not of the form `<?...>` → OBJ-1001.
8. **Mode check.**
   - Hex refuses SIN ASIN LOG RAD COS ACOS SQRT DEG TAN ATAN LN PI `^` **ABS**.
   - Decimal refuses AND OR XOR LSH RSH LRO RRO.
   - Either → OBJ-1006.
9. **Grammar checker.** A switch on each token's type, looking at the next non-whitespace
   token, with handlers for the function forms; §2 gives the full rules. It ends with a
   check of the first and last tokens.
10. **Nickname/pointer resolution pass.** Only partly read. It raises OBJ-1002/1006; its
    loops resolve `<name>` and normalize `X[Y]` pointers.
11. **Display printer.** Writes the template display 0x61FF and the formula display 0x6228.
12. **`#` printer.** Writes the template internal 0x6229 and the formula internal 0x61FD. A
    result longer than 270 characters → OBJ-1008.

### 1.2 Competing hypotheses and open conflicts

- **H1. Hex constant without `h`.** The converter code path I read accepts `DH1 + 7` as
  `UH7`, shown `7h`. The dialog refused `DH1 + 7` and `DH1 + 70000` [obs arc.md Q-M13b].
  - `70000` is explained: 5 digits → OBJ-1009.
  - `7` is not explained by the OK path. So there is a check I did not find. Candidates:
    (a) the dialog's live check mark on the formula field (the OK handler reads a
    check-mark colour and shows an error box when it is red, before the driver runs);
    (b) a keyboard/keypad filter.
  - Until it is found, treat "hex needs the `h`" as observed and "the driver would take
    it" as code-only.
  - The same unknown check may also refuse hex words with no `h` that the driver takes
    (`FACE`, `A`).
- **H2. Comma check.** A comma that no function handler consumed goes through two helper
  checks. Each looks up to three tokens back and compares types against fixed lists, but
  the loop compares only the first 19 entries of lists that are longer. Read literally:
  - `x , y` at formula level → OBJ-037 (decimal comma).
  - Some patterns pass, for example `MAX ( DS1 , DS2 )` and `DS1 + 1 , 5`.

  Which patterns are really accepted is **[inf]**. Treat stray commas as unresolved.
- **H3. SUM/MAX/MIN/AVG/MDN/ABS handlers.** Not read past their summaries. Their error
  returns map to OBJ-1001/1002/1013/1014/1015/1016. The CPU gate (OBJ-1016) for
  MAX/MIN/MDN/AVG/RAND/ABS is read [code]. The model assumes `F ( addr : addr )` (ABS: one
  argument) [obs: all fixtures use that shape].
- **H4. `IsAddress` (baseEx) was not read.** Address normalization (`ds01` → `DS1`, `x1` →
  `X001`) comes from laddercodec's own rules. Only `XD0u` keeping a lowercase `u` is
  [obs retyped/math_xd].

### 1.3 Paths not followed

- Tokenizer passes 2 to 4 in detail (keyword splitting inside words such as `DS1MOD2`).
- The nickname/pointer pass.
- The SUM/MAX/MDN/ABS/pointer handlers' bodies.
- RAND's value checks after its shape check (low < high?, data types via the bank table).
- The live check-mark path (H1).
- `IsAddress`.
- The real-number normalizer near the start of the DLL (`%.7G`/`%G`); no caller seen on
  the OK path.

---

## 2. Grammar (after tokenization) [code unless tagged]

Tokens: whitespace is skipped by every rule. `.` (type 35) is skipped by the grammar checker
but refused after `(`, after an operator, and as the first or last token.

```ebnf
formula      = first , { token } , last ;              (* see FIRST/LAST below *)
operand      = constant | address | pointer | PI
             | "(" , expr , ")"
             | call ;
call         = TRIG "(" expr ")"         (* any `,`/`:` inside must be matched by a SUM *)
             | SUM  "(" range ")"        (* body not read; [obs] SUM ( a : b ) *)
             | RANGEF "(" range ")"      (* MAX MIN MDN AVG; [obs] ( a : b ); CPU gate *)
             | ABS "(" expr ")"          (* decimal only; CPU gate; body not read *)
             | RAND "(" arg2 "," arg2 ")"            (* CPU gate *)
             | SHIFT "(" arg1 "," arg2 ")" ;         (* hex only *)
arg1         = address | pointer ;                    (* a constant is refused *)
arg2         = constant | address | pointer ;         (* exactly one token each *)
range        = address , ":" , address ;              (* [inf] from fixtures *)
binop        = "+" | "-" | "*" | "/" | "MOD"
             | "^"                     (* decimal only *)
             | "AND" | "OR" | "XOR" ;  (* hex only *)
TRIG         = SIN|COS|TAN|ASIN|ACOS|ATAN|LOG|LN|SQRT|RAD|DEG ;   (* decimal only *)
PI           = "PI" ;                                              (* decimal only *)
SHIFT        = LSH|RSH|LRO|RRO ;
```

The checker is a follow-set machine, not a recursive parser. These are the rules exactly as
coded, where X → not Y means "X may not be followed by Y":

| token | may not be followed by |
|---|---|
| `(` | `^ * / MOD AND OR XOR , : . ) [ ]` (so `( -x` and `( +x` pass) |
| `)` | `( ` any function, PI, constant, address, `.`, `[ ]` |
| binary op (`/ * - + ^ MOD AND OR XOR`) | `)`, any binary op (**including `-` and `+`**), `, : . [ ]` |
| constant | `(`, any function, PI, constant, address, `[ ]` |
| address | the same set as constant; a **bit** address (X Y C T CT SC) → OBJ-1002 |
| PI | any function, PI, constant, address, `, : . [ ]` (`(` and `)` are not in the list) |
| TRIG | anything but `(` (a pointer is not in the refusal list either) |
| `,` `:` | `)`, any binary op, LSH..RRO, `, : . [ ]`, then the H2 helpers |
| word, `[`, `]` | always OBJ-1001 |

- **FIRST** may be `(`, any function, PI, `-`, `+`, LSH..RRO, constant, address or pointer.
  It may not be `) [ ] / * ^ MOD AND OR XOR , : .`.
- **LAST** must be `)`, `]`, PI, constant, address or pointer.
- Anything else is OBJ-1001.

**Per mode:**

- *Decimal:*
  - Constants are `H`/`W` integers (only `0-9+-`; length round-trip through `%d` of the
    low 32 bits) or `F` reals (whole string parsed by strtod and inside float32). That
    takes in `1.`, `.5`, `1E5`, `1e+5`, `NAN` [inf: NaN slips through the range test],
    and strtod hex reals such as `0x1A` [inf].
  - A signed constant exists only through the unary merge (start, `(`, `,`).
  - Bit addresses are refused outside SUM [code for the address handler; dev's
    "bits only in SUM" agrees].
- *Hex:*
  - A constant is a word that, once its first `H` is deleted, is 1 to 4 hex digits.
  - No sign ever merges, so `( - Ah )` is unary `-` then a constant
    [obs clicknick/minus-ah.bin].
  - Real constants never form: digits before `E` split in the tokenizer, so `1Eh` is
    `1` `Eh` → two constants side by side → OBJ-1001.

---

## 3. Printers [code; confirmed by every native fixture]

**Display printer.** Joins the tokens with single spaces.

- Template display (0x61FF): an address → `@`, a pointer → `@` plus brackets.
- Formula display (0x6228): addresses as classified (normalized; `<name>` kept in
  nickname view).
- Constants:
  - The first prefix found among `UH`, `UW`, `H`, `W`, `F` is removed.
  - `UH`/`UW` print as `%Xh` of the value: uppercase digits, no leading zeros, lowercase
    `h`. So `0fH` → `Fh`, `00h` → `0h`, `7H7` → `77h`.
  - `H`/`W`/`F` print the typed text, uppercased by pass 4 in decimal (`1e5` → `1E5`
    [inf from code, no capture]).
  - `UW` (32-bit hex) exists in the printer but no path creates it.
- The trailing space is dropped.

**`#` printer.**

- Spaces are removed inside each token, so the merged `- 5` becomes `-5`.
- Template internal (0x6229): addresses → `@`. Formula internal (0x61FD) keeps them.
- `F ( a , b )` for RAND and LSH..RRO is written `a#F#b`, and its `(`, `,` and `)` slots
  are emptied.
- Tokens are joined with `#`, skipping empty slots.
- The final trailing-`#` strip tests one character past the end (off by one), so it never
  fires. A formula ending in RAND/LSH keeps a trailing `#` (`H1#RAND#H100#`
  [obs tumbler]).
- Internal length > 270 → OBJ-1008.
- Help CL187 separately says input is capped at 128 characters (edit box) [obs Help].

---

## 4. Check over every Math in the fixtures

`model.py` runs the model on each blob's stored **display** formula, in that blob's mode.
Nicknames are mapped to addresses in the order they appear in the blob's own internal
string. It then compares all four stored views.

- 191 Math blobs (144 distinct view sets; dump in `fixtures2.json`). 82 were written by
  CLICK's editor (cell bytes 1,3: tumbler clipboard, v4_captures math_hex_upper_h /
  math_hex_signed / math_nickname_display / math_typed / sweep_math / retyped math_xd /
  math_neg, clicknick captures). 109 were written by the encoder (1,1).
- **All 82 native blobs re-derive exactly.** 186 of 191 match overall.
- The 5 that differ are all encoder-written `v4_captures/retyped/math_wide.bin`:
  - The 69-address sum: its internal form is about 700 characters, so the model raises
    OBJ-1008. It is also over the 128-character input cap, so CLICK could not have typed
    it.
  - Four XD/YD rungs (`XD0 AND 1h`, `XD0u AND 1h`, `YD1 AND 1h`, `MAX ( XD0 : XD3 )`):
    the encoder stored the address in the template where CLICK writes `@`
    [obs native retyped/math_xd.bin].

Limits: stored displays are already in canonical spacing, so this confirms the converter,
the grammar checker's acceptances and both printers. It does not test the tokenizer on raw
typing.

---

## 5. Dialog predictions (ranked by how much they settle)

Each is typed and then OK'd; give the message or the redisplay.

1. Hex `DH1 + 1Eh` (also `DH1 + 0Eh`, `DH1 + 2E5h`) → **refused, OBJ-1001**. The tokenizer
   splits the digits before `E`. laddercodec accepts these today.
2. Decimal `DS1 * -5` → **refused, OBJ-1001**: an operator may not be followed by a sign.
   `DS1 * ( -5 )` is accepted. laddercodec accepts the first.
3. Hex `DH1 + -Ah` → **refused, OBJ-1001**. This settles the open move9 question.
4. Hex `DH1 + 7`: **which message?** (H1). "The Formula has an error." would point to the
   live check; another text would point to a different filter. Also try `DH1 + FACE` and
   `DH1 + A`.
5. Hex `LSH ( 1h , 2h )` → **refused**: the first argument must be an address or pointer.
   `LSH ( DH1 , DH2 )` is accepted.
6. Decimal `SIN ( MAX ( DF1 : DF3 ) )` → **refused**; `SIN ( SUM ( DF1 : DF3 ) )` →
   accepted (the colon must be matched by a SUM).
7. Hex `DH1 + 7HH` → refused, and `DH1 + H7` → `DH1 + 7h` (the first `H` is deleted, from
   anywhere).
8. Hex `DH1 + C1` → OBJ-1002 (C1 is read as the address, a bit), not `C1h`.
9. Decimal `DS1 + NAN` → accepted, shown `DS1 + NAN` [inf]. `DS1 + INF` → OBJ-1009.
10. Decimal `DS1 + 1e5` → redisplayed `DS1 + 1E5`; `DS1 + 1.` → accepted as `1.`.
11. Decimal `-0` (whole formula) → OBJ-1009; `DS1 + 007` → OBJ-1009 (dev agrees).
12. Decimal `DS1 + TXT1` → the driver does not refuse it. Watch for any message at all;
    OBJ-1003 is never raised inside Inst_Math.
13. Decimal `PI ( 2 )` → passes the checker [code]; what does it store? Also
    `RAND ( PI , 10 )` → refused (PI may not be followed by `,`).
14. Decimal `MAX ( DS1 , DS2 )` and `DS1 + 1,5`: OBJ-037, OBJ-1001 or accepted (H2).
15. Hex `ABS ( DH1 )` and `DH1 ^ 2h` → OBJ-1006 (dev agrees).

---

## 6. Where laddercodec dev disagrees

Dev at `eb7b6f1` already contains move9: the merge of `6157e35`, which also brings in
`ae09c79`, `d16eab3` and `3267568`. The move9 worktree no longer exists. File:
`C:\Users\Sam\documents\github\laddercodec\src\laddercodec\instructions\math.py`.

- **Signs after operators.**
  - `_BEFORE_SIGN` includes `+ - * / ^ MOD AND OR XOR :`. CLICK merges a sign only at the
    start, after `(` and after `,`; after a binary operator a sign is OBJ-1001.
  - Dev accepts and stores `DS1 * -5`, which CLICK refuses (prediction 2).
  - `_normalize_spacing` also rewrites `DS1 - -5` into a single `-5`.
- **Hex constants with digits then `E`.** `_HEX_CONSTANT` matches `1Eh`, `0Eh`, `3E8h`,
  but CLICK's tokenizer splits them (prediction 1). The fix is to refuse a hex constant
  whose digits before the first letter are followed by `E`/`e`. The split itself is code;
  the outcome needs the dialog.
- **No follow-set grammar.** `_check_expression` checks words, parens, mode words, bits,
  ranges, constants and length, but not order. CLICK refuses all of these and dev
  accepts them:
  - `DS1 DS2`, `5 ( DS1 )`, `( ) `, `* DS1`, `DS1 +`;
  - `MOD` first;
  - `PI` before a comma;
  - an operator before `)`.

  A port of the table in §2 would close this. It is short and every line of it is code.
- **Comma-function arguments.**
  - CLICK requires exactly one token per argument: RAND takes const/address/pointer
    twice; LSH..RRO take address/pointer, then const/address/pointer.
  - Dev deliberately accepts compound arguments and writes them in call form (docstring:
    they pass Check Program when pasted). That is a project choice, not a parser match.
  - Dev also accepts a constant first argument to LSH, which CLICK's editor refuses.
- **Trig bodies.** CLICK refuses `,`/`:` inside a trig call unless matched by a SUM; dev
  has no such rule.
- **`7H7`.** Dev refuses it (BOB ruling). The code shows the rule is fixed, not a guess:
  delete the **first** `H` anywhere, then 1 to 4 hex digits. So `7H7` → `77h`, `H7` →
  `7h`, `7HH` refused. Dev is stricter than CLICK. The ruling's cost note ("rule guessed
  from one case") no longer holds.
- **Hex without `h`.** Dev refuses it, as the dialog does [obs]. The code path read would
  accept it (H1). Keep dev as is.
- **Real constants.** Dev's `_NUMBER` refuses `NAN`, `0x1A`, `1.` stays, and dev keeps a
  typed lowercase `e`. CLICK accepts `NAN` [inf], the hex real `0x1A` [inf] and `1.`
  [code], and uppercases `e` [code, no capture].
- **Agreements** [code matches dev]:
  - mode-only words (incl. ABS, `^` and PI decimal-only);
  - nesting 8;
  - the `_wtoi64`/`%d` length rule (`007`, `-0`);
  - four typed hex digits, leading zeros counted;
  - hex display `%Xh`;
  - spaced sign before a hex constant;
  - 270-character internal cap;
  - trailing `#` after RAND/LSH;
  - bit addresses refused outside SUM.
- **Nicknames.** CLICK resolves `<name>` through the project's tag database, which a
  codec does not have. Dev's refusal of a typed `<nickname>` (with the nickname capture
  decoded) is the only safe choice.
