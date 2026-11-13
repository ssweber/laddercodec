"""Oracle score for laddercodec._layout: CLICK's own layouts must be fixed points.

For every native rung, layout(rung) must give back the rung: the same row count, the same
contact label and right/down flags in every cell, the same AF token (with pin rows) on every
row, and no AF-column down flag.  For before/after pairs (layoutthy, pyrung's topology
golden, orcompact, r30, windy road), layout(pasted) must equal CLICK's checked rung(s).

Run from the layout worktree:  uv run --no-sync python ../buildbot/jobs/layout/oracle.py
Writes oracle.txt (summary + every miss) beside this script.
"""

from __future__ import annotations

import gzip
import sys
from collections import Counter, defaultdict
from pathlib import Path

import laddercodec
from laddercodec import decode, decode_program, read_csv
from laddercodec._layout import LayoutError, layout
from laddercodec._layout.network import cell_of
from laddercodec.decode import inspect_cells
from laddercodec.model import AfInstruction, PinnedInstruction

JOB = Path(__file__).parent
WT = Path(laddercodec.__file__).resolve().parents[2]  # the checkout it runs in
FIX = WT / "tests" / "fixtures"
LT = Path("C:/Users/Sam/Documents/GitHub/laddercodec-wt/buildbot/jobs/layoutthy")  # layoutthy captures
PYRUNG_GOLD = Path("C:/Users/Sam/Documents/GitHub/pyrung/tests/click/ladder_topology_golden")
LETTERS = [chr(65 + i) for i in range(26)] + ["AA", "AB", "AC", "AD", "AE"]


def as_list(x):
    return x if isinstance(x, list) else [x]


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


class Score:
    def __init__(self) -> None:
        self.counts: dict[str, Counter] = defaultdict(Counter)
        self.misses: dict[str, list[str]] = defaultdict(list)
        self.order: list[str] = []

    def add(self, source: str, name: str, native: list, got_or_err, natives_down=None, inputs=None) -> None:
        if source not in self.order:
            self.order.append(source)
        c = self.counts[source]
        c["rungs"] += 1
        if isinstance(got_or_err, Exception):
            code = getattr(got_or_err, "code", None)
            c["refused"] += 1
            self.misses[source].append(f"--- {name}: REFUSED ({code}): {got_or_err}")
            for n in native:
                self.misses[source].extend(show(n))
            return
        downs = natives_down or [None] * len(native)
        want = [sig(n, d) for n, d in zip(native, downs, strict=True)]
        have = [sig(g) for g in got_or_err]
        if want == have:
            c["hit"] += 1
            pinned = [a for n in native for a in n.instructions if isinstance(a, PinnedInstruction)]
            if pinned:
                c["hit pinned"] += 1
                default = type(pinned[0]).__dataclass_fields__["pin_rows"].default
                if any(p.pin_rows != default for p in pinned):
                    c["hit pinned grown"] += 1
            if any(isinstance(a, AfInstruction) and a.cell_params().get("visual_rows", 1) > 1
                   and not isinstance(a, PinnedInstruction) for n in native for a in n.instructions):
                c["hit tall"] += 1
            if sum(1 for n in native for a in n.instructions if a not in ("", None)) > 1:
                c["hit multi-output"] += 1
            return
        c["miss"] += 1
        lines = [f"--- {name}: MISS ({len(native)} native rung(s), {len(got_or_err)} laid out)"]
        if inputs is not None:
            lines.append(" input:")
            for n in inputs:
                lines.extend(show(n))
        lines.append(" native:")
        for n in native:
            lines.extend(show(n))
        lines.append(" layout:")
        for g in got_or_err:
            lines.extend(show(g))
        for a, b in zip(have, want, strict=False):
            lines.extend("   " + d for d in diff(a, b)[:12])
        self.misses[source].append("\n".join(lines))


