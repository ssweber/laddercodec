"""Test ``message()``, ``short()`` and ``detail()``, which show a refusal with the user's names.

A refusal keeps the parts of its message: the label, the operand with its short rule, the
explanation and CLICK's id.  ``str(err)`` is built from them, and the three methods render
them again with names for the addresses.  ``tests/conftest.py`` checks that every refusal of
a class in its ``NAMED`` set keeps its parts.
"""

from __future__ import annotations

import copy
import csv
import dataclasses
import itertools
import pickle
import re
import warnings
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from laddercodec import (
    AddressError,
    Box,
    Branch,
    Circuit,
    FieldError,
    Math,
    Parallel,
    RefusedFieldWarning,
    Series,
    read_csv,
)
from laddercodec.codes import Code
from laddercodec.csv import CSV_HEADER
from laddercodec.errors import CsvReadError, LaddercodecError
from laddercodec.instructions import Tee
from laddercodec.instructions.call import Call
from laddercodec.instructions.coil import Coil
from laddercodec.instructions.comparison import CompareContact
from laddercodec.instructions.contact import Contact
from laddercodec.instructions.copy import BlockCopy, Copy, Fill, Pack, Unpack
from laddercodec.instructions.counter import Counter
from laddercodec.instructions.drum import Drum
from laddercodec.instructions.forloop import ForLoop
from laddercodec.instructions.out_variant import OutVariant
from laddercodec.instructions.raw import RawInstruction
from laddercodec.instructions.search import Search
from laddercodec.instructions.send_receive import (
    ModbusAddress,
    ModbusRtuTarget,
    ModbusTcpTarget,
    Receive,
    Send,
)
from laddercodec.instructions.shift import Shift
from laddercodec.instructions.timer import Timer
from laddercodec.instructions.undecoded import Undecoded
from laddercodec.operands.address import (
    check_address,
    display_form_only,
    normalize_address,
    parse_address,
)
from laddercodec.operands.checks import bank_of
from laddercodec.operands.message import parts_of
from laddercodec.operands.unchecked import refusals, unchecked


def _refusal(build: Callable[[], object]) -> FieldError:
    with pytest.raises(FieldError) as raised:
        build()
    return raised.value


def _read_af(tmp_path: Path, af: str, *, unchecked: bool = False) -> None:
    path = tmp_path / "rung.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        writer.writerow(["R", "X001"] + ["-"] * 30 + [af])
    read_csv(path, unchecked=unchecked)


def _copy_ds1_into_c1() -> FieldError:
    return _refusal(lambda: Copy(source="DS1", dest="C1"))


# ---------------------------------------------------------------------------
# message()
# ---------------------------------------------------------------------------


def test_message_shows_each_named_address_with_clicks_form_after_it() -> None:
    error = _copy_ds1_into_c1()
    assert str(error) == (
        "Copy.dest: 'C1' can't take 'DS1'; a numeric register copies to DS, DD, DH, DF, YD, "
        "TD, CTD, SD, TXT (OBJ-024)"
    )
    assert error.message({"C1": "Valve", "DS1": "Count"}) == (
        "Copy.dest: Valve (C1) can't take Count (DS1); a numeric register copies to DS, DD, "
        "DH, DF, YD, TD, CTD, SD, TXT (OBJ-024)"
    )


def test_message_drops_the_quotes_of_an_address_with_no_name() -> None:
    """With names, an address that has no name is shown bare, as CLICK writes it."""
    error = _copy_ds1_into_c1()
    assert error.message({"C1": "Valve"}).startswith("Copy.dest: Valve (C1) can't take DS1;")


@pytest.mark.parametrize("names", [None, {}])
def test_message_with_no_names_is_str(names: dict[str, str] | None) -> None:
    error = _copy_ds1_into_c1()
    assert error.message(names) == str(error)


def test_message_matches_a_key_in_any_form_that_click_reads() -> None:
    error = _copy_ds1_into_c1()
    assert error.message({"c001": "Valve", "ds1": "Count"}) == error.message(
        {"C1": "Valve", "DS1": "Count"}
    )


def test_message_ignores_a_key_that_is_no_address() -> None:
    """A key that is no CLICK address, such as ``X999`` outside every X slot, names nothing.
    The names still drop the quotes, because ``names`` is not empty."""
    error = _copy_ds1_into_c1()
    assert error.message({"Valve": "C1", "": "x", "X999": "far"}) == (
        "Copy.dest: C1 can't take DS1; a numeric register copies to DS, DD, DH, DF, YD, TD, "
        "CTD, SD, TXT (OBJ-024)"
    )
    assert error.message({"Valve": "C1", "C1": "Valve"}) == error.message({"C1": "Valve"})


def test_message_takes_the_later_of_two_keys_for_one_address() -> None:
    error = _copy_ds1_into_c1()
    assert error.message({"C1": "First", "c001": "Second"}).startswith("Copy.dest: Second (C1)")


@pytest.mark.parametrize(
    ("build", "names", "want"),
    [
        pytest.param(
            lambda: BlockCopy(source_start="C2", source_end="C1", dest_start="DS1", dest_end="DS2"),
            {"C1": "Valve1", "C2": "Valve2"},
            "BlockCopy.source_end: Valve2..Valve1 (C2..C1) runs backwards; a range ends after "
            "its start (OBJ-009). Write an end above C2, and move the destination end to match.",
            id="range-both-ends-named",
        ),
        pytest.param(
            lambda: Pack(source_start="C1", source_end="C40", dest="DS1"),
            {"C1": "Valve1"},
            "Pack.source_end: Valve1..C40 (C1..C40) is 40 bits; a pack into DS1 takes at most "
            "16 (OBJ-027)",
            id="range-start-named",
        ),
        pytest.param(
            lambda: Fill(value="1", dest_start="DS1", dest_end="DS[DD1]"),
            {"DD1": "Ptr"},
            "Fill.dest_end: DS[Ptr] (DS[DD1]) is a pointer; only a single Copy takes one. "
            "Write an address, such as DS2.",
            id="pointer-index-named",
        ),
        pytest.param(
            lambda: Copy(source="5", dest="x1"),
            {"X1": "Start"},
            "Copy.dest: Start (X001) is not allowed; Copy.dest takes Y, C, DS, DD, DH, DF, YD, "
            "TD, CTD, SD, TXT (OBJ-024)",
            id="typed-text",
        ),
        pytest.param(
            lambda: Fill(value="1", dest_start="x1", dest_end="x2"),
            {"X1": "Start"},
            "Fill.dest_start: Start..x2 (X001..X002) is not allowed; Fill.dest_start takes DS, "
            "DD, DH, DF, YD, TD, CTD, SD, TXT",
            id="merged-range-typed",
        ),
    ],
)
def test_message_names_ranges_pointers_and_typed_text(
    build: Callable[[], object], names: dict[str, str], want: str
) -> None:
    assert _refusal(build).message(names) == want


def test_a_constant_is_never_renamed() -> None:
    error = _refusal(lambda: Fill(value="12", dest_start="TXT1", dest_end="TXT2"))
    assert error.message({"TXT1": "Name"}) == str(error)
    assert str(error).startswith("Fill.value: 12 is 2 characters")


def test_message_never_names_an_address_in_a_list_of_the_rule() -> None:
    """The list of writable SD registers is not an operand, so a name for ``SD29`` leaves
    it alone."""
    error = _refusal(lambda: Fill(value="1", dest_start="SD1", dest_end="SD2"))
    assert "the writable SD are SD29, SD31," in str(error)
    message = error.message({"SD29": "X"})
    assert message.startswith("Fill.dest_start: SD1..SD2 holds SD1, which is not")
    assert "the writable SD are SD29, SD31," in message
    assert "X (SD29)" not in message


# ---------------------------------------------------------------------------
# short() and detail()
# ---------------------------------------------------------------------------


def test_short_is_the_operand_and_its_rule() -> None:
    error = _copy_ds1_into_c1()
    assert error.short() == "'C1' can't take 'DS1'"
    assert error.short({"C1": "Valve"}) == "Valve (C1) can't take DS1"


def test_detail_is_the_explanation_alone() -> None:
    error = _copy_ds1_into_c1()
    assert error.detail() == "a numeric register copies to DS, DD, DH, DF, YD, TD, CTD, SD, TXT"


def test_detail_names_the_addresses_in_the_explanation() -> None:
    error = _refusal(lambda: Pack(source_start="C1", source_end="C40", dest="DS1"))
    assert error.detail({"DS1": "Count"}) == "a pack into Count (DS1) takes at most 16"


def test_short_and_detail_leave_the_id_and_label_out() -> None:
    """The id that follows the short rule belongs to neither part."""
    with pytest.raises(AddressError) as raised:
        check_address("DS5000", "Thing.field", range_ids={"DS": "OBJ-010"})
    error = raised.value
    assert (
        str(error)
        == "Thing.field: 'DS5000' is outside the range of Thing.field (OBJ-010); it takes DS1-DS4500"
    )
    assert error.short() == "'DS5000' is outside the range of this field"
    assert error.detail() == "it takes DS1-DS4500"


def test_detail_ends_with_what_to_do() -> None:
    error = _refusal(lambda: Fill(value="12", dest_start="TXT1", dest_end="TXT2"))
    assert error.short() == "12 is 2 characters, and a Fill into TXT takes one"
    assert error.detail() == "Write one character, such as 5, or a real, such as 1.5."


@pytest.mark.parametrize(("source", "dest"), [("DF1", "DD1"), ("DD1", "DF1")])
def test_a_wrong_converter_between_a_real_and_a_32_bit_integer_offers_to_binary(
    source: str, dest: str
) -> None:
    error = _refusal(lambda: Copy(source, dest, convert="to_text"))
    assert error.code == Code.COPY_CONVERTER_BANK
    assert error.detail() == "Leave convert out, or write convert=to_binary."
    Copy(source, dest, convert="to_binary")


