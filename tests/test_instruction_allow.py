"""``allow=`` on the constructor of each instruction class, Modbus target and Modbus address.

The cases of ``tests/test_refused_fields.py`` cover every family: a golden edited to hold a
value that CLICK's dialog refuses. Each test builds the edited instruction with its
constructor, from the values that ``read_csv`` read. The tests show that:

- the constructor with ``allow=`` builds the instruction that ``read_csv(..., allow=...)``
  reads, and ``encode()`` writes the same bytes for it;
- a refusal with a code that ``allow`` leaves out raises as it does without ``allow``;
- an instruction that holds no refusal is built as it is without ``allow``;
- ``allow`` takes no part in equality, hashing or ``repr``;
- a bad ``allow`` raises ``LaddercodecError``;
- a Send or Receive builds its Modbus target again with its own ``allow``;
- ``replace`` checks a changed copy again, unless you pass ``allow`` to it;
- ``lay_out`` and ``check()`` take a rung that holds such an instruction.
"""

from __future__ import annotations

import dataclasses
import warnings
from pathlib import Path
from typing import Any

import pytest

import laddercodec
from laddercodec import (
    Box,
    Branch,
    Circuit,
    Code,
    CsvReadError,
    FieldError,
    LaddercodecError,
    RefusedFieldWarning,
    Rung,
    check,
    decode,
    encode,
    lay_out,
    read_csv,
)
from laddercodec.instructions import (
    Coil,
    Contact,
    Counter,
    End,
    ForLoop,
    Math,
    ModbusAddress,
    ModbusRtuTarget,
    ModbusTcpTarget,
    Receive,
    Send,
    Timer,
)
from laddercodec.operands.address import NotDisplayForm, display_form_only
from laddercodec.operands.unchecked import (
    allowed,
    rebuilt,
    refusals,
    stored_blob,
    unchecked,
)
from tests.test_refused_fields import _IDS, CASES, GOLDEN, _edited, _held

BANK = Code.BANK_NOT_ALLOWED
TARGET = Code.INVALID_MODBUS_TARGET


def _read(path: Path, **kwargs: Any) -> list[Rung]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RefusedFieldWarning)
        return read_csv(path, **kwargs)


def _codes(held: object) -> set[Code]:
    return {error.code for error in refusals(held) if error.code is not None}


def _built(inst: Any, allow: Any) -> Any:
    """Return a new instance of *inst*'s class, built from its field values with
    ``allow=allow``. Build each Modbus target or Modbus address in a field in the same way.
    """
    values = {}
    for f in dataclasses.fields(inst):
        value = getattr(inst, f.name)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            value = _built(value, allow)
        values[f.name] = value
    return type(inst)(**values, allow=allow)


def _swapped(rungs: list[Rung], old: object, new: object) -> list[Rung]:
    """Return *rungs* with *new* in place of the token *old*."""

    def swap(token: object) -> object:
        return new if token is old else token

    return [
        dataclasses.replace(
            rung,
            conditions=tuple(tuple(swap(t) for t in row) for row in rung.conditions),
            instructions=tuple(swap(t) for t in rung.instructions),
        )
        for rung in rungs
    ]


def _place(rungs: list[Rung], token: object) -> tuple[int, int, int | None]:
    """Return the rung, row and condition column of *token*. The column is None for the AF
    column."""
    for index, rung in enumerate(rungs):
        for row, cells in enumerate(rung.conditions):
            for column, cell in enumerate(cells):
                if cell is token:
                    return index, row, column
        for row, cell in enumerate(rung.instructions):
            if cell is token:
                return index, row, None
    raise AssertionError(token)


def _at(rungs: list[Rung], place: tuple[int, int, int | None]) -> Any:
    index, row, column = place
    rung = rungs[index]
    return rung.instructions[row] if column is None else rung.conditions[row][column]


def _without_target_name(back: Any, held: Any) -> Any:
    """Return *back* with the name of *held*'s target, if both are a Send or Receive.

    The blob does not store the name of a target."""
    if isinstance(held, (Send, Receive)) and back.target.name != held.target.name:
        return rebuilt(back, target=rebuilt(back.target, name=held.target.name))
    return back


