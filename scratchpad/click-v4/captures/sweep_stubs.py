"""Write paste-test CSVs for the DLL-sweep fixes (see /arc.md).

stubs/sweep_<group>.csv, one per group.  Each rung's comment is its id, then every
AF token it should decode to (tests/test_v4_captures.py checks that).

A rung is either
  reopen  the real instruction is pasted; in CLICK open its dialog and press OK
  build   a NOP placeholder is pasted; build the instruction from the comment
A reopen rung that the current encoder can't encode is downgraded to build.

Addresses are private to this arc (C only goes to C2000): contacts C1-C527 (C(1+100g+10k+j): group g, rung k, pin j),
outputs/flags C601-C723, DS2000+, DD300+, DF300+, TXT100+, TD130+.

Run from the laddercodec root:  uv run python scratchpad/click-v4/captures/sweep_stubs.py
"""

from __future__ import annotations

import csv
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from laddercodec import encode, read_csv
from laddercodec.csv.contract import CONDITION_COLUMNS, CSV_HEADER

HERE = Path(__file__).parent
WIDTH = len(CONDITION_COLUMNS)


@dataclass
class Case:
    id: str
    af: str
    mode: str  # "reopen" | "build"
    pins: list[str] = field(default_factory=list)  # pin tokens, e.g. ".reset()"


def _drum_time(unit: str, n: int, presets: str = "[1000,2000]") -> str:
    return (
        f"time_drum(outputs=[C{640 + 2 * n},C{641 + 2 * n}],presets={presets},unit={unit},"
        f"pattern=[[1,0],[0,1]],current_step=DS{2300 + n},accumulator=TD{130 + n},"
        f"completion_flag=C{660 + n})"
    )


def _drum_te(unit: str, n: int) -> str:
    return (
        f"time_event_drum(outputs=[C{640 + 2 * n},C{641 + 2 * n}],presets=[1000,2000],"
        f"events=[C{670 + 2 * n},C{671 + 2 * n}],unit={unit},pattern=[[1,0],[0,1]],"
        f"current_step=DS{2300 + n},accumulator=TD{130 + n},completion_flag=C{660 + n})"
    )


_TCP = 'ModbusTcpTarget(name="tcp",ip="192.168.1.20",port=502,device_id=1'
_STATUS_S = "sending=C{0},success=C{1},error=C{2},exception_response=DS{3}"
_STATUS_R = "receiving=C{0},success=C{1},error=C{2},exception_response=DS{3}"