def test_a_refusal_with_no_explanation_has_an_empty_detail() -> None:
    with pytest.raises(AddressError) as raised:
        check_address("Q1", "Thing.field")
    assert raised.value.short() == "'Q1' has no CLICK bank 'Q'"
    with pytest.raises(AddressError) as raised:
        check_address("C2001", "Thing.field")
    assert raised.value.detail() == ""


def test_not_display_form_has_no_explanation() -> None:
    with display_form_only(), pytest.raises(FieldError) as raised:
        Copy(source="ds1", dest="DS2")
    error = raised.value
    assert str(error) == "Copy.source: 'ds1' is not CLICK's display form 'DS1'"
    # The operand is not in CLICK's form, so no name replaces it.
    assert error.short({"DS1": "Count"}) == "'ds1' is not CLICK's display form 'DS1'"
    assert error.detail() == ""


# ---------------------------------------------------------------------------
# Several refusals, unconverted errors, CSV
# ---------------------------------------------------------------------------


def test_each_of_several_refusals_renders_its_own_parts() -> None:
    """``str(err)`` is the first refusal's text.  Each item of ``errors`` renders its own."""
    error = _refusal(lambda: Copy(source="DS[DD1]", dest="X1"))
    assert len(error.errors) == 2
    assert str(error) == (
        "Copy.source pointer: 'DD1' is not allowed; Copy.source pointer takes DS. "
        "Write a DS address as the index, such as DS[DS1]."
    )
    assert error.short({"DD1": "Ptr"}) == "Ptr (DD1) is not allowed"
    second = error.errors[1]
    assert second.short({"X1": "Start"}) == "Start (X001) is not allowed"
    assert second.message({"X1": "Start"}).startswith("Copy.dest: Start (X001) is not allowed;")


def test_an_error_with_no_parts_ignores_names() -> None:
    error = FieldError(
        "Thing.field: 'C1' is refused; it needs another", field="Thing.field", code=Code.BLANK_FIELD
    )
    assert error.message({"C1": "Valve"}) == str(error)
    assert error.short({"C1": "Valve"}) == "'C1' is refused; it needs another"
    assert error.detail({"C1": "Valve"}) == ""


def test_an_error_whose_text_was_rewritten_ignores_its_parts() -> None:
    error = _copy_ds1_into_c1()
    error.args = (f"{error}. More text.",)
    assert parts_of(error) is None
    assert error.message({"C1": "Valve"}) == str(error)


def test_a_csv_refusal_keeps_its_location_on_message_only(tmp_path: Path) -> None:
    with pytest.raises(FieldError) as raised:
        _read_af(tmp_path, "copy(DS1,C1)")
    error = raised.value
    location = str(error)[str(error).index(" (at ") :]
    assert location.endswith(", column AF)")
    assert error.message({"C1": "Valve"}).endswith("(OBJ-024)" + location)
    assert error.message({"C1": "Valve"}).startswith("Copy.dest: Valve (C1) can't take DS1;")
    assert error.short({"C1": "Valve"}) == "Valve (C1) can't take DS1"
    assert "(at " not in error.detail()


@pytest.mark.parametrize(
    ("af", "short"),
    [
        pytest.param(
            "copy(DS1,TXT1,convert=to_binary(foo=1))",
            "'foo' is not an option",
            id="convert-option",
        ),
        pytest.param(
            "copy(DS1,TXT1,convert=to_text(),termination_code=$0D)",
            "'$0D' stands alone only for TXT copied to TXT, with no converter, not beside "
            "to_text()",
            id="termination-code-beside-converter",
        ),
        pytest.param(
            "copy(DS1,TXT1,convert=to_text(suppress_zero=1),termination_code=$0D)",
            "'$0D' stands alone only for TXT copied to TXT, with no converter, not beside "
            "to_text(suppress_zero=True)",
            id="termination-code-beside-a-flag",
        ),
    ],
)
def test_a_copy_csv_token_refusal_keeps_its_parts(tmp_path: Path, af: str, short: str) -> None:
    """These two refusals come from parsing the CSV token, which the guard in
    ``tests/conftest.py`` does not see."""
    with pytest.raises(FieldError) as raised:
        _read_af(tmp_path, af)
    error = raised.value
    assert parts_of(error) is not None
    assert error.short() == short


def test_a_for_count_refusal_says_its_short_rule_and_what_to_do() -> None:
    error = _refusal(lambda: ForLoop("1 0"))
    assert parts_of(error) is not None
    assert error.short() == "'1 0' has a space in it"
    assert error.detail() == "Write the count as digits only, such as 10."


