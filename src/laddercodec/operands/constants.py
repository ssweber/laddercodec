"""Constants as CLICK's shared input check reads them.

A dialog field that takes a constant first runs its text through one check shared by every
instruction dialog, then applies its own limits.
:func:`classify` reads text the same way: it says which kind of constant the text is and
returns its value.  It applies no field's limits: a set point's 0 to 32767, the hex
constants a Copy puts in DD only, the printable-ASCII text of a Compare (:func:`printable`),
or which kinds a field takes at all belong to the field.

The shared check works on an uppercase copy of the text, so ``ffffh``, ``$0d`` and ``1e5``
are constants.  It tries, in order:

- hex: hex digits then ``H``.  At most FFFFh is 16-bit; above that, at most eight digits
  is 32-bit (:attr:`Constant.wide`); longer text is no constant.  Hex comes before an
  address, so ``DH``, ``EH`` and ``ABCH`` are hex constants (a single Copy refuses ``EH``
  and ``1EH``, which CLICK's Copy stores as the reals 0.0 and 1.0).
- text: ``"..."``, the text between the quotes (see :data:`TEXT_MAX`).
- an address, which is no constant (:func:`classify` returns ``None``).
- a decimal integer: an int16 value, or an int32 value (wide); outside int32, no constant.
- a floating-point number (text with ``.`` or ``E``).
- a character code ``$hh``.

:func:`parse_digits` is the digits-only test several dialogs make instead (a Timer set point,
an Out variant preset, a For count).
"""

from __future__ import annotations

import math
import re
import struct
from enum import StrEnum
from typing import NamedTuple

from .errors import FieldError, Reason


class Kind(StrEnum):
    """The kind of a constant."""

    INTEGER = "integer"  #: a decimal integer: ``42``, ``-7``, ``+1``, ``007``
    FLOAT = "float"  #: a floating-point number: ``1.5``, ``.5``, ``1E5``, ``-1.5e-3``
    HEX = "hex"  #: hex digits then ``h``: ``FFFFh``, ``0h``
    #: Quoted text: ``"AB"``; the value is the text between the quotes.  ``"$41"`` is the
    #: three characters ``$41`` (a quoted ``$hh`` is literal text).
    TEXT = "text"
    CHAR = "char"  #: a character by code: ``$41``; the value is the code


class Constant(NamedTuple):
    """A constant read by :func:`classify`."""

    kind: Kind
    value: int | float | str
    #: An integer outside int16 (-32768 to 32767), or a hex constant above FFFFh: the 32-bit
    #: form of the kind, which some fields refuse.
    wide: bool = False


#: The int16 and int32 bounds of a decimal integer.
INT16_MIN, INT16_MAX = -(2**15), 2**15 - 1
INT32_MIN, INT32_MAX = -(2**31), 2**31 - 1
#: The highest 16-bit hex constant, and the most digits a 32-bit one has.
HEX16_MAX = 0xFFFF
HEX32_DIGITS = 8

#: The most characters between the quotes of a text constant.  The shared check takes at
#: most 130 characters, quotes included, and any character.
TEXT_MAX = 128
#: The characters :func:`printable` allows: printable ASCII, 0x20 to 0x7E.
PRINTABLE_ASCII = frozenset(chr(c) for c in range(0x20, 0x7F))

_HEX_RE = re.compile(r"([0-9A-F]+)H")
_INTEGER_RE = re.compile(r"([+-]?)([0-9]+)")
# The shared check sends text holding ``.``, ``E`` or ``,`` to its floating-point test.  A
# comma is refused here: what that test does with one is not known, and a comma separates
# CSV arguments.
_FLOAT_RE = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:E[+-]?[0-9]+)?")
# The shared check also takes ``$1`` as a character code, and a ``$`` value above FF as a
# second kind.  A code is picked from CLICK's Embed ASCII Code table, ``$00`` to ``$FF``,
# so only ``$`` and two hex digits is one.
_CHAR_RE = re.compile(r"\$([0-9A-F]{2})")
_DIGITS_RE = re.compile(r"[0-9]+")
#: More significant digits than any CLICK limit needs (int() refuses very long text).
_MAX_DIGITS = 20


