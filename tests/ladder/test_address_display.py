"""Every address an instruction holds is in CLICK's display form.

CLICK normalizes an address as it is typed: C001 becomes C1, and X1 becomes X001 (user
dialog check 2026-11-11, scratchpad/validation/arc.md Q-D5).  laddercodec follows
pyclickplc's display form: X and Y pad to 3 digits, every other bank is unpadded, the bank
is uppercase, and XD0u keeps its lowercase ``u``.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from laddercodec import encode, read_csv
from laddercodec.csv import CSV_HEADER
from laddercodec.decode import Rung
from laddercodec.instructions import Contact, Copy, Drum
from laddercodec.instructions.send_receive import ModbusRtuTarget, ModbusTcpTarget
from laddercodec.model import (
    ADDRESS_BANKS,
    AddressError,
    InstructionType,
    check_address,
    normalize_address,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class TestNormalizeAddress:
    @pytest.mark.parametrize(
        ("typed", "display"),
        [
            # X and Y pad to 3 digits.
            ("X1", "X001"),
            ("X001", "X001"),
            ("X0001", "X001"),
            ("x21", "X021"),
            ("Y1", "Y001"),
            ("y21", "Y021"),
            ("Y816", "Y816"),
            # Every other bank is unpadded.
            ("C001", "C1"),
            ("c1", "C1"),
            ("C2000", "C2000"),
            ("T01", "T1"),
            ("CT001", "CT1"),
            ("sc050", "SC50"),
            ("ds07", "DS7"),
            ("DS4500", "DS4500"),
            ("Dd01", "DD1"),
            ("dh0500", "DH500"),
            ("DF001", "DF1"),
            ("td1", "TD1"),
            ("CTD0250", "CTD250"),
            ("sd01", "SD1"),
            ("txt0001", "TXT1"),
            # XD and YD: XD0, XD0u, XDn.
            ("XD0", "XD0"),
            ("XD00", "XD0"),
            ("xd0u", "XD0u"),
            ("XD0U", "XD0u"),
            ("yd01", "YD1"),
            ("YD8", "YD8"),
            # A u suffix outside XD0 is kept for check_address to refuse.
            ("x1u", "X001u"),
            ("ds01U", "DS1u"),
            # A pointer normalizes both parts.
            ("ds[ds01]", "DS[DS1]"),
            ("DD[DS007]", "DD[DS7]"),
        ],
    )
    def test_display_form(self, typed: str, display: str) -> None:
        assert normalize_address(typed) == display
        assert normalize_address(display) == display

    def test_every_bank(self) -> None:
        for bank in ADDRESS_BANKS:
            lo, hi = ADDRESS_BANKS[bank]
            for number in (max(lo, 1), hi):
                display = f"{bank}{number:03d}" if bank in ("X", "Y") else f"{bank}{number}"
                assert normalize_address(f"{bank.lower()}0{number}") == display
                assert check_address(display, "f").number == number

    @pytest.mark.parametrize(
        "text",
        ["", "1", "-5", "1.5", "1Eh", "FFh", '"A"', '"c001"', "$41", "Q01", "ABCD1", " X1",
         "X1 ", "C-1", "C123456", "X١", "DS[DS1", "QQ[DS1]"],
    )  # fmt: skip
    def test_other_text_unchanged(self, text: str) -> None:
        assert normalize_address(text) == text

    @pytest.mark.parametrize(
        ("typed", "message"),
        [
            ("Q01", r"^Contact\.operand: 'Q01' has no CLICK bank 'Q'"),
            ("X1 ", r"^Contact\.operand: 'X1 ' is not a CLICK address$"),
            ("C123456", r"^Contact\.operand: 'C123456' is not a CLICK address$"),
            ("X١", r"^Contact\.operand: 'X١' is not a CLICK address$"),
            ("x017", r"^Contact\.operand: 'X017' is outside X001-X016"),
            ("x1u", r"^Contact\.operand: 'X001u' is outside X001-X016"),
            ("c02001", r"^Contact\.operand: 'C2001' is outside C1-C2000$"),
            ("ds1", r"^Contact\.operand: 'DS1' is not allowed; Contact\.operand takes X, Y, C"),
        ],
    )
    def test_refused_forms_still_refused(self, typed: str, message: str) -> None:
        with pytest.raises(AddressError, match=message):
            Contact(InstructionType.CONTACT_NO, typed)


def _rung_csv(path: Path, condition: str, af: str) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerow(["R", condition] + ["-"] * 30 + [af])
        if af.startswith(("count_", "event_drum", "time_drum", "time_event_drum")):
            w.writerow(["", "X002"] + ["-"] * 30 + [".reset()"])
    return path


#: (typed condition, its display form)
CONDITIONS = [
    ("x1", "X001"),
    ("~c001", "~C1"),
    ("X02.immediate", "X002.immediate"),
    ("rise(c0005)", "rise(C5)"),
    ("ds01==ds2", "DS1==DS2"),
    ("DS07>5", "DS7>5"),
    ('txt01=="A"', 'TXT1=="A"'),
    ("xd0u==FFh", "XD0u==FFh"),
]

#: (typed AF token, its display form)
INSTRUCTIONS = [
    ("out(y1)", "out(Y001)"),
    ("out(C001..C0010)", "out(C1..C10)"),
    ("latch(immediate(y1..y2))", "latch(immediate(Y001..Y002))"),
    ("reset(sc050)", "reset(SC50)"),
    ("toggle(c01101)", "toggle(C1101)"),
    (
        "debounce(C1104,on_acc=td03,on_preset=ds01,off_acc=TD004,off_preset=200,unit=Tms)",
        "debounce(C1104,on_acc=TD3,on_preset=DS1,off_acc=TD4,off_preset=200,unit=Tms)",
    ),
    ("on_delay(t02,td02,preset=ds05,unit=Tms)", "on_delay(T2,TD2,preset=DS5,unit=Tms)"),
    ("count_up(ct02,ctd02,preset=dd01)", "count_up(CT2,CTD2,preset=DD1)"),
    ("shift(c01041..c01048)", "shift(C1041..C1048)"),
    (
        "event_drum(outputs=[y1,c0184],events=[x1,c0186],pattern=[[1,0],[0,1]],"
        "current_step=ds0182,completion_flag=c0187)",
        "event_drum(outputs=[Y001,C184],events=[X001,C186],pattern=[[1,0],[0,1]],"
        "current_step=DS182,completion_flag=C187)",
    ),
    (
        "time_drum(outputs=[C1361,C1362],presets=[ds01302,1000],unit=Tms,"
        "pattern=[[1,0],[0,1]],current_step=DS1206,accumulator=td0106,completion_flag=C1406)",
        "time_drum(outputs=[C1361,C1362],presets=[DS1302,1000],unit=Tms,"
        "pattern=[[1,0],[0,1]],current_step=DS1206,accumulator=TD106,completion_flag=C1406)",
    ),
    ("for(ds01)", "for(DS1)"),
    ("copy(ds[ds01],dd001)", "copy(DS[DS1],DD1)"),
    ("copy(3.14,df01)", "copy(3.14,DF1)"),
    ("blockcopy(DS028..DS031,ds32..ds35)", "blockcopy(DS28..DS31,DS32..DS35)"),
    ("fill(ds01,DS052..DS055)", "fill(DS1,DS52..DS55)"),
    ("pack_bits(c0108..c0123,ds0167)", "pack_bits(C108..C123,DS167)"),
    ("unpack_to_bits(ds0172,c0128..c0143)", "unpack_to_bits(DS172,C128..C143)"),
    (
        "search(ds0144..ds0153 == ds0143,result=ds0154,found=c093,continuous=1)",
        "search(DS144..DS153 == DS143,result=DS154,found=C93,continuous=1)",
    ),
    (
        "math(ds01 + SUM(x1:x16),df01,mode=decimal)",
        "math(DS1 + SUM ( X001 : X016 ),DF1,mode=decimal)",
    ),
    ("math(dh01 AND 0Fh,yd0u,mode=hex)", "math(DH1 AND 0Fh,YD0u,mode=hex)"),
    (
        'send(target=ModbusTcpTarget(name="tcp",ip="192.168.1.10",port=502,device_id=ds02),'
        'remote_start="c001",source=c011..c012,sending=c01,success=c02,error=c03)',
        'send(target=ModbusTcpTarget(name="tcp",ip="192.168.1.10",port=502,device_id=DS2),'
        'remote_start="C1",source=C11..C12,sending=C1,success=C2,error=C3)',
    ),
    (
        'receive(target=ModbusRtuTarget(name="rtu",com_port="cpu2",device_id=5),'
        'remote_start="ds01",dest=ds01..ds05,receiving=c01,success=c02,error=c03,'
        "exception_response=ds0100)",
        'receive(target=ModbusRtuTarget(name="rtu",com_port="cpu2",device_id=5),'
        'remote_start="DS1",dest=DS1..DS5,receiving=C1,success=C2,error=C3,'
        "exception_response=DS100)",
    ),
    (
        'receive(target=ModbusRtuTarget(name="rtu",com_port="cpu2",device_id=5),'
        'remote_start="x1",dest=y1..y2)',
        'receive(target=ModbusRtuTarget(name="rtu",com_port="cpu2",device_id=5),'
        'remote_start="X001",dest=Y001..Y002)',
    ),
]


class TestThroughCsv:
    @pytest.mark.parametrize(("typed", "display"), CONDITIONS)
    def test_condition(self, tmp_path: Path, typed: str, display: str) -> None:
        (rung,) = read_csv(_rung_csv(tmp_path / "typed.csv", typed, "out(Y001)"))
        (shown,) = read_csv(_rung_csv(tmp_path / "shown.csv", display, "out(Y001)"))
        assert rung.conditions[0][0].to_csv() == display
        assert rung == shown
        assert encode(rung) == encode(shown)

    @pytest.mark.parametrize(("typed", "display"), INSTRUCTIONS)
    def test_instruction(self, tmp_path: Path, typed: str, display: str) -> None:
        (rung,) = read_csv(_rung_csv(tmp_path / "typed.csv", "X001", typed))
        (shown,) = read_csv(_rung_csv(tmp_path / "shown.csv", "X001", display))
        assert rung.instructions[0].to_csv() == display
        assert rung == shown
        assert encode(rung) == encode(shown)


class TestConstructor:
    def test_contact(self) -> None:
        assert Contact(InstructionType.CONTACT_NO, "x1") == Contact(
            InstructionType.CONTACT_NO, "X001"
        )

    def test_copy_pointer(self) -> None:
        copy = Copy("dd[ds01]", "ds0002")
        assert (copy.source, copy.destination) == ("DD[DS1]", "DS2")

    def test_drum_lists_and_jump(self) -> None:
        drum = Drum(
            drum_kind="event",
            outputs=["y1", "C002"],
            events_or_presets=["x1", "c03"],
            pattern=[[1, 0], [0, 1]],
            current_step="ds01",
            completion_flag="c09",
            jump_enabled=True,
            jump_target="ds002",
        )
        assert drum.outputs == ["Y001", "C2"]
        assert drum.events_or_presets == ["X001", "C3"]
        assert (drum.current_step, drum.completion_flag, drum.jump_target) == ("DS1", "C9", "DS2")

    @pytest.mark.parametrize("target", [ModbusRtuTarget, ModbusTcpTarget])
    def test_slave_id_address(self, target: type) -> None:
        if target is ModbusRtuTarget:
            made = target(name="r", com_port="cpu2", device_id="ds02420")
        else:
            made = target(name="t", ip="1.2.3.4", port=502, device_id="ds02420")
        assert made.device_id == "DS2420"


_ADDRESS_TOKEN = re.compile(r"(?<![A-Za-z0-9_$.<])([A-Z]{1,3})([0-9]{1,5})(u?)(?![A-Za-z0-9_])")
#: AF tokens whose fields are opaque tag text, not addresses laddercodec reads.
_OPAQUE = ("raw(", "email(", "home(", "position(", "velocity(")


def _loosen(cell: str) -> str:
    """Write each address outside quotes in lowercase with a leading zero."""
    if cell.startswith(_OPAQUE):
        return cell

    def loose(m: re.Match[str]) -> str:
        if m.group(1) not in ADDRESS_BANKS:
            return m.group(0)
        return f"{m.group(1).lower()}0{m.group(2)}{m.group(3).upper()}"

    parts = cell.split('"')
    parts[::2] = [_ADDRESS_TOKEN.sub(loose, part) for part in parts[::2]]
    return '"'.join(parts)


def _fixture_csvs() -> list[Path]:
    return sorted(FIXTURES.rglob("*.csv"))


@pytest.mark.parametrize("path", _fixture_csvs(), ids=lambda p: p.relative_to(FIXTURES).as_posix())
def test_fixture_csv_reads_the_same_with_loose_addresses(tmp_path: Path, path: Path) -> None:
    """Every fixture CSV, its addresses lowercased and zero-padded, reads as the same rungs."""
    try:
        rungs: list[Rung] = read_csv(path)
    except ValueError:
        pytest.skip("the fixture itself does not read")
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    loosened = [
        row if not row or row[0].startswith("#") else [row[0], *map(_loosen, row[1:])]
        for row in rows
    ]
    if loosened == rows:
        pytest.skip("no address to loosen")
    loose = tmp_path / path.name
    with loose.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(loosened)
    assert read_csv(loose) == rungs
