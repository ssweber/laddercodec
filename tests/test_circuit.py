"""The public circuit types refuse bad parts, and ``lay_out`` draws what CLICK holds."""

from __future__ import annotations

import pytest

from laddercodec import (
    Box,
    Branch,
    Circuit,
    Code,
    Coil,
    Contact,
    Copy,
    Counter,
    FieldError,
    LayoutError,
    Parallel,
    Reason,
    Rung,
    Series,
    Tee,
    Timer,
    check,
    csv_rows,
    decode,
    encode,
    lay_out,
)

C = Contact
X1, X2, X3 = C("X001"), C("X002"), C("X003")
Y1, Y2 = Coil("Y001"), Coil("Y002")
RETAINED = Timer("on_delay", "T1", "TD1", "100", "Tms", retained=True)
PLAIN_TIMER = Timer("on_delay", "T1", "TD1", "100", "Tms")


def _refusal(build: object, field: str, words: str) -> FieldError:
    """Return the refusal that calling *build* raises, after checking its field and code."""
    assert callable(build)
    with pytest.raises(FieldError) as caught:
        build()
    error = caught.value
    assert error.code is Code.INVALID_CIRCUIT
    assert error.field == field
    assert words in str(error)
    return error


def _rows(rungs: list[Rung]) -> list[list[str]]:
    """Return each CSV row as its marker, the cells up to the last that holds something, and AF.

    A comment row is returned as it is.
    """
    out = []
    for row in csv_rows(rungs):
        if row[0] == "#":
            out.append(row)
            continue
        cells = row[1:-1]
        while cells and not cells[-1]:
            cells.pop()
        out.append([row[0], *cells, "|", row[-1]])
    return out


def _wire(start: int) -> list[str]:
    """Return the cells from column *start* to AE, all wire."""
    return ["-"] * (31 - start)


# ---------------------------------------------------------------------------
# Refusals at construction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("legs", [(), (X1,)])
def test_parallel_needs_two_legs(legs: tuple[object, ...]) -> None:
    error = _refusal(lambda: Parallel(legs), "Parallel.legs", "A Parallel needs two or more legs")
    assert error.reason is Reason.FORM


@pytest.mark.parametrize(
    ("build", "field"),
    [
        (lambda: Series((X1, Series(()))), "Series.terms[1]"),
        (lambda: Branch((Series(()),), (Box(Y1),)), "Branch.conditions[0]"),
        (lambda: Box(RETAINED, {".reset": Series(())}), "Box.pins[0]"),
    ],
)
def test_empty_series_is_only_an_or_leg(build: object, field: str) -> None:
    _refusal(build, field, "Use one only as a leg of a Parallel")


def test_empty_series_is_an_or_leg() -> None:
    assert Parallel((X1, Series(()))).legs == (X1, Series(()))


@pytest.mark.parametrize("wires", [2, 3])
def test_parallel_needs_a_leg_that_is_not_a_wire(wires: int) -> None:
    error = _refusal(
        lambda: Parallel((Series(()),) * wires),
        "Parallel.legs",
        "A Parallel needs at least one leg that is not a wire",
    )
    assert error.reason is Reason.FORM


@pytest.mark.parametrize(
    ("build", "field"),
    [
        (lambda: Series((X1, Y1)), "Series.terms[1]"),
        (lambda: Parallel((Tee(X1), X2)), "Parallel.legs[0]"),
        (lambda: Branch(("X001",), (Box(Y1),)), "Branch.conditions[0]"),
        (lambda: Box(RETAINED, {".reset": "X002"}), "Box.pins[0]"),
    ],
)
def test_a_leaf_is_a_contact(build: object, field: str) -> None:
    _refusal(build, field, "is not a contact or a circuit")


@pytest.mark.parametrize("instruction", [X1, "nop", None])
def test_box_holds_an_af_instruction_or_nop(instruction: object) -> None:
    _refusal(lambda: Box(instruction), "Box.instruction", "is not an output instruction")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("instruction", "pins", "words"),
    [
        (RETAINED, {".jog": X2}, "'.jog' is not a pin of Timer. Write one of '.reset'"),
        (
            PLAIN_TIMER,
            {".reset": X2},
            "'.reset' is turned off in this Timer. Turn it on with retained=True",
        ),
        (
            Counter("count_up", "CT1", "CTD1", "10"),
            {".down": X2},
            "'.down' is turned off in this Counter. Turn it on with down_enabled=True",
        ),
        (Y1, {".reset": X2}, "A Coil has no pins"),
        ("NOP", {".reset": X2}, "'.reset' is not a pin of NOP. A NOP has no pins"),
    ],
)
def test_a_pin_is_one_the_box_uses(
    instruction: object, pins: dict[str, object], words: str
) -> None:
    _refusal(lambda: Box(instruction, pins), "Box.pins[0]", words)  # type: ignore[arg-type]


