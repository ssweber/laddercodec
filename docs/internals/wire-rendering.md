# Wire Rendering

This page documents how Click renders wires in the ladder grid and how the encoder maps CSV wire tokens to binary flag bytes.

## Wire flag bytes

The low bytes of three uint32 LE cell fields describe wires:

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

Contacts and coils normally set right=1 — they behave like horizontal wires with instruction data layered on top. Instruction occupancy and right-wire presence are separate in the native format: a drum placed on a newly inserted blank row can have right=0. A contact cell can additionally set down=1 (a branch rooted directly under the contact): since right is already 1, that's the T shape, and the CSV renders it as a `T:` prefix on the contact token (e.g. `T:C1204`), mapping to `wire_down=True` on `Contact`/`CompareContact`.

## Row-start flag

The uint32 field at `+0x15` is separate from the segment flag. CLICK's clipboard writer copies the ordinary SCR row's low flag bit into column A and writes zero in other columns. The old `enable/contact` name described only some uses of this field; it is not specific to contacts or NOP instructions.

The encoder constructs this field through `ClickCell.row_start_flag` and its contact convention. It does not preserve arbitrary native row flags, because the public `Rung` model does not retain them. The full editing semantics of the row bit remain open; the [SCR mapping](binary-format.md#scr-row-topology-blocks) is established by the native writer.

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

The encoder uses the following capture-derived construction conventions. CLICK itself persists segment bits per entry and copies them during clipboard serialization; it does not recompute them using these formulas.

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

The encoder sets all AF instruction segment flags to zero in multi-rung buffers. This is its generation convention, not a native rule that selecting multiple rungs changes stored segment bits.

The native `time_drum_insert_rows` fixture demonstrates both drum AF states within one multi-rung capture: `(segment, right) = (1, 1)` on the original wired row and `(0, 0)` on an inserted blank row. The original NOP's wired row retains segment 1 after moving down beneath the drum. The encoder's zero-segment drum convention therefore does not describe all native captures.

### Note on native captures

Click's native segment flags track **editor creation order** — "insert row above" keeps the original row exempt rather than row 0. The encoder always treats row 0 as exempt, matching top-down construction. Native captures built via "insert row above" can therefore show a different exempt row. They are evidence of state the encoder does not preserve, and a later exempt row is not evidence that earlier rows should be discarded.

## Instruction index

Click stores a per-cell instruction index at +0x0D, but the value reflects **editor creation order**, not a structural rule. Click accepts any ordering on paste. The encoder uses a deterministic scheme: condition-side instructions numbered in row-major column-major order, then AF-side instructions in row order.

## Validation constraints

- `T` and `|` tokens are rejected on the **last row** (vertical-down has nowhere to go)
- `T` and `|` tokens are rejected on **column A** (leftmost condition column)
- At most one `NOP` per rung