def test_a_refusal_that_read_csv_keeps_shows_names(tmp_path: Path) -> None:
    """``read_csv(..., unchecked=True)`` keeps a refused Copy, and the warning's error
    keeps its parts."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _read_af(tmp_path, "copy(DS1,C1)", unchecked=True)
    [warning] = [w.message for w in caught if isinstance(w.message, RefusedFieldWarning)]
    assert warning.error.message({"C1": "Valve"}).startswith(
        "Copy.dest: Valve (C1) can't take DS1;"
    )


@pytest.mark.parametrize(
    ("build", "click_id", "want", "detail"),
    [
        pytest.param(
            lambda: Copy(source="$0D", dest="X[DS1]"),
            "OBJ-004",
            "Copy.dest: X[Count] (X[DS1]) is not allowed; a pointer in Copy.dest addresses C, "
            "DS, DD, DH, DF, YD, TD, CTD, TXT (OBJ-004)",
            "a pointer in this field addresses C, DS, DD, DH, DF, YD, TD, CTD, TXT",
            id="OBJ-004",
        ),
        pytest.param(
            lambda: Copy(source="-FFh", dest="DS1"),
            "OBJ-005",
            "Copy.source: -FFh is refused; a hex constant has no sign (OBJ-005)",
            "a hex constant has no sign",
            id="OBJ-005",
        ),
    ],
)
def test_a_refusal_raised_again_with_an_id_keeps_its_parts(
    build: Callable[[], object], click_id: str, want: str, detail: str
) -> None:
    error = _refusal(build)
    assert error.click_id == click_id
    assert parts_of(error) is not None
    assert error.message({"DS1": "Count"}) == want
    assert error.detail() == detail


def test_a_csv_read_error_passes_the_calls_to_its_refusal() -> None:
    refusal = _copy_ds1_into_c1()
    wrapped = CsvReadError(str(refusal), refusal=refusal)
    assert wrapped.message({"C1": "Valve"}) == refusal.message({"C1": "Valve"})
    assert wrapped.short({"C1": "Valve"}) == refusal.short({"C1": "Valve"})
    assert wrapped.detail() == refusal.detail()


def test_a_csv_read_error_with_its_own_text_ignores_names() -> None:
    refusal = _copy_ds1_into_c1()
    wrapped = CsvReadError(f"The file name is wrong. {refusal}. Rename it.", refusal=refusal)
    assert wrapped.message({"C1": "Valve"}) == str(wrapped)
    assert wrapped.detail() == ""


def test_any_laddercodec_error_has_the_methods() -> None:
    error = LaddercodecError("something is wrong")
    assert error.message({"C1": "Valve"}) == "something is wrong"
    assert error.short() == "something is wrong"
    assert error.detail() == ""


# ---------------------------------------------------------------------------
# Copies of an error
# ---------------------------------------------------------------------------


def test_pickling_keeps_the_parts() -> None:
    error = _copy_ds1_into_c1()
    back = pickle.loads(pickle.dumps(error))
    assert back.message({"C1": "Valve"}) == error.message({"C1": "Valve"})
    assert back.detail() == error.detail()


def test_copy_keeps_the_parts() -> None:
    error = _copy_ds1_into_c1()
    assert copy.copy(error).message({"C1": "Valve"}) == error.message({"C1": "Valve"})


# ---------------------------------------------------------------------------
# Every address in a refusal can take a name
# ---------------------------------------------------------------------------

_POOL = (
    "DS1", "ds1", "C1", "c2", "C16", "X1", "x2", "X021", "Y1", "TXT1", "TXT2", "SD1",
    "SD29", "DD1", "DF1", "TD1", "DS[DD1]", "X[DS1]", "", "5", "1.5", "FFh", '"AB"', "$0D",
    "TXT1000",
)  # fmt: skip
_SMALL = ("DS1", "c2", "C16", "X1", "x2", "Y1", "TXT1", "SD1", "SD29", "DD1", "DS[DD1]", "")


def _builds() -> Iterator[tuple[Callable[[], object], tuple[str, ...]]]:
    """Yield each build of a Copy-family instruction in the corpus, with its text fields."""
    for a, b in itertools.product(_POOL, _POOL):
        for convert in (None, "to_value", "to_text", "to_binary", "to_ascii"):
            yield (lambda a=a, b=b, c=convert: Copy(source=a, dest=b, convert=c)), (a, b)
    for a, b, c in itertools.product(_SMALL, _SMALL, _SMALL):
        yield (lambda a=a, b=b, c=c: Fill(value=a, dest_start=b, dest_end=c)), (a, b, c)
        for kind in ("pack_bits", "pack_words", "pack_text"):
            yield (
                (lambda a=a, b=b, c=c, k=kind: Pack(source_start=a, source_end=b, dest=c, kind=k)),
                (a, b, c),
            )
        for kind in ("unpack_to_bits", "unpack_to_words"):
            yield (
                (lambda a=a, b=b, c=c, k=kind: Unpack(source=a, dest_start=b, dest_end=c, kind=k)),
                (a, b, c),
            )
    for a, b, c, d in itertools.product(
        ("DS1", "DS4", "c1", "C16", "Y1", "TXT1", "SD29"), repeat=4
    ):
        yield (
            (
                lambda a=a, b=b, c=c, d=d: BlockCopy(
                    source_start=a, source_end=b, dest_start=c, dest_end=d
                )
            ),
            (a, b, c, d),
        )


def _box_builds() -> Iterator[tuple[Callable[[], object], tuple[str, ...]]]:
    """Yield each build of a Timer, Counter, Shift, ForLoop or Drum in the corpus."""
    pool = ("T1", "T2", "TD1", "TD2", "CT1", "CTD1", "CTD2", "DS1", "DS[DD1]", "C1", "c2", "X1")
    for a, b, c in itertools.product(pool, pool, ("5", "DS1", "C1", "x1", "")):
        for kind in ("on_delay", "off_delay", "T1"):
            for unit in ("Tms", "C1"):
                yield (
                    (lambda a=a, b=b, c=c, k=kind, u=unit: Timer(k, a, b, c, u)),
                    (a, b, c, unit),
                )
        for kind in ("count_up", "count_down", "C1"):
            yield (lambda a=a, b=b, c=c, k=kind: Counter(k, a, b, c)), (a, b, c)
        yield (lambda a=a, b=b: Shift(a, b)), (a, b)
    for count in (*pool, "", " ", "1 0", "-0", "99999999999", "1.5", "DS[DD1]"):
        yield (lambda c=count: ForLoop(c)), (count,)
    for kind in ("event_drum", "time_drum", "time_event_drum", "C1"):
        for out in (("Y1", "Y2"), ("Y1", "y1"), ("C1", "C2"), ("DS1",), ("X1",), ()):
            for flag in ("C1", "C3", "DS1", "x1"):
                for ev, pre in ((("C5", "C6"), ("5", "DS1")), (("",), ("",)), ((), ())):
                    for unit in ("", "Tms", "C1"):
                        yield (
                            (
                                lambda k=kind, o=out, f=flag, e=ev, p=pre, u=unit: Drum(
                                    k,
                                    o,
                                    p,
                                    e,
                                    ((0,) * len(o),) * 2,
                                    "DS1",
                                    f,
                                    "TD1",
                                    unit=u,
                                    jump_enabled=True,
                                    jump_step="C1",
                                )
                            ),
                            (*out, flag, *ev, *pre, unit),
                        )
    for kind, rows in (("on_delay", (1, 2)), ("on_delay", (0,)), ("on_delay", (3, 2))):
        yield (lambda k=kind, r=rows: Timer(k, "T1", "TD1", "5", "Tms", pin_rows=r)), ()
    for pattern in (((0, 2),) * 2, ((0, 1),)):
        yield (
            (lambda p=pattern: Drum("event_drum", ("Y1", "Y2"), (), ("C5", "C6"), p, "DS1", "C1")),
            (),
        )


def _addresses(fields: tuple[str, ...]) -> dict[str, str]:
    """Return each CLICK address in ``fields``, in display form, mapped to the text typed."""
    out: dict[str, str] = {}
    for value in fields:
        for piece in re.split(r"\.\.|\[|\]", value):
            try:
                display = normalize_address(piece)
            except ValueError:
                continue
            if display and parse_address(display) is not None:
                out[display] = piece
    return out


def _outside_parentheses(text: str) -> str:
    while True:
        stripped = re.sub(r"\([^()]*\)", "", text)
        if stripped == text:
            return text
        text = stripped


def test_every_address_that_a_copy_family_refusal_quotes_takes_a_name() -> None:
    """Name each address in the fields, and no address is left in quotes.

    An address in quotes outside parentheses is plain text in the parts, so no name can
    replace it.  An address in a bank list, a limit or an example is not in quotes.
    """
    plain: dict[str, str] = {}
    count = 0
    for build, fields in (*_builds(), *_box_builds()):
        try:
            build()
        except FieldError as exc:
            addresses = _addresses(fields)
            names = {display: f"<{display}>" for display in addresses}
            for error in exc.errors:
                count += 1
                text = _outside_parentheses(error.message(names))
                for display, typed in addresses.items():
                    if f"'{display}'" in text or f"'{typed}'" in text:
                        plain.setdefault(str(error), display)
    assert count > 1000
    assert not plain, plain


# ---------------------------------------------------------------------------
# Send, Receive and the Modbus targets
# ---------------------------------------------------------------------------

_TCP = ModbusTcpTarget("tcp", "192.168.1.10", 502, 1)
_ADDRESSES = (
    "DS1", "ds1", "DS5", "DS4500", "C1", "c2", "C2000", "X1", "x1", "X021", "X816", "Y1", "Y16",
    "TXT1", "TXT999", "SD1", "SD29", "DD1", "DF1", "DH1", "XD0", "YD0", "TD1", "T1", "CT1",
    "SC1", "DS[DD1]", "Q1", "",
)  # fmt: skip
_STATUS = ("", "C1", "c2", "DS1", "X1")


def _send_receive_builds() -> Iterator[tuple[Callable[[], object], tuple[str, ...]]]:
    """Yield each build of a Send or Receive in the corpus, with its text fields."""
    for make, field in ((Send, "source"), (Receive, "dest")):
        for remote, local in itertools.product(_ADDRESSES, _ADDRESSES):
            for quantity in (1, 2, 17, 251, 2001):
                for fc in (None, 5, 6, 1, 16):
                    kw = {
                        "remote_start": remote,
                        field: local,
                        "quantity": quantity,
                        "function_code": fc,
                    }
                    yield (lambda make=make, kw=kw: _send_receive(make, **kw)), (remote, local)
        for remote, local in itertools.product(_MODBUS, ("DS1", "C1", "DD1", "TXT999", "Y1")):
            for quantity in (1, 3, 125, 250):
                kw = {"remote_start": remote, field: local, "quantity": quantity}
                yield (lambda make=make, kw=kw: _send_receive(make, **kw)), (local,)
        names = (
            "sending" if make is Send else "receiving",
            "success",
            "error",
            "exception_response",
        )
        for statuses in itertools.product(_STATUS, repeat=4):
            kw = dict(zip(names, statuses, strict=True))
            yield (lambda make=make, kw=kw: _send_receive(make, **kw)), statuses


_MODBUS = (
    ModbusAddress("400001"),
    ModbusAddress("500000"),
    ModbusAddress("FFFEh"),
    ModbusAddress("FFFCh"),
    ModbusAddress("0h", "coil"),
    ModbusAddress("10h", "input"),
)


def _send_receive(make: type, **kw: object) -> object:
    base: dict[str, object] = {
        "target": _TCP,
        "remote_start": "DS1",
        "quantity": 1,
        "success": "",
        "error": "",
        "exception_response": "",
    }
    base["source" if make is Send else "dest"] = "DS1"
    base["sending" if make is Send else "receiving"] = ""
    base.update(kw)
    return make(**base)


def test_every_address_that_a_send_or_receive_refusal_names_takes_a_name() -> None:
    """Name each address in the fields, and no address is left in quotes or bare.

    An address in quotes outside parentheses is plain text in the parts, and so is a bare
    address.  The sentence that says what to do and the example ranges of an X or Y count are
    plain on purpose.
    """
    plain: dict[str, str] = {}
    count = 0
    for build, fields in _send_receive_builds():
        try:
            build()
        except FieldError as exc:
            addresses = _addresses(fields)
            names = {display: f"<{display}>" for display in addresses}
            for error in exc.errors:
                count += 1
                parts = parts_of(error)
                assert parts is not None, str(error)
                # The sentence that says what to do gives an example address, in plain text.
                text = _outside_parentheses(dataclasses.replace(parts, then="").text(names))
                for display, typed in addresses.items():
                    bare = re.search(rf"(?<![\w<]){re.escape(display)}(?![\w>])", text)
                    if f"'{display}'" in text or f"'{typed}'" in text or bare:
                        plain.setdefault(str(error), display)
    assert count > 1000
    assert not plain, plain


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda: ModbusRtuTarget("r", "bogus", 1), id="rtu-com-port"),
        pytest.param(lambda: ModbusRtuTarget("r", "cpu2", 248), id="rtu-device-id"),
        pytest.param(lambda: ModbusRtuTarget("r", "cpu2", "DD1"), id="rtu-device-id-bank"),
        pytest.param(lambda: ModbusTcpTarget("t", "1.2.3", 502, 1), id="tcp-ip"),
        pytest.param(lambda: ModbusTcpTarget("t", "1.2.3.4", 0, 1), id="tcp-port-range"),
        pytest.param(lambda: ModbusTcpTarget("t", "1.2.3.4", "502", 1), id="tcp-port-form"),
        pytest.param(lambda: ModbusAddress("xyz"), id="address-form"),
        pytest.param(lambda: ModbusAddress("10h", "bogus"), id="address-register-type"),
    ],
)
def test_a_modbus_target_refusal_keeps_its_parts(build: Callable[[], object]) -> None:
    error = _refusal(build)
    assert parts_of(error) is not None
    assert error.message() == str(error)


def test_a_slave_id_in_another_bank_shows_its_name() -> None:
    error = _refusal(lambda: ModbusRtuTarget("r", "cpu2", "DD1"))
    assert error.short({"DD1": "Id"}) == "Id (DD1) is not an address from DS1 to DS4500"


@pytest.mark.parametrize(
    ("af", "short"),
    [
        pytest.param(
            'send(target=ModbusTcpTarget(name="t",ip="1.2.3.4",port=abc,device_id=1),'
            'remote_start="DS1",source=DS1)',
            "'abc' is not a port number",
            id="port",
        ),
        pytest.param(
            'send(target=ModbusTcpTarget(name="t",ip="1.2.3.4",port=502,device_id=1),'
            'remote_start="DS1",source=DS5..DS1)',
            "range 'DS5..DS1' runs backwards",
            id="range-backwards",
        ),
        pytest.param(
            'send(target=ModbusTcpTarget(name="t",ip="1.2.3.4",port=502,device_id=1),'
            'remote_start="DS1",source=DS1..C5)',
            "range 'DS1..C5' mixes banks DS and C",
            id="range-banks",
        ),
        pytest.param(
            'send(target=ModbusTcpTarget(name="t",ip="1.2.3.4",port=502,device_id=1),'
            'remote_start="DS1",source=DS1,function_code=x)',
            "function_code must be a number, got 'x'",
            id="function-code",
        ),
    ],
)
def test_a_send_csv_token_refusal_keeps_its_parts(tmp_path: Path, af: str, short: str) -> None:
    """These refusals come from parsing the CSV token, which the guard in
    ``tests/conftest.py`` does not see."""
    with pytest.raises(FieldError) as raised:
        _read_af(tmp_path, af)
    error = raised.value
    assert parts_of(error) is not None
    assert error.short() == short


_BIT_POOL = (
    "X1", "x2", "Y1", "C1", "c2", "C16", "DS1", "ds1", "TD1", "SC1", "SC50", "T1", "DS[DD1]",
    "", "5", "1.5", "FFh", '"A"', "DH",
)  # fmt: skip
_BIT_SMALL = ("X1", "Y1", "C1", "c2", "DS1", "TD1", "SC50", "5", "DH", "")


def _bit_builds() -> Iterator[tuple[Callable[[], object], tuple[str, ...]]]:
    """Yield each build of a bit instruction in the corpus, with its text fields."""
    for a in _BIT_POOL:
        for kind in ("no", "nc", "rise", "fall", "bogus"):
            for imm in (False, True):
                yield (lambda a=a, k=kind, i=imm: Contact(a, kind=k, immediate=i)), (a,)
        for kind in ("out", "latch", "reset", "bogus"):
            for one in (False, True):
                yield (lambda a=a, k=kind, o=one: Coil(a, kind=k, oneshot=o)), (a,)
            for imm in (False, True):
                yield (lambda a=a, k=kind, i=imm: Coil(a, kind=k, immediate=i)), (a,)
            for b in _BIT_POOL:
                yield (lambda a=a, b=b, k=kind: Coil(a, kind=k, range_end=b)), (a, b)
        for op in ("==", "<", "bogus", None):
            for b in _BIT_POOL:
                yield (lambda a=a, b=b, o=op: CompareContact(op=o, left=a, right=b)), (a, b)
    for kind in ("toggle", "debounce", "flasher", "timed", "bogus"):
        for a, b, c in itertools.product(_BIT_SMALL, _BIT_SMALL, _BIT_SMALL):
            for unit in ("", "Tms", "Ts", "bogus"):
                for maintained in (False, True):
                    yield (
                        (
                            lambda a=a, b=b, c=c, k=kind, u=unit, m=maintained: OutVariant(
                                k,
                                a,
                                on_acc=b,
                                on_preset=c,
                                off_acc=b,
                                off_preset=c,
                                unit=u,
                                maintained=m,
                            )  # fmt: skip
                        ),
                        (a, b, c),
                    )


def test_every_address_that_a_bit_instruction_refusal_quotes_takes_a_name() -> None:
    """The same check as for the Copy family, over the bit instructions."""
    plain: dict[str, str] = {}
    count = 0
    for build, fields in _bit_builds():
        try:
            build()
        except FieldError as exc:
            addresses = _addresses(fields)
            names = {display: f"<{display}>" for display in addresses}
            for error in exc.errors:
                count += 1
                text = _outside_parentheses(error.message(names))
                for display, typed in addresses.items():
                    if f"'{display}'" in text or f"'{typed}'" in text:
                        plain.setdefault(str(error), display)
    assert count > 1000
    assert not plain, plain


def test_a_bit_instruction_csv_refusal_keeps_its_parts(tmp_path: Path) -> None:
    """A refused flag in an ``out(...)`` token comes from the CSV parse, which the guard in
    ``tests/conftest.py`` does not see.  A refused address of the same token is built by
    ``Coil`` itself, and it keeps its parts."""
    with pytest.raises(FieldError) as flag:
        _read_af(tmp_path, "out(C1,oneshot=2)")
    assert parts_of(flag.value) is not None
    assert flag.value.short() == "2 is not 1 or 0"
    assert flag.value.message({"C1": "Valve"}).split(" (at ")[0] == (
        "Coil.oneshot: 2 is not 1 or 0. Write oneshot=1 or oneshot=0."
    )
    with pytest.raises(FieldError) as target:
        _read_af(tmp_path, "out(DS1)")
    assert parts_of(target.value) is not None
    assert target.value.short({"DS1": "Count"}) == "Count (DS1) is not allowed"
    assert target.value.message({"DS1": "Count"}).split(" (at ")[0] == (
        "Coil.operand: Count (DS1) is not allowed; Coil.operand takes Y, C, SC (OBJ-004)"
    )


def test_a_coil_refusal_shows_the_name_of_each_end_of_the_range() -> None:
    error = _refusal(lambda: Coil("C2", range_end="C1"))
    assert error.message({"C1": "Last", "C2": "First"}).startswith(
        "Coil.range_end: Last (C1) is not above First (C2);"
    )
    assert str(error).startswith("Coil.range_end: 'C1' is not above 'C2';")


# ---------------------------------------------------------------------------
# Search, Call, Tee, RawInstruction and Undecoded
# ---------------------------------------------------------------------------

_MISC_NAMES = {"DS1": "Count", "DS5": "Last", "TXT1": "Text", "DD1": "Ptr"}


@pytest.mark.parametrize(
    ("build", "short", "detail"),
    [
        pytest.param(
            lambda: Search("DS1", "DS5", "DS7", "DS10", "C10", "bad"),
            "'bad' is not allowed",
            "it is one of ==, !=, >, >=, <, <=",
            id="search-op",
        ),
        pytest.param(
            lambda: Search("DS1", "DS5", '"ab"', "DS10", "C10", ">"),
            "'>' is not offered for text \"ab\"",
            "text searches with == or !=",
            id="search-text-order",
        ),
        pytest.param(
            lambda: Search("TXT1", "TXT5", "5", "DS10", "C10", "=="),
            "5 is an integer value, which searches CTD, DD, DF, DS, TD, not TXT",
            "a TXT table takes quoted text, a $hh character code or a TXT address",
            id="search-constant-table",
        ),
        pytest.param(
            lambda: Search("DS1", "DS5", "DH1", "DS10", "C10", "=="),
            "'DH1' is a hex address, which searches DH, not DS",
            "a DS table takes a number or a DS, DD, DF, TD, CTD or SD address",
            id="search-group-table",
        ),
        pytest.param(
            lambda: Search("DH1", "DH5", "5", "DS10", "C10", "=="),
            "5 is an integer value, which searches CTD, DD, DF, DS, TD, not DH",
            "a DH table takes a hex value or a DH, XD or YD address",
            id="search-hex-table",
        ),
        pytest.param(
            lambda: Call(""),
            "The subroutine name is blank",
            "Enter the name of the subroutine to call.",
            id="call-blank",
        ),
        pytest.param(
            lambda: Call("a/b"),
            "'a/b' holds /",
            'a subroutine name may not hold any of \\ / : * ? " < > |',
            id="call-forbidden",
        ),
        pytest.param(
            lambda: Call("a" * 25),
            "'" + "a" * 25 + "' is 25 characters",
            "a subroutine name is at most 24",
            id="call-long",
        ),
        pytest.param(
            lambda: Call("con"),
            "'con' uses the Windows device name 'con'",
            "CLICK refuses it as a subroutine name",
            id="call-device",
        ),
        pytest.param(
            lambda: Tee(Tee(Contact("X1"))),
            "Tee(contact=Contact(operand='X001', kind='no', immediate=False)) is a Tee already",
            "Wrap the contact once, such as Tee(Contact('X001')).",
            id="tee-tee",
        ),
        pytest.param(
            lambda: Tee("X1"),
            "'X1' is not a contact",
            "Wrap a Contact or a CompareContact, such as Tee(Contact('X001')). "
            "For a wire down with no contact, write 'T'.",
            id="tee-not-a-contact",
        ),
        pytest.param(
            lambda: Undecoded(5, 0),
            "5 must be text that says why",
            "",
            id="undecoded-error-form",
        ),
        pytest.param(
            lambda: Undecoded("", 0),
            "is blank",
            "it must be text that says why",
            id="undecoded-error-blank",
        ),
        pytest.param(
            lambda: Undecoded("a\nb", 0),
            "'a\\nb' must be one line",
            "",
            id="undecoded-error-lines",
        ),
        pytest.param(
            lambda: Undecoded("a", -1),
            "-1 must be a whole number from 0",
            "",
            id="undecoded-rung",
        ),
        pytest.param(
            lambda: Undecoded("a", 0, 1.5),
            "1.5 must be None or a whole number from 0",
            "",
            id="undecoded-row",
        ),
        pytest.param(
            lambda: Undecoded("a", 0, None, 40),
            "40 must be None or 0 to 31",
            "",
            id="undecoded-column",
        ),
        pytest.param(
            lambda: Undecoded("a", 0, stop="bad"),
            "'bad' must be 'end' or 'return'",
            "",
            id="undecoded-stop",
        ),
        pytest.param(
            lambda: RawInstruction(5, b"", 1),
            "5 is not text",
            "",
            id="raw-class-name",
        ),
        pytest.param(
            lambda: RawInstruction("Foo", "x", 1),
            "str is not bytes",
            "",
            id="raw-blob",
        ),
        pytest.param(
            lambda: RawInstruction("Foo", b"", 70000),
            "70000 is not a whole number from 0 to 65535",
            "",
            id="raw-part-count-range",
        ),
        pytest.param(
            lambda: RawInstruction("Foo", b"", "1"),
            "'1' is not a whole number from 0 to 65535",
            "",
            id="raw-part-count-form",
        ),
        pytest.param(
            lambda: RawInstruction("Foo", b"", 1, 0),
            "0 is not a whole number from 1 to 255",
            "",
            id="raw-rows",
        ),
        pytest.param(
            lambda: RawInstruction("Foo", b"", 1, None, "2"),
            "'2' is not a whole number from 1 to 255",
            "",
            id="raw-sub",
        ),
    ],
)
def test_a_refusal_of_search_call_tee_raw_or_undecoded_renders_its_parts(
    build: Callable[[], object], short: str, detail: str
) -> None:
    error = _refusal(build)
    assert parts_of(error) is not None
    assert error.short() == short
    assert error.detail(_MISC_NAMES) == detail
    assert error.message() == str(error)


def test_a_search_refusal_names_the_table_and_the_value() -> None:
    error = _refusal(lambda: Search("C1", "C5", "DS7", "DS10", "C10", "=="))
    assert error.short({"C1": "Valve"}) == "Valve..C5 (C1..C5) is not allowed"
    error = _refusal(lambda: Search("DS1", "DS5", "DH1", "DS10", "C10", "=="))
    assert error.message({"DH1": "Word"}) == (
        "Search.value: Word (DH1) is a hex address, which searches DH, not DS; a DS table "
        "takes a number or a DS, DD, DF, TD, CTD or SD address (OBJ-004)"
    )
    error = _refusal(lambda: Search("DS1", "DS5", '"ab"', "DS10", "C10", ">"))
    assert error.short({"ab": "x"}) == "'>' is not offered for text \"ab\""


def test_a_text_that_looks_like_an_address_is_never_renamed() -> None:
    """A subroutine name, a marker's error text and a class name are plain text."""
    names = {"DS1": "Count"}
    assert _refusal(lambda: Call("DS1/")).short(names) == "'DS1/' holds /"
    assert _refusal(lambda: Undecoded("DS1\n", 0)).short(names) == "'DS1\\n' must be one line"
    assert _refusal(lambda: RawInstruction("DS1", "x", 1)).short(names) == "str is not bytes"


