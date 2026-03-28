"""Reverse-engineered offsets for the Click clipboard binary format.

Fixed-size 64-byte cell layout and the 0x0254 header entry table.
"""

from __future__ import annotations

# --- Header table (32 entries x 64 bytes) ---
HEADER_ENTRY_BASE = 0x0254
HEADER_ENTRY_SIZE = 0x40
HEADER_ENTRY_COUNT = 32

# --- Grid/cell layout ---
GRID_FIRST_ROW_START = 0x0A60
CELL_SIZE = 0x40
COLS_PER_ROW = 32
GRID_ROW_STRIDE = CELL_SIZE * COLS_PER_ROW  # 0x800

# Cell-local topology flag offsets
CELL_HORIZONTAL_LEFT_OFFSET = 0x19
CELL_HORIZONTAL_RIGHT_OFFSET = 0x1D
CELL_VERTICAL_DOWN_OFFSET = 0x21


def cell_offset(row: int, column: int) -> int:
    if row < 0:
        raise ValueError(f"Row must be >= 0; got {row}")
    if not (0 <= column < COLS_PER_ROW):
        raise ValueError(f"Column out of range: {column}")
    return GRID_FIRST_ROW_START + row * GRID_ROW_STRIDE + column * CELL_SIZE
