"""Test ``addresses()``: the addresses that CLICK looks up in the project when it pastes."""

from __future__ import annotations

import re
import struct
import warnings
from pathlib import Path

import pytest

from laddercodec import (
    CompareContact,
    Contact,
    Copy,
    End,
    FieldError,
    Math,
    ModbusTcpTarget,
    RawInstruction,
    Receive,
    Rung,
    Search,
    UnknownCondition,
    addresses,
    csv_rows,
    decode,
    encode,
    read_csv,
)
from laddercodec.binary_helpers import _build_blob, _tagged_field, _variant_tagged_field
from laddercodec.instructions.math_formula import parse
from laddercodec.instructions.raw import _decompose_blob
from laddercodec.operands.address import parse_address, read_as_typed
from laddercodec.paste import _cells, _field_addresses, _read_operand
from laddercodec.topology import GRID_FIRST_ROW_START
from laddercodec.undecoded import Undecoded, UndecodedRungWarning, markers

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN_CSVS = sorted((FIXTURES / "ladder_captures" / "golden").glob("*.csv")) + sorted(
    (FIXTURES / "coverage" / "golden").glob("*.csv")
)
CAPTURES = sorted((FIXTURES / "v4_captures").rglob("*.bin")) + [
    FIXTURES / "tumbler" / "main.clipboard.bin"
]

# The blobs of a Copy of "A"B" into TXT1 and a Search of TXT1..TXT10 for "A"B", from a
# clipboard capture. The Copy stores its end, TXT3, in 0x6077. The Search stores DS30 and
# C101 in 0x6079 and 0x607A.
_COPY_BLOB = bytes.fromhex(
    "43006f007000790000002127000001000d0000007460ffffffff2200410022004200220000007560ffffff"
    "ff00007660ffffffff540058005400310000007760ffffffff540058005400330000000622ffffffff3000"
    "0000f811ffffffff300000002322ffffffff300000001832ffffffff380039003600300000002722ffffff"
    "ff300000002112ffffffff300000001632ffffffff300000000112ffffffff2d00310000000000ffffffff"
    "0000"
)
_SEARCH_BLOB = bytes.fromhex(
    "53006500610072006300680000002227000001000a0000006560ffffffff22004100220042002200000066"
    "60ffffffff540058005400310000006760ffffffff5400580054003100300000007960ffffffff44005300"
    "3300300000007a60ffffffff430031003000310000007712ffffffff300000001832ffffffff3800390036"
    "0034000000f811ffffffff30000000f721ffffffff300000000000ffffffff0000"
)


def _email_blob() -> bytes:
    """Return the blob of an Email that stores TXT12 and TXT13 in its indexed slots.

    Each slot holds the tag, a 4-byte index and the value. Index 0 and the 0x68B0 slot
    are empty, and index 3 holds text that is not an address."""
    fields = [
        _tagged_field(0x6081, "TXT11"),
        _variant_tagged_field(0x68B1, struct.pack("<I", 0), ""),
        _variant_tagged_field(0x68B1, struct.pack("<I", 1), "TXT12"),
        _variant_tagged_field(0x68B1, struct.pack("<I", 2), "TXT13"),
        _variant_tagged_field(0x68B1, struct.pack("<I", 3), "Hello"),
        _variant_tagged_field(0x68B0, struct.pack("<I", 0), ""),
        _tagged_field(0x0000, ""),
    ]
    header = struct.pack("<IHI", 0x2737, 1, len(fields))
    return "Email\0".encode("utf-16-le") + header + b"".join(fields)


_EMAIL_BLOB = _email_blob()

# Address text in a CSV cell, outside quotes. The tests read it as a person reads the
# CSV, to check addresses() against.
_QUOTED = re.compile(r'"[^"]*"')
_WORD = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z]{1,3}[0-9]{1,5}[uU]?)(?![A-Za-z0-9_])")


def _rung(af: object, condition: object = "-") -> Rung:
    return Rung([[condition] + ["-"] * 30], [af], None)