@pytest.mark.parametrize(
    ("token", "short"),
    [
        pytest.param("raw(Foo)", "raw(Foo): a raw token is raw(ClassName,...)", id="no-comma"),
        pytest.param("notraw(x)", "Not a raw token: 'notraw(x)'", id="not-raw"),
        pytest.param("raw(Foo,zz)", "'zz' is not hex bytes", id="hex"),
        pytest.param(
            "raw(Foo,0102,pins=1)",
            "raw(Foo,hex,...): pins=1 can't follow the hex",
            id="hex-pins",
        ),
        pytest.param(
            "raw(Foo,0102,extra)",
            "raw(Foo,hex,...): only rows= and sub= may follow the hex, not 'extra'",
            id="hex-extra",
        ),
        pytest.param(
            "raw(Foo,0x1234,x)",
            "raw(Foo,...): type marker is 0xTTTT and part count is digits",
            id="type-marker",
        ),
        pytest.param(
            "raw(Foo,0x1234,65536)",
            "raw(Foo,...): part count 65536 is not a whole number from 0 to 65535",
            id="part-count",
        ),
        pytest.param(
            "raw(Foo,0x1234,3,pins=1/2,rows=5)",
            "raw(Foo,...): 'rows=5' goes right after the part count, rows= then sub= then "
            "pins=, once each",
            id="order",
        ),
        pytest.param(
            "raw(Foo,0x1234,3,rows=2,pins=1/2)",
            "raw(Foo,...): rows=2 does not fit pins=1/2",
            id="rows-pins",
        ),
        pytest.param(
            "raw(Foo,0102,rows=0)",
            "raw(Foo,...): rows='0' is not a whole number from 1 to 32",
            id="rows",
        ),
        pytest.param(
            "raw(Foo,0102,sub=256)",
            "raw(Foo,...): sub='256' is not a whole number from 1 to 255",
            id="sub",
        ),
        pytest.param(
            "raw(Foo,0x1234,300)",
            "raw(Foo,...): 300 parts need pins=, each row 1 to 31",
            id="pins-needed",
        ),
        pytest.param(
            "raw(Foo,0x1234,1,pins=1)",
            "raw(Foo,...): pins=1 is only for a box of 2 or more parts, not 1",
            id="pins-one-part",
        ),
        pytest.param(
            "raw(Foo,0x1234,3,pins=1)",
            "raw(Foo,...): pins=1 must hold 2 rows, one per part after the first, joined by /",
            id="pins-count",
        ),
        pytest.param(
            "raw(Foo,0x1234,3,pins=1/x)",
            "raw(Foo,...): pins=1/x holds a row that is not a whole number from 1 to 31",
            id="pins-row",
        ),
        pytest.param(
            "raw(Foo,0x1234,3,pins=2/1)",
            "raw(Foo,...): pins=2/1 must ascend",
            id="pins-order",
        ),
        pytest.param("raw(Foo,0x1234,1,bad)", "Invalid field spec: 'bad'", id="field-spec"),
    ],
)
def test_a_raw_token_refusal_keeps_its_parts(token: str, short: str) -> None:
    error = _refusal(lambda: RawInstruction.from_csv_token(token))
    assert parts_of(error) is not None
    assert error.short() == short
    assert error.message(_MISC_NAMES) == str(error)


