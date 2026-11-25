"""Parse a Math formula once, and print from that parse each form that a Math blob stores.

The parser follows the check that CLICK v4's Math dialog runs when you click OK.
``docs/internals/instruction-blobs.md`` describes the steps and rules of that check, in the
section "Math formula grammar". The step numbers below are the ones in that section. If the
dialog would refuse the formula, :func:`parse` raises :class:`FieldError` on
``Math.expression``. The error names the token and the rule, and its
:attr:`~FieldError.errors` holds every refusal found. The parser works in these stages:

1. :func:`_lex` splits the text as the dialog's tokenizer does (step 1). It splits on
   spaces and tabs, on ``+ - * / ^ ( ) , :`` and on ``[ ]``. When a run of digits is
   followed by ``.``, ``E`` or ``e``, the tokenizer cuts the run at the end of the longest
   real number that it starts. For example, ``1.5E+10`` is one token, and the hex ``1Eh``
   becomes ``1`` and then ``Eh``. A run cut this way is refused, with one exception. If
   you type the hex constant ``1e3``, CLICK stores it as ``1E3h``. The parser reads a word
   as hex if the cut leaves only a lone ``h`` after its hex digits.
2. :func:`_classify` decides what each word is: a function or word operator, an address,
   or a constant of the Math's mode (step 6). An address must pass the full address check.
   Any other word is refused (step 7). The parser keeps a hex constant in CLICK's form:
   uppercase digits with no leading zeros, and then ``h``.
3. The parentheses must balance and nest at most 8 deep (step 3).
4. In a decimal Math, a ``-`` or ``+`` joins the decimal constant after it if the sign is
   at the start, after ``(`` or after ``,`` (step 5). In a hex Math, a sign is always a
   token of its own.
5. The parser checks the value of each constant (step 6). It keeps a real as CLICK prints
   it back, so ``1.50`` becomes ``1.5`` and ``1e3`` becomes ``1000.0``. Then it refuses each
   key of the other mode's keypad (step 8).
6. :func:`_check_order` checks which token may follow each token, the form of each
   function call, and how the formula starts and ends (step 9).
7. :func:`_check_rand` refuses a RAND bound that is a real constant, and a RAND whose two
   bounds are equal.
8. :func:`_check_operands` checks the banks and the order of each range. It checks that
   each address, a RAND bound included, is in a bank that the mode accepts
   (:data:`_OPERANDS`). It checks the size of a median's range, and the ends of an X or Y
   range that fall in the option slot. Last, :func:`parse` checks the internal template
   against its limit of 270 characters.

Some refusals stop the parse at once. These are a character that a formula cannot hold, a
bracket, parentheses that do not balance or nest too deep, and a token out of order. The
parse collects every other refusal and goes on past it. These are a refused word, a
constant's value, a key of the other mode, a refused RAND bound, an address in a bank that
the mode does not accept, and a refused range. After a refused word, the parse goes on as
if the word were what it looks like: an address, a constant or a function name. If a word
looks like none of these, the parse does not check the order, the RAND bounds, the banks or
the ranges. If a constant or such a word is refused, the parse does not check the length,
because neither has an internal form to count.

Each refusal sets :attr:`~FieldError.span` to the place of the refused text in the formula
as it was passed. A refusal of a word, a constant, an address or a RAND bound spans that
token, and a sign that joins a constant is part of it. A refusal of a range, SUM's bank
refusal included, spans ``a : b``. A refusal of a call's form spans the call, from the
function's name to its ``)``. A refusal of the order spans the two tokens that may not stand
together. Four refusals have no span: a blank formula, a formula that is too long, a ``(``
with no ``)``, and a key that only the other mode takes.

:class:`Formula` holds the tokens. Its properties and :meth:`Formula.internal` print the
display formula, the template, the nickname display, and the internal formula and internal
template, whose tokens are joined with ``#``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import NoReturn

from ..codes import Code
from ..model import (
    ADDRESS_BANKS,
    XY_SLOTS,
    Address,
    FieldError,
    check_address,
    normalize_address,
    to_display,
)
from ..operands.address import bank_prefix
from ..operands.banks import WORD_IO_BANKS, XY_BANKS, Bank, banks, bits_per_register
from ..operands.constants import (
    FLOAT32_MAX,
    INT16_MAX,
    INT16_MIN,
    INT32_MAX,
    INT32_MIN,
    Kind,
    classify,
    hex_display,
)
from ..operands.errors import Reason
from ..operands.math_real import MathReal, held_for
from ..operands.message import Op, Rule, make_refusal, says

_NAME = "Math.expression"

#: A half-open ``(start, end)`` pair of character offsets into the formula as it was passed.
Span = tuple[int, int]


def _error(
    said: Rule,
    reason: Reason,
    click_id: str | None = None,
    *,
    code: Code,
    then: str = "",
    span: Span | None = None,
) -> FieldError:
    """Return a refusal of the formula, with the message ``Math.expression: said``.

    If CLICK's id for the refusal is known, it follows the rule in parentheses. ``then`` is
    a sentence that tells the user what to do. It follows the id. ``span`` is the refused
    text's place in the formula (:attr:`FieldError.span`)."""
    error = make_refusal(
        FieldError, _NAME, said, field=_NAME, reason=reason, code=code, click_id=click_id, then=then
    )
    return _at(error, span)


def _at(error: FieldError, span: Span | None) -> FieldError:
    """Set the :attr:`~FieldError.span` of ``error`` to ``span``, and return ``error``."""
    error.span = span
    return error


def _between(first: Token, last: Token) -> Span | None:
    """Return the span from the start of ``first`` to the end of ``last``, or None if either
    token has no span."""
    if first.span is None or last.span is None:
        return None
    return first.span[0], last.span[1]


def _quoted(token: Token) -> Op | str:
    """Return ``token`` as a refusal quotes it.

    An address is an :class:`Op`, so that a name can replace it. Any other token is the
    repr of its text, and no name replaces it."""
    return Op(token.text) if token.kind == "addr" else repr(token.text)


def _bare(token: Token) -> Op | str:
    """Return ``token`` as a refusal shows it without quotes.

    An address is an unquoted :class:`Op`. Any other token is its text."""
    return Op(token.text, quoted=False) if token.kind == "addr" else token.text


def _raise(found: Sequence[FieldError]) -> NoReturn:
    """Raise the first refusal found, with :attr:`~FieldError.errors` holding them all."""
    first = found[0]
    first.errors = tuple(found)
    raise first


# ---------------------------------------------------------------------------
# Names (the keyword map of grammar step 2)
# ---------------------------------------------------------------------------

#: One-argument functions on the decimal keypad.
TRIG = frozenset({"SIN", "COS", "TAN", "ASIN", "ACOS", "ATAN", "LOG", "LN", "SQRT", "RAD", "DEG"})
#: Functions over a range ``F ( a : b )``.
RANGE_FUNCTIONS = frozenset({"SUM", "MAX", "MIN", "MDN", "AVG"})
SHIFT = frozenset({"LSH", "RSH", "LRO", "RRO"})
#: Two-argument functions, written ``F ( a , b )``. The internal formula stores them as
#: ``a#F#b``.
COMMA_FUNCTIONS = SHIFT | {"RAND"}
FUNCTIONS = TRIG | RANGE_FUNCTIONS | COMMA_FUNCTIONS | {"ABS"}
WORD_OPERATORS = frozenset({"MOD", "AND", "OR", "XOR"})
#: Every name on CLICK's Math keypads.
NAMES = FUNCTIONS | WORD_OPERATORS | {"PI"}
#: The keys that only the decimal keypad has, and the keys that only the hex keypad has.
DECIMAL_ONLY = TRIG | {"PI", "ABS", "^"}
HEX_ONLY = SHIFT | {"AND", "OR", "XOR"}

_SYMBOLS = frozenset("+-*/^(),:[]")
_SIGNS = ("+", "-")
_DIGITS = frozenset("0123456789")
_HEX_DIGITS = _DIGITS | frozenset("ABCDEFabcdef")

