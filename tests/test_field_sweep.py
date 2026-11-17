"""Odd field values give an outcome no worse than the recorded one.

``devtools/field_sweep.py`` rebuilds every golden instruction with odd values in its fields
and ``tests/fixtures/field_sweep/outcomes.json`` records, per rebuild, whether it was
accepted (``a``), refused with ``FieldError`` (``F``) or ``AddressError`` (``A``), or failed
with another exception (``X``), as the code gave it before any instruction collected its
refusals (a golden added later is recorded from the code of its day).  Now each rebuild must give the same outcome, except that a crash may become a
refusal: what was accepted stays accepted, what was refused stays refused with the same
class, and a refusal never becomes a crash.

The record is keyed by a digest of the instruction's class name and CSV text, which a field
rename does not change: after a pure rename the keys are the same and, if the field order and
types are unchanged, so are the outcome strings.  The record changes only with the golden set:
``make field-sweep``.
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
    """Whether outcome ``now`` may follow ``recorded``: the same, or a crash become a refusal."""
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
