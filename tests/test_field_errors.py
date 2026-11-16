"""The field error pyrung reads: every refusal of one construction, each with a stable shape.

``FieldError.errors`` holds every refusal, the raised one first; ``field`` is ``Class.attr``;
``reason`` is a :class:`~laddercodec.Reason` and ``click_id`` CLICK's own error id.  The
fixture in ``conftest.py`` checks the field and reason of every refusal the suite builds.
"""

from __future__ import annotations

import dataclasses
import pickle
from typing import Any

import pytest

from laddercodec import (
    AddressError,
    Coil,
    CompareContact,
    Counter,
    Drum,
    FieldError,
    ForLoop,
    Math,
    ModbusRtuTarget,
    Reason,
    Receive,
    Send,
    Shift,
    Timer,
)
from laddercodec.model import AfInstruction, InstructionType
from laddercodec.operands.address import check_address, display_form_only
from laddercodec.operands.checks import (
    ALL_KINDS,
    Constants,
    Refusals,
    check_constant,
    check_flag,
    check_operand,
    check_out_target,
    check_quoted_text,
)
from laddercodec.operands.constants import Kind

OUT, LATCH = InstructionType.COIL_OUT, InstructionType.COIL_LATCH


def _refusals(build: Any) -> tuple[FieldError, ...]:
    with pytest.raises(FieldError) as caught:
        build()
    assert caught.value.errors[0] is caught.value
    return caught.value.errors


def _shape(errors: tuple[FieldError, ...]) -> list[tuple[str | None, str | None, str | None]]:
    return [(e.field, e.reason, e.click_id) for e in errors]


def _timer(**kw: Any) -> Timer:
    fields: dict[str, Any] = dict(
        timer_type="on_delay", done_bit="T1", current="TD1", setpoint="100", unit="Tms"
    )
    return Timer(**{**fields, **kw})


# ---------------------------------------------------------------------------
# The error
# ---------------------------------------------------------------------------


def test_reason_set_is_fixed() -> None:
    assert [r.value for r in Reason] == [
        "address",
        "bank",
        "range",
        "pointer",
        "kind",
        "form",
        "not_writable",
        "flag",
        "choice",
        "conflict",
        "missing",
    ]
    assert Reason.BANK == "bank"


def test_a_lone_refusal_is_its_own_errors() -> None:
    exc = FieldError("Coil.operand: no", field="Coil.operand")
    assert exc.errors == (exc,)
    assert exc.fields == ("Coil.operand",)
    assert (exc.reason, exc.click_id, exc.obj) == (None, None, None)


def test_a_pair_names_both_fields() -> None:
    exc = FieldError("no", field=("CompareContact.left", "CompareContact.right"))
    assert exc.field == "CompareContact.left"
    assert exc.fields == ("CompareContact.left", "CompareContact.right")


def test_no_field() -> None:
    exc = FieldError("raw(Tmr,...): pins= can't follow the hex", field=None)
    assert (exc.field, exc.fields) == (None, ())


def test_pickle_keeps_every_refusal() -> None:
    with pytest.raises(FieldError) as caught:
        _timer(done_bit="C1", setpoint="40000")
    copy = pickle.loads(pickle.dumps(caught.value))
    assert type(copy) is AddressError
    assert [str(e) for e in copy.errors] == [str(e) for e in caught.value.errors]
    assert copy.errors[0] is copy
    assert _shape(copy.errors) == _shape(caught.value.errors)


# ---------------------------------------------------------------------------
# Collection: Timer
# ---------------------------------------------------------------------------


def test_timer_gives_every_refusal() -> None:
    """A wrong done bit and a set point of 40000: two refusals; the TD match is not checked."""
    errors = _refusals(lambda: _timer(done_bit="C1", setpoint="40000"))
    assert _shape(errors) == [
        ("Timer.done_bit", "bank", None),
        ("Timer.setpoint", "range", "OBJ-005"),
    ]
    assert all(isinstance(e.obj, Timer) for e in errors)
    assert str(errors[1]) == "Timer.setpoint: '40000' is outside 0 to 32767 (OBJ-005)"


def test_timer_current_against_done_bit() -> None:
    (error,) = _refusals(lambda: _timer(current="TD2"))
    assert error.fields == ("Timer.current", "Timer.done_bit")
    assert error.reason == Reason.CONFLICT


