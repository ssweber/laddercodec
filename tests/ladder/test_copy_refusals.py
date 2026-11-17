"""Copy, BlockCopy, Fill, Pack and Unpack keep every refusal, each with a reason.

An instruction with two independent bad fields reports both in ``FieldError.errors``; each
refusal has a :class:`~laddercodec.Reason`, and ``click_id`` is set where CLICK's id for the
refusal is known.  ``tests/conftest.py`` checks that no refusal of these classes lacks a reason.
"""

from __future__ import annotations

from typing import Any

import pytest

from laddercodec import AddressError, BlockCopy, Copy, FieldError, Fill, Pack, Search, Unpack


def _errors(build: Any) -> tuple[FieldError, ...]:
    with pytest.raises(FieldError) as caught:
        build()
    assert caught.value.errors[0] is caught.value
    return caught.value.errors


#: A Block Copy into SD refused for an address after its start: the destination with the
#: source, whose length sets the end.
_SD_RANGE = ("BlockCopy.dest_start", "BlockCopy.source_start", "BlockCopy.source_end")


def _shape(errors: tuple[FieldError, ...]) -> list[tuple[str | None, str | None, str | None]]:
    return [(e.field, e.reason, e.click_id) for e in errors]


# ---------------------------------------------------------------------------
# Two independent bad fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        (
            lambda: Copy("DS1", "DS2", format="bogus", oneshot=2),
            [("Copy.format", "choice", None), ("Copy.oneshot", "flag", None)],
        ),
        (
            lambda: Copy("DS[DS0]", "X1"),
            [("Copy.source", "pointer", None), ("Copy.destination", "bank", None)],
        ),
        (
            lambda: Copy("DS1", "DS2", suppress_zero="2", exponential="x"),
            [("Copy.suppress_zero", "choice", None), ("Copy.exponential", "choice", None)],
        ),
        (
            lambda: BlockCopy("DS1", "DS0", "XD1", "DS5", format="bogus"),
            [
                ("BlockCopy.format", "choice", None),
                ("BlockCopy.source_end", "address", None),
                ("BlockCopy.dest_start", "bank", "OBJ-004"),
            ],
        ),
        (
            lambda: Fill("X1", "DS1", "DS0", oneshot=2),
            [
                ("Fill.value", "bank", None),
                ("Fill.dest_end", "address", None),
                ("Fill.oneshot", "flag", None),
            ],
        ),
        (
            lambda: Pack("C1", "C0", "XD1", pack_type="bogus", allow_whitespace=2),
            [
                ("Pack.pack_type", "choice", None),
                ("Pack.source_end", "address", None),
                ("Pack.destination", "bank", "OBJ-004"),
                ("Pack.allow_whitespace", "flag", None),
            ],
        ),
        (
            lambda: Unpack("X1", "C1", "C0", unpack_type="bogus", oneshot=2),
            [
                ("Unpack.unpack_type", "choice", None),
                ("Unpack.source", "bank", "OBJ-004"),
                ("Unpack.dest_end", "address", None),
                ("Unpack.oneshot", "flag", None),
            ],
        ),
    ],
)
def test_independent_refusals_are_all_reported(build: Any, expected: list[Any]) -> None:
    assert _shape(_errors(build)) == expected


def test_a_refused_field_is_not_checked_again_in_a_pair() -> None:
    # A bad source: the pairing with the destination is not checked.
    assert _shape(_errors(lambda: Copy("DS0", "X1"))) == [
        ("Copy.source", "address", None),
        ("Copy.destination", "bank", None),
    ]
    assert _shape(_errors(lambda: Copy("DS0", "Y1"))) == [("Copy.source", "address", None)]
    # A refused format is not read for the termination code.
    assert _shape(_errors(lambda: Copy("DS1", "TXT1", format="bogus", termination_code="$0D"))) == [
        ("Copy.format", "choice", None)
    ]


# ---------------------------------------------------------------------------
# Copy: a reason for each refusal
# ---------------------------------------------------------------------------


