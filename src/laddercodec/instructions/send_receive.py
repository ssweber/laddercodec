"""The Modbus Send and Receive instructions.

CLICK stores a Send with the binary class name ``"SD"`` and the type marker 0x2729. It
stores a Receive with ``"RD"`` and 0x2728.

An SD blob has 411 tagged fields. There are 30 fields with fixed meanings, then 250
padding fields tagged 0x6889, then the IP and port fields, then 128 padding fields tagged
0x688F, and then a terminator.

An RD blob has 169 tagged fields. There are 40 fields with fixed meanings, then 128
padding fields tagged 0x688F, and then a terminator.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast, get_args

from ..binary_helpers import tag_int, tag_value
from ..codes import Code
from ..errors import CsvReadError
from ..model import (
    ADDRESS_BANKS,
    XY_SLOTS,
    Address,
    AddressError,
    FieldError,
    Instruction,
    Reason,
    check_address,
    normalize_address,
    to_display,
)
from ..operands.address import (
    address_shape,
    digits_value,
    parse_address,
    too_long,
    xy_points,
    xy_room,
)
from ..operands.banks import BIT_BANKS, WORD_IO_BANKS, XY_BANKS
from ..operands.checks import (
    Constants,
    Refusals,
    check_constant,
    check_csv_flag,
    choice_operand,
)
from ..operands.constants import Kind, hex_display
from ..operands.message import Op, Rule, make_refusal, operand, says, wrong_type
from ..operands.unchecked import AllowsRefusals, allowed, holds_refusals, read_in_another_form
from .family import AfInstructionFamilySpec, fixed_cell_params

if TYPE_CHECKING:
    from collections.abc import Collection

    from ..csv.ast import AfCall

#: The cell keyword arguments of a Send or Receive box. The box is three rows tall. In the
#: cell header, +0x09 and +0x0A are both 3.
_CELL_PARAMS: dict = {"visual_rows": 3}

ModbusRtuPort = Literal["cpu2", "cpu3", "slot0_1", "slot0_2", "slot1_1", "slot1_2"]
"""The serial port of a Modbus RTU target."""

ModbusTcpPort = Literal["ethernet", "wlan"]
"""The network port of a Modbus TCP target. ``"ethernet"`` is CPU port 1."""

ModbusRegisterType = Literal["coil", "discrete_input", "holding", "input"]
"""The register type of a Modbus address given in hex. A Receive reads the four types with
function codes 1, 2, 3 and 4, in that order."""

ReceiveFunctionCode = Literal[1, 2, 3, 4]
"""A Modbus function code that a Receive can use."""

SendFunctionCode = Literal[5, 6, 15, 16]
"""A Modbus function code that a Send can use."""

# ---------------------------------------------------------------------------
# Helper dataclasses
# ---------------------------------------------------------------------------


@holds_refusals
@dataclass(frozen=True)
class ModbusRtuTarget(AllowsRefusals):
    """A Modbus RTU device on a serial port, which a Send or Receive talks to."""

    name: str  # human label, not in binary
    com_port: ModbusRtuPort
    #: Slave ID: a number, or the DS register CLICK reads it from (``"DS2420"``).
    device_id: int | str

    def __post_init__(self) -> None:  # ty: ignore[invalid-dataclass]
        with Refusals(self) as check:
            if not isinstance(self.com_port, str) or self.com_port not in _RTU_PORT_MODE:
                check.refuse(
                    "com_port",
                    says(
                        "must be one of {ports}, got {com_port}",
                        ports=", ".join(_RTU_PORT_MODE),
                        com_port=choice_operand(self.com_port),
                    ),
                    _choice_reason(self.com_port),
                    code=Code.INVALID_CHOICE,
                )
            _check_device_id(check, self, 247)


@holds_refusals
@dataclass(frozen=True)
class ModbusTcpTarget(AllowsRefusals):
    """A Modbus TCP device at an IP address and port, which a Send or Receive talks to."""

    name: str  # human label, not in binary
    ip: str
    port: int
    #: Slave ID: a number, or the DS register CLICK reads it from (``"DS2420"``).
    device_id: int | str
    com_port: ModbusTcpPort = "ethernet"

    def __post_init__(self) -> None:  # ty: ignore[invalid-dataclass]
        with Refusals(self) as check:
            if not isinstance(self.com_port, str) or self.com_port not in _TCP_PORT_MODE:
                check.refuse(
                    "com_port",
                    says(
                        "must be one of {ports}, got {com_port}",
                        ports=", ".join(_TCP_PORT_MODE),
                        com_port=choice_operand(self.com_port),
                    ),
                    _choice_reason(self.com_port),
                    code=Code.INVALID_CHOICE,
                )
            _check_device_id(check, self, 255)
            _check_ip(check, self)
            if isinstance(self.port, bool) or not isinstance(self.port, int):
                check.refuse(
                    "port",
                    says("{port} is not an int", port=operand(self.port)),
                    Reason.FORM,
                    code=Code.INVALID_MODBUS_TARGET,
                    then="Pass the port as a whole number, such as port=502.",
                )
            elif not 1 <= self.port <= 65535:
                check.refuse(
                    "port",
                    says(_PORT_RANGE, port=self.port),
                    Reason.RANGE,
                    code=Code.INVALID_MODBUS_TARGET,
                    then=_PORT_THEN,
                )


#: The refusal of a port outside 1-65535, and the sentence that follows it.
_PORT_RANGE = "{port} is outside 1-65535"
_PORT_THEN = "Write a port from 1 to 65535, such as port=502."


def _device_id_then(high: int) -> str:
    """Return the sentence that follows the refusal of a Slave ID, for a target whose
    highest Slave ID is *high*."""
    return f"Write a number from 0 to {high}, or an address from DS1 to DS4500, such as 1."


def _choice_reason(value: object) -> Reason:
    """Return the reason to give when *value* is not one of a field's named values.

    The reason is ``CHOICE`` when *value* is text, and ``FORM`` when it is not text.
    """
    return Reason.CHOICE if isinstance(value, str) else Reason.FORM


def _check_device_id(check: Refusals, target: ModbusRtuTarget | ModbusTcpTarget, high: int) -> None:
    """Refuse a Slave ID that is neither a number from 0 to *high* nor an address from DS1
    to DS4500.

    CLICK's Slave ID box accepts a number or a DS address. It refuses DD, DH, C and the
    other banks.
    """
    device_id = target.device_id
    if isinstance(device_id, str):
        check.normalize("device_id")
        if check.refused("device_id"):
            return
        typed = str(target.device_id)  # check.normalize put it in display form
        shape = address_shape(typed)
        # In display form, a DS number has no leading zero, so DS0 and DS00 are refused here.
        ds = shape is not None and shape[0] == "DS" and not shape[1].startswith("0")
        # Check the length before int(). DS4500 is the last DS address, so more than four
        # digits is out of range, and int() raises for a string of more than 4300 digits.
        if not ds or len(shape[1]) > 4 or int(shape[1]) > 4500:
            check.refuse(
                "device_id",
                says("{typed} is not an address from DS1 to DS4500", typed=Op(typed)),
                _device_id_reason(typed, check.field("device_id")),
                code=Code.INVALID_MODBUS_TARGET,
                then=_device_id_then(high),
            )
    elif isinstance(device_id, bool) or not isinstance(device_id, int):
        check.refuse(
            "device_id",
            says("{device_id} is not a number or a DS address", device_id=operand(device_id)),
            Reason.FORM,
            code=Code.INVALID_MODBUS_TARGET,
            then=_device_id_then(high),
        )
    elif not 0 <= device_id <= high:
        check.refuse(
            "device_id",
            says(_DEVICE_ID_RANGE, high=high, device_id=device_id),
            Reason.RANGE,
            code=Code.INVALID_MODBUS_TARGET,
            then=_device_id_then(high),
        )


#: The refusal of a Slave ID number outside the target's range.
_DEVICE_ID_RANGE = "{device_id} is outside 0-{high}"


def _device_id_reason(device_id: str, field: str) -> Reason:
    """Return the reason that *device_id* is not a DS address from DS1 to DS4500.

    The text may be no address at all, an address in another bank, or a DS address past
    DS4500.
    """
    try:
        address = check_address(device_id, field)
    except AddressError as exc:
        return exc.reason or Reason.FORM
    return Reason.BANK if address.bank != "DS" else Reason.FORM


_IP_RE = re.compile(r"([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})")
#: The parts of an IP that CLICK refuses with OBJ-005: a blank part, -1 and -01.
_IP_REFUSED_PARTS = frozenset({"", "-1", "-01"})


def _check_ip(check: Refusals, target: ModbusTcpTarget) -> None:
    """Refuse an IP address that is not four decimal octets from 0 to 255, or set
    ``target.ip`` to it without leading zeros.

    0.0.0.0 is accepted. An octet may have leading zeros, as in 010.002.003.004. They are
    decimal, not octal. When the address is accepted, this function sets ``target.ip`` to it
    without them, as 10.2.3.4. An octet of zeros is 0.
    """
    ip = target.ip
    m = _IP_RE.fullmatch(ip) if isinstance(ip, str) else None
    rule = says("{ip} is not an IP address", ip=operand(ip))
    then = "Write four numbers from 0 to 255 joined by dots, such as 192.168.0.10."
    if m is None:
        check.refuse(
            "ip", rule, Reason.FORM, _ip_click_id(ip), code=Code.INVALID_MODBUS_TARGET, then=then
        )
    elif any(int(octet) > 255 for octet in m.groups()):
        check.refuse("ip", rule, Reason.RANGE, code=Code.INVALID_MODBUS_TARGET, then=then)
    else:
        object.__setattr__(target, "ip", ".".join(str(int(octet)) for octet in m.groups()))


def _ip_click_id(ip: object) -> str | None:
    """Return CLICK's id for the refusal of *ip*, or None if CLICK's id for it is not known.

    The id is OBJ-005 for a blank IP. It is also OBJ-005 for four parts where each part is
    an octet from 0 to 255, a blank, -1 or -01, and at least one part is not an octet, as
    in 1..3.4, 1.2.3.-1 and -1.2..4. Any other negative part, such as -0, -2 or -001, has
    no id.
    """
    if not isinstance(ip, str):
        return None
    if ip == "":
        return "OBJ-005"
    parts = ip.split(".")
    if len(parts) != 4:
        return None
    refused = sum(part in _IP_REFUSED_PARTS for part in parts)
    octets = sum(
        part.isascii() and part.isdigit() and len(part) <= 3 and int(part) <= 255 for part in parts
    )
    return "OBJ-005" if refused and refused + octets == 4 else None


#: The most digits that int() converts. A decimal address with more digits is refused as
#: not a number.
_MAX_INT_DIGITS = 4300


@holds_refusals
@dataclass(frozen=True)
class ModbusAddress(AllowsRefusals):
    """A remote address given as a MODBUS 984 number or in hex, not as a CLICK address."""

    address: str  # "400001" or "0h"
    register_type: ModbusRegisterType | None = None  # only for a hex address

    def __post_init__(self) -> None:  # ty: ignore[invalid-dataclass]
        with Refusals(self) as check:
            if self.register_type is not None and self.register_type not in REGISTER_TYPES:
                check.refuse(
                    "register_type",
                    says(
                        "must be one of {types}, got {register_type}",
                        types=", ".join(REGISTER_TYPES),
                        register_type=operand(self.register_type),
                    ),
                    _choice_reason(self.register_type),
                    code=Code.INVALID_CHOICE,
                )
            if not isinstance(self.address, str):
                check.refuse(
                    "address",
                    wrong_type(self.address, "text"),
                    Reason.KIND,
                    code=Code.NOT_AN_ADDRESS,
                    then="Pass the MODBUS address as a str.",
                )
            elif self.address.endswith(("h", "H")):
                if check("address", check_constant, _REMOTE_HEX) is not None:
                    # The range check reads the value, not the number of digits. So leading
                    # zeros do not take it out of range, even past four digits. CLICK stores
                    # the digits in uppercase, without leading zeros, and with a lowercase h
                    # (0FFFEh -> FFFEh, 0H -> 0h).
                    display = check.run(
                        to_display,
                        self.address,
                        hex_display(self.address[:-1]),
                        check.field("address"),
                    )
                    if display is not None:
                        object.__setattr__(self, "address", display)
            elif (
                not self.address.isascii()
                or not self.address.isdigit()
                or len(self.address) > _MAX_INT_DIGITS
            ):
                check.refuse(
                    "address",
                    says(
                        "{address} is not a MODBUS 984 number or hex address",
                        address=Op(self.address),
                    ),
                    Reason.KIND,
                    code=Code.NOT_AN_ADDRESS,
                    then="Write a MODBUS 984 number, such as 400001, or hex from 0h to FFFEh.",
                )

    @property
    def is_hex(self) -> bool:
        return self.address.endswith("h")


#: Register types of a hex remote address, in function-code order (Receive FC01-FC04).
REGISTER_TYPES: tuple[ModbusRegisterType, ...] = get_args(ModbusRegisterType)
#: A hex remote address: 0h to FFFEh.
_REMOTE_HEX = Constants(frozenset({Kind.HEX}), hex_high=0xFFFE, range_id=None)


# ---------------------------------------------------------------------------
# Protocol mode tables
# ---------------------------------------------------------------------------

#: Protocol mode (0x220C) per port.
_RTU_PORT_MODE: dict[ModbusRtuPort, str] = {
    "cpu2": "0",
    "cpu3": "1",
    "slot0_1": "4",
    "slot0_2": "5",
    "slot1_1": "6",
    "slot1_2": "7",
}
_TCP_PORT_MODE: dict[ModbusTcpPort, str] = {
    "ethernet": "2",
    "wlan": "3",
}

_RTU_PORT_MODE_INV: dict[str, ModbusRtuPort] = {v: k for k, v in _RTU_PORT_MODE.items()}
_TCP_PORT_MODE_INV: dict[str, ModbusTcpPort] = {v: k for k, v in _TCP_PORT_MODE.items()}

# ---------------------------------------------------------------------------
# Function codes
# ---------------------------------------------------------------------------

#: The fc_subtype (0x2211) of each Modbus function code. It is the index of the code in
#: the Function Code box of the Send or Receive dialog.
_RD_FC_SUBTYPE: dict[int, str] = {1: "0", 2: "1", 3: "2", 4: "3"}
_SD_FC_SUBTYPE: dict[int, str] = {5: "0", 6: "1", 15: "2", 16: "3"}
_RD_FC_FROM_SUBTYPE: dict[str, int] = {v: k for k, v in _RD_FC_SUBTYPE.items()}
_SD_FC_FROM_SUBTYPE: dict[str, int] = {v: k for k, v in _SD_FC_SUBTYPE.items()}

#: Register types of a hex remote address, by Receive function code.
_RD_FC_REGISTER_TYPE: dict[int, ModbusRegisterType] = dict(
    zip(get_args(ReceiveFunctionCode), REGISTER_TYPES, strict=True)
)
_RD_REGISTER_TYPE_FC: dict[str, int] = {v: k for k, v in _RD_FC_REGISTER_TYPE.items()}


def _check_function_code(check: Refusals, function_code: object, allowed: tuple[int, ...]) -> None:
    if function_code is None:
        return
    if type(function_code) is not int or function_code not in allowed:
        listed = ", ".join(str(fc) for fc in allowed)
        reason = Reason.FORM if type(function_code) is not int else Reason.CHOICE
        check.refuse(
            "function_code",
            says(
                "{function_code} is not one of {listed}",
                function_code=operand(function_code),
                listed=listed,
            ),  # fmt: skip
            reason,
            code=Code.INVALID_CHOICE,
        )


# ---------------------------------------------------------------------------
# Address helpers
# ---------------------------------------------------------------------------


def _xy_points_left(number: int) -> int:
    """X/Y points from ``number`` through the last slot (X816), counted along the slots."""
    return xy_points(number, XY_SLOTS[-1][1])


def _remote_xy_room(local: Address, remote_addr: Address) -> int:
    """Return how many points a count from the X or Y point ``local`` can cover when the
    remote start is the CLICK address ``remote_addr``.

    For a remote X or Y start, the higher of the two start numbers decides the slot run
    (:func:`~laddercodec.operands.address.xy_room`). For a remote start in another bank,
    such as C, the room is the smaller of the room left in that bank and the slot run from
    ``local``. A Send with a CLICK remote address uses this room for an X/Y source. A
    Receive into Y uses it too, except from a remote C start past Y036
    (:func:`_receive_y_room`).
    """
    if remote_addr.bank in XY_BANKS:
        return xy_room(max(local.number, remote_addr.number))
    remote_room = ADDRESS_BANKS[remote_addr.bank][1] + 1 - remote_addr.number
    return min(remote_room, xy_room(local.number))


def _receive_y_room(
    local: Address, remote: str | ModbusAddress, remote_addr: Address | None
) -> int:
    """Return how many points a Receive can count into Y from the Y point ``local``.

    The limit is the room in the slot run from ``local``
    (:func:`~laddercodec.operands.address.xy_room`), for
    every kind of remote address. The remote start can lower it. For a remote X or Y
    start, the run is taken from the higher of the two start numbers. A remote C, T, CT or
    SC start caps the count at the room left in that bank. A MODBUS 984 start up to 65535
    caps it at 65536 minus the start.

    From Y101 on, CLICK's two range tests both skip the slot rule for a remote C start.
    There, only the room left in C and the Y points that exist through Y816 limit the
    count.
    """
    if remote_addr is not None:
        if remote_addr.bank == "C" and local.number > 36:
            remote_room = ADDRESS_BANKS["C"][1] + 1 - remote_addr.number
            return min(remote_room, _xy_points_left(local.number))
        return _remote_xy_room(local, remote_addr)
    room = xy_room(local.number)
    if isinstance(remote, ModbusAddress) and not remote.is_hex and int(remote.address) <= 0xFFFF:
        room = min(room, 0x10000 - int(remote.address))
    return room


def _check_c_remote_room(check: Refusals, quantity: int, remote_addr: Address) -> None:
    """Refuse a count between local C bits and a CLICK remote address that does not fit
    on the remote side.

    For a remote X or Y start, the room is the slot run from that start
    (:func:`~laddercodec.operands.address.xy_room`). For a remote C, T, CT or SC start, it
    is the room left in that bank. :func:`_check_quantity` checks the room left in C on the
    local side.
    """
    bank, number = remote_addr.bank, remote_addr.number
    if bank in XY_BANKS:
        room = xy_room(number)
        if quantity > room:
            check.refuse(
                "quantity",
                says(
                    "{quantity} from remote {remote} is outside 1-{room} (X/Y points count "
                    "by slot: {bank}001-{bank}016 with {bank}021-{bank}036, then "
                    "{bank}101-{bank}116 ...)",
                    quantity=quantity,
                    remote=Op(remote_addr.display, quoted=False),
                    room=room,
                    bank=bank,
                ),
                Reason.RANGE,
                _RANGE_ID,
                code=Code.COUNT_OUT_OF_RANGE,
            )
        return
    last_number = ADDRESS_BANKS[bank][1]
    left = last_number - number + 1
    if quantity > left:
        check.refuse(
            "quantity",
            says(
                "{quantity} from remote {remote} runs past {last} ({left} left)",
                quantity=quantity,
                remote=Op(remote_addr.display, quoted=False),
                last=Op(f"{bank}{last_number}", quoted=False),
                left=left,
            ),
            Reason.RANGE,
            _RANGE_ID,
            code=Code.COUNT_OUT_OF_RANGE,
        )


def _xy_nth(prefix: str, number: int, steps: int, cls: str) -> int:
    """Return the X/Y point that is ``steps`` points after ``number``.

    Count only the points in the slots, and skip the numbers between slots. Raise
    ``FieldError`` if the count runs past the last slot.
    """
    quantity = steps + 1
    for lo, hi in XY_SLOTS:
        if hi < number:
            continue
        first = max(lo, number)
        if first + steps <= hi:
            return first + steps
        steps -= hi - first + 1
    raise make_refusal(
        FieldError,
        f"{cls}.quantity",
        says(
            "{quantity} addresses from {start} run past {last}, the last {prefix} address",
            quantity=quantity,
            start=Op(Address(prefix, number).display, quoted=False),
            last=Op(Address(prefix, XY_SLOTS[-1][1]).display, quoted=False),
            prefix=prefix,
        ),
        field=f"{cls}.quantity",
        reason=Reason.RANGE,
        code=Code.COUNT_OUT_OF_RANGE,
        then="Lower the count, or start at a lower address.",
    )


def _addr_end(start: str, quantity: int, cls: str) -> str:
    """Return the last address of ``quantity`` elements from ``start``.

    Five elements from DS1 end at DS5, and 17 from X001 end at X021.
    """
    shape = address_shape(start)
    if shape is None:
        return start
    if too_long(shape[1]):
        return start  # not an address, so it has no end
    prefix, number = shape[0], digits_value(shape[1])
    if prefix in XY_BANKS:
        return Address(prefix, _xy_nth(prefix, number, quantity - 1, cls)).display
    return Address(prefix, number + quantity - 1).display


def _span(start: Address, count: int) -> str:
    """Return ``count`` elements of a Send's source from ``start`` as the CSV token writes
    them: a range such as ``DS1..DS4``, or the address alone for one element."""
    if count <= 1:
        return start.display
    return f"{start.display}..{_addr_end(start.display, count, 'Send')}"


def _txt_span(start: int, count: int) -> str:
    """Return ``count`` TXT characters from ``TXT{start}`` as :func:`_span` writes them. If
    they would run past TXT1000, the range starts lower and ends at TXT1000."""
    last = ADDRESS_BANKS["TXT"][1]
    return _span(Address("TXT", max(1, min(start, last - count + 1))), count)


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
# A refusal of a bank that a field does not accept carries CLICK's id OBJ-004. A refusal
# of a count past its cap or room, or of a hex start past FFFDh, carries OBJ-010.
# ---------------------------------------------------------------------------

_BANK_ID = "OBJ-004"
_RANGE_ID = "OBJ-010"

#: The remote banks that a Send with a CLICK address accepts for each function code. SD is in
#: the register sets only so that a number outside SD is refused as out of range. A Send
#: refuses every SD remote address after that check.
_SEND_REMOTE_BITS = frozenset({"Y", "C"})
_SEND_REMOTE_REGS_FC06 = frozenset({"DS", "DH", "SD", "TD", "YD", "TXT"})
_SEND_REMOTE_REGS_FC16 = frozenset({"CTD", "DS", "DD", "DH", "DF", "SD", "TD", "TXT"})
#: The local banks that a Send accepts for each function code. CLICK's bank masks are 0x3f
#: for bits, 0xdd40 for FC06 and 0xf3c0 for FC16.
_SEND_LOCAL_REGS_FC06 = frozenset({"DS", "DH", "XD", "YD", "TD", "SD", "TXT"})
_SEND_LOCAL_REGS_FC16 = frozenset({"CTD", "DS", "DD", "DH", "DF", "TD", "SD", "TXT"})
#: Banks that only FC16 can write. A Send of one element uses FC16 if either side is in one
#: of these banks.
_FC16_ONLY = frozenset({"CTD", "DD", "DF"})
#: Local data types whose hex remote start stops at FFFDh (int32, float, text).
_SEND_HEX_FFFD = frozenset({"DD", "CTD", "DF", "TXT"})
#: A Send TXT count is in characters, two to a register.
_TXT_SEND_MAX = 246
#: CLICK's id for a TXT count that is odd.
_ODD_ID = "OBJ-029"

#: The register banks of each data type: int16, int32, float, hex and text. With a CLICK
#: remote address, a Send or Receive pairs a local bank only with remote banks of its own
#: data type.
_SAME_TYPE: dict[str, frozenset[str]] = {
    bank: group
    for group in (
        frozenset({"DS", "TD", "SD"}),
        frozenset({"DD", "CTD"}),
        frozenset({"DF"}),
        frozenset({"DH", "XD", "YD"}),
        frozenset({"TXT"}),
    )
    for bank in group
}

#: The remote banks that a Receive with a CLICK address reads into each local register bank:
#:
#: - DS reads DS, TD and SD.
#: - DD reads DD and CTD.
#: - DF reads DF.
#: - DH reads DH, XD and YD. YD reads the same three banks.
#: - TXT reads TXT.
#:
#: CLICK refuses any other pair with OBJ-004. A Receive into YD, and a Receive from XD or YD
#: into DH, has a count of 1.
_RECEIVE_REMOTE_FOR_DEST: dict[str, frozenset[str]] = {
    dest: _SAME_TYPE[dest] for dest in ("DS", "DD", "DF", "DH", "YD", "TXT")
}
_RECEIVE_REMOTE_REGS = frozenset().union(*_RECEIVE_REMOTE_FOR_DEST.values())
#: The local banks that a Receive accepts. FC01 and FC02 read a remote X, Y, C, T, CT or SC
#: bit into Y or C. FC03 and FC04 read a remote register into DS, DD, DF, DH, YD or TXT.
_RECEIVE_LOCAL_BITS = frozenset({"Y", "C"})
_RECEIVE_LOCAL_REGS = frozenset(_RECEIVE_REMOTE_FOR_DEST)

_STATUS_BITS = frozenset({"C"})
_EXCEPTION_BANKS = frozenset({"DS", "DD"})

#: Local banks whose elements are two registers wide, so the count cap halves.
_WIDE_BANKS = frozenset({"DD", "DF", "CTD"})

#: Count caps: (bits, registers, 32-bit registers).
_SEND_CAPS = (1968, 123, 61)
_RECEIVE_CAPS = (2000, 125, 62)
#: A Receive TXT count is in characters, two to a register.
_TXT_RECEIVE_MAX = 250


def _txt_count_rule(quantity: int) -> Rule:
    """Return the rule that a Receive TXT count of *quantity* breaks."""
    return says(
        "{quantity} TXT characters must be an even count of 2 to {high}",
        quantity=quantity,
        high=_TXT_RECEIVE_MAX,
    )


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


def _check_target(check: Refusals, target: ModbusRtuTarget | ModbusTcpTarget, rtu_low: int) -> None:
    """Refuse a blank target, and a numeric Slave ID below *rtu_low* on an RTU target.

    The target is ``""`` when it is blank, as in the CSV token ``send(target=,...)``.

    A Receive passes 1 and a Send passes 0. A DS address always passes. The target checks
    the upper limits, 247 for RTU and 255 for TCP, when it is built.

    The target runs its own checks when it is built, and their refusals name the target's
    field, such as ``ModbusTcpTarget.port``. The refusal of a Slave ID below 1 on a Receive
    names ``Receive.target``."""
    if target == "":
        check.refuse(
            "target", says("is blank", "it needs a value"), Reason.MISSING, code=Code.BLANK_FIELD
        )
        return
    if not isinstance(target, (ModbusRtuTarget, ModbusTcpTarget)):
        check.refuse(
            "target",
            wrong_type(target, "a Modbus target"),
            Reason.FORM,
            code=Code.INVALID_MODBUS_TARGET,
            then="Pass a ModbusTcpTarget or ModbusRtuTarget.",
        )
        return
    device_id = target.device_id
    if isinstance(device_id, str):
        return
    if isinstance(target, ModbusRtuTarget) and device_id < rtu_low:
        check.refuse(
            "target",
            says(
                "its device_id {device_id} is outside {low}-247 for RTU",
                device_id=device_id,
                low=rtu_low,
            ),
            Reason.RANGE,
            code=Code.INVALID_MODBUS_TARGET,
            then=f"Give the target a device_id from {rtu_low} to 247, such as device_id=1.",
        )


def _check_remote_type(check: Refusals, inst: Send | Receive) -> bool:
    """Refuse a ``remote_start`` that is neither text nor a ``ModbusAddress``.  Return
    whether it is either one.

    The checks of the remote start read it as text or as a ``ModbusAddress``, so they run
    only when this returns True."""
    if isinstance(inst.remote_start, (str, ModbusAddress)):
        return True
    check.refuse(
        "remote_start",
        wrong_type(inst.remote_start, "text or a ModbusAddress"),
        Reason.ADDRESS,
        code=Code.NOT_AN_ADDRESS,
        then="Pass the address as a str, or a ModbusAddress.",
    )
    return False


def _normalize_operands(check: Refusals, inst: Send | Receive, names: tuple[str, ...]) -> None:
    """Put ``remote_start`` and each field in *names* in display form if it is a CLICK
    address. Leave a ModbusAddress as written."""
    check.normalize(*(n for n in ("remote_start", *names) if isinstance(getattr(inst, n), str)))


def _check_status(
    check: Refusals, inst: Send | Receive, name: str, banks: frozenset[str]
) -> Address | None:
    value = getattr(inst, name)
    if value:
        label = f"{type(inst).__name__} {name}"
        return check(name, check_address, banks, label=label, bank_id=_BANK_ID)
    return None


def _check_status_bits(
    check: Refusals,
    inst: Send | Receive,
    names: tuple[str, str, str],
    click_id: str | None = None,
) -> None:
    """Refuse a status field that is not a C bit, and a C bit that two status fields use."""
    seen: dict[tuple[str, int], str] = {}
    for name in names:
        found = _check_status(check, inst, name, _STATUS_BITS)
        if found is None:
            continue
        key = (found.bank, found.number)
        if key in seen:
            check.refuse(
                (name, seen[key]),
                says(
                    "{value} is already the {other} bit",
                    value=Op(getattr(inst, name), quoted=False),
                    other=seen[key],
                ),
                Reason.CONFLICT,
                click_id,
                code=Code.DUPLICATE_ADDRESS,
                then=f"Give {name} a C bit of its own, such as {_free_c_bit(inst, names)}.",
            )
        else:
            seen[key] = name


def _free_c_bit(inst: Send | Receive, names: tuple[str, ...]) -> str:
    """Return the first C bit that none of the status fields *names* of *inst* holds, such
    as C2."""
    values = [getattr(inst, name) for name in names]
    held = [parse_address(value) for value in values if isinstance(value, str)]
    numbers = {a.number for a in held if a is not None and a.bank == "C"}
    number = next(n for n in range(1, len(names) + 2) if n not in numbers)
    return Address("C", number, False).display


def _check_984(check: Refusals, address: str, kinds: dict[str, tuple[int, int]]) -> str | None:
    """Return the kind, a key of ``kinds``, whose MODBUS 984 range holds *address*.

    If no range holds it, refuse the address and return None.
    """
    n = int(address)
    for kind, (low, high) in kinds.items():
        if low <= n <= high:
            return kind
    ranges = ", ".join(f"{low}-{high}" for low, high in kinds.values())
    check.refuse(
        "remote_start",
        says(
            "{address} is outside the MODBUS 984 ranges {ranges}",
            address=Op(address),
            ranges=ranges,
        ),
        Reason.RANGE,
        code=Code.REMOTE_ADDRESS_OUT_OF_RANGE,
    )
    return None


def _check_int_quantity(check: Refusals, quantity: object) -> None:
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        check.refuse(
            "quantity",
            says("{quantity} is not an integer", quantity=operand(quantity)),
            Reason.FORM,
            code=Code.CONSTANT_KIND_NOT_ALLOWED,
            then="Pass the quantity as a whole number, such as quantity=1.",
        )


def _check_quantity(
    check: Refusals,
    quantity: int,
    local: Address,
    caps: tuple[int, int, int],
    bit: bool,
    xy_room: int | None = None,
    unit: str | None = None,
) -> None:
    """Refuse a count above the cap for its kind, then a count that runs past the room left
    from the local start.

    ``xy_room`` is the room from an X or Y start, which depends on the remote address. If
    it is None, the room is the X/Y points left through the last slot. A Send to a MODBUS
    984 or hex address passes None. ``unit`` names what the cap counts when it does not
    count registers. A Receive TXT count is in characters.
    """
    bits, regs, wide = caps
    if bit:
        high, kind = bits, "bits"
    elif local.bank in _WIDE_BANKS:
        high, kind = wide, f"{local.bank} registers"
    else:
        high, kind = regs, unit or "registers"
    if not 1 <= quantity <= high:
        check.refuse(
            "quantity",
            says("{quantity} is outside 1-{high} {kind}", quantity=quantity, high=high, kind=kind),
            Reason.RANGE,
            _RANGE_ID,
            code=Code.COUNT_OUT_OF_RANGE,
        )
        return
    if local.bank in XY_BANKS:
        room = _xy_points_left(local.number) if xy_room is None else xy_room
        if quantity > room:
            check.refuse(
                "quantity",
                says(
                    "{quantity} from {local} is outside 1-{room} (X/Y points count by "
                    "slot: {bank}001-{bank}016 with {bank}021-{bank}036, then "
                    "{bank}101-{bank}116 ...)",
                    quantity=quantity,
                    local=Op(local.display, quoted=False),
                    room=room,
                    bank=local.bank,
                ),
                Reason.RANGE,
                _RANGE_ID,
                code=Code.COUNT_OUT_OF_RANGE,
            )
        return
    if local.bank in WORD_IO_BANKS:
        return  # XD and YD take one element, and another check refuses a larger count
    last_number = ADDRESS_BANKS[local.bank][1]
    left = last_number - local.number + 1
    if quantity > left:
        check.refuse(
            "quantity",
            says(
                "{quantity} from {local} runs past {last} ({left} left)",
                quantity=quantity,
                local=Op(local.display, quoted=False),
                last=Op(f"{local.bank}{last_number}", quoted=False),
                left=left,
            ),
            Reason.RANGE,
            _RANGE_ID,
            code=Code.COUNT_OUT_OF_RANGE,
        )


def _check_quantity_bounds(
    check: Refusals, quantity: int, caps: tuple[int, int, int], bit: bool | None
) -> None:
    """Refuse a count that no start could take. That is a count below 1, or above the
    largest cap of the kinds that the remote and local fields still allow.

    The callers use it when the remote or local field is refused."""
    high = caps[1] if bit is False else caps[0]
    if not 1 <= quantity <= high:
        check.refuse(
            "quantity",
            says("{quantity} is outside 1-{high}", quantity=quantity, high=high),
            Reason.RANGE,
            _RANGE_ID,
            code=Code.COUNT_OUT_OF_RANGE,
        )


def _or_list(names: list[str]) -> str:
    """Return ``names`` joined as a list that ends with "or": ``DS, TD or SD``."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} or {names[-1]}"