def test_a_pin_is_named_once() -> None:
    _refusal(
        lambda: Box(RETAINED, ((".reset", X2), (".reset", X3))), "Box.pins[1]", "names the pin"
    )


@pytest.mark.parametrize("pins", [X2, [X2]])
def test_pins_are_a_mapping(pins: object) -> None:
    _refusal(lambda: Box(RETAINED, pins), "Box.pins", "is not a mapping of pin names")  # type: ignore[arg-type]


def test_branch_needs_an_output() -> None:
    error = _refusal(lambda: Branch((X1,)), "Branch.outputs", "A Branch needs at least one output")
    assert error.reason is Reason.MISSING


def test_branch_output_is_a_box_or_branch() -> None:
    _refusal(lambda: Branch((X1,), (Y1,)), "Branch.outputs[0]", "is not a Box or a Branch")


@pytest.mark.parametrize(
    ("build", "field"),
    [
        (lambda: Series(X1), "Series.terms"),
        (lambda: Parallel("X001"), "Parallel.legs"),
        (lambda: Branch(X1, (Box(Y1),)), "Branch.conditions"),
        (lambda: Branch((X1,), Box(Y1)), "Branch.outputs"),
    ],
)
def test_parts_are_a_tuple(build: object, field: str) -> None:
    _refusal(build, field, "is not a tuple of parts")


def test_circuit_holds_a_branch_and_a_text_comment() -> None:
    _refusal(lambda: Circuit(Box(Y1)), "Circuit.branch", "is not a Branch")  # type: ignore[arg-type]
    _refusal(lambda: Circuit(Branch((), (Box(Y1),)), 5), "Circuit.comment", "is not text")  # type: ignore[arg-type]


def test_every_refusal_of_one_part_is_kept() -> None:
    with pytest.raises(FieldError) as caught:
        Branch((Y1,), ())
    assert [e.field for e in caught.value.errors] == ["Branch.conditions[0]", "Branch.outputs"]


# ---------------------------------------------------------------------------
# The types are frozen, hashable and stored as tuples
# ---------------------------------------------------------------------------


def test_parts_are_tuples_and_hash() -> None:
    drum_free = Counter("count_up", "CT1", "CTD1", "10", down_enabled=True)
    a = Box(drum_free, {".reset": X1, ".down": X2})
    b = Box(drum_free, [(".down", X2), (".reset", X1)])
    assert a == b
    assert hash(a) == hash(b)
    assert a.pins == ((".down", X2), (".reset", X1))
    circuit = Circuit(Branch([X1, Parallel([X2, X3])], [a]), "note")
    assert circuit.branch.conditions == (X1, Parallel((X2, X3)))
    assert hash(circuit) == hash(Circuit(Branch((X1, Parallel((X2, X3))), (b,)), "note"))
    with pytest.raises(AttributeError):
        circuit.comment = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# lay_out
# ---------------------------------------------------------------------------


def test_lay_out_series_and_or() -> None:
    circuit = Circuit(Branch((X1, Parallel((X2, C("C1")))), (Box(Y1),)), "Start")
    assert _rows(lay_out(circuit)) == [
        ["#", "Start"],
        ["R", "X001", "T:X002", "T", *_wire(3), "|", "out(Y001)"],
        ["", "", "C1", "|", ""],
    ]


def test_comment_goes_on_the_first_rung_of_a_split() -> None:
    """Outputs that meet only at the rail become one CLICK rung each."""
    rungs = lay_out(Circuit(Branch((), (Box(Y1), Branch((X1,), (Box(Y2),)))), "Two"))
    assert [r.comment for r in rungs] == ["Two", None]
    assert [r.instructions for r in rungs] == [(Y1,), (Y2,)]


def test_or_legs_and_outputs_keep_source_order() -> None:
    """Parallel legs and Branch outputs are drawn from the top down in the order given."""
    for legs, outputs in [((X1, X2, X3), (Y1, Y2)), ((X3, X1, X2), (Y2, Y1))]:
        (rung,) = lay_out(Circuit(Branch((Parallel(legs),), tuple(Box(y) for y in outputs))))
        contacts = [
            row[0].contact if isinstance(row[0], Tee) else row[0] for row in rung.conditions
        ]
        assert contacts == list(legs)
        assert [i for i in rung.instructions if i] == list(outputs)


