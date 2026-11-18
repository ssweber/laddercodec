"""Test that the grids in tests/fixtures/editor_grids match what devtools/editor_grids.py writes.

Each grid lists cases that ClickNick's runner types into CLICK's dialogs. Each verdicts file
records whether laddercodec's field rules accept or refuse each case. When a rule changes, a
verdict changes. When a bank or a kind of constant changes, the cases change. Then run
``uv run devtools/editor_grids.py`` and commit the files. CLICK's own answers are not tested
here, and nobody edits them to fit the code.
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
GRIDS = ROOT / "tests" / "fixtures" / "editor_grids"

_OPERATORS = ("==", "!=", ">", "<", ">=", "<=")


@dataclass(frozen=True)
class Dialog:
    """A dialog as the runner's ``INSTRUCTIONS`` names it.

    ``modes`` is empty for a dialog without modes. ``fields`` holds the names of all its
    fields, whatever the mode, and ``options`` the control ids of its option buttons. A
    ``contact`` is placed only with ``--wire``."""

    modes: tuple[str, ...]
    fields: frozenset[str]
    options: frozenset[str] = frozenset()
    contact: bool = False


#: Each dialog that the runner fills, as its ``INSTRUCTIONS`` has it.
DIALOGS = {
    "math": Dialog(("decimal", "hex"), frozenset({"result", "formula"})),
    "copy": Dialog(
        ("single", "block", "pack", "unpack"),
        frozenset({"source", "source_end", "destination", "destination_end", "termination_code"}),
        frozenset({"5019", "5020", "5036", "5037", "5021", "5024"}),
    ),
    "out": Dialog((), frozenset({"address", "address_end"})),
    "receive": Dialog(
        (),
        frozenset(
            {"slave_id", "slave_address", "master_address", "count"}
            | {"receiving", "success", "error", "exception"}
        ),
    ),
    "compare": Dialog(_OPERATORS, frozenset({"a", "b"}), contact=True),
    "search": Dialog(
        _OPERATORS,
        frozenset({"value", "start", "end", "result", "found"}),
        frozenset({"5021", "5022"}),
    ),
}
#: Copy's Fill mode, which the runner does not drive yet. A Fill case names its fields as the
#: runner names the Copy dialog's fields. Only the files in FILL_FILES hold Fill cases, and
#: they hold nothing else.
FILL = ("copy", "fill")
FILL_FIELDS = {"source", "destination", "destination_end"}
FILL_FILES = {"copy_fill.json", "preflight_fill.json", "risky_fill.json"}
#: The runner takes these keys of a case and no others.
CASE_KEYS = {"row", "case", "instruction", "mode", "fields", "choices", "options"}
#: The number of cases in each row, over the dialog grids and the risky files, as committed. If a
#: generator loop drops cases, the files still match the generator, but a count here changes.
#: A deliberate change to the cases also changes a count here.
ROW_COUNTS = {
    "compare.a.banks": 85,
    "compare.a.constants": 9,
    "compare.a.forms": 54,
    "compare.b.banks": 88,
    "compare.b.constants": 107,
    "compare.b.forms": 54,
    "compare.control": 3,
    "compare.mixed.operators": 60,
    "compare.operators": 28,
    "compare.pairs.banks": 86,
    "compare.pairs.constants": 77,
    "compare.text.operators": 29,
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
    "copy.fill.control": 1,
    "copy.fill.destination-end.banks": 54,
    "copy.fill.destination-end.constants": 9,
    "copy.fill.destination-end.forms": 5,
    "copy.fill.destination-start.constants": 9,
    "copy.fill.destination-start.forms": 5,
    "copy.fill.destination.mixed-banks": 63,
    "copy.fill.destination.ranges": 101,
    "copy.fill.hex-wide": 50,
    "copy.fill.pairs.banks": 251,
    "copy.fill.pairs.constants": 118,
    "copy.fill.real-digits": 6,
    "copy.fill.sd": 18,
    "copy.fill.text.characters": 3,
    "copy.fill.text.constants": 20,
    "copy.fill.text.numbers": 14,
    "copy.fill.text.registers": 5,
    "copy.fill.value.banks": 87,
    "copy.fill.value.constants": 111,
    "copy.fill.value.forms": 53,
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
    "search.control": 2,
    "search.found.banks": 87,
    "search.found.forms": 5,
    "search.operators": 23,
    "search.options": 8,
    "search.result.banks": 88,
    "search.result.forms": 5,
    "search.table-end.banks": 24,
    "search.table-end.forms": 5,
    "search.table-start.banks": 36,
    "search.table-start.forms": 5,
    "search.table.mixed-banks": 61,
    "search.table.ranges": 104,
    "search.text.operators": 41,
    "search.value.banks": 88,
    "search.value.constants": 106,
    "search.value.forms": 54,
    "search.value.pairs": 81,
}

#: The most cases that one grid file may hold. Split a longer file by hand, because the
#: runner takes about 4 seconds a case. devtools/editor_grids.py marks such a file as over
#: the split limit, and it does not split the file.
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
    """Return the verdicts in *text* without their messages, so that the wording is not
    compared."""
    return {
        label: {k: v for k, v in verdict.items() if k != "message"}
        for label, verdict in json.loads(text).items()
    }


def _grid_files() -> list[Path]:
    """Return the grid files, leaving out the verdicts files and CLICK's answers
    (``<grid>.answers.json``)."""
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
        "out", "copy_fill", "compare", "search", "risky", "risky_compare", "risky_fill",
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
        fill_file = path.name in FILL_FILES
        for case in cases:
            where = f"{path.name}: {case['case']}"
            assert set(case) <= CASE_KEYS, where
            assert case["row"] and case["case"], where
            dialog = DIALOGS[case["instruction"]]
            is_fill = (case["instruction"], case.get("mode")) == FILL
            assert is_fill == fill_file, where
            if is_fill:
                fields = FILL_FIELDS
            elif dialog.modes:
                assert case["mode"] in dialog.modes, where
                fields = dialog.fields
            else:
                assert "mode" not in case, where
                fields = dialog.fields
            assert case["fields"], where
            assert set(case["fields"]) <= fields, where
            assert all(isinstance(v, str) for v in case["fields"].values()), where
            # No grid chooses an item from a list yet.
            assert "choices" not in case, where
            options = case.get("options", {})
            assert set(options) <= dialog.options, where
            assert all(type(v) is int and v in (0, 1) for v in options.values()), where
        # The runner places a contact only with --wire, which applies to the whole file, so a
        # file holds only contacts or none.
        contacts = {DIALOGS[c["instruction"]].contact for c in cases}
        assert len(contacts) == 1, f"{path.name} mixes contacts with other instructions"


def test_verdicts_are_accepted_or_refused() -> None:
    for path in GRIDS.glob("*.verdicts.json"):
        for label, verdict in json.loads(path.read_text(encoding="utf-8")).items():
            assert verdict["verdict"] in ("accepted", "refused"), f"{path.name}: {label}"
            assert (verdict["verdict"] == "refused") == ("message" in verdict), label