def _slave_banks(source_bank: str, fc: int | None) -> list[str]:
    """Return the CLICK slave banks that a Send from ``source_bank`` writes with ``fc``, in
    CLICK's bank order. With no ``fc``, return the banks of either FC06 or FC16."""
    if fc == 6:
        remote_banks = _SEND_REMOTE_REGS_FC06
    elif fc == 16:
        remote_banks = _SEND_REMOTE_REGS_FC16
    else:
        remote_banks = _SEND_REMOTE_REGS_FC06 | _SEND_REMOTE_REGS_FC16
    same = _SAME_TYPE.get(source_bank, frozenset()) & remote_banks
    return [bank for bank in ADDRESS_BANKS if bank in same and bank != "SD"]


def _send_fc(send: Send) -> int | None:
    """Return the Send's function code if it is one that a Send takes, or None."""
    fc = send.function_code
    return fc if isinstance(fc, int) and fc in (5, 6, 15, 16) else None


def _slave_example(send: Send) -> Collection[str] | None:
    """Return the CLICK slave banks that suit the Send's source and function code, for the
    address that a refusal of ``remote_start`` suggests. Return None if no bank is known
    to suit them."""
    fc = _send_fc(send)
    source = parse_address(send.source) if isinstance(send.source, str) else None
    if fc in (5, 15) or (fc is None and source is not None and source.bank in BIT_BANKS):
        return _SEND_REMOTE_BITS
    if source is not None and source.bank not in BIT_BANKS:
        return _slave_banks(source.bank, fc) or None
    if fc is None:
        return None
    return (_SEND_REMOTE_REGS_FC06 if fc == 6 else _SEND_REMOTE_REGS_FC16) - {"SD"}


