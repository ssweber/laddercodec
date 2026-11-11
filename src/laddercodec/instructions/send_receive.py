"""Send / Receive (Modbus) instruction family.

Binary class names: ``"SD"`` (Send, type marker 0x2729) and
``"RD"`` (Receive, type marker 0x2728).

SD has 411 tagged fields (30 semantic + 250 x 0x6889 padding + 2 post-padding
+ 128 x 0x688F padding + terminator).

RD has 169 tagged fields (40 semantic + 128 x 0x688F padding + terminator).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..binary_helpers import tag_int, tag_value
from ..model import (
    ADDRESS_BANKS,
    XY_SLOTS,
    Address,
    AfInstruction,
    FieldError,
    check_address,
)
from .family import AfInstructionFamilySpec

if TYPE_CHECKING:
    from ..csv.ast import AfCall

# ---------------------------------------------------------------------------
# Helper dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModbusRtuTarget:
    """RTU serial target."""

    name: str  # human label, not in binary
    com_port: str  # "cpu2", "cpu3", "slot0_1", "slot0_2", "slot1_1", "slot1_2"
    #: Slave ID: a number, or the DS register CLICK reads it from (``"DS2420"``).
    device_id: int | str

    def __post_init__(self) -> None:
        if self.com_port not in _RTU_PORT_MODE:
            raise FieldError(
                f"ModbusRtuTarget com_port must be one of {', '.join(_RTU_PORT_MODE)}, "
                f"got {self.com_port!r}"
            )
        _check_device_id(self.device_id)


@dataclass(frozen=True)
class ModbusTcpTarget:
    """TCP/IP target."""

    name: str  # human label, not in binary
    ip: str
    port: int
    #: Slave ID: a number, or the DS register CLICK reads it from (``"DS2420"``).
    device_id: int | str
    com_port: str = "ethernet"  # "ethernet" (CPU Port 1) or "wlan"

    def __post_init__(self) -> None:
        if self.com_port not in _TCP_PORT_MODE:
            raise FieldError(
                f"ModbusTcpTarget com_port must be one of {', '.join(_TCP_PORT_MODE)}, "
                f"got {self.com_port!r}"
            )
        _check_device_id(self.device_id)
        _check_ip(self.ip)
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise FieldError(f"ModbusTcpTarget port must be an integer, got {self.port!r}")
        if not 1 <= self.port <= 65535:
            raise FieldError(f"ModbusTcpTarget port must be 1-65535, got {self.port}")


_DS_ADDRESS_RE = re.compile(r"DS([1-9][0-9]*)")


def _check_device_id(device_id: int | str) -> None:
    """CLICK's Slave ID box takes a number or a DS address (DD, DH, C... are refused)."""
    if isinstance(device_id, str):
        m = _DS_ADDRESS_RE.fullmatch(device_id)
        if not m or int(m.group(1)) > 4500:
            raise FieldError(
                f"device_id must be a number or a DS address (DS1..DS4500), got {device_id!r}"
            )
    elif isinstance(device_id, bool) or not isinstance(device_id, int):
        raise FieldError(f"device_id must be a number or a DS address, got {device_id!r}")


_IP_RE = re.compile(r"([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})")


def _check_ip(ip: str) -> None:
    """A TCP server IP is four octets, each 0-255 (0.0.0.0 is accepted)."""
    m = _IP_RE.fullmatch(ip) if isinstance(ip, str) else None
    if m is None or any(int(octet) > 255 for octet in m.groups()):
        raise FieldError(
            f"ModbusTcpTarget ip must be four octets, each 0-255 (a.b.c.d), got {ip!r}"
        )


@dataclass(frozen=True)
class ModbusAddress:
    """Non-CLICK remote address (MODBUS 984 or hex)."""

    address: str  # "400001" or "0h"
    register_type: str | None = None  # "coil"|"holding"|... — only for hex

    def __post_init__(self) -> None:
        if self.register_type is not None and self.register_type not in REGISTER_TYPES:
            raise FieldError(
                f"ModbusAddress register_type must be one of {', '.join(REGISTER_TYPES)}, "
                f"got {self.register_type!r}"
            )
        if self.is_hex:
            if not _HEX_RE.fullmatch(self.address) or int(self.address[:-1], 16) > 0xFFFE:
                raise FieldError(
                    f"ModbusAddress address must be 0h-FFFEh in hex, got {self.address!r}"
                )
        elif not self.address.isascii() or not self.address.isdigit():
            raise FieldError(
                f"ModbusAddress address must be a MODBUS 984 number or hex (0h-FFFEh), "
                f"got {self.address!r}"
            )

    @property
    def is_hex(self) -> bool:
        return self.address.endswith("h")


#: Register types of a hex remote address, in function-code order (Receive FC01-FC04).
REGISTER_TYPES: tuple[str, ...] = ("coil", "discrete_input", "holding", "input")
_HEX_RE = re.compile(r"[0-9A-Fa-f]{1,4}h")


# ---------------------------------------------------------------------------
# Protocol mode tables
# ---------------------------------------------------------------------------

#: Protocol mode (0x220C) per port, from InstCtl_SD / InstCtl_RD and v4_captures/sweep_comm.bin.
_RTU_PORT_MODE: dict[str, str] = {
    "cpu2": "0",
    "cpu3": "1",
    "slot0_1": "4",
    "slot0_2": "5",
    "slot1_1": "6",
    "slot1_2": "7",
}
_TCP_PORT_MODE: dict[str, str] = {
    "ethernet": "2",
    "wlan": "3",
}

_RTU_PORT_MODE_INV: dict[str, str] = {v: k for k, v in _RTU_PORT_MODE.items()}
_TCP_PORT_MODE_INV: dict[str, str] = {v: k for k, v in _TCP_PORT_MODE.items()}

# ---------------------------------------------------------------------------
# Function codes
# ---------------------------------------------------------------------------

#: fc_subtype (0x2211) per Modbus function code: the item index in each dialog's
#: Function Code box.
_RD_FC_SUBTYPE: dict[int, str] = {1: "0", 2: "1", 3: "2", 4: "3"}
_SD_FC_SUBTYPE: dict[int, str] = {5: "0", 6: "1", 15: "2", 16: "3"}
_RD_FC_FROM_SUBTYPE: dict[str, int] = {v: k for k, v in _RD_FC_SUBTYPE.items()}
_SD_FC_FROM_SUBTYPE: dict[str, int] = {v: k for k, v in _SD_FC_SUBTYPE.items()}

#: Register types of a hex remote address, by Receive function code.
_RD_FC_REGISTER_TYPE: dict[int, str] = dict(zip((1, 2, 3, 4), REGISTER_TYPES, strict=True))
_RD_REGISTER_TYPE_FC: dict[str, int] = {v: k for k, v in _RD_FC_REGISTER_TYPE.items()}