def test_timer_checks_current_alone_when_done_bit_is_refused() -> None:
    errors = _refusals(lambda: _timer(done_bit="T0", current="DS1"))
    assert _shape(errors) == [
        ("Timer.done_bit", "address", None),
        ("Timer.current", "bank", None),
    ]


def test_timer_reasons() -> None:
    errors = _refusals(
        lambda: _timer(timer_type="bogus", unit="Tx", retained=2, setpoint="DS[DS1]")
    )
    assert _shape(errors) == [
        ("Timer.retained", "flag", None),
        ("Timer.timer_type", "choice", None),
        ("Timer.unit", "choice", None),
        ("Timer.setpoint", "pointer", None),
    ]
    # A refused flag keeps the value given.
    assert errors[0].obj.retained == 2


def test_timer_retained_off_delay_needs_both_fields_taken() -> None:
    (error,) = _refusals(lambda: _timer(timer_type="off_delay", retained=True))
    assert error.fields == ("Timer.retained", "Timer.timer_type")
    assert error.reason == Reason.CONFLICT
    # A refused flag value is not read again for the pair.
    (flag,) = _refusals(lambda: _timer(timer_type="off_delay", retained=2))
    assert flag.reason == Reason.FLAG


def test_timer_pin_rows() -> None:
    errors = _refusals(lambda: _timer(setpoint="40000", pin_rows=(0,)))
    assert _shape(errors) == [
        ("Timer.setpoint", "range", "OBJ-005"),
        ("Timer.pin_rows", "range", None),
    ]


# ---------------------------------------------------------------------------
# Collection: Coil
# ---------------------------------------------------------------------------


def test_coil_gives_every_refusal() -> None:
    errors = _refusals(lambda: Coil(LATCH, "X1", "SC1", oneshot=True))
    assert _shape(errors) == [
        ("Coil.oneshot", "conflict", None),
        ("Coil.operand", "bank", "OBJ-004"),
        ("Coil.range_end", "not_writable", "OBJ-003"),
    ]
    assert errors[0].fields == ("Coil.oneshot", "Coil.type")


@pytest.mark.parametrize("kind", [OUT, LATCH, InstructionType.COIL_RESET])
@pytest.mark.parametrize(
    ("start", "end", "click_id"),
    [("C5", "Y5", "OBJ-008"), ("C9", "C1", "OBJ-009"), ("C5", "C5", "OBJ-012")],
)
def test_coil_range(kind: InstructionType, start: str, end: str, click_id: str) -> None:
    """Out, Set and Reset give the same ids: another bank, an end below, the same address."""
    (error,) = _refusals(lambda: Coil(kind, start, end))
    assert error.fields == ("Coil.range_end", "Coil.operand")
    assert (error.reason, error.click_id) == (Reason.CONFLICT, click_id)
    assert str(error).endswith(f" ({click_id})")


def test_coil_skips_what_depends_on_a_refused_field() -> None:
    # A refused type: the one-shot pairing is not checked.
    assert _shape(_refusals(lambda: Coil(99, "C1", oneshot=True))) == [  # type: ignore[arg-type]
        ("Coil.type", "choice", None)
    ]
    # A refused immediate flag: C1 is not refused as an immediate target.
    assert _shape(_refusals(lambda: Coil(OUT, "C1", immediate=2))) == [
        ("Coil.immediate", "flag", None)
    ]
    # A refused range start: the range pairing is not checked.
    assert _shape(_refusals(lambda: Coil(OUT, "C0", "Y5"))) == [("Coil.operand", "address", None)]


def test_coil_typed_text_is_named_in_each_refusal() -> None:
    errors = _refusals(lambda: Coil(OUT, "x1", "c0"))
    assert [str(e) for e in errors] == [
        "Coil.operand: 'x1' (X001) is not allowed; Coil.operand takes Y, C, SC (OBJ-004)",
        "Coil.range_end: 'c0' (C0) is outside C1-C2000",
    ]


def test_coil_immediate_target_is_a_conflict_with_immediate() -> None:
    (error,) = _refusals(lambda: Coil(OUT, "C1", immediate=True))
    assert error.fields == ("Coil.operand", "Coil.immediate")
    assert error.reason == Reason.CONFLICT
    # A pair refuses its leading field only: the range end is checked against immediate too.
    errors = _refusals(lambda: Coil(OUT, "C1", "C5", immediate=True))
    assert [e.fields for e in errors] == [
        ("Coil.operand", "Coil.immediate"),
        ("Coil.range_end", "Coil.immediate"),
    ]


