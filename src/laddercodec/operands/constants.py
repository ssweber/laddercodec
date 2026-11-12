"""Constants as CLICK's shared input check reads them.

A dialog field that takes a constant first runs its text through one check shared by every
instruction dialog (DLL: baseEx.dll, CheckInputData), then applies its own limits.
:func:`classify` reads text the same way: it says which kind of constant the text is and
returns its value.  It applies no field's limits: a set point's 0 to 32767, the hex
constants a Copy puts in DD only, the printable-ASCII text of a Compare (:func:`printable`),
or which kinds a field takes at all belong to the field.

The shared check works on an uppercase copy of the text, so ``ffffh``, ``$0d`` and ``1e5``
are constants.  It tries, in order:

- hex: hex digits then ``H``.  At most FFFFh is 16-bit; above that, at most eight digits
  is 32-bit (:attr:`Constant.wide`); longer text is no constant.  Hex comes before an
  address, so ``DH``, ``EH`` and ``ABCH`` are hex constants.
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

from .errors import FieldError


class Kind(StrEnum):
    """The kind of a constant."""

    INTEGER = "integer"  #: a decimal integer: ``42``, ``-7``, ``+1``, ``007``
    FLOAT = "float"  #: a floating-point number: ``1.5``, ``.5``, ``1E5``, ``-1.5e-3``
    HEX = "hex"  #: hex digits then ``h``: ``FFFFh``, ``0h``
    #: Quoted text: ``"AB"``; the value is the text between the quotes.  ``"$41"`` is the
    #: three characters ``$41`` (arc.md Q-B7 ruling, 2026-11-11, revised again).
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
# second kind.  A code is picked from CLICK's Embed ASCII Code table, ``$00`` to ``$FF``
# (Help ``ascii table2.gif``), so only ``$`` and two hex digits is one.
_CHAR_RE = re.compile(r"\$([0-9A-F]{2})")
_DIGITS_RE = re.compile(r"[0-9]+")
#: More significant digits than any CLICK limit needs (int() refuses very long text).
_MAX_DIGITS = 20


def classify(text: str) -> Constant | None:
    """Return the constant ``text`` spells, or ``None`` if it is no constant.

    ``None`` covers an empty text, an address, a value outside its kind and anything else the
    shared check refuses.  A value outside its kind is an integer outside int32, hex longer
    than eight digits, or a float that is not finite or above the float32 range.  Only ASCII
    digits count (arc.md ruling 2026-11-11): ``٣`` is no digit.  No space is trimmed; a field
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
        return Constant(Kind.FLOAT, value) if _float32(value) else None
    m = _CHAR_RE.fullmatch(upper)
    if m is not None:
        return Constant(Kind.CHAR, int(m.group(1), 16))
    return None


#: The table banks a Search value of each kind searches (arc.md Q-M21, dialog 2026-11-12): a
#: decimal integer or a real the integer and real banks, a hex value DH, text or a character
#: code TXT.
SEARCH_TABLE_BANKS: dict[Kind, frozenset[str]] = {
    Kind.INTEGER: frozenset({"DS", "DD", "DF", "TD", "CTD"}),
    Kind.FLOAT: frozenset({"DS", "DD", "DF", "TD", "CTD"}),
    Kind.HEX: frozenset({"DH"}),
    Kind.TEXT: frozenset({"TXT"}),
    Kind.CHAR: frozenset({"TXT"}),
}


def _float32(value: float) -> bool:
    """Whether ``value`` is finite and fits float32.

    A value that rounds to float32's largest finite number, about 3.4028235E+38, fits
    (arc.md Q-M17, dialog answer 2026-11-12).
    """
    if not math.isfinite(value):
        return False
    try:
        struct.pack("<f", value)
    except OverflowError:
        return False
    return True


def _text(inner: str) -> Constant | None:
    # A quote inside the text is refused: the CSV token can't hold one ($22 spells it).
    if not 1 <= len(inner) <= TEXT_MAX or '"' in inner:
        return None
    return Constant(Kind.TEXT, inner)


def printable(text: str) -> bool:
    """Whether ``text`` is printable ASCII only.

    Not part of the shared check, which takes any character: a field limit.  A Compare text
    constant (arc.md Q-B7 ruling, 2026-11-11, revised), a Search text value (arc.md Q-M10
    ruling) and the text of a single Copy or a Fill (BOB ruling 2026-11-12) hold printable
    ASCII only; ``$hh`` spells any other code.
    """
    return PRINTABLE_ASCII.issuperset(text)


#: Why a ``$`` value is refused; :func:`check_char_code` raises it in every field.
CHAR_CODE_RULE = "a character code is $ and two hex digits, $00 to $FF, such as $41"


def check_char_code(text: str, name: str) -> int:
    """Return the code ``text`` spells as ``$hh``; raise :class:`FieldError` naming field
    ``name`` for any other text.

    A code is picked from CLICK's Embed ASCII Code table, ``$00`` to ``$FF`` (Help
    ``ascii table2.gif``), so ``$``, ``$1``, ``$100`` and ``$G1`` are refused.  Compare, Search,
    Fill, a single Copy source and a Copy termination code call it on every ``$`` value.
    """
    m = _CHAR_RE.fullmatch(text.upper()) if text.isascii() else None
    if m is None:
        raise FieldError(f"{name}: {text!r} is refused; {CHAR_CODE_RULE}")
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
    # The shared check lets a sign stand anywhere among the digits.  The arc.md Q-D2 dialog
    # check (2026-11-11) found ``1-2`` refused in the Counter dialog, whose own parse runs
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
