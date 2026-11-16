"""Odd field values give the outcome they gave before refusals were collected.

Every instruction the golden CSVs read to is rebuilt with one field replaced by None, 5, 2.5,
a tuple, a list and a list with a None item, and with one field refused while another holds
None, 5 or 2.5.  Each rebuild is accepted, refused (``FieldError`` or ``AddressError``) or
fails with another exception, and ``fixtures/field_sweep/outcomes.json`` records which, as
the code gave it before any instruction collected its refusals.  A change to what a field
accepts changes this record, so it is a check on a branch that moves no rule.

To record again (after a golden is added or removed, or a rule is meant to move)::

    uv run python -I tests/test_field_sweep.py
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import json
import sys
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"
RECORD = FIXTURES / "field_sweep" / "outcomes.json"
_ODD: list[Any] = [None, 5, 2.5]
#: One letter per outcome; X for an exception not listed.
_LETTERS = {
    "accepted": "a",
    "FieldError": "F",
    "AddressError": "A",
    "TypeError": "T",
    "AttributeError": "E",
    "ValueError": "V",
    "KeyError": "K",
    "IndexError": "I",
}


def golden_instructions() -> dict[str, Any]:
    """Every instruction object the golden CSVs read to, by a digest of its repr."""
    from laddercodec import read_csv
    from laddercodec.model import AfInstruction, ConditionInstruction

    found: dict[str, Any] = {}
    paths = itertools.chain(
        (FIXTURES / "coverage" / "golden").glob("*.csv"),
        (FIXTURES / "ladder_captures" / "golden").glob("*.csv"),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for path in sorted(paths):
            for rung in read_csv(path):
                cells = [c for row in rung.conditions for c in row] + list(rung.instructions)
                for cell in cells:
                    if isinstance(cell, (AfInstruction, ConditionInstruction)):
                        key = hashlib.sha1(repr(cell).encode()).hexdigest()[:12]
                        found.setdefault(key, cell)
    return found


def _variants(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        items = list(value)
        return [*_ODD, tuple(items), items, [None, *items[1:]]]
    return [*_ODD, (value,), [value], [None]]


def rebuilds(inst: Any) -> Iterator[dict[str, Any]]:
    """The field changes the sweep tries on ``inst``, in a fixed order."""
    values = {f.name: getattr(inst, f.name) for f in dataclasses.fields(inst) if f.init}
    fields = [name for name, v in values.items() if isinstance(v, (str, bool, list, tuple))]
    for name in fields:
        for variant in _variants(values[name]):
            yield {name: variant}
    for refused, odd in itertools.permutations(fields, 2):
        if isinstance(values[refused], (list, tuple)):
            continue
        bad = 7 if isinstance(values[refused], bool) else "QQ9"
        for value in _ODD:
            yield {refused: bad, odd: value}


def outcomes(inst: Any) -> str:
    """One letter per rebuild, from :data:`_LETTERS`."""
    from laddercodec import FieldError

    letters = []
    for changes in rebuilds(inst):
        try:
            dataclasses.replace(inst, **changes)
            outcome = "accepted"
        except FieldError as exc:
            outcome = type(exc).__name__
        except Exception as exc:  # noqa: BLE001 - recorded, whatever it is
            outcome = type(exc).__name__
        letters.append(_LETTERS.get(outcome, "X"))
    return "".join(letters)


def test_odd_values_give_the_recorded_outcome() -> None:
    recorded: dict[str, str] = json.loads(RECORD.read_text(encoding="utf-8"))
    found = golden_instructions()
    assert set(recorded) == set(found), "goldens changed: record again (see the docstring)"
    differ = {key: (recorded[key], outcomes(inst)) for key, inst in found.items()}
    differ = {key: pair for key, pair in differ.items() if pair[0] != pair[1]}
    assert not differ, "\n".join(
        f"{found[key]!r}\n  recorded {old}\n  now      {new}" for key, (old, new) in differ.items()
    )


def test_the_record_tries_every_kind_of_outcome() -> None:
    letters = set("".join(json.loads(RECORD.read_text(encoding="utf-8")).values()))
    assert {"a", "F", "A", "T"} <= letters


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
    record = {key: outcomes(inst) for key, inst in sorted(golden_instructions().items())}
    RECORD.parent.mkdir(exist_ok=True)
    RECORD.write_text(json.dumps(record, indent=0, sort_keys=True) + "\n", encoding="utf-8")
    print(len(record), "instructions", sum(map(len, record.values())), "rebuilds")