def test_copy_pairings_are_conflicts_of_both_fields() -> None:
    (pair,) = _errors(lambda: Copy("X1", "DS1"))
    assert (pair.fields, pair.reason, pair.click_id) == (
        ("Copy.destination", "Copy.source"),
        "conflict",
        "OBJ-024",
    )
    assert str(pair).endswith(" (OBJ-024)")
    (hexed,) = _errors(lambda: Copy("10000h", "DS1"))
    assert (hexed.fields, hexed.reason, hexed.click_id) == (
        ("Copy.destination", "Copy.source"),
        "conflict",
        "OBJ-024",
    )


def test_copy_format_conflicts() -> None:
    (error,) = _errors(lambda: Copy("DS1", "DS2", format="text"))
    assert error.fields == ("Copy.format", "Copy.source", "Copy.destination")
    assert (error.reason, error.click_id) == ("conflict", None)
    (error,) = _errors(lambda: Copy("DS1", "TXT1", format="text", exponential="1"))
    assert (error.fields, error.reason) == (("Copy.exponential", "Copy.source"), "conflict")


def test_copy_termination_code() -> None:
    (error,) = _errors(lambda: Copy("DS1", "DS2", termination_code="$0D"))
    assert error.fields[0] == "Copy.termination_code"
    assert error.reason == "conflict"
    (error,) = _errors(lambda: Copy("DS1", "TXT1", format="text", termination_code="13"))
    assert (error.field, error.reason, error.click_id) == (
        "Copy.termination_code",
        "form",
        "OBJ-036",
    )


@pytest.mark.parametrize("fmt", ["text", "binary"])
@pytest.mark.parametrize("code", ["$D", "$ZZ", "$", "$0", "$100", "$-1", "$0D0D", "$0d "])
def test_copy_termination_code_not_a_character_code_is_obj_036(fmt: str, code: str) -> None:
    (error,) = _errors(lambda: Copy("DS1", "TXT1", format=fmt, termination_code=code))
    assert (error.field, error.reason, error.click_id) == (
        "Copy.termination_code",
        "form",
        "OBJ-036",
    )


def test_copy_text_past_the_last_txt_is_out_of_range() -> None:
    """CLICK refuses "AB" into TXT1000 as outside the range (OBJ-003), as it does -5."""
    (error,) = _errors(lambda: Copy('"ABC"', "TXT1000"))
    assert (error.fields, error.reason, error.click_id) == (
        ("Copy.destination",),
        "range",
        "OBJ-003",
    )


@pytest.mark.parametrize(
    ("build", "field", "reason"),
    [
        (lambda: Copy("DS1", "DS[DS1]x"), "Copy.destination", "address"),
        (lambda: Copy("DS1", "DS[X1]"), "Copy.destination", "pointer"),
        (lambda: Copy("2147483648", "DD1"), "Copy.source", "range"),
        (lambda: Copy("+1h", "DD1"), "Copy.source", "form"),
        (lambda: Copy("DS1", "DS2", suppress_zero="2"), "Copy.suppress_zero", "choice"),
    ],
)
def test_copy_reasons(build: Any, field: str, reason: str) -> None:
    (error,) = _errors(build)
    assert (error.field, error.reason) == (field, reason)


def test_copy_csv_convert_option_is_a_choice() -> None:
    with pytest.raises(FieldError) as caught:
        Copy.from_csv_token("copy(DS1,TXT2,convert=to_binary(suppress_zero=1))")
    assert (caught.value.field, caught.value.reason) == ("Copy.format", "choice")