#: Parentheses nest at most 8 deep (OBJ-1010).
MAX_NESTING = 8
#: The most characters that the internal template may hold. The template has ``@`` for each
#: address and ``#`` between tokens. CLICK refuses a longer one with OBJ-1008,
#: "The Formula is too long". A sum of 68 addresses fits, and a sum of 69 does not.
MAX_INTERNAL_LENGTH = 270
#: The largest real that a decimal Math takes, as a refusal shows it: the text to write for
#: FLOAT32_MAX (``3.402823E+38``). Its value is not above FLOAT32_MAX, and CLICK keeps it
#: as typed.
_LARGEST_REAL_TEXT = MathReal(repr(FLOAT32_MAX)).instead
#: The longest integer CLICK prints back: ``-2147483648``.
_MAX_PRINTED = 11
#: The most bytes that the registers of a median may cover (OBJ-1013).
_MEDIAN_MAX_BYTES = 1024


@dataclass(frozen=True)
class _Operands:
    """The banks that a formula of one mode accepts.

    An address in any other bank is refused with OBJ-1002.
    """

    #: The register banks accepted anywhere in the formula.
    anywhere: frozenset[str]
    #: The bit banks accepted only as the range of ``SUM ( a : b )``.
    in_sum: frozenset[str]
    #: The rule, as each refusal states it.
    rule: str
    #: The register banks accepted as a bound of ``RAND ( a , b )``. A bound in any other
    #: bank is refused.
    in_rand: frozenset[str]
    #: RAND's rule, as each refusal of a bound states it.
    rand_rule: str


#: The operand banks of each mode. A decimal SUM accepts no CT range. An older CPU accepts
#: no bit range in a SUM at all. Building a Math accepts such a range anyway, and
#: :func:`~laddercodec.compat.find_v4_only` reports it. A RAND bound accepts fewer banks
#: than the rest of the formula, and a decimal RAND bound cannot be a real constant
#: (:func:`_check_rand`).
_OPERANDS = {
    "decimal": _Operands(
        banks(Bank.DS | Bank.DD | Bank.DF | Bank.TD | Bank.CTD | Bank.SD),
        banks(Bank.X | Bank.Y | Bank.C | Bank.T | Bank.SC),
        "a decimal Math takes only DS, DD, DF, TD, CTD and SD registers and decimal constants, "
        "and X, Y, C, T and SC bits only as the range of SUM ( a : b )",
        banks(Bank.DS | Bank.DD),
        "a decimal RAND bound is a DS or DD register or an integer constant",
    ),
    "hex": _Operands(
        banks(Bank.DH | Bank.XD | Bank.YD),
        frozenset(),
        "a hex Math takes only DH, XD and YD registers and hex constants",
        banks(Bank.DH),
        "a hex RAND bound is a DH register or a hex constant",
    ),
}
#: For each mode, the registers that the refusal of a RAND bound tells you to copy the bound
#: into.
_RAND_COPY_INTO = {"decimal": "a DS or DD", "hex": "a DH"}
#: The numbers of the XD and YD addresses, in order. The addresses between the ends of
#: ``MAX ( XD0 : XD3 )`` are XD0u, XD1 and XD2, and CLICK stores those.
_XY_WORD_ORDER = ("0", "0u", "1", "2", "3", "4", "5", "6", "7", "8")
#: The CPU slot (1-16) and its option slot (21-36), and the 4 numbers between them (17-20).
_CPU_SLOT, _OPTION_SLOT = XY_SLOTS[0], XY_SLOTS[1]
_OPTION_GAP = _OPTION_SLOT[0] - _CPU_SLOT[1] - 1


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    """One token of a formula.

    ``kind`` is ``(``, ``)``, ``,``, ``:``, ``op`` (``+ - * / ^`` and the word operators),
    ``func``, ``pi``, ``const``, ``addr`` or ``word``. A ``word`` is a refused word that looks
    like no other kind. ``text`` is the token as the display formula shows it. For a
    constant, ``internal`` is the constant as the internal formula stores it (``H5``,
    ``F1.5``, ``UH10``). ``refused`` is True for a word or constant that the parser has
    already refused. The parser goes on as if such a token were the ``kind`` it looks like.
    ``real`` is set for a real constant that the parser accepts. The token's ``text`` and
    ``internal`` are then :attr:`MathReal.stored` and :attr:`MathReal.internal`. Two tokens
    that store the same text are equal, however the real was typed. ``span`` is where the
    token was typed in the formula. A sign that joins a constant is part of its span. Two
    tokens in different places are equal if the rest is equal.
    """

    kind: str
    text: str
    internal: str = ""
    refused: bool = False
    real: MathReal | None = field(default=None, compare=False)
    span: Span | None = field(default=None, compare=False)

    @classmethod
    def of_real(cls, real: MathReal, span: Span | None = None) -> Token:
        """Return the constant token of ``real``, a real that CLICK keeps, typed at ``span``."""
        return cls("const", real.stored, real.internal, real=real, span=span)

    @property
    def written(self) -> str:
        """The token as the Math holds it: :attr:`MathReal.held` for a real, else ``text``."""
        return self.real.held if self.real is not None else self.text


def address_parts(text: str) -> tuple[str, str] | None:
    """Return ``(bank, number)`` if ``text`` has the shape of an address, else ``None``.

    An address is an uppercase bank from :data:`ADDRESS_BANKS` followed by the digits 0-9.
    After XD or YD, a ``u`` may follow the digits (``DS1``, ``X001``, ``XD0u``). This
    function does not check that the number is in range.
    """
    bank = bank_prefix(text)
    number = text[len(bank) :]
    if bank not in ADDRESS_BANKS:
        return None
    digits = number[:-1] if bank in WORD_IO_BANKS and number.endswith("u") else number
    if not digits or not all(c in _DIGITS for c in digits):
        return None
    return bank, number


def _hex_digits(word: str) -> str | None:
    """Return the digits of ``word`` if it is a hex constant, else ``None``.

    A hex constant is one or more hex digits followed by one ``h`` or ``H``."""
    if len(word) < 2 or word[-1] not in "hH" or not all(c in _HEX_DIGITS for c in word[:-1]):
        return None
    return word[:-1]


def _real_end(text: str, start: int) -> int:
    """Return the index where the longest real number that starts at ``start`` ends.

    This is as far as ``wcstod`` would read. If no real number starts there, return
    ``start``. A real number is digits with an optional ``.`` and fraction, or ``.`` and
    digits. An exponent may follow: ``E`` or ``e``, an optional sign, and digits.
    """
    n = len(text)
    i = start
    while i < n and text[i] in _DIGITS:
        i += 1
    digits = i - start
    if i < n and text[i] == ".":
        j = i + 1
        while j < n and text[j] in _DIGITS:
            j += 1
        digits += j - i - 1
        i = j
    if digits == 0:
        return start
    if i < n and text[i] in "Ee":
        j = i + 1
        if j < n and text[j] in _SIGNS:
            j += 1
        if j < n and text[j] in _DIGITS:
            while j < n and text[j] in _DIGITS:
                j += 1
            i = j
    return i


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch in "._"


@dataclass(frozen=True)
class _Raw:
    """A token as :func:`_lex` split it, before :func:`_classify` decides what it is.

    It is a symbol, a word, or a real number that the tokenizer read as one token.
    """

    text: str
    symbol: bool = False
    number: bool = False
    #: For a word that starts with a number that the tokenizer cut, the index in the word
    #: where that number ends. 0 for any other token.
    cut: int = 0
    #: The index in the formula where the token starts. The token ends at ``start`` plus
    #: the length of ``text``.
    start: int = 0

    @property
    def span(self) -> Span:
        """Where the token is in the formula."""
        return self.start, self.start + len(self.text)


