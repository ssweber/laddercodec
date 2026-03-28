"""Fresh byte-level spec of multi-rung format vs single-rung baseline.

Captures (all non-comment, completely empty rungs):
  ref_single_empty.bin  -- 1 x 1-row empty rung  (baseline)
  multi_2empty.bin      -- 2 x 1-row empty rungs
  multi_3empty.bin      -- 3 x 1-row empty rungs
"""

import struct
from pathlib import Path

CAPTURES_DIR = Path(r"C:\Users\Sam\Documents\GitHub\clicknick\devtools\captures")

FILES = {
    "single_1": CAPTURES_DIR / "ref_single_empty.bin",
    "multi_2": CAPTURES_DIR / "multi_2empty.bin",
    "multi_3": CAPTURES_DIR / "multi_3empty.bin",
}

GRID_START = 0x0A60
CELL_SIZE = 0x40
COLS = 32
ROW_STRIDE = CELL_SIZE * COLS  # 0x800
PH_BASE = 0x0254


def cell_off(row, col):
    return GRID_START + row * ROW_STRIDE + col * CELL_SIZE


def get_cell(data, row, col):
    off = cell_off(row, col)
    if off + CELL_SIZE > len(data):
        return None
    return data[off : off + CELL_SIZE]


def nz(cell):
    return {i: v for i, v in enumerate(cell) if v != 0}


def cell_key(data, row, col, *offsets):
    c = get_cell(data, row, col)
    if c is None:
        return None
    return {o: c[o] for o in offsets if c[o] != 0}


def section(title):
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


def hex_dump(data, start, length, indent="  "):
    for i in range(0, length, 16):
        chunk = data[start + i : start + i + 16]
        h = " ".join(f"{b:02x}" for b in chunk)
        print(f"{indent}{start + i:#06x}: {h}")


# Load
data = {}
for name, path in FILES.items():
    data[name] = path.read_bytes()

# -----------------------------------------------------------------------
section("1. BUFFER SIZES")
for name, d in data.items():
    avail = (len(d) - GRID_START) // ROW_STRIDE
    pages = len(d) // 0x1000
    print(f"  {name}: {len(d):#x} ({pages} pages x 0x1000)  grid_rows_avail={avail}")

# -----------------------------------------------------------------------
section("2. PROGRAM HEADER (+0x00 row_word, +0x17 flag)")
for name, d in data.items():
    ph = d[PH_BASE : PH_BASE + 0x40]
    rw = struct.unpack_from("<H", ph, 0)[0]
    f17 = ph[0x17]
    print(f"  {name}: row_word={rw:#06x}={rw}  +0x17={f17:#04x}={f17}")

print()
print("  row_word formula:")
print("    single_1: 1 grid row  -> (1+1)*0x20 = 0x40 [check]")
print("    multi_2:  ? grid rows -> row_word=0x80 = (4+1)*0x20? or (N_rows+1)*0x20")
print("    multi_3:  ? grid rows -> row_word=0xC0 = (6+1)*0x20? or ...")
for name, d in data.items():
    ph = d[PH_BASE : PH_BASE + 0x40]
    rw = struct.unpack_from("<H", ph, 0)[0]
    avail = (len(d) - GRID_START) // ROW_STRIDE
    derived = rw // 0x20 - 1
    print(f"    {name}: rw={rw:#x} => rw/0x20-1 = {derived}  avail_grid_rows={avail}")

# -----------------------------------------------------------------------
section("3. CELL STRUCTURE: single_1 row0 (baseline) vs multi_2 rows 0..3")
# Fields known from single-rung encoder (empty_multirow.py):
#   +0x01=col, +0x05=row+1, +0x09=1, +0x0A=1, +0x0C=1,
#   +0x0D/0E/0F/10=0xFF, +0x11=1, +0x38=linkage, +0x3D=link_target

STRUCTURAL = (
    0x01,
    0x05,
    0x09,
    0x0A,
    0x0B,
    0x0C,
    0x0D,
    0x0E,
    0x0F,
    0x10,
    0x11,
    0x15,
    0x30,
    0x38,
    0x39,
    0x3D,
)


