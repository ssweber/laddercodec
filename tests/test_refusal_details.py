"""Tests that every refusal says what happened and what to do, and names its field.

A caller such as pyrung shows ``short()`` next to the field that ``field`` names, and
``detail()`` below it.  So every refusal needs a ``short()``, a ``detail()`` and a ``field``
of the form ``Class.attr`` or ``Class.attr[i]``.

The refusals come from three sources:

- every case of the editor grids (``devtools/editor_grids.py``);
- every rebuild of the field sweep (``devtools/field_sweep.py``);
- the cases in ``CASES`` below, which reach refusals that the other two miss, such as those
  of CSV token parsing.

The codes in ``NO_DETAIL`` may still have refusals with an empty ``detail()``.  The list may
only shrink: a test fails when a code in it no longer has such a refusal.
"""

from __future__ import annotations

import ast
import dataclasses
import functools
import importlib.util
import re
import sys
import warnings
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

import laddercodec
from laddercodec import Code, FieldError
from laddercodec.circuit import Parallel, Series
from laddercodec.csv.ast import AfCall
from laddercodec.csv.token_parser import parse_af_token
from laddercodec.instructions import (
    BlockCopy,
    Coil,
    CompareContact,
    Contact,
    Copy,
    Counter,
    Drum,
    Fill,
    Math,
    ModbusAddress,
    ModbusRtuTarget,
    ModbusTcpTarget,
    OutVariant,
    Pack,
    Receive,
    Search,
    Send,
    Shift,
    Tee,
    Undecoded,
    Unpack,
    parse_af_call,
)
from laddercodec.instructions.send_receive import _parse_range_quantity
from laddercodec.operands.address import check_address, display_form_only
from tests.test_field_names import CLASSES

ROOT = Path(__file__).resolve().parents[1]

#: The codes that may still have a refusal with an empty ``detail()``, and why.  Remove a
#: code when every refusal of it has a detail.
NO_DETAIL: dict[Code, str] = {
    Code.INVALID_CHOICE: "a wrong value of a fixed set; its 25 sites name the set already",
    Code.ADDRESS_OUT_OF_RANGE: "the short names the bank's range",
    Code.CONSTANT_OUT_OF_RANGE: "the short names the range",
    Code.COUNT_OUT_OF_RANGE: "the short names the range",
    Code.REMOTE_ADDRESS_OUT_OF_RANGE: "the short names the ranges",
    Code.DRUM_SIZE_OUT_OF_RANGE: "the short names the range",
    Code.DRUM_PATTERN_SHAPE: "the short names the shape the drum needs",
    Code.INVALID_INPUT_ROWS: "a wrong pin_rows value; the short names the shape",
    Code.INVALID_RAW: "a wrong value in a raw() instruction",
    Code.INVALID_UNDECODED: "a wrong value in an Undecoded marker",
    Code.INVALID_TOKEN: "the short names the form of the token",
    Code.COPY_TXT_NEEDS_CONVERT: "the short names the converters to write",
    Code.TIMER_PAIR_MISMATCH: "the short names the address to write",
    Code.DEBOUNCE_NEEDS_PHASE: "the short names the fields to set",
    Code.IMMEDIATE_EDGE_CONTACT: "the short says the edge contact has no immediate form",
    Code.NOT_CLICK_FORM: "the short names the display form to write",
}