def _lex(text: str) -> list[_Raw]:
    """Split ``text`` as CLICK's tokenizer does (grammar step 1)."""
    out: list[_Raw] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        # Only a space or a tab separates tokens; other white space is refused below.
        if ch in " \t":
            i += 1
            continue
        if ch in _SYMBOLS:
            out.append(_Raw(ch, symbol=True, start=i))
            i += 1
            continue
        if ch in '"$':
            # A whole formula is quoted as it is. A name never replaces an address in it.
            # The span is the character that starts the text constant.
            raise _error(
                says(
                    "{text!r} holds a text constant", "a Math formula takes numbers only", text=text
                ),
                Reason.KIND,
                code=Code.MATH_CONSTANT_KIND,
                span=(i, i + 1),
            )
        if not _is_word_char(ch):
            raise _error(
                says("{ch!r} in {text!r} is no part of a Math formula", ch=ch, text=text),
                Reason.FORM,
                code=Code.MATH_INVALID_TOKEN,
                then=f"Remove the {ch!r}.",
                span=(i, i + 1),
            )
        end = i
        while end < n and _is_word_char(text[end]):
            end += 1
        # Digits followed by '.', 'E' or 'e', or a '.' with no digits before it, start a
        # real number.
        k = i
        while k < end and text[k] in _DIGITS:
            k += 1
        if k < end and text[k] in ".Ee" and (k > i or text[k] == "."):
            stop = _real_end(text, i)
            if stop > i:
                if stop < n and _is_word_char(text[stop]):
                    # The word goes on past the number: CLICK cuts it in two.
                    end = stop
                    while end < n and _is_word_char(text[end]):
                        end += 1
                    out.append(_Raw(text[i:end], cut=stop - i, start=i))
                    i = end
                    continue
                out.append(_Raw(text[i:stop], number=True, start=i))
                i = stop
                continue
        out.append(_Raw(text[i:end], start=i))
        i = end
    return out


def _has_sign(raws: Sequence[_Raw], i: int) -> bool:
    """Whether a ``+`` or ``-`` stands before ``raws[i]`` at the start of the formula or
    after ``(`` or ``,``."""
    return i > 0 and raws[i - 1].text in _SIGNS and (i == 1 or raws[i - 2].text in ("(", ","))


def _signed(raws: Sequence[_Raw], i: int, word: str) -> str:
    """Return ``word`` with the sign before it, if :func:`_has_sign` finds one. Otherwise
    return ``word``."""
    return f"{raws[i - 1].text}{word}" if _has_sign(raws, i) else word


def _signed_span(raws: Sequence[_Raw], i: int) -> Span:
    """Return the span of ``raws[i]``, from the sign before it if :func:`_has_sign` finds
    one."""
    start = raws[i - 1].start if _has_sign(raws, i) else raws[i].start
    return start, raws[i].span[1]


def _in_call(raws: Sequence[_Raw], i: int) -> bool:
    """Whether ``raws[i]`` starts an argument of RAND, LSH, RSH, LRO or RRO."""
    if i < 1:
        return False
    before = raws[i - 1].text
    return before == "," or (
        before == "(" and i >= 2 and raws[i - 2].text.upper() in COMMA_FUNCTIONS
    )


def _word_refusal(word: str) -> FieldError:
    return _error(
        says(
            "{word!r} is not an address, a function name or a constant",
            "a Math formula takes only those",
            word=word,
        ),
        Reason.KIND,
        "OBJ-1001",
        code=Code.MATH_INVALID_TOKEN,
    )


def _classify(raws: Sequence[_Raw], i: int, mode: str, found: list[FieldError]) -> Token | None:
    """Return the token that ``raws[i]`` is (grammar steps 2 and 6).

    If the word is refused (step 7), add the refusal to ``found``. Then return the token
    that the word looks like, marked as refused, or ``None`` if it looks like no token.
    """
    raw = raws[i]
    word = raw.text

    def refuse(
        error: FieldError, kind: str | None, text: str = word, span: Span = raw.span
    ) -> Token | None:
        found.append(_at(error, span))
        return None if kind is None else Token(kind, text, refused=True)

    if raw.symbol:
        kind = "op" if word in "+-*/^" else word
        return Token(kind, word)
    if any(c.isdecimal() and not c.isascii() for c in word):
        return refuse(
            _error(
                says("{word!r} has a digit outside 0-9", word=word),
                Reason.FORM,
                code=Code.MATH_INVALID_TOKEN,
                then="Write its digits as 0-9.",
            ),
            None,
        )
    hex_digits = _hex_digits(word)
    # If you type a hex Math constant with no h that looks like a real number, such as 1e3,
    # CLICK stores it as the digits and then h (1E3h). The tokenizer cuts 1E3h after 1E3 and
    # leaves only the h. The parser reads a word cut that way as a hex constant.
    stored_hex = raw.cut and hex_digits is not None and len(word) - raw.cut == 1
    if raw.cut and not stored_hex:
        if hex_digits is not None and mode == "hex":
            first, rest = word[: raw.cut], word[raw.cut :]
            error = _error(
                says(
                    "{word} is refused",
                    "CLICK reads the digits before E as a real number, so it reads {word} as "
                    "{first} then {rest}",
                    word=word,
                    first=first,
                    rest=rest,
                ),
                Reason.FORM,
                code=Code.MATH_INVALID_TOKEN,
            )
            return refuse(error, "const")
        if hex_digits is None:
            return refuse(_word_refusal(word), None)
    upper = word.upper()
    if not raw.number and not raw.cut:
        if upper in NAMES:
            kind = "op" if upper in WORD_OPERATORS else "pi" if upper == "PI" else "func"
            try:
                return Token(kind, to_display(word, upper, _NAME))
            except FieldError as exc:
                return refuse(exc, kind, upper)
        try:
            address = normalize_address(word, _NAME)
        except FieldError as exc:
            # Only an address not in display form is refused here.
            return refuse(exc, "addr")
        if address_parts(address) is not None:
            try:
                check_address(address, _NAME, ADDRESS_BANKS)
            except FieldError as exc:
                return refuse(exc, "addr", address)
            return Token("addr", address)
    if hex_digits is not None:
        if mode == "decimal":
            error = _error(
                says(
                    "{constant} is a hex constant",
                    "a decimal Math takes decimal constants such as 7",
                    constant=hex_display(hex_digits),
                ),
                Reason.KIND,
                "OBJ-1001",
                code=Code.MATH_CONSTANT_KIND,
            )
            return refuse(error, "const")
        if len(hex_digits) > 4:
            # CLICK counts the digits as typed, leading zeros too (0FFFEh is refused).
            error = _error(
                says(
                    "{digits}h is outside 0h..FFFFh",
                    "a hex constant has at most 4 digits",
                    digits=hex_digits,
                ),
                Reason.RANGE,
                "OBJ-1009",
                code=Code.MATH_CONSTANT_OUT_OF_RANGE,
            )
            return refuse(error, "const")
        try:
            text = to_display(word, hex_display(hex_digits), _NAME)
        except FieldError as exc:
            return refuse(exc, "const")
        return Token("const", text, f"UH{int(hex_digits, 16)}")
    if mode == "hex" and 0 < len(word) <= 4 and all(c in _HEX_DIGITS for c in word):
        # CLICK's hex Math reads up to 4 hex digits with no h as hex: 005 is 5h, FF is FFh and
        # 1e3 is 1E3h. It refuses 5 digits, even 00005. laddercodec refuses such text. Where
        # the h form is accepted, the refusal names it, because the h form says plainly what
        # the constant means.
        signed = _signed(raws, i, word)
        fixed = f"{signed[: len(signed) - len(word)]}{hex_display(word)}"
        said = says("{signed} has no h", "a hex Math takes hex constants such as 7h", signed=signed)
        if signed == word or not _in_call(raws, i - 1):
            # Name the h form only where it is accepted. A signed argument of RAND, LSH, RSH,
            # LRO or RRO is refused even with its h.
            said = says(
                "{signed} has no h",
                "a hex Math takes hex constants, and CLICK reads it as {fixed}: write {fixed}",
                signed=signed,
                fixed=fixed,
            )
        error = _error(said, Reason.KIND, code=Code.MATH_CONSTANT_KIND)
        return refuse(error, "const", span=_signed_span(raws, i))
    if raw.number or (word and all(c in _DIGITS for c in word)):
        if mode == "hex":
            error = _error(
                says(
                    "{constant} is a decimal constant",
                    "a hex Math takes hex constants such as 7h",
                    constant=_signed(raws, i, word),
                ),
                Reason.KIND,
                code=Code.MATH_CONSTANT_KIND,
            )
            return refuse(error, "const", span=_signed_span(raws, i))
        return Token("const", word)
    return refuse(_word_refusal(word), None)


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def _example(formula: str, mode: str) -> str:
    """Return ``formula``, an example written for a decimal Math, as a Math of ``mode``
    writes it.

    In a hex Math, each DS address becomes the DH address of the same number, and each
    integer constant gets an ``h``. So ``DS1 * ( -2 )`` becomes ``DH1 * ( -2h )``. The
    tokens of ``formula`` are separated by single spaces.
    """
    if mode != "hex":
        return formula
    words = []
    for word in formula.split(" "):
        if word.startswith("DS"):
            word = f"DH{word[2:]}"
        elif word.lstrip("+-").isdigit():
            word = f"{word}h"
        words.append(word)
    return " ".join(words)