# ---------------------------------------------------------------------------
# BlockCopy, Fill, Pack, Unpack
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "fields", "click_id"),
    [
        (
            lambda: BlockCopy("DS1", "DD4", "DS10", "DS13"),
            ("BlockCopy.source_end", "BlockCopy.source_start"),
            "OBJ-008",
        ),
        (
            lambda: BlockCopy("DS4", "DS1", "DS10", "DS13"),
            ("BlockCopy.source_end", "BlockCopy.source_start"),
            "OBJ-009",
        ),
        (
            lambda: BlockCopy("DS1", "DS1", "DS10", "DS10"),
            ("BlockCopy.source_end", "BlockCopy.source_start"),
            "OBJ-012",
        ),
        (
            lambda: BlockCopy("X016", "X021", "C1", "C6"),
            ("BlockCopy.source_end", "BlockCopy.source_start"),
            None,
        ),
        (
            lambda: BlockCopy("DS1", "DS4", "DS10", "DD13"),
            ("BlockCopy.dest_end", "BlockCopy.dest_start"),
            "OBJ-008",
        ),
        (
            lambda: BlockCopy("DS1", "DS4", "C1", "C4"),
            ("BlockCopy.dest_start", "BlockCopy.source_start"),
            "OBJ-024",
        ),
        (
            lambda: Pack("X016", "X021", "DH1", pack_type="bits"),
            ("Pack.source_end", "Pack.source_start"),
            "OBJ-033",
        ),
        (
            lambda: Pack("X1", "X16", "DS1", pack_type="bits"),
            ("Pack.destination", "Pack.source_start"),
            "OBJ-024",
        ),
        (
            lambda: Unpack("DH1", "Y016", "Y021", unpack_type="bits"),
            ("Unpack.dest_end", "Unpack.dest_start"),
            "OBJ-1009",
        ),
        # An Unpack's destination refuses a bank its source can't unpack to as a bank
        # (OBJ-004), where the other pairings are OBJ-024; Y, which only a DH unpacks to,
        # is a pairing of kinds (OBJ-024).
        (
            lambda: Unpack("DS5", "Y1", "Y16", unpack_type="bits"),
            ("Unpack.dest_start", "Unpack.source"),
            "OBJ-024",
        ),
        (
            lambda: Unpack("DS1", "DS1", "DS2", unpack_type="words"),
            ("Unpack.dest_start", "Unpack.source"),
            "OBJ-004",
        ),
    ],
)
def test_pair_refusals_name_both_fields_with_the_id(
    build: Any, fields: tuple[str, str], click_id: str | None
) -> None:
    (error,) = _errors(build)
    assert (error.fields, error.reason, error.click_id) == (fields, "conflict", click_id)
    assert str(error).endswith(f" ({click_id})") == (click_id is not None)


def test_blockcopy_bank_and_ends() -> None:
    # A bank no Block Copy source takes is OBJ-004; the same holds for the destination.
    error, end = _errors(lambda: BlockCopy("XD1", "XD2", "DS1", "DS2"))
    assert (end.field, end.click_id) == ("BlockCopy.source_end", "OBJ-004")
    assert (error.field, error.reason, error.click_id) == (
        "BlockCopy.source_start",
        "bank",
        "OBJ-004",
    )
    error, _ = _errors(lambda: BlockCopy("DS1", "DS2", "X1", "X2"))
    assert (error.field, error.reason, error.click_id) == (
        "BlockCopy.dest_start",
        "bank",
        "OBJ-004",
    )
    (error,) = _errors(lambda: BlockCopy("DS1", "DS4", "DS10", "DS14"))
    assert error.fields[:2] == ("BlockCopy.dest_end", "BlockCopy.dest_start")
    assert (error.reason, error.click_id) == ("conflict", None)
    (error,) = _errors(lambda: BlockCopy("DS1", "DS4", "DS10", "DS13", format="value"))
    assert (error.field, error.reason) == ("BlockCopy.format", "conflict")
    assert error.fields[1] == "BlockCopy.source_start"
    (error,) = _errors(lambda: BlockCopy("C1", "C16", "Y010", "Y025"))
    assert (error.field, error.reason) == ("BlockCopy.dest_start", "conflict")


@pytest.mark.parametrize(
    ("source", "destination", "click_id"),
    [
        # A bit into a bit bank a Copy does not write: an address it can't use.
        ("X001", "X001", "OBJ-004"),
        ("C1", "SC50", "OBJ-004"),
        ("C1", "SC303", "OBJ-004"),
        ("C1", "T1", "OBJ-004"),
        ("C1", "CT1", "OBJ-004"),
        # Anything else into a bit bank: a pairing of kinds.
        ("DS2", "X001", "OBJ-024"),
        ("5", "X001", "OBJ-024"),
        ("TXT1", "SC50", "OBJ-024"),
        ('"A"', "T1", "OBJ-024"),
        # XD has no answer.
        ("DS1", "XD1", None),
        ("C1", "XD1", None),
    ],
)
def test_copy_destination_bank_id_follows_the_source_kind(
    source: str, destination: str, click_id: str | None
) -> None:
    (error,) = _errors(lambda: Copy(source, destination))
    assert (error.field, error.reason, error.click_id) == ("Copy.destination", "bank", click_id)