def _lowest(bank: str) -> str:
    """Return the lowest address of ``bank`` in display form, such as ``DS1``."""
    return Address(bank, ADDRESS_BANKS[bank][0]).display


def _check_send_pair(check: Refusals, remote_addr: Address, local: Address, fc: int | None) -> None:
    """Refuse a CLICK slave address whose bank is not of the source's data type.

    A DS, TD or SD source writes DS or TD. A DH, XD or YD source writes DH or YD. A DD or
    CTD source writes DD or CTD. A DF source writes DF, and a TXT source writes TXT. FC16
    writes no YD.
    """
    if remote_addr.bank in _SAME_TYPE[local.bank]:
        return
    takes = _slave_banks(local.bank, fc)
    if not takes:
        return  # the source check refuses a bank that this function code can't send
    example = _lowest(takes[0])
    check.refuse(
        ("remote_start", "source"),
        says(
            "{remote} can't take a source in {bank}",
            remote=Op(remote_addr.display),
            bank=local.bank,
        ),
        Reason.CONFLICT,
        _BANK_ID,
        code=Code.BANK_NOT_ALLOWED,
        then=f'Pick a slave address in {_or_list(takes)}, such as remote_start="{example}".',
    )


def _send_hex_room(remote: str | ModbusAddress, local: Address) -> int | None:
    """Return the number of elements that a Send from ``local`` may write from a hex
    ``remote`` start, or None if the start is not hex or the source refuses it.

    Each element counts as one address, and a TXT character counts as one element. The
    count may run to FFFDh from a DD, DF or CTD source, and to FFFEh from any other register
    source. A DS source from FFFEh writes 1 element, and a DD source from FFF0h writes 14.
    From FFFCh the room is 3 TXT characters, so a TXT source sends at most 2."""
    if not isinstance(remote, ModbusAddress) or not remote.is_hex or local.bank not in _SAME_TYPE:
        return None
    start = int(remote.address[:-1], 16)
    if local.bank in _SEND_HEX_FFFD and start > 0xFFFD:
        return None
    last = 0xFFFD if local.bank in _WIDE_BANKS else 0xFFFE
    return last - start + 1


