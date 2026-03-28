"""Reverse-engineered offsets for the Click clipboard binary format.

Fixed-size 64-byte cell layout, program header, and rung preamble.
"""

from __future__ import annotations

# --- Program header (0x0254–0x025F) ---
PROGRAM_HEADER_BASE = 0x0254

# --- Rung preamble ---
# Each rung has a 0x40-byte preamble that precedes its data rows.
# Rung 0's preamble starts at 0x0260, immediately after the program header.
# Rung N>0's preamble is cell 0 of its preamble row in the grid.
# Comment data sits at fixed offsets within any preamble:
RUNG0_PREAMBLE_BASE = 0x0260
PREAMBLE_COMMENT_FLAG = 0x30  # 0x01 when comment present
PREAMBLE_COMMENT_LENGTH = 0x34  # 4-byte LE payload length
PREAMBLE_COMMENT_BODY = 0x38  # RTF payload bytes start here

# --- Grid/cell layout ---
GRID_FIRST_ROW_START = 0x0A60
CELL_SIZE = 0x40
COLS_PER_ROW = 32
GRID_ROW_STRIDE = CELL_SIZE * COLS_PER_ROW  # 0x800

# Cell-local topology flag offsets
# +0x19: segment flag — load-bearing; getting it wrong causes contacts/wires
#        to shift down to their own row.  Encoder computes per-row boundary
#        from T/|/contact positions.
CELL_SEGMENT_FLAG_OFFSET = 0x19
CELL_HORIZONTAL_RIGHT_OFFSET = 0x1D
CELL_VERTICAL_DOWN_OFFSET = 0x21


def cell_offset(row: int, column: int) -> int:
    if row < 0:
        raise ValueError(f"Row must be >= 0; got {row}")
    if not (0 <= column < COLS_PER_ROW):
        raise ValueError(f"Column out of range: {column}")
    return GRID_FIRST_ROW_START + row * GRID_ROW_STRIDE + column * CELL_SIZE
