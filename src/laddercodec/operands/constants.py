"""Constants as CLICK's shared input check reads them.

A dialog field that takes a constant first runs its text through one check shared by every
instruction dialog (DLL: baseEx.dll, CheckInputData), then applies its own limits.
:func:`classify` reads text the same way: it says which kind of constant the text is and
returns its value.  It applies no field's limits: a set point's 0 to 32767, the hex
constants a Copy puts in DD only, or which kinds a field takes at all belong to the field.

The shared check works on an uppercase copy of the text, so ``ffffh``, ``$0d`` and ``1e5``
are constants.  It tries, in order:

- hex: hex digits then ``H``.  At most FFFFh is 16-bit; above that, at most eight digits
  is 32-bit (:attr:`Constant.wide`); longer text is no constant.
- text: ``"..."``, the text between the quotes (see :data:`TEXT_MAX`).
- an address, which is no constant (:func:`classify` returns ``None``).
- a decimal integer: an int16 value, or an int32 value (wide); outside int32, no constant.
- a floating-point number (text with ``.`` or ``E``).
- a character code ``$hh``.

:func:`parse_digits` is the digits-only test several dialogs make instead (a Timer set point,
an Out variant preset, a drum duration, a For count).
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import NamedTuple


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
#: most 130 characters, quotes included.
TEXT_MAX = 128
#: Characters a text constant may hold: printable ASCII, the quote excepted.  The shared
#: check takes any character; the arc.md Q-B7 ruling (2026-11-11, revised) narrows a text
#: constant to printable ASCII and refuses a quote inside it, since the CSV token can't hold
#: one (``$22`` spells it).  The ruling wins.
TEXT_CHARS = frozenset(chr(c) for c in range(0x20, 0x7F)) - {'"'}

_HEX_RE = re.compile(r"([0-9A-F]+)H")
_INTEGER_RE = re.compile(r"[+-]?([0-9]+)")
# The shared check sends text holding ``.``, ``E`` or ``,`` to its floating-point test.  A
# comma is refused here: what that test does with one is not known, and a comma separates
# CSV arguments.
_FLOAT_RE = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:E[+-]?[0-9]+)?")
# The shared check also takes ``$1`` as a character code, and a ``$`` value above FF as a
# second kind; the arc.md Q-B7 note keeps every ``$`` form but two hex digits refused until
# a capture shows what CLICK stores for them.
_CHAR_RE = re.compile(r"\$([0-9A-F]{2})")
_DIGITS_RE = re.compile(r"[0-9]+")
#: More significant digits than any CLICK limit needs (int() refuses very long text).
_MAX_DIGITS = 20


def classify(text: str) -> Constant | None:
    """Return the constant ``text`` spells, or ``None`` if it is no constant.

    ``None`` covers an empty text, an address, a value outside its kind (an integer outside
    int32, hex longer than eight digits) and anything else the shared check refuses.  Only
    ASCII digits count (arc.md ruling 2026-11-11): ``٣`` is no digit.  No space is trimmed;
    a field that strips its text does so first.
    """
    if not text or not text.isascii():
        return None
    upper = text.upper()
    m = _HEX_RE.fullmatch(upper)
    if m is not None:
        return _hex(m.group(1))
    if len(text) >= 2 and text[0] == text[-1] == '"':
        inner = text[1:-1]
        if not 1 <= len(inner) <= TEXT_MAX or not TEXT_CHARS.issuperset(inner):
            return None
        return Constant(Kind.TEXT, inner)
    m = _INTEGER_RE.fullmatch(upper)
    if m is not None:
        return _integer(upper, m.group(1))
    if _FLOAT_RE.fullmatch(upper):
        return Constant(Kind.FLOAT, float(upper))
    m = _CHAR_RE.fullmatch(upper)
    if m is not None:
        return Constant(Kind.CHAR, int(m.group(1), 16))
    return None


def _hex(digits: str) -> Constant | None:
    # 16-bit by value, so 0FFFFh is 16-bit; 32-bit by digit count, so 0FFFFFFFFh is none.
    if len(digits.lstrip("0")) <= 4:
        return Constant(Kind.HEX, int(digits, 16))
    if len(digits) > HEX32_DIGITS:
        return None
    return Constant(Kind.HEX, int(digits, 16), wide=True)


def _integer(text: str, digits: str) -> Constant | None:
    # The shared check lets a sign stand anywhere among the digits; the arc.md Q-D2 dialog
    # check (2026-11-11) found ``1-2`` refused, so a sign only leads.
    if len(digits.lstrip("0")) > len(str(INT32_MAX)):
        return None
    value = int(text)
    if INT16_MIN <= value <= INT16_MAX:
        return Constant(Kind.INTEGER, value)
    if INT32_MIN <= value <= INT32_MAX:
        return Constant(Kind.INTEGER, value, wide=True)
    return None


def parse_digits(text: str) -> int | None:
    """Return the value of text that is ASCII digits only, or ``None``.

    The digits-only test of a Timer set point, an Out variant preset, a drum duration and a
    For count: no sign, no space, no decimal point.  Leading zeros are allowed (``007`` is
    7).  Text with more than 20 significant digits is ``None``; every limit those fields
    have is far below it.
    """
    if not _DIGITS_RE.fullmatch(text) or len(text.lstrip("0")) > _MAX_DIGITS:
        return None
    return int(text)
