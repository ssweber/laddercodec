"""One-time script to create the initial set of golden CSV files.

After running, the CSV files become the source of truth.
Edit them directly for future changes.

Usage: uv run python devtools/create_golden_csvs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from golden_io import GOLDEN_DIR, write_golden_csv

E = ""
D = "-"


def empty(n: int = 31) -> list[str]:
    return [E] * n


def full_wire(n: int = 31) -> list[str]:
    return [D] * n


def sparse_ac() -> list[str]:
    """Wire at A (col 0) and C (col 2)."""
    row = [E] * 31
    row[0] = D
    row[2] = D
    return row


def wire_a() -> list[str]:
    """Wire at col A only."""
    row = [E] * 31
    row[0] = D
    return row


def wire_ae() -> list[str]:
    """Wire at col AE only (rightmost condition)."""
    row = [E] * 31
    row[30] = D
    return row


def write(
    name: str, conditions: list[list[str]], af: list[str], comment: str | None = None
) -> None:
    path = GOLDEN_DIR / f"{name}.csv"
    write_golden_csv(path, conditions, af, comment)
    rows = len(conditions)
    cmt = f" comment={len(comment)}ch" if comment else ""
    print(f"  {name}.csv  ({rows} row{'s' if rows > 1 else ''}{cmt})")


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    print("Non-comment fixtures:")

    # 1. Minimal baseline
    write("nc-1row-empty", [empty()], [E])

    # 2. Max density + NOP on row 0
    write("nc-1row-fullwire-nop", [full_wire()], ["NOP"])

    # 3. Leftmost edge only
    write("nc-1row-wire-a", [wire_a()], [E])

    # 4. Rightmost edge only
    write("nc-1row-wire-ae", [wire_ae()], [E])

    # 5. Sparse wire (A, C) both rows
    write("nc-2row-sparse", [sparse_ac(), sparse_ac()], [E, E])

    # 6. NOP on final row
    write("nc-2row-nop-last", [empty(), empty()], [E, "NOP"])

    # 7. T-junction topology: wire from rail, T at B, wire continues;
    #    row 1 receives vertical at B; row 2 empty
    write(
        "nc-3row-t-junction",
        [
            [D, "T"] + [D] * 29,  # row 0: wire, T at B, wire continues
            [E, D] + [E] * 29,  # row 1: wire at B (receiving vertical)
            empty(),  # row 2: empty
        ],
        [E, E, E],
    )

    # 8. NOP on middle row (row 1 of 3)
    write("nc-3row-nop-middle", [empty(), empty(), empty()], [E, "NOP", E])

    # 9. Vertical chain: T -> | -> | -> wire at B
    write(
        "nc-4row-vertical",
        [
            [D, "T"] + [E] * 29,  # row 0: wire from rail, T at B
            [E, "|"] + [E] * 29,  # row 1: vertical pass-through
            [E, "|"] + [E] * 29,  # row 2: vertical pass-through
            [E, D] + [E] * 29,  # row 3: wire at B (terminal)
        ],
        [E, E, E, E],
    )

    # 10. Max row count
    write("nc-32row-empty", [empty() for _ in range(32)], [E] * 32)

    print()
    print("Comment fixtures:")

    # 11. Short comment, empty grid
    write("cmt-1row-empty", [empty()], [E], comment="Hello")

    # 12. Short comment, full wire + NOP
    write("cmt-1row-fullwire-nop", [full_wire()], ["NOP"], comment="Hello")

    # 13. Max 1400-byte comment, full wire + NOP
    write(
        "cmt-1row-max1400",
        [full_wire()],
        ["NOP"],
        comment="ABCDEFGHIJ" * 140,
    )

    # 14. Comment + multi-row baseline
    write("cmt-2row-empty", [empty(), empty()], [E, E], comment="Two rows")

    # 15. Max comment that fits in 2-row buffer (1324 chars)
    write(
        "cmt-2row-max1324",
        [sparse_ac(), sparse_ac()],
        [E, "NOP"],
        comment="ABCDEFGHIJ" * 132 + "ABCD",
    )

    # 16. Comment + wire at A + NOP on last row
    write(
        "cmt-2row-nop-wire",
        [wire_a(), wire_a()],
        [E, "NOP"],
        comment="Wired",
    )

    # 17. Mixed wire patterns across rows
    write(
        "cmt-3row-mixed",
        [full_wire(), sparse_ac(), empty()],
        [E, E, E],
        comment="Mixed",
    )

    # 18. Max 1400-byte comment at 3 rows
    write(
        "cmt-3row-max1400",
        [full_wire(), sparse_ac(), empty()],
        [E, E, E],
        comment="ABCDEFGHIJ" * 140,
    )

    # 19. Mid-range row count with sparse wire
    write(
        "cmt-5row-sparse",
        [full_wire()] + [sparse_ac()] * 3 + [empty()],
        [E] * 5,
        comment="Five rows",
    )

    # 20. Max rows + comment
    write(
        "cmt-32row-sparse",
        [full_wire()] + [sparse_ac()] * 30 + [empty()],
        [E] * 32,
        comment="Max rows",
    )

    print()
    print(f"Created 20 golden CSV files in {GOLDEN_DIR}")


if __name__ == "__main__":
    main()