# ---------------------------------------------------------------------------
# Every family
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_a_listed_refusal_is_kept_as_read_csv_keeps_it(
    tmp_path, golden, old, new, cls, fields
) -> None:
    path = _edited(tmp_path, golden, old, new)
    codes = _codes(_held(_read(path, unchecked=True))[1])
    read = _read(path, allow=codes)
    _, held = _held(read)
    built = _built(held, codes)
    assert isinstance(built, cls)
    assert built == held
    assert allowed(built)
    assert stored_blob(built) is None

    def shape(errors: tuple[FieldError, ...]) -> list[tuple[object, ...]]:
        return [(e.fields, e.reason, e.code, e.click_id, str(e)) for e in errors]

    assert [e.field for e in refusals(built)] == fields
    assert shape(refusals(built)) == shape(refusals(held))

    rungs = _swapped(read, held, built)
    data = encode(rungs)
    assert data == encode(read)
    with pytest.warns(RefusedFieldWarning):
        decoded = decode(data)
    back = _at(decoded, _place(rungs, built))
    assert _without_target_name(back, built) == built
    assert [e.field for e in refusals(back)] == fields


@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_a_code_left_out_raises_as_without_allow(tmp_path, golden, old, new, cls, fields) -> None:
    path = _edited(tmp_path, golden, old, new)
    _, held = _held(_read(path, unchecked=True))
    codes = _codes(held)
    with pytest.raises(FieldError) as default:
        _built(held, None)
    for left_out in codes:
        # blank-field is never in these refusals, so the list is never empty.
        with pytest.raises(FieldError) as raised:
            _built(held, [*(codes - {left_out}), Code.BLANK_FIELD])
        assert type(raised.value) is type(default.value)
        assert str(raised.value) == str(default.value)


@pytest.mark.parametrize(("golden", "old", "new", "cls", "fields"), CASES, ids=_IDS)
def test_an_instruction_with_no_refusal_is_built_as_without_allow(
    tmp_path, golden, old, new, cls, fields
) -> None:
    path = _edited(tmp_path, golden, old, new)
    edited = _read(path, unchecked=True)
    _, held = _held(edited)
    codes = _codes(held)
    plain = _at(read_csv(GOLDEN / f"{golden}.csv"), _place(edited, held))
    assert isinstance(plain, cls)
    built = _built(plain, codes)
    assert built == plain
    assert repr(built) == repr(plain)
    assert refusals(built) == ()
    assert not allowed(built)
    assert built.build_blob() == plain.build_blob()


# ---------------------------------------------------------------------------
# Equality, repr and replace()
# ---------------------------------------------------------------------------


def test_allow_takes_no_part_in_equality_hash_or_repr() -> None:
    plain = Coil("Y001")
    built = Coil("Y001", allow=[BANK])
    assert built == plain
    assert hash(built) == hash(plain)
    assert (
        repr(built)
        == repr(plain)
        == ("Coil(operand='Y001', kind='out', range_end=None, immediate=False, oneshot=False)")
    )
    held = Coil("X001", allow=[BANK])
    assert repr(held) == (
        "Coil(operand='X001', kind='out', range_end=None, immediate=False, oneshot=False)"
    )
    with unchecked():
        kept = Coil("X001")
    assert held == kept
    assert hash(held) == hash(kept)
    assert "allow" not in {f.name for f in dataclasses.fields(held)}


def test_replace_checks_a_changed_copy_again() -> None:
    held = Coil("X001", allow=[BANK])
    with pytest.raises(FieldError, match="^Coil.operand"):
        laddercodec.replace(held, operand="X002")
    with pytest.raises(FieldError, match="^Coil.operand"):
        laddercodec.replace(held, operand="X002", allow=())
    same = laddercodec.replace(held, operand="X001")
    assert allowed(same)
    assert same.build_blob() == held.build_blob()


def test_replace_with_allow_builds_the_copy_as_the_constructor() -> None:
    held = Coil("X001", allow=[BANK])
    moved = laddercodec.replace(held, operand="X002", allow=[BANK])
    assert moved == Coil("X002", allow=[BANK])
    assert allowed(moved)
    with pytest.raises(FieldError, match="^Coil.operand"):
        laddercodec.replace(held, operand="X002", allow=[Code.BLANK_FIELD])
    with pytest.raises(LaddercodecError, match="^Coil: allow='bank-not-allowed' is one code"):
        laddercodec.replace(held, allow="bank-not-allowed")


def test_replace_with_allow_marks_a_decoded_instruction_allowed() -> None:
    with unchecked():
        kept = Coil("X001")
    assert not allowed(kept)
    copy = laddercodec.replace(kept, allow=[BANK])
    assert copy == kept
    assert allowed(copy)
    assert stored_blob(copy) is None
    assert copy.build_blob() == Coil("X001", allow=[BANK]).build_blob()