def classify(text: str) -> Constant | None:
    """Return the constant ``text`` spells, or ``None`` if it is no constant.

    ``None`` covers an empty text, an address, a value outside its kind and anything else the
    shared check refuses.  A value outside its kind is an integer outside int32, hex longer
    than eight digits, or a float that is not finite or above the float32 range.  Only ASCII
    digits count: ``٣`` is no digit.  No space is trimmed; a field
    that strips its text does so first.
    """
    if len(text) >= 2 and text[0] == text[-1] == '"':
        # Quoted text can't end in H, so trying it before hex changes no result.
        return _text(text[1:-1])
    if not text or not text.isascii():
        return None
    upper = text.upper()
    m = _HEX_RE.fullmatch(upper)
    if m is not None:
        return _hex(m.group(1))
    m = _INTEGER_RE.fullmatch(upper)
    if m is not None:
        return _integer(m.group(1), m.group(2))
    if _FLOAT_RE.fullmatch(upper):
        value = float(upper)
        return Constant(Kind.FLOAT, value) if fits_float32(value) else None
    m = _CHAR_RE.fullmatch(upper)
    if m is not None:
        return Constant(Kind.CHAR, int(m.group(1), 16))
    return None


#: The table banks a Search value of each kind searches (dialog): a
#: decimal integer or a real the integer and real banks, a hex value DH, text or a character
#: code TXT.
SEARCH_TABLE_BANKS: dict[Kind, frozenset[str]] = {
    Kind.INTEGER: frozenset({"DS", "DD", "DF", "TD", "CTD"}),
    Kind.FLOAT: frozenset({"DS", "DD", "DF", "TD", "CTD"}),
    Kind.HEX: frozenset({"DH"}),
    Kind.TEXT: frozenset({"TXT"}),
    Kind.CHAR: frozenset({"TXT"}),
}


def fits_float32(value: float) -> bool:
    """Whether ``value`` is finite and fits float32.

    A value that rounds to float32's largest finite number, about 3.4028235E+38, fits.
    """
    if not math.isfinite(value):
        return False
    try:
        struct.pack("<f", value)
    except OverflowError:
        return False
    return True


def hex_display(digits: str) -> str:
    """CLICK's form of a hex value: uppercase digits without leading zeros, then ``h``.

    ``0000Fh`` is stored ``Fh``, ``ffeh`` is ``FFEh`` and zero is ``0h``.
    """
    return f"{digits.upper().lstrip('0') or '0'}h"


#: The significant digits CLICK prints a real constant with.
REAL_DIGITS = 7


def real_display(text: str) -> str:
    """A real constant as laddercodec writes it: its value printed back, a typed ``+`` kept.

    CLICK stores a real in a Math and a Copy source as it prints it back: ``1.50`` is
    ``1.5``, ``.5`` is ``0.5``, ``1e3`` is ``1000.0``, ``1E5`` is ``100000.0``, and a typed
    ``+2.5`` stays.  laddercodec prints with 7 significant digits, positional with at least
    one digit after the point, as those answers do; the digit count and the rest are
    laddercodec's until CLICK answers.  ``text`` comes back as given where that print is
    another float32 value (more than 7 significant digits that count), and where 7 digits
    print it in exponent form, from 1E+07 up and below 1E-04: CLICK keeps ``1.5E+10`` as
    typed, and its form for the rest is not known.  ``text`` is a real :func:`classify`
    reads: finite and within float32.
    """
    value = float(text)
    printed = f"{value:.{REAL_DIGITS}G}"
    if "E" in printed:
        return text
    if "." not in printed:
        printed += ".0"
    if struct.pack("<f", float(printed)) != struct.pack("<f", value):
        return text
    return f"+{printed}" if text.startswith("+") else printed


