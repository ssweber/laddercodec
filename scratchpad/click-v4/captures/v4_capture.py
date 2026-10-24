"""CLICK v4 capture stubs: pyrung writes the expected tokens, CLICK supplies the blobs.

Each case is one rung written with the v4 verbs.  pyrung exports it, and the
exported AF tokens become the rung comment:

    line 1      the rung id (``out__debounce_both``)
    line 2..n   every non-empty AF cell, in row order, exactly as laddercodec
                should decode it

The paste CSV carries that comment over a placeholder the codec can already
encode: NOP for the Out variants, a v3 ``time_drum`` for the Time & Event
drum (switch the base in the dialog), and the real instruction for math and
register-duration time drums (try those as-is first).

Usage (from the pyrung repo root):

    uv run python scratchpad/click-v4/captures/v4_capture.py

writes ``stubs/<group>.csv`` (paste these) and ``expected/<group>.csv``
(pyrung's own export, for reference).  Address map: README.md.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from pathlib import Path

from pyrung import (
    Block,
    Bool,
    Dint,
    Int,
    Program,
    Real,
    Rung,
    TagType,
    Timer,
    Word,
    calc,
    comment,
    debounce,
    flasher,
    immediate,
    time_drum,
    time_event_drum,
    timed,
    toggle,
)
from pyrung.click import ClickBlocks, LadderExportError, TagMap, pyrung_to_ladder

HERE = Path(__file__).resolve().parent

x, y, c, t, ct, sc, ds, dd, dh, df, xd, yd, xd0u, yd0u, td, ctd, sd, txt = ClickBlocks()

_BLOCKS = {"X": x, "Y": y, "C": c, "DS": ds, "DD": dd, "DH": dh, "DF": df, "TD": td}
_TYPES = {"X": Bool, "Y": Bool, "C": Bool, "DS": Int, "DD": Dint, "DH": Word, "DF": Real, "TD": Int}
_TAG_TYPES = {"C": TagType.BOOL, "DS": TagType.INT, "DD": TagType.DINT, "DH": TagType.WORD,
              "DF": TagType.REAL}
_ADDR_RE = re.compile(r"([A-Z]+)(\d+)")

_tags: dict[str, Any] = {}
_mapping: list[Any] = []
_skipped_checks: dict[str, set[str]] = {}

# The Out variants own T1..T40 / TD1..TD40 (C0112: a coil claims its whole timer number).
TIMER_COUNT = 40
Timers = Timer.clone("CapTimers", count=TIMER_COUNT)
_mapping.append(Timers._blocks["Done"].map_to(t.select(1, TIMER_COUNT)))
_mapping.append(Timers._blocks["Acc"].map_to(td.select(1, TIMER_COUNT)))


def a(address: str) -> Any:
    """A tag named and mapped after its raw CLICK address (``a("DS1001")``)."""
    if address not in _tags:
        prefix, index = _ADDR_RE.fullmatch(address).groups()  # type: ignore[union-attr]
        tag = _TYPES[prefix](address)
        _mapping.append(tag.map_to(_BLOCKS[prefix][int(index)]))
        _tags[address] = tag
    return _tags[address]


def r(first: str, last: str) -> Any:
    """A raw address range (``r("DS1401", "DS1410")``) as a mapped Block selection."""
    key = f"{first}:{last}"
    if key not in _tags:
        prefix, start = _ADDR_RE.fullmatch(first).groups()  # type: ignore[union-attr]
        _, end = _ADDR_RE.fullmatch(last).groups()  # type: ignore[union-attr]
        block = Block(f"{first}_to_{last}", _TAG_TYPES[prefix], int(start), int(end))
        _mapping.append(block.map_to(_BLOCKS[prefix].select(int(start), int(end))))
        _tags[key] = block.select(int(start), int(end))
    return _tags[key]


@dataclass(frozen=True)
class Case:
    id: str
    cond: Callable[[], Sequence[Any]]
    real: Callable[[], object]
    #: Placeholder body for the paste CSV: None means NOP; ``REAL`` means paste the real thing.
    stub: Callable[[], object] | None = None
    #: AF tokens pyrung can't produce yet (``randint``); replace the exported ones.
    af_override: tuple[str, ...] | None = None


def REAL() -> None:  # sentinel: the stub is the real instruction
    raise AssertionError


# ---------------------------------------------------------------------------
# Out family: contacts C1001+, targets C1101+ / Y001+, timers T1..T40, presets DS1001+
# ---------------------------------------------------------------------------


def _out(n: int, id: str, body: Callable[[], object]) -> Case:
    return Case(id, lambda: [a(f"C{1000 + n}")], body)


T = Timers
OUT = [
    _out(1, "out__toggle", lambda: toggle(a("C1101"))),
    _out(2, "out__toggle_y", lambda: toggle(a("Y001"))),
    _out(3, "out__toggle_immediate", lambda: toggle(immediate(a("Y002")))),
    _out(6, "out__debounce_both", lambda: debounce(a("C1104"), on=(T[3], 100), off=(T[4], 200))),
    _out(7, "out__debounce_sec",
         lambda: debounce(a("C1105"), on=(T[5], 2), off=(T[6], 3), unit="sec")),
    _out(8, "out__debounce_ds",
         lambda: debounce(a("C1106"), on=(T[7], a("DS1001")), off=(T[8], a("DS1002")))),
    _out(9, "out__debounce_mixed",
         lambda: debounce(a("C1107"), on=(T[9], a("DS1003")), off=(T[10], 50))),
    _out(10, "out__debounce_y", lambda: debounce(a("Y003"), on=(T[11], 100), off=(T[25], 100))),
    _out(11, "out__flasher", lambda: flasher(a("C1108"), on=(T[12], 500), off=(T[13], 250))),
    _out(12, "out__flasher_sec",
         lambda: flasher(a("C1109"), on=(T[14], 1), off=(T[15], 2), unit="sec")),
    _out(13, "out__flasher_ds",
         lambda: flasher(a("C1110"), on=(T[16], a("DS1004")), off=(T[17], a("DS1005")))),
    _out(14, "out__timed", lambda: timed(a("C1111"), T[18], 1000)),
    _out(15, "out__timed_sec", lambda: timed(a("C1112"), T[19], 3, "sec")),
    _out(16, "out__timed_min", lambda: timed(a("C1113"), T[20], 2, "min")),
    _out(17, "out__timed_ds", lambda: timed(a("C1114"), T[21], a("DS1006"))),
    _out(18, "out__timed_maintained", lambda: timed(a("C1115"), T[22], 1000, maintained=True)),
    _out(19, "out__timed_maintained_sec",
         lambda: timed(a("C1116"), T[23], 3, "sec", maintained=True)),
    _out(20, "out__timed_maintained_min",
         lambda: timed(a("C1117"), T[24], 1, "min", maintained=True)),
]


# ---------------------------------------------------------------------------
# Drum: contacts C1201+, outputs C1301+, step DS1201+, acc TD101+, done C1401+,
# events C1501+, reset/jog/jump C1601+, durations DS1301+
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Drum:
    n: int
    presets: Sequence[Any]
    events: Sequence[Any] | None  # None: plain time_drum
    unit: str
    reset: str
    jog: str | None = None
    jump: tuple[str, str] | None = None

    def _outputs(self):
        steps = len(self.presets)
        return [a(f"C{1300 + 10 * self.n + i}") for i in range(1, steps + 1)]

    def _pattern(self):
        steps = len(self.presets)
        return [[1 if i == j else 0 for i in range(steps)] for j in range(steps)]

    def _common(self) -> dict[str, Any]:
        return dict(
            outputs=self._outputs(),
            unit=self.unit,
            pattern=self._pattern(),
            current_step=a(f"DS{1200 + self.n}"),
            accumulator=a(f"TD{100 + self.n}"),
            completion_flag=a(f"C{1400 + self.n}"),
        )

    def _chain(self, builder):
        builder = builder.reset(a(self.reset))
        if self.jump is not None:
            builder = builder.jump(a(self.jump[0]), step=a(self.jump[1]))
        if self.jog is not None:
            builder = builder.jog(a(self.jog))

    def real(self) -> None:
        presets = [a(p) if isinstance(p, str) else p for p in self.presets]
        if self.events is None:
            self._chain(time_drum(presets=presets, **self._common()))
        else:
            events = [a(e) if isinstance(e, str) else e for e in self.events]
            self._chain(time_event_drum(presets=presets, events=events, **self._common()))

    def v3_stub(self) -> None:
        """The same drum as a v3 Time drum: literal presets, a blank step becomes 1."""
        presets = [p if isinstance(p, int) else 1 for p in self.presets]
        self._chain(time_drum(presets=presets, **self._common()))


def _drum(id: str, drum: _Drum) -> Case:
    stub = REAL if drum.events is None else drum.v3_stub
    return Case(id, lambda: [a(f"C{1200 + drum.n}")], drum.real, stub)


DRUM = [
    _drum("drum__te_mixed",
          _Drum(1, [1000, None, 500], [None, "C1501", "C1502"], "ms", reset="C1601")),
    _drum("drum__te_ds", _Drum(2, ["DS1301", None], ["C1503", "C1504"], "sec", reset="C1602")),
    _drum("drum__te_jog_jump",
          _Drum(3, [2, 3, None], [None, "C1505", "C1506"], "min", reset="C1603",
                jog="C1604", jump=("C1605", "DS1210"))),
    _drum("drum__te_hour", _Drum(4, [1, None], [None, "C1507"], "hour", reset="C1606")),
    _drum("drum__te_day", _Drum(5, [1, 2], ["C1508", "C1509"], "day", reset="C1607")),
    _drum("drum__time_ds", _Drum(6, ["DS1302", "DS1303"], None, "ms", reset="C1608")),
    _drum("drum__time_ds_mixed", _Drum(7, ["DS1304", 500], None, "sec", reset="C1609")),
]


# ---------------------------------------------------------------------------
# Math: contacts C1701+, sources DS1401.. DD101.. DF101.. DH101.. C1801..,
# destinations DS1501.. DD201.. DF201.. DH201..
# ---------------------------------------------------------------------------

_SOURCES = {
    "ds": ("DS1401", "DS1410", "DS15{:02d}"),
    "dd": ("DD101", "DD110", "DD2{:02d}"),
    "df": ("DF101", "DF110", "DF2{:02d}"),
    "dh": ("DH101", "DH104", "DH2{:02d}"),
}
MATH: list[Case] = []


def _math(id: str, body: Callable[[], object], af: str | None = None) -> None:
    n = len(MATH) + 1
    MATH.append(Case(id, lambda: [a(f"C{1700 + n}")], body, REAL,
                     None if af is None else (af,)))


for _bank, (_first, _last, _dest) in _SOURCES.items():
    for _i, _method in enumerate(("max", "min", "median", "mean"), start=1):
        _math(
            f"math__{_method}_{_bank}",
            lambda f=_first, l=_last, d=_dest.format(_i), m=_method: calc(
                getattr(r(f, l), m)(), a(d)
            ),
        )
_math("math__sum_bits", lambda: calc(r("C1801", "C1816").sum(), a("DS1505")))
_math("math__abs_ds", lambda: calc(abs(a("DS1411")), a("DS1506")))
_math("math__abs_df", lambda: calc(abs(a("DF111")), a("DF205")))
_math("math__composed",
      lambda: calc(r("DS1401", "DS1410").max() + abs(a("DS1411")), a("DS1507")))
# randint isn't built yet (feature 6): the body is a stand-in, the token is a guess at
# CLICK's spelling.  The capture's decoded formula is the answer.
_math("math__rand_const", lambda: calc(a("DS1412"), a("DS1508")),
      af="math(RAND(1,100),DS1508,mode=decimal)")
_math("math__rand_reg", lambda: calc(a("DD111"), a("DD205")),
      af="math(RAND(DD111,DD112),DD205,mode=decimal)")
_math("math__rand_hex", lambda: calc(a("DH105"), a("DH205")),
      af="math(RAND(DH105,DH106),DH205,mode=hex)")


GROUPS = {"out": OUT, "drum": DRUM, "math": MATH}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _export(case: Case, body: Callable[[], object] | None, text: str | None) -> list[list[str]]:
    """Export one rung; return its rows (comment + data), header and end() dropped."""
    with Program(strict=False) as logic:
        if text is not None:
            comment(text)
        with Rung(*case.cond()):
            if body is not None:
                body()
    mapping = TagMap(_mapping, include_system=False)
    try:
        bundle = pyrung_to_ladder(logic, mapping)
    except LadderExportError as exc:
        # The precheck still treats v3-only findings (register drum durations) as errors.
        codes = sorted(set(re.findall(r"CLK_[A-Z_]+", str(exc))))
        _skipped_checks.setdefault(case.id, set()).update(codes)
        bundle = pyrung_to_ladder(logic, mapping, validate=False)
    rows = [list(row) for row in bundle.main_rows[1:]]
    while rows and rows[-1][-1] == "end()":
        rows.pop()
    return rows


_MATH_RE = re.compile(r"math\((.*)(,[A-Z]+\d+,mode=\w+(?:,oneshot=1)?\))")


def _click_formula(token: str) -> str:
    """CLICK spells a call ``NAME ( a , b )``: spaces around each paren and separator.

    Seen natively as ``SUM ( DS301 : DS350 )`` and ``RAND ( DD111 , DD112 )``.
    pyrung renders ``ABS(x)``; the capture decodes to CLICK's spelling.
    """
    match = _MATH_RE.fullmatch(token)
    if match is None:
        return token
    formula = re.sub(r"\s*([(),:])\s*", r" \1 ", match.group(1))
    formula = re.sub(r"  +", " ", formula).strip()
    return f"math({formula}{match.group(2)}"


_DONE_KW_RE = re.compile(r",(?:on|off)_done=T\d+")


def _click_out_variant(token: str) -> str:
    """CLICK's Out coil stores only the TD (``0x60B4``/``0x60B6``); drop the ``_done`` keys.

    Decided 2026-10-23: the token says only what the blob holds; T<n> follows from TD<n>.
    """
    return _DONE_KW_RE.sub("", token)


def _af_tokens(rows: list[list[str]]) -> list[str]:
    return [
        _click_out_variant(_click_formula(row[-1]))
        for row in rows
        if row[0] != "#" and row[-1]
    ]


def _apply_override(rows: list[list[str]], case: Case) -> list[list[str]]:
    if case.af_override is None:
        return rows
    data = [row for row in rows if row[0] != "#" and row[-1]]
    assert len(data) == len(case.af_override), case.id
    for row, token in zip(data, case.af_override, strict=True):
        row[-1] = token
    return rows


def build_group(cases: list[Case]) -> tuple[list[list[str]], list[list[str]]]:
    header = None
    stubs: list[list[str]] = []
    expected: list[list[str]] = []
    for case in cases:
        real_rows = _apply_override(_export(case, case.real, None), case)
        text = "\n".join([case.id, *_af_tokens(real_rows)])
        expected += _apply_override(_export(case, case.real, text), case)
        stub_body = case.real if case.stub is REAL else case.stub
        stub_rows = _export(case, stub_body, text)
        if case.stub is REAL:
            stub_rows = _apply_override(stub_rows, case)
        stubs += stub_rows
    with Program(strict=False) as logic:
        with Rung(a("C1")):
            pass
    header = list(pyrung_to_ladder(logic, TagMap(_mapping, include_system=False)).main_rows[0])
    return [header, *stubs], [header, *expected]


def main() -> None:
    for name, cases in GROUPS.items():
        stubs, expected = build_group(cases)
        for folder, rows in (("stubs", stubs), ("expected", expected)):
            path = HERE / folder / f"{name}.csv"
            path.parent.mkdir(exist_ok=True)
            with path.open("w", encoding="utf-8", newline="") as handle:
                csv.writer(handle).writerows(rows)
        print(f"{name}: {len(cases)} rungs -> stubs/{name}.csv, expected/{name}.csv")
    for case_id, codes in _skipped_checks.items():
        print(f"  exported without validation: {case_id} ({', '.join(sorted(codes))})")


if __name__ == "__main__":
    main()
