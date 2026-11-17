"""Record what odd field values do to every golden instruction: tests/fixtures/field_sweep/.

    make field-sweep    # add the golden instructions the record lacks, drop the ones gone

Every instruction the golden CSVs read to is rebuilt with one field replaced by None, 5, 2.5,
a tuple, a list and a list with a None item, and with one field refused while another holds
None, 5 or 2.5.  Each rebuild is accepted (``a``), refused with ``FieldError`` (``F``) or
``AddressError`` (``A``), or fails with another exception (``X``).  The record keeps one
string of these letters per instruction, keyed by a digest of its class name and CSV text, so
renaming a field does not change a key.

An instruction already in the record keeps its letters: only a change to the golden set
changes the record.  ``tests/test_field_sweep.py`` compares the code with it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import json
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from laddercodec import FieldError, read_csv
from laddercodec.model import AfInstruction, ConditionInstruction

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
RECORD = FIXTURES / "field_sweep" / "outcomes.json"
_ODD: list[Any] = [None, 5, 2.5]


def key_of(inst: Any) -> str:
    """The record's key: a digest of the class name and the CSV text."""
    return hashlib.sha1(f"{type(inst).__name__}|{inst.to_csv()}".encode()).hexdigest()[:12]


def golden_instructions() -> dict[str, Any]:
    """Every instruction object the golden CSVs read to, by ``key_of``."""
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
                        found.setdefault(key_of(cell), cell)
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
    """One letter per rebuild: a, F, A or X."""
    letters = []
    for changes in rebuilds(inst):
        try:
            dataclasses.replace(inst, **changes)
            letters.append("a")
        except FieldError as exc:
            letters.append("A" if type(exc).__name__ == "AddressError" else "F")
        except Exception:  # noqa: BLE001 - any other exception is one outcome
            letters.append("X")
    return "".join(letters)


def main() -> None:
    record: dict[str, str] = (
        json.loads(RECORD.read_text(encoding="utf-8")) if RECORD.exists() else {}
    )
    found = golden_instructions()
    kept = {key: record[key] for key in found if key in record}
    added = {key: outcomes(inst) for key, inst in found.items() if key not in record}
    merged = dict(sorted({**kept, **added}.items()))
    RECORD.parent.mkdir(exist_ok=True)
    RECORD.write_text(json.dumps(merged, indent=0) + "\n", encoding="utf-8")
    print(f"{len(merged)} instructions: {len(added)} added, {len(record) - len(kept)} dropped")


if __name__ == "__main__":
    main()