@pytest.mark.parametrize(
    "destination", ["X000", "X017", "X020", "X817", "T0", "T501", "CT251", "SC1001"]
)
@pytest.mark.parametrize(
    "source",
    [
        "DS2",
        # laddercodec's own: no answer covers a number or a bit into these addresses.
        pytest.param("5", id="own-5"),
        pytest.param("C1", id="own-C1"),
    ],
)
def test_copy_into_an_address_outside_its_bit_bank_is_obj_004(
    source: str, destination: str
) -> None:
    # Outside its bank, in a bit bank a Copy does not write: OBJ-004 from DS2 (CLICK's
    # answer), and from any other source.
    (error,) = _errors(lambda: Copy(source, destination))
    assert (error.field, error.reason, error.click_id) == ("Copy.destination", "bank", "OBJ-004")


@pytest.mark.parametrize(
    ("source", "destination", "reason"),
    [
        ("$41", "DS1", "conflict"),
        ("$1", "DS1", "conflict"),
        ("$ff", "DS1", "conflict"),
        ("$41", "DD1", "conflict"),
        ("$41", "Y001", "conflict"),
        ("$41", "C[DS1]", "conflict"),
        ("$41", "YD0", "conflict"),
        ("$41", "X001", "bank"),
        ("$41", "T1", "bank"),
        ("$41", "XD0", "bank"),
        # A pointer of a bank the field takes no pointer to.
        ("$41", "X[DS1]", "pointer"),
        ("$41", "Y[DS1]", "pointer"),
        ("$41", "T[DS1]", "pointer"),
        ("$41", "CT[DS1]", "pointer"),
        ("$41", "SC[DS1]", "pointer"),
        ("$41", "XD[DS1]", "pointer"),
        ("$41", "SD[DS1]", "pointer"),
    ],
)
def test_copy_of_a_character_code_outside_txt_is_obj_004(
    source: str, destination: str, reason: str
) -> None:
    # A $hh code copies to TXT only; anywhere else CLICK can't use the address (OBJ-004),
    # where quoted text is a pairing of kinds (OBJ-024).
    (error,) = _errors(lambda: Copy(source, destination))
    assert (error.field, error.reason, error.click_id) == ("Copy.destination", reason, "OBJ-004")
    assert Copy(source, "TXT1").destination == "TXT1"
    assert Copy(source, "TXT[DS1]").destination == "TXT[DS1]"


@pytest.mark.parametrize(
    ("source", "destination"),
    [
        ("DS2", "X[DS1]"),
        ("DS2", "XD[DS1]"),
        ("DS2", "SD[DS1]"),
        ("$41", "DS[DS0]"),
        ("$41", "X[DS[DS1]]"),
    ],
)
def test_copy_into_a_refused_pointer_keeps_no_id(source: str, destination: str) -> None:
    # Only a $hh code into a pointer CLICK reads takes OBJ-004 here.  CLICK gives DS2 into
    # X[DS1] OBJ-005 and into XD[DS1] or SD[DS1] OBJ-004, which the rules leave without an
    # id for now; the malformed pointers have no answer.
    (error,) = _errors(lambda: Copy(source, destination))
    assert (error.field, error.reason, error.click_id) == ("Copy.destination", "pointer", None)


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ('""', "range"),
        ("0FFFFFFFFh", "range"),
        ("100000000h", "range"),
        ("FFFFFFFFFh", "range"),
        ("+FFh", "form"),
        ("-FFh", "form"),
        (f'"{"A" * 129}"', "range"),
    ],
)
@pytest.mark.parametrize(
    "destination",
    [
        "DS1",
        # laddercodec's own: CLICK answered these sources into DS1 only.
        pytest.param("DD1", id="own-DD1"),
        pytest.param("TXT1", id="own-TXT1"),
        pytest.param("Y001", id="own-Y001"),
    ],
)
def test_copy_source_value_comes_before_the_pairing(
    source: str, reason: str, destination: str
) -> None:
    # CLICK refuses an empty text, a text of 129 characters, a signed hex constant and one of
    # more than 8 digits into DS1 as values (OBJ-005); the pairing, which depends on the
    # refused source, is not checked.
    (error,) = _errors(lambda: Copy(source, destination))
    assert (error.field, error.reason, error.click_id) == ("Copy.source", reason, "OBJ-005")
    assert str(error).endswith("(OBJ-005)")