def _check_send_txt_count(
    check: Refusals, quantity: int, local: Address, hex_room: int | None
) -> None:
    """Refuse a TXT count that is not an even number of characters from 2 to 246, or that
    runs past TXT1000.

    After a hex start, ``hex_room`` lowers the top of the range. A count outside the range
    gets the range id, even when it is also odd."""
    last = ADDRESS_BANKS["TXT"][1]
    left = last - local.number + 1
    high = _TXT_SEND_MAX if hex_room is None else max(2, min(_TXT_SEND_MAX, hex_room))
    if quantity > left:
        if left >= 2:
            fewer = _txt_span(local.number, min(left - left % 2, high - high % 2))
            then = f"Send fewer characters, such as {fewer}."
        else:
            count = quantity if quantity <= high and quantity % 2 == 0 else 2
            then = f"Start at a lower TXT address, such as {_txt_span(last, count)}."
        check.refuse(
            "quantity",
            says(
                "{quantity} characters from {local} run past {last}",
                quantity=quantity,
                local=Op(local.display, quoted=False),
                last=Op(f"TXT{last}", quoted=False),
            ),
            Reason.RANGE,
            _RANGE_ID,
            code=Code.COUNT_OUT_OF_RANGE,
            then=then,
        )
    elif not 2 <= quantity <= high:
        check.refuse(
            "quantity",
            says("{quantity} is outside 2-{high} TXT characters", quantity=quantity, high=high),
            Reason.RANGE,
            _RANGE_ID,
            code=Code.COUNT_OUT_OF_RANGE,
            then="Send an even count of characters, such as "
            f"{_txt_span(local.number, 2 if quantity < 2 else high - high % 2)}.",
        )
    elif quantity % 2:
        even = quantity + 1 if quantity < min(left, high) else quantity - 1
        check.refuse(
            "quantity",
            says("{quantity} is an odd count of TXT characters", quantity=quantity),
            Reason.RANGE,
            _ODD_ID,
            code=Code.COUNT_OUT_OF_RANGE,
            then=f"Send an even count of characters, such as {_txt_span(local.number, even)}.",
        )


def _check_send_hex_room(
    check: Refusals, remote: ModbusAddress, local: Address, quantity: int | None
) -> None:
    """Refuse a hex remote start past FFFDh for a DD, DF, CTD or TXT source, and a count
    of registers that runs past the room that :func:`_send_hex_room` returns.

    ``quantity`` is None when the count is refused. The TXT count check refuses a TXT count
    that runs past the room. The count that the message suggests stays inside the Send's
    count cap."""
    start = int(remote.address[:-1], 16)
    if local.bank in _SEND_HEX_FFFD and start > 0xFFFD:
        check.refuse(
            ("remote_start", "source"),
            says(
                "{address} is outside 0h-FFFDh for a {bank} source",
                address=Op(remote.address),
                bank=local.bank,
            ),
            Reason.CONFLICT,
            _RANGE_ID,
            code=Code.REMOTE_ADDRESS_OUT_OF_RANGE,
        )
        return
    room = _send_hex_room(remote, local)
    if room is None or local.bank == "TXT" or quantity is None or quantity <= room:
        return
    cap = _SEND_CAPS[2] if local.bank in _WIDE_BANKS else _SEND_CAPS[1]
    check.refuse(
        "quantity",
        says(
            "{quantity} from hex {address} is outside 1-{room}",
            quantity=quantity,
            address=Op(remote.address),
            room=room,
        ),
        Reason.RANGE,
        _RANGE_ID,
        code=Code.COUNT_OUT_OF_RANGE,
        then=f"Send one element, such as {local.display}."
        if min(room, cap) == 1
        else f"Lower the count, such as {_span(local, min(room, cap))}.",
    )