def _check_function_code(who: str, function_code: object, allowed: tuple[int, ...]) -> None:
    if function_code is None:
        return
    if type(function_code) is not int or function_code not in allowed:
        listed = ", ".join(str(fc) for fc in allowed)
        raise FieldError(f"{who} function_code: {function_code!r} is not one of {listed}")


# ---------------------------------------------------------------------------
# Address helpers
# ---------------------------------------------------------------------------

_ADDR_NUM_RE = re.compile(r"^([A-Z]+)([0-9]+)$")
_XY_BANKS = frozenset({"X", "Y"})


def _xy_points(first: int, last: int) -> int:
    """How many X/Y points of :data:`XY_SLOTS` lie in ``first..last``."""
    return sum(max(0, min(last, hi) - max(first, lo) + 1) for lo, hi in XY_SLOTS)


def _xy_points_left(number: int) -> int:
    """X/Y points from ``number`` through the last slot (X816), counted along the slots."""
    return _xy_points(number, XY_SLOTS[-1][1])


def _xy_click_room(number: int) -> int:
    """Points the slot run from X/Y point ``number`` holds.

    The CPU slot and its dual option slot count as one run (X001 gives 32); a count from an
    expansion slot stays in that slot (X101 gives 16).  Inst_SD.dll 0x10018501, the X/Y case
    of the quantity limit at 0x10017d80, for a CLICK-addressed Send; Inst_RD.dll 0x10015e03
    for every Receive into Y.
    """
    if number <= 16:
        return 33 - number
    if number <= 36:
        return 37 - number
    return 17 - number % 100


def _receive_y_room(
    local: Address, remote: str | ModbusAddress, remote_addr: Address | None
) -> int:
    """Points a Receive can count into Y point ``local``: the slot run, capped by the remote.

    Inst_RD.dll 0x10015e03, the local Y case of the quantity limit at 0x100155a0, uses the
    slot run in every addressing mode.  A remote X/Y start takes the higher of the two start
    numbers (0x10015e1b); a remote C, T, CT or SC caps the count at the room left in that bank
    (0x10015e6e, 0x10015f84, 0x10016057, 0x1001612a); a MODBUS 984 start up to 65535 caps it at
    65536 minus the start (0x100161fd).

    From Y101 on, the remote C case skips its slot formula (both range tests at 0x10015f52
    and 0x10015f64 jump past it), so only the C room and the points that exist through Y816
    apply there.
    """
    if remote_addr is not None:
        if remote_addr.bank in _XY_BANKS:
            return _xy_click_room(max(local.number, remote_addr.number))
        remote_room = ADDRESS_BANKS[remote_addr.bank][1] + 1 - remote_addr.number
        if remote_addr.bank == "C" and local.number > 36:
            return min(remote_room, _xy_points_left(local.number))
        return min(remote_room, _xy_click_room(local.number))
    room = _xy_click_room(local.number)
    if isinstance(remote, ModbusAddress) and not remote.is_hex and int(remote.address) <= 0xFFFF:
        room = min(room, 0x10000 - int(remote.address))
    return room


def _check_c_remote_room(who: str, quantity: int, remote_addr: Address) -> None:
    """A count between local C and a CLICK remote also fits the remote side.

    The room is the lesser of the C room and the remote's: the slot run from an X/Y start
    (Inst_SD.dll 0x100181f6, Inst_RD.dll 0x10015c7a), or the room left in a C, T, CT or SC
    bank (SD 0x100181d6, RD 0x10015c6c, 0x10015dc5, 0x10015de5, 0x10015dec).  These are the
    local C cases (SD 0x100181be, RD 0x10015c54) of each dialog's quantity limit.
    """
    bank, number = remote_addr.bank, remote_addr.number
    if bank in _XY_BANKS:
        room = _xy_click_room(number)
        if quantity > room:
            raise FieldError(
                f"{who} quantity: {quantity} from remote {bank}{number:03d} is outside "
                f"1-{room} (X/Y points count by slot: {bank}001-{bank}016 with {bank}021-"
                f"{bank}036, then {bank}101-{bank}116 ...)"
            )
        return
    last_number = ADDRESS_BANKS[bank][1]
    left = last_number - number + 1
    if quantity > left:
        raise FieldError(
            f"{who} quantity: {quantity} from remote {bank}{number} runs past "
            f"{bank}{last_number} ({left} left)"
        )


def _xy_nth(number: int, steps: int) -> int:
    """The X/Y point ``steps`` points after ``number``, counted along the slots."""
    for lo, hi in XY_SLOTS:
        if hi < number:
            continue
        first = max(lo, number)
        if first + steps <= hi:
            return first + steps
        steps -= hi - first + 1
    raise FieldError(f"X/Y count runs past the last slot from point {number}")


def _addr_end(start: str, quantity: int) -> str:
    """End address of ``quantity`` elements from ``start`` (DS1 + 5 is DS5, X001 + 17 is X021)."""
    m = _ADDR_NUM_RE.fullmatch(start)
    if not m:
        return start
    prefix, digits = m.group(1), m.group(2)
    if prefix in _XY_BANKS:
        return f"{prefix}{_xy_nth(int(digits), quantity - 1):0{len(digits)}d}"
    return f"{prefix}{int(digits) + quantity - 1}"


def _addr_type_code(remote_start: str | ModbusAddress) -> str:
    """Return the binary address_type field value."""
    if isinstance(remote_start, str):
        return "2"  # CLICK
    if remote_start.is_hex:
        return "1"  # hex
    return "0"  # MODBUS 984


def _remote_start_str(remote_start: str | ModbusAddress) -> str:
    """Return the raw string value for the binary remote_start field."""
    if isinstance(remote_start, str):
        return remote_start
    return remote_start.address


# ---------------------------------------------------------------------------
# Field rules
#
# CLICK v4.00 Help topics 180/181 (RTU) and 213/214 (TCP), and the dialog code in
# Inst_SD.dll / Inst_RD.dll.  Address masks are baseEx CreateAddressInstValidator masks: a
# bank outside the mask raises OBJ-004, a number outside the limit OBJ-010.
# ---------------------------------------------------------------------------

_SEND_REMOTE_BITS = frozenset({"Y", "C"})
_SEND_REMOTE_REGS_FC06 = frozenset({"DS", "DH", "SD", "TD", "YD", "TXT"})
_SEND_REMOTE_REGS_FC16 = frozenset({"CTD", "DS", "DD", "DH", "DF", "SD", "TD", "TXT"})
#: Send local banks per function code: SD 0x10006cb1 (masks 0x3f, 0xdd40, 0xf3c0).
_SEND_LOCAL_BITS = frozenset({"X", "Y", "C", "T", "CT", "SC"})
_SEND_LOCAL_REGS_FC06 = frozenset({"DS", "DH", "XD", "YD", "TD", "SD", "TXT"})
_SEND_LOCAL_REGS_FC16 = frozenset({"CTD", "DS", "DD", "DH", "DF", "TD", "SD", "TXT"})
#: Banks that only FC16 carries; one of them makes a single-element Send FC16.
_FC16_ONLY = frozenset({"CTD", "DD", "DF"})
#: Local data types whose hex remote start stops at FFFDh (int32, float, text): SD 0x10005511.
_SEND_HEX_FFFD = frozenset({"DD", "CTD", "DF", "TXT"})

