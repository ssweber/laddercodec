"""Cell object builders for the ladder clipboard binary format.

Each cell is a fixed-size bytes blob (0x40 bytes for wire/NOP cells).
Future instruction cells (contacts, coils) will be larger.

Three cell types:

    Data cell       Rung content row: wire flags, NOP, structural bytes.
    Preamble cell   Multi-rung boundary: marks the start of the next rung.
    Terminal cell    End-of-grid sentinel (``+0x05 = 0xFF``).

The builders are pure functions that take pre-computed parameters and
return ``bytes``.  Wire-flag resolution (token → flag values) and NOP
detection stay in the calling encoder — this module only serializes.
"""

from __future__ import annotations

from collections.abc import Sequence

from .topology import CELL_SIZE, COLS_PER_ROW

# ---------------------------------------------------------------------------
# Data cell builder
# ---------------------------------------------------------------------------


def build_data_cell(
    col: int,
    global_row: int,
    local_row: int,
    logical_rows: int,
    rung_idx: int,
    is_last_rung: bool,
    *,
    single_rung: bool = False,
    wire_left: int = 0,
    wire_right: int = 0,
    wire_down: int = 0,
    nop_enable: int = 0,
    af_nop: int = 0,
) -> bytes:
    """Build a 0x40-byte data cell.

    Parameters
    ----------
    col:
        Column index (0–31).
    global_row:
        0-based row in the overall grid (includes preamble rows for
        multi-rung buffers).
    local_row:
        0-based row within the current rung.
    logical_rows:
        Total rows in the current rung.
    rung_idx:
        0-based rung index.
    is_last_rung:
        Whether this is the final rung in the buffer.
    single_rung:
        Controls the col31 ``+0x3D`` formula.  Single-rung buffers
        write ``(global_row + 2) & 0xFF`` for non-terminal col31;
        multi-rung buffers always write ``0x00``.
    wire_left, wire_right, wire_down:
        Wire flag bytes at ``+0x19``, ``+0x1D``, ``+0x21``.
    nop_enable:
        ``+0x15`` byte (1 on col 0 for non-first NOP rows).
    af_nop:
        ``+0x1D`` override for the AF column NOP marker.  When set,
        ``wire_right`` is ignored (they share the same offset).
    """
    is_last_row = local_row == logical_rows - 1

    cell = bytearray(CELL_SIZE)

    # --- Fixed structural bytes ---
    cell[0x01] = col
    cell[0x05] = (global_row + 1) & 0xFF
    cell[0x09] = 0x01
    cell[0x0A] = 0x01
    cell[0x0C] = 0x01
    cell[0x0D] = 0xFF
    cell[0x0E] = 0xFF
    cell[0x0F] = 0xFF
    cell[0x10] = 0xFF
    cell[0x11] = 0x01

    # --- Wire / NOP flags ---
    cell[0x15] = nop_enable
    cell[0x19] = wire_left
    cell[0x1D] = af_nop if af_nop else wire_right
    cell[0x21] = wire_down

    # --- Variable fields (+0x38, +0x39, +0x3D) ---
    if col < 31:
        cell[0x38] = 0x01
        cell[0x39] = rung_idx
        cell[0x3D] = (local_row + 1) & 0xFF
    else:  # col 31
        if is_last_row and is_last_rung:
            cell[0x38] = 0x00
            cell[0x39] = 0x00
            cell[0x3D] = 0x00
        else:
            cell[0x38] = 0x01
            cell[0x39] = (rung_idx + 1) if is_last_row else rung_idx
            if single_rung:
                cell[0x3D] = (global_row + 2) & 0xFF
            else:
                cell[0x3D] = 0x00

    return bytes(cell)


# ---------------------------------------------------------------------------
# Preamble cell builder (multi-rung only)
# ---------------------------------------------------------------------------


def build_preamble_cell(col: int, global_row: int, rung_idx: int) -> bytes:
    """Build a 0x40-byte preamble cell for a multi-rung boundary.

    Preamble rows mark the start of the *next* rung.  ``+0x30 = 0x01``
    is the preamble marker that Click uses for comment detection.
    """
    cell = bytearray(CELL_SIZE)

    cell[0x01] = col
    cell[0x05] = (global_row + 1) & 0xFF
    cell[0x09] = 0x01
    cell[0x0A] = 0x01
    cell[0x0C] = 0x01
    cell[0x0D] = 0xFF
    cell[0x0E] = 0xFF
    cell[0x0F] = 0xFF
    cell[0x10] = 0xFF
    cell[0x11] = 0x01

    cell[0x30] = 0x01  # preamble marker
    cell[0x38] = 0x01
    cell[0x39] = rung_idx + 1
    cell[0x3D] = 0x01 if col == 31 else 0x00

    return bytes(cell)


# ---------------------------------------------------------------------------
# Terminal cell builder (multi-rung only)
# ---------------------------------------------------------------------------


def build_terminal_cell() -> bytes:
    """Build a 0x40-byte terminal sentinel cell.

    ``+0x05 = 0xFF`` is the sentinel Click uses to detect the end of
    the grid.  All 32 terminal cells are identical.
    """
    cell = bytearray(CELL_SIZE)

    cell[0x01] = 0x01
    cell[0x02] = 0x01
    cell[0x03] = 0x30
    cell[0x04] = 0x01
    cell[0x05] = 0xFF
    cell[0x06] = 0xFF
    cell[0x07] = 0xFF
    cell[0x08] = 0xFF
    cell[0x09] = 0x01

    return bytes(cell)


# ---------------------------------------------------------------------------
# Row helper
# ---------------------------------------------------------------------------


def build_row(cells: Sequence[bytes | bytearray]) -> bytes:
    """Concatenate 32 cells into one grid row.

    Validates that exactly ``COLS_PER_ROW`` cells are provided and each
    is at least ``CELL_SIZE`` bytes (instruction cells may be larger).
    """
    if len(cells) != COLS_PER_ROW:
        raise ValueError(f"Expected {COLS_PER_ROW} cells, got {len(cells)}")
    for i, c in enumerate(cells):
        if len(c) < CELL_SIZE:
            raise ValueError(f"Cell {i}: expected >= {CELL_SIZE} bytes, got {len(c)}")
    return b"".join(cells)