def dump_cell_structural(d, row, col, label):
    c = get_cell(d, row, col)
    if c is None:
        print(f"  {label}: out of range")
        return
    vals = {o: c[o] for o in STRUCTURAL if c[o] != 0}
    all_nz = {i: v for i, v in enumerate(c) if v != 0}
    extra = {k: v for k, v in all_nz.items() if k not in STRUCTURAL}
    print(f"  {label}: {vals}", end="")
    if extra:
        print(f"  EXTRA:{extra}", end="")
    print()


# Baseline: single_1 row0
print("\n  [single_1] (1-row rung, no multi)")
dump_cell_structural(data["single_1"], 0, 0, "row0 col0 ")
dump_cell_structural(data["single_1"], 0, 1, "row0 col1 ")
dump_cell_structural(data["single_1"], 0, 31, "row0 col31")

print("\n  [multi_2] (2 rungs x 1 row each)")
for row in range(4):
    for col in (0, 1, 31):
        dump_cell_structural(data["multi_2"], row, col, f"row{row} col{col:2d}")
    print()

# -----------------------------------------------------------------------
section("4. WHICH BYTES DIFFER: single_1 row0 vs multi_2 row0 (same rung shape)")

s1c0 = get_cell(data["single_1"], 0, 0)
m2c0 = get_cell(data["multi_2"], 0, 0)
m2c1 = get_cell(data["multi_2"], 0, 1)
m2c31 = get_cell(data["multi_2"], 0, 31)
s1c31 = get_cell(data["single_1"], 0, 31)

print("  col0 diffs:")
for i in range(CELL_SIZE):
    if s1c0[i] != m2c0[i]:
        print(f"    +{i:#04x}: single={s1c0[i]:#04x} multi={m2c0[i]:#04x}")

print("  col31 diffs:")
for i in range(CELL_SIZE):
    if s1c31[i] != m2c31[i]:
        print(f"    +{i:#04x}: single={s1c31[i]:#04x} multi={m2c31[i]:#04x}")

print("  col1 (mid) in multi_2 row0 (nonzero only):")
print(f"    {nz(m2c1)}")
print("  col1 (mid) in single_1 row0 (nonzero only):")
s1c1 = get_cell(data["single_1"], 0, 1)
print(f"    {nz(s1c1)}")

# -----------------------------------------------------------------------
section("5. PER-ROW SUMMARY: multi_2 (4 rows)")

print(
    "  Legend: +0x05=row_idx, +0x0B=flag30, +0x15=multi_enable, "
    "+0x30=flag48, +0x38=continues, +0x39=rung_boundary?, +0x3D=link_target"
)
print()
for row in range(4):
    row_tag = ""
    c0 = get_cell(data["multi_2"], row, 0)
    c31 = get_cell(data["multi_2"], row, 31)
    if c0 is None:
        break
    # Classify row type
    is_normal = c0[0x09] == 1 and c0[0x0A] == 1
    row_tag = "RUNG" if is_normal else "TERM"

    def fmt(c):
        return {o: c[o] for o in STRUCTURAL if c[o] != 0}

    # Check +0x0B uniformity across all cols
    ob_vals = set()
    for col in range(COLS):
        cx = get_cell(data["multi_2"], row, col)
        if cx:
            ob_vals.add(cx[0x0B])

    print(f"  row{row} [{row_tag}]")
    print(f"    col0 : {fmt(c0)}")
    print(f"    col31: {fmt(c31)}")
    print(f"    +0x0B across all cols: {sorted(ob_vals)}")
    print()

# -----------------------------------------------------------------------
section("6. PER-ROW SUMMARY: multi_3 (6 rows)")

for row in range(6):
    c0 = get_cell(data["multi_3"], row, 0)
    c31 = get_cell(data["multi_3"], row, 31)
    if c0 is None:
        break
    is_normal = c0[0x09] == 1 and c0[0x0A] == 1
    row_tag = "RUNG" if is_normal else "TERM"

    def fmt(c):
        return {o: c[o] for o in STRUCTURAL if c[o] != 0}

    ob_vals = set()
    for col in range(COLS):
        cx = get_cell(data["multi_3"], row, col)
        if cx:
            ob_vals.add(cx[0x0B])

    print(f"  row{row} [{row_tag}]")
    print(f"    col0 : {fmt(c0)}")
    print(f"    col31: {fmt(c31)}")
    print(f"    +0x0B across all cols: {sorted(ob_vals)}")
    print()