_RECEIVE_REMOTE_BITS = frozenset({"X", "Y", "C", "T", "CT", "SC"})
#: CLICK-addressed Receive remote banks per local bank (RD 0x10005019..0x100050a9):
#: int16, int32, float, hex and text pair only with their own kind.
_RECEIVE_REMOTE_FOR_DEST: dict[str, frozenset[str]] = {
    "DS": frozenset({"DS", "TD", "SD"}),
    "DD": frozenset({"DD", "CTD"}),
    "DF": frozenset({"DF"}),
    "DH": frozenset({"DH", "XD", "YD"}),
    "YD": frozenset({"DH", "XD", "YD"}),
    "TXT": frozenset({"TXT"}),
}
_RECEIVE_REMOTE_REGS = frozenset().union(*_RECEIVE_REMOTE_FOR_DEST.values())
#: Receive local banks: FC01/02 mask 6, FC03/04 mask 0x8bc0 (RD 0x1000640c, 0x100071c3).
_RECEIVE_LOCAL_BITS = frozenset({"Y", "C"})
_RECEIVE_LOCAL_REGS = frozenset(_RECEIVE_REMOTE_FOR_DEST)

_STATUS_BITS = frozenset({"C"})
_EXCEPTION_BANKS = frozenset({"DS", "DD"})

#: Local banks whose elements are two registers wide, so the count cap halves.
_WIDE_BANKS = frozenset({"DD", "DF", "CTD"})

#: Count caps: (bits, registers, 32-bit registers).
_SEND_CAPS = (1968, 123, 61)
_RECEIVE_CAPS = (2000, 125, 62)

#: MODBUS 984 start addresses by kind.
_984_COIL = (1, 65535)
_984_INPUT_BIT = (100001, 165535)
_984_INPUT_REG = (300001, 365535)
_984_HOLDING = (400001, 465535)
_RECEIVE_984_KINDS = {
    "coil": _984_COIL,
    "discrete_input": _984_INPUT_BIT,
    "input": _984_INPUT_REG,
    "holding": _984_HOLDING,
}
_SEND_984_KINDS = {"coil": _984_COIL, "holding": _984_HOLDING}


def _check_slave_id(who: str, target: ModbusRtuTarget | ModbusTcpTarget, rtu_low: int) -> None:
    """A numeric Slave ID: RTU 0-247 (Receive 1-247), TCP 0-255; a DS address always passes."""
    device_id = target.device_id
    if isinstance(device_id, str):
        return
    if isinstance(target, ModbusRtuTarget):
        low, high, link = rtu_low, 247, "RTU"
    else:
        low, high, link = 0, 255, "TCP"
    if not low <= device_id <= high:
        raise FieldError(f"{who} target.device_id: {device_id} is outside {low}-{high} for {link}")


def _check_status(who: str, name: str, value: str, banks: frozenset[str]) -> Address | None:
    if value:
        return check_address(value, f"{who} {name}", banks=banks)
    return None


def _check_status_bits(who: str, inst: Send | Receive, names: tuple[str, str, str]) -> None:
    """Each status field is a C bit, and no C bit serves two of them."""
    seen: dict[tuple[str, int], str] = {}
    for name in names:
        value = getattr(inst, name)
        found = _check_status(who, name, value, _STATUS_BITS)
        if found is None:
            continue
        key = (found.bank, found.number)
        if key in seen:
            raise FieldError(f"{who} {name}: {value} is already the {seen[key]} bit")
        seen[key] = name


def _check_984(who: str, address: str, kinds: dict[str, tuple[int, int]]) -> str:
    """The kind (a key of ``kinds``) a MODBUS 984 start address belongs to."""
    n = int(address)
    for kind, (low, high) in kinds.items():
        if low <= n <= high:
            return kind
    ranges = ", ".join(f"{low}-{high}" for low, high in kinds.values())
    raise FieldError(f"{who} remote_start: {address!r} is outside the MODBUS 984 ranges {ranges}")


def _check_int_quantity(who: str, quantity: object) -> None:
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise FieldError(f"{who} quantity: {quantity!r} is not an integer")


def _check_quantity(
    who: str,
    quantity: int,
    local: Address,
    caps: tuple[int, int, int],
    bit: bool,
    xy_room: int | None = None,
) -> None:
    """The count cap per kind, then the room left from the local start.

    ``xy_room`` is the room from an X/Y start, which depends on the remote side.  None, for
    a Send to a MODBUS 984 or hex address, is the points left through the last slot.
    """
    bits, regs, wide = caps
    if bit:
        high, kind = bits, "bits"
    elif local.bank in _WIDE_BANKS:
        high, kind = wide, f"{local.bank} registers"
    else:
        high, kind = regs, "registers"
    if not 1 <= quantity <= high:
        raise FieldError(f"{who} quantity: {quantity} is outside 1-{high} {kind}")
    if local.bank in _XY_BANKS:
        room = _xy_points_left(local.number) if xy_room is None else xy_room
        if quantity > room:
            raise FieldError(
                f"{who} quantity: {quantity} from {local.bank}{local.number:03d} is outside "
                f"1-{room} (X/Y points count by slot: {local.bank}001-{local.bank}016 with "
                f"{local.bank}021-{local.bank}036, then {local.bank}101-{local.bank}116 ...)"
            )
        return
    if local.bank in ("XD", "YD"):
        return  # one element only; the function code or local bank rule says so
    last_number = ADDRESS_BANKS[local.bank][1]
    left = last_number - local.number + 1
    if quantity > left:
        raise FieldError(
            f"{who} quantity: {quantity} from {local.bank}{local.number} runs past "
            f"{local.bank}{last_number} ({left} left)"
        )


def _send_default_fc(send: Send, bit: bool, local: Address, remote_bank: str | None) -> int:
    """FC05/FC15 for bits, FC06/FC16 for registers; one element is FC05/FC06 unless a bank
    only FC16 carries (DD, DF, CTD) is on either side."""
    single = send.quantity == 1
    if bit:
        return 5 if single else 15
    if single and local.bank not in _FC16_ONLY and remote_bank not in _FC16_ONLY:
        return 6
    return 16


