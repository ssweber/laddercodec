# CSV Format

laddercodec uses a 33-column CSV format for describing ladder rungs. This is the same format used by clicknick and pyrung's `to_ladder()` export.

## Column layout

| Column | Name | Content |
|---|---|---|
| 0 | Marker | Row type: `R` (first row), `#` (comment), `""` (continuation/pin row) |
| 1–31 | A–AE | Condition columns (wire tokens or instruction tokens) |
| 32 | AF | Output column (instruction token, `NOP`, or blank) |

## Template

A minimal single-rung CSV you can copy-paste and modify:

```csv
marker,A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z,AA,AB,AC,AD,AE,AF
R,X001,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,-,out(Y001)
```

## Wire tokens

The condition columns accept four tokens:

| Token | Meaning | Binary flags (right, down) |
|---|---|---|
| `-` | Horizontal wire | (1, 0) |
| `\|` | Vertical down | (0, 1) |
| `T` | Branch junction | (1, 1) |
| *(blank)* | No wire | (0, 0) |

## Instruction tokens

### Condition side (columns A–AE)

Contacts, comparison contacts, and wire-down prefixed contacts appear in condition columns:

| Example | Meaning |
|---|---|
| `X001` | NO contact |
| `~X001` | NC contact |
| `rise(X001)` | Rising edge |
| `fall(X001)` | Falling edge |
| `immediate(X001)` or `X001.immediate` | Immediate NO |
| `~immediate(X001)` | Immediate NC |
| `DS1==DS2` | Comparison (EQ) |
| `DS1!=100` | Comparison (NE, literal) |
| `T:X001` | Contact with vertical-down wire |
| `T:~X002` | NC contact with vertical-down wire |
| `T:rise(C1)` | Edge contact with vertical-down wire |

### AF side (column AF)

| Example | Meaning |
|---|---|
| `out(Y001)` | Output coil |
| `latch(Y001)` | Latch coil |
| `reset(Y001)` | Reset coil |
| `out(C1..C8)` | Range output |
| `out(immediate(Y001))` | Immediate output |
| `on_delay(T1,TD1,preset=1000,unit=Tms)` | On-delay timer |
| `off_delay(T1,TD1,preset=500,unit=Tms)` | Off-delay timer |
| `NOP` | No operation |
| `raw(ClassName,hex)` | Opaque blob passthrough |
| *(blank)* | No instruction |

## Comments

Comment lines start with `#` in the marker column. Multiple `#` rows form a multi-line comment. Markdown-style inline formatting is supported:

```csv
#,**Motor Start**,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
#,_See electrical drawing E-101_,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
R,X001,-,-,,,,,,,,,,,,,,,,,,,,,,,,,,,,out(Y001)
```

- `**text**` → bold
- `*text*` or `_text_` → italic
- `__text__` → underline

## Multi-rung CSV

Multiple rungs are separated by empty rows. Each rung starts fresh with its own comment lines (if any) followed by data rows:

```csv
#,First rung comment,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
R,-,-,-,,,,,,,,,,,,,,,,,,,,,,,,,,,,out(Y001)

#,Second rung,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
R,X001,-,-,,,,,,,,,,,,,,,,,,,,,,,,,,,,out(Y002)
```

## Pin rows

Pin rows are continuation rows whose AF token starts with a dot (`.reset()`, `.down()`, etc.). They modify the instruction on the row above rather than producing a separate AF instruction:

```csv
R,X001,-,-,,,,,,,,,,,,,,,,,,,,,,,,,,,,on_delay(T001,TD1,preset=1000,unit=Tms)
,X002,-,-,,,,,,,,,,,,,,,,,,,,,,,,,,,,,.reset()
```

The `.reset()` row makes the parent timer retentive (`retained=True`). Its condition columns contribute the reset-enable branch.

## Tall instructions

Some AF instructions occupy more than one grid row:

| Instruction | Grid rows |
|---|---|
| Contacts, coils | 1 |
| Timers | 2 |

If a timer rung has only 1 data row in the CSV, the parser auto-pads with a blank continuation row. You can also write the second row explicitly.

## Validation rules

- `T` and `|` are rejected on the last row (vertical-down has nowhere to go)
- `T` and `|` are rejected on column A (no room for the branch)
- At most one `NOP` per rung
- AF column must be explicit: `""`, `"NOP"`, or an instruction token
