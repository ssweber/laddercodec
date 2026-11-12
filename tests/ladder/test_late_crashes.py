"""Inputs a constructor used to accept that crashed later raise FieldError up front.

Each case names its field.  The first group are combinations CLICK has no dialog for
(Set/Reset one-shot, count_down's Down input, off_delay retention); the rest are
malformed values (a type, an edge kind, pin rows, a raw part count).  Native blobs still
decode: a blob whose pin rows the checks refuse stays raw.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from laddercodec.csv import read_csv
from laddercodec.csv.converter import ConvertError
from laddercodec.instructions import (
    Coil,
    Contact,
    Counter,
    Drum,
    RawInstruction,
    Shift,
    Timer,
    parse_af_blob,
)
from laddercodec.model import FieldError, InstructionType


def _counter(**kw) -> Counter:
    return Counter("count_up", "CT1", "CTD1", "5", reset_enabled=True, **kw)


def _timer(**kw) -> Timer:
    return Timer("on_delay", "T1", "TD1", "5", "Ts", **kw)


def _shift(**kw) -> Shift:
    return Shift("C1", "C8", **kw)


def _drum(**kw) -> Drum:
    return Drum(
        drum_kind="event",
        outputs=["C1", "C2"],
        events_or_presets=["C3", "C4"],
        pattern=[[1, 0], [0, 1]],
        current_step="DS1",
        completion_flag="C5",
        **kw,
    )


@pytest.mark.parametrize("coil_type", [InstructionType.COIL_LATCH, InstructionType.COIL_RESET])
def test_set_reset_oneshot_refused(coil_type) -> None:
    # CLICK's Set/Reset dialog has no One Shot box.
    with pytest.raises(FieldError, match="Coil.oneshot"):
        Coil(coil_type, "C1", oneshot=True)


def test_out_oneshot_kept() -> None:
    assert Coil(InstructionType.COIL_OUT, "C1", oneshot=True).func_code == "8205"


def test_count_down_down_enabled_refused() -> None:
    with pytest.raises(FieldError, match="Counter.down_enabled"):
        Counter("count_down", "CT1", "CTD1", "5", down_enabled=True, reset_enabled=True)


def test_counter_type_refused() -> None:
    with pytest.raises(FieldError, match="Counter.counter_type"):
        Counter("count_sideways", "CT1", "CTD1", "5", reset_enabled=True)  # type: ignore[arg-type]


def test_off_delay_retained_refused() -> None:
    with pytest.raises(FieldError, match="Timer.retained"):
        Timer("off_delay", "T1", "TD1", "5", "Ts", retained=True)


@pytest.mark.parametrize("bad", [0x99, 0x2711, "out", None])
def test_coil_type_refused(bad) -> None:
    with pytest.raises(FieldError, match="Coil.type"):
        Coil(bad, "C1")


@pytest.mark.parametrize("bad", [0x99, InstructionType.COIL_OUT, "NO", None])
def test_contact_type_refused(bad) -> None:
    with pytest.raises(FieldError, match="Contact.type"):
        Contact(bad, "X1")


@pytest.mark.parametrize("bad", ["", "rising", None])
def test_edge_contact_needs_edge_kind(bad) -> None:
    with pytest.raises(FieldError, match="Contact.edge_kind"):
        Contact(InstructionType.CONTACT_EDGE, "X1", edge_kind=bad)


def test_plain_contact_has_no_edge_kind() -> None:
    with pytest.raises(FieldError, match="Contact.edge_kind"):
        Contact(InstructionType.CONTACT_NO, "X1", edge_kind="rise")


@pytest.mark.parametrize(
    "make",
    [
        lambda rows: _timer(pin_rows=rows),
        lambda rows: _counter(pin_rows=rows),
        lambda rows: _shift(pin_rows=rows),
        lambda rows: _drum(pin_rows=rows),
    ],
    ids=["timer", "counter", "shift", "drum"],
)
@pytest.mark.parametrize(
    "rows",
    [(), (1,) * 5, (0, 1, 2), (3, 2, 1), (1, 1, 1), (1, 2, 300), [1, 2], ("1", "2"), (True, 2)],
    ids=repr,
)
def test_pin_rows_refused(make, rows) -> None:
    with pytest.raises(FieldError, match="pin_rows"):
        make(rows)


def test_pin_rows_refused_on_copy() -> None:
    with pytest.raises(FieldError, match="Timer.pin_rows"):
        _timer().with_pin_rows(())


def test_pin_rows_valid_kept() -> None:
    assert _timer(pin_rows=(4,)).pin_rows == (4,)
    assert _counter(pin_rows=(2, 7)).pin_rows == (2, 7)
    assert Counter("count_down", "CT1", "CTD1", "5", reset_enabled=True).pin_rows == (1, 2)


def test_blob_with_unwritable_pin_rows_stays_raw() -> None:
    blob = bytearray(_timer().build_blob())
    marker = blob.index(b"\x02\x00", 2 * len("Tmr") + 2 + 4)
    assert blob[marker + 2] == 1
    blob[marker + 2] = 0  # a row CLICK never writes
    assert parse_af_blob(bytes(blob)) is None


@pytest.mark.parametrize("bad", ["1", 1.0, None, True, -1, 65536])
def test_raw_part_count_refused(bad) -> None:
    with pytest.raises(FieldError, match="RawInstruction.part_count"):
        RawInstruction("Zzz", b"", part_count=bad)


def test_raw_blob_and_name_types_refused() -> None:
    with pytest.raises(FieldError, match="RawInstruction.blob"):
        RawInstruction("Zzz", "ab")  # type: ignore[arg-type]
    with pytest.raises(FieldError, match="RawInstruction.class_name"):
        RawInstruction(b"Zzz", b"")  # type: ignore[arg-type]


def test_raw_keeps_every_part_count_decode_makes() -> None:
    assert RawInstruction("Zzz", b"", part_count=0).part_count == 0
    assert RawInstruction("Zzz", b"", part_count=0xFFFF).part_count == 0xFFFF


@pytest.mark.parametrize("bad", [[], {}, {1}, [1, 2]], ids=repr)
def test_unhashable_fields_raise_field_error(bad) -> None:
    with pytest.raises(FieldError, match="Coil.type"):
        Coil(bad, "C1")
    with pytest.raises(FieldError, match="Contact.type"):
        Contact(bad, "X1")
    with pytest.raises(FieldError, match="Contact.edge_kind"):
        Contact(InstructionType.CONTACT_EDGE, "X1", edge_kind=bad)
    with pytest.raises(FieldError, match="Timer.unit"):
        Timer("on_delay", "T1", "TD1", "5", bad)  # type: ignore[arg-type]
    with pytest.raises(FieldError, match="Timer.timer_type"):
        Timer(bad, "T1", "TD1", "5", "Ts")  # type: ignore[arg-type]
    with pytest.raises(FieldError, match="Counter.counter_type"):
        Counter(bad, "CT1", "CTD1", "5", reset_enabled=True)  # type: ignore[arg-type]
    with pytest.raises(FieldError, match="Coil.oneshot"):
        Coil(InstructionType.COIL_OUT, "C1", oneshot=bad)  # type: ignore[arg-type]
    with pytest.raises(FieldError, match="Contact.immediate"):
        Contact(InstructionType.CONTACT_NO, "X1", immediate=bad)  # type: ignore[arg-type]
    with pytest.raises(FieldError, match="Counter.down_enabled"):
        Counter("count_up", "CT1", "CTD1", "5", down_enabled=bad, reset_enabled=True)  # type: ignore[arg-type]


def test_pin_rows_error_names_the_instruction() -> None:
    with pytest.raises(FieldError) as info:
        _timer(pin_rows=())
    assert info.value.obj is not None
    assert "(1 for a Timer)" in str(info.value)


def _csv_af(tmp_path: Path, *afs: str) -> list:
    import csv

    from laddercodec.csv import CSV_HEADER

    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        for i, af in enumerate(afs):
            w.writerow(["R" if i == 0 else "", "X1" if i == 0 else ""] + [""] * 30 + [af])
    return read_csv(path)


@pytest.mark.parametrize("token", ["latch(C1,oneshot=1)", "reset(C1..C2,oneshot=1)"])
def test_csv_set_reset_oneshot_refused(tmp_path: Path, token: str) -> None:
    with pytest.raises(FieldError, match="Coil.oneshot"):
        _csv_af(tmp_path, token)


def test_csv_off_delay_with_reset_refused(tmp_path: Path) -> None:
    # The converter reports a pin's refusal as a ConvertError that carries the message.
    with pytest.raises(ConvertError, match="Timer.retained"):
        _csv_af(tmp_path, "off_delay(T1,TD1,preset=5,unit=Ts)", ".reset()")


def test_int_flags_normalise_to_bool() -> None:
    one = Coil(InstructionType.COIL_OUT, "Y1", oneshot=1, immediate=1)  # type: ignore[arg-type]
    true = Coil(InstructionType.COIL_OUT, "Y1", oneshot=True, immediate=True)
    assert one.oneshot is True and one.immediate is True
    assert one.build_blob() == true.build_blob()
    off = Coil(InstructionType.COIL_OUT, "Y1", oneshot=0)  # type: ignore[arg-type]
    assert off.oneshot is False
    contact = Contact(InstructionType.CONTACT_NO, "X1", immediate=1)  # type: ignore[arg-type]
    assert contact.immediate is True
    assert contact.build_blob() == Contact(InstructionType.CONTACT_NO, "X1", True).build_blob()
    counter = Counter("count_up", "CT1", "CTD1", "5", down_enabled=1, reset_enabled=1)  # type: ignore[arg-type]
    assert counter.down_enabled is True and counter.reset_enabled is True


@pytest.mark.parametrize("bad", [2, -1, "1", None, 1.0, []], ids=repr)
def test_other_flag_values_refused(bad) -> None:
    with pytest.raises(FieldError, match="Coil.oneshot"):
        Coil(InstructionType.COIL_OUT, "C1", oneshot=bad)
    with pytest.raises(FieldError, match="Contact.immediate"):
        Contact(InstructionType.CONTACT_NO, "X1", immediate=bad)