def _validate_send(send: Send) -> tuple[int, int]:
    """Check every field; return the function code the Send is written with, and the default."""
    who = "Send"
    _check_slave_id(who, send.target, 0)
    _check_function_code(who, send.function_code, tuple(_SD_FC_SUBTYPE))
    remote, quantity = send.remote_start, send.quantity
    _check_int_quantity(who, quantity)
    remote_addr: Address | None = None
    if isinstance(remote, str):
        remote_addr = check_address(
            remote,
            f"{who} remote_start",
            _SEND_REMOTE_BITS | _SEND_REMOTE_REGS_FC06 | _SEND_REMOTE_REGS_FC16,
        )
        bit = remote_addr.bank in _SEND_REMOTE_BITS
    elif remote.is_hex:
        register_type = remote.register_type or "holding"
        if register_type not in ("coil", "holding"):
            raise FieldError(
                f"{who} remote_start: register_type {register_type!r} cannot be written; "
                "a Send takes coil or holding"
            )
        bit = register_type == "coil"
    else:
        bit = _check_984(who, remote.address, _SEND_984_KINDS) == "coil"

    if bit:
        banks = _SEND_LOCAL_BITS
    else:
        banks = _SEND_LOCAL_REGS_FC06 | _SEND_LOCAL_REGS_FC16
    local = check_address(send.source, f"{who} source", banks)
    remote_bank = remote_addr.bank if remote_addr is not None else None
    default_fc = _send_default_fc(send, bit, local, remote_bank)
    fc = send.function_code or default_fc

    # The function code must suit the remote kind, and FC05/FC06 carry one element.
    if fc not in ((5, 15) if bit else (6, 16)):
        kind = "a coil" if bit else "a register"
        raise FieldError(f"{who} function_code: FC{fc:02d} cannot write {kind}")
    if fc in (5, 6) and quantity != 1:
        raise FieldError(f"{who} function_code: FC{fc:02d} writes one element, not {quantity}")
    if not bit:
        fc06 = fc == 6
        local_banks = _SEND_LOCAL_REGS_FC06 if fc06 else _SEND_LOCAL_REGS_FC16
        check_address(send.source, f"{who} source (FC{fc:02d})", local_banks)
        if isinstance(remote, str):
            remote_banks = _SEND_REMOTE_REGS_FC06 if fc06 else _SEND_REMOTE_REGS_FC16
            check_address(remote, f"{who} remote_start (FC{fc:02d})", remote_banks)

    xy_room = None
    if local.bank in _XY_BANKS and remote_addr is not None:
        if remote_addr.bank in _XY_BANKS:
            # SD 0x10018501: the higher of the two start numbers decides the room.
            xy_room = _xy_click_room(max(local.number, remote_addr.number))
        else:
            # Remote C: the room left in C (SD 0x1001853f) or in the local slot run.
            c_room = ADDRESS_BANKS[remote_addr.bank][1] + 1 - remote_addr.number
            xy_room = min(c_room, _xy_click_room(local.number))
    _check_quantity(who, quantity, local, _SEND_CAPS, bit, xy_room)
    if local.bank == "C" and remote_addr is not None:
        _check_c_remote_room(who, quantity, remote_addr)

    if isinstance(remote, ModbusAddress) and remote.is_hex and local.bank in _SEND_HEX_FFFD:
        start = int(remote.address[:-1], 16)
        if start > 0xFFFD:  # SD 0x10005511, OBJ-010
            raise FieldError(
                f"{who} remote_start: {remote.address!r} is outside 0h-FFFDh for a "
                f"{local.bank} source"
            )
        room = min(_SEND_CAPS[2], 0xFFFE - start)  # SD 0x100191c9
        if local.bank == "DD" and quantity > room:
            raise FieldError(
                f"{who} quantity: {quantity} from hex {remote.address!r} is outside 1-{room}"
            )

    # SD 0x100095f0: one C bit can't serve two status fields (OBJ-014).
    _check_status_bits(who, send, ("sending", "success", "error"))
    _check_status(who, "exception_response", send.exception_response, _EXCEPTION_BANKS)
    return fc, default_fc


def _receive_default_fc(remote: str | ModbusAddress, bit: bool) -> int:
    """FC01 or FC03 for a CLICK address; a hex or 984 address names its own code."""
    if isinstance(remote, str):
        return 1 if bit else 3
    if remote.is_hex:
        return _RD_REGISTER_TYPE_FC[remote.register_type or "holding"]
    return _RD_REGISTER_TYPE_FC[_check_984("Receive", remote.address, _RECEIVE_984_KINDS)]


def _validate_receive(receive: Receive) -> tuple[int, int]:
    """Check every field; return the function code the Receive is written with, and the default."""
    who = "Receive"
    _check_slave_id(who, receive.target, 1)
    _check_function_code(who, receive.function_code, tuple(_RD_FC_SUBTYPE))
    remote, quantity = receive.remote_start, receive.quantity
    _check_int_quantity(who, quantity)
    remote_addr: Address | None = None
    if isinstance(remote, str):
        remote_addr = check_address(
            remote, f"{who} remote_start", _RECEIVE_REMOTE_BITS | _RECEIVE_REMOTE_REGS
        )
        bit = remote_addr.bank in _RECEIVE_REMOTE_BITS
    elif remote.is_hex:
        bit = (remote.register_type or "holding") in ("coil", "discrete_input")
    else:
        bit = _check_984(who, remote.address, _RECEIVE_984_KINDS) in ("coil", "discrete_input")
    default_fc = _receive_default_fc(remote, bit)
    fc = receive.function_code or default_fc
    if remote_addr is not None:
        # RD 0x1000c0db..0x1000cefb: a CLICK address is read with whichever code is picked.
        if fc not in ((1, 2) if bit else (3, 4)):
            kind = "a bit" if bit else "a register"
            raise FieldError(f"{who} function_code: FC{fc:02d} cannot read {kind}")
    elif fc != default_fc:
        raise FieldError(
            f"{who} function_code: FC{fc:02d} does not match remote_start "
            f"{_remote_start_to_csv(remote)}, which is FC{default_fc:02d}"
        )

    local = check_address(
        receive.dest, f"{who} dest", _RECEIVE_LOCAL_BITS if bit else _RECEIVE_LOCAL_REGS
    )
    hex_pair = False
    if isinstance(remote, str) and remote_addr is not None and not bit:
        name = f"{who} remote_start (for a {local.bank} dest)"
        check_address(remote, name, _RECEIVE_REMOTE_FOR_DEST[local.bank])
        hex_pair = remote_addr.bank in ("XD", "YD")
    xy_room = _receive_y_room(local, remote, remote_addr) if local.bank in _XY_BANKS else None
    _check_quantity(who, quantity, local, _RECEIVE_CAPS, bit, xy_room)
    if local.bank == "C" and remote_addr is not None:
        _check_c_remote_room(who, quantity, remote_addr)
    if (local.bank == "YD" or hex_pair) and quantity != 1:
        # RD 0x1001420d / 0x100141ec: a YD dest, or a DH dest read from XD/YD, is "(1 to 1)".
        raise FieldError(f"{who} quantity: {quantity} is outside 1-1 for this dest and remote")
    if local.bank == "TXT" and (quantity < 2 or quantity % 2):
        # RD 0x10006bab: text arrives two characters per register.
        raise FieldError(f"{who} quantity: {quantity} TXT characters must be an even count of 2+")

    if receive.word_swap:
        # RD 0x10006b78, 0x10006afa, 0x1000686d, 0x10006bab: CLICK forces Word Swap off here.
        if bit:
            reason = "bits"
        elif local.bank in ("YD", "TXT") or hex_pair:
            reason = f"a {local.bank} dest"
        elif local.bank in ("DD", "DF") and remote_addr is not None:
            reason = f"a {local.bank} dest read from a CLICK address"
        elif local.bank in ("DS", "DH") and quantity == 1:
            # RD 0x10006a3e..0x10006aeb: a DS or DH dest enables Word Swap above one element.
            reason = f"one {local.bank} element"
        else:
            reason = ""
        if reason:
            raise FieldError(f"{who} word_swap: CLICK turns Word Swap off for {reason}")

    # RD 0x100092c9, 0x1000a5e9: one C bit can't serve two status fields (0x271e).
    _check_status_bits(who, receive, ("receiving", "success", "error"))
    _check_status(who, "exception_response", receive.exception_response, _EXCEPTION_BANKS)
    return fc, default_fc