def test_a_raw_token_refusal_that_states_what_the_box_needs_has_a_detail() -> None:
    error = _refusal(lambda: RawInstruction.from_csv_token("raw(Foo,0102,pins=1)"))
    assert error.detail() == "the blob holds the part bytes"
    error = _refusal(lambda: RawInstruction.from_csv_token("raw(Foo,0x1234,3,rows=2,pins=1/2)"))
    assert error.detail() == "the box ends one row below its last pin (rows=3)"


@pytest.mark.parametrize(
    ("af", "short"),
    [
        pytest.param(
            'undecoded("why",rung=x,stop=end)',
            "'x' must be a whole number from 0",
            id="rung-form",
        ),
        pytest.param(
            'undecoded("why",stop=end)',
            "'undecoded(\"why\",stop=end)' has no rung=",
            id="rung-missing",
        ),
        pytest.param(
            'undecoded("why",rung=0)',
            "'undecoded(\"why\",rung=0)' has no stop=",
            id="stop-missing",
        ),
        pytest.param(
            'undecoded("why",rung=0,stop=bad)',
            "'bad' must be 'end' or 'return'",
            id="stop-choice",
        ),
        pytest.param(
            "undecoded(why,rung=0,stop=end)",
            "'undecoded(why,rung=0,stop=end)' must be "
            'undecoded("<error>",rung=N,row=R,column=C,stop=end,to_the_end=1), '
            "row, column and to_the_end optional",
            id="syntax",
        ),
    ],
)
def test_an_undecoded_csv_token_refusal_keeps_its_parts(
    tmp_path: Path, af: str, short: str
) -> None:
    """These refusals come from parsing the CSV token, which the guard in
    ``tests/conftest.py`` does not see."""
    with pytest.raises(FieldError) as raised:
        _read_af(tmp_path, af)
    error = raised.value
    assert parts_of(error) is not None
    assert error.short() == short
    assert error.message(_MISC_NAMES).startswith("Undecoded")


_SEARCH_ADDRESSES = (
    "DS1", "ds1", "DS5", "DS4500", "C1", "c2", "X1", "Y1", "TXT1", "TXT9", "SD1", "DD1", "DF1",
    "DH1", "XD0", "TD1", "T1", "CT1", "CTD1", "DS[DD1]", "Q1", "",
)  # fmt: skip


def _search_builds() -> Iterator[tuple[Callable[[], object], tuple[str, ...]]]:
    """Yield each build of a Search in the corpus, with its text fields."""
    for start, end, value in itertools.product(_SEARCH_ADDRESSES, repeat=3):
        for op in ("==", ">"):
            fields = (start, end, value)
            yield (
                (
                    lambda a=fields, op=op: Search(
                        table_start=a[0],
                        table_end=a[1],
                        value=a[2],
                        result="DS10",
                        found="C10",
                        op=op,
                    )
                ),
                fields,
            )
    for result, found in itertools.product(_SEARCH_ADDRESSES, repeat=2):
        yield (
            (lambda r=result, f=found: Search("DS1", "DS5", "DS7", result=r, found=f, op="==")),
            (result, found),
        )


def test_every_address_that_a_search_refusal_names_takes_a_name() -> None:
    """Name each address in the fields, and no address is left in quotes or bare.

    A limit such as ``DS1-DS4500`` is plain on purpose, so a refusal that states one is not
    checked for the address that the limit holds.  The example in the sentence that says
    what to write is plain too, so the test removes that sentence before the check.
    """
    plain: dict[str, str] = {}
    count = 0
    for build, fields in _search_builds():
        try:
            build()
        except FieldError as exc:
            addresses = _addresses(fields)
            names = {display: f"<{display}>" for display in addresses}
            for error in exc.errors:
                count += 1
                parts = parts_of(error)
                assert parts is not None, str(error)
                if re.search(r"\b[A-Z]+\d+-[A-Z]*\d+", str(error)):
                    continue
                # The sentence that says what to do gives an example address, in plain text.
                text = _outside_parentheses(dataclasses.replace(parts, then="").text(names))
                for display, typed in addresses.items():
                    bare = re.search(rf"(?<![\w<]){re.escape(display)}(?![\w>])", text)
                    if f"'{display}'" in text or f"'{typed}'" in text or bare:
                        plain.setdefault(str(error), display)
    assert count > 1000
    assert not plain, plain


