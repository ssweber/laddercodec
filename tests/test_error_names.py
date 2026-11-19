"""Test ``message()``, ``short()`` and ``detail()``, which show a refusal with the user's names.

A refusal keeps the parts of its message: the label, the operand with its short rule, the
explanation and CLICK's id.  ``str(err)`` is built from them, and the three methods render
them again with names for the addresses.  ``tests/conftest.py`` checks that every refusal of
a class in its ``NAMED`` set keeps its parts.
"""

from __future__ import annotations

import copy
import csv
import itertools
import pickle
import re
import warnings
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from laddercodec import AddressError, FieldError, RefusedFieldWarning, read_csv
from laddercodec.codes import Code
from laddercodec.csv import CSV_HEADER
from laddercodec.errors import CsvReadError, LaddercodecError
from laddercodec.instructions.copy import BlockCopy, Copy, Fill, Pack, Unpack
from laddercodec.operands.address import (
    check_address,
    display_form_only,
    normalize_address,
    parse_address,
)
from laddercodec.operands.message import parts_of


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
            "its start (OBJ-009)",
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
            "Fill.dest_end: DS[Ptr] (DS[DD1]) is a pointer; only a single Copy takes one",
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
    assert str(error).startswith("Fill.value: '12' is 2 characters")


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
    assert error.short() == "'DS5000' is outside the range of Thing.field"
    assert error.detail() == "it takes DS1-DS4500"


def test_detail_ends_with_what_to_do() -> None:
    error = _refusal(lambda: Fill(value="12", dest_start="TXT1", dest_end="TXT2"))
    assert error.short() == "'12' is 2 characters, and a Fill into TXT takes one"
    assert error.detail() == "Write one character, such as '5', or a real, such as 1.5."


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
    assert str(error) == "Copy.source pointer: 'DD1' is not allowed; Copy.source pointer takes DS"
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
            "a pointer in Copy.dest addresses C, DS, DD, DH, DF, YD, TD, CTD, TXT",
            id="OBJ-004",
        ),
        pytest.param(
            lambda: Copy(source="-FFh", dest="DS1"),
            "OBJ-005",
            "Copy.source: '-FFh' is refused; a hex constant has no sign (OBJ-005)",
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
    for build, fields in _builds():
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
