# Wire Rendering

This page documents how Click renders wires in the ladder grid and how the encoder maps CSV wire tokens to binary flag bytes.

## Wire flag bytes

Each cell has three flag bytes at fixed offsets:

| Offset | Name | Purpose |
|---|---|---|
| +0x19 | Segment | Branch zone membership (see below) |
| +0x1D | Right | Horizontal connection to the right |
| +0x21 | Down | Vertical connection downward |

Wire tokens are classified by (right, down) only — the segment flag is independent:

| Right | Down | Token | Meaning |
|---|---|---|---|
| 1 | 0 | `-` | Horizontal wire |
| 0 | 1 | `\|` | Vertical down |
| 1 | 1 | `T` | Branch junction (right + down) |
| 0 | 0 | *(blank)* | No wire |

Instruction cells (contacts, coils) also set right=1 — they behave like horizontal wires with instruction data layered on top.

## Left-edge rendering

Click renders the T's down-wire at the **left edge** of the cell, not the center. This means two cells can connect to a single T's down-wire — one from each side of that edge:

1. **Same-column (DOWN):** A `-` directly below a T connects via the standard vertical edge.
2. **Diagonal (UP/RIGHT):** A `-` one column to the LEFT and one row BELOW connects UP one row and ONE COLUMN TO THE RIGHT to the T. The `-`'s right-wire meets the T's down-wire at the shared cell boundary.

```
Connected:                          Not connected:
R, -, T, T, -, -, out(Y1)          R, -, T, T, -, -, out(Y1)
 , -, -, -, -, -, out(Y2)           , -,  , -, -, -, out(Y2)
      ^                                   ^
      B has "-" = bridge                  B is blank = gap
```

In the not-connected case: row 1 column A connects UP/RIGHT to T@B (rule 2), row 1 column C connects UP to T@C (rule 1), and the blank at B is the gap that keeps the two branches independent.

## Segment flag

The segment flag (+0x19) determines branch zone membership. Getting it wrong causes contacts and wires to visually shift down to their own row in Click's editor.

### Boundary rules

The encoder computes a per-row boundary column:

**Row 0** is exempt — boundary=0, all non-blank cells get seg=1.

**Row R (R > 0):**

1. Start with boundary = 0
2. From row R-1 only: `T` at column C → boundary = max(boundary, C+2); `|` at column C → boundary = max(boundary, C+1)
3. From rows 0..R-1: `Contact`/`CompareContact` at column C → boundary = max(boundary, C+2)
4. Non-blank cells at col < boundary get seg=0; at col >= boundary get seg=1
5. Blank cells and `|` cells are always seg=0

### AF column segment rules

Single-rung buffers:

| Cell type | Row | Segment |
|---|---|---|
| Coil | 0 | 1 |
| Coil | 1+ | 0 |
| Timer | any | 0 |
| NOP data cell | any | 1 |

In multi-rung buffers, all AF instruction cells get segment=0 regardless of type or row.

### Note on native captures

Click's native segment flags track **editor creation order** — "insert row above" keeps the original row exempt rather than row 0. The encoder always treats row 0 as exempt, matching top-down construction. Native captures built via "insert row above" will show a different exempt row; don't use those for segment flag validation.

## Instruction index

Click stores a per-cell instruction index at +0x0D, but the value reflects **editor creation order**, not a structural rule. Click accepts any ordering on paste. The encoder uses a deterministic scheme: condition-side instructions numbered in row-major column-major order, then AF-side instructions in row order.

## Validation constraints

- `T` and `|` tokens are rejected on the **last row** (vertical-down has nowhere to go)
- `T` and `|` tokens are rejected on **column A** (leftmost condition column)
- At most one `NOP` per rung