# ---------------------------------------------------------------------------
# The circuit types
# ---------------------------------------------------------------------------

_CONTACT = Contact("X001")
_COIL = Coil("Y001")
_COIL_REPR = "Coil(operand='Y001', kind='out', range_end=None, immediate=False, oneshot=False)"
_COUNTER = Counter("count_up", "CT1", "CTD1", "5")
_NAMES = {"X001": "Start", "Y001": "Lamp"}

_CIRCUIT_CASES = [
    pytest.param(
        lambda: Series(_CONTACT),
        "Series.terms",
        "Contact(operand='X001', kind='no', immediate=False) is not a tuple of parts",
        "Write a tuple, such as Series((Contact('X001'), Contact('X002'))).",
        id="series-not-a-tuple",
    ),
    pytest.param(
        lambda: Series((Series(()),)),
        "Series.terms[0]",
        "Series(()) is empty, and an empty Series is a wire",
        "Use one only as a leg of a Parallel, such as Parallel((Contact('X001'), Series(()))).",
        id="series-empty-term",
    ),
    pytest.param(
        lambda: Series(("X001",)),
        "Series.terms[0]",
        "'X001' is not a contact or a circuit",
        "Write a Contact, a CompareContact, a Series or a Parallel, such as Contact('X001').",
        id="series-address-text-as-a-term",
    ),
    pytest.param(
        lambda: Parallel((_CONTACT,)),
        "Parallel.legs",
        "has 1 leg",
        "A Parallel needs two or more legs, "
        "such as Parallel((Contact('X001'), Contact('X002'))). "
        "For one term, write the term without a Parallel.",
        id="parallel-one-leg",
    ),
    pytest.param(
        lambda: Parallel(()),
        "Parallel.legs",
        "has 0 legs",
        "A Parallel needs two or more legs, such as Parallel((Contact('X001'), Contact('X002'))).",
        id="parallel-no-legs",
    ),
    pytest.param(
        lambda: Parallel((Series(()), Series(()))),
        "Parallel.legs",
        "holds only wires",
        "A Parallel needs at least one leg that is not a wire, "
        "such as Parallel((Contact('X001'), Series(()))).",
        id="parallel-only-wires",
    ),
    pytest.param(
        lambda: Box("COIL"),
        "Box.instruction",
        "'COIL' is not an output instruction",
        "Write an Instruction or 'NOP', such as Box(Coil('Y001')).",
        id="box-not-an-instruction",
    ),
    pytest.param(
        lambda: Box(_COIL, {".reset": _CONTACT}),
        "Box.pins[0]",
        "'.reset' is not a pin of Coil",
        "A Coil has no pins, so pass no pins.",
        id="box-pin-of-a-pinless-instruction",
    ),
    pytest.param(
        lambda: Box(_COIL, 5),
        "Box.pins",
        "5 is not a mapping of pin names to terms",
        "Write a dict, such as {'.reset': Contact('X002')}.",
        id="box-pins-not-a-mapping",
    ),
    pytest.param(
        lambda: Box(_COUNTER, {".down": _CONTACT}),
        "Box.pins[0]",
        "'.down' is turned off in this Counter",
        "Turn it on with down_enabled=True, or leave '.down' out of pins.",
        id="box-pin-turned-off",
    ),
    pytest.param(
        lambda: Box(_COUNTER, {".bad": _CONTACT}),
        "Box.pins[0]",
        "'.bad' is not a pin of Counter",
        "Write one of '.down', '.reset', such as {'.down': Contact('X002')}.",
        id="box-pin-not-listed",
    ),
    pytest.param(
        lambda: Box("NOP", [(".reset", _CONTACT), (".reset", _CONTACT)]),
        "Box.pins[1]",
        "names the pin '.reset' twice",
        "Give each pin one term.",
        id="box-pin-twice",
    ),
    pytest.param(
        lambda: Branch((_CONTACT,), ()),
        "Branch.outputs",
        "is empty",
        "A Branch needs at least one output, "
        "such as Branch((Contact('X001'),), (Box(Coil('Y001')),)).",
        id="branch-no-outputs",
    ),
    pytest.param(
        lambda: Branch((_CONTACT,), (_COIL,)),
        "Branch.outputs[0]",
        f"{_COIL_REPR} is not a Box or a Branch",
        "Put an instruction in a Box, such as Box(Coil('Y001')).",
        id="branch-output-not-a-box",
    ),
    pytest.param(
        lambda: Circuit(_COIL),
        "Circuit.branch",
        f"{_COIL_REPR} is not a Branch",
        "Write a Branch from the rail, "
        "such as Circuit(Branch((Contact('X001'),), (Box(Coil('Y001')),))).",
        id="circuit-not-a-branch",
    ),
    pytest.param(
        lambda: Circuit(Branch((_CONTACT,), (Box(_COIL),)), 5),
        "Circuit.comment",
        "5 is not text",
        "Write the comment as a str, or pass None.",
        id="circuit-comment",
    ),
]


@pytest.mark.parametrize(("build", "field", "short", "then"), _CIRCUIT_CASES)
def test_a_circuit_refusal_keeps_its_parts(
    build: Callable[[], object], field: str, short: str, then: str
) -> None:
    """A circuit type's refusal says its short rule, then what to do.  It names no address
    of the user's, so the names leave it as it is."""
    error = _refusal(build)
    assert parts_of(error) is not None
    assert error.field == field
    assert error.short() == short
    assert error.detail() == then
    assert error.message(_NAMES) == f"{field}: {short}. {then}"
    assert error.message() == error.message(_NAMES)


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------

_DECIMAL_BANKS = (
    "a decimal Math takes only DS, DD, DF, TD, CTD and SD registers and decimal constants, and "
    "X, Y, C, T and SC bits only as the range of SUM ( a : b )"
)
_MATH_NAMES = {"C1": "Valve", "DS1": "Count", "DS2": "Two", "DS5": "Last", "DH1": "Word"}


#: What an option-slot refusal of a SUM says to write.
_OPTION_SLOT_THEN = (
    "In the option slot, write a range of one point or of two points next to each other, "
    "such as SUM ( X025 : X026 )."
)


