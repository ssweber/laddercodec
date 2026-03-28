"""Generate modbus send/receive coverage CSV fixtures.

Minimal set to cover all Click UI dropdown/checkbox options:
- 8 RTU register fixtures (4 com_port variants x click/modbus remote x single/block)
- 5 TCP coil/input fixtures (FC 01/02/04/05/15 — FCs not covered by register fixtures)
- 2 word_swap fixtures (send + receive with 32-bit DD addresses)
= 15 total
"""

import os

HEADER = "marker,A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z,AA,AB,AC,AD,AE,AF"
DASHES = ",".join(["-"] * 30)  # B through AE

TCP = 'ModbusTcpTarget(name=""plc2"",ip=""192.168.1.10"",port=502,device_id=1)'

# Each RTU combo gets a different com_port to cover all port formats
RTU_PORTS = {
    ("click", "single"): ("cpu1", 5),
    ("click", "block"): ("cpu2", 5),
    ("modbus", "single"): ("slot0_1", 3),
    ("modbus", "block"): ("slot1_2", 3),
}

CLICK_REMOTE = '""DS1""'
MODBUS_REMOTE = "ModbusAddress(address=0,register_type=holding)"

# Specific FC to select in Click UI for register fixtures.
REG_FC = {
    ("send", "single"): "select FC 06 (Write Single Register)",
    ("send", "block"): "select FC 16 (Write Multiple Registers)",
    ("receive", "single"): "select FC 03 (Read Holding Registers)",
    ("receive", "block"): "select FC 03 (Read Holding Registers)",
}

OUT = "tests/fixtures/coverage/golden"


def write_fixture(rung_id, comment, token):
    row = f'R,C10,{DASHES},"{token}"'
    content = f"{HEADER}\n#,{comment}\n{row}\n"
    path = os.path.join(OUT, f"{rung_id}.csv")
    with open(path, "w", newline="") as f:
        f.write(content)
    print(f"  wrote {path}")


def make_token(direction, target, remote, data_key, data_val, flag_key, extra_kwargs=""):
    kw = f",{extra_kwargs}" if extra_kwargs else ""
    return (
        f"{direction}("
        f"target={target},"
        f"remote_start={remote},"
        f"{data_key}={data_val},"
        f"{flag_key}=C1,"
        f"success=C2,"
        f"error=C3,"
        f"exception_response=DS100{kw})"
    )


# --- 8 RTU register fixtures: com_port variants x remote x data ---

for direction in ("send", "receive"):
    data_key = "source" if direction == "send" else "dest"
    flag_key = "sending" if direction == "send" else "receiving"

    for remote_name, remote_val in (("click", CLICK_REMOTE), ("modbus", MODBUS_REMOTE)):
        for data_name, data_val in (("single", "DS1"), ("block", "DS1..DS5")):
            com_port, dev_id = RTU_PORTS[(remote_name, data_name)]
            target_val = (
                f'ModbusRtuTarget(name=""rtu1"",com_port=""{com_port}"",device_id={dev_id})'
            )
            rung_id = f"{direction}__rtu_{remote_name}_{data_name}"
            comment = f"{rung_id} \u2014 {REG_FC[(direction, data_name)]}"
            token = make_token(direction, target_val, remote_val, data_key, data_val, flag_key)
            write_fixture(rung_id, comment, token)


# --- 5 TCP coil/input fixtures: remaining FC dropdown options ---
# All TCP + Click addressing (dialog shared with RTU).

COIL_FIXTURES = [
    (
        "send__tcp_click_coil",
        "select FC 05 (Write Single Coil)",
        "send",
        '""C1""',
        "source",
        "C11",
        "sending",
    ),
    (
        "send__tcp_click_coils",
        "select FC 15 (Write Multiple Coils)",
        "send",
        '""C1""',
        "source",
        "C11..C15",
        "sending",
    ),
    (
        "receive__tcp_click_coil",
        "select FC 01 (Read Coil Status)",
        "receive",
        '""C1""',
        "dest",
        "C11..C15",
        "receiving",
    ),
    (
        "receive__tcp_click_input",
        "select FC 02 (Read Input Status)",
        "receive",
        '""X1""',
        "dest",
        "C11..C15",
        "receiving",
    ),
    (
        "receive__tcp_click_input_reg",
        "select FC 04 (Read Input Registers)",
        "receive",
        '""DS1""',
        "dest",
        "DS1..DS5",
        "receiving",
    ),
]

for rung_id, fc_hint, direction, remote, data_key, data_val, flag_key in COIL_FIXTURES:
    comment = f"{rung_id} \u2014 {fc_hint}"
    token = make_token(direction, TCP, remote, data_key, data_val, flag_key)
    write_fixture(rung_id, comment, token)


# --- 2 word_swap fixtures: 32-bit DD addresses with swap enabled ---

for direction, data_key, flag_key in (
    ("send", "source", "sending"),
    ("receive", "dest", "receiving"),
):
    rung_id = f"{direction}__tcp_click_wordswap"
    comment = f"{rung_id} \u2014 Word Swap checkbox ON (32-bit DD addresses)"
    token = make_token(
        direction, TCP, '""DD1""', data_key, "DD1..DD5", flag_key, extra_kwargs="word_swap=1"
    )
    write_fixture(rung_id, comment, token)


print(f"\nDone \u2014 15 fixtures in {OUT}/")