def _check_parentheses(tokens: Sequence[Token], shown: str, mode: str) -> FieldError | None:
    """Return the first refusal of the parentheses (grammar step 3), or ``None``.

    ``mode`` is the Math's mode, which the example in a refusal is written for."""
    depth = 0
    for token in tokens:
        if token.kind == "(":
            depth += 1
            if depth > MAX_NESTING:
                return _error(
                    says(
                        "{shown!r} nests parentheses {depth} deep",
                        "CLICK allows {most}",
                        shown=shown,
                        depth=depth,
                        most=MAX_NESTING,
                    ),
                    Reason.RANGE,
                    "OBJ-1010",
                    code=Code.MATH_NESTING_DEPTH,
                    then="Take out the extra pairs of parentheses.",
                    span=token.span,
                )
        elif token.kind == ")":
            depth -= 1
            if depth < 0:
                return _error(
                    says("{shown!r} has a ')' with no '('", shown=shown),
                    Reason.FORM,
                    "OBJ-1004",
                    code=Code.MATH_UNBALANCED_PARENS,
                    then="Add the '(' that opens it, or remove the ')'.",
                    span=token.span,
                )
    if depth > 0:
        return _error(
            says("{shown!r} has a '(' with no ')'", shown=shown),
            Reason.FORM,
            "OBJ-1005",
            code=Code.MATH_UNBALANCED_PARENS,
            then=f"Add the ')' that closes it, such as {_example('( DS1 + 2 )', mode)}.",
        )
    return None


def _merge_signs(tokens: list[Token]) -> list[Token]:
    """Return *tokens* with each sign joined to the decimal constant after it (step 5).

    A ``-`` or ``+`` joins the constant only if the sign is at the start, after ``(`` or
    after ``,``. If you type ``DS1 + ( +5 )``, CLICK stores ``DS1#+#(#H+5#)``.
    """
    out: list[Token] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if (
            token.text in _SIGNS
            and (not out or out[-1].kind in ("(", ","))
            and nxt is not None
            and nxt.kind == "const"
            and not nxt.internal
        ):
            # Join the sign to a refused constant too, so that the order check sees the same
            # tokens as for a constant it accepts, such as 5.
            text = f"{token.text}{nxt.text}"
            out.append(Token("const", text, refused=nxt.refused, span=_between(token, nxt)))
            i += 2
            continue
        out.append(token)
        i += 1
    return out


def _decimal_internal(text: str) -> str | MathReal | FieldError:
    """Return the internal form of a decimal integer, the :class:`MathReal` of a real, or
    the refusal of the constant's value (OBJ-1009).

    CLICK reads an integer with ``_wtoi64`` and keeps the low 32 bits. It prints them with
    ``%d``, with a ``+`` in front if one was typed (``+5``). If the printed text is not as
    long as the typed text, CLICK refuses the token. For example, ``3000000000``, ``007``
    and ``-0`` are refused. ``6000000000`` passes, because its low 32 bits print as
    ``1705032704``, which has the same length. CLICK stores an int16 value as ``H`` and a
    wider value as ``W``, each followed by the typed text (``H+5``).

    A real is refused when its value is out of range (:attr:`MathReal.in_range`). It is also
    refused when CLICK may save it as a different value (:attr:`MathReal.kept`), and that
    refusal names the constant to write (:attr:`MathReal.instead`).
    """
    body = text[1:] if text[:1] in _SIGNS else text
    if not all(c in _DIGITS for c in body):
        real = MathReal(text)
        if not real.in_range:
            return _error(
                says(
                    "{text} is outside the float32 range",
                    "a real constant in Math is at most {largest} in size",
                    text=text,
                    largest=_LARGEST_REAL_TEXT,
                ),
                Reason.RANGE,
                "OBJ-1009",
                code=Code.MATH_CONSTANT_OUT_OF_RANGE,
            )
        if not real.kept:
            if real.saved is not None:
                said = says(
                    "{text} has more digits than CLICK keeps in Math",
                    "CLICK saves it as {saved}: write {instead}",
                    text=text,
                    saved=real.saved,
                    instead=real.instead,
                )
            else:
                said = says("{text} may have more digits than CLICK keeps in Math", text=text)
                return _error(
                    said,
                    Reason.FORM,
                    code=Code.MATH_CONSTANT_OUT_OF_RANGE,
                    then=f"Write {real.instead}.",
                )
            return _error(said, Reason.FORM, code=Code.MATH_CONSTANT_OUT_OF_RANGE)
        return real
    if len(text) > _MAX_PRINTED:
        # %d of a 32-bit value, with a typed '+', prints at most 11 characters.
        return _error(
            says(
                "{text} is refused",
                "CLICK prints an integer back in at most {most} characters, which is not what "
                "was typed",
                text=text,
                most=_MAX_PRINTED,
            ),
            _integer_reason(text, body),
            "OBJ-1009",
            code=Code.MATH_CONSTANT_OUT_OF_RANGE,
        )
    value = int(text)
    # _wtoi64 saturates at the int64 limits.
    low = (max(-(2**63), min(2**63 - 1, value)) + 2**31) % 2**32 - 2**31
    printed = f"+{low}" if text.startswith("+") else str(low)
    if len(printed) != len(text):
        if not INT32_MIN <= value <= INT32_MAX:
            reason = _integer_reason(text, body)
            if reason is Reason.FORM:
                # The leading zeros are what is refused. Without them, the value is accepted.
                said = says(
                    "{text} is refused", "an integer constant has no leading zeros", text=text
                )
            else:
                said = says(
                    "{text} is outside {low}..{high}",
                    "an integer constant is 32-bit",
                    text=text,
                    low=INT32_MIN,
                    high=INT32_MAX,
                )
            return _error(said, reason, "OBJ-1009", code=Code.MATH_CONSTANT_OUT_OF_RANGE)
        return _error(
            says(
                "{text} is refused",
                "CLICK reads it back as {printed}, which is not what was typed",
                text=text,
                printed=printed,
            ),
            Reason.FORM,
            "OBJ-1009",
            code=Code.MATH_CONSTANT_OUT_OF_RANGE,
        )
    return f"{'H' if INT16_MIN <= value <= INT16_MAX else 'W'}{text}"


def _integer_reason(text: str, body: str) -> Reason:
    """Return the reason that CLICK refuses an integer: RANGE for its value, else FORM.

    Leading zeros are a matter of form. ``06000000000`` is refused, but ``6000000000`` is
    accepted. So the value is the reason only if the integer is refused without its leading
    zeros too. ``body`` is ``text`` without its sign. This function converts text to a
    number only when the text is at most 11 characters long, because Python refuses to
    convert a string of more than 4300 digits.
    """
    stripped = text[: len(text) - len(body)] + (body.lstrip("0") or "0")
    if len(stripped) > _MAX_PRINTED:
        return Reason.RANGE  # 11 digits and a sign, or 12 digits, is too big for 32 bits
    if stripped != text:
        alone = _decimal_internal(stripped)
        refused = isinstance(alone, FieldError) and alone.reason is Reason.RANGE
        return Reason.RANGE if refused else Reason.FORM
    return Reason.FORM if INT32_MIN <= int(text) <= INT32_MAX else Reason.RANGE


