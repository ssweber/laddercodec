"""Cell object builders for the ladder clipboard binary format.

Five cell types:

    ClickCell        Unified data/instruction cell (via ``to_bytes()``).
    Preamble cell    Multi-rung boundary: marks the start of the next rung (0x40 bytes).
    Terminal cell    End-of-grid sentinel (``+0x05 = 0xFF``) (0x40 bytes).

Wire-flag resolution (token → flag values) and NOP detection stay in
the calling encoder — this module only serializes.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass

from .topology import CELL_SIZE, COLS_PER_ROW

# Instruction data starts at this offset in the cell header.
_INSTR_DATA_OFFSET = 0x25

# Pre-compiled struct for the 37-byte cell header (single pack replaces 8 calls).
# Layout: pad(1) col(u32) row(u32) span(u8) vis(u8) 0(u8) extra(u8)
#         instr_idx(i32) 1(u32) contact(u32) seg(u32) right(u32) down(u32)
_HEADER_STRUCT = struct.Struct("<xIIBBBBiIIIII")


# ---------------------------------------------------------------------------
# Unified cell builder
# ---------------------------------------------------------------------------


@dataclass
class ClickCell:
    """Unified representation of a Click PLC Ladder Cell.

    When ``blob`` is empty the cell is a data cell (0x40 bytes fixed).
    When ``blob`` is set the cell is a variable-length instruction cell
    (0x25-byte header + blob + 16-byte tail).
    """

    # Positional
    col: int
    global_row: int
    rung_idx: int
    local_row: int
    logical_rows: int

    # Context
    is_last_rung: bool = False
    single_rung: bool = False
    is_contact: bool = False
    rung_has_instructions: bool = False

    # Wire / NOP
    segment: int = 0
    wire_right: int = 0
    wire_down: int = 0
    nop_enable: int = 0
    af_nop: int = 0

    # Instruction (empty = data cell)
    instr_index: int = -1
    instr_count: int = 0  # total instructions in rung (written to AF tail)
    blob: bytes = b""

    # Multi-row AF instruction (timers, counters, etc.)
    # row_span: how many data rows this cell occupies (1 = normal, 2 = timer)
    # visual_rows: visual sub-row count (1 = contact/coil, 2 = timer/copy/search)
    row_span: int = 1
    visual_rows: int = 1

    def build_header(self) -> bytes:
        """Build the 0x25 (37-byte) structured header."""
        # 8-bit structural bytes at +0x09..+0x0C
        if self.row_span > 1:
            # Multi-row AF instruction (timer): +0x09 = row span,
            # +0x0A = visual sub-rows, +0x0B stays 0x00 (no 0xFD marker).
            b09, b0a, b0c = self.row_span, self.visual_rows, 0
        elif self.blob or self.rung_has_instructions:
            # Instruction cell or wire cell in an instruction-bearing rung.
            # Native Click writes +0x0B=0x00, +0x0C=0x00 for these cells
            # (confirmed via native captures: 1rung_2rows, instr-cond__and).
            b09, b0a, b0c = 1, 1, 0
        else:
            # Pure wire/data cell in a wire-only rung: +0x0C = 0x01
            b09, b0a, b0c = 1, 1, 1

        # 32-bit LE Wire & Logic Flags
        if self.blob:
            contact_flag = 1 if (self.is_contact and self.col == 0 and self.local_row == 0) else 0
        else:
            contact_flag = self.nop_enable
        right_flag = self.af_nop if self.af_nop else self.wire_right

        return _HEADER_STRUCT.pack(
            self.col,
            self.global_row + 1,
            b09,
            b0a,
            0,
            b0c,
            self.instr_index,
            1,
            contact_flag,
            self.segment,
            right_flag,
            self.wire_down,
        )

    def build_tail(self) -> bytearray:
        """Build the 16-byte tail with dynamic rung index."""
        tail = bytearray(16)

        if self.blob:
            # Instruction cell tail — always has marker, dynamic rung_idx.
            # Condition-side (col < 31): tail[13] = local_row + 1.
            # AF-side (col 31): single-rung and multi-rung use different
            # row/rung counters in native captures.

            # Multi-rung last-row-of-last-rung: tail[12] = 1 constant
            # marker, no tail[8]/tail[9].  Confirmed via native captures
            # (nopaddedrows: 1 AF/rung, multiinstructions: 4 AF/rung —
            # both show tail[12]=1).
            if self.col == 31 and not self.single_rung:
                is_last_row = self.local_row == self.logical_rows - 1
                if is_last_row and self.is_last_rung:
                    tail[12] = 0x01
                    return tail

            tail[8] = 0x01
            tail[9] = self.rung_idx
            if self.col < 31:
                tail[13] = (self.local_row + 1) & 0xFF
            elif self.single_rung:
                # Single-rung AF instructions keep the legacy row hint.
                if self.is_last_rung:
                    tail[13] = (self.local_row + 2) & 0xFF
                elif self.logical_rows > 1:
                    tail[13] = min(self.instr_index + 1, self.logical_rows) & 0xFF
            else:
                # Multi-rung AF instructions:
                #   - tail[9] switches to next rung index at non-last rung end.
                #   - tail[13] is only present on non-final data rows.
                is_last_row = self.local_row == self.logical_rows - 1
                if not self.is_last_rung and is_last_row:
                    tail[9] = (self.rung_idx + 1) & 0xFF
                if not is_last_row:
                    tail[13] = (self.local_row + 2) & 0xFF
        else:
            # Data cell tail — position-dependent logic.
            is_last_row = self.local_row == self.logical_rows - 1
            if self.col < 31:
                tail[8] = 0x01
                tail[9] = self.rung_idx
                tail[13] = (self.local_row + 1) & 0xFF
            else:  # col 31
                if is_last_row and self.is_last_rung:
                    # Native Click writes the instruction count at tail[12]
                    # for AF data cells in instruction-bearing rungs.
                    if self.instr_count > 0:
                        tail[12] = self.instr_count & 0xFF
                else:
                    tail[8] = 0x01
                    tail[9] = (self.rung_idx + 1) if is_last_row else self.rung_idx
                    if self.single_rung or not is_last_row:
                        tail[13] = (self.local_row + 2) & 0xFF

        return tail

    def to_bytes(self) -> bytes:
        """Stitch header + content + tail into a final binary payload."""
        header = self.build_header()
        tail = self.build_tail()

        if not self.blob:
            # Data cell: header(37) + padding(11) + tail(16) = 64 bytes.
            padding = bytes(CELL_SIZE - _INSTR_DATA_OFFSET - 16)
            return bytes(header + padding + tail)

        # Instruction cell: header(37) + blob + tail(16).
        return bytes(header + self.blob + tail)


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