def _csv_addresses(rungs: list[Rung]) -> set[str]:
    """Return the addresses that the CSV text of *rungs* names outside quotes and comments."""
    found: set[str] = set()
    for row in csv_rows(rungs):
        if row[0] == "#":
            continue
        for cell in row[1:]:
            for word in _WORD.findall(_QUOTED.sub("", cell)):
                address = parse_address(read_as_typed(word))
                if address is not None:
                    found.add(address.display)
    return found


def _formula_addresses(rungs: list[Rung]) -> set[str]:
    """Return the operands of each Math formula in *rungs* that CLICK's Math dialog accepts."""
    found: set[str] = set()
    for rung in rungs:
        for token in rung.instructions:
            if not isinstance(token, Math):
                continue
            try:
                found.update(parse(token.expression, token.mode).operands)
            except FieldError:
                continue  # a decoded Math that holds a refusal
    return found


@pytest.mark.parametrize(
    ("af", "expected"),
    [
        pytest.param(Copy('"HALLO"', "TXT1"), ["TXT1", "TXT5"], id="text-copy-end"),
        pytest.param(Copy('"A"B"', "TXT1"), ["TXT1", "TXT3"], id="text-copy-lone-quote"),
        pytest.param(Copy('"A""B"', "TXT1"), ["TXT1", "TXT4"], id="text-copy-doubled-quote"),
        pytest.param(Copy('"DS1"', "TXT1"), ["TXT1", "TXT3"], id="quoted-address"),
        pytest.param(Copy("5", "DS1"), ["DS1"], id="number"),
        pytest.param(Copy("FFh", "DH1"), ["DH1"], id="hex"),
        pytest.param(Copy("DS[DS2]", "DS5"), ["DS2", "DS5"], id="pointer-source"),
        pytest.param(Copy('"AB"', "TXT[DS2]"), ["DS2"], id="pointer-dest"),
        pytest.param(
            Search("TXT1", "TXT10", '"A"', "DS30", "C101", "=="),
            ["TXT1", "TXT10", "DS30", "C101"],
            id="search-range",
        ),
        pytest.param(
            Math("SUM ( DS1 : DS3 ) + DS10", "DS20"),
            ["DS20", "DS1", "DS3", "DS10"],
            id="math-range-ends",
        ),
        pytest.param(Math("XD0u AND 1h", "DH1", mode="hex"), ["DH1", "XD0u"], id="math-hex"),
    ],
)
def test_lists_each_address_of_an_instruction(af: object, expected: list[str]) -> None:
    rung = _rung(af)
    assert addresses(rung) == expected
    assert addresses(encode(rung)) == expected


def test_reads_no_address_inside_quoted_text() -> None:
    rung = _rung("NOP", CompareContact("==", "TXT1", '"DS1"'))
    assert addresses(rung) == ["TXT1"]


def test_lists_the_addresses_of_raw_cells() -> None:
    copy = RawInstruction("Copy", _COPY_BLOB, rows=2, sub=2)
    search = RawInstruction("Search", _SEARCH_BLOB, rows=2, sub=2)
    rungs = [
        _rung(copy, Contact("X001")),
        _rung(search, Contact("X002")),
        _rung(copy, Contact("X001")),
        _rung(search, Contact("X002")),
        _rung(End()),
    ]
    expected = ["X001", "TXT1", "TXT3", "X002", "TXT10", "DS30", "C101"]
    assert addresses(rungs) == expected
    assert addresses(encode(rungs)) == expected


def test_reads_only_operand_tags_of_an_unknown_class() -> None:
    # 0x6066 holds an address and 0x6074 a quoted text. 0x6208 holds a name, not an operand.
    blob = _build_blob(
        "Unknown", 0x27FF, (0x6066, 0x6074, 0x6208, 0x3218), ["DS5", '"DS6"', "DS7", "5"]
    )
    assert addresses(_rung(RawInstruction("Unknown", blob))) == ["DS5"]


def test_lists_the_end_of_a_receive() -> None:
    rungs = read_csv(FIXTURES / "coverage" / "golden" / "receive__rtu_click_block.csv")
    assert "DS5" in addresses(rungs)


def test_lists_the_remote_start_of_a_receive() -> None:
    # DS50 is an address in the other PLC. The payload stores it, so the list holds it.
    target = ModbusTcpTarget(name="tcp", ip="192.168.1.10", port=502, device_id=1)
    rung = _rung(Receive(target, "DS50", "DS1", 5, "C1", "C2", "C3", "DS100"))
    expected = ["C1", "C2", "C3", "DS100", "DS50", "DS1", "DS5", "SD50", "SD60"]
    assert addresses(rung) == expected
    assert addresses(encode(rung)) == expected


