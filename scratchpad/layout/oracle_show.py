from __future__ import annotations

from laddercodec._layout.network import cell_of
from laddercodec.decode import inspect_cells
from laddercodec.model import PinnedInstruction

LETTERS = [chr(65 + i) for i in range(26)] + ["AA", "AB", "AC", "AD", "AE"]


def label(tok: object) -> str:
    if tok in ("", None):
        return ""
    text = tok.to_csv() if hasattr(tok, "to_csv") else repr(tok)
    return text[2:] if text.startswith("T:") else text


def af_label(tok: object) -> str:
    if tok in ("", None):
        return ""
    if tok == "NOP":
        return "NOP"
    text = label(tok)
    if isinstance(tok, PinnedInstruction):
        text += f" pins={tok.pin_rows}"
    return text


def sig(rung, af_down=None):
    rows = len(rung.conditions)
    cells = []
    for row in rung.conditions:
        out = []
        for t in row:
            c = cell_of(t)
            out.append((label(c.contact) if c.contact is not None else "", c.right, c.down))
        cells.append(tuple(out))
    af = tuple(af_label(rung.instructions[r]) if r < len(rung.instructions) else "" for r in range(rows))
    down = tuple(af_down) if af_down is not None else (False,) * rows
    return (rows, tuple(cells), af, down)


def af_down_of(data: bytes, index: int, rows: int) -> list[bool]:
    dumps = inspect_cells(data, [(index, r, "AF") for r in range(rows)])
    return [bool(d.flags[2]) for d in dumps]


def show(rung) -> list[str]:
    """Compact drawing: columns up to the last non-wire cell, then '-..' for a dash run to AE."""
    rows = []
    for r, cond in enumerate(rung.conditions):
        toks = [(t.to_csv() if hasattr(t, "to_csv") else str(t)) for t in cond]
        af = rung.instructions[r] if r < len(rung.instructions) else ""
        rows.append((toks, af_label(af)))
    last = 0
    for toks, _ in rows:
        end = 31
        if toks[-1] == "-":
            while end > 0 and toks[end - 1] == "-":
                end -= 1
            last = max(last, end)
        else:
            nb = [c for c in range(31) if toks[c]]
            if nb:
                last = max(last, nb[-1])
    upto = min(31, last + 2)
    width = [max(len(LETTERS[c]), *(len(t[c]) for t, _ in rows)) for c in range(upto)]
    lines = ["      " + " ".join(LETTERS[c].ljust(width[c]) for c in range(upto))]
    for i, (toks, af) in enumerate(rows):
        rest = toks[upto:]
        tail = " -.." if rest and all(t == "-" for t in rest) else ("    " if all(t == "" for t in rest) else " " + ",".join(t or "." for t in rest))
        body = " ".join((toks[c] or ".").ljust(width[c]) for c in range(upto))
        lines.append(f"  {i:>2}: {body}{tail} | {af[:60]}")
    return lines


def diff(a, b) -> list[str]:
    out = []
    if a[0] != b[0]:
        out.append(f"rows {a[0]} vs {b[0]}")
    for r in range(min(a[0], b[0])):
        for c in range(31):
            if a[1][r][c] != b[1][r][c]:
                x, y = a[1][r][c], b[1][r][c]
                out.append(f"r{r}{LETTERS[c]}: {x[0] or '-'} R{int(x[1])}D{int(x[2])} vs {y[0] or '-'} R{int(y[1])}D{int(y[2])}")
        if a[2][r] != b[2][r]:
            out.append(f"r{r}AF: {a[2][r][:40] or '.'} vs {b[2][r][:40] or '.'}")
        if a[3][r] != b[3][r]:
            out.append(f"r{r}AF down: {a[3][r]} vs {b[3][r]}")
    return out