# ---------------------------------------------------------------------------
# Tag tuples — exact field order verified from binary captures
# ---------------------------------------------------------------------------

_RD_TAGS: tuple[int, ...] = (
    0x3218,  # [0]  func_code
    0x220C,  # [1]  protocol_mode
    0x2225,  # [2]  reserved '0'
    0x220D,  # [3]  reserved '0'
    0x120A,  # [4]  receiving_enabled
    0x607C,  # [5]  receiving_bit
    0x1209,  # [6]  success_enabled
    0x607B,  # [7]  success_bit
    0x120B,  # [8]  error_enabled
    0x607D,  # [9]  error_bit
    0x121A,  # [10] exception_enabled
    0x6083,  # [11] exception_response
    0x121B,  # [12] reserved '0'
    0x6084,  # [13] reserved ''
    0x320E,  # [14] device_id
    0x60B2,  # [15] device_id_dup
    0x223A,  # [16] reserved '0'
    0x2211,  # [17] fc_subtype
    0x320F,  # [18] address_type
    0x6085,  # [19] remote_start
    0x607E,  # [20] dest
    0x3210,  # [21] quantity
    0x221C,  # [22] word_swap_off
    0x221D,  # [23] reserved '0'
    0x607F,  # [24] reserved ''
    0x6080,  # [25] reserved ''
    0x2212,  # [26] reserved '0'
    0x121E,  # [27] reserved '0'
    0x6086,  # [28] reserved ''
    0x2213,  # [29] reserved '0'
    0x121F,  # [30] reserved '0'
    0x6087,  # [31] reserved ''
    0x1220,  # [32] reserved '0'
    0x2214,  # [33] reserved '0'
    0x2215,  # [34] reserved '0'
    0x3216,  # [35] reserved '0'
    0x622B,  # [36] ip_or_name
    0x322C,  # [37] port
    0x608D,  # [38] sd_status_1
    0x608E,  # [39] sd_status_2
)

_SD_TAGS: tuple[int, ...] = (
    0x3218,  # [0]  func_code
    0x220C,  # [1]  protocol_mode
    0x2225,  # [2]  reserved '0'
    0x120A,  # [3]  sending_enabled
    0x607C,  # [4]  sending_bit
    0x1209,  # [5]  success_enabled
    0x607B,  # [6]  success_bit
    0x120B,  # [7]  error_enabled
    0x607D,  # [8]  error_bit
    0x121A,  # [9]  exception_enabled
    0x6083,  # [10] exception_response
    0x320E,  # [11] device_id
    0x60B2,  # [12] device_id_dup
    0x223A,  # [13] reserved '0'
    0x2211,  # [14] fc_subtype
    0x320F,  # [15] address_type
    0x6085,  # [16] remote_start
    0x607E,  # [17] source
    0x3210,  # [18] quantity
    0x221C,  # [19] word_swap_off
    0x220D,  # [20] reserved '0'
    0x6217,  # [21] reserved ''
    0x6081,  # [22] reserved ''
    0x6082,  # [23] reserved ''
    0x1220,  # [24] reserved '0'
    0x2214,  # [25] reserved '0'
    0x1221,  # [26] reserved '0'
    0x2215,  # [27] reserved '0'
    0x3216,  # [28] reserved '0'
    0x622A,  # [29] reserved ''
)

_RD_RESERVED_DEFAULTS: tuple[str, ...] = (
    "0",
    "",  # [23-24]  0x221D, 0x607F
    "",  # [25]     0x6080
    "0",
    "0",  # [26-27]  0x2212, 0x121E
    "",  # [28]     0x6086
    "0",
    "0",  # [29-30]  0x2213, 0x121F
    "",  # [31]     0x6087
    "0",
    "0",
    "0",
    "0",  # [32-35] 0x1220, 0x2214, 0x2215, 0x3216
)

_SD_RESERVED_DEFAULTS: tuple[str, ...] = (
    "0",  # [20] 0x220D
    "",
    "",
    "",  # [21-23] 0x6217, 0x6081, 0x6082
    "0",
    "0",  # [24-25] 0x1220, 0x2214
    "0",
    "0",  # [26-27] 0x1221, 0x2215
    "0",
    "",  # [28-29] 0x3216, 0x622A
)

# ---------------------------------------------------------------------------
# Func code constants
# ---------------------------------------------------------------------------

#: Modbus func code (0x3218) by (TCP, slave ID is an address), from InstCtl_RD / InstCtl_SD.
#: The ASCII variants (RD 9729/9730, SD 9732/9733) aren't modelled and decode as raw.
_RD_FUNC: dict[tuple[bool, bool], str] = {
    (False, False): "9728",
    (True, False): "9735",
    (False, True): "9749",
    (True, True): "9750",
}
_SD_FUNC: dict[tuple[bool, bool], str] = {
    (False, False): "9731",
    (True, False): "9736",
    (False, True): "9751",
    (True, True): "9752",
}


@dataclass(frozen=True)
class _TargetFields:
    func_code: str
    protocol_mode: str  # 0x220C
    slave_id: str  # 0x320E: the number, or 1 for an address
    slave_text: str  # 0x60B2: what the Slave ID box shows
    slave_is_address: str  # 0x223A
    ip: str  # 0x622B
    port: str  # 0x322C


