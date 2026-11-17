"""Read constants the way CLICK's shared input check reads them.

Every instruction dialog runs the text of a constant field through one shared check, and
then applies the field's own limits.  :func:`classify` reads text the same way as the
shared check.  It returns the kind of constant that the text is, and its value.  It applies
no field's limits.  These belong to the field: a preset's 0 to 32767, the hex constants
that a Copy puts only in DD, the printable-ASCII text of a Compare (:func:`printable`), and
which kinds of constant the field takes at all.

The shared check works on an uppercase copy of the text, so ``ffffh``, ``$0d`` and ``1e5``
are constants.  It tries these forms in order:

- Hex: hex digits then ``H``.  A value up to FFFFh is 16-bit.  Above that, hex of at most
  eight digits is 32-bit (:attr:`Constant.wide`), and longer text is no constant.  Hex
  comes before an address, so ``DH``, ``EH`` and ``ABCH`` are hex constants.  A single
  Copy refuses ``EH`` and ``1EH``.  CLICK's Copy stores them as the reals 0.0 and 1.0.
- Text: ``"..."``.  The value is the text between the quotes (see :data:`TEXT_MAX`).
- An address.  An address is no constant, and :func:`classify` returns ``None``.
- A decimal integer: an int16 value, or an int32 value (wide).  Outside int32 it is no
  constant.
- A floating-point number: text with ``.`` or ``E``.
- A character code ``$hh``.
"""

from __future__ import annotations

import math
import re
import struct
from decimal import Decimal
from enum import StrEnum
from typing import NamedTuple


class Kind(StrEnum):
    """The kind of a constant."""

    INTEGER = "integer"  #: a decimal integer: ``42``, ``-7``, ``+1``, ``007``
    FLOAT = "float"  #: a floating-point number: ``1.5``, ``.5``, ``1E5``, ``-1.5e-3``
    HEX = "hex"  #: hex digits then ``h``: ``FFFFh``, ``0h``
    #: Quoted text: ``"AB"``.  The value is the text between the quotes.  ``"$41"`` is the
    #: three characters ``$41``, because a ``$hh`` inside quotes is literal text.
    TEXT = "text"
    CHAR = "char"  #: a character by code: ``$41``; the value is the code


class Constant(NamedTuple):
    """A constant read by :func:`classify`."""

    kind: Kind
    value: int | float | str
    #: True for an integer outside int16 (-32768 to 32767) or a hex constant above FFFFh.
    #: That is the 32-bit form of the kind, and some fields refuse it.
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
# The shared check sends text holding ``.``, ``E`` or ``,`` to its floating-point test.  This
# pattern refuses a comma for two reasons.  What that test does with a comma is not known, and
# a comma separates CSV arguments.
_FLOAT_RE = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:E[+-]?[0-9]+)?")
# The shared check also takes ``$1`` as a character code, and reads a ``$`` value above FF
# as a second kind of constant.  A user picks a code from CLICK's Embed ASCII Code table,
# ``$00`` to ``$FF``.  This pattern therefore takes only ``$`` and two hex digits as a code.
_CHAR_RE = re.compile(r"\$([0-9A-F]{2})")