@pytest.mark.parametrize("source", ['"""', '"a"b"'])
def test_copy_source_with_a_quote_inside_keeps_no_id(source: str) -> None:
    # No answer covers a quote inside the text.
    (error,) = _errors(lambda: Copy(source, "DS1"))
    assert (error.field, error.reason, error.click_id) == ("Copy.source", "form", None)


def test_copy_text_characters_come_after_the_pairing() -> None:
    # Text outside printable ASCII is refused after the pairing: "é" into DS1 is OBJ-024.
    assert _shape(_errors(lambda: Copy('"é"', "DS1"))) == [
        ("Copy.destination", "conflict", "OBJ-024"),
        ("Copy.source", "form", None),
    ]


@pytest.mark.parametrize(
    "source", ["X001", "Y001", "C1", "T1", "CT1", "SC1", '"A"', '"AB"', "10000h"]
)
def test_copy_pairing_comes_before_the_writable_sd(source: str) -> None:
    # A source no SD takes is a pairing (OBJ-024), even into an SD a Copy does not write.
    assert _shape(_errors(lambda: Copy(source, "SD1"))) == [
        ("Copy.destination", "conflict", "OBJ-024")
    ]


def test_copy_destination_bank_has_no_id_after_a_refused_source() -> None:
    error, dest = _errors(lambda: Copy("DS0", "X001"))
    assert error.field == "Copy.source"
    assert (dest.field, dest.reason, dest.click_id) == ("Copy.destination", "bank", None)


@pytest.mark.parametrize(
    "source", ["99999999999", "1e99", "FFFFFFFFFh", '"é"', '"' + "A" * 200 + '"']
)
def test_copy_destination_bank_has_no_id_for_a_refused_constant(source: str) -> None:
    # The constant's own check runs after the destination's, and keeps that order.
    dest, error = _errors(lambda: Copy(source, "X001"))
    assert (dest.field, dest.reason, dest.click_id) == ("Copy.destination", "bank", None)
    assert error.field == "Copy.source"


@pytest.mark.parametrize(
    ("build", "field"),
    [
        (lambda: Pack("C1", "C16", "X001"), "Pack.destination"),
        (lambda: Pack("C1", "C16", "SD29"), "Pack.destination"),
        (lambda: Pack("X001", "X016", "Y001"), "Pack.destination"),
        (lambda: Unpack("X001", "C1", "C16"), "Unpack.source"),
        (lambda: Unpack("C1", "C2", "C17"), "Unpack.source"),
        (lambda: Unpack("DS1", "X001", "X016"), "Unpack.dest_start"),
        (lambda: Unpack("DH1", "SC50", "SC65"), "Unpack.dest_start"),
        (lambda: Unpack("DD1", "SD31", "SD32", unpack_type="words"), "Unpack.dest_start"),
    ],
)
def test_pack_and_unpack_bank_no_row_holds_is_obj_004(build: Any, field: str) -> None:
    error = _errors(build)[0]
    assert (error.field, error.reason, error.click_id) == (field, "bank", "OBJ-004")
    assert str(error).endswith(" (OBJ-004)")


def test_blockcopy_ends_are_not_computed_from_a_refused_range() -> None:
    # A backwards source range: no destination end is worked out from it.
    assert _shape(_errors(lambda: BlockCopy("DS4", "DS1", "DS10", "DS99"))) == [
        ("BlockCopy.source_end", "conflict", "OBJ-009")
    ]


# ---------------------------------------------------------------------------
# The writable SD registers: a single Copy's and a Block Copy's destination
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("address", ["SD1", "SD28", "SD30", "SD43", "SD105", "SD216", "SD1000"])
def test_copy_into_an_sd_that_is_not_writable_is_obj_004(address: str) -> None:
    assert _shape(_errors(lambda: Copy("DS1", address))) == [
        ("Copy.destination", "not_writable", "OBJ-004")
    ]