@pytest.mark.parametrize(
    ("build", "short", "detail", "named"),
    [
        pytest.param(
            lambda: Math("C1 + DS2", "DS3"),
            "C1 is refused",
            _DECIMAL_BANKS,
            f"Math.expression: Valve (C1) is refused; {_DECIMAL_BANKS} (OBJ-1002)",
            id="bank",
        ),
        pytest.param(
            lambda: Math("SUM ( DH1 : DH5 )", "DS3"),
            "SUM ( DH1 : DH5 ) is refused for DH1",
            _DECIMAL_BANKS,
            f"Math.expression: SUM ( Word (DH1) : DH5 ) is refused for Word (DH1); "
            f"{_DECIMAL_BANKS} (OBJ-1002)",
            id="sum-bank",
        ),
        pytest.param(
            lambda: Math("RAND ( DF1 , DS2 )", "DS3"),
            "DF1 is refused",
            "a decimal RAND bound is a DS or DD register or an integer constant: copy DF1 into "
            "a DS or DD register first",
            "Math.expression: Rate (DF1) is refused; a decimal RAND bound is a DS or DD "
            "register or an integer constant: copy Rate (DF1) into a DS or DD register first "
            "(OBJ-1002)",
            id="rand-bank",
        ),
        pytest.param(
            lambda: Math("RAND ( DS1 , DS1 )", "DS3"),
            "RAND ( DS1 , DS1 ) has equal bounds",
            "RAND takes two different bounds",
            "Math.expression: RAND ( Count (DS1) , Count (DS1) ) has equal bounds; RAND takes "
            "two different bounds (OBJ-1001)",
            id="rand-equal",
        ),
        pytest.param(
            lambda: Math("SUM ( DS5 : DS1 )", "DS3"),
            "DS5 : DS1 runs high to low",
            "a range runs low : high",
            "Math.expression: Last (DS5) : Count (DS1) runs high to low; a range runs low : high "
            "(OBJ-1014)",
            id="range-order",
        ),
        pytest.param(
            lambda: Math("SUM ( DS1 : DD5 )", "DS3"),
            "DS1 : DD5 spans two banks",
            "a range stays in one",
            "Math.expression: Count (DS1) : DD5 spans two banks; a range stays in one (OBJ-1015)",
            id="range-banks",
        ),
        pytest.param(
            lambda: Math("MDN ( DS1 : DS600 )", "DS3"),
            "MDN ( DS1 : DS600 ) covers 1200 bytes",
            "a median covers at most 1024",
            "Math.expression: MDN ( Count (DS1) : DS600 ) covers 1200 bytes; a median covers at "
            "most 1024 (OBJ-1013)",
            id="median",
        ),
        pytest.param(
            lambda: Math("SUM ( X025 : X027 )", "DS3"),
            "SUM ( X025 : X027 ) is refused: X025 and X027 are in the option slot (X021-X036)",
            _OPTION_SLOT_THEN,
            "Math.expression: SUM ( Left (X025) : X027 ) is refused: Left (X025) and X027 are in "
            f"the option slot (X021-X036). {_OPTION_SLOT_THEN}",
            id="option-slot",
        ),
        pytest.param(
            lambda: Math("DS1 DS2", "DS3"),
            "'DS2' after 'DS1': two values need an operator between them",
            "Put an operator between them, such as DS1 + DS2.",
            "Math.expression: Two (DS2) after Count (DS1): two values need an operator between "
            "them (OBJ-1001). Put an operator between them, such as DS1 + DS2.",
            id="order-addresses",
        ),
        pytest.param(
            lambda: Math("DS1 + -5", "DS3"),
            "'-' after '+': a sign right after an operator is refused",
            "Put the signed value in parentheses, such as DS1 * ( -2 ).",
            "Math.expression: '-' after '+': a sign right after an operator is refused "
            "(OBJ-1001). Put the signed value in parentheses, such as DS1 * ( -2 ).",
            id="order-sign",
        ),
        pytest.param(
            lambda: Math("DS1 AND DS2", "DS3"),
            "AND is hex only",
            "'DS1 AND DS2' is a decimal Math. Take AND out of the formula, or set mode to hex. "
            "In a hex Math, write its registers as DH, XD or YD. Write the result to a DH or YD "
            "register.",
            "Math.expression: AND is hex only; 'DS1 AND DS2' is a decimal Math (OBJ-1006). "
            "Take AND out of the formula, or set mode to hex. In a hex Math, write its registers "
            "as DH, XD or YD. Write the result to a DH or YD register.",
            id="key-of-the-other-mode",
        ),
        pytest.param(
            lambda: Math("DS1 + <Foo>", "DS3"),
            "'DS1 + <Foo>' holds a <nickname>",
            "Math takes addresses, not nicknames. Write the address of each nickname in its place.",
            "Math.expression: 'DS1 + <Foo>' holds a <nickname>; Math takes addresses, not "
            "nicknames. Write the address of each nickname in its place.",
            id="nickname",
        ),
        pytest.param(
            lambda: Math("DS1 + foo", "DS3"),
            "'foo' is not an address, a function name or a constant",
            "a Math formula takes only those",
            "Math.expression: 'foo' is not an address, a function name or a constant; a Math "
            "formula takes only those (OBJ-1001)",
            id="word",
        ),
        pytest.param(
            lambda: Math("DS1 + 1e50", "DS3"),
            "1e50 is outside the float32 range",
            "a real constant in Math is at most 3.402823E+38 in size",
            "Math.expression: 1e50 is outside the float32 range; a real constant in Math is at "
            "most 3.402823E+38 in size (OBJ-1009)",
            id="real-range",
        ),
        pytest.param(
            lambda: Math("DS1 + 1.23456789", "DS3"),
            "1.23456789 has more digits than CLICK keeps in Math",
            "CLICK saves it as 1.234568: write 1.234568",
            "Math.expression: 1.23456789 has more digits than CLICK keeps in Math; CLICK saves it "
            "as 1.234568: write 1.234568",
            id="real-digits",
        ),
        pytest.param(
            lambda: Math("DH1 + 5", "DH3", "hex"),
            "5 has no h",
            "a hex Math takes hex constants, and CLICK reads it as 5h: write 5h",
            "Math.expression: 5 has no h; a hex Math takes hex constants, and CLICK reads it as "
            "5h: write 5h",
            id="hex-no-h",
        ),
        pytest.param(
            lambda: Math(" + ".join(f"DS{n}" for n in range(1, 70)), "DS3"),
            "the formula is 273 characters in CLICK's internal form",
            "CLICK allows 270. Shorten the formula.",
            "Math.expression: the formula is 273 characters in CLICK's internal form; CLICK "
            "allows 270 (OBJ-1008). Shorten the formula.",
            id="too-long",
        ),
        pytest.param(
            lambda: Math("DS1", "DS3", "octal"),
            "'octal' is not 'decimal' or 'hex'",
            "",
            "Math.mode: 'octal' is not 'decimal' or 'hex'",
            id="mode",
        ),
    ],
)
def test_a_math_refusal_keeps_its_parts(
    build: Callable[[], object], short: str, detail: str, named: str
) -> None:
    """A Math refusal names each address in it, a range's ends and a RAND bound included.
    A whole formula, a constant, a key and a word stay as they are."""
    error = _refusal(build)
    assert parts_of(error) is not None
    assert error.short() == short
    assert error.detail() == detail
    assert error.message({**_MATH_NAMES, "DF1": "Rate", "X025": "Left"}) == named


@pytest.mark.parametrize(
    ("expression", "dest", "mode", "detail"),
    [
        (
            "DH1 AND DH2",
            "DS3",
            "decimal",
            "'DH1 AND DH2' is a decimal Math. Take AND out of the formula, or set mode to hex. "
            "In a hex Math, write the result to a DH or YD register.",
        ),
        (
            "SIN ( DH1 )",
            "DH3",
            "hex",
            "'SIN ( DH1 )' is a hex Math. Take SIN out of the formula, or set mode to decimal. "
            "In a decimal Math, write its registers as DS, DD, DF, TD, CTD or SD. Write the "
            "result to a DS, DD, DF, TD, CTD or SD register.",
        ),
    ],
)
def test_a_key_of_the_other_mode_names_its_registers_only_when_they_change(
    expression: str, dest: str, mode: str, detail: str
) -> None:
    """The refusal names the other mode's registers when the formula holds one it refuses."""
    error = _refusal(lambda: Math(expression, dest, mode=mode))
    assert error.code == Code.MATH_FUNCTION_MODE
    assert error.detail() == detail


def test_a_math_address_in_a_refused_bank_shows_its_name() -> None:
    error = _refusal(lambda: Math("DS1 + C1", "DS3"))
    assert error.short({"C1": "Valve"}) == "Valve (C1) is refused"
    assert error.detail({"C1": "Valve"}) == _DECIMAL_BANKS
    assert error.message({"C1": "Valve"}) == (
        f"Math.expression: Valve (C1) is refused; {_DECIMAL_BANKS} (OBJ-1002)"
    )


def test_a_math_sum_with_one_end_in_the_option_slot_names_that_end() -> None:
    error = _refusal(lambda: Math("SUM ( X001 : X036 )", "DS3"))
    assert error.short({"X036": "Top"}) == (
        "SUM ( X001 : Top (X036) ) is refused: Top (X036) is in the option slot (X021-X036)"
    )
    assert error.detail({"X036": "Top"}) == _OPTION_SLOT_THEN
    assert error.message({"X036": "Top"}) == (
        "Math.expression: SUM ( X001 : Top (X036) ) is refused: Top (X036) is in the option "
        f"slot (X021-X036). {_OPTION_SLOT_THEN}"
    )


def test_a_math_token_not_in_display_form_shows_its_name_in_an_order_refusal() -> None:
    """Under ``display_form_only()``, ``Y1`` keeps its typed text, and ``Y001`` names it."""
    with display_form_only(), pytest.raises(FieldError) as raised:
        Math("Y1 DS1", "DS3")
    error = raised.value.errors[1]
    assert str(error) == (
        "Math.expression: 'DS1' after 'Y1': two values need an operator between them "
        "(OBJ-1001). Put an operator between them, such as DS1 + DS2."
    )
    assert error.short({"Y001": "Out"}) == (
        "DS1 after Out (Y1): two values need an operator between them"
    )
    assert error.detail({"Y001": "Out"}) == "Put an operator between them, such as DS1 + DS2."
    assert error.message({"Y001": "Out"}) == (
        "Math.expression: DS1 after Out (Y1): two values need an operator between them "
        "(OBJ-1001). Put an operator between them, such as DS1 + DS2."
    )


def test_a_math_address_typed_in_another_form_takes_the_name_of_its_display_form() -> None:
    """A hex Math refuses ``ds1``.  The refusal names DS1, and ``{"DS1": ...}`` names it."""
    error = _refusal(lambda: Math("ds1 + DH2", "DH3", "hex"))
    assert str(error) == (
        "Math.expression: DS1 is refused; a hex Math takes only DH, XD and YD registers and hex "
        "constants (OBJ-1002)"
    )
    assert error.short({"DS1": "Count"}) == "Count (DS1) is refused"
    assert error.short({"ds1": "Count"}) == "Count (DS1) is refused"
    assert error.detail({"DS1": "Count"}) == (
        "a hex Math takes only DH, XD and YD registers and hex constants"
    )
    assert error.message({"DS1": "Count"}) == (
        "Math.expression: Count (DS1) is refused; a hex Math takes only DH, XD and YD registers "
        "and hex constants (OBJ-1002)"
    )


def test_each_refusal_of_a_math_formula_keeps_its_parts() -> None:
    """``Math`` raises the first refusal of the formula, and its ``errors`` hold them all.
    Each keeps its own parts, and so do a copy and a pickled copy of the error."""
    error = _refusal(lambda: Math("C1 + DH1 + 1e50 + LSH ( DS1 , 2 )", "DS3"))
    names = {"C1": "Valve", "DH1": "Word", "DS1": "Count"}
    want_short = [
        "1e50 is outside the float32 range",
        "LSH is hex only",
        "Valve (C1) is refused",
        "Word (DH1) is refused",
    ]
    want_detail = [
        "a real constant in Math is at most 3.402823E+38 in size",
        "'C1 + DH1 + 1e50 + LSH ( DS1 , 2 )' is a decimal Math. Take LSH out of the formula.",
        _DECIMAL_BANKS,
        _DECIMAL_BANKS,
    ]
    want_message = [
        "Math.expression: 1e50 is outside the float32 range; a real constant in Math is at most "
        "3.402823E+38 in size (OBJ-1009)",
        "Math.expression: LSH is hex only; 'C1 + DH1 + 1e50 + LSH ( DS1 , 2 )' is a decimal Math "
        "(OBJ-1006). Take LSH out of the formula.",
        f"Math.expression: Valve (C1) is refused; {_DECIMAL_BANKS} (OBJ-1002)",
        f"Math.expression: Word (DH1) is refused; {_DECIMAL_BANKS} (OBJ-1002)",
    ]
    for each in (error, copy.copy(error), pickle.loads(pickle.dumps(error))):
        assert all(parts_of(e) is not None for e in each.errors)
        assert [e.short(names) for e in each.errors] == want_short
        assert [e.detail(names) for e in each.errors] == want_detail
        assert [e.message(names) for e in each.errors] == want_message


