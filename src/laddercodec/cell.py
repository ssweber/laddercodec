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
from typing import TYPE_CHECKING

from .topology import CELL_SIZE, COLS_PER_ROW

if TYPE_CHECKING:
    from .instructions.compare import CompareContact
    from .instructions.contact_no import Contact
    from .instructions.out import Coil
    from .instructions.tmr import Timer

# Instruction data starts at this offset in the cell header.
_INSTR_DATA_OFFSET = 0x25


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
    # visual_rows: visual sub-row count (1 = contact/coil, 2 = timer, 3 = retentive timer)
    row_span: int = 1
    visual_rows: int = 1

    # AF summary block — appended between blob and tail on the LAST AF
    # instruction cell when the rung has 2+ AF instructions.  Pre-built
    # by the encoder; this module just splices it in.
    af_summary: bytes = b""

    def build_header(self) -> bytearray:
        """Build the 0x25 (37-byte) structured header."""
        header = bytearray(_INSTR_DATA_OFFSET)

        # 32-bit LE Column Index and Row Index
        header[0x01:0x05] = struct.pack("<I", self.col)
        header[0x05:0x09] = struct.pack("<I", self.global_row + 1)

        # 8-bit structural bytes
        if self.row_span > 1:
            # Multi-row AF instruction (timer): +0x09 = row span,
            # +0x0A = visual sub-rows, +0x0B stays 0x00 (no 0xFD marker).
            header[0x09] = self.row_span
            header[0x0A] = self.visual_rows
        elif self.blob or self.rung_has_instructions:
            # Instruction cell or wire cell in an instruction-bearing rung.
            # Native Click writes +0x0B=0x00, +0x0C=0x00 for these cells
            # (confirmed via native captures: 1rung_2rows, instr-cond__and).
            header[0x09] = 0x01
            header[0x0A] = 0x01
        else:
            # Pure wire/data cell in a wire-only rung: +0x0C = 0x01
            header[0x09] = 0x01
            header[0x0A] = 0x01
            header[0x0C] = 0x01

        # 32-bit LE Instruction Index (-1 packs to 0xFFFFFFFF for data cells)
        header[0x0D:0x11] = struct.pack("<i", self.instr_index)

        # 32-bit LE Structural Flag (always 1)
        header[0x11:0x15] = struct.pack("<I", 1)

        # 32-bit LE Wire & Logic Flags
        if self.blob:
            contact_flag = 1 if (self.is_contact and self.col == 0 and self.local_row == 0) else 0
        else:
            contact_flag = self.nop_enable
        right_flag = self.af_nop if self.af_nop else self.wire_right

        header[0x15:0x19] = struct.pack("<I", contact_flag)
        header[0x19:0x1D] = struct.pack("<I", self.segment)
        header[0x1D:0x21] = struct.pack("<I", right_flag)
        header[0x21:0x25] = struct.pack("<I", self.wire_down)

        return header

    def build_tail(self) -> bytearray:
        """Build the 16-byte tail with dynamic rung index."""
        tail = bytearray(16)

        if self.af_summary:
            # Modified tail for the last AF instruction cell when a summary
            # block is present.  Confirmed via native capture (instr-3row-branch).
            tail[3] = 0x01
            tail[12] = 0x01
            tail[15] = 0x01
        elif self.blob:
            # Instruction cell tail — always has marker, dynamic rung_idx.
            # Condition-side (col < 31): tail[13] = local_row + 1 (confirmed
            #   via native capture — NOT a running counter).
            # AF-side (col 31): tail[13] = local_row + 2 for last rung
            #   (confirmed via native captures: instr-2row-spread, instr-3row-branch).
            #   Non-last rungs: visual row hint from native capture (3rung_mixed.bin):
            #   1-row → 0, 2-row → 2.
            tail[8] = 0x01
            tail[9] = self.rung_idx
            if self.col < 31:
                tail[13] = (self.local_row + 1) & 0xFF
            elif self.is_last_rung:
                tail[13] = (self.local_row + 2) & 0xFF
            elif self.logical_rows > 1:
                tail[13] = min(self.instr_index + 1, self.logical_rows) & 0xFF
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

        # Instruction cell: header(37) + blob [+ af_summary] + tail(16).
        return bytes(header + self.blob + self.af_summary + tail)


# ---------------------------------------------------------------------------
# Shared blob encoding helpers (used by instructions/ modules)
# ---------------------------------------------------------------------------


def _utf16le_null(s: str) -> bytes:
    """Encode *s* as UTF-16LE with a null terminator."""
    return s.encode("utf-16-le") + b"\x00\x00"


def _tagged_field(tag: int, value: str) -> bytes:
    """Build ``[2B tag LE][FFFFFFFF sentinel][UTF-16LE null-terminated value]``."""
    return struct.pack("<H", tag) + b"\xff\xff\xff\xff" + _utf16le_null(value)


def _variant_tagged_field(tag: int, sub_marker: bytes, value: str) -> bytes:
    """Build ``[2B tag LE][4B sub-marker][UTF-16LE null-terminated value]``."""
    return struct.pack("<H", tag) + sub_marker + _utf16le_null(value)


# ---------------------------------------------------------------------------
# Instruction blob builders — delegate to instructions/ modules.
#
# These thin wrappers preserve the existing call sites in encode.py
# and encode_multi.py.
# ---------------------------------------------------------------------------


def build_contact_blob(contact: Contact) -> bytes:
    """Build the instruction data blob for a contact cell."""
    from .instructions.contact_no import build_blob

    return build_blob(contact)


def build_coil_blob(coil: Coil) -> bytes:
    """Build the instruction data blob for a coil cell."""
    from .instructions.out import build_blob

    return build_blob(coil)


def build_compare_blob(compare: CompareContact) -> bytes:
    """Build the instruction data blob for a compare contact cell."""
    from .instructions.compare import build_blob

    return build_blob(compare)


def build_timer_blob(timer: Timer) -> bytes:
    """Build the instruction data blob for a timer cell."""
    from .instructions.tmr import build_blob

    return build_blob(timer)


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
