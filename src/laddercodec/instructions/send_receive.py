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

from ..binary_helpers import tag_flag, tag_int, tag_value
from ..model import AfInstruction
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
            raise ValueError(
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
            raise ValueError(
                f"ModbusTcpTarget com_port must be one of {', '.join(_TCP_PORT_MODE)}, "
                f"got {self.com_port!r}"
            )
        _check_device_id(self.device_id)


_DS_ADDRESS_RE = re.compile(r"DS([1-9]\d*)")


def _check_device_id(device_id: int | str) -> None:
    """CLICK's Slave ID box takes a number or a DS address (DD, DH, C... are refused)."""
    if isinstance(device_id, str):
        m = _DS_ADDRESS_RE.fullmatch(device_id)
        if not m or int(m.group(1)) > 4500:
            raise ValueError(
                f"device_id must be a number or a DS address (DS1..DS4500), got {device_id!r}"
            )


@dataclass(frozen=True)
class ModbusAddress:
    """Non-CLICK remote address (MODBUS 984 or hex)."""

    address: str  # "400001" or "0h"
    register_type: str | None = None  # "coil"|"holding"|... — only for hex


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
# FC inference
# ---------------------------------------------------------------------------

#: CLICK bit-address prefixes (coil / discrete input).
_CLICK_BIT_PREFIXES = frozenset({"X", "Y", "C", "T", "CT", "SC"})
#: CLICK register-address prefixes.
_CLICK_REG_PREFIXES = frozenset({"DS", "DD", "DH", "DF", "TD", "CTD", "TXT", "YD", "SD", "XD"})
#: CLICK writable-bit prefixes (for Send).
_CLICK_WRITABLE_BIT = frozenset({"Y", "C"})

_ADDR_PREFIX_RE = re.compile(r"^([A-Z]+)")


def _click_prefix(addr: str) -> str:
    m = _ADDR_PREFIX_RE.match(addr)
    if not m:
        raise ValueError(f"Cannot extract prefix from CLICK address: {addr!r}")
    return m.group(1)


def _is_click_bit(addr: str) -> bool:
    return _click_prefix(addr) in _CLICK_BIT_PREFIXES


def _is_click_register(addr: str) -> bool:
    return _click_prefix(addr) in _CLICK_REG_PREFIXES


def _modbus984_is_coil(addr: str) -> bool:
    """True if a MODBUS 984 address falls in the coil range (0xxxxx)."""
    n = int(addr)
    return n < 100001


def _modbus984_fc_subtype_rd(addr: str) -> str:
    n = int(addr)
    if n < 100001:
        return "0"  # FC01
    if n < 200001:
        return "1"  # FC02
    if n < 400001:
        return "3"  # FC04
    return "2"  # FC03


def _rd_fc_subtype(remote_start: str | ModbusAddress) -> str:
    """Compute RD fc_subtype from the remote address."""
    if isinstance(remote_start, str):
        # CLICK address — bits → FC01, registers → FC03
        if _is_click_bit(remote_start):
            return "0"  # FC01
        return "2"  # FC03
    if remote_start.address.endswith("h"):
        # Hex address — use register_type
        rt = remote_start.register_type or "holding"
        return {"coil": "0", "discrete_input": "1", "holding": "2", "input": "3"}[rt]
    # MODBUS 984
    return _modbus984_fc_subtype_rd(remote_start.address)


def _sd_fc_subtype(remote_start: str | ModbusAddress, quantity: int) -> str:
    """Compute SD fc_subtype from address and quantity."""
    is_coil = False

    if isinstance(remote_start, str):
        # CLICK address
        prefix = _click_prefix(remote_start)
        is_coil = prefix in _CLICK_WRITABLE_BIT
    elif remote_start.address.endswith("h"):
        # Hex
        rt = remote_start.register_type or "holding"
        is_coil = rt == "coil"
    else:
        # MODBUS 984
        is_coil = _modbus984_is_coil(remote_start.address)

    if is_coil:
        return "0" if quantity == 1 else "2"  # FC05 / FC15
    return "1" if quantity == 1 else "3"  # FC06 / FC16


# ---------------------------------------------------------------------------
# Address helpers
# ---------------------------------------------------------------------------

_ADDR_NUM_RE = re.compile(r"^([A-Z]+)(\d+)$")


def _addr_end(start: str, quantity: int) -> str:
    """Compute end address from start + quantity (e.g. DS1 + 5 → DS5)."""
    m = _ADDR_NUM_RE.fullmatch(start)
    if not m:
        return start
    prefix, num = m.group(1), int(m.group(2))
    return f"{prefix}{num + quantity - 1}"


def _addr_type_code(remote_start: str | ModbusAddress) -> str:
    """Return the binary address_type field value."""
    if isinstance(remote_start, str):
        return "2"  # CLICK
    if remote_start.address.endswith("h"):
        return "1"  # hex
    return "0"  # MODBUS 984


def _remote_start_str(remote_start: str | ModbusAddress) -> str:
    """Return the raw string value for the binary remote_start field."""
    if isinstance(remote_start, str):
        return remote_start
    return remote_start.address


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

    def to_csv(self) -> str:
        parts: list[str] = []
        parts.append(f"target={_target_to_csv(self.target)}")
        parts.append(f"remote_start={_remote_start_to_csv(self.remote_start)}")
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
        fc_subtype = _rd_fc_subtype(self.remote_start)
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

    def to_csv(self) -> str:
        parts: list[str] = []
        parts.append(f"target={_target_to_csv(self.target)}")
        parts.append(f"remote_start={_remote_start_to_csv(self.remote_start)}")
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
        fc_subtype = _sd_fc_subtype(self.remote_start, self.quantity)
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


def _build_remote_start(
    tags: dict[int, str],
    rd: bool,
) -> str | ModbusAddress | None:
    remote_start_raw = tag_value(tags, 0x6085)
    if not remote_start_raw:
        return None

    address_type = tag_value(tags, 0x320F)
    fc_subtype = tag_value(tags, 0x2211)

    if address_type == "2":
        return remote_start_raw
    if address_type == "1":
        if rd:
            rt = {"0": "coil", "1": "discrete_input", "2": "holding", "3": "input"}.get(
                fc_subtype, "holding"
            )
        else:
            rt = {"0": "coil", "1": "holding", "2": "coil", "3": "holding"}.get(
                fc_subtype, "holding"
            )
        return ModbusAddress(address=remote_start_raw, register_type=rt)
    return ModbusAddress(address=remote_start_raw)


def _from_tags_rd(tags: dict[int, str]) -> Receive | None:
    target = _build_target(tags, "RD")
    remote_start = _build_remote_start(tags, rd=True)
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
    )


