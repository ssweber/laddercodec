"""List every address that rungs store or imply. For a range, list only its two ends.

When CLICK pastes rungs, it drops each operand whose address is not in the project. That
includes the ends that CLICK works out and stores itself, such as the end of a text Copy
(``"HALLO"`` into TXT1 stores TXT5). :func:`addresses` reads the payload as encoded and
returns every address that it uses, so that a caller can add them to the project first.
It lists an address whether or not the paste needs it. An extra address costs one row in
the project, and a missing one loses an operand.

The function reads the tagged fields of each instruction blob. It lists the addresses in
these places:

- A string tag ``0x60xx``. Most instructions store each operand in one of these tags. An
  operand is a field that holds an address or a constant. The function lists the value if
  it reads as an address or as a pointer. For a pointer such as ``TXT[DS1]``, it lists the
  index, DS1. The address that the pointer reaches is known only when the PLC runs. A
  Send's or a Receive's remote start (``0x6085``) is in one of these tags too, and the
  function lists it, though it is an address in the other PLC.
- An indexed string slot ``0x68xx``. Each slot has the tag, a 4-byte index and the value.
  A drum stores its events (``0x6872``), outputs (``0x6873``) and presets (``0x6891``) in
  these slots, a Math stores its operands in ``0x6888``, and an Email stores addresses in
  ``0x68B0`` and ``0x68B1``. A Math's reserved slots (``0x688C``) are the exception. They
  hold the addresses between the ends of a range, and CLICK needs only the two ends.
- A Math's internal formula (``0x61FD``). CLICK splits it into tokens on ``#``, and the
  function reads each token as an operand. CLICK's own save of a Math can leave the operand
  slots empty, so the formula is the field that always holds the addresses.
- The end of a Send's source or a Receive's destination. The blob stores the start and a
  count, and the function works out the end from them.
- A time drum's done bit, the T address with the number of its TD accumulator (``0x606F``).
  The function lists T4 for TD4, whether or not the blob stores the done bit (``0x6068``).

A constant never reads as an address. CLICK stores a number as digits, with or without a
sign, a ``.`` or an ``E``. It stores a hex constant with its ``h``, text with its quotes,
and a character code as ``$hh``. In the internal formula, each constant starts with
``H``, ``W``, ``F`` or ``UH``, and no bank has one of these names. An address is a bank
name and then digits, and nothing follows them except the ``u`` of ``XD0u`` and ``YD0u``.
A pointer is a bank name and a DS address in brackets. So the function reads a raw cell or
an unknown condition by the same rule, though laddercodec does not know its fields. Other
string tags hold names and text, such as a subroutine's name (``0x6208``) or a Send's IP
address (``0x622B``). The function does not read them.
"""

from __future__ import annotations

import struct
import warnings
from collections.abc import Iterable, Iterator

from .binary_helpers import _STANDARD_SENTINEL, NotANumber, tag_int
from .csv.contract import CONDITION_COLUMNS, OUTPUT_COLUMN
from .decode import (
    _DATA,
    _INSTR_DATA_OFFSET,
    Rung,
    _read_rung0_comment,
    _rung_rows,
    _validate_buffer,
    _walk_grid,
    _walk_row_cells,
)
from .encode import encode
from .instructions.raw import _decompose_blob
from .instructions.send_receive import _addr_end
from .instructions.undecoded import Undecoded
from .model import FieldError
from .operands.address import Address, parse_address, read_as_typed, split_pointer
from .topology import GRID_FIRST_ROW_START, PROGRAM_HEADER_BASE
from .undecoded import BAD_BYTES, UndecodedRungWarning, reason

#: The high byte of the string tags that hold an operand.
_OPERAND_TAGS = 0x60
#: The high byte of the indexed string slots.
_SLOT_TAGS = 0x68
#: A Math's reserved slots, which hold the addresses between the ends of each range.
_RANGE_INTERIOR = 0x688C
#: A Math's internal formula, whose tokens are joined with ``#``.
_FORMULA = 0x61FD
#: A Send's source or a Receive's destination, and the count of addresses from it.
_START = 0x607E
_COUNT = 0x3210
#: The class name of a Send and of a Receive, and the name that a refusal uses for each.
_COUNTED = {"SD": "Send", "RD": "Receive"}
#: The class name of a drum, and the tag of a time drum's TD accumulator.
_DRUM = "Drum"
_ACCUMULATOR = 0x606F

#: A cell that holds an instruction: its rung, its row in the rung, its column and its blob.
_Cell = tuple[int, int, int, bytes]
#: The name of each column, A to AE and AF, by its index from 0.
_COLUMN_NAMES = (*CONDITION_COLUMNS, OUTPUT_COLUMN)


