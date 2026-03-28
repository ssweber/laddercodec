"""Create multi-rung golden CSV fixtures.

Multi-rung CSVs use multiple R markers — each R starts a new rung.
Comments (# rows) before an R belong to that rung.

Usage: uv run python devtools/create_multi_golden_csvs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from golden_io import GOLDEN_DIR, MultiRungItem, write_multi_rung_golden_csv

E = ""
D = "-"


def empty(n: int = 31) -> list[str]:
    return [E] * n


def full_wire(n: int = 31) -> list[str]:
    return [D] * n


def wire_a() -> list[str]:
    row = [E] * 31
    row[0] = D
    return row


def sparse_bd() -> list[str]:
    """Wire at B (col 1) and D (col 3)."""
    row = [E] * 31
    row[1] = D
    row[3] = D
    return row


def sparse_ac() -> list[str]:
    """Wire at A (col 0) and C (col 2)."""
    row = [E] * 31
    row[0] = D
    row[2] = D
    return row


def t_junction_row() -> list[str]:
    """Row 0 of a T-junction: wire A, T at B, wire C..AE."""
    row = [D] * 31
    row[1] = "T"
    return row


def t_recv_row() -> list[str]:
    """Row below a T-junction: wire at B only (receives the vertical)."""
    row = [E] * 31
    row[1] = D
    return row


def vertical_cont_row() -> list[str]:
    """Vertical continuation: | at B."""
    row = [E] * 31
    row[1] = "|"
    return row


def write_mr(name: str, rungs: list[MultiRungItem]) -> None:
    path = GOLDEN_DIR / f"{name}.csv"
    total_rows = sum(lr for lr, _, _, _ in rungs)
    write_multi_rung_golden_csv(path, rungs)
    print(f"  {name}.csv  ({len(rungs)} rungs, {total_rows} total rows)")


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    print("Multi-rung fixtures:")

    # mr-2rung-empty: 2 x 1-row empty rungs (basic sanity)
    write_mr(
        "mr-2rung-empty",
        [
            (1, [empty()], [E], None),
            (1, [empty()], [E], None),
        ],
    )

    # mr-3rung-empty: 3 x 1-row empty rungs (N > 2)
    write_mr(
        "mr-3rung-empty",
        [
            (1, [empty()], [E], None),
            (1, [empty()], [E], None),
            (1, [empty()], [E], None),
        ],
    )

    # mr-2rung-wire: rung 0 wire at A, rung 1 full horizontal wire
    write_mr(
        "mr-2rung-wire",
        [
            (1, [wire_a()], [E], None),
            (1, [full_wire()], [E], None),
        ],
    )

    # mr-2rung-nop: each rung has NOP on AF column
    write_mr(
        "mr-2rung-nop",
        [
            (1, [empty()], ["NOP"], None),
            (1, [empty()], ["NOP"], None),
        ],
    )

    # mr-2rung-2row: 2 rungs each with 2 rows
    #   rung 0: full wire row 0, empty row 1
    #   rung 1: wire at A row 0, empty row 1
    write_mr(
        "mr-2rung-2row",
        [
            (2, [full_wire(), empty()], [E, E], None),
            (2, [wire_a(), empty()], [E, E], None),
        ],
    )

    # mr-3rung-wire-nop: 3 rungs mixing wire topologies and NOP
    #   rung 0: sparse wire (B+D), NOP
    #   rung 1: full wire, no NOP
    #   rung 2: empty, NOP
    write_mr(
        "mr-3rung-wire-nop",
        [
            (1, [sparse_bd()], ["NOP"], None),
            (1, [full_wire()], [E], None),
            (1, [empty()], ["NOP"], None),
        ],
    )

    # --- Multi-row multi-rung fixtures ---

    # mr-2rung-3row-t: rung 0 is 3-row T-junction at B, rung 1 is 1-row empty
    #   Mirrors nc-3row-t-junction topology in multi-rung context
    write_mr(
        "mr-2rung-3row-t",
        [
            (3, [t_junction_row(), t_recv_row(), empty()], [E, E, E], None),
            (1, [empty()], [E], None),
        ],
    )

    # mr-2rung-4row-vert: rung 0 is 4-row vertical chain at B, rung 1 is 1-row wire
    #   Mirrors nc-4row-vertical topology in multi-rung context
    write_mr(
        "mr-2rung-4row-vert",
        [
            (
                4,
                [t_junction_row(), vertical_cont_row(), vertical_cont_row(), t_recv_row()],
                [E, E, E, E],
                None,
            ),
            (1, [full_wire()], [E], None),
        ],
    )

    # mr-2rung-2row-nop: rung 0 is 2-row with NOP on row 1, rung 1 is 1-row empty
    #   Mirrors nc-2row-nop-last topology in multi-rung context
    write_mr(
        "mr-2rung-2row-nop",
        [
            (2, [empty(), empty()], [E, "NOP"], None),
            (1, [empty()], [E], None),
        ],
    )

    # mr-2rung-2row-sparse: 2 rungs each 2-row with sparse wire (A+C)
    #   Mirrors nc-2row-sparse topology in multi-rung context
    write_mr(
        "mr-2rung-2row-sparse",
        [
            (2, [sparse_ac(), sparse_ac()], [E, E], None),
            (2, [sparse_bd(), sparse_bd()], [E, E], None),
        ],
    )

    # mr-3rung-mixed-rows: 3 rungs with different row counts and topologies
    #   rung 0: 1-row full wire + NOP
    #   rung 1: 3-row T-junction at B
    #   rung 2: 2-row with wire at A + NOP on row 0
    write_mr(
        "mr-3rung-mixed-rows",
        [
            (1, [full_wire()], ["NOP"], None),
            (3, [t_junction_row(), t_recv_row(), empty()], [E, E, E], None),
            (2, [wire_a(), empty()], ["NOP", E], None),
        ],
    )

    # --- Multi-rung comment fixtures ---

    # mr-2rung-cmt-r0: rung 0 has comment, rung 1 empty
    #   Tests 0x0294 payload in multi-rung context (same as single-rung)
    write_mr(
        "mr-2rung-cmt-r0",
        [
            (1, [empty()], [E], "Rung0Comment"),
            (1, [empty()], [E], None),
        ],
    )

    # mr-2rung-cmt-r1: rung 1 has comment, rung 0 empty
    #   Tests separator truncation + per-rung payload embedding
    write_mr(
        "mr-2rung-cmt-r1",
        [
            (1, [empty()], [E], None),
            (1, [empty()], [E], "Rung1Comment"),
        ],
    )

    # mr-2rung-cmt-both: both rungs have comments
    #   Tests 0x0294 payload + separator truncation combined
    write_mr(
        "mr-2rung-cmt-both",
        [
            (1, [empty()], [E], "FirstRungComment"),
            (1, [empty()], [E], "SecondRungComment"),
        ],
    )

    # mr-3rung-cmt-wire: 3 rungs, comments on rung 0 and 2, wire on rung 1
    #   Tests skipping separator 0 (no comment on rung 1) + truncating separator 1
    write_mr(
        "mr-3rung-cmt-wire",
        [
            (1, [full_wire()], ["NOP"], "Wire rung with NOP"),
            (1, [sparse_bd()], [E], None),
            (1, [empty()], [E], "Last rung comment"),
        ],
    )

    print()
    print(f"Created 15 multi-rung CSV files in {GOLDEN_DIR}")


if __name__ == "__main__":
    main()
