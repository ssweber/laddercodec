"""A real constant in a decimal Math formula, and each form of it.

CLICK's Math saves a real in a form that depends on how it is typed.

- Typed without an ``E``, it keeps 6 digits after the point and cuts trailing zeros.  It is
  saved in positional form from 1E-04 to below 1E+07 (``0.33333334`` as ``0.333333``,
  ``0.00012345`` as ``0.000123``, ``1234567.0`` as ``1234567``), and in exponent form
  otherwise (``0.000012345678`` as ``1.234568E-05``, ``12345678.9`` as ``1.234568E+07``).
- Typed with an ``E``, it keeps 7 significant digits.  It is saved in positional form from
  1E-04 to below 1E+07 (``1.2345E-04`` as ``0.00012345``, ``1E5`` as ``100000``), and in
  exponent form otherwise (``1.2345678E+15`` as ``1.234568E+15``, ``3.0E+38`` as
  ``3E+38``).

CLICK's form for a real typed with a lowercase ``e`` is not known.  laddercodec accepts such
a real only when CLICK would keep its value under both rules: the rule for a real typed
without an ``E``, and the rule for one typed with an ``E``.

CLICK's save rule is stated once, in :attr:`MathReal.saves`.  :attr:`MathReal.in_range`
states the range rule.  :attr:`MathReal.stored` states the text that laddercodec writes for
an integral real.  The other properties are derived from these three.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from .constants import FLOAT32_MAX

#: The digits after the point that CLICK keeps of a real typed without an ``E``, in
#: positional form and in exponent form.
DECIMALS = 6
#: The significant digits that CLICK keeps of a real typed with an ``E``.
DIGITS = 7
#: The exponents, in exponent form, of the reals typed without an ``E`` that CLICK saves in
#: positional form: from 1E-04 to below 1E+07.
_POSITIONAL = range(-4, 7)
#: The type that the internal formula stores for each real.  CLICK stores some integral
#: reals as integers, ``W`` or ``H``.  laddercodec writes every real as ``F``.
REAL_TYPE = "F"


def _positional(value: float) -> str:
    printed = f"{value:.{DECIMALS}f}".rstrip("0").rstrip(".")
    return "0" if printed == "-0" else printed


def _exponent(value: float) -> str:
    mantissa, exponent = f"{value:.{DECIMALS}E}".split("E")
    return f"{mantissa.rstrip('0').rstrip('.')}E{exponent}"


def _signed(typed: str, text: str) -> str:
    """Return ``text`` with the ``+`` that ``typed`` starts with, if any."""
    return f"+{text}" if typed.startswith("+") else text


@dataclass(frozen=True)
class MathReal:
    """A real constant in a decimal Math formula.

    ``text`` is the real as it is typed.  It must be a real that
    :func:`~laddercodec.operands.constants.classify` reads: finite and within float32.
    Each property returns one form of the real.  CLICK's save rule is stated once, in
    :attr:`saves`.  :attr:`in_range` states the range rule.  :attr:`stored` states the text
    that laddercodec writes for an integral real.  The other properties are derived from
    these three.
    """

    text: str

    @property
    def value(self) -> float:
        """The real's value, read as a double."""
        return float(self.text)

    @property
    def in_range(self) -> bool:
        """Whether a decimal Math takes the real's value.

        A decimal Math takes a real only up to :data:`FLOAT32_MAX` in size.  It refuses
        ``3.4028235E+38``, though float32 rounds that value to its largest one.
        """
        return abs(self.value) <= FLOAT32_MAX

    @cached_property
    def saves(self) -> tuple[str, ...]:
        """The texts that CLICK's Math may save for the real, without a typed ``+``.

        The tuple holds one text when CLICK's form is known.  It holds two for a real typed
        with a lowercase ``e``: the form of a real typed without an ``E``, and the form of
        one typed with an ``E``.
        """
        value = self.value
        exponent = int(f"{value:.{DECIMALS}E}".split("E")[1])
        plain = _positional(value) if exponent in _POSITIONAL else _exponent(value)
        general = f"{value:.{DIGITS}G}"
        if "E" in self.text:
            return (general,)
        if "e" in self.text:
            return (plain, general)
        return (plain,)

    @property
    def saved(self) -> str | None:
        """The text that CLICK saves for the real, or None when it is not known."""
        return self.saves[0] if len(self.saves) == 1 else None

    @property
    def kept(self) -> bool:
        """Whether CLICK saves the real as the same value: each text in :attr:`saves` holds it."""
        return all(float(s) == self.value for s in self.saves)

    @property
    def instead(self) -> str:
        """A text to write in place of the real, when CLICK saves the real as another value.

        The text is one that CLICK saves as typed.  It holds the real's value when such a
        text exists (``1.2345E-04`` for ``0.00012345``), and else the value that CLICK
        saves (``0.333333`` for ``0.33333334``).  A typed ``+`` is not written.
        """
        value = self.value
        kept = [c for c in (*self.saves, _exponent(value)) if MathReal(c).kept]
        same = [c for c in kept if float(c) == value]
        return (same or kept or [_exponent(value)])[0]

    @property
    def typing(self) -> str | None:
        """A text that CLICK saves with the real's value when you type it, or None if no such
        text exists.

        The text is :attr:`text` itself when CLICK keeps it.  Otherwise it is
        :attr:`instead`, with a typed ``+``, when that text holds the same value.  CLICK
        cuts ``0.00012345`` to ``0.000123`` when you type it so, and the text for it is
        ``1.2345E-04``.
        """
        if self.kept:
            return self.text
        instead = self.instead
        if float(instead) != self.value:
            return None
        return _signed(self.text, instead)

    @property
    def stored(self) -> str:
        """The text that the display formula stores for the real, and that the internal
        formula stores after :attr:`stored_type`.

        The real must be one that CLICK keeps (:attr:`kept`).  The text is the one that
        CLICK saves, with a typed ``+``: ``1.50`` is ``1.5``, ``0.000015`` is ``1.5E-05``,
        ``20000000.0`` is ``2E+07`` and ``1234.000001`` stays.

        CLICK stores an integral real typed with an ``E``, and ``1234567.0``, as an integer
        (``1E5`` as ``W100000``).  When the saved text is an integer, laddercodec writes the
        value with 7 significant digits and ``.0``, and a typed ``+`` stays: ``1E5`` is
        ``100000.0``, ``+1e3`` is ``+1000.0`` and ``-0.0`` is ``-0.0``.  Such a value has at
        most 7 digits, because CLICK saves it in positional form below 1E+07.
        """
        saved = self.saves[0]
        if "." not in saved and "E" not in saved:
            # The saved text of -0.0 is 0. The G print keeps its sign.
            return _signed(self.text, f"{self.value:.{DIGITS}G}.0")
        return _signed(self.text, saved)

    @property
    def stored_type(self) -> str:
        """The type letter of the real in the internal formula (:data:`REAL_TYPE`)."""
        return REAL_TYPE

    @property
    def internal(self) -> str:
        """The real as the internal formula stores it: :attr:`stored_type`, then
        :attr:`stored` (``F1.5``)."""
        return f"{self.stored_type}{self.stored}"

    @property
    def held(self) -> str:
        """The text that a Math holds for the real, and that its CSV writes.

        It is :func:`held_for` of :attr:`stored`.  Typed again, it gives the same
        :attr:`stored`.
        """
        return held_for(self.stored)


def held_for(stored: str) -> str:
    """Return the text that a Math holds for a real that its formula stores as ``stored``.

    The text is one that CLICK saves with the same value when you type it
    (:attr:`MathReal.typing`).  CLICK saves ``1.2345E-04`` as ``0.00012345``, and it cuts
    ``0.00012345`` to ``0.000123`` when you type it so.  So ``0.00012345`` is held as
    ``1.2345E-04``.  When CLICK cuts the value however you type it, the text is ``stored``
    itself.  ``stored`` must be a real that
    :func:`~laddercodec.operands.constants.classify` reads.
    """
    return MathReal(stored).typing or stored
