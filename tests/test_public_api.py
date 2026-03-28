from __future__ import annotations

from pathlib import Path

import laddercodec
from laddercodec import (
    BlockCopy,
    Call,
    Coil,
    CompareContact,
    Contact,
    Copy,
    Counter,
    Drum,
    End,
    Fill,
    ForLoop,
    Math,
    ModbusAddress,
    ModbusRtuTarget,
    ModbusTcpTarget,
    Next,
    Pack,
    Program,
    Project,
    RawInstruction,
    Receive,
    Return,
    Rung,
    Search,
    Send,
    Shift,
    Timer,
    Unpack,
    decode,
    decode_program,
    encode,
    read_csv,
    write_csv,
)

EXPECTED_ROOT_EXPORTS = (
    "encode",
    "decode",
    "decode_program",
    "read_csv",
    "write_csv",
    "Rung",
    "Program",
    "Project",
    "BlockCopy",
    "Call",
    "Contact",
    "CompareContact",
    "Counter",
    "Coil",
    "Drum",
    "Copy",
    "End",
    "Fill",
    "ForLoop",
    "Math",
    "Next",
    "ModbusAddress",
    "ModbusRtuTarget",
    "ModbusTcpTarget",
    "Pack",
    "Receive",
    "Send",
    "Timer",
    "Unpack",
    "RawInstruction",
    "Return",
    "Search",
    "Shift",
)


def test_root_public_api_manifest_is_explicit() -> None:
    assert tuple(laddercodec.__all__) == EXPECTED_ROOT_EXPORTS
    for name in EXPECTED_ROOT_EXPORTS:
        assert getattr(laddercodec, name) is not None


def test_root_public_api_supports_basic_roundtrip(tmp_path: Path) -> None:
    rung = Rung(
        logical_rows=1,
        conditions=[[Contact.from_csv_token("X001")] + [""] * 30],
        instructions=[Coil.from_csv_token("out(Y001)")],
        comment="Motor start circuit",
    )

    encoded = encode(rung)
    decoded = decode(encoded)

    assert isinstance(decoded, Rung)
    assert decoded.logical_rows == 1
    assert decoded.comment == "Motor start circuit"
    assert isinstance(decoded.conditions[0][0], Contact)
    assert isinstance(decoded.instructions[0], Coil)

    csv_path = tmp_path / "roundtrip.csv"
    write_csv(csv_path, [decoded])
    reread = read_csv(csv_path)

    assert len(reread) == 1
    assert reread[0].logical_rows == 1
    assert reread[0].conditions == decoded.conditions
    assert reread[0].instructions == decoded.instructions
    assert reread[0].comment == decoded.comment


def test_program_and_project_models_are_root_exports() -> None:
    main = Program(name="Main", prog_idx=0, rungs=[])
    project = Project(main=main)

    assert project.main is main
    assert project.subroutines == []


def test_advanced_helpers_remain_module_scoped() -> None:
    from laddercodec.csv.bundle import parse_bundle
    from laddercodec.decode import decode_rung, decode_rungs, inspect_cells

    assert callable(decode_rung)
    assert callable(decode_rungs)
    assert callable(inspect_cells)
    assert callable(parse_bundle)

    assert "decode_rung" not in laddercodec.__all__
    assert "decode_rungs" not in laddercodec.__all__
    assert "inspect_cells" not in laddercodec.__all__
    assert "parse_bundle" not in laddercodec.__all__


def test_root_imports_are_all_usable() -> None:
    # These assertions keep static imports above from becoming dead weight.
    assert encode
    assert decode
    assert decode_program
    assert read_csv
    assert write_csv
    assert Rung
    assert Program
    assert Project
    assert Contact
    assert CompareContact
    assert Coil
    assert Timer
    assert Counter
    assert Copy
    assert BlockCopy
    assert Fill
    assert Pack
    assert Unpack
    assert Math
    assert Shift
    assert Search
    assert Drum
    assert Call
    assert Return
    assert End
    assert ForLoop
    assert Next
    assert Send
    assert Receive
    assert ModbusAddress
    assert ModbusRtuTarget
    assert ModbusTcpTarget
    assert RawInstruction