def addresses(payload: Rung | Iterable[Rung] | bytes) -> list[str]:
    """Return every address that *payload* stores or implies, with only a range's two ends.

    *payload* is a ``Rung``, a list of rungs, or clipboard bytes as ``encode()`` writes
    them or CLICK copies them. The function encodes rungs first. ``addresses()`` returns
    the same list for a rung and for its encoded bytes. Each address is in display form
    (``X001``, ``DS1``, ``XD0u``) and appears once, in the order that the payload first
    uses it.

    The list holds each address that an instruction's fields store, both ends of each
    range, the ends that the encoder works out (``"HALLO"`` into TXT1 ends in TXT5), and
    the index of each pointer (DS1 in ``TXT[DS1]``). It holds the addresses in a Math
    formula, in an Email's indexed arrays, in a raw cell and in an unknown condition too.
    It also lists a Send's or a Receive's remote start, an address in the other PLC, and a
    time drum's done bit (T4 for the accumulator TD4). The list does not hold the
    addresses between the ends of a range, or text inside a quoted constant.

    If the function can't walk a row of the bytes, it issues an ``UndecodedRungWarning``
    that names the row. The list then lacks the addresses in that row and in every row
    after it. If the function can't read the fields of a cell, it issues an
    ``UndecodedRungWarning`` that names the cell, and the list lacks the addresses in that
    cell. ``decode()`` reads such a cell as an unknown cell and issues no warning.

    Raises
    ------
    TypeError
        If *payload* is text or ``None``.
    EncodeError, FieldError
        If *payload* is rungs that ``encode()`` refuses.
    DecodeError
        If *payload* is bytes that lack the ``CLICK   `` magic or end before the cell grid.
    """
    if payload is None or isinstance(payload, str):
        raise TypeError("addresses() reads a Rung, a list of Rungs or bytes; read the file first")
    data = (
        bytes(payload) if isinstance(payload, (bytes, bytearray, memoryview)) else encode(payload)
    )
    failed: list[UndecodedRungWarning] = []
    found: dict[str, None] = {}
    for rung, row, column, blob in _cells(data, failed):
        try:
            class_name, _, _, _, fields = _decompose_blob(blob)
        except BAD_BYTES as exc:
            failed.append(_unread_cell(Undecoded(reason(exc), rung, row, column)))
            continue
        for address in _field_addresses(class_name, fields):
            found.setdefault(address)
    for warning in failed:
        warnings.warn(warning, stacklevel=2)
    return list(found)


def _cells(data: bytes, failed: list[UndecodedRungWarning]) -> Iterator[_Cell]:
    """Yield each cell of *data* that holds an instruction, with its blob from ``+0x25``.

    The cells come in the order that the buffer stores them: row by row, and in each row
    from column A to AF. The rows are grouped into rungs as ``decode()`` groups them. The
    walk stops at a row that the decoder can't walk, and at a rung with no data rows. At
    that stop, the function adds a warning that names the row to *failed*.
    """
    _validate_buffer(data)
    total_grid_rows = struct.unpack_from("<I", data, PROGRAM_HEADER_BASE)[0] // 0x20
    _, payload_len = _read_rung0_comment(data)
    row_infos, is_multi = _walk_grid(data, GRID_FIRST_ROW_START + payload_len, total_grid_rows)
    for rung, (_, rows) in enumerate(_rung_rows(row_infos, is_multi, total_grid_rows)):
        if not rows:
            failed.append(_unread_rest(Undecoded("the rung has no data rows", rung)))
            return
        for row, (tag, cursor, error) in enumerate(rows):
            if tag != _DATA:
                failed.append(_unread_rest(Undecoded(str(error), rung, row)))
                return
            for column, (start, end, has_instruction) in enumerate(_walk_row_cells(data, cursor)):
                if has_instruction:
                    yield rung, row, column, data[start + _INSTR_DATA_OFFSET : end]


def _unread_rest(marker: Undecoded) -> UndecodedRungWarning:
    """Return the warning for a row that the walk can't read, or a rung with no data rows."""
    text = (
        f"{marker.where} can't be read, so addresses() lists no address from there to the "
        f"end of the bytes: {marker.error}"
    )
    return UndecodedRungWarning(marker, text=text)


def _unread_cell(marker: Undecoded) -> UndecodedRungWarning:
    """Return the warning for a cell whose fields can't be read."""
    column = "" if marker.column is None else f", column {_COLUMN_NAMES[marker.column]}"
    text = (
        f"{marker.where}{column} can't be read, so addresses() lists no address from that "
        f"cell: {marker.error}"
    )
    return UndecodedRungWarning(marker, text=text)


def _field_addresses(class_name: str, fields: list[tuple[int, bytes, str]]) -> list[str]:
    """Return the addresses in the tagged fields of one instruction blob, in field order."""
    found: list[str] = []
    for tag, sentinel, value in fields:
        if sentinel == _STANDARD_SENTINEL:
            if tag == _FORMULA:
                texts = value.split("#")
            elif tag >> 8 == _OPERAND_TAGS:
                texts = [value]
            else:
                continue
        elif tag >> 8 == _SLOT_TAGS and tag != _RANGE_INTERIOR:
            texts = [value]
        else:
            continue
        for text in texts:
            address = _read_operand(text)
            if address is None:
                continue
            found.append(address)
            if tag == _START and class_name in _COUNTED:
                found.extend(_counted_end(address, fields, _COUNTED[class_name]))
            elif tag == _ACCUMULATOR and class_name == _DRUM:
                found.extend(_done_bit(address))
    return found


def _done_bit(accumulator: str) -> list[str]:
    """Return the done bit of a time drum's TD accumulator: T4 for TD4.

    Return an empty list if *accumulator* is not a TD address."""
    address = parse_address(accumulator)
    if address is None or address.bank != "TD":
        return []
    return [Address("T", address.number).display]


def _read_operand(value: str) -> str | None:
    """Return the address that an operand's stored text names, in display form, or None.

    CLICK saves some fields as typed (``ds1``, ``DS001``, `` DS1``), so the text is read
    as typed. A pointer names its index address.
    """
    text = read_as_typed(value.strip(" "))
    pointer = split_pointer(text)
    if pointer is not None:
        text = pointer[1]
    address = parse_address(text)
    return None if address is None else address.display


def _counted_end(start: str, fields: list[tuple[int, bytes, str]], cls: str) -> list[str]:
    """Return the last address of a Send's source or a Receive's destination.

    Return an empty list if the count is 1, or if it is not a number of addresses that fit
    in the bank.
    """
    tags = {tag: value for tag, sentinel, value in fields if sentinel == _STANDARD_SENTINEL}
    try:
        count = tag_int(tags, _COUNT)
        return [_addr_end(start, count, cls)] if count > 1 else []
    except (NotANumber, FieldError):
        return []