def test_wire_only_or_leg_is_drawn_and_check_reports_it() -> None:
    circuit = Circuit(Branch((Parallel((X1, Series(()))),), (Box(Y1),)))
    rungs = lay_out(circuit)
    assert _rows(rungs) == [
        ["R", "X001", "T", *_wire(2), "|", "out(Y001)"],
        ["", "-", "|", ""],
    ]
    assert decode(encode(rungs)) == rungs
    assert [(f.code, f.click_id) for f in check(rungs)] == [(Code.SHORTED_CONTACT, "C0002")]


def test_wire_leg_first_is_drawn_first() -> None:
    (rung,) = lay_out(Circuit(Branch((Parallel((Series(()), X1)),), (Box(Y1),))))
    assert _rows([rung]) == [
        ["R", "-", "T", *_wire(2), "|", "out(Y001)"],
        ["", "X001", "|", ""],
    ]


def test_contact_into_nop_is_drawn_and_check_reports_it() -> None:
    rungs = lay_out(Circuit(Branch((X1,), (Box("NOP"),))))
    assert _rows(rungs) == [["R", "X001", *_wire(1), "|", "NOP"]]
    assert [(f.code, f.click_id) for f in check(rungs)] == [(Code.CONTACT_FEEDS_ONLY_NOP, "C0003")]


def test_nop_on_the_rail() -> None:
    rungs = lay_out(Circuit(Branch((), (Box("NOP"),))))
    assert _rows(rungs) == [["R", *_wire(0), "|", "NOP"]]
    assert check(rungs) == []


def test_pins_go_on_their_rows() -> None:
    rungs = lay_out(Circuit(Branch((X1,), (Box(RETAINED, {".reset": X2}),))))
    assert _rows(rungs) == [
        ["R", "X001", *_wire(1), "|", "on_delay(T1,TD1,preset=100,unit=Tms)"],
        ["", "X002", *_wire(1), "|", ".reset()"],
    ]
    assert check(rungs) == []


def test_a_used_pin_left_out_is_drawn_unwired() -> None:
    rungs = lay_out(Circuit(Branch((X1,), (Box(RETAINED),))))
    assert _rows(rungs) == [
        ["R", "X001", *_wire(1), "|", "on_delay(T1,TD1,preset=100,unit=Tms)"],
        ["", "|", ".reset()"],
    ]
    assert [f.code for f in check(rungs)] == [Code.UNWIRED_INPUT]


# ---------------------------------------------------------------------------
# LayoutError: what CLICK can't hold
# ---------------------------------------------------------------------------


def _layout_error(circuit: Circuit, code: Code, click_id: str | None = None) -> LayoutError:
    """Return the error that ``lay_out`` raises, after checking its code and message."""
    with pytest.raises(LayoutError) as caught:
        lay_out(circuit)
    error = caught.value
    assert error.code is code
    assert error.click_id == click_id
    # The message names no row or column of the drawing, and it gives an example.
    assert "row " not in str(error)
    assert "column " not in str(error)
    assert "such as" in str(error) or "For example" in str(error)
    if code not in (Code.LAYOUT_TOO_TALL, Code.SHARED_INPUT_NET, Code.OUTPUT_ABOVE_BOX_INPUTS):
        assert isinstance(error.__cause__, LayoutError)
        assert error.__cause__.code is code
    return error


def test_32_rows_fit_and_33_raise() -> None:
    coils = [Box(Coil(f"C{n}")) for n in range(1, 34)]
    (rung,) = lay_out(Circuit(Branch((X1,), tuple(coils[:32]))))
    assert rung.logical_rows == 32
    error = _layout_error(Circuit(Branch((X1,), tuple(coils))), Code.LAYOUT_TOO_TALL)
    assert "needs 33 rows" in str(error)


def test_tall_boxes_count_every_row() -> None:
    """A Copy spans two rows, so 17 of them need 34."""
    copies = tuple(Box(Copy(str(n), f"DS{n}")) for n in range(1, 18))
    _layout_error(Circuit(Branch((X1,), copies)), Code.LAYOUT_TOO_TALL)


def test_31_contacts_fit_and_32_raise() -> None:
    contacts = [C(f"C{n}") for n in range(1, 33)]
    (rung,) = lay_out(Circuit(Branch(tuple(contacts[:31]), (Box(Y1),))))
    assert list(rung.conditions[0]) == contacts[:31]
    _layout_error(Circuit(Branch(tuple(contacts), (Box(Y1),))), Code.LAYOUT_TOO_WIDE)