def _target_fields(
    target: ModbusRtuTarget | ModbusTcpTarget, func: dict[tuple[bool, bool], str]
) -> _TargetFields:
    tcp = isinstance(target, ModbusTcpTarget)
    is_address = isinstance(target.device_id, str)
    if isinstance(target, ModbusTcpTarget):
        protocol_mode = _TCP_PORT_MODE[target.com_port]
        ip, port = target.ip, str(target.port)
    else:
        protocol_mode = _RTU_PORT_MODE[target.com_port]
        ip, port = "...", "502"
    return _TargetFields(
        func_code=func[(tcp, is_address)],
        protocol_mode=protocol_mode,
        slave_id="1" if is_address else str(target.device_id),
        slave_text=str(target.device_id),
        slave_is_address="1" if is_address else "0",
        ip=ip,
        port=port,
    )


# ---------------------------------------------------------------------------
# Instruction dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Receive(AfInstruction):
    """A Modbus Receive (RD) instruction."""

    target: ModbusRtuTarget | ModbusTcpTarget
    remote_start: str | ModbusAddress
    dest: str  # start address
    quantity: int
    receiving: str  # C bit ("" if disabled)
    success: str
    error: str
    exception_response: str  # DS/DD address ("" if disabled)
    word_swap: bool = False
    #: Modbus function code 1-4.  None reads a CLICK bit address with FC01 and a register
    #: with FC03; FC02 and FC04 must be named.  A hex or 984 address fixes its own code.
    function_code: int | None = None

    def __post_init__(self) -> None:
        fc, default_fc = _validate_receive(self)
        self.function_code = None if fc == default_fc else fc

    def to_csv(self) -> str:
        parts: list[str] = []
        parts.append(f"target={_target_to_csv(self.target)}")
        parts.append(f"remote_start={_remote_start_to_csv(self.remote_start)}")
        if self.function_code is not None:
            parts.append(f"function_code={self.function_code}")
        if self.quantity > 1:
            parts.append(f"dest={self.dest}..{_addr_end(self.dest, self.quantity)}")
        else:
            parts.append(f"dest={self.dest}")
        if self.receiving:
            parts.append(f"receiving={self.receiving}")
        if self.success:
            parts.append(f"success={self.success}")
        if self.error:
            parts.append(f"error={self.error}")
        if self.exception_response:
            parts.append(f"exception_response={self.exception_response}")
        if self.word_swap:
            parts.append("word_swap=1")
        return f"receive({','.join(parts)})"

    def cell_params(self) -> dict:
        return {"visual_rows": 3}

    def build_blob(self) -> bytes:
        from ..binary_helpers import _tagged_field, _utf16le_null

        t = _target_fields(self.target, _RD_FUNC)
        fc_subtype = _RD_FC_SUBTYPE[_validate_receive(self)[0]]
        address_type = _addr_type_code(self.remote_start)

        fields: list[str] = [
            t.func_code,  # [0]
            t.protocol_mode,  # [1]
            "0",  # [2]  reserved
            "0",  # [3]  reserved
            "1" if self.receiving else "0",  # [4]  receiving_enabled
            self.receiving or "",  # [5]  receiving_bit
            "1" if self.success else "0",  # [6]  success_enabled
            self.success or "",  # [7]  success_bit
            "1" if self.error else "0",  # [8]  error_enabled
            self.error or "",  # [9]  error_bit
            "1" if self.exception_response else "0",  # [10] exception_enabled
            self.exception_response or "",  # [11] exception_response
            "0",  # [12] reserved
            "",  # [13] reserved
            t.slave_id,  # [14] device_id
            t.slave_text,  # [15] device_id text
            t.slave_is_address,  # [16] device_id is an address
            fc_subtype,  # [17] fc_subtype
            address_type,  # [18] address_type
            _remote_start_str(self.remote_start),  # [19] remote_start
            self.dest,  # [20] dest
            str(self.quantity),  # [21] quantity
            "0" if self.word_swap else "1",  # [22] word_swap_off
        ]
        fields.extend(_RD_RESERVED_DEFAULTS)  # [23-35]
        fields.extend([t.ip, t.port, "SD50", "SD60"])  # [36-39]

        type_marker = 0x2728
        field_count = len(_RD_TAGS) + 128 + 1  # 40 + 128 padding + terminator = 169

        out = bytearray()
        out += _utf16le_null("RD")
        out += struct.pack("<I", type_marker)
        out += b"\x01\x00"  # part count
        out += struct.pack("<I", field_count)
        for tag, value in zip(_RD_TAGS, fields, strict=True):
            out += _tagged_field(tag, value)
        for _ in range(128):
            out += _tagged_field(0x688F, "")
        out += _tagged_field(0x0000, "")  # terminator
        return bytes(out)


@dataclass
class Send(AfInstruction):
    """A Modbus Send (SD) instruction."""

    target: ModbusRtuTarget | ModbusTcpTarget
    remote_start: str | ModbusAddress
    source: str  # start address
    quantity: int
    sending: str
    success: str
    error: str
    exception_response: str
    word_swap: bool = False
    #: Modbus function code 5, 6, 15 or 16.  None writes one element with FC05/FC06 (FC16
    #: when DD, DF or CTD is on either side) and a block with FC15/FC16.
    function_code: int | None = None

    def __post_init__(self) -> None:
        fc, default_fc = _validate_send(self)
        self.function_code = None if fc == default_fc else fc

    def to_csv(self) -> str:
        parts: list[str] = []
        parts.append(f"target={_target_to_csv(self.target)}")
        parts.append(f"remote_start={_remote_start_to_csv(self.remote_start)}")
        if self.function_code is not None:
            parts.append(f"function_code={self.function_code}")
        if self.quantity > 1:
            parts.append(f"source={self.source}..{_addr_end(self.source, self.quantity)}")
        else:
            parts.append(f"source={self.source}")
        if self.sending:
            parts.append(f"sending={self.sending}")
        if self.success:
            parts.append(f"success={self.success}")
        if self.error:
            parts.append(f"error={self.error}")
        if self.exception_response:
            parts.append(f"exception_response={self.exception_response}")
        if self.word_swap:
            parts.append("word_swap=1")
        return f"send({','.join(parts)})"

    def cell_params(self) -> dict:
        return {"visual_rows": 3}

    def build_blob(self) -> bytes:
        from ..binary_helpers import _tagged_field, _utf16le_null

        t = _target_fields(self.target, _SD_FUNC)
        fc_subtype = _SD_FC_SUBTYPE[_validate_send(self)[0]]
        address_type = _addr_type_code(self.remote_start)

        fields: list[str] = [
            t.func_code,  # [0]
            t.protocol_mode,  # [1]
            "0",  # [2]  reserved
            "1" if self.sending else "0",  # [3]  sending_enabled
            self.sending or "",  # [4]  sending_bit
            "1" if self.success else "0",  # [5]  success_enabled
            self.success or "",  # [6]  success_bit
            "1" if self.error else "0",  # [7]  error_enabled
            self.error or "",  # [8]  error_bit
            "1" if self.exception_response else "0",  # [9]  exception_enabled
            self.exception_response or "",  # [10] exception_response
            t.slave_id,  # [11] device_id
            t.slave_text,  # [12] device_id text
            t.slave_is_address,  # [13] device_id is an address
            fc_subtype,  # [14] fc_subtype
            address_type,  # [15] address_type
            _remote_start_str(self.remote_start),  # [16] remote_start
            self.source,  # [17] source
            str(self.quantity),  # [18] quantity
            "0" if self.word_swap else "1",  # [19] word_swap_off
        ]
        fields.extend(_SD_RESERVED_DEFAULTS)  # [20-29]

        type_marker = 0x2729
        # 30 semantic + 250 padding(0x6889) + 2 post + 128 padding(0x688F) + 1 term = 411
        field_count = 30 + 250 + 2 + 128 + 1

        out = bytearray()
        out += _utf16le_null("SD")
        out += struct.pack("<I", type_marker)
        out += b"\x01\x00"  # part count
        out += struct.pack("<I", field_count)
        for tag, value in zip(_SD_TAGS, fields, strict=True):
            out += _tagged_field(tag, value)
        for _ in range(250):
            out += _tagged_field(0x6889, "")
        out += _tagged_field(0x622B, t.ip)  # [280] ip_or_name
        out += _tagged_field(0x322C, t.port)  # [281] port
        for _ in range(128):
            out += _tagged_field(0x688F, "")
        out += _tagged_field(0x0000, "")  # terminator
        return bytes(out)