def _load(name: str) -> ModuleType:
    """Load ``devtools/<name>.py`` as a module of its own, apart from any other test's copy."""
    spec = importlib.util.spec_from_file_location(
        f"_details_{name}", ROOT / "devtools" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


def _token(text: str) -> Callable[[], object]:
    """Return a function that reads the CSV instruction token *text*."""

    def read() -> object:
        node = parse_af_token(text)
        assert isinstance(node, AfCall)
        return parse_af_call(node)

    return read


_RTU = ModbusRtuTarget("r", "cpu2", 1)
_SEND = 'send(target=ModbusRtuTarget(name="r",com_port="cpu2",device_id=1),remote_start="DS1",'
_TCP = 'send(target=ModbusTcpTarget(name="t",ip="1.2.3.4",{}),remote_start="DS1",source=DS1)'

#: Builds that each raise a refusal which the editor grids and the field sweep do not reach.
CASES: dict[str, Callable[[], object]] = {
    "coil-time-unit": lambda: OutVariant("timed", "C1", "TD1", "5", unit="x"),  # type: ignore[arg-type]
    "option-not-offered": lambda: OutVariant("toggle", "C1", unit="Ts"),
    "immediate-not-allowed": lambda: OutVariant("timed", "C1", "TD1", "5", unit="Ts", immediate=True),
    "debounce-needs-phase": lambda: OutVariant("debounce", "C1", unit="Ts"),
    "duplicate-address-out-variant": lambda: OutVariant(
        "flasher", "C1", "TD1", "5", "TD1", "5", unit="Ts"
    ),
    "immediate-edge-contact": lambda: Contact("X001", "rise", immediate=True),
    "timer-pair-mismatch": lambda: Counter("count_up", "CT2", "CTD1", "5"),
    "not-an-address": lambda: Contact("out"),
    "pointer": lambda: Fill("DS[DS1]", "DS1", "DS2"),
    "pointer-not-ds": lambda: Copy("DD[DS1+2]", "DS1"),
    "constant-out-of-range": lambda: Copy("5000000000", "DD1"),
    "copy-txt-needs-convert": lambda: Copy("5", "TXT1"),
    "drum-step-empty-event": lambda: Drum(
        "event_drum", ("C1",), events=("X001", ""), pattern=((1,), (0,)), current_step="DS1",
        completion_flag="C9",
    ),
    "drum-step-empty-time": lambda: Drum(
        "time_drum", ("C1",), presets=("5", ""), pattern=((1,), (0,)), current_step="DS1",
        completion_flag="C9", accumulator="TD1", unit="Ts",
    ),
    "drum-presets-on-event-drum": lambda: Drum(
        "event_drum", ("C1",), presets=("5",), events=("X001",), pattern=((1,),),
        current_step="DS1", completion_flag="C9",
    ),
    "math-syntax-error": lambda: Math("DS1 DS2", "DS9"),
    "math-ends-with-an-operator": lambda: Math("DS1 +", "DS9"),
    "math-function-without-parentheses": lambda: Math("SIN DF1", "DF9"),
    "math-invalid-token": lambda: Math("DS1 += DS2", "DS9"),
    "math-digit-outside-0-9": lambda: Math("DS1 + ٣", "DS9"),
    "math-arg-expression": lambda: Math("SUM ( DS1 + DS2 )", "DS9"),
    "math-unbalanced-parens": lambda: Math("( DS1", "DS9"),
    "math-constant-out-of-range": lambda: Math("DF1 * ( 1.2345e-04 )", "DF9"),
    "math-pointer": lambda: Math("DS[DS1]", "DS9"),
    "sum-option-slot": lambda: Math("SUM ( X025 : X101 )", "DS9"),
    "modbus-ip": lambda: ModbusTcpTarget("t", "1.2.3", 502, 1),
    "modbus-port": lambda: ModbusTcpTarget("t", "1.2.3.4", 70000, 1),
    "modbus-device-id": lambda: ModbusTcpTarget("t", "1.2.3.4", 502, 300),
    "modbus-device-id-address": lambda: ModbusRtuTarget("r", "cpu2", "DD1"),
    "modbus-address": lambda: ModbusAddress("40x"),
    "duplicate-address": lambda: Receive(_RTU, "DS1", "DS1", 1, "C1", "C1", "C2", ""),
    "constant-kind-not-allowed": lambda: Send(_RTU, "DS1", "DS1", 1.5, "C1", "C2", "C3", ""),  # type: ignore[arg-type]
    "function-code-mismatch": lambda: Send(
        _RTU, "DS1", "DS1", 1, "C1", "C2", "C3", "", function_code=5
    ),
    "function-code-quantity": lambda: Send(
        _RTU, "DS1", "DS1", 2, "C1", "C2", "C3", "", function_code=6
    ),
    "word-swap": lambda: Receive(_RTU, "DS1", "DS1", 1, "C1", "C2", "C3", "", word_swap=True),
    "undecoded-column": lambda: Undecoded("why", 0, 0, 40),
    "csv-range-backwards": _token(_SEND + "source=DS5..DS1)"),
    "csv-range-mixed-banks": _token(_SEND + "source=DS1..DD5)"),
    "csv-range-not-two-addresses": _token(_SEND + "source=DS1..)"),
    "csv-port-too-long": _token(_TCP.format("port=" + "7" * 5000)),
    "csv-device-id-too-long": _token(
        'send(target=ModbusRtuTarget(name="r",com_port="cpu2",device_id=' + "7" * 5000
        + '),remote_start="DS1",source=DS1)'
    ),
    "csv-flag": _token("copy(DS1,DS2,oneshot=2)"),
    "csv-raw-token": _token("raw(Search,zz,1)"),
    "csv-undecoded-token": _token("undecoded(why)"),
    "copy-converter-bank-to-text": lambda: Copy("TXT1", "DS1", convert="to_text"),
    "copy-converter-bank-to-value": lambda: Copy("DS1", "TXT1", convert="to_value"),
    "copy-converter-bank-to-binary": lambda: Copy("TXT1", "DS1", convert="to_binary"),
    "copy-converter-bank-df": lambda: Copy("TXT1", "DF1", convert="to_value"),
    "block-copy-converter-bank": lambda: BlockCopy("DS1", "DS2", "TXT1", "TXT2", convert="to_value"),
    "block-copy-converter-txt": lambda: BlockCopy("TXT1", "TXT2", "TXT11", "TXT12", convert="to_value"),
    "block-copy-end-mismatch": lambda: BlockCopy("DS1", "DS2", "DS11", "DS13"),
    "pack-kind-mismatch": lambda: Pack("DS1", "DS2", "DD1", kind="pack_bits"),
    "pack-kind-mismatch-text": lambda: Pack("TXT1", "TXT2", "DS1", kind="pack_words"),
    "math-nickname": lambda: Math("DS1 + <Foo>", "DS9"),
    "math-nesting-depth": lambda: Math("( " * 9 + "DS1" + " )" * 9, "DS9"),
    "math-function-mode": lambda: Math("DS1 XOR DS2", "DS9"),
    "math-formula-too-long": lambda: Math(" + ".join(f"DS{n}" for n in range(1, 70)), "DS9"),
    "math-hex-syntax-error": lambda: Math("DH1 DH2", "DH9", mode="hex"),
    "math-hex-pointer": lambda: Math("DH1 + DH[DS1]", "DH9", mode="hex"),
    "math-hex-sign": lambda: Math("DH1 * -2h", "DH9", mode="hex"),
    "math-hex-unbalanced-parens": lambda: Math("( DH1", "DH9", mode="hex"),
    "math-hex-empty-parens": lambda: Math("DH1 + ( )", "DH9", mode="hex"),
    "math-hex-value-before": lambda: Math("( * DH1 )", "DH9", mode="hex"),
    "math-hex-after-paren": lambda: Math("( DH1 ) DH2", "DH9", mode="hex"),
    "math-hex-after-colon": lambda: Math("SUM ( DH1 : )", "DH9", mode="hex"),
    "math-hex-ends-with-an-operator": lambda: Math("DH1 +", "DH9", mode="hex"),
    "math-hex-starts-with-an-operator": lambda: Math("* DH1", "DH9", mode="hex"),
    "immediate-contact-not-x": lambda: Contact("C1", immediate=True),
    # check_address refuses an upper byte only when its caller passes no banks, so the case
    # calls it directly.
    "upper-byte-not-allowed": lambda: check_address("XD0u", "Contact.operand"),
    "not-click-form": lambda: _in_display_form_only(lambda: Contact("x1")),
    "invalid-tee": lambda: Tee(Tee(Contact("X001"))),  # type: ignore[arg-type]
    "invalid-circuit": lambda: Parallel((Contact("X001"),)),
    "invalid-circuit-wires": lambda: Parallel((Series(()), Series(()))),
}  # fmt: skip


def _in_display_form_only(build: Callable[[], object]) -> object:
    """Return ``build()``, run as a decoder runs it: text not in display form is refused."""
    with display_form_only():
        return build()


def _refusals_of(build: Callable[[], object]) -> list[FieldError]:
    """Return the refusals that ``build()`` raises, or an empty list if it raises none."""
    try:
        build()
    except FieldError as exc:
        return [error for error in exc.errors if isinstance(error, FieldError)]
    except Exception:  # noqa: BLE001 - only the refusals are judged here
        return []
    return []


@functools.cache
def _collected() -> tuple[tuple[str, FieldError], ...]:
    """Return each refusal of the three sources, with the source's name."""
    found: list[tuple[str, FieldError]] = []
    grids = _load("editor_grids")
    real = grids.verdict_of

    def verdict_of(build: Callable[[], object]) -> object:
        found.extend(("editor grids", error) for error in _refusals_of(build))
        return real(build)

    grids.verdict_of = verdict_of
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        grids.build()
        sweep = _load("field_sweep")
        for inst in sweep.golden_instructions().values():
            for changes in sweep.rebuilds(inst):
                rebuilt = functools.partial(dataclasses.replace, inst, **changes)
                found.extend(("field sweep", error) for error in _refusals_of(rebuilt))
        for name, build in CASES.items():
            found.extend((name, error) for error in _refusals_of(build))
    return tuple(found)


@pytest.mark.parametrize("name", list(CASES))
def test_each_case_is_refused(name: str) -> None:
    assert _refusals_of(CASES[name]), f"{name} raised no FieldError"


def test_the_sources_give_refusals() -> None:
    sources = {source for source, _ in _collected()}
    assert {"editor grids", "field sweep"} <= sources


#: The places in the package that build refusals: the instruction families, the shared
#: operand checks, the circuit types and the CSV reader.
_REFUSAL_PLACES = ("instructions", "operands", "circuit.py", "csv")

#: The codes that those places pass as ``code=`` but never raise as a :class:`FieldError`,
#: and why.  The check of the codes leaves them out.
NOT_A_FIELD_ERROR: dict[Code, str] = {
    Code.DUPLICATE_SUBROUTINE_NAME: "read_bundle and write_bundle raise it as CsvReadError or "
    "CsvWriteError, which the sources here do not collect",
}


def _codes_in_source() -> set[Code]:
    """Return each code that :data:`_REFUSAL_PLACES` pass as ``code=Code.NAME``."""
    package = Path(laddercodec.__file__).parent
    paths: list[Path] = []
    for place in _REFUSAL_PLACES:
        path = package / place
        paths.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path])
    codes: set[Code] = set()
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.keyword)
                and node.arg == "code"
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "Code"
            ):
                codes.add(Code[node.value.attr])
    return codes