@pytest.mark.parametrize("address", ["SD29", "SD42", "SD107", "SD140", "SD147", "SD215"])
def test_copy_into_a_writable_sd(address: str) -> None:
    assert Copy("DS1", address).destination == address
    assert Copy("5", address).destination == address


@pytest.mark.parametrize(
    ("start", "end", "dest", "dest_end", "fields", "click_id"),
    [
        # the start is not writable: no id
        ("DS1", "DS2", "SD43", "SD44", ("BlockCopy.dest_start",), None),
        ("DS1", "DS2", "SD1", "SD2", ("BlockCopy.dest_start",), None),
        # a read-only SD after a writable start (OBJ-018)
        ("DS1", "DS2", "SD42", "SD43", _SD_RANGE, "OBJ-018"),
        ("DS1", "DS2", "SD147", "SD148", _SD_RANGE, "OBJ-018"),
        ("DS1", "DS9", "SD140", "SD148", _SD_RANGE, "OBJ-018"),
        # past SD215, the last writable SD (OBJ-004)
        ("DS1", "DS2", "SD215", "SD216", _SD_RANGE, "OBJ-004"),
        ("DS1", "DS3", "SD214", "SD216", _SD_RANGE, "OBJ-004"),
        # both: no id
        ("DS1", "DS70", "SD147", "SD216", _SD_RANGE, None),
    ],
)
def test_blockcopy_into_sd_needs_every_address_writable(
    start: str, end: str, dest: str, dest_end: str, fields: tuple[str, ...], click_id: str | None
) -> None:
    (error,) = _errors(lambda: BlockCopy(start, end, dest, dest_end))
    assert (error.fields, error.reason, error.click_id) == (fields, "not_writable", click_id)


def test_blockcopy_into_writable_sd() -> None:
    assert BlockCopy("DS1", "DS8", "SD140", "SD147").dest_end == "SD147"
    assert BlockCopy("DS1", "DS2", "SD214", "SD215").dest_end == "SD215"
    assert BlockCopy("DS1", "DS3", "SD34", "SD36").dest_end == "SD36"


def test_fill_reasons() -> None:
    (error,) = _errors(lambda: Fill("TXT1", "DS1", "DS4"))
    assert (error.fields, error.reason) == (("Fill.dest_start", "Fill.value"), "conflict")
    # Fill's pairing refusal carries no id: its dialog's is not known.
    assert error.click_id is None
    (error,) = _errors(lambda: Fill("0", "DS1", "DD5"))
    assert (error.fields, error.reason, error.click_id) == (
        ("Fill.dest_end", "Fill.dest_start"),
        "conflict",
        None,
    )
    # Neither a backwards range nor a one-address range has an id for Fill.
    for end in ("DS5", "DS1"):
        (error,) = _errors(lambda end=end: Fill("0", "DS5", end))
        assert (error.reason, error.click_id) == ("conflict", None)
        assert "OBJ-" not in str(error)


def test_fill_into_txt_takes_one_character_with_no_id() -> None:
    (error,) = _errors(lambda: Fill('"AB"', "TXT1", "TXT4"))
    assert (error.field, error.reason, error.click_id) == ("Fill.value", "range", None)
    assert "takes one character" in str(error)


def test_pack_and_unpack_choices_and_kinds() -> None:
    (error,) = _errors(lambda: Pack("C1", "C4", "DS1", pack_type="text"))
    assert (error.fields, error.reason) == (("Pack.source_start", "Pack.pack_type"), "conflict")
    (error,) = _errors(lambda: Pack("DS1", "DS2", "DD1", pack_type="bits"))
    assert (error.fields, error.reason) == (("Pack.source_start", "Pack.pack_type"), "conflict")
    (error,) = _errors(lambda: Unpack("DD1", "DS2", "DS3", unpack_type="bits"))
    assert (error.fields, error.reason) == (
        ("Unpack.dest_start", "Unpack.unpack_type"),
        "conflict",
    )