# ---------------------------------------------------------------------------
# CSV formatting helpers
# ---------------------------------------------------------------------------


def _target_to_csv(target: ModbusRtuTarget | ModbusTcpTarget) -> str:
    if isinstance(target, ModbusRtuTarget):
        return (
            f'ModbusRtuTarget(name="{target.name}"'
            f',com_port="{target.com_port}"'
            f",device_id={target.device_id})"
        )
    com_port = "" if target.com_port == "ethernet" else f',com_port="{target.com_port}"'
    return (
        f'ModbusTcpTarget(name="{target.name}"'
        f',ip="{target.ip}"'
        f",port={target.port}"
        f",device_id={target.device_id}{com_port})"
    )


def _remote_start_to_csv(remote_start: str | ModbusAddress) -> str:
    if isinstance(remote_start, str):
        return f'"{remote_start}"'
    if remote_start.register_type is not None:
        return (
            f"ModbusAddress(address={remote_start.address}"
            f",register_type={remote_start.register_type})"
        )
    return f"ModbusAddress(address={remote_start.address})"


# ---------------------------------------------------------------------------
# Shared from_tags factory
# ---------------------------------------------------------------------------

_RD_TYPE_CODE = 0x2728
_SD_TYPE_CODE = 0x2729


def from_tags(
    class_name: str,
    type_code: int,
    tags: dict[int, str],
    variant_u16_tags: dict[int, dict[int, int]] | None = None,
    variant_string_tags: dict[int, dict[int, str]] | None = None,
) -> Receive | Send | None:
    """Construct a Send or Receive from tag data (shared by both decoders)."""
    if class_name == "RD" and type_code == _RD_TYPE_CODE:
        return _from_tags_rd(tags)
    if class_name == "SD" and type_code == _SD_TYPE_CODE:
        return _from_tags_sd(tags)
    return None


def _build_target(
    tags: dict[int, str], class_name: str
) -> ModbusRtuTarget | ModbusTcpTarget | None:
    """The target, or None for a port or func code we don't model (decodes as raw)."""
    func_code = tags.get(0x3218)
    known = _RD_FUNC if class_name == "RD" else _SD_FUNC
    if func_code is not None and func_code not in known.values():
        return None
    protocol_mode = tag_value(tags, 0x220C)
    if tag_value(tags, 0x223A) == "1":
        device_id: int | str = tag_value(tags, 0x60B2)
    else:
        # SCR blobs elide fields at their class default: Receive's device_id
        # default is 1, Send's 0 (a Send at device_id 0 stores no 0x320E/0x60B2
        # tag, while one at 1 stores both — verified against a native scr+clipboard pair).
        device_id = tag_int(tags, 0x320E if 0x320E in tags else 0x60B2, class_name)
    try:
        if protocol_mode in _TCP_PORT_MODE_INV:
            return ModbusTcpTarget(
                name="tcp",
                ip=tag_value(tags, 0x622B),
                port=tag_int(tags, 0x322C),
                device_id=device_id,
                com_port=_TCP_PORT_MODE_INV[protocol_mode],
            )
        if protocol_mode in _RTU_PORT_MODE_INV:
            return ModbusRtuTarget(
                name="rtu",
                com_port=_RTU_PORT_MODE_INV[protocol_mode],
                device_id=device_id,
            )
    except ValueError:  # a slave-ID address CLICK's dialog wouldn't accept
        return None
    return None


def _build_remote_start(tags: dict[int, str], function_code: int) -> str | ModbusAddress | None:
    remote_start_raw = tag_value(tags, 0x6085)
    if not remote_start_raw:
        return None

    address_type = tag_value(tags, 0x320F)
    if address_type == "2":
        return remote_start_raw
    if address_type == "1":
        if function_code in _RD_FC_REGISTER_TYPE:
            rt = _RD_FC_REGISTER_TYPE[function_code]
        else:
            rt = "coil" if function_code in (5, 15) else "holding"
        return ModbusAddress(address=remote_start_raw, register_type=rt)
    return ModbusAddress(address=remote_start_raw)


def _from_tags_rd(tags: dict[int, str]) -> Receive | None:
    target = _build_target(tags, "RD")
    function_code = _RD_FC_FROM_SUBTYPE.get(tag_value(tags, 0x2211))
    if function_code is None:
        return None
    remote_start = _build_remote_start(tags, function_code)
    dest = tag_value(tags, 0x607E)
    if target is None or remote_start is None or not dest:
        return None

    return Receive(
        target=target,
        remote_start=remote_start,
        dest=dest,
        quantity=tag_int(tags, 0x3210),
        receiving=tag_value(tags, 0x607C),
        success=tag_value(tags, 0x607B),
        error=tag_value(tags, 0x607D),
        exception_response=tag_value(tags, 0x6083),
        word_swap=tag_value(tags, 0x221C) == "0",
        function_code=function_code,
    )


