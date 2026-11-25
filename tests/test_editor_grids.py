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

    ``modes`` is empty for a dialog without modes. ``fields`` holds the names of all its fields
    in every mode. ``lists`` holds the names of its drop-down lists. ``options`` holds the
    control ids of its option buttons, or for a dialog in UNDRIVEN the names of its flags. A
    ``contact`` is placed only with ``--wire``."""

    modes: tuple[str, ...]
    fields: frozenset[str]
    options: frozenset[str] = frozenset()
    contact: bool = False
    lists: frozenset[str] = frozenset()


#: Each dialog that the runner fills, as its ``INSTRUCTIONS`` has it.
DIALOGS = {
    "math": Dialog(("decimal", "hex"), frozenset({"result", "formula"})),
    "copy": Dialog(
        ("single", "block", "pack", "unpack"),
        frozenset({"source", "source_end", "destination", "destination_end", "termination_code"}),
        # The runner also takes an option by the label of its button: Copy Binary is 5020.
        frozenset({"5019", "5020", "5036", "5037", "5021", "5024", "Copy Binary"}),
    ),
    "out": Dialog((), frozenset({"address", "address_end"})),
    # Set and Reset have the fields of Out.
    "set": Dialog((), frozenset({"address", "address_end"})),
    "reset": Dialog((), frozenset({"address", "address_end"})),
    # On a TCP port, Receive has the IP address and server port fields of Send.
    "receive": Dialog(
        (),
        frozenset(
            {"slave_id", "ip", "server_port", "slave_address", "master_address", "count"}
            | {"receiving", "success", "error", "exception"}
        ),
        lists=frozenset({"port", "function", "addressing", "word_swap"}),
    ),
    "compare": Dialog(_OPERATORS, frozenset({"a", "b"}), contact=True),
    "search": Dialog(
        _OPERATORS,
        frozenset({"value", "start", "end", "result", "found"}),
        frozenset({"5021", "5022"}),
    ),
}
#: Copy's Fill mode. A Fill case names its fields as the runner names the Copy dialog's
#: fields. Only the files in FILL_FILES hold Fill cases, and they hold nothing else, except
#: the files in FILL_MIXED_FILES.
FILL = ("copy", "fill")
FILL_FIELDS = {"source", "destination", "destination_end"}
FILL_FILES = {"copy_fill.json", "preflight_fill.json", "risky_fill.json"}
#: The grids that ClickNick wrote with Fill cases beside the cases of other dialogs.
FILL_MIXED_FILES = {"saves.json"}
#: The dialogs that the runner does not drive yet. Until it does, a case names the mode, the
#: fields, the lists and the option buttons by laddercodec's names. Only a dialog's own three
#: files (UNDRIVEN_FILES) hold its cases, and they hold nothing else.
UNDRIVEN = {
    "timer": Dialog(
        ("on_delay", "off_delay"),
        frozenset({"done", "accumulator", "preset"}),
        frozenset({"retained"}),
        lists=frozenset({"unit"}),
    ),
    "counter": Dialog(
        ("count_up", "count_down", "count_up_down"),
        frozenset({"done", "accumulator", "preset"}),
    ),
    "shift": Dialog((), frozenset({"start_bit", "end_bit"})),
    "for": Dialog((), frozenset({"count"}), frozenset({"oneshot"})),
    "drum": Dialog(
        ("time_drum", "event_drum", "time_event_drum"),
        frozenset(
            {"num_steps", "num_outputs"}
            | {f"{name}[{i}]" for name in ("outputs", "presets", "events") for i in range(16)}
            | {"current_step", "accumulator", "completion_flag", "jump_step"}
        ),
        frozenset({"jog_enabled", "jump_enabled"}),
        lists=frozenset({"unit"}),
    ),
    # A Send field or list that mirrors one of Receive's has Receive's name. The others have
    # laddercodec's names: sending (Send), and ip and port (ModbusTcpTarget).
    "send": Dialog(
        (),
        frozenset(
            {"slave_id", "ip", "server_port", "slave_address", "master_address", "count"}
            | {"sending", "success", "error", "exception"}
        ),
        lists=frozenset({"port", "function", "addressing", "word_swap"}),
    ),
}
UNDRIVEN_FILES = {
    name: {f"{name}.json", f"preflight_{name}.json", f"risky_{name}.json"} for name in UNDRIVEN
}
#: ClickNick's grids of drum events hold Drum cases too.
UNDRIVEN_FILES["drum"] |= {
    f"drum_events{name}.json" for name in ("", "_names", "_shapes", "_padded", "_padded2", "_exprs")
}
#: The grids that ClickNick wrote with the cases of one dialog in UNDRIVEN and of dialogs in
#: DIALOGS, each mapped to its dialog in UNDRIVEN. ``ip_field.json`` and ``ip_field_neg.json``
#: hold Send cases, which are in UNDRIVEN, and Receive cases, which are in DIALOGS.
MIXED_FILES = {"ip_field.json": "send", "ip_field_neg.json": "send"}
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
    "compare.text.quotes": 8,
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
    "copy.fill.text.quotes": 4,
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
    "copy.single.text.quotes": 8,
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
    "counter.accumulator": 1,
    "counter.control": 3,
    "counter.done.banks": 87,
    "counter.done.forms": 6,
    "counter.preset.banks": 88,
    "counter.preset.constants": 106,
    "counter.preset.edges": 18,
    "counter.preset.forms": 53,
    "counter.preset.lengths": 4,
    "drum.accumulator.banks": 87,
    "drum.completion-flag.banks": 87,
    "drum.control": 2,
    "drum.current-step.banks": 87,
    "drum.events.banks": 87,
    "drum.events.forms": 6,
    "drum.jog": 2,
    "drum.jump": 15,
    "drum.outputs": 8,
    "drum.outputs.banks": 86,
    "drum.outputs.conflicts": 3,
    "drum.outputs.forms": 6,
    "drum.presets.banks": 88,
    "drum.presets.constants": 108,
    "drum.presets.edges": 30,
    "drum.presets.forms": 54,
    "drum.steps": 8,
    "drum.units": 5,
    "for.control": 1,
    "for.count.banks": 88,
    "for.count.constants": 112,
    "for.count.forms": 53,
    "for.oneshot": 4,
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
    "search.text.quotes": 3,
    "search.value.banks": 88,
    "search.value.constants": 106,
    "search.value.forms": 54,
    "search.value.pairs": 81,
    "send.click.x-to-register": 6,
    "send.control": 8,
    "send.count.edges": 61,
    "send.count.risky": 6,
    "send.count.single": 6,
    "send.count.txt": 30,
    "send.count.xy": 40,
    "send.function.click-pairs": 174,
    "send.function.remote": 12,
    "send.function.source-banks": 60,
    "send.ports": 7,
    "send.remote.984": 25,
    "send.remote.click.banks": 75,
    "send.remote.click.forms": 8,
    "send.remote.hex": 44,
    "send.remote.hex-wide": 31,
    "send.remote.risky": 6,
    "send.slave-id.ports": 30,
    "send.slave-id.risky": 6,
    "send.slave-id.rtu": 18,
    "send.slave-id.tcp": 18,
    "send.source.banks": 75,
    "send.source.constants": 5,
    "send.source.forms": 13,
    "send.source.risky": 4,
    "send.status.error.banks": 16,
    "send.status.error.risky": 6,
    "send.status.exception.banks": 88,
    "send.status.exception.risky": 6,
    "send.status.forms": 12,
    "send.status.sending.banks": 88,
    "send.status.sending.risky": 6,
    "send.status.shared": 8,
    "send.status.success.banks": 16,
    "send.status.success.risky": 6,
    "send.tcp.ip": 3,
    "send.tcp.server-port": 5,
    "send.word-swap": 9,
    "shift.control": 1,
    "shift.end.banks": 86,
    "shift.end.constants": 5,
    "shift.end.forms": 6,
    "shift.ranges": 37,
    "shift.start.banks": 87,
    "shift.start.constants": 5,
    "shift.start.forms": 6,
    "shift.xy": 2,
    "timer.accumulator": 1,
    "timer.control": 2,
    "timer.done.banks": 87,
    "timer.done.forms": 6,
    "timer.preset.banks": 88,
    "timer.preset.constants": 108,
    "timer.preset.edges": 40,
    "timer.preset.forms": 53,
    "timer.retained": 6,
    "timer.units": 8,
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


def _grid_files() -> list[Path]:
    """Return the grid files, leaving out the verdicts files and CLICK's answers
    (``<grid>.answers.json``)."""
    return sorted(
        p for p in GRIDS.glob("*.json") if not p.name.endswith((".verdicts.json", ".answers.json"))
    )


def test_files_are_the_generators(generator: Any, built: dict[str, str]) -> None:
    """Each grid and verdicts file is one that the generator writes, or a grid that ClickNick
    wrote (``RUNNER_GRIDS``), whose verdicts file the generator writes."""
    committed = [p.name for p in GRIDS.glob("*.json") if not p.name.endswith(".answers.json")]
    runner = [f"{name}.json" for name in generator.RUNNER_GRIDS]
    assert not set(runner) & set(built)
    assert sorted(committed) == sorted([*built, *runner])


def test_rows_keep_their_cases() -> None:
    counts: dict[str, int] = {}
    for name in (
        "math_decimal", "math_hex", "copy_single", "copy_block", "copy_pack", "copy_unpack",
        "out", "copy_fill", "compare", "search", "risky", "risky_compare", "risky_fill",
        *UNDRIVEN, *(f"risky_{n}" for n in UNDRIVEN),
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
            assert json.loads(committed) == json.loads(text), name


def test_every_case_has_a_verdict() -> None:
    for path in _grid_files():
        cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
        verdicts = json.loads(path.with_suffix(".verdicts.json").read_text(encoding="utf-8"))
        assert [c["case"] for c in cases] == list(verdicts), path.name


def test_cases_are_in_the_runners_shape() -> None:
    # A dialog that the runner drives has its entry in DIALOGS and none in UNDRIVEN.
    assert not set(UNDRIVEN) & set(DIALOGS)
    for path in _grid_files():
        cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
        assert 0 < len(cases) <= MAX_CASES, path.name
        labels = [c["case"] for c in cases]
        assert len(labels) == len(set(labels)), f"{path.name} repeats a case label"
        fill_file = path.name in FILL_FILES
        undriven_file = next((n for n, files in UNDRIVEN_FILES.items() if path.name in files), None)
        for case in cases:
            where = f"{path.name}: {case['case']}"
            assert set(case) <= CASE_KEYS, where
            assert case["row"] and case["case"], where
            undriven = case["instruction"] if case["instruction"] in UNDRIVEN else None
            if path.name in MIXED_FILES:
                assert undriven in (None, MIXED_FILES[path.name]), where
            else:
                assert undriven == undriven_file, where
            dialog = UNDRIVEN[undriven] if undriven else DIALOGS[case["instruction"]]
            is_fill = (case["instruction"], case.get("mode")) == FILL
            assert is_fill == fill_file or path.name in FILL_MIXED_FILES, where
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
            choices = case.get("choices", {})
            assert set(choices) <= dialog.lists, where
            assert all(isinstance(v, str) and v for v in choices.values()), where
            options = case.get("options", {})
            assert set(options) <= dialog.options, where
            assert all(type(v) is int and v in (0, 1) for v in options.values()), where
        # The runner places a contact only with --wire, which applies to the whole file, so a
        # file holds only contacts or none.
        contacts = {(UNDRIVEN | DIALOGS)[c["instruction"]].contact for c in cases}
        assert len(contacts) == 1, f"{path.name} mixes contacts with other instructions"


def test_verdicts_are_accepted_or_refused() -> None:
    for path in GRIDS.glob("*.verdicts.json"):
        for label, verdict in json.loads(path.read_text(encoding="utf-8")).items():
            assert verdict["verdict"] in ("accepted", "refused"), f"{path.name}: {label}"
            assert (verdict["verdict"] == "refused") == ("message" in verdict), label