@pytest.mark.parametrize("kind", [OUT, LATCH, InstructionType.COIL_RESET])
def test_coil_bank_id(kind: InstructionType) -> None:
    (error,) = _refusals(lambda: Coil(kind, "DS1"))
    assert (error.reason, error.click_id) == (Reason.BANK, "OBJ-004")


@pytest.mark.parametrize("kind", [OUT, LATCH, InstructionType.COIL_RESET])
def test_coil_sc_not_writable_is_obj_003(kind: InstructionType) -> None:
    (error,) = _refusals(lambda: Coil(kind, "SC163"))
    assert (error.field, error.reason, error.click_id) == (
        "Coil.operand",
        Reason.NOT_WRITABLE,
        "OBJ-003",
    )
    assert str(error).endswith(" (OBJ-003)")
    assert Coil(kind, "SC50").operand == "SC50"
    assert Coil(kind, "SC162").operand == "SC162"


# ---------------------------------------------------------------------------
# A crash after a refusal still raises the refusal
# ---------------------------------------------------------------------------


def test_timer_refusal_survives_a_later_crash() -> None:
    with pytest.raises(FieldError) as caught:
        Timer("on_delay", "T1", "TD1", None, unit="bogus")  # type: ignore[arg-type]
    assert caught.value.field == "Timer.unit"
    assert isinstance(caught.value.__cause__, TypeError)


def test_coil_refusal_survives_a_later_crash() -> None:
    with pytest.raises(FieldError) as caught:
        Coil(OUT, 5, immediate=2)  # type: ignore[arg-type]
    assert caught.value.field == "Coil.immediate"
    assert isinstance(caught.value.__cause__, TypeError)


def test_a_crash_with_no_refusal_is_raised_as_is() -> None:
    with pytest.raises(TypeError):
        _timer(setpoint=None)


# ---------------------------------------------------------------------------
# Refusals: items, nested constructions, errors raised out of the block
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _Inner(AfInstruction):
    a: str = ""
    b: str = ""

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            check.refuse("a", "is refused", Reason.KIND)
            check.refuse("b", "is refused", Reason.FORM)


@dataclasses.dataclass
class _Outer(AfInstruction):
    items: tuple[str, ...] = ()
    other: str = ""
    mode: str = ""

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            if self.mode == "item":
                check.refuse("items[1]", "is refused", Reason.BANK)
                check.refuse("items", "is refused too", Reason.RANGE)  # its item was refused
                check.refuse("other", "is refused", Reason.KIND)
            elif self.mode == "pair":
                check.refuse(("items", "other"), "is refused", Reason.CONFLICT)
                check.refuse(("other", "mode"), "is refused too", Reason.CONFLICT)
                check.refuse("items[0]", "is skipped", Reason.BANK)  # items leads a refusal
            elif self.mode == "list":
                check.refuse("items", "is refused", Reason.RANGE)
                assert check.refused("items[0]")
                check.refuse("items[2]", "is refused too", Reason.BANK)
            elif self.mode == "nested":
                check.refuse("other", "is refused", Reason.KIND)
                check.run(_Inner)
            elif self.mode == "raised":
                check.refuse("other", "is refused", Reason.KIND)
                raise FieldError("_Outer.other: again", field="_Outer.other")
            elif self.mode == "raised nested":
                _Inner()


def test_an_item_refused_covers_its_list() -> None:
    errors = _refusals(lambda: _Outer(mode="item"))
    assert [e.field for e in errors] == ["_Outer.items[1]", "_Outer.other"]


def test_a_pair_refuses_its_leading_field_only() -> None:
    errors = _refusals(lambda: _Outer(mode="pair"))
    assert [e.fields for e in errors] == [
        ("_Outer.items", "_Outer.other"),
        ("_Outer.other", "_Outer.mode"),
    ]


def test_a_list_refused_covers_its_items() -> None:
    errors = _refusals(lambda: _Outer(mode="list"))
    assert [e.field for e in errors] == ["_Outer.items"]


def test_a_nested_construction_keeps_every_inner_refusal() -> None:
    errors = _refusals(lambda: _Outer(mode="nested"))
    assert [e.field for e in errors] == ["_Outer.other", "_Inner.a", "_Inner.b"]
    assert [type(e.obj) for e in errors] == [_Outer, _Inner, _Inner]