def _check_send_word_swap(
    check: Refusals, send: Send, fc: int, bit: bool, local: Address, counted: bool
) -> None:
    """Refuse Word Swap where a Send does not offer it.

    A Send offers Word Swap only with FC16. It offers it for a DD, DF or CTD source, and
    for a DS, DH, TD or SD source with a count of 2 or more. If ``word_swap`` is not a
    flag, it is refused as not a flag instead."""
    if bit or fc != 16:
        why, partner = f"with FC{fc:02d}", "function_code"
    elif local.bank == "TXT":
        why, partner = "for a TXT source", "source"
    elif local.bank not in _WIDE_BANKS and counted and send.quantity == 1:
        why, partner = f"for one {local.bank} register", "quantity"
    else:
        return
    if not _is_flag(send.word_swap):
        check.flag("word_swap")
        return
    check.refuse(
        ("word_swap", partner),
        says("Word Swap is not offered {why}", why=why),
        Reason.CONFLICT,
        code=Code.OPTION_NOT_OFFERED,
        then="Drop word_swap=True.",
    )


def _send_default_fc(send: Send, bit: bool, local: Address, remote_bank: str | None) -> int:
    """Return the function code that a Send uses by default.

    Bits use FC05 for one element and FC15 for more. Registers use FC06 for one element
    and FC16 for more. One register uses FC16 if either side is in DD, DF or CTD, which
    only FC16 can write."""
    single = send.quantity == 1
    if bit:
        return 5 if single else 15
    if single and local.bank not in _FC16_ONLY and remote_bank not in _FC16_ONLY:
        return 6
    return 16


def _validate_send(send: Send) -> tuple[int, int]:
    """Check every field of *send*, and return the function code that the Send is written
    with and the default function code.

    If the refusals of *send* were allowed by code (:func:`allowed`), return the two
    function codes without raising the refusals. A refusal that leaves either code unknown
    still raises."""
    if allowed(send):
        found = _check_send(send, Refusals(send))
        if found is not None:
            return found
    with Refusals(send) as check:
        found = _check_send(send, check)
    assert found is not None  # a refusal ended the block
    return found


def _odd_txt_start(start: int, quantity: int | None) -> int:
    """Return an odd TXT address below the even ``start`` from which ``quantity`` characters
    end by TXT1000. With no ``quantity``, return the address just below ``start``."""
    odd = start - 1
    if quantity is not None and quantity > 0:
        odd = min(odd, 1001 - quantity)
    odd -= 1 - odd % 2
    return max(odd, 1)


def _odd_txt_span(start: int, quantity: int | None) -> str:
    """Return the TXT characters from :func:`_odd_txt_start` as :func:`_span` writes them.
    The range holds ``quantity`` characters if that is an even count, and is the address
    alone otherwise."""
    odd = _odd_txt_start(start, quantity)
    even = quantity is not None and quantity > 0 and quantity % 2 == 0
    return _txt_span(odd, quantity if even and quantity is not None else 1)


def _check_send(send: Send, check: Refusals) -> tuple[int, int] | None:
    """Check every field of *send*, and record each refusal in *check*.

    Skip a check that depends on a field that is already refused. Return the function code
    that the Send is written with and the default function code. Return None if a refusal
    leaves either code unknown."""
    who = "Send"
    _check_target(check, send.target, 0)
    _check_function_code(check, send.function_code, tuple(_SD_FC_SUBTYPE))
    remote, quantity = send.remote_start, send.quantity
    _check_int_quantity(check, quantity)
    if not _check_remote_type(check, send):
        return None
    counted = not check.refused("quantity")
    remote_addr: Address | None = None
    bit: bool | None = None  # None: the remote_start is refused, so its kind is not known
    if isinstance(remote, str):
        remote_addr = check(
            "remote_start",
            check_address,
            _SEND_REMOTE_BITS | _SEND_REMOTE_REGS_FC06 | _SEND_REMOTE_REGS_FC16,
            label=f"{who} remote_start",
            bank_id=_BANK_ID,
            example=_slave_example(send),
        )
        if remote_addr is not None:
            bit = remote_addr.bank in _SEND_REMOTE_BITS
            if remote_addr.bank == "SD":
                source = parse_address(send.source) if isinstance(send.source, str) else None
                banks = _slave_banks(source.bank if source is not None else "DS", _send_fc(send))
                check.refuse(
                    "remote_start",
                    says(
                        "{remote} is in SD, which a Send can't write",
                        remote=Op(remote_addr.display),
                    ),  # fmt: skip
                    Reason.NOT_WRITABLE,
                    _BANK_ID,
                    code=Code.NOT_WRITABLE,
                    then="Pick a slave address in another bank, such as "
                    f'remote_start="{_lowest(banks[0] if banks else "DS")}".',
                )
    elif remote.is_hex:
        register_type = remote.register_type or "holding"
        if register_type not in ("coil", "holding"):
            check.refuse(
                "remote_start",
                says(
                    "register_type {register_type} cannot be written",
                    "a Send takes coil or holding",
                    register_type=Op(register_type),
                ),
                Reason.CHOICE,
                code=Code.NOT_WRITABLE,
            )
        else:
            bit = register_type == "coil"
    else:
        kind = _check_984(check, remote.address, _SEND_984_KINDS)
        if kind is not None:
            bit = kind == "coil"

    if bit is None:
        banks = BIT_BANKS | _SEND_LOCAL_REGS_FC06 | _SEND_LOCAL_REGS_FC16
    elif bit:
        banks = BIT_BANKS
    else:
        banks = _SEND_LOCAL_REGS_FC06 | _SEND_LOCAL_REGS_FC16
    local = check("source", check_address, banks, label=f"{who} source", bank_id=_BANK_ID)
    even_txt = False
    if local is not None and local.bank == "TXT" and local.number % 2 == 0:
        # A TXT source starts at an odd address. An even start is refused before the count
        # is checked.
        even_txt = True
        check.refuse(
            "source",
            says(
                "{source} is an even TXT address",
                "a Send of TXT starts at an odd address",
                source=Op(local.display, quoted=False),
            ),
            Reason.RANGE,
            "OBJ-028",
            code=Code.TXT_START_NOT_ODD,
            then="Start at an odd TXT address, such as "
            f"{_odd_txt_span(local.number, quantity if counted else None)}.",
        )
    remote_bank = remote_addr.bank if remote_addr is not None else None
    default_fc = None
    if bit is not None and local is not None:
        default_fc = _send_default_fc(send, bit, local, remote_bank)
    fc = None
    if not check.refused("function_code"):
        fc = send.function_code or default_fc

    # The function code must suit the remote kind, and FC05/FC06 carry one element.
    if fc is not None and bit is not None:
        codes = (5, 15) if bit else (6, 16)
        if fc not in codes:
            kind = "a coil" if bit else "a register"
            check.refuse(
                ("function_code", "remote_start"),
                says("FC{fc:02d} cannot write {kind}", fc=fc, kind=kind),
                Reason.CONFLICT,
                code=Code.FUNCTION_CODE_MISMATCH,
                then=(
                    f"Write {kind} with FC{codes[0]:02d} or FC{codes[1]:02d}, "
                    f"such as function_code={codes[1]}."
                ),
            )
        if fc in (5, 6) and counted and quantity != 1:
            many = fc + 10
            check.refuse(
                ("function_code", "quantity"),
                says("FC{fc:02d} writes one element, not {quantity}", fc=fc, quantity=quantity),
                Reason.CONFLICT,
                code=Code.FUNCTION_CODE_MISMATCH,
                then=(
                    f"Write with FC{many:02d}, such as function_code={many}, or send one element"
                    + ("." if local is None else f", such as {local.display}.")
                ),
            )
        if not bit and local is not None and not check.refused("function_code"):
            fc06 = fc == 6
            local_banks = _SEND_LOCAL_REGS_FC06 if fc06 else _SEND_LOCAL_REGS_FC16
            check(
                "source",
                check_address,
                local_banks,
                label=f"{who} source (FC{fc:02d})",
                bank_id=_BANK_ID,
            )
            if isinstance(remote, str):
                remote_banks = _SEND_REMOTE_REGS_FC06 if fc06 else _SEND_REMOTE_REGS_FC16
                check(
                    "remote_start",
                    check_address,
                    remote_banks,
                    label=f"{who} remote_start (FC{fc:02d})",
                    bank_id=_BANK_ID,
                )

    if remote_addr is not None and bit is False and local is not None:
        _check_send_pair(check, remote_addr, local, fc)

    # The count of a TXT source that starts at an even address is not checked.
    checks_count = counted and not even_txt
    if bit is not None and local is not None and checks_count:
        xy_room = None
        if local.bank in XY_BANKS and remote_addr is not None:
            xy_room = _remote_xy_room(local, remote_addr)
        if local.bank == "TXT" and (fc or default_fc) != 6:
            _check_send_txt_count(check, quantity, local, _send_hex_room(remote, local))
        else:
            _check_quantity(check, quantity, local, _SEND_CAPS, bit, xy_room)
        if local.bank == "C" and remote_addr is not None:
            _check_c_remote_room(check, quantity, remote_addr)
    elif checks_count:
        _check_quantity_bounds(check, quantity, _SEND_CAPS, bit)

    if isinstance(remote, ModbusAddress) and remote.is_hex and local is not None:
        _check_send_hex_room(check, remote, local, quantity if counted else None)

    # Send: one C bit can't serve two status fields (OBJ-014).
    _check_status_bits(check, send, ("sending", "success", "error"), "OBJ-014")
    _check_status(check, send, "exception_response", _EXCEPTION_BANKS)

    if send.word_swap and fc is not None and bit is not None and local is not None:
        _check_send_word_swap(check, send, fc, bit, local, counted)
    if fc is None or default_fc is None:
        return None
    return fc, default_fc


def _is_flag(value: object) -> bool:
    """Whether ``value`` is True, False, 1 or 0."""
    return isinstance(value, int) and value in (0, 1)


def _receive_default_fc(remote: str | ModbusAddress, bit: bool, kind_984: str | None) -> int:
    """Return the function code that a Receive uses by default.

    A CLICK address uses FC01 for bits and FC03 for registers. A hex address sets the
    code by its register type, and a 984 address by the range it is in."""
    if isinstance(remote, str):
        return 1 if bit else 3
    if remote.is_hex:
        return _RD_REGISTER_TYPE_FC[remote.register_type or "holding"]
    return _RD_REGISTER_TYPE_FC[kind_984 or "holding"]