# -----------------------------------------------------------------------
section("7. TERMINAL ROW HEX DUMP")
# single_1: terminal is row1 (all zeros)
# multi_2:  terminal is row3
# multi_3:  terminal is row5

print("  [single_1] row1 (zero padding at 0x1260):")
hex_dump(data["single_1"], cell_off(1, 0), 0x40)
print("  [single_1] row1 col31:")
hex_dump(data["single_1"], cell_off(1, 31), 0x40)

print()
print("  [multi_2] row3 col0:")
hex_dump(data["multi_2"], cell_off(3, 0), 0x40)
print("  [multi_2] row3 col31:")
hex_dump(data["multi_2"], cell_off(3, 31), 0x40)

print()
print("  [multi_3] row5 col0:")
hex_dump(data["multi_3"], cell_off(5, 0), 0x40)
print("  [multi_3] row5 col31:")
hex_dump(data["multi_3"], cell_off(5, 31), 0x40)

# -----------------------------------------------------------------------
section("8. LINKAGE FIELD WALK")
# Walk +0x38 and +0x3D on col31 for all rows

for name, d in data.items():
    avail = (len(d) - GRID_START) // ROW_STRIDE
    print(f"\n  [{name}] col31 linkage (+0x38, +0x3D):")
    for row in range(avail):
        c = get_cell(d, row, 31)
        if c is None:
            break
        b38 = c[0x38]
        b3d = c[0x3D]
        b39 = c[0x39]
        b05 = c[0x05]
        print(f"    row{row}: +0x05={b05} +0x38={b38} +0x39={b39} +0x3D={b3d}")

# -----------------------------------------------------------------------
section("9. +0x39 FIELD: RUNG-INDEX POINTER?")
# Check +0x39 on both col0 and col31 for multi captures

for name in ("multi_2", "multi_3"):
    d = data[name]
    avail = (len(d) - GRID_START) // ROW_STRIDE
    print(f"\n  [{name}] +0x39 on col0 and col31:")
    for row in range(avail):
        c0 = get_cell(d, row, 0)
        c31 = get_cell(d, row, 31)
        if c0 is None:
            break
        b0 = c0[0x39]
        b31 = c31[0x39]
        print(f"    row{row}: col0+0x39={b0} col31+0x39={b31}")

# -----------------------------------------------------------------------
section("10. +0x15 FIELD: col0 only, across all rows")

for name in ("single_1", "multi_2", "multi_3"):
    d = data[name]
    avail = (len(d) - GRID_START) // ROW_STRIDE
    print(f"\n  [{name}] col0 +0x15:")
    for row in range(avail):
        c = get_cell(d, row, 0)
        if c is None:
            break
        v = c[0x15]
        print(f"    row{row}: {v}")

# -----------------------------------------------------------------------
section("11. FULL NONZERO SCAN: terminal row (all cols)")

for name, term_row in [("multi_2", 3), ("multi_3", 5)]:
    d = data[name]
    print(f"\n  [{name}] terminal row{term_row} - nonzero byte summary per col:")
    for col in range(COLS):
        c = get_cell(d, term_row, col)
        nzc = nz(c)
        if nzc:
            print(f"    col{col:2d}: {nzc}")

# -----------------------------------------------------------------------
section("12. FORMULA SUMMARY")

print("""
  Observed data:
    single_1 (1 rung x 1 row): 0x2000 bytes, 2 grid rows avail, rw=0x40
    multi_2  (2 rungs x 1 row): 0x3000 bytes, 4 grid rows avail, rw=0x80
    multi_3  (3 rungs x 1 row): 0x4000 bytes, 6 grid rows avail, rw=0xC0

  Grid rows:
    single_1: 1 rung row + 1 zero pad = 2 avail
    multi_2:  ? (3 rung rows + 1 terminal?) or (2+1 sep+1 term=4?)
    multi_3:  ? (5 rung rows + 1 terminal?) or (3+2 sep+1 term=6?)

  row_word derivation:
    0x40 = (2+1)*0x20? or (1+1+1+1)*0x10? ... checking:
""")

for name, d in data.items():
    ph = d[PH_BASE : PH_BASE + 0x40]
    rw = struct.unpack_from("<H", ph, 0)[0]
    avail = (len(d) - GRID_START) // ROW_STRIDE
    print(f"  {name}: rw={rw:#x}  avail={avail}  rw/0x20={rw // 0x20}  avail+1={(avail + 1)}")
