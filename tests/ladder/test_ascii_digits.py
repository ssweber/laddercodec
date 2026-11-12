"""Constants, counts and address numbers take the ASCII digits 0-9 only.

Python's ``\\d`` and ``int()`` accept every Unicode decimal digit (ARABIC-INDIC DIGIT
THREE, ``\\u0663``); CLICK's validators do not.  A Search text value follows the Compare
rule.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from pathlib import Path

import pytest

from laddercodec import FieldError, read_csv
from laddercodec.csv import CSV_HEADER
from laddercodec.csv.ast import AfCall
from laddercodec.instructions import parse_af_blob
from laddercodec.instructions.comparison import CompareContact
from laddercodec.instructions.contact import Contact
from laddercodec.instructions.copy import BlockCopy, Copy, Fill, Pack, Unpack
from laddercodec.instructions.counter import Counter
from laddercodec.instructions.drum import Drum, _check_duration
from laddercodec.instructions.drum import parse_af_call as parse_drum_call
from laddercodec.instructions.forloop import ForLoop
from laddercodec.instructions.math import Math
from laddercodec.instructions.out_variant import OutVariant
from laddercodec.instructions.raw import RawInstruction
from laddercodec.instructions.search import Search
from laddercodec.instructions.send_receive import ModbusAddress
from laddercodec.instructions.shift import Shift
from laddercodec.instructions.timer import Timer
from laddercodec.model import AddressError, InstructionType, check_address

ASCII = "3"
UNICODE = "٣"


def _termination(code: str) -> Copy:
    return Copy("DS1", "TXT1", format="binary", termination_code=code)


# (id, constructor taking the digit text).
CONSTRUCTORS: list[tuple[str, Callable[[str], object]]] = [
    ("address", lambda d: check_address(f"DS{d}", "x")),
    ("contact", lambda d: Contact(InstructionType.CONTACT_NO, f"X00{d}")),
    ("compare", lambda d: CompareContact("==", "DS1", d)),
    ("copy", lambda d: Copy(d, "DS1")),
    ("copy-dest", lambda d: Copy("1", f"DS{d}")),
    ("fill", lambda d: Fill(d, "DS1", "DS5")),
    ("search-source", lambda d: Search("DS1", "DS10", d, "DS20", "C20", "==")),
    ("search-table", lambda d: Search("DS1", f"DS1{d}", "1", "DS20", "C20", "==")),
    ("timer", lambda d: Timer("on_delay", "T1", "TD1", d, "Tms")),
    ("counter", lambda d: Counter("count_up", "CT1", "CTD1", d)),
    ("for", lambda d: ForLoop(d)),
    ("out-variant", lambda d: OutVariant("timed", "C1", "TD1", d, unit="Tms")),
    ("modbus-address", lambda d: ModbusAddress(d)),
    ("drum-duration", lambda d: _check_duration(d, "Drum.duration")),
    ("drum-duration-register", lambda d: _check_duration(f"DS{d}", "Drum.duration")),
    ("math", lambda d: Math(f"DS1 + {d}", "DS2", "decimal")),
    ("math-range", lambda d: Math(f"SUM ( DS1 : DS{d} )", "DS2", "decimal")),
    ("blockcopy", lambda d: BlockCopy("DS1", f"DS{d}", "DS10", "DS12")),
    ("pack", lambda d: Pack("C1", f"C{d}", "DS1")),
    ("unpack", lambda d: Unpack("DS1", "C1", f"C{d}")),
    ("shift", lambda d: Shift("C1", f"C{d}")),
    ("termination-code", lambda d: _termination(f"$0{d}")),
    ("math-address", lambda d: Math("DS1 + 1", f"DS{d}", "decimal")),
]

# Counter and Drum need pin rows or a syntax read_csv does not take; their constructors
# and checks are covered above.
# (id, condition-column token or None, AF token) with ``@`` where the digit goes.
CSV_TOKENS: list[tuple[str, str, str]] = [
    ("contact", "X00@", ""),
    ("contact-C", "C@", ""),
    ("compare", "DS1==@", ""),
    ("compare-real", "DF1==@.5", ""),
    ("copy", "C1", "copy(@,DS1)"),
    ("copy-hex", "C1", "copy(@Fh,DH1)"),
    ("copy-dest", "C1", "copy(1,DS@)"),
    ("fill", "C1", "fill(@,DS1..DS5)"),
    ("search", "C1", "search(DS1..DS10 == @,result=DS20,found=C20)"),
    ("search-table", "C1", "search(DS1..DS1@ == 1,result=DS20,found=C20)"),
    ("timer", "C1", "on_delay(T1,TD1,preset=@,unit=Tms)"),
    ("for", "C1", "for(@)"),
    ("out-variant", "C1", "timed(C1111,on_acc=TD18,on_preset=@,unit=Tms)"),
    ("math", "C1", "math(DS1 + @,DS2,mode=decimal)"),
    ("math-range", "C1", "math(SUM(DS1:DS@),DS2,mode=decimal)"),
    ("latch-range", "C1", "latch(C1..C@)"),
    ("out-range", "C1", "out(C1..C@)"),
    ("pack", "C1", "pack_bits(C1..C@,DS1)"),
    ("unpack", "C1", "unpack_to_bits(DS1,C1..C@)"),
    ("blockcopy", "C1", "blockcopy(DS1..DS@,DS10..DS12)"),
    ("shift", "C1", "shift(C1..C@)"),
    ("termination-code", "C1", "copy(DS1,TXT1,convert=to_binary(termination_code=$0@))"),
    ("math-address", "C1", "math(DS1 + 1,DS@,mode=decimal)"),
    (
        "receive-count",
        "C1",
        'receive(target=ModbusRtuTarget(name="rtu",com_port="cpu2",device_id=5),'
        "remote_start=ModbusAddress(address=40000@),dest=DS1..DS5,receiving=C1,success=C2,"
        "error=C3,exception_response=DS100)",
    ),
    (
        "send-dest",
        "C1",
        'send(target=ModbusRtuTarget(name="rtu",com_port="cpu2",device_id=5),'
        'remote_start="DS1",source=DS1..DS@,sending=C1,success=C2,error=C3,'
        "exception_response=DS100)",
    ),
    (
        "send-port",
        "C1",
        'send(target=ModbusTcpTarget(name="tcp",ip="1.2.3.4",port=50@,device_id=5),'
        'remote_start="DS1",source=DS1,sending=C1,success=C2,error=C3,exception_response=DS100)',
    ),
]


def _write(tmp_path: Path, cond: str, af: str) -> Path:
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", cond] + ["-"] * 30 + [af])
    return path


@pytest.mark.parametrize(("name", "build"), CONSTRUCTORS, ids=[c[0] for c in CONSTRUCTORS])
def test_constructor_takes_ascii_digit_only(name: str, build: Callable[[str], object]) -> None:
    build(ASCII)
    with pytest.raises(FieldError):
        build(UNICODE)


@pytest.mark.parametrize(("name", "cond", "af"), CSV_TOKENS, ids=[c[0] for c in CSV_TOKENS])
def test_read_csv_takes_ascii_digit_only(tmp_path: Path, name: str, cond: str, af: str) -> None:
    read_csv(_write(tmp_path, cond.replace("@", ASCII), af.replace("@", ASCII)))
    with pytest.raises(ValueError):
        read_csv(_write(tmp_path, cond.replace("@", UNICODE), af.replace("@", UNICODE)))


class TestSearchEmptyText:
    def _search(self, source: str) -> Search:
        return Search("TXT1", "TXT10", source, "DS20", "C20", "==")

    def test_empty_refused_through_constructor(self) -> None:
        with pytest.raises(FieldError, match=r"^Search\.source: .*1 to 128"):
            self._search('""')

    def test_empty_refused_through_read_csv(self, tmp_path: Path) -> None:
        af = 'search(TXT1..TXT10 == "",result=DS20,found=C20)'
        with pytest.raises(FieldError, match=r"^Search\.source: .*1 to 128"):
            read_csv(_write(tmp_path, "C1", af))

    @pytest.mark.parametrize(
        "source", ['"A"', '"AB"', '"$41"', '"' + "x" * 128 + '"', "$00", "$41"]
    )
    def test_text_and_code_accepted(self, source: str) -> None:
        assert self._search(source).source == source

    @pytest.mark.parametrize(
        "source",
        ['"' + "x" * 129 + '"', '"a"b"', '"é"'],
        ids=["129-chars", "inner-quote", "non-ascii"],
    )
    def test_refused_text(self, source: str) -> None:
        with pytest.raises(FieldError, match=r"^Search\.source: "):
            self._search(source)

    def test_refused_text_through_read_csv(self, tmp_path: Path) -> None:
        af = f'search(TXT1..TXT10 == "{"x" * 129}",result=DS20,found=C20)'
        with pytest.raises(FieldError, match=r"^Search\.source: "):
            read_csv(_write(tmp_path, "C1", af))

    def test_quoted_character_code_is_text_and_round_trips(self, tmp_path: Path) -> None:
        af = 'search(TXT1..TXT10 == "$41",result=DS20,found=C20)'
        search = read_csv(_write(tmp_path, "C1", af))[0].instructions[0]
        assert isinstance(search, Search) and search.source == '"$41"'
        bare = self._search("$41")
        blob = search.build_blob()
        assert blob != bare.build_blob()
        assert '"$41"'.encode("utf-16-le") in blob
        parsed = parse_af_blob(blob)
        assert isinstance(parsed, Search) and parsed.source == '"$41"'
        assert parsed.to_csv() == search.to_csv()

    def test_native_blob_with_empty_text_is_not_parsed(self) -> None:
        # decode() keeps a blob that parse_af_blob does not parse as a RawInstruction.
        blob = Search("TXT1", "TXT10", '"A"', "DS20", "C20", "==").build_blob()
        needle = '"A"'.encode("utf-16-le")
        assert blob.count(needle) == 1
        empty = blob.replace(needle, '""'.encode("utf-16-le"))
        assert parse_af_blob(empty) is None


@pytest.mark.parametrize("code", ["$\u0663", "$0x1", "$1_0", "$ 1", "$+1", "$", "$123", "$G1"])
def test_termination_code_is_two_hex_digits(code: str) -> None:
    with pytest.raises(FieldError, match="Copy.termination_code"):
        _termination(code)


def test_termination_code_accepts_two_hex_digits() -> None:
    assert _termination("$0d").termination_code == "$0D"


def _drum_pattern(cells: str) -> Drum:
    call = AfCall(
        name="event_drum",
        args=(),
        known=False,
        kwargs={
            "outputs": "[C1,C2]",
            "events": "[C3,C4]",
            "pattern": f"[[{cells}],[1,0]]",
            "current_step": "DS1",
            "completion_flag": "C5",
        },
        raw="event_drum(...)",
    )
    return parse_drum_call(call)


@pytest.mark.parametrize("cells", ["\u0661,0", "+1,0", "1_0,0", " 2,0", "01,0", "1,"])
def test_drum_pattern_cell_is_0_or_1(cells: str) -> None:
    with pytest.raises(ValueError):
        _drum_pattern(cells)


def test_drum_pattern_accepts_0_and_1() -> None:
    assert _drum_pattern("1,0").pattern == [[1, 0], [1, 0]]


def test_math_refuses_a_nickname_with_unicode_digits() -> None:
    with pytest.raises(FieldError, match="Math.expression.*nickname"):
        Math("DS1 + <n\u0663>", "DS2", "decimal")


def test_contact_with_unicode_digit_names_the_operand(tmp_path: Path) -> None:
    with pytest.raises(AddressError, match="^Contact.operand"):
        read_csv(_write(tmp_path, "X00\u0663", ""))


@pytest.mark.parametrize("fields", ["zz,1", "0x27_2,1", "0x2722,x", "0x2722,+1", "0x2722"])
def test_raw_token_header_is_hex_and_digits(fields: str) -> None:
    with pytest.raises(ValueError):
        RawInstruction._from_fields_token("Search", fields)