def _validate_receive(receive: Receive) -> tuple[int, int]:
    """Check every field of *receive*, and return the function code that the Receive is
    written with and the default function code.

    If the refusals of *receive* were allowed by code (:func:`allowed`), return the two
    function codes without raising the refusals. A refusal that leaves either code unknown
    still raises."""
    if allowed(receive):
        found = _check_receive(receive, Refusals(receive))
        if found is not None:
            return found
    with Refusals(receive) as check:
        found = _check_receive(receive, check)
    assert found is not None  # a refusal ended the block
    return found


def _check_receive(receive: Receive, check: Refusals) -> tuple[int, int] | None:
    """Check every field of *receive*, and record each refusal in *check*.

    Skip a check that depends on a field that is already refused. Return the function code
    that the Receive is written with and the default function code. Return None if a
    refusal leaves either code unknown."""
    who = "Receive"
    _check_target(check, receive.target, 1)
    _check_function_code(check, receive.function_code, tuple(_RD_FC_SUBTYPE))
    remote, quantity = receive.remote_start, receive.quantity
    _check_int_quantity(check, quantity)
    if not _check_remote_type(check, receive):
        return None
    counted = not check.refused("quantity")
    remote_addr: Address | None = None
    kind_984: str | None = None
    bit: bool | None = None  # None: the remote_start is refused, so its kind is not known
    if isinstance(remote, str):
        remote_addr = check(
            "remote_start",
            check_address,
            BIT_BANKS | _RECEIVE_REMOTE_REGS,
            label=f"{who} remote_start",
            bank_id=_BANK_ID,
        )
        if remote_addr is not None:
            bit = remote_addr.bank in BIT_BANKS
    elif remote.is_hex:
        bit = (remote.register_type or "holding") in ("coil", "discrete_input")
    else:
        kind_984 = _check_984(check, remote.address, _RECEIVE_984_KINDS)
        if kind_984 is not None:
            bit = kind_984 in ("coil", "discrete_input")
    default_fc = None if bit is None else _receive_default_fc(remote, bit, kind_984)
    fc = None
    if not check.refused("function_code"):
        fc = receive.function_code or default_fc
    if fc is not None:
        if remote_addr is not None:
            # A Receive may read a CLICK address with either code for its kind: FC01 or FC02
            # for a bit, and FC03 or FC04 for a register. CLICK refuses the slave address
            # of the other kind with OBJ-004.
            codes = (1, 2) if bit else (3, 4)
            if bit is not None and fc not in codes:
                kind = "a bit" if bit else "a register"
                check.refuse(
                    ("function_code", "remote_start"),
                    says("FC{fc:02d} cannot read {kind}", fc=fc, kind=kind),
                    Reason.CONFLICT,
                    _BANK_ID,
                    code=Code.FUNCTION_CODE_MISMATCH,
                    then=(
                        f"Read {kind} with FC{codes[0]:02d} or FC{codes[1]:02d}, "
                        f"such as function_code={codes[0]}."
                    ),
                )
        elif default_fc is not None and fc != default_fc and not isinstance(remote, str):
            check.refuse(
                ("function_code", "remote_start"),
                says(
                    "FC{fc:02d} does not match remote_start {remote}, which is FC{default:02d}",
                    fc=fc,
                    remote=_remote_start_to_csv(remote),
                    default=default_fc,
                ),
                Reason.CONFLICT,
                code=Code.FUNCTION_CODE_MISMATCH,
                then=f"Set function_code={default_fc}, or leave it None.",
            )

    if bit is None:
        dest_banks = _RECEIVE_LOCAL_BITS | _RECEIVE_LOCAL_REGS
    else:
        dest_banks = _RECEIVE_LOCAL_BITS if bit else _RECEIVE_LOCAL_REGS
    local = check("dest", check_address, dest_banks, label=f"{who} dest", bank_id=_BANK_ID)
    hex_pair = False
    if remote_addr is not None and bit is False and local is not None:
        check(
            "remote_start",
            check_address,
            _RECEIVE_REMOTE_FOR_DEST[local.bank],
            label=f"{who} remote_start (for a {local.bank} dest)",
            bank_id=_BANK_ID,
        )
        hex_pair = remote_addr.bank in WORD_IO_BANKS
    if bit is not None and local is not None and counted:
        xy_room = _receive_y_room(local, remote, remote_addr) if local.bank in XY_BANKS else None
        if local.bank == "TXT":
            # A Receive TXT count is in characters, two to a register. It must be even, from
            # 2 to 250.
            caps, unit = (_RECEIVE_CAPS[0], _TXT_RECEIVE_MAX, _RECEIVE_CAPS[2]), "characters"
        else:
            caps, unit = _RECEIVE_CAPS, None
        _check_quantity(check, quantity, local, caps, bit, xy_room, unit)
        if local.bank == "C" and remote_addr is not None:
            _check_c_remote_room(check, quantity, remote_addr)
        if (local.bank == "YD" or hex_pair) and quantity != 1:
            # A YD dest, or a DH dest read from XD or YD, takes one element. CLICK's message
            # gives the range as "(1 to 1)".
            check.refuse(
                "quantity",
                says("{quantity} is outside 1-1 for this dest and remote", quantity=quantity),
                Reason.RANGE,
                _RANGE_ID,
                code=Code.COUNT_OUT_OF_RANGE,
            )
        if local.bank == "TXT" and quantity < 2:
            # A count below 2 gets the range id OBJ-010, even a count of 1, which is also
            # odd.
            check.refuse(
                "quantity",
                _txt_count_rule(quantity),
                Reason.RANGE,
                _RANGE_ID,
                code=Code.COUNT_OUT_OF_RANGE,
            )
        elif local.bank == "TXT" and quantity % 2:
            check.refuse(
                "quantity",
                _txt_count_rule(quantity),
                Reason.RANGE,
                _ODD_ID,
                code=Code.COUNT_OUT_OF_RANGE,
            )
    elif counted:
        _check_quantity_bounds(check, quantity, _RECEIVE_CAPS, bit)

    # CLICK turns Word Swap off for a Receive in the cases below. If word_swap is not a
    # flag, it is refused as not a flag instead.
    if receive.word_swap and bit is not None:
        if bit:
            why, partner = "bits", "remote_start"
        elif local is None:
            why, partner = "", ""
        elif local.bank in ("YD", "TXT") or hex_pair:
            why, partner = f"a {local.bank} dest", "dest"
        elif local.bank in ("DD", "DF") and remote_addr is not None:
            why, partner = f"a {local.bank} dest read from a CLICK address", "dest"
        elif local.bank in ("DS", "DH") and counted and quantity == 1:
            # CLICK offers Word Swap for a DS or DH dest only when the count is above one.
            why, partner = f"one {local.bank} element", "quantity"
        else:
            why, partner = "", ""
        if why and not _is_flag(receive.word_swap):
            check.flag("word_swap")
        elif why:
            check.refuse(
                ("word_swap", partner),
                says("Word Swap is not offered for {why}", why=why),
                Reason.CONFLICT,
                code=Code.OPTION_NOT_OFFERED,
                then="Drop word_swap=True.",
            )

    # Receive: one C bit can't serve two status fields.
    _check_status_bits(check, receive, ("receiving", "success", "error"))
    _check_status(check, receive, "exception_response", _EXCEPTION_BANKS)
    if fc is None or default_fc is None:
        return None
    return fc, default_fc


# ---------------------------------------------------------------------------
# Tag tuples — exact field order
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

#: The Modbus func code (0x3218), keyed by (the target is TCP, the Slave ID is an address).
#: The ASCII variants (RD 9729/9730, SD 9732/9733) are not modelled, so they decode as raw
#: instructions.
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


@dataclass(frozen=True)
class Receive(Instruction, AllowsRefusals):
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
    #: The Modbus function code, 1 to 4. With None, a Receive reads a CLICK bit address with
    #: FC01 and a register with FC03. To read a CLICK address with FC02 or FC04, name the
    #: code. A hex or 984 address sets its own code. Construction sets the field to None
    #: when it equals the default.
    function_code: ReceiveFunctionCode | None = None

    def __post_init__(self) -> None:  # ty: ignore[invalid-dataclass]
        with Refusals(self) as check:
            _normalize_operands(
                check, self, ("dest", "receiving", "success", "error", "exception_response")
            )
            found = _check_receive(self, check)
            if found is not None:
                # Set inside the block, so that a Receive that holds a refusal also has
                # None for its default code.
                fc, default_fc = found
                object.__setattr__(self, "function_code", None if fc == default_fc else fc)
            check.flag("word_swap")
        assert found is not None  # a refusal ended the block

    @classmethod
    def from_csv_token(cls, token: str) -> Receive:
        """Parse the CSV token of a Receive, such as
        ``receive(target=ModbusTcpTarget(name="plc",ip="192.168.1.10"),remote_start="DS1",dest=DS1)``.

        ``read_csv`` reads the AF cell of a Receive with the same parser. The method raises
        ``CsvReadError`` or ``FieldError``, as ``read_csv`` does for the same AF cell.
        """
        return cast(Receive, _from_csv_token(token, "receive"))

    def to_csv(self) -> str:
        parts: list[str] = []
        parts.append(f"target={_target_to_csv(self.target)}")
        parts.append(f"remote_start={_remote_start_to_csv(self.remote_start)}")
        if self.function_code is not None:
            parts.append(f"function_code={self.function_code}")
        if self.quantity > 1:
            parts.append(f"dest={self.dest}..{_addr_end(self.dest, self.quantity, 'Receive')}")
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
        return dict(_CELL_PARAMS)

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