def copy_real_display(text: str) -> str:
    """A real constant as a single Copy source stores it.

    As :func:`real_display`, with two differences CLICK's Copy answers show: a typed ``+``
    is dropped (``+1.5`` is ``1.5``), and a real typed in exponent form whose float32 value
    7 significant digits print in exponent form, but not exactly, is written in that print
    (``3.4028235E+38`` is ``3.402823E+38``, a slightly smaller float32 value).  One that 7
    digits print exactly is kept as typed (``1E-45``, ``1E-50``); CLICK's form for one typed
    otherwise (``1e7``, ``1.0E-10``) is not known.  ``text`` is a real :func:`classify`
    reads: finite and within float32.
    """
    text = text.removeprefix("+")
    value = _float32(float(text))
    printed = f"{value:.{REAL_DIGITS}G}"
    if "E" in text.upper() and "E" in printed and _float32(float(printed)) != value:
        return printed
    return real_display(text)


def _float32(value: float) -> float:
    """The float32 value nearest ``value``, which is within float32."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


#: The largest finite float32 value.
_FLOAT32_MAX = struct.unpack("<f", b"\xff\xff\x7f\x7f")[0]
#: Enough significant digits to write any float32 value at or below its exact value.
_REAL_DIGITS_MAX = 17


def constant_text(value: int | float | str, *, hex: bool = False) -> str:
    """Write a Python value as the constant text a Math or a Copy source takes.

    The text is the one building the instruction stores for that value:

    - an ``int`` is a decimal integer, -2147483648 to 2147483647 (``-7``), or with
      ``hex=True`` hex digits then ``h``, 0h to FFFFFFFFh (``255`` is ``FFh``);
    - a ``float`` is the float32 value nearest it, in the fewest significant digits that
      read back as that value and stay within float32, printed as laddercodec prints a real
      (``1000.0``, ``0.5``);
    - a ``str`` is a text constant in quotes (``"AB"``); one character outside printable
      ASCII is its code, ``$`` and two hex digits (``$0D``).

    The text builds a Math or a single Copy holding that value, but for one kind of real: a
    Copy writes a real in exponent form that 7 significant digits don't print exactly in
    CLICK's 7 digits, which is not the value.  The largest float32 value is
    ``3.402823466E+38``, which a Copy stores as ``3.402823E+38``, a slightly smaller value.

    Provisional until CLICK answers: a real that 7 significant digits print in exponent
    form (from 1E+07 up and below 1E-04) is written in Python's ``G`` form (``1.5E+10``),
    and one that needs more than 7 digits keeps them (``0.33333334``); how CLICK writes
    either in a Math is not known.

    Whether a field takes the text (an int above int16, a hex value above FFFFh, a real in
    a hex Math) is the field's check, made when the instruction is built.  A value no
    constant spells raises ``ValueError``: an int outside the ranges above, a real that is
    not finite or is outside the float32 range, empty text, text with a quote or longer
    than 128 characters, or a character above ``$FF``.  A ``bool``, a float with
    ``hex=True`` or any other type raises ``TypeError``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{value!r} is not an int, a float or a str")
    if isinstance(value, str):
        return _text_constant(value)
    if hex:
        if not isinstance(value, int):
            raise TypeError(f"{value!r} is not an int; a hex constant is a whole number")
        if not 0 <= value < 16**HEX32_DIGITS:
            raise ValueError(f"{value} is outside 0h..FFFFFFFFh, the hex constants")
        return hex_display(f"{value:X}")
    if isinstance(value, int):
        if not INT32_MIN <= value <= INT32_MAX:
            raise ValueError(f"{value} is outside {INT32_MIN}..{INT32_MAX}, the integer constants")
        return str(value)
    if not fits_float32(value):
        raise ValueError(f"{value!r} is not a finite float32 value")
    # The float32 value nearest, then the fewest digits that read back as it.  A rounded
    # print above the largest float32 value is skipped, though it may round back to it.
    nearest = struct.unpack("<f", struct.pack("<f", value))[0]
    text = repr(nearest)
    for digits in range(1, _REAL_DIGITS_MAX + 1):
        candidate = f"{nearest:.{digits}G}"
        if abs(float(candidate)) > _FLOAT32_MAX:
            continue
        if struct.unpack("<f", struct.pack("<f", float(candidate)))[0] == nearest:
            text = candidate
            break
    if "." not in text and "E" not in text:
        text += ".0"  # a real, not an integer
    return real_display(text)