def _from_tags_sd(tags: dict[int, str]) -> Send | None:
    target = _build_target(tags, "SD")
    function_code = _SD_FC_FROM_SUBTYPE.get(tag_value(tags, 0x2211))
    if function_code is None:
        return None
    remote_start = _build_remote_start(tags, function_code)
    source = tag_value(tags, 0x607E)
    if target is None or remote_start is None or not source:
        return None

    return Send(
        target=target,
        remote_start=remote_start,
        source=source,
        quantity=tag_int(tags, 0x3210),
        sending=tag_value(tags, 0x607C),
        success=tag_value(tags, 0x607B),
        error=tag_value(tags, 0x607D),
        exception_response=tag_value(tags, 0x6083),
        word_swap=tag_value(tags, 0x221C) == "0",
        function_code=function_code,
    )


# ---------------------------------------------------------------------------
# CSV call parser
# ---------------------------------------------------------------------------

_CONSTRUCTOR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\((.+)\)$", re.DOTALL)


def _parse_constructor_kwargs(inner: str) -> dict[str, str]:
    """Parse comma-separated kwargs from a constructor call body."""
    kwargs: dict[str, str] = {}
    depth = 0
    start = 0
    for i, ch in enumerate(inner):
        if ch in ("(", "["):
            depth += 1
        elif ch in (")", "]"):
            depth -= 1
        elif ch == "," and depth == 0:
            _add_kwarg(inner[start:i], kwargs)
            start = i + 1
    _add_kwarg(inner[start:], kwargs)
    return kwargs


def _add_kwarg(seg: str, kwargs: dict[str, str]) -> None:
    seg = seg.strip()
    if "=" not in seg:
        return
    k, v = seg.split("=", 1)
    kwargs[k.strip()] = v.strip()


def _strip_quotes(s: str) -> str:
    """Remove surrounding double-quotes if present."""
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def _parse_target(raw: str) -> ModbusRtuTarget | ModbusTcpTarget:
    m = _CONSTRUCTOR_RE.fullmatch(raw.strip())
    if not m:
        raise ValueError(f"Cannot parse target: {raw!r}")
    cls_name = m.group(1)
    kw = _parse_constructor_kwargs(m.group(2))

    name = _strip_quotes(kw.get("name", ""))
    raw_id = _strip_quotes(kw.get("device_id", "0"))
    device_id: int | str = (
        int(raw_id) if raw_id.isascii() and raw_id.lstrip("-").isdigit() else raw_id
    )

    if cls_name == "ModbusRtuTarget":
        com_port = _strip_quotes(kw.get("com_port", "cpu2"))
        return ModbusRtuTarget(name=name, com_port=com_port, device_id=device_id)
    if cls_name == "ModbusTcpTarget":
        ip = _strip_quotes(kw.get("ip", ""))
        raw_port = kw.get("port", "502")
        if not raw_port.isascii() or not raw_port.lstrip("-").isdigit():
            raise FieldError(f"ModbusTcpTarget port must be an integer, got {raw_port!r}")
        port = int(raw_port)
        com_port = _strip_quotes(kw.get("com_port", "ethernet"))
        return ModbusTcpTarget(name=name, ip=ip, port=port, device_id=device_id, com_port=com_port)
    raise ValueError(f"Unknown target type: {cls_name!r}")


def _parse_remote_start(raw: str) -> str | ModbusAddress:
    """Parse remote_start value — quoted string or ModbusAddress(...)."""
    raw = raw.strip()
    if raw.startswith('"'):
        return _strip_quotes(raw)
    m = _CONSTRUCTOR_RE.fullmatch(raw)
    if m and m.group(1) == "ModbusAddress":
        kw = _parse_constructor_kwargs(m.group(2))
        return ModbusAddress(
            address=kw.get("address", ""),
            register_type=kw.get("register_type"),
        )
    return raw


def _parse_range_quantity(raw: str) -> tuple[str, int]:
    """Parse 'DS1..DS5' → ('DS1', 5) or 'DS1' → ('DS1', 1).

    CLICK stores a start and a count.  An X/Y range counts the points of the slots it
    covers, so X001..X021 is 17 (X001-X016, then X021).
    """
    if ".." in raw:
        start, end = raw.split("..", 1)
        start = start.strip()
        end = end.strip()
        m_start = _ADDR_NUM_RE.fullmatch(start)
        m_end = _ADDR_NUM_RE.fullmatch(end)
        if not (m_start and m_end):
            raise FieldError(f"range {raw!r} must run between two addresses of one bank")
        prefix = m_start.group(1)
        if m_end.group(1) != prefix:
            raise FieldError(f"range {raw!r} mixes banks {prefix} and {m_end.group(1)}")
        check_address(end, f"range end of {raw!r}", banks={prefix})
        first, last = int(m_start.group(2)), int(m_end.group(2))
        if last < first:
            raise FieldError(f"range {raw!r} runs backwards")
        qty = _xy_points(first, last) if prefix in _XY_BANKS else last - first + 1
        return start, qty
    return raw.strip(), 1


def _parse_function_code(kw: dict[str, str]) -> int | None:
    raw = kw.get("function_code")
    if raw is None:
        return None
    if not raw.isascii() or not raw.isdigit():
        raise FieldError(f"function_code must be a number, got {raw!r}")
    return int(raw)


def parse_af_call(call: AfCall) -> Receive | Send:
    """Parse a CSV AF call node into a Send or Receive instruction."""
    kw = call.kwargs

    target = _parse_target(kw["target"])
    remote_start = _parse_remote_start(kw["remote_start"])
    word_swap = kw.get("word_swap") == "1"
    function_code = _parse_function_code(kw)

    receiving = kw.get("receiving", "")
    sending = kw.get("sending", "")
    success = kw.get("success", "")
    error = kw.get("error", "")
    exception_response = kw.get("exception_response", "")

    if call.name == "receive":
        dest_raw = kw.get("dest", "")
        dest, quantity = _parse_range_quantity(dest_raw)
        return Receive(
            target=target,
            remote_start=remote_start,
            dest=dest,
            quantity=quantity,
            receiving=receiving,
            success=success,
            error=error,
            exception_response=exception_response,
            word_swap=word_swap,
            function_code=function_code,
        )

    if call.name == "send":
        source_raw = kw.get("source", "")
        source, quantity = _parse_range_quantity(source_raw)
        return Send(
            target=target,
            remote_start=remote_start,
            source=source,
            quantity=quantity,
            sending=sending,
            success=success,
            error=error,
            exception_response=exception_response,
            word_swap=word_swap,
            function_code=function_code,
        )

    raise ValueError(f"Unsupported send_receive instruction: {call.name!r}")


# ---------------------------------------------------------------------------
# Family spec
# ---------------------------------------------------------------------------

SPEC = AfInstructionFamilySpec(
    family_name="send_receive",
    instruction_types=(Receive, Send),
    binary_class_names=("RD", "SD"),
    from_tags=from_tags,
    csv_names=("receive", "send"),
    parse_csv_call=parse_af_call,
    min_csv_rows=3,
)
