"""Box and contact instructions report every field they refuse, each with a reason.

Contact, CompareContact, OutVariant, Counter, Shift, Call, ForLoop, Drum and Search run their
checks through ``Refusals``: an instruction with two independent bad fields reports both in
``FieldError.errors``, the first being the one raised.
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
)
from laddercodec.instructions.out_variant import OutVariant
from laddercodec.model import InstructionType

NO, EDGE = InstructionType.CONTACT_NO, InstructionType.CONTACT_EDGE


def _errors(build: Any) -> list[tuple[str | None, Reason | None, str | None]]:
    with pytest.raises(FieldError) as caught:
        build()
    assert caught.value.errors[0] is caught.value
    return [(e.field, e.reason, e.click_id) for e in caught.value.errors]


def _fields(build: Any) -> list[tuple[str, ...]]:
    with pytest.raises(FieldError) as caught:
        build()
    return [e.fields for e in caught.value.errors]


def _drum(kind: str = "event", **kw: Any) -> Drum:
    fields: dict[str, Any] = dict(
        drum_kind=kind,
        outputs=["C1", "C2"],
        events_or_presets=["C10", "C11"],
        pattern=[[1, 0], [0, 1]],
        current_step="DS1",
        completion_flag="C3",
    )
    if kind != "event":
        fields.update(events_or_presets=["100", "200"], unit="Tms", accumulator="TD1")
    if kind == "time_event":
        fields.update(events=["C10", "C11"])
    return Drum(**{**fields, **kw})


def _search(**kw: Any) -> Search:
    fields: dict[str, Any] = dict(
        table_start="DS1",
        table_end="DS5",
        source="DS10",
        result="DS11",
        found="C1",
        comparison="==",
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
    fields: dict[str, Any] = dict(
        counter_type="count_up", done_bit="CT1", current="CTD1", preset="100"
    )
    return Counter(**{**fields, **kw})


# ---------------------------------------------------------------------------
# Two independent bad fields report both
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "want"),
    [
        (
            lambda: Contact(NO, "DS1", immediate=7),
            [("Contact.immediate", Reason.FLAG), ("Contact.operand", Reason.BANK)],
        ),
        (
            lambda: Contact(EDGE, "DS1", edge_kind="up"),
            [("Contact.operand", Reason.BANK), ("Contact.edge_kind", Reason.CHOICE)],
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
            lambda: _counter(counter_type="up", preset="DH1"),
            [("Counter.counter_type", Reason.CHOICE), ("Counter.preset", Reason.BANK)],
        ),
        (
            lambda: Shift("DS1", "DS2"),
            [("Shift.start_bit", Reason.BANK), ("Shift.end_bit", Reason.BANK)],
        ),
        (
            lambda: ForLoop("DH1", oneshot=7),
            [("ForLoop.limit", Reason.BANK), ("ForLoop.oneshot", Reason.FLAG)],
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
            lambda: _search(table_start="C1", table_end="C2", comparison="~"),
            [
                ("Search.comparison", Reason.CHOICE),
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
        (lambda: Contact(InstructionType.COIL_OUT, "C1"), ("Contact.type", Reason.CHOICE, None)),
        (lambda: Contact(NO, "DS1"), ("Contact.operand", Reason.BANK, None)),
        (lambda: Contact(NO, "C1", immediate=True), ("Contact.immediate", Reason.CONFLICT, None)),
        (
            lambda: Contact(EDGE, "X1", immediate=True, edge_kind="rise"),
            ("Contact.immediate", Reason.CONFLICT, None),
        ),
        (lambda: Contact(EDGE, "X1"), ("Contact.edge_kind", Reason.CHOICE, None)),
        (
            lambda: Contact(NO, "X1", edge_kind="rise"),
            ("Contact.edge_kind", Reason.CONFLICT, None),
        ),
        (lambda: Contact(NO, "X1", wire_down=2), ("Contact.wire_down", Reason.FLAG, None)),
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
        (lambda: _counter(counter_type="up"), ("Counter.counter_type", Reason.CHOICE, None)),
        (lambda: _counter(reset_enabled=False), ("Counter.reset_enabled", Reason.CHOICE, None)),
        (
            lambda: _counter(counter_type="count_down", down_enabled=True, pin_rows=(1,)),
            ("Counter.down_enabled", Reason.CONFLICT, None),
        ),
        (lambda: _counter(current="CTD2"), ("Counter.current", Reason.CONFLICT, None)),
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
        (lambda: ForLoop(""), ("ForLoop.limit", Reason.MISSING, None)),
        (lambda: ForLoop("1 0"), ("ForLoop.limit", Reason.FORM, None)),
        (lambda: ForLoop("DH1"), ("ForLoop.limit", Reason.BANK, "OBJ-004")),
        (lambda: ForLoop("2147483648"), ("ForLoop.limit", Reason.RANGE, "OBJ-005")),
        (lambda: ForLoop("3", oneshot=2), ("ForLoop.oneshot", Reason.FLAG, None)),
        # Drum
        (lambda: _drum("spin"), ("Drum.drum_kind", Reason.CHOICE, None)),
        (
            lambda: _drum(events_or_presets=["C10"] * 17),
            ("Drum.events_or_presets", Reason.RANGE, None),
        ),
        (lambda: _drum(outputs=[]), ("Drum.outputs", Reason.RANGE, None)),
        (lambda: _drum(pattern=[[1, 0]]), ("Drum.pattern", Reason.FORM, None)),
        (lambda: _drum(pattern=[[1, 2], [0, 1]]), ("Drum.pattern", Reason.CHOICE, None)),
        (lambda: _drum(outputs=["DS1", "C2"]), ("Drum.outputs[0]", Reason.BANK, None)),
        (lambda: _drum(current_step="C1"), ("Drum.current_step", Reason.BANK, None)),
        (lambda: _drum(outputs=["C1", "C1"]), ("Drum.outputs[1]", Reason.CONFLICT, "OBJ-014")),
        (lambda: _drum(outputs=["C1", "C3"]), ("Drum.outputs[1]", Reason.CONFLICT, "OBJ-014")),
        (
            lambda: _drum(events_or_presets=["DS1", "C11"]),
            ("Drum.events_or_presets[0]", Reason.BANK, None),
        ),
        (
            lambda: _drum(events_or_presets=["C10", ""]),
            ("Drum.events_or_presets", Reason.MISSING, "OBJ-021"),
        ),
        (lambda: _drum("time", unit="Tx"), ("Drum.unit", Reason.CHOICE, None)),
        (lambda: _drum("time", accumulator="DS1"), ("Drum.accumulator", Reason.BANK, None)),
        (
            lambda: _drum("time", events_or_presets=["DH1", "200"]),
            ("Drum.events_or_presets[0]", Reason.BANK, "OBJ-004"),
        ),
        (
            lambda: _drum("time", events_or_presets=["100", ""]),
            ("Drum.events_or_presets", Reason.MISSING, "OBJ-022"),
        ),
        (lambda: _drum("time_event", events=["C10"]), ("Drum.events", Reason.CONFLICT, None)),
        (
            lambda: _drum("time_event", events_or_presets=["100", ""], events=["C10", ""]),
            ("Drum.events_or_presets[1]", Reason.MISSING, "OBJ-1019"),
        ),
        (
            lambda: _drum(jump_enabled=True, jump_target="C1"),
            ("Drum.jump_target", Reason.BANK, None),
        ),
        (lambda: _drum(jog_enabled=2), ("Drum.jog_enabled", Reason.FLAG, None)),
        # Search
        (lambda: _search(comparison="~"), ("Search.comparison", Reason.CHOICE, None)),
        (
            lambda: _search(table_start="C1", table_end="C2"),
            ("Search.table_start", Reason.BANK, None),
        ),
        (lambda: _search(result="C1"), ("Search.result", Reason.BANK, None)),
        (lambda: _search(found="DS1"), ("Search.found", Reason.BANK, None)),
        (lambda: _search(source="C1"), ("Search.source", Reason.BANK, None)),
        (lambda: _search(source='"A'), ("Search.source", Reason.ADDRESS, None)),
        (
            lambda: _search(source="TXT1", comparison=">"),
            ("Search.comparison", Reason.CONFLICT, None),
        ),
        (lambda: _search(source="0FFh"), ("Search.source", Reason.CONFLICT, None)),
        (lambda: _search(continuous=2), ("Search.continuous", Reason.FLAG, None)),
    ],
)
def test_each_refusal_has_a_reason(build: Any, want: tuple[str, Reason, str | None]) -> None:
    assert _errors(build)[0] == want


def test_a_pair_names_both_fields() -> None:
    assert _fields(lambda: Contact(NO, "C1", immediate=True)) == [
        ("Contact.immediate", "Contact.operand")
    ]
    assert _fields(lambda: CompareContact("==", "DS1", "DH1")) == [
        ("CompareContact.left", "CompareContact.right")
    ]
    assert _fields(lambda: _debounce(off_acc="TD1")) == [
        ("OutVariant.off_acc", "OutVariant.on_acc")
    ]
    assert _fields(lambda: _counter(current="CTD2")) == [("Counter.current", "Counter.done_bit")]
    assert _fields(lambda: Shift("C1", "C1")) == [("Shift.end_bit", "Shift.start_bit")]
    assert _fields(lambda: _drum(outputs=["C1", "C1"])) == [("Drum.outputs[1]", "Drum.outputs[0]")]
    assert _fields(lambda: _search(source="0FFh")) == [("Search.source", "Search.table_start")]


# ---------------------------------------------------------------------------
# What a refused field hides, and what it must not
# ---------------------------------------------------------------------------


def test_a_refused_operand_is_not_read_by_a_rule_that_needs_it() -> None:
    assert _errors(lambda: Contact(NO, "QQ9", immediate=True)) == [
        ("Contact.operand", Reason.ADDRESS, None)
    ]
    assert _errors(lambda: Shift("QQ9", "C2")) == [("Shift.start_bit", Reason.ADDRESS, None)]
    assert _errors(lambda: _counter(done_bit="QQ9", current="CTD2")) == [
        ("Counter.done_bit", Reason.ADDRESS, None)
    ]


def test_drum_items_refuse_one_by_one() -> None:
    """An item refusal does not hide another item's."""
    build = lambda: _drum(outputs=["DS1", "QQ9"])  # noqa: E731
    assert [f for f, _, _ in _errors(build)] == ["Drum.outputs[0]", "Drum.outputs[1]"]