_C000A = Code.SHARED_INPUT_NET
_C000A_ABOVE = Code.OUTPUT_ABOVE_BOX_INPUTS
_C000A_MESSAGE = (
    "An output hangs off the input circuit of a box whose pin is used (C000A). Put the output "
    "in a rung of its own, such as Circuit(Branch((Contact('X001'),), (Box(Coil('Y001')),)))."
)


@pytest.mark.parametrize(
    ("outputs", "code"),
    [
        ((Box(RETAINED, {".reset": X2}), Box(Y1)), _C000A),
        ((Box(Y1), Box(RETAINED, {".reset": X2})), _C000A_ABOVE),
    ],
    ids=["after", "above"],
)
def test_box_beside_a_pinned_box_on_its_net_is_c000a(outputs: tuple[Box, Box], code: Code) -> None:
    """A coil after or above a retentive timer on the timer's main input net is refused
    with C000A.  One message fits both sides.  It says to put the coil in a rung of its own.
    """
    error = _layout_error(Circuit(Branch((X1,), outputs)), code, "C000A")
    assert str(error) == _C000A_MESSAGE
    assert "above" not in str(error)
    assert "after" not in str(error)


def test_coil_above_a_pinned_box_is_what_check_reports() -> None:
    """lay_out refuses the coil above the timer with the code that check() gives the same
    rung drawn as a grid."""
    timer = RETAINED
    grid = Rung(
        [[X1, "T", *["-"] * 29], ["", "-", *["-"] * 29], [X2, *["-"] * 30]],
        [Coil("Y001"), timer, ""],
        None,
    )
    [finding] = check(grid)
    error = _layout_error(
        Circuit(Branch((X1,), (Box(Y1), Box(timer, {".reset": X2})))), _C000A_ABOVE, "C000A"
    )
    assert (finding.code, finding.click_id) == (error.code, error.click_id)


@pytest.mark.parametrize("side", ["after", "above"])
def test_box_beside_a_branch_to_a_pinned_box_is_c000a(side: str) -> None:
    """The coil hangs off X001's net, and the timer's main input circuit runs through it.

    CLICK refuses that circuit with the coil above the timer with C000A.
    """
    timer_branch = Branch((X3,), (Box(RETAINED, {".reset": X2}),))
    nested = Branch((C("C1"),), (timer_branch,))
    code = _C000A if side == "after" else _C000A_ABOVE
    for branch in (timer_branch, nested):
        outputs = (branch, Box(Y1)) if side == "after" else (Box(Y1), branch)
        _layout_error(Circuit(Branch((X1,), outputs)), code, "C000A")


def test_box_above_a_branch_beside_a_pinned_box_lays_out() -> None:
    """The coil hangs off X004's net, which is not on the timer's main input circuit, so
    lay_out draws it above the timer."""
    timer_branch = Branch((X3,), (Box(RETAINED, {".reset": X2}),))
    coil_branch = Branch((C("X004"),), (Box(Y1),))
    (rung,) = lay_out(Circuit(Branch((X1,), (coil_branch, timer_branch))))
    assert check(rung) == []


def test_box_after_a_branch_beside_a_pinned_box_cannot_be_drawn() -> None:
    """The coil hangs off X004's net, which is not on the timer's main input circuit."""
    timer_branch = Branch((X3,), (Box(RETAINED, {".reset": X2}),))
    coil_branch = Branch((C("X004"),), (Box(Y1),))
    circuit = Circuit(Branch((X1,), (timer_branch, coil_branch)))
    error = _layout_error(circuit, Code.LAYOUT_CANNOT_DRAW)
    assert "two of its wires would cross" in str(error)
    assert "move each of those boxes into a Circuit of its own" in str(error)


def test_c000a_lays_out_with_each_later_box_in_its_own_circuit() -> None:
    """The message for C000A says to put each output in a rung of its own.  If one of two
    later boxes stays, the circuit is still refused."""
    timer = Box(RETAINED, {".reset": X2})
    later = (Box(Y1), Box(Y2))
    _layout_error(Circuit(Branch((X1,), (timer, *later))), _C000A, "C000A")
    _layout_error(Circuit(Branch((X1,), (timer, later[0]))), _C000A, "C000A")
    rungs = [r for box in (timer, *later) for r in lay_out(Circuit(Branch((X1,), (box,))))]
    assert check(rungs) == []


def test_nop_beside_another_output_on_the_rail() -> None:
    _layout_error(Circuit(Branch((), (Box("NOP"), Box(Y1)))), Code.LAYOUT_NOP_SPLIT)