def test_every_code_in_the_source_has_a_collected_refusal() -> None:
    """Each code that the instructions, operands, circuit types and CSV reader raise has a
    refusal in the sources here, so the checks of this module reach it."""
    collected = {error.code for _, error in _collected()}
    missing = sorted(
        str(code) for code in _codes_in_source() - collected - NOT_A_FIELD_ERROR.keys()
    )
    assert not missing, f"add a case to CASES for: {', '.join(missing)}"


def test_the_codes_that_are_no_field_error_are_still_in_the_source() -> None:
    """``NOT_A_FIELD_ERROR`` only shrinks: a code leaves it when the places no longer pass it,
    or when a source here collects it."""
    collected = {error.code for _, error in _collected()}
    stale = [
        str(code)
        for code in NOT_A_FIELD_ERROR
        if code not in _codes_in_source() or code in collected
    ]
    assert not stale, f"remove these codes from NOT_A_FIELD_ERROR: {', '.join(stale)}"


def test_every_refusal_has_a_short() -> None:
    bad = [f"{source}: {error}" for source, error in _collected() if not error.short()]
    assert not bad, "\n".join(bad[:30])


def test_every_refusal_has_a_detail() -> None:
    bad = {
        error.code: f"{error.code} ({source}): {error}"
        for source, error in _collected()
        if not error.detail() and error.code not in NO_DETAIL
    }
    assert not bad, "\n".join(bad.values())