def classify(text: str) -> Constant | None:
    """Return the constant ``text`` spells, or ``None`` if it is no constant.

    ``None`` covers an empty text, an address, a value outside its kind and anything else the
    shared check refuses.  A value outside its kind is an integer outside int32, hex above
    FFFFh written with more than eight digits, or a float that is not finite or above the
    float32 range.  Only ASCII digits count: ``٣`` is no digit.  No space is trimmed; a field
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


#: The banks that a Search table may be in, by the kind of the search value, as CLICK's
#: dialog allows them.  A decimal integer or a real searches the integer and real banks.  A
#: hex value searches DH.  Text or a character code searches TXT.
SEARCH_TABLE_BANKS: dict[Kind, frozenset[str]] = {
    Kind.INTEGER: frozenset({"DS", "DD", "DF", "TD", "CTD"}),
    Kind.FLOAT: frozenset({"DS", "DD", "DF", "TD", "CTD"}),
    Kind.HEX: frozenset({"DH"}),
    Kind.TEXT: frozenset({"TXT"}),
    Kind.CHAR: frozenset({"TXT"}),
}


#: The largest finite float32 value, about 3.402823466E+38.
FLOAT32_MAX = struct.unpack("<f", b"\xff\xff\x7f\x7f")[0]


def fits_float32(value: float) -> bool:
    """Return whether ``value`` is finite and fits float32.

    A value that rounds to float32's largest finite number, about 3.4028235E+38, fits.  A
    decimal Math is stricter.  It takes a real only up to :data:`FLOAT32_MAX` in size, so it
    refuses 3.4028235E+38, which fits here.
    """
    if not math.isfinite(value):
        return False
    try:
        struct.pack("<f", value)
    except OverflowError:
        return False
    return True


def hex_display(digits: str) -> str:
    """Return CLICK's form of a hex value: uppercase digits without leading zeros, then ``h``.

    ``0000Fh`` is stored ``Fh``, ``ffeh`` is ``FFEh`` and zero is ``0h``.
    """
    return f"{digits.upper().lstrip('0') or '0'}h"


#: The significant digits CLICK keeps of a real constant in a single Copy source.
REAL_DIGITS = 7
#: The significant digits CLICK keeps of a real constant in a Math formula.
MATH_REAL_DIGITS = 6


def real_display(text: str) -> str:
    """Return the text that laddercodec writes for the real constant ``text``.

    The text is the real's value printed back, and a typed ``+`` stays.  CLICK stores a real
    in a Math and a Copy source the way it prints the real back: ``1.50`` is ``1.5``, ``.5``
    is ``0.5``, ``1e3`` is ``1000.0``, ``1E5`` is ``100000.0``, and a typed ``+2.5`` stays.
    laddercodec prints with 7 significant digits, in positional form, with at least one
    digit after the point, which matches those examples.  The digit count and the other
    details are laddercodec's own choice until CLICK's behaviour is captured.

    ``text`` comes back as given in two cases.  The first is when the 7-digit print is a
    different float32 value, because ``text`` has more than 7 significant digits that
    count.  The second is when 7 digits print the value in exponent form: from 1E+07 up, or
    below 1E-04.  CLICK keeps ``1.5E+10`` as typed, and its form for the other values is
    not known.  ``text`` must be a real that :func:`classify` reads: finite and within
    float32.
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
    """Return the text that a single Copy source stores for the real constant ``text``.

    The text is the one :func:`real_display` returns, with two differences that CLICK's Copy
    shows.  First, a typed ``+`` is dropped: ``+1.5`` is ``1.5``.  Second, a real may be
    typed in exponent form, and 7 significant digits may print its float32 value in
    exponent form but not exactly.  Such a real is written as that print: ``3.4028235E+38``
    is ``3.402823E+38``, a slightly smaller float32 value.  A real that 7 digits print
    exactly is kept as typed, as ``1E-45`` and ``1E-50`` are.  CLICK's form for one typed
    otherwise, such as ``1e7`` or ``1.0E-10``, is not known.  ``text`` must be a real that
    :func:`classify` reads: finite and within float32.  A single Copy refuses a real typed
    with more than 7 significant digits before it calls this function
    (:func:`real_beyond_kept_digits`).
    """
    text = text.removeprefix("+")
    value = _float32(float(text))
    printed = f"{value:.{REAL_DIGITS}G}"
    if "E" in text.upper() and "E" in printed and _float32(float(printed)) != value:
        return printed
    return real_display(text)


