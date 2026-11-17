"""Odd field values give an outcome no worse than the recorded one.

``devtools/field_sweep.py`` rebuilds every golden instruction with odd values in its fields.
``tests/fixtures/field_sweep/outcomes.json`` records one outcome for each rebuild. The rebuild
was accepted (``a``), refused with ``FieldError`` (``F``) or ``AddressError`` (``A``), or
failed with another exception (``X``). Each instruction's outcomes were recorded when it was
added to the record, and they are not recorded again.

Each rebuild must give its recorded outcome, with one exception: a crash may become a
refusal. A rebuild that was accepted must still be accepted. A rebuild that was refused must
still be refused with the same exception class. A refusal must never become a crash.

The record is keyed by a digest of the instruction's class name and its CSV text. Renaming a
field changes neither, so the keys stay the same. If the fields also keep their order and
types, the outcome strings stay the same too. Only a change to the set of golden
instructions changes the record. ``make field-sweep`` applies that change.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _sweep() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "field_sweep", ROOT / "devtools" / "field_sweep.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SWEEP = _sweep()


def allowed(recorded: str, now: str) -> bool:
    """Return whether outcome ``now`` may replace the outcome ``recorded``.

    It may if the two are the same, or if a crash (``X``) became a refusal (``F`` or ``A``).
    """
    return recorded == now or (recorded == "X" and now in "FA")


def test_allowed() -> None:
    assert all(allowed(o, o) for o in "aFAX")
    assert allowed("X", "F") and allowed("X", "A")
    for recorded, now in ["aF", "Fa", "aA", "Aa", "aX", "Xa", "FX", "AX", "FA", "AF"]:
        assert not allowed(recorded, now), (recorded, now)


def test_odd_values_give_an_allowed_outcome() -> None:
    recorded: dict[str, str] = json.loads(SWEEP.RECORD.read_text(encoding="utf-8"))
    found = SWEEP.golden_instructions()
    assert set(recorded) == set(found), "the golden set changed: make field-sweep"
    differ = []
    for key, inst in found.items():
        now = SWEEP.outcomes(inst)
        assert len(now) == len(recorded[key]), f"{inst!r}: the sweep's rebuilds changed"
        for changes, old, new in zip(SWEEP.rebuilds(inst), recorded[key], now, strict=True):
            if not allowed(old, new):
                differ.append(f"{inst!r} with {changes!r}: recorded {old}, now {new}")
    assert not differ, "\n".join(differ[:50])


def test_the_record_holds_every_outcome() -> None:
    letters = set("".join(json.loads(SWEEP.RECORD.read_text(encoding="utf-8")).values()))
    assert letters == set("aFAX")
