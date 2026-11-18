"""Box and contact instructions report every field that they refuse, each with a reason.

Contact, CompareContact, OutVariant, Counter, Shift, Call, ForLoop, Drum and Search run their
checks through ``Refusals``. When one of them has two bad fields that do not depend on each
other, it reports both in ``FieldError.errors``. The first error in that list is the one
raised.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

import laddercodec
from laddercodec import (
    Call,
    CompareContact,
    Contact,
    Counter,
    Drum,
    FieldError,
    ForLoop,
    Reason,
    Search,
    Shift,
    Tee,
)
from laddercodec.instructions.out_variant import OutVariant


def _errors(build: Any) -> list[tuple[str | None, Reason | None, str | None]]:
    with pytest.raises(FieldError) as caught:
        build()
    assert caught.value.errors[0] is caught.value
    return [(e.field, e.reason, e.click_id) for e in caught.value.errors]


def _fields(build: Any) -> list[tuple[str, ...]]:
    with pytest.raises(FieldError) as caught:
        build()
    return [e.fields for e in caught.value.errors]


def _drum(kind: str = "event_drum", **kw: Any) -> Drum:
    fields: dict[str, Any] = dict(
        kind=kind,
        outputs=["C1", "C2"],
        pattern=[[1, 0], [0, 1]],
        current_step="DS1",
        completion_flag="C3",
    )
    if kind == "event_drum":
        fields.update(events=["C10", "C11"])
    else:
        fields.update(presets=["100", "200"], unit="Tms", accumulator="TD1")
    if kind == "time_event_drum":
        fields.update(events=["C10", "C11"])
    return Drum(**{**fields, **kw})


def _search(**kw: Any) -> Search:
    fields: dict[str, Any] = dict(
        table_start="DS1",
        table_end="DS5",
        value="DS10",
        result="DS11",
        found="C1",
        op="==",
    )
    return Search(**{**fields, **kw})


def _variant(**kw: Any) -> OutVariant:
    fields: dict[str, Any] = dict(
        kind="timed", operand="C1", on_acc="TD1", on_preset="100", unit="Tms"
    )
    return OutVariant(**{**fields, **kw})


def _debounce(**kw: Any) -> OutVariant:
    fields: dict[str, Any] = dict(
        kind="debounce",
        operand="C1",
        on_acc="TD1",
        on_preset="100",
        off_acc="TD2",
        off_preset="100",
        unit="Tms",
    )
    return OutVariant(**{**fields, **kw})


def _counter(**kw: Any) -> Counter:
    fields: dict[str, Any] = dict(kind="count_up", done="CT1", accumulator="CTD1", preset="100")
    return Counter(**{**fields, **kw})


# ---------------------------------------------------------------------------
# Two independent bad fields report both
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "want"),
    [
        (
            lambda: Contact("DS1", immediate=7),
            [("Contact.immediate", Reason.FLAG), ("Contact.operand", Reason.BANK)],
        ),
        (
            lambda: Contact("DS1", kind="up"),  # type: ignore[arg-type]
            [("Contact.operand", Reason.BANK), ("Contact.kind", Reason.CHOICE)],
        ),
        (
            lambda: CompareContact("==", "DS1", "QQ9"),
            [("CompareContact.right", Reason.ADDRESS)],
        ),
        (
            lambda: CompareContact("==", "QQ9", "ZZ9"),
            [("CompareContact.left", Reason.ADDRESS), ("CompareContact.right", Reason.ADDRESS)],
        ),
        (
            lambda: _variant(operand="DS1", unit="Th"),
            [("OutVariant.operand", Reason.BANK), ("OutVariant.unit", Reason.CHOICE)],
        ),
        (
            lambda: _counter(kind="up", preset="DH1"),
            [("Counter.kind", Reason.CHOICE), ("Counter.preset", Reason.BANK)],
        ),
        (
            lambda: Shift("DS1", "DS2"),
            [("Shift.start_bit", Reason.BANK), ("Shift.end_bit", Reason.BANK)],
        ),
        (
            lambda: ForLoop("DH1", oneshot=7),
            [("ForLoop.count", Reason.BANK), ("ForLoop.oneshot", Reason.FLAG)],
        ),
        (
            lambda: _drum(current_step="C1", completion_flag="DS1"),
            [("Drum.current_step", Reason.BANK), ("Drum.completion_flag", Reason.BANK)],
        ),
        (
            lambda: _search(result="C1", found="DS1"),
            [("Search.result", Reason.BANK), ("Search.found", Reason.BANK)],
        ),
        (
            lambda: _search(table_start="C1", table_end="C2", op="~"),
            [
                ("Search.op", Reason.CHOICE),
                ("Search.table_start", Reason.BANK),
                ("Search.table_end", Reason.BANK),
            ],
        ),
    ],
)
def test_independent_bad_fields_report_both(build: Any, want: list[tuple[str, Reason]]) -> None:
    assert [(f, r) for f, r, _ in _errors(build)] == want


def test_call_reports_its_one_field_once() -> None:
    assert _errors(lambda: Call("")) == [("Call.subroutine", Reason.MISSING, None)]


# ---------------------------------------------------------------------------
# A reason per refusal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "want"),
    [
        # Contact
        (lambda: Contact("C1", kind="out"), ("Contact.kind", Reason.CHOICE, None)),  # type: ignore[arg-type]
        (lambda: Contact("DS1"), ("Contact.operand", Reason.BANK, None)),
        (lambda: Contact("C1", immediate=True), ("Contact.immediate", Reason.CONFLICT, None)),
        (
            lambda: Contact("X1", kind="rise", immediate=True),
            ("Contact.immediate", Reason.CONFLICT, None),
        ),
        (lambda: Contact("X1", immediate=2), ("Contact.immediate", Reason.FLAG, None)),
        (lambda: Tee("X001"), ("Tee.contact", Reason.FORM, None)),
        # CompareContact
        (
            lambda: CompareContact("==", "DS1", "QQ9"),
            ("CompareContact.right", Reason.ADDRESS, None),
        ),
        (
            lambda: CompareContact("==", "DS1", "DH1"),
            ("CompareContact.left", Reason.CONFLICT, None),
        ),
        (
            lambda: CompareContact("<", "TXT1", "TXT2"),
            ("CompareContact.op", Reason.CONFLICT, None),
        ),
        # OutVariant
        (lambda: _variant(kind="spin"), ("OutVariant.kind", Reason.CHOICE, None)),
        (lambda: _variant(off_preset="5"), ("OutVariant.off_preset", Reason.CONFLICT, None)),
        (
            lambda: _variant(operand="Y1", immediate=True),
            ("OutVariant.immediate", Reason.CONFLICT, None),
        ),
        (lambda: _debounce(maintained=True), ("OutVariant.maintained", Reason.CONFLICT, None)),
        (lambda: _variant(unit="Td"), ("OutVariant.unit", Reason.CHOICE, None)),
        (
            lambda: _debounce(on_acc="", on_preset="", off_acc="", off_preset=""),
            ("OutVariant.on_preset", Reason.MISSING, "OBJ-006"),
        ),
        (
            lambda: _debounce(off_acc="TD1"),
            ("OutVariant.off_acc", Reason.CONFLICT, "OBJ-012"),
        ),
        (lambda: _variant(on_preset="40000"), ("OutVariant.on_preset", Reason.RANGE, "OBJ-005")),
        (lambda: _variant(on_acc="DS1"), ("OutVariant.on_acc", Reason.BANK, None)),
        (lambda: _variant(operand="SC310"), ("OutVariant.operand", Reason.NOT_WRITABLE, None)),
        # Counter
        (lambda: _counter(kind="up"), ("Counter.kind", Reason.CHOICE, None)),
        (lambda: _counter(reset_enabled=False), ("Counter.reset_enabled", Reason.CHOICE, None)),
        (
            lambda: _counter(kind="count_down", down_enabled=True, pin_rows=(1,)),
            ("Counter.down_enabled", Reason.CONFLICT, None),
        ),
        (lambda: _counter(accumulator="CTD2"), ("Counter.accumulator", Reason.CONFLICT, None)),
        (lambda: _counter(preset="DH1"), ("Counter.preset", Reason.BANK, "OBJ-004")),
        (lambda: _counter(preset="99999999999"), ("Counter.preset", Reason.RANGE, "OBJ-005")),
        (lambda: _counter(pin_rows=(2, 1)), ("Counter.pin_rows", Reason.FORM, None)),
        # Shift
        (lambda: Shift("DS1", "C2"), ("Shift.start_bit", Reason.BANK, "OBJ-004")),
        (lambda: Shift("C1", "C1"), ("Shift.end_bit", Reason.CONFLICT, "OBJ-012")),
        (lambda: Shift("C1", "C2", pin_rows=(300, 400)), ("Shift.pin_rows", Reason.RANGE, None)),
        # Call
        (lambda: Call(""), ("Call.subroutine", Reason.MISSING, None)),
        (lambda: Call("a/b"), ("Call.subroutine", Reason.FORM, "GUI-040")),
        (lambda: Call("x" * 300), ("Call.subroutine", Reason.RANGE, None)),
        # ForLoop
        (lambda: ForLoop(""), ("ForLoop.count", Reason.MISSING, None)),
        (lambda: ForLoop("1 0"), ("ForLoop.count", Reason.FORM, None)),
        (lambda: ForLoop("DH1"), ("ForLoop.count", Reason.BANK, "OBJ-004")),
        (lambda: ForLoop("2147483648"), ("ForLoop.count", Reason.RANGE, "OBJ-005")),
        (lambda: ForLoop("3", oneshot=2), ("ForLoop.oneshot", Reason.FLAG, None)),
        # Drum
        (lambda: _drum("spin"), ("Drum.kind", Reason.CHOICE, None)),
        (
            lambda: _drum(events=["C10"] * 17),
            ("Drum.events", Reason.RANGE, None),
        ),
        (lambda: _drum(outputs=[]), ("Drum.outputs", Reason.RANGE, None)),
        (lambda: _drum(pattern=[[1, 0]]), ("Drum.pattern", Reason.FORM, None)),
        (lambda: _drum(pattern=[[1, 2], [0, 1]]), ("Drum.pattern", Reason.CHOICE, None)),
        (lambda: _drum(outputs=["DS1", "C2"]), ("Drum.outputs[0]", Reason.BANK, None)),
        (lambda: _drum(current_step="C1"), ("Drum.current_step", Reason.BANK, None)),
        (lambda: _drum(outputs=["C1", "C1"]), ("Drum.outputs[1]", Reason.CONFLICT, "OBJ-014")),
        (lambda: _drum(outputs=["C1", "C3"]), ("Drum.outputs[1]", Reason.CONFLICT, "OBJ-014")),
        (
            lambda: _drum(events=["DS1", "C11"]),
            ("Drum.events[0]", Reason.BANK, None),
        ),
        (
            lambda: _drum(events=["C10", ""]),
            ("Drum.events", Reason.MISSING, "OBJ-021"),
        ),
        (lambda: _drum("time_drum", unit="Tx"), ("Drum.unit", Reason.CHOICE, None)),
        (lambda: _drum("time_drum", accumulator="DS1"), ("Drum.accumulator", Reason.BANK, None)),
        (
            lambda: _drum("time_drum", presets=["DH1", "200"]),
            ("Drum.presets[0]", Reason.BANK, "OBJ-004"),
        ),
        (
            lambda: _drum("time_drum", presets=["100", ""]),
            ("Drum.presets", Reason.MISSING, "OBJ-022"),
        ),
        (
            lambda: _drum("time_event_drum", events=["C10"]),
            ("Drum.events", Reason.CONFLICT, None),
        ),
        (
            lambda: _drum("time_event_drum", presets=["100", ""], events=["C10", ""]),
            ("Drum.presets[1]", Reason.MISSING, "OBJ-1019"),
        ),
        (
            lambda: _drum(presets=["100", "200"]),
            ("Drum.presets", Reason.CONFLICT, None),
        ),
        (
            lambda: _drum("time_drum", events=["C10", "C11"]),
            ("Drum.events", Reason.CONFLICT, None),
        ),
        (
            lambda: _drum(jump_enabled=True, jump_step="C1"),
            ("Drum.jump_step", Reason.BANK, None),
        ),
        (lambda: _drum(jog_enabled=2), ("Drum.jog_enabled", Reason.FLAG, None)),
        # Search
        (lambda: _search(op="~"), ("Search.op", Reason.CHOICE, None)),
        (
            lambda: _search(table_start="C1", table_end="C2"),
            ("Search.table_start", Reason.BANK, None),
        ),
        (lambda: _search(result="C1"), ("Search.result", Reason.BANK, None)),
        (lambda: _search(found="DS1"), ("Search.found", Reason.BANK, None)),
        (lambda: _search(value="C1"), ("Search.value", Reason.BANK, None)),
        (lambda: _search(value='"A'), ("Search.value", Reason.ADDRESS, None)),
        (
            lambda: _search(value="TXT1", op=">"),
            ("Search.op", Reason.CONFLICT, None),
        ),
        (lambda: _search(value="0FFh"), ("Search.value", Reason.CONFLICT, None)),
        (lambda: _search(continuous=2), ("Search.continuous", Reason.FLAG, None)),
    ],
)
def test_each_refusal_has_a_reason(build: Any, want: tuple[str, Reason, str | None]) -> None:
    assert _errors(build)[0] == want


def test_a_pair_names_both_fields() -> None:
    assert _fields(lambda: Contact("C1", immediate=True)) == [
        ("Contact.immediate", "Contact.operand")
    ]
    assert _fields(lambda: CompareContact("==", "DS1", "DH1")) == [
        ("CompareContact.left", "CompareContact.right")
    ]
    assert _fields(lambda: _debounce(off_acc="TD1")) == [
        ("OutVariant.off_acc", "OutVariant.on_acc")
    ]
    assert _fields(lambda: _counter(accumulator="CTD2")) == [
        ("Counter.accumulator", "Counter.done")
    ]
    assert _fields(lambda: Shift("C1", "C1")) == [("Shift.end_bit", "Shift.start_bit")]
    assert _fields(lambda: _drum(outputs=["C1", "C1"])) == [("Drum.outputs[1]", "Drum.outputs[0]")]
    assert _fields(lambda: _search(value="0FFh")) == [("Search.value", "Search.table_start")]


# ---------------------------------------------------------------------------
# What a refused field hides, and what it must not
# ---------------------------------------------------------------------------


def test_a_refused_operand_is_not_read_by_a_rule_that_needs_it() -> None:
    assert _errors(lambda: Contact("QQ9", immediate=True)) == [
        ("Contact.operand", Reason.ADDRESS, None)
    ]
    assert _errors(lambda: Shift("QQ9", "C2")) == [("Shift.start_bit", Reason.ADDRESS, None)]
    assert _errors(lambda: _counter(done="QQ9", accumulator="CTD2")) == [
        ("Counter.done", Reason.ADDRESS, None)
    ]


def test_drum_items_refuse_one_by_one() -> None:
    """The refusal of one Drum output does not hide the refusal of another."""
    build = lambda: _drum(outputs=["DS1", "QQ9"])  # noqa: E731
    assert [f for f, _, _ in _errors(build)] == ["Drum.outputs[0]", "Drum.outputs[1]"]


def test_drum_duplicate_outputs_each_refuse() -> None:
    build = lambda: _drum(  # noqa: E731
        outputs=["C1", "C1", "C1"], pattern=[[1, 0, 0], [0, 1, 0]]
    )
    assert [f for f, _, _ in _errors(build)] == ["Drum.outputs[1]", "Drum.outputs[2]"]


def test_drum_blank_step_beside_a_refused_item() -> None:
    """A bad event and a blank event give two refusals.

    The refusal of the blank event names its step, as ``Drum.events[1]``.
    """
    build = lambda: _drum(events=["DS1", ""])  # noqa: E731
    assert _errors(build) == [
        ("Drum.events[0]", Reason.BANK, None),
        ("Drum.events[1]", Reason.MISSING, "OBJ-021"),
    ]


def test_drum_size_and_pattern() -> None:
    """When the number of steps is refused, the pattern is not also refused for having a
    different number of steps."""
    build = lambda: _drum(events=["C10"] * 17)  # noqa: E731
    assert [f for f, _, _ in _errors(build)] == ["Drum.events"]


def test_out_variant_refused_maintained_decides_nothing_about_the_unit() -> None:
    assert _errors(lambda: _debounce(maintained=True)) == [
        ("OutVariant.maintained", Reason.CONFLICT, None)
    ]


def test_out_variant_junk_flag_is_refused_last() -> None:
    assert [f for f, _, _ in _errors(lambda: _variant(operand="DS1", immediate=7))] == [
        "OutVariant.operand",
        "OutVariant.immediate",
    ]


def test_search_range_end_beside_a_refused_start() -> None:
    build = lambda: _search(table_start="QQ9", table_end="C2")  # noqa: E731
    assert [f for f, _, _ in _errors(build)] == ["Search.table_start", "Search.table_end"]


# ---------------------------------------------------------------------------
# Every refusal in these modules has a reason
# ---------------------------------------------------------------------------

_MODULES = (
    "contact",
    "comparison",
    "out_variant",
    "counter",
    "shift",
    "call",
    "forloop",
    "end",
    "return_",
    "drum",
    "search",
)


def _calls(name: str) -> list[ast.Call]:
    path = Path(laddercodec.__file__).parent / "instructions" / f"{name}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


@pytest.mark.parametrize("module", _MODULES)
def test_every_refusal_written_here_gives_a_reason(module: str) -> None:
    """Every ``FieldError(...)`` in the module passes ``reason=``.

    Every ``check.refuse(...)`` passes a reason as its third argument or as ``reason=``.
    """
    for call in _calls(module):
        func = call.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name == "FieldError":
            assert any(k.arg == "reason" for k in call.keywords), f"{module}:{call.lineno}"
        elif name == "refuse" and isinstance(func, ast.Attribute):
            given = len(call.args) >= 3 or any(k.arg == "reason" for k in call.keywords)
            assert given, f"{module}:{call.lineno}"


def test_drum_refused_kind_leaves_out_the_checks_that_read_it() -> None:
    build = lambda: Drum(  # noqa: E731
        "zzz",
        outputs=["Y1", "Y2"],
        presets=["X1", "X2"],
        events=["ZZ", ""],
        pattern=[[1, 0], [0, 1]],
        current_step="DS1",
        completion_flag="C1",
    )
    assert _errors(build) == [("Drum.kind", Reason.CHOICE, None)]


def test_out_variant_junk_maintained_refuses_unit_first() -> None:
    build = lambda: _variant(maintained="x")  # noqa: E731
    assert [(f, r) for f, r, _ in _errors(build)] == [
        ("OutVariant.unit", Reason.CHOICE),
        ("OutVariant.maintained", Reason.FLAG),
    ]