def _check_mode(tokens: Sequence[Token], mode: str, shown: str) -> list[FieldError]:
    """Return a refusal for each key of the other mode's keypad in ``tokens`` (grammar step 8).

    Each refusal names ``Math.mode`` as well, because a Math of the other mode accepts the
    key. If the formula holds a register that the other mode refuses, the refusal names the
    registers that the other mode takes.
    """
    other = HEX_ONLY if mode == "decimal" else DECIMAL_ONLY
    other_mode = "hex" if mode == "decimal" else "decimal"
    takes = _OPERANDS[other_mode].anywhere
    foreign = any(
        (parts := address_parts(token.text)) is not None and parts[0] not in takes
        for token in tokens
        if token.kind == "addr"
    )
    registers = [bank for bank in ADDRESS_BANKS if bank in takes]
    named = f"{', '.join(registers[:-1])} or {registers[-1]}"

    def then(key: str) -> str:
        if foreign:
            return (
                f"Take {key} out of the formula, or set mode to {other_mode} and write its "
                f"registers as {named}."
            )
        return f"Set mode to {other_mode}, or take {key} out of the formula."

    return [
        make_refusal(
            FieldError,
            _NAME,
            says(
                "{key} is {other} only",
                "{shown!r} is a {mode} Math",
                key=token.text,
                other=other_mode,
                shown=shown,
                mode=mode,
            ),
            field=(_NAME, "Math.mode"),
            reason=Reason.CONFLICT,
            click_id="OBJ-1006",
            code=Code.MATH_FUNCTION_MODE,
            then=then(token.text),
        )
        for token in tokens
        if token.kind in ("op", "func", "pi") and token.text in other
    ]


_VALUES = ("func", "pi", "const", "addr")


def _follow_refusal(a: Token, b: Token, mode: str) -> tuple[Rule, str] | None:
    """Return why ``b`` may not follow ``a`` and what to write instead, or ``None`` if it
    may (the table in step 9).

    The rule starts with the two tokens: ``'+' after '(': it needs a value before it``. A
    token that is an address is an :class:`Op`. The example is written for a Math of
    ``mode``.
    """
    why = _follow_rule(a, b, mode)
    if why is None:
        return None
    short, then = why
    said = says("{after} after {before}: {short}", after=_quoted(b), before=_quoted(a), short=short)
    return said, then


def _follow_rule(a: Token, b: Token, mode: str) -> tuple[str, str] | None:
    """Return why ``b`` may not follow ``a``: a short rule, and a sentence that says what to
    write instead.

    The sentence's example is a formula that a Math of ``mode`` accepts. Return ``None`` if
    ``b`` may follow ``a``."""

    def such_as(formula: str) -> str:
        return _example(formula, mode)

    if a.kind == "(":
        if b.kind == ")":
            return (
                "the parentheses hold nothing",
                f"Put a value in them, such as {such_as('( DS1 )')}.",
            )
        if b.kind in (",", ":") or (b.kind == "op" and b.text not in _SIGNS):
            return (
                "it needs a value before it",
                f"Put a value before it, such as {such_as('( DS1 * 2 )')}.",
            )
    elif a.kind == ")":
        if b.kind == "(" or b.kind in _VALUES:
            return (
                "a value after ')' needs an operator between them",
                f"Put an operator after the ')', such as {such_as('( DS1 + 1 ) * DS2')}.",
            )
    elif a.kind == "op":
        if b.kind == "op" and b.text in _SIGNS:
            return (
                "a sign right after an operator is refused",
                f"Put the signed value in parentheses, such as {such_as('DS1 * ( -2 )')}.",
            )
        if b.kind in (")", ",", ":", "op"):
            return (
                "an operator needs a value after it",
                f"Put a value after it, such as {such_as('DS1 + 2')}.",
            )
    elif a.kind in ("const", "addr", "pi"):
        # PI may be followed by '(': typed PI ( 2 ) is stored PI#(#H2#).
        if (b.kind == "(" and a.kind != "pi") or b.kind in _VALUES:
            return (
                "two values need an operator between them",
                f"Put an operator between them, such as {such_as('DS1 + DS2')}.",
            )
        if a.kind == "pi" and b.kind in (",", ":"):
            return "PI may not stand before ',' or ':'", "Write an address or a number there."
    elif a.kind == "func":
        if b.kind != "(":
            return (
                f"{a.text} takes its argument in parentheses, {a.text} ( ... )",
                f"Write it as {_call_example(a.text, mode)}.",
            )
    elif a.kind in (",", ":"):
        if b.kind in (")", ",", ":", "op"):
            return (
                "it needs a value after it",
                f"Put an address after it, such as {such_as('DS10')}.",
            )
        if b.kind == "func" and b.text in SHIFT:
            return (
                f"{b.text} may not stand right after ',' or ':'",
                f"Write an address there, such as {such_as('DS1')}.",
            )
    return None


def _call_example(function: str, mode: str) -> str:
    """Return a call of the Math function ``function`` to show in a refusal, such as
    ``SUM ( DS1 : DS10 )``.

    A Math of ``mode`` accepts the call if its keypad has ``function``. A function that only
    the other mode's keypad has gets a call that a Math of that mode accepts, such as
    ``LSH ( DH1 , 1h )`` in a decimal Math.
    """
    if function in DECIMAL_ONLY:
        mode = "decimal"
    elif function in HEX_ONLY:
        mode = "hex"
    if function in SHIFT:
        call = f"{function} ( DS1 , 1 )"
    elif function in COMMA_FUNCTIONS:
        call = f"{function} ( 1 , 10 )"
    elif function in RANGE_FUNCTIONS:
        call = f"{function} ( DS1 : DS10 )"
    else:
        call = f"{function} ( DS1 )"
    return _example(call, mode)


def _closing(tokens: Sequence[Token], i: int) -> int:
    """Return the index of the ``)`` that closes the ``(`` at ``i``, or the last index."""
    depth = 0
    for j in range(i, len(tokens)):
        if tokens[j].kind == "(":
            depth += 1
        elif tokens[j].kind == ")":
            depth -= 1
            if depth == 0:
                return j
    return len(tokens) - 1


