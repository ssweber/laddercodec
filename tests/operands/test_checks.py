"""Test the field checks in ``laddercodec.operands.checks``.

Each check gets the values that it accepts and the values that it refuses, for each set of
parameters.
"""

from __future__ import annotations

import re

import pytest

from laddercodec.model import check_flag as model_check_flag
from laddercodec.operands.address import Address
from laddercodec.operands.checks import (
    ALL_KINDS,
    POINTER_BANKS,
    WRITABLE_SC,
    WRITABLE_SD,
    Constants,
    Operand,
    check_constant,
    check_flag,
    check_operand,
    check_out_target,
    check_writable_sd,
)
from laddercodec.operands.constants import Constant, Kind
from laddercodec.operands.errors import AddressError, FieldError

N, F, H, T, C = Kind.INTEGER, Kind.FLOAT, Kind.HEX, Kind.TEXT, Kind.CHAR

#: Every kind of constant, within the limits that classify() applies. A Copy source uses these.
ANY = Constants(ALL_KINDS)
#: A timer preset: digits only, 0 to 32767.
DIGITS = Constants(frozenset({N}), signs="", high=32767)
#: A counter preset: an int32 integer, a leading '-' only, at most 12 characters.
COUNTER = Constants(frozenset({N}), signs="-", max_length=12)
#: A Compare constant. Hex is at most 16 bits, and a real outside float32 is OBJ-005.
COMPARE = Constants(ALL_KINDS, hex_high=0xFFFF, real_id="OBJ-005")
#: A hex remote address: 0h to FFFEh.
HEX_REMOTE = Constants(frozenset({H}), hex_high=0xFFFE)
#: A Fill into TXT: one character.
ONE_CHAR = Constants(frozenset({T, C}), text_max=1)


# ---------------------------------------------------------------------------
# check_constant
# ---------------------------------------------------------------------------

ACCEPTED: list[tuple[str, Constants, Constant]] = [
    ("0", ANY, Constant(N, 0)),
    ("-2147483648", ANY, Constant(N, -2147483648, wide=True)),
    ("+1", ANY, Constant(N, 1)),
    ("1.5", ANY, Constant(F, 1.5)),
    ("3.4028235E+38", ANY, Constant(F, 3.4028235e38)),
    ("FFFFFFFFh", ANY, Constant(H, 0xFFFFFFFF, wide=True)),
    ("DH", ANY, Constant(H, 0xD)),
    ('"AB"', ANY, Constant(T, "AB")),
    ('"' + "A" * 128 + '"', ANY, Constant(T, "A" * 128)),
    ("$0d", ANY, Constant(C, 0x0D)),
    # digits only, 0 to 32767
    ("007", DIGITS, Constant(N, 7)),
    ("32767", DIGITS, Constant(N, 32767)),
    ("0000000000000000000000005", DIGITS, Constant(N, 5)),
    # a counter: '-' leads, 12 characters at most
    ("-5", COUNTER, Constant(N, -5)),
    ("000000000005", COUNTER, Constant(N, 5)),
    ("-2147483648", COUNTER, Constant(N, -2147483648, wide=True)),
    # Compare: 16-bit hex, and a real that rounds to float32's largest value
    ("FFFFh", COMPARE, Constant(H, 0xFFFF)),
    ("000000001h", COMPARE, Constant(H, 1)),
    ("3.4028235E+38", COMPARE, Constant(F, 3.4028235e38)),
    ("-3.4028235E+38", COMPARE, Constant(F, -3.4028235e38)),
    # a Fill into TXT
    ('"A"', ONE_CHAR, Constant(T, "A")),
    ("$41", ONE_CHAR, Constant(C, 0x41)),
    # a remote hex address: 0h to FFFEh
    ("0H", Constants(frozenset({H}), hex_high=0xFFFE), Constant(H, 0)),
    ("0FFFEh", Constants(frozenset({H}), hex_high=0xFFFE), Constant(H, 0xFFFE)),
]


@pytest.mark.parametrize(("value", "constants", "expected"), ACCEPTED)
def test_check_constant_accepts(value: str, constants: Constants, expected: Constant) -> None:
    assert check_constant(value, "X.f", constants) == expected


@pytest.mark.parametrize("value", ["3.4028236E+38", "3.5E+38", "-3.5E+38", "1E39", "1E999"])
def test_a_real_beyond_float32_carries_the_fields_id(value: str) -> None:
    """A real that float32 can't hold is refused with the field's ``real_id``, and with no
    id where the field gives none."""
    with pytest.raises(FieldError, match="within float32") as caught:
        check_constant(value, "X.f", COMPARE)
    assert caught.value.click_id == "OBJ-005"
    with pytest.raises(FieldError, match="within float32") as caught:
        check_constant(value, "X.f", ANY)
    assert caught.value.click_id is None