# ---------------------------------------------------------------------------
# Refusals that raise whatever allow lists
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "code"),
    [
        pytest.param(lambda allow: Coil("Y001", kind="bogus", allow=allow), Code.INVALID_CHOICE),
        pytest.param(lambda allow: Coil("Y001", oneshot=2, allow=allow), Code.NOT_A_FLAG),  # type: ignore[arg-type]
        pytest.param(
            lambda allow: Timer("on_delay", "T1", "TD1", "100", "Txx", allow=allow),  # type: ignore[arg-type]
            Code.INVALID_CHOICE,
        ),
    ],
    ids=["coil-kind", "coil-oneshot", "timer-unit"],
)
def test_a_value_no_instruction_holds_raises_whatever_is_allowed(build, code) -> None:
    with pytest.raises(FieldError) as default:
        build(None)
    assert code in {e.code for e in default.value.errors}
    with pytest.raises(FieldError) as raised:
        build(list(Code))
    assert str(raised.value) == str(default.value)


def test_a_not_display_form_refusal_raises_whatever_is_allowed() -> None:
    with display_form_only(), pytest.raises(NotDisplayForm):
        Coil("y1", allow=list(Code))


def test_a_pin_rows_refusal_raises_whatever_is_allowed() -> None:
    with pytest.raises(FieldError) as raised:
        Timer("on_delay", "T1", "TD1", "100", "Tms", retained=True, pin_rows=(0,), allow=list(Code))
    assert raised.value.field == "Timer.pin_rows"


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda allow: Math("TD501 + 1", "DS1", allow=allow), id="math-formula"),
        pytest.param(lambda allow: Coil("", allow=allow), id="coil-blank"),
        pytest.param(lambda allow: ForLoop("", allow=allow), id="for-blank"),
    ],
)
def test_an_instruction_laddercodec_cant_write_raises_as_without_allow(build) -> None:
    """The instruction keeps its refusal with every code allowed. Its blob does not read back
    to it, so the constructor raises its first refusal."""
    with pytest.raises(FieldError) as default:
        build(None)
    with pytest.raises(FieldError) as raised:
        build(list(Code))
    assert str(raised.value) == str(default.value)
    assert [e.field for e in raised.value.errors] == [e.field for e in default.value.errors]
    with unchecked(allow=list(Code)):
        kept = build(None)
    assert allowed(kept)


# ---------------------------------------------------------------------------
# A bad allow=
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "name"),
    [
        pytest.param(lambda allow: Coil("X001", allow=allow), "Coil", id="refused"),
        pytest.param(lambda allow: Coil("Y001", allow=allow), "Coil", id="accepted"),
        pytest.param(lambda allow: End(allow=allow), "End", id="no-checks"),
        pytest.param(
            lambda allow: ModbusRtuTarget("rtu", "cpu2", 5, allow=allow),
            "ModbusRtuTarget",
            id="modbus-target",
        ),
    ],
)
@pytest.mark.parametrize(
    ("allow", "message"),
    [
        (["bank-not-alowed"], "allow= holds 'bank-not-alowed', which is not a code"),
        (["BANK_NOT_ALLOWED"], "allow= holds 'BANK_NOT_ALLOWED', which is not a code"),
        ([4], "allow= holds 4, which is not a code"),
        (
            "bank-not-allowed",
            r"allow='bank-not-allowed' is one code name\. Pass a list of code names, such as "
            r"allow=\['bank-not-allowed'\]\.$",
        ),
        (
            BANK,
            r"allow='bank-not-allowed' is one code name\. Pass a list of code names, such as "
            r"allow=\['bank-not-allowed'\]\.$",
        ),
        (b"bank", r"allow=b'bank' is not a list of code names"),
        (5, r"allow=5 is not a list of code names"),
    ],
)
def test_a_bad_allow_raises_laddercodec_error(build, name, allow, message) -> None:
    with pytest.raises(LaddercodecError, match=message) as raised:
        build(allow)
    assert type(raised.value) is LaddercodecError
    assert not isinstance(raised.value, CsvReadError)
    assert str(raised.value).startswith(f"{name}: ")


@pytest.mark.parametrize("empty", [None, (), []])
def test_an_empty_allow_builds_as_without_allow(empty) -> None:
    with pytest.raises(FieldError, match="^Coil.operand"):
        Coil("X001", allow=empty)
    with unchecked():
        kept = Coil("X001", allow=empty)
    assert refusals(kept)
    assert not allowed(kept)


