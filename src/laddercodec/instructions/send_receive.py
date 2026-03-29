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
    com_port: str  # "cpu2", "slot0_1", "slot1_2"
    device_id: int


@dataclass(frozen=True)
class ModbusTcpTarget:
    """TCP/IP target."""

    name: str  # human label, not in binary
    ip: str
    port: int
    device_id: int


@dataclass(frozen=True)
class ModbusAddress:
    """Non-CLICK remote address (MODBUS 984 or hex)."""

    address: str  # "400001" or "0h"
    register_type: str | None = None  # "coil"|"holding"|... — only for hex


# ---------------------------------------------------------------------------
# Protocol mode tables
# ---------------------------------------------------------------------------

_COM_PORT_MODE: dict[str, str] = {
    "tcp": "2",
    "cpu2": "0",
    "slot0_1": "4",
    "slot0_2": "5",
    "slot1_1": "6",
    "slot1_2": "7",
}

_COM_PORT_MODE_INV: dict[str, str] = {v: k for k, v in _COM_PORT_MODE.items()}

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

_RD_FC_RTU = "9728"
_RD_FC_TCP = "9735"
_SD_FC_RTU = "9731"
_SD_FC_TCP = "9736"

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

        if isinstance(self.target, ModbusTcpTarget):
            func_code = _RD_FC_TCP
            protocol_mode = _COM_PORT_MODE["tcp"]
            ip = self.target.ip
            port = str(self.target.port)
        else:
            func_code = _RD_FC_RTU
            protocol_mode = _COM_PORT_MODE[self.target.com_port]
            ip = "..."
            port = "502"
        fc_subtype = _rd_fc_subtype(self.remote_start)
        address_type = _addr_type_code(self.remote_start)
        device_id = str(self.target.device_id)

        fields: list[str] = [
            func_code,  # [0]
            protocol_mode,  # [1]
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
            device_id,  # [14] device_id
            device_id,  # [15] device_id_dup
            "0",  # [16] reserved
            fc_subtype,  # [17] fc_subtype
            address_type,  # [18] address_type
            _remote_start_str(self.remote_start),  # [19] remote_start
            self.dest,  # [20] dest
            str(self.quantity),  # [21] quantity
            "0" if self.word_swap else "1",  # [22] word_swap_off
        ]
        fields.extend(_RD_RESERVED_DEFAULTS)  # [23-35]
        fields.extend([ip, port, "SD50", "SD60"])  # [36-39]

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

        if isinstance(self.target, ModbusTcpTarget):
            func_code = _SD_FC_TCP
            protocol_mode = _COM_PORT_MODE["tcp"]
            ip = self.target.ip
            port = str(self.target.port)
        else:
            func_code = _SD_FC_RTU
            protocol_mode = _COM_PORT_MODE[self.target.com_port]
            ip = "..."
            port = "502"
        fc_subtype = _sd_fc_subtype(self.remote_start, self.quantity)
        address_type = _addr_type_code(self.remote_start)
        device_id = str(self.target.device_id)

        fields: list[str] = [
            func_code,  # [0]
            protocol_mode,  # [1]
            "0",  # [2]  reserved
            "1" if self.sending else "0",  # [3]  sending_enabled
            self.sending or "",  # [4]  sending_bit
            "1" if self.success else "0",  # [5]  success_enabled
            self.success or "",  # [6]  success_bit
            "1" if self.error else "0",  # [7]  error_enabled
            self.error or "",  # [8]  error_bit
            "1" if self.exception_response else "0",  # [9]  exception_enabled
            self.exception_response or "",  # [10] exception_response
            device_id,  # [11] device_id
            device_id,  # [12] device_id_dup
            "0",  # [13] reserved
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
        out += _tagged_field(0x622B, ip)  # [280] ip_or_name
        out += _tagged_field(0x322C, port)  # [281] port
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
    return (
        f'ModbusTcpTarget(name="{target.name}"'
        f',ip="{target.ip}"'
        f",port={target.port}"
        f",device_id={target.device_id})"
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
# Blob parser
# ---------------------------------------------------------------------------


def parse_blob(raw: bytes) -> Receive | Send | None:
    """Parse an RD or SD instruction blob."""
    from ..binary_helpers import _parse_tagged_fields_verbose, _read_utf16le

    class_name, pos = _read_utf16le(raw, 0)
    if class_name not in ("RD", "SD"):
        return None
    if pos + 10 > len(raw):
        return None

    pos += 4  # skip type marker
    pos += 2  # skip part count
    field_count = int.from_bytes(raw[pos : pos + 4], "little")
    pos += 4

    # Must use _parse_tagged_fields_verbose because SD/RD padding fields
    # (0x6889, 0x688F) use incrementing sentinels, not 0xFFFFFFFF.
    verbose, _ = _parse_tagged_fields_verbose(raw, pos, field_count)
    fields = [val for _, _, val in verbose]

    if class_name == "RD":
        return _parse_rd(fields)
    return _parse_sd(fields)


def _parse_rd(fields: list[str]) -> Receive | None:
    if len(fields) < 40:
        return None

    func_code = fields[0]
    protocol_mode = fields[1]
    device_id = int(fields[14]) if fields[14] else 0

    # Determine target
    is_tcp = func_code == _RD_FC_TCP
    if is_tcp:
        ip = fields[36] if len(fields) > 36 else ""
        port = int(fields[37]) if len(fields) > 37 and fields[37] else 502
        target: ModbusRtuTarget | ModbusTcpTarget = ModbusTcpTarget(
            name="tcp", ip=ip, port=port, device_id=device_id
        )
    else:
        com_port = _COM_PORT_MODE_INV.get(protocol_mode, "cpu2")
        target = ModbusRtuTarget(name="rtu", com_port=com_port, device_id=device_id)

    # Determine remote_start
    address_type = fields[18]
    remote_start_raw = fields[19]
    remote_start: str | ModbusAddress
    if address_type == "2":
        remote_start = remote_start_raw
    elif address_type == "1":
        # Hex — infer register_type from fc_subtype
        fc_sub = fields[17]
        rt = {"0": "coil", "1": "discrete_input", "2": "holding", "3": "input"}.get(
            fc_sub, "holding"
        )
        remote_start = ModbusAddress(address=remote_start_raw, register_type=rt)
    else:
        remote_start = ModbusAddress(address=remote_start_raw)

    # Flags
    receiving = fields[5] if fields[4] == "1" else ""
    success = fields[7] if fields[6] == "1" else ""
    error = fields[9] if fields[8] == "1" else ""
    exception_response = fields[11] if fields[10] == "1" else ""

    word_swap = fields[22] == "0"  # word_swap_off='0' means swap ON
    quantity = int(fields[21]) if fields[21] else 1

    return Receive(
        target=target,
        remote_start=remote_start,
        dest=fields[20],
        quantity=quantity,
        receiving=receiving,
        success=success,
        error=error,
        exception_response=exception_response,
        word_swap=word_swap,
    )


def _parse_sd(fields: list[str]) -> Send | None:
    if len(fields) < 30:
        return None

    func_code = fields[0]
    protocol_mode = fields[1]
    device_id = int(fields[11]) if fields[11] else 0

    is_tcp = func_code == _SD_FC_TCP
    if is_tcp:
        ip = fields[280] if len(fields) > 280 else ""
        port = int(fields[281]) if len(fields) > 281 and fields[281] else 502
        target: ModbusRtuTarget | ModbusTcpTarget = ModbusTcpTarget(
            name="tcp", ip=ip, port=port, device_id=device_id
        )
    else:
        com_port = _COM_PORT_MODE_INV.get(protocol_mode, "cpu2")
        target = ModbusRtuTarget(name="rtu", com_port=com_port, device_id=device_id)

    address_type = fields[15]
    remote_start_raw = fields[16]
    remote_start: str | ModbusAddress
    if address_type == "2":
        remote_start = remote_start_raw
    elif address_type == "1":
        fc_sub = fields[14]
        rt = {"0": "coil", "1": "holding", "2": "coil", "3": "holding"}.get(fc_sub, "holding")
        remote_start = ModbusAddress(address=remote_start_raw, register_type=rt)
    else:
        remote_start = ModbusAddress(address=remote_start_raw)

    sending = fields[4] if fields[3] == "1" else ""
    success = fields[6] if fields[5] == "1" else ""
    error = fields[8] if fields[7] == "1" else ""
    exception_response = fields[10] if fields[9] == "1" else ""

    word_swap = fields[19] == "0"
    quantity = int(fields[18]) if fields[18] else 1

    return Send(
        target=target,
        remote_start=remote_start,
        source=fields[17],
        quantity=quantity,
        sending=sending,
        success=success,
        error=error,
        exception_response=exception_response,
        word_swap=word_swap,
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
    device_id = int(kw.get("device_id", "0"))

    if cls_name == "ModbusRtuTarget":
        com_port = _strip_quotes(kw.get("com_port", "cpu2"))
        return ModbusRtuTarget(name=name, com_port=com_port, device_id=device_id)
    if cls_name == "ModbusTcpTarget":
        ip = _strip_quotes(kw.get("ip", ""))
        port = int(kw.get("port", "502"))
        return ModbusTcpTarget(name=name, ip=ip, port=port, device_id=device_id)
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
    parse_blob=parse_blob,
    csv_names=("receive", "send"),
    parse_csv_call=parse_af_call,
    min_csv_rows=3,
)
