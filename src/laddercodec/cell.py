"""Build the cells of the ladder clipboard binary format.

The module builds three kinds of cell:

    ClickCell        A data (wire) cell or an instruction cell (via ``to_bytes()``).
    Preamble cell    Multi-rung boundary: marks the start of the next rung (0x40 bytes).
    Terminal cell    End-of-grid sentinel (``+0x05 = 0xFF``) (0x40 bytes).

The encoder that calls this module turns wire tokens into flag values and
finds the NOPs. This module only writes the bytes.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass

from .errors import EncodeError
from .topology import CELL_SIZE, COLS_PER_ROW

# The cell header is this long, so instruction data starts at this offset in the cell.
_INSTR_DATA_OFFSET = 0x25

# Pre-compiled struct for the 37-byte cell header, so that one pack call writes all of it.
# Layout: pad(1) col(u32) row(u32) span(u8) vis(u8) 0(u8) extra(u8)
#         instr_idx(i32) 1(u32) row_start(u32) seg(u32) right(u32) down(u32)
_HEADER_STRUCT = struct.Struct("<xIIBBBBiIIIII")


def _put_rung(buf: bytearray, offset: int, rung: int) -> None:
    """Write a rung index as two little-endian bytes, so an index past 255 fits."""
    buf[offset : offset + 2] = rung.to_bytes(2, "little")


# ---------------------------------------------------------------------------
# Unified cell builder
# ---------------------------------------------------------------------------


@dataclass
class ClickCell:
    """One cell of a Click PLC ladder grid: a data cell or an instruction cell.

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
    row_start_flag: int = 0
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
        # 8-bit structural bytes at +0x09..+0x0C.  The encoder always writes 0x00 at +0x0B.
        # CLICK's own cells can hold other values at +0x0B and +0x0C, and the decoder reads
        # neither byte.
        if self.row_span > 1 or self.visual_rows > 1:
            # Multi-row AF instruction (timer): +0x09 = row span,
            # +0x0A = visual sub-rows.
            # A raw box keeps its native bytes, which can be 01 03 (Math).
            b09, b0a, b0c = self.row_span, self.visual_rows, 0
        elif self.blob or self.rung_has_instructions:
            # Instruction cell or wire cell in an instruction-bearing rung: +0x0C = 0x00.
            b09, b0a, b0c = 1, 1, 0
        else:
            # Pure wire/data cell in a wire-only rung: +0x0C = 0x01
            b09, b0a, b0c = 1, 1, 1

        # CLICK sets +0x15 from bit 0 of the stored row's flags, and only in column A.
        # A Rung does not keep those flags, so these rules write the encoder's own
        # value. They set it for contacts and NOPs, but the flag means more than that.
        # 32-bit LE Wire & Logic Flags
        if self.blob:
            row_start = 1 if (self.is_contact and self.col == 0 and self.local_row == 0) else 0
        else:
            row_start = self.row_start_flag
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
            row_start,
            self.segment,
            right_flag,
            self.wire_down,
        )

    def build_tail(self) -> bytearray:
        """Build the 16-byte tail, with rung and row numbers that depend on the cell's place."""
        tail = bytearray(16)

        if self.blob:
            # An instruction cell's tail always has a marker byte.
            # Condition side (col < 31): tail[13] = local_row + 1.
            # AF side (col 31): a single-rung and a multi-rung encode use different
            # row and rung counters.

            # On the last row of the last rung in a multi-rung encode, the tail is
            # only the marker tail[12] = 1, with no tail[8] or tail[9].
            if self.col == 31 and not self.single_rung:
                is_last_row = self.local_row == self.logical_rows - 1
                if is_last_row and self.is_last_rung:
                    tail[12] = 0x01
                    return tail

            tail[8] = 0x01
            _put_rung(tail, 9, self.rung_idx)
            if self.col < 31:
                tail[13] = (self.local_row + 1) & 0xFF
            elif self.single_rung:
                # A single-rung encode writes local_row + 2 at tail[13], the 1-based number
                # of the row below.  encode() passes is_last_rung=True with single_rung=True,
                # so the elif branch below does not run.
                if self.is_last_rung:
                    tail[13] = (self.local_row + 2) & 0xFF
                elif self.logical_rows > 1:
                    tail[13] = min(self.instr_index + 1, self.logical_rows) & 0xFF
            else:
                # Multi-rung AF instructions:
                #   - on the last row of any rung but the last, tail[9] holds the
                #     next rung's index.
                #   - tail[13] is written only on rows before the rung's last row.
                is_last_row = self.local_row == self.logical_rows - 1
                if not self.is_last_rung and is_last_row:
                    _put_rung(tail, 9, self.rung_idx + 1)
                if not is_last_row:
                    tail[13] = (self.local_row + 2) & 0xFF
        else:
            # Data cell tail. What it holds depends on the cell's column and row.
            is_last_row = self.local_row == self.logical_rows - 1
            if self.col < 31:
                tail[8] = 0x01
                _put_rung(tail, 9, self.rung_idx)
                tail[13] = (self.local_row + 1) & 0xFF
            else:  # col 31
                if is_last_row and self.is_last_rung:
                    # Native Click writes the instruction count at tail[12]
                    # for AF data cells in instruction-bearing rungs.
                    if self.instr_count > 0:
                        tail[12] = self.instr_count & 0xFF
                else:
                    tail[8] = 0x01
                    _put_rung(tail, 9, self.rung_idx + 1 if is_last_row else self.rung_idx)
                    if self.single_rung or not is_last_row:
                        tail[13] = (self.local_row + 2) & 0xFF

        return tail

    def to_bytes(self) -> bytes:
        """Return the cell's bytes: the header, then the blob or padding, then the tail."""
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
    cell[0x05:0x09] = (global_row + 1).to_bytes(4, "little")
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
    _put_rung(cell, 0x39, rung_idx + 1)
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
        raise EncodeError(f"Expected {COLS_PER_ROW} cells, got {len(cells)}")
    for i, c in enumerate(cells):
        if len(c) < CELL_SIZE:
            raise EncodeError(f"Cell {i}: expected >= {CELL_SIZE} bytes, got {len(c)}")
    return b"".join(cells)
