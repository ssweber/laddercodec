"""Test the shape of FieldError, which pyrung reads.

One construction raises one FieldError, and ``FieldError.errors`` holds every refusal, with
the raised one first. In each refusal, ``field`` is ``Class.attr``, ``reason`` is a
:class:`~laddercodec.Reason`, and ``click_id`` is CLICK's own error id. The fixture in
``conftest.py`` checks the field and reason of every refusal that the test suite builds.
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
from laddercodec.codes import Code
from laddercodec.instructions.coil import CoilKind
from laddercodec.model import AfInstruction
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


def _refusals(build: Any) -> tuple[FieldError, ...]:
    with pytest.raises(FieldError) as caught:
        build()
    assert caught.value.errors[0] is caught.value
    return caught.value.errors


def _shape(errors: tuple[FieldError, ...]) -> list[tuple[str | None, str | None, str | None]]:
    return [(e.field, e.reason, e.click_id) for e in errors]


def _timer(**kw: Any) -> Timer:
    fields: dict[str, Any] = dict(
        kind="on_delay", done="T1", accumulator="TD1", preset="100", unit="Tms"
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
    exc = FieldError("Coil.operand: no", field="Coil.operand", code=Code.BANK_NOT_ALLOWED)
    assert exc.errors == (exc,)
    assert exc.fields == ("Coil.operand",)
    assert (exc.reason, exc.click_id, exc.obj) == (None, None, None)


def test_a_pair_names_both_fields() -> None:
    exc = FieldError(
        "no",
        field=("CompareContact.left", "CompareContact.right"),
        code=Code.COMPARE_MIXED_TYPES,
    )
    assert exc.field == "CompareContact.left"
    assert exc.fields == ("CompareContact.left", "CompareContact.right")


def test_no_field() -> None:
    exc = FieldError(
        "raw(Tmr,...): pins= can't follow the hex", field=None, code=Code.INVALID_TOKEN
    )
    assert (exc.field, exc.fields) == (None, ())


def test_pickle_keeps_every_refusal() -> None:
    with pytest.raises(FieldError) as caught:
        _timer(done="C1", preset="40000")
    copy = pickle.loads(pickle.dumps(caught.value))
    assert type(copy) is AddressError
    assert [str(e) for e in copy.errors] == [str(e) for e in caught.value.errors]
    assert copy.errors[0] is copy
    assert _shape(copy.errors) == _shape(caught.value.errors)
    assert [e.code for e in copy.errors] == [e.code for e in caught.value.errors]


# ---------------------------------------------------------------------------
# Collection: Timer
# ---------------------------------------------------------------------------


def test_timer_gives_every_refusal() -> None:
    """A done bit in the wrong bank and a preset of 40000 give two refusals.

    The accumulator is not checked against the refused done bit."""
    errors = _refusals(lambda: _timer(done="C1", preset="40000"))
    assert _shape(errors) == [
        ("Timer.done", "bank", None),
        ("Timer.preset", "range", "OBJ-005"),
    ]
    assert all(isinstance(e.obj, Timer) for e in errors)
    assert str(errors[1]) == "Timer.preset: '40000' is outside 0 to 32767 (OBJ-005)"


def test_timer_accumulator_against_done() -> None:
    (error,) = _refusals(lambda: _timer(accumulator="TD2"))
    assert error.fields == ("Timer.accumulator", "Timer.done")
    assert error.reason == Reason.CONFLICT


def test_timer_checks_accumulator_alone_when_done_is_refused() -> None:
    errors = _refusals(lambda: _timer(done="T0", accumulator="DS1"))
    assert _shape(errors) == [
        ("Timer.done", "address", None),
        ("Timer.accumulator", "bank", None),
    ]


def test_timer_reasons() -> None:
    errors = _refusals(lambda: _timer(kind="bogus", unit="Tx", retained=2, preset="DS[DS1]"))
    assert _shape(errors) == [
        ("Timer.retained", "flag", None),
        ("Timer.kind", "choice", None),
        ("Timer.unit", "choice", None),
        ("Timer.preset", "pointer", None),
    ]
    # A refused flag keeps the value given.
    assert errors[0].obj.retained == 2


def test_timer_retained_off_delay_needs_both_fields_taken() -> None:
    (error,) = _refusals(lambda: _timer(kind="off_delay", retained=True))
    assert error.fields == ("Timer.retained", "Timer.kind")
    assert error.reason == Reason.CONFLICT
    # When the flag value itself is refused, the pair is not checked.
    (flag,) = _refusals(lambda: _timer(kind="off_delay", retained=2))
    assert flag.reason == Reason.FLAG


def test_timer_pin_rows() -> None:
    errors = _refusals(lambda: _timer(preset="40000", pin_rows=(0,)))
    assert _shape(errors) == [
        ("Timer.preset", "range", "OBJ-005"),
        ("Timer.pin_rows", "range", None),
    ]


# ---------------------------------------------------------------------------
# Collection: Coil
# ---------------------------------------------------------------------------


def test_coil_gives_every_refusal() -> None:
    errors = _refusals(lambda: Coil("X1", kind="latch", range_end="SC1", oneshot=True))
    assert _shape(errors) == [
        ("Coil.oneshot", "conflict", None),
        ("Coil.operand", "bank", "OBJ-004"),
        ("Coil.range_end", "not_writable", "OBJ-003"),
    ]
    assert errors[0].fields == ("Coil.oneshot", "Coil.kind")


@pytest.mark.parametrize("kind", ["out", "latch", "reset"])
@pytest.mark.parametrize(
    ("start", "end", "click_id"),
    [("C5", "Y5", "OBJ-008"), ("C9", "C1", "OBJ-009"), ("C5", "C5", "OBJ-012")],
)
def test_coil_range(kind: CoilKind, start: str, end: str, click_id: str) -> None:
    """Out, Set and Reset refuse a bad range end with the same CLICK ids.

    The ids are OBJ-008 for another bank, OBJ-009 for an end below the start, and OBJ-012
    for the same address."""
    (error,) = _refusals(lambda: Coil(start, kind=kind, range_end=end))
    assert error.fields == ("Coil.range_end", "Coil.operand")
    assert (error.reason, error.click_id) == (Reason.CONFLICT, click_id)
    assert str(error).endswith(f" ({click_id})")


@pytest.mark.parametrize("kind", ["out", "latch", "reset"])
@pytest.mark.parametrize(
    ("start", "end"),
    [("C1", "DS1"), ("C1", "TXT1"), ("Y001", "X001"), ("Y001", "ds1"), ("Y001", "DS[DS1]")],
)
def test_coil_range_into_a_refused_bank_is_obj_008(kind: CoilKind, start: str, end: str) -> None:
    """A range end in another bank is refused with OBJ-008 alone, before any refusal of the
    end itself. The same holds for a pointer that CLICK reads."""
    errors = _refusals(lambda: Coil(start, kind=kind, range_end=end))
    assert _shape(errors) == [("Coil.range_end", "conflict", "OBJ-008")]
    assert errors[0].fields == ("Coil.range_end", "Coil.operand")


@pytest.mark.parametrize("end", ["X[DS1]", "DS[DS0]", "DS[DS[DS1]]"])
def test_coil_range_end_click_does_not_read_as_a_pointer_has_no_id(end: str) -> None:
    """A pointer that CLICK does not read has no bank to compare, so its refusal has no id.

    CLICK refuses Y001..X[DS1] with OBJ-005."""
    assert _shape(_refusals(lambda: Coil("Y001", range_end=end))) == [
        ("Coil.range_end", "address", None)
    ]


@pytest.mark.parametrize(
    ("start", "end", "immediate"), [("C1", "SC1", False), ("Y001", "C2", True)]
)
def test_coil_range_across_banks_comes_before_the_end_s_own_checks(
    start: str, end: str, immediate: bool
) -> None:
    """A range end in another bank is OBJ-008, before the checks of the end itself.

    This order is laddercodec's choice. No CLICK answer covers an end that CLICK would also
    refuse as not writable (SC1) or as not immediate (C2). laddercodec checks the bank pair
    first, as for ``C1..DS1``."""
    assert _shape(_refusals(lambda: Coil(start, range_end=end, immediate=immediate))) == [
        ("Coil.range_end", "conflict", "OBJ-008")
    ]


def test_coil_skips_what_depends_on_a_refused_field() -> None:
    # When the kind is refused, the one-shot pairing is not checked.
    assert _shape(_refusals(lambda: Coil("C1", kind=99, oneshot=True))) == [  # type: ignore[arg-type]
        ("Coil.kind", "choice", None)
    ]
    # When the immediate flag is refused, C1 is not refused as an immediate target.
    assert _shape(_refusals(lambda: Coil("C1", immediate=2))) == [("Coil.immediate", "flag", None)]
    # When the range start is refused, the range pairing is not checked.
    assert _shape(_refusals(lambda: Coil("C0", range_end="Y5"))) == [
        ("Coil.operand", "address", None)
    ]


def test_coil_typed_text_is_named_in_each_refusal() -> None:
    errors = _refusals(lambda: Coil("x1", range_end="c0"))
    assert [str(e) for e in errors] == [
        "Coil.operand: 'x1' (X001) is not allowed; Coil.operand takes Y, C, SC (OBJ-004)",
        "Coil.range_end: 'c0' (C0) is outside C1-C2000",
    ]


def test_coil_immediate_target_is_a_conflict_with_immediate() -> None:
    (error,) = _refusals(lambda: Coil("C1", immediate=True))
    assert error.fields == ("Coil.operand", "Coil.immediate")
    assert error.reason == Reason.CONFLICT
    # A refusal of a pair blocks later refusals of its leading field only, so the range end
    # is still checked against immediate.
    errors = _refusals(lambda: Coil("C1", range_end="C5", immediate=True))
    assert [e.fields for e in errors] == [
        ("Coil.operand", "Coil.immediate"),
        ("Coil.range_end", "Coil.immediate"),
    ]


@pytest.mark.parametrize("kind", ["out", "latch", "reset"])
def test_coil_bank_id(kind: CoilKind) -> None:
    (error,) = _refusals(lambda: Coil("DS1", kind=kind))
    assert (error.reason, error.click_id) == (Reason.BANK, "OBJ-004")


@pytest.mark.parametrize("kind", ["out", "latch", "reset"])
def test_coil_sc_not_writable_is_obj_003(kind: CoilKind) -> None:
    (error,) = _refusals(lambda: Coil("SC163", kind=kind))
    assert (error.field, error.reason, error.click_id) == (
        "Coil.operand",
        Reason.NOT_WRITABLE,
        "OBJ-003",
    )
    assert str(error).endswith(" (OBJ-003)")
    assert Coil("SC50", kind=kind).operand == "SC50"
    assert Coil("SC162", kind=kind).operand == "SC162"


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
        Coil(5, immediate=2)  # type: ignore[arg-type]
    assert caught.value.field == "Coil.immediate"
    assert isinstance(caught.value.__cause__, TypeError)


def test_a_crash_with_no_refusal_is_raised_as_is() -> None:
    with pytest.raises(TypeError):
        _timer(preset=None)


# ---------------------------------------------------------------------------
# Refusals: items, nested constructions, errors raised out of the block
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _Inner(AfInstruction):
    a: str = "x"  # not blank, because a blank value is refused as missing
    b: str = "x"

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            check.refuse("a", "is refused", Reason.KIND, code=Code.CONSTANT_KIND_NOT_ALLOWED)
            check.refuse("b", "is refused", Reason.FORM, code=Code.INVALID_CONSTANT)


@dataclasses.dataclass
class _Outer(AfInstruction):
    items: tuple[str, ...] = ()
    other: str = "x"
    mode: str = ""

    def __post_init__(self) -> None:
        with Refusals(self) as check:
            if self.mode == "item":
                check.refuse("items[1]", "is refused", Reason.BANK, code=Code.BANK_NOT_ALLOWED)
                check.refuse(
                    "items", "is refused too", Reason.RANGE, code=Code.CONSTANT_OUT_OF_RANGE
                )  # dropped, because an item of the list was refused
                check.refuse(
                    "other", "is refused", Reason.KIND, code=Code.CONSTANT_KIND_NOT_ALLOWED
                )
            elif self.mode == "pair":
                check.refuse(
                    ("items", "other"), "is refused", Reason.CONFLICT, code=Code.OPTION_NOT_OFFERED
                )
                check.refuse(
                    ("other", "mode"),
                    "is refused too",
                    Reason.CONFLICT,
                    code=Code.OPTION_NOT_OFFERED,
                )
                check.refuse(
                    "items[0]", "is skipped", Reason.BANK, code=Code.BANK_NOT_ALLOWED
                )  # dropped, because items leads a refusal above
            elif self.mode == "list":
                check.refuse("items", "is refused", Reason.RANGE, code=Code.CONSTANT_OUT_OF_RANGE)
                assert check.refused("items[0]")
                check.refuse("items[2]", "is refused too", Reason.BANK, code=Code.BANK_NOT_ALLOWED)
            elif self.mode == "nested":
                check.refuse(
                    "other", "is refused", Reason.KIND, code=Code.CONSTANT_KIND_NOT_ALLOWED
                )
                check.run(_Inner)
            elif self.mode == "raised":
                check.refuse(
                    "other", "is refused", Reason.KIND, code=Code.CONSTANT_KIND_NOT_ALLOWED
                )
                raise FieldError(
                    "_Outer.other: again", field="_Outer.other", code=Code.INVALID_CHOICE
                )
            elif self.mode == "raised nested":
                _Inner()
            elif self.mode == "together":
                # Two refusals of one field from one check, as a Math formula check raises them.
                error = FieldError(
                    "_Outer.other: one", field="_Outer.other", code=Code.INVALID_CHOICE
                )
                error.errors = (
                    error,
                    FieldError("_Outer.other: two", field="_Outer.other", code=Code.INVALID_CHOICE),
                )
                check.add(error)
                check.refuse(
                    "other", "is skipped", Reason.KIND, code=Code.CONSTANT_KIND_NOT_ALLOWED
                )


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


def test_refusals_of_one_field_that_come_together_are_all_kept() -> None:
    errors = _refusals(lambda: _Outer(mode="together"))
    assert [str(e) for e in errors] == ["_Outer.other: one", "_Outer.other: two"]


def test_an_error_raised_out_of_the_block_is_checked_as_a_refusal() -> None:
    errors = _refusals(lambda: _Outer(mode="raised"))
    assert [str(e) for e in errors] == ["_Outer.other: is refused"]


# ---------------------------------------------------------------------------
# Not converted yet: one refusal, a uniform field
# ---------------------------------------------------------------------------


def test_unconverted_class_raises_one_refusal() -> None:
    (error,) = _refusals(lambda: Counter("count_up", "CT1", "CTD2", "1", reset_enabled=True))
    assert error.field == "Counter.accumulator"


def test_labels_are_not_fields() -> None:
    """Send and Receive messages start with their own label, such as ``Receive dest:``.

    The field is still ``Class.attr``."""
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
            "event_drum", outputs=["C1"], events=["DS1"], pattern=[[1]],
            current_step="DS1", completion_flag="C2",
        )  # fmt: skip

    (error,) = _refusals(build)
    assert (error.field, error.reason) == ("Drum.events[0]", Reason.BANK)
    assert str(error).startswith("Drum.events[0]: ")


def test_display_form_refusal_names_the_field() -> None:
    with display_form_only():
        errors = _refusals(lambda: _timer(done="T01", preset="ds1"))
    assert _shape(errors) == [("Timer.done", "form", None), ("Timer.preset", "form", None)]


def test_sweep_refuses_a_field_that_is_no_dataclass_field() -> None:
    """The conftest fixture fails a refusal that names a field its class does not have."""

    @dataclasses.dataclass
    class Box(AfInstruction):
        operand: str = "C1"

        def __post_init__(self) -> None:
            with Refusals(self) as check:
                check.refuse(
                    "nothing", "is refused", Reason.KIND, code=Code.CONSTANT_KIND_NOT_ALLOWED
                )

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
        (lambda: _timer(preset="DD1"), "Timer.preset", "OBJ-004"),
        (lambda: Shift("DS1", "C2"), "Shift.start_bit", "OBJ-004"),
        (lambda: Shift("C1", "C1"), "Shift.end_bit", "OBJ-012"),
        (lambda: Counter("count_up", "CT1", "CTD1", "DH1"), "Counter.preset", "OBJ-004"),
        (lambda: ForLoop("DH1"), "ForLoop.count", "OBJ-004"),
        (lambda: Math("1", "C1"), "Math.dest", "OBJ-004"),
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
    """Each member of Reason has a docstring after it, which the API reference shows."""
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