def test_a_nested_construction_raised_out_of_the_block() -> None:
    errors = _refusals(lambda: _Outer(mode="raised nested"))
    assert [e.field for e in errors] == ["_Inner.a", "_Inner.b"]


def test_an_error_raised_out_of_the_block_is_checked_as_a_refusal() -> None:
    errors = _refusals(lambda: _Outer(mode="raised"))
    assert [str(e) for e in errors] == ["_Outer.other: is refused"]


# ---------------------------------------------------------------------------
# Not converted yet: one refusal, a uniform field
# ---------------------------------------------------------------------------


def test_unconverted_class_raises_one_refusal() -> None:
    (error,) = _refusals(lambda: Counter("count_up", "CT1", "CTD2", "1", reset_enabled=True))
    assert error.field == "Counter.current"


def test_labels_are_not_fields() -> None:
    """Send and Receive messages keep their wording; the field is ``Class.attr``."""
    target = ModbusRtuTarget(name="r", com_port="cpu2", device_id=1)
    common: dict[str, Any] = dict(
        target=target, remote_start="DS1", quantity=1, success="", error="",
        exception_response="",
    )  # fmt: skip
    (dest,) = _refusals(lambda: Receive(dest="X001", receiving="", **common))
    assert (dest.field, dest.reason) == ("Receive.dest", Reason.BANK)
    assert str(dest).startswith("Receive dest: ")
    (status,) = _refusals(lambda: Send(source="DS2", sending="DS1", **common))
    assert (status.field, status.reason) == ("Send.sending", Reason.BANK)
    assert str(status).startswith("Send sending: ")


def test_compare_group_names_both_operands() -> None:
    (error,) = _refusals(lambda: CompareContact("==", "DS1", "DH1"))
    assert error.fields == ("CompareContact.left", "CompareContact.right")


def test_drum_event_names_its_list_item() -> None:
    def build() -> Drum:
        return Drum(
            "event", outputs=["C1"], events_or_presets=["DS1"], pattern=[[1]],
            current_step="DS1", completion_flag="C2",
        )  # fmt: skip

    (error,) = _refusals(build)
    assert (error.field, error.reason) == ("Drum.events_or_presets[0]", Reason.BANK)
    assert str(error).startswith("Drum.events[0]: ")


def test_display_form_refusal_names_the_field() -> None:
    with display_form_only():
        errors = _refusals(lambda: _timer(done_bit="T01", setpoint="ds1"))
    assert _shape(errors) == [("Timer.done_bit", "form", None), ("Timer.setpoint", "form", None)]


def test_sweep_refuses_a_field_that_is_no_dataclass_field() -> None:
    """The conftest fixture is active: a refusal naming no field of its class fails."""

    @dataclasses.dataclass
    class Box(AfInstruction):
        operand: str = "C1"

        def __post_init__(self) -> None:
            with Refusals(self) as check:
                check.refuse("nothing", "is refused", Reason.KIND)

    with pytest.raises(AssertionError, match="Box.nothing"):
        Box()


# ---------------------------------------------------------------------------
# The shared checks: a reason for every refusal
# ---------------------------------------------------------------------------

_INT = Constants(frozenset({Kind.INTEGER}), signs="", low=0, high=100)
_TEXT1 = Constants(frozenset({Kind.TEXT}), text_max=1)