@pytest.mark.parametrize(
    ("build", "click_id"),
    [
        (lambda: Pack("C1", "C17", "DS1", pack_type="bits"), "OBJ-027"),
        (lambda: Pack("C1", "C33", "DD1", pack_type="bits"), "OBJ-041"),
        (lambda: Pack("DS1", "DS3", "DD1", pack_type="words"), "OBJ-040"),
        (lambda: Unpack("DS1", "C1", "C17", unpack_type="bits"), "OBJ-032"),
        (lambda: Unpack("DD1", "C1", "C33", unpack_type="bits"), "OBJ-039"),
        (lambda: Unpack("DD1", "DS1", "DS3", unpack_type="words"), "OBJ-042"),
    ],
)
def test_pack_and_unpack_counts(build: Any, click_id: str) -> None:
    (error,) = _errors(build)
    assert (error.reason, error.click_id) == ("range", click_id)
    assert len(error.fields) == 3
    assert error.field.endswith("_end")


_PACK_COUNT = ("Pack.source_end", "range")
_PACK_PAIR = ("Pack.destination", "conflict", "OBJ-024")


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        # A Pack's source is counted before its pairing: against the destination where the
        # source packs into it, else against 32 bits, or two words from a DH.
        (lambda: Pack("T1", "T33", "DS1"), [(*_PACK_COUNT, "OBJ-041"), _PACK_PAIR]),
        (lambda: Pack("SC1", "SC33", "DD1"), [(*_PACK_COUNT, "OBJ-041"), _PACK_PAIR]),
        (lambda: Pack("T1", "T17", "DS1"), [_PACK_PAIR]),
        (lambda: Pack("T1", "T32", "DH1"), [(*_PACK_COUNT, "OBJ-027")]),
        (lambda: Pack("C1", "C33", "DS1"), [(*_PACK_COUNT, "OBJ-027")]),
        (lambda: Pack("C1", "C33", "TD1"), [(*_PACK_COUNT, "OBJ-041"), _PACK_PAIR]),
        # CLICK stops after OBJ-040 for a DH source (no second box); the OBJ-024 after it is
        # laddercodec's own.
        (
            lambda: Pack("DH1", "DH16", "DH1", pack_type="words"),
            [(*_PACK_COUNT, "OBJ-040"), _PACK_PAIR],
        ),
        (lambda: Pack("DH1", "DH2", "DH1", pack_type="words"), [_PACK_PAIR]),
        # A DS source is not counted where it does not pack into the destination.
        (lambda: Pack("DS1", "DS16", "DH1", pack_type="words"), [_PACK_PAIR]),
        (lambda: Pack("DS1", "DS3", "DD1", pack_type="words"), [(*_PACK_COUNT, "OBJ-040")]),
    ],
)
def test_pack_counts_its_source_before_the_pairing(
    build: Any, expected: list[tuple[str, str, str]]
) -> None:
    assert _shape(_errors(build)) == expected


def test_pack_count_without_a_pairing_states_the_limit_of_every_pack() -> None:
    error = _errors(lambda: Pack("T1", "T33", "DS1"))[0]
    assert (
        str(error)
        == "Pack.source_end: T1..T33 is 33 bits; a pack of bits takes at most 32 (OBJ-041)"
    )
    assert error.fields == ("Pack.source_end", "Pack.source_start", "Pack.destination")
    assert type(error) is FieldError