def test_the_codes_without_a_detail_still_have_a_refusal_without_one() -> None:
    """``NO_DETAIL`` only shrinks: a code leaves it when its refusals all have a detail."""
    empty = {error.code for _, error in _collected() if not error.detail()}
    fixed = [str(code) for code in NO_DETAIL if code not in empty]
    assert not fixed, f"remove these codes from NO_DETAIL: {', '.join(fixed)}"


#: Each example of a refusal: the text after ``such as``, up to ``, or``, ``; ``, the end of
#: a sentence, CLICK's id or the end of the message.
_EXAMPLE = re.compile(r"such as (.+?)(?=, or |; |\. | \([A-Z]+-\d+\)|\.?$)")
#: An example written as a keyword argument, such as ``function_code=16``.
_KEYWORD = re.compile(r"([a-z_]\w*)=(.+)")
#: An example of a whole range, such as ``SD31..SD32``.
_RANGE = re.compile(r"([A-Z]{1,3}\d+)\.\.([A-Z]{1,3}\d+)")
#: An example that is one address, such as ``DS1``.
_ADDRESS = re.compile(r"[A-Z]{1,3}\d+")
#: A field name, split into its class, its attribute and the index of an item.
_FIELD_PARTS = re.compile(r"([A-Z]\w*)\.([a-z_]\w*)(?:\[(\d+)\])?")