@pytest.mark.parametrize(
    ("call", "reason", "click_id"),
    [
        (lambda: check_address("1X", "X.f"), "address", None),
        (lambda: check_address("QQ1", "X.f"), "address", None),
        (lambda: check_address("C1", "X.f", {"DS"}), "bank", None),
        (lambda: check_address("C1", "X.f", {"DS"}, bank_id="OBJ-004"), "bank", "OBJ-004"),
        (lambda: check_address("C0", "X.f"), "address", None),
        (lambda: check_address("DS5000", "X.f"), "address", None),
        (lambda: check_address("DS0u", "X.f"), "address", None),
        (lambda: check_address("XD0u", "X.f"), "form", None),
        (lambda: check_constant("1.5", "X.f", _INT), "kind", None),
        (lambda: check_constant("abc", "X.f", _INT), "kind", None),
        (lambda: check_constant("101", "X.f", _INT), "range", "OBJ-005"),
        (lambda: check_constant("99999999999", "X.f", _INT), "range", "OBJ-005"),
        (lambda: check_constant("-1", "X.f", _INT), "form", "OBJ-005"),
        (lambda: check_constant('"AB"', "X.f", _TEXT1), "range", None),
        (lambda: check_constant('""', "X.f", Constants(ALL_KINDS)), "range", None),
        (lambda: check_constant('"a"b"', "X.f", Constants(ALL_KINDS)), "form", None),
        (lambda: check_constant('"\t"', "X.f", Constants(ALL_KINDS)), "form", None),
        (lambda: check_constant("$1", "X.f", Constants(ALL_KINDS)), "form", None),
        (lambda: check_constant("+1h", "X.f", Constants(ALL_KINDS)), "form", None),
        (
            lambda: check_constant("1FFFFh", "X.f", Constants(ALL_KINDS, hex_high=0xFFFF)),
            "range",
            "OBJ-005",
        ),  # fmt: skip
        (lambda: check_constant("1E39", "X.f", Constants(ALL_KINDS)), "range", None),
        (
            lambda: check_constant("12", "X.f", Constants(ALL_KINDS, max_length=1)),
            "range",
            "OBJ-005",
        ),  # fmt: skip
        (lambda: check_operand("DS[DS1]", "X.f"), "pointer", None),
        (lambda: check_operand("X[DS1]", "X.f", pointer=True), "pointer", None),
        (lambda: check_operand("DS[DS0]", "X.f", pointer=True), "pointer", None),
        (lambda: check_out_target("C1", "X.f", immediate=True), "conflict", None),
        (lambda: check_out_target("SC1", "X.f"), "not_writable", None),
        (lambda: check_flag(2, "X.f"), "flag", None),
        (lambda: check_quoted_text('""', "X.f"), "range", None),
        (lambda: check_quoted_text('"\t"', "X.f"), "form", None),
        (lambda: check_quoted_text('"a"b"', "X.f"), "form", None),
    ],
)
def test_shared_check_reason(call: Any, reason: str, click_id: str | None) -> None:
    with pytest.raises(FieldError) as caught:
        call()
    exc = caught.value
    assert (exc.field, exc.reason, exc.click_id) == ("X.f", reason, click_id)
    assert str(exc).endswith(f"({click_id})") == (click_id is not None)


def test_immediate_names_the_immediate_field() -> None:
    with pytest.raises(FieldError) as caught:
        check_out_target("C1", "OutVariant.operand", immediate=True)
    assert caught.value.fields == ("OutVariant.operand", "OutVariant.immediate")


@pytest.mark.parametrize(
    ("build", "field", "click_id"),
    [
        (lambda: _timer(setpoint="DD1"), "Timer.setpoint", "OBJ-004"),
        (lambda: Shift("DS1", "C2"), "Shift.start_bit", "OBJ-004"),
        (lambda: Shift("C1", "C1"), "Shift.end_bit", "OBJ-012"),
        (lambda: Counter("count_up", "CT1", "CTD1", "DH1"), "Counter.preset", "OBJ-004"),
        (lambda: ForLoop("DH1"), "ForLoop.limit", "OBJ-004"),
        (lambda: Math("1", "C1"), "Math.result", "OBJ-004"),
    ],
)
def test_click_id_where_the_dialog_is_known(build: Any, field: str, click_id: str) -> None:
    (error,) = _refusals(build)
    assert (error.field, error.click_id) == (field, click_id)
    assert str(error).endswith(f"({click_id})")


def test_shift_same_ends_is_a_conflict() -> None:
    (error,) = _refusals(lambda: Shift("C1", "C1"))
    assert error.fields == ("Shift.end_bit", "Shift.start_bit")
    assert error.reason == Reason.CONFLICT


def test_every_reason_has_a_docstring() -> None:
    """A string after each member, which the API reference shows."""
    import ast
    import inspect

    from laddercodec.operands import errors

    (cls,) = [
        n for n in ast.parse(inspect.getsource(errors)).body
        if isinstance(n, ast.ClassDef) and n.name == "Reason"
    ]  # fmt: skip
    body = cls.body
    documented = {
        node.targets[0].id
        for node, after in zip(body, body[1:], strict=False)
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and isinstance(after, ast.Expr) and isinstance(after.value, ast.Constant)
        and isinstance(after.value.value, str)
    }  # fmt: skip
    assert documented == set(Reason.__members__)


def test_label_names_the_message_only() -> None:
    with pytest.raises(AddressError) as caught:
        check_address("C2001", "Send.source", label="Send source (FC05)")
    assert caught.value.field == "Send.source"
    assert str(caught.value) == "Send source (FC05): 'C2001' is outside C1-C2000"