def _text_constant(value: str) -> str:
    if len(value) == 1 and not printable(value):
        if ord(value) > 0xFF:
            raise ValueError(f"{value!r} is above $FF; a character code is $00 to $FF")
        return f"${ord(value):02X}"
    if not 1 <= len(value) <= TEXT_MAX or '"' in value:
        raise ValueError(
            f"{value!r} is no text constant: 1 to {TEXT_MAX} characters, with no quote "
            "($22 spells one)"
        )
    return f'"{value}"'


def _text(inner: str) -> Constant | None:
    # A quote inside the text is refused: the CSV token can't hold one ($22 spells it).
    if not 1 <= len(inner) <= TEXT_MAX or '"' in inner:
        return None
    return Constant(Kind.TEXT, inner)


def printable(text: str) -> bool:
    """Whether ``text`` is printable ASCII only.

    Not part of the shared check, which takes any character: a field limit.  A Compare text
    constant, a Search text value and the text of a single Copy or a Fill hold printable
    ASCII only; ``$hh`` spells any other code.
    """
    return PRINTABLE_ASCII.issuperset(text)


#: Why a ``$`` value is refused; :func:`check_char_code` raises it in every field.
CHAR_CODE_RULE = "a character code is $ and two hex digits, $00 to $FF, such as $41"


def check_char_code(text: str, field: str) -> int:
    """Return the code ``text`` spells as ``$hh``; raise :class:`FieldError` naming
    ``field`` for any other text.

    A code is picked from CLICK's Embed ASCII Code table, ``$00`` to ``$FF``, so ``$``, ``$1``,
    ``$100`` and ``$G1`` are refused.  Compare, Search, Fill, a single Copy source and a Copy
    termination code call it on every ``$`` value; a single Copy writes a source ``$1`` as
    ``$01`` first, as CLICK stores it.
    """
    m = _CHAR_RE.fullmatch(text.upper()) if text.isascii() else None
    if m is None:
        raise FieldError(
            f"{field}: {text!r} is refused; {CHAR_CODE_RULE}", field=field, reason=Reason.FORM
        )
    return int(m.group(1), 16)


def _hex(digits: str) -> Constant | None:
    # 16-bit by value, so 0FFFFh is 16-bit; 32-bit by digit count, so 0FFFFFFFFh is none.
    significant = digits.lstrip("0") or "0"
    if len(significant) <= 4:
        return Constant(Kind.HEX, int(significant, 16))
    if len(digits) > HEX32_DIGITS:
        return None
    return Constant(Kind.HEX, int(significant, 16), wide=True)


def _integer(sign: str, digits: str) -> Constant | None:
    # The shared check lets a sign stand anywhere among the digits.  The dialog
    # check found ``1-2`` refused in the Counter dialog, whose own parse runs
    # after it; the classifier extends that to every field, so a sign only leads.
    significant = digits.lstrip("0") or "0"
    if len(significant) > len(str(INT32_MAX)):
        return None
    value = int(sign + significant)
    if INT16_MIN <= value <= INT16_MAX:
        return Constant(Kind.INTEGER, value)
    if INT32_MIN <= value <= INT32_MAX:
        return Constant(Kind.INTEGER, value, wide=True)
    return None


def parse_digits(text: str) -> int | None:
    """Return the value of text that is ASCII digits only, or ``None``.

    The digits-only test of a Timer set point, an Out variant preset and a For count: no
    sign, no space, no decimal point.  A drum duration goes through the shared check's int16
    kind with no sign allowed, which accepts the same text.  Leading zeros are allowed
    (``007`` is 7).  Text with more than 20 significant digits is ``None``; every limit those
    fields have is far below it.
    """
    if not _DIGITS_RE.fullmatch(text):
        return None
    significant = text.lstrip("0") or "0"
    if len(significant) > _MAX_DIGITS:
        return None
    return int(significant)