REFUSED: list[tuple[str, Constants, str]] = [
    # what classify() refuses, whatever the field
    ("", ANY, "is blank"),
    ("2147483648", ANY, "-2147483648 to 2147483647"),
    ("+1h", ANY, "has no sign"),
    ("100000000h", ANY, "is above FFFFFFFFh; a hex constant here is 0h to FFFFFFFFh (OBJ-005)"),
    ("0FFFFFFFFh", ANY, "a hex constant above FFFFh has at most 8 digits"),
    ("3.5E+38", ANY, "float32"),
    ('""', ANY, "1 to 128 characters"),
    ('"a"b"', ANY, "holds a quote with other characters"),
    ("$1", ANY, "two hex digits"),
    ("$100", ANY, "two hex digits"),
    ("nan", ANY, "not a constant"),
    ("٣", ANY, "not a constant"),
    (" 5", ANY, "not a constant"),
    # a kind the field does not take
    ("1.5", DIGITS, "is a real; X.f takes a decimal integer"),
    ("FFh", DIGITS, "is a hex value"),
    ('"A"', DIGITS, "is quoted text"),
    ("$41", DIGITS, "is a $hh character code"),
    ("5", ONE_CHAR, "takes quoted text, a $hh character code"),
    # signs
    ("+1", DIGITS, "takes no sign"),
    ("-0", DIGITS, "takes no sign"),
    ("+1", COUNTER, "takes no plus sign (OBJ-005)"),
    # limits
    ("32768", DIGITS, "outside 0 to 32767"),
    ("0", Constants(frozenset({N}), signs="", low=1, high=32767), "outside 1 to 32767"),
    # An integer beyond int32 is refused by the field's own kind, sign rule or limits. The
    # low limit in the message is 0 when the field accepts no '-'.
    ("3000000000", DIGITS, "outside 0 to 32767 (OBJ-005)"),
    ("-3000000000", COUNTER, "outside -2147483648 to 2147483647 (OBJ-005)"),
    ("3000000000", Constants(frozenset({N}), signs="", low=0, high=2**31 - 1), "outside 0 to"),
    ("3000000000", Constants(frozenset({H})), "is a decimal integer; X.f takes a hex value"),
    ("-3000000000", Constants(frozenset({N}), signs=""), "takes no sign"),
    ("+3000000000", COUNTER, "takes no plus sign (OBJ-005)"),
    ("10000h", COMPARE, "above FFFFh"),
    ("FFFFh", Constants(frozenset({H}), hex_high=0xFFFE), "above FFFEh"),
    ("0000000000005", COUNTER, "13 characters"),
    ('"AB"', ONE_CHAR, "takes one character"),
    ('"A' + "B" * 128 + '"', ONE_CHAR, "a text constant is one character in quotes"),
    ('"ABC"', Constants(frozenset({T}), text_max=2), "at most 2"),
    ('"é"', ANY, "printable ASCII"),
]


@pytest.mark.parametrize(("value", "constants", "message"), REFUSED)
def test_check_constant_refuses(value: str, constants: Constants, message: str) -> None:
    with pytest.raises(FieldError, match=f"^X.f: .*{re.escape(message)}") as caught:
        check_constant(value, "X.f", constants)
    assert type(caught.value) is FieldError
    assert caught.value.field == "X.f"