def test_a_class_that_holds_no_refusal_ignores_allow() -> None:
    assert End(allow=[BANK]) == End()


# ---------------------------------------------------------------------------
# Modbus targets and addresses
# ---------------------------------------------------------------------------


def _send(target: Any, **kwargs: Any) -> Send:
    return Send(target, "DS1", "DS1", 1, "C1", "C2", "C3", "", **kwargs)


def test_a_send_keeps_the_refusal_of_its_target() -> None:
    target = ModbusTcpTarget("plc", "192.168.1.10", 502, 256, allow=[TARGET])
    assert allowed(target)
    send = _send(target, allow=[TARGET])
    assert allowed(send)
    assert [e.field for e in refusals(send)] == ["ModbusTcpTarget.device_id"]
    with pytest.warns(RefusedFieldWarning):
        [back] = decode(encode(Rung([[Contact("X001"), *["-"] * 30]], [send], None)))
    assert _without_target_name(back.instructions[0], send) == send


def test_a_send_builds_its_target_again_with_its_own_allow() -> None:
    with unchecked():
        decoded = ModbusTcpTarget("plc", "192.168.1.10", 502, 256)
    assert not allowed(decoded)
    send = _send(decoded, allow=[TARGET])
    assert send.target == decoded
    assert send.target is not decoded
    assert allowed(send.target)
    assert not allowed(decoded)
    assert allowed(send)


def test_a_send_raises_the_refusal_of_a_target_that_its_allow_leaves_out() -> None:
    target = ModbusTcpTarget("plc", "192.168.1.10", 502, 256, allow=[TARGET])
    with pytest.raises(FieldError, match="^ModbusTcpTarget.device_id"):
        _send(target, allow=[BANK])


def test_a_send_without_allow_keeps_an_allowed_target() -> None:
    target = ModbusTcpTarget("plc", "192.168.1.10", 502, 256, allow=[TARGET])
    send = _send(target)
    assert send.target is target
    assert allowed(send)
    assert send.build_blob() == _send(target, allow=[TARGET]).build_blob()


def test_a_send_raises_for_a_target_laddercodec_cant_write() -> None:
    """An IP that is not text is kept with its code allowed, but the blob can't hold it."""
    with pytest.raises(FieldError) as default:
        ModbusTcpTarget("plc", 5, 502, 1)  # type: ignore[arg-type]
    target = ModbusTcpTarget("plc", 5, 502, 1, allow=[TARGET])  # type: ignore[arg-type]
    assert allowed(target)
    for allow in (None, [TARGET]):
        with pytest.raises(FieldError) as raised:
            _send(target, allow=allow)
        assert str(raised.value) == str(default.value)


def test_a_receive_keeps_the_refusal_of_its_rtu_target() -> None:
    target = ModbusRtuTarget("rtu", "cpu2", 248, allow=[TARGET])
    receive = Receive(target, "DS1", "DS1", 5, "C1", "C2", "C3", "", allow=[TARGET])
    assert allowed(receive)
    assert [e.field for e in refusals(receive)] == ["ModbusRtuTarget.device_id"]


def test_a_modbus_address_takes_allow() -> None:
    with pytest.raises(FieldError) as default:
        ModbusAddress("10000h", register_type="coil")
    codes = {e.code for e in default.value.errors}
    address = ModbusAddress("10000h", register_type="coil", allow=codes)
    assert allowed(address)
    with pytest.raises(FieldError):
        ModbusAddress("10000h", register_type="coil", allow=[BANK])


# ---------------------------------------------------------------------------
# lay_out() and check()
# ---------------------------------------------------------------------------


def test_lay_out_and_check_take_an_allowed_instruction() -> None:
    contact = Contact("DS2", allow=[BANK])
    counter = Counter(
        "count_down", "Y001", "CTD3", "50", reset_enabled=True, pin_rows=(1, 2), allow=[BANK]
    )
    coil = Coil("X001", allow=[BANK])
    rungs = [
        *lay_out(Circuit(Branch((contact,), (Box(counter, {".reset": Contact("X002")}),)))),
        *lay_out(Circuit(Branch((Contact("X003"),), (Box(coil),)))),
    ]
    assert check(rungs) == []
    tokens = [t for rung in rungs for row in rung.conditions for t in row]
    tokens += [t for rung in rungs for t in rung.instructions]
    held = [t for t in tokens if refusals(t)]
    assert len(held) == 3
    assert all(allowed(t) for t in held)
    with pytest.warns(RefusedFieldWarning):
        assert decode(encode(rungs)) == rungs