@dataclass(frozen=True)
class Send(Instruction, AllowsRefusals):
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
    #: The Modbus function code: 5, 6, 15 or 16. With None, a Send writes one element with
    #: FC05 or FC06, and more than one with FC15 or FC16. It writes one element with FC16
    #: when either side is in DD, DF or CTD. Construction sets the field to None when it
    #: equals the default.
    function_code: SendFunctionCode | None = None

    def __post_init__(self) -> None:  # ty: ignore[invalid-dataclass]
        with Refusals(self) as check:
            _normalize_operands(
                check, self, ("source", "sending", "success", "error", "exception_response")
            )
            found = _check_send(self, check)
            if found is not None:
                # Set inside the block, so that a Send that holds a refusal also has None
                # for its default code.
                fc, default_fc = found
                object.__setattr__(self, "function_code", None if fc == default_fc else fc)
            check.flag("word_swap")
        assert found is not None  # a refusal ended the block

    @classmethod
    def from_csv_token(cls, token: str) -> Send:
        """Parse the CSV token of a Send, such as
        ``send(target=ModbusTcpTarget(name="plc",ip="192.168.1.10"),remote_start="DS1",source=DS1)``.

        ``read_csv`` reads the AF cell of a Send with the same parser. The method raises
        ``CsvReadError`` or ``FieldError``, as ``read_csv`` does for the same AF cell.
        """
        return cast(Send, _from_csv_token(token, "send"))

    def to_csv(self) -> str:
        parts: list[str] = []
        parts.append(f"target={_target_to_csv(self.target)}")
        parts.append(f"remote_start={_remote_start_to_csv(self.remote_start)}")
        if self.function_code is not None:
            parts.append(f"function_code={self.function_code}")
        if self.quantity > 1:
            parts.append(f"source={self.source}..{_addr_end(self.source, self.quantity, 'Send')}")
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
        return dict(_CELL_PARAMS)

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
    if target == "":
        return ""  # a blank target is written blank, so that it reads back blank
    # A quote inside the name is written twice, as in any quoted CSV text.
    name = str(target.name).replace('"', '""')
    if isinstance(target, ModbusRtuTarget):
        return (
            f'ModbusRtuTarget(name="{name}"'
            f',com_port="{target.com_port}"'
            f",device_id={target.device_id})"
        )
    com_port = "" if target.com_port == "ethernet" else f',com_port="{target.com_port}"'
    return (
        f'ModbusTcpTarget(name="{name}"'
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
    """Construct a Send or Receive from the tags of a decoded blob.

    Return None if the blob is neither, or if it lacks a field or holds a value that this
    module does not model. The clipboard and program-file decoders both use it.
    """
    if class_name == "RD" and type_code == _RD_TYPE_CODE:
        return _from_tags_rd(tags)
    if class_name == "SD" and type_code == _SD_TYPE_CODE:
        return _from_tags_sd(tags)
    return None


def _build_target(
    tags: dict[int, str], class_name: str
) -> ModbusRtuTarget | ModbusTcpTarget | None:
    """Return the target that the tags describe.

    Return None for a port or func code that this module does not model. Also return None
    if building the target raises ``ValueError``. That happens for a Slave ID address that
    CLICK's dialog would not accept, and for a port tag that is not a number. In each case
    the instruction then decodes as raw.
    """
    func_code = tags.get(0x3218)
    known = _RD_FUNC if class_name == "RD" else _SD_FUNC
    if func_code is not None and func_code not in known.values():
        return None
    protocol_mode = tag_value(tags, 0x220C)
    if tag_value(tags, 0x223A) == "1":
        device_id: int | str = tag_value(tags, 0x60B2)
    else:
        # A program file (SCR) leaves out a field that has its class default. The default
        # device_id is 1 for a Receive and 0 for a Send. A Send with device_id 0 stores
        # neither 0x320E nor 0x60B2, and one with device_id 1 stores both.
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


def _keep_stored_ip(built: Send | Receive, tags: dict[int, str]) -> None:
    """Mark *built* to keep its stored blob if CLICK saved a TCP address with leading zeros.

    The target holds the address without them.
    """
    target = built.target
    if isinstance(target, ModbusTcpTarget) and target.ip != tag_value(tags, 0x622B):
        read_in_another_form(built)


def _from_tags_rd(tags: dict[int, str]) -> Receive | None:
    target = _build_target(tags, "RD")
    function_code = _RD_FC_FROM_SUBTYPE.get(tag_value(tags, 0x2211))
    if function_code is None:
        return None
    remote_start = _build_remote_start(tags, function_code)
    dest = tag_value(tags, 0x607E)
    if target is None or remote_start is None or not dest:
        return None

    built = Receive(
        target=target,
        remote_start=remote_start,
        dest=dest,
        quantity=tag_int(tags, 0x3210),
        receiving=tag_value(tags, 0x607C),
        success=tag_value(tags, 0x607B),
        error=tag_value(tags, 0x607D),
        exception_response=tag_value(tags, 0x6083),
        word_swap=tag_value(tags, 0x221C) == "0",
        function_code=cast("ReceiveFunctionCode", function_code),
    )
    _keep_stored_ip(built, tags)
    return built


def _from_tags_sd(tags: dict[int, str]) -> Send | None:
    target = _build_target(tags, "SD")
    function_code = _SD_FC_FROM_SUBTYPE.get(tag_value(tags, 0x2211))
    if function_code is None:
        return None
    remote_start = _build_remote_start(tags, function_code)
    source = tag_value(tags, 0x607E)
    if target is None or remote_start is None or not source:
        return None

    built = Send(
        target=target,
        remote_start=remote_start,
        source=source,
        quantity=tag_int(tags, 0x3210),
        sending=tag_value(tags, 0x607C),
        success=tag_value(tags, 0x607B),
        error=tag_value(tags, 0x607D),
        exception_response=tag_value(tags, 0x6083),
        word_swap=tag_value(tags, 0x221C) == "0",
        function_code=cast("SendFunctionCode", function_code),
    )
    _keep_stored_ip(built, tags)
    return built


# ---------------------------------------------------------------------------
# CSV call parser
# ---------------------------------------------------------------------------

_CONSTRUCTOR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\((.+)\)$", re.DOTALL)


#: The keywords that each call in a ``send(...)`` or ``receive(...)`` token accepts, in the
#: order that ``to_csv`` writes them.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "send": (
        "target",
        "remote_start",
        "function_code",
        "source",
        "sending",
        "success",
        "error",
        "exception_response",
        "word_swap",
    ),
    "receive": (
        "target",
        "remote_start",
        "function_code",
        "dest",
        "receiving",
        "success",
        "error",
        "exception_response",
        "word_swap",
    ),
    "ModbusTcpTarget": ("name", "ip", "port", "device_id", "com_port"),
    "ModbusRtuTarget": ("name", "com_port", "device_id"),
    "ModbusAddress": ("address", "register_type"),
}

#: The call that is paired with each call. A refusal of a keyword that only the paired call
#: accepts names that call.
_PAIRED = {
    "send": "receive",
    "receive": "send",
    "ModbusTcpTarget": "ModbusRtuTarget",
    "ModbusRtuTarget": "ModbusTcpTarget",
}

#: The keyword that a Send or Receive accepts in place of a keyword of the other class.
_IN_PLACE_OF = {
    ("send", "dest"): "source",
    ("send", "receiving"): "sending",
    ("receive", "source"): "dest",
    ("receive", "sending"): "receiving",
}

#: A token of each call, as a refusal of its arguments shows it.
_CALL_EXAMPLES = {
    "send": 'send(target=ModbusTcpTarget(name="plc",ip="192.168.1.10"),remote_start="DS1",'
    "source=DS1)",
    "receive": 'receive(target=ModbusTcpTarget(name="plc",ip="192.168.1.10"),'
    'remote_start="DS1",dest=DS1)',
    "ModbusTcpTarget": 'ModbusTcpTarget(name="plc",ip="192.168.1.10",port=502,device_id=1)',
    "ModbusRtuTarget": 'ModbusRtuTarget(name="plc",com_port="cpu2",device_id=1)',
    "ModbusAddress": "ModbusAddress(address=400001)",
}


def _call_keywords(call: str, inner: str) -> dict[str, str]:
    """Return the keyword arguments of the call *call*, whose arguments are *inner*, as they
    are written.

    Raise ``CsvReadError`` for an argument with no keyword, a keyword that *call* does not
    accept and a keyword given twice. In a target or a ``ModbusAddress``, also raise it for
    a value that holds more than one argument, as when a comma is missing.
    """
    # The csv package imports this module, so the import waits for the call.
    from ..csv.token_parser import _kwarg_eq_index, _split_args

    kwargs: dict[str, str] = {}
    for seg in _split_args(inner):
        eq = _kwarg_eq_index(seg)
        key, value = (seg[:eq].strip(), seg[eq + 1 :].strip()) if eq >= 0 else ("", seg)
        refused = _argument_refusal(call, seg, key, value, kwargs)
        if refused is not None:
            raise CsvReadError(refused)
        kwargs[key] = value
    return kwargs


def _argument_refusal(
    call: str, seg: str, key: str, value: str, kwargs: dict[str, str]
) -> str | None:
    """Return the message that refuses the argument *seg* of the call *call*, or None.

    *key* and *value* are the two sides of *seg*, and *key* is blank when *seg* has no
    keyword. *kwargs* holds the keyword arguments before *seg*.
    """
    shown = f"{call}(...)"
    if not seg:
        return (
            f"{shown} has an empty argument. Remove the extra comma, as in {_CALL_EXAMPLES[call]}."
        )
    if not key:
        return (
            f"{shown} has the argument {seg!r} with no keyword. Write each argument as "
            f"keyword=value, such as {_CALL_EXAMPLES[call]}."
        )
    if key in kwargs:
        return f"{shown} has {key}= more than once. Keep one, such as {key}={kwargs[key]}."
    if key not in _KEYWORDS[call]:
        return _unknown_keyword(call, key, value)
    # In a send or receive, the AF token parser refuses text after a closing quote, and the
    # field checks refuse an unquoted value that runs into the next argument.
    if call not in ("send", "receive") and not _one_value(value):
        return (
            f"Could not read {seg!r} in {shown}. Put a comma between two arguments, put text "
            f'in double quotes, and write a quote inside text as "", such as '
            f"{_CALL_EXAMPLES[call]}."
        )
    return None


def _unknown_keyword(call: str, key: str, value: str) -> str:
    """Return the message that refuses the keyword *key*, which the call *call* does not
    accept. *value* is the value written after the keyword."""
    shown = f"{call}(...)"
    paired = _PAIRED.get(call)
    if paired is not None and key in _KEYWORDS[paired]:
        said = f"{shown} has {key}=. Only {paired}(...) accepts it."
        instead = _IN_PLACE_OF.get((call, key))
        if instead is not None:
            return f"{said} Write {instead}={value} instead."
        return f"{said} Remove {key}=, or write a {paired}(...), such as {_CALL_EXAMPLES[paired]}."
    said = f"{shown} does not accept {key}=."
    if key == "quantity" and call in ("send", "receive"):
        data = "source" if call == "send" else "dest"
        return f"{said} Write the count as a range, such as {data}=DS1..DS5."
    accepted = ", ".join(f"{k}=" for k in _KEYWORDS[call])
    return f"{said} Remove it, or use one of its keywords: {accepted}."