def test_lists_the_outputs_and_done_bit_of_a_time_drum() -> None:
    # The blob of this drum stores no done bit. T4 is the done bit of the accumulator TD4.
    rungs = read_csv(FIXTURES / "coverage" / "golden" / "time_drum__basic.csv")
    expected = ["C205", "DS185", "TD4", "T4", "C208", "C206", "C207", "C209"]
    assert addresses(rungs) == expected
    assert addresses(encode(rungs)) == expected


def test_lists_the_addresses_in_an_email_array() -> None:
    rung = _rung(RawInstruction("Email", _EMAIL_BLOB))
    assert addresses(rung) == ["TXT11", "TXT12", "TXT13"]
    assert addresses(encode(rung)) == ["TXT11", "TXT12", "TXT13"]


def test_reads_an_unknown_condition() -> None:
    # A Contact blob under a class name that no parser knows decodes as an unknown condition.
    data = encode(_rung(Copy("DS1", "DS2"), Contact("X001")))
    data = data.replace("Contact".encode("utf-16-le"), "Unknown".encode("utf-16-le"))
    assert isinstance(decode(data)[0].conditions[0][0], UnknownCondition)
    assert addresses(data) == ["X001", "DS1", "DS2"]


def _where(caught: pytest.WarningsRecorder) -> list[tuple[int, int | None, int | None]]:
    """Return the rung, row and column of each UndecodedRungWarning in *caught*."""
    return [(w.message.marker.rung, w.message.marker.row, w.message.marker.column) for w in caught]


def test_warns_where_decode_stops_for_a_row_it_cannot_walk() -> None:
    # One changed byte in rung 1, row 0 hides the end of a cell, so the walk stops there.
    data = bytearray(
        encode(
            [
                _rung(Copy('"HALLO"', "TXT1"), Contact("X001")),
                _rung(Copy("DS1", "DS2"), Contact("X002")),
            ]
        )
    )
    data[0x21B6] = 0x29
    with pytest.warns(UndecodedRungWarning) as decoded:
        decode(bytes(data))
    with pytest.warns(UndecodedRungWarning) as caught:
        assert addresses(data) == ["X001", "TXT1", "TXT5"]
    assert (
        _where(caught) == [(m.rung, m.row, m.column) for m in _markers(decoded)] == [(1, 0, None)]
    )
    assert [m.to_the_end for m in _markers(caught)] == [m.to_the_end for m in _markers(decoded)]
    assert [m.to_the_end for m in _markers(caught)] == [True]


def test_warns_for_a_cell_whose_fields_it_cannot_read() -> None:
    data = bytearray(encode(_rung(Copy('"HALLO"', "TXT1"), Contact("X001"))))
    # Cell A's blob starts at +0x25 with the class name ContactNO. Its part count follows
    # at +0x18 of the blob. A part count of 0xFF01 runs past the end of the blob.
    data[GRID_FIRST_ROW_START + 0x25 + 0x19] = 0xFF
    with pytest.warns(UndecodedRungWarning) as caught:
        assert addresses(data) == ["TXT1", "TXT5"]
    assert _where(caught) == [(0, 0, 0)]


def test_warns_for_a_cell_and_for_a_later_row_of_the_same_rung() -> None:
    # Cell A of rung 0, row 0 can't be read. A changed byte in rung 0, row 1 then stops
    # the walk, and decode() stops at the same row.
    first = Rung(
        [[Contact("X001")] + ["-"] * 30, [Contact("X003")] + ["-"] * 30],
        [Copy('"HALLO"', "TXT1"), Copy("DS7", "DS8")],
        None,
    )
    data = bytearray(encode([first, _rung(Copy("DS1", "DS2"), Contact("X002"))]))
    data[GRID_FIRST_ROW_START + 0x25 + 0x19] = 0xFF
    data[0x13A8] = 0xC0
    with pytest.warns(UndecodedRungWarning) as decoded:
        decode(bytes(data))
    with pytest.warns(UndecodedRungWarning) as caught:
        assert addresses(data) == ["TXT1", "TXT5"]
    assert [(m.rung, m.row) for m in _markers(decoded)] == [(0, 1)]
    assert _where(caught) == [(0, 0, 0), (0, 1, None)]