def test_drum_duplicate_outputs_each_refuse() -> None:
    build = lambda: _drum(  # noqa: E731
        outputs=["C1", "C1", "C1"], pattern=[[1, 0, 0], [0, 1, 0]]
    )
    assert [f for f, _, _ in _errors(build)] == ["Drum.outputs[1]", "Drum.outputs[2]"]


def test_drum_blank_step_beside_a_refused_item() -> None:
    """A bad event and a blank step are two refusals, the blank one named by its step."""
    build = lambda: _drum(events_or_presets=["DS1", ""])  # noqa: E731
    assert _errors(build) == [
        ("Drum.events_or_presets[0]", Reason.BANK, None),
        ("Drum.events_or_presets[1]", Reason.MISSING, "OBJ-021"),
    ]


def test_drum_size_and_pattern() -> None:
    """A wrong step count does not also report the pattern against it."""
    build = lambda: _drum(events_or_presets=["C10"] * 17)  # noqa: E731
    assert [f for f, _, _ in _errors(build)] == ["Drum.events_or_presets"]


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
    """``FieldError(...)`` names a ``reason=``; ``check.refuse(...)`` gives one as its third
    argument (or ``reason=``)."""
    for call in _calls(module):
        func = call.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name == "FieldError":
            assert any(k.arg == "reason" for k in call.keywords), f"{module}:{call.lineno}"
        elif name == "refuse" and isinstance(func, ast.Attribute):
            given = len(call.args) >= 3 or any(k.arg == "reason" for k in call.keywords)
            assert given, f"{module}:{call.lineno}"
