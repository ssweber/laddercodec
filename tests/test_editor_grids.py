"""The editor grids under tests/fixtures/editor_grids match what devtools/editor_grids.py writes.

The grids are the cases ClickNick's runner types into CLICK's dialogs; the verdicts files hold
what laddercodec's field rules say about each case. A rule that changes moves a verdict, and a
bank or constant kind that changes moves the cases: regenerate with
``uv run devtools/editor_grids.py`` and commit the files. CLICK's own answers are not tested
here and are never edited to fit the code.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
GRIDS = ROOT / "tests" / "fixtures" / "editor_grids"

#: The runner's dialogs: each field's name, and the modes (none for Out).
DIALOGS = {
    "math": ({"result", "formula"}, {"decimal", "hex"}),
    "copy": (
        {"source", "source_end", "destination", "destination_end"},
        {"single", "block", "pack", "unpack"},
    ),
    "out": ({"address", "address_end"}, set()),
}
#: The runner takes these keys of a case and no others.
CASE_KEYS = {"row", "case", "instruction", "mode", "fields"}
#: Cases per row over the dialog grids and the risky file, as written. A loop that loses cases moves a
#: count here, which the match with the generator cannot see; a deliberate change moves it too.
ROW_COUNTS = {
    "copy.block.control": 1,
    "copy.block.destination.banks": 95,
    "copy.block.destination.constants": 9,
    "copy.block.destination.forms": 5,
    "copy.block.pairs.banks": 226,
    "copy.block.pairs.xy-spans": 62,
    "copy.block.source-end.constants": 9,
    "copy.block.source-end.forms": 5,
    "copy.block.source.banks": 70,
    "copy.block.source.constants": 9,
    "copy.block.source.forms": 5,
    "copy.block.source.mixed-banks": 64,
    "copy.block.source.ranges": 104,
    "copy.pack.bits.widths": 167,
    "copy.pack.bits.xy-spans": 20,
    "copy.pack.control": 1,
    "copy.pack.destination.banks": 78,
    "copy.pack.destination.constants": 9,
    "copy.pack.destination.forms": 5,
    "copy.pack.source-end.constants": 9,
    "copy.pack.source-end.forms": 5,
    "copy.pack.source.banks": 80,
    "copy.pack.source.constants": 9,
    "copy.pack.source.forms": 5,
    "copy.pack.source.ranges": 90,
    "copy.pack.words.widths": 140,
    "copy.single.control": 1,
    "copy.single.destination.banks": 87,
    "copy.single.destination.forms": 53,
    "copy.single.pairs.banks": 239,
    "copy.single.pairs.constants": 135,
    "copy.single.pairs.constants-pointer": 80,
    "copy.single.pairs.pointer": 48,
    "copy.single.source.banks": 88,
    "copy.single.source.constants": 110,
    "copy.single.source.forms": 53,
    "copy.single.text.fill": 17,
    "copy.unpack.bits.widths": 167,
    "copy.unpack.bits.xy-spans": 20,
    "copy.unpack.control": 1,
    "copy.unpack.destination-end.constants": 9,
    "copy.unpack.destination-end.forms": 5,
    "copy.unpack.destination.banks": 80,
    "copy.unpack.destination.constants": 9,
    "copy.unpack.destination.forms": 5,
    "copy.unpack.destination.ranges": 78,
    "copy.unpack.source.banks": 78,
    "copy.unpack.source.constants": 9,
    "copy.unpack.source.forms": 5,
    "copy.unpack.words.widths": 140,
    "math.avg.decimal.ranges": 32,
    "math.constants.decimal": 110,
    "math.constants.decimal.alone": 110,
    "math.constants.hex": 110,
    "math.constants.hex.alone": 110,
    "math.control": 2,
    "math.max.decimal.ranges": 32,
    "math.mdn.decimal.ranges": 32,
    "math.min.decimal.ranges": 32,
    "math.operand.decimal.banks": 88,
    "math.operand.decimal.banks-alone": 88,
    "math.operand.decimal.forms": 53,
    "math.operand.hex.banks": 88,
    "math.operand.hex.banks-alone": 88,
    "math.operand.hex.forms": 53,
    "math.rand.decimal.constants": 18,
    "math.rand.decimal.high-bound": 88,
    "math.rand.decimal.low-bound": 88,
    "math.rand.decimal.order": 7,
    "math.rand.hex.constants": 18,
    "math.rand.hex.high-bound": 88,
    "math.rand.hex.low-bound": 88,
    "math.rand.hex.order": 7,
    "math.result.decimal.banks": 87,
    "math.result.decimal.forms": 53,
    "math.result.decimal.not-an-address": 6,
    "math.result.hex.banks": 87,
    "math.result.hex.forms": 53,
    "math.result.hex.not-an-address": 6,
    "math.sum.decimal.mixed": 60,
    "math.sum.decimal.ranges": 104,
    "math.sum.hex.ranges": 104,
    "out.banks": 87,
    "out.constants": 110,
    "out.control": 1,
    "out.forms": 53,
    "out.range-end.banks": 54,
    "out.range-end.constants": 9,
    "out.range-end.forms": 5,
    "out.range-start.forms": 5,
    "out.ranges": 104,
    "out.ranges.mixed": 60,
}

#: A file longer than this is split: the runner takes about 4 seconds a case.
MAX_CASES = 2000


@pytest.fixture(scope="module")
def generator() -> Any:
    spec = importlib.util.spec_from_file_location(
        "editor_grids", ROOT / "devtools" / "editor_grids.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def built(generator: Any) -> dict[str, str]:
    return generator.build()


def _verdict_core(text: str) -> dict[str, Any]:
    """The verdicts without their messages: wording is not part of what is compared."""
    return {
        label: {k: v for k, v in verdict.items() if k != "message"}
        for label, verdict in json.loads(text).items()
    }


def _grid_files() -> list[Path]:
    """The grids: not the verdicts, and not CLICK's answers (``<grid>.answers.json``)."""
    return sorted(
        p for p in GRIDS.glob("*.json") if not p.name.endswith((".verdicts.json", ".answers.json"))
    )