_C = Code
#: The reasons of :data:`EXAMPLE_NOT_SUBSTITUTED`.
_NO_OBJ = "a Modbus target or a ModbusAddress sets no obj on its refusal"
_CSV_RANGE = "read_csv refuses the range before it builds the Send, so the refusal holds none"
_CODE = "the example is Python code that builds the value"
_COPY_PAIR = "no character code copies into the destination's bank"
_PARTNER_REFUSED = "the other end or the destination is refused on its own, so no example fits it"

#: The examples that the test can't put back into their field, or that need another field
#: changed too, by code, field and example, and why.  The list may only shrink: a test
#: fails when an entry's example is accepted, or when no refusal holds it.
EXAMPLE_NOT_SUBSTITUTED: dict[tuple[Code, str, str], str] = {
    (_C.INVALID_MODBUS_TARGET, "ModbusRtuTarget.device_id", "1"): _NO_OBJ,
    (_C.INVALID_MODBUS_TARGET, "ModbusTcpTarget.device_id", "1"): _NO_OBJ,
    (_C.INVALID_MODBUS_TARGET, "ModbusTcpTarget.ip", "192.168.0.10"): _NO_OBJ,
    (_C.INVALID_MODBUS_TARGET, "ModbusTcpTarget.port", "port=502"): _NO_OBJ,
    (_C.NOT_AN_ADDRESS, "ModbusAddress.address", "400001"): _NO_OBJ,
    (_C.NOT_AN_ADDRESS, "Send.source", "DS1..DS10"): _CSV_RANGE,
    (_C.RANGE_MIXED_BANKS, "Send.source", "DS1..DS10"): _CSV_RANGE,
    (_C.RANGE_NOT_ASCENDING, "Send.source", "DS1..DS10"): _CSV_RANGE,
    (_C.INVALID_CIRCUIT, "Parallel.legs", "Parallel((Contact('X001'), Contact('X002')))"): _CODE,
    (_C.INVALID_CIRCUIT, "Parallel.legs", "Parallel((Contact('X001'), Series(())))"): _CODE,
    (_C.INVALID_TEE, "Tee.contact", "Tee(Contact('X001'))"): _CODE,
    (_C.INVALID_CHAR_CODE, "Copy.source", "$41"): _COPY_PAIR,
    (_C.INVALID_CHAR_CODE, "Fill.value", "$41"): _COPY_PAIR,
    (_C.NOT_AN_ADDRESS, "BlockCopy.source_start", "DS1"): _PARTNER_REFUSED,
    (_C.NOT_AN_ADDRESS, "BlockCopy.source_end", "DS2"): _PARTNER_REFUSED,
    (_C.POINTER_OUTSIDE_COPY, "BlockCopy.source_start", "DS1"): _PARTNER_REFUSED,
    (_C.POINTER_OUTSIDE_COPY, "BlockCopy.source_end", "DS2"): _PARTNER_REFUSED,
    (_C.NOT_AN_ADDRESS, "Pack.source_start", "C15"): _PARTNER_REFUSED,
    (_C.POINTER_OUTSIDE_COPY, "Pack.source_start", "C15"): _PARTNER_REFUSED,
    (_C.NOT_AN_ADDRESS, "Unpack.dest_start", "C15"): _PARTNER_REFUSED,
    (_C.POINTER_OUTSIDE_COPY, "Unpack.dest_start", "C15"): _PARTNER_REFUSED,
}


