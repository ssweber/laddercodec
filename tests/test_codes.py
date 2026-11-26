"""Test the ``Code`` names, the error codes page, and the codes on the fixtures.

``tests/conftest.py`` checks every refusal that the other tests raise, as it is raised. Its
code must be a ``Code``, and its ``click_id`` must be one that ``CLICK_IDS`` lists for that
code. These tests check the codes that the other tests never raise: those of the refusals
that decoding keeps on the fixtures, of the ``check()`` findings on the fixtures, and of the
refusals raised when ``devtools/field_sweep.py`` rebuilds each golden instruction with
changed fields.
"""

from __future__ import annotations

import dataclasses
import gzip
import importlib.util
import warnings
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from laddercodec import CLICK_IDS, Code, FieldError, check, decode, decode_program, read_csv
from laddercodec.operands.unchecked import refusals
from tests.conftest import code_problems

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

#: The approved value of every ``Code`` member, in the order that ``Code`` defines them.
NAMES = """
blank-field not-an-address address-out-of-range bank-not-allowed upper-byte-not-allowed
not-click-form not-writable pointer-outside-copy pointer-bank-not-allowed pointer-not-ds
constant-kind-not-allowed not-a-constant constant-out-of-range invalid-constant
invalid-char-code invalid-text-constant not-a-flag invalid-choice
option-not-offered range-mixed-banks range-not-ascending range-crosses-slot duplicate-address
timer-pair-mismatch immediate-contact-not-x immediate-coil-not-y immediate-edge-contact
immediate-not-allowed text-order-compare invalid-subroutine-name duplicate-subroutine-name
invalid-input-rows
copy-bank-incompatible constant-into-bit copy-converter-bank copy-txt-needs-convert
copy-hex-reads-as-real text-past-bank block-copy-end-mismatch pack-kind-mismatch pack-too-many
math-nickname math-invalid-token math-constant-kind math-constant-out-of-range
math-nesting-depth math-unbalanced-parens math-function-mode math-syntax-error
math-arg-expression random-bound-type random-equal-bounds math-operand-bank
sum-bank-unavailable math-range-mixed-banks math-range-not-ascending median-range-too-large
sum-option-slot math-formula-too-long
compare-mixed-types search-value-bank coil-time-unit debounce-needs-phase
drum-size-out-of-range drum-pattern-shape drum-step-empty function-code-mismatch
count-out-of-range txt-start-not-odd remote-address-out-of-range invalid-modbus-target
for-count-bank
invalid-token invalid-raw invalid-undecoded invalid-tee invalid-circuit
not-series-parallel no-rail feeds-no-box no-coil contact-feeds-only-nop unwired-input
output-above-box-inputs shared-input-net input-without-contact input-shares-enable
inputs-share-contacts unpowered-box shorted-contact undecoded-rung comment-too-long
for-without-next next-without-for for-nesting-depth oneshot-inside-loop return-inside-loop
nested-call
layout-too-wide layout-too-tall layout-nop-split layout-cannot-draw
""".split()


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PAGE_GEN = _load("gen_codes", ROOT / "docs" / "gen_codes.py")


def test_the_names_are_pinned() -> None:
    assert [code.value for code in Code] == NAMES
    assert len(NAMES) == len(set(NAMES)) == 102
    assert all(code.name == code.value.upper().replace("-", "_") for code in Code)


def test_each_code_has_a_one_line_docstring() -> None:
    groups = PAGE_GEN.groups(PAGE_GEN.SOURCE.read_text(encoding="utf-8"))
    members = [m for _, _, group in groups for m in group]
    assert [value for _, value, _ in members] == NAMES
    for _, value, doc in members:
        assert doc and "\n" not in doc and doc.endswith("."), value


def test_click_ids_name_codes() -> None:
    assert all(isinstance(code, Code) for code in CLICK_IDS)
    for code, ids in CLICK_IDS.items():
        assert ids and len(ids) == len(set(ids)), code
        assert all(isinstance(i, str) and i[:1] in "OCG" for i in ids), code


def test_the_codes_page_is_current() -> None:
    page = PAGE_GEN.PAGE.read_text(encoding="utf-8")
    assert page == PAGE_GEN.render(), "the error codes page is out of date: make docs-generate"


# ---------------------------------------------------------------------------
# The corpora
# ---------------------------------------------------------------------------


def _decoded() -> Iterator[tuple[str, list[Any]]]:
    """Yield the path and the rungs of every fixture that decodes or reads.

    Skip a fixture that raises.
    """
    for path in sorted(FIXTURES.rglob("*")):
        name = path.name
        if not path.is_file():
            continue
        rel = path.relative_to(FIXTURES).as_posix()
        try:
            if name.endswith((".bin", ".bin.gz")):
                data = path.read_bytes()
                rungs = decode(gzip.decompress(data) if name.endswith(".gz") else data)
            elif path.suffix in (".scr", ".tmp"):
                rungs = list(decode_program(path.read_bytes()).rungs)
            elif path.suffix == ".csv":
                rungs = read_csv(path, strict=False)
            else:
                continue
        except Exception:  # noqa: BLE001 - a fixture that does not decode keeps nothing
            continue
        yield rel, rungs


def _tokens(rung: Any) -> Iterator[Any]:
    for row in rung.conditions:
        yield from (cell for cell in row if not isinstance(cell, str))
    yield from (token for token in rung.instructions if token is not None)


@pytest.fixture(scope="module")
def corpora() -> list[tuple[str, list[Any]]]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return list(_decoded())


def test_every_kept_refusal_in_the_corpora_has_its_code(
    corpora: list[tuple[str, list[Any]]],
) -> None:
    kept = 0
    problems = []
    for rel, rungs in corpora:
        for rung in rungs:
            for token in _tokens(rung):
                for error in refusals(token):
                    kept += 1
                    problems += [f"{rel}: {p}" for p in code_problems(error)]
    # The v4 Math captures keep a few refusals, with the codes sum-option-slot and
    # math-formula-too-long.
    assert kept >= 5, "the corpora keep fewer refusals than they hold: the walk is broken"
    assert not problems, "\n".join(problems[:50])


def test_every_finding_on_the_corpora_has_its_code(corpora: list[tuple[str, list[Any]]]) -> None:
    seen: set[Code] = set()
    problems = []
    for rel, rungs in corpora:
        for finding in check(rungs):
            seen.add(finding.code)
            if not isinstance(finding.code, Code):
                problems.append(f"{rel}: {finding.code!r} is not a Code")
            elif finding.click_id is not None and finding.click_id not in CLICK_IDS.get(
                finding.code, ()
            ):
                problems.append(f"{rel}: {finding.code} does not list {finding.click_id}")
    assert seen, "no finding on the corpora: the walk is broken"
    assert not problems, "\n".join(problems[:50])


def test_every_refusal_of_the_field_sweep_has_its_code() -> None:
    sweep = _load("field_sweep", ROOT / "devtools" / "field_sweep.py")
    refused = 0
    problems = []
    for inst in sweep.golden_instructions().values():
        for changes in sweep.rebuilds(inst):
            try:
                dataclasses.replace(inst, **changes)
            except FieldError as exc:
                refused += 1
                problems += [
                    f"{inst!r} {changes!r}: {p}" for e in exc.errors for p in code_problems(e)
                ]
            except Exception:  # noqa: BLE001, S112 - test_field_sweep judges the other outcomes
                continue
    assert refused, "the field sweep refused nothing: the walk is broken"
    assert not problems, "\n".join(problems[:50])