def _check_order(tokens: Sequence[Token], mode: str) -> FieldError | None:
    """Return the first refusal of the token order (grammar step 9), or ``None``.

    The check reads the tokens in order. It checks the form of each function call when it
    reaches the function's name. The example in a refusal is written for a Math of ``mode``.
    """
    call_separators: set[int] = set()
    for i, token in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt is not None:
            found = _follow_refusal(token, nxt, mode)
            if found is not None:
                said, then = found
                return _error(
                    said,
                    Reason.FORM,
                    "OBJ-1001",
                    code=Code.MATH_SYNTAX_ERROR,
                    then=then,
                    span=_between(token, nxt),
                )
        if token.kind == "," and i not in call_separators:
            # CLICK reads a comma outside RAND ( a , b ) or LSH..RRO ( a , b ) as a decimal
            # comma, and refuses DS1 , DS2 with OBJ-037. MAX ( DS1 , DS2 ) is refused too,
            # but at MAX, because its arguments are not a range. That happens before the
            # comma is read, and CLICK's id for that refusal is not known.
            return _error(
                says(
                    "',' stands outside RAND, LSH, RSH, LRO or RRO ( a , b )",
                    "CLICK reads it as a decimal comma: use a period (.) as the decimal point",
                ),
                Reason.FORM,
                "OBJ-037",
                code=Code.MATH_SYNTAX_ERROR,
                span=token.span,
            )
        if token.kind == ":" and i not in call_separators:
            # A ':' outside SUM..AVG ( a : b ) is refused.
            return _error(
                says(
                    "':' stands outside SUM, MAX, MIN, MDN or AVG ( a : b )",
                    "a range is written in one of those",
                ),
                Reason.FORM,
                code=Code.MATH_SYNTAX_ERROR,
                span=token.span,
            )
        if token.kind != "func":
            continue
        # The call runs from the function's name to the ')' that closes its '('.
        call = _between(token, tokens[_closing(tokens, i + 1)])
        if token.text in COMMA_FUNCTIONS:
            # The form is F ( a , b ), with one token for each argument. For LSH..RRO, a
            # must be an address.
            first = ("addr",) if token.text in SHIFT else ("addr", "const")
            shape = tokens[i + 1 : i + 6]
            if not (
                len(shape) == 5
                and [t.kind for t in shape[::2]] == ["(", ",", ")"]
                and shape[1].kind in first
                and shape[3].kind in ("addr", "const")
            ):
                what = "an address" if token.text in SHIFT else "an address or a constant"
                return _error(
                    says(
                        "{function} takes {function} ( a , b ): a is {what}, b an address or a "
                        "constant, one each",
                        function=token.text,
                        what=what,
                    ),
                    Reason.FORM,
                    "OBJ-1001",
                    code=Code.MATH_ARG_EXPRESSION,
                    then=f"Write it as {_call_example(token.text, mode)}.",
                    span=call,
                )
            call_separators.add(i + 3)
        elif token.text in RANGE_FUNCTIONS:
            # The form is F ( a : b ), where a and b are addresses. SUM ( DS1 + DS2 ) is
            # refused.
            shape = [t.kind for t in tokens[i + 1 : i + 6]]
            if shape != ["(", "addr", ":", "addr", ")"]:
                return _error(
                    says(
                        "{function} takes {function} ( a : b ), a range from address a to "
                        "address b",
                        function=token.text,
                    ),
                    Reason.FORM,
                    code=Code.MATH_ARG_EXPRESSION,
                    then=f"Write it as {_call_example(token.text, mode)}.",
                    span=call,
                )
            call_separators.add(i + 3)
        elif token.text in TRIG:
            # Inside a trig call, there must be as many SUMs as ',' and ':' together. Each
            # SUM accounts for the ':' of its range.
            body = tokens[i + 1 : _closing(tokens, i + 1) + 1]
            balance = sum(t.kind in (",", ":") for t in body) - sum(t.text == "SUM" for t in body)
            if balance:
                return _error(
                    says(
                        "{function} ( ... ) holds a ',' or ':' that is not a SUM range",
                        "remove it",
                        function=token.text,
                    ),
                    Reason.FORM,
                    "OBJ-1001",
                    code=Code.MATH_SYNTAX_ERROR,
                    span=call,
                )
    first, last = tokens[0], tokens[-1]
    if first.kind in (")", ",", ":") or (first.kind == "op" and first.text not in _SIGNS):
        return _error(
            says("the formula starts with {first!r}", first=first.text),
            Reason.FORM,
            "OBJ-1001",
            code=Code.MATH_SYNTAX_ERROR,
            then=f"Start the formula with a value or '(', such as {_example('DS1 + 2', mode)}.",
            span=first.span,
        )
    if last.kind not in (")", "pi", "const", "addr"):
        return _error(
            says("the formula ends with {last!r}", last=last.text),
            Reason.FORM,
            "OBJ-1001",
            code=Code.MATH_SYNTAX_ERROR,
            then=f"End the formula with a value or ')', such as {_example('DS1 + 2', mode)}.",
            span=last.span,
        )
    return None


def _range_position(bank: str, number: str) -> int:
    if bank in WORD_IO_BANKS:
        return _XY_WORD_ORDER.index(number) if number in _XY_WORD_ORDER else -1
    return int(number.rstrip("u"))


def _rand_calls(tokens: Sequence[Token]) -> list[int]:
    """Return the index of each ``RAND`` in ``tokens``. Its bounds are 2 and 4 tokens after it.

    Call this only on tokens that passed :func:`_check_order`. That check makes sure that
    each RAND has the form ``RAND ( a , b )``.
    """
    return [i for i, t in enumerate(tokens) if t.kind == "func" and t.text == "RAND"]


def _check_rand(tokens: Sequence[Token], mode: str) -> list[FieldError]:
    """Return a refusal (OBJ-1001) for each RAND bound that is a real constant, and for each
    RAND whose two bounds are equal.

    Two bounds are equal when their display forms are the same text. ``RAND ( 1h , 01h )``
    displays as ``RAND ( 1h , 1h )``, so it is refused. ``RAND ( 1 , +1 )`` is accepted. A
    bound that was refused when it was read is not checked again. :func:`_check_operands`
    checks the banks of a bound, along with the other addresses.
    """
    rule = _OPERANDS[mode].rand_rule
    found: list[FieldError] = []
    for i in _rand_calls(tokens):
        low, high = tokens[i + 2], tokens[i + 4]
        for bound in (low, high):
            if bound.real is not None:
                said = says("{real} is a real constant", "{rule}", real=bound.text, rule=rule)
                found.append(
                    _error(
                        said,
                        Reason.KIND,
                        "OBJ-1001",
                        code=Code.RANDOM_BOUND_TYPE,
                        span=bound.span,
                    )
                )
        if not (low.refused or high.refused) and low.text == high.text:
            found.append(
                _error(
                    says(
                        "RAND ( {low} , {high} ) has equal bounds",
                        "RAND takes two different bounds",
                        low=_bare(low),
                        high=_bare(high),
                    ),
                    Reason.FORM,
                    "OBJ-1001",
                    code=Code.RANDOM_EQUAL_BOUNDS,
                    span=_between(tokens[i], tokens[i + 5]),
                )
            )
    return found


def _check_operands(tokens: Sequence[Token], mode: str) -> list[FieldError]:
    """Return the refusals of the ranges and of the address banks in ``tokens``.

    A range must stay in one bank and run from low to high. Each address must be in a bank
    that the mode accepts. :data:`_OPERANDS` lists the banks of each mode: the registers it
    accepts anywhere, the bits it accepts only as the range of ``SUM ( a : b )``, and the
    registers it accepts as a bound of ``RAND ( a , b )``. An address in any other bank is
    refused with OBJ-1002. An X or Y range with an end in the option slot is refused too
    (:func:`_check_xy_range`).

    There is one refusal for each address refused outside a SUM, one for each SUM refused,
    and at most one for each range. An address refused when it was read (``DS0``) is not
    checked again. If an end of a range is refused for its bank, the range is still checked
    for its banks, its order and a median's size. It is not checked for ends in the option
    slot.

    CLICK checks a range's banks (OBJ-1015) and its order (OBJ-1014) before the bank of an
    address (OBJ-1002). For example, it refuses ``SUM ( DH2 : DH1 )`` in a decimal Math with
    OBJ-1014. So the refusals of a range's banks and order come first in the list. The bank
    refusals come next, and then the refusals of a median's size and of option-slot ends.
    """
    in_banks, bank_refused = _check_banks(tokens, mode)
    shapes, sizes = _check_ranges(tokens, bank_refused)
    return [*shapes, *in_banks, *sizes]