def _with_example(error: FieldError, example: str) -> tuple[Callable[[], object], str] | str:
    """Return a build of the instance of ``error`` with ``example`` in its field, and the
    field that the example fills.

    Return a string that says why when the example can't be put back.
    """
    m = _FIELD_PARTS.fullmatch(error.field or "")
    if m is None:
        return "the refusal names no field"
    cls_name, attr, index = m.groups()
    obj = error.obj
    if obj is None or type(obj).__name__ != cls_name:
        return f"the refusal holds no {cls_name}"
    keyword = _KEYWORD.fullmatch(example)
    ends = _RANGE.fullmatch(example)
    attrs = [_FIELD_PARTS.fullmatch(field) for field in error.fields]
    pair = sorted(m.group(2) for m in attrs if m is not None and m.group(3) is None)
    local = {"Send": "source", "Receive": "dest"}.get(cls_name)
    counted = local is not None and (
        (ends is not None and {local, "quantity"} & set(pair))
        or ("quantity" in pair and _ADDRESS.fullmatch(example))
    )
    if counted and local is not None:
        # A range example such as DS1..DS4 sets a Send's source, or a Receive's dest, and the
        # count, as the CSV token reads them. An address alone that a refusal of the count
        # suggests is one element.
        try:
            start, count = _parse_range_quantity(example, f"{cls_name}.{local}")
        except FieldError as exc:
            return f"the example is no range: {exc}"
        build = functools.partial(dataclasses.replace, obj, **{local: start, "quantity": count})
        return build, f"{cls_name}.quantity"
    if ends and len(pair) == 2 and pair[0].endswith("_end") and pair[1].endswith("_start"):
        # A range example such as SD31..SD32 fills the start and the end that the refusal
        # names.
        end_attr, start_attr = pair
        build = functools.partial(
            dataclasses.replace, obj, **{start_attr: ends.group(1), end_attr: ends.group(2)}
        )
        return build, f"{cls_name}.{attr}"
    if keyword is not None:
        # A keyword example such as source="TXT999" names its field and quotes text.
        attr, index = keyword.group(1), None
        text = keyword.group(2)
        value: object = text[1:-1] if len(text) >= 2 and text[0] == text[-1] == '"' else text
        value = int(text) if text.isdigit() else value
    else:
        current = getattr(obj, attr)
        if index is None and isinstance(current, (list, tuple)):
            # The refusal names the whole list, such as a drum step with no event. The
            # example goes in each blank item.
            if not any(item == "" for item in current):
                return "the example is for a blank item, and the list has none"
            value = type(current)(example if item == "" else item for item in current)
        elif index is None:
            value = example
            if isinstance(current, int) and not isinstance(current, bool) and example.isdigit():
                value = int(example)
        else:
            items = list(current)
            items[int(index)] = example
            value = type(current)(items)
    return functools.partial(dataclasses.replace, obj, **{attr: value}), f"{cls_name}.{attr}"


@functools.cache
def _example_failures() -> dict[tuple[Code, str, str], str]:
    """Return each example that its field still refuses, or that the test can't put back.

    The key is the refusal's code, its field without the index, and the example.  The value
    says what happened.
    """
    failures: dict[tuple[Code, str, str], str] = {}
    for _, error in _collected():
        for example, why in _example_problems(error):
            failures[(error.code, re.sub(r"\[\d+\]$", "", error.field or ""), example)] = why
    return failures


def _example_problems(error: FieldError) -> list[tuple[str, str]]:
    """Return each example in ``error`` that its field still refuses, or that the test can't
    put back, with what happened."""
    problems = []
    for example in _EXAMPLE.findall(str(error)):
        built = _with_example(error, example)
        if isinstance(built, str):
            problems.append((example, built))
            continue
        build, filled = built
        named = {error.field, filled}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            still = [again for again in _refusals_of(build) if named & set(again.fields)]
        if still:
            problems.append((example, f"{error}  ->  {still[0]}"))
    return problems