def circuit_key(rungs: list, af_down=None) -> list:
    """Per box input (box label, slot): the sorted contact paths from the rail."""
    from laddercodec._layout import network_of_rung

    key = []
    for k, r in enumerate(rungs):
        net = network_of_rung(r, af_down if k == 0 else None)
        adj = defaultdict(list)
        for e in net.edges:
            adj[e.src].append(e)
        for s in net.sinks:
            paths = []

            def walk(n, seen, trail):
                if n == s.net:
                    paths.append(tuple(trail))
                for e in adj[n]:
                    if e.dst not in seen:
                        walk(e.dst, seen | {e.dst}, [*trail, label(e.contact)])

            walk(net.rail, {net.rail}, [])
            box = net.boxes[s.box].token
            name = "NOP" if box == "NOP" else label(box).split(" pins=")[0]
            key.append((name, s.slot, tuple(sorted(paths))))
    return sorted(key)


checks = Counter()
check_misses: list[str] = []


def run(rung, af_down=None, name=""):
    try:
        got = layout(rung, af_down)
    except (LayoutError, ValueError) as exc:
        return exc
    checks["laid out"] += 1
    if circuit_key(got) == circuit_key([rung], af_down):
        checks["same circuit"] += 1
    else:
        check_misses.append(f"circuit differs: {name or rung.comment!r}")
    try:
        again = [x for g in got for x in layout(g)]
        if [sig(a) for a in again] == [sig(g) for g in got]:
            checks["idempotent"] += 1
        else:
            check_misses.append(f"not idempotent: {name or rung.comment!r}")
    except (LayoutError, ValueError) as exc:
        check_misses.append(f"re-layout refused: {name or rung.comment!r}: {exc}")
    return got


score = Score()


# ---- fixed points: native clipboard bins ----
def fixed_point_bin(source: str, path: Path, data: bytes | None = None) -> None:
    data = data if data is not None else path.read_bytes()
    rungs = as_list(decode(data))
    for i, r in enumerate(rungs):
        down = af_down_of(data, i, r.logical_rows)
        score.add(source, f"{path.name} rung {i}", [r], run(r), [down])


def fixed_point_rungs(source: str, name: str, rungs: list) -> None:
    for i, r in enumerate(rungs):
        score.add(source, f"{name} rung {i}", [r], run(r))


TUMBLER = FIX / "tumbler"
tumbler_bins = [TUMBLER / "main.clipboard.bin", *sorted((TUMBLER / "subroutines").glob("*.clipboard.bin"))]
for p in tumbler_bins:
    fixed_point_bin("tumbler clipboard (native)", p)
for p in [TUMBLER / "main.scr", *sorted((TUMBLER / "subroutines").glob("*.scr"))]:
    fixed_point_rungs("tumbler SCR (native)", p.name, decode_program(p.read_bytes()).rungs)

SCR = FIX / "scr_captures"
for stem in ("coverage", "counter_scr", "or_topology", "shift_scr", "time_drum_b_column", "time_drum_insert_rows"):
    fixed_point_bin("scr_captures clipboard (native)", SCR / f"{stem}.bin")
fixed_point_bin("scr_captures clipboard (native)", SCR / "rungs_266.bin.gz", gzip.decompress((SCR / "rungs_266.bin.gz").read_bytes()))
for stem in ("coverage", "counter_scr", "or_topology", "shift_scr", "time_drum_b_column", "time_drum_insert_rows", "time_drums", "rungs_266"):
    fixed_point_rungs("scr_captures SCR (native)", f"{stem}.scr", decode_program((SCR / f"{stem}.scr").read_bytes()).rungs)

V4 = FIX / "v4_captures"
for name in ("or_compact_checked.bin", "r30_tallbox_checked.bin"):
    fixed_point_bin("v4 checked (native)", V4 / name)
fixed_point_bin("v4 checked (native)", LT / "windy-road-after-syntax.bin")
fixed_point_bin("layoutthy checked (native)", LT / "layoutthy-checked.bin")

# Native copy-backs of laddercodec/pyrung pastes that were never syntax-checked: the layout
# there is the paster's, so these are informational only.
for p in sorted(V4.glob("*.bin")):
    if "checked" in p.name or "pasted" in p.name:
        continue
    fixed_point_bin("v4 pasted, not checked (informational)", p)
fixed_point_bin("ladder_captures drum_weird_branch (informational)", FIX / "ladder_captures" / "drum_weird_branch.bin")


# ---- before/after pairs ----
def by_comment(rungs: list) -> dict[int, list]:
    out: dict[int, list] = {}
    cur = None
    for r in rungs:
        if r.comment:
            cur = int(r.comment.split(" ", 1)[0])
        out.setdefault(cur, []).append(r)
    return out