def _check_banks(tokens: Sequence[Token], mode: str) -> tuple[list[FieldError], set[int]]:
    """Return a refusal for each address in a bank that the mode does not accept, and the
    indexes of those addresses.

    An address outside a SUM gets a refusal of its own. A SUM gets one refusal, however many
    of its ends are refused. The returned set holds the index of every address refused for
    its bank, in a SUM or not. It leaves out a refused RAND bound.
    """
    operands = _OPERANDS[mode]
    texts = [t.text for t in tokens]
    found: list[FieldError] = []
    sum_at: dict[int, int] = {}  # the index of each end of a SUM range -> index of its SUM
    for i in range(len(texts) - 5):
        if texts[i : i + 2] == ["SUM", "("] and texts[i + 3] == ":" and texts[i + 5] == ")":
            sum_at.update({i + 2: i, i + 4: i})
    rand_bounds = {i + k for i in _rand_calls(tokens) for k in (2, 4)}
    sum_refused: set[int] = set()  # the SUMs refused for their bank, once each
    bank_refused: set[int] = set()  # the addresses refused for their bank, in a SUM or not
    for i, token in enumerate(tokens):
        parts = address_parts(token.text)
        if token.refused or parts is None:
            continue
        bank = parts[0]
        if i in rand_bounds:
            if bank in operands.in_rand:
                continue
            address = Op(token.text, quoted=False)
            said = says("{address} is refused", "{rule}", address=address, rule=operands.rand_rule)
            if bank in operands.anywhere:
                # The rest of the formula accepts this register, so the refusal tells you to
                # copy it into a register that a bound accepts.
                said = says(
                    "{address} is refused",
                    "{rule}: copy {address} into {into} register first",
                    address=address,
                    rule=operands.rand_rule,
                    into=_RAND_COPY_INTO[mode],
                )
            error = _error(said, Reason.BANK, "OBJ-1002", code=Code.RANDOM_BOUND_TYPE)
            found.append(_at(error, token.span))
            continue
        if bank in operands.anywhere or (i in sum_at and bank in operands.in_sum):
            continue
        bank_refused.add(i)
        if i not in sum_at:
            said = says(
                "{address} is refused",
                "{rule}",
                address=Op(token.text, quoted=False),
                rule=operands.rule,
            )
            error = _error(said, Reason.BANK, "OBJ-1002", code=Code.MATH_OPERAND_BANK)
            found.append(_at(error, token.span))
        elif (at := sum_at[i]) not in sum_refused:
            sum_refused.add(at)
            said = says(
                "SUM ( {low} : {high} ) is refused for {address}",
                "{rule}",
                low=_bare(tokens[at + 2]),
                high=_bare(tokens[at + 4]),
                address=Op(token.text, quoted=False),
                rule=operands.rule,
            )
            error = _error(said, Reason.BANK, "OBJ-1002", code=Code.SUM_BANK_UNAVAILABLE)
            # The refusal is about the whole range, so it spans a : b.
            found.append(_at(error, _between(tokens[at + 2], tokens[at + 4])))
    return found, bank_refused


def _check_ranges(
    tokens: Sequence[Token], bank_refused: set[int]
) -> tuple[list[FieldError], list[FieldError]]:
    """Return the refusals of each ``a : b`` range, in two lists.

    The first list holds the refusals of ranges for their banks and order. The second holds
    the refusals for a median's size and for ends in the option slot. A range in two banks
    (OBJ-1015) or from high to low (OBJ-1014) is not checked further. A median covers at
    most 1024 bytes (OBJ-1013). An X or Y range whose ends are not refused for their bank is
    checked for the option slot (:func:`_check_xy_range`).
    """
    texts = [t.text for t in tokens]
    shapes: list[FieldError] = []
    sizes: list[FieldError] = []
    for i in range(1, len(texts) - 1):
        if texts[i] != ":" or tokens[i - 1].refused or tokens[i + 1].refused:
            continue
        low, high = address_parts(texts[i - 1]), address_parts(texts[i + 1])
        if low is None or high is None:
            continue
        ends = {"low": _bare(tokens[i - 1]), "high": _bare(tokens[i + 1])}
        # Each refusal of a range spans the whole a : b.
        span = _between(tokens[i - 1], tokens[i + 1])
        if low[0] != high[0]:
            shapes.append(
                _error(
                    says("{low} : {high} spans two banks", "a range stays in one", **ends),
                    Reason.FORM,
                    "OBJ-1015",
                    code=Code.MATH_RANGE_MIXED_BANKS,
                    span=span,
                )
            )
            continue
        count = _range_position(*high) - _range_position(*low) + 1
        if count < 1:
            said = says("{low} : {high} runs high to low", "a range runs low : high", **ends)
            shapes.append(
                _error(said, Reason.FORM, "OBJ-1014", code=Code.MATH_RANGE_NOT_ASCENDING, span=span)
            )
            continue
        width = (bits_per_register(low[0]) or 0) // 8
        if texts[i - 3 : i - 1] == ["MDN", "("] and width and count * width > _MEDIAN_MAX_BYTES:
            sizes.append(
                _error(
                    says(
                        "MDN ( {low} : {high} ) covers {size} bytes",
                        "a median covers at most {most}",
                        size=count * width,
                        most=_MEDIAN_MAX_BYTES,
                        **ends,
                    ),
                    Reason.RANGE,
                    "OBJ-1013",
                    code=Code.MEDIAN_RANGE_TOO_LARGE,
                    span=span,
                )
            )
            continue
        # Only a SUM accepts a bit range. A bit range anywhere else is already refused for
        # its bank.
        if low[0] in XY_BANKS and i - 1 not in bank_refused:
            error = _check_xy_range(texts[i - 3], low[0], int(low[1]), int(high[1]))
            if error is not None:
                sizes.append(_at(error, span))
    return shapes, sizes


def _check_xy_range(function: str, bank: str, start: int, end: int) -> FieldError | None:
    """Return the refusal of an X or Y range with an end in the option slot (21-36), or None.

    On a CPU with no I/O modules, CLICK stores the wrong points for such a range
    (:func:`_xy_bound`). Three such ranges are accepted: a range from the CPU slot to 21, a
    range of one point, and a range of two points numbered one apart (X025 : X026).
    """
    first, last = _OPTION_SLOT
    if not (first <= start <= last or first <= end <= last):
        return None
    if end - start <= 1 or (start <= _CPU_SLOT[1] and end == first):
        return None
    first_shown, last_shown = Address(bank, first).display, Address(bank, last).display
    inside = [
        Op(Address(bank, n).display, quoted=False) for n in (start, end) if first <= n <= last
    ]
    values = {
        "function": function,
        "low": Op(Address(bank, start).display, quoted=False),
        "high": Op(Address(bank, end).display, quoted=False),
        "first": first_shown,
        "last": last_shown,
    }
    if len(inside) == 1:
        said = says(
            "{function} ( {low} : {high} ) is refused: {end} is in the option slot "
            "({first}-{last})",
            end=inside[0],
            **values,
        )
    else:
        said = says(
            "{function} ( {low} : {high} ) is refused: {low} and {high} are in the option "
            "slot ({first}-{last})",
            **values,
        )
    pair = f"{Address(bank, first + 4).display} : {Address(bank, first + 5).display}"
    return _error(
        said,
        Reason.RANGE,
        code=Code.SUM_OPTION_SLOT,
        then=(
            "In the option slot, write a range of one point or of two points next to each "
            f"other, such as {function} ( {pair} )."
        ),
    )


def _xy_points_between(low: int, high: int) -> list[int]:
    """Return the numbers of the X/Y points in :data:`XY_SLOTS` strictly between ``low``
    and ``high``."""
    return [n for first, last in XY_SLOTS for n in range(first, last + 1) if low < n < high]


def _xy_bound(number: int) -> int:
    """Return the number that an end of an X or Y range counts as when CLICK lists its points.

    An end counts as its own number, except an end in the option slot. That end counts as if
    the option slot came right after the CPU slot, so X021 counts as 17 and X036 as 32. For
    example, ``SUM ( X001 : X036 )`` lists the points numbered 2 to 31: X002..X016 and
    X021..X031. ``SUM ( X021 : X116 )`` lists X021 itself, because X021 counts as 17. The
    rule is fitted to a C2-03CPU with no I/O modules.
    """
    if _OPTION_SLOT[0] <= number <= _OPTION_SLOT[1]:
        return number - _OPTION_GAP
    return number


