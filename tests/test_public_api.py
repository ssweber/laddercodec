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
    "CsvLocation",
    "find_v4_only",
    "is_v4_only",
    "check",
    "Finding",
    "Rung",
    "Program",
    "Project",
    "FieldError",
    "AddressError",
    "Reason",
    "Code",
    "CLICK_IDS",
    "LaddercodecError",
    "DecodeError",
    "EncodeError",
    "WriterError",
    "CsvError",
    "LegacyEncodingWarning",
    "RefusedFieldWarning",
    "UndecodedRungWarning",
    "UndecodedCommentWarning",
    "ConditionInstruction",
    "AfInstruction",
    "ConditionToken",
    "AfToken",
    "BlockCopy",
    "Call",
    "Contact",
    "CompareContact",
    "Counter",
    "Coil",
    "OutVariant",
    "Drum",
    "Copy",
    "Email",
    "End",
    "Fill",
    "ForLoop",
    "Home",
    "Math",
    "Next",
    "Break",
    "Continue",
    "ModbusAddress",
    "ModbusRtuTarget",
    "ModbusTcpTarget",
    "Pack",
    "Position",
    "Receive",
    "Send",
    "Timer",
    "Undecoded",
    "UnknownCondition",
    "UnknownInstruction",
    "Unpack",
    "Velocity",
    "RawInstruction",
    "Return",
    "Search",
    "Shift",
    "Tee",
    "BlockCopyConvert",
    "CoilKind",
    "CompareOp",
    "ContactKind",
    "CopyConvert",
    "CounterKind",
    "DrumKind",
    "MathMode",
    "ModbusRegisterType",
    "ModbusRtuPort",
    "ModbusTcpPort",
    "OutVariantKind",
    "OutVariantUnit",
    "PackKind",
    "ReceiveFunctionCode",
    "SendFunctionCode",
    "TimeUnit",
    "TimerKind",
    "UndecodedStop",
    "UnpackKind",
    "constant_text",
    "replace",
)


def test_root_public_api_manifest_is_explicit() -> None:
    assert tuple(laddercodec.__all__) == EXPECTED_ROOT_EXPORTS
    for name in EXPECTED_ROOT_EXPORTS:
        assert getattr(laddercodec, name) is not None


def test_root_public_api_supports_basic_roundtrip(tmp_path: Path) -> None:
    rung = Rung(
        conditions=[[Contact.from_csv_token("X001")] + [""] * 30],
        instructions=[Coil.from_csv_token("out(Y001)")],
        comment="Motor start circuit",
    )

    encoded = encode(rung)
    decoded_rungs = decode(encoded)

    assert isinstance(decoded_rungs, list) and len(decoded_rungs) == 1
    decoded = decoded_rungs[0]
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
    main = Program(name="Main", prog_idx=1, rungs=[])
    project = Project(main=main)

    assert project.main is main
    assert project.subroutines == []


def test_new_root_exports_are_their_home_module_objects() -> None:
    import importlib

    decode_mod = importlib.import_module("laddercodec.decode")
    from laddercodec import instructions
    from laddercodec.csv import converter, writer

    assert laddercodec.DecodeError is decode_mod.DecodeError
    assert laddercodec.WriterError is writer.WriterError
    assert laddercodec.CsvError is converter.CsvError
    assert laddercodec.UnknownCondition is instructions.UnknownCondition
    assert laddercodec.UnknownInstruction is instructions.UnknownInstruction
    assert laddercodec.Email is instructions.email.Email
    assert laddercodec.Home is instructions.home.Home
    assert laddercodec.Position is instructions.position.Position
    assert laddercodec.Velocity is instructions.velocity.Velocity
    codes = importlib.import_module("laddercodec.codes")
    assert laddercodec.Code is codes.Code
    assert laddercodec.CLICK_IDS is codes.CLICK_IDS
    assert laddercodec.CLICK_IDS[laddercodec.Code.ADDRESS_OUT_OF_RANGE] == ("OBJ-003",)
    unchecked = importlib.import_module("laddercodec.operands.unchecked")
    assert laddercodec.replace is unchecked.replace


def test_errors_form_one_tree_of_value_errors() -> None:
    from laddercodec.errors import LayoutError

    base = laddercodec.LaddercodecError
    assert issubclass(base, ValueError)
    for error in (
        laddercodec.DecodeError,
        laddercodec.EncodeError,
        laddercodec.CsvError,
        laddercodec.WriterError,
        laddercodec.FieldError,
        LayoutError,
    ):
        assert issubclass(error, base), error
    assert issubclass(laddercodec.AddressError, laddercodec.FieldError)
    assert not hasattr(laddercodec, "ConvertError")


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
    # Use each name imported at the top of the file, so that no import goes unused.
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