lt_pasted_data = (LT / "layoutthy-pasted.bin").read_bytes()
lt_checked_data = (LT / "layoutthy-checked.bin").read_bytes()
lt_checked = as_list(decode(lt_checked_data))
lt_downs = [af_down_of(lt_checked_data, i, r.logical_rows) for i, r in enumerate(lt_checked)]
idx_by_n: dict[int, list[int]] = {}
cur = None
for i, r in enumerate(lt_checked):
    if r.comment:
        cur = int(r.comment.split(" ", 1)[0])
    idx_by_n.setdefault(cur, []).append(i)
for r in as_list(decode(lt_pasted_data)):
    n = int(r.comment.split(" ", 1)[0])
    if n not in idx_by_n:
        got = run(r)
        ok = isinstance(got, LayoutError) and got.code is not None
        score.counts["layoutthy pasted -> checked"]["rungs"] += 1
        score.counts["layoutthy pasted -> checked"]["hit" if ok else "miss"] += 1
        if not ok:
            score.misses["layoutthy pasted -> checked"].append(f"--- rung {n}: CLICK refused it; layout gave {got!r}")
        continue
    idx = idx_by_n[n]
    score.add("layoutthy pasted -> checked", f"rung {n}", [lt_checked[i] for i in idx], run(r), [lt_downs[i] for i in idx], inputs=[r])
if "layoutthy pasted -> checked" not in score.order:
    score.order.append("layoutthy pasted -> checked")

# orcompact / r30 / windy pairs
or_pasted = as_list(decode((V4 / "or_compact_pasted.bin").read_bytes()))
or_checked = as_list(decode((V4 / "or_compact_checked.bin").read_bytes()))
pairs = {0: [0], 1: [1, 2], 2: [3], 3: [4], 4: [5]}  # tests/test_v4_captures.py
for i, js in pairs.items():
    if i < len(or_pasted):
        score.add("v4 pasted -> checked", f"or_compact rung {i}", [or_checked[j] for j in js], run(or_pasted[i]), inputs=[or_pasted[i]])
r30p = as_list(decode((V4 / "r30_tallbox_pasted.bin").read_bytes()))
r30c = as_list(decode((V4 / "r30_tallbox_checked.bin").read_bytes()))
for i, r in enumerate(r30p):
    score.add("v4 pasted -> checked", f"r30_tallbox rung {i}", [r30c[i]], run(r), inputs=[r])
wd = (LT / "windy-road.bin").read_bytes()
wr = as_list(decode(wd))[0]
wc = as_list(decode((LT / "windy-road-after-syntax.bin").read_bytes()))
score.add("v4 pasted -> checked", "windy-road (AF down flags read from the bin)", wc, run(wr, af_down_of(wd, 0, wr.logical_rows)), inputs=[wr])

# pyrung topology golden: pasted CSV rung i -> main.csv rung i
saved = read_csv(PYRUNG_GOLD / "main.csv")
for r in saved[:-1]:
    score.add("pyrung main.csv (CLICK saved, fixed point)", "main", [r], run(r))
for name in ("pasted-2026-11-12", "pasted-2026-11-13"):
    pasted = read_csv(PYRUNG_GOLD / f"{name}.csv")
    for i, r in enumerate(pasted[:-1]):
        score.add("pyrung pasted -> CLICK saved", f"{name} R{i + 1}", [saved[i]], run(r), inputs=[r])

# ---- report ----
summary = []
for src in score.order:
    c = score.counts[src]
    summary.append(f"{src}: {c['hit']}/{c['rungs']} hit, {c['miss']} miss, {c['refused']} refused" f" (hits: {c['hit multi-output']} multi-output, {c['hit tall']} tall box, {c['hit pinned']} pinned, {c['hit pinned grown']} grown pins)")
summary.append(
    f"every layout: {checks['laid out']} laid out, {checks['same circuit']} keep the circuit, "
    f"{checks['idempotent']} idempotent"
)
summary.extend(check_misses)
lines =["# Oracle: layout(native) == native", "", *summary, ""]
for src in score.order:
    if score.misses[src]:
        lines.append(f"===== {src}")
        lines.extend(score.misses[src])
        lines.append("")
(JOB / "oracle.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(summary))
sys.exit(0)