def test_files_are_the_generators(built: dict[str, str]) -> None:
    committed = [p.name for p in GRIDS.glob("*.json") if not p.name.endswith(".answers.json")]
    assert sorted(committed) == sorted(built)


def test_rows_keep_their_cases() -> None:
    counts: dict[str, int] = {}
    for name in (
        "math_decimal", "math_hex", "copy_single", "copy_block", "copy_pack", "copy_unpack",
        "out", "risky",
    ):  # fmt: skip
        for case in json.loads((GRIDS / f"{name}.json").read_text(encoding="utf-8"))["cases"]:
            counts[case["row"]] = counts.get(case["row"], 0) + 1
    assert counts == ROW_COUNTS


def test_cases_match_the_generator(built: dict[str, str]) -> None:
    for name, text in built.items():
        if name.endswith(".verdicts.json"):
            continue
        assert (GRIDS / name).read_text(encoding="utf-8") == text, name


def test_verdicts_match_the_generator(built: dict[str, str]) -> None:
    for name, text in built.items():
        if name.endswith(".verdicts.json"):
            committed = (GRIDS / name).read_text(encoding="utf-8")
            assert _verdict_core(committed) == _verdict_core(text), name


def test_every_case_has_a_verdict() -> None:
    for path in _grid_files():
        cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
        verdicts = json.loads(path.with_suffix(".verdicts.json").read_text(encoding="utf-8"))
        assert [c["case"] for c in cases] == list(verdicts), path.name


def test_cases_are_in_the_runners_shape() -> None:
    for path in _grid_files():
        cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
        assert 0 < len(cases) <= MAX_CASES, path.name
        labels = [c["case"] for c in cases]
        assert len(labels) == len(set(labels)), f"{path.name} repeats a case label"
        for case in cases:
            where = f"{path.name}: {case['case']}"
            assert set(case) <= CASE_KEYS, where
            assert case["row"] and case["case"], where
            fields, modes = DIALOGS[case["instruction"]]
            if modes:
                assert case["mode"] in modes, where
            else:
                assert "mode" not in case, where
            assert case["fields"], where
            assert set(case["fields"]) <= fields, where
            assert all(isinstance(v, str) for v in case["fields"].values()), where


def test_verdicts_are_accepted_or_refused() -> None:
    for path in GRIDS.glob("*.verdicts.json"):
        for label, verdict in json.loads(path.read_text(encoding="utf-8")).items():
            assert verdict["verdict"] in ("accepted", "refused"), f"{path.name}: {label}"
            assert (verdict["verdict"] == "refused") == ("message" in verdict), label