def test_every_example_is_accepted_by_its_field() -> None:
    """Each "such as" example in a refusal, put back into its field, is not refused there."""
    bad = [
        f"{key}: {why}"
        for key, why in _example_failures().items()
        if key not in EXAMPLE_NOT_SUBSTITUTED
    ]
    assert not bad, "\n".join(sorted(bad))


def test_the_examples_not_substituted_still_fail() -> None:
    """``EXAMPLE_NOT_SUBSTITUTED`` only shrinks: an entry leaves it when its example builds."""
    failing = _example_failures()
    fixed = [str(key) for key in EXAMPLE_NOT_SUBSTITUTED if key not in failing]
    assert not fixed, f"remove these from EXAMPLE_NOT_SUBSTITUTED: {', '.join(fixed)}"


def _send(**kw: object) -> Send:
    """Build a Send from DS1 to DS1, with ``kw`` in place of its fields."""
    fields: dict = {"target": _RTU, "remote_start": "DS1", "source": "DS1", "quantity": 1}
    status = {"sending": "C1", "success": "C2", "error": "C3", "exception_response": "DS100"}
    return Send(**{**fields, **status, **kw})


#: Refused instructions whose refusal suggests a value for ``attr`` that must fit another
#: field: the other end of a range, the other operand, or a Send's function code. Each
#: builds the instruction with ``attr`` given, and its other fields as they are.
_PARTNER_CASES: dict[str, tuple[Callable[..., object], str]] = {
    "coil end": (lambda **kw: Coil(**{"operand": "Y001", "range_end": "$41", **kw}), "range_end"),
    "coil start": (lambda **kw: Coil(**{"operand": "$41", "range_end": "Y005", **kw}), "operand"),
    "shift start": (lambda **kw: Shift(**{"start_bit": "5", "end_bit": "C1", **kw}), "start_bit"),
    "copy source": (lambda **kw: Copy(**{"source": "5x", "dest": "C1", **kw}), "source"),
    "copy dest": (lambda **kw: Copy(**{"source": "X001", "dest": "5x", **kw}), "dest"),
    "block dest": (
        lambda **kw: BlockCopy(
            **{
                "source_start": "X001",
                "source_end": "X016",
                "dest_start": "5x",
                "dest_end": "C16",
                **kw,
            }
        ),
        "dest_start",
    ),
    "pack dest": (
        lambda **kw: Pack(**{"source_start": "X001", "source_end": "X016", "dest": "5x", **kw}),
        "dest",
    ),
    "unpack source": (
        lambda **kw: Unpack(**{"source": "5x", "dest_start": "Y001", "dest_end": "Y016", **kw}),
        "source",
    ),
    "compare left": (
        lambda **kw: CompareContact(**{"op": "==", "left": "5x", "right": "TXT1", **kw}),
        "left",
    ),
    "compare right": (
        lambda **kw: CompareContact(**{"op": "==", "left": "DH1", "right": "5x", **kw}),
        "right",
    ),
    "search value": (
        lambda **kw: Search(
            **{
                "table_start": "DH1",
                "table_end": "DH10",
                "value": "5x",
                "result": "DS1",
                "found": "C1",
                "op": "==",
                **kw,
            }
        ),
        "value",
    ),
    "send FC06 bank": (
        lambda **kw: _send(**{"remote_start": "5x", "function_code": 6, **kw}),
        "remote_start",
    ),
    "send FC06 SD": (
        lambda **kw: _send(**{"remote_start": "SD1", "function_code": 6, **kw}),
        "remote_start",
    ),
    "send source": (lambda **kw: _send(**{"remote_start": "DD1", "source": "5x", **kw}), "source"),
    "receive dest": (
        lambda **kw: _receive(**{"remote_start": "DD1", "dest": "5x", **kw}),
        "dest",
    ),
    "receive remote": (
        lambda **kw: _receive(**{"remote_start": "5x", "dest": "DD1", **kw}),
        "remote_start",
    ),
    "copy TXT source": (lambda **kw: Copy(**{"source": "5x", "dest": "TXT1", **kw}), "source"),
    "copy TXT dest": (lambda **kw: Copy(**{"source": "TXT1", "dest": "5x", **kw}), "dest"),
    "block SC end": (
        lambda **kw: BlockCopy(
            **{
                "source_start": "SC50",
                "source_end": "5x",
                "dest_start": "C1",
                "dest_end": "C3",
                **kw,
            }
        ),
        "source_end",
    ),
    "block SD start": (
        lambda **kw: BlockCopy(
            **{
                "source_start": "5x",
                "source_end": "SD29",
                "dest_start": "DS1",
                "dest_end": "DS4",
                **kw,
            }
        ),
        "source_start",
    ),
    "pack SC end": (
        lambda **kw: Pack(**{"source_start": "SC53", "source_end": "5x", "dest": "DH1", **kw}),
        "source_end",
    ),
    "pack SC start": (
        lambda **kw: Pack(**{"source_start": "5x", "source_end": "SC50", "dest": "DH1", **kw}),
        "source_start",
    ),
}