def test_pack_text_into_dh_takes_four_characters() -> None:
    Pack("TXT1", "TXT4", "DH1", pack_type="text")
    Pack("TXT999", "TXT1000", "DH1", pack_type="text")
    for end in ("TXT5", "TXT16", "TXT1000"):
        (error,) = _errors(lambda end=end: Pack("TXT1", end, "DH1", pack_type="text"))
        assert (error.fields, error.reason, error.click_id) == (
            ("Pack.source_end", "Pack.source_start", "Pack.destination"),
            "range",
            "OBJ-003",
        )
    assert str(error) == (
        "Pack.source_end: TXT1..TXT1000 is 1000 characters; a pack into 'DH1' takes at most 4 "
        "(OBJ-003)"
    )
    # The other registers a pack of text writes have no limit yet.
    for dest in ("DS1", "DD1", "DF1", "TD1", "CTD1"):
        Pack("TXT1", "TXT16", dest, pack_type="text")


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        # An Unpack pairs its destination's start with the source before it reads the end:
        # the end's fit with a refused start is not checked.
        (
            lambda: Unpack("DS1", "DS2", "DS1", unpack_type="words"),
            [("Unpack.dest_start", "conflict", "OBJ-004")],
        ),
        (
            lambda: Unpack("DS1", "DS001", "C16", unpack_type="words"),
            [("Unpack.dest_start", "conflict", "OBJ-004")],
        ),
        (
            lambda: Unpack("DH1", "DS1", "DS1", unpack_type="words"),
            [("Unpack.dest_start", "conflict", "OBJ-004")],
        ),
        (
            lambda: Unpack("DS1", "Y816", "Y817"),
            [("Unpack.dest_start", "conflict", "OBJ-024"), ("Unpack.dest_end", "address", None)],
        ),
        (lambda: Unpack("DD1", "Y001", "Y032"), [("Unpack.dest_start", "conflict", "OBJ-024")]),
        # A start the source unpacks to is followed by the end's checks.
        (
            lambda: Unpack("DS1", "C1", "DS1"),
            [("Unpack.dest_end", "conflict", "OBJ-008")],
        ),
        (lambda: Unpack("DH1", "Y001", "Y032"), [("Unpack.dest_end", "conflict", "OBJ-1009")]),
        (lambda: Unpack("DH1", "Y001", "Y036"), [("Unpack.dest_end", "conflict", "OBJ-1009")]),
    ],
)
def test_unpack_pairs_its_destination_before_the_range(
    build: Any, expected: list[tuple[str, str, str | None]]
) -> None:
    assert _shape(_errors(build)) == expected


def test_unpack_into_one_y_slot_from_dh_is_accepted() -> None:
    Unpack("DH1", "Y001", "Y016")
    Unpack("DH1", "Y021", "Y036")


def test_pack_txt_refusals_stay_address_errors() -> None:
    for build in (
        lambda: Pack("TXT3", "TXT4", "CTD1", pack_type="bits"),
        lambda: Pack("X21", "X31", "DH1", pack_type="text"),
    ):
        (error,) = _errors(build)
        assert type(error) is AddressError
        assert (error.fields, error.reason) == (("Pack.source_start", "Pack.pack_type"), "conflict")


@pytest.mark.parametrize(
    ("build", "field", "reason"),
    [
        (lambda: Pack("C1", "C0", "DS1"), "Pack.source_end", "address"),
        (lambda: Pack("C1", "C4", "DS1x"), "Pack.destination", "address"),
        (lambda: Pack("C1", "C4", "XD1"), "Pack.destination", "bank"),
        (lambda: Pack("C1", "C4", "DS[DS1]"), "Pack.destination", "pointer"),
        (lambda: Pack("C[DS1]", "C4", "DS1"), "Pack.source_start", "pointer"),
        (lambda: Unpack("DS1", "C1", "C0"), "Unpack.dest_end", "address"),
        (lambda: Unpack("X1", "C1", "C16"), "Unpack.source", "bank"),
        (lambda: Unpack("DS[DS1]", "C1", "C16"), "Unpack.source", "pointer"),
        (lambda: Unpack("DS1", "C[DS1]", "C16"), "Unpack.dest_start", "pointer"),
    ],
)
def test_pack_and_unpack_shared_refusals(build: Any, field: str, reason: str) -> None:
    error = _errors(build)[0]
    assert (error.field, error.reason) == (field, reason)


@pytest.mark.parametrize(
    ("start", "end", "click_id"),
    [("DS1", "DD5", "OBJ-008"), ("DS9", "DS1", "OBJ-009"), ("DS5", "DS5", "OBJ-012")],
)
def test_search_table_range_refusals_carry_reason_and_id(
    start: str, end: str, click_id: str
) -> None:
    """Search uses ``check_range`` for its table: the pair, a reason and CLICK's id."""
    (error,) = _errors(lambda: Search(start, end, "5", "DS20", "C1", "=="))
    assert error.fields == ("Search.table_end", "Search.table_start")
    assert (error.reason, error.click_id) == ("conflict", click_id)
    assert str(error).endswith(f" ({click_id})")