def _from_tags_sd(tags: dict[int, str]) -> Send | None:
    target = _build_target(tags, "SD")
    remote_start = _build_remote_start(tags, rd=False)
    source = tag_value(tags, 0x607E)
    if target is None or remote_start is None or not source:
        return None

    return Send(
        target=target,
        remote_start=remote_start,
        source=source,
        quantity=tag_int(tags, 0x3210),
        sending=tag_value(tags, 0x607C) if tag_flag(tags, 0x120A) else "",
        success=tag_value(tags, 0x607B) if tag_flag(tags, 0x1209) else "",
        error=tag_value(tags, 0x607D) if tag_flag(tags, 0x120B) else "",
        exception_response=tag_value(tags, 0x6083) if tag_flag(tags, 0x121A) else "",
        word_swap=tag_value(tags, 0x221C) == "0",
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
    device_id: int | str = int(raw_id) if raw_id.lstrip("-").isdigit() else raw_id

    if cls_name == "ModbusRtuTarget":
        com_port = _strip_quotes(kw.get("com_port", "cpu2"))
        return ModbusRtuTarget(name=name, com_port=com_port, device_id=device_id)
    if cls_name == "ModbusTcpTarget":
        ip = _strip_quotes(kw.get("ip", ""))
        port = int(kw.get("port", "502"))
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
    """Parse 'DS1..DS5' → ('DS1', 5) or 'DS1' → ('DS1', 1)."""
    if ".." in raw:
        start, end = raw.split("..", 1)
        start = start.strip()
        end = end.strip()
        m_start = _ADDR_NUM_RE.fullmatch(start)
        m_end = _ADDR_NUM_RE.fullmatch(end)
        if m_start and m_end and m_start.group(1) == m_end.group(1):
            qty = int(m_end.group(2)) - int(m_start.group(2)) + 1
            return start, qty
        return start, 1
    return raw.strip(), 1


def parse_af_call(call: AfCall) -> Receive | Send:
    """Parse a CSV AF call node into a Send or Receive instruction."""
    kw = call.kwargs

    target = _parse_target(kw["target"])
    remote_start = _parse_remote_start(kw["remote_start"])
    word_swap = kw.get("word_swap") == "1"

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
