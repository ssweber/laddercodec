# Copy `as_*` wrapper parsing plan

## Current state

Copy module (`instructions/copy.py`) handles flat CSV tokens:
- `copy(DS7,DS8)` — basic
- `copy(DS7,DS8,oneshot=1)` — with oneshot
- Text option kwargs emitted when non-default

## Goal

Parse `as_*` wrappers in the source (first positional arg) of `copy()`.
The CSV keeps the wrappers; laddercodec unpacks them into Copy fields.

## CSV formats to support

```
copy(DS7,DS8)                          → format=none, source=DS7
copy(42,DS9)                           → format=none, source=42 (literal)
copy(3.14,DF1)                         → format=none, source=3.14 (literal)
copy(as_value(DS10),DS11)              → format=value, source=DS10
copy(as_text(DS12,suppress_zero=1,pad=none,exponential=0,termination_code=none),DS13)
                                       → format=text, source=DS12, text opts unpacked
copy(as_binary(DS22),DS23)             → format=binary, source=DS22
copy(as_ascii(DS24),DS25)              → format=ascii, source=DS24
copy(DS26,DS27,oneshot=1)              → format=none, oneshot
```

## Changes needed

### 1. Copy dataclass — add `format` field

```python
@dataclass
class Copy:
    source: str
    destination: str
    format: str = "none"  # "none", "value", "text", "binary", "ascii"
    oneshot: bool = False
    suppress_zero: str = "0"
    pad: str = "0"
    exponential: str = "0"
    termination_code: str = "0"
```

### 2. `from_csv_token` — parse `as_*` wrappers in source arg

The first positional arg is either:
- A bare operand/literal: `DS7`, `42`, `3.14`
- An `as_*()` wrapper: `as_text(DS12,suppress_zero=1,...)`

Parse logic:
1. Split `copy(...)` into positional args — but careful, `as_text(DS12,opts)` contains commas
2. Need parenthesis-aware splitting (already exists in token_parser.py?)
3. If first arg starts with `as_`, extract wrapper name and inner args
4. Inner first arg = source operand
5. Inner kwargs = text options (only for `as_text`)

Tricky part: splitting `copy(as_text(DS12,suppress_zero=1),DS13)` correctly.
Can't naively split on commas — need to respect nested parens.

Approach: use the same paren-aware splitter from `csv/token_parser.py`
(`_split_args_respecting_parens` or similar). Or write a simple one:
scan for commas at depth 0 only.

### 3. `to_csv` — reconstruct wrapper

```python
def to_csv(self) -> str:
    # Build source representation
    if self.format == "none":
        src = self.source
    elif self.format == "text":
        text_opts = [self.source]
        text_opts.append(f"suppress_zero={self.suppress_zero}")
        text_opts.append(f"pad={self.pad}")
        text_opts.append(f"exponential={self.exponential}")
        text_opts.append(f"termination_code={self.termination_code}")
        src = f"as_text({','.join(text_opts)})"
    elif self.format in ("value", "binary", "ascii"):
        src = f"as_{self.format}({self.source})"

    parts = [src, self.destination]
    if self.oneshot:
        parts_kw = ["oneshot=1"]
        return f"copy({','.join(parts)},{','.join(parts_kw)})"
    return f"copy({','.join(parts)})"
```

Question: should `to_csv` always emit ALL text opts (even defaults), or only non-defaults?
The existing coverage CSVs emit all of them explicitly. Follow that convention.

### 4. `build_blob` — map format to binary field[4]

field[4] (tag=0x2206) is "0" for basic copy. Tentative mapping:
- "none" → "0"
- "value" → ? (needs capture)
- "text" → ? (needs capture)
- "binary" → ? (needs capture)
- "ascii" → ? (needs capture)

Until captures verify the mapping, use "0" for all and note it's tentative.

### 5. `parse_blob` — reverse: field[4] → format

Same — tentative until captures.

### 6. CSV converter (`csv/converter.py`)

`_af_call_to_token` already handles `copy()`. Update to:
1. Paren-aware split the first arg
2. Detect `as_*` wrapper
3. Unpack into Copy fields

### 7. Coverage CSVs

The golden CSVs already have the `as_*` format. No changes needed to CSVs.
`copy__as_text_opts.csv` uses positional syntax: `as_text(DS14,0,3,0,none)`.
Decide: support both positional and kwargs in `as_text`? The kwargs form is
clearer. Could normalize positional to kwargs on parse.

## Paren-aware arg splitting

Need a helper to split `as_text(DS12,suppress_zero=1),DS13` at the top-level
comma only. Simple approach:

```python
def _split_top_level(s: str) -> list[str]:
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(s):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ',' and depth == 0:
            parts.append(s[start:i].strip())
            start = i + 1
    parts.append(s[start:].strip())
    return parts
```

This replaces the naive `m.group(1).split(",")` in `from_csv_token`.

## Open questions

- What binary field values do as_value/as_text/as_binary/as_ascii set?
  Need captures of each variant to verify field[4] mapping.
- Should `to_csv` for as_text always emit all options, or only non-defaults?
- copy__as_text_opts.csv uses positional args — support both or normalize?
