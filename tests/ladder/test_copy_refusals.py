"""Copy, BlockCopy, Fill, Pack and Unpack keep every refusal, each with a reason.

An instruction with two independent bad fields reports both in ``FieldError.errors``; each
refusal has a :class:`~laddercodec.Reason`, and ``click_id`` is set where CLICK's id for the
refusal is known.  ``tests/conftest.py`` checks that no refusal of these classes lacks a reason.
"""

from __future__ import annotations

from typing import Any

import pytest

from laddercodec import BlockCopy, Copy, FieldError, Fill, Pack, Unpack


def _errors(build: Any) -> tuple[FieldError, ...]:
    with pytest.raises(FieldError) as caught:
        build()
    assert caught.value.errors[0] is caught.value
    return caught.value.errors


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
                ("Pack.destination", "bank", None),
                ("Pack.allow_whitespace", "flag", None),
            ],
        ),
        (
            lambda: Unpack("X1", "C1", "C0", unpack_type="bogus", oneshot=2),
            [
                ("Unpack.unpack_type", "choice", None),
                ("Unpack.source", "bank", None),
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
    (error,) = _errors(lambda: Copy("DS1", "TXT1", format="text", termination_code="$D"))
    assert (error.field, error.reason) == ("Copy.termination_code", "form")


def test_copy_text_past_the_last_txt_conflicts_with_its_destination() -> None:
    (error,) = _errors(lambda: Copy('"ABC"', "TXT1000"))
    assert (error.fields, error.reason) == (("Copy.destination", "Copy.source"), "conflict")


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
            "OBJ-035",
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
            "OBJ-019",
        ),
        (
            lambda: Unpack("DS5", "Y1", "Y16", unpack_type="bits"),
            ("Unpack.dest_start", "Unpack.source"),
            "OBJ-024",
        ),
    ],
)
def test_pair_refusals_name_both_fields_with_the_id(
    build: Any, fields: tuple[str, str], click_id: str
) -> None:
    (error,) = _errors(build)
    assert (error.fields, error.reason, error.click_id) == (fields, "conflict", click_id)
    assert str(error).endswith(f" ({click_id})")


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


def test_blockcopy_ends_are_not_computed_from_a_refused_range() -> None:
    # A backwards source range: no destination end is worked out from it.
    assert _shape(_errors(lambda: BlockCopy("DS4", "DS1", "DS10", "DS99"))) == [
        ("BlockCopy.source_end", "conflict", "OBJ-009")
    ]


def test_fill_reasons() -> None:
    (error,) = _errors(lambda: Fill("TXT1", "DS1", "DS4"))
    assert (error.fields, error.reason) == (("Fill.dest_start", "Fill.value"), "conflict")
    # Fill's pairing refusal carries no id: its dialog's is not known.
    assert error.click_id is None
    (error,) = _errors(lambda: Fill("0", "DS1", "DD5"))
    assert (error.fields, error.reason, error.click_id) == (
        ("Fill.dest_end", "Fill.dest_start"),
        "conflict",
        "OBJ-008",
    )


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