#: Constants that the field refuses, with the exact message. Each message states the
#: field's own rule.
REFUSED_EXACT: list[tuple[str, Constants, str]] = [
    # A field of decimal integers only refuses a real beyond float32 with the same message
    # as 1.5.
    ("1.5", DIGITS, "X.f: 1.5 is a real; X.f takes a decimal integer"),
    ("3.5E+38", DIGITS, "X.f: 3.5E+38 is a real; X.f takes a decimal integer"),
    ("123456789h", DIGITS, "X.f: 123456789h is a hex value; X.f takes a decimal integer"),
    ("$G1", DIGITS, "X.f: '$G1' is refused; X.f takes a decimal integer"),
    ('"A"b"', DIGITS, "X.f: '\"A\"b\"' is quoted text; X.f takes a decimal integer"),
    ("$G1", COUNTER, "X.f: '$G1' is refused; X.f takes a decimal integer"),
    ("$G1", HEX_REMOTE, "X.f: '$G1' is refused; X.f takes a hex value"),
    ("100000000h", COMPARE, "X.f: 100000000h is above FFFFh; a hex constant here is 0h to FFFFh (OBJ-005)"),
    ("1 2", DIGITS, "X.f: '1 2' is refused; X.f takes a decimal integer"),
    # A hex field accepts any number of leading zeros on a value within its range. It
    # refuses a sign, and text that is not hex digits then h.
    ("h", HEX_REMOTE, "X.f: 'h' is refused; X.f takes a hex value: hex digits then h"),
    ("+1h", HEX_REMOTE, "X.f: +1h is refused; a hex constant has no sign"),
    ("-1h", HEX_REMOTE, "X.f: -1h is refused; a hex constant has no sign"),
    ("100000000h", HEX_REMOTE, "X.f: 100000000h is above FFFEh; a hex constant here is 0h to FFFEh (OBJ-005)"),
    ("5", HEX_REMOTE, "X.f: 5 is a decimal integer; X.f takes a hex value"),
    # a sign the field does not take
    ("+1", COUNTER, "X.f: +1 is refused; a constant here takes no plus sign (OBJ-005)"),
    ("+1", DIGITS, "X.f: +1 is refused; a constant here takes no sign (OBJ-005)"),
    ("-1", Constants(frozenset({N}), signs="+"), "X.f: -1 is refused; a constant here takes no minus sign (OBJ-005)"),
    # a Fill into TXT takes one character, a Compare text up to 128
    ('"' + "A" * 129 + '"', ONE_CHAR, "X.f: \"" + "A" * 129 + "\" is refused; a text constant is one character in quotes, with no quote inside (write the quote character as $22)"),
]  # fmt: skip


@pytest.mark.parametrize(("value", "constants", "message"), REFUSED_EXACT)
def test_check_constant_words_the_fields_own_rule(
    value: str, constants: Constants, message: str
) -> None:
    with pytest.raises(FieldError) as caught:
        check_constant(value, "X.f", constants)
    assert str(caught.value) == message
    assert caught.value.field == "X.f"


def test_a_padded_hex_constant_within_the_fields_range_is_accepted() -> None:
    assert check_constant("000000001h", "X.f", HEX_REMOTE) == Constant(H, 1)


def test_text_outside_printable_ascii_passes_when_the_field_allows_it() -> None:
    assert check_constant('"é"', "X.f", Constants(ALL_KINDS, printable=False)) == Constant(T, "é")


@pytest.mark.parametrize(("value", "code"), [("$1", 1), ("$D", 13), ("$d", 13), ("$41", 0x41)])
def test_a_one_digit_code_is_a_char_where_the_field_takes_it(value: str, code: int) -> None:
    one_digit = Constants(ALL_KINDS, one_digit_char=True)
    assert check_constant(value, "X.f", one_digit) == Constant(C, code)


@pytest.mark.parametrize("value", ["$", "$G", "$100", "$٣"])
def test_a_field_taking_one_digit_codes_refuses_other_dollar_forms(value: str) -> None:
    one_digit = Constants(ALL_KINDS, one_digit_char=True)
    with pytest.raises(FieldError, match=r"\$ and one or two hex digits, \$0 to \$FF"):
        check_constant(value, "X.f", one_digit)


# ---------------------------------------------------------------------------
# check_operand
# ---------------------------------------------------------------------------

REGISTERS = frozenset({"DS", "DD", "DH", "DF", "XD", "YD", "TD", "CTD", "SD", "TXT"})

OPERANDS: list[tuple[str, dict, Operand]] = [
    ("DS1", {}, Operand("DS", Address("DS", 1))),
    ("XD0u", {"banks": REGISTERS}, Operand("XD", Address("XD", 0, upper=True))),
    ("5", {"banks": {"DS"}, "constants": DIGITS}, Operand(constant=Constant(N, 5))),
    ("DS2", {"banks": {"DS"}, "constants": DIGITS}, Operand("DS", Address("DS", 2))),
    (
        "DD[DS1]",
        {"banks": REGISTERS, "pointer": True},
        Operand("DD", index=Address("DS", 1)),
    ),
    ('"A"', {"banks": REGISTERS, "constants": ANY}, Operand(constant=Constant(T, "A"))),
    ("DH", {"banks": REGISTERS, "constants": ANY}, Operand(constant=Constant(H, 0xD))),
    ("-5", {"banks": {"DS"}, "constants": COUNTER, "letter_first": True}, Operand(constant=Constant(N, -5))),
]  # fmt: skip


@pytest.mark.parametrize(("value", "kwargs", "expected"), OPERANDS)
def test_check_operand_accepts(value: str, kwargs: dict, expected: Operand) -> None:
    assert check_operand(value, "X.f", **kwargs) == expected


