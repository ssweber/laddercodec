"""Constants, counts and address numbers take the ASCII digits 0-9 only.

``\\d`` and ``int()`` accept every Unicode decimal digit (ARABIC-INDIC DIGIT THREE,
``\\u0663``); CLICK's validators do not.  Search refuses an empty text value.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from pathlib import Path

import pytest

from laddercodec import FieldError, read_csv
from laddercodec.csv import CSV_HEADER
from laddercodec.instructions import parse_af_blob
from laddercodec.instructions.comparison import CompareContact
from laddercodec.instructions.contact import Contact
from laddercodec.instructions.copy import Copy, Fill
from laddercodec.instructions.counter import Counter
from laddercodec.instructions.drum import _check_duration
from laddercodec.instructions.forloop import ForLoop
from laddercodec.instructions.math import Math
from laddercodec.instructions.out_variant import OutVariant
from laddercodec.instructions.search import Search
from laddercodec.instructions.send_receive import ModbusAddress
from laddercodec.instructions.timer import Timer
from laddercodec.model import InstructionType, check_address

ASCII = "3"
UNICODE = "٣"

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
        return Search("DS1", "DS10", source, "DS20", "C20", "==")

    def test_empty_refused_through_constructor(self) -> None:
        with pytest.raises(FieldError, match=r"^Search\.source: .*1 to 128"):
            self._search('""')

    def test_empty_refused_through_read_csv(self, tmp_path: Path) -> None:
        af = 'search(DS1..DS10 == "",result=DS20,found=C20)'
        with pytest.raises(FieldError, match=r"^Search\.source: .*1 to 128"):
            read_csv(_write(tmp_path, "C1", af))

    @pytest.mark.parametrize("source", ['"A"', '"AB"', '"' + "x" * 128 + '"', "$00", "$41"])
    def test_text_and_code_accepted(self, source: str) -> None:
        assert self._search(source).source == source

    @pytest.mark.parametrize(
        "source",
        ['"' + "x" * 129 + '"', '"$41"', '"a"b"', '"é"'],
        ids=["129-chars", "quoted-code", "inner-quote", "non-ascii"],
    )
    def test_refused_text(self, source: str) -> None:
        with pytest.raises(FieldError, match=r"^Search\.source: "):
            self._search(source)

    def test_refused_text_through_read_csv(self, tmp_path: Path) -> None:
        af = 'search(DS1..DS10 == "$41",result=DS20,found=C20)'
        with pytest.raises(FieldError, match=r"^Search\.source: "):
            read_csv(_write(tmp_path, "C1", af))

    def test_native_blob_with_empty_text_is_not_parsed(self) -> None:
        # decode() keeps a blob that parse_af_blob does not parse as a RawInstruction.
        blob = Search("DS1", "DS10", '"A"', "DS20", "C20", "==").build_blob()
        needle = '"A"'.encode("utf-16-le")
        assert blob.count(needle) == 1
        empty = blob.replace(needle, '""'.encode("utf-16-le"))
        assert parse_af_blob(empty) is None