def _receive(**kw: object) -> Receive:
    """Build a Receive from DS1 to DS1, with ``kw`` in place of its fields."""
    fields: dict = {"target": _RTU, "remote_start": "DS1", "dest": "DS1", "quantity": 1}
    status = {"receiving": "C1", "success": "C2", "error": "C3", "exception_response": "DS100"}
    return Receive(**{**fields, **status, **kw})


@pytest.mark.parametrize("name", list(_PARTNER_CASES))
def test_the_example_fits_the_partner_field(name: str) -> None:
    """The address that a refusal suggests is accepted with the instruction's other fields
    as they are."""
    build, attr = _PARTNER_CASES[name]
    with pytest.raises(FieldError) as caught:
        build()
    field = f"{type(caught.value.obj).__name__}.{attr}"
    error = next(e for e in caught.value.errors if e.field == field)
    example = _EXAMPLE.search(str(error))
    assert example is not None, str(error)
    build(**{attr: example.group(1).removeprefix(f"{attr}=").strip('"')})


#: Refused Sends whose refusal may suggest a source range, with the count it sets. Each
#: example must be a range that the Send accepts, or the start alone.
_SEND_RANGE_CASES: dict[str, Callable[[], object]] = {
    "TXT even start, count past the bank": lambda: _send(
        remote_start="TXT1", source="TXT2", quantity=2000
    ),
    "TXT even start, count past the text limit": lambda: _send(
        remote_start="TXT1", source="TXT2", quantity=250
    ),
    "TXT count past the text limit": lambda: _send(
        remote_start="TXT1", source="TXT1", quantity=250
    ),
    "XD past the hex room under FC16": lambda: _send(
        remote_start=ModbusAddress("FFF0h"), source="XD0", quantity=16
    ),
    "DS past the hex room": lambda: _send(
        remote_start=ModbusAddress("FFF0h"), source="DS1", quantity=32
    ),
}


@pytest.mark.parametrize("name", list(_SEND_RANGE_CASES))
def test_a_send_range_example_is_accepted(name: str) -> None:
    """A range that a Send refusal suggests exists and is accepted with the Send's other
    fields as they are."""
    with pytest.raises(FieldError) as caught:
        _SEND_RANGE_CASES[name]()
    errors = [e for e in caught.value.errors if isinstance(e, FieldError)]
    problems = [
        f"{example}: {why}" for error in errors for example, why in _example_problems(error)
    ]
    assert not problems, "\n".join(problems)


_FIELD = re.compile(r"([A-Z]\w*)\.([a-z_]\w*)(?:\[\d+\])?")


def _field_problems(error: FieldError) -> list[str]:
    """Return a message for each item of ``error.fields`` that names no field of a class."""
    problems = []
    if error.field is None and not error.fields:
        return []  # a refusal of a token's syntax, such as raw(...), names no field
    if error.field != error.fields[0]:
        problems.append(f"field {error.field!r} is not the first of fields {error.fields!r}")
    for field in error.fields:
        m = _FIELD.fullmatch(field)
        cls = CLASSES.get(m.group(1)) if m else None
        names = {f.name for f in dataclasses.fields(cls)} if cls else set()
        if m is None or m.group(2) not in names:
            problems.append(f"{field!r} is no Class.field or Class.field[i]")
    return problems


def test_every_refusal_names_a_field_of_its_class() -> None:
    bad = {
        f"{source}: {error}: {problem}"
        for source, error in _collected()
        for problem in _field_problems(error)
    }
    assert not bad, "\n".join(sorted(bad)[:30])