def _markers(caught: pytest.WarningsRecorder) -> list[Undecoded]:
    """Return the marker of each UndecodedRungWarning in *caught*."""
    return [w.message.marker for w in caught]


@pytest.mark.parametrize("payload", ["prog.bin", None])
def test_refuses_text_and_none(payload: object) -> None:
    with pytest.raises(TypeError, match=r"^addresses\(\) reads a Rung"):
        addresses(payload)  # ty: ignore[invalid-argument-type]


def test_reads_the_formula_of_a_math_with_empty_operand_slots() -> None:
    # CLICK saved these Math boxes as typed, with the addresses in the formula only.
    found = addresses((FIXTURES / "v4_captures" / "retyped" / "math_wide.bin").read_bytes())
    assert {"XD0", "XD0u", "XD3", "YD1"} <= set(found)
    # XD1 and XD2 lie between the ends of MAX ( XD0 : XD3 ).
    assert not {"XD1", "XD2"} & set(found)


def test_accepts_a_bytearray() -> None:
    data = encode(_rung(Copy('"HALLO"', "TXT1")))
    assert addresses(bytearray(data)) == addresses(memoryview(data)) == ["TXT1", "TXT5"]


@pytest.mark.parametrize("path", GOLDEN_CSVS, ids=lambda p: p.stem)
def test_golden_lists_every_address_of_its_csv(path: Path) -> None:
    rungs = read_csv(path)
    found = addresses(path.with_suffix(".bin").read_bytes())
    assert addresses(rungs) == found
    assert _csv_addresses(rungs) | _formula_addresses(rungs) <= set(found)
    assert len(found) == len(set(found))


@pytest.mark.parametrize("path", CAPTURES, ids=lambda p: p.relative_to(FIXTURES).as_posix())
def test_capture_lists_every_address_of_its_csv(path: Path) -> None:
    data = path.read_bytes()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        rungs = decode(data)
    wanted = _csv_addresses(rungs) | _formula_addresses(rungs)
    assert wanted <= set(addresses(data))
    if not markers(rungs):
        # The encoder may write a payload that differs from CLICK's, so this checks the
        # rungs against their own encoded bytes.
        assert wanted <= set(addresses(rungs))
        assert addresses(rungs) == addresses(encode(rungs))


# The fields that hold an address that addresses() leaves out on purpose. A Math stores
# copies of its formula in 0x61FF, 0x6228 and 0x6229, and the addresses between the ends
# of each range in 0x688C.
_NOT_LISTED = {("Math", 0x61FF), ("Math", 0x6228), ("Math", 0x6229), ("Math", 0x688C)}
ALL_BINS = sorted(FIXTURES.rglob("*.bin"))


def test_lists_every_field_that_holds_an_address() -> None:
    """Check that the list of each blob of each fixture holds every address in its fields.

    A field holds an address when a word of its text outside quotes reads as one. The
    fields in _NOT_LISTED are the exceptions. A field of a kind that addresses() does not
    read fails this test. The payloads are every fixture .bin and an Email whose indexed
    slots hold addresses."""
    missed: dict[tuple[str, int], str] = {}
    email = encode(_rung(RawInstruction("Email", _EMAIL_BLOB)))
    payloads = [(path.name, path.read_bytes()) for path in ALL_BINS] + [("email", email)]
    for name, data in payloads:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cells = list(_cells(data, {}))
            listed = set(addresses(data))
        for _, _, _, blob in cells:
            class_name, _, _, _, fields = _decompose_blob(blob)
            in_blob = set(_field_addresses(class_name, fields))
            assert in_blob <= listed
            for tag, _, value in fields:
                if (class_name, tag) in _NOT_LISTED:
                    continue
                for word in [value, *_WORD.findall(_QUOTED.sub("", value))]:
                    address = _read_operand(word)
                    if address is not None and address not in in_blob:
                        missed.setdefault((class_name, tag), f"{name}: {value!r}")
    assert missed == {}
