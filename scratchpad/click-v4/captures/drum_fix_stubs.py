"""Write paste-test CSVs for the drum Jog func code + unused-pin-row fixes.

stubs/drum_fix.csv      event and time drums, every pin combination (paste in v3 and v4)
stubs/drum_fix_te.csv   time & event drums (v4 only)

Each rung n uses its own addresses: contacts C(2000+10n)..C(2000+10n+6), output
C(2100+n), done C(2200+n), step DS(1800+n), acc TD(120+n), jump step DS1850.
"""

from __future__ import annotations

import csv
from pathlib import Path

from laddercodec.csv.contract import CONDITION_COLUMNS, CSV_HEADER

HERE = Path(__file__).parent
WIDTH = len(CONDITION_COLUMNS)


def _row(marker: str, contact: str = "", af: str = "", *, t_at_b: bool = False, down_at_b: bool = False, wire: bool = True) -> list[str]:
    cells = (["-"] * WIDTH) if wire else ([""] * WIDTH)
    cells[0] = contact
    if t_at_b:
        cells[1] = "T"
    elif down_at_b:
        cells[1] = "|"
    return [marker, *cells, af]


def _drum(kind: str, n: int) -> str:
    out, done, step = f"C{2100 + n}", f"C{2200 + n}", f"DS{1800 + n}"
    if kind == "event":
        return f"event_drum(outputs=[{out}],events=[C{2000 + 10 * n + 9}],pattern=[[1]],current_step={step},completion_flag={done})"
    if kind == "time":
        return f"time_drum(outputs=[{out}],presets=[1000],unit=Tms,pattern=[[1]],current_step={step},accumulator=TD{120 + n},completion_flag={done})"
    return (
        f"time_event_drum(outputs=[{out}],presets=[1000],events=[C{2000 + 10 * n + 9}],unit=Tms,"
        f"pattern=[[1]],current_step={step},accumulator=TD{120 + n},completion_flag={done})"
    )


# (id, kind, pins): each pin is (name, legs) in pin order; legs = extra OR contacts under it.
CASES = [
    ("jog_only", [("reset", 0), ("jog", 0)]),
    ("jog_reset_or", [("reset", 1), ("jog", 0)]),
    ("jog_reset_or2", [("reset", 2), ("jog", 0)]),
    ("jump_only", [("reset", 0), ("jump", 0)]),
    ("jump_reset_or", [("reset", 1), ("jump", 0)]),
    ("all_pins", [("reset", 0), ("jump", 0), ("jog", 0)]),
    ("all_pins_reset_or", [("reset", 1), ("jump", 0), ("jog", 0)]),
]


def _rung(case_id: str, kind: str, pins: list[tuple[str, int]], n: int) -> list[list[str]]:
    contact = iter(f"C{2000 + 10 * n + k}" for k in range(9))
    drum = _drum(kind, n)
    rows = [["#", f"drum_fix__{kind}_{case_id}"], ["#", drum]]
    rows += [["#", f".{name}(DS1850)" if name == "jump" else f".{name}()"] for name, _ in pins]
    rows.append(_row("R", next(contact), drum))
    for name, legs in pins:
        label = f".{name}(DS1850)" if name == "jump" else f".{name}()"
        rows.append(_row("", next(contact), label, t_at_b=legs > 0))
        for k in range(legs):
            rows.append(_row("", next(contact), wire=False, down_at_b=k < legs - 1))
    return rows


def write(name: str, kinds: list[str]) -> None:
    rows: list[list[str]] = [list(CSV_HEADER)]
    n = 0
    for kind in kinds:
        for case_id, pins in CASES:
            n += 1
            rows += _rung(case_id, kind, pins, n)
    rows.append(_row("R", "-", "end()"))
    path = HERE / "stubs" / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)
    print(f"{path.name}: {n} drum rungs + end")


write("drum_fix.csv", ["event", "time"])
write("drum_fix_te.csv", ["time_event"])