GROUPS: dict[str, list[Case]] = {
    "search": [
        Case("search__text_eq", 'search(TXT101..TXT110 == "A",result=DS2001,found=C601)', "reopen"),
        Case("search__text_ne", 'search(TXT101..TXT110 != "A",result=DS2002,found=C602)', "reopen"),
        Case("search__text_ne_oneshot", 'search(TXT101..TXT110 != "A",result=DS2003,found=C603,oneshot=1)', "reopen"),
        Case("search__data_eq_oneshot", "search(DS2101..DS2110 == DS2100,result=DS2004,found=C604,oneshot=1)", "reopen"),
        Case("search__data_le_oneshot", "search(DS2101..DS2110 <= DS2100,result=DS2005,found=C605,oneshot=1)", "reopen"),
        Case("search__data_gt", "search(DS2101..DS2110 > DS2100,result=DS2006,found=C606)", "reopen"),
    ],
    "coil": [
        Case("coil__out_oneshot_immediate", "out(immediate(Y001),oneshot=1)", "build"),
        Case("coil__out_range_oneshot", "out(C611..C614,oneshot=1)", "build"),
        Case("coil__out_range_oneshot_immediate", "out(immediate(Y002..Y004),oneshot=1)", "build"),
    ],
    "copy": [
        Case("copy__df_text_real", "copy(DF301,TXT121,convert=to_text(exponential=0,termination_code=none))", "build"),
        Case("copy__df_text_exp", "copy(DF302,TXT122,convert=to_text(exponential=1,termination_code=none))", "reopen"),
        Case("copy__dd_df_value", "copy(DD301,DF303)", "build"),
        Case("copy__df_dd_value", "copy(DF304,DD302)", "build"),
        Case("copy__dd_df_binary", "copy(DD303,DF305,convert=to_binary)", "build"),
        Case("blockcopy__to_ascii_v4", "blockcopy(TXT151..TXT154,DS2201..DS2204,convert=to_ascii)", "reopen"),
    ],
    "drum": [
        Case("drum__time_th_jog", _drum_time("Th", 1), "reopen", [".reset()", ".jog()"]),
        Case("drum__time_th_jump_jog", _drum_time("Th", 2), "reopen", [".reset()", ".jump(DS2350)", ".jog()"]),
        Case("drum__te_th_jog", _drum_te("Th", 3), "reopen", [".reset()", ".jog()"]),
        Case("drum__time_tm_jog", _drum_time("Tm", 4), "reopen", [".reset()", ".jog()"]),
        Case("drum__time_ds_preset", _drum_time("Tms", 5, "[DS2311,1000]"), "reopen", [".reset()"]),
        Case("drum__time_ds_preset_th_jog", _drum_time("Th", 6, "[DS2312,1000]"), "reopen", [".reset()", ".jog()"]),
    ],
    "comm": [
        Case(
            "send__wlan",
            f'send(target={_TCP},com_port="wlan"),remote_start="DS1",source=DS2401,'
            + _STATUS_S.format(701, 702, 703, 2402) + ")",
            "build",
        ),
        Case(
            "receive__cpu3",
            'receive(target=ModbusRtuTarget(name="rtu",com_port="cpu3",device_id=2),remote_start="DS1",dest=DS2411,'
            + _STATUS_R.format(711, 712, 713, 2412) + ")",
            "build",
        ),
        Case(
            "send__slave_id_ds",
            'send(target=ModbusRtuTarget(name="rtu",com_port="cpu2",device_id=DS2420),remote_start="DS1",source=DS2421,'
            + _STATUS_S.format(721, 722, 723, 2422) + ")",
            "build",
        ),
    ],
    "math": [
        Case("math__w_literal", "math(DD501 + 100000,DD502,mode=decimal)", "reopen"),
        Case("math__w_literal_low", "math(DD503 + 40000,DD504,mode=decimal)", "reopen"),
        Case("math__h_literal_max", "math(DD505 + 32767,DD506,mode=decimal)", "reopen"),
    ],
}


def _row(marker: str, contact: str, af: str) -> list[str]:
    cells = ["-"] * WIDTH
    cells[0] = contact
    return [marker, *cells, af]


def _rows(case: Case, contacts: list[str], af: str) -> list[list[str]]:
    rows = [["#", case.id], ["#", case.af], *[["#", p] for p in case.pins]]
    rows.append(_row("R", contacts[0], af))
    for k, pin in enumerate(case.pins):
        rows.append(_row("", contacts[k + 1], pin if af != "NOP" else ""))
    return rows


def _encodes(rows: list[list[str]]) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "probe.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(CSV_HEADER)
            w.writerows(rows)
        try:
            encode(read_csv(path))
        except Exception:  # noqa: BLE001 - any failure means "can't paste the real thing"
            return False
    return True


def main() -> None:
    out_dir = HERE / "stubs"
    for g, (group, cases) in enumerate(GROUPS.items()):
        rows: list[list[str]] = []
        print(f"== sweep_{group}")
        for k, case in enumerate(cases):
            contacts = [f"C{1 + 100 * g + 10 * k + j}" for j in range(4)]
            mode = case.mode
            real = _rows(case, contacts, case.af)
            if mode == "reopen" and not _encodes(real):
                mode = "build (encoder can't produce it yet)"
            rows += real if mode == "reopen" else _rows(case, contacts, "NOP")
            print(f"  {case.id:36} {mode}")
        path = out_dir / f"sweep_{group}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(CSV_HEADER)
            w.writerows(rows)


if __name__ == "__main__":
    main()