def range_interiors(texts: Sequence[str]) -> list[str]:
    """Return the addresses between the ends of each ``A : B`` range, one range after another.

    ``texts`` are the display tokens of a formula. CLICK stores these addresses in the
    reserved slots (tag ``0x688C``), and stores the ends of each range as ordinary operands.
    For example, ``SUM ( DS201 : DS300 )`` stores DS202..DS299 in the reserved slots. An X
    or Y range lists the points of :data:`XY_SLOTS` whose numbers lie between the bounds of
    its ends (:func:`_xy_bound`).
    """
    interiors: list[str] = []
    for i in range(1, len(texts) - 1):
        if texts[i] != ":":
            continue
        low, high = address_parts(texts[i - 1]), address_parts(texts[i + 1])
        if low is None or high is None or low[0] != high[0]:
            continue
        bank, start, end = low[0], low[1], high[1]
        if bank in WORD_IO_BANKS:
            if start in _XY_WORD_ORDER and end in _XY_WORD_ORDER:
                inside = _XY_WORD_ORDER[_XY_WORD_ORDER.index(start) + 1 : _XY_WORD_ORDER.index(end)]
                interiors.extend(f"{bank}{n}" for n in inside)
            continue
        if bank in XY_BANKS:
            listed = _xy_points_between(_xy_bound(int(start)), _xy_bound(int(end)))
            interiors.extend(Address(bank, n).display for n in listed)
            continue
        interiors.extend(Address(bank, n).display for n in range(int(start) + 1, int(end)))
    return interiors


# ---------------------------------------------------------------------------
# The parse and its printers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Formula:
    """A parsed Math formula.

    Its properties and :meth:`internal` return the forms of the formula that a Math blob
    stores, and the addresses in it.
    """

    tokens: tuple[Token, ...]

    @property
    def display(self) -> str:
        """The formula as CLICK shows it (tag 0x6228), one space between tokens."""
        return " ".join(t.text for t in self.tokens)

    @property
    def written(self) -> str:
        """The formula as a Math holds it and its CSV writes it.

        It is the display formula, with each real in a form that CLICK keeps as typed
        (:attr:`MathReal.held`). Parsed again, it gives the same formula.
        """
        return " ".join(t.written for t in self.tokens)

    @property
    def template(self) -> str:
        """The display formula with ``@`` for each address (tag 0x61FF)."""
        return " ".join("@" if t.kind == "addr" else t.text for t in self.tokens)

    @property
    def nickname_display(self) -> str:
        """The display formula as nickname view shows it when no address has a nickname.

        Each address is written ``<?ADDR>``."""
        return " ".join(f"<?{t.text}>" if t.kind == "addr" else t.text for t in self.tokens)

    @property
    def operands(self) -> list[str]:
        """Each address in the formula, in order and with duplicates. Each fills one operand
        slot."""
        return [t.text for t in self.tokens if t.kind == "addr"]

    @property
    def range_interiors(self) -> list[str]:
        return range_interiors([t.text for t in self.tokens])

    def internal(self, *, template: bool = False) -> str:
        """Return the internal formula (tag 0x61FD), or the internal template (tag 0x6229) if
        ``template`` is True.

        Each token is written in its internal form (``200`` is ``H200``, ``Ah`` is
        ``UH10``), and the tokens are joined with ``#``. ``F ( a , b )`` is written
        ``a#F#b``, followed by an empty slot that stands for its ``( , )``. An empty slot
        writes nothing. A ``#`` follows each token, unless the token is in the last slot.
        So if a formula ends with such a call, the empty slot is last, and the result ends
        with ``#``: ``RAND ( 1 , 100 )`` is ``H1#RAND#H100#``.
        """

        def form(token: Token) -> str:
            if token.kind == "addr":
                return "@" if template else token.text
            return token.internal or token.text

        parts: list[str] = []
        i = 0
        tokens = self.tokens
        while i < len(tokens):
            token = tokens[i]
            if token.kind == "func" and token.text in COMMA_FUNCTIONS:
                parts += [form(tokens[i + 2]), token.text, form(tokens[i + 4]), ""]
                i += 6
                continue
            parts.append(form(token))
            i += 1
        out = ""
        for k, part in enumerate(parts):
            if part:
                out += part if k == len(parts) - 1 else f"{part}#"
        return out


def stored_reals_written(expression: str) -> str:
    """Return a decimal formula that CLICK stored, with each real in a form that CLICK keeps
    as typed.

    Each real is replaced by the text that :func:`held_for` returns for it. CLICK saves
    ``1.2345E-04`` as ``0.00012345``, a text that it cuts to ``0.000123`` when you type it
    so, and this function writes ``1.2345E-04``. A real that CLICK cuts however you type
    it, a real out of range, and every other word stay as stored.
    """
    words = expression.split(" ")
    for k, word in enumerate(words):
        constant = classify(word)
        if constant is None or constant.kind is not Kind.FLOAT:
            continue
        if MathReal(word).in_range:
            words[k] = held_for(word)
    return " ".join(words)


def parse(text: str, mode: str) -> Formula:
    """Parse a Math formula as CLICK's Math dialog reads it, and return the :class:`Formula`.

    ``mode`` is ``"decimal"`` or ``"hex"``. If the dialog would refuse the formula, raise
    :class:`FieldError`. The error is the first refusal found, and its
    :attr:`~FieldError.errors` holds every refusal found. The module docstring says which
    refusals stop the parse.
    """
    raws = _lex(text)
    if not raws:
        # A Math blob with no formula decodes as raw(), so laddercodec never encodes a Math
        # with no formula.
        raise _error(
            says("is blank", "a Math needs a formula"), Reason.MISSING, code=Code.BLANK_FIELD
        )
    for raw in raws:
        if raw.symbol and raw.text in ("[", "]"):
            # Refuse a pointer such as DS[DS1] here, before its bank name is refused as a
            # word.
            raise _error(
                says("{key!r} is part of a pointer", "Math takes no pointer", key=raw.text),
                Reason.POINTER,
                code=Code.POINTER_OUTSIDE_COPY,
                then=f"Write an address, such as {_example('DS1', mode)}.",
                span=raw.span,
            )
    found: list[FieldError] = []
    tokens: list[Token] = []
    known = True  # every word looks like a token
    for i, raw in enumerate(raws):
        token = _classify(raws, i, mode, found)
        if token is None:
            known = False
            token = Token("word", raw.text, refused=True)
        tokens.append(replace(token, span=raw.span))
    shown = " ".join(t.text for t in tokens)
    if (error := _check_parentheses(tokens, shown, mode)) is not None:
        _raise([*found, error])
    if mode == "decimal":
        tokens = _merge_signs(tokens)
        for k, t in enumerate(tokens):
            if t.kind != "const" or t.refused:
                continue
            internal = _decimal_internal(t.text)
            if isinstance(internal, FieldError):
                found.append(_at(internal, t.span))
                tokens[k] = Token("const", t.text, refused=True, span=t.span)
            elif isinstance(internal, MathReal):
                tokens[k] = Token.of_real(internal, t.span)
            else:
                tokens[k] = Token("const", t.text, internal, span=t.span)
        shown = " ".join(t.text for t in tokens)
    found += _check_mode(tokens, mode, shown)
    if not known:
        _raise(found)
    if (error := _check_order(tokens, mode)) is not None:
        _raise([*found, error])
    found += _check_rand(tokens, mode)
    found += _check_operands(tokens, mode)
    formula = Formula(tuple(tokens))
    # The length limit applies to CLICK's internal template, which the blob stores in tag
    # 0x6229. A template of 270 characters holds at most 68 operands, so the 500 operand
    # slots never overflow. A refused constant, or a word that looks like no token, has no
    # internal form to count. A refused address still counts as an @, and a refused name as
    # its own text.
    uncounted = any(t.refused and t.kind in ("const", "word") for t in tokens)
    if not uncounted and (length := len(formula.internal(template=True))) > MAX_INTERNAL_LENGTH:
        found.append(
            _error(
                says(
                    "the formula is {length} characters in CLICK's internal form",
                    "CLICK allows {most}",
                    length=length,
                    most=MAX_INTERNAL_LENGTH,
                ),
                Reason.RANGE,
                "OBJ-1008",
                code=Code.MATH_FORMULA_TOO_LONG,
                then="Shorten the formula.",
            )
        )
    if found:
        _raise(found)
    return formula
