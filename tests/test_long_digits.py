"""A constant of more than 4300 digits is refused, never a crash.

``int()`` refuses a string of more than 4300 digits with a ``ValueError``, so a field that
reads its constant with ``int()`` before checking its length crashes.  Every instruction the
golden CSVs read to (``devtools/field_sweep.py`` lists them) is rebuilt with each text field,
and each text in a list field, replaced by digit text in the spellings a constant takes:
decimal, signed, hex, real, with an exponent, and inside an expression.  Each rebuild is
accepted or refused with ``FieldError``; any other exception fails.  A spelling beyond every
field's range must be refused.  Leading zeros and a long fraction hold a value in range, so a
field may take them.  The fields no check reads are named in ``UNCHECKED``.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import warnings
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from laddercodec import FieldError

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

_RUN = "7" * 4400
_ZEROS = "0" * 4400
#: Spellings whose value is in range: a field may take them.
IN_RANGE = [
    _ZEROS + "1",
    "1." + _RUN,
]
#: Compare takes a real of any size (its constants are not held to float32).
HUGE_REALS = [_RUN + ".5", "1E" + _RUN, "1E+" + _RUN]
HUGE_REAL_FIELDS = {"CompareContact.left", "CompareContact.right"}
OUT_OF_RANGE = [
    _RUN,
    "-" + _RUN,
    "+" + _RUN,
    _RUN + "h",
    "-" + _RUN + "h",
    _RUN + ".5",
    "1E" + _RUN,
    "1E+" + _RUN,
    "DS1 + " + _RUN,
    "DS1 + " + _RUN + "h",
    "(" + _RUN + ")",
    "$" + _RUN,
    "DS" + _RUN,
    "DS[" + _RUN + "]",
]

#: Fields (``Class.field``) no check reads, so any text is kept: the compare operator
#: (``from_csv_token`` only builds the six), a drum's jump target while its jump is off, and
#: a raw instruction's class name.
UNCHECKED = {"CompareContact.op", "Drum.jump_target", "RawInstruction.class_name"}


def _cases() -> list[tuple[str, Any, str, int | None]]:
    """Each (label, instruction, field, list index or None) holding text."""
    cases = []
    for inst in SWEEP.golden_instructions().values():
        for f in dataclasses.fields(inst):
            if not f.init:
                continue
            value = getattr(inst, f.name)
            if isinstance(value, str):
                cases.append((f"{type(inst).__name__}.{f.name}", inst, f.name, None))
            elif isinstance(value, (list, tuple)):
                for i, item in enumerate(value):
                    if isinstance(item, str):
                        cases.append((f"{type(inst).__name__}.{f.name}[{i}]", inst, f.name, i))
    # One case per field is enough; the golden set holds many instances of each.
    seen: dict[str, tuple[str, Any, str, int | None]] = {}
    for case in cases:
        seen.setdefault(case[0], case)
    return list(seen.values())


def _replace(inst: Any, field: str, index: int | None, text: str) -> Any:
    if index is None:
        return dataclasses.replace(inst, **{field: text})
    items = list(getattr(inst, field))
    items[index] = text
    return dataclasses.replace(inst, **{field: items})


CASES = _cases()


def test_every_instruction_family_is_swept() -> None:
    families = {label.split(".")[0] for label, *_ in CASES}
    assert {"Copy", "Fill", "Math", "Timer", "Counter", "Drum", "ForLoop", "Search"} <= families
    assert len(CASES) > 100


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_long_digit_text_is_refused_not_a_crash(case: tuple[str, Any, str, int | None]) -> None:
    label, inst, field, index = case
    crashes = []
    accepted = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for text in [*IN_RANGE, *OUT_OF_RANGE]:
            try:
                _replace(inst, field, index, text)
            except FieldError:
                continue
            except Exception as exc:  # noqa: BLE001 - the crash is what this test looks for
                crashes.append(f"{text[:6]}...{text[-6:]}: {type(exc).__name__}: {exc}"[:120])
                continue
            if text in OUT_OF_RANGE and not (label in HUGE_REAL_FIELDS and text in HUGE_REALS):
                accepted.append(text[:6] + "..." + text[-6:])
    assert not crashes, f"{label} crashed: {crashes}"
    if label not in UNCHECKED:
        assert not accepted, f"{label} accepted long digit text: {accepted}"