#: Each case is (value, kwargs, error class, message). The error class shows which check
#: read the text: FieldError for the constant check, AddressError for the address check.
OPERANDS_REFUSED: list[tuple[str, dict, type[FieldError], str]] = [
    # By default, text spelled as a constant the field takes is a constant ...
    ("40000", {"banks": {"DS"}, "constants": DIGITS}, FieldError, "outside 0 to 32767"),
    ("2147483648", {"constants": ANY}, FieldError, "-2147483648 to 2147483647"),
    ("$1", {"constants": ANY}, FieldError, "two hex digits"),
    ('"a"b"', {"constants": ANY}, FieldError, "holds a quote with other characters"),
    # ... and any other text an address. A field of whole numbers names the kind of another
    # constant and says what to write.
    ("+1", {"banks": {"DS"}, "constants": DIGITS}, AddressError, "+1 has a plus sign. Write a whole number from 0 to 32767, or a DS address, such as DS1."),
    ("1.5", {"banks": {"DS"}, "constants": DIGITS}, AddressError, "1.5 is not a whole number. Write a whole number from 0 to 32767, or a DS address, such as DS1."),
    ("$41", {"banks": {"DS"}, "constants": DIGITS}, AddressError, "'$41' is text"),
    ("FFh", {"banks": {"DS"}, "constants": DIGITS}, AddressError, "FFh is a hex value. Write a whole number"),
    ("5.0", {"banks": {"DS"}, "constants": DIGITS}, AddressError, "5.0 is a real. Write a whole number"),
    ("-0", {"banks": {"DS"}, "constants": DIGITS}, AddressError, "-0 has a minus sign. Write a whole number"),
    ('"A"', {"banks": {"DS"}, "constants": DIGITS}, AddressError, '"A" is quoted text. Write a whole number'),
    ("DH", {"banks": {"DS"}, "constants": DIGITS}, AddressError, "'DH' is not a CLICK address"),
    ("-5", {"banks": {"TD", "DD"}, "constants": DIGITS}, AddressError, "or an address in DD or TD, such as DD1."),
    ("-5", {"constants": DIGITS}, AddressError, "or an address, such as DS1."),
    ("0x10", {"banks": {"DS"}, "constants": DIGITS}, AddressError, "'0x10' is not a CLICK address"),
    ("", {"banks": {"DS"}, "constants": DIGITS}, AddressError, "is blank"),
    ("DD1", {"banks": {"DS"}, "constants": DIGITS}, AddressError, "takes DS"),
    ("1,5", {"constants": ANY}, AddressError, "not a CLICK address"),
    ("nan", {"constants": ANY}, AddressError, "not a CLICK address"),
    # A sign before hex digits makes the text an address, unless hex_sign is set. With
    # hex_sign the text is read, and refused, as a constant.
    ("+1h", {"constants": COMPARE}, AddressError, "not a CLICK address"),
    ("+1h", {"constants": Constants(ALL_KINDS, hex_sign=True)}, FieldError, "has no sign"),
    # With letter_first, text that starts with a letter is an address, other text a constant.
    ("FFFFh", {"banks": {"DS"}, "constants": COUNTER, "letter_first": True}, AddressError, "not a CLICK address"),
    ("+1", {"banks": {"DS"}, "constants": COUNTER, "letter_first": True}, FieldError, "takes no plus sign"),
    ("1.5", {"banks": {"DS"}, "constants": COUNTER, "letter_first": True}, FieldError, "is a real"),
    ("", {"banks": {"DS"}, "constants": COUNTER, "letter_first": True}, FieldError, "is blank"),
    (" DS1", {"banks": {"DS"}, "constants": COUNTER, "letter_first": True}, FieldError, "X.f takes a decimal integer"),
    # Without constants, every text is an address.
    ("5", {"banks": {"DS"}}, AddressError, "not a CLICK address"),
    # Pointers
    ("DS[DS1]", {"banks": {"DS"}}, AddressError, "is a pointer; only a single Copy takes one. Write an address, such as DS1."),
    ("DS[DS1]", {"banks": {"TD", "DD"}}, AddressError, "Write an address, such as DD1."),
    ("X[DS1]", {"banks": {"X", "C"}}, AddressError, "Write an address, such as X001."),
    ("Y[DS1]", {"pointer": True}, AddressError, "a pointer in X.f addresses C, DS"),
    ("DS[DS1]", {"banks": {"DD"}, "pointer": True}, AddressError, "addresses DD"),
]  # fmt: skip


