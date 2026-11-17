"""Build the clipboard payload of an empty rung with 1 to 32 rows.

The payload follows these rules, which have been checked for empty rungs only:
- The row word in the program header (+0x00/+0x01) is (rows + 1) * 0x20.
- The payload length grows in pages of 0x1000 bytes.
- The byte at header +0x05 and the byte at 0x0A59 are zero.
- The bytes of each cell in the rung's rows are set by fixed formulas of row and column.
"""

from __future__ import annotations

from importlib import resources

from .errors import EncodeError
from .topology import (
    CELL_SIZE,
    COLS_PER_ROW,
    GRID_FIRST_ROW_START,
    GRID_ROW_STRIDE,
    PROGRAM_HEADER_BASE,
    cell_offset,
)

EMPTY_MULTIROW_MIN_ROWS = 1
EMPTY_MULTIROW_MAX_ROWS = 32
EMPTY_MULTIROW_PAGE_SIZE = 0x1000
EMPTY_MULTIROW_TRAILER_OFFSET = 0x0A59
EMPTY_MULTIROW_ROW_WORD_STRIDE = 0x20
EMPTY_MULTIROW_TEMPLATE_RESOURCE = "resources/empty_multirow_rule_minimal.scaffold.bin"


def _validate_rows(logical_rows: int) -> None:
    if not isinstance(logical_rows, int):
        raise TypeError(f"logical_rows must be int; got {type(logical_rows).__name__}")
    if not (EMPTY_MULTIROW_MIN_ROWS <= logical_rows <= EMPTY_MULTIROW_MAX_ROWS):
        raise EncodeError(
            f"logical_rows must be in [{EMPTY_MULTIROW_MIN_ROWS}, {EMPTY_MULTIROW_MAX_ROWS}], "
            f"got {logical_rows}"
        )


def _load_template() -> bytes:
    data = resources.files("laddercodec").joinpath(EMPTY_MULTIROW_TEMPLATE_RESOURCE).read_bytes()
    if len(data) < GRID_FIRST_ROW_START + GRID_ROW_STRIDE:
        raise EncodeError(f"Empty multi-row template is too short: {len(data)} bytes")
    return data


def empty_multirow_payload_length(logical_rows: int) -> int:
    """Return the payload length in bytes of an empty rung with ``logical_rows`` rows."""
    _validate_rows(logical_rows)
    return EMPTY_MULTIROW_PAGE_SIZE * (((logical_rows + 1) // 2) + 1)


def empty_multirow_row_word(logical_rows: int) -> int:
    """Return the row word for ``logical_rows`` rows. The program header stores it
    little-endian at +0x00 and +0x01."""
    _validate_rows(logical_rows)
    return (logical_rows + 1) * EMPTY_MULTIROW_ROW_WORD_STRIDE


def synthesize_empty_multirow(
    logical_rows: int,
    *,
    template: bytes | None = None,
) -> bytes:
    """Build the payload of an empty rung with ``logical_rows`` rows, starting from
    ``template`` or, if it is None, from the packaged template file."""
    _validate_rows(logical_rows)

    template_bytes = template if template is not None else _load_template()
    if len(template_bytes) < GRID_FIRST_ROW_START + GRID_ROW_STRIDE:
        raise EncodeError(f"template payload too short ({len(template_bytes)} bytes)")

    payload_len = empty_multirow_payload_length(logical_rows)
    out = bytearray(payload_len)
    copy_len = min(len(template_bytes), payload_len)
    out[:copy_len] = template_bytes[:copy_len]
    out[:8] = b"CLICK   "

    # Write row word into program header (+0x00/+0x01).
    row_word = empty_multirow_row_word(logical_rows)
    out[PROGRAM_HEADER_BASE + 0x00] = row_word & 0xFF
    out[PROGRAM_HEADER_BASE + 0x01] = (row_word >> 8) & 0xFF
    if EMPTY_MULTIROW_TRAILER_OFFSET < len(out):
        out[EMPTY_MULTIROW_TRAILER_OFFSET] = 0x00

    # Clear all available row blocks first, then write active rows only.
    available_rows = max(0, (len(out) - GRID_FIRST_ROW_START) // GRID_ROW_STRIDE)
    for row in range(available_rows):
        row_start = cell_offset(row, 0)
        row_end = row_start + COLS_PER_ROW * CELL_SIZE
        out[row_start:row_end] = b"\x00" * (row_end - row_start)

    for row in range(logical_rows):
        is_terminal = row == logical_rows - 1
        for column in range(COLS_PER_ROW):
            start = cell_offset(row, column)
            out[start + 0x01] = column & 0xFF
            out[start + 0x05] = (row + 1) & 0xFF
            out[start + 0x09] = 0x01
            out[start + 0x0A] = 0x01
            out[start + 0x0C] = 0x01
            out[start + 0x0D] = 0xFF
            out[start + 0x0E] = 0xFF
            out[start + 0x0F] = 0xFF
            out[start + 0x10] = 0xFF
            out[start + 0x11] = 0x01

            out[start + 0x38] = 0x00 if (is_terminal and column == 31) else 0x01
            if is_terminal and column == 31:
                out[start + 0x3D] = 0x00
            elif column == 31:
                out[start + 0x3D] = (row + 2) & 0xFF
            else:
                out[start + 0x3D] = (row + 1) & 0xFF

    return bytes(out)