def test_a_math_refusal_that_unchecked_keeps_shows_names() -> None:
    with unchecked():
        math = Math("SUM ( X025 : X027 )", "DS3")
    [error] = refusals(math)
    assert error.short({"X027": "Right"}) == (
        "SUM ( X025 : Right (X027) ) is refused: X025 and Right (X027) are in the option slot "
        "(X021-X036)"
    )


def test_a_math_csv_token_refusal_keeps_its_parts(tmp_path: Path) -> None:
    """``read_csv`` raises the refusal with its CSV location, and ``unchecked=True`` keeps it
    in a warning.  Both keep the parts."""
    with pytest.raises(FieldError) as raised:
        _read_af(tmp_path, "math(DS1 + C1,DS3,mode=decimal)")
    assert raised.value.short({"C1": "Valve"}) == "Valve (C1) is refused"
    assert raised.value.detail() == _DECIMAL_BANKS
    assert raised.value.message({"C1": "Valve"}).startswith(
        "Math.expression: Valve (C1) is refused; "
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _read_af(tmp_path, "math(RAND ( DS1 , DS1 ),DS3,mode=decimal)", unchecked=True)
    [warning] = [w.message for w in caught if isinstance(w.message, RefusedFieldWarning)]
    assert warning.error.short({"DS1": "Count"}) == (
        "RAND ( Count (DS1) , Count (DS1) ) has equal bounds"
    )


_MATH_ADDRESSES = (
    "X001", "x1", "X021", "X030", "Y001", "C1", "c2", "T1", "CT1", "SC1", "DS1", "ds1", "DS001",
    "DS5", "DS0", "DD1", "DH1", "dh1", "DF1", "XD0", "XD3", "YD0", "TD1", "CTD1", "SD1", "TXT1",
)  # fmt: skip
_MATH_SINGLE = ("A + 1", "RAND ( A , 2 )", "LSH ( A , 1h )", "A A", "SIN ( A )", "A +")
_MATH_PAIR = ("A + B", "SUM ( A : B )", "MDN ( A : B )", "RAND ( A , B )")


def _math_builds() -> Iterator[tuple[Callable[[], object], tuple[str, ...]]]:
    """Yield each build of a Math in the corpus, with its formula."""
    for mode, dest in (("decimal", "DS100"), ("hex", "DH100")):
        for template, a in itertools.product(_MATH_SINGLE, _MATH_ADDRESSES):
            formula = template.replace("A", a)
            yield (lambda f=formula, m=mode, d=dest: Math(f, d, m)), (formula,)
        for template, a, b in itertools.product(_MATH_PAIR, _MATH_ADDRESSES, _MATH_ADDRESSES):
            formula = template.replace("A", "\0").replace("B", b).replace("\0", a)
            yield (lambda f=formula, m=mode, d=dest: Math(f, d, m)), (formula,)


def test_every_address_that_a_math_refusal_names_takes_a_name() -> None:
    """Name each address in the formula, and no address is left in quotes or bare.

    A refusal that quotes the whole formula leaves it as it is, so a quoted text is not
    checked for the addresses that it holds.  A limit such as ``DS1-DS4500`` or
    ``X021-X036`` is plain on purpose, so the test removes it before the check.  So is the
    example in the sentence that says what to write, and the test removes that sentence
    too.  The test
    skips each refusal of an address or a constant outside its range.  The limits that
    such a refusal lists for an address also hold single addresses such as ``XD0``.
    """
    plain: dict[str, str] = {}
    count = 0
    for build, (formula,) in _math_builds():
        try:
            build()
        except FieldError as exc:
            addresses = _addresses(tuple(formula.split(" ")))
            names = {display: f"<{display}>" for display in addresses}
            for error in exc.errors:
                count += 1
                parts = parts_of(error)
                assert parts is not None, str(error)
                if " is outside " in str(error):
                    continue
                # Remove the sentence that says what to do, whose example address is plain
                # text, then CLICK's form after each name, then the limits.
                text = dataclasses.replace(parts, then="").text(names)
                text = re.sub(r"(?<=>) \([^()]*\)", "", text)
                text = re.sub(r"\b[A-Z]+\d+-[A-Z]*\d+", "", text)
                for display, typed in addresses.items():
                    if f"'{display}'" in text or f"'{typed}'" in text:
                        plain.setdefault(str(error), display)
                bare = re.sub(r"'[^']*'", "''", text)
                for display in addresses:
                    if re.search(rf"(?<![\w<]){re.escape(display)}(?![\w>])", bare):
                        plain.setdefault(str(error), display)
    assert count > 1000
    assert not plain, plain


# ---------------------------------------------------------------------------
# The wording that short() and detail() use beside the field
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "text", "short", "detail"),
    [
        pytest.param(
            lambda: Fill(value='"ab"', dest_start="TXT1", dest_end="TXT2"),
            'Fill.value: "ab" is 2 characters; Fill.value takes one character',
            '"ab" is 2 characters',
            "this field takes one character",
            id="field",
        ),
        pytest.param(
            lambda: Copy(source="DS[DD1]", dest="DS2"),
            "Copy.source pointer: 'DD1' is not allowed; Copy.source pointer takes DS. "
            "Write a DS address as the index, such as DS[DS1].",
            "'DD1' is not allowed",
            "the pointer takes DS. Write a DS address as the index, such as DS[DS1].",
            id="pointer",
        ),
        pytest.param(
            lambda: check_address("C1", "Send.source", {"DS"}, label="Send source (FC16)"),
            "Send source (FC16): 'C1' is not allowed; Send source (FC16) takes DS",
            "'C1' is not allowed",
            "this field (FC16) takes DS",
            id="note",
        ),
    ],
)
def test_short_and_detail_say_this_field_for_the_label(
    build: Callable[[], object], text: str, short: str, detail: str
) -> None:
    """A caller shows short() and detail() next to the field, so they do not name it.

    ``str(err)`` and ``message()`` keep the label."""
    error = _refusal(build)
    assert str(error) == text
    assert error.message({"DS9": "Other"}).startswith(text.split(":")[0] + ": ")
    assert error.short() == short
    assert error.detail() == detail


def test_a_label_that_names_no_field_stays_in_short_and_detail() -> None:
    with pytest.raises(AddressError) as raised:
        check_address("DS1", "Thing.field", {"C"}, label="range end of 'C1..DS1'")
    assert raised.value.detail() == "range end of 'C1..DS1' takes C"


def test_a_flag_in_a_converter_call_shows_as_python_writes_it() -> None:
    error = _refusal(lambda: Copy("DS1", "TXT1", convert="to_text", exponential=True))
    assert (
        error.short() == "to_text(exponential=True) needs a DF source or a real constant, not 'DS1'"
    )
    error = _refusal(lambda: Copy("TXT1", "DS1", convert="to_value", suppress_zero=True))
    assert error.short() == "suppress_zero=True is not an option for 'TXT1'"


def test_a_text_constant_shows_in_its_own_quotes() -> None:
    error = _refusal(lambda: Copy('"a,b"', "DS1"))
    assert error.short() == "'DS1' can't take \"a,b\""
    assert error.short({"DS1": "Count"}) == 'Count (DS1) can\'t take "a,b"'


def test_a_text_with_a_quote_inside_keeps_its_repr_quotes() -> None:
    # A Copy and a Compare take a quote inside their text, and a Fill refuses it.
    error = _refusal(lambda: Fill('"a"b"', "TXT1", "TXT10"))
    assert error.short().startswith('\'"a"b"\' is refused')


@pytest.mark.parametrize(
    ("names", "shown"),
    [
        pytest.param({"X001": "X1"}, "X1", id="own-address"),
        pytest.param({"x1": "x001"}, "x001", id="own-address-any-case"),
        pytest.param({"X001": "X2"}, "X2 (X001)", id="another-address"),
        pytest.param({"X001": "Start"}, "Start (X001)", id="nickname"),
    ],
)
def test_a_name_that_is_its_own_address_gets_no_brackets(names: dict[str, str], shown: str) -> None:
    error = _refusal(lambda: Copy(source="DS1", dest="X1"))
    assert error.short(names) == f"{shown} is not allowed"


def test_a_range_with_one_own_address_name_keeps_the_brackets_for_the_other() -> None:
    error = _refusal(lambda: Fill(value="1", dest_start="C1", dest_end="C5"))
    assert error.short({"C1": "c1"}) == "c1..C5 is not allowed"
    assert error.short({"C1": "c1", "C5": "Valve"}) == "c1..Valve (C1..C5) is not allowed"


def test_a_pointer_outside_copy_says_what_to_write() -> None:
    error = _refusal(lambda: ForLoop("DS[DS1]"))
    assert error.code == Code.POINTER_OUTSIDE_COPY
    assert str(error) == (
        "ForLoop.count: 'DS[DS1]' is a pointer; only a single Copy takes one. Write an "
        "address, such as DS1."
    )
    assert error.short() == "'DS[DS1]' is a pointer"
    assert error.detail() == "only a single Copy takes one. Write an address, such as DS1."


def test_bank_of_builds_no_pointer_refusal_for_a_copy_field() -> None:
    """A pointer outside a single Copy is refused with a message that names Copy, so
    ``bank_of`` builds no such refusal for a Copy field."""
    built: list[str] = []
    original = LaddercodecError.__init__

    def record(self: LaddercodecError, *args: object, **kwargs: object) -> None:
        original(self, *args, **kwargs)
        built.append(str(self))

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(LaddercodecError, "__init__", record)
        assert bank_of("X[DS1]", "Copy.dest") is None
    assert built == []