def _one_value(value: str) -> bool:
    """Return whether *value*, the value of one keyword argument of a target or a
    ``ModbusAddress``, holds one value.

    A value in double quotes ends at its closing quote, and ``""`` inside it is one quote.
    Any other value holds no ``=`` or ``"``. A missing comma before the next keyword leaves
    one of the two in the value.
    """
    # The csv package imports this module, so the import waits for the call.
    from ..csv.token_parser import _decode_af_string_literal

    if value.startswith('"'):
        try:
            _decode_af_string_literal(value)
        except CsvReadError:
            return False
        return True
    return "=" not in value and '"' not in value


def _strip_quotes(s: str) -> str:
    """Return the text of *s* without its surrounding double quotes, if it has them.

    Each ``""`` inside the quotes is one quote of the text, as :func:`_one_value` reads it.
    """
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace('""', '"')
    return s


def _parse_target(raw: str) -> ModbusRtuTarget | ModbusTcpTarget:
    m = _CONSTRUCTOR_RE.fullmatch(raw.strip())
    if m is None or m.group(1) not in ("ModbusTcpTarget", "ModbusRtuTarget"):
        raise CsvReadError(
            f"Could not read target={raw}. Write ModbusTcpTarget(...) or ModbusRtuTarget(...), "
            f"such as {_CALL_EXAMPLES['ModbusTcpTarget']}."
        )
    cls_name = m.group(1)
    kw = _call_keywords(cls_name, m.group(2))

    name = _strip_quotes(kw.get("name", ""))
    raw_id = _strip_quotes(kw.get("device_id", "0"))
    device_id: int | str = raw_id
    digits = raw_id.removeprefix("-")
    if digits.isascii() and digits.isdigit():
        if too_long(digits):
            high = 247 if cls_name == "ModbusRtuTarget" else 255
            raise _target_number_refusal(
                "device_id",
                cls_name,
                says(_DEVICE_ID_RANGE, high=high, device_id=raw_id),
                _device_id_then(high),
            )
        device_id = -digits_value(digits) if raw_id != digits else digits_value(digits)

    # A target refuses a com_port that is not one of its ports.
    if cls_name == "ModbusRtuTarget":
        com_port = cast("ModbusRtuPort", _strip_quotes(kw.get("com_port", "cpu2")))
        return ModbusRtuTarget(name=name, com_port=com_port, device_id=device_id)
    ip = _strip_quotes(kw.get("ip", ""))
    raw_port = kw.get("port", "502")
    if not raw_port.isascii() or not raw_port.removeprefix("-").isdigit():
        raise make_refusal(
            FieldError,
            "ModbusTcpTarget.port",
            says("{port} is not a port number", port=Op(raw_port)),
            field="ModbusTcpTarget.port",
            reason=Reason.FORM,
            code=Code.INVALID_MODBUS_TARGET,
            then="Enter a whole number, such as 502.",
        )
    if too_long(raw_port.removeprefix("-")):
        raise _target_number_refusal("port", cls_name, says(_PORT_RANGE, port=raw_port), _PORT_THEN)
    port_digits = raw_port.removeprefix("-")
    port = -digits_value(port_digits) if raw_port != port_digits else digits_value(port_digits)
    com_port = cast("ModbusTcpPort", _strip_quotes(kw.get("com_port", "ethernet")))
    return ModbusTcpTarget(name=name, ip=ip, port=port, device_id=device_id, com_port=com_port)


def _target_number_refusal(field: str, cls_name: str, said: Rule, then: str) -> FieldError:
    """Return the refusal of a number in a target token that is too long for ``int()``.

    ``said`` and ``then`` are the refusal that the target gives a number outside its range,
    with the text of the number in it."""
    name = f"{cls_name}.{field}"
    return make_refusal(
        FieldError,
        name,
        said,
        field=name,
        reason=Reason.RANGE,
        code=Code.INVALID_MODBUS_TARGET,
        then=then,
    )


def _parse_remote_start(raw: str) -> str | ModbusAddress:
    """Parse remote_start value — quoted string or ModbusAddress(...)."""
    raw = raw.strip()
    if raw.startswith('"'):
        return _strip_quotes(raw)
    m = _CONSTRUCTOR_RE.fullmatch(raw)
    if m and m.group(1) == "ModbusAddress":
        kw = _call_keywords("ModbusAddress", m.group(2))
        return ModbusAddress(
            address=kw.get("address", ""),
            # The ModbusAddress refuses any other register type.
            register_type=cast("ModbusRegisterType | None", kw.get("register_type")),
        )
    return raw


#: The sentence that follows the refusal of a range that is not two addresses of one bank.
_RANGE_THEN = "Write two addresses of one bank joined by '..', such as DS1..DS10."


def _parse_range_quantity(raw: str, field: str) -> tuple[str, int]:
    """Parse 'DS1..DS5' → ('DS1', 5) or 'DS1' → ('DS1', 1).

    CLICK stores a start and a count.  An X/Y range counts the points of the slots it
    covers, so X001..X021 is 17 (X001-X016, then X021).
    """
    if ".." in raw:
        start, end = raw.split("..", 1)
        start = normalize_address(start.strip(), field)
        end = normalize_address(end.strip(), field)
        m_start = address_shape(start)
        m_end = address_shape(end)
        if not (m_start and m_end):
            raise make_refusal(
                FieldError,
                None,
                says("range {raw} must run between two addresses of one bank", raw=Op(raw)),
                field=field,
                reason=Reason.FORM,
                code=Code.NOT_AN_ADDRESS,
                then=_RANGE_THEN,
            )
        prefix = m_start[0]
        if m_end[0] != prefix:
            raise make_refusal(
                FieldError,
                None,
                says(
                    "range {raw} mixes banks {prefix} and {other}",
                    raw=Op(raw),
                    prefix=prefix,
                    other=m_end[0],
                ),
                field=field,
                reason=Reason.FORM,
                code=Code.RANGE_MIXED_BANKS,
                then=_RANGE_THEN,
            )
        check_address(end, field, {prefix}, label=f"range end of {raw!r}")
        first, last = digits_value(m_start[1]), digits_value(m_end[1])
        if last < first:
            raise make_refusal(
                FieldError,
                None,
                says("range {raw} runs backwards", raw=Op(raw)),
                field=field,
                reason=Reason.FORM,
                code=Code.RANGE_NOT_ASCENDING,
                then="Write the lower address first, such as DS1..DS10.",
            )
        qty = xy_points(first, last) if prefix in XY_BANKS else last - first + 1
        return start, qty
    return raw.strip(), 1


def _parse_function_code(kw: dict[str, str], cls: str) -> int | None:
    raw = kw.get("function_code")
    if raw is None:
        return None
    if not raw.isascii() or not raw.isdigit() or too_long(raw):
        raise make_refusal(
            FieldError,
            None,
            says("function_code must be a number, got {raw}", raw=Op(raw)),
            field=f"{cls}.function_code",
            reason=Reason.FORM,
            code=Code.INVALID_CHOICE,
        )
    return digits_value(raw)


def parse_af_call(call: AfCall) -> Receive | Send:
    """Parse a CSV AF call node into a Send or Receive instruction."""
    kw = call.kwargs
    # The node keeps the last of two keywords with one name, so read the arguments as written.
    written = _CONSTRUCTOR_RE.fullmatch((call.raw or call.to_token()).strip())
    if written is not None and call.name in ("send", "receive"):
        _call_keywords(call.name, written.group(2))
    for name in ("target", "remote_start"):
        if name not in kw:
            raise CsvReadError(f"{call.name} needs a {name}= keyword")

    # The Send or Receive refuses a blank target as missing.
    target = _parse_target(kw["target"]) if kw["target"] else cast("ModbusTcpTarget", "")
    remote_start = _parse_remote_start(kw["remote_start"])
    cls = "Receive" if call.name == "receive" else "Send"
    word_swap = check_csv_flag(kw, "word_swap", f"{cls}.word_swap")
    function_code = _parse_function_code(kw, cls)

    receiving = kw.get("receiving", "")
    sending = kw.get("sending", "")
    success = kw.get("success", "")
    error = kw.get("error", "")
    exception_response = kw.get("exception_response", "")

    if call.name == "receive":
        dest_raw = kw.get("dest", "")
        dest, quantity = _parse_range_quantity(dest_raw, "Receive.dest")
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
            # The Receive refuses a function code that is not 1, 2, 3 or 4.
            function_code=cast("ReceiveFunctionCode | None", function_code),
        )

    if call.name == "send":
        source_raw = kw.get("source", "")
        source, quantity = _parse_range_quantity(source_raw, "Send.source")
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
            # The Send refuses a function code that is not 5, 6, 15 or 16.
            function_code=cast("SendFunctionCode | None", function_code),
        )

    raise make_refusal(
        FieldError,
        None,
        says("Unsupported send_receive instruction: {name}", name=Op(call.name)),
        field=None,  # token syntax, not a field value
        reason=Reason.FORM,
        code=Code.INVALID_TOKEN,
    )


def _from_csv_token(token: str, name: Literal["send", "receive"]) -> Receive | Send:
    """Parse *token* as ``read_csv`` parses an AF cell, and build the Send or Receive.

    Raise ``CsvReadError`` when the token is not a call named *name*."""
    from ..csv.ast import AfCall
    from ..csv.token_parser import parse_af_token  # the csv package imports this module

    label = name.capitalize()
    shape = f"{name}(target=...,remote_start=...,{'source' if name == 'send' else 'dest'}=...)"
    node = parse_af_token(token)
    if isinstance(node, AfCall) and node.name == name:
        return parse_af_call(node)
    other = "receive" if name == "send" else "send"
    if isinstance(node, AfCall) and node.name == other:
        raise CsvReadError(
            f"Could not read {token!r} as a {label}, because it is a {other}(...) token. Read it "
            f"with {other.capitalize()}.from_csv_token(), or write a {label} as {shape}, such as "
            f"{_CALL_EXAMPLES[name]}."
        )
    raise CsvReadError(
        f"Could not read {token!r} as a {label}. Write it as {shape}, such as "
        f"{_CALL_EXAMPLES[name]}."
    )


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
    cell_params_from_tags=fixed_cell_params(
        _CELL_PARAMS, ("RD", _RD_TYPE_CODE), ("SD", _SD_TYPE_CODE)
    ),
)