def _float32(value: float) -> float:
    """Return the float32 value nearest ``value``.  ``value`` must be within float32."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


_EXPONENT_RE = re.compile(r"[Ee]")
#: Where 7 significant digits print a real in positional form: from 1E-04 to below 1E+07.
_POSITIONAL_FROM, _POSITIONAL_BELOW = 1e-4, 1e7


def significant_digits(text: str) -> int:
    """Return the number of significant digits that a real constant is typed with: its
    digits before any exponent, without leading and trailing zeros.

    ``0.0015`` has 2, ``1.50`` has 2, ``3.4028235E+38`` has 8, ``100000000.0`` has 1.
    Trailing zeros are not counted.  CLICK prints ``1.50`` back as ``1.5``.
    """
    mantissa = _EXPONENT_RE.split(text, maxsplit=1)[0]
    return len("".join(c for c in mantissa if c.isdigit()).strip("0"))


def real_beyond_kept_digits(text: str, digits: int = REAL_DIGITS) -> str | None:
    """Return the real constant ``text`` rounded to ``digits`` significant digits, when it
    is typed with more.  Return None when it is typed with at most that many.

    CLICK keeps 7 significant digits of a real in a single Copy source
    (:data:`REAL_DIGITS`) and 6 in a Math formula (:data:`MATH_REAL_DIGITS`).  It saves
    ``3.4028235E+38`` copied into DF1 as ``3.402823E+38``, and ``0.33333334`` in a Math as
    ``0.333333``.  The text returned is the constant to write instead.  It is the float32
    value printed with ``digits`` significant digits.  From 1E-04 to below 1E+07 the print
    is positional, as :func:`real_display` prints (``1234570.0``).  ``.0`` is added where
    the print has neither a point nor an exponent.  ``text`` must be a real that
    :func:`classify` reads: finite and within float32.
    """
    if significant_digits(text) <= digits:
        return None
    printed = f"{_float32(float(text)):.{digits}G}"
    if "E" in printed and _POSITIONAL_FROM <= abs(float(printed)) < _POSITIONAL_BELOW:
        # Print in positional form from 1E-04 to below 1E+07, as laddercodec prints a real:
        # 1234570.0, not 1.23457E+06.
        printed = format(Decimal(printed), "f")
    if "." not in printed and "E" not in printed:
        printed += ".0"
    return printed


#: The most significant digits that :func:`constant_text` tries for a real.  A shorter text
#: can round up past the largest float32 value, and the search skips it.  At 17 digits, the
#: text reads back as exactly the float32 value, so the search always finds a text.
_REAL_DIGITS_MAX = 17


def constant_text(value: int | float | str, *, hex: bool = False) -> str:
    """Return the constant text for a Python value, as a Math or a Copy source takes it.

    The text is the one that the instruction stores for that value when you build it:

    - an ``int`` is a decimal integer, -2147483648 to 2147483647 (``-7``), or with
      ``hex=True`` hex digits then ``h``, 0h to FFFFFFFFh (``255`` is ``FFh``);
    - a ``float`` is the float32 value nearest it, in the fewest significant digits that
      read back as that value and stay within float32, printed as laddercodec prints a real
      (``1000.0``, ``0.5``);
    - a ``str`` is a text constant in quotes (``"AB"``).  A ``str`` of one character outside
      printable ASCII is that character's code, ``$`` and two hex digits (``$0D``).

    A Math accepts the text for a real of at most 6 significant digits, and a single Copy
    accepts it for a real of at most 7.  CLICK keeps 6 digits in a Math and 7 in a Copy,
    and saves a real with more digits cut to that many.  A Math or a Copy refuses such a
    real, and its message names the constant to write (:func:`real_beyond_kept_digits`).
    The largest float32 value is ``3.402823466E+38``.  Write it as ``3.40282E+38`` in a
    Math and as ``3.402823E+38`` in a Copy.

    Two choices are provisional until CLICK's behaviour is captured.  A real that 7
    significant digits print in exponent form, from 1E+07 up or below 1E-04, is written in
    Python's ``G`` form (``1.5E+10``).  A real that needs more than 7 digits keeps them
    (``0.33333334``).

    When you build the instruction, the field's own check decides whether it takes the
    text, such as an int above int16, a hex value above FFFFh or a real in a hex Math.  This
    function does not check that.  A value that no constant spells raises ``ValueError``:
    an int outside the ranges above, a real that is not finite or is outside the float32
    range, empty text, text with a quote or longer than 128 characters, or a character
    above ``$FF``.  A ``bool``, a float with ``hex=True`` or any other type raises
    ``TypeError``.
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
    # Find the nearest float32 value, then the fewest digits that read back as it.  Skip a
    # rounded print above the largest float32 value, even when it would round back to it.
    nearest = struct.unpack("<f", struct.pack("<f", value))[0]
    text = repr(nearest)
    for digits in range(1, _REAL_DIGITS_MAX + 1):
        candidate = f"{nearest:.{digits}G}"
        if abs(float(candidate)) > FLOAT32_MAX:
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
    """Return whether ``text`` is printable ASCII only.

    This is a limit of some fields, not part of the shared check, which takes any
    character.  A Compare text constant and the text of a Fill hold printable ASCII only,
    and ``$hh`` spells any other code.  A single Copy's text and a Search text value take
    the characters that :func:`kept_text` accepts instead.
    """
    return PRINTABLE_ASCII.issuperset(text)


#: The rule that text breaks when :func:`kept_text` refuses it.
KEPT_TEXT_RULE = "text holds characters U+0001 to U+FFFF, no NUL and no surrogate; write NUL as $00"


def kept_text(text: str) -> bool:
    """Return whether CLICK keeps each character of ``text`` as typed, in one TXT register each.

    CLICK keeps printable ASCII, a tab, a control character (U+0001), Latin-1 (U+00E9) and
    the rest of its 16-bit characters (U+20AC) in a single Copy source and a Search text
    value.  NUL can't be stored, since it ends a stored string, and a surrogate or a
    character above U+FFFF is no 16-bit character.
    """
    return all(0 < ord(c) < 0xD800 or 0xE000 <= ord(c) <= 0xFFFF for c in text)


#: The rule that a refused ``$`` value breaks.  The shared field check puts it in the refusal
#: in every field.
CHAR_CODE_RULE = "a character code is $ and two hex digits, $00 to $FF, such as $41"


def _hex(digits: str) -> Constant | None:
    # The 16-bit limit counts the value, so 0FFFFh is 16-bit.  The 32-bit limit counts the
    # digits, so 0FFFFFFFFh is no constant.
    significant = digits.lstrip("0") or "0"
    if len(significant) <= 4:
        return Constant(Kind.HEX, int(significant, 16))
    if len(digits) > HEX32_DIGITS:
        return None
    return Constant(Kind.HEX, int(significant, 16), wide=True)


def _integer(sign: str, digits: str) -> Constant | None:
    # The shared check lets a sign stand anywhere among the digits.  The Counter
    # dialog refuses ``1-2`` in its own parse, which runs after the shared check.
    # classify() refuses such text in every field, so a sign may only lead.
    significant = digits.lstrip("0") or "0"
    if len(significant) > len(str(INT32_MAX)):
        return None
    value = int(sign + significant)
    if INT16_MIN <= value <= INT16_MAX:
        return Constant(Kind.INTEGER, value)
    if INT32_MIN <= value <= INT32_MAX:
        return Constant(Kind.INTEGER, value, wide=True)
    return None
