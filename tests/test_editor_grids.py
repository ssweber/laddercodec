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


def test_files_are_the_generators(built: dict[str, str]) -> None:
    assert sorted(p.name for p in GRIDS.glob("*.json")) == sorted(built)


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
    for path in GRIDS.glob("*.json"):
        if path.name.endswith(".verdicts.json"):
            continue
        cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
        verdicts = json.loads(path.with_suffix(".verdicts.json").read_text(encoding="utf-8"))
        assert [c["case"] for c in cases] == list(verdicts), path.name


def test_cases_are_in_the_runners_shape() -> None:
    for path in GRIDS.glob("*.json"):
        if path.name.endswith(".verdicts.json"):
            continue
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