@pytest.mark.parametrize(("value", "kwargs", "error", "message"), OPERANDS_REFUSED)
def test_check_operand_refuses(
    value: str, kwargs: dict, error: type[FieldError], message: str
) -> None:
    with pytest.raises(FieldError, match=re.escape(message)) as caught:
        check_operand(value, "X.f", **kwargs)
    assert type(caught.value) is error
    assert caught.value.field == "X.f"


@pytest.mark.parametrize(
    ("value", "message", "field"),
    [
        ("DS[DD1]", "X.f pointer: 'DD1' is not allowed", "X.f"),
        ("DS[DS0]", "X.f pointer: 'DS0' is outside DS1-DS4500", "X.f"),
    ],
)
def test_pointer_index_is_refused_as_a_pointer(value: str, message: str, field: str) -> None:
    with pytest.raises(AddressError, match=re.escape(message)) as caught:
        check_operand(value, "X.f", pointer=True)
    assert caught.value.field == field
    assert caught.value.reason == "pointer"


def test_pointer_banks() -> None:
    assert frozenset({"C", "DS", "DD", "DH", "DF", "XD", "YD", "TD", "CTD", "TXT"}) == POINTER_BANKS


# ---------------------------------------------------------------------------
# check_out_target
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "kwargs", "expected"),
    [
        ("Y001", {}, Address("Y", 1)),
        ("C2000", {}, Address("C", 2000)),
        ("SC50", {}, Address("SC", 50)),
        ("SC326", {}, Address("SC", 326)),
        ("Y816", {"immediate": True}, Address("Y", 816)),
        ("C1", {"banks": {"Y", "C"}}, Address("C", 1)),
    ],
)
def test_check_out_target_accepts(value: str, kwargs: dict, expected: Address) -> None:
    assert check_out_target(value, "X.f", **kwargs) == expected


@pytest.mark.parametrize(
    ("value", "kwargs", "error", "message"),
    [
        ("X001", {}, AddressError, "takes Y, C, SC"),
        ("DS1", {}, AddressError, "takes Y, C, SC"),
        ("SC1", {}, AddressError, "not a writable SC bit"),
        ("SC52", {}, AddressError, "not a writable SC bit"),
        ("C1", {"immediate": True}, FieldError, "an immediate coil takes Y only"),
        # The immediate check runs first, so an immediate SC target is refused whatever its
        # number.
        ("SC1", {"immediate": True}, FieldError, "an immediate coil takes Y only"),
        ("SC50", {"banks": {"Y", "C"}}, AddressError, "takes Y, C"),
    ],
)
def test_check_out_target_refuses(
    value: str, kwargs: dict, error: type[FieldError], message: str
) -> None:
    with pytest.raises(FieldError, match=message) as caught:
        check_out_target(value, "X.f", **kwargs)
    assert type(caught.value) is error
    assert caught.value.field == "X.f"


def test_writable_sc_bits() -> None:
    assert len(WRITABLE_SC) == 25
    assert min(WRITABLE_SC) == 50 and max(WRITABLE_SC) == 326


def test_writable_sd_registers() -> None:
    assert len(WRITABLE_SD) == 29
    assert min(WRITABLE_SD) == 29 and max(WRITABLE_SD) == 215


@pytest.mark.parametrize("address", [Address("SD", 29), Address("SD", 215), Address("DS", 1)])
def test_check_writable_sd_passes(address: Address) -> None:
    check_writable_sd(address, "X.f")


def test_check_writable_sd_refuses() -> None:
    with pytest.raises(
        AddressError, match=r"^X.f: 'SD43' is not a writable SD register; "
    ) as caught:
        check_writable_sd(Address("SD", 43), "X.f", click_id="OBJ-004")
    assert (caught.value.field, caught.value.reason, caught.value.click_id) == (
        "X.f",
        "not_writable",
        "OBJ-004",
    )
    assert str(caught.value).endswith("SD214, SD215 (OBJ-004)")


# ---------------------------------------------------------------------------
# check_flag
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"), [(True, True), (False, False), (1, True), (0, False)]
)
def test_check_flag_accepts(value: object, expected: bool) -> None:
    assert check_flag(value, "X.f") is expected


@pytest.mark.parametrize("value", [2, -1, "1", "True", None, 1.0, []])
def test_check_flag_refuses(value: object) -> None:
    with pytest.raises(
        FieldError, match=r"^X.f: .* is not True, False, 1 or 0\. Pass True or False\.$"
    ) as caught:
        check_flag(value, "X.f")
    assert caught.value.field == "X.f"


def test_model_reexports_check_flag() -> None:
    assert model_check_flag is check_flag
